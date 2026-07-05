import logging
import secrets
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select

from backend.database import (
    MasterBot,
    ReferralApplication,
    ReferralCode,
    Subscription,
    async_session_maker,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PromoApplyResult:
    ok: bool
    message: str
    code: str | None = None


class ReferralService:
    BONUS_DAYS = 30

    async def ensure_code(self, telegram_id: int) -> str:
        async with async_session_maker() as session:
            existing = (await session.execute(
                select(ReferralCode).where(ReferralCode.telegram_id == telegram_id)
            )).scalars().first()
            if existing:
                return existing.code

            used_codes = set((await session.execute(select(ReferralCode.code))).scalars().all())
            for _ in range(100):
                code = f"{secrets.randbelow(10000):04d}"
                if code not in used_codes:
                    row = ReferralCode(telegram_id=telegram_id, code=code)
                    session.add(row)
                    await session.commit()
                    return code

            for number in range(10000):
                code = f"{number:04d}"
                if code not in used_codes:
                    row = ReferralCode(telegram_id=telegram_id, code=code)
                    session.add(row)
                    await session.commit()
                    return code

        raise RuntimeError("Не удалось создать промокод")

    async def has_paid_before(self, telegram_id: int, exclude_subscription_id: int | None = None) -> bool:
        async with async_session_maker() as session:
            query = select(Subscription.id).where(
                Subscription.master_telegram_id == telegram_id,
                Subscription.paid_at.isnot(None),
            )
            if exclude_subscription_id:
                query = query.where(Subscription.id != exclude_subscription_id)
            return (await session.execute(query.limit(1))).scalars().first() is not None

    async def get_applied_code(self, telegram_id: int) -> str | None:
        """Returns the pending applied promo code; None once it has been rewarded."""
        async with async_session_maker() as session:
            result = await session.execute(
                select(ReferralCode.code)
                .join(ReferralApplication, ReferralApplication.code_id == ReferralCode.id)
                .where(
                    ReferralApplication.referred_telegram_id == telegram_id,
                    ReferralApplication.status == "applied",
                )
            )
            return result.scalars().first()

    async def apply_code(self, referred_telegram_id: int, raw_code: str) -> PromoApplyResult:
        code = "".join(ch for ch in (raw_code or "") if ch.isdigit())
        if len(code) != 4:
            return PromoApplyResult(False, "Промокод должен состоять из 4 цифр.")
        if await self.has_paid_before(referred_telegram_id):
            return PromoApplyResult(False, "Промокод можно применить только до первой оплаты.")

        async with async_session_maker() as session:
            referral = (await session.execute(
                select(ReferralCode).where(ReferralCode.code == code)
            )).scalars().first()
            if not referral:
                return PromoApplyResult(False, "Не удалось найти владельца этого промокода.")
            if referral.telegram_id == referred_telegram_id:
                return PromoApplyResult(False, "Нельзя применить собственный промокод.")

            existing = (await session.execute(
                select(ReferralApplication).where(
                    ReferralApplication.referred_telegram_id == referred_telegram_id
                )
            )).scalars().first()
            if existing:
                return PromoApplyResult(False, "Вы уже использовали промокод.")
            else:
                session.add(ReferralApplication(
                    code_id=referral.id,
                    referrer_telegram_id=referral.telegram_id,
                    referred_telegram_id=referred_telegram_id,
                ))
            await session.commit()

        return PromoApplyResult(True, "Промокод применён. Бонусный месяц будет добавлен после оплаты.", code)

    async def reward_after_payment(self, payment_provider: str, payment_id: str) -> dict:
        async with async_session_maker() as session:
            sub = (await session.execute(
                select(Subscription).where(
                    Subscription.payment_provider == payment_provider,
                    Subscription.payment_id == payment_id,
                ).order_by(Subscription.created_at.desc())
            )).scalars().first()
            if not sub:
                return {"rewarded": False}
            if await self._has_paid_before_in_session(session, sub.master_telegram_id, sub.id):
                return {"rewarded": False, "reason": "not_first_payment"}

            application = (await session.execute(
                select(ReferralApplication).where(
                    ReferralApplication.referred_telegram_id == sub.master_telegram_id,
                    ReferralApplication.status == "applied",
                    ReferralApplication.rewarded_at.is_(None),
                )
            )).scalars().first()
            if not application:
                return {"rewarded": False, "reason": "no_promo"}

            if not sub.lifetime:
                sub.period_days = (sub.period_days or 0) + self.BONUS_DAYS

            referrer_sub = await self._latest_referrer_subscription(session, application.referrer_telegram_id)
            if referrer_sub and not referrer_sub.lifetime:
                referrer_sub.period_days = (referrer_sub.period_days or 0) + self.BONUS_DAYS
            elif not referrer_sub:
                bot_id = (await session.execute(
                    select(MasterBot.id)
                    .where(MasterBot.master_telegram_id == application.referrer_telegram_id)
                    .order_by(MasterBot.created_at.desc(), MasterBot.id.desc())
                    .limit(1)
                )).scalars().first()
                session.add(Subscription(
                    master_telegram_id=application.referrer_telegram_id,
                    master_bot_id=bot_id,
                    period_days=self.BONUS_DAYS,
                    price=0,
                    payment_provider="promo_bonus",
                    payment_id=f"promo:{application.id}:{sub.id}",
                    status="active",
                    paid_at=datetime.utcnow(),
                ))

            application.status = "rewarded"
            application.subscription_id = sub.id
            application.rewarded_at = datetime.utcnow()
            await session.commit()

        return {
            "rewarded": True,
            "referrer_telegram_id": application.referrer_telegram_id,
            "referred_telegram_id": application.referred_telegram_id,
        }

    async def revoke_reward_after_refund(self, subscription_id: int) -> dict:
        """Revoke promo bonus from both sides when the referred payment is refunded."""
        async with async_session_maker() as session:
            sub = await session.get(Subscription, subscription_id)
            if not sub:
                return {"revoked": False, "reason": "subscription_not_found"}

            application = (await session.execute(
                select(ReferralApplication).where(
                    ReferralApplication.subscription_id == subscription_id,
                    ReferralApplication.status == "rewarded",
                )
            )).scalars().first()
            if not application:
                return {"revoked": False, "reason": "no_rewarded_application"}

            affected: list[dict] = []
            if not sub.lifetime:
                sub.period_days = max(0, (sub.period_days or 0) - self.BONUS_DAYS)
                affected.append({
                    "telegram_id": sub.master_telegram_id,
                    "master_bot_id": sub.master_bot_id,
                    "subscription_id": sub.id,
                })

            promo_bonus = (await session.execute(
                select(Subscription).where(
                    Subscription.payment_provider == "promo_bonus",
                    Subscription.payment_id == f"promo:{application.id}:{sub.id}",
                ).order_by(Subscription.created_at.desc())
            )).scalars().first()
            if promo_bonus:
                promo_bonus.status = "refunded"
                affected.append({
                    "telegram_id": promo_bonus.master_telegram_id,
                    "master_bot_id": promo_bonus.master_bot_id,
                    "subscription_id": promo_bonus.id,
                })
            else:
                referrer_sub = await self._latest_referrer_subscription(session, application.referrer_telegram_id)
                if referrer_sub and not referrer_sub.lifetime:
                    referrer_sub.period_days = max(0, (referrer_sub.period_days or 0) - self.BONUS_DAYS)
                    affected.append({
                        "telegram_id": referrer_sub.master_telegram_id,
                        "master_bot_id": referrer_sub.master_bot_id,
                        "subscription_id": referrer_sub.id,
                    })

            application.status = "reward_revoked"
            await session.commit()

        return {
            "revoked": True,
            "referrer_telegram_id": application.referrer_telegram_id,
            "referred_telegram_id": application.referred_telegram_id,
            "affected": affected,
        }

    async def _has_paid_before_in_session(self, session, telegram_id: int, exclude_subscription_id: int) -> bool:
        query = select(Subscription.id).where(
            Subscription.master_telegram_id == telegram_id,
            Subscription.paid_at.isnot(None),
            Subscription.id != exclude_subscription_id,
        )
        return (await session.execute(query.limit(1))).scalars().first() is not None

    async def _latest_referrer_subscription(self, session, telegram_id: int) -> Subscription | None:
        result = await session.execute(
            select(Subscription)
            .where(
                Subscription.master_telegram_id == telegram_id,
                Subscription.status == "active",
                Subscription.paid_at.isnot(None),
            )
            .order_by(Subscription.paid_at.desc(), Subscription.created_at.desc())
            .limit(1)
        )
        return result.scalars().first()


referral_service = ReferralService()
