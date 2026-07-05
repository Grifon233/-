"""
Analytics API endpoints
Статистика и отчеты
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.services.analytics_service import get_dashboard_stats
from app.api.deps import get_project_id

router = APIRouter()

@router.get("/dashboard")
async def dashboard_stats(db: AsyncSession = Depends(get_db), project_id: int = Depends(get_project_id)):
    """Get summarized stats for dashboard."""
    return await get_dashboard_stats(db, project_id=project_id)
