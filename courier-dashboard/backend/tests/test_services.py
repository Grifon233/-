import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from app.config import Settings, settings
from app.schemas import Quote
from app.services import extract, geo, llm_router, sightings
from app.services.geometry import normalize_geometry, sample_locations


def test_sqlite_survives_restart_deduplicates_and_prunes(tmp_path, monkeypatch):
    path = tmp_path / "persistent.sqlite3"
    now = 1_790_000_000
    clock = SimpleNamespace(time=lambda: now)
    monkeypatch.setattr(sightings, "time", clock)
    q = Quote(text="Курьер", link="https://t.me/test/10", ts=datetime.fromtimestamp(now, timezone.utc))
    geometry = {"type": "Point", "coordinates": [37.6, 55.7]}

    first = sightings.SightingsStore(str(path))
    try:
        assert first.add("Москва", "ул. Баумана", q, "event1", now + 10, geometry)
        assert not first.add("Казань", "улица Баумана", q, "event1", now + 50)
        assert first.add("Москва", "Баумана улица", q, "event2", now + 20)
    finally:
        first.close()

    reopened = sightings.SightingsStore(str(path))
    try:
        assert reopened.find_event("event1") == ("Москва", "ул. Баумана")
        assert reopened.get_geometry("Москва", "улица Баумана") == geometry
        result = reopened.list_streets("Moscow")
        assert len(result) == 1
        assert result[0].id == "москва::улица баумана"
        assert len(result[0].quotes) == 2
        assert result[0].expires_at.timestamp() == now + 20
        now += 11
        assert len(reopened.get_street(result[0].id).quotes) == 1
        assert reopened.find_event("event1") is None
        now += 10
        assert reopened.get_street(result[0].id) is None
        reopened.purge_expired()
        assert reopened._db.execute("SELECT COUNT(*) FROM sightings").fetchone()[0] == 0
        assert reopened._db.execute("SELECT COUNT(*) FROM streets").fetchone()[0] == 0
    finally:
        reopened.close()


def test_settings_requires_explicit_persistence_path_and_hides_bad_token():
    with pytest.raises(ValueError, match="SIGHTINGS_DB_PATH"):
        Settings(store_backend="sqlite", sightings_db_path="", _env_file=None)
    with pytest.raises(ValueError) as error:
        Settings(feedback_bot_token="secret-token-that-must-not-be-logged", _env_file=None)
    assert "secret-token-that-must-not-be-logged" not in str(error.value)


@pytest.mark.parametrize("geometry", [
    {"type": "LineString", "coordinates": [[37.6, 55.7]]},
    {"type": "LineString", "coordinates": [[37.6, 55.7], [float("nan"), 55.8]]},
    {"type": "Point", "coordinates": [True, 55.8]},
    {"type": "Point", "coordinates": [300, 55.8]},
    {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1]]]},
    {"type": ["LineString"], "coordinates": [[0, 0], [1, 1]]},
])
def test_rejects_malformed_geojson(geometry):
    assert normalize_geometry(geometry) is None
    assert not sample_locations(geometry, limit=50)


def test_sampling_uses_full_polyline_and_respects_limit():
    points = sample_locations({"type": "LineString", "coordinates": [[37.6, 55.7], [37.6, 55.8]]}, limit=4)
    assert len(points) == 4
    assert points[0]["lat"] < 55.73 < 55.77 < points[-1]["lat"]


def test_geocoding_ignores_wrong_city_and_malformed_first_candidates(monkeypatch):
    monkeypatch.setattr(settings, "nominatim_url", "https://geocoder.test")
    geometry = {"type": "LineString", "coordinates": [[37.6, 55.7], [37.7, 55.8]]}
    calls = 0

    async def get(_client, url, *, params, headers):
        nonlocal calls
        calls += 1
        assert params["countrycodes"] == "ru"
        assert headers["User-Agent"]
        return httpx.Response(200, request=httpx.Request("GET", url), json=[
            "bad",
            {"address": {"state": "Татарстан"}, "geojson": geometry},
            {"address": {"city": "Москва"}, "geojson": {"type": "LineString", "coordinates": []}},
            {"address": {"city": "Moscow"}, "geojson": geometry},
        ])

    monkeypatch.setattr(httpx.AsyncClient, "get", get)
    geo.clear_geo_cache()
    try:
        async def run():
            assert await geo.geocode_street("Москва", "ул. Баумана") == geometry
            assert await geo.geocode_street("Москва", "Баумана улица") == geometry
        asyncio.run(run())
        assert calls == 1
    finally:
        geo.clear_geo_cache()


def test_geo_failure_expires_instead_of_poisoning_cache(monkeypatch):
    monkeypatch.setattr(settings, "nominatim_url", "https://geocoder.test")
    clock = 100.0
    monkeypatch.setattr(geo, "time", SimpleNamespace(monotonic=lambda: clock))
    geometry = {"type": "Point", "coordinates": [37.6, 55.7]}
    calls = 0

    async def get(_client, url, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("offline")
        return httpx.Response(200, request=httpx.Request("GET", url), json=[
            {"address": {"city": "Москва"}, "geojson": geometry},
        ])

    monkeypatch.setattr(httpx.AsyncClient, "get", get)
    geo.clear_geo_cache()
    try:
        async def run():
            nonlocal clock
            assert await geo.geocode_street("Москва", "улица Баумана") is None
            assert await geo.geocode_street("Москва", "улица Баумана") is None
            assert calls == 1
            clock += 16
            assert await geo.geocode_street("Москва", "улица Баумана") == geometry
            assert calls == 2

        asyncio.run(run())
    finally:
        geo.clear_geo_cache()


def test_anthropic_reads_result_and_respects_negative_decision(monkeypatch):
    import anthropic

    monkeypatch.setattr(settings, "anthropic_api_key", "test")
    payload = '{"is_courier_sighting": false, "street": null, "confidence": 0.9}'
    messages = []

    class FakeAnthropic:
        def __init__(self, *, api_key, **kwargs):
            assert api_key == "test"
            self.messages = self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def create(self, *, messages: list, **kwargs):
            assert messages[0]["role"] == "user"
            return SimpleNamespace(content=[SimpleNamespace(type="text", text=payload)])

    monkeypatch.setattr(anthropic, "AsyncAnthropic", FakeAnthropic)
    text = "Курьер стоит на улице Баумана"
    assert asyncio.run(extract.extract(text)) is None
    payload = '{"is_courier_sighting": true, "street": "Баумана улица", "confidence": 0.9}'
    assert asyncio.run(extract.extract(text))["street"] == "Баумана улица"


@pytest.mark.parametrize("raw", [
    '{"is_courier_sighting": "false", "street": "Баумана", "confidence": 0.8}',
    '{"is_courier_sighting": true, "city": [], "street": "Баумана", "confidence": 0.8}',
    '{"is_courier_sighting": true, "street": "Баумана", "confidence": NaN}',
    '{"is_courier_sighting": true, "street": "Баумана", "confidence": 100}',
    '{"is_courier_sighting": true, "street": "   ", "confidence": 0.8}',
])
def test_extraction_result_is_strict(raw):
    assert extract._parse_json(raw) is None


def test_llm_router_invalid_first_provider_does_not_starve_backup(tmp_path, monkeypatch):
    key_file = tmp_path / "llm-keys.txt"
    key_file.write_text("Mistral\nkey 1 - fake-key-one\nkey 2 - fake-key-two\nCohere\nkey 1 - fake-key-three\n", encoding="utf-8")
    monkeypatch.setattr(settings, "llm_api_keys_file", str(key_file))
    monkeypatch.setattr(settings, "llm_provider_order", "mistral,cohere")
    monkeypatch.setattr(settings, "llm_max_attempts", 2)
    router = llm_router.LLMRouter()
    called = []

    async def post(_client, url, **kwargs):
        called.append(url)
        if "mistral" in url:
            return httpx.Response(200, json={"choices": [{"message": {"content": "not JSON"}}]})
        return httpx.Response(200, json={"message": {"content": [{"text": "valid"}]}})

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    assert router.configured
    assert asyncio.run(router.chat([], validator=lambda result: result == "valid")) == "valid"
    assert len(called) == 2
    assert "mistral" in called[0] and "cohere" in called[1]
    monkeypatch.setattr(settings, "llm_api_keys_file", "")
    assert not router.configured
