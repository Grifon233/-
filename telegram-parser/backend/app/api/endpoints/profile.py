"""Endpoints for the Telegram-account profile editor and personal channel."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from pyrogram import errors as pyrogram_errors
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.api.deps import get_project_id
from app.schemas.account import (
    Account,
    ChannelCreateRequest,
    ChannelPostRequest,
    PersonalChannelTemplateRequest,
    ProfileWriteRequest,
)
from app.services import account_service, profile_service
from app.services.profile_preset_service import build_random_profile_preset
from sqlalchemy.orm import selectinload

router = APIRouter()


class RandomProfilePresetRequest(BaseModel):
    gender: str
    locale: str = "ru"


class UsernameCheckRequest(BaseModel):
    username: str


# Pyrogram error classes that mean "this account cannot be used
# right now, do not retry automatically". We surface them as 401/403
# with a clear human message instead of the default 500.
def _pyrogram_to_http(exc: Exception) -> HTTPException:
    if isinstance(exc, pyrogram_errors.AuthKeyUnregistered):
        return HTTPException(
            status_code=401,
            detail="Telegram session is no longer valid. Re-login the account.",
        )
    if isinstance(exc, pyrogram_errors.UserDeactivated):
        return HTTPException(
            status_code=403,
            detail="Telegram account is deactivated.",
        )
    if isinstance(exc, pyrogram_errors.FloodWait):
        return HTTPException(
            status_code=429,
            detail=f"Telegram says: FloodWait {exc.value}s",
        )
    # Young / freshly-registered accounts can't yet create a public
    # channel or take a public username. Telegram signals this in several
    # ways (no single error code), so we match on the known markers and
    # return ONE clear, human message instead of a raw Telegram code.
    _msg = str(getattr(exc, "MESSAGE", "") or "") + " " + str(exc)
    # Account-level restriction: Telegram has limited/flagged THIS account
    # (commonly spam-blocked or a freshly imported one). CreateChannel and
    # other write actions are refused outright with USER_RESTRICTED. This is
    # a different, harder case than "too young for a public username", so we
    # give a distinct, actionable message instead of a raw Telegram code.
    if "USER_RESTRICTED" in _msg:
        return HTTPException(
            status_code=400,
            detail=(
                "Telegram ограничил этот аккаунт (USER_RESTRICTED) — он сейчас не "
                "может создавать каналы и публичный контент. Так Telegram помечает "
                "аккаунты, заподозренные в спаме (часто новые или импортированные). "
                "Что делать: напишите боту @SpamBot в Telegram с этого аккаунта и "
                "проверьте статус, дайте аккаунту прогреться (раздел «Прогрев») и "
                "повторите позже. Создание канала заработает, когда Telegram снимет "
                "ограничение."
            ),
        )
    _markers = (
        "USERNAME_PURCHASE_AVAILABLE",  # account too new to take a free @username
        "CHANNELS_ADMIN_PUBLIC_TOO_MUCH",
        "CHANNELS_TOO_MUCH",
        "FRESH_CHANGE",  # FRESH_CHANGE_PHONE/ADMINS_FORBIDDEN — too new
        "YOUNG",
        "PEER_FLOOD",
        "подобрать свободный username",  # raised by our own _ensure_channel_username
        "слишком молодой",  # legacy young-account guard message (kept for safety)
    )
    if any(m.lower() in _msg.lower() for m in _markers):
        return HTTPException(
            status_code=400,
            detail=(
                "Аккаунт пока слишком молодой, чтобы создать публичный личный "
                "канал (Telegram не выдаёт новым аккаунтам публичный @username). "
                "Дайте аккаунту прогреться несколько дней и попробуйте снова."
            ),
        )
    if isinstance(exc, pyrogram_errors.BadRequest):
        return HTTPException(
            status_code=400,
            detail=f"Telegram says: {exc.MESSAGE if hasattr(exc, 'MESSAGE') else str(exc)}",
        )
    return HTTPException(status_code=502, detail=f"Telegram: {exc}")


async def _get_account_or_404(
    db: AsyncSession, account_id: int, project_id: int
):
    account = await account_service.get_account(db, account_id, project_id=project_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


async def _get_account_with_proxy_or_404(
    db: AsyncSession, account_id: int, project_id: int
):
    """Variant that eagerly loads the ``proxy`` relationship so that
    :func:`telegram_service.get_client` can read ``account.proxy``
    synchronously (Pyrogram client construction needs scheme/host/port).

    Without ``selectinload`` SQLAlchemy would try to lazy-load the
    relationship inside an async context and raise the
    ``greenlet_spawn has not been called`` error.
    """
    from sqlalchemy import select
    from app.models.account import Account as AccountModel

    result = await db.execute(
        select(AccountModel)
        .where(AccountModel.id == account_id, AccountModel.project_id == project_id)
        .options(selectinload(AccountModel.proxy))
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


@router.post("/{account_id}/profile/refresh", response_model=Account)
async def refresh_profile(
    account_id: int,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    """Re-read the account profile from Telegram and update the cache."""
    account = await _get_account_with_proxy_or_404(db, account_id, project_id)
    try:
        return await profile_service.refresh_profile(db, account)
    except account_service.ProxyRequiredError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except pyrogram_errors.exceptions.unauthorized_401.AuthKeyUnregistered:
        raise HTTPException(
            status_code=401,
            detail="Telegram session is no longer valid. Re-login the account.",
        )
    except pyrogram_errors.UserDeactivated:
        raise HTTPException(status_code=403, detail="Telegram account is deactivated.")
    except pyrogram_errors.FloodWait as exc:
        raise HTTPException(status_code=429, detail=f"FloodWait {exc.value}s")
    except pyrogram_errors.BadRequest as exc:
        raise HTTPException(status_code=400, detail=f"Telegram: {exc.MESSAGE if hasattr(exc, 'MESSAGE') else str(exc)}")
    except Exception as exc:
        raise _pyrogram_to_http(exc)


@router.post("/{account_id}/profile", response_model=Account)
async def update_profile(
    account_id: int,
    payload: ProfileWriteRequest,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    account = await _get_account_with_proxy_or_404(db, account_id, project_id)
    try:
        return await profile_service.update_profile(
            db,
            account,
            first_name=payload.first_name,
            last_name=payload.last_name,
            bio=payload.bio,
            username=payload.username,
        )
    except account_service.ProxyRequiredError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except pyrogram_errors.exceptions.unauthorized_401.AuthKeyUnregistered:
        raise HTTPException(status_code=401, detail="Telegram session is no longer valid. Re-login the account.")
    except pyrogram_errors.UserDeactivated:
        raise HTTPException(status_code=403, detail="Telegram account is deactivated.")
    except pyrogram_errors.FloodWait as exc:
        raise HTTPException(status_code=429, detail=f"FloodWait {exc.value}s")
    except pyrogram_errors.BadRequest as exc:
        raise HTTPException(status_code=400, detail=f"Telegram: {exc.MESSAGE if hasattr(exc, 'MESSAGE') else str(exc)}")
    except Exception as exc:
        raise _pyrogram_to_http(exc)


@router.post("/{account_id}/profile/random-preset")
async def random_profile_preset(
    account_id: int,
    payload: RandomProfilePresetRequest,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    """Return a local random name/avatar preset for the profile editor."""
    await _get_account_or_404(db, account_id, project_id)
    gender = payload.gender if payload.gender in {"male", "female"} else None
    locale = payload.locale if payload.locale in {"ru", "en"} else None
    if gender is None:
        raise HTTPException(status_code=400, detail="Выберите мужской или женский пол")
    if locale is None:
        raise HTTPException(status_code=400, detail="Язык должен быть ru или en")
    try:
        return build_random_profile_preset(gender, locale)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{account_id}/profile/check-username")
async def check_username(
    account_id: int,
    payload: UsernameCheckRequest,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    account = await _get_account_with_proxy_or_404(db, account_id, project_id)
    try:
        return await profile_service.check_username_available(db, account, payload.username)
    except account_service.ProxyRequiredError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except pyrogram_errors.FloodWait as exc:
        raise HTTPException(status_code=429, detail=f"FloodWait {exc.value}s")
    except pyrogram_errors.BadRequest as exc:
        raise HTTPException(status_code=400, detail=f"Telegram: {exc.MESSAGE if hasattr(exc, 'MESSAGE') else str(exc)}")
    except Exception as exc:
        raise _pyrogram_to_http(exc)


@router.post("/{account_id}/profile/avatar", response_model=Account)
async def upload_avatar(
    account_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    account = await _get_account_with_proxy_or_404(db, account_id, project_id)
    blob = await file.read()
    if not blob:
        raise HTTPException(status_code=400, detail="empty file")
    try:
        return await profile_service.upload_avatar(db, account, blob, suffix=".jpg")
    except account_service.ProxyRequiredError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{account_id}/personal-channel")
async def create_personal_channel(
    account_id: int,
    payload: ChannelCreateRequest,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    account = await _get_account_with_proxy_or_404(db, account_id, project_id)
    try:
        return await profile_service.create_personal_channel(
            db,
            account,
            title=payload.title,
            about=payload.about,
            username=payload.username,
            set_as_personal=payload.set_as_personal,
        )
    except account_service.ProxyRequiredError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        # Persist a restriction marker if Telegram limited the account, so the
        # Accounts list can show an "ограничен" badge (same flag as messaging).
        from app.api.endpoints.accounts import _restriction_reason, _set_account_restriction
        reason = _restriction_reason(exc)
        if reason:
            _set_account_restriction(account, reason)
            await db.commit()
        raise _pyrogram_to_http(exc)


@router.post("/{account_id}/personal-channel/post")
async def post_to_personal_channel(
    account_id: int,
    payload: ChannelPostRequest,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    account = await _get_account_with_proxy_or_404(db, account_id, project_id)
    try:
        return await profile_service.post_to_personal_channel(db, account, payload.text)
    except account_service.ProxyRequiredError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise _pyrogram_to_http(exc)


@router.post("/{account_id}/personal-channel/posts")
async def post_many_to_personal_channel(
    account_id: int,
    texts: list[str] = Form(...),
    images: list[UploadFile] = File(default=[]),
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    account = await _get_account_with_proxy_or_404(db, account_id, project_id)
    clean_texts = [item.strip() for item in texts if item and item.strip()]
    if not clean_texts:
        raise HTTPException(status_code=400, detail="At least one post text is required")
    if len(clean_texts) > 20:
        raise HTTPException(status_code=400, detail="At most 20 posts can be sent at once")

    image_payloads: list[tuple[bytes, str]] = []
    for image in images:
        blob = await image.read()
        if blob:
            suffix = ".png" if image.filename and image.filename.lower().endswith(".png") else ".jpg"
            image_payloads.append((blob, suffix))

    sent = []
    try:
        for index, text in enumerate(clean_texts):
            image = image_payloads[index] if index < len(image_payloads) else None
            sent.append(
                await profile_service.post_media_to_personal_channel(
                    db,
                    account,
                    text=text,
                    image_bytes=image[0] if image else None,
                    suffix=image[1] if image else ".jpg",
                )
            )
    except account_service.ProxyRequiredError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise _pyrogram_to_http(exc)
    return {"posted": len(sent), "messages": sent}


@router.delete("/{account_id}/personal-channel")
async def delete_personal_channel(
    account_id: int,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    account = await _get_account_with_proxy_or_404(db, account_id, project_id)
    try:
        await profile_service.delete_personal_channel(db, account)
    except account_service.ProxyRequiredError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise _pyrogram_to_http(exc)
    return {"status": "ok"}


@router.post("/{account_id}/personal-channel/apply-template")
async def apply_personal_channel_template(
    account_id: int,
    payload: PersonalChannelTemplateRequest,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    from sqlalchemy import select
    from app.models.account import Account as AccountModel

    source_account = await _get_account_with_proxy_or_404(db, account_id, project_id)
    result = await db.execute(
        select(AccountModel)
        .where(
            AccountModel.project_id == project_id,
            AccountModel.id.in_(payload.target_account_ids),
        )
        .options(selectinload(AccountModel.proxy))
    )
    targets = list(result.scalars().all())
    if not targets:
        raise HTTPException(status_code=404, detail="No target accounts found")
    try:
        return await profile_service.apply_personal_channel_template(
            db,
            source_account,
            targets,
            title=payload.title,
            about=payload.about,
            posts=payload.posts,
            create_if_missing=payload.create_if_missing,
        )
    except account_service.ProxyRequiredError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise _pyrogram_to_http(exc)
