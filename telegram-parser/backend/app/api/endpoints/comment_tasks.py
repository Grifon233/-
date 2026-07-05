from typing import List, Any
from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update
from sqlalchemy.orm import selectinload

from app.db.session import get_db
from app.schemas.comment_task import (
    CommentTaskResponse,
    CommentTaskCreate,
    CommentTaskUpdate,
    CommentDraftResponse,
    CommentLogResponse,
)
from app.models.comment_task import CommentTask, CommentDraft, CommentLog, CommentTaskStatus
from app.models.account import Account
from app.models.telegram_source import TelegramSource, TelegramSourceType
from app.tasks.commenting import (
    _run_neuro_commenting_task,
    run_neuro_commenting_task,
    pause_comment_task,
    stop_comment_task,
)
from app.tasks.commenting import approve_draft as celery_approve_draft
from app.api.deps import get_project_id
from app.services.ai_provider_service import get_provider_config

router = APIRouter()

SAFE_COMMENT_LIMITS = {
    "comments_per_account": 10,
    "comments_per_source": 1,
    "min_delay": 60,
    "max_delay": 180,
}


def _celery_has_workers() -> bool:
    try:
        return bool(run_neuro_commenting_task.app.control.ping(timeout=0.5))
    except Exception:
        return False


async def _validate_accounts_ready_for_task(
    db: AsyncSession,
    account_ids: list[int],
    project_id: int,
) -> list[str]:
    """Check accounts before starting a neuro-commenting task.

    Returns a list of warning strings for accounts with concerning but
    non-blocking proxy state (e.g. proxy expires soon). Raises 400 if any
    account has no proxy or a deactivated proxy — those would cause the task
    to produce zero results and mislead the operator.
    """
    from datetime import datetime, timedelta

    if not account_ids:
        return []

    result = await db.execute(
        select(Account)
        .options(selectinload(Account.proxy))
        .where(Account.id.in_(account_ids), Account.project_id == project_id)
    )
    accounts = result.scalars().all()
    valid_ids = {account.id for account in accounts}
    invalid_ids = set(account_ids) - valid_ids
    if invalid_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Аккаунты не найдены в проекте: {sorted(invalid_ids)}",
        )

    blocked: list[str] = []
    warnings: list[str] = []
    now = datetime.utcnow()

    for acc in accounts:
        phone = acc.phone_number or f"id={acc.id}"
        if not acc.proxy_id or acc.proxy is None:
            blocked.append(f"{phone}: прокси не назначен")
        elif acc.proxy.is_active is False:
            blocked.append(
                f"{phone}: прокси {acc.proxy.host}:{acc.proxy.port} отключён"
            )
        elif acc.proxy.expires_at and acc.proxy.expires_at < now + timedelta(days=3):
            days_left = max(0, (acc.proxy.expires_at - now).days)
            warnings.append(
                f"{phone}: прокси {acc.proxy.host}:{acc.proxy.port} истекает через {days_left} д."
            )

    if blocked:
        raise HTTPException(
            status_code=400,
            detail="Задача не запущена — у части аккаунтов нет рабочего прокси: "
            + " | ".join(blocked),
        )

    return warnings


@router.post("", response_model=CommentTaskResponse, status_code=status.HTTP_201_CREATED)
async def create_comment_task(
    task_in: CommentTaskCreate,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    """Create a new neuro-commenting task."""
    # Validate provider/model
    try:
        provider = get_provider_config(task_in.provider)
        if task_in.model not in provider["models"]:
            raise HTTPException(status_code=400, detail=f"Model {task_in.model} not supported by {task_in.provider}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    await _validate_accounts_ready_for_task(db, task_in.account_ids or [], project_id)

    # Validate sources exist and belong to project
    if task_in.source_ids:
        target_modes = {
            mode.value if hasattr(mode, "value") else str(mode)
            for mode in (task_in.target_modes or [task_in.target_mode])
        }
        allowed_types = set()
        if "channel_posts" in target_modes:
            allowed_types.add(TelegramSourceType.CHANNEL)
        if "group_context" in target_modes:
            allowed_types.add(TelegramSourceType.GROUP)
        result = await db.execute(
            select(TelegramSource.id, TelegramSource.source_type).where(
                TelegramSource.id.in_(task_in.source_ids),
                TelegramSource.project_id == project_id,
            )
        )
        rows = result.all()
        valid_ids = {row[0] for row in rows}
        invalid_ids = set(task_in.source_ids) - valid_ids
        if invalid_ids:
            raise HTTPException(status_code=400, detail=f"Invalid source IDs: {invalid_ids}")
        wrong_type_ids = [
            row[0]
            for row in rows
            if row[1] not in allowed_types and row[1] != TelegramSourceType.UNKNOWN
        ]
        if wrong_type_ids:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Selected sources do not match task mode. "
                    f"Wrong source IDs: {wrong_type_ids}"
                ),
            )

    payload = task_in.model_dump()
    if payload.get("target_modes"):
        payload["target_mode"] = payload["target_modes"][0]
    payload.update(SAFE_COMMENT_LIMITS)
    db_obj = CommentTask(
        **payload,
        project_id=project_id,
    )
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj


@router.get("", response_model=List[CommentTaskResponse])
async def read_comment_tasks(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    """Get all comment tasks for the project."""
    result = await db.execute(
        select(CommentTask)
        .where(CommentTask.project_id == project_id)
        .offset(skip)
        .limit(limit)
        .order_by(CommentTask.created_at.desc())
    )
    tasks = result.scalars().all()
    return [CommentTaskResponse.model_validate(t) for t in tasks]


@router.get("/{task_id}", response_model=CommentTaskResponse)
async def read_comment_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    """Get a specific comment task."""
    result = await db.execute(
        select(CommentTask).where(
            CommentTask.id == task_id,
            CommentTask.project_id == project_id,
        )
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Comment task not found")
    return task


@router.patch("/{task_id}", response_model=CommentTaskResponse)
async def update_comment_task(
    task_id: int,
    task_in: CommentTaskUpdate,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    """Update a comment task."""
    result = await db.execute(
        select(CommentTask).where(
            CommentTask.id == task_id,
            CommentTask.project_id == project_id,
        )
    )
    db_obj = result.scalar_one_or_none()
    if not db_obj:
        raise HTTPException(status_code=404, detail="Comment task not found")

    update_data = task_in.model_dump(exclude_unset=True)
    for safety_field in SAFE_COMMENT_LIMITS:
        update_data.pop(safety_field, None)

    # Validate provider/model if changing
    if "provider" in update_data or "model" in update_data:
        provider_name = update_data.get("provider", db_obj.provider)
        model_name = update_data.get("model", db_obj.model)
        try:
            provider = get_provider_config(provider_name)
            if model_name not in provider["models"]:
                raise HTTPException(status_code=400, detail=f"Model not supported")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    for field, value in update_data.items():
        setattr(db_obj, field, value)

    await db.commit()
    await db.refresh(db_obj)
    return db_obj


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
):
    """Delete a comment task and all its drafts/logs."""
    result = await db.execute(
        select(CommentTask).where(
            CommentTask.id == task_id,
            CommentTask.project_id == project_id,
        )
    )
    db_obj = result.scalar_one_or_none()
    if not db_obj:
        raise HTTPException(status_code=404, detail="Comment task not found")

    await db.delete(db_obj)
    await db.commit()
    return None


@router.post("/{task_id}/start")
async def start_comment_task(
    task_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
):
    """Start a neuro-commenting task."""
    result = await db.execute(
        select(CommentTask).where(
            CommentTask.id == task_id,
            CommentTask.project_id == project_id,
        )
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Comment task not found")

    # Guard against a double-start race. The old guard also required
    # ``started_at is not None``, but the runner sets started_at only once
    # it actually begins — so a fast second click (status already RUNNING,
    # started_at still NULL) slipped through and launched a SECOND runner,
    # producing duplicate comments. Status alone is the correct guard.
    if task.status == CommentTaskStatus.RUNNING:
        raise HTTPException(status_code=409, detail="Task is already running")

    proxy_warnings = await _validate_accounts_ready_for_task(db, task.account_ids or [], project_id)

    task.status = CommentTaskStatus.RUNNING
    await db.commit()

    if _celery_has_workers():
        run_neuro_commenting_task.delay(task_id)
        runner = "celery"
    else:
        background_tasks.add_task(_run_neuro_commenting_task, task_id)
        runner = "local-background"

    return {"status": "started", "task_id": task_id, "runner": runner, "warnings": proxy_warnings}


@router.post("/{task_id}/pause")
async def pause_comment_task_endpoint(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
):
    """Pause a running task."""
    result = await db.execute(
        select(CommentTask).where(
            CommentTask.id == task_id,
            CommentTask.project_id == project_id,
        )
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Comment task not found")

    if task.status != CommentTaskStatus.RUNNING:
        raise HTTPException(status_code=400, detail="Task is not running")

    task.status = CommentTaskStatus.PAUSED
    await db.commit()

    if _celery_has_workers():
        pause_comment_task.delay(task_id)

    return {"status": "paused"}


@router.post("/{task_id}/stop")
async def stop_comment_task_endpoint(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
):
    """Stop a task."""
    result = await db.execute(
        select(CommentTask).where(
            CommentTask.id == task_id,
            CommentTask.project_id == project_id,
        )
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Comment task not found")

    task.status = CommentTaskStatus.STOPPED
    await db.commit()

    if _celery_has_workers():
        stop_comment_task.delay(task_id)

    return {"status": "stopped"}


# Draft management
@router.get("/{task_id}/drafts", response_model=List[CommentDraftResponse])
async def read_task_drafts(
    task_id: int,
    skip: int = 0,
    limit: int = 100,
    status_filter: str = None,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
):
    """Get drafts for a task."""
    # Verify task belongs to project
    task_result = await db.execute(
        select(CommentTask.id).where(
            CommentTask.id == task_id,
            CommentTask.project_id == project_id,
        )
    )
    if not task_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Comment task not found")

    query = select(CommentDraft).where(CommentDraft.task_id == task_id)

    if status_filter:
        query = query.where(CommentDraft.status == status_filter)

    query = query.offset(skip).limit(limit).order_by(CommentDraft.created_at.desc())

    result = await db.execute(query)
    drafts = result.scalars().all()
    return [CommentDraftResponse.model_validate(d) for d in drafts]


@router.post("/{task_id}/drafts/{draft_id}/approve")
async def approve_draft(
    task_id: int,
    draft_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
):
    """Approve a draft for publication."""
    from app.tasks.commenting import _approve_draft as _approve_draft_fn

    # Verify task belongs to project
    task_result = await db.execute(
        select(CommentTask.id).where(
            CommentTask.id == task_id,
            CommentTask.project_id == project_id,
        )
    )
    if not task_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Comment task not found")

    # Verify draft belongs to task
    draft_result = await db.execute(
        select(CommentDraft).where(
            CommentDraft.id == draft_id,
            CommentDraft.task_id == task_id,
        )
    )
    draft = draft_result.scalar_one_or_none()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    if draft.status not in ("pending", "approved"):
        raise HTTPException(status_code=400, detail="Draft is not pending")

    draft.status = "approved"
    draft.approved_by = "manual"
    await db.commit()

    if _celery_has_workers():
        celery_approve_draft.delay(draft_id, "manual")
    else:
        background_tasks.add_task(_approve_draft_fn, draft_id, "manual")

    return {"status": "approved", "draft_id": draft_id}


@router.post("/{task_id}/drafts/{draft_id}/reject")
async def reject_draft(
    task_id: int,
    draft_id: int,
    reason: str | None = Body(default=None, embed=True),
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
):
    """Reject a draft.

    ``reason`` is read from the JSON body (``{"reason": "..."}``) and is
    optional. Previously it was a query parameter, which is an awkward way
    to pass a human-written note; body keeps it consistent with the rest
    of the API.
    """
    task_result = await db.execute(
        select(CommentTask.id).where(
            CommentTask.id == task_id,
            CommentTask.project_id == project_id,
        )
    )
    if not task_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Comment task not found")

    draft_result = await db.execute(
        select(CommentDraft).where(
            CommentDraft.id == draft_id,
            CommentDraft.task_id == task_id,
        )
    )
    draft = draft_result.scalar_one_or_none()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    if draft.status != "pending":
        raise HTTPException(status_code=400, detail="Draft is not pending")

    draft.status = "rejected"
    draft.rejection_reason = reason
    # Record the rejection so the operator sees it happened (and why) in the
    # task log, mirroring how the runtime logs approvals/publishes.
    db.add(
        CommentLog(
            task_id=task_id,
            action="rejected",
            account_id=draft.account_id,
            source_id=draft.source_id,
            draft_id=draft.id,
            details={"reason": reason},
        )
    )
    await db.commit()

    return {"status": "rejected", "draft_id": draft_id}


@router.get("/{task_id}/logs", response_model=List[CommentLogResponse])
async def read_task_logs(
    task_id: int,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
):
    """Get logs for a task."""
    # Verify task belongs to project
    task_result = await db.execute(
        select(CommentTask.id).where(
            CommentTask.id == task_id,
            CommentTask.project_id == project_id,
        )
    )
    if not task_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Comment task not found")

    result = await db.execute(
        select(CommentLog)
        .where(CommentLog.task_id == task_id)
        .offset(skip)
        .limit(limit)
        .order_by(CommentLog.created_at.desc())
    )
    logs = result.scalars().all()
    return [CommentLogResponse.model_validate(l) for l in logs]
