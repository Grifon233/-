"""Тесты backend: позитивные и негативные сценарии всех эндпоинтов."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

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

    MSG["ts"] = datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(settings, "ingest_api_key", "")
    monkeypatch.setattr(settings, "ingest_allow_unauthenticated", True)
    monkeypatch.setattr(settings, "llm_api_keys_file", "")
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(ingest_module, "geocode_street", fake_geocode)
    feedback_module._requests.clear()
    feedback_module._global_requests.clear()
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
    from app.services import sightings

    assert client.post("/ingest", json=MSG).json()["accepted"]
    clock = datetime.fromisoformat(MSG["ts"]).timestamp() + settings.sighting_ttl + 1
    monkeypatch.setattr(sightings, "time", SimpleNamespace(time=lambda: clock))
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
        def json(self): return {"trip": {"summary": {}, "legs": [{"shape": "a_valid_polyline"}]}}

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
    monkeypatch.setattr(settings, "feedback_bot_token", "123:TESTTOKEN")
    monkeypatch.setattr(settings, "feedback_chat_id", "12345")

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
    monkeypatch.setattr(settings, "feedback_bot_token", "123:TESTTOKEN")
    monkeypatch.setattr(settings, "feedback_chat_id", "12345")

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
    monkeypatch.setattr(settings, "feedback_bot_token", "123:TESTTOKEN")
    monkeypatch.setattr(settings, "feedback_chat_id", "12345")
    monkeypatch.setattr(settings, "feedback_rate_limit", 1)

    async def unavailable(*args, **kwargs):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx.AsyncClient, "post", unavailable)
    first = client.post("/feedback", json={"text": "один"}).json()
    second = client.post("/feedback", json={"text": "два"}).json()
    assert first["reason"] == "request_failed"
    assert second["reason"] == "rate_limited"



def test_ingest_fails_closed_without_api_key(monkeypatch):
    monkeypatch.setattr(settings, "ingest_allow_unauthenticated", False)
    response = client.post("/ingest", json=MSG)
    assert response.status_code == 503
    assert response.json()["detail"] == "ingest_not_configured"


@pytest.mark.parametrize(("offset", "reason"), [(-36000, "stale_message"), (301, "future_message")])
def test_ingest_rejects_outdated_timestamps_before_extraction(monkeypatch, offset, reason):
    from app.services import extract

    async def unexpected(*args, **kwargs):
        pytest.fail("An old or future message must not make an external request")

    monkeypatch.setattr(extract, "extract", unexpected)
    timestamp = datetime.now(timezone.utc) + timedelta(seconds=offset)
    response = client.post("/ingest", json=dict(MSG, ts=timestamp.isoformat()))
    assert response.json() == {"accepted": False, "reason": reason}


def test_expiry_counts_from_observation_time():
    timestamp = datetime.now(timezone.utc) - timedelta(minutes=20)
    assert client.post("/ingest", json=dict(MSG, ts=timestamp.isoformat())).json()["accepted"]
    street = client.get("/streets", params={"city": "  МСК  "}).json()[0]
    assert datetime.fromisoformat(street["expires_at"]) == timestamp + timedelta(seconds=settings.sighting_ttl)


@pytest.mark.parametrize("timestamp", [42, "42", "2026-01-02", "0001-01-01T01:00:00+02:00"])
def test_rejects_non_iso_or_overflow_timestamp(timestamp):
    assert client.post("/ingest", json=dict(MSG, ts=timestamp)).status_code == 422


def test_rejects_non_telegram_source_link():
    assert client.post("/ingest", json=dict(MSG, message_link="https://example.test/1")).status_code == 422


def test_private_source_quote_does_not_export_chat_id_or_text(monkeypatch):
    from app.services import extract

    async def unexpected(*args, **kwargs):
        pytest.fail("Unexpected external request for a private quote")

    monkeypatch.setattr(extract, "_extract_with_providers", unexpected)
    response = client.post("/ingest", json=dict(MSG, message_link="chat:-10001/1"))
    assert response.json()["accepted"]
    street = client.get("/streets").json()[0]
    assert street["quotes"] == [{
        "text": "Отметка из непубличного источника", "link": "", "ts": MSG["ts"].replace("+00:00", "Z"),
    }]
    assert client.get("/streets").headers["Cache-Control"] == "no-store"


def test_concurrent_duplicate_skips_extraction_and_keeps_original(monkeypatch):
    from app.services import extract

    calls = 0

    async def fake_extract(text):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.02)
        return {"city": "Москва", "street": "улица Баумана"}

    monkeypatch.setattr(extract, "extract", fake_extract)

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as api:
            return await asyncio.gather(*(api.post("/ingest", json=MSG) for _ in range(5)))

    results = [response.json() for response in asyncio.run(run())]
    assert calls == 1
    assert sum(not result["duplicate"] for result in results) == 1
    assert {result["street"] for result in results} == {"улица Баумана"}
    assert client.post("/ingest", json=dict(MSG, text="замена")).json()["street"] == "улица Баумана"


@pytest.mark.parametrize("text", [
    "Видел автобус на улице Баумана",
    "Вчера видел курьера на улице Баумана",
    "Нужен курьер на улице Баумана",
    "Где курьер на улице Баумана?",
    "Курьера нет на улице Баумана",
    "Курьер сейчас на улице",
])
def test_regex_does_not_make_false_sightings(text):
    assert client.post("/ingest", json=dict(MSG, text=text)).json() == {
        "accepted": False, "reason": "not_a_sighting",
    }


@pytest.mark.parametrize(("text", "street"), [
    ("Курьер стоит в переулке Сивцев Вражек", "переулок Сивцев Вражек"),
    ("Доставщик на проспекте Мира", "проспект Мира"),
    ("Курьер на улице 50 лет Октября", "улица 50 лет Октября"),
    ("Курьер едет по шоссе Энтузиастов", "шоссе Энтузиастов"),
])
def test_regex_keeps_street_type_and_multiple_words(text, street):
    assert client.post("/ingest", json=dict(MSG, text=text)).json()["street"] == street


def test_feedback_rejects_spaces_and_unbounded_fields():
    assert client.post("/feedback", json={"text": " \n\t "}).status_code == 422
    assert client.post("/feedback", json={"text": "тест", "city": "x" * 101}).status_code == 422


def test_feedback_ignores_unsigned_attribution_and_disables_preview(monkeypatch):
    monkeypatch.setattr(settings, "feedback_bot_token", "123:TESTTOKEN")
    monkeypatch.setattr(settings, "feedback_chat_id", "12345")

    async def post(_client, _url, *, json):
        assert not "подмена" in json["text"]
        assert json["chat_id"] == "12345"
        assert json["link_preview_options"] == {"is_disabled": True}
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    response = client.post("/feedback", json={"text": "тест", "user": "подмена"})
    assert response.json()["sent"] is True


def test_route_handles_no_path_and_malformed_return(monkeypatch):
    monkeypatch.setattr(settings, "valhalla_url", "http://valhalla")
    responses = iter([
        httpx.Response(400, json={"error_code": 442}),
        httpx.Response(200, json={"unexpected": "value"}),
        httpx.Response(200, text="not JSON"),
    ])

    async def post(_client, url, **kwargs):
        response = next(responses)
        response.request = httpx.Request("POST", url)
        return response

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    params = {"city": "мск", "from_lat": 55.75, "from_lng": 37.61, "to_lat": 55.76, "to_lng": 37.62}
    for status, detail in [(404, "route_not_found"), (502, "invalid_valhalla_response"), (502, "invalid_valhalla_response")]:
        response = client.get("/route", params=params)
        assert response.status_code == status
        assert response.json()["detail"] == detail


def test_route_never_silently_skips_occupied_street_without_geometry(monkeypatch):
    from app.routers import ingest

    async def no_geo(*args):
        return None

    monkeypatch.setattr(settings, "valhalla_url", "http://valhalla")
    client.post("/ingest", json=MSG)
    monkeypatch.setattr(ingest, "geocode_street", no_geo)
    client.post("/ingest", json=dict(MSG, message_id=2, text="Курьер стоит на улице Пушкина"))
    params = {"city": "мск", "from_lat": 55.75, "from_lng": 37.61, "to_lat": 55.76, "to_lng": 37.62,
              "avoid": "occupied"}
    response = client.get("/route", params=params)
    assert response.status_code == 409
    assert response.json()["detail"] == "occupied_geometry_unavailable"


def test_body_limits_apply_before_json_parsing():
    for path, max_size in [("/ingest", 128 * 1024), ("/feedback", 32 * 1024)]:
        response = client.post(path, content=b" " * (max_size + 1))
        assert response.status_code == 413
        assert response.json()["detail"] == "request_too_large"


def test_feedback_http_client_logs_do_not_include_token(caplog):
    import logging

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200)),
        ) as http:
            await http.post("https://api.telegram.org/bot123:TESTTOKEN/sendMessage")

    with caplog.at_level(logging.INFO, logger="httpx"):
        asyncio.run(run())
    assert "TESTTOKEN" not in caplog.text
    assert "bot[redacted]/sendMessage" in caplog.text


def test_ingest_accepts_full_quote_with_escaped_unicode():
    import json

    prefix = MSG["text"] + ". "
    text = prefix + "😀" * (10_000 - len(prefix))
    encoded = json.dumps(dict(MSG, text=text), ensure_ascii=True).encode("ascii")
    assert 100_000 < len(encoded) < 128 * 1024
    response = client.post("/ingest", content=encoded, headers={"Content-Type": "application/json"})
    assert response.status_code == 200
    assert response.json()["accepted"] is True
