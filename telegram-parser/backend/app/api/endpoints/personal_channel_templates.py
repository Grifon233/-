"""Project-scoped personal channel templates."""
from __future__ import annotations

import base64
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from pyrogram import errors as pyrogram_errors
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_project_id
from app.db.session import SessionLocal, get_db

logger = logging.getLogger(__name__)
from app.models.account import Account as AccountModel
from app.models.personal_channel_template import (
    PersonalChannelTemplate,
    PersonalChannelTemplatePost,
)
from app.services import account_service, profile_service

router = APIRouter()

MEDIA_DIR = Path("var/personal_channel_templates")
MEDIA_DIR.mkdir(parents=True, exist_ok=True)


class TemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    channel_title: Optional[str] = Field(default=None, max_length=128)
    channel_about: Optional[str] = Field(default=None, max_length=255)


class TemplateUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    channel_title: Optional[str] = Field(default=None, min_length=1, max_length=128)
    channel_about: Optional[str] = Field(default=None, max_length=255)
    channel_avatar_mode: Optional[str] = Field(default=None, pattern="^(none|template|profile)$")


class ApplyTemplateRequest(BaseModel):
    account_ids: list[int] = Field(..., min_length=1)
    create_if_missing: bool = True


class ReorderPostsRequest(BaseModel):
    # Post ids in the desired DISPLAY order (first = position 1 = the post
    # a visitor sees first on entering the channel).
    post_ids: list[int] = Field(..., min_length=1)


@router.get("")
async def list_templates(
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    result = await db.execute(
        select(PersonalChannelTemplate)
        .where(PersonalChannelTemplate.project_id == project_id)
        .options(selectinload(PersonalChannelTemplate.posts))
        .order_by(PersonalChannelTemplate.updated_at.desc(), PersonalChannelTemplate.id.desc())
    )
    return [_template_dict(item, include_image_data=False) for item in result.scalars().all()]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_template(
    payload: TemplateCreate,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    obj = PersonalChannelTemplate(
        project_id=project_id,
        name=payload.name.strip(),
        channel_title=(payload.channel_title or payload.name).strip(),
        channel_about=(payload.channel_about or "").strip() or None,
    )
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return _template_dict(obj, include_image_data=False)


@router.get("/{template_id}")
async def get_template(
    template_id: int,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    obj = await _get_template(db, template_id, project_id)
    return _template_dict(obj, include_image_data=True)


@router.put("/{template_id}")
async def update_template(
    template_id: int,
    payload: TemplateUpdate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    obj = await _get_template(db, template_id, project_id)
    if payload.name is not None:
        obj.name = payload.name.strip()
    if payload.channel_title is not None:
        obj.channel_title = payload.channel_title.strip()
    if payload.channel_about is not None:
        obj.channel_about = payload.channel_about.strip() or None
    if payload.channel_avatar_mode is not None:
        obj.channel_avatar_mode = payload.channel_avatar_mode
    obj.updated_at = datetime.utcnow()
    await db.commit()
    # Note: propagation to bound accounts is triggered explicitly via the
    # ``/sync`` endpoint AFTER the frontend has finished saving posts too,
    # so the resync uses the FINAL template state (not the half-saved one
    # that exists right after this metadata PUT).
    return _template_dict(obj, include_image_data=True)


@router.post("/{template_id}/avatar")
async def upsert_avatar(
    template_id: int,
    mode: str = Form(default="template", pattern="^(none|template|profile)$"),
    image: Optional[UploadFile] = File(default=None),
    clear_avatar: bool = Form(default=False),
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    template = await _get_template(db, template_id, project_id)
    template.channel_avatar_mode = mode

    if clear_avatar or mode in {"none", "profile"}:
        if template.channel_avatar_path:
            _delete_file(template.channel_avatar_path)
        template.channel_avatar_path = None
        template.channel_avatar_filename = None
        template.channel_avatar_mime_type = None

    if mode == "template":
        if image is not None:
            blob = await image.read()
            if not blob:
                raise HTTPException(status_code=400, detail="empty avatar")
            if len(blob) > 10 * 1024 * 1024:
                raise HTTPException(status_code=400, detail="avatar larger than 10 MB")
            suffix = Path(image.filename or "avatar.jpg").suffix.lower()
            if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
                raise HTTPException(status_code=400, detail="Поддерживаются jpg/png/webp")
            folder = MEDIA_DIR / str(template.id)
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / f"channel_avatar_{int(datetime.utcnow().timestamp())}{suffix}"
            target.write_bytes(blob)
            if template.channel_avatar_path:
                _delete_file(template.channel_avatar_path)
            template.channel_avatar_path = str(target)
            template.channel_avatar_filename = image.filename
            template.channel_avatar_mime_type = image.content_type or "image/jpeg"
        elif not template.channel_avatar_path:
            raise HTTPException(status_code=400, detail="Загрузите аватарку или выберите режим “как у профиля”")

    template.updated_at = datetime.utcnow()
    await db.commit()
    obj = await _get_template(db, template_id, project_id)
    return _template_dict(obj, include_image_data=True)


@router.delete("/{template_id}")
async def delete_template(
    template_id: int,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    obj = await _get_template(db, template_id, project_id)
    media_path = MEDIA_DIR / str(obj.id)
    await db.delete(obj)
    await db.commit()
    shutil.rmtree(media_path, ignore_errors=True)
    return {"status": "ok"}


@router.post("/{template_id}/posts", status_code=status.HTTP_201_CREATED)
async def upsert_post(
    template_id: int,
    post_id: Optional[int] = Form(default=None),
    position: int = Form(..., ge=1, le=100),
    text: Optional[str] = Form(default=None, max_length=4096),
    image: Optional[UploadFile] = File(default=None),
    clear_image: bool = Form(default=False),
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    template = await _get_template(db, template_id, project_id)
    post = None
    if post_id:
        post = next((item for item in template.posts if item.id == post_id), None)
        if post is None:
            raise HTTPException(status_code=404, detail="Post not found")
    if post is None:
        post = PersonalChannelTemplatePost(template_id=template.id)
        db.add(post)

    clean_text = (text or "").strip()
    if not clean_text and image is None and not clear_image and not post.image_path:
        raise HTTPException(status_code=400, detail="Пост должен содержать текст или картинку")

    post.position = position
    post.text = clean_text or None
    if clear_image and post.image_path:
        _delete_file(post.image_path)
        post.image_path = None
        post.image_filename = None
        post.image_mime_type = None

    if image is not None:
        blob = await image.read()
        if not blob:
            raise HTTPException(status_code=400, detail="empty image")
        if len(blob) > 10 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="image larger than 10 MB")
        suffix = Path(image.filename or "image.jpg").suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
            raise HTTPException(status_code=400, detail="Поддерживаются jpg/png/webp")
        folder = MEDIA_DIR / str(template.id)
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"post_{position}_{int(datetime.utcnow().timestamp())}{suffix}"
        target.write_bytes(blob)
        if post.image_path:
            _delete_file(post.image_path)
        post.image_path = str(target)
        post.image_filename = image.filename
        post.image_mime_type = image.content_type or "image/jpeg"

    post.updated_at = datetime.utcnow()
    template.updated_at = datetime.utcnow()
    await db.commit()
    obj = await _get_template(db, template_id, project_id)
    return _template_dict(obj, include_image_data=True)


@router.delete("/{template_id}/posts/{post_id}")
async def delete_post(
    template_id: int,
    post_id: int,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    template = await _get_template(db, template_id, project_id)
    post = next((item for item in template.posts if item.id == post_id), None)
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")
    if post.image_path:
        _delete_file(post.image_path)
    await db.delete(post)
    template.updated_at = datetime.utcnow()
    await db.commit()
    return {"status": "ok"}


@router.post("/{template_id}/posts/reorder")
async def reorder_posts(
    template_id: int,
    payload: ReorderPostsRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    """Reassign post positions from a desired display order (first id = 1).

    Lets the operator swap posts around (e.g. make a later post the first
    one a visitor sees). The change is pushed to bound accounts in the
    background, idempotently (no duplicates)."""
    template = await _get_template(db, template_id, project_id)
    by_id = {post.id: post for post in template.posts}
    unknown = [pid for pid in payload.post_ids if pid not in by_id]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown post ids: {unknown}")
    for index, pid in enumerate(payload.post_ids, start=1):
        by_id[pid].position = index
    # Any posts not listed keep going after the listed ones, preserving
    # their relative order.
    tail = sorted(
        (p for p in template.posts if p.id not in set(payload.post_ids)),
        key=lambda p: p.position,
    )
    for offset, post in enumerate(tail, start=len(payload.post_ids) + 1):
        post.position = offset
    template.updated_at = datetime.utcnow()
    await db.commit()
    obj = await _get_template(db, template_id, project_id)
    return _template_dict(obj, include_image_data=True)


@router.post("/{template_id}/apply-avatar")
async def apply_avatar_to_bound_accounts(
    template_id: int,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    """Set the personal-channel avatar for every account bound to this template.

    Unlike the full sync/rebuild, this only touches the avatar — no post
    wipe/repost.  Runs synchronously so the caller gets per-account results
    immediately (useful for diagnosing why an avatar isn't updating).
    """
    template = await _get_template(db, template_id, project_id)
    if template.channel_avatar_mode == "none":
        return {"bound_accounts": 0, "ok": 0, "results": [], "info": "avatar mode is none — nothing to apply"}

    accounts = (
        await db.execute(
            select(AccountModel)
            .options(selectinload(AccountModel.proxy))
            .where(
                AccountModel.personal_channel_template_id == template_id,
                AccountModel.project_id == project_id,
            )
        )
    ).scalars().all()

    results: list[dict] = []
    for account in accounts:
        row: dict[str, Any] = {
            "account_id": account.id,
            "phone": account.phone_number,
            "status": "skipped",
            "reason": None,
        }
        try:
            if not account.personal_channel_id:
                row["status"] = "no_channel"
                row["reason"] = "нет личного канала — сначала создайте канал"
                results.append(row)
                continue
            account_service.assert_proxy_bound(account)
            if template.channel_avatar_mode == "profile":
                await profile_service.set_personal_channel_avatar(db, account, use_profile_avatar=True)
            elif template.channel_avatar_mode == "template" and template.channel_avatar_path:
                await profile_service.set_personal_channel_avatar(
                    db, account, image_path=template.channel_avatar_path
                )
            else:
                row["status"] = "skipped"
                row["reason"] = "нет файла аватарки в шаблоне"
                results.append(row)
                continue
            row["status"] = "ok"
        except Exception as exc:  # noqa: BLE001
            logger.warning("apply-avatar failed for account %s: %s", account.id, exc)
            row["status"] = "error"
            row["reason"] = str(exc)[:150]
        results.append(row)

    ok = sum(1 for r in results if r["status"] == "ok")
    return {
        "bound_accounts": len(accounts),
        "ok": ok,
        "results": results,
    }


@router.post("/{template_id}/apply")
async def apply_template(
    template_id: int,
    payload: ApplyTemplateRequest,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    template = await _get_template(db, template_id, project_id)
    result = await db.execute(
        select(AccountModel)
        .where(
            AccountModel.project_id == project_id,
            AccountModel.id.in_(payload.account_ids),
        )
        .options(selectinload(AccountModel.proxy))
    )
    accounts = list(result.scalars().all())
    if not accounts:
        raise HTTPException(status_code=404, detail="No target accounts found")

    rows = []
    for account in accounts:
        row = {
            "account_id": account.id,
            "phone_number": account.phone_number,
            "status": "skipped",
            "created_channel": False,
            "posted": 0,
            "reason": None,
        }
        try:
            account_service.assert_proxy_bound(account)
            if not account.personal_channel_id and not payload.create_if_missing:
                row["reason"] = "personal channel is missing"
                rows.append(row)
                continue

            # IDEMPOTENT apply: wipe the channel and re-post exactly the
            # template content. This is what stops duplicates when the same
            # template is applied twice OR when the operator switches the
            # account to a different template (old posts are removed, new
            # ones substituted). Posts go up in reverse position order so
            # post #1 ends up newest (seen first on entering the channel).
            result_info = await profile_service.rebuild_personal_channel_from_template(
                db,
                account,
                template,
                avatar=template.channel_avatar_mode or "none",
            )
            row["created_channel"] = result_info["created"]
            row["channel_id"] = result_info["channel_id"]
            row["channel_username"] = result_info["channel_username"]
            row["posted"] = result_info["posted"]
            row["status"] = "applied"

            # Bind the template to the account so the UI can show it as
            # applied (no "Без шаблона" ambiguity) and a future template
            # edit can auto-resync this account.
            account.personal_channel_template_id = template.id
            await db.commit()
        except pyrogram_errors.FloodWait as exc:
            row["status"] = "failed"
            row["reason"] = f"Telegram просит подождать {exc.value} сек. Повторите позже."
        except Exception as exc:
            row["status"] = "failed"
            row["reason"] = str(exc)
        rows.append(row)
    return {
        "applied": sum(1 for row in rows if row["status"] == "applied"),
        "results": rows,
    }


async def resync_template_to_bound_accounts(template_id: int, project_id: int) -> dict:
    """Idempotently re-apply a template to EVERY account bound to it.

    Powers both the explicit ``/sync`` endpoint and the automatic resync
    that runs after a template edit, so "обновил шаблон → подтянулось в
    аккаунты" holds. Uses the same wipe-and-repost rebuild as apply, so it
    never produces duplicates.
    """
    async with SessionLocal() as db:
        template = (
            await db.execute(
                select(PersonalChannelTemplate)
                .options(selectinload(PersonalChannelTemplate.posts))
                .where(
                    PersonalChannelTemplate.id == template_id,
                    PersonalChannelTemplate.project_id == project_id,
                )
            )
        ).scalar_one_or_none()
        if template is None:
            return {"synced": 0, "results": []}
        accounts = (
            await db.execute(
                select(AccountModel)
                .options(selectinload(AccountModel.proxy))
                .where(
                    AccountModel.personal_channel_template_id == template_id,
                    AccountModel.project_id == project_id,
                )
            )
        ).scalars().all()
        results = []
        for account in accounts:
            row = {"account_id": account.id, "phone_number": account.phone_number,
                   "status": "skipped", "posted": 0, "reason": None}
            try:
                account_service.assert_proxy_bound(account)
                info = await profile_service.rebuild_personal_channel_from_template(
                    db, account, template, avatar=template.channel_avatar_mode or "none",
                )
                row["status"] = "synced"
                row["posted"] = info["posted"]
            except Exception as exc:  # noqa: BLE001
                logger.warning("resync failed for account %s: %s", account.id, exc)
                row["status"] = "failed"
                row["reason"] = str(exc)
            results.append(row)
        return {
            "synced": sum(1 for r in results if r["status"] == "synced"),
            "results": results,
        }


@router.post("/{template_id}/sync")
async def sync_template(
    template_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    """Push this template's current content to every account using it.

    Runs in the background (wipe-and-repost is idempotent, so no
    duplicates) and returns immediately so the Save button stays snappy.
    """
    template = await _get_template(db, template_id, project_id)
    bound = await db.execute(
        select(AccountModel.id).where(
            AccountModel.personal_channel_template_id == template_id,
            AccountModel.project_id == project_id,
        )
    )
    bound_count = len(bound.scalars().all())
    background_tasks.add_task(resync_template_to_bound_accounts, template_id, project_id)
    return {"status": "syncing", "template_id": template_id, "bound_accounts": bound_count}


async def _get_template(
    db: AsyncSession,
    template_id: int,
    project_id: int,
) -> PersonalChannelTemplate:
    result = await db.execute(
        select(PersonalChannelTemplate)
        .where(
            PersonalChannelTemplate.id == template_id,
            PersonalChannelTemplate.project_id == project_id,
        )
        .options(selectinload(PersonalChannelTemplate.posts))
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Template not found")
    return obj


def _template_dict(obj: PersonalChannelTemplate, *, include_image_data: bool) -> dict:
    return {
        "id": obj.id,
        "project_id": obj.project_id,
        "name": obj.name,
        "channel_title": obj.channel_title,
        "channel_about": obj.channel_about,
        "channel_avatar_mode": obj.channel_avatar_mode or "none",
        "channel_avatar_filename": obj.channel_avatar_filename,
        "channel_avatar_mime_type": obj.channel_avatar_mime_type,
        "channel_avatar_base64": _image_base64(obj.channel_avatar_path, include_image_data),
        "created_at": obj.created_at.isoformat() if obj.created_at else None,
        "updated_at": obj.updated_at.isoformat() if obj.updated_at else None,
        "posts": [_post_dict(post, include_image_data=include_image_data) for post in sorted(obj.posts, key=lambda item: item.position)],
    }


def _post_dict(post: PersonalChannelTemplatePost, *, include_image_data: bool) -> dict:
    return {
        "id": post.id,
        "position": post.position,
        "text": post.text or "",
        "image_filename": post.image_filename,
        "image_mime_type": post.image_mime_type,
        "image_base64": _image_base64(post.image_path, include_image_data),
    }


def _image_base64(path: Optional[str], include_image_data: bool) -> Optional[str]:
    if include_image_data and path and Path(path).exists():
        return base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return None


def _delete_file(path: str) -> None:
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass
