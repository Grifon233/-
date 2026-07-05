from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT_DIR = Path(__file__).resolve().parents[1]
CONTEXT_PATH = ROOT_DIR / "ai" / "project_context.md"
HUMANIZING_PATH = ROOT_DIR / "ai" / "humanizing.md"
DEFAULT_KEYS_DIR = Path(
    os.environ.get(
        "AI_ROUTER_DIR",
        r"C:\Users\ЗС\OneDrive\Рабочий стол\Апи ключи роутинг",
    )
)
API_KEYS_FILE = DEFAULT_KEYS_DIR / "Апишники.txt"


@dataclass(frozen=True)
class Provider:
    group: str
    name: str
    url: str
    model: str
    kind: str


PROVIDERS: dict[str, Provider] = {
    "mistral": Provider(
        group="mistral",
        name="Mistral",
        url="https://api.mistral.ai/v1/chat/completions",
        model="mistral-large-latest",
        kind="openai",
    ),
    "cohere": Provider(
        group="cohere",
        name="Cohere",
        url="https://api.cohere.com/v2/chat",
        model="command-a-03-2025",
        kind="cohere",
    ),
    "openrouter": Provider(
        group="openrouter",
        name="OpenRouter",
        url="https://openrouter.ai/api/v1/chat/completions",
        model="meta-llama/llama-3.3-70b-instruct:free",
        kind="openai",
    ),
    "cloudflare": Provider(
        group="cloudflare",
        name="Cloudflare",
        url="https://api.cloudflare.com/client/v4/accounts/18e987563108f245c732ad4f65497371/ai/run/@cf/qwen/qwen2.5-72b-instruct",
        model="qwen2.5-72b-instruct",
        kind="cloudflare",
    ),
    "aihubmix": Provider(
        group="aihubmix",
        name="AiHubMix",
        url="https://aihubmix.com/v1/chat/completions",
        model="gpt-4o-mini-free",
        kind="openai",
    ),
}

ROUTE_ORDER = ["mistral", "cohere", "openrouter", "cloudflare", "aihubmix"]


class AIReplyError(RuntimeError):
    pass


def _read_project_context() -> str:
    if not CONTEXT_PATH.exists():
        return ""
    return CONTEXT_PATH.read_text(encoding="utf-8")


def _read_humanizing_rules() -> str:
    if not HUMANIZING_PATH.exists():
        return ""
    return HUMANIZING_PATH.read_text(encoding="utf-8")


def _parse_keys() -> dict[str, list[str]]:
    groups = {name: [] for name in PROVIDERS}
    if not API_KEYS_FILE.exists():
        return groups

    current_group: str | None = None
    content = API_KEYS_FILE.read_text(encoding="utf-8")
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lower = line.lower()
        for group in PROVIDERS:
            if group in lower and " - " not in line:
                current_group = group
                break
        match = re.search(r" - ([\w\-.]+)", line)
        if match and current_group:
            groups[current_group].append(match.group(1))
    return groups


def _request_json(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: int = 70,
) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(url, data=body, headers=headers, method="POST")
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _chat(provider: Provider, key: str, messages: list[dict[str, str]]) -> str:
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json; charset=utf-8",
    }

    if provider.kind == "cohere":
        payload = {
            "model": provider.model,
            "messages": messages,
            "temperature": 0.35,
            "max_tokens": 650,
        }
        data = _request_json(provider.url, headers, payload)
        return data["message"]["content"][0]["text"].strip()

    if provider.kind == "cloudflare":
        payload = {"messages": messages}
        data = _request_json(provider.url, {"Authorization": f"Bearer {key}"}, payload)
        return (data.get("result", {}) or {}).get("response", "").strip()

    payload = {
        "model": provider.model,
        "messages": messages,
        "temperature": 0.35,
        "max_tokens": 650,
    }
    data = _request_json(provider.url, headers, payload)
    return data["choices"][0]["message"]["content"].strip()


def _build_messages(
    lead: dict[str, Any],
    project_context: str,
    humanizing_rules: str,
) -> list[dict[str, str]]:
    title = lead.get("title") or ""
    description = lead.get("description") or ""
    budget = lead.get("budget") or ""
    source = lead.get("source") or ""
    category = lead.get("category") or ""
    keywords = ", ".join(lead.get("matched_keywords") or [])

    system = (
        "Ты помогаешь опытному русскоязычному фрилансеру писать отклики на задачи. "
        "Специализация: автоматизация бизнеса, чат-боты, парсинг, API-интеграции, CRM, AI-инструменты. "
        "Пиши от первого лица, спокойно, уверенно, живым человеческим языком, без канцелярита и без выдуманных сроков/цен. "
        "Не раскрывай внутренние технические детали, пути к файлам, секреты, ключи и приватные названия. "
        "Не обещай то, чего нет в задаче. Не придумывай стоимость, сроки, функции и детали прошлых кейсов. "
        "Опыт можно упоминать только в формулировках, которые следуют из контекста. "
        "Если точного совпадения кейса нет, пиши честно: похожий опыт по ботам, формам, интеграциям, хранению данных или автоматизации. "
        "Не превращай кейс Telegram-бота для расписания в кейс по генерации договоров или документов. "
        "Если клиент просит цену, но данных мало, скажи, что оценишь после короткого уточнения объема. "
        "Если данных мало, задай 1-2 уточняющих вопроса в конце. "
        "Перед финальным ответом мысленно проверь текст на AI-паттерны: формульность, рекламность, одинаковый ритм, слишком гладкие общие фразы."
    )
    user = f"""
Сформируй готовый отклик на фриланс-задачу.

Контекст опыта исполнителя:
{project_context}

Humanizing-правила, которые обязательно нужно учитывать:
{humanizing_rules}

Задача:
- Площадка: {source}
- Заголовок: {title}
- Категория: {category}
- Бюджет: {budget}
- Ключевые совпадения: {keywords}
- Описание:
{description}

Требования к отклику:
- 800-1250 знаков максимум.
- Сразу начни с текста отклика, без заголовков вроде "Отклик на задачу".
- Первое предложение должно быть в таком смысле: "Я недавно начал искать здесь заказы, поэтому у меня пока нет хороших отзывов в профиле. Но у меня богатый аналогичный опыт..."
- Дальше объясни, почему именно я подхожу для этой работы.
- Упомяни 1-2 релевантных похожих кейса из опыта, но без длинного списка.
- Покажи, что понял конкретную задачу клиента, а не написал универсальный отклик.
- Не используй markdown, заголовки, жирный текст и маркированные списки.
- В конце предложи короткий следующий шаг.
- Перед ответом проверь: не выдумал ли ты кейс, цену, срок или точную функцию, которой нет в контексте.
""".strip()
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def generate_reply(lead: dict[str, Any]) -> dict[str, str]:
    keys_by_group = _parse_keys()
    context = _read_project_context()
    humanizing_rules = _read_humanizing_rules()
    messages = _build_messages(lead, context, humanizing_rules)
    errors: list[str] = []

    for group_name in ROUTE_ORDER:
        provider = PROVIDERS[group_name]
        for key in keys_by_group.get(group_name, []):
            try:
                started = time.monotonic()
                text = _chat(provider, key, messages)
                if text:
                    return {
                        "reply": text,
                        "provider": provider.name,
                        "model": provider.model,
                        "elapsed_seconds": f"{time.monotonic() - started:.1f}",
                    }
            except HTTPError as error:
                if error.code in {401, 403, 429}:
                    errors.append(f"{provider.name}: {error.code}")
                    continue
                errors.append(f"{provider.name}: HTTP {error.code}")
            except (URLError, TimeoutError, KeyError, IndexError, json.JSONDecodeError) as error:
                errors.append(f"{provider.name}: {type(error).__name__}")

    detail = "; ".join(errors[-8:]) if errors else "ключи не найдены"
    raise AIReplyError(f"Не удалось получить ответ ИИ: {detail}")
