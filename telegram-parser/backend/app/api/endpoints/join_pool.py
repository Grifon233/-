"""API endpoints for the progressive channel-joining pool.

GET  /join-pool/status        — runner state
POST /join-pool/run           — trigger a join session manually
GET  /join-pool/coverage      — per-source coverage + orphan detection
POST /join-pool/distribute    — split global pool evenly across accounts
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from app.services import channel_joiner_runner, channel_joiner_service

router = APIRouter()


@router.get("/status")
async def get_status():
    return channel_joiner_runner.get_state()


@router.post("/run")
async def trigger_run(project_id: int = Query(1)):
    """Manually trigger one join session for all eligible accounts."""
    return channel_joiner_runner.start(project_id)


@router.get("/coverage")
async def get_coverage(project_id: int = Query(1)):
    """Return per-source join coverage and orphan report."""
    return await channel_joiner_service.get_pool_coverage(project_id)


@router.post("/distribute")
async def distribute_pool(
    project_id: int = Query(1),
    group_id: Optional[int] = Query(None, description="Source group to use; omit for all enabled sources"),
):
    """Split the source pool evenly across all eligible accounts.

    Resets join_session_count and joined_source_ids on every account so
    each account starts fresh with its new slice.
    """
    return await channel_joiner_service.distribute_pool(project_id, group_id)
