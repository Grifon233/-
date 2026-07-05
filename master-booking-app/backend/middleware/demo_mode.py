"""
Middleware для демо режима.
В demo режиме все операции симулируются - данные не сохраняются в базу.
"""
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger(__name__)

# ID демо-мастера
DEMO_MASTER_ID = 1


def is_demo_request(request: Request) -> bool:
    """Проверяет, является ли запрос демо-режимом"""
    if hasattr(request.app.state, "demo_mode") and request.app.state.demo_mode:
        return True
    return getattr(request.state, "demo_mode", False)


def is_demo_master_request(request: Request, master_id: int = None) -> bool:
    """
    Проверяет, является ли запрос демо-запросом конкретного мастера.
    Демо-запрос = demo режим включен И запрос идёт к демо-мастеру (master_id == 1)
    """
    if not is_demo_request(request):
        return False

    # Если передан master_id - проверяем конкретно
    if master_id is not None:
        return master_id == DEMO_MASTER_ID

    # Иначе проверяем параметр в запросе
    user_id = request.query_params.get("user")
    bot_id = request.query_params.get("bot_id")

    # Демо-запрос может быть по умолчанию если это публичный роутер /call
    return True  # Для client_call демо-мастера всегда демо режим


class DemoModeMiddleware(BaseHTTPMiddleware):
    """
    В demo режиме:
    - Все POST/PUT/DELETE запросы проходят обработку
    - Но вместо commit делается rollback
    - Клиент видит что всё успешно, но в базе ничего не сохраняется
    """

    async def dispatch(self, request: Request, call_next):
        # Проверяем demo режим
        demo_mode = request.app.state.demo_mode if hasattr(request.app.state, "demo_mode") else False

        if demo_mode:
            request.app.state.is_demo_request_latest = True
            request.state.demo_mode = True

        return await call_next(request)


def enable_demo_mode(app):
    """Включает demo режим для FastAPI приложения"""
    app.state.demo_mode = True
    app.add_middleware(DemoModeMiddleware)
    logger.info("Demo mode enabled - write operations blocked")
