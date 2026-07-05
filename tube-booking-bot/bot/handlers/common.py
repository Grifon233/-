from aiogram import Router, F, Bot
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command

from bot.models.database import get_db, User
from bot.config import ATHLETES, TRAINER_ID, DEVELOPER_ID
from bot.keyboards.common import get_trainer_panel, get_athlete_panel

router = Router()
router.message.filter(F.chat.type == "private")


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    """Обработка команды /start"""
    await state.clear()
    telegram_id = message.from_user.id
    allowed_ids = set(ATHLETES) | {TRAINER_ID, DEVELOPER_ID}

    with get_db() as db:
        user = db.query(User).filter(User.telegram_id == telegram_id).first()

        if telegram_id not in allowed_ids:
            await message.answer("У вас нет доступа к этому боту.")
            return

        if not user:
            athlete_data = ATHLETES[telegram_id]
            role = athlete_data.get("role", "athlete")
            user = User(
                telegram_id=telegram_id,
                name=athlete_data["name"],
                full_name=athlete_data["full_name"],
                role=role
            )
            db.add(user)
            db.commit()
            db.refresh(user)

        if user.role == "trainer":
            await message.answer(
                f"Привет, {user.full_name}! 👋\n\n"
                "Отправь мне сообщение с расписанием тренировок.\n"
                "Например: 'пн Кочуров 14:00' или 'вт Степанов 16:00'\n\n"
                "Или нажми «📝 Ответ за спортсмена», чтобы заполнить воскресный "
                "опрос за спортсмена, если он не может ответить сам.\n\n"
                "Бот уведомит спортсменов и опубликует расписание в группу.",
                reply_markup=get_trainer_panel()
            )
        else:
            await message.answer(
                f"Привет, {user.full_name}! 👋\n\n"
                "Я помогу тебе записаться на тренировки.\n"
                "Каждое воскресенье я буду спрашивать о твоих планах. "
                "Если уже знаешь ответ, нажми «📝 Ответить заранее».",
                reply_markup=get_athlete_panel(user.notifications_enabled)
            )


@router.message(Command("help"))
async def cmd_help(message: Message):
    """Обработка команды /help"""
    telegram_id = message.from_user.id

    if telegram_id == TRAINER_ID:
        help_text = (
            "📖 Помощь для тренера:\n\n"
            "Отправь сообщение с расписанием в формате:\n"
            "• пн Кочуров 14:00\n"
            "• вт Степанов 16:00\n"
            "• ср Кочуров 14:00, Степанов 18:00\n\n"
            "Бот уведомит спортсменов и опубликует расписание в группу."
        )
    else:
        help_text = (
            "📖 Помощь:\n\n"
            "Каждое воскресенье в 14:00 я спрошу, когда ты планируешь летать.\n\n"
            "Укажи дни и время в формате:\n"
            "пн с 14 до 22\n"
            "ср с 16 до 22\n\n"
            "После назначения тренировки я напомню загрузить видео."
        )

    await message.answer(help_text)


@router.message(F.text.startswith("🔔 Уведомления:") | F.text.startswith("🔕 Уведомления:"))
async def toggle_notifications(message: Message, state: FSMContext):
    """Включение/выключение уведомлений"""
    await state.clear()
    telegram_id = message.from_user.id

    with get_db() as db:
        user = db.query(User).filter(User.telegram_id == telegram_id).first()
        if not user or user.role != "athlete":
            return

        if message.text.startswith("🔕"):
            # Нажали "🔕 Уведомления: ВЫКЛ" = выключаем
            user.notifications_enabled = False
            status = "выключены"
            text = (
                f"🔕 Уведомления {status}.\n\n"
                "Напоминание о загрузке видео в 18:00 приходить не будет."
            )
        else:
            # Нажали "🔔 Уведомления: ВКЛ" = включаем
            user.notifications_enabled = True
            status = "включены"
            text = (
                f"🔔 Уведомления {status}.\n\n"
                "В день тренировки в 18:00 вы будете получать напоминание "
                "о загрузке видео на Яндекс.Диск."
            )

        db.commit()

        await message.answer(
            text,
            reply_markup=get_athlete_panel(user.notifications_enabled)
        )


@router.message(F.text == "📹 Проверить видео", F.from_user.id == TRAINER_ID)
async def trainer_check_videos(message: Message, bot: Bot):
    """Проверить кто не загрузил видео"""
    from bot.config import MIN_VIDEOS_COUNT
    from bot.models.database import get_db, Training, VideoCheck
    from bot.services.yandex_disk import yandex_disk
    from datetime import datetime

    with get_db() as db:
        trainings = db.query(Training).filter(Training.videos_uploaded == False).all()

        if not trainings:
            await message.answer("✅ Нет активных тренировок. Все видео загружены.")
            return

        not_uploaded = []
        check_errors = []
        for training in trainings:
            try:
                videos_count = await yandex_disk.count_videos(training.yandex_folder_path)
            except Exception as e:
                check_errors.append(f"{training.athlete_name} ({training.date} {training.time})")
                continue

            check = VideoCheck(training_id=training.id, videos_count=videos_count)
            db.add(check)

            if videos_count >= MIN_VIDEOS_COUNT:
                training.videos_uploaded = True
                training.completed_at = datetime.now()
            else:
                not_uploaded.append({
                    "name": training.athlete_name,
                    "count": videos_count,
                    "date": training.date,
                    "time": training.time
                })

        db.commit()

    if not_uploaded:
        lines = ["⚠️ Не загрузили видео:\n"]
        for item in sorted(not_uploaded, key=lambda x: (x["date"], x["time"], x["name"])):
            lines.append(f"  • {item['name']} ({item['date']} {item['time']}) — {item['count']} видео")
    else:
        lines = ["✅ Все доступные папки проверены: видео загружены."]

    if check_errors:
        lines.append("\n⚠️ Не удалось проверить:")
        lines.extend(f"  • {item}" for item in check_errors)

    await message.answer("\n".join(lines))


@router.message(F.text == "📊 Статус опроса", F.from_user.id == TRAINER_ID)
async def trainer_poll_status(message: Message):
    """Показать статус опроса"""
    from bot.models.database import get_db, SundayPoll

    with get_db() as db:
        latest_poll = db.query(SundayPoll).order_by(SundayPoll.poll_date.desc()).first()
        if not latest_poll:
            await message.answer("Опросы ещё не проводились.")
            return

        poll_date = latest_poll.poll_date
        polls = db.query(SundayPoll).filter(SundayPoll.poll_date == poll_date).all()

        responded = []
        waiting = []

        for poll in polls:
            athlete = ATHLETES.get(poll.telegram_id)
            if not athlete:
                continue

            name = athlete["name"]
            if poll.responded_at:
                status = "✅" if poll.will_fly else "❌"
                responded.append(f"{status} {name}")
            else:
                waiting.append(f"⏳ {name}")

        text = f"📊 Статус опроса ({poll_date.strftime('%d.%m')}):\n\n"
        if waiting:
            text += "⏳ Ожидаем ответ:\n" + "\n".join(waiting) + "\n\n"
        if responded:
            text += "Ответили:\n" + "\n".join(responded)

        if not waiting and not responded:
            text = "Нет данных по текущему опросу."

        await message.answer(text)
