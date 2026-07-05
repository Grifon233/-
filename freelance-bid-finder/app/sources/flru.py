from __future__ import annotations

import json
import re
import urllib.request
from urllib.error import HTTPError, URLError
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup

from app.http_client import fetch_bytes
from app.models import Lead
from app.utils import clean_text, html_to_text, normalize_for_match, parse_rss_datetime, short_source_id


RSS_URL = "https://www.fl.ru/rss/projects.xml"


def _text(item: ET.Element, name: str) -> str:
    child = item.find(name)
    return clean_text(child.text if child is not None else "")


def _split_budget(title: str) -> tuple[str, str]:
    match = re.search(r"\((Бюджет:[^)]+)\)\s*$", title, flags=re.IGNORECASE)
    if not match:
        return title, ""
    return clean_text(title[: match.start()]), clean_text(match.group(1))


def _fetch_detail_description(url: str, config: dict) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": config["user_agent"],
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=8) as response:
        html = response.read().decode("utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text("", strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("description"):
            return html_to_text(data["description"])
    return ""


def closed_reason(url: str, config: dict) -> str | None:
    try:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": config["user_agent"],
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
            },
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            html = response.read().decode("utf-8", errors="ignore")
    except HTTPError as error:
        if error.code in {403, 404, 410}:
            return f"FL.ru: страница недоступна ({error.code})"
        return None
    except URLError:
        return None

    text = html.lower()
    closed_markers = [
        "проект закрыт",
        "проект завершен",
        "проект завершён",
        "исполнитель выбран",
        "заказчик выбрал исполнителя",
        "проект недоступен",
        "проект удален",
        "проект удалён",
    ]
    for marker in closed_markers:
        if marker in text:
            return f"FL.ru: {marker}"
    return None


def _may_need_details(title: str, description: str, config: dict) -> bool:
    text = normalize_for_match(f"{title} {description}")
    return any(
        normalize_for_match(keyword) in text
        for keyword in config.get("positive_keywords", [])
    )


def fetch_leads(config: dict) -> list[Lead]:
    leads: list[Lead] = []
    details_left = int(config["sources"]["fl_ru"].get("detail_pages", 8))

    for category in config["sources"]["fl_ru"]["categories"]:
        content = fetch_bytes(RSS_URL, config, {"category": category})
        root = ET.fromstring(content)
        for item in root.findall("./channel/item"):
            raw_title = _text(item, "title")
            title, budget = _split_budget(raw_title)
            link = _text(item, "link")
            pub_date = _text(item, "pubDate")
            description = html_to_text(_text(item, "description"))
            if (
                details_left > 0
                and (description.endswith("...") or description.endswith("…"))
                and _may_need_details(title, description, config)
            ):
                try:
                    description = _fetch_detail_description(link, config) or description
                    details_left -= 1
                except Exception:
                    pass

            leads.append(
                Lead(
                    source="fl_ru",
                    source_id=short_source_id(link, r"/projects/(\d+)/"),
                    title=title,
                    url=link,
                    description=description,
                    budget=budget,
                    category=_text(item, "category"),
                    published_at=parse_rss_datetime(pub_date),
                    raw_published=pub_date,
                )
            )

    return leads
