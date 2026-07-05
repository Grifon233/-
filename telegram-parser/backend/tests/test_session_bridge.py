"""Tests for the Pyrogram → Telethon session bridge.

The two Telethon-based parsers (telegram-channels-monitor,
keyword_alert_bot) cannot consume the combine's Pyrogram session
strings directly. ``session_bridge`` rebuilds a Telethon
``StringSession`` from the same MTProto auth key + datacenter, so the
account never has to log in again.

These tests do NOT touch Telegram servers. They build a synthetic
Pyrogram session string with a known auth key and assert that the
converted Telethon string carries the *same* dc_id and auth key — the
two values that decide whether the session authorizes.
"""
import base64
import os
import struct

import pytest

from app.services import session_bridge


def _make_pyrogram_string(dc_id: int, auth_key: bytes, user_id: int,
                          api_id: int = 123456, test_mode: bool = False,
                          is_bot: bool = False) -> str:
    """Build a Pyrogram v2 session string (``>BI?256sQ?``)."""
    packed = struct.pack(">BI?256sQ?", dc_id, api_id, test_mode,
                         auth_key, user_id, is_bot)
    return base64.urlsafe_b64encode(packed).decode().rstrip("=")


def _make_pyrogram_string_old64(dc_id: int, auth_key: bytes,
                                user_id: int, test_mode: bool = False,
                                is_bot: bool = False) -> str:
    """Build an old (pre-api_id) 64-bit Pyrogram string (``>B?256sQ?``)."""
    packed = struct.pack(">B?256sQ?", dc_id, test_mode, auth_key,
                         user_id, is_bot)
    return base64.urlsafe_b64encode(packed).decode().rstrip("=")


def test_converted_string_preserves_dc_and_auth_key():
    auth_key = os.urandom(256)
    pyro = _make_pyrogram_string(dc_id=2, auth_key=auth_key, user_id=99999)

    telethon_string = session_bridge.pyrogram_to_telethon_string(pyro)

    # Parse it back through Telethon's own loader — the source of truth.
    from telethon.sessions import StringSession
    loaded = StringSession(telethon_string)
    assert loaded.dc_id == 2
    assert bytes(loaded.auth_key.key) == auth_key


def test_converted_string_handles_each_datacenter():
    for dc_id in (1, 2, 3, 4, 5):
        auth_key = os.urandom(256)
        pyro = _make_pyrogram_string(dc_id=dc_id, auth_key=auth_key, user_id=1)
        from telethon.sessions import StringSession
        loaded = StringSession(
            session_bridge.pyrogram_to_telethon_string(pyro)
        )
        assert loaded.dc_id == dc_id
        assert bytes(loaded.auth_key.key) == auth_key


def test_supports_old_64bit_pyrogram_format():
    auth_key = os.urandom(256)
    pyro = _make_pyrogram_string_old64(dc_id=4, auth_key=auth_key, user_id=7)

    loaded_string = session_bridge.pyrogram_to_telethon_string(pyro)

    from telethon.sessions import StringSession
    loaded = StringSession(loaded_string)
    assert loaded.dc_id == 4
    assert bytes(loaded.auth_key.key) == auth_key


def test_parse_returns_user_id_and_dc():
    auth_key = os.urandom(256)
    pyro = _make_pyrogram_string(dc_id=5, auth_key=auth_key, user_id=4242)

    info = session_bridge.parse_pyrogram_session_string(pyro)

    assert info.dc_id == 5
    assert info.user_id == 4242
    assert info.auth_key == auth_key


def test_invalid_string_raises():
    with pytest.raises(session_bridge.SessionBridgeError):
        session_bridge.pyrogram_to_telethon_string("not-a-valid-session")
