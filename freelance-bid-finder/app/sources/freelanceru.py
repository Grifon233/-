from __future__ import annotations

from urllib.parse import urljoin
from urllib.error import HTTPError, URLError

from bs4 import BeautifulSoup

from app.http_client import fetch_text
from app.models import Lead
from app.utils import clean_text, parse_russian_datetime, short_source_id


BASE_URL = "https://freelance.ru"
TASK_URL = f"{BASE_URL}/task"


def _params(config: dict, page: int) -> list[tuple[str, object]]:
    params: list[tuple[str, object]] = [("a", 1), ("v", 1), ("page", page)]
    for category in config["sources"]["freelance_ru"]["categories"]:
        params.append(("c[]", category))
    return params


def _fetch_detail_description(url: str, config: dict) -> str:
    html = fetch_text(url, config)
    soup = BeautifulSoup(html, "html.parser")
    selectors = [
        ".task-card__desc",
        ".task-description",
        ".task__description",
        ".task-view__description",
        "[itemprop='description']",
    ]
    for selector in selectors:
        node = soup.select_one(selector)
        if not node:
            continue
        text = clean_text(node.get_text(" ", strip=True))
        if text:
            return text
    return ""


def closed_reason(url: str, config: dict) -> str | None:
    try:
        html = fetch_text(url, config)
    except HTTPError as error:
        if error.code in {403, 404, 410}:
            return f"Freelance.ru: страница недоступна ({error.code})"
        return None
    except URLError:
        return None

    text = html.lower()
    closed_markers = [
        "задача закрыта",
        "проект закрыт",
        "заказ закрыт",
        "исполнитель выбран",
        "работа завершена",
        "задание удалено",
        "страница не найдена",
    ]
    for marker in closed_markers:
        if marker in text:
            return f"Freelance.ru: {marker}"
    return None


def _is_short_preview(description: str) -> bool:
    text = description.rstrip()
    return text.endswith("...") or text.endswith("…")


def fetch_leads(config: dict) -> list[Lead]:
    leads: list[Lead] = []
    seen: set[str] = set()
    pages = int(config["sources"]["freelance_ru"]["pages"])
    details_left = int(config["sources"]["freelance_ru"].get("detail_pages", 8))

    for page in range(1, pages + 1):
        html = fetch_text(TASK_URL, config, _params(config, page))
        soup = BeautifulSoup(html, "html.parser")

        for card in soup.select("article.task-card"):
            title_link = card.select_one(".task-card__title-link")
            if not title_link:
                continue

            url = urljoin(BASE_URL, title_link.get("href", ""))
            source_id = short_source_id(url, r"/task/view/(\d+)")
            if source_id in seen:
                continue
            seen.add(source_id)

            description_node = card.select_one(".task-card__desc")
            budget = card.select_one(".task-card__budget")
            published = card.select_one(".task-card__foot-item")
            chips = [
                clean_text(chip.get_text(" ", strip=True))
                for chip in card.select(".task-chip")
            ]

            raw_published = ""
            if published:
                raw_published = published.get("title") or published.get_text(" ", strip=True)
            description = clean_text(
                description_node.get_text(" ", strip=True) if description_node else ""
            )
            if details_left > 0 and _is_short_preview(description):
                try:
                    full_description = _fetch_detail_description(url, config)
                    if len(full_description) > len(description):
                        description = full_description
                    details_left -= 1
                except Exception:
                    pass

            leads.append(
                Lead(
                    source="freelance_ru",
                    source_id=source_id,
                    title=clean_text(title_link.get_text(" ", strip=True)),
                    url=url,
                    description=description,
                    budget=clean_text(
                        budget.get_text(" ", strip=True) if budget else ""
                    ),
                    category=", ".join(chips),
                    published_at=parse_russian_datetime(raw_published),
                    raw_published=raw_published,
                )
            )

    return leads
