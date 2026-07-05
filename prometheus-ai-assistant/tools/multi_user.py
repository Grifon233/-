"""Multi-user allowlist for the Telegram gateway.

Each Prometheus instance is owned by one Telegram user (the one whose
``HERMES_TELEGRAM_BOT_TOKEN`` belongs to the bot) but the owner can
authorize additional Telegram user_ids to also use the same bot. State
is persisted in ``HERMES_HOME/multi_user.json`` so it survives gateway
restarts.

Design notes:
  * ``owner_user_id`` is set at first run (from the first authorized
    user) and is immutable until ``/transferowner`` is invoked.
  * The owner is always authorized, even if their user_id is removed
    from ``authorized_users`` (defense against self-lockout).
  * The owner is the only one who can ``/adduser`` or ``/removeuser``.
    Removing the owner is a no-op (returns error in the gateway).
  * All mutations are thread-safe (``threading.RLock``) because the
    gateway may receive messages from multiple adapters concurrently.

This module is the source of truth for "is this Telegram user allowed
to talk to this bot?". The gateway's existing pairing/auth flow falls
back to it after the pairing handshake completes.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional

logger = logging.getLogger(__name__)


# --- Data model -------------------------------------------------------------


@dataclass
class UserEntry:
    """One authorized Telegram user."""
    user_id: int
    user_name: str = ""             # human-readable, e.g. "@alice" or "Alice"
    added_at: float = field(default_factory=lambda: time.time())
    added_by: int = 0               # user_id of the owner who authorized them


@dataclass
class MultiUserState:
    """Persistable state for the allowlist."""
    owner_user_id: int = 0
    authorized_users: List[UserEntry] = field(default_factory=list)
    version: int = 1

    def find(self, user_id: int) -> Optional[UserEntry]:
        for entry in self.authorized_users:
            if entry.user_id == user_id:
                return entry
        return None

    def is_authorized(self, user_id: int) -> bool:
        if not user_id:
            return False
        if user_id == self.owner_user_id:
            return True
        return any(e.user_id == user_id for e in self.authorized_users)

    def list_users(self) -> List[UserEntry]:
        # Owner first, then by added_at.
        rest = [e for e in self.authorized_users if e.user_id != self.owner_user_id]
        rest.sort(key=lambda e: e.added_at)
        return rest


# --- State I/O --------------------------------------------------------------


def state_path(hermes_home: Optional[Path] = None) -> Path:
    if hermes_home is None:
        from hermes_constants import get_hermes_home
        hermes_home = get_hermes_home()
    return Path(hermes_home) / "multi_user.json"


def load_state(hermes_home: Optional[Path] = None) -> MultiUserState:
    """Read state from disk. Missing file → fresh state (no owner)."""
    path = state_path(hermes_home)
    if not path.exists():
        return MultiUserState()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("multi_user.json unreadable (%s); starting fresh", exc)
        return MultiUserState()

    state = MultiUserState()
    state.owner_user_id = int(raw.get("owner_user_id") or 0)
    state.version = int(raw.get("version") or 1)
    for entry in raw.get("authorized_users") or []:
        if not isinstance(entry, dict):
            continue
        try:
            uid = int(entry.get("user_id"))
        except (TypeError, ValueError):
            continue
        if not uid:
            continue
        state.authorized_users.append(UserEntry(
            user_id=uid,
            user_name=str(entry.get("user_name") or ""),
            added_at=float(entry.get("added_at") or 0),
            added_by=int(entry.get("added_by") or 0),
        ))
    return state


def save_state(state: MultiUserState, hermes_home: Optional[Path] = None) -> Path:
    """Atomic write of state to disk with mode 600."""
    path = state_path(hermes_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "owner_user_id": state.owner_user_id,
        "version": state.version,
        "authorized_users": [asdict(e) for e in state.authorized_users],
    }
    body = json.dumps(payload, indent=2, sort_keys=True) + "\n"

    import tempfile
    fd, tmp_name = tempfile.mkstemp(prefix="multi_user.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    try:
        os.chmod(path, 0o600)
    except (OSError, NotImplementedError):
        pass
    return path


# --- Thread-safe state holder ----------------------------------------------


class MultiUserManager:
    """In-process allowlist with disk persistence and locking.

    The gateway instantiates one of these per bot. Every mutation
    acquires ``_lock`` so the in-memory state and the on-disk file
    stay in lock-step. Reads are also under the lock to avoid races
    between "is X authorized" and a concurrent "remove X".
    """

    def __init__(self, hermes_home: Optional[Path] = None):
        self._hermes_home = hermes_home
        self._lock = threading.RLock()
        self._state = load_state(hermes_home)

    # --- queries ---

    @property
    def owner_user_id(self) -> int:
        with self._lock:
            return self._state.owner_user_id

    def is_authorized(self, user_id: Optional[int]) -> bool:
        if not user_id:
            return False
        with self._lock:
            return self._state.is_authorized(int(user_id))

    def is_owner(self, user_id: Optional[int]) -> bool:
        if not user_id:
            return False
        with self._lock:
            return self._state.owner_user_id == int(user_id)

    def list_users(self) -> List[UserEntry]:
        with self._lock:
            return list(self._state.list_users())

    # --- bootstrap ---

    def ensure_owner(self, user_id: int, user_name: str = "") -> bool:
        """If no owner is set yet, claim this user as owner. Returns True
        if a claim was made (i.e. this is the first authorized user).

        Safe to call from the gateway on every inbound message — no-op
        when the owner is already set.
        """
        if not user_id:
            return False
        with self._lock:
            if self._state.owner_user_id:
                return False
            self._state.owner_user_id = int(user_id)
            self._state.authorized_users.append(UserEntry(
                user_id=int(user_id), user_name=user_name or "",
                added_by=int(user_id),
            ))
            save_state(self._state, self._hermes_home)
            logger.info("MultiUserManager: owner claimed user_id=%s", user_id)
            return True

    # --- mutations ---

    def add_user(self, owner_id: int, user_id: int, user_name: str = "") -> "OpResult":
        """Owner authorizes another user. Returns ok=False with reason if
        the caller is not the owner or the user is already in the list.
        """
        if not user_id:
            return OpResult(ok=False, reason="invalid_id")
        with self._lock:
            if self._state.owner_user_id != int(owner_id):
                return OpResult(ok=False, reason="not_owner")
            if int(user_id) == self._state.owner_user_id:
                return OpResult(ok=False, reason="already_owner")
            if self._state.find(int(user_id)) is not None:
                return OpResult(ok=False, reason="already_authorized")
            self._state.authorized_users.append(UserEntry(
                user_id=int(user_id), user_name=user_name or "",
                added_by=int(owner_id),
            ))
            save_state(self._state, self._hermes_home)
            return OpResult(ok=True)

    def remove_user(self, owner_id: int, user_id: int) -> "OpResult":
        """Owner revokes another user. Cannot remove the owner."""
        if not user_id:
            return OpResult(ok=False, reason="invalid_id")
        with self._lock:
            if self._state.owner_user_id != int(owner_id):
                return OpResult(ok=False, reason="not_owner")
            if int(user_id) == self._state.owner_user_id:
                return OpResult(ok=False, reason="cannot_remove_owner")
            before = len(self._state.authorized_users)
            self._state.authorized_users = [
                e for e in self._state.authorized_users if e.user_id != int(user_id)
            ]
            if len(self._state.authorized_users) == before:
                return OpResult(ok=False, reason="not_found")
            save_state(self._state, self._hermes_home)
            return OpResult(ok=True)

    def transfer_ownership(self, current_owner_id: int, new_owner_id: int) -> "OpResult":
        """Hand owner to another user. The new owner must already be in
        the allowlist (so the new owner has interacted with the bot
        before and isn't an empty Telegram account)."""
        if not new_owner_id:
            return OpResult(ok=False, reason="invalid_id")
        with self._lock:
            if self._state.owner_user_id != int(current_owner_id):
                return OpResult(ok=False, reason="not_owner")
            if int(new_owner_id) == self._state.owner_user_id:
                return OpResult(ok=False, reason="already_owner")
            if self._state.find(int(new_owner_id)) is None:
                return OpResult(ok=False, reason="not_in_allowlist")
            self._state.owner_user_id = int(new_owner_id)
            save_state(self._state, self._hermes_home)
            return OpResult(ok=True)


@dataclass(frozen=True)
class OpResult:
    ok: bool
    reason: Optional[str] = None  # "not_owner" | "already_authorized" | "not_found" | ...


# --- Module-level singleton -------------------------------------------------

_manager: Optional[MultiUserManager] = None
_manager_lock = threading.Lock()


def get_manager(hermes_home: Optional[Path] = None) -> MultiUserManager:
    """Return the process-wide MultiUserManager, creating it on first use."""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = MultiUserManager(hermes_home)
    return _manager


def reset_for_tests() -> None:
    """Drop the cached singleton — used by tests only."""
    global _manager
    with _manager_lock:
        _manager = None


__all__ = [
    "UserEntry", "MultiUserState", "MultiUserManager", "OpResult",
    "load_state", "save_state", "state_path",
    "get_manager", "reset_for_tests",
]
