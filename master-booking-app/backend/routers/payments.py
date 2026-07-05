import logging

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from architect.services.subscription_service import subscription_service
from architect.services.yookassa_payment import yookassa_payment
from backend.database import Subscription, async_session_maker

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/payments/yookassa", tags=["payments"])


@router.post("/webhook")
async def yookassa_webhook(request: Request):
    payload = await request.json()
    event = payload.get("event")
    event_object = payload.get("object") or {}

    if event == "refund.succeeded":
        payment_id = event_object.get("payment_id")
        if not payment_id:
            return {"ok": True}

        # Не доверяем телу вебхука: его может прислать кто угодно, зная payment_id.
        # Перепроверяем у провайдера, что возврат действительно произошёл.
        try:
            payment = await yookassa_payment.get_payment(payment_id)
        except Exception:
            logger.exception("Failed to verify YooKassa refund for payment %s", payment_id)
            raise HTTPException(status_code=500, detail="Failed to verify refund")

        refunded_value = (payment.get("refunded_amount") or {}).get("value")
        try:
            refunded_ok = refunded_value is not None and float(refunded_value) > 0
        except (TypeError, ValueError):
            refunded_ok = False
        if not refunded_ok:
            logger.warning(
                "Ignoring unverified refund webhook for payment %s (provider shows no refund)",
                payment_id,
            )
            return {"ok": True}

        amount = event_object.get("amount") or {}
        await subscription_service.mark_subscription_refunded(
            payment_provider=yookassa_payment.CHECKOUT_PROVIDER,
            payment_id=payment_id,
            refund_id=event_object.get("id"),
            refund_amount=amount.get("value"),
        )
        return {"ok": True}

    payment_id = event_object.get("id")
    if event != "payment.succeeded" or not payment_id:
        return {"ok": True}

    try:
        payment = await yookassa_payment.get_payment(payment_id)
    except Exception:
        logger.exception("Failed to verify YooKassa payment %s", payment_id)
        raise HTTPException(status_code=500, detail="Failed to verify payment")

    if payment.get("status") != "succeeded":
        return {"ok": True}

    await subscription_service.activate_pending_subscription(
        payment_provider=yookassa_payment.CHECKOUT_PROVIDER,
        payment_id=payment_id,
        provider_payment_charge_id=payment_id,
    )
    return {"ok": True}


@router.get("/status")
async def payment_status(payment_id: str, request: Request):
    from backend.rate_limiter import client_ip_from_request, rate_limiter
    # Каждый вызов ходит в YooKassa — ограничиваем частоту, чтобы нельзя было
    # заспамить провайдера запросами от нашего магазина.
    if not await rate_limiter.check(f"payment-status:{client_ip_from_request(request)}"):
        raise HTTPException(status_code=429, detail="Слишком много запросов. Попробуйте позже.")
    async with async_session_maker() as session:
        subscription = (await session.execute(
            select(Subscription)
            .where(
                (Subscription.payment_id == payment_id)
                | (Subscription.telegram_payment_charge_id == payment_id)
                | (Subscription.provider_payment_charge_id == payment_id)
            )
            .order_by(Subscription.created_at.desc())
        )).scalars().first()
    if not subscription:
        raise HTTPException(status_code=404, detail="Платёж не найден")

    if subscription.payment_provider != yookassa_payment.CHECKOUT_PROVIDER:
        return {"status": subscription.status, "provider": subscription.payment_provider}
    if subscription.status == "refunded":
        return {
            "status": "refunded",
            "provider": subscription.payment_provider,
            "paid": False,
            "amount": {},
        }

    payment = await yookassa_payment.get_payment(subscription.payment_id)
    if payment.get("status") == "succeeded" and subscription.status == "pending":
        await subscription_service.activate_pending_subscription(
            payment_provider=subscription.payment_provider,
            payment_id=subscription.payment_id,
            provider_payment_charge_id=subscription.payment_id,
        )
    return {
        "status": payment.get("status"),
        "provider": subscription.payment_provider,
        "paid": payment.get("paid", False),
        "amount": payment.get("amount", {}),
    }
