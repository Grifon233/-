from aiogram import Router, F, Bot
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from datetime import datetime

from bot.utils.states import PollStates
from bot.keyboards.common import (
    get_send_keyboard,
    get_history_keyboard,
    get_retry_keyboard,
    get_athlete_panel,
    get_trainer_panel,
    get_trainer_poll_athletes_keyboard,
)
from bot.utils.parsers import parse_athlete_schedule, format_schedule
from bot.models.database import get_db, SundayPoll, FlightHistory, User
from bot.config import ATHLETES, TRAINER_ID, ATHLETE_IDS
from bot.services.scheduler import (
    get_upcoming_poll_date,
    notify_trainer_about_late_poll_response,
    poll_response_window_is_open,
)

router = Router()
router.message.filter(F.chat.type == "private")
router.callback_query.filter(F.message.chat.type == "private")

POLL_CANCEL_TEXT = "❌ Отмена"


@router.message(F.text == "/cancel")
async def cancel_poll_flow(message: Message, state: FSMContext):
    await _cancel_poll_response(message, state, "Текущее действие отменено.")


async def broadcast_poll(bot: Bot, poll_date: datetime):
    """
    Рассылает опрос всем спортсменам.
    Использует broadcast вместо цикла для надёжности.
    """
    sent_count = 0
    errors = []

    for telegram_id in ATHLETE_IDS:
        try:
            # Получаем последнее расписание для кнопки быстрого выбора
            with get_db() as db:
                last_history = db.query(FlightHistory).filter(
                    FlightHistory.telegram_id == telegram_id
                ).order_by(FlightHistory.created_at.desc()).first()
                last_schedule = last_history.schedule_text if last_history else None

            # Создаём запись опроса
            with get_db() as db:
                existing = db.query(SundayPoll).filter(
                    SundayPoll.poll_date == poll_date,
                    SundayPoll.telegram_id == telegram_id
                ).first()

                if not existing:
                    poll = SundayPoll(
                        poll_date=poll_date,
                        telegram_id=telegram_id
                    )
                    db.add(poll)
                    db.commit()

            # Формируем сообщение
            message_text = "Будете ли вы летать (тренироваться) на следующей неделе?"

            keyboard_buttons = []
            if last_schedule:
                short_schedule = last_schedule.replace("\n", ", ")
                if len(short_schedule) > 30:
                    short_schedule = short_schedule[:27] + "..."
                keyboard_buttons.append(f"Да, {short_schedule}")

            keyboard_buttons.extend(["Да", "Нет"])

            from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
            keyboard = ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text=b)] for b in keyboard_buttons],
                resize_keyboard=True,
                one_time_keyboard=True
            )

            # Отправляем сообщение
            await bot.send_message(
                telegram_id,
                message_text,
                reply_markup=keyboard
            )
            sent_count += 1
            print(f"Опрос отправлен {ATHLETES[telegram_id]['name']} ({telegram_id})")

        except Exception as e:
            error_msg = f"{ATHLETES.get(telegram_id, {'name': str(telegram_id)})['name']}: {e}"
            errors.append(error_msg)
            print(f"Ошибка отправки опроса {telegram_id}: {e}")

    return sent_count, errors


async def check_and_send_results(bot: Bot):
    """Совместимость: общий отчёт отправляет только планировщик в 17:00 ЕКБ."""
    return


def _poll_date_from_state(data: dict) -> datetime | None:
    raw_poll_date = data.get("poll_date")
    if isinstance(raw_poll_date, datetime):
        return raw_poll_date
    if isinstance(raw_poll_date, str):
        try:
            return datetime.fromisoformat(raw_poll_date)
        except ValueError:
            return None
    return None


def _poll_date_label(poll_date: datetime) -> str:
    return poll_date.strftime("%d.%m")


def _target_telegram_id(message_user_id: int, data: dict) -> int:
    return int(data.get("proxy_telegram_id") or message_user_id)


def _is_proxy_answer(data: dict) -> bool:
    return bool(data.get("proxy_telegram_id"))


def _reply_panel_for_sender(sender_id: int):
    if sender_id == TRAINER_ID:
        return get_trainer_panel()
    if sender_id in ATHLETE_IDS:
        return _get_athlete_panel_for_user(sender_id)
    return None


def _target_name(telegram_id: int) -> str:
    athlete = ATHLETES.get(telegram_id)
    return athlete["name"] if athlete else str(telegram_id)


def _get_athlete_panel_for_user(telegram_id: int):
    with get_db() as db:
        user = db.query(User).filter(User.telegram_id == telegram_id).first()
        notifications_enabled = True if not user else bool(user.notifications_enabled)
    return get_athlete_panel(notifications_enabled)


def _cancel_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=POLL_CANCEL_TEXT)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )


def _ensure_poll_record(telegram_id: int, poll_date: datetime) -> None:
    with get_db() as db:
        existing = db.query(SundayPoll).filter(
            SundayPoll.poll_date == poll_date,
            SundayPoll.telegram_id == telegram_id
        ).first()
        if existing:
            return
        db.add(SundayPoll(poll_date=poll_date, telegram_id=telegram_id))
        db.commit()


def _delete_empty_future_poll_record(telegram_id: int, poll_date: datetime | None) -> bool:
    if not poll_date:
        return False
    if poll_response_window_is_open(poll_date):
        return False
    if poll_date != get_upcoming_poll_date():
        return False

    with get_db() as db:
        poll = db.query(SundayPoll).filter(
            SundayPoll.poll_date == poll_date,
            SundayPoll.telegram_id == telegram_id
        ).first()
        if not poll:
            return False
        if (
            poll.responded_at is not None
            or poll.will_fly is not None
            or poll.schedule_text
            or poll.comment
        ):
            return False

        db.delete(poll)
        db.commit()
        return True


def _early_poll_response_is_allowed(poll_date: datetime) -> bool:
    return (
        poll_date == get_upcoming_poll_date()
        or poll_response_window_is_open(poll_date)
    )


def _get_open_poll_date_for_trainer() -> datetime | None:
    with get_db() as db:
        latest_poll = db.query(SundayPoll).order_by(SundayPoll.poll_date.desc()).first()
        if not latest_poll:
            return None
        poll_date = latest_poll.poll_date

    if not poll_response_window_is_open(poll_date):
        return None

    return poll_date


def _waiting_athlete_ids_for_poll(poll_date: datetime) -> list[int]:
    with get_db() as db:
        waiting_polls = db.query(SundayPoll).filter(
            SundayPoll.poll_date == poll_date,
            SundayPoll.responded_at == None
        ).all()
    return [
        poll.telegram_id
        for poll in waiting_polls
        if poll.telegram_id in ATHLETE_IDS
    ]


async def _cancel_poll_response(
    message: Message,
    state: FSMContext,
    fallback_text: str = "Действие отменено.",
) -> None:
    data = await state.get_data()
    poll_date = _poll_date_from_state(data)
    telegram_id = _target_telegram_id(message.from_user.id, data)
    is_early_response = bool(data.get("early_poll"))
    is_proxy_response = _is_proxy_answer(data)

    deleted = False
    if is_early_response and not is_proxy_response:
        deleted = _delete_empty_future_poll_record(telegram_id, poll_date)

    await state.clear()

    if is_proxy_response:
        text = f"Ответ за {_target_name(telegram_id)} отменён."
    elif deleted:
        text = "Ответ заранее отменён. В воскресенье я задам вопрос как обычно."
    else:
        text = fallback_text

    await message.answer(text, reply_markup=_reply_panel_for_sender(message.from_user.id))


def _poll_answer_keyboard(telegram_id: int) -> ReplyKeyboardMarkup:
    with get_db() as db:
        history = db.query(FlightHistory).filter(
            FlightHistory.telegram_id == telegram_id
        ).order_by(FlightHistory.created_at.desc()).first()
        last_schedule = history.schedule_text if history else None

    keyboard_buttons = []
    if last_schedule:
        short_schedule = last_schedule.replace("\n", ", ")
        if len(short_schedule) > 30:
            short_schedule = short_schedule[:27] + "..."
        keyboard_buttons.append(KeyboardButton(text=f"Да, {short_schedule}"))

    keyboard_buttons.extend([
        KeyboardButton(text="Да"),
        KeyboardButton(text="Нет"),
        KeyboardButton(text=POLL_CANCEL_TEXT),
    ])
    return ReplyKeyboardMarkup(
        keyboard=[[button] for button in keyboard_buttons],
        resize_keyboard=True,
        one_time_keyboard=True
    )


def _save_poll_response(
    telegram_id: int,
    poll_date: datetime,
    will_fly: bool,
    schedule_text: str | None = None,
    comment: str | None = None,
) -> None:
    with get_db() as db:
        poll = db.query(SundayPoll).filter(
            SundayPoll.poll_date == poll_date,
            SundayPoll.telegram_id == telegram_id
        ).first()

        if not poll:
            poll = SundayPoll(poll_date=poll_date, telegram_id=telegram_id)
            db.add(poll)

        poll.will_fly = will_fly
        poll.schedule_text = schedule_text if will_fly else None
        poll.comment = comment
        poll.responded_at = datetime.now()

        if will_fly and schedule_text:
            db.add(FlightHistory(telegram_id=telegram_id, schedule_text=schedule_text))

        db.commit()


async def _ensure_poll_is_open(message: Message, state: FSMContext) -> bool:
    data = await state.get_data()
    telegram_id = _target_telegram_id(message.from_user.id, data)
    poll_date = _poll_date_from_state(data)
    is_early_response = bool(data.get("early_poll"))

    with get_db() as db:
        if poll_date:
            poll = db.query(SundayPoll).filter(
                SundayPoll.telegram_id == telegram_id,
                SundayPoll.poll_date == poll_date
            ).first()
        else:
            poll = db.query(SundayPoll).filter(
                SundayPoll.telegram_id == telegram_id,
                SundayPoll.responded_at == None
            ).order_by(SundayPoll.poll_date.desc()).first()

    if poll and is_early_response and _early_poll_response_is_allowed(poll.poll_date):
        await state.update_data(poll_date=poll.poll_date.isoformat(), early_poll=True)
        return True

    if poll and poll.responded_at is None and poll_response_window_is_open(poll.poll_date):
        await state.update_data(poll_date=poll.poll_date.isoformat(), early_poll=False)
        return True

    await state.clear()
    await message.answer(
        "Опрос уже закрыт. Ответы принимаются в воскресенье с 12:00 до 20:00 "
        "по Екатеринбургу."
    )
    return False


@router.message(F.text == "📝 Ответить заранее")
async def start_early_poll_response(message: Message, state: FSMContext):
    """Постоянная кнопка для ответа на ближайший воскресный опрос заранее."""
    telegram_id = message.from_user.id
    athlete = ATHLETES.get(telegram_id)
    if telegram_id not in ATHLETE_IDS or not athlete:
        return

    poll_date = get_upcoming_poll_date()
    _ensure_poll_record(telegram_id, poll_date)

    await state.clear()
    await state.update_data(poll_date=poll_date.isoformat(), early_poll=True)
    await state.set_state(PollStates.waiting_for_answer)

    await message.answer(
        f"Ответ заранее на опрос {_poll_date_label(poll_date)}.\n"
        "Будете ли вы летать (тренироваться) на следующей неделе?",
        reply_markup=_poll_answer_keyboard(telegram_id)
    )


@router.message(F.text == "📝 Ответ за спортсмена", F.from_user.id == TRAINER_ID)
async def start_trainer_proxy_poll_response(message: Message, state: FSMContext):
    """Тренер отвечает за спортсмена только во время активного воскресного опроса."""
    await state.clear()
    poll_date = _get_open_poll_date_for_trainer()
    if not poll_date:
        await message.answer(
            "Сейчас нет активного опроса. Ответ за спортсмена доступен только "
            "в воскресенье с 12:00 до 20:00 по Екатеринбургу, после запуска опроса.",
            reply_markup=get_trainer_panel()
        )
        return

    waiting_ids = _waiting_athlete_ids_for_poll(poll_date)
    if not waiting_ids:
        await message.answer(
            f"По опросу {_poll_date_label(poll_date)} все спортсмены уже ответили.",
            reply_markup=get_trainer_panel()
        )
        return

    await message.answer(
        f"Опрос {_poll_date_label(poll_date)} активен. "
        "Выберите спортсмена, за которого нужно ответить:",
        reply_markup=get_trainer_poll_athletes_keyboard(waiting_ids)
    )


@router.callback_query(F.data == "trainer_poll_cancel", F.from_user.id == TRAINER_ID)
async def cancel_trainer_proxy_poll_response(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Ответ за спортсмена отменён.")
    await callback.answer()


@router.callback_query(F.data.startswith("trainer_poll_athlete:"), F.from_user.id == TRAINER_ID)
async def choose_trainer_proxy_poll_athlete(callback: CallbackQuery, state: FSMContext):
    telegram_id = int(callback.data.split(":", 1)[1])
    athlete = ATHLETES.get(telegram_id)
    if telegram_id not in ATHLETE_IDS or not athlete:
        await callback.answer("Спортсмен не найден.", show_alert=True)
        return

    poll_date = _get_open_poll_date_for_trainer()
    if not poll_date:
        await state.clear()
        await callback.message.edit_text(
            "Опрос уже закрыт или ещё не запущен. Ответ за спортсмена доступен "
            "только во время активного воскресного опроса."
        )
        await callback.answer()
        return

    with get_db() as db:
        poll = db.query(SundayPoll).filter(
            SundayPoll.poll_date == poll_date,
            SundayPoll.telegram_id == telegram_id
        ).first()

    if not poll:
        await callback.answer("Для этого спортсмена нет активного вопроса.", show_alert=True)
        return
    if poll.responded_at is not None:
        await callback.answer("Этот спортсмен уже ответил.", show_alert=True)
        return

    await state.clear()
    await state.update_data(
        poll_date=poll_date.isoformat(),
        early_poll=False,
        proxy_telegram_id=telegram_id,
    )
    await state.set_state(PollStates.waiting_for_answer)

    await callback.message.edit_text(
        f"Ответ за спортсмена: {athlete['name']}\n"
        f"Опрос: {_poll_date_label(poll_date)}\n\n"
        "Будет летать на следующей неделе?"
    )
    await callback.message.answer(
        "Выберите ответ:",
        reply_markup=_poll_answer_keyboard(telegram_id)
    )
    await callback.answer()


@router.message(
    StateFilter(
        PollStates.waiting_for_answer,
        PollStates.waiting_for_no_comment,
        PollStates.waiting_for_schedule,
        PollStates.waiting_for_comment,
    ),
    F.text == POLL_CANCEL_TEXT,
)
async def cancel_poll_response_button(message: Message, state: FSMContext):
    await _cancel_poll_response(message, state)


@router.message(PollStates.waiting_for_answer)
async def process_poll_answer(message: Message, state: FSMContext, bot: Bot):
    """Обработка ответа на воскресный опрос"""
    if not await _ensure_poll_is_open(message, state):
        return

    answer = message.text or ""
    data = await state.get_data()
    telegram_id = _target_telegram_id(message.from_user.id, data)
    poll_date = _poll_date_from_state(data)
    if not poll_date:
        await state.clear()
        await message.answer(
            "Активный опрос не найден.",
            reply_markup=_reply_panel_for_sender(message.from_user.id)
        )
        return

    # Логика "Быстрого ответа" (Да, расписание)
    if answer.startswith("Да, "):
        last_schedule = None
        with get_db() as db:
            history = db.query(FlightHistory).filter(
                FlightHistory.telegram_id == telegram_id
            ).order_by(FlightHistory.created_at.desc()).first()
            if history:
                last_schedule = history.schedule_text

        if last_schedule:
            _save_poll_response(telegram_id, poll_date, True, schedule_text=last_schedule)
            if _is_proxy_answer(data):
                text = f"Ответ за {_target_name(telegram_id)} отправлен (как в прошлый раз)."
            else:
                text = "Ваш ответ (как в прошлый раз) отправлен."
            await message.answer(text, reply_markup=_reply_panel_for_sender(message.from_user.id))
            await state.clear()
            await notify_trainer_about_late_poll_response(bot, telegram_id)
            return

    if answer not in ["Да", "Нет"]:
        await message.answer(
            "Пожалуйста, нажмите кнопку «Да», «Нет» или кнопку быстрого выбора.",
            reply_markup=_poll_answer_keyboard(telegram_id)
        )
        return

    await state.update_data(will_fly=(answer == "Да"))

    if answer == "Нет":
        await message.answer(
            "Напишите текстом комментарий почему нет и отправьте. "
            "Отправка комментария не обязательна, если вы нажмёте отправить без текста.",
            reply_markup=get_send_keyboard(include_cancel=True)
        )
        await state.set_state(PollStates.waiting_for_no_comment)
    else:
        with get_db() as db:
            history = db.query(FlightHistory).filter(
                FlightHistory.telegram_id == telegram_id
            ).order_by(FlightHistory.created_at.desc()).limit(10).all()

        unique_history = []
        seen_texts = set()
        for h in history:
            if h.schedule_text not in seen_texts:
                unique_history.append(h.schedule_text)
                seen_texts.add(h.schedule_text)
            if len(unique_history) == 4:
                break

        message_text = (
            "Напишите, когда вы планируете летать, сначала день недели, "
            "потом со скольки и до скольки. Пример:\n"
            "пн с 14 до 22\n"
            "ср с 16 до 22"
        )

        if unique_history:
            await message.answer(message_text, reply_markup=get_history_keyboard(unique_history))
            await message.answer(
                "Можно выбрать вариант из истории, написать время текстом или отменить ответ.",
                reply_markup=_cancel_reply_keyboard()
            )
        else:
            await message.answer(message_text, reply_markup=_cancel_reply_keyboard())

        await state.set_state(PollStates.waiting_for_schedule)


@router.message(PollStates.waiting_for_no_comment)
async def process_no_comment(message: Message, state: FSMContext, bot: Bot):
    """Обработка комментария при отказе"""
    if not await _ensure_poll_is_open(message, state):
        return

    data = await state.get_data()
    telegram_id = _target_telegram_id(message.from_user.id, data)
    if message.text is None:
        await message.answer(
            "Отправьте комментарий текстом или нажмите «Отправить».",
            reply_markup=get_send_keyboard(include_cancel=True)
        )
        return
    if message.text.startswith("/"):
        await message.answer("Сначала завершите ввод или используйте /cancel.")
        return
    comment = message.text if message.text != "Отправить" else None
    poll_date = _poll_date_from_state(data)

    if not poll_date:
        await message.answer("Активный опрос не найден или уже был обработан.")
        await state.clear()
        return

    _save_poll_response(telegram_id, poll_date, False, comment=comment)

    text = f"Ответ за {_target_name(telegram_id)} отправлен" if _is_proxy_answer(data) else "Ваш ответ отправлен"
    await message.answer(text, reply_markup=_reply_panel_for_sender(message.from_user.id))
    await state.clear()
    await notify_trainer_about_late_poll_response(bot, telegram_id)


@router.message(PollStates.waiting_for_schedule)
async def process_schedule(message: Message, state: FSMContext):
    """Обработка расписания полётов"""
    if not await _ensure_poll_is_open(message, state):
        return

    data = await state.get_data()
    telegram_id = _target_telegram_id(message.from_user.id, data)
    text = message.text or message.caption
    if not text:
        await message.answer(
            "Расписание нужно отправить текстом.",
            reply_markup=_cancel_reply_keyboard()
        )
        return
    if text.startswith("/"):
        await message.answer("Сначала завершите ввод или используйте /cancel.")
        return

    schedule = parse_athlete_schedule(text)

    if not schedule:
        await message.answer(
            "Мне не удалось понять, укажите ваше время ещё раз. Пример:\n"
            "пн с 14 до 22\n"
            "ср с 16 до 22",
            reply_markup=_cancel_reply_keyboard()
        )
        return

    formatted = format_schedule(schedule)
    await state.update_data(schedule_text=text, formatted_schedule=formatted)

    await message.answer(
        f"Вы выбрали время:\n{formatted}\n\n"
        "Напишите комментарий к полёту, если он есть, и отправьте. "
        "Отправка комментария не обязательна.",
        reply_markup=get_retry_keyboard()
    )
    await message.answer("Отправить", reply_markup=get_send_keyboard(include_cancel=True))
    await state.set_state(PollStates.waiting_for_comment)


@router.callback_query(PollStates.waiting_for_comment, F.data == "retry_schedule")
async def retry_schedule(callback: CallbackQuery, state: FSMContext):
    """Повторный ввод расписания"""
    await callback.message.answer(
        "Укажите ваше время ещё раз. Пример:\n"
        "пн с 14 до 22\n"
        "ср с 16 до 22",
        reply_markup=_cancel_reply_keyboard()
    )
    await state.set_state(PollStates.waiting_for_schedule)
    await callback.answer()


@router.callback_query(PollStates.waiting_for_schedule, F.data.startswith("history_"))
async def use_history(callback: CallbackQuery, state: FSMContext):
    """Использование истории полётов"""
    data = await state.get_data()
    telegram_id = _target_telegram_id(callback.from_user.id, data)
    history_idx = int(callback.data.split("_")[1])

    with get_db() as db:
        history = db.query(FlightHistory).filter(
            FlightHistory.telegram_id == telegram_id
        ).order_by(FlightHistory.created_at.desc()).limit(4).all()

    if history_idx < len(history):
        schedule_text = history[history_idx].schedule_text
        schedule = parse_athlete_schedule(schedule_text)
        if not schedule:
            await callback.message.answer("История больше не распознаётся. Введите расписание заново.")
            await state.set_state(PollStates.waiting_for_schedule)
            await callback.answer()
            return

        formatted = format_schedule(schedule)
        await state.update_data(schedule_text=schedule_text, formatted_schedule=formatted)

        await callback.message.answer(
            f"Вы выбрали время:\n{formatted}\n\n"
            "Напишите комментарий к полёту, если он есть, и отправьте.",
            reply_markup=get_retry_keyboard()
        )
        await callback.message.answer("Отправить", reply_markup=get_send_keyboard(include_cancel=True))
        await state.set_state(PollStates.waiting_for_comment)

    await callback.answer()


@router.message(PollStates.waiting_for_comment)
async def process_comment(message: Message, state: FSMContext, bot: Bot):
    """Обработка комментария к полёту"""
    if not await _ensure_poll_is_open(message, state):
        return

    data = await state.get_data()
    telegram_id = _target_telegram_id(message.from_user.id, data)

    if message.text is None:
        await message.answer(
            "Отправьте комментарий текстом или нажмите «Отправить».",
            reply_markup=get_send_keyboard(include_cancel=True)
        )
        return
    if message.text.startswith("/"):
        await message.answer("Сначала завершите ввод или используйте /cancel.")
        return

    comment = message.text if message.text != "Отправить" else None
    poll_date = _poll_date_from_state(data)

    if not poll_date:
        await message.answer("Активный опрос не найден или уже был обработан.")
        await state.clear()
        return

    _save_poll_response(
        telegram_id,
        poll_date,
        True,
        schedule_text=data.get("schedule_text"),
        comment=comment
    )

    text = f"Ответ за {_target_name(telegram_id)} отправлен" if _is_proxy_answer(data) else "Ваш ответ отправлен"
    await message.answer(text, reply_markup=_reply_panel_for_sender(message.from_user.id))
    await state.clear()
    await notify_trainer_about_late_poll_response(bot, telegram_id)
