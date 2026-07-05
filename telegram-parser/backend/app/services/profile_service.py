"""Profile editor + personal-channel management.

This module wraps the Pyrogram client to apply profile changes
(name, bio, username, avatar) and to manage the account's
personal broadcast channel. Every mutation is mirrored into the
``accounts`` row so the UI shows the same data without making an
extra round-trip to Telegram.

Hard rule: every public function calls :func:`assert_proxy_bound`
*first* so a profile change cannot accidentally route through the
operator's own IP. If the proxy goes down while the request is
in flight, the Pyrogram client raises and the function propagates
the error — the DB write is skipped so the cached profile stays
consistent with the server.
"""
from __future__ import annotations

import logging
import os
import random
import re
import uuid
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Optional

from pyrogram import Client, errors, raw, utils as pyrogram_utils
from pyrogram.raw.core import TLObject
from pyrogram.raw.core.primitives import Int
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account, AccountStatus
from app.services.account_service import assert_proxy_bound
from app.services.account_service import detect_gender
from app.services.telegram_service import telegram_service

logger = logging.getLogger(__name__)


class UpdatePersonalChannel(TLObject):  # type: ignore[misc]
    """Raw account.updatePersonalChannel missing from Pyrogram 2.0.106."""

    __slots__ = ["channel"]
    ID = 0xD94305E0
    QUALNAME = "functions.account.UpdatePersonalChannel"

    def __init__(self, *, channel: "raw.base.InputChannel") -> None:
        self.channel = channel

    @staticmethod
    def read(b: BytesIO, *args: Any) -> "UpdatePersonalChannel":
        return UpdatePersonalChannel(channel=TLObject.read(b))

    def write(self, *args) -> bytes:
        b = BytesIO()
        b.write(Int(self.ID, False))
        b.write(self.channel.write())
        return b.getvalue()


# Where avatar blobs are stored on disk. Created at import time so
# the read path doesn't have to.
BACKEND_ROOT = Path(__file__).resolve().parents[2]
AVATAR_DIR = BACKEND_ROOT / "var" / "avatars"
AVATAR_DIR.mkdir(parents=True, exist_ok=True)
CHANNEL_USERNAME_WORDS = [
    "studio",
    "notes",
    "life",
    "daily",
    "work",
    "space",
    "profile",
    "journal",
]


async def _client(account: Account) -> Client:
    """Get a connected Pyrogram client for ``account`` via the
    shared pool (proxy + session_string are honored automatically)."""
    return await telegram_service.get_client(account)


async def _ensure_known_chat(client: Client, chat_id: int) -> None:
    """Warm Pyrogram's peer cache for a channel/chat id.

    After a fresh reconnect Pyrogram may forget a previously created
    channel peer and raise ``PEER_ID_INVALID`` for perfectly valid
    channel ids until that peer appears again in dialogs.
    """
    try:
        await client.get_chat(chat_id)
        return
    except Exception:
        pass

    async for dialog in client.get_dialogs(limit=300):
        if getattr(dialog.chat, "id", None) == chat_id:
            break


def _username_slug(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9_]+", "_", value).strip("_")
    if not value or not value[0].isalpha():
        value = f"channel_{value}"
    return value[:20].strip("_") or "channel"


def _channel_username_candidates(account: Account, title: str) -> list[str]:
    base = _username_slug(account.username or title or account.phone_number)
    prefix = random.choice(["tg", "life", "daily", "note", "profile"])
    word = random.choice(CHANNEL_USERNAME_WORDS)
    candidates = []
    for _ in range(12):
        left = random.randint(24, 99)
        right = random.randint(100, 9999)
        raw_name = random.choice(
            [
                f"{base}_{word}_{right}",
                f"{prefix}_{base}_{right}",
                f"{base}{left}_{right}",
                f"{prefix}{left}_{word}_{right}",
            ]
        )
        username = re.sub(r"[^A-Za-z0-9_]", "", raw_name)[:32].strip("_")
        if len(username) >= 5 and username[0].isalpha():
            candidates.append(username)
    return candidates


async def _ensure_channel_username(
    client: Client,
    account: Account,
    channel_id: int,
    title: str,
    preferred: Optional[str] = None,
) -> Optional[str]:
    """Make the personal channel public by assigning a t.me username."""
    await _ensure_known_chat(client, channel_id)
    chat = await client.get_chat(channel_id)
    current = getattr(chat, "username", None)
    if current:
        return current

    candidates = []
    if preferred:
        candidates.append(preferred.strip().lstrip("@"))
    candidates.extend(_channel_username_candidates(account, title))

    for candidate in candidates:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{4,31}", candidate or ""):
            continue
        try:
            await client.set_chat_username(channel_id, candidate)
            return candidate
        except (errors.UsernameOccupied, errors.UsernameInvalid):
            continue
    raise ValueError("Не удалось подобрать свободный username для личного канала")


async def _set_as_personal_channel(client: Client, channel_id: int) -> None:
    await _ensure_known_chat(client, channel_id)
    channel = await client.resolve_peer(channel_id)
    await client.invoke(UpdatePersonalChannel(channel=channel))


async def refresh_profile(db: AsyncSession, account: Account) -> Account:
    """Read the current ``users.getFullUser`` from Telegram and
    update the cached fields on the ``Account`` row."""
    assert_proxy_bound(account)
    client = await _client(account)
    try:
        me = await client.get_me()
        full = await client.get_users(me.id)
        account.first_name = getattr(full, "first_name", None) or None
        account.last_name = getattr(full, "last_name", None) or None
        account.username = getattr(full, "username", None) or None
        # ``bio`` lives on the full chat info, NOT on the User returned by
        # ``get_users`` (that always yields None and would wipe our cached
        # bio). Read it from ``get_chat("me")`` instead.
        try:
            _self_chat = await client.get_chat("me")
            account.bio = getattr(_self_chat, "bio", None) or None
        except Exception:  # noqa: BLE001
            pass
        account.sex = detect_gender(account.first_name)
        # Personal channel id (Telegram exposes this only on ``users.full``).
        personal = getattr(full, "personal_channel_id", None)
        account.personal_channel_id = int(personal) if personal else None
        # Avatar: download the highest-resolution profile photo.
        # ``get_chat_photos`` does not accept the ``"me"`` alias — it needs
        # a real chat_id (or username). For the user's own profile photos
        # the canonical entry point is ``users.getUserPhotos`` (mapped to
        # ``get_users(me.id).profile_photos`` in Pyrogram). Falling back
        # to ``get_chat_photos(me.id)`` works on userbots but is the
        # documented public path.
        try:
            photos = [p async for p in client.get_chat_photos(me.id, limit=1)]
        except Exception as exc:  # noqa: BLE001 — we never want avatar download to fail the whole refresh
            logger.warning("avatar download failed for %s: %s", account.id, exc)
            photos = []
        if photos:
            target = AVATAR_DIR / f"{account.id}.jpg"
            tmp_target = AVATAR_DIR / f"{account.id}_{uuid.uuid4().hex}.jpg"
            await client.download_media(photos[0], file_name=str(tmp_target))
            try:
                os.replace(tmp_target, target)
            except PermissionError:
                logger.warning("avatar cache file is locked for %s: %s", account.id, target)
            else:
                account.avatar_path = str(target)
        account.last_check_at = datetime.utcnow()
        await db.commit()
        await db.refresh(account)
        return account
    finally:
        # Don't disconnect — the client belongs to the pool.
        pass


async def update_profile(
    db: AsyncSession,
    account: Account,
    *,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    bio: Optional[str] = None,
    username: Optional[str] = None,
) -> Account:
    """Push a profile change to Telegram and mirror it into the DB.

    * Only the fields the caller passed are touched. An empty string
      in ``last_name`` clears the last name (Telegram's behaviour).
    * ``username`` validation happens in the Pydantic schema; the
      schema also enforces a 5-32 char alnum rule.
    * Errors from Telegram (USERNAME_OCCUPIED, USERNAME_INVALID,
      etc.) are propagated so the API layer can return them as 400s.
    """
    assert_proxy_bound(account)
    client = await _client(account)
    # ``update_profile`` takes first_name, last_name, about (= bio).
    # Pyrogram accepts ``last_name=""`` to clear it.
    await client.update_profile(
        first_name=first_name if first_name is not None else account.first_name,
        last_name=last_name if last_name is not None else (account.last_name or ""),
        bio=bio if bio is not None else (account.bio or ""),
    )
    # ``set_username`` is separate; it raises ``UsernameOccupied`` etc.
    if username is not None and username != account.username:
        try:
            await client.set_username(username)
        except errors.UsernameOccupied:
            raise
        except errors.FloodWait as e:
            logger.warning("FloodWait on set_username for %s: %ss", account.id, e.value)
            raise
    # Re-read so the DB row has the canonical values.
    return await refresh_profile(db, account)


async def check_username_available(db: AsyncSession, account: Account, username: str) -> dict:
    """Ask Telegram whether ``username`` is currently available."""
    assert_proxy_bound(account)
    username = (username or "").strip().lstrip("@")
    if not username:
        raise ValueError("username is empty")
    client = await _client(account)
    try:
        from pyrogram.raw.functions.account import CheckUsername
        available = await client.invoke(CheckUsername(username=username))
        return {"username": username, "available": bool(available)}
    except errors.UsernameOccupied:
        return {"username": username, "available": False, "reason": "occupied"}
    except errors.UsernameInvalid:
        return {"username": username, "available": False, "reason": "invalid"}


async def upload_avatar(
    db: AsyncSession, account: Account, file_bytes: bytes, suffix: str = ".jpg"
) -> Account:
    """Upload ``file_bytes`` as a new profile photo for the account.

    Telegram limits the photo to 10 MB and 1280x1280 px. We don't
    resize here — the operator is expected to upload a square
    image that already meets the spec.
    """
    assert_proxy_bound(account)
    if len(file_bytes) > 10 * 1024 * 1024:
        raise ValueError("avatar larger than 10 MB; Telegram will reject it")
    client = await _client(account)
    tmp_path = AVATAR_DIR / f"{account.id}_upload_{uuid.uuid4().hex}{suffix}"
    tmp_path.write_bytes(file_bytes)
    try:
        # ``Client.save_file()`` reads ``client.me.is_premium`` to decide
        # the upload size limit. In long-lived pooled userbot sessions
        # ``client.me`` can still be empty, so we warm it explicitly first.
        if getattr(client, "me", None) is None:
            client.me = await client.get_me()
        uploaded = await client.save_file(str(tmp_path))
        await client.invoke(
            raw.functions.photos.UploadProfilePhoto(
                file=uploaded,
            )
        )
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        except PermissionError:
            logger.warning("temporary avatar file is still locked for %s: %s", account.id, tmp_path)
    return await refresh_profile(db, account)


async def create_personal_channel(
    db: AsyncSession,
    account: Account,
    *,
    title: str,
    about: Optional[str] = None,
    username: Optional[str] = None,
    set_as_personal: bool = True,
) -> dict:
    """Create a broadcast channel owned by ``account`` and (optionally)
    set it as the account's personal channel.

    Returns a dict ``{channel_id, channel_username, title}``.
    """
    assert_proxy_bound(account)

    # NB: we deliberately do NOT pre-block "young" accounts here. The age
    # heuristic was wrong for many accounts — Telegram often lets a fresh
    # account create a public channel just fine. So we ATTEMPT the create
    # and let Telegram be the judge: if it really refuses (it signals this
    # via USERNAME_PURCHASE_AVAILABLE / CHANNELS_ADMIN_PUBLIC_TOO_MUCH /
    # FRESH_CHANGE… — see _pyrogram_to_http in api/endpoints/profile.py),
    # the error bubbles up and is translated into the "account too young"
    # message. The rollback block below guarantees we never leave an
    # orphan channel behind when that happens.
    client = await _client(account)
    updates = await client.invoke(
        raw.functions.channels.CreateChannel(
            title=title,
            about=about or "",
            broadcast=True,
        )
    )
    raw_channel = next(
        (
            item for item in getattr(updates, "chats", [])
            if isinstance(item, raw.types.Channel)
        ),
        None,
    )
    if raw_channel is None:
        raise RuntimeError("Telegram не вернул данные созданного канала")
    peer_id = pyrogram_utils.get_peer_id(raw.types.PeerChannel(channel_id=raw_channel.id))
    channel_username = getattr(raw_channel, "username", None)

    # Everything after CreateChannel is rolled back on failure so that a
    # young account Telegram refuses NEVER leaves a half-created channel
    # behind — that orphan was the source of the duplicate posts the
    # operator saw on later applies.
    try:
        channel_username = await _ensure_channel_username(
            client,
            account,
            peer_id,
            title,
            preferred=username,
        )
        if set_as_personal:
            try:
                await _set_as_personal_channel(client, peer_id)
            except Exception as exc:
                # Binding as the profile's personal channel can fail
                # independently (and Pyrogram 2.0.106 can't verify it).
                # The channel itself is fine, so this is warn-only.
                logger.warning("set_as_personal failed for %s: %s", account.id, exc)
        # Re-read the account so Telegram-originated fields stay fresh.
        await refresh_profile(db, account)
    except Exception:
        # Hard rollback: delete the channel and clear any binding so the
        # account is left exactly as it was before the failed attempt.
        try:
            await client.delete_channel(peer_id)
        except Exception:  # noqa: BLE001
            logger.warning("rollback delete_channel failed for account %s", account.id)
        if account.personal_channel_id == int(peer_id):
            account.personal_channel_id = None
            account.personal_channel_username = None
            await db.commit()
        raise

    if not account.personal_channel_id:
        account.personal_channel_id = int(peer_id)
        account.personal_channel_username = channel_username
        await db.commit()
        await db.refresh(account)
    elif channel_username and not account.personal_channel_username:
        account.personal_channel_username = channel_username
        await db.commit()
        await db.refresh(account)

    try:
        chat = await client.get_chat(peer_id)
        chat_title = chat.title
        channel_username = channel_username or getattr(chat, "username", None)
    except Exception:
        chat_title = title

    return {
        "channel_id": peer_id,
        "channel_username": channel_username,
        "title": chat_title,
    }


async def ensure_personal_channel(
    db: AsyncSession,
    account: Account,
    *,
    title: str,
    about: Optional[str] = None,
) -> dict:
    """Ensure that ``account`` has a personal channel bound.

    If the account already has a personal channel, we reuse it. If not,
    we create a new one and bind it as the personal channel.
    """
    assert_proxy_bound(account)
    if account.personal_channel_id:
        client = await _client(account)
        channel_username = account.personal_channel_username
        if not channel_username:
            channel_username = await _ensure_channel_username(
                client,
                account,
                account.personal_channel_id,
                title,
            )
            account.personal_channel_username = channel_username
            await db.commit()
            await db.refresh(account)
        try:
            await _set_as_personal_channel(client, account.personal_channel_id)
        except Exception as exc:
            logger.warning("set_as_personal failed for existing channel %s: %s", account.id, exc)
        return {
            "channel_id": account.personal_channel_id,
            "channel_username": channel_username,
            "title": title,
            "created": False,
        }

    created = await create_personal_channel(
        db,
        account,
        title=title,
        about=about,
        username=None,
        set_as_personal=True,
    )
    return {
        **created,
        "created": True,
    }


async def set_personal_channel_avatar(
    db: AsyncSession,
    account: Account,
    *,
    image_path: Optional[str] = None,
    use_profile_avatar: bool = False,
) -> dict:
    """Set the account's personal channel photo.

    ``use_profile_avatar`` reuses the cached account avatar; if the cache is
    empty we refresh the profile first. The actual Telegram call still goes
    through the account's configured proxy because the shared client is used.
    """
    assert_proxy_bound(account)
    if not account.personal_channel_id:
        raise ValueError("account has no personal channel set; create one first")

    source_path = image_path
    if use_profile_avatar:
        if not account.avatar_path or not Path(account.avatar_path).exists():
            await refresh_profile(db, account)
        source_path = account.avatar_path

    if not source_path or not Path(source_path).exists():
        raise ValueError("channel avatar image is missing")

    client = await _client(account)
    await _ensure_known_chat(client, account.personal_channel_id)
    if getattr(client, "me", None) is None:
        client.me = await client.get_me()
    await client.set_chat_photo(account.personal_channel_id, photo=str(source_path))

    # Telegram posts a service message "Channel photo updated" after set_chat_photo.
    # Delete it so the channel feed stays clean.
    import asyncio as _asyncio
    await _asyncio.sleep(1)
    try:
        async for msg in client.get_chat_history(account.personal_channel_id, limit=3):
            if getattr(msg, "service", None) is not None:
                await client.delete_messages(account.personal_channel_id, msg.id)
                break
    except Exception:  # noqa: BLE001
        pass

    return {"status": "ok", "channel_id": account.personal_channel_id}


async def post_to_personal_channel(
    db: AsyncSession, account: Account, text: str
) -> dict:
    """Send a single text post to the account's personal channel."""
    assert_proxy_bound(account)
    if not account.personal_channel_id:
        raise ValueError("account has no personal channel set; create one first")
    client = await _client(account)
    await _ensure_known_chat(client, account.personal_channel_id)
    msg = await client.send_message(account.personal_channel_id, text)
    return {"message_id": msg.id}


async def post_media_to_personal_channel(
    db: AsyncSession,
    account: Account,
    *,
    text: str,
    image_bytes: Optional[bytes] = None,
    suffix: str = ".jpg",
) -> dict:
    """Send one post to the account's personal channel, optionally with an image."""
    assert_proxy_bound(account)
    if not account.personal_channel_id:
        raise ValueError("account has no personal channel set; create one first")
    client = await _client(account)
    if not image_bytes:
        return await post_to_personal_channel(db, account, text)

    if len(image_bytes) > 10 * 1024 * 1024:
        raise ValueError("post image larger than 10 MB")
    await _ensure_known_chat(client, account.personal_channel_id)
    if getattr(client, "me", None) is None:
        client.me = await client.get_me()
    tmp_path = AVATAR_DIR / f"{account.id}_channel_post_{datetime.utcnow().timestamp()}{suffix}"
    tmp_path.write_bytes(image_bytes)
    try:
        msg = await client.send_photo(account.personal_channel_id, photo=str(tmp_path), caption=text)
        return {"message_id": msg.id}
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        except PermissionError:
            logger.warning("temporary channel post file is still locked for %s: %s", account.id, tmp_path)


async def apply_personal_channel_template(
    db: AsyncSession,
    source_account: Account,
    target_accounts: list[Account],
    *,
    title: str,
    about: Optional[str] = None,
    posts: list[str] | None = None,
    create_if_missing: bool = True,
) -> dict:
    """Apply one personal-channel template to multiple target accounts.

    Each target must already have a proxy bound; accounts without a
    proxy are reported as skipped and never touched.
    """
    assert_proxy_bound(source_account)
    results: list[dict] = []
    posts = posts or []

    for account in target_accounts:
        row = {
            "account_id": account.id,
            "phone_number": account.phone_number,
            "status": "skipped",
            "created_channel": False,
            "posted": 0,
            "reason": None,
        }
        try:
            assert_proxy_bound(account)
            if not account.personal_channel_id and not create_if_missing:
                row["reason"] = "personal channel is missing"
                results.append(row)
                continue

            ensured = await ensure_personal_channel(
                db,
                account,
                title=title,
                about=about,
            )
            row["created_channel"] = bool(ensured.get("created"))

            # Publish in REVERSE so the first post in the list ends up as the
            # newest message — the one a visitor sees first on entering the
            # channel. (Telegram puts the newest message at the bottom, which
            # is where the channel view opens.)
            for post in reversed(posts):
                await post_to_personal_channel(db, account, post)
                row["posted"] += 1

            row["status"] = "ok"
        except Exception as exc:  # noqa: BLE001 - batch endpoint needs per-account reporting
            logger.warning("personal-channel template failed for %s: %s", account.id, exc)
            row["status"] = "error"
            row["reason"] = str(exc)
        results.append(row)

    return {
        "applied": sum(1 for item in results if item["status"] == "ok"),
        "results": results,
    }


async def clear_personal_channel(db: AsyncSession, account: Account) -> int:
    """Delete every message in the account's personal channel.

    Used to make template application IDEMPOTENT: instead of appending
    the posts again (which produced 2x/10x duplicates), we wipe the
    channel and re-post exactly the template content. Returns the number
    of messages deleted.
    """
    assert_proxy_bound(account)
    if not account.personal_channel_id:
        return 0
    client = await _client(account)
    await _ensure_known_chat(client, account.personal_channel_id)
    ids: list[int] = []
    async for msg in client.get_chat_history(account.personal_channel_id, limit=1000):
        ids.append(msg.id)
    deleted = 0
    for i in range(0, len(ids), 100):
        chunk = ids[i : i + 100]
        try:
            await client.delete_messages(account.personal_channel_id, chunk)
            deleted += len(chunk)
        except Exception as exc:  # noqa: BLE001
            logger.warning("clear_personal_channel: delete failed for %s: %s", account.id, exc)
    return deleted


async def set_channel_link_in_bio(db: AsyncSession, account: Account) -> bool:
    """Put a clickable link to the personal channel into the account's bio.

    This is the practical "channel link in the profile" — anyone viewing
    the account can tap through to the channel. (The native Telegram
    "personal channel" block needs a newer Pyrogram; the bio link works on
    every version and is visible to everyone.)
    """
    if not account.personal_channel_username:
        return False
    assert_proxy_bound(account)
    client = await _client(account)
    bio = f"Мой канал: @{account.personal_channel_username}"[:70]
    try:
        await client.update_profile(bio=bio)
    except Exception as exc:  # noqa: BLE001
        logger.warning("set channel link in bio failed for %s: %s", account.id, exc)
        return False
    account.bio = bio
    await db.commit()
    return True


async def rebuild_personal_channel_from_template(
    db: AsyncSession,
    account: Account,
    template,
    *,
    avatar: str = "profile",
) -> dict:
    """Idempotently make the channel match the template exactly.

    Wipes the channel, sets the avatar, then publishes the template's
    posts in REVERSE position order (position 1 is published last so it
    becomes the newest message — the first one a visitor sees on entry).

    ``avatar``: ``"profile"`` (account's own avatar), ``"template"``
    (template image) or ``"none"``.
    """
    assert_proxy_bound(account)
    ensured = await ensure_personal_channel(
        db, account, title=template.channel_title, about=template.channel_about
    )
    cleared = await clear_personal_channel(db, account)

    avatar_set = False
    try:
        if avatar == "profile":
            await set_personal_channel_avatar(db, account, use_profile_avatar=True)
            avatar_set = True
        elif avatar == "template" and getattr(template, "channel_avatar_path", None):
            await set_personal_channel_avatar(
                db, account, image_path=template.channel_avatar_path
            )
            avatar_set = True
    except Exception as exc:  # noqa: BLE001
        logger.warning("rebuild: channel avatar failed for %s: %s", account.id, exc)

    # De-dupe by position, then publish DESCENDING so that position 1 is
    # published LAST → becomes the newest message → first visible on entry.
    # Position N (highest) is published first → oldest → bottom of history.
    unique = {p.position: p for p in template.posts}
    ordered = sorted(unique.values(), key=lambda p: p.position, reverse=True)
    posted = 0
    for post in ordered:
        image_bytes = Path(post.image_path).read_bytes() if post.image_path else None
        suffix = Path(post.image_path).suffix if post.image_path else ".jpg"
        await post_media_to_personal_channel(
            db, account, text=post.text or "", image_bytes=image_bytes, suffix=suffix
        )
        posted += 1

    # Make the channel reachable from the account's profile via a bio link.
    bio_link_set = await set_channel_link_in_bio(db, account)

    return {
        "channel_id": account.personal_channel_id,
        "channel_username": account.personal_channel_username,
        "cleared": cleared,
        "posted": posted,
        "avatar_set": avatar_set,
        "bio_link_set": bio_link_set,
        "created": bool(ensured.get("created")),
    }


async def delete_personal_channel(db: AsyncSession, account: Account) -> None:
    """Delete the account's personal channel."""
    assert_proxy_bound(account)
    if not account.personal_channel_id:
        raise ValueError("account has no personal channel to delete")
    client = await _client(account)
    await _ensure_known_chat(client, account.personal_channel_id)
    await client.delete_channel(account.personal_channel_id)
    account.personal_channel_id = None
    account.personal_channel_username = None
    await db.commit()
