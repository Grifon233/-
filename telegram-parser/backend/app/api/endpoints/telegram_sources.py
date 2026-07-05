import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pyrogram.enums import ChatType
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.api.deps import get_project_id
from app.db.session import get_db
from app.models.account import Account
from app.models.project import Project
from app.models.telegram_source import TelegramSource, TelegramSourceGroup, TelegramSourceType
from app.schemas.telegram_source import (
    TelegramSourceBulkCreate,
    TelegramSourceBulkResponse,
    TelegramSourceDeduplicateResponse,
    TelegramSourceDiagnoseRequest,
    TelegramSourceDiagnoseResponse,
    TelegramSourceGroupCreate,
    TelegramSourceGroupResponse,
    TelegramSourceGroupUpdate,
    TelegramSourceResponse,
)
from app.services.telegram_service import telegram_service

router = APIRouter()

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{5,32}$")
TME_RE = re.compile(r"^(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me)/(.+?)/?$", re.IGNORECASE)
TME_TEXT_RE = re.compile(r"(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me)/[A-Za-z0-9_+/.-]+", re.IGNORECASE)


def normalize_telegram_link(raw_link: str) -> Optional[str]:
    link = raw_link.strip()
    if not link:
        return None
    if link.startswith("@"):
        username = link[1:]
        return f"https://t.me/{username.lower()}" if USERNAME_RE.fullmatch(username) else None

    match = TME_RE.fullmatch(link)
    if not match:
        return None
    path = match.group(1).strip("/")
    if not path or any(character.isspace() for character in path):
        return None
    if path.startswith("+") or path.startswith("joinchat/"):
        return f"https://t.me/{path}"
    username = path.split("/", 1)[0]
    if not USERNAME_RE.fullmatch(username):
        return None
    return f"https://t.me/{path.lower()}"


def is_invite_link(link: str) -> bool:
    return "/+" in link or "/joinchat/" in link


def telegram_chat_target(link: str) -> str:
    """Convert stored public t.me links to the username Pyrogram expects."""
    value = (link or "").strip()
    if not value or is_invite_link(value):
        return value
    if value.startswith("@"):
        return value[1:]
    match = TME_RE.fullmatch(value)
    if match:
        return match.group(1).strip("/").split("/", 1)[0]
    return value


def find_redirect_link(text: Optional[str], current_link: str) -> Optional[str]:
    if not text:
        return None
    for raw in TME_TEXT_RE.findall(text):
        normalized = normalize_telegram_link(raw)
        if normalized and normalized != current_link:
            return normalized
    return None


def map_chat_type(chat_type) -> TelegramSourceType:
    if chat_type == ChatType.CHANNEL:
        return TelegramSourceType.CHANNEL
    if chat_type in (ChatType.GROUP, ChatType.SUPERGROUP):
        return TelegramSourceType.GROUP
    if chat_type in (ChatType.PRIVATE, ChatType.BOT):
        return TelegramSourceType.CHAT
    return TelegramSourceType.UNKNOWN


@router.get("", response_model=List[TelegramSourceResponse])
async def list_sources(
    source_type: Optional[TelegramSourceType] = None,
    group_id: Optional[int] = None,
    project_id: int = Depends(get_project_id),
    db: AsyncSession = Depends(get_db),
):
    query = select(TelegramSource).where(TelegramSource.project_id == project_id)
    if source_type:
        query = query.where(TelegramSource.source_type == source_type)
    if group_id:
        query = query.where(TelegramSource.group_id == group_id)
    result = await db.execute(query.order_by(TelegramSource.created_at.desc()))
    return result.scalars().all()


@router.get("/groups", response_model=List[TelegramSourceGroupResponse])
async def list_source_groups(
    project_id: int = Depends(get_project_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(TelegramSourceGroup)
        .where(TelegramSourceGroup.project_id == project_id)
        .order_by(TelegramSourceGroup.created_at.desc())
    )
    return result.scalars().all()


@router.post("/groups", response_model=TelegramSourceGroupResponse, status_code=status.HTTP_201_CREATED)
async def create_source_group(
    group_in: TelegramSourceGroupCreate,
    project_id: int = Depends(get_project_id),
    db: AsyncSession = Depends(get_db),
):
    if not await db.get(Project, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    existing = await db.execute(
        select(TelegramSourceGroup.id).where(
            TelegramSourceGroup.project_id == project_id,
            TelegramSourceGroup.name == group_in.name.strip(),
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Source group already exists")
    db_obj = TelegramSourceGroup(
        project_id=project_id,
        name=group_in.name.strip(),
        description=group_in.description,
    )
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj


@router.patch("/groups/{group_id}", response_model=TelegramSourceGroupResponse)
async def update_source_group(
    group_id: int,
    group_in: TelegramSourceGroupUpdate,
    project_id: int = Depends(get_project_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(TelegramSourceGroup).where(
            TelegramSourceGroup.id == group_id,
            TelegramSourceGroup.project_id == project_id,
        )
    )
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="Source group not found")
    update_data = group_in.model_dump(exclude_unset=True)
    if "name" in update_data and update_data["name"]:
        group.name = update_data["name"].strip()
    if "description" in update_data:
        group.description = update_data["description"]
    await db.commit()
    await db.refresh(group)
    return group


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source_group(
    group_id: int,
    project_id: int = Depends(get_project_id),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import delete as sa_delete
    result = await db.execute(
        select(TelegramSourceGroup).where(
            TelegramSourceGroup.id == group_id,
            TelegramSourceGroup.project_id == project_id,
        )
    )
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="Source group not found")

    # Get IDs of sources in this group to cascade-delete dependents
    src_ids_result = await db.execute(
        select(TelegramSource.id).where(
            TelegramSource.group_id == group_id,
            TelegramSource.project_id == project_id,
        )
    )
    source_ids = [row[0] for row in src_ids_result.fetchall()]

    if source_ids:
        # FK chain without CASCADE in DB:
        # comment_logs.draft_id → comment_drafts.id
        # comment_logs.source_id → telegram_sources.id (SET NULL, also not in DB)
        # comment_drafts.source_id → telegram_sources.id
        # comment_task_source_states.source_id → telegram_sources.id
        # Must delete in dependency order.
        from app.models.comment_task import CommentDraft, CommentLog, CommentTaskSourceState

        # 1. Get draft IDs for these sources
        draft_ids_result = await db.execute(
            select(CommentDraft.id).where(CommentDraft.source_id.in_(source_ids))
        )
        draft_ids = [row[0] for row in draft_ids_result.fetchall()]

        # 2. Delete logs that ref these drafts or sources (both FKs)
        log_filter = []
        if draft_ids:
            log_filter.append(CommentLog.draft_id.in_(draft_ids))
        log_filter.append(CommentLog.source_id.in_(source_ids))
        from sqlalchemy import or_
        await db.execute(sa_delete(CommentLog).where(or_(*log_filter)))

        # 3. Delete drafts
        await db.execute(sa_delete(CommentDraft).where(CommentDraft.source_id.in_(source_ids)))

        # 4. Delete source states
        await db.execute(
            sa_delete(CommentTaskSourceState).where(CommentTaskSourceState.source_id.in_(source_ids))
        )

        # 5. Delete the sources themselves
        await db.execute(sa_delete(TelegramSource).where(TelegramSource.id.in_(source_ids)))

    await db.delete(group)
    await db.commit()


@router.delete("/orphaned", status_code=status.HTTP_200_OK)
async def delete_orphaned_sources(
    project_id: int = Depends(get_project_id),
    db: AsyncSession = Depends(get_db),
):
    """Delete all sources not assigned to any group (group_id IS NULL)."""
    from sqlalchemy import delete as sa_delete
    result = await db.execute(
        sa_delete(TelegramSource).where(
            TelegramSource.project_id == project_id,
            TelegramSource.group_id.is_(None),
        ).returning(TelegramSource.id)
    )
    deleted_ids = result.fetchall()
    await db.commit()
    return {"deleted": len(deleted_ids)}


@router.post("/bulk", response_model=TelegramSourceBulkResponse, status_code=status.HTTP_201_CREATED)
async def bulk_create_sources(
    source_in: TelegramSourceBulkCreate,
    project_id: int = Depends(get_project_id),
    db: AsyncSession = Depends(get_db),
):
    if not await db.get(Project, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    if source_in.group_id:
        group = await db.execute(
            select(TelegramSourceGroup.id).where(
                TelegramSourceGroup.id == source_in.group_id,
                TelegramSourceGroup.project_id == project_id,
            )
        )
        if not group.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Source group not found")

    created = 0
    skipped = 0
    invalid = []
    seen = set()
    for link in source_in.links:
        normalized = normalize_telegram_link(link)
        if not normalized:
            invalid.append(link)
            continue
        if normalized in seen:
            skipped += 1
            continue
        seen.add(normalized)

        existing = await db.execute(
            select(TelegramSource.id).where(
                TelegramSource.project_id == project_id,
                TelegramSource.group_id == source_in.group_id,
                TelegramSource.normalized_link == normalized,
            )
        )
        if existing.scalar_one_or_none():
            skipped += 1
            continue
        db.add(
            TelegramSource(
                project_id=project_id,
                group_id=source_in.group_id,
                link=link.strip(),
                normalized_link=normalized,
                source_type=source_in.source_type,
            )
        )
        created += 1

    await db.commit()
    return TelegramSourceBulkResponse(created=created, skipped=skipped, invalid=invalid)


@router.post("/deduplicate", response_model=TelegramSourceDeduplicateResponse)
async def deduplicate_sources(
    group_id: Optional[int] = None,
    project_id: int = Depends(get_project_id),
    db: AsyncSession = Depends(get_db),
):
    """Delete duplicate normalized links, keeping the oldest row."""
    query = select(TelegramSource).where(TelegramSource.project_id == project_id)
    if group_id:
        query = query.where(TelegramSource.group_id == group_id)
    result = await db.execute(query.order_by(TelegramSource.created_at.asc(), TelegramSource.id.asc()))
    seen: set[str] = set()
    removed = 0
    for source in result.scalars().all():
        if source.normalized_link in seen:
            await db.delete(source)
            removed += 1
        else:
            seen.add(source.normalized_link)
    await db.commit()
    return TelegramSourceDeduplicateResponse(removed=removed)


async def _pick_diagnose_account(
    db: AsyncSession, project_id: int, account_id: Optional[int]
) -> Account:
    query = select(Account).where(
        Account.project_id == project_id,
        Account.session_string.is_not(None),
        Account.proxy_id.is_not(None),
    )
    if account_id:
        query = query.where(Account.id == account_id)
    result = await db.execute(query.order_by(Account.id.asc()))
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(
            status_code=400,
            detail="No account with session and proxy is available for source diagnosis",
        )
    return account


@router.post("/diagnose", response_model=TelegramSourceDiagnoseResponse)
async def diagnose_sources(
    payload: TelegramSourceDiagnoseRequest,
    project_id: int = Depends(get_project_id),
    db: AsyncSession = Depends(get_db),
):
    """Resolve Telegram links and update their source type.

    This does not post or comment. It only connects through one selected
    account, calls ``get_chat`` and records the detected type. Invite
    links that cannot be resolved without joining are marked as ``closed``.
    """
    account = await _pick_diagnose_account(db, project_id, payload.account_id)
    query = select(TelegramSource).where(TelegramSource.project_id == project_id)
    if payload.group_id:
        query = query.where(TelegramSource.group_id == payload.group_id)
    query = query.limit(payload.limit).order_by(TelegramSource.id.asc())
    sources = (await db.execute(query)).scalars().all()
    client = await telegram_service.get_client(account)

    checked = updated = deleted = failed = 0
    errors: list[str] = []
    counts = {item.value: 0 for item in TelegramSourceType}

    for source in sources:
        checked += 1
        source_target = telegram_chat_target(source.normalized_link)
        try:
            chat = await client.get_chat(source_target)
            detected = map_chat_type(chat.type)
            if detected != source.source_type:
                source.source_type = detected
                updated += 1
            source.title = getattr(chat, "title", None) or getattr(chat, "first_name", None)

            if detected == TelegramSourceType.CHAT:
                source.is_enabled = False
                if payload.delete_invalid:
                    await db.delete(source)
                    deleted += 1
                    counts[TelegramSourceType.CHAT.value] = counts.get(TelegramSourceType.CHAT.value, 0) + 1
                    continue

            if detected == TelegramSourceType.CHANNEL:
                try:
                    latest_messages = [item async for item in client.get_chat_history(source_target, limit=1)]
                except Exception:
                    latest_messages = []
                latest_text = ""
                if latest_messages:
                    latest = latest_messages[0]
                    latest_text = getattr(latest, "text", None) or getattr(latest, "caption", None) or ""
                redirect_link = find_redirect_link(latest_text, source.normalized_link)
                if redirect_link:
                    source.is_enabled = False
                    source.title = f"{source.title or source.normalized_link} (есть новая ссылка)"
                    errors.append(f"{source.normalized_link}: найден переход на {redirect_link}")
                    if payload.delete_invalid:
                        await db.delete(source)
                        deleted += 1
                        continue

            counts[detected.value] = counts.get(detected.value, 0) + 1
        except Exception as exc:  # noqa: BLE001
            error_text = str(exc)
            if is_invite_link(source.normalized_link):
                if source.source_type != TelegramSourceType.CLOSED:
                    source.source_type = TelegramSourceType.CLOSED
                    updated += 1
                counts[TelegramSourceType.CLOSED.value] = counts.get(TelegramSourceType.CLOSED.value, 0) + 1
            elif payload.delete_invalid:
                await db.delete(source)
                deleted += 1
            else:
                failed += 1
                source.is_enabled = False
                errors.append(f"{source.normalized_link}: {error_text[:160]}")
    await db.commit()
    return TelegramSourceDiagnoseResponse(
        checked=checked,
        updated=updated,
        deleted=deleted,
        failed=failed,
        counts=counts,
        errors=errors[:20],
    )


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(
    source_id: int,
    project_id: int = Depends(get_project_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(TelegramSource).where(
            TelegramSource.id == source_id,
            TelegramSource.project_id == project_id,
        )
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="Telegram source not found")
    await db.delete(source)
    await db.commit()
