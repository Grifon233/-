from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from bot.config import ATHLETE_IDS, ATHLETES


def get_yes_no_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура Да/Нет"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Да"), KeyboardButton(text="Нет")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )


def get_send_keyboard(include_cancel: bool = False) -> ReplyKeyboardMarkup:
    """Клавиатура с кнопкой Отправить"""
    keyboard = [[KeyboardButton(text="Отправить")]]
    if include_cancel:
        keyboard.append([KeyboardButton(text="❌ Отмена")])
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        one_time_keyboard=True
    )


def get_history_keyboard(history: list) -> InlineKeyboardMarkup:
    """Клавиатура с историей полётов"""
    buttons = []
    for idx, schedule in enumerate(history[:4]):
        buttons.append([InlineKeyboardButton(
            text=schedule.replace("\n", ", "),
            callback_data=f"history_{idx}"
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_retry_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для повторного ввода"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Указать время ещё раз", callback_data="retry_schedule")]
        ]
    )


def get_confirm_schedule_keyboard(request_id: str) -> InlineKeyboardMarkup:
    """Клавиатура подтверждения расписания"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"confirm_schedule:{request_id}"),
                InlineKeyboardButton(text="❌ Отменить", callback_data=f"cancel_schedule:{request_id}")
            ]
        ]
    )


def get_trainer_panel() -> ReplyKeyboardMarkup:
    """Панель тренера"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎬 Старт"), KeyboardButton(text="🛠 Панель разработчика")],
            [KeyboardButton(text="📹 Проверить видео"), KeyboardButton(text="📊 Статус опроса")],
            [KeyboardButton(text="📝 Ответ за спортсмена"), KeyboardButton(text="🗓 Тренировки")]
        ],
        resize_keyboard=True
    )


def get_athlete_panel(notifications_enabled: bool = True) -> ReplyKeyboardMarkup:
    """Панель спортсмена"""
    notif_text = "🔕 Уведомления: ВЫКЛ" if notifications_enabled else "🔔 Уведомления: ВКЛ"
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📝 Ответить заранее")],
            [KeyboardButton(text=notif_text)]
        ],
        resize_keyboard=True
    )


def get_trainer_poll_athletes_keyboard(athlete_ids: list[int] | None = None) -> InlineKeyboardMarkup:
    """Выбор спортсмена, за которого тренер отвечает на опрос."""
    athlete_ids = athlete_ids or ATHLETE_IDS
    buttons = [
        [InlineKeyboardButton(
            text=ATHLETES[telegram_id]["name"],
            callback_data=f"trainer_poll_athlete:{telegram_id}"
        )]
        for telegram_id in athlete_ids
    ]
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="trainer_poll_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_cancel_inline_keyboard(callback_data: str = "trainer_poll_cancel") -> InlineKeyboardMarkup:
    """Одна inline-кнопка отмены для коротких сценариев."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data=callback_data)]
    ])


def get_dev_panel() -> ReplyKeyboardMarkup:
    """Панель разработчика"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🧪 Тестовые команды")],
            [KeyboardButton(text="🗑 Удалить тренировку")],
            [KeyboardButton(text="➕ Добавить тренировку")],
            [KeyboardButton(text="📊 Статистика")],
            [KeyboardButton(text="🔄 Перезапуск")],
            [KeyboardButton(text="🔙 Назад")]
        ],
        resize_keyboard=True
    )


def get_test_commands_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура тестовых команд"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📢 Запустить опрос", callback_data="dev_test_poll")],
            [InlineKeyboardButton(text="📹 Проверить видео", callback_data="dev_test_video")],
            [InlineKeyboardButton(text="📨 Отправить напоминание", callback_data="dev_test_reminder")],
            [InlineKeyboardButton(text="⏰ Симуляция времени", callback_data="dev_time_sim")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="dev_back")]
        ]
    )
