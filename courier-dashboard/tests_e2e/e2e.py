"""Проверки Mini App в Chromium с настоящим локальным FastAPI.

Из каталога courier-dashboard: python -m pytest -q tests_e2e/e2e.py
Внешние службы заменены тестовыми ответами; реальные сообщения не отправляются.
"""

import base64
import re
import socket
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest
import uvicorn
from playwright.sync_api import expect, sync_playwright

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))
from app.config import settings

if settings.store_backend != "memory":
    pytest.skip("Браузерные тесты требуют STORE_BACKEND=memory", allow_module_level=True)

from app.main import app
from app.routers import ingest
from app.services.sightings import store


PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aG8sAAAAASUVORK5CYII="
)
KEY = "e2e-only-key-not-for-production"
CITY = re.compile(r"Москва|Санкт-Петербург|Новосибирск|Екатеринбург|Казань")


@pytest.fixture
def live_api(monkeypatch):
    async def geocode(city, street):
        if "Баумана" not in street:
            return None
        return {
            "type": "LineString",
            "coordinates": [[37.610, 55.754], [37.621, 55.760]],
        }

    monkeypatch.setattr(ingest, "geocode_street", geocode)
    for name, value in {
        "ingest_api_key": KEY,
        "feedback_bot_token": "",
        "feedback_chat_id": "",
        "anthropic_api_key": "",
        "llm_api_keys_file": "",
    }.items():
        monkeypatch.setattr(settings, name, value)
    store.clear()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, access_log=False, log_level="warning", ws="none"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        try:
            for _ in range(150):
                if server.started or not thread.is_alive():
                    break
                time.sleep(0.02)
            assert server.started, "Тестовый FastAPI не запустился"
            yield f"http://127.0.0.1:{port}"
        finally:
            server.should_exit = True
            thread.join(5)
            assert not thread.is_alive(), "Тестовый FastAPI не завершился"
            store.clear()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            yield browser
        finally:
            browser.close()


@pytest.fixture
def page(browser, live_api):
    with browser.new_context(viewport={"width": 360, "height": 760}) as context:
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def isolate(route):
            host = urlsplit(route.request.url).hostname or ""
            if route.request.url.startswith(live_api + "/"):
                route.continue_()
            elif host == "tile.openstreetmap.org" or host.endswith(".tile.openstreetmap.org"):
                route.fulfill(content_type="image/png", body=PNG)
            else:
                route.abort()

        page.route("**/*", isolate)
        yield page
        assert errors == []


def open_app(page, url):
    response = page.goto(url + "/app/", wait_until="domcontentloaded")
    assert response.ok


def choose(page, city="moscow"):
    page.locator(f'button.city-card[data-city="{city}"]').click()


def seed(url, street, message_id):
    with httpx.Client(base_url=url, timeout=3, trust_env=False) as client:
        message = {
            "source_chat": "@test_couriers",
            "message_id": message_id,
            "message_link": f"https://t.me/test_couriers/{message_id}",
            "text": f"Курьер стоит на улице {street}",
            "ts": datetime.now(timezone.utc).isoformat(),
            "city": "Москва",
        }
        response = client.post("/ingest", json=message, headers={"X-API-Key": KEY})
        assert response.status_code == 200, response.text
        assert response.json()["accepted"] is True


def test_city_selection_empty_map_and_saved_city(page, live_api):
    open_app(page, live_api)
    expect(page.get_by_role("button", name=CITY)).to_have_count(5)
    expect(page.locator("#screen-map")).to_be_hidden()
    choose(page)
    expect(page.locator("#current-city-name")).to_have_text("Москва")
    expect(page.locator("#status-text")).to_have_text("Занятых улиц нет")
    expect(page.locator("#map.leaflet-container")).to_be_visible()
    expect(page.locator("#map .leaflet-tile-pane img").first).to_be_visible()
    page.get_by_role("button", name="Сменить город").click()
    expect(page.locator("#screen-city")).to_be_visible()
    choose(page, "kazan")
    expect(page.locator("#current-city-name")).to_have_text("Казань")
    page.reload(wait_until="domcontentloaded")
    expect(page.locator("#current-city-name")).to_have_text("Казань")
    expect(page.locator("#screen-city")).to_be_hidden()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_real_ingest_visible_in_correct_city_with_and_without_geometry(page, live_api):
    seed(live_api, "Баумана", 1)
    seed(live_api, "Ленина", 2)
    open_app(page, live_api)
    choose(page)
    expect(page.locator("#map .leaflet-overlay-pane path")).to_have_count(1)
    page.locator("#street-summary").click()
    lenin = page.locator("#street-list summary").filter(has_text="улица Ленина")
    expect(lenin).to_be_visible()
    lenin.click()
    expect(page.get_by_role("link", name="Открыть источник")).to_have_attribute(
        "href", "https://t.me/test_couriers/2"
    )
    page.get_by_role("button", name="Сменить город").click()
    choose(page, "kazan")
    expect(page.locator("#status-text")).to_have_text("Занятых улиц нет")
    expect(page.locator("#map .leaflet-overlay-pane path")).to_have_count(0)
    expect(lenin).to_have_count(0)


def test_feedback_keyboard_validation_failure_and_draft(page, live_api):
    open_app(page, live_api)
    choose(page)
    feedback = page.get_by_role("button", name="Сообщить о проблеме")
    feedback.focus()
    page.keyboard.press("Enter")
    dialog = page.get_by_role("dialog")
    textarea = dialog.get_by_role("textbox")
    expect(textarea).to_be_focused()
    dialog.get_by_role("button", name="Отправить").click()
    expect(page.locator("#feedback-error")).to_contain_text("Напишите")
    textarea.fill("  Карта не открывается  ")
    with page.expect_response(lambda res: res.url == live_api + "/feedback") as result:
        dialog.get_by_role("button", name="Отправить").click()
    assert result.value.json()["reason"] == "feedback_bot_not_configured"
    expect(page.locator("#feedback-error")).to_contain_text("не настроен")
    expect(textarea).to_have_value("  Карта не открывается  ")
    page.keyboard.press("Escape")
    expect(dialog).to_be_hidden()
    expect(feedback).to_be_focused()


def test_unreachable_streets_recovers_with_refresh(page, live_api):
    def drop(route):
        route.abort()

    pattern = "**/streets?city=*"
    page.route(pattern, drop)
    open_app(page, live_api)
    choose(page, "spb")
    expect(page.locator("#status-chip")).to_have_class(re.compile("status-error"))
    expect(page.locator("#status-text")).to_contain_text(re.compile("связ|загруз", re.I))
    page.unroute(pattern, drop)
    page.get_by_role("button", name=re.compile("Обновить|Повторить")).click()
    expect(page.locator("#status-text")).to_have_text("Занятых улиц нет")


def test_street_list_available_if_leaflet_script_fails(page, live_api):
    seed(live_api, "Ленина", 1)
    page.route("**/leaflet.js", lambda route: route.abort())
    open_app(page, live_api)
    choose(page)
    expect(page.locator("#street-list summary").filter(has_text="улица Ленина")).to_be_visible()
    expect(page.locator("#map.leaflet-container")).to_have_count(0)


def test_tile_outage_does_not_hide_street_report_on_small_screen(page, live_api):
    page.set_viewport_size({"width": 320, "height": 600})
    seed(live_api, "Баумана", 1)
    page.route("https://tile.openstreetmap.org/**", lambda route: route.abort())
    open_app(page, live_api)
    choose(page)
    expect(page.locator("#map-note")).to_contain_text(re.compile("карт|подлож", re.I))
    expect(page.locator("#map .leaflet-overlay-pane path")).to_have_count(1)
    page.locator("#street-summary").click()
    expect(page.locator("#street-list summary").filter(has_text="улица Баумана")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
