import pytest
from fastapi import HTTPException
from types import SimpleNamespace

from backend.client_profiles import (
    normalize_full_name,
    normalize_phone,
    sign_client_access,
    verify_client_access,
)
from backend.handlers.master_bot import booking_card_text


@pytest.mark.parametrize(
    ("raw_name", "expected"),
    [
        ("иванов иван", "Иванов Иван"),
        ("  петрова   анна  ", "Петрова Анна"),
        ("сидоров-петров олег", "Сидоров-петров Олег"),
    ],
)
def test_normalize_full_name_accepts_surname_and_name(raw_name, expected):
    assert normalize_full_name(raw_name) == expected


@pytest.mark.parametrize("raw_name", ["Иван", "Фвкпр Трнк", "Иванов 123", "А Б"])
def test_normalize_full_name_rejects_incomplete_or_random_input(raw_name):
    with pytest.raises(ValueError):
        normalize_full_name(raw_name)


def test_normalize_phone_keeps_only_verified_contact_digits():
    assert normalize_phone("+7 (912) 345-67-89") == "+79123456789"


def test_client_access_signature_is_bound_to_master():
    signature = sign_client_access(123, 10, "bot-token")
    verify_client_access(123, 10, signature, "bot-token")

    with pytest.raises(HTTPException):
        verify_client_access(123, 11, signature, "bot-token")


def test_booking_card_contains_master_calendar_details():
    booking = SimpleNamespace(
        time="10:30:00",
        service_name="Стрижка + Укладка",
        duration_minutes=90,
        comment="Позвонить заранее",
        master_comment="Постоянный клиент",
    )
    client = SimpleNamespace(name="Иванов Иван", phone="+79123456789", telegram_id=123)

    text = booking_card_text(booking, client, 1)

    assert "Иванов Иван" in text
    assert "+79123456789" in text
    assert 'href="tg://user?id=123"' in text
    assert "Стрижка + Укладка — всего 90 мин" in text
    assert "Позвонить заранее" in text
    assert "Постоянный клиент" in text
