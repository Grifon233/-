"""
Сервис уведомлений мастеру о новых записях.
Основан на документации aiogram: https://docs.aiogram.dev/en/latest/api/methods/send_message.html
"""
import logging
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import AiogramError

logger = logging.getLogger(__name__)


class NotificationService:
    """Отправка уведомлений мастеру через Telegram bot"""

    def __init__(self, bot_token: str):
        self.bot = Bot(token=bot_token)

    async def _check_bot_frozen(self, master_telegram_id: int) -> tuple[bool, Optional[dict]]:
        """
        Проверяет, заморожен ли бот мастера.

        Returns:
            (is_frozen, subscription_info)
        """
        from backend.database import async_session_maker, Subscription, Master, MasterBot
        from datetime import datetime, timedelta
        from sqlalchemy import select, and_

        async with async_session_maker() as db:
            # Получаем подписку мастера
            result = await db.execute(
                select(Subscription).where(
                    and_(
                        Subscription.master_telegram_id == master_telegram_id,
                        Subscription.status == "active"
                    )
                ).order_by(Subscription.created_at.desc())
            )
            subscription = result.scalar_one_or_none()

            # Проверяем активна ли подписка
            is_active = False
            days_left = 0

            if subscription and subscription.lifetime:
                is_active = True
                days_left = None
            elif subscription and subscription.paid_at:
                expiry = subscription.paid_at + timedelta(days=subscription.period_days)
                now = datetime.now()
                if now < expiry:
                    is_active = True
                    days_left = (expiry.date() - now.date()).days

            # Получаем статус бота
            bot_result = await db.execute(
                select(MasterBot).where(MasterBot.master_telegram_id == master_telegram_id)
            )
            bot = bot_result.scalar_one_or_none()

            # Если подписка не требуется - всегда активны
            master_result = await db.execute(
                select(Master).where(Master.telegram_id == master_telegram_id)
            )
            master = master_result.scalar_one_or_none()

            if master and not master.subscription_required:
                return False, {"subscription_required": False}

            # Если подписка требуется но неактивна или истекла - бот заморожен
            if master and master.subscription_required:
                if not is_active or not subscription:
                    return True, {"days_left": 0, "subscription_required": True}

            return False, {"days_left": days_left, "subscription_required": True}

    async def send_booking_notification(
        self,
        master_telegram_id: int,
        client_name: str,
        client_phone: str,
        client_username: Optional[str],
        service_name: str,
        date_str: str,
        time_str: str,
    ) -> bool:
        """
        Отправляет уведомление мастеру о новой записи.

        Формат сообщения:
        📋 Новая запись!

        👤 Фамилия Имя
        📱 +7XXXXXXXXXX
        💬 @username (кнопка-ссылка)
        📌 Услуга
        🗓 28 мая 2026, 14:00

        Args:
            master_telegram_id: Telegram ID мастера
            client_name: ФИ клиента
            client_phone: Телефон клиента
            client_username: Telegram username клиента
            service_name: Название услуги
            date_str: Дата записи
            time_str: Время записи

        Returns:
            True если отправлено успешно
        """
        # Проверяем заморожен ли бот
        is_frozen, sub_info = await self._check_bot_frozen(master_telegram_id)
        if is_frozen:
            logger.info(f"Skipping notification - bot is frozen for master {master_telegram_id}")
            return False

        # Проверяем включена ли подписка у мастера
        if sub_info.get("subscription_required"):
            days_left = sub_info.get("days_left", 0)

        # Формируем текст уведомления
        lines = [
            "📋 Новая запись!",
            "",
            f"👤 {client_name}",
            f"📱 {client_phone}",
        ]

        # Добавляем Telegram если есть
        if client_username:
            lines.append(f"💬 @{client_username}")

        lines.extend([
            f"📌 {service_name}",
            f"🗓 {date_str}, {time_str}",
        ])

        message_text = "\n".join(lines)

        # Формируем кнопку для быстрого перехода в чат
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

        keyboard = InlineKeyboardMarkup(inline_keyboard=[])
        if client_username:
            # Кнопка-ссылка на чат с клиентом
            chat_button = InlineKeyboardButton(
                text=f"💬 Чат с {client_name.split()[0] if client_name else 'клиентом'}",
                url=f"tg://resolve?domain={client_username}"
            )
            keyboard.inline_keyboard.append([chat_button])

        try:
            await self.bot.send_message(
                chat_id=master_telegram_id,
                text=message_text,
                reply_markup=keyboard,
            )
            logger.info(f"Notification sent to master {master_telegram_id} about booking")
            return True

        except AiogramError as e:
            logger.error(f"Failed to send notification: {e}")
            return False

    async def send_subscription_reminder(
        self,
        master_telegram_id: int,
        days_left: int,
        action_url: Optional[str] = None,
    ) -> bool:
        """Отправляет напоминание о подписке"""
        if days_left == 0:
            message = "⚠️ Подписка истекает сегодня!\n\nПродлите подписку чтобы бот продолжал работать."
        elif days_left == 1:
            message = "📅 Подписка истекает завтра!\n\nПродлите чтобы не прерывать работу."
        elif days_left == 3:
            message = "📅 Подписка истекает через 3 дня\n\nУспейте продлить!"
        else:
            message = f"📅 Подписка активна, осталось {days_left} дней."

        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

        keyboard = InlineKeyboardMarkup(inline_keyboard=[])
        if action_url:
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(text="💳 Продлить подписку", url=action_url)
            ])

        try:
            await self.bot.send_message(
                chat_id=master_telegram_id,
                text=message,
                reply_markup=keyboard,
            )
            return True
        except AiogramError as e:
            logger.error(f"Failed to send subscription reminder: {e}")
            return False

    async def send_freeze_notification(self, master_telegram_id: int) -> bool:
        """Уведомление о заморозке бота"""
        message = (
            "❄️ Ваш бот заморожен\n\n"
            "Подписка истекла. Для активации продлите подписку в Architect Bot.\n\n"
            "Клиенты смогут записываться, но уведомления не приходят."
        )

        try:
            await self.bot.send_message(
                chat_id=master_telegram_id,
                text=message,
            )
            return True
        except AiogramError as e:
            logger.error(f"Failed to send freeze notification: {e}")
            return False

    async def close(self):
        """Закрывает сессию бота"""
        await self.bot.session.close()


def create_notification_service(bot_token: str) -> NotificationService:
    """Factory для создания сервиса уведомлений"""
    return NotificationService(bot_token=bot_token)
