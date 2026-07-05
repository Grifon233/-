"""Tests for the proxy-guard that backs every Telegram call.

The guard has to be the only chokepoint — if any code path bypasses
``assert_proxy_bound`` we lose the safety property. These tests pin
the behaviour at the service level.
"""
from __future__ import annotations

import pytest

from app.services.account_service import (
    ProxyRequiredError,
    assert_proxy_bound,
)
from app.models.account import Account, AccountStatus


def _make_account(**overrides) -> Account:
    """Build an unsaved ``Account`` for unit tests (no DB needed)."""
    defaults = dict(
        id=1,
        project_id=1,
        phone_number="+79001234567",
        api_id=12345,
        api_hash="a" * 32,
        session_string=None,
        status=AccountStatus.NEW,
        proxy_id=None,
    )
    defaults.update(overrides)
    return Account(**defaults)


def test_assert_proxy_bound_raises_when_no_proxy():
    acc = _make_account(proxy_id=None)
    with pytest.raises(ProxyRequiredError) as exc_info:
        assert_proxy_bound(acc)
    assert "+79001234567" in str(exc_info.value)
    assert "id=1" in str(exc_info.value)


def test_assert_proxy_bound_passes_with_proxy():
    acc = _make_account(proxy_id=42)
    # Should not raise.
    assert_proxy_bound(acc)


def test_telegram_service_refuses_account_without_proxy():
    """The Telegram pool must raise ``ProxyRequiredError`` for an
    account that has no proxy bound — this is the LAST line of
    defence behind every API endpoint, the bulk importer, and the
    Celery tasks."""
    from app.services.telegram_service import telegram_service, ProxyRequiredError

    acc = _make_account(proxy_id=None, session_string="BQA-fake-session")
    import asyncio
    with pytest.raises(ProxyRequiredError):
        asyncio.run(telegram_service.get_client(acc))


def test_telegram_service_refuses_account_without_session_too():
    """The guard is independent of session_string — an unauthorized
    account with no proxy is also refused (you cannot even hit the
    login flow without a proxy)."""
    from app.services.telegram_service import telegram_service, ProxyRequiredError

    acc = _make_account(proxy_id=None, session_string=None)
    import asyncio
    with pytest.raises(ProxyRequiredError):
        asyncio.run(telegram_service.get_client(acc))
