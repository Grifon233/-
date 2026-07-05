"""Фильтр мусора + извлечение {город, улица} из текста (см. docs/02, шаги 2-3).

Два уровня:
1) Дешёвый regex-префильтр — отсекает явный мусор, чтобы не гонять LLM на всё подряд.
2) LLM-router — устойчив к сленгу/опечаткам и переключается между провайдерами.
   Anthropic оставлен как дополнительный резерв.
"""
import json
import logging
import re

from app.config import settings
from app.services.llm_router import llm_router

logger = logging.getLogger(__name__)

# Маркеры, по которым сообщение похоже на отметку о курьере.
_MARKERS = re.compile(
    r"курьер|курьэр|доставщик|доставк|видел|стои[тл]|идёт|идет|на улиц|по улиц",
    re.IGNORECASE,
)
# Явный мусор/реклама -> сразу отбрасываем.
_SPAM = re.compile(r"реклам|купи|скидк|подпишись|розыгрыш|казино|ставк", re.IGNORECASE)
# Грубое извлечение улицы (fallback без LLM).
_STREET = re.compile(
    r"(?:улиц[аеу]|ул\.?|проспект|пр-?т|переул|пер\.?|шоссе|бульвар)\s+([А-ЯЁа-яё\-]+)",
    re.IGNORECASE,
)


def prefilter(text: str) -> bool:
    """True -> сообщение стоит обрабатывать дальше."""
    if _SPAM.search(text):
        return False
    return bool(_MARKERS.search(text))


def _extract_regex(text: str) -> dict | None:
    m = _STREET.search(text)
    if not m:
        return None
    return {"is_courier_sighting": True, "city": None,
            "street": f"улица {m.group(1)}", "confidence": 0.5}


_PROMPT = (
    "Ты фильтруешь сообщения городского Telegram-чата. Определи, содержит ли сообщение "
    "актуальное наблюдение о местоположении курьера-доставщика. Отбрасывай рекламу, "
    "вакансии, предложения услуг, заказы доставки, шутки, вопросы без наблюдения, "
    "обсуждение прошлых событий и пустой разговор. "
    "Верни СТРОГО JSON без пояснений: "
    '{"is_courier_sighting": bool, "city": str|null, "street": str|null, "confidence": 0..1}. '
    "street — максимально точное место: официальное название улицы, проспекта, шоссе "
    "или известного объекта в именительном падеже. Исправляй разговорную форму на "
    "официальное название только когда уверен (например, «на Бауманской» -> "
    "«Бауманская улица»). Не выдумывай адрес. "
    "Если местоположение не указано, ставь street=null."
)


async def _extract_llm(text: str) -> dict | None:
    import anthropic
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    msg = await client.messages.create(
        model=settings.llm_model,
        max_tokens=200,
        system=_PROMPT,
        messages=[{"role": "user", "content": text}],
    )
    if not msg.content:
        return None


def _parse_json(raw: str | None) -> dict | None:
    if not raw:
        return None
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        return json.loads(raw[start:end + 1])
    except json.JSONDecodeError:
        return None


async def _extract_routed_llm(text: str) -> dict | None:
    raw = await llm_router.chat([
        {"role": "system", "content": _PROMPT},
        {"role": "user", "content": text},
    ])
    return _parse_json(raw)
    raw = msg.content[0].text.strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < start:
        return None
    raw = raw[start:end + 1]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


async def extract(text: str) -> dict | None:
    """Главная точка входа. None -> отметку не создаём."""
    if not prefilter(text):
        return None
    if llm_router.configured:
        try:
            data = await _extract_routed_llm(text)
        except Exception:
            logger.exception("Routed LLM extraction failed")
            data = None
    elif settings.anthropic_api_key:
        try:
            data = await _extract_llm(text)
        except Exception:
            logger.exception("LLM extraction failed; falling back to regex")
            data = _extract_regex(text)
    else:
        data = _extract_regex(text)
    if data is None:
        data = _extract_regex(text)
    if not isinstance(data, dict):
        return None
    if not data.get("is_courier_sighting") or not isinstance(data.get("street"), str):
        return None
    try:
        confidence = float(data.get("confidence", 1.0))
    except (TypeError, ValueError):
        return None
    if confidence < 0.5:
        return None
    return data
