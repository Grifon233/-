from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional
from datetime import datetime

from app.db.session import get_db
from app.models.safety import SourceAllowlist, SafetyDraft, ActionLog, SourceType, DraftStatus
from app.models.account import Account
from app.schemas.safety import (
    SourceAllowlistCreate, SourceAllowlistResponse,
    AccountLimitResponse,
    SafetyDraftCreate, SafetyDraftResponse,
    DraftModerateRequest,
    ActionLogResponse,
    RateLimitCheck, RateLimitResult,
)
from app.services.safety_manager import SafetyManager, get_safety_manager
from app.api.deps import get_project_id

router = APIRouter(tags=["safety"])


@router.get("/sources", response_model=List[SourceAllowlistResponse])
async def list_sources(
    project_id: int = Depends(get_project_id),
    db: AsyncSession = Depends(get_db),
):
    """Список разрешённых источников."""
    result = await db.execute(
        select(SourceAllowlist).where(SourceAllowlist.project_id == project_id)
    )
    return result.scalars().all()


@router.post("/sources", response_model=SourceAllowlistResponse)
async def add_source(
    data: SourceAllowlistCreate,
    project_id: int = Depends(get_project_id),
    db: AsyncSession = Depends(get_db),
):
    """Добавить источник в allowlist."""
    sm = get_safety_manager(db)
    return await sm.add_source(
        project_id=project_id,
        source_type=data.source_type,
        source_id=data.source_id,
        source_title=data.source_title,
    )


@router.post("/sources/{source_id}/verify", response_model=SourceAllowlistResponse)
async def verify_consent(
    source_id: int,
    expires_days: int = Query(365, ge=1, le=3650),
    db: AsyncSession = Depends(get_db),
):
    """Подтвердить consent источника."""
    sm = get_safety_manager(db)
    try:
        return await sm.verify_consent(source_id, expires_days)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/drafts", response_model=List[SafetyDraftResponse])
async def list_drafts(
    project_id: int = Depends(get_project_id),
    status: Optional[DraftStatus] = None,
    account_id: Optional[int] = None,
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Список черновиков."""
    query = select(SafetyDraft).where(SafetyDraft.project_id == project_id)

    if status:
        query = query.where(SafetyDraft.status == status)
    if account_id:
        query = query.where(SafetyDraft.account_id == account_id)

    query = query.order_by(SafetyDraft.created_at.desc()).limit(limit)

    result = await db.execute(query)
    return result.scalars().all()


@router.post("/drafts", response_model=SafetyDraftResponse)
async def create_draft(
    data: SafetyDraftCreate,
    project_id: int = Depends(get_project_id),
    db: AsyncSession = Depends(get_db),
):
    """Создать черновик (для AI генерации)."""
    sm = get_safety_manager(db)

    # Проверка allowlist
    allowed = await sm.check_allowlist(
        data.source_id,
        SourceType.CHANNEL,
        project_id,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Source not in allowlist")

    return await sm.create_draft(
        project_id=project_id,
        account_id=data.account_id,
        source_id=data.source_id,
        post_id=data.post_id,
        context=data.context,
        draft=data.draft,
        prompt_version=data.prompt_version,
        model_used=data.model_used,
    )


@router.post("/drafts/{draft_id}/moderate", response_model=SafetyDraftResponse)
async def moderate_draft(
    draft_id: int,
    data: DraftModerateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Одобрить или отклонить черновик."""
    sm = get_safety_manager(db)

    try:
        if data.action == "approve":
            return await sm.approve_draft(draft_id, "admin", data.edited_draft)
        else:
            return await sm.reject_draft(draft_id, "admin")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/limits/{account_id}", response_model=AccountLimitResponse)
async def get_limits(
    account_id: int,
    project_id: int = Depends(get_project_id),
    db: AsyncSession = Depends(get_db),
):
    """Получить текущие лимиты аккаунта."""
    # Check account exists in project
    acc_check = await db.execute(
        select(Account).where(Account.id == account_id, Account.project_id == project_id)
    )
    if not acc_check.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Account not found in this project")

    sm = get_safety_manager(db)

    result = {"account_id": account_id, "date": datetime.utcnow()}
    for action_type in ["dm", "comment", "reaction", "join"]:
        rl = await sm.check_rate_limit(account_id, action_type)
        result[f"{action_type}_count"] = rl["current"]
        result[f"{action_type}_remaining"] = rl["remaining"]

    result["limits"] = {
        "dm": 50,
        "comment": 30,
        "reaction": 100,
        "join": 5,
    }

    return result


@router.post("/limits/check", response_model=RateLimitResult)
async def check_rate_limit(
    data: RateLimitCheck,
    project_id: int = Depends(get_project_id),
    db: AsyncSession = Depends(get_db),
):
    """Проверить rate limit для действия."""
    # Check account exists in project
    acc_check = await db.execute(
        select(Account).where(Account.id == data.account_id, Account.project_id == project_id)
    )
    if not acc_check.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Account not found in this project")

    sm = get_safety_manager(db)
    return await sm.check_rate_limit(data.account_id, data.action_type)


@router.get("/logs", response_model=List[ActionLogResponse])
async def list_logs(
    project_id: int = Depends(get_project_id),
    account_id: Optional[int] = None,
    action_type: Optional[str] = None,
    limit: int = Query(100, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Журнал действий."""
    query = select(ActionLog).where(ActionLog.project_id == project_id)

    if account_id:
        query = query.where(ActionLog.account_id == account_id)
    if action_type:
        query = query.where(ActionLog.action_type == action_type)

    query = query.order_by(ActionLog.timestamp.desc()).limit(limit)

    result = await db.execute(query)
    return result.scalars().all()
