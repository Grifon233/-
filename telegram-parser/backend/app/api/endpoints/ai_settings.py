"""
AI Settings API endpoints
Настройки нейро-функций: Диалоги, Чаттинг, Комментинг
"""

from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.db.session import get_db
from app.models.account import Account
from app.models.ai_settings import AISettings as AISettingsModel, AIType
from app.schemas.ai_settings import (
    AISettingsCreate,
    AISettingsUpdate,
    AISettingsResponse,
    PromptPreset,
    ConversationSummary,
)
from app.services.dialogs_service import (
    get_conversation_summary,
    clear_conversation,
    get_default_prompts,
)
from app.api.deps import get_project_id
from app.services.ai_provider_service import get_provider_catalog, get_provider_config

router = APIRouter()


@router.get("", response_model=List[AISettingsResponse])
async def list_ai_settings(
    db: AsyncSession = Depends(get_db),
    account_id: int = None,
    ai_type: AIType = None,
    project_id: int = Depends(get_project_id),
):
    """Get all AI settings."""
    from sqlalchemy.orm import selectinload
    query = select(AISettingsModel).where(AISettingsModel.project_id == project_id).options(selectinload(AISettingsModel.account))

    if account_id:
        query = query.where(AISettingsModel.account_id == account_id)

    if ai_type:
        query = query.where(AISettingsModel.type == ai_type)

    result = await db.execute(query)
    settings = result.scalars().all()

    responses = []
    for s in settings:
        account_name = s.account.phone_number if s.account else f"Account {s.account_id}"

        responses.append(AISettingsResponse(
            id=s.id,
            account_id=s.account_id,
            account_name=account_name,
            type=s.type,
            enabled=s.enabled,
            system_prompt=s.system_prompt,
            context_depth=s.context_depth,
            min_delay=s.min_delay,
            max_delay=s.max_delay,
            model=s.model,
            provider=s.provider,
            created_at=s.created_at,
        ))

    return responses


@router.post("/setup", response_model=AISettingsResponse)
async def create_or_update_ai_settings(
    settings_data: AISettingsCreate,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
):
    """Setup AI for an account (create or update)."""
    provider = get_provider_config(settings_data.provider)
    if settings_data.model not in provider["models"]:
        raise HTTPException(status_code=400, detail="Model is not supported by selected provider")
    # Check account exists
    result = await db.execute(select(Account).where(Account.id == settings_data.account_id, Account.project_id == project_id))
    account = result.scalar_one_or_none()

    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    # Check if settings already exist for this account+type
    existing = await db.execute(
        select(AISettingsModel).where(
            AISettingsModel.account_id == settings_data.account_id,
            AISettingsModel.type == settings_data.type,
            AISettingsModel.project_id == project_id,
        )
    )
    existing = existing.scalar_one_or_none()

    if existing:
        # Update
        existing.system_prompt = settings_data.system_prompt
        existing.context_depth = settings_data.context_depth
        existing.min_delay = settings_data.min_delay
        existing.max_delay = settings_data.max_delay
        existing.model = settings_data.model
        existing.provider = settings_data.provider
        existing.enabled = settings_data.enabled
        settings_obj = existing
    else:
        # Create
        settings_obj = AISettingsModel(
            account_id=settings_data.account_id,
            type=settings_data.type,
            system_prompt=settings_data.system_prompt,
            context_depth=settings_data.context_depth,
            min_delay=settings_data.min_delay,
            max_delay=settings_data.max_delay,
            model=settings_data.model,
            provider=settings_data.provider,
            enabled=settings_data.enabled,
            project_id=project_id,
        )
        db.add(settings_obj)

    await db.commit()
    await db.refresh(settings_obj)

    return AISettingsResponse(
        id=settings_obj.id,
        account_id=settings_obj.account_id,
        account_name=account.phone_number if account else f"Account {settings_obj.account_id}",
        type=settings_obj.type,
        enabled=settings_obj.enabled,
        system_prompt=settings_obj.system_prompt,
        context_depth=settings_obj.context_depth,
        min_delay=settings_obj.min_delay,
        max_delay=settings_obj.max_delay,
        model=settings_obj.model,
        provider=settings_obj.provider,
        created_at=settings_obj.created_at,
    )


@router.get("/prompts/presets", response_model=List[PromptPreset])
async def get_prompt_presets():
    """Get available prompt presets."""
    prompts = get_default_prompts()
    return [
        PromptPreset(id=key, name=key.capitalize(), prompt=value)
        for key, value in prompts.items()
    ]


@router.get("/providers/catalog")
async def list_ai_providers():
    return get_provider_catalog()


@router.get("/conversations/{conversation_key}", response_model=ConversationSummary)
async def get_conversation(
    conversation_key: str,
):
    """Get conversation summary."""
    summary = await get_conversation_summary(conversation_key)
    return ConversationSummary(
        conversation_key=conversation_key,
        message_count=summary["message_count"],
        messages=summary["messages"],
        is_active=summary["is_active"],
    )


@router.delete("/conversations/{conversation_key}")
async def clear_conversation_history(conversation_key: str):
    """Clear conversation history."""
    await clear_conversation(conversation_key)
    return {"status": "cleared", "conversation_key": conversation_key}


@router.get("/{settings_id}", response_model=AISettingsResponse)
async def get_ai_settings(
    settings_id: int,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
):
    """Get specific AI settings."""
    result = await db.execute(select(AISettingsModel).where(AISettingsModel.id == settings_id, AISettingsModel.project_id == project_id))
    settings = result.scalar_one_or_none()

    if not settings:
        raise HTTPException(status_code=404, detail="Settings not found")

    account = await db.execute(select(Account).where(Account.id == settings.account_id))
    account = account.scalar_one_or_none()

    return AISettingsResponse(
        id=settings.id,
        account_id=settings.account_id,
        account_name=account.phone_number if account else f"Account {settings.account_id}",
        type=settings.type,
        enabled=settings.enabled,
        system_prompt=settings.system_prompt,
        context_depth=settings.context_depth,
        min_delay=settings.min_delay,
        max_delay=settings.max_delay,
        model=settings.model,
        provider=settings.provider,
        created_at=settings.created_at,
    )


@router.patch("/{settings_id}", response_model=AISettingsResponse)
async def update_ai_settings(
    settings_id: int,
    update_data: AISettingsUpdate,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
):
    """Update AI settings."""
    result = await db.execute(select(AISettingsModel).where(AISettingsModel.id == settings_id, AISettingsModel.project_id == project_id))
    settings = result.scalar_one_or_none()

    if not settings:
        raise HTTPException(status_code=404, detail="Settings not found")

    update_dict = update_data.model_dump(exclude_unset=True)
    provider_id = update_dict.get("provider", settings.provider)
    provider = get_provider_config(provider_id)
    model = update_dict.get("model", settings.model)
    if model not in provider["models"]:
        raise HTTPException(status_code=400, detail="Model is not supported by selected provider")
    for field, value in update_dict.items():
        setattr(settings, field, value)

    await db.commit()
    await db.refresh(settings)

    account = await db.execute(select(Account).where(Account.id == settings.account_id))
    account = account.scalar_one_or_none()

    return AISettingsResponse(
        id=settings.id,
        account_id=settings.account_id,
        account_name=account.phone_number if account else f"Account {settings.account_id}",
        type=settings.type,
        enabled=settings.enabled,
        system_prompt=settings.system_prompt,
        context_depth=settings.context_depth,
        min_delay=settings.min_delay,
        max_delay=settings.max_delay,
        model=settings.model,
        provider=settings.provider,
        created_at=settings.created_at,
    )


@router.post("/{settings_id}/toggle")
async def toggle_ai_settings(
    settings_id: int,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
):
    """Toggle AI settings enabled/disabled."""
    result = await db.execute(select(AISettingsModel).where(AISettingsModel.id == settings_id, AISettingsModel.project_id == project_id))
    settings = result.scalar_one_or_none()

    if not settings:
        raise HTTPException(status_code=404, detail="Settings not found")

    settings.enabled = not settings.enabled
    await db.commit()

    return {"id": settings.id, "enabled": settings.enabled}


@router.delete("/{settings_id}")
async def delete_ai_settings(
    settings_id: int,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
):
    """Delete AI settings."""
    result = await db.execute(select(AISettingsModel).where(AISettingsModel.id == settings_id, AISettingsModel.project_id == project_id))
    settings = result.scalar_one_or_none()

    if not settings:
        raise HTTPException(status_code=404, detail="Settings not found")

    await db.delete(settings)
    await db.commit()

    return {"status": "deleted", "id": settings_id}
