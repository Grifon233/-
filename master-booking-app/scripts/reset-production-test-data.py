"""Remove real test accounts while preserving the read-only architect demo."""
import asyncio
import logging
import os
import sys
from pathlib import Path

from sqlalchemy import delete, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from architect.services.bot_manager import bot_manager
from backend.database import (
    ArchitectFunnelEvent,
    BlockedTime,
    Booking,
    BookingStatusHistory,
    Client,
    ClientProfile,
    Master,
    MasterBot,
    MenuButton,
    ReferralApplication,
    ReferralCode,
    Service,
    ShortUrl,
    SlotHold,
    Subscription,
    async_session_maker,
    ensure_demo_content,
    get_demo_master,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    allow_paid_delete = os.getenv("ALLOW_DELETE_PAID_BOTS") == "YES"
    async with async_session_maker() as db:
        paid_telegram_ids = set((await db.execute(
            select(Subscription.master_telegram_id).where(Subscription.status == "active")
        )).scalars().all())
        telegram_ids = set((await db.execute(
            select(Master.telegram_id).where(
                Master.is_demo == False,
                Master.telegram_id.isnot(None),
            )
        )).scalars().all())
        telegram_ids.update((await db.execute(
            select(MasterBot.master_telegram_id)
        )).scalars().all())

    deleted_accounts = 0
    for telegram_id in telegram_ids:
        if telegram_id in paid_telegram_ids and not allow_paid_delete:
            logger.warning(
                "Skip paid account %s. Set ALLOW_DELETE_PAID_BOTS=YES only for a deliberate full wipe.",
                telegram_id,
            )
            continue
        if await bot_manager.delete_master_account(telegram_id):
            deleted_accounts += 1

    async with async_session_maker() as db:
        orphan_masters = (await db.execute(
            select(Master).where(Master.is_demo == False)
        )).scalars().all()
        for master in orphan_masters:
            if master.telegram_id in paid_telegram_ids and not allow_paid_delete:
                logger.warning("Skip paid orphan master %s", master.telegram_id)
                continue
            booking_ids = select(Booking.id).where(Booking.master_id == master.id)
            await db.execute(delete(BookingStatusHistory).where(BookingStatusHistory.booking_id.in_(booking_ids)))
            await db.execute(delete(SlotHold).where(SlotHold.master_id == master.id))
            await db.execute(delete(Booking).where(Booking.master_id == master.id))
            await db.execute(delete(Client).where(Client.master_id == master.id))
            await db.execute(delete(Service).where(Service.master_id == master.id))
            await db.execute(delete(MenuButton).where(MenuButton.master_id == master.id))
            await db.execute(delete(BlockedTime).where(BlockedTime.master_id == master.id))
            await db.delete(master)
        await db.execute(delete(ClientProfile))
        await db.execute(delete(ShortUrl))
        await db.execute(delete(ReferralApplication))
        await db.execute(delete(ReferralCode))
        await db.execute(delete(ArchitectFunnelEvent))
        demo_master = await get_demo_master(db)
        await ensure_demo_content(db, demo_master)
        await db.commit()

    logger.info(
        "Reset complete: deleted %s real account(s); preserved architect demo",
        deleted_accounts,
    )


if __name__ == "__main__":
    asyncio.run(main())
