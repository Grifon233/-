import json
from typing import Any, Dict, Optional

from aiogram.fsm.storage.base import BaseStorage, StorageKey
from sqlalchemy.orm import Session
from bot.models.database import UserState, get_db

class SQLiteStorage(BaseStorage):
    """
    Persistent FSM storage using the existing SQLite database.
    """
    async def set_state(self, key: StorageKey, state: Optional[str] = None) -> None:
        with get_db() as db:
            user_state = self._get_or_create_state(db, key)
            user_state.state = state
            db.commit()

    async def get_state(self, key: StorageKey) -> Optional[str]:
        with get_db() as db:
            user_state = db.query(UserState).filter(UserState.telegram_id == key.user_id).first()
            return user_state.state if user_state else None

    async def set_data(self, key: StorageKey, data: Dict[str, Any]) -> None:
        with get_db() as db:
            user_state = self._get_or_create_state(db, key)
            user_state.data = data
            db.commit()

    async def get_data(self, key: StorageKey) -> Dict[str, Any]:
        with get_db() as db:
            user_state = db.query(UserState).filter(UserState.telegram_id == key.user_id).first()
            return user_state.data if user_state and user_state.data else {}

    async def close(self) -> None:
        pass

    def _get_or_create_state(self, db: Session, key: StorageKey) -> UserState:
        user_state = db.query(UserState).filter(UserState.telegram_id == key.user_id).first()
        if not user_state:
            user_state = UserState(
                telegram_id=key.user_id,
                chat_id=key.chat_id,
                bot_id=key.bot_id
            )
            db.add(user_state)
        return user_state
