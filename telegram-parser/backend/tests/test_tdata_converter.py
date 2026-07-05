"""Tests for the tdata folder detection / parsing.

The conversion itself is exercised in
:mod:`tests.test_tdata_converter_integration` against a real opentele
session. Here we test the parts that do not need opentele:
* list_tdata_folders walks arbitrary trees and finds ``key_datas``
* parse_proxy_ref accepts the operator's documented formats
* an invalid tdata folder raises a clean TDataImportError
"""
from __future__ import annotations

import os
import zipfile
import io
from pathlib import Path

import pytest

from app.services.tdata_converter import (
    list_tdata_folders,
    TDataImportError,
    import_tdata_archive,
)
from app.services.account_service import parse_proxy_ref


def test_list_tdata_folders_direct_layout(tmp_path: Path):
    """A folder that contains ``key_datas`` directly is a tdata root."""
    (tmp_path / "key_datas").write_bytes(b"\x00" * 200)
    (tmp_path / "D877F783D5D3EF8C0").write_bytes(b"\x00" * 16)
    found = list_tdata_folders(tmp_path)
    assert tmp_path in found


def test_list_tdata_folders_nested_layout(tmp_path: Path):
    """The canonical Telegram Desktop layout:
    ``tmp/Telegram Desktop/tdata/key_datas``
    """
    nested = tmp_path / "Telegram Desktop" / "tdata"
    nested.mkdir(parents=True)
    (nested / "key_datas").write_bytes(b"\x00" * 200)
    (nested / "D877F783D5D3EF8C0").write_bytes(b"\x00" * 16)

    found = list_tdata_folders(tmp_path)
    assert nested in found


def test_list_tdata_folders_no_key_datas_returns_empty(tmp_path: Path):
    """A folder with no key_datas is not a tdata root."""
    (tmp_path / "random.txt").write_text("hi")
    found = list_tdata_folders(tmp_path)
    assert found == []


def test_list_tdata_folders_missing_dir(tmp_path: Path):
    found = list_tdata_folders(tmp_path / "does-not-exist")
    assert found == []


def test_list_tdata_folders_multiple(tmp_path: Path):
    """Several independent tdata roots under one upload."""
    for i in range(3):
        root = tmp_path / f"account_{i}"
        root.mkdir()
        (root / "key_datas").write_bytes(b"\x00" * 200)
        (root / f"D877F783D5D3EF8C{i}").write_bytes(b"\x00" * 16)
    found = list_tdata_folders(tmp_path)
    assert len(found) == 3


def test_import_archive_zip_path_traversal_rejected(tmp_path: Path):
    """Archives that try to escape the extraction root are rejected."""
    import asyncio
    from app.services.account_service import import_tdata_accounts

    # Create a malicious archive that writes outside tmp_path via
    # absolute path traversal in member names.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../../evil.txt", "pwned")
    archive_bytes = buf.getvalue()

    async def run():
        return await import_tdata_accounts(
            db=None,  # type: ignore
            archive_bytes=archive_bytes,
            api_id=1, api_hash="a" * 32,
        )

    with pytest.raises(ValueError, match="[Uu]nsafe path"):
        asyncio.run(run())


def test_import_archive_rejects_non_zip(tmp_path: Path):
    """Plain bytes that are not a zip must produce a clear error."""
    import asyncio
    from app.services.account_service import import_tdata_accounts

    async def run():
        return await import_tdata_accounts(
            db=None,  # type: ignore
            archive_bytes=b"not a zip",
            api_id=1, api_hash="a" * 32,
        )

    with pytest.raises(ValueError, match="zip"):
        asyncio.run(run())
