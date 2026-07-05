"""Тонкий клиент VK API для сообщество-ботов мастеров.

Канал VK — зеркало Telegram-канала. Бот принимает сообщения через Bots Long
Poll API (нужен scope «Управление сообществом») и отвечает через messages.send.
"""
import asyncio
import hashlib
import io
import json
import logging
import random
import time
from pathlib import Path
from urllib.parse import urlsplit
from typing import Any, Optional

import httpx
from PIL import Image  # apt: python3-pil
from backend.media_storage import PUBLIC_UPLOAD_PREFIX, get_upload_dir

logger = logging.getLogger(__name__)

VK_API_VERSION = "5.199"
VK_API_BASE = "https://api.vk.com/method"
_PHOTO_CACHE_TTL_SECONDS = 6 * 60 * 60
_PHOTO_DISK_CACHE_TTL_SECONDS = 30 * 24 * 60 * 60
_PHOTO_CACHE_MAX_ITEMS = 512
_photo_attachment_cache: dict[tuple[str, str], tuple[float, str]] = {}
_photo_upload_locks: dict[tuple[str, str], asyncio.Lock] = {}
_document_attachment_cache: dict[tuple[str, str], str] = {}
_document_upload_locks: dict[tuple[str, str], asyncio.Lock] = {}
_persistent_photo_cache: dict[str, dict[str, Any]] = {}
_persistent_photo_cache_loaded = False
_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(30.0, connect=5.0),
            limits=httpx.Limits(max_connections=30, max_keepalive_connections=15, keepalive_expiry=30.0),
        )
    return _http_client


async def close_http_client() -> None:
    global _http_client
    if _http_client is not None and not _http_client.is_closed:
        await _http_client.aclose()
    _http_client = None


def _persistent_cache_path():
    return get_upload_dir() / ".vk_attachment_cache.json"


def _load_persistent_photo_cache() -> None:
    global _persistent_photo_cache_loaded, _persistent_photo_cache
    if _persistent_photo_cache_loaded:
        return
    _persistent_photo_cache_loaded = True
    try:
        data = json.loads(_persistent_cache_path().read_text(encoding="utf-8"))
        if isinstance(data, dict):
            _persistent_photo_cache = data
    except (FileNotFoundError, OSError, ValueError):
        _persistent_photo_cache = {}


def _persistent_cache_key(token_key: str, photo_url: str) -> str:
    return hashlib.sha256(f"{token_key}\0{photo_url}".encode("utf-8")).hexdigest()


def _get_cached_attachment(token_key: str, photo_url: str) -> str | None:
    cached = _photo_attachment_cache.get((token_key, photo_url))
    if cached and time.monotonic() - cached[0] < _PHOTO_CACHE_TTL_SECONDS:
        return cached[1]

    _load_persistent_photo_cache()
    disk_cached = _persistent_photo_cache.get(_persistent_cache_key(token_key, photo_url))
    if not isinstance(disk_cached, dict):
        return None
    if time.time() - float(disk_cached.get("saved_at") or 0) > _PHOTO_DISK_CACHE_TTL_SECONDS:
        return None
    attachment = disk_cached.get("attachment")
    if not isinstance(attachment, str) or not attachment.startswith("photo"):
        return None
    _photo_attachment_cache[(token_key, photo_url)] = (time.monotonic(), attachment)
    return attachment


def _save_persistent_photo_cache() -> None:
    cache_path = _persistent_cache_path()
    temporary_path = cache_path.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(_persistent_photo_cache, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    temporary_path.replace(cache_path)


class VkApiError(Exception):
    """Ошибка VK API с кодом и человекочитаемым сообщением."""

    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"VK API error {code}: {message}")


async def vk_call(method: str, token: str, params: dict[str, Any] | None = None, timeout: float = 30.0) -> Any:
    """Вызвать метод VK API. Возвращает содержимое response или бросает VkApiError."""
    payload = {k: v for k, v in (params or {}).items() if v is not None}
    payload["access_token"] = token
    payload["v"] = VK_API_VERSION
    resp = await _get_http_client().post(
        f"{VK_API_BASE}/{method}",
        data=payload,
        timeout=timeout,
    )
    data = resp.json()
    if "error" in data:
        err = data["error"]
        raise VkApiError(err.get("error_code", -1), err.get("error_msg", "unknown error"))
    return data.get("response")


# Обязательные права ключа сообщества. Без любого из них бот не работает.
REQUIRED_TOKEN_SCOPES = {
    "manage": "Управление сообществом",
    "messages": "Доступ к сообщениям сообщества",
    "photos": "Доступ к фотографиям сообщества",
}


async def get_token_permissions(token: str) -> set[str]:
    """Возвращает множество выданных ключу scope-имён (manage, messages, photos, ...).

    VK в зависимости от версии API кладёт список под ключ "permissions" (5.199)
    или "settings" (старые версии) — поддерживаем оба, иначе валидный ключ
    ошибочно считался без прав.
    """
    data = await vk_call("groups.getTokenPermissions", token)
    if not isinstance(data, dict):
        return set()
    items = data.get("permissions") or data.get("settings") or []
    return {item.get("name") for item in items if isinstance(item, dict) and item.get("name")}


async def validate_community_token(token: str) -> dict:
    """Проверяет токен сообщества и наличие нужных прав.

    Возвращает {"group_id": int, "group_name": str}.
    Бросает ValueError с понятным текстом, если токен невалиден или ключу не
    выданы все три обязательные галочки (управление, сообщения, фотографии),
    без которых бот не сможет работать.
    """
    try:
        groups = await vk_call("groups.getById", token)
    except VkApiError as e:
        if e.code == 5:
            raise ValueError("Ключ недействителен. Скопируйте его заново из настроек сообщества.")
        raise ValueError(f"Не удалось проверить ключ: {e.message}")
    except Exception as e:
        raise ValueError(f"Не удалось связаться с ВКонтакте: {e}")

    # VK возвращает либо список, либо {"groups": [...]} в зависимости от версии.
    if isinstance(groups, dict):
        groups = groups.get("groups", [])
    if not groups:
        raise ValueError("Не удалось определить сообщество по этому ключу.")
    group = groups[0]
    group_id = group.get("id")
    group_name = group.get("name") or "Сообщество"

    # Жёстко требуем все три галочки: проверяем фактически выданные ключу права.
    try:
        granted_scopes = await get_token_permissions(token)
    except VkApiError as e:
        if e.code == 5:
            raise ValueError("Ключ недействителен. Скопируйте его заново из настроек сообщества.")
        raise ValueError(f"Не удалось проверить права ключа: {e.message}")
    except Exception as e:
        raise ValueError(f"Не удалось связаться с ВКонтакте: {e}")

    missing = [label for scope, label in REQUIRED_TOKEN_SCOPES.items() if scope not in granted_scopes]
    if missing:
        raise ValueError(
            "Этот ключ принять нельзя: при его создании отмечены не все галочки, "
            "поэтому бот работать не будет.\n\n"
            "Не хватает прав:\n"
            + "\n".join(f"• {label}" for label in missing)
            + "\n\nСоздайте ключ заново, отметив все три галочки сразу, и пришлите новый ключ."
        )

    # Проверяем scope «Управление сообществом» и сразу включаем Long Poll.
    # setLongPollSettings требует manage-права — если ошибка 15, значит прав нет.
    # getLongPollServer вместо этого давал ошибку 100 "longpoll for this group is not enabled"
    # у новых сообществ, где longpoll ещё не активирован.
    try:
        await vk_call(
            "groups.setLongPollSettings",
            token,
            {
                "group_id": group_id,
                "enabled": 1,
                "api_version": VK_API_VERSION,
                "message_new": 1,
            },
        )
    except VkApiError as e:
        if e.code == 15:
            raise ValueError(
                "Ключу не хватает прав «Управление сообществом». "
                "Создайте ключ заново и отметьте галочку «Управление сообществом» "
                "вместе с «Доступ к сообщениям сообщества»."
            )
        raise ValueError(f"Не удалось включить приём сообщений: {e.message}")

    return {"group_id": group_id, "group_name": group_name}


async def ensure_long_poll_enabled(token: str, group_id: int) -> None:
    """Включает Long Poll и событие message_new для сообщества."""
    await vk_call(
        "groups.setLongPollSettings",
        token,
        {
            "group_id": group_id,
            "enabled": 1,
            "api_version": VK_API_VERSION,
            "message_new": 1,
        },
    )


async def get_long_poll_server(token: str, group_id: int) -> dict:
    """Возвращает {"key", "server", "ts"} для Bots Long Poll."""
    return await vk_call("groups.getLongPollServer", token, {"group_id": group_id})


async def send_message(
    token: str,
    peer_id: int,
    message: str,
    keyboard: Optional[dict] = None,
    attachment: Optional[str] = None,
    dont_parse_links: bool = False,
) -> bool:
    """Отправляет сообщение от имени сообщества."""
    params: dict[str, Any] = {
        "peer_id": peer_id,
        "message": message,
        "random_id": random.randint(1, 2**31 - 1),
    }
    if keyboard is not None:
        params["keyboard"] = json.dumps(keyboard, ensure_ascii=False)
    if attachment:
        params["attachment"] = attachment
    if dont_parse_links:
        params["dont_parse_links"] = 1
    try:
        await vk_call("messages.send", token, params)
        return True
    except Exception as e:
        logger.warning("VK send_message failed for peer %s: %s", peer_id, e)
        return False


def _compress_image(data: bytes, content_type: str, max_size: int = 1280, quality: int = 82) -> tuple[bytes, str]:
    """Сжимает изображение до max_size px по длинной стороне и конвертирует в JPEG."""
    if content_type in {"image/jpeg", "image/jpg"} and len(data) <= 512 * 1024:
        return data, "image/jpeg"
    try:
        img = Image.open(io.BytesIO(data))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        w, h = img.size
        if w > max_size or h > max_size:
            img.thumbnail((max_size, max_size), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        return buf.getvalue(), "image/jpeg"
    except Exception:
        return data, content_type


async def _load_photo_payload(photo_url: str) -> tuple[str, bytes, str]:
    source_path = urlsplit(photo_url).path
    if source_path.startswith(PUBLIC_UPLOAD_PREFIX):
        filename = source_path.removeprefix(PUBLIC_UPLOAD_PREFIX)
        candidate = (get_upload_dir() / filename).resolve()
        upload_root = get_upload_dir().resolve()
        if candidate.parent == upload_root and candidate.is_file():
            data = await asyncio.to_thread(candidate.read_bytes)
            content_type = "image/jpeg" if candidate.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
            data, content_type = await asyncio.to_thread(_compress_image, data, content_type)
            return candidate.name, data, content_type

    response = await _get_http_client().get(photo_url, timeout=httpx.Timeout(15.0, connect=5.0))
    response.raise_for_status()
    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
    if not content_type.startswith("image/"):
        raise ValueError(f"Media source is not an image: {content_type or 'unknown'}")
    data, content_type = await asyncio.to_thread(_compress_image, response.content, content_type)
    filename = source_path.rsplit("/", 1)[-1] or "photo.jpg"
    return filename, data, content_type


def _cache_attachment(token_key: str, photo_url: str, attachment: str) -> None:
    if len(_photo_attachment_cache) >= _PHOTO_CACHE_MAX_ITEMS:
        oldest_key = min(_photo_attachment_cache, key=lambda key: _photo_attachment_cache[key][0])
        _photo_attachment_cache.pop(oldest_key, None)
        _photo_upload_locks.pop(oldest_key, None)
    _photo_attachment_cache[(token_key, photo_url)] = (time.monotonic(), attachment)
    _load_persistent_photo_cache()
    _persistent_photo_cache[_persistent_cache_key(token_key, photo_url)] = {
        "attachment": attachment,
        "saved_at": int(time.time()),
    }
    if len(_persistent_photo_cache) > _PHOTO_CACHE_MAX_ITEMS:
        oldest_keys = sorted(
            _persistent_photo_cache,
            key=lambda key: float((_persistent_photo_cache.get(key) or {}).get("saved_at") or 0),
        )[:len(_persistent_photo_cache) - _PHOTO_CACHE_MAX_ITEMS]
        for key in oldest_keys:
            _persistent_photo_cache.pop(key, None)
    try:
        _save_persistent_photo_cache()
    except OSError as exc:
        logger.warning("VK attachment cache could not be persisted: %s", exc)


async def upload_photo_for_message(token: str, peer_id: int, photo_url: str) -> Optional[str]:
    """Загружает фото из URL в VK для отправки в сообщении (требует scope photos).
    Возвращает строку вложения 'photo{owner_id}_{id}' или None при ошибке."""
    token_key = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
    cache_key = (token_key, photo_url)
    cached = _get_cached_attachment(token_key, photo_url)
    if cached:
        return cached

    lock = _photo_upload_locks.setdefault(cache_key, asyncio.Lock())
    async with lock:
        cached = _get_cached_attachment(token_key, photo_url)
        if cached:
            return cached

        try:
            upload_server_res, payload = await asyncio.gather(
                vk_call("photos.getMessagesUploadServer", token, {"peer_id": peer_id}, timeout=12.0),
                _load_photo_payload(photo_url),
            )
            upload_url = upload_server_res.get("upload_url") if upload_server_res else None
            if not upload_url:
                return None
            filename, photo_data, content_type = payload
            upload_resp = await _get_http_client().post(
                upload_url,
                files={"file1": (filename, photo_data, content_type)},
                timeout=httpx.Timeout(15.0, connect=5.0),
            )
            upload_resp.raise_for_status()
            body = upload_resp.text.strip()
            if not body:
                logger.warning("VK upload server returned empty body for %s", photo_url)
                return None
            ud = json.loads(body)
            saved = await vk_call("photos.saveMessagesPhoto", token, {
                "photo": ud.get("photo"), "server": ud.get("server"), "hash": ud.get("hash"),
            }, timeout=12.0)
            photo = (saved[0] if isinstance(saved, list) else saved) if saved else None
            if photo and photo.get("owner_id") and photo.get("id"):
                attachment = f"photo{photo['owner_id']}_{photo['id']}"
                _cache_attachment(token_key, photo_url, attachment)
                return attachment
        except Exception as e:
            logger.warning("VK photo upload failed for %s: %s", photo_url, e)
    return None


async def upload_document_for_message(
    token: str,
    peer_id: int,
    file_path: str | Path,
    title: str | None = None,
) -> Optional[str]:
    """Загружает локальный файл в VK-сообщение как документ.

    Используется для коротких видеоинструкций: если у ключа сообщества VK нет
    нужных прав или загрузка временно недоступна, возвращает None и не ломает
    основной сценарий.
    """
    path = Path(file_path)
    try:
        stat = await asyncio.to_thread(path.stat)
    except OSError as exc:
        logger.warning("VK document source is unavailable: %s", exc)
        return None

    token_key = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
    source_key = f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}"
    cache_key = (token_key, source_key)
    cached = _document_attachment_cache.get(cache_key)
    if cached:
        return cached

    lock = _document_upload_locks.setdefault(cache_key, asyncio.Lock())
    async with lock:
        cached = _document_attachment_cache.get(cache_key)
        if cached:
            return cached
        try:
            upload_server = await vk_call(
                "docs.getMessagesUploadServer",
                token,
                {"peer_id": peer_id, "type": "doc"},
                timeout=12.0,
            )
            upload_url = upload_server.get("upload_url") if upload_server else None
            if not upload_url:
                return None
            data = await asyncio.to_thread(path.read_bytes)
            upload_response = await _get_http_client().post(
                upload_url,
                files={"file": (path.name, data, "video/mp4")},
                timeout=httpx.Timeout(90.0, connect=8.0),
            )
            upload_response.raise_for_status()
            upload_data = upload_response.json()
            saved = await vk_call(
                "docs.save",
                token,
                {"file": upload_data.get("file"), "title": title or path.name},
                timeout=20.0,
            )
            doc = saved.get("doc") if isinstance(saved, dict) else None
            if isinstance(doc, list):
                doc = doc[0] if doc else None
            if isinstance(doc, dict) and doc.get("owner_id") and doc.get("id"):
                attachment = f"doc{doc['owner_id']}_{doc['id']}"
                _document_attachment_cache[cache_key] = attachment
                return attachment
            logger.warning("VK docs.save returned unexpected payload: %s", saved)
        except Exception as exc:
            logger.warning("VK document upload failed for %s: %s", path, exc)
    return None


async def send_local_document(
    token: str,
    peer_id: int,
    file_path: str | Path,
    title: str,
    message: str = "",
    keyboard: Optional[dict] = None,
) -> bool:
    attachment = await upload_document_for_message(token, peer_id, file_path, title=title)
    if not attachment:
        return False
    return await send_message(token, peer_id, message or title, keyboard=keyboard, attachment=attachment)


async def upload_photo_batch_for_message(
    token: str,
    peer_id: int,
    photo_urls: list[str],
) -> dict[str, str]:
    """Upload up to five photos through one VK upload server request."""
    urls = list(dict.fromkeys(url for url in photo_urls if url))[:5]
    if not urls:
        return {}

    token_key = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
    result: dict[str, str] = {}
    missing: list[str] = []
    for url in urls:
        cached = _get_cached_attachment(token_key, url)
        if cached:
            result[url] = cached
        else:
            missing.append(url)
    if not missing:
        return result

    try:
        upload_server, payloads = await asyncio.gather(
            vk_call("photos.getMessagesUploadServer", token, {"peer_id": peer_id}, timeout=12.0),
            asyncio.gather(*(_load_photo_payload(url) for url in missing)),
        )
        upload_url = upload_server.get("upload_url") if upload_server else None
        if not upload_url:
            return result
        files = [
            (f"file{index}", (filename, data, content_type))
            for index, (filename, data, content_type) in enumerate(payloads)
        ]
        upload_response = await _get_http_client().post(
            upload_url,
            files=files,
            timeout=httpx.Timeout(20.0, connect=5.0),
        )
        upload_response.raise_for_status()
        upload_data = upload_response.json()
        saved = await vk_call(
            "photos.saveMessagesPhoto",
            token,
            {
                "photo": upload_data.get("photo"),
                "server": upload_data.get("server"),
                "hash": upload_data.get("hash"),
            },
            timeout=12.0,
        )
        photos = saved if isinstance(saved, list) else ([saved] if saved else [])
        if len(photos) != len(missing):
            logger.info("VK batch upload returned %d/%d photos; using individual fallback", len(photos), len(missing))
            return result
        for url, photo in zip(missing, photos):
            if photo.get("owner_id") and photo.get("id"):
                attachment = f"photo{photo['owner_id']}_{photo['id']}"
                result[url] = attachment
                _cache_attachment(token_key, url, attachment)
    except Exception as exc:
        logger.info("VK batch photo upload is unavailable; using individual fallback: %s", exc)
    return result


async def upload_photos_for_message(
    token: str,
    peer_id: int,
    photo_urls: list[str],
    concurrency: int = 9,
) -> tuple[list[str], list[str]]:
    """Upload message photos concurrently while preserving their source order."""
    urls = list(dict.fromkeys(url for url in photo_urls if url))[:10]
    if not urls:
        return [], []
    uploaded: dict[str, str] = {}
    for offset in range(0, len(urls), 5):
        batch = urls[offset:offset + 5]
        if len(batch) > 1:
            uploaded.update(await upload_photo_batch_for_message(token, peer_id, batch))

    missing = [url for url in urls if url not in uploaded]
    if missing:
        semaphore = asyncio.Semaphore(max(1, min(concurrency, 6)))

        async def upload(url: str) -> tuple[str, Optional[str]]:
            async with semaphore:
                return url, await upload_photo_for_message(token, peer_id, url)

        fallback_results = await asyncio.gather(*(upload(url) for url in missing), return_exceptions=True)
        for fallback in fallback_results:
            if isinstance(fallback, tuple) and fallback[1]:
                uploaded[fallback[0]] = fallback[1]

    attachments = [uploaded[url] for url in urls if url in uploaded]
    failed_urls = [url for url in urls if url not in uploaded]
    return attachments, failed_urls


async def get_creator_id(token: str, group_id: int) -> Optional[int]:
    """VK id создателя сообщества (для уведомлений мастеру). Требует scope manage."""
    try:
        data = await vk_call("groups.getMembers", token, {"group_id": group_id, "filter": "managers"})
        items = data.get("items", []) if isinstance(data, dict) else []
        creator = next((m for m in items if m.get("role") == "creator"), None)
        if creator:
            return creator.get("id")
        if items:
            return items[0].get("id")
    except Exception as e:
        logger.warning("VK get_creator_id failed for group %s: %s", group_id, e)
    return None


async def get_user_name(token: str, user_id: int) -> Optional[str]:
    """Имя VK-пользователя (для карточки мастера). Не критично при сбое."""
    try:
        users = await vk_call("users.get", token, {"user_ids": user_id})
        if users:
            u = users[0]
            return f"{u.get('first_name', '')} {u.get('last_name', '')}".strip() or None
    except Exception:
        return None
    return None
