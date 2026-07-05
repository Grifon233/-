from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from architect.keyboards.menu import architect_menu_keyboard, main_menu_keyboard
from architect.handlers.start import WELCOME_TEXT
from architect.services.bot_manager import bot_manager
from architect.services.subscription_service import subscription_service

router = Router()


@router.callback_query(F.data.in_(["settings_menu", "settings"]))
async def settings(callback: CallbackQuery):
    status = await bot_manager.get_bot_status(callback.from_user.id)

    # Получаем статус подписки
    sub_status = await subscription_service.get_subscription_status(callback.from_user.id)

    sub_text = "❌ Нет подписки"
    if sub_status["status"] == "active":
        sub_text = "✅ Пожизненная" if sub_status.get("lifetime") else f"✅ Активна ({sub_status.get('days_left', 0)} дн.)"
    elif sub_status["status"] == "trialing":
        sub_text = f"🕐 Пробный период ({sub_status.get('days_left', 0)} дн.)"

    bot_text = "❌ Бот не создан"
    if status:
        bot_username = status.get('username', 'Неизвестно')
        bot_status = status.get('status', 'unknown')
        status_icon = "🟢" if bot_status == "running" else "🟡" if bot_status == "creating" else "🔴"
        bot_text = f"{status_icon} @{bot_username}"

    await callback.message.edit_text(
        "⚙️ Настройки:\n\n"
        f"📱 Бот: {bot_text}\n"
        f"💳 Подписка: {sub_text}\n\n"
        "Выберите действие:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔔 Уведомления", callback_data="settings_notifications")],
            [InlineKeyboardButton(text="📝 Информация о боте", callback_data="settings_bot_info")],
            [InlineKeyboardButton(text="🗑 Удалить моего бота", callback_data="settings_delete_bot_confirm")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")],
        ])
    )
    await callback.answer()


@router.callback_query(F.data == "settings_notifications")
async def notifications_settings(callback: CallbackQuery):
    # Получаем настройки уведомлений мастера
    from backend.database import async_session_maker, Master
    from sqlalchemy import select

    async with async_session_maker() as session:
        result = await session.execute(select(Master).where(Master.telegram_id == callback.from_user.id))
        master = result.scalar_one_or_none()

    notify_new = master.notify_new_bookings if master else True
    notify_reminders = master.notify_reminders if master else True
    reminder_time = master.reminder_time if master else "18:00"
    weekly_report = master.weekly_report_enabled if master else False

    await callback.message.edit_text(
        "🔔 Настройки уведомлений:\n\n"
        "Управляйте уведомлениями о новых записях, напоминаниями клиентам и недельными отчётами.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"{'✅' if notify_new else '⬜'} Новые записи мне",
                callback_data="toggle_new_bookings"
            )],
            [InlineKeyboardButton(
                text=f"{'✅' if notify_reminders else '⬜'} За сутки напомнить клиентам о записи",
                callback_data="toggle_reminders"
            )],
            [InlineKeyboardButton(
                text=f"🕐 Время напоминания: {reminder_time}",
                callback_data="settings_reminder_time"
            )],
            [InlineKeyboardButton(
                text=f"{'✅' if weekly_report else '⬜'} Отправлять в конце недели отчёт",
                callback_data="toggle_weekly_report"
            )],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="settings_menu")],
        ])
    )
    await callback.answer()


@router.callback_query(F.data == "toggle_new_bookings")
async def toggle_new_bookings(callback: CallbackQuery):
    from backend.database import async_session_maker, Master
    from sqlalchemy import select, update

    new_value = False
    async with async_session_maker() as session:
        result = await session.execute(select(Master).where(Master.telegram_id == callback.from_user.id))
        master = result.scalar_one_or_none()

        if master:
            new_value = not (master.notify_new_bookings if master.notify_new_bookings is not None else True)
            await session.execute(
                update(Master).where(Master.id == master.id).values(notify_new_bookings=new_value)
            )
            await session.commit()

    await callback.answer("Настройка обновлена" if new_value else "Уведомления о новых записях выключены", show_alert=True)
    # Перезагружаем меню уведомлений
    await notifications_settings(callback)


@router.callback_query(F.data == "toggle_reminders")
async def toggle_reminders(callback: CallbackQuery):
    from backend.database import async_session_maker, Master
    from sqlalchemy import select, update

    new_value = False
    async with async_session_maker() as session:
        result = await session.execute(select(Master).where(Master.telegram_id == callback.from_user.id))
        master = result.scalar_one_or_none()

        if master:
            new_value = not (master.notify_reminders if master.notify_reminders is not None else True)
            await session.execute(
                update(Master).where(Master.id == master.id).values(notify_reminders=new_value)
            )
            await session.commit()

    await callback.answer("Напоминания обновлены" if new_value else "Напоминания клиентам выключены", show_alert=True)
    await notifications_settings(callback)


@router.callback_query(F.data == "toggle_weekly_report")
async def toggle_weekly_report(callback: CallbackQuery):
    from backend.database import async_session_maker, Master
    from sqlalchemy import select

    new_value = False
    async with async_session_maker() as session:
        master = (await session.execute(
            select(Master).where(Master.telegram_id == callback.from_user.id)
        )).scalar_one_or_none()
        if master:
            master.weekly_report_enabled = not bool(master.weekly_report_enabled)
            new_value = master.weekly_report_enabled
            await session.commit()
    await callback.answer("Недельный отчёт включён" if new_value else "Недельный отчёт выключен", show_alert=True)
    await notifications_settings(callback)


@router.callback_query(F.data == "settings_reminder_time")
async def reminder_time_settings(callback: CallbackQuery):
    times = [f"{hour:02d}:00" for hour in range(24)]
    await callback.message.edit_text(
        "🕐 Выберите время, когда за сутки до записи клиенту придёт напоминание:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=value, callback_data=f"set_reminder_time_{value.replace(':', '')}")
                for value in times[index:index + 4]
            ]
            for index in range(0, len(times), 4)
        ] + [[InlineKeyboardButton(text="◀️ Назад", callback_data="settings_notifications")]])
    )
    await callback.answer()


@router.callback_query(F.data.startswith("set_reminder_time_"))
async def set_reminder_time(callback: CallbackQuery):
    from backend.database import async_session_maker, Master
    from sqlalchemy import select

    raw = callback.data.replace("set_reminder_time_", "")
    value = f"{raw[:2]}:{raw[2:]}"
    async with async_session_maker() as session:
        master = (await session.execute(
            select(Master).where(Master.telegram_id == callback.from_user.id)
        )).scalar_one_or_none()
        if master:
            master.reminder_time = value
            # Выбор времени — явное намерение включить напоминания: иначе мастер
            # ставил время, а уведомления молчали из-за выключенного флага.
            master.notify_reminders = True
            await session.commit()
    await callback.answer(
        f"Напоминание включено: клиентам придёт уведомление за сутки в {value}",
        show_alert=True,
    )
    await notifications_settings(callback)


@router.callback_query(F.data == "settings_bot_info")
async def bot_info_settings(callback: CallbackQuery):
    status = await bot_manager.get_bot_status(callback.from_user.id)
    sub_status = await subscription_service.get_subscription_status(callback.from_user.id)

    if status:
        bot_username = status.get('username') or 'не указан'
        bot_status = status.get('status', 'unknown')
        status_icon = "🟢" if bot_status == "running" else "🟡" if bot_status == "creating" else "🔴"
        status_text = "Работает" if bot_status == "running" else "Создаётся" if bot_status == "creating" else "Ошибка"

        sub_text = "Нет подписки"
        if sub_status["status"] == "active":
            sub_text = "Пожизненная" if sub_status.get("lifetime") else f"Активна ({sub_status.get('days_left', 0)} дней)"
        elif sub_status["status"] == "trialing":
            sub_text = f"Пробный период ({sub_status.get('days_left', 0)} дней)"

        info_text = (
            "📝 Информация о боте\n\n"
            f"Бот: @{bot_username}\n"
            f"Статус: {status_icon} {status_text}\n"
            f"ID: {status.get('bot_id')}\n\n"
            f"Подписка: {sub_text}"
        )
    else:
        info_text = (
            "📝 Информация о боте\n\n"
            "У вас пока нет созданного бота.\n\n"
            "Создайте бота через меню Архитектора."
        )

    await callback.message.edit_text(
        info_text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Удалить бота", callback_data="settings_delete_bot_confirm")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="settings_menu")],
        ])
    )
    await callback.answer()


@router.callback_query(F.data == "settings_delete_bot_confirm")
async def delete_bot_confirm(callback: CallbackQuery):
    status = await bot_manager.get_bot_status(callback.from_user.id)
    if not status:
        await callback.message.edit_text(
            "🗑 Удаление бота\n\n"
            "У вас пока нет созданного бота.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="settings")],
            ])
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        "🗑 Удаление бота\n\n"
        f"Вы уверены, что хотите удалить {status.get('username') or 'бота'}?\n\n"
        "Будут сняты webhook всех ваших ботов и безвозвратно удалены настройки мастера, "
        "услуги, клиенты, записи и подписки. Это действие нельзя отменить.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, удалить бота и базу", callback_data="settings_delete_bot")],
            [InlineKeyboardButton(text="◀️ Отмена", callback_data="settings")],
        ])
    )
    await callback.answer()


@router.callback_query(F.data == "settings_delete_bot")
async def delete_bot(callback: CallbackQuery):
    success = await bot_manager.delete_master_account(callback.from_user.id)
    if success:
        await callback.message.edit_text(
            "✅ Бот и связанные с ним данные удалены.\n\n"
            "Вы можете создать нового бота через меню.",
            reply_markup=architect_menu_keyboard(user_id=callback.from_user.id)
        )
        await callback.answer("Бот удалён")
    else:
        await callback.message.edit_text(
            "❌ Бот не найден.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="settings")],
            ])
        )
        await callback.answer()


@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        WELCOME_TEXT,
        reply_markup=await main_menu_keyboard(callback.from_user.id),
    )
    await callback.answer()
