from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import (
    ArchitectFunnelEvent,
    BlockedTime,
    Booking,
    BookingStatusHistory,
    Client,
    Master,
    MasterBot,
    MasterVkProfile,
    MenuButton,
    ReferralApplication,
    Service,
    SlotHold,
    Subscription,
    VkBot,
)


async def delete_master_bot_data(db: AsyncSession, bot: MasterBot) -> None:
    """Delete a bot while preserving historical bookings and funnel events."""
    subscription_ids = select(Subscription.id).where(Subscription.master_bot_id == bot.id)
    await db.execute(
        update(ReferralApplication)
        .where(ReferralApplication.subscription_id.in_(subscription_ids))
        .values(subscription_id=None)
    )
    await db.execute(
        update(Booking)
        .where(Booking.master_bot_id == bot.id)
        .values(master_bot_id=None)
    )
    await db.execute(
        update(ArchitectFunnelEvent)
        .where(ArchitectFunnelEvent.master_bot_id == bot.id)
        .values(master_bot_id=None)
    )
    await db.execute(delete(Subscription).where(Subscription.master_bot_id == bot.id))
    await db.delete(bot)


async def delete_master_profile_data(db: AsyncSession, master: Master) -> None:
    """Delete one working profile and all profile-owned data in FK-safe order."""
    bots = list((await db.execute(
        select(MasterBot).where(MasterBot.master_id == master.id)
    )).scalars().all())
    for bot in bots:
        await delete_master_bot_data(db, bot)

    await db.execute(delete(VkBot).where(VkBot.master_id == master.id))
    await db.execute(delete(MasterVkProfile).where(MasterVkProfile.master_id == master.id))

    booking_ids = select(Booking.id).where(Booking.master_id == master.id)
    await db.execute(
        delete(BookingStatusHistory).where(BookingStatusHistory.booking_id.in_(booking_ids))
    )
    await db.execute(delete(SlotHold).where(SlotHold.master_id == master.id))
    await db.execute(delete(Booking).where(Booking.master_id == master.id))
    await db.execute(delete(Client).where(Client.master_id == master.id))
    await db.execute(delete(Service).where(Service.master_id == master.id))
    await db.execute(delete(MenuButton).where(MenuButton.master_id == master.id))
    await db.execute(delete(BlockedTime).where(BlockedTime.master_id == master.id))
    await db.delete(master)


async def delete_master_account_data(db: AsyncSession, owner_telegram_id: int) -> bool:
    bots = list((await db.execute(
        select(MasterBot).where(MasterBot.master_telegram_id == owner_telegram_id)
    )).scalars().all())
    master_ids = {bot.master_id for bot in bots if bot.master_id}
    owner_masters = list((await db.execute(
        select(Master).where(Master.telegram_id == owner_telegram_id)
    )).scalars().all())
    master_ids.update(master.id for master in owner_masters)

    if not bots and not master_ids:
        return False

    for bot in bots:
        await delete_master_bot_data(db, bot)

    masters = list((await db.execute(
        select(Master).where(Master.id.in_(master_ids))
    )).scalars().all()) if master_ids else []
    for master in masters:
        await delete_master_profile_data(db, master)

    remaining_subscription_ids = select(Subscription.id).where(
        Subscription.master_telegram_id == owner_telegram_id
    )
    await db.execute(
        update(ReferralApplication)
        .where(ReferralApplication.subscription_id.in_(remaining_subscription_ids))
        .values(subscription_id=None)
    )
    await db.execute(
        delete(Subscription).where(Subscription.master_telegram_id == owner_telegram_id)
    )
    return True
