"""Orchestrator: launches/stops external-parser runs.

Mirrors the in-process model the rest of the combine uses (parsing,
comment tasks): work runs as an ``asyncio.create_task`` inside the
uvicorn process, status is persisted to the DB row, and a module-level
registry lets the API stop realtime runs.
"""
from __future__ import annotations

import asyncio
import logging

from app.models.external_parser import ExternalParserStatus, ExternalParserType
from app.services.external_parsers import base

logger = logging.getLogger(__name__)


async def _connect_authorized(client) -> None:
    await client.connect()
    if not await client.is_user_authorized():
        raise ValueError(
            "Telethon-сессия не авторизована. Проверьте аккаунт или "
            "конвертацию Pyrogram→Telethon."
        )


async def _execute(run_id: int, parser: ExternalParserType,
                   account_id: int, project_id: int, config: dict) -> None:
    handle = base.get_handle(run_id)
    if handle is None:
        handle = base.register(run_id)
    writer = base.ResultWriter(run_id)
    client = None
    final_status = ExternalParserStatus.COMPLETED
    try:
        await base.set_status(run_id, ExternalParserStatus.RUNNING, started=True)

        from app.db.session import SessionLocal

        async with SessionLocal() as db:
            account = await base.load_account_with_proxy(db, account_id, project_id)
        if account is None:
            raise ValueError("аккаунт не найден или не принадлежит проекту")

        if parser == ExternalParserType.KEYWORDS:
            from app.services.external_parsers.keywords import run_keywords
            await run_keywords(account, config, writer, handle.stop_event)
            final_status = ExternalParserStatus.COMPLETED

        elif parser == ExternalParserType.MONITOR:
            client = await base.build_telethon_client(account)
            await _connect_authorized(client)
            handle.client = client
            from app.services.external_parsers.monitor import run_monitor
            await run_monitor(client, config, writer, handle.stop_event)
            final_status = ExternalParserStatus.STOPPED

        elif parser == ExternalParserType.ALERT_BOT:
            client = await base.build_telethon_client(account)
            await _connect_authorized(client)
            handle.client = client
            from app.services.external_parsers.alert_bot import run_alert_bot
            await run_alert_bot(client, config, writer, handle.stop_event)
            final_status = ExternalParserStatus.STOPPED

        else:
            raise ValueError(f"unknown parser type: {parser}")

        writer.close()
        await base.set_status(
            run_id, final_status, finished=True,
            result_count=writer.count,
            file_path=writer.path if writer.count else None,
        )
    except asyncio.CancelledError:
        writer.close()
        await base.set_status(
            run_id, ExternalParserStatus.STOPPED, finished=True,
            result_count=writer.count,
            file_path=writer.path if writer.count else None,
        )
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("external parser run %s failed", run_id)
        writer.close()
        await base.set_status(
            run_id, ExternalParserStatus.FAILED, finished=True,
            last_error=str(exc),
            result_count=writer.count,
            file_path=writer.path if writer.count else None,
        )
    finally:
        if client is not None:
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001
                pass
        base.unregister(run_id)


def start(run_id: int, parser: ExternalParserType, account_id: int,
          project_id: int, config: dict) -> None:
    """Register and launch a run as a background task."""
    handle = base.register(run_id)
    handle.task = asyncio.create_task(
        _execute(run_id, parser, account_id, project_id, config or {})
    )


async def stop(run_id: int) -> bool:
    """Signal a realtime run to stop. Returns True if it was running."""
    return await base.request_stop(run_id)
