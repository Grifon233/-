"""
Сервис синхронизации статусов подписки и бота.
Вызывается из superadmin endpoints freeze/unfreeze/extend.
Порядок важен: для unfreeze сначала вызываем BotManager (пока статус frozen),
потом выставляем MasterBot.status = "running" или "error".
"""
import logging

from sqlalchemy import update

from backend.database import async_session_maker, MasterBot
from architect.services.bot_manager import bot_manager

logger = logging.getLogger(__name__)


class SubscriptionAdminService:
    """Синхронизация Subscription.status и MasterBot.status."""

    async def sync_status(self, master_telegram_id: int, target_status: str, master_bot_id: int | None = None) -> None:
        """
        Синхронизирует MasterBot.status с Subscription.status.
        Порядок для active: unfreeze_bot → running/error.
        Порядок для frozen:  freeze_bot → frozen.
        """
        if target_status == "frozen":
            # Сначала вызываем freeze_bot — он удалит webhook
            if master_bot_id is None:
                await bot_manager.freeze_bot(master_telegram_id)
            else:
                await bot_manager.freeze_bot(master_telegram_id, master_bot_id)
            # Потом убеждаемся что статус frozen (на случай если freeze_bot не нашёл запись)
            async with async_session_maker() as session:
                await session.execute(
                    update(MasterBot)
                    .where(MasterBot.master_telegram_id == master_telegram_id)
                    .where(MasterBot.id == master_bot_id if master_bot_id is not None else True)
                    .values(status="frozen")
                )
                await session.commit()
            logger.info(f"Forced MasterBot.status=frozen for {master_telegram_id}")

        elif target_status == "active":
            # Вызываем unfreeze_bot ПОКА статус ещё frozen (он проверяет bot.status == "frozen")
            if master_bot_id is None:
                success = await bot_manager.unfreeze_bot(master_telegram_id)
            else:
                success = await bot_manager.unfreeze_bot(master_telegram_id, master_bot_id)
            # После успеха/неудачи выставляем running или error
            async with async_session_maker() as session:
                await session.execute(
                    update(MasterBot)
                    .where(MasterBot.master_telegram_id == master_telegram_id)
                    .where(MasterBot.id == master_bot_id if master_bot_id is not None else True)
                    .values(status="running" if success else "error")
                )
                await session.commit()
            logger.info(f"Unfreeze for {master_telegram_id}: {'running' if success else 'error'}")

        else:
            raise ValueError(f"Unknown target_status: {target_status}")


subscription_admin_service = SubscriptionAdminService()
