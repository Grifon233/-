import logging
import hashlib
import hmac
import os
from datetime import date

from aiogram import Bot, Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, KeyboardButtonRequestUser
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from backend.database import async_session_maker
from backend.client_profiles import get_client_profile, normalize_full_name, normalize_phone, save_client_profile, sign_client_access
from backend.config import build_url, get_urls
from sqlalchemy import select

logger = logging.getLogger(__name__)

router = Router()
ARCHITECT_BOT_URL = "https://t.me/SoftwareArchitects_bot"
CLIENT_HELP_TEXT = (
    "ℹ️ <b>Как использовать бота</b>\n\n"
    "1. Чтобы записаться, нажмите кнопку «Записаться» и перейдите на сайт. В календаре выберите дату, "
    "затем подходящее свободное время. При необходимости оставьте комментарий и нажмите «Записаться». "
    "После этого мастер получит уведомление о вашей записи.\n\n"
    "2. Авторизация на сайте происходит автоматически через Telegram-аккаунт, из которого вы перешли. "
    "К записи прикрепляются ваши фамилия, имя и номер телефона.\n\n"
    "3. Если дата в календаре неактивна, запись на неё ещё не открыта или этот день недоступен.\n\n"
    "4. Если вы хотите записать другого человека, укажите его данные в комментарии."
)


class ClientRegistration(StatesGroup):
    waiting_for_contact = State()
    waiting_for_full_name = State()


def sign_auth_params(user_id: int) -> str | None:
    secret = os.getenv("AUTH_SIGNING_SECRET") or os.getenv("ARCHITECT_TOKEN")
    if not secret:
        return None
    payload = f"user={int(user_id)}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()

BOT_TOKEN = None
BOT_USERNAME = None


def set_bot_token(token: str):
    global BOT_TOKEN, BOT_USERNAME
    BOT_TOKEN = token
    import httpx
    try:
        response = httpx.get(f"https://api.telegram.org/bot{token}/getMe", timeout=5)
        data = response.json()
        if data.get("ok"):
            BOT_USERNAME = data["result"].get("username")
    except:
        pass


def get_web_url(path: str, params: dict = None) -> str:
    return build_url(path, params)


async def _find_bot_by_token(session, raw_token: str):
    """Найти MasterBot по сырому токену (с учётом шифрования)."""
    from backend.database import MasterBot
    from backend.token_utils import decrypt_token

    result = await session.execute(select(MasterBot))
    for b in result.scalars().all():
        if decrypt_token(b.token) == raw_token:
            return b
    return None


async def get_master_id_for_bot() -> int | None:
    if not BOT_TOKEN:
        return None

    from backend.database import MasterBot, Master

    async with async_session_maker() as session:
        bot = await _find_bot_by_token(session, BOT_TOKEN)
        if not bot:
            return None

        # Приоритет — закреплённый master_id в таблице ботов
        if bot.master_id:
            return bot.master_id

        # Fallback для старых ботов — поиск по telegram_id владельца
        result = await session.execute(
            select(Master).where(Master.telegram_id == bot.master_telegram_id)
        )
        master = result.scalar_one_or_none()

        return master.id if master else None


async def is_admin(user_telegram_id: int) -> tuple[bool, int | None]:
    if not BOT_TOKEN:
        return False, None

    from backend.database import MasterBot, Master

    async with async_session_maker() as session:
        bot = await _find_bot_by_token(session, BOT_TOKEN)
        if not bot:
            return False, None

        if user_telegram_id == bot.master_telegram_id:
            # Если у бота есть привязанный профиль, используем его
            if bot.master_id:
                return True, bot.master_id

            # Иначе ищем по telegram_id (для первого бота владельца)
            result = await session.execute(
                select(Master).where(Master.telegram_id == bot.master_telegram_id)
            )
            master = result.scalar_one_or_none()
            if not master:
                # Если профиля совсем нет — создаём его
                master = Master(
                    telegram_id=bot.master_telegram_id,
                    name="Мастер",
                    is_demo=False,
                    use_services=False,
                    interval_minutes=60,
                )
                session.add(master)
                await session.flush()
                # Сразу привязываем к боту
                bot.master_id = master.id
                await session.commit()
                await session.refresh(master)
                logger.warning(f"Created missing master profile for bot owner {bot.master_telegram_id}")
            else:
                # Привязываем существующий профиль, если он не был привязан
                bot.master_id = master.id
                await session.commit()
                
            return True, master.id

        return False, None


async def get_today_bookings(master_id: int):
    """Получает записи на сегодня для мастера"""
    from backend.database import Booking, Client

    today = date.today().isoformat()

    async with async_session_maker() as session:
        result = await session.execute(
            select(Booking, Client)
            .join(Client, Booking.client_id == Client.id)
            .where(Booking.master_id == master_id)
            .where(Booking.date == today)
            .where(Booking.status == "upcoming")
            .order_by(Booking.time)
        )
        bookings = result.all()

        return bookings


def admin_keyboard(telegram_id: int, master_id: int, first_name: str = None, username: str = None) -> InlineKeyboardMarkup:
    params = {"user": telegram_id, "master_id": master_id}
    sig = sign_auth_params(telegram_id)
    if sig:
        params["sig"] = sig
    if first_name:
        params["name"] = first_name
    if username:
        params["username"] = username

    calendar_url = get_web_url("/calendar", params)
    bot_url = f"https://t.me/{BOT_USERNAME}" if BOT_USERNAME else get_web_url("/call", {"master_id": master_id})

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Календарь", url=calendar_url)],
        [InlineKeyboardButton(text="📋 Мои записи", callback_data="my_bookings")],
        [InlineKeyboardButton(text="📤 Поделиться ссылкой на бота", callback_data="share_contact")],
        [InlineKeyboardButton(text="🔗 Создать URL-ссылку на вашего бота", url=bot_url)],
    ])
    return keyboard


def client_keyboard(master_id: int, telegram_id: int, first_name: str = None, username: str = None) -> InlineKeyboardMarkup:
    params = {
        "master_id": master_id,
        "user": telegram_id,
        "client_sig": sign_client_access(telegram_id, master_id, BOT_TOKEN),
    }
    if first_name:
        params["name"] = first_name
    if username:
        params["username"] = username
    client_url = get_web_url("/call", params)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Записаться", url=client_url)],
        [InlineKeyboardButton(text="ℹ️ Как использовать бота", callback_data="client_help")],
        [InlineKeyboardButton(text="🤖 Хочу себе такого же бота", url=ARCHITECT_BOT_URL)],
    ])
    return keyboard


def contact_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Поделиться номером телефона", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


async def ask_for_contact(message: Message, state: FSMContext) -> None:
    await state.set_state(ClientRegistration.waiting_for_contact)
    await message.answer(
        "Чтобы запись прошла спокойно и без ошибок, поделитесь номером телефона кнопкой ниже.\n\n"
        "Номер нужен только для связи по вашей записи. Вводить его вручную не потребуется.",
        reply_markup=contact_keyboard(),
    )


@router.message(CommandStart())
async def handle_start(message: Message, state: FSMContext):
    user = message.from_user

    is_admin_user, master_id = await is_admin(user.id)

    if is_admin_user and master_id:
        await message.answer(
            f"👋 Добро пожаловать, {user.first_name}!\n\n"
            "Вы вошли в рабочий режим.",
            reply_markup=admin_keyboard(user.id, master_id, user.first_name, user.username)
        )
    else:
        client_master_id = await get_master_id_for_bot()

        if client_master_id:
            async with async_session_maker() as session:
                profile = await get_client_profile(session, user.id)
            if not profile:
                await ask_for_contact(message, state)
                return
            await state.clear()
            await message.answer(
                f"👋 Добро пожаловать!\n\n"
                "Нажмите кнопку ниже чтобы записаться.",
                reply_markup=client_keyboard(client_master_id, user.id, user.first_name, user.username)
            )
        else:
            await message.answer(
                f"👋 Добро пожаловать!\n\n"
                "Бот временно недоступен. Попробуйте позже."
            )


@router.callback_query(F.data == "my_bookings")
async def show_my_bookings(callback: CallbackQuery, state: FSMContext):
    """Показывает записи на сегодня"""
    user = callback.from_user

    is_admin_user, master_id = await is_admin(user.id)

    if not is_admin_user or not master_id:
        await callback.answer("❌ Нет доступа")
        return

    bookings = await get_today_bookings(master_id)

    today = date.today().strftime("%d.%m.%Y")

    if not bookings:
        text = f"📋 Записи на {today}:\n\n❌ Записей нет"
    else:
        text = f"📋 Записи на {today}:\n\n"
        from backend.handlers.master_bot import booking_card_text
        text += "\n\n".join(booking_card_text(booking, client, i) for i, (booking, client) in enumerate(bookings, 1))

    text += "\n👇 Используйте кнопки ниже:"

    await callback.message.edit_text(
        text,
        reply_markup=admin_keyboard(user.id, master_id, user.first_name, user.username)
    )
    await callback.answer()


@router.callback_query(F.data == "client_help")
async def show_client_help(callback: CallbackQuery):
    master_id = await get_master_id_for_bot()
    if not master_id:
        await callback.answer("Бот временно недоступен", show_alert=True)
        return
    await callback.message.answer(CLIENT_HELP_TEXT, reply_markup=client_keyboard(master_id, callback.from_user.id, callback.from_user.first_name, callback.from_user.username))
    await callback.answer()


@router.callback_query(F.data == "share_contact")
async def request_share_contact(callback: CallbackQuery, state: FSMContext):
    """Запрос на выбор контакта"""
    user = callback.from_user

    is_admin_user, master_id = await is_admin(user.id)

    if not is_admin_user or not master_id:
        await callback.answer("❌ Нет доступа")
        return

    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👤 Выбрать контакт", request_user=KeyboardButtonRequestUser(request_id=1))]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )

    await callback.message.answer(
        "📤 Выберите контакт из списка, чтобы отправить ему приглашение:",
        reply_markup=keyboard
    )
    await callback.answer()


@router.message(F.user_shared)
async def handle_user_shared(message: Message, state: FSMContext):
    """Обработка выбранного контакта"""
    user = message.from_user
    shared_user_id = message.user_shared.user_id

    is_admin_user, master_id = await is_admin(user.id)

    if not is_admin_user or not master_id:
        return

    # Формируем ссылку на бота
    bot_link = f"https://t.me/{BOT_USERNAME}" if BOT_USERNAME else "нашего бота"

    try:
        bot_instance = Bot(token=BOT_TOKEN)

        await bot_instance.send_message(
            chat_id=shared_user_id,
            text=f"Вы можете записаться ко мне через этого бота: {bot_link}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📅 Записаться", url=bot_link)]
            ])
        )

        await bot_instance.session.close()

        # Отправляем подтверждение мастеру
        await message.answer(
            "✅ Сообщение отправлено выбранному контакту!",
            reply_markup=ReplyKeyboardRemove()
        )
        await message.answer(
            "👋 Главное меню:",
            reply_markup=admin_keyboard(user.id, master_id, user.first_name, user.username)
        )

        logger.info(f"Sent invite to user {shared_user_id} from master {user.id}")

    except Exception as e:
        logger.error(f"Failed to send message to user {shared_user_id}: {e}")
        await message.answer(
            f"❌ Не удалось отправить сообщение.\n\n"
            f"Пользователь должен был запустить этого бота: {bot_link}",
            reply_markup=ReplyKeyboardRemove()
        )
        await message.answer(
            "👋 Главное меню:",
            reply_markup=admin_keyboard(user.id, master_id, user.first_name, user.username)
        )


@router.message(ClientRegistration.waiting_for_contact, F.contact)
async def handle_contact(message: Message, state: FSMContext):
    contact = message.contact
    if not contact or contact.user_id != message.from_user.id:
        await message.answer("Отправьте именно свой номер кнопкой ниже.", reply_markup=contact_keyboard())
        return
    try:
        phone = normalize_phone(contact.phone_number)
    except ValueError:
        await message.answer("Telegram передал некорректный номер. Попробуйте ещё раз.", reply_markup=contact_keyboard())
        return
    await state.update_data(phone=phone)
    await state.set_state(ClientRegistration.waiting_for_full_name)
    await message.answer(
        "Спасибо, номер получен.\n\nТеперь напишите фамилию и имя через пробел. Например: Иванов Иван.",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(ClientRegistration.waiting_for_contact)
async def reject_contact_text(message: Message):
    await message.answer("Не вводите телефон текстом. Нажмите кнопку ниже.", reply_markup=contact_keyboard())


@router.message(ClientRegistration.waiting_for_full_name, F.text)
async def handle_full_name(message: Message, state: FSMContext):
    try:
        full_name = normalize_full_name(message.text)
    except ValueError as error:
        await message.answer(f"{error}.\n\nНапишите фамилию и имя через пробел. Например: Иванов Иван.")
        return
    data = await state.get_data()
    if not data.get("phone"):
        await ask_for_contact(message, state)
        return
    master_id = await get_master_id_for_bot()
    if not master_id:
        await state.clear()
        return
    async with async_session_maker() as session:
        await save_client_profile(session, message.from_user.id, message.from_user.username, data["phone"], full_name)
        await session.commit()
    await state.clear()
    await message.answer(
        "Готово. Данные сохранены, повторная регистрация в других ботах мастеров не потребуется.",
        reply_markup=client_keyboard(master_id, message.from_user.id, message.from_user.first_name, message.from_user.username),
    )
