"""Import existing Pyrogram/Telethon SQLite session files.

This is an offline converter: it reads the SQLite ``.session`` file
and packs a Pyrogram ``session_string``. It does not connect to
Telegram, so proxy safety is enforced by the account-creation layer:
the caller must bind a proxy before the authorized session is saved.
"""
from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
import struct
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


PYROGRAM_SESSION_STRING_FORMAT = ">BI?256sQ?"


class SessionImportError(ValueError):
    """Raised when a session file cannot be converted safely."""


@dataclass
class ImportedSession:
    session_string: str
    dc_id: int
    user_id: int
    api_id: int
    api_hash: str
    phone_number: str
    source_type: str


def import_sqlite_session(
    session_bytes: bytes,
    *,
    filename: str,
    api_id: int,
    api_hash: str,
    phone_number: Optional[str] = None,
    user_id: Optional[int] = None,
    metadata_bytes: Optional[bytes] = None,
) -> ImportedSession:
    """Convert a Pyrogram or Telethon SQLite session to Pyrogram string."""
    metadata = _read_metadata(metadata_bytes)
    effective_api_id = int(metadata.get("app_id") or api_id)
    effective_api_hash = str(metadata.get("app_hash") or api_hash)
    effective_phone = _normalize_phone(phone_number or metadata.get("phone"))
    effective_user_id = int(user_id or metadata.get("id") or 0)

    tmp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".session") as tmp:
            tmp.write(session_bytes)
            tmp_path = Path(tmp.name)

        con = sqlite3.connect(str(tmp_path))
        try:
            table_names = {
                row[0] for row in con.execute(
                    "select name from sqlite_master where type='table'"
                ).fetchall()
            }
            if "sessions" not in table_names:
                raise SessionImportError("SQLite session has no sessions table")

            columns = [row[1] for row in con.execute("pragma table_info(sessions)").fetchall()]
            row = con.execute("select * from sessions limit 1").fetchone()
            if not row:
                raise SessionImportError("SQLite session has no session row")
            data = dict(zip(columns, row))

            # Telethon stores user info in a separate entities table.
            # Read it while the connection is still open.
            telethon_entity: dict = {}
            if "entities" in table_names:
                try:
                    ent_cols = [r[1] for r in con.execute("pragma table_info(entities)").fetchall()]
                    # Prefer self-entity: positive id with a phone number.
                    ent_row = con.execute(
                        "select * from entities where id > 0 and phone is not null"
                        " order by date desc limit 1"
                    ).fetchone()
                    if not ent_row:
                        ent_row = con.execute(
                            "select * from entities where id > 0 order by date desc limit 1"
                        ).fetchone()
                    if ent_row:
                        telethon_entity = dict(zip(ent_cols, ent_row))
                except Exception:
                    pass
        finally:
            con.close()
    finally:
        if tmp_path:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass

    auth_key = data.get("auth_key")
    if not isinstance(auth_key, bytes) or len(auth_key) != 256:
        raise SessionImportError("Session auth_key is missing or invalid")

    dc_id = int(data.get("dc_id") or 0)
    if dc_id <= 0:
        raise SessionImportError("Session dc_id is missing")

    source_type = _detect_source_type(filename, data)
    if source_type == "pyrogram":
        effective_user_id = int(data.get("user_id") or effective_user_id or 0)
    else:
        # Telethon/unknown: try to pull user_id (and phone) from the entities table.
        if telethon_entity:
            effective_user_id = int(telethon_entity.get("id") or effective_user_id or 0)
            if not effective_phone:
                phone_from_entity = telethon_entity.get("phone")
                if phone_from_entity:
                    effective_phone = _normalize_phone(str(phone_from_entity))

    if effective_user_id <= 0:
        # Derive a stable 11-digit placeholder from auth_key (SHA-256).
        # Deterministic: re-importing the same session gives the same value.
        placeholder = int.from_bytes(hashlib.sha256(auth_key).digest()[:4], "big")
        placeholder = (placeholder % (10 ** 10)) + 10 ** 10  # 10000000000..19999999999
        effective_user_id = placeholder

    if not effective_phone:
        # Account.phone_number is unique and E.164-validated in this project.
        # When the real phone is not available, use a stable technical value.
        effective_phone = f"+{effective_user_id}"

    packed = struct.pack(
        PYROGRAM_SESSION_STRING_FORMAT,
        dc_id,
        effective_api_id,
        False,
        auth_key,
        effective_user_id,
        False,
    )
    return ImportedSession(
        session_string=base64.urlsafe_b64encode(packed).decode().rstrip("="),
        dc_id=dc_id,
        user_id=effective_user_id,
        api_id=effective_api_id,
        api_hash=effective_api_hash,
        phone_number=effective_phone,
        source_type=source_type,
    )


def _read_metadata(metadata_bytes: Optional[bytes]) -> dict:
    if not metadata_bytes:
        return {}
    try:
        return json.loads(metadata_bytes.decode("utf-8-sig"))
    except Exception as exc:
        raise SessionImportError(f"Invalid JSON metadata: {exc}") from exc


def _normalize_phone(value: object) -> Optional[str]:
    if value is None:
        return None
    phone = str(value).strip()
    if not phone:
        return None
    return phone if phone.startswith("+") else f"+{phone}"


def _detect_source_type(filename: str, data: dict) -> str:
    lower = filename.lower()
    if "user_id" in data or "pyrogram" in lower:
        return "pyrogram"
    if "server_address" in data or "telethon" in lower:
        return "telethon"
    return "unknown"
