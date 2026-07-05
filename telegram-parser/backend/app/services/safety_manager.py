import asyncio
import random
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import and_, func

from app.models.safety import (
    SourceAllowlist, AccountActionLimit, SafetyDraft, ActionLog,
    SourceType, DraftStatus
)
from app.models.account import Account

logger = logging.getLogger(__name__)

# Anti-ban задержки (секунды)
DELAYS = {
    "dm": (60, 180),
    "comment": (30, 120),
    "reaction": (3, 10),
    "join": (30, 60),
    "typing": (5, 15),
}

# Дневные лимиты по умолчанию
DEFAULT_LIMITS = {
    "dm": 50,
    "comment": 30,
    "reaction": 100,
    "join": 5,
}


class SafetyManager:
    """Единая точка проверок безопасности."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def check_allowlist(
        self,
        source_id: str,
        source_type: SourceType = SourceType.CHANNEL,
        project_id: int = 1
    ) -> bool:
        """Проверка, что источник в allowlist."""
        result = await self.db.execute(
            select(SourceAllowlist).where(
                and_(
                    SourceAllowlist.source_id == source_id,
                    SourceAllowlist.source_type == source_type,
                    SourceAllowlist.project_id == project_id,
                    SourceAllowlist.consent_verified == True,
                )
            )
        )
        source = result.scalar_one_or_none()

        if not source:
            return False

        # Проверка срока consent
        if source.consent_expires_at and source.consent_expires_at < datetime.utcnow():
            return False

        return True

    async def check_rate_limit(
        self,
        account_id: int,
        action_type: str
    ) -> Dict:
        """Проверка rate limit для аккаунта."""
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        limit = DEFAULT_LIMITS.get(action_type, 50)

        result = await self.db.execute(
            select(AccountActionLimit).where(
                and_(
                    AccountActionLimit.account_id == account_id,
                    AccountActionLimit.date >= today,
                )
            )
        )
        record = result.scalar_one_or_none()

        if not record:
            return {
                "allowed": True,
                "remaining": limit,
                "ttl": 86400,
                "current": 0,
                "limit": limit,
            }

        count = getattr(record, f"{action_type}_count", 0)
        remaining = max(0, limit - count)

        # TTL до конца дня
        tomorrow = today + timedelta(days=1)
        ttl = int((tomorrow - datetime.utcnow()).total_seconds())

        return {
            "allowed": remaining > 0,
            "remaining": remaining,
            "ttl": ttl,
            "current": count,
            "limit": limit,
        }

    async def increment_counter(self, account_id: int, action_type: str) -> None:
        """Увеличить счётчик действия."""
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

        result = await self.db.execute(
            select(AccountActionLimit).where(
                and_(
                    AccountActionLimit.account_id == account_id,
                    AccountActionLimit.date >= today,
                )
            )
        )
        record = result.scalar_one_or_none()

        if not record:
            record = AccountActionLimit(
                account_id=account_id,
                date=today,
            )
            self.db.add(record)

        counter_field = f"{action_type}_count"
        current = getattr(record, counter_field, 0)
        setattr(record, counter_field, current + 1)
        record.last_action_at = datetime.utcnow()

        await self.db.commit()

    async def apply_anti_ban_delay(self, action_type: str) -> None:
        """Применить случайную задержку перед действием."""
        min_delay, max_delay = DELAYS.get(action_type, (30, 120))
        delay = random.randint(min_delay, max_delay)
        logger.debug(f"Anti-ban delay: {delay}s for {action_type}")
        await asyncio.sleep(delay)

    async def moderate_draft(self, text: str) -> Dict:
        """Проверка текста через OpenAI Moderation API."""
        # Заглушка - требует интеграции с OpenAI
        return {
            "approved": True,
            "flags": [],
        }

    async def create_draft(
        self,
        project_id: int,
        account_id: int,
        source_id: str,
        post_id: int,
        context: str,
        draft: str,
        prompt_version: str = None,
        model_used: str = None,
    ) -> SafetyDraft:
        """Создать черновик комментария."""
        moderation = await self.moderate_draft(draft)

        db_draft = SafetyDraft(
            project_id=project_id,
            account_id=account_id,
            source_id=source_id,
            post_id=post_id,
            context=context,
            draft=draft,
            status=DraftStatus.PENDING,
            moderation_result=moderation,
            prompt_version=prompt_version,
            model_used=model_used,
        )

        self.db.add(db_draft)
        await self.db.commit()
        await self.db.refresh(db_draft)

        return db_draft

    async def approve_draft(
        self,
        draft_id: int,
        approved_by: str = "system",
        edited_draft: str = None
    ) -> SafetyDraft:
        """Одобрить черновик."""
        result = await self.db.execute(
            select(SafetyDraft).where(SafetyDraft.id == draft_id)
        )
        draft = result.scalar_one_or_none()

        if not draft:
            raise ValueError(f"Draft {draft_id} not found")

        if edited_draft:
            draft.draft = edited_draft
            moderation = await self.moderate_draft(edited_draft)
            draft.moderation_result = moderation
            if not moderation.get("approved", True):
                raise ValueError("Edited draft failed moderation")

        draft.status = DraftStatus.APPROVED
        draft.approved_by = approved_by
        draft.approved_at = datetime.utcnow()

        await self.db.commit()
        await self.db.refresh(draft)

        return draft

    async def reject_draft(self, draft_id: int, rejected_by: str = "system") -> SafetyDraft:
        """Отклонить черновик."""
        result = await self.db.execute(
            select(SafetyDraft).where(SafetyDraft.id == draft_id)
        )
        draft = result.scalar_one_or_none()

        if not draft:
            raise ValueError(f"Draft {draft_id} not found")

        draft.status = DraftStatus.REJECTED
        draft.approved_by = None
        draft.approved_at = None

        await self.db.commit()
        await self.db.refresh(draft)

        return draft

    async def log_action(
        self,
        project_id: int,
        action_type: str,
        account_id: int = None,
        source_id: str = None,
        source_type: str = None,
        result: str = "success",
        error: str = None,
        metadata: dict = None,
    ) -> ActionLog:
        """Логировать действие."""
        log = ActionLog(
            project_id=project_id,
            account_id=account_id,
            action_type=action_type,
            source_id=source_id,
            source_type=source_type,
            result=result,
            error=error,
            extra_data=metadata,
        )

        self.db.add(log)
        await self.db.commit()
        await self.db.refresh(log)

        return log

    async def add_source(
        self,
        project_id: int,
        source_type: SourceType,
        source_id: str,
        source_title: str = None,
        consent_verified: bool = False,
    ) -> SourceAllowlist:
        """Добавить источник в allowlist."""
        result = await self.db.execute(
            select(SourceAllowlist).where(
                and_(
                    SourceAllowlist.source_id == source_id,
                    SourceAllowlist.project_id == project_id,
                )
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            return existing

        source = SourceAllowlist(
            project_id=project_id,
            source_type=source_type,
            source_id=source_id,
            source_title=source_title,
            consent_verified=consent_verified,
        )

        self.db.add(source)
        await self.db.commit()
        await self.db.refresh(source)

        return source

    async def verify_consent(
        self,
        source_id: int,
        expires_in_days: int = 365,
    ) -> SourceAllowlist:
        """Подтвердить consent для источника."""
        result = await self.db.execute(
            select(SourceAllowlist).where(SourceAllowlist.id == source_id)
        )
        source = result.scalar_one_or_none()

        if not source:
            raise ValueError(f"Source {source_id} not found")

        source.consent_verified = True
        source.consent_expires_at = datetime.utcnow() + timedelta(days=expires_in_days)

        await self.db.commit()
        await self.db.refresh(source)

        return source


def get_safety_manager(db: AsyncSession) -> SafetyManager:
    """Получить SafetyManager для сессии."""
    return SafetyManager(db)
