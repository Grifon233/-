from typing import Any, List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, update

from app.db.session import get_db
from app.schemas.campaign import Campaign, CampaignCreate, CampaignUpdate, CampaignWithStats
from app.models.campaign import Campaign as CampaignModel
from app.models.campaign import MessageLog
from app.tasks.messaging import run_campaign
from app.api.deps import get_project_id
from app.models.template import MessageTemplate

router = APIRouter()

@router.post("", response_model=Campaign, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    campaign_in: CampaignCreate,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    template = await db.execute(
        select(MessageTemplate.id).where(
            MessageTemplate.id == campaign_in.template_id,
            MessageTemplate.project_id == project_id,
        )
    )
    if template.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Template not found in current project")
    db_obj = CampaignModel(**campaign_in.model_dump(), project_id=project_id)
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj

@router.get("", response_model=List[CampaignWithStats])
async def read_campaigns(
    skip: int = 0,
    limit: int = 10000,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    stmt = (
        select(
            CampaignModel,
            func.count(MessageLog.id).label("total"),
            func.count(MessageLog.id).filter(MessageLog.status == "sent").label("sent"),
            func.count(MessageLog.id).filter(MessageLog.status == "failed").label("failed")
        )
        .outerjoin(MessageLog, MessageLog.campaign_id == CampaignModel.id)
        .where(CampaignModel.project_id == project_id)
        .group_by(CampaignModel.id)
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.all()

    campaigns_with_stats = []
    for row in rows:
        c, total, sent, failed = row
        c_dict = CampaignWithStats.model_validate(c).model_dump()
        c_dict["sent_count"] = sent
        c_dict["failed_count"] = failed
        campaigns_with_stats.append(c_dict)

    return campaigns_with_stats

@router.get("/{campaign_id}", response_model=Campaign)
async def read_campaign(
    campaign_id: int,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    result = await db.execute(select(CampaignModel).where(CampaignModel.id == campaign_id, CampaignModel.project_id == project_id))
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign

@router.patch("/{campaign_id}", response_model=Campaign)
async def update_campaign(
    campaign_id: int,
    campaign_in: CampaignUpdate,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    result = await db.execute(select(CampaignModel).where(CampaignModel.id == campaign_id, CampaignModel.project_id == project_id))
    db_obj = result.scalar_one_or_none()
    if not db_obj:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign_in.template_id:
        template = await db.execute(
            select(MessageTemplate.id).where(
                MessageTemplate.id == campaign_in.template_id,
                MessageTemplate.project_id == project_id,
            )
        )
        if template.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Template not found in current project")
    
    update_data = campaign_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_obj, field, value)
    
    await db.commit()
    await db.refresh(db_obj)
    return db_obj

@router.delete("/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_campaign(
    campaign_id: int,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
):
    result = await db.execute(select(CampaignModel).where(CampaignModel.id == campaign_id, CampaignModel.project_id == project_id))
    db_obj = result.scalar_one_or_none()
    if not db_obj:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    await db.delete(db_obj)
    await db.commit()
    return None

@router.post("/{campaign_id}/start")
async def start_campaign(
    campaign_id: int,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
):
    result = await db.execute(
        update(CampaignModel)
        .where(
            CampaignModel.id == campaign_id,
            CampaignModel.project_id == project_id,
            CampaignModel.status != "running",
        )
        .values(status="running", started_at=func.now())
    )
    if result.rowcount == 0:
        exists = await db.execute(select(CampaignModel.id).where(CampaignModel.id == campaign_id, CampaignModel.project_id == project_id))
        if exists.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Campaign not found")
        raise HTTPException(status_code=409, detail="Campaign is already running")
    await db.commit()
    
    # Trigger Celery task
    run_campaign.delay(campaign_id)
    
    return {"status": "started"}

@router.post("/{campaign_id}/pause")
async def pause_campaign(
    campaign_id: int,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
):
    result = await db.execute(select(CampaignModel).where(CampaignModel.id == campaign_id, CampaignModel.project_id == project_id))
    db_obj = result.scalar_one_or_none()
    if not db_obj:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if db_obj.status != "running":
        raise HTTPException(status_code=400, detail="Campaign is not running")

    db_obj.status = "paused"
    await db.commit()
    return {"status": "paused"}
