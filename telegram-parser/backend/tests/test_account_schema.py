"""Tests for ``AccountCreate`` Pydantic schema — covers the
proxy-required guard for any account that ships with a session_string.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.account import AccountCreate


def test_create_account_minimum_fields():
    acc = AccountCreate(
        phone_number="+79001234567",
        api_id=12345,
        api_hash="a" * 32,
    )
    assert acc.proxy_id is None
    assert acc.session_string is None
    assert acc.status.value == "new"


def test_create_account_with_session_requires_proxy():
    """An account with a session_string MUST have a proxy_id."""
    with pytest.raises(ValidationError) as exc_info:
        AccountCreate(
            phone_number="+79001234567",
            api_id=12345,
            api_hash="a" * 32,
            session_string="BQA-abcdef" + "=" * 100,
        )
    errors = exc_info.value.errors()
    assert any("proxy" in str(e).lower() for e in errors)


def test_create_account_with_session_and_proxy_ok():
    acc = AccountCreate(
        phone_number="+79001234567",
        api_id=12345,
        api_hash="a" * 32,
        proxy_id=42,
        session_string="BQA-abcdef" + "=" * 100,
    )
    assert acc.proxy_id == 42
    assert acc.session_string is not None


def test_phone_must_be_e164():
    with pytest.raises(ValidationError):
        AccountCreate(
            phone_number="79001234567",  # missing +
            api_id=12345,
            api_hash="a" * 32,
        )
    with pytest.raises(ValidationError):
        AccountCreate(
            phone_number="+7900",  # too short
            api_id=12345,
            api_hash="a" * 32,
        )


def test_api_hash_must_be_32_hex():
    with pytest.raises(ValidationError):
        AccountCreate(
            phone_number="+79001234567",
            api_id=12345,
            api_hash="z" * 32,  # non-hex
        )
    with pytest.raises(ValidationError):
        AccountCreate(
            phone_number="+79001234567",
            api_id=12345,
            api_hash="a" * 16,  # too short
        )


def test_api_id_must_be_positive():
    with pytest.raises(ValidationError):
        AccountCreate(
            phone_number="+79001234567",
            api_id=0,
            api_hash="a" * 32,
        )
