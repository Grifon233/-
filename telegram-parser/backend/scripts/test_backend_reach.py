import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox'])
        page = await browser.new_page()
        for url in ['http://127.0.0.1:8000/api/v1/health', 'http://[::1]:8000/api/v1/health', 'http://localhost:8000/api/v1/health']:
            try:
                resp = await page.goto(url, timeout=5000, wait_until='domcontentloaded')
                status = resp.status if resp else 'no resp'
                body = (await page.content())[:200]
                print(f'{url} -> {status}')
                print(f'  body: {body}')
            except Exception as e:
                print(f'{url} -> FAIL: {str(e)[:200]}')
        await browser.close()

asyncio.run(main())
