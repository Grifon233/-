import logging
from typing import Any

from backend.database import ArchitectFunnelEvent, async_session_maker

logger = logging.getLogger(__name__)


async def record_funnel_event(
    event_type: str,
    telegram_id: int | None,
    master_bot_id: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Record Architect Bot funnel events without breaking user-facing flows."""
    if not telegram_id:
        return
    try:
        async with async_session_maker() as session:
            session.add(ArchitectFunnelEvent(
                event_type=event_type,
                telegram_id=int(telegram_id),
                master_bot_id=master_bot_id,
                metadata_json=metadata or {},
            ))
            await session.commit()
    except Exception as exc:
        logger.warning("Failed to record funnel event %s for %s: %s", event_type, telegram_id, exc)
