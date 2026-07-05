from typing import Any, List
from fastapi import APIRouter, Depends, HTTPException, status, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.template import MessageTemplate, TemplateCreate, TemplateUpdate
from app.services import template_service
from app.api.deps import get_project_id

router = APIRouter()

@router.post("", response_model=MessageTemplate, status_code=status.HTTP_201_CREATED)
async def create_template(
    template_in: TemplateCreate,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    return await template_service.create_template(db, template_in, project_id=project_id)

@router.get("", response_model=List[MessageTemplate])
async def read_templates(
    skip: int = 0,
    limit: int = 10000,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    return await template_service.get_templates(db, skip=skip, limit=limit, project_id=project_id)

@router.get("/{template_id}", response_model=MessageTemplate)
async def read_template(
    template_id: int,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    template = await template_service.get_template(db, template_id, project_id=project_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template

@router.put("/{template_id}", response_model=MessageTemplate)
async def update_template(
    template_id: int,
    template_in: TemplateUpdate,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    template = await template_service.update_template(db, template_id, template_in, project_id=project_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template

@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: int,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
):
    success = await template_service.delete_template(db, template_id, project_id=project_id)
    if not success:
        raise HTTPException(status_code=404, detail="Template not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
