"""Phase-based warmup endpoints.

POST /phase-warmup/start   — initialize warmup for selected accounts
POST /phase-warmup/tick    — advance all accounts whose sleep period elapsed
GET  /phase-warmup/status  — current phase status for all accounts in warmup
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.api.deps import get_db
from app.models.account import Account
from app.services.warmup_phase_service import (
    get_tick_state,
    phase_status,
    start_tick_background,
    start_warmup,
)

router = APIRouter()


class StartWarmupRequest(BaseModel):
    account_ids: List[int]
    language: str = "ru"           # ru | en
    gender: str = "male"           # male | female
    pool_ids: List[int] = []       # source IDs; empty = use all project sources
    channel_template_id: Optional[int] = None   # optional


@router.post("/start")
async def start_phase_warmup(payload: StartWarmupRequest):
    """Initialize phase warmup for the given accounts."""
    return await start_warmup(
        account_ids=payload.account_ids,
        language=payload.language,
        gender=payload.gender,
        pool_ids=payload.pool_ids,
        channel_template_id=payload.channel_template_id,
    )


@router.post("/tick")
async def tick_phase_warmup():
    """Advance accounts whose sleep period has elapsed.

    Called by the frontend every 30 minutes and on page load.
    Also called automatically on server startup.
    """
    return {
        **start_tick_background(),
        "checked_at": datetime.utcnow().isoformat(),
    }


@router.get("/tick")
async def get_phase_warmup_tick():
    """Return current background tick status."""
    return get_tick_state()


@router.get("/status")
async def get_phase_warmup_status(db: AsyncSession = Depends(get_db)):
    """Return phase warmup status for all accounts currently in warmup."""
    result = await db.execute(
        select(Account)
        .where(Account.warmup_phase.isnot(None))
        .options(selectinload(Account.proxy))
    )
    accounts = result.scalars().all()
    return {"accounts": [phase_status(acc) for acc in accounts]}


@router.post("/cancel/{account_id}")
async def cancel_phase_warmup(account_id: int, db: AsyncSession = Depends(get_db)):
    """Cancel warmup for one account and unlock it."""
    account = await db.get(Account, account_id)
    if not account:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Account not found")
    account.warmup_phase = None
    account.warmup_next_phase_at = None
    account.warmup_locked = False
    await db.commit()
    return {"cancelled": True, "account_id": account_id}
