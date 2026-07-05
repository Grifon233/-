"""One-time linking of a VK Architect identity to a real Telegram account."""
import secrets
import time

from sqlalchemy import select, update

from backend.database import (
    Master,
    MasterBot,
    MasterVkProfile,
    Subscription,
    VkBot,
    async_session_maker,
)

LINK_TTL_SECONDS = 15 * 60


class AccountLinkService:
    async def create_master_bot_owner_link(self, vk_id: int, master_bot_id: int, username: str) -> str:
        code = secrets.token_urlsafe(24)
        async with async_session_maker() as session:
            profile = (await session.execute(
                select(MasterVkProfile).where(MasterVkProfile.vk_id == vk_id)
            )).scalar_one_or_none()
            bot = await session.get(MasterBot, master_bot_id)
            profile_owner_id = self.owner_id(profile) if profile else None
            if not profile or not bot or bot.master_telegram_id != profile_owner_id:
                raise ValueError("Не удалось подготовить подтверждение владельца")
            state_data = dict(profile.state_data_json or {})
            claims = dict(state_data.get("master_bot_owner_claims") or {})
            claims[code] = {
                "master_bot_id": master_bot_id,
                "expires_at": int(time.time()) + LINK_TTL_SECONDS,
            }
            state_data["master_bot_owner_claims"] = claims
            profile.state_data_json = state_data
            await session.commit()
        return f"https://t.me/{username}?start=owner_{code}"

    async def claim_master_bot_owner(self, code: str, telegram_id: int, token: str) -> bool:
        from backend.token_utils import decrypt_token

        if not code:
            return False
        async with async_session_maker() as session:
            profiles = (await session.execute(select(MasterVkProfile))).scalars().all()
            for profile in profiles:
                state_data = dict(profile.state_data_json or {})
                claims = dict(state_data.get("master_bot_owner_claims") or {})
                claim = claims.get(code)
                if not claim:
                    continue
                bot = await session.get(MasterBot, int(claim.get("master_bot_id") or 0))
                valid = (
                    int(claim.get("expires_at") or 0) >= int(time.time())
                    and bot is not None
                    and decrypt_token(bot.token) == token
                    and bot.master_telegram_id in {
                        profile.pseudo_telegram_id,
                        int(state_data.get("linked_telegram_id") or profile.pseudo_telegram_id),
                    }
                )
                claims.pop(code, None)
                state_data["master_bot_owner_claims"] = claims
                profile.state_data_json = state_data
                if not valid:
                    await session.commit()
                    return False

                old_owner_id = profile.pseudo_telegram_id
                bot.master_telegram_id = telegram_id
                await session.execute(
                    update(VkBot)
                    .where(VkBot.master_telegram_id == old_owner_id)
                    .values(master_telegram_id=telegram_id, owner_vk_id=profile.vk_id)
                )
                # Переносим подписки старого (псевдо-)владельца на реальный Telegram:
                # и привязанные к боту, и «общие» (master_bot_id IS NULL), оформленные
                # из ВКонтакте до привязки — иначе оплаченная подписка не видна в Telegram.
                await session.execute(
                    update(Subscription)
                    .where(Subscription.master_telegram_id == old_owner_id)
                    .values(master_telegram_id=telegram_id)
                )
                await session.execute(
                    update(Subscription)
                    .where(Subscription.master_bot_id == bot.id)
                    .values(master_telegram_id=telegram_id)
                )
                master = await session.get(Master, bot.master_id) if bot.master_id else None
                existing_master = (await session.execute(
                    select(Master).where(Master.telegram_id == telegram_id)
                )).scalar_one_or_none()
                if master and not existing_master:
                    master.telegram_id = telegram_id
                elif master and existing_master and master.id != existing_master.id:
                    master.telegram_id = None
                linked_pairs = list(state_data.get("linked_pairs") or [])
                linked_pairs.append({"master_bot_id": bot.id, "telegram_id": telegram_id})
                state_data["linked_pairs"] = linked_pairs
                state_data["linked_telegram_id"] = telegram_id
                profile.state_data_json = state_data
                await session.commit()
                return True
        return False

    async def create_telegram_link(self, vk_id: int) -> str:
        code = secrets.token_urlsafe(24)
        async with async_session_maker() as session:
            profile = (await session.execute(
                select(MasterVkProfile).where(MasterVkProfile.vk_id == vk_id)
            )).scalar_one_or_none()
            if not profile:
                raise ValueError("Профиль ВКонтакте не найден")
            state_data = dict(profile.state_data_json or {})
            state_data.update({
                "account_link_code": code,
                "account_link_expires_at": int(time.time()) + LINK_TTL_SECONDS,
            })
            profile.state_data_json = state_data
            await session.commit()
        return f"https://t.me/SoftwareArchitects_bot?start=linkvk_{code}"

    async def claim_telegram_link(self, code: str, telegram_id: int) -> bool:
        if not code:
            return False
        async with async_session_maker() as session:
            profiles = (await session.execute(select(MasterVkProfile))).scalars().all()
            profile = next(
                (
                    item for item in profiles
                    if (item.state_data_json or {}).get("account_link_code") == code
                ),
                None,
            )
            if not profile:
                return False
            state_data = dict(profile.state_data_json or {})
            if int(state_data.get("account_link_expires_at") or 0) < int(time.time()):
                state_data.pop("account_link_code", None)
                state_data.pop("account_link_expires_at", None)
                profile.state_data_json = state_data
                await session.commit()
                return False

            old_owner_id = profile.pseudo_telegram_id
            existing_master = (await session.execute(
                select(Master).where(Master.telegram_id == telegram_id)
            )).scalar_one_or_none()
            vk_master = await session.get(Master, profile.master_id) if profile.master_id else None

            if vk_master and not existing_master:
                vk_master.telegram_id = telegram_id
            elif vk_master and existing_master and vk_master.id != existing_master.id:
                vk_master.telegram_id = None

            await session.execute(
                update(MasterBot)
                .where(MasterBot.master_telegram_id == old_owner_id)
                .values(master_telegram_id=telegram_id)
            )
            await session.execute(
                update(VkBot)
                .where(VkBot.master_telegram_id == old_owner_id)
                .values(master_telegram_id=telegram_id, owner_vk_id=profile.vk_id)
            )
            await session.execute(
                update(VkBot)
                .where(VkBot.master_telegram_id == telegram_id)
                .values(owner_vk_id=profile.vk_id)
            )
            await session.execute(
                update(Subscription)
                .where(Subscription.master_telegram_id == old_owner_id)
                .values(master_telegram_id=telegram_id)
            )

            state_data.pop("account_link_code", None)
            state_data.pop("account_link_expires_at", None)
            state_data["linked_telegram_id"] = telegram_id
            profile.state_data_json = state_data
            await session.commit()
        return True

    @staticmethod
    def owner_id(profile: MasterVkProfile) -> int:
        return int((profile.state_data_json or {}).get("linked_telegram_id") or profile.pseudo_telegram_id)


account_link_service = AccountLinkService()
