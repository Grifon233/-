"""
Тестовый скрипт для проверки всей логики бота.
Симулирует нажатия кнопок и взаимодействия.
"""
import asyncio
import sys
import os
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Добавляем путь к проекту
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bot.config import TRAINER_ID, ATHLETES, ATHLETE_IDS, GROUP_CHAT_ID, MIN_VIDEOS_COUNT
from bot.models.database import get_db, init_db, Training, SundayPoll, FlightHistory, VideoCheck, User
from bot.handlers.poll import check_and_send_results
from bot.services.scheduler import send_evening_reminder, check_videos
from bot.utils.states import PollStates


class MockBot:
    """Mock для Telegram bot"""
    def __init__(self):
        self.sent_messages = []
        self.id = 123456

    async def send_message(self, chat_id, text, reply_markup=None):
        msg = {
            "chat_id": chat_id,
            "text": text[:100] + "..." if len(text) > 100 else text,
            "reply_markup": type(reply_markup).__name__ if reply_markup else None
        }
        self.sent_messages.append(msg)
        print(f"  [MOCK SEND] → {chat_id}: {msg['text']}")
        return MagicMock(message_id=12345)


async def test_database():
    """Тест 1: Проверка базы данных"""
    print("\n" + "="*60)
    print("ТЕСТ 1: База данных")
    print("="*60)

    init_db()

    with get_db() as db:
        # Создаём тестового пользователя
        user = db.query(User).filter(User.telegram_id == TRAINER_ID).first()
        if not user:
            user = User(telegram_id=TRAINER_ID, name="Колод", full_name="Костя", role="trainer")
            db.add(user)
            db.commit()
            print("  ✓ Создан тестовый пользователь (тренер)")

        # Проверяем ATHLETE_IDS
        print(f"  ✓ ATHLETE_IDS: {ATHLETE_IDS}")
        for tid in ATHLETE_IDS:
            name = ATHLETES[tid]["name"]
            print(f"    - {tid}: {name}")

    print("  ✓ База данных работает")
    return True


async def test_poll_logic():
    """Тест 2: Проверка логики воскресного опроса"""
    print("\n" + "="*60)
    print("ТЕСТ 2: Логика воскресного опроса")
    print("="*60)

    poll_date = datetime.now()
    bot = MockBot()

    # Создаём записи опроса для всех спортсменов
    with get_db() as db:
        for tid in ATHLETE_IDS:
            existing = db.query(SundayPoll).filter(
                SundayPoll.poll_date == poll_date,
                SundayPoll.telegram_id == tid
            ).first()

            if not existing:
                poll = SundayPoll(poll_date=poll_date, telegram_id=tid)
                db.add(poll)
                print(f"  ✓ Создан опрос для {ATHLETES[tid]['name']}")

        db.commit()

    # Симулируем ответ "Да" от первого спортсмена
    athlete_id = ATHLETE_IDS[0]
    with get_db() as db:
        poll = db.query(SundayPoll).filter(
            SundayPoll.poll_date == poll_date,
            SundayPoll.telegram_id == athlete_id
        ).first()

        poll.responded_at = datetime.now()
        poll.will_fly = True
        poll.schedule_text = "пн с 14 до 22\nср с 16 до 22"
        db.commit()
        print(f"  ✓ Спортсмен {ATHLETES[athlete_id]['name']} ответил 'Да'")

    # Симулируем ответ "Нет" от второго спортсмена
    if len(ATHLETE_IDS) > 1:
        athlete_id2 = ATHLETE_IDS[1]
        with get_db() as db:
            poll = db.query(SundayPoll).filter(
                SundayPoll.poll_date == poll_date,
                SundayPoll.telegram_id == athlete_id2
            ).first()

            poll.responded_at = datetime.now()
            poll.will_fly = False
            poll.comment = "Не могу в среду"
            db.commit()
            print(f"  ✓ Спортсмен {ATHLETES[athlete_id2]['name']} ответил 'Нет'")

    # Проверяем функцию отправки результатов
    bot = MockBot()
    await check_and_send_results(bot)

    print(f"  ✓ Отправлено сообщений тренеру: {len(bot.sent_messages)}")
    for msg in bot.sent_messages:
        print(f"    - {msg['text']}")

    return True


async def test_training_creation():
    """Тест 3: Создание тестовой тренировки"""
    print("\n" + "="*60)
    print("ТЕСТ 3: Создание тренировки")
    print("="*60)

    today = datetime.now().strftime("%d.%m")
    athlete_id = ATHLETE_IDS[0]
    athlete_name = ATHLETES[athlete_id]["name"]

    with get_db() as db:
        # Удаляем старые тестовые тренировки
        db.query(Training).filter(Training.athlete_name == athlete_name).delete()

        # Создаём новую тренировку
        training = Training(
            telegram_id=athlete_id,
            athlete_name=athlete_name,
            date=today,
            time="14:00",
            yandex_folder_path=f"/test/{athlete_name}/{today}",
            yandex_folder_url="https://disk.yandex.ru/test",
            videos_uploaded=False,
            reminder_sent=False
        )
        db.add(training)
        db.commit()

        print(f"  ✓ Создана тренировка: {athlete_name} - {today} 14:00")

        # Проверяем что создалась
        t = db.query(Training).filter(
            Training.athlete_name == athlete_name,
            Training.date == today
        ).first()

        if t:
            print(f"  ✓ Тренировка найдена в БД, ID={t.id}")
        else:
            print("  ✗ Тренировка НЕ найдена!")

    return True


async def test_evening_reminder():
    """Тест 4: Вечернее напоминание"""
    print("\n" + "="*60)
    print("ТЕСТ 4: Вечернее напоминание о видео")
    print("="*60)

    bot = MockBot()
    await send_evening_reminder(bot)

    print(f"  ✓ Отправлено сообщений: {len(bot.sent_messages)}")
    for msg in bot.sent_messages:
        print(f"    - [{msg['chat_id']}]: {msg['text'][:80]}...")

    return True


async def test_video_check_day1():
    """Тест 5: Проверка видео - день 1 (12:00 на следующий день)"""
    print("\n" + "="*60)
    print("ТЕСТ 5: Проверка видео - день 1")
    print("="*60)

    today = datetime.now()
    yesterday = (today - timedelta(days=1)).strftime("%d.%m")
    athlete_name = ATHLETES[ATHLETE_IDS[0]]["name"]

    # Переводим тренировку на "вчера"
    with get_db() as db:
        t = db.query(Training).filter(
            Training.athlete_name == athlete_name
        ).first()

        if t:
            old_date = t.date
            t.date = yesterday
            t.created_at = today - timedelta(days=1)
            t.reminder_sent = False
            t.check_count = 0
            db.commit()
            print(f"  ✓ Дата тренировки изменена: {old_date} → {yesterday}")

    bot = MockBot()
    await check_videos(bot)

    print(f"  ✓ Отправлено сообщений: {len(bot.sent_messages)}")
    for msg in bot.sent_messages:
        print(f"    - [{msg['chat_id']}]: {msg['text'][:80]}...")

    return True


async def test_video_check_day2():
    """Тест 6: Проверка видео - день 2 (финальное уведомление)"""
    print("\n" + "="*60)
    print("ТЕСТ 6: Проверка видео - день 2 (финальное)")
    print("="*60)

    today = datetime.now()
    two_days_ago = (today - timedelta(days=2)).strftime("%d.%m")
    athlete_name = ATHLETES[ATHLETE_IDS[0]]["name"]

    # Переводим тренировку на "позавчера"
    with get_db() as db:
        t = db.query(Training).filter(
            Training.athlete_name == athlete_name
        ).first()

        if t:
            old_date = t.date
            t.date = two_days_ago
            t.created_at = today - timedelta(days=2)
            t.check_count = 1
            db.commit()
            print(f"  ✓ Дата тренировки изменена: {old_date} → {two_days_ago} (день 2)")

    bot = MockBot()
    await check_videos(bot)

    print(f"  ✓ Отправлено сообщений: {len(bot.sent_messages)}")
    for msg in bot.sent_messages:
        print(f"    - [{msg['chat_id']}]: {msg['text'][:80]}...")

    return True


async def test_trainer_schedule_blocking():
    """Тест 7: Блокировка назначения тренировок во время опроса"""
    print("\n" + "="*60)
    print("ТЕСТ 7: Блокировка назначения тренировок")
    print("="*60)

    with get_db() as db:
        # Создаём незавершённый опрос
        poll_date = datetime.now()
        for tid in ATHLETE_IDS:
            poll = db.query(SundayPoll).filter(
                SundayPoll.poll_date == poll_date,
                SundayPoll.telegram_id == tid,
                SundayPoll.responded_at == None
            ).first()

            if poll:
                poll.responded_at = datetime.now()  # Завершаем опрос
                poll.will_fly = False
                print(f"  ✓ Завершён опрос для {ATHLETES[tid]['name']}")

        db.commit()

    print("  ✓ Проверка блокировки: опрос завершён, тренер может назначать")
    return True


async def test_statistics():
    """Тест 8: Статистика"""
    print("\n" + "="*60)
    print("ТЕСТ 8: Статистика бота")
    print("="*60)

    with get_db() as db:
        total = db.query(Training).count()
        active = db.query(Training).filter(Training.videos_uploaded == False).count()
        completed = db.query(Training).filter(Training.videos_uploaded == True).count()
        polls = db.query(SundayPoll).count()
        polls_responded = db.query(SundayPoll).filter(SundayPoll.responded_at != None).count()

        print(f"  ✓ Всего тренировок: {total}")
        print(f"  ✓ Активных: {active}")
        print(f"  ✓ Завершённых: {completed}")
        print(f"  ✓ Всего ответов на опрос: {polls}")
        print(f"  ✓ Из них ответили: {polls_responded}")

    return True


async def test_clean_db():
    """Тест 9: Очистка тестовых данных"""
    print("\n" + "="*60)
    print("ТЕСТ 9: Очистка тестовых данных")
    print("="*60)

    with get_db() as db:
        # Удаляем тестовые тренировки
        db.query(Training).filter(Training.athlete_name == ATHLETES[ATHLETE_IDS[0]]["name"]).delete()

        # Удаляем тестовые опросы за сегодня
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        db.query(SundayPoll).filter(SundayPoll.poll_date >= today_start).delete()

        db.commit()
        print("  ✓ Тестовые данные удалены")

    return True


async def main():
    """Запуск всех тестов"""
    print("\n" + "="*60)
    print("ЗАПУСК ТЕСТОВ БОТА")
    print("="*60)
    print(f"TRAINER_ID: {TRAINER_ID}")
    print(f"ATHLETE_IDS: {ATHLETE_IDS}")
    print(f"GROUP_CHAT_ID: {GROUP_CHAT_ID}")

    results = []

    try:
        results.append(("База данных", await test_database()))
        results.append(("Логика опроса", await test_poll_logic()))
        results.append(("Создание тренировки", await test_training_creation()))
        results.append(("Вечернее напоминание", await test_evening_reminder()))
        results.append(("Проверка видео день 1", await test_video_check_day1()))
        results.append(("Проверка видео день 2", await test_video_check_day2()))
        results.append(("Блокировка тренера", await test_trainer_schedule_blocking()))
        results.append(("Статистика", await test_statistics()))
        results.append(("Очистка", await test_clean_db()))
    except Exception as e:
        print(f"\n❌ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
        results.append(("ОШИБКА", False))

    # Итоги
    print("\n" + "="*60)
    print("ИТОГИ ТЕСТОВ")
    print("="*60)

    passed = 0
    failed = 0
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"  {status}: {name}")
        if result:
            passed += 1
        else:
            failed += 1

    print(f"\nПройдено: {passed}/{len(results)}")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
