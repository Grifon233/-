from contextlib import asynccontextmanager
import asyncio
from contextlib import suppress
import os
from pathlib import Path
import logging
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.database import init_db, seed_master, async_session_maker, ShortUrl
from backend.webhook import close_cached_bots, router as webhook_router, run_master_bot_polling, start_webhook_server
from backend.routers.master import router as master_router
from backend.routers.booking import router as booking_router
from backend.routers.admin import router as admin_router
from backend.routers.demo import router as demo_router
from backend.routers.shorten import router as shorten_router
from backend.routers.superadmin import router as superadmin_router
from backend.routers.payments import router as payments_router
from backend.routers.utm import router as utm_router
from backend.media_storage import get_upload_dir

# Настройка логирования
Path("logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    handlers=[
        logging.FileHandler('logs/api.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    async with async_session_maker() as session:
        await seed_master(session)

    # Запуск webhook сервера для ботов мастеров.
    # При нескольких FastAPI workers (gunicorn/uvicorn --workers) каждый worker
    # пытается занять порт 8081, что приводит к ошибке.
    # Решение: WEBHOOK_SERVER_ENABLED=true только у одного worker (например,
    # через переменную окружения или отдельный entrypoint).
    webhook_runner = None
    if os.environ.get("WEBHOOK_SERVER_ENABLED", "").lower() in ("true", "1", "yes"):
        webhook_runner = await start_webhook_server()
        logger.info("Webhook server started on port 8081")
    else:
        logger.info("Webhook server disabled (set WEBHOOK_SERVER_ENABLED=true to enable)")

    from backend.services.booking_notifications import run_booking_notification_loop
    from backend.vk.longpoll import run_vk_bots_polling
    notification_task = asyncio.create_task(run_booking_notification_loop())
    master_bot_polling_task = asyncio.create_task(run_master_bot_polling())
    vk_polling_task = asyncio.create_task(run_vk_bots_polling())

    yield

    # Cleanup
    notification_task.cancel()
    master_bot_polling_task.cancel()
    vk_polling_task.cancel()
    with suppress(asyncio.CancelledError):
        await notification_task
    with suppress(asyncio.CancelledError):
        await master_bot_polling_task
    with suppress(asyncio.CancelledError):
        await vk_polling_task
    await close_cached_bots()
    from backend.vk.api import close_http_client
    await close_http_client()
    if webhook_runner:
        await webhook_runner.cleanup()
        logger.info("Webhook server stopped")


app = FastAPI(title="Master Booking API", version="1.0", lifespan=lifespan)

# Demo режим - включается переменной окружения DEMO_MODE=true
if os.environ.get("DEMO_MODE", "").lower() == "true":
    from backend.middleware.demo_mode import enable_demo_mode
    enable_demo_mode(app)

allowed_origins = [
    origin.strip()
    for origin in os.environ.get("CORS_ALLOW_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve uploaded files
uploads_dir = get_upload_dir()
app.mount("/api/uploads", StaticFiles(directory=str(uploads_dir)), name="uploads")

app.include_router(admin_router, prefix="/api")
app.include_router(master_router, prefix="/api")
app.include_router(booking_router, prefix="/api")
app.include_router(demo_router, prefix="/api")
app.include_router(shorten_router, prefix="/api")
app.include_router(superadmin_router)
app.include_router(payments_router)
app.include_router(utm_router)
app.include_router(webhook_router)


@app.get("/s/{code}")
async def redirect_short(code: str):
    from fastapi import HTTPException
    from fastapi.responses import RedirectResponse
    from sqlalchemy import select

    async with async_session_maker() as session:
        result = await session.execute(select(ShortUrl).where(ShortUrl.code == code))
        short = result.scalar_one_or_none()

    if not short:
        raise HTTPException(status_code=404, detail="Ссылка не найдена")

    # Редиректим только на безопасные схемы — чтобы короткая ссылка под нашим
    # доменом не стала инструментом для javascript:/data: и прочего.
    safe = ("http://", "https://", "tel:", "mailto:")
    if not short.original_url.lower().startswith(safe):
        raise HTTPException(status_code=400, detail="Небезопасный адрес ссылки")

    return RedirectResponse(url=short.original_url, status_code=302)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
