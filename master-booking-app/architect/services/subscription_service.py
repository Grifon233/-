"""Subscription service with reminders before expiration."""
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func, select, update
from backend.database import async_session_maker, MasterBot, MasterVkProfile, Subscription, VkBot
from architect.services.bot_manager import bot_manager
from architect.services.funnel_events import record_funnel_event
from architect.services.referral_service import referral_service

logger = logging.getLogger(__name__)


class SubscriptionService:
    """Управление подписками мастеров."""

    # Пороги для напоминаний (в днях)
    REMINDER_DAYS = [3, 1, 0]
    TRIAL_HOURS = 2

    async def _notify_vk_trial_deleted(
        self,
        owner_vk_id: int | None,
        bot_label: str,
        source_token: str | None = None,
    ) -> bool:
        if not owner_vk_id:
            return False
        from backend.token_utils import decrypt_token
        from backend.vk import api as vk_api

        message = (
            "⌛ Тестовый период завершён.\n\n"
            f"Бот {bot_label} удалён, потому что подписка не была оплачена в течение 2 часов. "
            "Если вы передумаете, то сможете повторно создать бота в будущем."
        )
        if source_token:
            try:
                if await vk_api.send_message(decrypt_token(source_token), owner_vk_id, message):
                    return True
            except Exception as exc:
                logger.warning("Failed to notify VK owner %s from deleted bot: %s", owner_vk_id, exc)

        async with async_session_maker() as session:
            architect_vk_bot = (await session.execute(
                select(VkBot).where(
                    VkBot.bot_type == "architect",
                    VkBot.status == "running",
                )
            )).scalars().first()
        if not architect_vk_bot:
            logger.warning("VK Architect bot is unavailable; cannot notify VK owner %s", owner_vk_id)
            return False
        try:
            sent = await vk_api.send_message(
                decrypt_token(architect_vk_bot.token),
                owner_vk_id,
                message,
            )
            if not sent:
                logger.warning("VK trial deletion notification was rejected for owner %s", owner_vk_id)
            return sent
        except Exception as exc:
            logger.warning("Failed to notify VK owner %s about trial deletion: %s", owner_vk_id, exc)
            return False

    async def delete_expired_unpaid_trial_bots(self, notification_bot=None) -> list[int]:
        """Delete bots that were created for testing but were not paid for in time."""
        cutoff = datetime.utcnow() - timedelta(hours=self.TRIAL_HOURS)
        async with async_session_maker() as session:
            bots = (await session.execute(
                select(MasterBot).where(
                    func.coalesce(MasterBot.trial_started_at, MasterBot.created_at) <= cutoff
                )
            )).scalars().all()
            bot_counts: dict[int, int] = {}
            for item in bots:
                bot_counts[item.master_telegram_id] = bot_counts.get(item.master_telegram_id, 0) + 1
            paid_bot_ids = set((await session.execute(
                select(Subscription.master_bot_id).where(
                    Subscription.status == "active",
                    Subscription.master_bot_id.isnot(None),
                )
            )).scalars().all())
            paid_master_ids = set((await session.execute(
                select(Subscription.master_telegram_id).where(
                    Subscription.status == "active",
                    Subscription.master_bot_id.is_(None),
                )
            )).scalars().all())
            legacy_protected_bot_ids: dict[int, int] = {}
            if paid_master_ids:
                all_master_bots = (await session.execute(
                    select(MasterBot)
                    .where(MasterBot.master_telegram_id.in_(paid_master_ids))
                    .order_by(MasterBot.master_telegram_id.asc(), MasterBot.created_at.asc(), MasterBot.id.asc())
                )).scalars().all()
                for item in all_master_bots:
                    legacy_protected_bot_ids.setdefault(item.master_telegram_id, item.id)

        deleted: list[int] = []
        for bot in bots:
            if bot.id in paid_bot_ids:
                continue
            # Legacy subscriptions without master_bot_id used to cover a single-bot master account.
            # Once a master has multiple bots, an old master-level subscription must not keep every
            # newer unpaid trial bot alive forever.
            if (
                bot.master_telegram_id in paid_master_ids
                and (
                    bot_counts.get(bot.master_telegram_id, 0) <= 1
                    or legacy_protected_bot_ids.get(bot.master_telegram_id) == bot.id
                )
            ):
                continue
            async with async_session_maker() as session:
                paired_vk_bots = (await session.execute(
                    select(VkBot).where(
                        VkBot.master_id == bot.master_id,
                        VkBot.bot_type == "client",
                    )
                )).scalars().all()
                paired_vk_notifications = [
                    (
                        item.owner_vk_id,
                        item.group_name or f"ВКонтакте #{item.group_id}",
                        item.token,
                    )
                    for item in paired_vk_bots
                ]
            if await bot_manager.delete_bot(bot.master_telegram_id, bot.id):
                deleted.append(bot.id)
                if paired_vk_bots and bot.master_id is not None:
                    try:
                        from architect.services.vk_bot_manager import vk_bot_manager
                        await vk_bot_manager.delete_vk_bot(
                            bot.master_telegram_id,
                            master_id=bot.master_id,
                        )
                    except Exception as exc:
                        logger.warning("Failed to delete VkBot for master %s during trial cleanup: %s",
                                       bot.master_telegram_id, exc)
                await record_funnel_event(
                    "trial_bot_deleted_unpaid",
                    bot.master_telegram_id,
                    bot.id,
                    {"username": bot.username},
                )
                if bot.master_telegram_id > 0 and notification_bot:
                    try:
                        await notification_bot.send_message(
                            bot.master_telegram_id,
                            "⌛ Тестовый период завершён.\n\n"
                            f"Бот @{bot.username or bot.id} удалён, потому что подписка не была оплачена в течение 2 часов. "
                            "Если вы передумаете, то сможете повторно создать бота в будущем.",
                        )
                    except Exception as exc:
                        logger.warning("Failed to notify owner about trial bot deletion %s: %s", bot.id, exc)
                for owner_vk_id, group_name, source_token in paired_vk_notifications:
                    await self._notify_vk_trial_deleted(owner_vk_id, group_name, source_token)

        async with async_session_maker() as session:
            standalone_vk_bots = (await session.execute(
                select(VkBot).where(
                    VkBot.bot_type == "client",
                    VkBot.created_at <= cutoff,
                )
            )).scalars().all()
            paired_master_ids = set((await session.execute(
                select(MasterBot.master_id).where(MasterBot.master_id.isnot(None))
            )).scalars().all())
            active_vk_owners = set((await session.execute(
                select(Subscription.master_telegram_id).where(Subscription.status == "active")
            )).scalars().all())

        for vk_bot in standalone_vk_bots:
            if vk_bot.master_id in paired_master_ids or vk_bot.master_telegram_id in active_vk_owners:
                continue
            owner_vk_id = vk_bot.owner_vk_id
            group_name = vk_bot.group_name or f"ВКонтакте #{vk_bot.group_id}"
            source_token = vk_bot.token
            from architect.services.vk_bot_manager import vk_bot_manager
            if await vk_bot_manager.delete_vk_bot(
                vk_bot.master_telegram_id,
                vk_bot_id=vk_bot.id,
            ):
                await record_funnel_event(
                    "trial_vk_bot_deleted_unpaid",
                    vk_bot.master_telegram_id,
                    metadata={"group_id": vk_bot.group_id, "group_name": group_name},
                )
                await self._notify_vk_trial_deleted(owner_vk_id, group_name, source_token)
        if deleted:
            logger.info("Deleted expired unpaid trial bots: %s", deleted)
        return deleted

    async def get_subscription_status(self, master_telegram_id: int, master_bot_id: int | None = None) -> dict:
        """Получить статус подписки владельца или конкретного бота."""
        async with async_session_maker() as session:
            query = select(Subscription).where(Subscription.master_telegram_id == master_telegram_id)
            if master_bot_id is not None:
                # Подписка, оформленная из ВКонтакте, привязана к владельцу, а не к
                # конкретному боту (master_bot_id IS NULL). Поэтому, кроме подписки
                # именно этого бота, учитываем и общую подписку аккаунта.
                query = query.where(
                    (Subscription.master_bot_id == master_bot_id)
                    | (Subscription.master_bot_id.is_(None))
                )
            result = await session.execute(query.order_by(Subscription.created_at.desc()))
            subs = result.scalars().all()

            if master_bot_id is not None:
                sub = next((s for s in subs if s.master_bot_id == master_bot_id), None)
                if sub is None:
                    sub = next((s for s in subs if s.master_bot_id is None), None)
            else:
                sub = subs[0] if subs else None

            if not sub:
                return {"status": "no_subscription", "days_left": 0}

            if sub.status == "pending" and sub.payment_provider == "yookassa_checkout":
                try:
                    from architect.services.yookassa_payment import yookassa_payment

                    payment = await yookassa_payment.get_payment(sub.payment_id)
                    if payment.get("status") == "succeeded":
                        activated = await self.activate_pending_subscription(
                            payment_provider=sub.payment_provider,
                            payment_id=sub.payment_id,
                            provider_payment_charge_id=sub.payment_id,
                        )
                        if activated:
                            sub = activated
                except Exception as exc:
                    logger.warning("Failed to refresh pending YooKassa payment %s: %s", sub.payment_id, exc)

            if sub.lifetime and sub.status == "active":
                return {
                    "status": "active",
                    "days_left": None,
                    "end_date": None,
                    "period_days": sub.period_days,
                    "lifetime": True,
                }

            if sub.paid_at and sub.status == "active":
                # Вычисляем дни до конца
                end_date = datetime.combine(sub.paid_at.date(), datetime.min.time()) + timedelta(days=sub.period_days)
                days_left = (end_date.date() - datetime.now().date()).days

                return {
                    "status": "active" if days_left > 0 else "expired",
                    "days_left": max(0, days_left),
                    "end_date": end_date.isoformat(),
                    "period_days": sub.period_days,
                }

            return {"status": sub.status, "days_left": 0}

    async def create_subscription(
        self,
        master_telegram_id: int,
        period_days: int = 30,
        price: float = 250,
        payment_provider: str = "manual",
        payment_id: str | None = None,
    ) -> Subscription:
        """Создать новую подписку (после оплаты)."""
        async with async_session_maker() as session:
            sub = Subscription(
                master_telegram_id=master_telegram_id,
                period_days=period_days,
                price=price,
                payment_provider=payment_provider,
                payment_id=payment_id,
                status="active",
                paid_at=datetime.now(),
            )
            session.add(sub)
            await session.commit()
            await session.refresh(sub)
            return sub

    async def activate_pending_subscription(
        self,
        payment_provider: str,
        payment_id: str,
        telegram_payment_charge_id: str | None = None,
        provider_payment_charge_id: str | None = None,
    ) -> Subscription | None:
        """Активировать pending подписку после webhook/notification от платёжки."""
        async with async_session_maker() as session:
            result = await session.execute(
                select(Subscription).where(
                    Subscription.payment_provider == payment_provider,
                    Subscription.payment_id == payment_id,
                ).order_by(Subscription.created_at.desc())
            )
            sub = result.scalars().first()
            if not sub:
                return None

            was_active = sub.status == "active"
            if sub.status != "active":
                sub.status = "active"
                sub.paid_at = datetime.now()
            if telegram_payment_charge_id:
                sub.telegram_payment_charge_id = telegram_payment_charge_id
            if provider_payment_charge_id:
                sub.provider_payment_charge_id = provider_payment_charge_id
            await session.commit()
            await session.refresh(sub)

        try:
            if sub.master_bot_id:
                access_restored = await bot_manager.unfreeze_bot(sub.master_telegram_id, sub.master_bot_id)
            else:
                access_restored = await bot_manager.unfreeze_bot(sub.master_telegram_id)
            if not access_restored:
                logger.error(
                    "Payment %s is active, but bot access was not restored; reconciliation will retry",
                    payment_id,
                )
        except Exception:
            logger.exception(
                "Payment %s is active, but bot access restoration failed; reconciliation will retry",
                payment_id,
            )

        reward = {"rewarded": False}
        if not was_active:
            reward = await referral_service.reward_after_payment(payment_provider, payment_id)
            if reward.get("rewarded"):
                async with async_session_maker() as session:
                    db_sub = await session.get(Subscription, sub.id)
                    if db_sub:
                        sub.period_days = db_sub.period_days
            await record_funnel_event(
                "subscription_paid",
                sub.master_telegram_id,
                sub.master_bot_id,
                {
                    "payment_provider": payment_provider,
                    "payment_id": payment_id,
                    "period_days": sub.period_days,
                    "price": sub.price,
                    "lifetime": sub.lifetime,
                },
            )
            await self._notify_payment_success(sub, promo_bonus=bool(reward.get("rewarded")))

        return sub

    async def reconcile_active_subscription_access(self) -> list[int]:
        """Restore frozen bots whose paid subscription is still active."""
        now = datetime.now()
        targets: set[tuple[int, int | None]] = set()
        async with async_session_maker() as session:
            subscriptions = (await session.execute(
                select(Subscription).where(Subscription.status == "active")
            )).scalars().all()
            for sub in subscriptions:
                if not sub.lifetime and (
                    not sub.paid_at
                    or sub.paid_at + timedelta(days=sub.period_days) <= now
                ):
                    continue

                query = select(MasterBot).where(
                    MasterBot.master_telegram_id == sub.master_telegram_id,
                    MasterBot.status == "frozen",
                )
                if sub.master_bot_id is not None:
                    query = query.where(MasterBot.id == sub.master_bot_id)
                frozen_bots = (await session.execute(query)).scalars().all()
                for master_bot in frozen_bots:
                    targets.add((sub.master_telegram_id, master_bot.id))

        restored: list[int] = []
        for telegram_id, bot_id in targets:
            try:
                if await bot_manager.unfreeze_bot(telegram_id, bot_id):
                    restored.append(bot_id)
            except Exception:
                logger.exception("Failed to reconcile paid access for bot %s", bot_id)
        return restored

    async def mark_subscription_refunded(
        self,
        payment_provider: str,
        payment_id: str,
        refund_id: str | None = None,
        refund_amount: str | None = None,
    ) -> Subscription | None:
        """Mark a paid subscription as refunded and freeze its bot when access is no longer paid."""
        async with async_session_maker() as session:
            result = await session.execute(
                select(Subscription).where(
                    Subscription.payment_provider == payment_provider,
                    (
                        (Subscription.payment_id == payment_id)
                        | (Subscription.provider_payment_charge_id == payment_id)
                    ),
                ).order_by(Subscription.created_at.desc())
            )
            sub = result.scalars().first()
            if not sub:
                return None

            if sub.status != "refunded":
                sub.status = "refunded"
            if refund_id:
                sub.provider_payment_charge_id = f"refund:{refund_id}"
            await session.commit()
            await session.refresh(sub)

            still_active = await self._has_current_active_access(
                session,
                sub.master_telegram_id,
                sub.master_bot_id,
                exclude_subscription_id=sub.id,
            )

        promo_revoke = await referral_service.revoke_reward_after_refund(sub.id)
        for affected in promo_revoke.get("affected", []):
            async with async_session_maker() as session:
                affected_still_active = await self._has_current_active_access(
                    session,
                    affected["telegram_id"],
                    affected.get("master_bot_id"),
                    exclude_subscription_id=None,
                )
            if not affected_still_active:
                try:
                    if affected.get("master_bot_id"):
                        await bot_manager.freeze_bot(affected["telegram_id"], affected.get("master_bot_id"))
                    else:
                        await bot_manager.freeze_bot(affected["telegram_id"])
                except Exception as e:
                    logger.warning("Failed to freeze bot after promo refund revoke %s: %s", payment_id, e)

        if not still_active:
            try:
                if sub.master_bot_id:
                    await bot_manager.freeze_bot(sub.master_telegram_id, sub.master_bot_id)
                else:
                    await bot_manager.freeze_bot(sub.master_telegram_id)
            except Exception as e:
                logger.warning("Failed to freeze bot after refund %s: %s", payment_id, e)

        await record_funnel_event(
            "subscription_refunded",
            sub.master_telegram_id,
            sub.master_bot_id,
            {
                "payment_provider": payment_provider,
                "payment_id": payment_id,
                "refund_id": refund_id,
                "refund_amount": refund_amount,
                "bot_frozen": not bool(still_active),
                "promo_revoke": promo_revoke,
            },
        )
        await self._notify_refund(sub, refund_amount=refund_amount, bot_frozen=not bool(still_active))
        return sub

    async def _has_current_active_access(
        self,
        session,
        master_telegram_id: int,
        master_bot_id: int | None,
        exclude_subscription_id: int | None = None,
    ) -> bool:
        query = select(Subscription).where(
            Subscription.master_telegram_id == master_telegram_id,
            Subscription.status == "active",
        )
        if exclude_subscription_id:
            query = query.where(Subscription.id != exclude_subscription_id)
        if master_bot_id:
            query = query.where(Subscription.master_bot_id == master_bot_id)
        else:
            query = query.where(Subscription.master_bot_id.is_(None))

        now = datetime.utcnow()
        subs = (await session.execute(query)).scalars().all()
        for item in subs:
            if item.lifetime:
                return True
            if not item.paid_at:
                return True
            if item.paid_at and item.paid_at + timedelta(days=item.period_days or 0) > now:
                return True
        return False

    async def _notify_refund(self, sub: Subscription, refund_amount: str | None = None, bot_frozen: bool = True) -> None:
        from aiogram import Bot
        from aiogram.client.session.aiohttp import AiohttpSession
        from architect.config import settings

        if not settings.architect_token or settings.architect_token == "<ASK_SECURE_MEMORY>":
            return
        if ":" not in settings.architect_token:
            return
        amount_line = f"Сумма возврата: {refund_amount} ₽\n" if refund_amount else ""
        message_text = (
            "↩️ Возврат оплаты обработан.\n\n"
            f"{amount_line}"
            "Подписка по этому платежу больше не активна.\n"
            + ("Бот заморожен, потому что после возврата у него не осталось активной подписки." if bot_frozen else "У бота осталась другая активная подписка, поэтому доступ не заморожен.")
        )
        proxy_url = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy") or settings.proxy_url
        for use_proxy in ([True, False] if proxy_url else [False]):
            session = AiohttpSession(proxy=proxy_url) if use_proxy and proxy_url else AiohttpSession()
            bot = Bot(token=settings.architect_token, session=session)
            try:
                await bot.send_message(sub.master_telegram_id, message_text, request_timeout=30)
                return
            except Exception as exc:
                logger.warning(
                    "Failed to notify refund for %s via %s: %s",
                    sub.master_telegram_id,
                    "proxy" if use_proxy and proxy_url else "direct",
                    exc,
                )
            finally:
                await bot.session.close()

    async def _notify_payment_success(self, sub: Subscription, promo_bonus: bool = False) -> None:
        from aiogram import Bot
        from aiogram.client.session.aiohttp import AiohttpSession
        from architect.config import settings

        if not settings.architect_token or settings.architect_token == "<ASK_SECURE_MEMORY>":
            return
        if ":" not in settings.architect_token:
            return
        period_text = "пожизненная подписка" if sub.lifetime else f"на {sub.period_days} дней"
        payment_ref = sub.provider_payment_charge_id or sub.telegram_payment_charge_id or sub.payment_id or "—"
        message_text = (
            "✅ Подписка оплачена!\n\n"
            f"Срок: {period_text}\n"
            f"Платёж: {payment_ref}\n\n"
            + ("Промокод применён: к подписке добавлен подарочный месяц.\n\n" if promo_bonus else "")
            + "Чек передан в YooKassa и будет отправлен на контакт, указанный для чека."
        )
        proxy_url = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy") or settings.proxy_url
        for use_proxy in ([True, False] if proxy_url else [False]):
            session = AiohttpSession(proxy=proxy_url) if use_proxy and proxy_url else AiohttpSession()
            bot = Bot(token=settings.architect_token, session=session)
            try:
                await bot.send_message(
                    sub.master_telegram_id,
                    message_text,
                    request_timeout=30,
                )
                return
            except Exception as exc:
                logger.warning(
                    "Failed to notify payment success for %s via %s: %s",
                    sub.master_telegram_id,
                    "proxy" if use_proxy and proxy_url else "direct",
                    exc,
                )
            finally:
                await bot.session.close()

    async def check_and_remind(self, bot) -> int:
        """
        Проверить все подписки и отправить напоминания.
        Возвращает количество отправленных напоминаний.
        """
        sent_count = 0
        async with async_session_maker() as session:
            result = await session.execute(
                select(Subscription).where(Subscription.status == "active")
            )
            subs = result.scalars().all()

            now = datetime.now()
            for sub in subs:
                if sub.lifetime:
                    continue
                if not sub.paid_at:
                    continue

                # Момент окончания — с точностью до времени, а не только до даты,
                # иначе бот замораживался утром последнего оплаченного дня.
                end_at = sub.paid_at + timedelta(days=sub.period_days)
                days_left = (end_at.date() - now.date()).days

                if days_left in self.REMINDER_DAYS and end_at > now:
                    try:
                        await bot.send_message(
                            chat_id=sub.master_telegram_id,
                            text=f"⏰ Напоминание: ваша подписка истекает через {days_left} дн.\n"
                                 f"Для продления нажмите /start → «💳 Подписка»."
                        )
                        sent_count += 1
                        logger.info(f"Sent reminder to {sub.master_telegram_id}: {days_left} days left")
                    except Exception as e:
                        logger.error(f"Failed to send reminder to {sub.master_telegram_id}: {e}")

                # Отключаем, если срок реально закончился (по времени, не по дате).
                if end_at <= now and sub.status == "active":
                    sub.status = "expired"
                    await session.commit()
                    # Заморозку выполняем БЕЗУСЛОВНО и в первую очередь: раньше она
                    # стояла внутри try после send_message, и если мастер заблокировал
                    # Архитектора, отправка падала и бот оставался работать бесплатно.
                    try:
                        if sub.master_bot_id:
                            await bot_manager.freeze_bot(sub.master_telegram_id, sub.master_bot_id)
                        else:
                            await bot_manager.freeze_bot(sub.master_telegram_id)
                    except Exception as e:
                        logger.error(f"Failed to freeze bot after expiry for {sub.master_telegram_id}: {e}")
                    try:
                        await bot.send_message(
                            chat_id=sub.master_telegram_id,
                            text="❌ Подписка истекла.\n"
                                 "Бот временно отключён. Чтобы включить его снова, нажмите "
                                 "/start → «💳 Подписка» и продлите подписку."
                        )
                    except Exception as e:
                        logger.error(f"Failed to notify about expiry: {e}")

        return sent_count

    async def check_subscriptions_and_freeze(self, bot_manager) -> list[dict]:
        """
        Проверяет все подписки и замораживает/размораживает боты.
        Возвращает список затронутых ботов.
        """
        from backend.database import Master
        affected = []

        async with async_session_maker() as session:
            # Получаем всех мастеров у которых включена проверка подписки
            result = await session.execute(
                select(Master).where(Master.subscription_required == True)
            )
            masters = result.scalars().all()

            for master in masters:
                if not master.telegram_id:
                    continue

                # Проверяем статус подписки
                status = await self.get_subscription_status(master.telegram_id)
                is_active = status.get("status") == "active"
                days_left = status.get("days_left", 0)

                # Получаем бота мастера
                bot_result = await session.execute(
                    select(MasterBot).where(MasterBot.master_telegram_id == master.telegram_id)
                )
                master_bot = bot_result.scalar_one_or_none()

                if not master_bot:
                    continue

                if is_active and (status.get("lifetime") or days_left > 0):
                    # Подписка активна - размораживаем если заморожен
                    if master_bot.status == "frozen":
                        await bot_manager.unfreeze_bot(master.telegram_id)
                        affected.append({
                            "bot_id": master_bot.id,
                            "username": master_bot.username,
                            "action": "unfreeze",
                            "days_left": days_left
                        })
                elif not is_active:
                    # Подписка неактивна - замораживаем если не заморожен
                    if master_bot.status != "frozen":
                        await bot_manager.freeze_bot(master.telegram_id)
                        affected.append({
                            "bot_id": master_bot.id,
                            "username": master_bot.username,
                            "action": "freeze",
                            "reason": "subscription expired"
                        })

        return affected

    async def get_all_stats(self) -> dict:
        """Статистика для админа."""
        async with async_session_maker() as session:
            from sqlalchemy import func
            from backend.database import Client, Booking

            total_masters = await session.execute(select(func.count(MasterBot.id)))
            total_masters = total_masters.scalar() or 0

            active_subs = await session.execute(
                select(func.count(Subscription.id)).where(Subscription.status == "active")
            )
            active_subs = active_subs.scalar() or 0

            expired_subs = await session.execute(
                select(func.count(Subscription.id)).where(Subscription.status == "expired")
            )
            expired_subs = expired_subs.scalar() or 0

            total_clients = await session.execute(select(func.count(Client.id)))
            total_clients = total_clients.scalar() or 0

            return {
                "total_masters": total_masters,
                "active_subscriptions": active_subs,
                "expired_subscriptions": expired_subs,
                "total_clients": total_clients,
            }

    async def get_all_masters(self) -> list[dict]:
        """Список всех мастеров с их статусами."""
        masters = []
        async with async_session_maker() as session:
            from sqlalchemy import func
            from backend.database import Client

            result = await session.execute(
                select(MasterBot, Subscription).join(
                    Subscription,
                    Subscription.master_telegram_id == MasterBot.master_telegram_id,
                    isouter=True
                ).order_by(MasterBot.created_at.desc())
            )
            rows = result.all()
            master_ids = {bot_row.master_id for bot_row, _ in rows if bot_row.master_id}
            client_counts = {}
            if master_ids:
                client_counts = dict((await session.execute(
                    select(Client.master_id, func.count(Client.id))
                    .where(Client.master_id.in_(master_ids))
                    .group_by(Client.master_id)
                )).all())

            for bot_row, sub in rows:
                client_count = client_counts.get(bot_row.master_id, 0)

                days_left = 0
                is_active = bot_row.status == "running"

                if sub and sub.lifetime and sub.status == "active":
                    days_left = 0
                    is_active = is_active and True
                elif sub and sub.paid_at and sub.status == "active":
                    end_date = sub.paid_at + timedelta(days=sub.period_days)
                    days_left = (end_date.date() - datetime.now().date()).days
                    is_active = is_active and days_left > 0

                masters.append({
                    "id": bot_row.id,
                    "name": f"Master #{bot_row.id}",
                    "username": bot_row.username,
                    "is_active": is_active,
                    "days_left": max(0, days_left),
                    "client_count": client_count,
                })

        return masters

    async def broadcast_to_masters(self, message: str) -> int:
        """Отправить сообщение всем активным мастерам."""
        from aiogram import Bot
        from architect.config import settings

        sent = 0
        bot = Bot(token=settings.architect_token)

        async with async_session_maker() as session:
            result = await session.execute(
                select(MasterBot).where(MasterBot.status == "running")
            )
            bots = result.scalars().all()

            for master_bot in bots:
                try:
                    await bot.send_message(
                        chat_id=master_bot.master_telegram_id,
                        text=f"📢 Сообщение от администратора:\n\n{message}"
                    )
                    sent += 1
                except Exception as e:
                    logger.error(f"Failed to broadcast to {master_bot.master_telegram_id}: {e}")

        return sent


subscription_service = SubscriptionService()
