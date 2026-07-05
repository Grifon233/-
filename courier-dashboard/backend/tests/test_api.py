"""Тесты backend: позитивные и негативные сценарии всех эндпоинтов."""
import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.config import settings
from app.services.sightings import store

client = TestClient(app)

MSG = {
    "source_chat": "@flowers_msk",
    "message_id": 1,
    "message_link": "https://t.me/flowers_msk/1",
    "text": "Курьер стоит на улице Баумана",
    "ts": "2026-06-13T10:00:00Z",
    "city": "Москва",
}


@pytest.fixture(autouse=True)
def clean_store(monkeypatch):
    import app.routers.feedback as feedback_module
    import app.routers.ingest as ingest_module

    async def fake_geocode(city, street):
        return {
            "type": "LineString",
            "coordinates": [[37.61, 55.75], [37.62, 55.76]],
        }

    monkeypatch.setattr(settings, "ingest_api_key", "")
    monkeypatch.setattr(settings, "llm_api_keys_file", "")
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(ingest_module, "geocode_street", fake_geocode)
    feedback_module._requests.clear()
    store.clear()
    yield
    store.clear()


# ---------- health ----------
def test_health():
    assert client.get("/health").json() == {"status": "ok"}


# ---------- ingest ----------
def test_ingest_valid_sighting():
    r = client.post("/ingest", json=MSG).json()
    assert r == {
        "accepted": True,
        "duplicate": False,
        "city": "Москва",
        "street": "улица Баумана",
        "geocoded": True,
    }


def test_ingest_duplicate_is_idempotent():
    first = client.post("/ingest", json=MSG).json()
    second = client.post("/ingest", json=MSG).json()
    streets = client.get("/streets", params={"city": "Москва"}).json()

    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert len(streets) == 1
    assert len(streets[0]["quotes"]) == 1


def test_ingest_api_key(monkeypatch):
    monkeypatch.setattr(settings, "ingest_api_key", "secret")
    assert client.post("/ingest", json=MSG).status_code == 401
    assert client.post(
        "/ingest", json=MSG, headers={"X-API-Key": "wrong"}
    ).status_code == 401
    assert client.post(
        "/ingest", json=MSG, headers={"X-API-Key": "secret"}
    ).status_code == 200


def test_ingest_spam_rejected():
    spam = dict(MSG, text="Реклама! Скидки на цветы, подпишись")
    assert client.post("/ingest", json=spam).json()["accepted"] is False


def test_ingest_slang_without_street_word_rejected_in_regex_mode():
    # 'бауманка' без слова 'улица' — ловит только LLM; в regex-режиме отметки нет
    slang = dict(MSG, text="Бауманка занята, видел курьера")
    assert client.post("/ingest", json=slang).json()["accepted"] is False


def test_ingest_falls_back_to_regex_when_llm_fails(monkeypatch):
    import app.services.extract as extract_module

    async def broken_llm(text):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(settings, "anthropic_api_key", "configured")
    monkeypatch.setattr(extract_module, "_extract_llm", broken_llm)
    result = client.post("/ingest", json=MSG).json()
    assert result["accepted"] is True
    assert result["street"] == "улица Баумана"


def test_ingest_unknown_city():
    no_city = dict(MSG, city=None, text="Курьер на улице Баумана")
    assert client.post("/ingest", json=no_city).json() == {
        "accepted": False, "reason": "unknown_city"
    }


def test_ingest_normalizes_city_alias():
    result = client.post("/ingest", json=dict(MSG, city="г. Москва")).json()
    assert result["accepted"] is True
    assert result["city"] == "Москва"


def test_ingest_validation_error():
    assert client.post("/ingest", json={"text": "x"}).status_code == 422


def test_ingest_rejects_timestamp_without_timezone():
    assert client.post(
        "/ingest", json=dict(MSG, ts="2026-06-13T10:00:00")
    ).status_code == 422


# ---------- streets ----------
def test_streets_empty():
    assert client.get("/streets", params={"city": "Москва"}).json() == []


def test_streets_grouping_multiple_quotes_one_street():
    client.post("/ingest", json=MSG)
    second = dict(MSG, message_id=2, source_chat="@b",
                  message_link="https://t.me/b/2",
                  text="Доставщик стоит на улице Баумана")
    client.post("/ingest", json=second)
    streets = client.get("/streets", params={"city": "Москва"}).json()
    assert len(streets) == 1
    assert len(streets[0]["quotes"]) == 2


def test_streets_city_filter():
    client.post("/ingest", json=MSG)  # Москва
    client.post("/ingest", json=dict(MSG, message_id=3, city="Казань",
                                     text="Курьер на улице Баумана"))
    assert len(client.get("/streets", params={"city": "Казань"}).json()) == 1
    assert len(client.get("/streets", params={"city": "Москва"}).json()) == 1
    assert len(client.get("/streets").json()) == 2  # без фильтра — все


def test_streets_active_flag():
    client.post("/ingest", json=MSG)
    assert client.get("/streets", params={"city": "Москва"}).json()[0]["active"] is True


# ---------- streets/{id} ----------
def test_get_street_found_and_404():
    client.post("/ingest", json=MSG)
    sid = client.get("/streets", params={"city": "Москва"}).json()[0]["id"]
    assert client.get(f"/streets/{sid}").json()["street"] == "улица Баумана"
    assert client.get("/streets/нет::такой").status_code == 404


# ---------- TTL ----------
def test_ttl_expiry(monkeypatch):
    monkeypatch.setattr(settings, "sighting_ttl", -1)  # протухает мгновенно
    client.post("/ingest", json=MSG)
    assert client.get("/streets", params={"city": "Москва"}).json() == []


# ---------- route ----------
def test_route_503_when_valhalla_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "valhalla_url", "")
    r = client.get("/route", params={
        "city": "Москва", "from_lat": 55.75, "from_lng": 37.61,
        "to_lat": 55.76, "to_lng": 37.62})
    assert r.status_code == 503


def test_route_rejects_unknown_avoid_mode(monkeypatch):
    monkeypatch.setattr(settings, "valhalla_url", "http://valhalla")
    r = client.get("/route", params={
        "city": "Москва", "from_lat": 55.75, "from_lng": 37.61,
        "to_lat": 55.76, "to_lng": 37.62, "avoid": "something"})
    assert r.status_code == 422
    assert r.json()["detail"] == "unsupported_avoid_mode"


def test_route_validates_coordinates(monkeypatch):
    monkeypatch.setattr(settings, "valhalla_url", "http://valhalla")
    r = client.get("/route", params={
        "city": "Москва", "from_lat": 155.75, "from_lng": 37.61,
        "to_lat": 55.76, "to_lng": 37.62})
    assert r.status_code == 422


def test_route_upstream_error_becomes_502(monkeypatch):
    monkeypatch.setattr(settings, "valhalla_url", "http://valhalla/")

    class _Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k):
            raise httpx.ConnectError("offline")

    import app.routers.route as route_module
    monkeypatch.setattr(route_module.httpx, "AsyncClient", _Client)

    r = client.get("/route", params={
        "city": "Москва", "from_lat": 55.75, "from_lng": 37.61,
        "to_lat": 55.76, "to_lng": 37.62})
    assert r.status_code == 502
    assert r.json()["detail"] == "valhalla_error"


def test_route_sends_occupied_geometry_to_valhalla(monkeypatch):
    monkeypatch.setattr(settings, "valhalla_url", "http://valhalla")
    client.post("/ingest", json=MSG)
    captured = {}

    class _Resp:
        def raise_for_status(self): pass
        def json(self): return {"trip": {"summary": {}}}

    class _Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json):
            captured.update(json)
            return _Resp()

    import app.routers.route as route_module
    monkeypatch.setattr(route_module.httpx, "AsyncClient", _Client)
    r = client.get("/route", params={
        "city": "Москва", "from_lat": 55.75, "from_lng": 37.61,
        "to_lat": 55.76, "to_lng": 37.62, "avoid": "occupied"})

    assert r.status_code == 200
    assert r.json()["avoidance_applied"] is True
    assert captured["exclude_locations"]


# ---------- feedback ----------
def test_feedback_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "feedback_bot_token", "")
    r = client.post("/feedback", json={"text": "карта не грузится"}).json()
    assert r == {"sent": False, "reason": "feedback_bot_not_configured"}


def test_feedback_empty_text_validation():
    assert client.post("/feedback", json={"text": ""}).status_code == 422


def test_feedback_sent_ok(monkeypatch):
    monkeypatch.setattr(settings, "feedback_bot_token", "TESTTOKEN")

    class _Resp:
        status_code = 200
        text = '{"ok":true}'
        def json(self):  # noqa: D401
            return {"ok": True}

    class _Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k): return _Resp()

    import app.routers.feedback as fb
    monkeypatch.setattr(fb.httpx, "AsyncClient", _Client)
    r = client.post("/feedback", json={"text": "тест", "city": "Москва"}).json()
    assert r == {"sent": True}


def test_feedback_invalid_json_is_handled(monkeypatch):
    monkeypatch.setattr(settings, "feedback_bot_token", "TESTTOKEN")

    class _Resp:
        status_code = 200
        def json(self):
            raise ValueError("not json")

    class _Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k): return _Resp()

    import app.routers.feedback as fb
    monkeypatch.setattr(fb.httpx, "AsyncClient", _Client)
    result = client.post("/feedback", json={"text": "тест"}).json()
    assert result == {"sent": False, "reason": "telegram_error"}


def test_feedback_rate_limit(monkeypatch):
    monkeypatch.setattr(settings, "feedback_rate_limit", 1)
    first = client.post("/feedback", json={"text": "один"}).json()
    second = client.post("/feedback", json={"text": "два"}).json()
    assert first["reason"] == "feedback_bot_not_configured"
    assert second["reason"] == "rate_limited"
