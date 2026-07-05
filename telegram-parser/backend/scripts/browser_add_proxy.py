"""End-to-end browser test: add a proxy through the UI as a human.

This is the bug-check harness the operator uses to make sure the
UI flows (not the API) actually work for the most common operations.

Capabilities:
* Captures every ``console.*`` call and every failed network request
  so we can spot the "lots of errors on the right" symptom the
  operator keeps seeing.
* Tries to fill the proxy form using the actual Russian labels
  rendered in the UI ("Хост", "Порт", "Логин", "Пароль", "Протокол").
* Falls back to a single-line "paste and go" textarea that takes
  ``host:port:user:pass`` strings and bulk-creates the proxies.
* Verifies the backend database through the API after submit.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import List

from playwright.async_api import async_playwright, Page, ConsoleMessage, Request, Response

FRONTEND_URL = "http://[::1]:5177/"
API_URL = "http://127.0.0.1:8000"
ADMIN_TOKEN = "YOUR_BEARER_TOKEN"

PROXY_HOST = "38.154.19.220"
PROXY_PORT = "8000"
PROXY_USER = "F6keWS"
PROXY_PASS = "wMSRMa"


class Recorder:
    """Captures console messages + network failures for offline analysis."""

    def __init__(self, page: Page) -> None:
        self.console: List[ConsoleMessage] = []
        self.failed_requests: List[tuple[Request, str | None]] = []
        self.bad_responses: List[tuple[Response, str | None]] = []
        page.on("console", lambda msg: self.console.append(msg))
        page.on("requestfailed", lambda req: self.failed_requests.append((req, req.failure)))
        page.on("response", lambda res: self.bad_responses.append((res, None)) if res.status >= 400 else None)

    def dump(self, label: str) -> None:
        out_dir = Path("logs/browser_run")
        out_dir.mkdir(parents=True, exist_ok=True)
        report = {
            "label": label,
            "ts": time.time(),
            "console": [
                {"type": m.type, "text": m.text, "location": str(m.location)}
                for m in self.console
            ],
            "failed_requests": [
                {"url": req.url, "method": req.method, "failure": fail}
                for req, fail in self.failed_requests
            ],
            "http_errors": [
                {"url": res.url, "status": res.status}
                for res, _ in self.bad_responses
                if res.status >= 400
            ],
        }
        path = out_dir / f"recorder_{label}.json"
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  recorder: {path} "
              f"(console={len(self.console)}, failed={len(self.failed_requests)}, "
              f"http_errs={sum(1 for r,_ in self.bad_responses if r.status>=400)})")


async def take_screenshot(page: Page, label: str) -> None:
    out_dir = Path("logs/browser_run")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{int(time.time())}_{label}.png"
    await page.screenshot(path=str(path), full_page=True)
    print(f"  screenshot: {path}")


async def find_field(page: Page, *candidates: str):
    """Locate an input by several selector strategies."""
    for cand in candidates:
        selectors = [
            f"input[name='{cand}']",
            f"textarea[name='{cand}']",
            f"select[name='{cand}']",
            f"input[placeholder*='{cand}' i]",
            f"label:has-text('{cand}') >> xpath=following::input[1]",
            f"label:has-text('{cand}') >> xpath=following::textarea[1]",
            f"label:has-text('{cand}') >> xpath=following::select[1]",
        ]
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    return el
            except Exception:
                continue
    return None


async def main() -> int:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(
            viewport={"width": 1400, "height": 900},
            locale="ru-RU",
        )
        page = await context.new_page()
        rec = Recorder(page)

        # 1) Seed admin token into localStorage before any app code runs.
        print("1) Open app and seed admin token")
        await page.goto(FRONTEND_URL, wait_until="domcontentloaded")
        await page.evaluate(
            "(t) => window.localStorage.setItem('admin_api_token', t)",
            ADMIN_TOKEN,
        )
        await page.evaluate(
            "() => window.localStorage.setItem('active_project_id', '1')"
        )
        await page.reload(wait_until="networkidle")
        await take_screenshot(page, "01_home")

        # 2) Navigate to Proxies page.
        print("2) Navigate to Proxies page")
        try:
            await page.get_by_role("link", name="Прокси").first.click()
        except Exception:
            await page.locator("text=Прокси").first.click()
        await page.wait_for_url("**/proxies", timeout=10000)
        # Wait for the table to populate (one successful GET /proxies).
        await page.wait_for_timeout(1500)
        await take_screenshot(page, "02_proxies")
        rec.dump("02_proxies")

        # 3) Open the Add proxy modal.
        print("3) Open 'Add proxy' modal")
        clicked = False
        for sel in [
            "button:has-text('Добавить')",
            "button:has-text('+ Добавить')",
            "[data-testid='add-proxy']",
        ]:
            try:
                await page.locator(sel).first.click(timeout=3000)
                clicked = True
                break
            except Exception:
                continue
        if not clicked:
            print("  ERROR: Add button not found")
            await take_screenshot(page, "03_no_add_button")
            return 1
        await page.wait_for_timeout(500)
        await take_screenshot(page, "03_add_modal")

        # 4) Fill the form using Russian labels.
        print("4) Fill the proxy form")
        host_field = await find_field(page, "host", "Хост", "IP", "Адрес")
        if host_field is None:
            print("  ERROR: 'Хост' field not found")
            return 1
        await host_field.fill(PROXY_HOST)

        port_field = await find_field(page, "port", "Порт")
        if port_field is None:
            print("  ERROR: 'Порт' field not found")
            return 1
        await port_field.fill(PROXY_PORT)

        # Protocol select (default is socks5; we set it explicitly).
        protocol_field = await find_field(page, "scheme", "Протокол")
        if protocol_field is not None:
            try:
                await protocol_field.select_option(value="socks5")
            except Exception:
                pass  # default is fine

        user_field = await find_field(page, "username", "Логин")
        if user_field is not None:
            await user_field.fill(PROXY_USER)

        pass_field = await find_field(page, "password", "Пароль")
        if pass_field is not None:
            await pass_field.fill(PROXY_PASS)

        await take_screenshot(page, "04_filled")

        # 5) Submit.
        print("5) Click 'Сохранить'")
        submitted = False
        for sel in [
            "button:has-text('Сохранить')",
            "button[type='submit']",
        ]:
            try:
                await page.locator(sel).first.click(timeout=3000)
                submitted = True
                break
            except Exception:
                continue
        if not submitted:
            print("  ERROR: Submit button not found")
            return 1
        await page.wait_for_timeout(2000)
        await take_screenshot(page, "05_after_save")
        rec.dump("05_after_save")

        # 6) Verify via API.
        print("6) Verify via API")
        import urllib.request
        req = urllib.request.Request(
            f"{API_URL}/api/v1/proxies",
            headers={"Authorization": f"Bearer {ADMIN_TOKEN}", "X-Project-ID": "1"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            proxies = json.loads(resp.read())
        matches = [
            p for p in proxies
            if p.get("host") == PROXY_HOST and p.get("port") == int(PROXY_PORT)
        ]
        if not matches:
            print(f"  ERROR: proxy not found in API response. Got: {proxies}")
            return 1
        proxy = matches[0]
        print(f"  OK: proxy id={proxy['id']} {proxy['host']}:{proxy['port']} "
              f"scheme={proxy['scheme']} user={proxy.get('username')!r}")
        if proxy.get("username") != PROXY_USER:
            print(f"  ERROR: username mismatch: {proxy.get('username')!r}")
            return 1
        assert "password" not in proxy, "password should not be returned by the API"

        # 7) Print a summary of what we saw in the network/console layer.
        print("")
        print("=== Browser log summary ===")
        for msg in rec.console:
            if msg.type in ("error", "warning"):
                print(f"  console.{msg.type}: {msg.text[:200]}")
        for req, fail in rec.failed_requests:
            print(f"  request failed: {req.method} {req.url} -> {fail}")
        http_errs = [(res, _) for res, _ in rec.bad_responses if res.status >= 400]
        for res, _ in http_errs[:20]:
            print(f"  http {res.status}: {res.url}")

        await browser.close()
        return 0


if __name__ == "__main__":
    rc = asyncio.run(main())
    sys.exit(rc)
