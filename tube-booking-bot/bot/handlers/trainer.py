from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from datetime import datetime
import uuid
import asyncio
import logging

from bot.utils.parsers import (
    parse_trainer_message,
    get_unparseable_warning,
    resolve_training_datetime,
)
from bot.utils.states import TrainerStates
from bot.models.database import get_db, Training, TrainerMessage, VideoCheck
from bot.config import ATHLETES, TRAINER_ID, FORUM_CHAT_ID, FORUM_MESSAGE_THREAD_ID
from bot.services.yandex_disk import yandex_disk
from bot.services.llm_service import llm_service
from bot.keyboards.common import (
    get_confirm_schedule_keyboard,
)

router = Router()
router.message.filter(F.chat.type == "private")
router.callback_query.filter(F.message.chat.type == "private")
logger = logging.getLogger(__name__)

MAX_TELEGRAM_MESSAGE_LENGTH = 4096


def _training_delete_keyboard(trainings: list[Training]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{training.athlete_name} {training.date} {training.time}",
            callback_data=f"trainer_training:{training.id}"
        )]
        for training in trainings
    ])


def _format_confirmation_message(trainings: list) -> str:
    """Форматирует сообщение с подтверждением расписания."""
    lines = ["📋 Подтвердите расписание:\n"]
    for t in trainings:
        date_str = t.get('date', 'ДАТА?')
        lines.append(f"✅ {t['name']} — {date_str} {t['time']}")

    lines.append("\nОтправляем уведомления спортсменам?")
    return "\n".join(lines)


async def _send_training_notifications(trainings: list, bot: Bot):
    """Отправляет уведомления спортсменам о тренировках."""
    for training in trainings:
        telegram_id = training["telegram_id"]
        athlete_name = training["name"]
        date = training["date"]
        time = training["time"]
        public_link = training.get("public_link", "")

        notification_text = (
            f"🏋️ Ваша тренировка назначена:\n"
            f"📅 Дата: {date}\n"
            f"🕐 Время: {time}\n\n"
        )
        if public_link:
            notification_text += f"📁 Ссылка на папку для видео:\n{public_link}"
        else:
            notification_text += "⚠️ Не удалось создать папку для видео. Свяжитесь с тренером."
        try:
            await bot.send_message(telegram_id, notification_text)
        except Exception as e:
            print(f"Ошибка отправки уведомления {telegram_id}: {e}")


async def _publish_to_group(trainings: list, bot: Bot):
    """Публикует расписание в форум."""
    by_date = {}
    for t in trainings:
        date = t["date"]
        if date not in by_date:
            by_date[date] = []
        by_date[date].append(t)

    message_lines = []
    for date in sorted(by_date.keys()):
        message_lines.append(f"\n📅 {date}")
        for t in sorted(by_date[date], key=lambda x: x["time"]):
            message_lines.append(f"  {t['time']} - {t['name']}")

    message_text = "📋 Расписание тренировок:" + "\n".join(message_lines)

    chunks = []
    current_chunk = ""
    for line in message_text.splitlines(keepends=True):
        if len(current_chunk) + len(line) > MAX_TELEGRAM_MESSAGE_LENGTH:
            if current_chunk:
                chunks.append(current_chunk.rstrip())
            current_chunk = line
        else:
            current_chunk += line
    if current_chunk:
        chunks.append(current_chunk.rstrip())

    try:
        kwargs = {"chat_id": FORUM_CHAT_ID}
        if FORUM_MESSAGE_THREAD_ID is not None:
            kwargs["message_thread_id"] = FORUM_MESSAGE_THREAD_ID
        for chunk in chunks:
            await bot.send_message(**kwargs, text=chunk)
        print(f"Расписание опубликовано в форум: {len(trainings)} тренировок")
        return True
    except Exception as e:
        print(f"Ошибка публикации в форум: {e}")
        return False


async def _create_training_records(trainings: list[dict], original_text: str) -> list[dict]:
    """Создать записи тренировок и папки на Яндекс.Диске."""
    processed_trainings = []
    batch_id = uuid.uuid4().hex

    with get_db() as db:
        for training in trainings:
            telegram_id = training["telegram_id"]
            athlete_name = training["name"]
            date = training["date"]
            time = training["time"]
            training_dt = resolve_training_datetime(date, time)
            if not training_dt:
                raise ValueError(f"Не удалось разобрать дату/время: {athlete_name} {date} {time}")
            if training_dt < datetime.now(training_dt.tzinfo):
                raise ValueError(f"Нельзя назначить тренировку в прошлое: {athlete_name} {date} {time}")

            existing = db.query(Training).filter(
                Training.telegram_id == telegram_id,
                Training.date == date,
                Training.time == time
            ).first()

            if existing:
                processed_trainings.append({
                    "telegram_id": telegram_id,
                    "name": athlete_name,
                    "date": date,
                    "time": time,
                    "public_link": existing.yandex_folder_url,
                    "existing": True,
                })
                continue

            folder_path, public_link = await yandex_disk.create_training_folder(athlete_name, date)
            if not folder_path or not public_link:
                raise RuntimeError(f"Не удалось создать папку на Яндекс.Диске: {athlete_name} {date}")

            training_obj = Training(
                telegram_id=telegram_id,
                athlete_name=athlete_name,
                date=date,
                time=time,
                yandex_folder_path=folder_path,
                yandex_folder_url=public_link
            )
            db.add(training_obj)

            db.add(TrainerMessage(
                message_text=original_text,
                parsed_data=training,
                batch_id=batch_id
            ))

            processed_trainings.append({
                "telegram_id": telegram_id,
                "name": athlete_name,
                "date": date,
                "time": time,
                "public_link": public_link,
                "existing": False,
            })

        db.commit()

    return processed_trainings


_worker_tasks: dict[int, asyncio.Task] = {}
_queues: dict[int, asyncio.Queue] = {}
_pending_confirmation: set[int] = set()  # user_ids с ожидающим подтверждением
_pending_request_ids: dict[int, str] = {}
_input_revisions: dict[int, int] = {}


async def _trainer_buffer_worker(
    user_id: int,
    chat_id: int,
    bot: Bot,
    state: FSMContext,
    input_revision: int,
    debounce_seconds: float = 2.0
):
    """
    Воркер, который накапливает текст от user_id через очередь.
    Ждёт первое сообщение, затем ждёт ещё debounce_seconds на следующие.
    По истечении таймаута — обрабатывает всё накопленное.
    """
    queue: asyncio.Queue = _queues.get(user_id)
    buffer: list[str] = []

    # Ждём первое сообщение без таймаута
    first_msg = await queue.get()
    buffer.append(first_msg)

    while True:
        try:
            # Каждый раз новый таймаут — отсчитывается от последнего прочитанного сообщения
            msg_text = await asyncio.wait_for(queue.get(), timeout=debounce_seconds)
            buffer.append(msg_text)
        except asyncio.TimeoutError:
            # Таймаут — окно закончилось
            break

    _queues.pop(user_id, None)
    _worker_tasks.pop(user_id, None)

    if not buffer:
        return

    combined_text = "\n".join(buffer)
    logger.info(f"[Debounce] Обработано {len(buffer)} сообщений: {combined_text[:100]}")

    try:
        await bot.send_chat_action(chat_id, "typing")
        
        # Обычные тренерские форматы разбираем локально и детерминированно.
        trainings = parse_trainer_message(combined_text)

        # ИИ используется только для действительно свободной формулировки.
        if not trainings:
            logger.info("Local parser returned nothing, trying AI fallback")
            try:
                trainings = await asyncio.wait_for(
                    llm_service.parse_schedule(combined_text),
                    timeout=10
                )
            except Exception as e:
                logger.warning(f"AI parsing failed or timed out: {e}")
                trainings = None

        if not trainings:
            await bot.send_message(chat_id, get_unparseable_warning(combined_text))
            return

        if any(isinstance(item, dict) and item.get("conflict") for item in trainings):
            await bot.send_message(chat_id, "⚠️ Не удалось однозначно определить спортсмена. Уточните фамилию полностью.")
            return

        if _input_revisions.get(user_id) != input_revision:
            logger.info("Ignoring stale trainer parse result for revision %s", input_revision)
            return

        logger.info(f"[Debounce] Parsed {len(trainings)} trainings: {trainings}")

        request_id = uuid.uuid4().hex
        _pending_confirmation.add(user_id)
        _pending_request_ids[user_id] = request_id
        await state.update_data(original_text=combined_text, parsed_trainings=trainings, confirmation_request_id=request_id)
        await state.set_state(TrainerStates.waiting_for_schedule_confirmation)
        await bot.send_message(chat_id, _format_confirmation_message(trainings),
                              reply_markup=get_confirm_schedule_keyboard(request_id))
    except Exception as e:
        logger.error(f"Error in trainer_buffer_worker: {e}", exc_info=True)
        _pending_confirmation.discard(user_id)
        _pending_request_ids.pop(user_id, None)
        await bot.send_message(chat_id, f"Ошибка: {e}")


@router.message(F.text == "🎬 Старт", F.from_user.id == TRAINER_ID)
async def trainer_start_info(message: Message):
    """Информация для тренера по кнопке Старт"""
    await message.answer(
        "👋 Привет, Тренер!\n\n"
        "Чтобы назначить тренировки, просто пришли сообщение в свободном формате.\n"
        "Например:\n"
        "• пн Ваня 14:00, Серега 16:00\n"
        "• Завтра Кочуров в 15\n\n"
        "Я постараюсь понять тебя с помощью ИИ!"
    )


@router.message(F.text == "🗓 Тренировки", F.from_user.id == TRAINER_ID)
async def trainer_trainings(message: Message):
    """Показать тренеру назначенные тренировки."""
    with get_db() as db:
        trainings = db.query(Training).order_by(Training.id.desc()).limit(50).all()

    if not trainings:
        await message.answer("Назначенных тренировок нет.")
        return

    await message.answer(
        "Выберите тренировку, которую хотите удалить:",
        reply_markup=_training_delete_keyboard(trainings)
    )


@router.callback_query(F.data.startswith("trainer_training:"), F.from_user.id == TRAINER_ID)
async def trainer_training_delete_confirmation(callback: CallbackQuery):
    """Запросить подтверждение удаления тренировки."""
    training_id = int(callback.data.split(":", 1)[1])
    with get_db() as db:
        training = db.get(Training, training_id)
        if not training:
            await callback.answer("Тренировка уже удалена.", show_alert=True)
            return

        text = (
            "Удалить тренировку?\n\n"
            f"{training.athlete_name} — {training.date} {training.time}"
        )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="✅ Удалить",
            callback_data=f"trainer_delete:{training_id}"
        ),
        InlineKeyboardButton(text="❌ Отмена", callback_data="trainer_delete_cancel")
    ]])
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data == "trainer_delete_cancel", F.from_user.id == TRAINER_ID)
async def trainer_training_delete_cancel(callback: CallbackQuery):
    await callback.message.edit_text("Удаление отменено.")
    await callback.answer()


@router.callback_query(F.data.startswith("trainer_delete:"), F.from_user.id == TRAINER_ID)
async def trainer_training_delete(callback: CallbackQuery):
    """Удалить тренировку, сохранив непустую папку с видео."""
    training_id = int(callback.data.split(":", 1)[1])
    with get_db() as db:
        training = db.get(Training, training_id)
        if not training:
            await callback.answer("Тренировка уже удалена.", show_alert=True)
            return

        athlete_name = training.athlete_name
        date = training.date
        time = training.time
        folder_path = training.yandex_folder_path
        db.query(VideoCheck).filter(VideoCheck.training_id == training.id).delete(
            synchronize_session=False
        )
        db.delete(training)
        db.commit()

    folder_note = ""
    if folder_path:
        deleted, reason = await yandex_disk.delete_folder(folder_path)
        if deleted:
            folder_note = "\nПустая папка тренировки также удалена."
        elif reason not in {"Папка не найдена", ""}:
            folder_note = f"\nПапка на Яндекс.Диске сохранена: {reason}."

    await callback.message.edit_text(
        f"✅ Тренировка удалена:\n{athlete_name} — {date} {time}{folder_note}"
    )
    await callback.answer()


@router.message(F.from_user.id == TRAINER_ID)
async def handle_trainer_message(message: Message, bot: Bot, state: FSMContext):
    if message.chat.type != 'private': return
    if message.text and (message.text.startswith('/') or message.text in ["🎬 Старт", "🛠 Панель разработчика", "📹 Проверить видео", "📊 Статус опроса", "📝 Ответ за спортсмена", "🗓 Тренировки"]): return

    text = message.text or message.caption
    if not text: return

    user_id = message.from_user.id

    # Если уже есть ожидающее подтверждение — игнорируем новое сообщение
    if user_id in _pending_confirmation:
        await state.clear()
        _pending_confirmation.discard(user_id)
        _pending_request_ids.pop(user_id, None)
        await bot.send_message(message.chat.id, "♻️ Получил новое сообщение. Заменяю предыдущее подтверждение.")

    if user_id not in _worker_tasks or _worker_tasks[user_id].done():
        # Первому сообщению — создаём очередь и воркера
        input_revision = _input_revisions.get(user_id, 0) + 1
        _input_revisions[user_id] = input_revision
        _queues[user_id] = asyncio.Queue()
        _queues[user_id].put_nowait(text)
        _worker_tasks[user_id] = asyncio.create_task(
            _trainer_buffer_worker(
                user_id,
                message.chat.id,
                bot,
                state,
                input_revision
            )
        )
    else:
        # Последующие сообщения — кладём в очередь, воркер сам подхватит после таймаута
        _queues[user_id].put_nowait(text)


@router.callback_query(TrainerStates.waiting_for_schedule_confirmation, F.data.startswith(("confirm_schedule:", "cancel_schedule:")))
async def handle_schedule_confirmation(callback: CallbackQuery, bot: Bot, state: FSMContext):
    """Обработка подтверждения расписания тренером"""
    if callback.from_user.id != TRAINER_ID:
        await callback.answer()
        return

    await callback.answer()

    action, request_id = callback.data.split(":", 1)
    current_request_id = _pending_request_ids.get(callback.from_user.id)
    if current_request_id != request_id:
        await callback.answer("Это старое подтверждение. Используйте последнее сообщение.", show_alert=True)
        return

    if action == "cancel_schedule":
        await state.clear()
        _pending_confirmation.discard(callback.from_user.id)
        _pending_request_ids.pop(callback.from_user.id, None)
        await callback.message.edit_text("❌ Действие отменено.")
        return

    try:
        user_data = await state.get_data()
        trainings = user_data.get("parsed_trainings", [])
        original_text = user_data.get("original_text", "")

        if not trainings:
            await callback.message.edit_text("⚠️ Ошибка: данные о тренировках утеряны.")
            return

        await callback.message.edit_text("⏳ Назначаю тренировки, подождите...")

        processed_trainings = await _create_training_records(trainings, original_text)

        await _send_training_notifications(processed_trainings, bot)
        await _publish_to_group(processed_trainings, bot)

        final_lines = ["✅ Тренировки назначены:\n"]
        for t in processed_trainings:
            final_lines.append(f"  {t['name']} — {t['date']} {t['time']}")

        await callback.message.edit_text("\n".join(final_lines))
    except Exception as e:
        logger.error(f"Error confirming schedule: {e}", exc_info=True)
        await callback.message.edit_text("❌ Произошла ошибка при назначении тренировок.")
    finally:
        await state.clear()
        _pending_confirmation.discard(callback.from_user.id)
        _pending_request_ids.pop(callback.from_user.id, None)
