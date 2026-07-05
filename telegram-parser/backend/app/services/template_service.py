"""
Template Service
Управление шаблонами сообщений

Based on:
- VoxHash/Telegram-Multi-Account-Message-Sender (spintax parsing)
- Spintax patterns for message variation
"""

import re
import random
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.template import MessageTemplate
from app.schemas.template import TemplateCreate, TemplateUpdate

def parse_spintax(text: str) -> str:
    """
    Parses spintax like {Hello|Hi|Greetings} and picks a random choice.
    Supports nested spintax.
    """
    while True:
        match = re.search(r'\{([^{}]+)\}', text)
        if not match:
            break
        choices = match.group(1).split('|')
        text = text[:match.start()] + random.choice(choices) + text[match.end():]
    return text

async def create_template(db: AsyncSession, template_in: TemplateCreate, project_id: int = 1) -> MessageTemplate:
    db_obj = MessageTemplate(**template_in.model_dump(), project_id=project_id)
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj

async def get_templates(db: AsyncSession, skip: int = 0, limit: int = 100, project_id: int = 1) -> List[MessageTemplate]:
    result = await db.execute(select(MessageTemplate).where(MessageTemplate.project_id == project_id).offset(skip).limit(limit))
    return list(result.scalars().all())

async def get_template(db: AsyncSession, template_id: int, project_id: int = 1) -> Optional[MessageTemplate]:
    result = await db.execute(select(MessageTemplate).where(MessageTemplate.id == template_id, MessageTemplate.project_id == project_id))
    return result.scalar_one_or_none()

async def update_template(db: AsyncSession, template_id: int, template_in: TemplateUpdate, project_id: int = 1) -> Optional[MessageTemplate]:
    template = await get_template(db, template_id, project_id=project_id)
    if not template:
        return None
    update_data = template_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(template, field, value)
    await db.commit()
    await db.refresh(template)
    return template

async def delete_template(db: AsyncSession, template_id: int, project_id: int = 1) -> bool:
    template = await get_template(db, template_id, project_id=project_id)
    if not template:
        return False
    await db.delete(template)
    await db.commit()
    return True

def get_randomized_content(template: MessageTemplate, variables: dict = None) -> str:
    """
    Returns randomized content from template and replaces variables.
    Example variables: {'first_name': 'John'}
    """
    content = parse_spintax(template.content)
    if variables:
        for key, value in variables.items():
            content = content.replace(f"{{{key}}}", str(value) if value else "")
    return content
