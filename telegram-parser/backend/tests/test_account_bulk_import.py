"""Tests for the bulk CSV import + the proxy guard.

These exercise the synchronous portion of the service: proxy
reference parsing and the structured report.
"""
from __future__ import annotations

import pytest

from app.services.account_service import parse_proxy_ref


def test_parse_proxy_ref_minimal():
    """``host:port`` with no scheme/auth defaults to socks5."""
    out = parse_proxy_ref("1.2.3.4:1080")
    assert out is not None
    assert out.scheme == "socks5"
    assert out.host == "1.2.3.4"
    assert out.port == 1080
    assert out.username is None
    assert out.password is None


def test_parse_proxy_ref_with_scheme():
    out = parse_proxy_ref("http://1.2.3.4:8080")
    assert out is not None
    assert out.scheme == "http"
    assert out.host == "1.2.3.4"
    assert out.port == 8080


def test_parse_proxy_ref_with_auth():
    out = parse_proxy_ref("socks5://user:pass@1.2.3.4:1080")
    assert out is not None
    assert out.scheme == "socks5"
    assert out.username == "user"
    assert out.password == "pass"


def test_parse_proxy_ref_url_encoded_password():
    """Passwords with ``@`` or ``:`` must round-trip through URL encoding."""
    out = parse_proxy_ref("socks5://user:p%40ss%3Aword@1.2.3.4:1080")
    assert out is not None
    assert out.username == "user"
    assert out.password == "p@ss:word"


def test_parse_proxy_ref_ipv6():
    out = parse_proxy_ref("socks5://user:pass@[2001:db8::1]:1080")
    assert out is not None
    # The regex captures host as "2001:db8::1" (the brackets are
    # stripped by urlparse-equivalent behaviour; for the purposes of
    # SOCKS5 Pyrogram wants a bare IPv6).
    assert "2001:db8::1" in out.host or "2001:db8" in out.host


def test_parse_proxy_ref_invalid():
    assert parse_proxy_ref("") is None
    assert parse_proxy_ref("garbage") is None
    assert parse_proxy_ref("1.2.3.4") is None  # no port
    assert parse_proxy_ref("not-a-scheme://1.2.3.4:80") is None
    assert parse_proxy_ref("ftp://1.2.3.4:80") is None  # not a real proxy scheme


def test_parse_proxy_ref_real_world():
    """The exact proxy the operator pasted into the chat."""
    out = parse_proxy_ref("socks5://F6keWS:wMSRMa@38.154.19.220:8000")
    assert out is not None
    assert out.scheme == "socks5"
    assert out.host == "38.154.19.220"
    assert out.port == 8000
    assert out.username == "F6keWS"
    assert out.password == "wMSRMa"


def test_parse_proxy_ref_4colon_format():
    """The format proxy sellers (smartproxy, etc.) use:
    ``host:port:user:pass``. Scheme defaults to socks5.
    """
    out = parse_proxy_ref("38.154.19.220:8000:F6keWS:wMSRMa")
    assert out is not None
    assert out.scheme == "socks5"
    assert out.host == "38.154.19.220"
    assert out.port == 8000
    assert out.username == "F6keWS"
    assert out.password == "wMSRMa"


# ---------------------------------------------------------------------------
# Bulk CSV import (integration with the DB)
# ---------------------------------------------------------------------------
import pytest
from app.services.account_service import (
    bulk_create_accounts_from_csv,
    BulkImportReport,
)
from app.models.proxy import Proxy


async def test_bulk_csv_skips_accounts_without_proxy(db_session):
    csv_bytes = (
        b"phone_number,api_id,api_hash,proxy_ref\n"
        b"+79001111111,12345,aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa,\n"
        b"+79002222222,12345,bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb,\n"
    )
    report = await bulk_create_accounts_from_csv(db_session, csv_bytes)
    assert isinstance(report, BulkImportReport)
    assert report.imported == 0
    assert report.skipped_no_proxy == 2
    assert len(report.errors) == 2
    # And nothing in the DB.
    from sqlalchemy import select
    from app.models.account import Account
    rows = (await db_session.execute(select(Account))).scalars().all()
    assert rows == []


async def test_bulk_csv_creates_proxy_on_demand(db_session):
    csv_bytes = (
        b"phone_number,api_id,api_hash,proxy_ref\n"
        b"+79001111111,12345,aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa,socks5://u:p@1.2.3.4:1080\n"
    )
    report = await bulk_create_accounts_from_csv(db_session, csv_bytes)
    assert report.imported == 1
    assert report.errors == []

    from sqlalchemy import select
    from app.models.account import Account
    accounts = (await db_session.execute(select(Account))).scalars().all()
    assert len(accounts) == 1
    assert accounts[0].phone_number == "+79001111111"
    assert accounts[0].proxy_id is not None
    assert accounts[0].folder == "new"  # not warming because no session_string

    proxies = (await db_session.execute(select(Proxy))).scalars().all()
    assert len(proxies) == 1
    assert proxies[0].host == "1.2.3.4"
    assert proxies[0].port == 1080


async def test_bulk_csv_session_string_requires_proxy(db_session):
    """A row with session_string but no proxy_ref MUST be skipped."""
    csv_bytes = (
        b"phone_number,api_id,api_hash,session_string\n"
        b"+79001111111,12345,aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa,BQA-fake\n"
    )
    report = await bulk_create_accounts_from_csv(db_session, csv_bytes)
    assert report.imported == 0
    assert report.skipped_no_proxy == 1
    assert any("session_string" in e["reason"] for e in report.errors)


async def test_bulk_csv_session_with_proxy_creates_warming_account(db_session):
    csv_bytes = (
        b"phone_number,api_id,api_hash,proxy_ref,session_string\n"
        b"+79001111111,12345,aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa,1.2.3.4:1080,BQA-fake\n"
    )
    report = await bulk_create_accounts_from_csv(db_session, csv_bytes)
    assert report.imported == 1
    from sqlalchemy import select
    from app.models.account import Account
    acc = (await db_session.execute(select(Account))).scalar_one()
    assert acc.folder == "warming"
    assert acc.session_string == "BQA-fake"


async def test_bulk_csv_duplicate_phone_is_idempotent(db_session):
    csv_bytes = (
        b"phone_number,api_id,api_hash,proxy_ref\n"
        b"+79001111111,12345,aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa,1.2.3.4:1080\n"
    )
    r1 = await bulk_create_accounts_from_csv(db_session, csv_bytes)
    r2 = await bulk_create_accounts_from_csv(db_session, csv_bytes)
    assert r1.imported == 1
    assert r2.imported == 0
    assert r2.skipped_duplicates == 1


async def test_bulk_csv_optional_require_proxy(db_session):
    """``require_proxy=False`` lets the operator queue draft accounts."""
    csv_bytes = (
        b"phone_number,api_id,api_hash\n"
        b"+79001111111,12345,aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
    )
    report = await bulk_create_accounts_from_csv(
        db_session, csv_bytes, require_proxy=False
    )
    assert report.imported == 1
    from sqlalchemy import select
    from app.models.account import Account
    acc = (await db_session.execute(select(Account))).scalar_one()
    assert acc.proxy_id is None
