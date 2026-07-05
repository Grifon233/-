"""Pyrogram ⇄ Telethon session bridge.

The combine stores every account's authorization as a **Pyrogram**
``session_string`` (see :mod:`app.services.telegram_service`). Two of
the three integrated parsers
(``telegram-channels-monitor``, ``keyword_alert_bot``) are written
against **Telethon** and cannot load a Pyrogram string.

A Telegram authorization is just an MTProto *auth key* (256 bytes)
tied to a *datacenter* (``dc_id``). Both libraries store exactly those
bytes — only the surrounding container differs. So we can rebuild a
Telethon ``StringSession`` from a Pyrogram string without ever
re-logging-in or touching Telegram servers.

Nothing here connects to the network; it is pure byte-shuffling and is
therefore fully unit-testable (see ``tests/test_session_bridge.py``).
"""
from __future__ import annotations

import base64
import struct
from dataclasses import dataclass
from typing import Optional

# Pyrogram session-string layouts (see pyrogram.storage.Storage):
#   current : ">BI?256sQ?"  dc_id, api_id, test_mode, auth_key, user_id, is_bot
#   old/64  : ">B?256sQ?"   dc_id, test_mode, auth_key, user_id(Q), is_bot
#   old/32  : ">B?256sI?"   dc_id, test_mode, auth_key, user_id(I), is_bot
_PYRO_FORMAT_CURRENT = ">BI?256sQ?"
_PYRO_FORMAT_OLD_64 = ">B?256sQ?"
_PYRO_FORMAT_OLD_32 = ">B?256sI?"

# Production datacenter IPs (IPv4). The auth key is bound to ``dc_id``,
# not to a specific IP, so any valid address for that DC lets Telethon
# connect; Telegram returns the canonical address after the handshake.
_DC_IPS = {
    1: "149.154.175.53",
    2: "149.154.167.51",
    3: "149.154.175.100",
    4: "149.154.167.91",
    5: "91.108.56.130",
}
_DEFAULT_PORT = 443


class SessionBridgeError(ValueError):
    """Raised when a session string cannot be parsed or converted."""


@dataclass
class PyrogramSessionInfo:
    dc_id: int
    auth_key: bytes
    user_id: int
    test_mode: bool
    api_id: Optional[int]
    is_bot: bool


def _b64_decode(session_string: str) -> bytes:
    """URL-safe base64 decode, restoring the stripped ``=`` padding."""
    try:
        return base64.urlsafe_b64decode(
            session_string + "=" * (-len(session_string) % 4)
        )
    except Exception as exc:  # noqa: BLE001
        raise SessionBridgeError(f"not valid base64: {exc}") from exc


def parse_pyrogram_session_string(session_string: str) -> PyrogramSessionInfo:
    """Decode a Pyrogram ``session_string`` into its components.

    Supports the current ``>BI?256sQ?`` layout plus the two legacy
    formats Pyrogram still emits/accepts.
    """
    if not session_string or not isinstance(session_string, str):
        raise SessionBridgeError("empty session string")

    data = _b64_decode(session_string.strip())
    size = len(data)

    if size == struct.calcsize(_PYRO_FORMAT_CURRENT):
        dc_id, api_id, test_mode, auth_key, user_id, is_bot = struct.unpack(
            _PYRO_FORMAT_CURRENT, data
        )
    elif size == struct.calcsize(_PYRO_FORMAT_OLD_64):
        dc_id, test_mode, auth_key, user_id, is_bot = struct.unpack(
            _PYRO_FORMAT_OLD_64, data
        )
        api_id = None
    elif size == struct.calcsize(_PYRO_FORMAT_OLD_32):
        dc_id, test_mode, auth_key, user_id, is_bot = struct.unpack(
            _PYRO_FORMAT_OLD_32, data
        )
        api_id = None
    else:
        raise SessionBridgeError(
            f"unexpected session payload length: {size} bytes"
        )

    if len(auth_key) != 256:
        raise SessionBridgeError("auth key is not 256 bytes")

    return PyrogramSessionInfo(
        dc_id=int(dc_id),
        auth_key=auth_key,
        user_id=int(user_id),
        test_mode=bool(test_mode),
        api_id=int(api_id) if api_id is not None else None,
        is_bot=bool(is_bot),
    )


def pyrogram_to_telethon_string(
    session_string: str, dc_ip: Optional[str] = None
) -> str:
    """Convert a Pyrogram session string to a Telethon ``StringSession``.

    The resulting string carries the same auth key and datacenter, so a
    Telethon client built from it is authorized as the same account.
    """
    info = parse_pyrogram_session_string(session_string)

    # Imported lazily — Telethon is heavy and not every caller needs it.
    from telethon.crypto import AuthKey
    from telethon.sessions import StringSession

    ip = dc_ip or _DC_IPS.get(info.dc_id, _DC_IPS[2])

    session = StringSession()
    session.set_dc(info.dc_id, ip, _DEFAULT_PORT)
    session.auth_key = AuthKey(info.auth_key)
    return session.save()


__all__ = [
    "SessionBridgeError",
    "PyrogramSessionInfo",
    "parse_pyrogram_session_string",
    "pyrogram_to_telethon_string",
]
