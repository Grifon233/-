"""Celery entry points for long-running Telegram automation."""

from app.core.celery_app import async_run, celery_app
from app.db.session import SessionLocal
from app.models.account import Account
from app.models.group_task import GroupTask
from app.models.reaction_task import ReactionTask
from app.services.groups_service import execute_group_task
from app.services.reactions_service import mass_react_for_account


@celery_app.task(name="app.tasks.automation.run_group_task")
def run_group_task(task_id: int, delay_min: int = 30, delay_max: int = 120):
    return async_run(_run_group_task(task_id, delay_min, delay_max))


async def _run_group_task(task_id: int, delay_min: int, delay_max: int) -> None:
    async with SessionLocal() as db:
        task = await db.get(GroupTask, task_id)
        if not task:
            return
        account = await db.get(Account, task.account_id)
        if account and account.project_id != task.project_id:
            return
        if not account:
            return
        await execute_group_task(
            account,
            task.get_groups(),
            task.id,
            delay_min=delay_min,
            delay_max=delay_max,
        )


@celery_app.task(name="app.tasks.automation.run_reaction_task")
def run_reaction_task(task_id: int):
    return async_run(_run_reaction_task(task_id))


async def _run_reaction_task(task_id: int) -> None:
    async with SessionLocal() as db:
        task = await db.get(ReactionTask, task_id)
        if not task:
            return
        account = await db.get(Account, task.account_id)
        if account and account.project_id != task.project_id:
            return
        if not account:
            return
        await mass_react_for_account(
            account,
            task.get_channels(),
            task.get_reactions(),
            task.id,
            posts_limit=task.posts_per_channel,
            max_reactions=task.reactions_per_day,
        )
