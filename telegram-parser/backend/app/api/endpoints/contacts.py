"""Contact CRUD and bulk import endpoints."""
from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, File, status
from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.api.deps import get_project_id
from app.db.session import get_db
from app.models.contact import Contact as ContactModel, ContactGroup
from app.schemas.contact import (
    Contact,
    ContactBulkCreate,
    ContactBulkResponse,
    ContactGroupCreate,
    ContactGroupResponse,
    ContactGroupUpdate,
)
from app.services import contact_service

router = APIRouter()


@router.get("", response_model=List[Contact])
async def read_contacts(
    skip: int = 0,
    limit: int = 10000,
    group_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    return await contact_service.get_contacts(
        db, skip=skip, limit=limit, project_id=project_id, group_id=group_id
    )


@router.get("/groups", response_model=List[ContactGroupResponse])
async def list_contact_groups(
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    result = await db.execute(
        select(ContactGroup)
        .where(ContactGroup.project_id == project_id)
        .order_by(ContactGroup.created_at.desc())
    )
    return result.scalars().all()


@router.post("/groups", response_model=ContactGroupResponse, status_code=status.HTTP_201_CREATED)
async def create_contact_group(
    group_in: ContactGroupCreate,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    existing = await db.execute(
        select(ContactGroup.id).where(
            ContactGroup.project_id == project_id,
            ContactGroup.name == group_in.name.strip(),
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Contact group already exists")
    group = ContactGroup(
        project_id=project_id,
        name=group_in.name.strip(),
        description=group_in.description,
    )
    db.add(group)
    await db.commit()
    await db.refresh(group)
    return group


@router.patch("/groups/{group_id}", response_model=ContactGroupResponse)
async def update_contact_group(
    group_id: int,
    group_in: ContactGroupUpdate,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    result = await db.execute(
        select(ContactGroup).where(ContactGroup.id == group_id, ContactGroup.project_id == project_id)
    )
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="Contact group not found")
    data = group_in.model_dump(exclude_unset=True)
    if "name" in data and data["name"]:
        group.name = data["name"].strip()
    if "description" in data:
        group.description = data["description"]
    await db.commit()
    await db.refresh(group)
    return group


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contact_group(
    group_id: int,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
):
    result = await db.execute(
        select(ContactGroup).where(ContactGroup.id == group_id, ContactGroup.project_id == project_id)
    )
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="Contact group not found")
    await db.delete(group)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/bulk", response_model=ContactBulkResponse, status_code=status.HTTP_201_CREATED)
async def bulk_create_contacts(
    payload: ContactBulkCreate,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    if payload.group_id:
        group = await db.execute(
            select(ContactGroup.id).where(ContactGroup.id == payload.group_id, ContactGroup.project_id == project_id)
        )
        if not group.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Contact group not found")

    created = 0
    skipped = 0
    invalid: list[str] = []
    seen: set[tuple[str, str]] = set()
    for value in payload.values:
        contact_in = contact_service.build_contact_from_value(value, group_id=payload.group_id)
        if not contact_in:
            invalid.append(value)
            continue
        identifiers = []
        key = None
        if contact_in.telegram_id:
            identifiers.append(ContactModel.telegram_id == contact_in.telegram_id)
            key = ("telegram_id", contact_in.telegram_id)
        if contact_in.username:
            identifiers.append(ContactModel.username == contact_in.username)
            key = ("username", contact_in.username)
        if contact_in.phone_number:
            identifiers.append(ContactModel.phone_number == contact_in.phone_number)
            key = ("phone", contact_in.phone_number)
        if key and key in seen:
            skipped += 1
            continue
        if key:
            seen.add(key)
        exists = await db.execute(
            select(ContactModel.id)
            .where(ContactModel.project_id == project_id, or_(*identifiers))
            .limit(1)
        )
        if exists.scalar_one_or_none():
            skipped += 1
            continue
        db.add(ContactModel(**contact_in.model_dump(), project_id=project_id))
        created += 1
    await db.commit()
    return ContactBulkResponse(created=created, skipped=skipped, invalid=invalid)


@router.post("/upload-csv")
async def upload_contacts_csv(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    content = await file.read()
    try:
        report = await contact_service.bulk_upload_contacts_csv(
            db, content, project_id=project_id
        )
    except ValueError as e:
        # Header validation failed; surface a 422 with a clear message.
        raise HTTPException(status_code=422, detail=str(e))

    return {
        "status": "success",
        "format": "csv",
        **report,
    }


@router.post("/upload-excel")
async def upload_contacts_excel(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    content = await file.read()
    try:
        report = await contact_service.bulk_upload_contacts_excel(
            db, content, project_id=project_id
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {
        "status": "success",
        "format": "excel",
        **report,
    }


@router.delete("/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contact(
    contact_id: int,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
):
    if not await contact_service.delete_contact(db, contact_id, project_id=project_id):
        raise HTTPException(status_code=404, detail="Contact not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
