from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation

from app.http_client import fetch_text
from app.models import Lead
from app.utils import clean_text, html_to_text


PROJECTS_URL = "https://kwork.ru/projects"


def _extract_state_data(html: str) -> dict:
    marker = "window.stateData="
    marker_index = html.find(marker)
    if marker_index == -1:
        raise ValueError("Kwork stateData not found")

    start = html.find("{", marker_index)
    if start == -1:
        raise ValueError("Kwork stateData JSON start not found")

    level = 0
    in_string = False
    escaped = False
    for index in range(start, len(html)):
        char = html[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            level += 1
        elif char == "}":
            level -= 1
            if level == 0:
                return json.loads(html[start : index + 1])

    raise ValueError("Kwork stateData JSON end not found")


def _money(value: object) -> str:
    if value in (None, ""):
        return ""
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        return clean_text(value)
    return f"{int(amount):,}".replace(",", " ") + " ₽"


def _budget(item: dict) -> str:
    parts: list[str] = []
    price = _money(item.get("priceLimit"))
    possible = _money(item.get("possiblePriceLimit"))
    if price:
        parts.append(price)
    if possible and possible != price:
        parts.append(f"допустимо до {possible}")
    max_days = clean_text(item.get("max_days"))
    if max_days:
        parts.append(f"срок {max_days} дн.")
    return ", ".join(parts)


def _wants(state: dict) -> list[dict]:
    list_data = state.get("wantsListData") or {}
    wants = list_data.get("wants") or state.get("wants") or []
    return wants if isinstance(wants, list) else []


def closed_reason(url: str, config: dict) -> str | None:
    html = fetch_text(url, config)
    state = _extract_state_data(html)
    want_data = state.get("wantData")
    if not isinstance(want_data, dict):
        return None

    status = clean_text(want_data.get("status")).lower()
    is_active = bool(want_data.get("isWantActive"))
    status_hint = ""
    hint = want_data.get("altStatusHint")
    if isinstance(hint, dict):
        status_hint = clean_text(hint.get("title"))

    if is_active and status == "active":
        return None
    if status or status_hint:
        return f"Kwork: {status_hint or status}"
    return "Kwork: задача не активна"


def fetch_leads(config: dict) -> list[Lead]:
    leads: list[Lead] = []
    errors: list[str] = []
    seen: set[str] = set()
    source_config = config["sources"]["kwork"]
    category_names = {
        str(key): value for key, value in source_config.get("category_names", {}).items()
    }

    scan_targets: list[tuple[object | None, int]] = []
    for page in range(1, int(source_config.get("all_pages", 0)) + 1):
        scan_targets.append((None, page))
    for category in source_config["categories"]:
        for page in range(1, int(source_config["pages"]) + 1):
            scan_targets.append((category, page))

    for category, page in scan_targets:
        try:
            params = {"page": page} if category is None else {"c": category, "page": page}
            html = fetch_text(PROJECTS_URL, config, params)
            state = _extract_state_data(html)
        except Exception as exc:
            category_label = "all" if category is None else category
            errors.append(f"category {category_label}, page {page}: {exc}")
            continue

        for item in _wants(state):
            source_id = str(item.get("id") or "")
            if not source_id or source_id in seen:
                continue
            seen.add(source_id)

            category_id = str(item.get("category_id") or category or "")
            category_name = category_names.get(category_id, f"Kwork category {category_id}")

            leads.append(
                Lead(
                    source="kwork",
                    source_id=source_id,
                    title=clean_text(item.get("name")),
                    url=f"https://kwork.ru/projects/{source_id}/view",
                    description=html_to_text(item.get("description")),
                    budget=_budget(item),
                    category=category_name,
                    published_at=clean_text(
                        item.get("date_create") or item.get("date_active")
                    )
                    or None,
                    raw_published=clean_text(
                        item.get("wantDates", {}).get("dateCreate")
                        if isinstance(item.get("wantDates"), dict)
                        else ""
                    ),
                )
            )

    if errors and not leads:
        raise RuntimeError("; ".join(errors))

    return leads
