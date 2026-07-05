import logging
from datetime import datetime
from pathlib import Path
import subprocess

from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from aiogram import Bot

from architect.keyboards.menu import architect_menu_keyboard
from architect.services.bot_manager import bot_manager
from architect.services.subscription_service import subscription_service
from architect.handlers.start import WELCOME_TEXT
from architect.config import settings

# Bot instance — устанавливается при старте в architect/main.py
_admin_bot: Bot | None = None


def set_admin_bot(bot: Bot):
    global _admin_bot
    _admin_bot = bot

router = Router()

# Логирование всех опасных команд
admin_logger = logging.getLogger("admin_commands")
admin_logger.setLevel(logging.INFO)
Path("logs").mkdir(exist_ok=True)
admin_handler = logging.FileHandler("logs/admin_commands.log")
admin_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
admin_logger.addHandler(admin_handler)

SUPERADMIN_ID = 623597334
ALLOWED_STATIC_DIR = Path("/var/www/master-booking/static").resolve()
ALLOWED_ASSETS_DIR = ALLOWED_STATIC_DIR / "assets"
ALLOWED_SUFFIXES = {".js", ".css", ".html"}
STATIC_DIRS = {
    ".js": ALLOWED_ASSETS_DIR,
    ".css": ALLOWED_ASSETS_DIR,
    ".html": ALLOWED_STATIC_DIR,
}


def _is_dangerous_enabled() -> bool:
    """Проверить, включены ли опасные команды."""
    return settings.admin_dangerous_commands_enabled


def _log_command(user_id: int, username: str | None, command: str, detail: str = ""):
    """Записать действие в лог."""
    who = f"user={user_id}"
    if username:
        who += f" ({username})"
    admin_logger.info(f"[{command}] {who} | {detail}")


def _reject_disabled(message: Message, command: str) -> bool:
    """Проверить флаг и ответить если выключено."""
    if not _is_dangerous_enabled():
        _log_command(message.from_user.id, message.from_user.username, command, "REJECTED — disabled")
        # Не говорим в ответ почему — безопасность через неясность
        return True
    return False


# Состояния для загрузки файлов
class DeployState(StatesGroup):
    waiting_for_file = State()


# Команда /id - получить свой Telegram ID
@router.message(Command("id"))
async def cmd_get_id(message):
    await message.answer(
        f"📌 Ваш ID: <code>{message.from_user.id}</code>\n\n"
        "Отправьте этот номер главному мастеру для добавления в аккаунт.",
        parse_mode="HTML"
    )


# Команда /menu - вернуться в меню
@router.message(Command("menu"))
async def cmd_menu(message):
    await message.answer(
        "Главное меню:",
        reply_markup=architect_menu_keyboard(user_id=message.from_user.id)
    )


# Команда /start
@router.message(Command("start"))
async def cmd_start(message):
    await message.answer(
        WELCOME_TEXT,
        reply_markup=architect_menu_keyboard(user_id=message.from_user.id)
    )


# Команда /stats - только для админа
@router.message(Command("stats"))
async def cmd_stats(message):
    if message.from_user.id != SUPERADMIN_ID:
        await message.answer("❌ Эта команда доступна только главному администратору.")
        return

    stats = await subscription_service.get_all_stats()
    text = (
        "📊 Статистика системы:\n\n"
        f"Всего мастеров: {stats['total_masters']}\n"
        f"Активных подписок: {stats['active_subscriptions']}\n"
        f"Истёкших подписок: {stats['expired_subscriptions']}\n"
        f"Всего клиентов: {stats['total_clients']}\n"
    )
    await message.answer(text)


# Команда /masters - список всех мастеров - только для админа
@router.message(Command("masters"))
async def cmd_masters(message):
    if message.from_user.id != SUPERADMIN_ID:
        await message.answer("❌ Эта команда доступна только главному администратору.")
        return

    masters = await subscription_service.get_all_masters()
    if not masters:
        await message.answer("📋 Мастеров пока нет.")
        return

    lines = ["📋 Все мастера:\n"]
    for m in masters:
        status = "🟢" if m['is_active'] else "🔴"
        days_left = m.get('days_left', 0)
        lines.append(
            f"{status} {m['name']} ({m.get('username', 'N/A')})\n"
            f"   Подписка: {days_left} дн. осталось\n"
            f"   Клиентов: {m.get('client_count', 0)}\n"
        )
    await message.answer("\n".join(lines))


# Команда /broadcast - отправить сообщение всем мастерам
@router.message(Command("broadcast"))
async def cmd_broadcast(message):
    if message.from_user.id != SUPERADMIN_ID:
        await message.answer("❌ Эта команда доступна только главному администратору.")
        return

    text = message.text.replace("/broadcast", "").strip()
    if not text:
        await message.answer("❌ Укажите сообщение: /broadcast <текст>")
        return

    sent = await subscription_service.broadcast_to_masters(text)
    await message.answer(f"✅ Сообщение отправлено {sent} мастерам.")


# Команда /deploy - загрузить файл на сервер (только для админа)
@router.message(Command("deploy"))
async def cmd_deploy(message: Message, state: FSMContext):
    if message.from_user.id != SUPERADMIN_ID:
        await message.answer("❌ Эта команда доступна только главному администратору.")
        return

    if _reject_disabled(message, "deploy"):
        await message.answer("❌ Эта команда сейчас недоступна.")
        return

    _log_command(message.from_user.id, message.from_user.username, "deploy", "ENTER")
    await state.set_state(DeployState.waiting_for_file)
    await message.answer(
        "📦 Режим загрузки файла\n\n"
        "Отправьте файл для загрузки на сервер.\n"
        "Допустимые типы: .js, .css, .html\n"
        f"Файлы сохраняются в: {ALLOWED_STATIC_DIR}"
    )


# Обработка загруженного файла
@router.message(DeployState.waiting_for_file, F.document)
async def handle_deploy_file(message: Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username

    if user_id != SUPERADMIN_ID:
        await state.clear()
        _log_command(user_id, username, "deploy", "REJECTED — not superadmin")
        await message.answer("❌ Доступ запрещён.")
        return

    doc = message.document
    file_name = Path(doc.file_name or "unknown").name
    suffix = Path(file_name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        await state.clear()
        _log_command(user_id, username, "deploy", f"REJECTED — bad suffix '{suffix}' for '{file_name}'")
        await message.answer("❌ Можно загружать только .js, .css и .html файлы.")
        return

    try:
        if _admin_bot is None:
            _log_command(user_id, username, "deploy", "ERROR: bot not set")
            await message.answer("❌ Внутренняя ошибка: bot не инициализирован.")
            return

        file = await _admin_bot.get_file(doc.file_id)
        file_content = await _admin_bot.download_file(file.file_path)

        target_dir = STATIC_DIRS.get(suffix, ALLOWED_ASSETS_DIR)
        target_dir_path = target_dir.resolve()
        target_path = (target_dir_path / file_name).resolve()

        # Защита path traversal: файл должен быть внутри разрешённого каталога
        if target_dir_path not in target_path.parents:
            await state.clear()
            _log_command(user_id, username, "deploy", f"REJECTED — path traversal '{target_path}'")
            await message.answer("❌ Недопустимое имя файла.")
            return

        target_dir_path.mkdir(parents=True, exist_ok=True)

        if hasattr(file_content, "read"):
            file_content = file_content.read()

        target_path.write_bytes(file_content)
        _log_command(user_id, username, "deploy", f"OK -> {target_path} ({len(file_content)} bytes)")

        if file_name.endswith(".html"):
            subprocess.run(["sudo", "systemctl", "reload", "nginx"], check=False, timeout=30)
            _log_command(user_id, username, "deploy", "nginx reloaded")

        await message.answer(
            f"✅ Файл загружен!\n\n"
            f"📁 Путь: {target_path}\n"
            f"📏 Размер: {len(file_content):,} байт"
        )
    except Exception as e:
        _log_command(user_id, username, "deploy", f"ERROR: {e}")
        await message.answer(f"❌ Ошибка: {str(e)}")
    finally:
        await state.clear()


# Отмена загрузки
@router.message(DeployState.waiting_for_file, F.text & ~F.document)
async def cancel_deploy(message: Message, state: FSMContext):
    if message.text.lower() in ["отмена", "cancel", "/cancel"]:
        await state.clear()
        await message.answer("❌ Загрузка отменена.")
    else:
        await message.answer("Пожалуйста, отправьте файл или напишите 'отмена'.")


# Команда /restartapi - перезапустить API сервер (только для админа)
@router.message(Command("restartapi"))
async def cmd_restart_api(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username

    if user_id != SUPERADMIN_ID:
        await message.answer("❌ Эта команда доступна только главному администратору.")
        return

    if _reject_disabled(message, "restartapi"):
        await message.answer("❌ Эта команда сейчас недоступна.")
        return

    _log_command(user_id, username, "restartapi", "EXEC")
    try:
        result = subprocess.run(
            ["sudo", "systemctl", "restart", "master-booking-api"],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            _log_command(user_id, username, "restartapi", "OK")
            await message.answer("✅ API сервер перезапущен!")
        else:
            _log_command(user_id, username, "restartapi", f"FAIL: {result.stderr}")
            await message.answer(f"❌ Ошибка: {result.stderr}")
    except Exception as e:
        _log_command(user_id, username, "restartapi", f"ERROR: {e}")
        await message.answer(f"❌ Ошибка: {str(e)}")
