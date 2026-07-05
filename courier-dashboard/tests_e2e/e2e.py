"""E2E-прогон всех пользовательских сценариев приложения через Playwright.

Запуск (сервер должен слушать BASE):
    backend/.venv/Scripts/python.exe tests_e2e/e2e.py
"""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

BASE = "http://127.0.0.1:8010"
SHOTS = Path(__file__).parent / "shots"
SHOTS.mkdir(exist_ok=True)

passed, failed = 0, 0


def check(name, cond):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}")


with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(viewport={"width": 390, "height": 844})  # телефон
    page = ctx.new_page()

    # ---- Сценарий 1: вход -> экран выбора города ----
    print("\n[1] Вход в приложение — экран выбора города")
    page.goto(f"{BASE}/app/", wait_until="networkidle")
    cards = page.locator(".city-card")
    check("показано 5 городов", cards.count() == 5)
    names = cards.locator(".city-name").all_inner_texts()
    check("есть Москва", "Москва" in names)
    check("есть Санкт-Петербург", "Санкт-Петербург" in names)
    check("есть Новосибирск", "Новосибирск" in names)
    check("есть Екатеринбург", "Екатеринбург" in names)
    check("есть Казань", "Казань" in names)
    check("карта ещё скрыта", page.locator("#screen-map").is_hidden())
    page.screenshot(path=str(SHOTS / "1_city_select.png"))

    # ---- Сценарий 2: выбор города -> карта ----
    print("\n[2] Выбор «Москва» — открывается карта")
    page.locator('.city-card[data-city="moscow"]').click()
    check("экран карты показан", page.locator("#screen-map").is_visible())
    check("экран выбора скрыт", page.locator("#screen-city").is_hidden())
    check("в шапке название города = Москва",
          page.locator("#current-city-name").inner_text() == "Москва")
    page.wait_for_function(
        "document.querySelector('#status-text').innerText !== 'Загрузка…'", timeout=8000)
    check("статус: занятых улиц нет (бэкенд доступен)",
          "Занятых улиц" in page.locator("#status-text").inner_text())
    check("карта Leaflet инициализирована",
          page.locator("#map.leaflet-container").count() == 1
          and page.locator("#map .leaflet-tile-pane").count() == 1)
    page.wait_for_timeout(1200)  # дать тайлам прогрузиться для скриншота
    page.screenshot(path=str(SHOTS / "2_map_moscow.png"))

    # ---- Сценарий 3: смена города ----
    print("\n[3] Смена города на «Казань»")
    page.locator("#btn-change-city").click()
    check("снова экран выбора города", page.locator("#screen-city").is_visible())
    page.locator('.city-card[data-city="kazan"]').click()
    check("название города = Казань",
          page.locator("#current-city-name").inner_text() == "Казань")
    page.wait_for_timeout(800)
    page.screenshot(path=str(SHOTS / "3_map_kazan.png"))

    # ---- Сценарий 4: обратная связь — пустое сообщение ----
    print("\n[4] Обратная связь — пустой текст не отправляется")
    page.locator("#btn-feedback").click()
    check("модалка открыта", page.locator("#feedback-modal").is_visible())
    page.locator("#fb-send").click()
    page.wait_for_selector("#toast:not(.hidden)", timeout=4000)
    check("тост: просьба написать сообщение",
          "Напишите" in page.locator("#toast").inner_text())

    # ---- Сценарий 5: обратная связь — отправка (бот не настроен) ----
    print("\n[5] Обратная связь — отправка (канал не настроен -> понятное сообщение)")
    page.locator("#feedback-text").fill("Тест: улица не подсвечивается")
    page.locator("#fb-send").click()
    page.wait_for_function(
        "document.querySelector('#toast') && document.querySelector('#toast').innerText.includes('настроен')",
        timeout=5000)
    check("тост: канал обратной связи не настроен",
          "настроен" in page.locator("#toast").inner_text())
    page.screenshot(path=str(SHOTS / "5_feedback.png"))
    page.locator("#fb-cancel").click()
    check("модалка закрыта", page.locator("#feedback-modal").is_hidden())

    ctx.close()

    # ---- Сценарий 6: ошибка соединения -> статус-индикатор краснеет ----
    print("\n[6] Сбой сервера — боковой индикатор показывает проблему")
    ctx2 = browser.new_context(viewport={"width": 390, "height": 844})
    page2 = ctx2.new_page()
    page2.route("**/streets*", lambda route: route.abort())
    page2.goto(f"{BASE}/app/", wait_until="domcontentloaded")
    page2.locator('.city-card[data-city="spb"]').click()
    page2.wait_for_function(
        "document.querySelector('#status-chip').className.includes('status-error')",
        timeout=8000)
    check("статус стал 'ошибка'",
          "status-error" in page2.locator("#status-chip").get_attribute("class"))
    check("текст про отсутствие связи",
          "связи" in page2.locator("#status-text").inner_text())
    page2.screenshot(path=str(SHOTS / "6_error_status.png"))
    ctx2.close()

    browser.close()

print(f"\n==== ИТОГ: {passed} passed, {failed} failed ====")
sys.exit(1 if failed else 0)
