import copy
from typing import Any, Dict, Optional

from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, StorageKey, StateType

from bot.models.database import UserState, get_db


def _state_to_str(state: StateType = None) -> Optional[str]:
    if state is None:
        return None
    if isinstance(state, State):
        return state.state
    return str(state)


class SQLAlchemyFSMStorage(BaseStorage):
    """Small persistent FSM storage backed by the existing user_states table."""

    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        state_value = _state_to_str(state)
        with get_db() as db:
            row = db.query(UserState).filter(UserState.telegram_id == key.user_id).first()
            if not row:
                row = UserState(
                    telegram_id=key.user_id,
                    chat_id=key.chat_id,
                    bot_id=key.bot_id,
                    data={},
                )
                db.add(row)
            row.chat_id = key.chat_id
            row.bot_id = key.bot_id
            row.state = state_value
            if state_value is None:
                row.data = {}
            db.commit()

    async def get_state(self, key: StorageKey) -> Optional[str]:
        with get_db() as db:
            row = db.query(UserState).filter(UserState.telegram_id == key.user_id).first()
            return row.state if row else None

    async def set_data(self, key: StorageKey, data: Dict[str, Any]) -> None:
        with get_db() as db:
            row = db.query(UserState).filter(UserState.telegram_id == key.user_id).first()
            if not row:
                row = UserState(
                    telegram_id=key.user_id,
                    chat_id=key.chat_id,
                    bot_id=key.bot_id,
                    state=None,
                )
                db.add(row)
            row.chat_id = key.chat_id
            row.bot_id = key.bot_id
            row.data = copy.deepcopy(data)
            db.commit()

    async def get_data(self, key: StorageKey) -> Dict[str, Any]:
        with get_db() as db:
            row = db.query(UserState).filter(UserState.telegram_id == key.user_id).first()
            if not row or not row.data:
                return {}
            return copy.deepcopy(row.data)

    async def close(self) -> None:
        return None
