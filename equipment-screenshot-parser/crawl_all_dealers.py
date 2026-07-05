"""
Оркестратор — обходит все 14 дилерских сайтов XCMG и делает full-page скриншоты.
Основан на логике crawl_smart.py (дедупликация + попап-киллер).

Запуск:
    python crawl_all_dealers.py

Параметры (меняй внизу файла):
    MAX_PAGES   — лимит страниц на один сайт (по умолчанию 150)
    START_FROM  — с какого сайта начинать (0 = с первого, удобно для продолжения)
"""

import os
import time
import asyncio
import datetime
import hashlib
from urllib.parse import urljoin, urlparse
from playwright.async_api import async_playwright
import requests
from bs4 import BeautifulSoup


# ─── Приоритетные разделы (контакты + о компании) ─────────────────────────────
# Страницы с такими префиксами путей идут в начало очереди

PRIORITY_PATHS = [
    # Контакты
    '/contacts', '/contact', '/contact-us', '/contact_us', '/contactus',
    '/kontakty', '/kontakti', '/contacts_ru', '/svyaz', '/obratnaya-svyaz',
    '/callback', '/napisat-nam', '/write-us',
    '/get-in-touch', '/reach-us', '/connect',
    # О компании
    '/about', '/about-us', '/about_us', '/company', '/company-info', '/who-we-are',
    '/o-kompanii', '/about-company', '/o-nas', '/onas', '/company-ru',
    '/our-story', '/mission', '/vision',
]

# ─── Игнорируемые разделы ─────────────────────────────────────────────────────
# Страницы с такими префиксами путей пропускаются полностью

IGNORE_PATHS = [
    # Каталог / товары
    '/catalog', '/catalogue', '/products', '/product', '/item', '/items',
    '/shop', '/store', '/market', '/marketplace',
    '/katalog', '/catalog-ru', '/produkty', '/tovary', '/assortiment',
    '/produkciya', '/nomenklatura',
    '/goods', '/collection', '/collections',
    '/price', '/prices', '/pricing',
    # Политики / юридические
    '/privacy', '/privacy-policy', '/policy', '/terms', '/terms-of-use',
    '/agreement', '/legal', '/compliance', '/gdpr',
    # Аккаунты / авторизация
    '/login', '/signin', '/signup', '/register',
    '/account', '/dashboard', '/profile',
    # Корзина / заказ
    '/cart', '/checkout', '/basket', '/order', '/payment',
    # Маркетинг / акции
    '/promo', '/sale', '/discount', '/campaign',
    '/offers',
    # Блог / статьи / новости
    '/blog', '/news', '/articles', '/press', '/media', '/insights',
    # SEO-мусор
    '/sitemap', '/search', '/tag', '/category', '/filter', '/amp',
    # Саппорт
    '/support', '/helpdesk', '/ticket', '/faq', '/help',
    # Новые стоп-слова
    '/product',
    '/catalogs',
    '/social_prj',
    '/3d-tur-xcmg',
    '/out',
    '/history',
    '/video',
    '/tekhnika-v-nalichii',
    '/feedback',
    '/action',
]

# ─── Расширения файлов для игнора ─────────────────────────────────────────────
IGNORE_EXTENSIONS = ('.pdf', '.jpg', '.jpeg', '.png', '.svg', '.gif',
                     '.zip', '.doc', '.docx', '.xls', '.xlsx')

# ─── Список дилеров ────────────────────────────────────────────────────────────

DEALERS = [
    ("ООО «СюйГун Ру»",            "https://xcmg-ru.ru"),
    ("ООО «СК Машинери»",          "https://scmachinery.ru"),
    ("ООО «ГЦ ТЕХНО»",             "https://techno-xcmg.ru"),
    ("ООО «СПЕЦЦЕНТР»",            "https://xcmg-rf.ru"),
    ("ООО «РУСТЕХНО»",             "https://xcmg.ru"),
    ("ООО «СТРОЙТЕХИМПОРТ»",       "https://xcmg-russia.ru"),
    ("ООО «Сильные машины Запад»", "https://silnmash.ru"),
    ("ООО «АльфаКом»",             "https://alfc.ru"),
    ("ООО «ТехИнвестГрупп»",       "https://tigr86.ru"),
    ("ООО Фирма «Интерпартнер»",   "https://interpartner.ru"),
    ("ООО «ИксСиЭмДжи Восток»",    "https://xcmgvostok.ru"),
    ("ООО «Спецтранспорт»",        "https://eastlog.ru"),
    ("ООО «ПРОМЭКС»",              "https://promexxgroup.ru"),
    ("ООО «Тевекс»",                       "https://tevex.ru"),
    ("ООО ТПК «НТЦ»",                     "https://ntcentr.com"),
    ("АО «МОТОРАВТО»",                     "https://stmotor.ru"),
    ("ООО «КАРЬЕРНЫЙ КЛУБ»",              "https://дсо.карьерный-клуб.рф"),
    ("ООО «ПСТ»",                          "https://pst-xcmg.ru"),
    ("ООО «ИксСиЭмДжи Северо-Запад»",     "https://xcmg-nw.ru"),
    ("ООО «Грузовая техника - Челябинск»", "https://gruz-tehnika.ru"),
    ("ООО «ТЕХСТРОЙПРОЕКТ»",              "https://tehstroiproekt.ru"),
    ("ООО «ТЦ Прогресс»",                 "https://xcmg-ru.ru"),
    ("ООО «Фентай»",                      "https://xcmg-rf.ru"),
    ("ООО «МегаТ»",                       "https://megat.ru"),
    ("ООО «Лучшие Дары Родины»",          "https://avtoprom-ldr.ru"),
    ("ООО «Юпитер 9»",                    "https://upiter9.ru"),
    ("ООО «НАК Машинери»",                "https://nacm.ru"),
    ("ЗАО «Корпорация Малком»",           "https://xcmg-malkom.ru"),
    ("ООО НПП «Леспромсервис»",           "https://xcmg11.ru"),
    ("ООО «КОМТРАНС ГРУП»",               "https://komtrans24.ru"),
    ("ООО «Техно-Профи»",                 "https://tecprofi.ru"),
    ("ООО «НПФ Технотранс»",              "https://xcmg-tt.ru"),
    ("ООО «Бриз»",                        "https://нанхуль.рф"),
    ("ООО «АРМ Техно»",                   "https://armtehno.ru"),
    ("ООО «Центр КА»",                    "http://centr-ka.ru"),
    ("ООО «Стальные машины»",             "https://www.alfc.ru"),
    ("ООО «Альфа»",                       "https://www.alfc.ru"),
    ("ООО «УМГ-СЕ»",                      "https://umg-ce.com"),
]


# ─── Краулер ───────────────────────────────────────────────────────────────────

class WebsiteCrawler:
    def __init__(self, base_url, output_dir):
        self.base_url = base_url
        self.output_dir = output_dir
        self.domain = urlparse(base_url).netloc
        self.visited_urls  = set()   # нормализованные URL которые уже взяли в работу
        self.to_visit      = [self._normalize_url(base_url)]
        self.existing_files = self._load_existing()
        # Уровень 3: хэши файлов (байт-точные дубли)
        self.seen_file_hashes = self._load_file_hashes()
        # Уровень 3: хэши текстового содержимого (одинаковый шаблон, пустые страницы)
        self.seen_text_hashes = set()
        print(f"  [INFO] Уже есть скриншотов: {len(self.existing_files)}", flush=True)

    # ── Инициализация ──────────────────────────────────────────────────────────

    def _load_existing(self):
        if not os.path.exists(self.output_dir):
            return set()
        return {f for f in os.listdir(self.output_dir) if f.endswith('.png')}

    def _load_file_hashes(self):
        hashes = set()
        if not os.path.exists(self.output_dir):
            return hashes
        for fname in self.existing_files:
            try:
                hashes.add(self._md5(os.path.join(self.output_dir, fname)))
            except:
                pass
        return hashes

    # ── Хэши ───────────────────────────────────────────────────────────────────

    @staticmethod
    def _md5(path):
        h = hashlib.md5()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(65536), b''):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _text_hash(text):
        return hashlib.md5(text.strip().encode('utf-8', errors='ignore')).hexdigest()

    # ── URL-утилиты ────────────────────────────────────────────────────────────

    @staticmethod
    def _normalize_url(url):
        """Убирает query/fragment, нормализует слэш, приводит домен к lower."""
        p = urlparse(url)
        path = p.path if p.path else '/'
        # Убираем дублирующиеся слэши, но оставляем trailing slash единообразно
        path = '/' + '/'.join(s for s in path.split('/') if s)
        normalized = p._replace(
            scheme=p.scheme.lower(),
            netloc=p.netloc.lower(),
            path=path,
            query='',
            fragment=''
        )
        return normalized.geturl()

    def _is_valid_url(self, url):
        p = urlparse(url)
        # Принимаем www и без www одного домена
        domain_clean = self.domain.removeprefix('www.')
        netloc_clean = p.netloc.lower().removeprefix('www.')
        return netloc_clean == domain_clean and p.scheme in ('http', 'https')

    def _is_ignored(self, url):
        path = urlparse(url).path.rstrip('/').lower()
        if path.endswith(IGNORE_EXTENSIONS):
            return True
        return any(
            path == p.rstrip('/') or path.startswith(p.rstrip('/') + '/')
            for p in IGNORE_PATHS
        )

    def _is_priority(self, url):
        path = urlparse(url).path.rstrip('/').lower()
        return any(
            path == p.rstrip('/') or path.startswith(p.rstrip('/') + '/')
            for p in PRIORITY_PATHS
        )

    def _url_to_filename_part(self, url):
        path = urlparse(url).path.strip('/').replace('/', '_') or 'index'
        return path[:100]

    def _is_processed(self, url):
        part = self._url_to_filename_part(url)
        return any(f.endswith(part + '.png') for f in self.existing_files)

    # ── Сбор ссылок ────────────────────────────────────────────────────────────

    def get_links(self, url):
        try:
            r = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
            soup = BeautifulSoup(r.content, 'html.parser')
            links = []
            for a in soup.find_all('a', href=True):
                full = self._normalize_url(urljoin(url, a['href']))
                if self._is_valid_url(full) and not self._is_ignored(full):
                    links.append(full)
            return list(set(links))
        except:
            return []

    def _enqueue(self, links):
        """Добавляет ссылки в очередь: приоритетные — вперёд, остальные — в конец."""
        for lnk in links:
            if lnk not in self.visited_urls and lnk not in self.to_visit:
                if self._is_priority(lnk):
                    self.to_visit.insert(0, lnk)
                else:
                    self.to_visit.append(lnk)

    def _probe_priority_pages(self):
        """
        До начала обхода перебирает все шаблоны PRIORITY_PATHS напрямую.
        Те что ответили 200 — вставляет в начало очереди.
        Занимает ~2-5 сек, зато контакты и о компании всегда идут первыми.
        """
        base = self.base_url.rstrip('/')
        found = []
        print(f"  [PROBE] Зондирую приоритетные разделы...", flush=True)
        for path in PRIORITY_PATHS:
            url = self._normalize_url(base + path)
            if url in self.visited_urls or url in self.to_visit:
                continue
            try:
                r = requests.head(url, timeout=5, allow_redirects=True,
                                  headers={'User-Agent': 'Mozilla/5.0'})
                if r.status_code == 200:
                    found.append(url)
                    print(f"  [PROBE] OK {url}", flush=True)
            except:
                pass
        # Вставляем найденные в начало очереди (в обратном порядке чтобы сохранить порядок)
        for url in reversed(found):
            if url not in self.to_visit:
                self.to_visit.insert(0, url)
        print(f"  [PROBE] Найдено приоритетных страниц: {len(found)}", flush=True)

    # ── Попапы ─────────────────────────────────────────────────────────────────

    async def _close_popups(self, page):
        try:
            await page.wait_for_timeout(2500)
            for _ in range(5):
                await page.keyboard.press('Escape')
                await page.wait_for_timeout(150)
            await page.evaluate("""() => {
                ['[class*="modal"]','[class*="popup"]','[class*="dialog"]',
                 '[class*="overlay"]','[class*="lightbox"]','[id*="modal"]',
                 '[id*="popup"]','[role="dialog"]','.fancybox-container','.mfp-wrap'
                ].forEach(s => document.querySelectorAll(s).forEach(el => el.remove()));
                document.body.style.overflow = 'auto';
                document.documentElement.style.overflow = 'auto';
                document.querySelectorAll('*').forEach(el => {
                    const z = parseInt(window.getComputedStyle(el).zIndex);
                    if (z > 1000) {
                        const r = el.getBoundingClientRect();
                        if (r.width > window.innerWidth * 0.3 && r.height > window.innerHeight * 0.3)
                            el.remove();
                    }
                });
            }""")
            await page.wait_for_timeout(400)
            for sel in ['button[class*="close"]', 'a[class*="close"]',
                        '[aria-label*="close" i]', '[aria-label*="закрыть" i]',
                        '.close', '.modal-close']:
                try:
                    for el in await page.query_selector_all(sel):
                        if await el.is_visible():
                            await el.click(timeout=500, force=True)
                            await page.wait_for_timeout(250)
                except:
                    pass
            await page.wait_for_timeout(600)
        except:
            pass

    # ── Скриншот + три уровня защиты от дублей ────────────────────────────────

    async def take_screenshot(self, page, url, filename):
        """
        Возвращает (success, final_url, text_hash).
        Уровень 1: page.url после редиректа
        Уровень 2: <link rel="canonical">
        Уровень 3: хэш текста + хэш файла
        """
        for attempt in range(3):
            try:
                if attempt == 0:
                    await page.goto(url, wait_until='domcontentloaded', timeout=60000)
                    await page.wait_for_timeout(2500)

                # Уровень 1 — финальный URL после редиректа
                final_url = self._normalize_url(page.url)

                # Уровень 2 — canonical tag
                try:
                    canonical = await page.eval_on_selector(
                        'link[rel="canonical"]', 'el => el.href'
                    )
                    if canonical:
                        canonical = self._normalize_url(canonical)
                        if self._is_valid_url(canonical):
                            final_url = canonical
                except:
                    pass

                # Уровень 3а — хэш текстового содержимого страницы
                try:
                    text = await page.evaluate('() => document.body.innerText')
                    th = self._text_hash(text)
                except:
                    th = None

                await self._close_popups(page)
                fpath = os.path.join(self.output_dir, filename)
                await page.screenshot(path=fpath, full_page=True, timeout=90000)

                # Уровень 3б — хэш файла (байт-точный)
                fh = self._md5(fpath)

                return True, final_url, th, fh

            except Exception as e:
                if attempt == 2:
                    print(f"  [ERROR] {url}: {e}", flush=True)
                    return False, url, None, None
                await page.wait_for_timeout(2000)

        return False, url, None, None

    # ── Основной цикл ──────────────────────────────────────────────────────────

    async def crawl(self, max_pages=150):
        os.makedirs(self.output_dir, exist_ok=True)
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            ctx = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                ignore_https_errors=True,
            )
            page = await ctx.new_page()

            # Зондируем приоритетные страницы до старта обхода
            self._probe_priority_pages()

            file_num  = len(self.existing_files)
            new_count = 0
            dup_count = 0
            skipped   = 0

            while self.to_visit and new_count < max_pages:
                url = self.to_visit.pop(0)
                if url in self.visited_urls:
                    continue
                self.visited_urls.add(url)

                if self._is_ignored(url):
                    continue

                if self._is_processed(url):
                    skipped += 1
                    self._enqueue(self.get_links(url))
                    continue

                file_num += 1
                part     = self._url_to_filename_part(url)
                filename = f"{file_num:03d}_{part}.png"
                print(f"  [{new_count+1}/{max_pages}] {url}", flush=True)

                success, final_url, th, fh = await self.take_screenshot(page, url, filename)

                if not success:
                    file_num -= 1
                    await asyncio.sleep(1)
                    continue

                fpath = os.path.join(self.output_dir, filename)

                # Уровень 1+2: редирект или canonical привёл к уже виденному URL
                if final_url != url:
                    self.visited_urls.add(final_url)
                    if self._is_ignored(final_url):
                        os.remove(fpath)
                        file_num -= 1
                        print(f"  [SKIP-REDIRECT] {url} -> {final_url}", flush=True)
                        await asyncio.sleep(1)
                        continue

                # Уровень 3а: дубль по тексту (одинаковый шаблон)
                if th and th in self.seen_text_hashes:
                    os.remove(fpath)
                    file_num -= 1
                    dup_count += 1
                    print(f"  [DUP-CONTENT] {filename}", flush=True)
                    await asyncio.sleep(1)
                    continue

                # Уровень 3б: дубль по файлу (байт-точный)
                if fh in self.seen_file_hashes:
                    os.remove(fpath)
                    file_num -= 1
                    dup_count += 1
                    print(f"  [DUP-FILE] {filename}", flush=True)
                    await asyncio.sleep(1)
                    continue

                # Уникальная страница — сохраняем
                if th:
                    self.seen_text_hashes.add(th)
                self.seen_file_hashes.add(fh)
                self.existing_files.add(filename)
                new_count += 1
                print(f"  [OK] {filename}", flush=True)
                self._enqueue(self.get_links(url))

                await asyncio.sleep(1)

            await browser.close()
            print(f"  Итог: новых={new_count}, дублей удалено={dup_count}, пропущено={skipped}", flush=True)
            return new_count, skipped


# ─── Оркестратор ───────────────────────────────────────────────────────────────

async def run_all(max_pages=150, start_from=0, end_at=None, only_domains=None, output_root="dealers_screenshots"):
    os.makedirs(output_root, exist_ok=True)
    log_path = os.path.join(output_root, "crawl_log.txt")

    total_start = time.time()
    results = []

    print(f"\n" + "="*70, flush=True)
    print(f"  XCMG Dealers Crawler  |  {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}", flush=True)
    print(f"  Сайтов: {len(DEALERS)}  |  Лимит: {max_pages} стр/сайт  |  Старт с #{start_from+1}", flush=True)
    print("="*70 + "\n", flush=True)

    dealers_to_run = DEALERS[start_from: start_from + end_at if end_at else None]

    for i, (name, url) in enumerate(dealers_to_run, start=start_from):
        domain = urlparse(url).netloc
        if only_domains and domain not in only_domains:
            continue
        folder = os.path.join(output_root, domain)
        site_start = time.time()

        print("\n" + "-"*70, flush=True)
        print(f"  [{i+1}/{len(DEALERS)}] {name}", flush=True)
        print(f"  URL: {url}", flush=True)
        print(f"  Папка: {folder}", flush=True)
        print("-"*70, flush=True)

        try:
            crawler = WebsiteCrawler(url, folder)
            new_count, skipped = await crawler.crawl(max_pages=max_pages)
            elapsed = round(time.time() - site_start)
            status = "OK"
            summary = f"новых: {new_count}, пропущено: {skipped}, время: {elapsed}с"
        except Exception as e:
            elapsed = round(time.time() - site_start)
            status = "ERROR"
            summary = str(e)
            print(f"  [FATAL] {e}", flush=True)

        results.append((name, domain, status, summary))
        print(f"\n  Итог: {status} — {summary}", flush=True)

    # ─── Итоговая таблица ──────────────────────────────────────────────────────
    total_elapsed = round(time.time() - total_start)
    mins, secs = divmod(total_elapsed, 60)

    print("\n\n" + "="*70, flush=True)
    print(f"  ИТОГ  |  Общее время: {mins}м {secs}с", flush=True)
    print("="*70, flush=True)
    print(f"  {'#':<3}  {'Домен':<28}  {'Статус':<7}  Детали", flush=True)
    print(f"  {'-'*3}  {'-'*28}  {'-'*7}  {'-'*25}", flush=True)
    for j, (name, domain, status, summary) in enumerate(results, 1):
        print(f"  {j:<3}  {domain:<28}  {status:<7}  {summary}", flush=True)
    print("="*70 + "\n", flush=True)

    # ─── Лог-файл ──────────────────────────────────────────────────────────────
    with open(log_path, 'w', encoding='utf-8') as f:
        f.write(f"Дата: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Лимит стр/сайт: {max_pages}\n")
        f.write(f"Общее время: {mins}м {secs}с\n\n")
        for j, (name, domain, status, summary) in enumerate(results, 1):
            f.write(f"{j}. {name} ({domain})\n   {status}: {summary}\n\n")
    print(f"  Лог сохранён: {log_path}", flush=True)


# ─── Точка входа ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    MAX_PAGES    = 30    # лимит страниц на один сайт
    START_FROM   = 0     # с какого сайта начинать (0 = с первого)
    END_AT       = None  # сколько сайтов обработать (None = все)
    ONLY_DOMAINS = [     # если список не пустой — обрабатывать только эти домены
        'tecprofi.ru',
        'xcmg-tt.ru',
        'armtehno.ru',
        'centr-ka.ru',
        'xcmg11.ru',
        'promexxgroup.ru',
    ]
                       # после теста поставь None чтобы запустить все

    asyncio.run(run_all(
        max_pages=MAX_PAGES,
        start_from=START_FROM,
        end_at=END_AT,
        only_domains=ONLY_DOMAINS,
        output_root="dealers_screenshots",
    ))
