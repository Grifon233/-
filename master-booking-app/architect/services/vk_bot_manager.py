"""Управление VK-ботами мастеров из Архитектора.

VK-бот привязывается к тому же профилю Master, что и Telegram-бот владельца,
поэтому меню, услуги и расписание у обоих каналов общие.
"""
import logging

from sqlalchemy import select

from backend.database import async_session_maker, Master, MasterBot, VkBot
from backend.token_utils import encrypt_token, decrypt_token
from backend.vk import api

logger = logging.getLogger(__name__)


class VkBotManager:
    async def create_vk_bot(
        self,
        master_telegram_id: int,
        token: str,
        master_bot_id: int | None = None,
    ) -> dict:
        """Проверяет ключ сообщества и поднимает VK-бота для мастера."""
        import asyncio
        # validate_community_token уже вызывает setLongPollSettings внутри —
        # повторный вызов ensure_long_poll_enabled не нужен
        info = await api.validate_community_token(token)  # бросает ValueError с понятным текстом
        group_id = info["group_id"]
        group_name = info["group_name"]

        # get_creator_id и DB-операции независимы — запускаем параллельно
        creator_task = (
            None
            if master_telegram_id < 0
            else asyncio.ensure_future(api.get_creator_id(token, group_id))
        )

        async with async_session_maker() as session:
            query = select(MasterBot).where(
                MasterBot.master_telegram_id == master_telegram_id,
                MasterBot.status == "running",
            )
            if master_bot_id:
                query = query.where(MasterBot.id == master_bot_id)
            result = await session.execute(
                query.order_by(MasterBot.created_at.desc(), MasterBot.id.desc())
            )
            telegram_bot = result.scalars().first()
            if master_bot_id and not telegram_bot:
                raise ValueError("Выбранный Telegram-бот не найден")
            owner_master = await session.get(Master, telegram_bot.master_id) if telegram_bot and telegram_bot.master_id else None
            if not owner_master:
                result = await session.execute(select(Master).where(Master.telegram_id == master_telegram_id))
                owner_master = result.scalar_one_or_none()
            if not owner_master:
                if creator_task:
                    creator_task.cancel()
                raise ValueError("Сначала создайте Telegram-бота, затем привязывайте ВКонтакте.")

            result = await session.execute(
                select(VkBot).where(VkBot.master_telegram_id == master_telegram_id)
            )
            existing = result.scalars().all()
            vk_bot = next((b for b in existing if b.group_id == group_id), None)

            if master_telegram_id < 0:
                owner_vk_id = -master_telegram_id
            else:
                try:
                    owner_vk_id = await asyncio.wait_for(creator_task, timeout=5.0)
                except Exception:
                    owner_vk_id = None

            if vk_bot:
                vk_bot.token = encrypt_token(token)
                vk_bot.group_name = group_name
                vk_bot.master_id = owner_master.id
                vk_bot.owner_vk_id = owner_vk_id or vk_bot.owner_vk_id
                vk_bot.status = "running"
            else:
                vk_bot = VkBot(
                    master_id=owner_master.id,
                    master_telegram_id=master_telegram_id,
                    token=encrypt_token(token),
                    group_id=group_id,
                    group_name=group_name,
                    owner_vk_id=owner_vk_id,
                    status="running",
                )
                session.add(vk_bot)
            await session.commit()
            await session.refresh(vk_bot)

        return {"vk_bot_id": vk_bot.id, "group_id": group_id, "group_name": group_name}

    async def get_vk_bot(self, master_telegram_id: int) -> dict | None:
        async with async_session_maker() as session:
            result = await session.execute(
                select(VkBot).where(VkBot.master_telegram_id == master_telegram_id)
            )
            vk_bot = result.scalars().first()
            if not vk_bot:
                return None
            return {
                "vk_bot_id": vk_bot.id,
                "group_id": vk_bot.group_id,
                "group_name": vk_bot.group_name,
                "status": vk_bot.status,
            }

    async def get_unlinked_telegram_bots(self, master_telegram_id: int) -> list[dict]:
        async with async_session_maker() as session:
            rows = (await session.execute(
                select(MasterBot)
                .where(
                    MasterBot.master_telegram_id == master_telegram_id,
                    MasterBot.status == "running",
                )
                .order_by(MasterBot.created_at, MasterBot.id)
            )).scalars().all()
            linked_master_ids = set((await session.execute(
                select(VkBot.master_id).where(
                    VkBot.master_telegram_id == master_telegram_id,
                    VkBot.status == "running",
                )
            )).scalars().all())
            return [
                {"id": bot.id, "username": bot.username or f"Бот {bot.id}", "master_id": bot.master_id}
                for bot in rows
                if bot.master_id not in linked_master_ids
            ]

    async def delete_vk_bot(
        self,
        master_telegram_id: int,
        vk_bot_id: int | None = None,
        master_id: int | None = None,
    ) -> bool:
        async with async_session_maker() as session:
            query = select(VkBot).where(
                VkBot.master_telegram_id == master_telegram_id,
                VkBot.bot_type == "client",
            )
            if vk_bot_id is not None:
                query = query.where(VkBot.id == vk_bot_id)
            if master_id is not None:
                query = query.where(VkBot.master_id == master_id)
            result = await session.execute(query)
            bots = result.scalars().all()
            if not bots:
                return False
            for bot in bots:
                await session.delete(bot)
            await session.commit()
        return True


vk_bot_manager = VkBotManager()
