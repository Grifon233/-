import logging
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi import HTTPException
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select

from backend.database import ArchitectFunnelEvent, UtmCampaign, async_session_maker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/utm", tags=["utm"])

_PIXEL_GIF = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!"
    b"\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01"
    b"\x00\x00\x02\x02D\x01\x00;"
)


@router.get("/organic-hit.gif")
async def organic_hit(request: Request):
    """Track direct/organic visits from the public site without CORS."""
    try:
        async with async_session_maker() as session:
            session.add(ArchitectFunnelEvent(
                event_type="utm_click",
                telegram_id=-1,
                metadata_json={
                    "source": "organic",
                    "path": request.query_params.get("path"),
                    "referrer": request.headers.get("referer"),
                },
                created_at=datetime.utcnow(),
            ))
            await session.commit()
    except Exception as e:
        logger.warning("Failed to record organic visit: %s", e)
    return Response(
        content=_PIXEL_GIF,
        media_type="image/gif",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


@router.get("/{source}")
async def utm_redirect(source: str):
    try:
        async with async_session_maker() as session:
            campaign = (await session.execute(
                select(UtmCampaign).where(
                    UtmCampaign.source == source,
                    UtmCampaign.active == True,
                )
            )).scalar_one_or_none()
            if not campaign:
                raise HTTPException(status_code=404)
            session.add(ArchitectFunnelEvent(
                event_type="utm_click",
                telegram_id=-1,
                metadata_json={"source": source},
                created_at=datetime.utcnow(),
            ))
            await session.commit()
            target = campaign.target_url
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Failed to record utm_click for %s: %s", source, e)
        raise HTTPException(status_code=404)
    return RedirectResponse(target, status_code=302)
