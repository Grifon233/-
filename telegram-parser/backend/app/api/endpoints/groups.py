"""
Groups API endpoints
Автоматическое вступление в группы
"""

from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.db.session import get_db
from app.models.account import Account
from app.models.group_task import GroupTask, GroupTaskStatus
from app.schemas.group import (
    GroupTaskCreate,
    GroupTaskResponse,
    GroupTaskCreateResponse,
)
from app.services.groups_service import stop_group_task, get_safe_groups
from app.tasks.automation import run_group_task
from app.api.deps import get_project_id

router = APIRouter()


@router.get("", response_model=List[GroupTaskResponse])
async def list_group_tasks(
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
    project_id: int = Depends(get_project_id),
):
    """Get all group tasks."""
    query = (
        select(GroupTask, Account)
        .outerjoin(Account, GroupTask.account_id == Account.id)
        .where(GroupTask.project_id == project_id)
        .order_by(GroupTask.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(query)
    rows = result.all()

    responses = []
    for task, account in rows:
        account_name = account.phone_number if account else f"Account {task.account_id}"

        responses.append(GroupTaskResponse(
            id=task.id,
            account_id=task.account_id,
            account_name=account_name,
            groups=task.get_groups(),
            status=task.status,
            groups_joined=task.groups_joined,
            started_at=task.started_at,
            completed_at=task.completed_at,
            created_at=task.created_at,
        ))

    return responses


@router.post("", response_model=GroupTaskCreateResponse)
async def create_group_task(
    task_data: GroupTaskCreate,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
):
    """Create and start a new group joining task."""
    # Check account exists
    result = await db.execute(select(Account).where(Account.id == task_data.account_id, Account.project_id == project_id))
    account = result.scalar_one_or_none()

    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    # Create task
    task = GroupTask(
        account_id=task_data.account_id,
        project_id=project_id,
        status=GroupTaskStatus.PENDING,
    )
    task.set_groups(task_data.groups)
    db.add(task)
    await db.commit()
    await db.refresh(task)

    run_group_task.delay(task.id, task_data.delay_min, task_data.delay_max)

    return GroupTaskCreateResponse(
        task_id=task.id,
        status="started",
        message=f"Group task {task.id} started",
    )


@router.post("/{task_id}/stop")
async def stop_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
):
    """Stop a running group task."""
    result = await db.execute(select(GroupTask).where(GroupTask.id == task_id, GroupTask.project_id == project_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status not in (GroupTaskStatus.PENDING, GroupTaskStatus.RUNNING):
        raise HTTPException(status_code=400, detail="Task is not running")

    task.status = GroupTaskStatus.STOPPED
    await db.commit()
    await stop_group_task(task_id)
    return {"status": "stopped", "task_id": task_id}


@router.get("/safe-groups", response_model=List[str])
async def list_safe_groups():
    """Get list of safe groups for joining."""
    return get_safe_groups()
