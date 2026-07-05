"""LIVE E2E: create a neuro-commenting task, run it (auto-publish), verify.

Posts ONE real comment from account id=11 (+8647164611) into the
narashivanie_resnic_chat group, then reads it back and confirms the
account's profile exposes a personal-channel link.

All Telegram access goes through the account's bound proxy (the shared
pool enforces assert_proxy_bound).
"""
import asyncio

from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.db.session import SessionLocal
from app.models.account import Account
from app.models.comment_task import (
    CommentTask, CommentTaskStatus, CommentPolicy, CommentTargetMode, CommentDraft, CommentLog,
)
from app.services.telegram_service import telegram_service
from app.tasks.commenting import _run_neuro_commenting_task, telegram_chat_target

ACCOUNT_ID = 11           # +8647164611 (has personal channel + avatar)
SOURCE_ID = 476           # narashivanie_resnic_chat (real conversation)


async def preflight():
    async with SessionLocal() as db:
        acc = (await db.execute(
            select(Account).options(selectinload(Account.proxy)).where(Account.id == ACCOUNT_ID)
        )).scalar_one_or_none()
        print(f"account #{acc.id} {acc.phone_number} status={acc.status} proxy={acc.proxy_id} "
              f"proxy_active={getattr(acc.proxy,'is_active',None)} "
              f"pchan={acc.personal_channel_id} pchan_user={acc.personal_channel_username}")
        if not acc.proxy_id:
            raise SystemExit("REFUSE: account has no proxy bound")
        client = await asyncio.wait_for(telegram_service.get_client(acc), timeout=60)
        me = await client.get_me()
        full = await client.get_users(me.id)
        pc = getattr(full, "personal_channel_id", None)
        print(f"connected via proxy: id={me.id} name={me.first_name} username={me.username}")
        print(f"profile personal_channel_id (live from Telegram): {pc}")
        return pc


async def create_task():
    async with SessionLocal() as db:
        task = CommentTask(
            name="E2E neuro-commenting (account 11)",
            project_id=1,
            status=CommentTaskStatus.DRAFT,
            policy=CommentPolicy.AUTO_PUBLISH,
            source_ids=[SOURCE_ID],
            target_mode=CommentTargetMode.GROUP_CONTEXT,
            target_modes=["channel_posts", "group_context"],
            account_ids=[ACCOUNT_ID],
            comments_per_account=10,
            comments_per_source=1,
            provider="deepseek",
            model="deepseek-v4-flash",
            topic="наращивание ресниц, бьюти-мастера",
            min_delay=60,
            max_delay=180,
            moderation_enabled=True,
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)
        print(f"created task #{task.id}")
        return task.id


async def report(task_id, pc_before):
    async with SessionLocal() as db:
        task = await db.get(CommentTask, task_id)
        print(f"\nTASK #{task_id} status={task.status} posts_checked={task.posts_checked} "
              f"drafts={task.drafts_created} posted={task.comments_posted} errors={task.errors_count}")
        drafts = (await db.execute(
            select(CommentDraft).where(CommentDraft.task_id == task_id)
        )).scalars().all()
        published = None
        for d in drafts:
            print(f"  draft#{d.id} status={d.status} pub_msg={d.published_message_id} "
                  f"err={d.error_message}")
            print(f"    draft_text: {d.draft_text!r}")
            if d.published_message_id:
                published = d
        print("  --- logs ---")
        for lg in (await db.execute(
            select(CommentLog).where(CommentLog.task_id == task_id).order_by(CommentLog.id)
        )).scalars().all():
            print(f"    [{lg.action}] err={lg.error_message} details={lg.details}")

        # Verify the published message is actually visible in the group.
        if published:
            acc = (await db.execute(
                select(Account).options(selectinload(Account.proxy)).where(Account.id == ACCOUNT_ID)
            )).scalar_one()
            client = await telegram_service.get_client(acc)
            target = telegram_chat_target(await db.get(__import__("app.models.telegram_source", fromlist=["TelegramSource"]).TelegramSource, SOURCE_ID))
            try:
                msg = await client.get_messages(target, published.published_message_id)
                print(f"\nVERIFIED IN GROUP: message id={msg.id} from={getattr(msg.from_user,'username',None)} "
                      f"text={msg.text!r} link=https://t.me/{target}/{msg.id}")
            except Exception as e:
                print("could not read back message:", repr(e))
        print(f"\nprofile personal_channel_id before run: {pc_before}")


async def main():
    pc = await preflight()
    task_id = await create_task()
    print("\n--- running task (this sleeps for rate-limit min_delay, can take a few minutes) ---")
    await _run_neuro_commenting_task(task_id)
    await report(task_id, pc)


if __name__ == "__main__":
    asyncio.run(main())
