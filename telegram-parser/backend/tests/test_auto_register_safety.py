from __future__ import annotations

import pytest

from app.models.account import Account
from app.services import auto_register_service
from app.services.smsfast_service import NoNumbersError, SmsFastError, SmsFastService


class _FakeDb:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


async def test_smsfast_cancel_requires_explicit_confirmation(monkeypatch):
    service = SmsFastService(token="test")

    async def bad_status(_activation_id: str, _status: int) -> str:
        return "ACCESS_ACTIVATION"

    monkeypatch.setattr(service, "set_status", bad_status)

    with pytest.raises(SmsFastError, match="не подтвердил отмену"):
        await service.cancel("123")


async def test_cancel_confirmation_clears_persisted_activation(monkeypatch):
    account = Account(
        id=10,
        phone_number="+15550001111",
        api_id=1,
        api_hash="a" * 32,
        project_id=1,
        health_factors={
            "auto_register_activation": {
                "activation_id": "123",
                "phone": "+15550001111",
            }
        },
    )
    db = _FakeDb()

    async def cancelled(_activation_id: str):
        return "cancel", None

    monkeypatch.setattr(
        auto_register_service.smsfast_service, "get_status", cancelled
    )

    await auto_register_service._cancel_and_confirm(
        db,
        account,
        "123",
        restore_phone="pending_test",
    )

    assert account.phone_number == "pending_test"
    assert account.health_factors is None
    assert db.commits == 1


async def test_smsfast_get_number_falls_back_to_any_and_detected_operators(monkeypatch):
    service = SmsFastService(token="test")
    calls: list[tuple[str, str | None]] = []

    async def fake_request(action: str, **params):
        if action == "getNumbersStatus":
            return '{"tg_0": 5, "tg_3": 2}'
        if action == "getNumber":
            calls.append((params.get("service"), params.get("operator")))
            if params.get("operator") == "any":
                raise NoNumbersError("none", code="NO_NUMBERS")
            if params.get("operator") == "0":
                return "ACCESS_NUMBER:42:15551234567"
            raise NoNumbersError("none", code="NO_NUMBERS")
        raise AssertionError(f"unexpected action {action}")

    monkeypatch.setattr(service, "_request", fake_request)

    activation_id, phone = await service.get_number(12)

    assert (activation_id, phone) == ("42", "15551234567")
    assert calls == [("tg", "any"), ("tg", "0")]


async def test_smsfast_get_number_uses_explicit_operator_without_fallback(monkeypatch):
    service = SmsFastService(token="test")
    calls: list[str | None] = []

    async def fake_request(action: str, **params):
        if action == "getNumber":
            calls.append(params.get("operator"))
            return "ACCESS_NUMBER:99:15550001111"
        raise AssertionError(f"unexpected action {action}")

    monkeypatch.setattr(service, "_request", fake_request)

    activation_id, phone = await service.get_number(12, operator="3")

    assert (activation_id, phone) == ("99", "15550001111")
    assert calls == ["3"]


def test_auto_registration_has_financial_attempt_ceiling():
    assert auto_register_service.MAX_ATTEMPTS == 30
