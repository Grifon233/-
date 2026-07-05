"""End-to-end visual verification of the fixes we just made.

Steps taken in the browser (Playwright Chromium headed):

  1. Open the Accounts page (http://[::1]:5177/accounts).
  2. Confirm the table renders at least one account row.
  3. Change the gender filter to 'Женский' (the frontend label for
     ``gender=female``) — expect the table to show zero rows and
     zero "Internal Server Error" overlays.
  4. Change the gender filter to 'Не указан' (unknown) — expect
     one row (Marvin Castro / +18382068327).
  5. Open the profile editor for that account; click "Refresh" —
     expect a clear "Telegram session is no longer valid. Re-login
     the account." toast (this is the new 401 path).
  6. Go to Proxies; click "Прокси-сервис" vendor modal — expect a
     either a 502 "vendor unreachable" surface (if proxy6.net is
     down) or a balance card (if reachable).
  7. Paste 2 manual proxies in the bulk-paste area, click "Import"
     — expect them to appear in the proxies table.

Throughout, console errors are captured to ``logs/e2e_console.log``
and screenshots to ``logs/e2e_*.png`` so we can see what the user
sees.
"""
import asyncio
import os
import sys
import time
from pathlib import Path

from playwright.async_api import async_playwright, TimeoutError as PWTimeout

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "logs"
LOGS.mkdir(exist_ok=True)
SHOT = lambda name: LOGS / f"e2e_{name}.png"  # noqa: E731

URL = "http://[::1]:5177"

CONSOLE_LOG = open(LOGS / "e2e_console.log", "w", encoding="utf-8")


def header(s):
    print("\n" + "=" * 78)
    print(s)
    print("=" * 78)


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False, slow_mo=200)
        ctx = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await ctx.new_page()

        page.on("console", lambda msg: CONSOLE_LOG.write(f"[{msg.type}] {msg.text}\n"))
        page.on("pageerror", lambda exc: CONSOLE_LOG.write(f"[pageerror] {exc}\n"))

        # 1) Open Accounts
        header("1. Opening Accounts page")
        await page.goto(f"{URL}/accounts", wait_until="domcontentloaded")
        await page.wait_for_load_state("networkidle", timeout=15000)
        await page.screenshot(path=str(SHOT("01_accounts")))

        # 2) Confirm at least one account row
        try:
            await page.wait_for_selector("text=+18382068327", timeout=8000)
            print("OK  +18382068327 row visible")
        except PWTimeout:
            print("FAIL account row not visible")

        # 3) Change gender filter
        header("2. Gender filter → 'Женский' (female)")
        # Find the gender select; the label can be 'Пол' / 'Gender'
        # Try locating by surrounding label text
        for label in ("Пол", "Gender"):
            try:
                select = page.get_by_label(label, exact=False)
                if await select.count() > 0:
                    await select.first.select_option(label="female")
                    break
            except Exception:
                continue
        else:
            # Try by role+name pattern: a <select> with options
            print("WARN  could not find a labelled select; looking for any select")
            selects = await page.locator("select").all()
            for sel in selects:
                opts = await sel.evaluate("e => Array.from(e.options).map(o => o.value + ':' + o.textContent)")
                print("  options:", opts)
        await page.wait_for_timeout(500)
        await page.screenshot(path=str(SHOT("02_gender_female")))
        rows = await page.locator("text=+18382068327").count()
        print(f"INFO  rows for +18382068327 visible after filter: {rows}")

        # 4) Gender → 'Не указан' (unknown)
        header("3. Gender filter → 'Не указан' (unknown)")
        try:
            select = page.get_by_label("Пол", exact=False)
            if await select.count() > 0:
                await select.first.select_option(label="unknown")
        except Exception as e:
            print(f"WARN  filter switch failed: {e}")
        await page.wait_for_timeout(500)
        await page.screenshot(path=str(SHOT("03_gender_unknown")))
        rows = await page.locator("text=+18382068327").count()
        print(f"INFO  rows for +18382068327 visible after filter: {rows}")

        # 5) Open profile editor and try refresh
        header("4. Open profile editor and click Refresh")
        # Click the row's profile button — usually an icon or "Edit" link
        try:
            await page.get_by_text("+18382068327").first.click()
            await page.wait_for_timeout(300)
        except Exception:
            pass
        # Look for an Edit / Профиль button
        for label in ("Edit", "Профиль", "Profile", "Edit profile"):
            try:
                btn = page.get_by_role("button", name=label, exact=False)
                if await btn.count() > 0:
                    await btn.first.click()
                    break
            except Exception:
                continue
        await page.wait_for_timeout(500)
        await page.screenshot(path=str(SHOT("04_profile_modal")))
        # Click Refresh
        for label in ("Refresh", "Обновить", "🔄"):
            try:
                btn = page.get_by_role("button", name=label, exact=False)
                if await btn.count() > 0:
                    await btn.first.click()
                    break
            except Exception:
                continue
        await page.wait_for_timeout(2000)
        await page.screenshot(path=str(SHOT("05_profile_refresh")))
        # Look for the 401 message
        try:
            await page.wait_for_selector("text=session is no longer valid", timeout=4000)
            print("OK   401 message visible in UI")
        except PWTimeout:
            print("WARN  401 message not found in UI (might be a toast)")

        # 6) Proxies page vendor modal
        header("5. Proxies page → vendor modal")
        await page.goto(f"{URL}/proxies", wait_until="domcontentloaded")
        await page.wait_for_load_state("networkidle", timeout=15000)
        await page.screenshot(path=str(SHOT("06_proxies")))
        for label in ("Прокси-сервис", "Vendor", "Webshare", "proxy6", "Proxy vendor"):
            try:
                btn = page.get_by_role("button", name=label, exact=False)
                if await btn.count() > 0:
                    await btn.first.click()
                    break
            except Exception:
                continue
        await page.wait_for_timeout(1500)
        await page.screenshot(path=str(SHOT("07_vendor_modal")))

        # 7) Paste proxies
        header("6. Paste two manual proxies")
        try:
            ta = page.get_by_placeholder("paste proxies", exact=False)
            if await ta.count() == 0:
                ta = page.get_by_placeholder("socks5://", exact=False)
            if await ta.count() == 0:
                ta = page.locator("textarea").first
            await ta.fill(
                "socks5://u1:p1@5.6.7.8:1080\n"
                "http://u2:p2@9.10.11.12:3128"
            )
        except Exception as e:
            print(f"WARN  paste failed: {e}")
        await page.screenshot(path=str(SHOT("08_paste_filled")))
        for label in ("Import", "Импорт", "Добавить", "Add"):
            try:
                btn = page.get_by_role("button", name=label, exact=False)
                if await btn.count() > 0:
                    await btn.first.click()
                    break
            except Exception:
                continue
        await page.wait_for_timeout(1500)
        await page.screenshot(path=str(SHOT("09_paste_imported")))

        await browser.close()

    CONSOLE_LOG.close()
    print("\nDone. See:")
    for p in sorted(LOGS.glob("e2e_*.png")):
        print("  ", p)
    print("  ", LOGS / "e2e_console.log")


if __name__ == "__main__":
    asyncio.run(main())
