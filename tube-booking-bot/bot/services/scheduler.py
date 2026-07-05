from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import asyncio
from datetime import datetime, timedelta, time
import pytz
from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import BaseStorage, StorageKey

from bot.models.database import get_db, SundayPoll, Training, VideoCheck, ProcessedEvent
from bot.config import (
    ATHLETES,
    TRAINER_ID,
    FORUM_CHAT_ID,
    FORUM_MESSAGE_THREAD_ID,
    MIN_VIDEOS_COUNT,
    ATHLETE_IDS,
)
from bot.services.yandex_disk import yandex_disk

scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
MOSCOW_TIMEZONE = pytz.timezone("Europe/Moscow")
BUSINESS_TIMEZONE = pytz.timezone("Asia/Yekaterinburg")
POLL_START_MOSCOW_TIME = time(10, 0)
POLL_CLOSE_BUSINESS_TIME = time(20, 0, 0, 999999)


async def send_forum_message(bot: Bot, text: str) -> None:
    kwargs = {"chat_id": FORUM_CHAT_ID}
    if FORUM_MESSAGE_THREAD_ID is not None:
        kwargs["message_thread_id"] = FORUM_MESSAGE_THREAD_ID
    await bot.send_message(**kwargs, text=text)


def _poll_result_event_key(poll_date: datetime) -> str:
    return f"poll_results:{poll_date.isoformat()}"


def get_upcoming_poll_date(now: datetime | None = None) -> datetime:
    """
    Return the canonical poll batch datetime for the nearest active/upcoming Sunday.

    Stored as a naive Moscow datetime at 10:00, which maps to 12:00 in
    Yekaterinburg on the same date.
    """
    current = now or datetime.now(BUSINESS_TIMEZONE)
    if current.tzinfo is None:
        current = BUSINESS_TIMEZONE.localize(current)
    else:
        current = current.astimezone(BUSINESS_TIMEZONE)

    days_ahead = (6 - current.weekday()) % 7
    if days_ahead == 0 and current.time() > POLL_CLOSE_BUSINESS_TIME:
        days_ahead = 7

    target_day = (current + timedelta(days=days_ahead)).date()
    return datetime.combine(target_day, POLL_START_MOSCOW_TIME)


def poll_results_already_sent(poll_date: datetime) -> bool:
    with get_db() as db:
        return db.query(ProcessedEvent).filter(
            ProcessedEvent.event_key == _poll_result_event_key(poll_date)
        ).first() is not None


def mark_poll_results_sent(poll_date: datetime) -> None:
    with get_db() as db:
        existing = db.query(ProcessedEvent).filter(
            ProcessedEvent.event_key == _poll_result_event_key(poll_date)
        ).first()
        if existing:
            return
        db.add(ProcessedEvent(
            event_key=_poll_result_event_key(poll_date),
            event_type="poll_results"
        ))
        db.commit()


def _poll_late_result_event_key(poll_date: datetime) -> str:
    return f"poll_late_results:{poll_date.isoformat()}"


def poll_late_results_already_sent(poll_date: datetime) -> bool:
    with get_db() as db:
        return db.query(ProcessedEvent).filter(
            ProcessedEvent.event_key == _poll_late_result_event_key(poll_date)
        ).first() is not None


def mark_poll_late_results_sent(poll_date: datetime) -> None:
    with get_db() as db:
        existing = db.query(ProcessedEvent).filter(
            ProcessedEvent.event_key == _poll_late_result_event_key(poll_date)
        ).first()
        if existing:
            return
        db.add(ProcessedEvent(
            event_key=_poll_late_result_event_key(poll_date),
            event_type="poll_late_results"
        ))
        db.commit()


def _poll_day_in_yekaterinburg(poll_date: datetime):
    if poll_date.tzinfo is None:
        poll_date = MOSCOW_TIMEZONE.localize(poll_date)
    return poll_date.astimezone(BUSINESS_TIMEZONE).date()


def _poll_stage2_start_moscow(poll_date: datetime) -> datetime:
    """17:00 EKB is 15:00 MSK on the poll day."""
    if poll_date.tzinfo is None:
        poll_date = MOSCOW_TIMEZONE.localize(poll_date)
    poll_day_msk = poll_date.astimezone(MOSCOW_TIMEZONE).date()
    return datetime.combine(poll_day_msk, time(15, 0))


def poll_response_window_is_open(
    poll_date: datetime,
    now: datetime | None = None
) -> bool:
    """Опрос принимает ответы в воскресенье с 12:00 до 20:00 по ЕКБ."""
    current = now or datetime.now(BUSINESS_TIMEZONE)
    if current.tzinfo is None:
        current = BUSINESS_TIMEZONE.localize(current)
    return (
        current.date() == _poll_day_in_yekaterinburg(poll_date)
        and time(12, 0) <= current.time() <= POLL_CLOSE_BUSINESS_TIME
    )


async def notify_trainer_about_late_poll_response(bot: Bot, telegram_id: int) -> None:
    """После позднего ответа закрыть второй этап, если больше некого ждать."""
    with get_db() as db:
        poll = db.query(SundayPoll).filter(
            SundayPoll.telegram_id == telegram_id
        ).order_by(SundayPoll.poll_date.desc()).first()
        if not poll or poll.responded_at is None:
            return
        if not poll_results_already_sent(poll.poll_date):
            return
        if not poll_response_window_is_open(poll.poll_date):
            return

    await send_late_poll_results(bot, force=False)


def _format_poll_item(name: str, will_fly: bool, schedule: str | None, comment: str | None) -> str:
    if will_fly:
        line = f"• {name}: да, {schedule or 'время не указано'}"
    else:
        line = f"• {name}: нет"
    if comment:
        line += f" ({comment})"
    return line


async def send_late_poll_results(bot: Bot, force: bool = True) -> None:
    """Отчёт по второму этапу: ответы после 17:00 ЕКБ и всё ещё молчащие."""
    with get_db() as db:
        latest_poll = db.query(SundayPoll).order_by(SundayPoll.poll_date.desc()).first()
        if not latest_poll:
            return

        poll_date = latest_poll.poll_date
        if not poll_results_already_sent(poll_date):
            return
        if poll_late_results_already_sent(poll_date):
            return

        stage2_start = _poll_stage2_start_moscow(poll_date)
        polls = db.query(SundayPoll).filter(SundayPoll.poll_date == poll_date).all()

        late_answered = []
        no_response = []
        for poll in polls:
            athlete = ATHLETES.get(poll.telegram_id)
            if not athlete:
                continue

            if poll.responded_at is None:
                no_response.append(athlete["name"])
            elif poll.responded_at >= stage2_start:
                late_answered.append({
                    "name": athlete["name"],
                    "will_fly": bool(poll.will_fly),
                    "schedule": poll.schedule_text,
                    "comment": poll.comment,
                })

        if not force and no_response:
            return
        if not late_answered and not no_response:
            return

    lines = ["📨 Второй этап опроса после 17:00:"]
    if late_answered:
        lines.append("")
        lines.append("Ответили после 17:00:")
        for item in sorted(late_answered, key=lambda x: x["name"]):
            lines.append(_format_poll_item(
                item["name"],
                item["will_fly"],
                item["schedule"],
                item["comment"]
            ))

    if no_response:
        lines.append("")
        lines.append("Не ответили до 20:00:")
        for name in sorted(no_response):
            lines.append(f"• {name}")

    await bot.send_message(TRAINER_ID, "\n".join(lines))
    mark_poll_late_results_sent(poll_date)


async def start_sunday_poll(bot: Bot, storage: BaseStorage):
    """
    Запуск воскресного опроса в 12:00.
    Рассылает опрос всем спортсменам (не тренерам).
    """
    poll_date = get_upcoming_poll_date()
    sent_count = 0
    skipped_count = 0
    errors = []

    print(f"=== ЗАПУСК ВОСКРЕСНОГО ОПРОСА ===")
    print(f"Дата: {poll_date}")
    print(f"Спортсмены для опроса: {ATHLETE_IDS}")

    for telegram_id in ATHLETE_IDS:
        try:
            athlete_name = ATHLETES[telegram_id]["name"]
            print(f"Отправляю опрос {athlete_name} ({telegram_id})...")

            with get_db() as db:
                existing_poll = db.query(SundayPoll).filter(
                    SundayPoll.poll_date == poll_date,
                    SundayPoll.telegram_id == telegram_id
                ).first()

            if existing_poll and existing_poll.responded_at is not None:
                skipped_count += 1
                print(f"⏭️ {athlete_name} уже ответил заранее")
                continue

            # Получаем историю для быстрого ответа
            last_schedule = None
            with get_db() as db:
                from bot.models.database import FlightHistory
                history = db.query(FlightHistory).filter(
                    FlightHistory.telegram_id == telegram_id
                ).order_by(FlightHistory.created_at.desc()).first()
                if history:
                    last_schedule = history.schedule_text

            # Формируем клавиатуру
            from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
            keyboard_buttons = []

            if last_schedule:
                short_schedule = last_schedule.replace("\n", ", ")
                if len(short_schedule) > 30:
                    short_schedule = short_schedule[:27] + "..."
                keyboard_buttons.append(KeyboardButton(text=f"Да, {short_schedule}"))

            keyboard_buttons.extend([KeyboardButton(text="Да"), KeyboardButton(text="Нет")])

            keyboard = ReplyKeyboardMarkup(
                keyboard=[[b] for b in keyboard_buttons],
                resize_keyboard=True,
                one_time_keyboard=True
            )

            # Отправляем сообщение
            await bot.send_message(
                telegram_id,
                "Будете ли вы летать (тренироваться) на следующей неделе?",
                reply_markup=keyboard
            )

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

            # Устанавливаем состояние FSM
            key = StorageKey(bot_id=bot.id, chat_id=telegram_id, user_id=telegram_id)
            state = FSMContext(storage=storage, key=key)
            from bot.utils.states import PollStates
            await state.update_data(poll_date=poll_date.isoformat(), early_poll=False)
            await state.set_state(PollStates.waiting_for_answer)

            sent_count += 1
            print(f"✅ Опрос отправлен {athlete_name}")

            # Rate limiting - пауза между отправками
            await asyncio.sleep(0.5)

        except Exception as e:
            athlete_name = ATHLETES.get(telegram_id, {}).get("name", str(telegram_id))
            errors.append(f"{athlete_name}: {e}")
            print(f"❌ Ошибка отправки {athlete_name}: {e}")

    print(f"=== ОПРОС ОТПРАВЛЕН ===")
    print(f"Успешно: {sent_count}")
    print(f"Уже ответили заранее: {skipped_count}")
    print(f"Ошибок: {len(errors)}")

    # Отправляем отчёт тренеру
    if errors:
        error_text = f"⚠️ Ошибки при отправке опроса:\n" + "\n".join(errors)
        await bot.send_message(TRAINER_ID, error_text)

    result_lines = [f"📊 Опрос запущен. Отправлено: {sent_count}"]
    if skipped_count:
        result_lines.append(f"Уже ответили заранее: {skipped_count}")
    await bot.send_message(TRAINER_ID, "\n".join(result_lines))


async def remind_poll(bot: Bot):
    """Напоминание не ответившим в 14:00"""
    with get_db() as db:
        latest_poll = db.query(SundayPoll).order_by(SundayPoll.poll_date.desc()).first()
        if not latest_poll:
            return

        polls = db.query(SundayPoll).filter(
            SundayPoll.poll_date == latest_poll.poll_date,
            SundayPoll.responded_at == None
        ).all()

        if not polls:
            return

        from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="Да"), KeyboardButton(text="Нет")]
            ],
            resize_keyboard=True,
            one_time_keyboard=True
        )

        for poll in polls:
            try:
                await bot.send_message(
                    poll.telegram_id,
                    "⏰ Напоминание: ответьте на опрос о тренировках",
                    reply_markup=keyboard
                )
            except Exception as e:
                print(f"Ошибка напоминания {poll.telegram_id}: {e}")

        no_response = []
        for poll in polls:
            athlete = ATHLETES.get(poll.telegram_id)
            no_response.append(athlete["name"] if athlete else str(poll.telegram_id))

        trainer_message = [
            f"⏰ Напоминание отправлено {len(polls)} спортсменам",
            "",
            "⚠️ Не ответили на опрос:",
            "\n".join(sorted(no_response))
        ]

        await bot.send_message(
            TRAINER_ID,
            "\n".join(trainer_message)
        )


async def send_poll_results(bot: Bot):
    """Отправка результатов опроса тренеру в 15:00"""
    with get_db() as db:
        latest_poll = db.query(SundayPoll).order_by(SundayPoll.poll_date.desc()).first()
        if not latest_poll:
            return

        poll_date = latest_poll.poll_date
        if poll_results_already_sent(poll_date):
            return
        polls = db.query(SundayPoll).filter(SundayPoll.poll_date == poll_date).all()

        will_fly = []
        wont_fly = []
        with_comments = []
        no_response = []
        total_athletes = 0

        for poll in polls:
            athlete = ATHLETES.get(poll.telegram_id)
            if not athlete:
                continue
            total_athletes += 1

            if poll.responded_at is None:
                no_response.append(athlete["name"])
            elif poll.will_fly is True:
                will_fly.append({
                    "name": athlete["name"],
                    "schedule": poll.schedule_text or "не указано",
                    "comment": poll.comment
                })
                if poll.comment:
                    with_comments.append({
                        "name": athlete["name"],
                        "comment": poll.comment,
                        "type": "полёт"
                    })
            else:  # will_fly is False (responded "No")
                wont_fly.append(athlete["name"])
                if poll.comment:
                    with_comments.append({
                        "name": athlete["name"],
                        "comment": poll.comment,
                        "type": "отказ"
                    })

    answered_count = len(will_fly) + len(wont_fly)
    summary = (
        "📊 Итоги опроса на 17:00 по Екатеринбургу\n\n"
        f"Всего спортсменов: {total_athletes}\n"
        f"Ответили: {answered_count}\n"
        f"Не ответили: {len(no_response)}\n"
        f"С комментариями: {len(with_comments)}\n"
        f"Без комментариев: {max(answered_count - len(with_comments), 0)}"
    )
    await bot.send_message(TRAINER_ID, summary)

    if will_fly:
        message1 = "📋 Список полётов на следующую неделю:\n\n"
        for item in sorted(will_fly, key=lambda x: x["name"]):
            message1 += f"{item['name']}\n{item['schedule']}\n\n"
        await bot.send_message(TRAINER_ID, message1)

    if wont_fly:
        message2 = "❌ Отказались от полётов:\n" + "\n".join(sorted(wont_fly))
        await bot.send_message(TRAINER_ID, message2)

    if with_comments:
        message3 = "💬 Комментарии:\n\n"
        for item in with_comments:
            message3 += f"{item['name']} ({item['type']}): {item['comment']}\n\n"
        await bot.send_message(TRAINER_ID, message3)

    if no_response:
        message4 = "⚠️ Не ответили на опрос:\n" + "\n".join(sorted(no_response))
        await bot.send_message(TRAINER_ID, message4)

    mark_poll_results_sent(poll_date)


async def send_evening_reminder(bot: Bot):
    """Вечернее напоминание о загрузке видео в 16:00"""
    today = datetime.now(pytz.timezone("Europe/Moscow")).strftime("%d.%m")

    with get_db() as db:
        from bot.models.database import User

        trainings = db.query(Training).filter(
            Training.date == today,
            Training.videos_uploaded == False,
            Training.reminder_sent == False
        ).all()

        if not trainings:
            print(f"Нет тренировок сегодня ({today}) для напоминания")
            return

        notified_count = 0

        for training in trainings:
            user = db.query(User).filter(User.telegram_id == training.telegram_id).first()
            if user and not user.notifications_enabled:
                training.reminder_sent = True
                continue

            try:
                await bot.send_message(
                    training.telegram_id,
                    f"📹 Напоминание: не забудьте загрузить видео с тренировки!\n\n"
                    f"Ссылка на папку:\n{training.yandex_folder_url}"
                )
                training.reminder_sent = True
                notified_count += 1
                print(f"Напоминание отправлено {training.athlete_name}")
            except Exception as e:
                print(f"Ошибка напоминания {training.telegram_id}: {e}")

        db.commit()

    await bot.send_message(TRAINER_ID, f"📹 Напоминание о видео отправлено {notified_count} спортсменам")


async def check_videos(bot: Bot):
    """Проверка загрузки видео в 10:00 (день 1 и день 2)"""
    print("=== ПРОВЕРКА ВИДЕО ===")

    # Тихо перепроверяем тренировки, которые уже прошли две проверки.
    # Если спортсмен загрузил видео позже второго дня, запись всё равно закроется.
    with get_db() as db:
        incomplete_trainings = db.query(Training).filter(
            Training.videos_uploaded == False,
            Training.check_count >= 2
        ).all()

        for training in incomplete_trainings:
            try:
                videos_count = await yandex_disk.count_videos(training.yandex_folder_path)
                if videos_count >= MIN_VIDEOS_COUNT:
                    training.videos_uploaded = True
                    training.completed_at = datetime.now()
                    db.add(VideoCheck(
                        training_id=training.id,
                        videos_count=videos_count
                    ))
                    print(
                        f"  ✅ Поздняя загрузка: {training.athlete_name} "
                        f"({training.date}) — {videos_count} видео"
                    )
            except Exception as e:
                print(f"  ❌ Ошибка фоновой проверки {training.athlete_name}: {e}")

        db.commit()

    for days_ago in [1, 2]:
        target_date = (datetime.now(pytz.timezone("Europe/Moscow")) - timedelta(days=days_ago)).strftime("%d.%m")
        print(f"Проверяю дату: {target_date} ({days_ago} дней назад)")

        with get_db() as db:
            trainings = db.query(Training).filter(
                Training.date == target_date,
                Training.videos_uploaded == False
            ).all()

            if not trainings:
                print(f"Нет тренировок за {target_date}")
                continue

            not_uploaded = []

            for training in trainings:
                try:
                    videos_count = await yandex_disk.count_videos(training.yandex_folder_path)
                    print(f"  {training.athlete_name}: {videos_count} видео")

                    check = VideoCheck(training_id=training.id, videos_count=videos_count)
                    db.add(check)

                    if videos_count >= MIN_VIDEOS_COUNT:
                        training.videos_uploaded = True
                        training.completed_at = datetime.now()
                        print(f"  ✅ {training.athlete_name}: видео загружены")
                    else:
                        not_uploaded.append({
                            "name": training.athlete_name,
                            "count": videos_count,
                            "date": training.date,
                            "days_since": days_ago
                        })
                        training.check_count += 1

                except Exception as e:
                    print(f"  ❌ Ошибка проверки {training.athlete_name}: {e}")

            db.commit()

            if not_uploaded:
                if days_ago == 1:
                    message = f"⚠️ Не загрузили видео ({target_date}):\n"
                else:
                    message = f"⚠️ Последний день! Не загрузили видео ({target_date}):\n"

                for item in not_uploaded:
                    message += f"• {item['name']} — {item['count']} видео ({item['days_since']} дн.)\n"

                print(f"Отправляю уведомление в форум: {message}")
                await send_forum_message(bot, message)

                # Также отправляем тренеру
                await bot.send_message(TRAINER_ID, message)

    print("=== ПРОВЕРКА ЗАВЕРШЕНА ===")


async def create_monthly_folders(bot: Bot):
    """Создание папок для следующего месяца (в последний день месяца в 22:00)."""
    now = datetime.now()
    next_month = (now.replace(day=1) + timedelta(days=32)).replace(day=1)
    month = next_month.month
    year = next_month.year

    created = await yandex_disk.create_athlete_folders(month, year, ATHLETES)
    if created:
        await bot.send_message(TRAINER_ID, f"📁 Папки для {month:02d}.{year} созданы")
    else:
        await bot.send_message(TRAINER_ID, f"⚠️ Не все папки для {month:02d}.{year} удалось создать")


def setup_scheduler(bot: Bot, storage: BaseStorage):
    """Настройка планировщика задач"""
    timezone = pytz.timezone("Europe/Moscow")

    # Каждую минуту (для отладки) - проверяем active polls
    # scheduler.add_job(
    #     lambda: print("Бот работает"),
    #     'interval',
    #     minutes=1
    # )

    # Опрос в воскресенье 10:00 (12:00 по Екатеринбургу)
    scheduler.add_job(
        start_sunday_poll,
        CronTrigger(day_of_week='sun', hour=10, minute=0, timezone=timezone),
        args=[bot, storage],
        id='sunday_poll'
    )

    # Напоминание в 13:00 (15:00 по Екатеринбургу)
    scheduler.add_job(
        remind_poll,
        CronTrigger(day_of_week='sun', hour=13, minute=0, timezone=timezone),
        args=[bot],
        id='remind_poll'
    )

    # Отправка результатов в 15:00 (17:00 по Екатеринбургу)
    scheduler.add_job(
        send_poll_results,
        CronTrigger(day_of_week='sun', hour=15, minute=0, timezone=timezone),
        args=[bot],
        id='poll_results'
    )

    # Финальный отчёт второго этапа в 18:00 (20:00 по Екатеринбургу)
    scheduler.add_job(
        send_late_poll_results,
        CronTrigger(day_of_week='sun', hour=18, minute=0, timezone=timezone),
        args=[bot],
        id='poll_late_results'
    )

    # Вечернее напоминание в 16:00
    scheduler.add_job(
        send_evening_reminder,
        CronTrigger(hour=16, minute=0, timezone=timezone),
        args=[bot],
        id='evening_reminder'
    )

    # Проверка видео в 10:00
    scheduler.add_job(
        check_videos,
        CronTrigger(hour=10, minute=0, timezone=timezone),
        args=[bot],
        id='check_videos'
    )

    # Создание папок в последний день месяца в 22:00
    scheduler.add_job(
        create_monthly_folders,
        CronTrigger(day='last', hour=22, minute=0, timezone=timezone),
        args=[bot],
        id='create_folders'
    )

    scheduler.start()
    print("✅ Планировщик запущен")
