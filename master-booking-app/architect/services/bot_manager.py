import asyncio
import logging
import os
from datetime import datetime
from typing import Optional

import httpx
from sqlalchemy import delete, select, update

from backend.database import (
    Booking,
    BookingStatusHistory,
    BlockedTime,
    Client,
    Master,
    MasterBot,
    MenuButton,
    Service,
    SlotHold,
    Subscription,
    VkBot,
    async_session_maker,
)
from backend.config import get_webhook_url
from backend.token_utils import encrypt_token, decrypt_token, mask_token
from architect.config import settings
from architect.services.funnel_events import record_funnel_event
from backend.services.data_deletion import delete_master_account_data, delete_master_bot_data

logger = logging.getLogger(__name__)


class BotManager:
    """Управление ботами мастеров через исходящий Telegram polling."""

    WEBHOOK_ALLOWED_UPDATES = ["message", "callback_query"]
    WEBHOOK_REQUEST_TIMEOUT = 20

    @staticmethod
    def _proxy_url() -> str | None:
        return os.getenv("HTTPS_PROXY") or os.getenv("https_proxy") or settings.proxy_url

    async def set_webhook_for_bot(self, raw_token: str) -> bool:
        """Устанавливает webhook для бота на основном сервере"""
        ok, error = await self.configure_webhook_for_bot(raw_token)
        if not ok:
            logger.error("Failed to set webhook for %s: %s", mask_token(raw_token), error)
        return ok

    async def configure_webhook_for_bot(self, raw_token: str) -> tuple[bool, Optional[str]]:
        """Prepare delivery for a master bot according to MASTER_BOT_DELIVERY."""
        from aiogram import Bot
        from aiogram.client.session.aiohttp import AiohttpSession

        proxy_url = self._proxy_url()
        session = AiohttpSession(proxy=proxy_url) if proxy_url else AiohttpSession()
        bot = Bot(token=raw_token, session=session)
        try:
            if os.getenv("MASTER_BOT_DELIVERY", "polling").lower() in {"webhook", "webhooks"}:
                await asyncio.wait_for(
                    bot.set_webhook(
                        get_webhook_url(raw_token),
                        allowed_updates=self.WEBHOOK_ALLOWED_UPDATES,
                        drop_pending_updates=False,
                        request_timeout=self.WEBHOOK_REQUEST_TIMEOUT,
                    ),
                    timeout=self.WEBHOOK_REQUEST_TIMEOUT + 2,
                )
                logger.info("Bot %s prepared for webhook", mask_token(raw_token))
                return True, None

            await asyncio.wait_for(
                bot.delete_webhook(
                    drop_pending_updates=False,
                    request_timeout=self.WEBHOOK_REQUEST_TIMEOUT,
                ),
                timeout=self.WEBHOOK_REQUEST_TIMEOUT + 2,
            )
            logger.info("Bot %s prepared for polling", mask_token(raw_token))
            return True, None

        except Exception as e:
            return False, str(e) or e.__class__.__name__
        finally:
            await bot.session.close()

    async def validate_token(self, token: str) -> tuple[bool, Optional[str]]:
        """Проверяет валидность токена через Telegram API (с прокси)"""
        proxy_url = self._proxy_url()
        client_kwargs = {"timeout": 8.0}
        if proxy_url:
            # HTTPX uses `proxy=...`; `proxies=...` raises TypeError on current versions.
            client_kwargs["proxy"] = proxy_url
        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                response = await client.get(
                    f"https://api.telegram.org/bot{token}/getMe"
                )
                data = response.json()
                if data.get("ok"):
                    username = data["result"].get("username", "")
                    return True, username
                logger.warning(
                    "Token validation rejected by Telegram for %s: %s",
                    mask_token(token),
                    data.get("description") or response.status_code,
                )
                return False, None
        except Exception as e:
            logger.error(f"Token validation failed for {mask_token(token)}: {e}")
            return False, None

    def _raw_token(self, bot) -> str:
        """Получить расшифрованный токен из объекта MasterBot."""
        return decrypt_token(bot.token)

    async def _reset_master_profile_for_new_bot(self, session, master: Master, master_name: str | None = None) -> None:
        """Clear stale settings before reusing an owner profile for a fresh bot."""
        booking_ids = select(Booking.id).where(Booking.master_id == master.id)
        await session.execute(delete(BookingStatusHistory).where(BookingStatusHistory.booking_id.in_(booking_ids)))
        await session.execute(delete(SlotHold).where(SlotHold.master_id == master.id))
        await session.execute(delete(Booking).where(Booking.master_id == master.id))
        await session.execute(delete(Client).where(Client.master_id == master.id))
        await session.execute(delete(Service).where(Service.master_id == master.id))
        await session.execute(delete(MenuButton).where(MenuButton.master_id == master.id))
        await session.execute(delete(BlockedTime).where(BlockedTime.master_id == master.id))

        if master_name:
            master.name = master_name
        master.avatar_url = None
        master.use_services = False
        master.interval_minutes = 60
        master.schedule_json = None
        master.subscription_required = False
        master.subscription_channel_id = None
        master.subscription_channel_name = None
        master.subscription_text = None
        master.notify_new_bookings = True
        # По умолчанию — включено, как в схеме БД и как показывает веб-интерфейс.
        # Раньше здесь стояло False → мастер видел галочку «вкл», а напоминания молчали.
        master.notify_reminders = True
        master.reminder_time = "18:00"
        master.weekly_report_enabled = False
        master.weekly_report_sent_at = None
        master.timezone = "Europe/Moscow"
        master.profile_link_warning_dismissed = False

    async def create_bot(
        self,
        master_telegram_id: int,
        token: str,
        master_name: str = None,
        profile_master_id: int | None = None,
    ) -> dict:
        """Создаёт и запускает бота для мастера"""
        # Валидация токена
        valid, username = await self.validate_token(token)
        if not valid:
            raise ValueError("Неверный токен бота")

        # Один мастер может подключить несколько ботов. Повторная отправка
        # того же токена обновляет существующую запись, новый токен создаёт новую.
        async with async_session_maker() as session:
            created_new = False
            existing = await session.execute(
                select(MasterBot).where(MasterBot.master_telegram_id == master_telegram_id)
            )
            existing_bots = existing.scalars().all()
            bot = next((item for item in existing_bots if self._raw_token(item) == token), None)

            if bot:
                # Обновляем токен (с шифрованием). Отсчёт триала НЕ сбрасываем:
                # иначе повторной отправкой того же токена каждые 2 часа можно было
                # бесконечно продлевать бесплатный тестовый период.
                bot.token = encrypt_token(token)
                bot.username = username
                bot.status = "creating"
                if bot.trial_started_at is None:
                    bot.trial_started_at = bot.created_at or datetime.utcnow()
            else:
                # Создаём owner-master если его нет. Первый бот использует его как профиль,
                # каждый следующий получает отдельный профиль с теми же базовыми настройками.
                owner_master = await session.get(Master, profile_master_id) if profile_master_id else None
                if owner_master and not (
                    owner_master.telegram_id in {None, master_telegram_id}
                    or master_telegram_id < 0
                ):
                    raise ValueError("Выбранный профиль не принадлежит этому аккаунту")
                if not owner_master:
                    master_result = await session.execute(
                        select(Master).where(Master.telegram_id == master_telegram_id)
                    )
                    owner_master = master_result.scalar_one_or_none()
                if not owner_master:
                    # Используем имя мастера если передано, иначе "Мастер"
                    name = master_name if master_name else "Мастер"
                    owner_master = Master(
                        telegram_id=master_telegram_id,
                        name=name,
                        is_demo=False,
                        use_services=False,
                        interval_minutes=60,
                    )
                    session.add(owner_master)
                    await session.flush()
                elif not existing_bots:
                    await self._reset_master_profile_for_new_bot(session, owner_master, master_name)

                if profile_master_id:
                    profile_master = owner_master
                elif existing_bots:
                    profile_master = Master(
                        name=owner_master.name,
                        avatar_url=None,
                        telegram_id=None,
                        telegram_username=owner_master.telegram_username,
                        subscription_channel_id=None,
                        subscription_channel_name=None,
                        subscription_text=None,
                        subscription_required=False,
                        # Each additional bot gets its own clean working profile.
                        # Reusing schedule/services from the first bot makes a new bot
                        # look preconfigured and confuses the owner.
                        use_services=False,
                        interval_minutes=60,
                        schedule_json=None,
                        is_demo=False,
                        notify_new_bookings=True,
                        notify_reminders=True,
                        reminder_time="18:00",
                        weekly_report_enabled=False,
                        weekly_report_sent_at=None,
                        timezone="Europe/Moscow",
                    )
                    session.add(profile_master)
                    await session.flush()
                else:
                    profile_master = owner_master

                # Создаём нового бота (с шифрованием токена)
                bot = MasterBot(
                    master_id=profile_master.id,
                    master_telegram_id=master_telegram_id,
                    token=encrypt_token(token),
                    username=username,
                    status="creating",
                    trial_started_at=datetime.utcnow(),
                )
                session.add(bot)
                created_new = True

            await session.commit()
            await session.refresh(bot)
            created_bot_id = bot.id

        # Снимаем webhook: backend supervisor подключит бота через polling.
        success, webhook_error = await self.configure_webhook_for_bot(token)

        # Running bots автоматически подхватываются backend polling supervisor.
        async with async_session_maker() as session:
            await session.execute(
                update(MasterBot)
                .where(MasterBot.id == bot.id)
                .values(status="running" if success else "error")
            )
            await session.commit()

        if not success:
            raise ValueError(
                "Токен верный, но webhook не установился. "
                "Проверьте, что WEBHOOK_BASE_URL ведёт на FastAPI, где доступен POST /api/webhook/{token}. "
                f"Детали Telegram: {webhook_error or 'unknown'}"
            )

        if created_new:
            await record_funnel_event(
                "bot_created",
                master_telegram_id,
                created_bot_id,
                {"username": username},
            )

        return {
            "bot_id": bot.id,
            "username": f"@{username}",
            "status": "running"
        }

    async def freeze_bot(self, master_telegram_id: int, bot_id: int | None = None) -> bool:
        """Замораживает Telegram- и VK-ботов выбранного профиля."""
        async with async_session_maker() as session:
            query = select(MasterBot).where(MasterBot.master_telegram_id == master_telegram_id)
            if bot_id:
                query = query.where(MasterBot.id == bot_id)
            result = await session.execute(query)
            bots = result.scalars().all()
            master_ids = {bot.master_id for bot in bots if bot.master_id}

            from aiogram import Bot
            from aiogram.client.session.aiohttp import AiohttpSession

            for bot in bots:
                proxy_url = self._proxy_url()
                aio_session = AiohttpSession(proxy=proxy_url) if proxy_url else AiohttpSession()
                bot_aiogram = Bot(token=self._raw_token(bot), session=aio_session)
                try:
                    await bot_aiogram.delete_webhook()
                except Exception as e:
                    logger.warning("Failed to delete webhook for bot %s: %s", bot.id, e)
                finally:
                    await bot_aiogram.session.close()
                bot.status = "frozen"

            vk_query = update(VkBot).where(VkBot.master_telegram_id == master_telegram_id)
            if bot_id:
                if master_ids:
                    vk_query = vk_query.where(VkBot.master_id.in_(master_ids))
                else:
                    vk_query = vk_query.where(False)
            vk_result = await session.execute(vk_query.values(status="frozen"))
            await session.commit()
            changed = bool(bots) or bool(vk_result.rowcount)
            if changed:
                logger.info("Bots frozen for master %s (telegram=%s, vk=%s)", master_telegram_id, len(bots), vk_result.rowcount)

        return changed

    async def unfreeze_bot(self, master_telegram_id: int, bot_id: int | None = None) -> bool:
        """Размораживает Telegram- и VK-ботов выбранного профиля."""
        async with async_session_maker() as session:
            query = select(MasterBot).where(MasterBot.master_telegram_id == master_telegram_id)
            if bot_id:
                query = query.where(MasterBot.id == bot_id)
            result = await session.execute(query)
            bots = result.scalars().all()
            master_ids = {bot.master_id for bot in bots if bot.master_id}
            telegram_success = True
            for bot in bots:
                success = await self.set_webhook_for_bot(self._raw_token(bot))
                bot.status = "running" if success else "error"
                telegram_success = telegram_success and success

            vk_query = update(VkBot).where(VkBot.master_telegram_id == master_telegram_id)
            if bot_id:
                if master_ids:
                    vk_query = vk_query.where(VkBot.master_id.in_(master_ids))
                else:
                    vk_query = vk_query.where(False)
            vk_result = await session.execute(vk_query.values(status="running"))
            await session.commit()
            changed = bool(bots) or bool(vk_result.rowcount)
            if changed:
                logger.info(
                    "Bots unfrozen for master %s (telegram=%s, vk=%s)",
                    master_telegram_id,
                    len(bots),
                    vk_result.rowcount,
                )

        return changed and telegram_success

    async def check_subscription_and_freeze(self, master_telegram_id: int) -> tuple[bool, Optional[int]]:
        """
        Проверяет подписку и замораживает/размораживает бота.
        Returns: (is_active, days_left)
        """
        from datetime import timedelta
        from sqlalchemy import and_

        async with async_session_maker() as session:
            from backend.database import Subscription, Master

            # Получаем мастера
            master_result = await session.execute(
                select(Master).where(Master.telegram_id == master_telegram_id)
            )
            master = master_result.scalar_one_or_none()

            # Если подписка не требуется
            if not master or not master.subscription_required:
                return True, None

            # Получаем активную подписку
            sub_result = await session.execute(
                select(Subscription).where(
                    and_(
                        Subscription.master_telegram_id == master_telegram_id,
                        Subscription.status == "active"
                    )
                ).order_by(Subscription.created_at.desc())
            )
            subscription = sub_result.scalars().first()

            # Проверяем срок
            if subscription and subscription.lifetime:
                await self.unfreeze_bot(master_telegram_id)
                return True, None
            if subscription and subscription.paid_at:
                expiry = subscription.paid_at + timedelta(days=subscription.period_days)
                now = datetime.now()

                if now < expiry:
                    days_left = (expiry.date() - now.date()).days
                    # Размораживаем если нужно
                    await self.unfreeze_bot(master_telegram_id)
                    return True, days_left
                else:
                    # Замораживаем
                    await self.freeze_bot(master_telegram_id)
                    return False, 0
            else:
                # Нет подписки - замораживаем
                await self.freeze_bot(master_telegram_id)
                return False, 0

    async def stop_bot(self, master_telegram_id: int, bot_id: int | None = None) -> bool:
        """Останавливает бота мастера (удаляет webhook).

        bot_id позволяет указать конкретного бота — у мастера их может быть
        несколько, иначе останавливался «первый попавшийся».
        """
        async with async_session_maker() as session:
            query = select(MasterBot).where(MasterBot.master_telegram_id == master_telegram_id)
            if bot_id is not None:
                query = query.where(MasterBot.id == bot_id)
            result = await session.execute(query.order_by(MasterBot.id))
            bot = result.scalars().first()

            if not bot:
                return False

            # Удаляем webhook
            from aiogram import Bot
            from aiogram.client.session.aiohttp import AiohttpSession

            proxy_url = self._proxy_url()
            session_aiogram = AiohttpSession(proxy=proxy_url) if proxy_url else AiohttpSession()
            raw = self._raw_token(bot)
            bot_aiogram = Bot(token=raw, session=session_aiogram)

            try:
                await bot_aiogram.delete_webhook()
            except Exception as e:
                logger.warning(f"Failed to delete webhook for bot {bot.id}: {e}")
            finally:
                await bot_aiogram.session.close()

            # Обновляем статус
            bot.status = "stopped"
            await session.commit()

        return True

    async def delete_bot(self, master_telegram_id: int, bot_id: int | None = None) -> bool:
        """Удаляет бота мастера из Architect и снимает webhook.

        Профиль мастера, клиенты и записи не удаляются — удаляется только строка MasterBot.
        """
        async with async_session_maker() as session:
            query = select(MasterBot).where(MasterBot.master_telegram_id == master_telegram_id)
            if bot_id is not None:
                query = query.where(MasterBot.id == bot_id)
            result = await session.execute(query)
            bot = result.scalars().first()

            if not bot:
                return False

            from aiogram import Bot
            from aiogram.client.session.aiohttp import AiohttpSession

            proxy_url = self._proxy_url()
            session_aiogram = AiohttpSession(proxy=proxy_url) if proxy_url else AiohttpSession()
            raw = self._raw_token(bot)
            bot_aiogram = Bot(token=raw, session=session_aiogram)

            try:
                await bot_aiogram.delete_webhook(drop_pending_updates=True)
            except Exception as e:
                logger.warning(f"Failed to delete webhook for bot {bot.id}: {e}")
            finally:
                await bot_aiogram.session.close()

            bot_id = bot.id
            await delete_master_bot_data(session, bot)
            await session.commit()
            logger.info(f"Bot {bot_id} deleted for master {master_telegram_id}")

        return True

    async def delete_master_account(self, master_telegram_id: int) -> bool:
        """Delete every bot and all master-owned booking data.

        ClientProfile stays intact because it is a verified global identity shared
        with other masters.
        """
        async with async_session_maker() as session:
            bots = (await session.execute(
                select(MasterBot).where(MasterBot.master_telegram_id == master_telegram_id)
            )).scalars().all()
            if not bots and not (await session.execute(
                select(Master.id).where(Master.telegram_id == master_telegram_id)
            )).scalars().first():
                return False

            from aiogram import Bot
            from aiogram.client.session.aiohttp import AiohttpSession

            for bot in bots:
                proxy_url = self._proxy_url()
                telegram_session = AiohttpSession(proxy=proxy_url) if proxy_url else AiohttpSession()
                telegram_bot = None
                try:
                    telegram_bot = Bot(token=self._raw_token(bot), session=telegram_session)
                    await telegram_bot.delete_webhook(drop_pending_updates=True)
                except Exception as exc:
                    logger.warning("Failed to delete webhook for bot %s: %s", bot.id, exc)
                finally:
                    if telegram_bot:
                        await telegram_bot.session.close()
                    else:
                        await telegram_session.close()

            await delete_master_account_data(session, master_telegram_id)
            await session.commit()
            logger.info("Deleted master account and owned data for %s", master_telegram_id)
        return True

    async def restart_bot(self, master_telegram_id: int, bot_id: int | None = None) -> dict:
        """Перезапускает бота мастера"""
        await self.stop_bot(master_telegram_id, bot_id)

        async with async_session_maker() as session:
            query = select(MasterBot).where(MasterBot.master_telegram_id == master_telegram_id)
            if bot_id is not None:
                query = query.where(MasterBot.id == bot_id)
            result = await session.execute(query.order_by(MasterBot.id))
            bot = result.scalars().first()

            if not bot:
                raise ValueError("Бот не найден")

            return await self.create_bot(master_telegram_id, self._raw_token(bot))

    async def get_bot_status(self, master_telegram_id: int, bot_id: int | None = None) -> Optional[dict]:
        """Проверяет статус бота мастера"""
        async with async_session_maker() as session:
            query = select(MasterBot).where(MasterBot.master_telegram_id == master_telegram_id)
            if bot_id is not None:
                query = query.where(MasterBot.id == bot_id)
            result = await session.execute(query.order_by(MasterBot.id))
            bot = result.scalars().first()

            if not bot:
                return None

            return {
                "bot_id": bot.id,
                "username": f"@{bot.username}" if bot.username else None,
                "status": bot.status,
                "created_at": bot.created_at.isoformat() if bot.created_at else None,
            }

    async def get_all_bots(self) -> list[dict]:
        """Возвращает список всех ботов"""
        async with async_session_maker() as session:
            result = await session.execute(select(MasterBot))
            bots = result.scalars().all()

            return [
                {
                    "bot_id": bot.id,
                    "master_telegram_id": bot.master_telegram_id,
                    "username": f"@{bot.username}" if bot.username else None,
                    "status": bot.status,
                    "created_at": bot.created_at.isoformat() if bot.created_at else None,
                }
                for bot in bots
            ]


# Глобальный экземпляр
bot_manager = BotManager()
