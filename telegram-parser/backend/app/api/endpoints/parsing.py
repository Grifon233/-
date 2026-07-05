"""Parsing API endpoints."""
import asyncio
import csv
import os
from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.api.deps import get_project_id
from app.db.session import get_db
from app.models.account import Account
from app.models.contact import Contact
from app.models.parsing import ParsingTask as ParsingTaskModel
from app.schemas.parsing import ParsingTask, ParsingTaskCreate
from app.services.contact_service import _build_contact_create
from app.tasks.parsing import _run as _run_parsing

router = APIRouter()


@router.post("/{task_id}/import")
async def import_task_results(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
):
    """Import the CSV produced by a parsing task into the contacts table.

    Returns a structured report with imported / skipped / errors so the
    UI can show meaningful feedback.
    """
    result = await db.execute(
        select(ParsingTaskModel).where(
            ParsingTaskModel.id == task_id, ParsingTaskModel.project_id == project_id
        )
    )
    task = result.scalar_one_or_none()
    if not task or not task.file_path:
        raise HTTPException(status_code=404, detail="Results file not found")
    file_path = os.path.abspath(task.file_path)
    if not os.path.exists(file_path) or not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="Results file not found")

    # Peek at the header row up front so we can fail fast with a useful
    # 422 instead of crashing on a KeyError mid-import.
    with open(file_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return {
                "status": "success",
                "imported": 0,
                "skipped_duplicates": 0,
                "errors": [],
                "total_in_file": 0,
            }
        fieldnames = list(reader.fieldnames)
        # Mapping from CSV columns to ContactCreate fields. ``phone`` in
        # the parser output maps to ``phone_number`` here.
        rename_map = {"phone": "phone_number"}
        rows = []
        for row_index, raw in enumerate(reader, start=2):
            mapped = {rename_map.get(k, k): v for k, v in raw.items()}
            rows.append((row_index, mapped))

    new_rows: list[Contact] = []
    skipped = 0
    errors: list[dict[str, Any]] = []
    total_in_file = len(rows)

    from sqlalchemy import or_

    for row_index, mapped in rows:
        try:
            contact_in = _build_contact_create({**mapped, "_source": f"parsing_{task.id}"})
            if contact_in is None:
                skipped += 1
                continue

            # De-dupe per project.
            existing_query = select(Contact.id).where(
                Contact.project_id == project_id
            )
            conditions = []
            if contact_in.telegram_id:
                conditions.append(Contact.telegram_id == contact_in.telegram_id)
            if contact_in.username:
                conditions.append(Contact.username == contact_in.username)
            if contact_in.phone_number:
                conditions.append(Contact.phone_number == contact_in.phone_number)
            if not conditions:
                skipped += 1
                continue
            existing = await db.execute(
                existing_query.where(or_(*conditions)).limit(1)
            )
            if existing.scalar_one_or_none() is not None:
                skipped += 1
                continue

            new_rows.append(Contact(**contact_in.model_dump(), project_id=project_id))
        except Exception as e:  # noqa: BLE001
            errors.append({"row": row_index, "reason": str(e)[:200]})

    if new_rows:
        db.add_all(new_rows)
        await db.commit()

    return {
        "status": "success",
        "imported": len(new_rows),
        "skipped_duplicates": skipped,
        "errors": errors,
        "total_in_file": total_in_file,
        "csv_columns": fieldnames,
    }


@router.post("", response_model=ParsingTask, status_code=status.HTTP_201_CREATED)
async def create_parsing_task(
    task_in: ParsingTaskCreate,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    if task_in.account_id:
        account = await db.execute(
            select(Account.id).where(
                Account.id == task_in.account_id, Account.project_id == project_id
            )
        )
        if account.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=404, detail="Account not found in current project"
            )
    db_obj = ParsingTaskModel(**task_in.model_dump(), project_id=project_id)
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)

    asyncio.create_task(_run_parsing(db_obj.id))
    return db_obj


@router.get("", response_model=List[ParsingTask])
async def read_parsing_tasks(
    skip: int = 0,
    limit: int = 10000,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    result = await db.execute(
        select(ParsingTaskModel)
        .where(ParsingTaskModel.project_id == project_id)
        .order_by(ParsingTaskModel.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()


@router.get("/{task_id}", response_model=ParsingTask)
async def read_parsing_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    result = await db.execute(
        select(ParsingTaskModel).where(
            ParsingTaskModel.id == task_id, ParsingTaskModel.project_id == project_id
        )
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Parsing task not found")
    return task


@router.get("/{task_id}/results")
async def get_task_results(
    task_id: int,
    limit: int = 500,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    """Return the first `limit` rows from the parsing task CSV."""
    result = await db.execute(
        select(ParsingTaskModel).where(
            ParsingTaskModel.id == task_id, ParsingTaskModel.project_id == project_id
        )
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Parsing task not found")
    if not task.file_path:
        return {
            "rows": [],
            "total": 0,
            "search_stats": (task.params or {}).get("search_stats"),
        }
    file_path = os.path.abspath(task.file_path)
    if not os.path.exists(file_path):
        return {
            "rows": [],
            "total": 0,
            "search_stats": (task.params or {}).get("search_stats"),
        }
    rows = []
    with open(file_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if i >= limit:
                break
            rows.append(dict(row))
    return {
        "rows": rows,
        "total": task.result_count,
        "search_stats": (task.params or {}).get("search_stats"),
    }


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_parsing_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
):
    result = await db.execute(
        select(ParsingTaskModel).where(
            ParsingTaskModel.id == task_id, ParsingTaskModel.project_id == project_id
        )
    )
    db_obj = result.scalar_one_or_none()
    if not db_obj:
        raise HTTPException(status_code=404, detail="Parsing task not found")
    await db.delete(db_obj)
    await db.commit()
    return None
