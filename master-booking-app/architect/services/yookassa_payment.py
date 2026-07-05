"""YooKassa subscription payments via external checkout with Telegram fallback."""
import logging
import os
import secrets
from dataclasses import dataclass
from decimal import Decimal
from uuid import uuid4

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.types import LabeledPrice, Message, PreCheckoutQuery
import httpx
from sqlalchemy import select

from architect.config import settings
from backend.database import Subscription, async_session_maker
from backend.client_profiles import get_client_profile
from backend.config import build_url

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class YooKassaPlan:
    period: str
    label: str
    days: int
    amount: Decimal

    @property
    def amount_minor(self) -> int:
        return int(self.amount * 100)


class YooKassaPayment:
    """Creates and validates RUB subscription payments paid through YooKassa."""

    PROVIDER = "telegram_yookassa"
    CHECKOUT_PROVIDER = "yookassa_checkout"
    CURRENCY = "RUB"
    PLANS = {
        "1_month": YooKassaPlan("1_month", "1 месяц", 30, Decimal("450.00")),
        "6_months": YooKassaPlan("6_months", "6 месяцев", 180, Decimal("2700.00")),
        "12_months": YooKassaPlan("12_months", "12 месяцев", 365, Decimal("5300.00")),
    }

    def get_plan(self, period: str) -> YooKassaPlan:
        return self.PLANS.get(period, self.PLANS["1_month"])

    def _provider_token(self) -> str:
        token = os.getenv("YOOKASSA_PROVIDER_TOKEN", "").strip()
        if not token:
            raise ValueError("YOOKASSA_PROVIDER_TOKEN не задан")
        return token

    def _api_credentials(self) -> tuple[str, str] | None:
        shop_id = os.getenv("YOOKASSA_SHOP_ID", "").strip()
        secret_key = os.getenv("YOOKASSA_SECRET_KEY", "").strip()
        if shop_id and secret_key:
            return shop_id, secret_key
        return None

    def supports_external_checkout(self) -> bool:
        return self._api_credentials() is not None

    def _client_kwargs(self) -> dict:
        # YooKassa API should bypass optional Telegram proxy settings.
        return {
            "timeout": 20.0,
            "trust_env": False,
        }

    async def _receipt_customer(self, master_telegram_id: int) -> dict:
        async with async_session_maker() as session:
            profile = await get_client_profile(session, master_telegram_id)

        if profile and profile.phone:
            return {"phone": profile.phone}

        receipt_email = os.getenv("YOOKASSA_RECEIPT_EMAIL", "").strip()
        if receipt_email:
            return {"email": receipt_email}

        receipt_phone = os.getenv("YOOKASSA_RECEIPT_PHONE", "").strip()
        if receipt_phone:
            return {"phone": receipt_phone}

        fallback_email = os.getenv("YOOKASSA_RECEIPT_FALLBACK_EMAIL", "").strip()
        if fallback_email:
            return {"email": fallback_email}

        fallback_phone = os.getenv("YOOKASSA_RECEIPT_FALLBACK_PHONE", "").strip()
        if fallback_phone:
            return {"phone": fallback_phone}

        raise ValueError(
            "YooKassa требует данные для чека. "
            "Сохраните телефон владельца в профиле или задайте "
            "YOOKASSA_RECEIPT_EMAIL/YOOKASSA_RECEIPT_PHONE либо резервные "
            "YOOKASSA_RECEIPT_FALLBACK_EMAIL/YOOKASSA_RECEIPT_FALLBACK_PHONE."
        )

    async def _build_receipt(self, master_telegram_id: int, plan: YooKassaPlan) -> dict:
        vat_code = int(os.getenv("YOOKASSA_VAT_CODE", "1"))
        return {
            "customer": await self._receipt_customer(master_telegram_id),
            "items": [
                {
                    "description": f"Подписка Master Booking на {plan.label}",
                    "quantity": "1.00",
                    "amount": {
                        "value": f"{plan.amount:.2f}",
                        "currency": self.CURRENCY,
                    },
                    "vat_code": vat_code,
                    "payment_mode": "full_prepayment",
                    "payment_subject": "service",
                }
            ],
        }

    def _payload(self, master_telegram_id: int, period: str, master_bot_id: int | None = None) -> str:
        nonce = secrets.token_urlsafe(12).replace("-", "").replace("_", "")[:16]
        return f"yookassa:{int(master_telegram_id)}:{master_bot_id or 0}:{period}:{nonce}"

    def _parse_payload(self, payload: str) -> tuple[int, int | None, YooKassaPlan] | None:
        parts = (payload or "").split(":")
        if parts[0] != "yookassa":
            return None
        try:
            master_telegram_id = int(parts[1])
            if len(parts) == 5 and parts[3] in self.PLANS:
                return master_telegram_id, int(parts[2]) or None, self.PLANS[parts[3]]
            if len(parts) == 4 and parts[2] in self.PLANS:
                return master_telegram_id, None, self.PLANS[parts[2]]
        except ValueError:
            return None
        return None

    async def create_payment_link(self, master_telegram_id: int, period: str = "1_month", master_bot_id: int | None = None) -> dict:
        plan = self.get_plan(period)
        payload = self._payload(master_telegram_id, plan.period, master_bot_id)
        if self.supports_external_checkout():
            return await self._create_checkout_payment(master_telegram_id, master_bot_id, plan, payload)
        return await self._create_telegram_invoice(master_telegram_id, master_bot_id, plan, payload)

    async def _create_checkout_payment(
        self,
        master_telegram_id: int,
        master_bot_id: int | None,
        plan: YooKassaPlan,
        payload: str,
    ) -> dict:
        credentials = self._api_credentials()
        if not credentials:
            raise ValueError("YOOKASSA_SHOP_ID или YOOKASSA_SECRET_KEY не заданы")
        shop_id, secret_key = credentials
        return_url = build_url("/payment-result", {"source": "yookassa", "payload": payload})
        body = {
            "amount": {
                "value": f"{plan.amount:.2f}",
                "currency": self.CURRENCY,
            },
            "capture": True,
            "confirmation": {
                "type": "redirect",
                "return_url": return_url,
            },
            "description": f"Подписка Master Booking на {plan.label}",
            "metadata": {
                "payload": payload,
                "master_telegram_id": str(master_telegram_id),
                "master_bot_id": str(master_bot_id or 0),
                "period": plan.period,
                "product": "master_booking_subscription",
            },
            "receipt": await self._build_receipt(master_telegram_id, plan),
        }
        headers = {
            "Idempotence-Key": str(uuid4()),
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(auth=(shop_id, secret_key), **self._client_kwargs()) as client:
            response = await client.post(
                "https://api.yookassa.ru/v3/payments",
                json=body,
                headers=headers,
            )
            if response.status_code >= 400:
                logger.error("YooKassa create payment failed: %s", response.text)
            response.raise_for_status()
            data = response.json()

        payment_id = data.get("id")
        confirmation_url = (data.get("confirmation") or {}).get("confirmation_url")
        if not payment_id or not confirmation_url:
            raise ValueError("YooKassa не вернула payment_id или confirmation_url")

        async with async_session_maker() as session:
            subscription = Subscription(
                master_telegram_id=master_telegram_id,
                master_bot_id=master_bot_id,
                period_days=plan.days,
                price=int(plan.amount),
                payment_provider=self.CHECKOUT_PROVIDER,
                payment_id=payment_id,
                telegram_payment_charge_id=payload,
                status="pending",
            )
            session.add(subscription)
            await session.commit()
            await session.refresh(subscription)

        return {
            "subscription_id": subscription.id,
            "period": plan.period,
            "period_label": plan.label,
            "period_days": plan.days,
            "amount": float(plan.amount),
            "payload": payload,
            "payment_id": payment_id,
            "url": confirmation_url,
            "checkout_mode": "external",
        }

    async def _create_telegram_invoice(
        self,
        master_telegram_id: int,
        master_bot_id: int | None,
        plan: YooKassaPlan,
        payload: str,
    ) -> dict:
        """Legacy fallback while shop API credentials are not configured."""
        provider_token = self._provider_token()
        if not settings.architect_token:
            raise ValueError("ARCHITECT_TOKEN не задан")
        proxy_url = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy") or settings.proxy_url
        session = AiohttpSession(proxy=proxy_url) if proxy_url else AiohttpSession()
        bot = Bot(token=settings.architect_token, session=session)
        try:
            invoice_url = await bot.create_invoice_link(
                title="Подписка Master Booking",
                description=f"Доступ к сервису на {plan.label}",
                payload=payload,
                provider_token=provider_token,
                currency=self.CURRENCY,
                prices=[LabeledPrice(label=f"Подписка на {plan.label}", amount=plan.amount_minor)],
            )
        finally:
            await bot.session.close()

        async with async_session_maker() as session:
            subscription = Subscription(
                master_telegram_id=master_telegram_id,
                master_bot_id=master_bot_id,
                period_days=plan.days,
                price=int(plan.amount),
                payment_provider=self.PROVIDER,
                payment_id=payload,
                status="pending",
            )
            session.add(subscription)
            await session.commit()
            await session.refresh(subscription)

        return {
            "subscription_id": subscription.id,
            "period": plan.period,
            "period_label": plan.label,
            "period_days": plan.days,
            "amount": float(plan.amount),
            "payload": payload,
            "url": invoice_url,
            "checkout_mode": "telegram",
        }

    async def get_payment(self, payment_id: str) -> dict:
        credentials = self._api_credentials()
        if not credentials:
            raise ValueError("YOOKASSA_SHOP_ID или YOOKASSA_SECRET_KEY не заданы")
        shop_id, secret_key = credentials
        async with httpx.AsyncClient(auth=(shop_id, secret_key), **self._client_kwargs()) as client:
            response = await client.get(f"https://api.yookassa.ru/v3/payments/{payment_id}")
            if response.status_code >= 400:
                logger.error("YooKassa get payment failed: %s", response.text)
            response.raise_for_status()
            return response.json()

    async def _get_pending(self, payload: str) -> Subscription | None:
        async with async_session_maker() as session:
            result = await session.execute(
                select(Subscription).where(
                    Subscription.payment_provider == self.PROVIDER,
                    Subscription.payment_id == payload,
                )
            )
            return result.scalar_one_or_none()

    async def validate_order(self, user_id: int, payload: str, currency: str, total_amount: int) -> str | None:
        """Return a user-facing error or None when the pending invoice is valid."""
        parsed = self._parse_payload(payload)
        if not parsed:
            return "Счёт повреждён. Создайте новый счёт в меню подписки."
        master_telegram_id, _, plan = parsed
        if int(user_id) != master_telegram_id:
            return "Этот счёт создан для другого пользователя."
        if currency != self.CURRENCY or total_amount != plan.amount_minor:
            return "Сумма счёта изменилась. Создайте новый счёт в меню подписки."
        subscription = await self._get_pending(payload)
        if not subscription or subscription.status != "pending":
            return "Счёт уже обработан или устарел. Создайте новый счёт."
        return None

    async def answer_pre_checkout(self, query: PreCheckoutQuery) -> None:
        error = await self.validate_order(
            query.from_user.id,
            query.invoice_payload,
            query.currency,
            query.total_amount,
        )
        await query.answer(ok=not error, error_message=error)

    async def handle_successful_payment(self, message: Message, subscription_service) -> bool:
        payment = message.successful_payment
        error = await self.validate_order(
            message.from_user.id,
            payment.invoice_payload,
            payment.currency,
            payment.total_amount,
        )
        if error:
            logger.error("Rejected successful YooKassa payment: %s", error)
            return False

        subscription = await subscription_service.activate_pending_subscription(
            payment_provider=self.PROVIDER,
            payment_id=payment.invoice_payload,
            telegram_payment_charge_id=payment.telegram_payment_charge_id,
            provider_payment_charge_id=payment.provider_payment_charge_id,
        )
        if not subscription:
            return False

        await message.answer(
            "✅ Оплата получена.\n\n"
            f"Подписка активирована на {subscription.period_days} дней. Ваш бот готов к работе."
        )
        return True


yookassa_payment = YooKassaPayment()
