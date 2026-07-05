import aiohttp
import asyncio
import logging
import urllib.parse
from typing import Optional
from datetime import datetime
from bot.config import YANDEX_DISK_TOKEN, YANDEX_DISK_BASE_PATH, VIDEO_FORMATS, MIN_VIDEOS_COUNT
from bot.utils.parsers import resolve_training_datetime

logger = logging.getLogger(__name__)

# YANDEX_DISK_BASE_PATH может содержать "disk:" префикс из .env
# Храним ВСЕГДА чистый путь (без disk:) для использования в URL и ссылках
def _clean_base_path(path: str) -> str:
    """Убирает disk: префикс, возвращает чистый путь для URL и конкатенации."""
    if not path:
        return ""
    # убираем disk: или disk:/ в начале
    clean = path
    if clean.startswith("disk:"):
        clean = clean[5:]  # убираем "disk:"
    if clean.startswith("/"):
        clean = clean[1:]  # убираем ведущий /
    return clean

# Чистый путь без disk: — используется во всей логике
CLEAN_BASE_PATH = _clean_base_path(YANDEX_DISK_BASE_PATH or "")


class YandexDiskService:
    def __init__(self):
        self.token = YANDEX_DISK_TOKEN
        self.base_url = "https://cloud-api.yandex.net/v1/disk"
        self.headers = {
            "Authorization": f"OAuth {self.token}",
            "Content-Type": "application/json"
        }
        self.timeout = aiohttp.ClientTimeout(total=20)

    def _api_path(self, clean_path: str) -> str:
        """Преобразует чистый путь в путь для API (с префиксом disk:)."""
        if clean_path.startswith("disk:"):
            return clean_path
        if clean_path.startswith("/"):
            return f"disk:{clean_path}"
        return f"disk:/{clean_path}"

    def _url_path(self, clean_path: str) -> str:
        """Преобразует чистый путь в публичную URL-ссылку."""
        if not clean_path.startswith("/"):
            clean_path = "/" + clean_path
        encoded = urllib.parse.quote(clean_path, safe="/")
        return f"https://disk.yandex.ru/client/disk{encoded}"

    def _month_folder_name(self, month: int) -> str:
        month_names = {
            1: "январь", 2: "февраль", 3: "март", 4: "апрель",
            5: "май", 6: "июнь", 7: "июль", 8: "август",
            9: "сентябрь", 10: "октябрь", 11: "ноябрь", 12: "декабрь"
        }
        month_name = month_names.get(month, "")
        return f"{month:02d} {month_name}"

    async def _resolve_existing_training_path(self, path: str) -> str:
        """
        Найти существующую папку тренировки.

        Старые папки могут называться ДД.ММ.ГГ, а новые записи в БД содержат
        путь ДД.ММ. Поддерживаем оба формата, чтобы проверка не давала ложный 0.
        """
        exact_info = await self.get_folder_info(path)
        if exact_info:
            return path

        parent_path, separator, folder_name = path.rpartition("/")
        if not separator or not parent_path:
            return path

        try:
            datetime.strptime(folder_name, "%d.%m")
        except ValueError:
            return path

        parent_info = await self.get_folder_info(parent_path)
        items = (parent_info or {}).get("_embedded", {}).get("items", [])
        candidates = [
            item
            for item in items
            if item.get("type") == "dir"
            and (
                item.get("name") == folder_name
                or str(item.get("name") or "").startswith(f"{folder_name}.")
            )
        ]
        if not candidates:
            return path

        candidate = sorted(candidates, key=lambda item: item.get("name", ""))[-1]
        return f"{parent_path}/{candidate['name']}"

    async def create_folder(self, path: str) -> bool:
        """Создать папку на Яндекс.Диске. Ожидает ЧИСТЫЙ путь (без disk:)."""
        api_path = self._api_path(path)
        url = f"{self.base_url}/resources"
        params = {"path": api_path}

        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            try:
                async with session.put(url, headers=self.headers, params=params) as response:
                    if response.status in [201, 409]:  # 409 = папка уже существует
                        return True
                    return False
            except Exception as e:
                logger.error(f"Error creating folder: {e}", exc_info=True)
                return False

    async def get_folder_info(self, path: str) -> Optional[dict]:
        """Получить информацию о папке. Ожидает ЧИСТЫЙ путь."""
        api_path = self._api_path(path)
        url = f"{self.base_url}/resources"
        params = {"path": api_path}

        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            try:
                async with session.get(url, headers=self.headers, params=params) as response:
                    if response.status == 200:
                        return await response.json()
                    return None
            except Exception as e:
                logger.error(f"Error getting folder info: {e}", exc_info=True)
                return None

    async def get_public_link(self, path: str) -> Optional[str]:
        """Получить публичную ссылку на папку. Ожидает ЧИСТЫЙ путь."""
        # Убеждаемся что путь чистый (без disk:)
        if path.startswith("disk:"):
            path = path[5:]
        if path.startswith("/"):
            path = path[1:]
        return self._url_path(path)

    async def _is_path_safe(self, path: str) -> bool:
        """Проверяет что путь безопасен для удаления."""
        if not path:
            return False
        if not CLEAN_BASE_PATH:
            logger.warning("YANDEX_DISK_BASE_PATH not configured")
            return False

        decoded_path = urllib.parse.unquote(path)

        normalized_base = CLEAN_BASE_PATH
        if not normalized_base.endswith('/'):
            normalized_base += '/'
        if not decoded_path.endswith('/'):
            decoded_path += '/'

        if not decoded_path.startswith(normalized_base):
            return False

        relative = decoded_path[len(normalized_base):].strip('/')
        depth = len([p for p in relative.split('/') if p])
        if depth < 1:
            return False

        return True

    async def _is_folder_empty(self, clean_path: str) -> bool:
        """Проверяет что папка пустая. Ожидает ЧИСТЫЙ путь."""
        folder_info = await self.get_folder_info(clean_path)

        if not folder_info:
            return True  # Папка не существует - считаем что "пустая"

        if "_embedded" not in folder_info:
            return True

        items = folder_info["_embedded"].get("items", [])
        return len(items) == 0

    async def delete_folder(self, path: str) -> tuple[bool, str]:
        """
        Безопасно удалить папку.
        Ожидает ЧИСТЫЙ путь (без disk:).
        """
        decoded_path = urllib.parse.unquote(path)

        if not await self._is_path_safe(path):
            logger.warning(f"Blocked attempt to delete unsafe path: {path}")
            return False, "Путь небезопасен для удаления"

        if not await self._is_folder_empty(decoded_path):
            logger.warning(f"Blocked attempt to delete non-empty folder: {path}")
            return False, "Нельзя удалить непустую папку"

        api_path = self._api_path(path)
        url = f"{self.base_url}/resources"
        params = {"path": api_path}

        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            try:
                async with session.delete(url, headers=self.headers, params=params) as response:
                    if response.status == 204:
                        logger.info(f"Successfully deleted folder: {path}")
                        return True, ""
                    elif response.status == 404:
                        return False, "Папка не найдена"
                    elif response.status == 409:
                        return False, "Папка не пуста или недоступна"
                    else:
                        text = await response.text()
                        logger.error(f"Error deleting folder {path}: {response.status} - {text}")
                        return False, f"Ошибка удаления: {response.status}"
            except Exception as e:
                logger.error(f"Exception deleting folder {path}: {e}", exc_info=True)
                return False, f"Исключение: {e}"

    async def delete_training_folder(self, athlete_name: str, date: str) -> tuple[bool, str]:
        """Удалить папку тренировки."""
        resolved_date = resolve_training_datetime(date)
        if not resolved_date:
            return False, "Не удалось определить дату тренировки"

        folder_path = f"{CLEAN_BASE_PATH}/{self._month_folder_name(resolved_date.month)}/{athlete_name}/{date}"

        return await self.delete_folder(folder_path)

    async def count_videos(self, path: str) -> int:
        """Подсчитать все видео в папке с учётом пагинации Яндекс.Диска."""
        if not path:
            raise ValueError("Путь к папке не указан")

        path = await self._resolve_existing_training_path(path)
        api_path = self._api_path(path)
        url = f"{self.base_url}/resources"
        limit = 1000
        offset = 0
        video_count = 0

        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            while True:
                params = {
                    "path": api_path,
                    "limit": limit,
                    "offset": offset,
                }
                async with session.get(url, headers=self.headers, params=params) as response:
                    if response.status != 200:
                        text = await response.text()
                        raise RuntimeError(
                            f"Яндекс.Диск вернул {response.status} для {path}: {text[:200]}"
                        )
                    folder_info = await response.json()

                embedded = folder_info.get("_embedded")
                if embedded is None:
                    raise RuntimeError(f"Яндекс.Диск не вернул содержимое папки: {path}")

                items = embedded.get("items", [])
                for item in items:
                    if self._is_video_file(item):
                        video_count += 1

                offset += len(items)
                total = embedded.get("total")
                if not items or (isinstance(total, int) and offset >= total):
                    break

        return video_count

    @staticmethod
    def _is_video_file(item: dict) -> bool:
        if item.get("type") != "file":
            return False

        media_type = str(item.get("media_type") or "").lower()
        mime_type = str(item.get("mime_type") or "").lower()
        file_name = str(item.get("name") or "").lower()

        return (
            media_type == "video"
            or mime_type.startswith("video/")
            or any(file_name.endswith(fmt.lower()) for fmt in VIDEO_FORMATS)
        )

    async def check_videos_uploaded(self, path: str) -> bool:
        """Проверить, загружено ли минимальное количество видео"""
        count = await self.count_videos(path)
        return count >= MIN_VIDEOS_COUNT

    async def create_month_folder(self, month: int, year: int) -> bool:
        """Создать папку для месяца."""
        folder_name = self._month_folder_name(month)
        folder_path = f"{CLEAN_BASE_PATH}/{folder_name}"

        return await self.create_folder(folder_path)

    async def create_athlete_folders(self, month: int, year: int, athletes: dict) -> bool:
        """Создать папки для всех спортсменов в месяце."""
        month_folder = f"{CLEAN_BASE_PATH}/{self._month_folder_name(month)}"

        if not await self.create_folder(month_folder):
            logger.error("Failed to create month folder: %s", month_folder)
            return False

        all_created = True
        for athlete_data in athletes.values():
            athlete_folder = f"{month_folder}/{athlete_data['name']}"
            if not await self.create_folder(athlete_folder):
                logger.error("Failed to create athlete folder: %s", athlete_folder)
                all_created = False

        return all_created

    async def create_training_folder(self, athlete_name: str, date: str) -> tuple[str, Optional[str]]:
        """
        Создать папку для тренировки.
        Возвращает (путь к папке тренировки, публичная ссылка на неё).
        """
        resolved_date = resolve_training_datetime(date)
        if not resolved_date or not CLEAN_BASE_PATH:
            return "", None

        month_folder = f"{CLEAN_BASE_PATH}/{self._month_folder_name(resolved_date.month)}"
        athlete_folder = f"{month_folder}/{athlete_name}"
        short_path = f"{athlete_folder}/{date}"

        if not await self.create_folder(month_folder):
            logger.error("Failed to create month folder for training: %s", month_folder)
            return "", None
        if not await self.create_folder(athlete_folder):
            logger.error("Failed to create athlete folder for training: %s", athlete_folder)
            return "", None

        folder_path = await self._resolve_existing_training_path(short_path)
        if folder_path == short_path:
            if not await self.create_folder(folder_path):
                logger.error("Failed to create training folder: %s", folder_path)
                return "", None
            if not await self.get_folder_info(folder_path):
                logger.error("Training folder was not found after creation: %s", folder_path)
                return "", None

        public_link = await self.get_public_link(folder_path)
        if not public_link:
            return "", None

        return folder_path, public_link

yandex_disk = YandexDiskService()
