import logging
from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from architect.keyboards.menu import architect_menu_keyboard, main_menu_keyboard
from architect.handlers.start import WELCOME_TEXT
from architect.services.referral_service import referral_service
from architect.services.subscription_service import subscription_service
from architect.services.yookassa_payment import yookassa_payment
from backend.database import MasterBot, Subscription, async_session_maker

logger = logging.getLogger(__name__)

router = Router()


class PromoCodeStates(StatesGroup):
    waiting_for_code = State()

SUBSCRIPTION_PERIODS = {
    "sub_1_month": "1_month",
    "sub_6_months": "6_months",
    "sub_12_months": "12_months",
}


async def _visible_owned_bots(master_telegram_id: int) -> list[MasterBot]:
    cutoff = datetime.utcnow() - timedelta(hours=2)
    async with async_session_maker() as session:
        bots = list((await session.execute(
            select(MasterBot).where(MasterBot.master_telegram_id == master_telegram_id).order_by(MasterBot.id)
        )).scalars().all())
        subs = list((await session.execute(
            select(Subscription).where(Subscription.master_telegram_id == master_telegram_id)
        )).scalars().all())
        # Бот виден в меню подписки, если у него КОГДА-ЛИБО была оформлена подписка
        # (в т.ч. истёкшая/замороженная) — иначе мастер после истечения не мог продлить.
        # Свежие "pending", которые уже протухли, не считаем.
        def _is_real_sub(sub: Subscription) -> bool:
            if sub.status == "pending" and not sub.paid_at:
                return (sub.created_at or datetime.utcnow()) > datetime.utcnow() - timedelta(hours=2)
            return True
        subbed_bot_ids = {sub.master_bot_id for sub in subs if sub.master_bot_id and _is_real_sub(sub)}
        # Подписка из ВКонтакте привязана к владельцу (master_bot_id IS NULL) и покрывает его ботов.
        has_master_level_sub = any(sub.master_bot_id is None and _is_real_sub(sub) for sub in subs)
    return [
        bot for bot in bots
        if bot.id in subbed_bot_ids
        or has_master_level_sub
        or (bot.trial_started_at or bot.created_at) > cutoff
    ]


def _plan_button_text(period: str) -> str:
    plan = yookassa_payment.get_plan(period)
    icon = {
        "1_month": "🥉",
        "6_months": "🥇",
        "12_months": "👑",
    }.get(period, "💳")
    return f"{icon} {plan.label} — {int(plan.amount)} ₽"


async def _subscription_intro(master_telegram_id: int, bot_label: str | None = None) -> tuple[str, bool]:
    code = await referral_service.ensure_code(master_telegram_id)
    can_use_promo = not await referral_service.has_paid_before(master_telegram_id)
    applied_code = await referral_service.get_applied_code(master_telegram_id)
    title = f"💳 Подписка для {bot_label}" if bot_label else "💳 Подписка на сервис"
    promo_line = f"Ваш промокод: <b>{code}</b>"
    if applied_code:
        promo_line = f"Применён промокод: <b>{applied_code}</b>\n{promo_line}"
    text = (
        f"{title}\n\n"
        "Выберите период подписки. После выбора откроется официальная страница YooKassa.\n\n"
        f"{promo_line}\n\n"
        "Поделитесь своим промокодом с другом. После его первой оплаты вы оба получите по одному "
        "подарочному месяцу подписки. Чем больше друзей оплатит сервис по вашему промокоду, "
        "тем больше бесплатных месяцев вы получите."
    )
    return text, can_use_promo


def _plans_keyboard(master_bot_id: int | None = None, can_use_promo: bool = False) -> InlineKeyboardMarkup:
    suffix = f":{master_bot_id}" if master_bot_id else ""
    rows = [
        [InlineKeyboardButton(text=_plan_button_text("1_month"), callback_data=f"sub_1_month{suffix}")],
        [InlineKeyboardButton(text=_plan_button_text("6_months"), callback_data=f"sub_6_months{suffix}")],
        [InlineKeyboardButton(text=_plan_button_text("12_months"), callback_data=f"sub_12_months{suffix}")],
        [InlineKeyboardButton(text="📋 Моя подписка", callback_data=f"my_subscription{suffix}")],
    ]
    if can_use_promo:
        rows.append([InlineKeyboardButton(text="🎁 Ввести промокод", callback_data="enter_promo_code")])
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "subscription")
async def subscription_menu(callback: CallbackQuery):
    text, can_use_promo = await _subscription_intro(callback.from_user.id)
    bots = await _visible_owned_bots(callback.from_user.id)

    if not bots:
        await callback.message.edit_text(
            "💳 Подписка\n\n"
            "У вас сейчас нет активных ботов. Сначала создайте бота, "
            "а потом оформляйте подписку — оплачивать её можно только при наличии активного бота.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🚀 Создать своего бота", callback_data="create_bot")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")],
            ]),
        )
        await callback.answer()
        return

    if len(bots) > 1:
        rows = [[InlineKeyboardButton(text=f"🤖 @{bot.username or bot.id}", callback_data=f"subscription_bot:{bot.id}")] for bot in bots]
        if can_use_promo:
            rows.append([InlineKeyboardButton(text="🎁 Ввести промокод", callback_data="enter_promo_code")])
        rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")])
        await callback.message.edit_text(
            f"{text}\n\nВыберите бота, для которого хотите оформить подписку.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        text,
        reply_markup=_plans_keyboard(bots[0].id if bots else None, can_use_promo),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("subscription_bot:"))
async def select_subscription_bot(callback: CallbackQuery):
    try:
        master_bot_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректный бот", show_alert=True)
        return
    async with async_session_maker() as session:
        bot = await session.get(MasterBot, master_bot_id)
    if not bot or bot.master_telegram_id != callback.from_user.id:
        await callback.answer("Бот не найден", show_alert=True)
        return
    text, can_use_promo = await _subscription_intro(callback.from_user.id, f"@{bot.username or bot.id}")
    await callback.message.edit_text(text, reply_markup=_plans_keyboard(bot.id, can_use_promo), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "enter_promo_code")
async def enter_promo_code(callback: CallbackQuery, state: FSMContext):
    if await referral_service.has_paid_before(callback.from_user.id):
        await callback.answer("Промокод можно применить только до первой оплаты", show_alert=True)
        return
    await state.set_state(PromoCodeStates.waiting_for_code)
    await callback.message.edit_text(
        "🎁 Введите промокод для получения бесплатного месяца подписки после первой оплаты.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="subscription")],
        ]),
    )
    await callback.answer()


@router.message(PromoCodeStates.waiting_for_code)
async def process_promo_code(message: Message, state: FSMContext):
    result = await referral_service.apply_code(message.from_user.id, message.text or "")
    await state.clear()
    await message.answer(
        ("✅ " if result.ok else "❌ ") + result.message,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 К подписке", callback_data="subscription")],
            [InlineKeyboardButton(text="◀️ В меню", callback_data="back_to_menu")],
        ]),
    )


@router.callback_query(F.data.startswith("sub_"))
async def select_subscription_period(callback: CallbackQuery):
    callback_name, _, bot_id_text = callback.data.partition(":")
    period = SUBSCRIPTION_PERIODS.get(callback_name)
    if not period:
        await callback.answer("Неизвестный тариф", show_alert=True)
        return

    master_id = callback.from_user.id
    master_bot_id = int(bot_id_text) if bot_id_text.isdigit() else None

    if master_bot_id is not None:
        async with async_session_maker() as session:
            bot = await session.get(MasterBot, master_bot_id)
        visible_bot_ids = {item.id for item in await _visible_owned_bots(master_id)}
        if not bot or bot.master_telegram_id != master_id or bot.id not in visible_bot_ids:
            await callback.answer("Бот не найден", show_alert=True)
            return
    elif not await _visible_owned_bots(master_id):
        await callback.answer(
            "Сначала создайте бота — подписку можно оплатить только при наличии активного бота.",
            show_alert=True,
        )
        return

    try:
        payment = await yookassa_payment.create_payment_link(master_id, period, master_bot_id)
        description = (
            "Для оплаты нажмите кнопку ниже. Откроется защищённая страница YooKassa, "
            "где будут доступны все способы оплаты, подключённые к вашему магазину."
            if payment.get("checkout_mode") == "external"
            else "Для оплаты нажмите кнопку ниже. Telegram откроет встроенную форму YooKassa. "
                 "Чтобы включить СБП и другие способы, добавьте на сервере YOOKASSA_SHOP_ID и YOOKASSA_SECRET_KEY."
        )
        await callback.message.edit_text(
            f"💳 Оформление подписки на {payment['period_label']}\n\n"
            f"Сумма: {payment['amount']:.0f} ₽\n\n"
            f"{description}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💰 Оплатить через YooKassa", url=payment["url"])],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="subscription")],
            ]),
            disable_web_page_preview=True,
        )
    except ValueError as e:
        logger.error("YooKassa payment is not configured: %s", e)
        await callback.message.edit_text(
            "❌ Оплата YooKassa пока не настроена.\n\n"
            "Для встроенной оплаты нужен YOOKASSA_PROVIDER_TOKEN, а для оплаты со СБП "
            "и внешней страницей нужны ещё YOOKASSA_SHOP_ID и YOOKASSA_SECRET_KEY.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="subscription")],
            ]),
        )
    except Exception as e:
        logger.error("Failed to create YooKassa payment link: %s", e)
        await callback.message.edit_text(
            "❌ Не удалось создать счёт. Попробуйте позже.",
            reply_markup=architect_menu_keyboard(user_id=callback.from_user.id),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("my_subscription"))
async def my_subscription(callback: CallbackQuery):
    master_id = callback.from_user.id
    _, _, bot_id_text = callback.data.partition(":")
    master_bot_id = int(bot_id_text) if bot_id_text.isdigit() else None

    if master_bot_id is None:
        async with async_session_maker() as session:
            bots = await _visible_owned_bots(master_id)
        if len(bots) > 1:
            await callback.message.edit_text(
                "📋 Состояние подписки\n\nВыберите бота, по которому нужно показать подписку.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    *[[InlineKeyboardButton(text=f"🤖 @{bot.username or bot.id}", callback_data=f"my_subscription:{bot.id}")] for bot in bots],
                    [InlineKeyboardButton(text="◀️ Назад", callback_data="subscription")],
                ]),
            )
            await callback.answer()
            return
        if bots:
            master_bot_id = bots[0].id

    status = await subscription_service.get_subscription_status(master_id, master_bot_id)

    if status["status"] == "no_subscription":
        text = (
            "📋 Состояние подписки\n\n"
            "У вас нет активной подписки.\n\n"
            "Оплатите подписку, чтобы пользоваться сервисом без ограничений."
        )
    elif status["status"] == "active":
        text = "✅ Подписка активна\n\n"
        if status.get("lifetime"):
            text += "До скончания времён"
        else:
            end_iso = status.get("end_date")
            end_human = "N/A"
            if end_iso:
                try:
                    end_human = datetime.fromisoformat(end_iso).strftime("%d.%m.%Y")
                except ValueError:
                    end_human = end_iso
            text += (
                f"Осталось дней: {status['days_left']}\n"
                f"До: {end_human}"
            )
    else:
        text = (
            "❌ Подписка не активна\n\n"
            "Выберите тариф и оплатите подписку через YooKassa."
        )

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оформить подписку", callback_data="subscription")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")],
        ]),
    )
    await callback.answer()


@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        WELCOME_TEXT,
        reply_markup=await main_menu_keyboard(callback.from_user.id),
    )
    await callback.answer()
