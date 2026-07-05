"""End-to-end browser test: import the tdata account through the UI.

Steps:
1. Open the app, seed admin token.
2. Go to Accounts page.
3. Click the 'TData' button.
4. Fill api_id, api_hash, pick the proxy, upload the tdata zip.
5. Click 'Импортировать'.
6. Verify the account landed in the backend with a non-null proxy_id
   and the correct phone number.
7. As a NEGATIVE test, try to call POST /send-code on the new
   account after setting its proxy_id to NULL. Verify the backend
   refuses with HTTP 400 (the proxy guard we just implemented).
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
import urllib.request
from pathlib import Path

from playwright.async_api import async_playwright, Page

FRONTEND_URL = "http://[::1]:5177/"
API_URL = "http://127.0.0.1:8000"
ADMIN_TOKEN = "YOUR_BEARER_TOKEN"

TDATA_ZIP = Path(r"C:\Users\ЗС\OneDrive\Рабочий стол\Телеграмм парсер\test_data\tdata_18382068327.zip")
API_ID = "2040"
API_HASH = "b18441a1ff607e10a989891a5462e627"
EXPECTED_PHONE = "+18382068327"


def api_get(path: str) -> dict | list:
    req = urllib.request.Request(
        f"{API_URL}{path}",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}", "X-Project-ID": "1"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def api_post(path: str, body: dict) -> tuple[int, dict | str]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{API_URL}{path}",
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {ADMIN_TOKEN}",
            "X-Project-ID": "1",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read()
        try:
            return exc.code, json.loads(body)
        except Exception:
            return exc.code, body.decode("utf-8", errors="replace")


def api_patch(path: str, body: dict) -> tuple[int, dict | str]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{API_URL}{path}",
        data=data,
        method="PATCH",
        headers={
            "Authorization": f"Bearer {ADMIN_TOKEN}",
            "X-Project-ID": "1",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")


async def main() -> int:
    if not TDATA_ZIP.exists():
        print(f"  ERROR: tdata zip not found at {TDATA_ZIP}")
        return 1

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = await browser.new_context(viewport={"width": 1400, "height": 900}, locale="ru-RU")
        page = await ctx.new_page()
        errors = []
        page.on("console", lambda m: errors.append(("console." + m.type, m.text[:300])) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(("pageerror", str(e)[:300])))

        # 1) Open app and seed token.
        print("1) Open app + seed admin token")
        await page.goto(FRONTEND_URL, wait_until="domcontentloaded")
        await page.evaluate("(t) => localStorage.setItem('admin_api_token', t)", ADMIN_TOKEN)
        await page.evaluate("() => localStorage.setItem('active_project_id', '1')")
        await page.reload(wait_until="networkidle")
        await page.wait_for_timeout(2000)
        await page.screenshot(path="logs/browser_run/tdata_01_home.png", full_page=True)

        # 2) Navigate to Accounts.
        print("2) Go to Accounts")
        try:
            await page.get_by_role("link", name="Аккаунты").first.click()
        except Exception:
            await page.locator("text=Аккаунты").first.click()
        await page.wait_for_url("**/accounts", timeout=10000)
        await page.wait_for_timeout(2000)
        await page.screenshot(path="logs/browser_run/tdata_02_accounts.png", full_page=True)

        # 3) Click TData button.
        print("3) Click 'TData' button")
        try:
            await page.locator("button:has-text('TData')").first.click(timeout=5000)
        except Exception as e:
            print(f"  ERROR: TData button not found: {e}")
            return 1
        await page.wait_for_timeout(800)
        await page.screenshot(path="logs/browser_run/tdata_03_modal.png", full_page=True)

        # 4) Fill api_id, api_hash. Scope the lookup to the modal so
        #    we don't pick up the page-level search input.
        print("4) Fill api_id and api_hash")
        modal = page.locator("div").filter(has_text="Импорт TData").last
        # Fall back to a wider selector if the heading-based scope
        # didn't catch the modal container.
        api_id_input = page.locator("input[type='number'][placeholder='1234567']").first
        api_hash_input = page.locator("input[placeholder*='abcdef1234567890abcdef1234567890']").first
        await api_id_input.fill(API_ID)
        await api_hash_input.fill(API_HASH)

        # 5) Pick the proxy.
        print("5) Pick the proxy")
        proxy_id = None
        proxies = api_get("/api/v1/proxies")
        for p in proxies:
            if p["host"] == "38.154.19.220" and p["port"] == 8000:
                proxy_id = p["id"]
                break
        if not proxy_id:
            print("  ERROR: proxy 38.154.19.220:8000 not found")
            return 1
        print(f"  Will attach proxy id={proxy_id}")
        # The proxy <select> has no name attribute; we pick the one
        # that already has options like "— выберите прокси —" in its
        # first option. Simplest: pick the LAST select in the page
        # (the modal is rendered last).
        try:
            selects = page.locator("select")
            count = await selects.count()
            print(f"  Found {count} selects")
            if count > 0:
                await selects.last.select_option(value=str(proxy_id))
        except Exception as e:
            print(f"  WARN: could not select proxy: {e}")

        # 6) Upload the tdata zip. The file input has accept=".zip"
        #    and is the only one in the modal.
        print("6) Upload tdata zip")
        file_input = page.locator("input[type='file'][accept='.zip']").first
        await file_input.set_input_files(str(TDATA_ZIP))
        await page.wait_for_timeout(500)
        await page.screenshot(path="logs/browser_run/tdata_04_filled.png", full_page=True)

        # 7) Click 'Импортировать'.
        print("7) Click 'Импортировать'")
        try:
            await page.locator("button:has-text('Импортировать')").first.click()
        except Exception as e:
            print(f"  ERROR: import button not found: {e}")
            return 1
        # Wait for the report to render.
        await page.wait_for_timeout(3000)
        await page.screenshot(path="logs/browser_run/tdata_05_imported.png", full_page=True)

        # 8) Verify the account landed in the DB.
        print("8) Verify via API")
        accounts = api_get("/api/v1/accounts?limit=200")
        matches = [a for a in accounts if a.get("phone_number") == EXPECTED_PHONE]
        if not matches:
            print(f"  ERROR: account {EXPECTED_PHONE} not found. Got: {[a.get('phone_number') for a in accounts]}")
            print(f"  Console errors so far: {len(errors)}")
            for k, t in errors[:10]:
                print(f"    {k}: {t}")
            return 1
        account = matches[0]
        print(f"  OK: account id={account['id']} phone={account['phone_number']} "
              f"status={account['status']} folder={account['folder']} proxy_id={account['proxy_id']} "
              f"has_session={account['has_session']}")
        if account["proxy_id"] != proxy_id:
            print(f"  ERROR: expected proxy_id={proxy_id}, got {account['proxy_id']}")
            return 1
        if not account["has_session"]:
            print(f"  ERROR: account should have a session after tdata import")
            return 1

        # 9) NEGATIVE TEST: prove the proxy guard fires by creating a
        #    fresh account with no proxy and then trying /send-code on
        #    it. We delete the just-imported account first so we don't
        #    leave junk.
        print("9) NEGATIVE: create a proxy-less account and try /send-code, expect 400")
        code, no_proxy = api_post("/api/v1/accounts", {
            "phone_number": "+10000000000",
            "api_id": 12345,
            "api_hash": "a" * 32,
        })
        if code not in (200, 201):
            print(f"  ERROR: could not create test account, status={code}: {no_proxy}")
            return 1
        bare_id = no_proxy["id"]
        code, body = api_post(f"/api/v1/accounts/{bare_id}/send-code", {})
        if code != 400:
            print(f"  ERROR: expected 400 from /send-code on proxy-less account, got {code}: {body}")
            return 1
        if "proxy" not in str(body).lower():
            print(f"  ERROR: expected 'proxy' in error body, got: {body}")
            return 1
        print(f"  OK: proxy-less /send-code correctly rejected with 400: {body}")

        # Clean up the bare test account.
        import urllib.request as _ur
        req = _ur.Request(
            f"{API_URL}/api/v1/accounts/{bare_id}",
            method="DELETE",
            headers={"Authorization": f"Bearer {ADMIN_TOKEN}", "X-Project-ID": "1"},
        )
        _ur.urlopen(req, timeout=10).close()
        await page.screenshot(path="logs/browser_run/tdata_06_neg_test.png", full_page=True)

        # 10) POSITIVE TEST: with proxy attached, /send-code passes the
        #     guard. It may still fail for a Telegram reason (rate
        #     limit, etc.) but NOT with our proxy 400.
        print("10) POSITIVE: /send-code with proxy reaches Telegram (no proxy 400)")
        code, body = api_post(f"/api/v1/accounts/{account['id']}/send-code", {})
        if code == 400 and "proxy" in str(body).lower():
            print(f"  ERROR: proxy guard still blocking: {body}")
            return 1
        print(f"  /send-code with proxy: HTTP {code} (proxy guard bypassed)")

        print("")
        print("=== Browser console errors during run ===")
        for k, t in errors[:20]:
            print(f"  {k}: {t}")

        await browser.close()
        return 0


if __name__ == "__main__":
    rc = asyncio.run(main())
    sys.exit(rc)
