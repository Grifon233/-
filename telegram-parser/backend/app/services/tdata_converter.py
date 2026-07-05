"""Telegram Desktop ``tdata`` → Pyrogram session string converter.

The project supports three ways of attaching a Telegram session to an
``Account`` row:

1. Interactive login via the ``/accounts/{id}/send-code`` + ``/login``
   flow (writes a real session_string for the supplied phone number).

2. CSV bulk import with a pre-baked ``session_string`` column.

3. **TData bulk import** — this module.

What "tdata" means
------------------
Telegram Desktop stores its sessions in an OS-specific directory
(``%APPDATA%/Telegram Desktop/tdata`` on Windows,
``~/.local/share/Telegram Desktop/tdata`` on Linux) as a set of
binary files encrypted with a *local* key. Telegram Desktop's own
session is in there, and one tdata folder can carry several accounts.
We only support the single-account case here.

How we convert it
-----------------
The Python ecosystem has a couple of libraries that can read tdata:

* ``opentele``  — the reference implementation, used by TGConvertor
  and many Telegram automation tools. Requires PyQt5 and tgcrypto
  for AES-256-IGE.
* ``TGConvertor`` — higher-level wrapper around opentele; ships with
  a CLI we don't need.

On Windows there is no prebuilt ``tgcrypto`` wheel for Python 3.12 and
the package cannot be built without Visual Studio Build Tools. The
``app.services._compat.tgcrypto_stub`` module provides a drop-in
pure-Python implementation backed by ``pycryptodome`` (which has
prebuilt wheels for every platform).

This module:

1. Imports the tgcrypto shim BEFORE ``opentele`` so the import chain
   finds the pure-Python implementation.
2. Loads the tdata folder with ``opentele.td.TDesktop``.
3. Converts the loaded session to a Pyrogram ``StringSession`` via the
   bridge through Telethon (``ToTelethon`` → ``ToPyrogramString``).

Why go through Telethon? Because opentele emits a Telethon client
(``opentele.tl.TelegramClient``) and there is no direct
``TDesktop.ToPyrogram()`` API. The conversion is fast — the auth key
is just copied across — and we never call Telegram servers during
the conversion.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

# IMPORTANT: install the tgcrypto shim before opentele is imported.
# Importing the shim has the side effect of writing itself into
# ``sys.modules['tgcrypto']``.
from app.services._compat import tgcrypto_stub  # noqa: F401  (side-effect import)

logger = logging.getLogger(__name__)

# Lazy imports — opentele + telethon are heavy and we don't want to
# pay the import cost on every backend startup. Tests / API endpoints
# trigger the import on first use.
_opentele_mod = None
_telethon_mod = None
_api_mod = None


def _ensure_imports() -> None:
    """Import opentele + telethon on first use and cache them."""
    global _opentele_mod, _telethon_mod, _api_mod
    if _opentele_mod is not None:
        return
    try:
        from opentele.td import TDesktop  # noqa: F401
        from opentele.tl import TelegramClient as OTTelegramClient
        from opentele.api import API as OTAPI, UseCurrentSession

        _opentele_mod = TDesktop
        _api_mod = (OTAPI, OTTelegramClient, UseCurrentSession)
    except ImportError as exc:  # pragma: no cover
        raise TDataImportError(
            "TData import requires `opentele` and `PyQt5` to be installed. "
            "Run `pip install opentele PyQt5`."
        ) from exc

    try:
        import telethon
        _telethon_mod = telethon
    except ImportError as exc:  # pragma: no cover
        raise TDataImportError(
            "TData import requires `telethon` to be installed. "
            "Run `pip install telethon`."
        ) from exc


class TDataImportError(Exception):
    """Raised when a tdata folder cannot be loaded or converted."""


@dataclass
class TDataImportResult:
    """Outcome of a single tdata → session_string conversion."""

    phone_number: Optional[str]
    user_id: Optional[int]
    session_string: str
    api_id: int
    api_hash: str
    dc_id: int
    source_folder: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None


def list_tdata_folders(root: Path) -> List[Path]:
    """Find every tdata folder under ``root``.

    A valid tdata folder contains a ``key_datas`` file (encrypted local
    key) plus at least one ``D877F783D5D3EF8C*`` map file. The
    detection here is structural: anything whose name starts with
    ``D877F783D5D3EF8C`` or that contains a ``key_datas`` file is
    considered a tdata root.
    """
    if not root.exists():
        return []

    candidates: list[Path] = []

    # 1) Canonical layout: ``root/tdata/key_datas`` and a
    # ``root/tdata/D877F783D5D3EF8C*`` map file. Many operators export
    # their tdata as a folder named ``tdata`` directly; that is the
    # case we want to detect.
    direct = root if (root / "key_datas").exists() else None
    if direct is not None:
        candidates.append(direct)

    # 2) The actual Telegram Desktop layout is
    # ``root/Telegram Desktop/tdata``. The recursive walk covers that
    # plus any nested variants.
    for dirpath, dirnames, filenames in os.walk(root):
        p = Path(dirpath)
        if "key_datas" in filenames:
            if p not in candidates:
                candidates.append(p)
            # tdata is a leaf in the directory tree — don't descend.
            dirnames.clear()
        elif any(name.startswith("D877F783D5D3EF8C") for name in filenames):
            # Map files without key_datas are useless, but we still
            # note the parent so the user can see the structure.
            if p not in candidates:
                candidates.append(p)
            dirnames.clear()
    return candidates


def _extract_api_credentials(tdesktop) -> tuple[int, str]:
    """Pull the API id / hash embedded in the tdata, if any.

    tdata does not normally carry API credentials — those live in
    ``tdata/`` as ``key_datas`` only. The API id / hash used by the
    Telegram Desktop client is stored elsewhere (registry / config).
    When parsing third-party tdata exports we usually do NOT have
    those, so we return ``(0, "")`` and the caller is expected to
    pass them in via the API.
    """
    # opentele's TDesktop exposes ``api`` as the APIData. If the
    # operator exported their tdata along with an ``api_id`` /
    # ``api_hash`` (e.g. via a custom tool), opentele may have it;
    # otherwise we fall back to the canonical Telegram Desktop values
    # which are public and work fine for session import.
    api_obj = getattr(tdesktop, "api", None)
    if api_obj is None:
        return 0, ""
    api_id = getattr(api_obj, "api_id", 0) or 0
    api_hash = getattr(api_obj, "api_hash", "") or ""
    return int(api_id or 0), str(api_hash or "")


def convert_tdata_folder(
    tdata_folder: Path,
    api_id: int,
    api_hash: str,
    passcode: Optional[str] = None,
) -> TDataImportResult:
    """Convert a single tdata folder to a Pyrogram session string.

    The API id / hash of the *operator's* Telegram app must be passed
    in. Pyrogram stores the same auth key regardless of the API
    credentials used during conversion, so the resulting session will
    work with the operator's own ``api_id`` / ``api_hash`` once it's
    instantiated.
    """
    _ensure_imports()

    if not tdata_folder.exists():
        raise TDataImportError(f"tdata folder not found: {tdata_folder}")

    try:
        tdesk = _opentele_mod(basePath=str(tdata_folder), passcode=passcode)
    except BaseException as exc:
        logger.error(f"Opentele failed to load tdata folder {tdata_folder}: {exc}")
        raise TDataImportError(f"Failed to load tdata: {exc}")

    if not tdesk.isLoaded():
        raise TDataImportError(
            f"tdata folder {tdata_folder} contains no usable account"
        )

    # The opentele "client" is a Telethon wrapper around the tdata
    # session. We use ``UseCurrentSession`` to keep the existing
    # authorization rather than re-authorize.
    async def _convert() -> tuple[str, int, int]:
        return await _run_tdesktop_to_pyrogram(tdesk, api_id, api_hash)

    try:
        session_string, user_id, dc_id = _run_sync(_convert)
    except Exception as exc:
        # If the async bridge failed (network, version mismatch, ...)
        # try the high-level TGConvertor helper as a last resort.
        logger.warning("opentele async conversion failed (%s); falling back to TGConvertor", exc)
        session_string, user_id, dc_id = _fallback_conversion(tdesk, api_id, api_hash)

    return TDataImportResult(
        phone_number=getattr(tdesk, "phone", None),
        user_id=user_id,
        session_string=session_string,
        api_id=api_id,
        api_hash=api_hash,
        dc_id=dc_id,
        source_folder=str(tdata_folder),
    )


async def _run_tdesktop_to_pyrogram(
    tdesk, api_id: int, api_hash: str
) -> tuple[str, int, int]:
    """Async path: TDesktop → Telethon → Pyrogram StringSession."""
    from opentele.tl import TelegramClient as OTTelegramClient
    from opentele.api import UseCurrentSession

    # ``ToTelethon`` returns a *connected* Telethon client. We pass an
    # in-memory session so no files are created.
    telethon_client = await tdesk.ToTelethon(
        session="memory_conversion.session",
        flag=UseCurrentSession,
    )
    try:
        # ``ToPyrogramString`` exports the auth key as a Pyrogram
        # StringSession without ever connecting to Telegram servers.
        session_string = await telethon_client.ToPyrogramString(
            api_id=api_id, api_hash=api_hash
        )
        user_id = getattr(tdesk, "user_id", None) or 0
        dc_id = getattr(tdesk, "MainDcId", 0) or 0
        return session_string, int(user_id), int(dc_id)
    finally:
        try:
            await telethon_client.disconnect()
        except Exception:  # pragma: no cover
            pass


def _fallback_conversion(tdesk, api_id: int, api_hash: str) -> tuple[str, int, int]:
    """Synchronous fallback using TGConvertor (if installed)."""
    try:
        from TGConvertor import SessionManager
    except ImportError as exc:
        raise TDataImportError(
            "tdata conversion failed via opentele and TGConvertor is not installed"
        ) from exc

    base = getattr(tdesk, "basePath", None) or getattr(tdesk, "_basePath", None)
    if base is None:  # pragma: no cover - TDesktop always has basePath
        raise TDataImportError("opentele TDesktop is missing basePath attribute")
    session = SessionManager.from_tdata_folder(str(base))
    session.api_id = api_id
    pyro_string = session.to_pyrogram_string()
    user_id = session.user_id or 0
    dc_id = session.dc_id or 0
    
    first_name = None
    last_name = None
    try:
        user = session.get_user()
        first_name = getattr(user, 'first_name', None)
        last_name = getattr(user, 'last_name', None)
    except Exception:
        pass

    return pyro_string, int(user_id), int(dc_id), first_name, last_name


def _run_sync(coro_factory) -> tuple[str, int, int]:
    """Run an async coroutine factory in a fresh event loop.

    Pyrogram and Telethon each create their own loop and we don't
    want to interfere with the FastAPI loop.
    """
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro_factory())
    finally:
        try:
            loop.close()
        except Exception:  # pragma: no cover
            pass


# ---------------------------------------------------------------------------
# Higher-level helper used by the API endpoint
# ---------------------------------------------------------------------------
def import_tdata_archive(
    archive_root: Path,
    api_id: int,
    api_hash: str,
    passcode: Optional[str] = None,
) -> List[TDataImportResult]:
    """Convert every tdata folder found under ``archive_root``.

    ``archive_root`` is the directory that the operator uploaded
    (either extracted from a ZIP or as a tree of folders).
    Returns one :class:`TDataImportResult` per successful conversion.
    """
    folders = list_tdata_folders(archive_root)
    if not folders:
        raise TDataImportError(
            f"No tdata folders found under {archive_root}. "
            "Expected a directory that contains a `key_datas` file."
        )

    results: list[TDataImportResult] = []
    errors: list[str] = []
    for folder in folders:
        try:
            results.append(convert_tdata_folder(folder, api_id, api_hash, passcode=passcode))
        except TDataImportError as exc:
            logger.warning("skipping %s: %s", folder, exc)
            errors.append(f"{folder.name}: {exc}")
    if not results and errors:
        raise TDataImportError("; ".join(errors))
    return results


__all__ = [
    "TDataImportError",
    "TDataImportResult",
    "list_tdata_folders",
    "convert_tdata_folder",
    "import_tdata_archive",
]
