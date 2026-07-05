"""Quick browser sanity check: open the Proxies page after the
CORS fix and dump console errors. Used to verify the network
errors are gone."""
import asyncio
import json
from playwright.async_api import async_playwright

ADMIN_TOKEN = "YOUR_BEARER_TOKEN"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = await browser.new_context(viewport={"width": 1400, "height": 900}, locale="ru-RU")
        page = await ctx.new_page()
        errors = []
        page.on("console", lambda m: errors.append(("console." + m.type, m.text[:200])) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(("pageerror", str(e)[:200])))

        await page.goto("http://[::1]:5177/", wait_until="domcontentloaded")
        await page.evaluate("(t) => localStorage.setItem('admin_api_token', t)", ADMIN_TOKEN)
        await page.evaluate("() => localStorage.setItem('active_project_id', '1')")
        await page.reload(wait_until="networkidle")
        await page.wait_for_timeout(2000)

        # Navigate to proxies
        try:
            await page.get_by_role("link", name="Прокси").first.click()
        except Exception:
            await page.locator("text=Прокси").first.click()
        await page.wait_for_url("**/proxies", timeout=10000)
        await page.wait_for_timeout(3000)

        await page.screenshot(path="logs/browser_run/test_after_cors_fix.png", full_page=True)
        body = await page.text_content("body")
        print('Has "Всего прокси":', "Всего прокси" in body)
        print('Has "Добавить прокси":', "Добавить прокси" in body)
        print("Errors during load:", len(errors))
        for kind, text in errors[:10]:
            print(f"  {kind}: {text[:200]}")
        await browser.close()

asyncio.run(main())
