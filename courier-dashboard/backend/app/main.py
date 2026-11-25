"""Backend проекта «Курьеры»: API и Mini App на одном origin."""
import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.middleware import RequestSizeLimit
from app.routers import feedback, ingest, route, streets
from app.services.sightings import store

logger = logging.getLogger(__name__)


async def _cleanup_expired() -> None:
    while True:
        await asyncio.sleep(min(settings.sighting_ttl, 60))
        try:
            await run_in_threadpool(store.purge_expired)
        except Exception as exc:
            logger.error("Sightings cleanup failed (%s)", type(exc).__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    cleanup = asyncio.create_task(_cleanup_expired())
    try:
        yield
    finally:
        cleanup.cancel()
        with suppress(asyncio.CancelledError):
            await cleanup


app = FastAPI(title="Курьеры — backend", version="0.3.0", lifespan=lifespan)
app.add_middleware(RequestSizeLimit)

# В Telegram WebView страницы и запросы к API идут с одного origin.
# При отдельном хостинге Mini App разрешаем только явно настроенные origin.
origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
if origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

app.include_router(ingest.router, tags=["ingest"])
app.include_router(streets.router, tags=["streets"])
app.include_router(route.router, tags=["route"])
app.include_router(feedback.router, tags=["feedback"])


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


_MINIAPP_DIR = Path(__file__).resolve().parents[2] / "miniapp"
if _MINIAPP_DIR.is_dir():
    @app.get("/", include_in_schema=False)
    async def home() -> RedirectResponse:
        return RedirectResponse(url="/app/")

    app.mount("/app", StaticFiles(directory=str(_MINIAPP_DIR), html=True), name="miniapp")
