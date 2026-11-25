# Courier Dashboard

Карта сообщений о занятых улицах с выбором города и обратной связью. Mini App открывается в обычном браузере и в Telegram. Backend обслуживает интерфейс и API на одном адресе. Сборщик Telegram запускается отдельно.

## Запуск локально

Python 3.12. Из каталога `courier-dashboard`:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
Set-Location backend
../.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

На Linux/macOS замените путь к Python на `../.venv/bin/python` после перехода в `backend`. Откройте [карту](http://127.0.0.1:8000/app/), [документацию API](http://127.0.0.1:8000/docs) или [проверку готовности](http://127.0.0.1:8000/health). Пустая карта ожидаема, пока в выбранном городе нет свежих сообщений. Открытие `index.html` напрямую не запускает API.

## Настройки

При запуске из `backend` приложение читает переменные процесса и необязательный `backend/.env`. Не добавляйте заполненные файлы, сессии или прокси-пароли в Git.

| Параметр | Назначение |
| --- | --- |
| `INGEST_API_KEY` | Общий ключ backend и сборщика, передаётся в заголовке `X-API-Key`. Если ключ не задан, приём сообщений по умолчанию отключён. |
| `SIGHTING_TTL` | Срок видимости подтверждённого сообщения в секундах, отсчитывается от времени самого сообщения. По умолчанию 7200. |
| `STORE_BACKEND`, `SIGHTINGS_DB_PATH` | `memory` — локальный запуск без сохранения состояния; `sqlite` — сохранение в указанный файл. Для SQLite процессу нужна запись в каталог файла. |
| `NOMINATIM_URL`, `GEOCODING_USER_AGENT` | Адрес геокодера и идентификатор клиента. Геокодирование по умолчанию отключено; без него сообщения остаются в списке без подсветки улиц. При использовании геокодера укажите идентификатор с рабочим контактом. |
| `FEEDBACK_BOT_TOKEN`, `FEEDBACK_CHAT_ID` | Токен бота и целевой чат. Оба должны быть заданы, а бот должен иметь право отправлять сообщения в чат. Иначе обратная связь недоступна. |
| `VALHALLA_URL` | Необязательный адрес Valhalla с нужными картографическими данными для `GET /route`. Обход использует выборку точек на улицах и не гарантирует исключения всей линии. Интерфейс карты не предлагает построение маршрута. |

Список улиц доступен без логина. Для публичных источников он может показывать исходную цитату и ссылку; для закрытых источников отображается только отметка улицы. Подключайте только согласованные источники.

### Docker Compose

```powershell
Copy-Item deploy/.env.example deploy/.env
# При подключении сборщика заполните INGEST_API_KEY в deploy/.env.
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up --build -d
docker compose --env-file deploy/.env -f deploy/docker-compose.yml ps
```

Этот запуск поднимает API и Mini App, сохраняет SQLite в томе `sightings` и слушает только `127.0.0.1`. Остановка через `docker compose down` сохраняет том, а `down -v` удаляет данные. Для доступа извне и запуска внутри Telegram нужен существующий HTTPS-прокси; Compose не настраивает публичный домен, бота или маршрутизатор.

### Сборщик Telegram

Установите `collector/requirements.txt`. Скопируйте `collector/accounts.example.yml` и `collector/sources.example.yml` в `accounts.yml` и `sources.yml` рядом с `collector/main.py`. У каждого аккаунта должен быть настроен прокси. Задайте `BACKEND_URL` (по умолчанию `http://127.0.0.1:8000`; для удалённого API требуется HTTPS) и такой же `INGEST_API_KEY`, как у API. Можно задать их в переменных процесса или в `collector/.env`.

```text
python collector/main.py --check-config
python collector/main.py
```

Первая команда проверяет конфигурацию без сетевых запросов. Первый вход требует интерактивного подтверждения Telegram: временно задайте `ALLOW_INTERACTIVE_LOGIN=1` и после создания сессии уберите эту настройку. Сборщик обрабатывает новые сообщения и не импортирует историю при запуске. Если для диагностики нужен `DEAD_LETTER_FILE`, указывайте закрытый файл вне репозитория: в нём сохраняются сообщения, которые не удалось доставить.

## Проверки

Команды запускаются из `courier-dashboard` с активным виртуальным окружением:

```text
python -m pip install -r backend/requirements-dev.txt -r collector/requirements.txt
python -m playwright install chromium
python -m pytest -q backend collector
python -m pytest -q tests_e2e/e2e.py
```

Для проверки JavaScript-клиента API в Node.js: `node --test miniapp/tests/api.test.cjs`.

Браузерные тесты сами поднимают локальный FastAPI с `STORE_BACKEND=memory`. Геокодер и картографические тайлы подменяются, реальные сообщения Telegram не отправляются.
