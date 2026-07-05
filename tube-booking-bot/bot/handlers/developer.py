from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from datetime import datetime, timedelta
import logging

from bot.config import TRAINER_ID, DEVELOPER_ID, ATHLETES, MIN_VIDEOS_COUNT
from bot.models.database import get_db, SundayPoll, Training, VideoCheck
from bot.keyboards.common import get_dev_panel, get_test_commands_keyboard
from bot.services.yandex_disk import yandex_disk
from bot.utils.states import DevStates
from bot.utils.parsers import resolve_training_datetime

logger = logging.getLogger(__name__)
router = Router()
router.message.filter(F.chat.type == "private")
router.callback_query.filter(F.message.chat.type == "private")

@router.message(F.text == "🗑 Удалить тренировку", F.from_user.id == DEVELOPER_ID)
async def list_trainings_for_delete(message: Message):
    """Список тренировок для удаления"""
    with get_db() as db:
        trainings = db.query(Training).filter(Training.videos_uploaded == False).all()
        if not trainings:
            await message.answer("✅ Нет активных тренировок.")
            return

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"{t.athlete_name} {t.date} {t.time}", callback_data=f"del_tr_{t.id}")]
            for t in trainings
        ] + [[InlineKeyboardButton(text="🔙 Назад", callback_data="dev_back")]])

        await message.answer("Выберите тренировку для удаления:", reply_markup=keyboard)

@router.callback_query(F.data.startswith("del_tr_"), F.from_user.id == DEVELOPER_ID)
async def delete_training(callback: CallbackQuery):
    """Удаление тренировки"""
    tr_id = int(callback.data.split("_")[2])
    with get_db() as db:
        tr = db.query(Training).get(tr_id)
        if tr:
            db.delete(tr)
            db.commit()
            await callback.message.answer(f"✅ Тренировка {tr.athlete_name} удалена.")
        else:
            await callback.message.answer("⚠️ Тренировка не найдена.")
    await callback.answer()

@router.message(F.text == "➕ Добавить тренировку", F.from_user.id == DEVELOPER_ID)
async def start_add_training(message: Message, state: FSMContext):
    """Запуск добавления тренировки"""
    await state.set_state(DevStates.waiting_for_new_training)
    await message.answer("Введите данные тренировки:\nИмя, дата (дд.мм), время\nПример: Кочуров, 21.05, 12:00")

@router.message(DevStates.waiting_for_new_training, F.from_user.id == DEVELOPER_ID)
async def process_new_training(message: Message, state: FSMContext, bot: Bot):
    """Создание тренировки"""
    try:
        parts = [p.strip() for p in message.text.split(",")]
        if len(parts) != 3:
            await message.answer("⚠️ Нужен формат: Имя, дд.мм, чч:мм")
            return
        name, date, time = parts[0], parts[1], parts[2]
        
        # Находим ID спортсмена
        telegram_id = None
        for tid, data in ATHLETES.items():
            if name.lower() in [n.lower() for n in [data['name'], data['full_name']]]:
                telegram_id = tid
                break
        
        if not telegram_id:
            await message.answer("⚠️ Спортсмен не найден.")
            return

        training_dt = resolve_training_datetime(date, time)
        if not training_dt:
            await message.answer("⚠️ Некорректная дата или время. Нужен формат: Кочуров, 21.05, 12:00")
            return
        if training_dt < datetime.now(training_dt.tzinfo):
            await message.answer("⚠️ Нельзя добавить тренировку в прошлое.")
            return

        with get_db() as db:
            existing = db.query(Training).filter(
                Training.telegram_id == telegram_id,
                Training.date == date,
                Training.time == time
            ).first()
            if existing:
                await message.answer("⚠️ Такая тренировка уже существует.")
                return

            folder, link = await yandex_disk.create_training_folder(name, date)
            if not folder or not link:
                await message.answer("⚠️ Не удалось создать папку на Яндекс.Диске. Тренировка не добавлена.")
                return
            tr = Training(
                telegram_id=telegram_id,
                athlete_name=name,
                date=date,
                time=time,
                yandex_folder_path=folder,
                yandex_folder_url=link
            )
            db.add(tr)
            db.commit()
        
        # Уведомление спортсмена
        try:
            await bot.send_message(
                telegram_id,
                f"🏋️ Тренер назначил вам тренировку:\n"
                f"📅 Дата: {date}\n"
                f"🕐 Время: {time}\n\n"
                f"📁 Папка для видео:\n{link}"
            )
            status_msg = " и уведомление отправлено спортсмену."
        except Exception:
            status_msg = ", но не удалось отправить уведомление спортсмену."

        await message.answer(f"✅ Тренировка добавлена: {name} {date} {time}{status_msg}")
    except Exception as e:
        await message.answer(f"⚠️ Ошибка: {e}")
    await state.clear()



@router.message(Command("dev"), F.from_user.id == DEVELOPER_ID)
@router.message(F.text == "🛠 Панель разработчика", F.from_user.id == DEVELOPER_ID)
async def show_dev_panel(message: Message):
    """Панель разработчика"""
    print(f"DEBUG: show_dev_panel called by user {message.from_user.id}")
    await message.answer(
        "🔧 Панель разработчика",
        reply_markup=get_dev_panel()
    )


@router.message(F.text == "🔙 Назад", F.from_user.id == DEVELOPER_ID)
async def back_to_trainer_panel(message: Message):
    """Назад к панели тренера"""
    from bot.keyboards.common import get_trainer_panel
    await message.answer(
        "🔙 Возврат в меню тренера",
        reply_markup=get_trainer_panel()
    )


@router.message(F.text == "🧪 Тестовые команды", F.from_user.id == DEVELOPER_ID)
async def show_test_commands(message: Message):
    """Тестовые команды"""
    await message.answer(
        "Выберите тест:",
        reply_markup=get_test_commands_keyboard()
    )


@router.callback_query(F.data == "dev_test_poll", F.from_user.id == DEVELOPER_ID)
async def test_poll(callback: CallbackQuery, bot: Bot):
    """Тест: запуск опроса"""
    from bot.services.scheduler import start_sunday_poll
    from bot.services.fsm_storage import SQLAlchemyFSMStorage

    storage = SQLAlchemyFSMStorage()
    await start_sunday_poll(bot, storage)

    await callback.message.answer("✅ Опрос запущен")
    await callback.answer()


@router.callback_query(F.data == "dev_test_video", F.from_user.id == DEVELOPER_ID)
async def test_video(callback: CallbackQuery, bot: Bot):
    """Тест: проверка видео"""
    with get_db() as db:
        trainings = db.query(Training).filter(Training.videos_uploaded == False).all()

        if not trainings:
            await callback.message.answer("✅ Нет активных тренировок")
            await callback.answer()
            return

        lines = ["📹 Проверка видео:\n"]
        errors = []
        for training in trainings:
            try:
                count = await yandex_disk.count_videos(training.yandex_folder_path)
            except Exception:
                errors.append(f"{training.athlete_name} ({training.date})")
                continue

            check = VideoCheck(training_id=training.id, videos_count=count)
            db.add(check)

            if count >= MIN_VIDEOS_COUNT:
                training.videos_uploaded = True
                training.completed_at = datetime.now()
            else:
                lines.append(f"• {training.athlete_name} ({training.date}) — {count} видео")

        db.commit()

    if len(lines) == 1:
        lines = ["✅ Все доступные папки проверены: видео загружены"]
    if errors:
        lines.append("\n⚠️ Не удалось проверить:")
        lines.extend(f"• {item}" for item in errors)
    await callback.message.answer("\n".join(lines))

    await callback.answer()


@router.callback_query(F.data == "dev_test_reminder", F.from_user.id == DEVELOPER_ID)
async def test_reminder(callback: CallbackQuery, bot: Bot):
    """Тест: вечернее напоминание"""
    from bot.services.scheduler import send_evening_reminder
    await send_evening_reminder(bot)
    await callback.message.answer("✅ Напоминание отправлено")
    await callback.answer()


@router.callback_query(F.data == "dev_time_sim", F.from_user.id == DEVELOPER_ID)
async def show_time_simulation(callback: CallbackQuery):
    """Показать меню симуляции времени"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏰ +12 часов", callback_data="sim_12h")],
        [InlineKeyboardButton(text="⏰ +24 часа", callback_data="sim_24h")],
        [InlineKeyboardButton(text="⏰ +36 часов", callback_data="sim_36h")],
        [InlineKeyboardButton(text="⏰ +48 часов", callback_data="sim_48h")],
        [InlineKeyboardButton(text="⏰ +60 часов", callback_data="sim_60h")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="dev_back")]
    ])
    await callback.message.answer(
        "🕐 Симуляция времени:\n\n"
        "Выберите на сколько перевести время.\n"
        "Это изменит дату тренировок и проверит уведомления.",
        reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(F.data.startswith("sim_"), F.from_user.id == DEVELOPER_ID)
async def simulate_time(callback: CallbackQuery, bot: Bot):
    """Симуляция прохождения времени"""
    hours = int(callback.data.split("_")[1])
    target_time = datetime.now() - timedelta(hours=hours)

    with get_db() as db:
        trainings = db.query(Training).filter(Training.videos_uploaded == False).all()

        if not trainings:
            await callback.message.answer("⚠️ Нет активных тренировок для симуляции")
            await callback.answer()
            return

        results = []
        for training in trainings:
            old_date = training.date

            # Вычисляем новую дату: hours / 24 = количество дней назад
            days_back = hours / 24
            new_date = (datetime.now() - timedelta(days=days_back)).strftime("%d.%m")
            training.date = new_date
            training.created_at = datetime.now() - timedelta(days=days_back)
            training.reminder_sent = False

            results.append(f"• {training.athlete_name}: {old_date} → {new_date}")

        db.commit()

    # Запускаем проверку видео
    from bot.services.scheduler import check_videos
    await check_videos(bot)

    days_back = hours / 24
    await callback.message.answer(
        f"✅ Время переведено на {hours} часов ({days_back:.1f} дней) назад\n\n"
        f"Тренировки обновлены:\n" + "\n".join(results) + "\n\n"
        f"Проверка видео выполнена."
    )
    await callback.answer()


@router.callback_query(F.data == "dev_back", F.from_user.id == DEVELOPER_ID)
async def back_to_dev_panel(callback: CallbackQuery):
    """Вернуться к панели разработчика"""
    await callback.message.edit_text(
        "🔧 Панель разработчика",
        reply_markup=get_dev_panel()
    )
    await callback.answer()


@router.message(F.text == "📊 Статистика", F.from_user.id == DEVELOPER_ID)
async def show_stats(message: Message):
    """Статистика бота"""
    with get_db() as db:
        total = db.query(Training).count()
        active = db.query(Training).filter(Training.videos_uploaded == False).count()
        completed = db.query(Training).filter(Training.videos_uploaded == True).count()
        polls = db.query(SundayPoll).count()

    # Показываем активные тренировки
    active_trainings = []
    with get_db() as db:
        trainings = db.query(Training).filter(Training.videos_uploaded == False).all()
        for t in trainings:
            age = datetime.now() - t.created_at
            active_trainings.append(f"• {t.athlete_name} ({t.date}) — {age.days} дн. назад")

    text = f"📊 Статистика:\n\n"
    text += f"Тренировок: {total}\n"
    text += f"Активных: {active}\n"
    text += f"Завершённых: {completed}\n"
    text += f"Опросов: {polls}\n\n"

    if active_trainings:
        text += "Активные тренировки:\n" + "\n".join(active_trainings)

    await message.answer(text)


@router.message(F.text == "🔄 Перезапуск", F.from_user.id == DEVELOPER_ID)
async def restart_bot(message: Message, state: FSMContext):
    """Очистка активных опросов"""
    await state.clear()

    with get_db() as db:
        active_polls = db.query(SundayPoll).filter(SundayPoll.responded_at == None).all()
        count = len(active_polls)
        for poll in active_polls:
            db.delete(poll)
        db.commit()

    await message.answer(
        f"✅ Очищено активных опросов: {count}",
        reply_markup=get_dev_panel()
    )


@router.message(Command("del"), F.from_user.id == DEVELOPER_ID)
async def delete_message(message: Message, bot: Bot):
    """Удаление сообщений бота"""
    if not message.reply_to_message:
        await message.answer("Ответьте на сообщение бота командой /del")
        return

    if message.reply_to_message.from_user.id != bot.id:
        await message.answer("Можно удалять только сообщения бота")
        return

    try:
        await bot.delete_message(
            chat_id=message.chat.id,
            message_id=message.reply_to_message.message_id
        )
        await message.delete()
    except Exception as e:
        await message.answer(f"Не удалось удалить: {e}")
