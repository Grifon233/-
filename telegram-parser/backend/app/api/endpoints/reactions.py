"""
Reactions API endpoints
Массовые реакции на посты
"""

from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.db.session import get_db
from app.models.account import Account
from app.models.reaction_task import ReactionTask, ReactionTaskStatus
from app.schemas.reaction import (
    ReactionTaskCreate,
    ReactionTaskUpdate,
    ReactionTaskResponse,
    ReactionTaskCreateResponse,
    ReactionStats,
)
from app.services.reactions_service import stop_reaction_task
from app.tasks.automation import run_reaction_task
from app.api.deps import get_project_id

router = APIRouter()


def task_to_response(task: ReactionTask, account_name: str = "") -> ReactionTaskResponse:
    return ReactionTaskResponse(
        id=task.id,
        account_id=task.account_id,
        account_name=account_name,
        channels=task.get_channels(),
        reactions_used=task.reactions_used,
        status=task.status,
        reactions_per_day=task.reactions_per_day,
        selected_reactions=task.get_reactions(),
        posts_per_channel=task.posts_per_channel,
        started_at=task.started_at,
        completed_at=task.completed_at,
        created_at=task.created_at,
    )

@router.get("/stats/summary", response_model=ReactionStats)
async def get_stats(db: AsyncSession = Depends(get_db), project_id: int = Depends(get_project_id)):
    """Get reaction statistics."""
    result = await db.execute(select(ReactionTask).where(ReactionTask.project_id == project_id))
    tasks = result.scalars().all()

    total_reactions = sum(t.reactions_used for t in tasks)
    active_tasks = sum(1 for t in tasks if t.status == ReactionTaskStatus.RUNNING)
    accounts = set(t.account_id for t in tasks if t.status == ReactionTaskStatus.RUNNING)

    return ReactionStats(
        total_reactions=total_reactions,
        reactions_today=0,
        active_tasks=active_tasks,
        accounts_reacting=len(accounts),
    )


@router.get("", response_model=List[ReactionTaskResponse])
async def list_reaction_tasks(
    db: AsyncSession = Depends(get_db),
    status: ReactionTaskStatus = None,
    limit: int = 50,
    project_id: int = Depends(get_project_id),
):
    """Get all reaction tasks."""
    query = (
        select(ReactionTask, Account)
        .outerjoin(Account, ReactionTask.account_id == Account.id)
        .where(ReactionTask.project_id == project_id)
        .order_by(ReactionTask.created_at.desc())
    )

    if status:
        query = query.where(ReactionTask.status == status)

    query = query.limit(limit)
    result = await db.execute(query)
    rows = result.all()

    responses = []
    for task, account in rows:
        account_name = account.phone_number if account else f"Account {task.account_id}"
        responses.append(task_to_response(task, account_name))

    return responses


@router.post("", response_model=ReactionTaskCreateResponse)
@router.post("/start", response_model=ReactionTaskCreateResponse)
async def create_reaction_task(
    task_data: ReactionTaskCreate,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
):
    """Create and start a new reaction task."""
    # Check account exists
    result = await db.execute(select(Account).where(Account.id == task_data.account_id, Account.project_id == project_id))
    account = result.scalar_one_or_none()

    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    # Create task
    task = ReactionTask(
        account_id=task_data.account_id,
        project_id=project_id,
        reactions_per_day=task_data.reactions_per_day,
        posts_per_channel=task_data.posts_per_channel,
        status=ReactionTaskStatus.PENDING,
    )
    task.set_channels(task_data.channels)
    task.set_reactions(task_data.reactions)
    db.add(task)
    await db.commit()
    await db.refresh(task)

    run_reaction_task.delay(task.id)

    return ReactionTaskCreateResponse(
        task_id=task.id,
        status="started",
        message=f"Reaction task {task.id} started",
    )


@router.get("/{task_id}", response_model=ReactionTaskResponse)
async def get_reaction_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
):
    """Get a specific reaction task."""
    result = await db.execute(select(ReactionTask).where(ReactionTask.id == task_id, ReactionTask.project_id == project_id))
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    account = await db.execute(select(Account).where(Account.id == task.account_id))
    account = account.scalar_one_or_none()
    account_name = account.phone_number if account else f"Account {task.account_id}"

    return task_to_response(task, account_name)


@router.post("/{task_id}/stop")
async def stop_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
):
    """Stop a running reaction task."""
    result = await db.execute(select(ReactionTask).where(ReactionTask.id == task_id, ReactionTask.project_id == project_id))
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status not in (ReactionTaskStatus.PENDING, ReactionTaskStatus.RUNNING):
        raise HTTPException(status_code=400, detail="Task is not running")

    await stop_reaction_task(task_id)

    task.status = ReactionTaskStatus.STOPPED
    await db.commit()

    return {"status": "stopped", "task_id": task_id}


@router.delete("/{task_id}")
async def delete_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
):
    """Delete a reaction task."""
    result = await db.execute(select(ReactionTask).where(ReactionTask.id == task_id, ReactionTask.project_id == project_id))
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status in (ReactionTaskStatus.PENDING, ReactionTaskStatus.RUNNING):
        raise HTTPException(status_code=409, detail="Stop task before deleting it")

    await db.delete(task)
    await db.commit()

    return {"status": "deleted", "task_id": task_id}


