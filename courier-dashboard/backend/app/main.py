"""Backend проекта «Курьеры». Точка входа FastAPI.

Запуск локально:
    cd backend
    python -m venv .venv && . .venv/Scripts/activate   # Windows
    pip install -r requirements.txt
    cp .env.example .env
    uvicorn app.main:app --reload

После запуска:
    Приложение (Mini App):  http://127.0.0.1:8000/app/
    Документация API:        http://127.0.0.1:8000/docs
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.routers import feedback, ingest, route, streets

app = FastAPI(title="Курьеры — backend", version="0.2.0")

# Mini App открывается внутри Telegram (чужой origin) -> разрешаем CORS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingest.router, tags=["ingest"])
app.include_router(streets.router, tags=["streets"])
app.include_router(route.router, tags=["route"])
app.include_router(feedback.router, tags=["feedback"])


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


# Отдаём само приложение (miniapp/) с того же сервера: http://127.0.0.1:8000/app/
_MINIAPP_DIR = Path(__file__).resolve().parents[2] / "miniapp"
if _MINIAPP_DIR.is_dir():
    app.mount("/app", StaticFiles(directory=str(_MINIAPP_DIR), html=True), name="miniapp")
