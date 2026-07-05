"""Celery task that runs parsing operations and writes results to CSV.

Notes
-----
* Fieldnames are the union of keys across all rows. Picking the first
  row's keys (the previous behaviour) silently dropped any extra column
  added by later message types, which led to ``KeyError`` on the import
  endpoint. See MED-004 from the 2026-06-02 audit.
* The task distinguishes "no results" from "results are saved". When
  nothing is found we mark the task as COMPLETED but leave
  ``file_path`` empty so the UI doesn't try to download a non-existent
  file. See MED-007.
* ``FloodWait`` is handled per-keyword so a single bad keyword doesn't
  burn the whole task.
* ``COMMENTS`` parsing walks the most recent posts in a channel and
  pulls the discussion (comment) thread of each one. The collected
  rows are the *authors* of those comments — useful for finding
  active beauty/tattoo masters who reply under channel posts.
* ``CHAT_SEARCH`` uses Telegram's raw ``contacts.Search`` (the public
  search index) instead of being limited to the account's own dialog
  list. The old ``CHANNELS`` only looked at ``get_dialogs()`` which
  meant a fresh account could never discover anything new. For each
  match we optionally call ``GetFullChannel`` to learn whether the
  channel has an open linked discussion (i.e. comments enabled),
  which is the actual signal a marketing operator cares about.
"""
import asyncio
import csv
import logging
import os
import re
from datetime import datetime
from typing import Any

from pyrogram import errors
from pyrogram.raw import functions, types
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.celery_app import async_run, celery_app
from app.core.rate_limiter import (
    NewbornAccountError,
    RateLimitExceeded,
    rate_limiter,
)
from app.db.session import SessionLocal
from app.models.account import Account
from app.models.parsing import ParsingStatus, ParsingTask, ParsingType
from app.services.telegram_service import telegram_service
from app.services.tgstat_service import TGStatError, tgstat_service

logger = logging.getLogger(__name__)


def _expand_chat_search_queries(keyword: str, enabled: bool = True) -> list[str]:
    """Build several Telegram catalog queries from one broad keyword.

    ``contacts.Search`` returns only a small relevance window (often 8-10
    chats) regardless of a requested limit of 100 or 200. Query expansion is
    therefore required to discover more than Telegram's first result window.
    """
    base = " ".join(keyword.split())
    if not base:
        return []
    if not enabled:
        return [base]

    has_cyrillic = bool(re.search(r"[А-Яа-яЁё]", base))
    suffixes = (
        [
            "чат",
            "группа",
            "канал",
            "сообщество",
            "клуб",
            "форум",
            "мастера",
            "специалисты",
            "услуги",
            "обучение",
            "студия",
            "салон",
            "объявления",
            "работа",
            "отзывы",
            "россия",
            "москва",
            "спб",
            "онлайн",
        ]
        if has_cyrillic
        else [
            "chat",
            "group",
            "channel",
            "community",
            "club",
            "forum",
            "masters",
            "specialists",
            "services",
            "training",
            "studio",
            "salon",
            "ads",
            "jobs",
            "reviews",
            "online",
        ]
    )
    # Prefix variants are not equivalent to suffix variants in Telegram's
    # relevance ranking and often expose a different result window.
    prefixes = ["чат", "группа", "канал"] if has_cyrillic else ["chat", "group", "channel"]
    queries = [
        base,
        *(f"{base} {suffix}" for suffix in suffixes),
        *(f"{prefix} {base}" for prefix in prefixes),
    ]
    # Preserve order while removing duplicates such as a keyword already
    # ending in "чат".
    return list(dict.fromkeys(query.casefold() for query in queries))


@celery_app.task(name="app.tasks.parsing.run_parsing_task")
def run_parsing_task(task_id: int):
    """Run a parsing task asynchronously."""
    return async_run(_run, task_id)


async def _run(task_id: int) -> None:
    async with SessionLocal() as db:
        result = await db.execute(select(ParsingTask).where(ParsingTask.id == task_id))
        task = result.scalar_one_or_none()

        if not task:
            logger.error("Parsing task %s not found", task_id)
            return

        task.status = ParsingStatus.RUNNING
        await db.commit()

        if task.account_id:
            acc_result = await db.execute(
                select(Account)
                .options(selectinload(Account.proxy))
                .where(
                    Account.id == task.account_id,
                    Account.project_id == task.project_id,
                )
            )
        else:
            # Picking an account for parsing:
            #   1) Prefer ones already in ``production`` — they've
            #      been warmed up and are the cheapest to use.
            #   2) Otherwise fall back to any account that has a
            #      ``session_string`` (i.e. an authorised login)
            #      regardless of status. The original code required
            #      ``status == 'production'`` which made the parser
            #      unusable in dev / on fresh installs. See issue
            #      PARSE-2026-06.
            acc_result = await db.execute(
                select(Account)
                .options(selectinload(Account.proxy))
                .where(
                    Account.project_id == task.project_id,
                    Account.session_string.isnot(None),
                    Account.session_string != "",
                )
                .order_by(
                    # production first, then warming, then anything
                    # else. ``CASE`` is supported by both sqlite and
                    # postgres.
                    (Account.status == "production").desc(),
                    (Account.status == "warming").desc(),
                    Account.id.asc(),
                )
            )

        account = acc_result.scalars().first()
        # ``TGSTAT_SEARCH`` runs against the TGStat public REST
        # API (https://api.tgstat.ru) and doesn't need a
        # Telegram user-account at all. Skip the account check
        # for it so the operator can use the parser before
        # they've added any authorised accounts.
        if not account and task.type != ParsingType.TGSTAT_SEARCH:
            logger.error("No available account for parsing task %s", task_id)
            task.status = ParsingStatus.FAILED
            task.finished_at = datetime.utcnow()
            task.params = {
                **(task.params or {}),
                "last_error": (
                    "no_authorized_account: добавьте и авторизуйте "
                    "Telegram-аккаунт, чтобы парсер мог подключиться"
                ),
            }
            await db.commit()
            return

        if account is not None and not account.session_string:
            logger.error(
                "Account %s is not authorised (no session_string)", account.id
            )
            task.status = ParsingStatus.FAILED
            task.finished_at = datetime.utcnow()
            task.params = {
                **(task.params or {}),
                "last_error": "account_not_authorized: пройдите авторизацию аккаунта",
            }
            await db.commit()
            return

        try:
            client = (
                await telegram_service.get_client(account)
                if account is not None
                else None
            )
            params = task.params or {}
            results: list[dict[str, Any]] = []
            seen_user_ids: set[Any] = set()
            from app.core.safety_guidelines import effective_account_age_days
            account_age_days = effective_account_age_days(account)

            if task.type == ParsingType.USERS:
                # Channel/group member listings are expensive on
                # Telegram's side. We go through the shared rate
                # limiter so multiple parse jobs on the same account
                # don't all hammer ``get_chat_members`` at once.
                await rate_limiter.acquire(
                    "search_members",
                    account.id,
                    account_age_days=account_age_days,
                    min_delay=1.0,
                )
                async for member in client.get_chat_members(task.target):
                    user = getattr(member, "user", None)
                    if not user or getattr(user, "is_bot", False):
                        continue
                    results.append(
                        {
                            "telegram_id": user.id,
                            "username": user.username or "",
                            "first_name": user.first_name or "",
                            "last_name": user.last_name or "",
                            "phone": user.phone_number or "",
                        }
                    )
                    if len(results) >= (params.get("limit") or 1000):
                        break

            elif task.type == ParsingType.MESSAGES:
                keywords = [k.strip() for k in task.target.split(",") if k.strip()]
                for keyword in keywords:
                    if len(results) >= (params.get("limit") or 1000):
                        break
                    await rate_limiter.acquire(
                        "search_global",
                        account.id,
                        account_age_days=account_age_days,
                        min_delay=2.0,
                    )
                    try:
                        async for message in client.search_global(
                            keyword, limit=params.get("limit") or 100
                        ):
                            from_user = getattr(message, "from_user", None)
                            if from_user and not getattr(from_user, "is_bot", False):
                                results.append(
                                    {
                                        "telegram_id": from_user.id,
                                        "username": from_user.username or "",
                                        "first_name": from_user.first_name or "",
                                        "last_name": from_user.last_name or "",
                                        "phone": from_user.phone_number or "",
                                        "context": (message.text or "")[:100],
                                    }
                                )
                            if len(results) >= (params.get("limit") or 1000):
                                break
                    except errors.FloodWait as e:
                        logger.warning("FloodWait on keyword %r: %ss", keyword, e.value)
                        await asyncio.sleep(e.value + 1)
                    except Exception as e:
                        logger.warning("search_global failed for %r: %s", keyword, e)

            elif task.type == ParsingType.CHANNELS:
                keyword = task.target.strip().lower()
                # ``get_dialogs`` is heavy on the first call (the
                # client has to fetch the whole dialog list). The
                # shared limiter caps it at 8/day per account, so
                # this isn't a "poll every minute" foot-gun.
                await rate_limiter.acquire(
                    "get_dialogs",
                    account.id,
                    account_age_days=account_age_days,
                    min_delay=1.0,
                )
                async for dialog in client.get_dialogs():
                    chat = getattr(dialog, "chat", None)
                    chat_type = getattr(chat, "type", None)
                    # ``chat.type`` is a pyrogram ``ChatType`` enum, not a
                    # plain string — comparing it to "channel" directly is
                    # always False (only ``.value`` is the string).
                    chat_type_value = getattr(chat_type, "value", chat_type)
                    if not chat or chat_type_value != "channel":
                        continue
                    username = (chat.username or "").lower()
                    title = (chat.title or "").lower()
                    if keyword and keyword not in username and keyword not in title:
                        continue
                    results.append(
                        {
                            "telegram_id": chat.id,
                            "username": chat.username or "",
                            "title": chat.title or "",
                            "members_count": getattr(chat, "members_count", 0) or 0,
                            "description": "",
                        }
                    )
                    if len(results) >= (params.get("limit") or 100):
                        break

            elif task.type == ParsingType.COMMENTS:
                # ``target`` is a channel (@username or t.me/...).
                # Walk the N most recent posts (default 20) and pull
                # the discussion thread of each one. Collect unique
                # authors — they're the *actual* beauty/tattoo
                # masters active in that channel's community.
                target = task.target
                post_limit = int(params.get("post_limit") or 20)
                per_post_limit = int(params.get("per_post_limit") or 200)
                total_limit = int(params.get("limit") or 5000)

                # Rate-limit is per account, not per post.
                await rate_limiter.acquire(
                    "search_global",
                    account.id,
                    account_age_days=account_age_days,
                    min_delay=1.0,
                )
                # Fetch recent post IDs from the channel history.
                post_ids: list[int] = []
                async for post in client.get_chat_history(
                    target, limit=post_limit
                ):
                    if getattr(post, "replies", None) is None and not getattr(
                        post, "is_topic_message", False
                    ):
                        # No discussion thread attached to this post.
                        continue
                    post_ids.append(post.id)
                    if len(post_ids) >= post_limit:
                        break

                for post_id in post_ids:
                    if len(results) >= total_limit:
                        break
                    try:
                        async for reply in client.get_discussion_replies(
                            target, post_id, limit=per_post_limit
                        ):
                            author = getattr(reply, "from_user", None)
                            if not author or getattr(author, "is_bot", False):
                                continue
                            if author.id in seen_user_ids:
                                continue
                            seen_user_ids.add(author.id)
                            results.append(
                                {
                                    "telegram_id": author.id,
                                    "username": author.username or "",
                                    "first_name": author.first_name or "",
                                    "last_name": author.last_name or "",
                                    "phone": author.phone_number or "",
                                    "post_id": post_id,
                                    "comment": (reply.text or "")[:200],
                                }
                            )
                            if len(results) >= total_limit:
                                break
                    except errors.FloodWait as e:
                        logger.warning(
                            "FloodWait on discussion %s/%s: %ss",
                            target, post_id, e.value,
                        )
                        await asyncio.sleep(e.value + 1)
                    except Exception as e:  # noqa: BLE001
                        # Not every post has a discussion group
                        # (e.g. posts with comments disabled). Skip
                        # those quietly and move on.
                        logger.debug(
                            "get_discussion_replies failed for %s/%s: %s",
                            target, post_id, e,
                        )

            elif task.type == ParsingType.CHAT_SEARCH:
                # ``target`` is a comma-separated list of keywords.
                # We hit Telegram's global public search index for
                # each keyword and pull the resulting channels/groups.
                # Optionally keep only those with a linked discussion
                # group (comments enabled).
                keywords = [k.strip() for k in task.target.split(",") if k.strip()]
                if not keywords:
                    raise ValueError("CHAT_SEARCH requires a non-empty target")

                only_with_discussion = bool(
                    params.get("only_with_discussion", True)
                )
                chat_type_filter = (params.get("chat_type") or "all").lower()
                # Reports intended for source discovery should not contain
                # empty/micro communities. Keep 150 as a hard floor even for
                # tasks created by an older frontend.
                min_participants = max(
                    150, int(params.get("min_participants") or 150)
                )
                total_limit = int(params.get("limit") or 5000)
                expand_queries = bool(params.get("expand_queries", True))
                # Keep per-keyword limit modest to avoid FloodWait
                per_keyword_limit = min(
                    int(params.get("per_keyword_limit") or 100), 200
                )
                raw_found = 0  # channels that passed type/participants filter
                scanned = 0  # channels inspected (for live progress display)
                search_requests = 0
                telegram_candidates = 0
                duplicate_count = 0
                filtered_type = 0
                filtered_participants = 0
                filtered_discussion = 0
                full_lookup_errors = 0

                # Live-progress helper. The UI polls /parsing every ~3 s; by
                # committing ``result_count`` and a human-readable progress
                # string as we go, the operator sees the number climb instead
                # of staring at a frozen "0 / в процессе". Throttled to one
                # commit every ~1.5 s so we don't hammer the DB.
                import time as _time
                _last_commit = 0.0

                async def _commit_progress(force: bool = False) -> None:
                    nonlocal _last_commit
                    now = _time.monotonic()
                    if not force and now - _last_commit < 1.5:
                        return
                    _last_commit = now
                    task.result_count = len(results)
                    task.params = {
                        **(task.params or {}),
                        "progress": (
                            f"Проверено каналов: {scanned} · "
                            f"запросов: {search_requests} · "
                            f"найдено подходящих: {len(results)}"
                        ),
                    }
                    await db.commit()

                for keyword in keywords:
                    if len(results) >= total_limit:
                        break
                    # Count one interactive search operation per user keyword,
                    # then issue several narrowly varied catalog queries. The
                    # previous code requested limit=200 once, but Telegram
                    # still returned only 8-10 relevance-ranked chats.
                    await rate_limiter.acquire(
                        "search_global",
                        account.id,
                        account_age_days=account_age_days,
                        min_delay=0.5,
                        max_delay=2.0,
                    )

                    search_queries = _expand_chat_search_queries(
                        keyword, enabled=expand_queries
                    )
                    for search_query in search_queries:
                        if len(results) >= total_limit:
                            break
                        search_requests += 1
                        await _commit_progress()

                        # Retry the same query once after FloodWait.
                        raw_result = None
                        for _attempt in range(2):
                            try:
                                raw_result = await client.invoke(
                                    functions.contacts.Search(
                                        q=search_query, limit=per_keyword_limit
                                    )
                                )
                                break
                            except errors.FloodWait as e:
                                logger.warning(
                                    "FloodWait on contacts.Search %r: %ss (attempt %d)",
                                    search_query, e.value, _attempt + 1,
                                )
                                await asyncio.sleep(e.value + 2)
                            except Exception as e:  # noqa: BLE001
                                logger.warning(
                                    "contacts.Search failed for %r: %s",
                                    search_query,
                                    e,
                                )
                                break

                        if raw_result is None:
                            continue

                        found_chats = getattr(raw_result, "chats", []) or []
                        telegram_candidates += len(found_chats)
                        logger.info(
                            "contacts.Search %r → %d chats",
                            search_query,
                            len(found_chats),
                        )
                        for ch in found_chats:
                            if len(results) >= total_limit:
                                break
                            # contacts.Search returns Channel objects for
                            # both broadcast channels and supergroups.
                            if not isinstance(ch, types.Channel):
                                continue
                            scanned += 1
                            await _commit_progress()
                            broadcast = bool(getattr(ch, "broadcast", False))
                            megagroup = bool(getattr(ch, "megagroup", False))
                            if broadcast and not megagroup:
                                chat_type = "channel"
                            elif megagroup and not broadcast:
                                chat_type = "group"
                            else:
                                chat_type = "channel" if broadcast else "group"

                            if (
                                chat_type_filter != "all"
                                and chat_type != chat_type_filter
                            ):
                                filtered_type += 1
                                continue

                            participants = (
                                getattr(ch, "participants_count", 0) or 0
                            )
                            if participants < min_participants:
                                filtered_participants += 1
                                continue

                            raw_found += 1

                            username = (getattr(ch, "username", "") or "").lower()
                            dedup_key = (ch.id, username)
                            if dedup_key in seen_user_ids:
                                duplicate_count += 1
                                continue
                            seen_user_ids.add(dedup_key)

                            # A public group is itself a writable discussion
                            # space and must not be discarded merely because it
                            # has no linked channel. Only broadcast channels
                            # require linked_chat_id when this filter is on.
                            linked_chat_id: int | None = None
                            about: str = ""
                            has_discussion = chat_type == "group"
                            if only_with_discussion and chat_type == "channel":
                                try:
                                    input_ch = types.InputChannel(
                                        channel_id=ch.id,
                                        access_hash=ch.access_hash,
                                    )
                                    full = await client.invoke(
                                        functions.channels.GetFullChannel(
                                            channel=input_ch
                                        )
                                    )
                                    full_chat = getattr(full, "full_chat", None)
                                    if full_chat is not None:
                                        linked_chat_id = getattr(
                                            full_chat, "linked_chat_id", None
                                        )
                                        about = (
                                            getattr(full_chat, "about", "") or ""
                                        )
                                        has_discussion = linked_chat_id is not None
                                except errors.FloodWait as e:
                                    logger.warning(
                                        "FloodWait GetFullChannel %s: %ss",
                                        ch.id,
                                        e.value,
                                    )
                                    await asyncio.sleep(e.value + 1)
                                except Exception as e:  # noqa: BLE001
                                    full_lookup_errors += 1
                                    logger.debug(
                                        "GetFullChannel failed for %s: %s",
                                        ch.id,
                                        e,
                                    )
                                if not has_discussion:
                                    filtered_discussion += 1
                                    continue

                            results.append(
                                {
                                    "telegram_id": ch.id,
                                    "username": username,
                                    "title": getattr(ch, "title", "") or "",
                                    "type": chat_type,
                                    "participants_count": participants,
                                    "has_discussion": has_discussion,
                                    "linked_chat_id": linked_chat_id or "",
                                    "about": about[:200],
                                    "keyword": keyword,
                                    "search_query": search_query,
                                    "link": f"https://t.me/{username}" if username else "",
                                }
                            )

                        if search_query != search_queries[-1]:
                            await asyncio.sleep(0.35)

                    # Small pause between user-provided keywords.
                    if keyword != keywords[-1]:
                        await asyncio.sleep(0.75)

                task.params = {
                    **(task.params or {}),
                    "search_stats": {
                        "requested_limit": total_limit,
                        "min_participants": min_participants,
                        "search_requests": search_requests,
                        "telegram_candidates": telegram_candidates,
                        "unique_after_filters": len(results),
                        "duplicates": duplicate_count,
                        "filtered_type": filtered_type,
                        "filtered_participants": filtered_participants,
                        "filtered_no_discussion": filtered_discussion,
                        "full_lookup_errors": full_lookup_errors,
                    },
                }
                await _commit_progress(force=True)

            elif task.type == ParsingType.TGSTAT_SEARCH:
                # Alternative to ``CHAT_SEARCH`` that does NOT
                # require an authorised Telegram account. We
                # query the TGStat catalog (https://api.tgstat.ru)
                # which has already indexed the public Telegram
                # graph through its own user-accounts. The trade-
                # off: results reflect what TGStat knows (last
                # crawled timestamp + paid catalog depth), not
                # live Telegram state.
                #
                # ``target`` is a comma-separated list of
                # keywords (or category names) — same shape as
                # ``chat_search`` so the operator doesn't have
                # to learn a new input format.
                if not tgstat_service.is_configured:
                    raise TGStatError(
                        "TGSTAT_API_TOKEN is not configured. Get a token at "
                        "https://tgstat.ru/my/profile and put it in backend/.env "
                        "as TGSTAT_API_TOKEN=..."
                    )

                keywords = [
                    k.strip() for k in task.target.split(",") if k.strip()
                ]
                if not keywords:
                    raise ValueError("TGSTAT_SEARCH requires a non-empty target")

                peer_type = (params.get("peer_type") or "all").lower()
                country = (params.get("country") or "").strip().lower() or None
                language = (params.get("language") or "russian").strip().lower()
                category = (params.get("category") or "").strip().lower() or None
                min_participants = max(
                    150, int(params.get("min_participants") or 150)
                )
                max_participants = int(params.get("max_participants") or 0)
                total_limit = int(params.get("limit") or 5000)
                per_keyword_limit = int(params.get("per_keyword_limit") or 100)

                for keyword in keywords:
                    if len(results) >= total_limit:
                        break
                    # TGStat caps per-request at 100. Loop with
                    # ``offset`` to collect more if the operator
                    # wants them.
                    offset = 0
                    while offset < per_keyword_limit:
                        page_size = min(100, per_keyword_limit - offset)
                        try:
                            items = await tgstat_service.search_channels(
                                q=keyword,
                                category=category,
                                country=country,
                                language=language,
                                peer_type=peer_type,
                                limit=page_size,
                                offset=offset,
                            )
                        except TGStatError as exc:
                            # Quota exhausted / bad key / etc. —
                            # surface and stop.
                            logger.warning(
                                "TGStat search failed for %r: %s", keyword, exc
                            )
                            raise
                        if not items:
                            break
                        for ch in items:
                            if len(results) >= total_limit:
                                break
                            participants = (
                                int(ch.get("participants_count") or 0)
                            )
                            if participants < min_participants:
                                continue
                            if (
                                max_participants
                                and participants > max_participants
                            ):
                                continue
                            tg_id = ch.get("tg_id")
                            if not tg_id:
                                continue
                            username = (ch.get("username") or "").lstrip("@").lower()
                            dedup_key = (tg_id, username)
                            if dedup_key in seen_user_ids:
                                continue
                            seen_user_ids.add(dedup_key)
                            results.append(
                                {
                                    "telegram_id": tg_id,
                                    "username": username,
                                    "title": ch.get("title") or "",
                                    "type": ch.get("peer_type") or "channel",
                                    "participants_count": participants,
                                    "category": ch.get("category") or "",
                                    "country": ch.get("country") or "",
                                    "language": ch.get("language") or "",
                                    "about": (ch.get("about") or "")[:200],
                                    "ci_index": ch.get("ci_index") or 0,
                                    "link": ch.get("link") or "",
                                    "source": "tgstat",
                                    "keyword": keyword,
                                }
                            )
                        offset += len(items)
                        # If TGStat returned fewer than a full
                        # page, we've exhausted this keyword.
                        if len(items) < page_size:
                            break

            # Write the results file. Use the union of keys so we never
            # silently drop columns added by other row types.
            if results:
                fieldnames: list[str] = []
                seen: set[str] = set()
                for row in results:
                    for key in row.keys():
                        if key not in seen:
                            seen.add(key)
                            fieldnames.append(key)

                os.makedirs("exports", exist_ok=True)
                filename = (
                    f"exports/parsing_{task_id}_"
                    f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
                )
                file_path = os.path.abspath(filename)

                with open(file_path, mode="w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                    writer.writeheader()
                    writer.writerows(results)

                task.file_path = file_path
                task.result_count = len(results)
                task.status = ParsingStatus.COMPLETED
                # Drop the transient live-progress line now that we're done.
                _p = {**(task.params or {})}
                _p.pop("progress", None)
                task.params = _p
            else:
                task.file_path = None
                task.result_count = 0
                task.status = ParsingStatus.COMPLETED
                # Store diagnostic when 0 results so the UI can explain why,
                # and drop the transient live-progress line.
                _p = {**(task.params or {})}
                _p.pop("progress", None)
                if task.type == ParsingType.CHAT_SEARCH:
                    _raw = locals().get("raw_found", 0)
                    _disc = locals().get("only_with_discussion", False)
                    if _disc and _raw > 0:
                        _p["debug_info"] = f"Найдено {_raw} каналов, но ни один не имеет открытых комментариев. Снимите галочку «только с открытыми комментариями» чтобы увидеть все."
                    elif not _raw:
                        _p["debug_info"] = "Telegram не нашёл каналов/групп по этим ключевым словам. Попробуйте другие слова или снимите фильтры."
                task.params = _p

        except NewbornAccountError as exc:
            # The account is in the first 3 days. Mark the task as
            # failed but with a *non-fatal* error so the operator
            # can re-queue it after the warm-up window passes.
            logger.warning("Parsing task %s skipped: %s", task_id, exc)
            task.status = ParsingStatus.FAILED
            task.file_path = None
            task.result_count = 0
            task.params = {
                **(task.params or {}),
                "last_error": f"newborn_account: {exc.phase}",
            }
        except RateLimitExceeded as exc:
            # Daily cap exhausted. Mark the task as failed with a
            # clear message; the operator can re-schedule it for
            # tomorrow.
            logger.warning("Parsing task %s hit rate limit: %s", task_id, exc)
            task.status = ParsingStatus.FAILED
            task.file_path = None
            task.result_count = 0
            task.params = {
                **(task.params or {}),
                "last_error": f"rate_limit: {exc}",
            }
        except Exception as e:
            logger.exception("Parsing task %s failed", task_id)
            task.status = ParsingStatus.FAILED
            task.file_path = None
            task.result_count = 0
            # Stash the error message in params so the UI can show it.
            task.params = {**(task.params or {}), "last_error": str(e)[:500]}

        task.finished_at = datetime.utcnow()
        await db.commit()
