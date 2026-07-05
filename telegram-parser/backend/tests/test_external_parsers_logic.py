"""Unit tests for the matching logic ported from the three upstream
parsers. No Telegram connection involved — these lock in the behaviour
we copied so a future edit can't silently break it.
"""
from app.services.external_parsers.monitor import check_key_msg
from app.services.external_parsers.alert_bot import (
    is_regex_str,
    js_to_py_re,
    _match_keyword,
    _normalize_channel,
)
from app.services.external_parsers.base import (
    int_config,
    normalize_channel_ref,
    peer_id_candidates,
    split_config_list,
    telegram_message_link,
)


# --- monitor (volom) check_key_msg: case-insensitive substring -------------
def test_monitor_substring_match_is_case_insensitive():
    matched, hits = check_key_msg("Looking for a Python DEV", ["python", "java"])
    assert matched is True
    assert "python" in hits


def test_monitor_no_match():
    matched, hits = check_key_msg("hello world", ["python"])
    assert matched is False
    assert hits == ""


def test_monitor_reports_all_hit_keywords():
    matched, hits = check_key_msg("python and rust", ["python", "rust", "go"])
    assert matched is True
    assert "python" in hits and "rust" in hits and "go" not in hits


# --- alert_bot (crazypeace) regex + substring ------------------------------
def test_is_regex_str_detects_js_regex():
    assert is_regex_str("/foo.*/i")
    assert is_regex_str("/bar/")
    assert not is_regex_str("plain keyword")


def test_match_keyword_regex_case_insensitive():
    assert _match_keyword("/pyth.n/i", "I love Python") == ["Python"]


def test_match_keyword_regex_no_match_returns_none():
    assert _match_keyword("/zzz/", "nothing here") is None


def test_match_keyword_plain_substring():
    assert _match_keyword("dev", "need a dev now") == ["dev"]
    assert _match_keyword("dev", "nothing here") is None


def test_js_to_py_re_global_flag_findall():
    fn = js_to_py_re("/\\d+/g")
    assert fn("a1 b22 c333") == ["1", "22", "333"]


# --- channel normalization -------------------------------------------------
def test_normalize_channel_strips_url_and_at():
    assert _normalize_channel("https://t.me/Some_Channel") == "some_channel"
    assert _normalize_channel("@Some_Channel") == "some_channel"
    assert _normalize_channel("t.me/chat/") == "chat"


def test_normalize_channel_accepts_private_message_link():
    assert normalize_channel_ref("https://t.me/c/123456789/77") == -100123456789


def test_peer_id_candidates_bridge_pyrogram_and_telethon_ids():
    assert peer_id_candidates(-100123456789) == {-100123456789, 123456789}
    assert peer_id_candidates(123456789) == {123456789, -100123456789}


def test_private_message_link_uses_internal_channel_id():
    assert (
        telegram_message_link(None, -100123456789, 77)
        == "https://t.me/c/123456789/77"
    )


def test_split_config_list_preserves_commas_inside_regex():
    assert split_config_list(
        "plain,/foo,bar/i\n/baz\\/,qux/i",
        preserve_regex_commas=True,
    ) == ["plain", "/foo,bar/i", "/baz\\/,qux/i"]


def test_int_config_clamps_out_of_range_values():
    assert int_config({"limit": 999999}, "limit", 3, minimum=1, maximum=50) == 50
    assert int_config({"limit": 0}, "limit", 3, minimum=1, maximum=50) == 1
    assert int_config({"limit": "bad"}, "limit", 3, minimum=1, maximum=50) == 3
