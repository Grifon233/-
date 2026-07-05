"""Telegram Payments handlers for YooKassa invoices."""
import logging

from aiogram import F, Router

from architect.services.subscription_service import subscription_service
from architect.services.yookassa_payment import yookassa_payment

logger = logging.getLogger(__name__)
router = Router()


@router.pre_checkout_query(F.invoice_payload.startswith("yookassa:"))
async def pre_checkout_query(query):
    await yookassa_payment.answer_pre_checkout(query)


@router.message(F.successful_payment.invoice_payload.startswith("yookassa:"))
async def successful_payment(message):
    try:
        activated = await yookassa_payment.handle_successful_payment(message, subscription_service)
    except Exception:
        logger.exception("Failed to activate YooKassa Telegram payment")
        activated = False

    if not activated:
        await message.answer(
            "⚠️ Оплата получена, но автоматическая активация не завершилась.\n"
            "Напишите в поддержку и приложите квитанцию из этого чата."
        )
