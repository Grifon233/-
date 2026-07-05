"""External-parser API endpoints.

One set of endpoints serves all three parsers (the ``parser`` field on
the run distinguishes them). The frontend renders one tab per parser
and filters runs by ``?parser=``.
"""
import csv
import os
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.api.deps import get_project_id
from app.db.session import get_db
from app.models.account import Account
from app.models.external_parser import (
    ExternalParserRun as ExternalParserRunModel,
    ExternalParserStatus,
    ExternalParserType,
)
from app.schemas.external_parser import ExternalParserRun, ExternalParserRunCreate
from app.services.external_parsers import base
from app.services.external_parsers import runner

router = APIRouter()

# Realtime parsers run until stopped; KEYWORDS is one-shot.
_REALTIME = {ExternalParserType.MONITOR, ExternalParserType.ALERT_BOT}


def _delete_result_file(file_path: Optional[str]) -> None:
    if not file_path:
        return
    try:
        export_root = os.path.abspath(base.EXPORT_DIR)
        target = os.path.abspath(file_path)
        if os.path.commonpath([export_root, target]) != export_root:
            return
        if os.path.exists(target):
            os.remove(target)
    except OSError:
        return


@router.post("", response_model=ExternalParserRun, status_code=status.HTTP_201_CREATED)
async def create_run(
    run_in: ExternalParserRunCreate,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    if not run_in.account_id:
        raise HTTPException(
            status_code=400,
            detail="account_id обязателен: парсеру нужен авторизованный аккаунт",
        )
    account = (
        await db.execute(
            select(Account).where(
                Account.id == run_in.account_id, Account.project_id == project_id
            )
        )
    ).scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=404, detail="Аккаунт не найден в проекте")
    if not account.session_string:
        raise HTTPException(
            status_code=400,
            detail="Аккаунт не авторизован (нет сессии) — пройдите авторизацию",
        )
    if account.proxy_id is None:
        raise HTTPException(
            status_code=400,
            detail="К аккаунту не привязан прокси — подключаться без прокси нельзя",
        )

    db_obj = ExternalParserRunModel(
        parser=run_in.parser,
        account_id=run_in.account_id,
        config=run_in.config or {},
        project_id=project_id,
        status=ExternalParserStatus.PENDING,
    )
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)

    runner.start(
        db_obj.id, run_in.parser, run_in.account_id, project_id, run_in.config or {}
    )
    return db_obj


@router.get("", response_model=List[ExternalParserRun])
async def list_runs(
    parser: Optional[ExternalParserType] = None,
    skip: int = 0,
    limit: int = 200,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    query = select(ExternalParserRunModel).where(
        ExternalParserRunModel.project_id == project_id
    )
    if parser is not None:
        query = query.where(ExternalParserRunModel.parser == parser)
    query = query.order_by(ExternalParserRunModel.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{run_id}", response_model=ExternalParserRun)
async def get_run(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    run = (
        await db.execute(
            select(ExternalParserRunModel).where(
                ExternalParserRunModel.id == run_id,
                ExternalParserRunModel.project_id == project_id,
            )
        )
    ).scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Запуск не найден")
    return run


@router.post("/{run_id}/stop", response_model=ExternalParserRun)
async def stop_run(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    run = (
        await db.execute(
            select(ExternalParserRunModel).where(
                ExternalParserRunModel.id == run_id,
                ExternalParserRunModel.project_id == project_id,
            )
        )
    ).scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Запуск не найден")
    await runner.stop(run_id)
    await db.refresh(run)
    return run


@router.get("/{run_id}/results")
async def get_run_results(
    run_id: int,
    limit: int = 1000,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    run = (
        await db.execute(
            select(ExternalParserRunModel).where(
                ExternalParserRunModel.id == run_id,
                ExternalParserRunModel.project_id == project_id,
            )
        )
    ).scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Запуск не найден")
    if not run.file_path or not os.path.exists(run.file_path):
        return {"rows": [], "total": run.result_count or 0}
    rows = []
    with open(run.file_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if i >= limit:
                break
            rows.append(dict(row))
    return {"rows": rows, "total": run.result_count or 0}


@router.delete("/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_run(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
):
    run = (
        await db.execute(
            select(ExternalParserRunModel).where(
                ExternalParserRunModel.id == run_id,
                ExternalParserRunModel.project_id == project_id,
            )
        )
    ).scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Запуск не найден")
    # Stop it first if it's a live run.
    await runner.stop(run_id)
    _delete_result_file(run.file_path)
    await db.delete(run)
    await db.commit()
    return None
