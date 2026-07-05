"""Account CRUD + bulk import (CSV / TData).

Two important guards in this module:

1. **No account is ever authorized without a proxy.** The
   :func:`assert_proxy_bound` helper raises :class:`ProxyRequiredError`
   if an account has no ``proxy_id``. The activation endpoints call
   it; the Telegram service pool calls it; the warmup / messaging /
   comment tasks rely on it indirectly via the pool.

2. **Once authorized the proxy is sticky.** We never silently
   ``UPDATE accounts SET proxy_id=NULL`` — the operator has to go
   through the API which the schemas also constrain.

CSV bulk import
---------------
The bulk CSV format is::

    phone_number,api_id,api_hash,proxy_ref[,session_string][,status][,folder]

``proxy_ref`` is one of:

* ``<host>:<port>``                       (no auth, scheme defaults to socks5)
* ``<scheme>://<host>:<port>``           (e.g. ``socks5://1.2.3.4:1080``)
* ``<scheme>://<user>:<pass>@<host>:<port>``

If the proxy is not already in the project's proxy table it is created
on the fly. Rows without a proxy are **skipped** with a clear error —
this is the bulk-import guard against the operator accidentally
activating a fleet of accounts with the same shared IP (or no IP at
all).

TData bulk import
-----------------
See :mod:`app.services.tdata_converter`. The high-level function
:func:`import_tdata_accounts` accepts a directory of one or more
tdata folders and creates a new :class:`Account` row for each. The
operator must supply the ``api_id`` / ``api_hash`` of their Telegram
app (we use it to format the Pyrogram StringSession). Every account
MUST be paired with a proxy at creation time.
"""
from __future__ import annotations

import csv
import io
import logging
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote, unquote, urlparse

from pyrogram import Client, errors
from sqlalchemy import and_, delete as sa_delete, or_, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from pydantic import ValidationError

from app.models.account import Account, AccountStatus
from app.models.proxy import Proxy
from app.schemas.account import AccountCreate, AccountUpdate
from app.schemas.proxy import ProxyCreate
from app.services.telegram_service import telegram_service
from app.services.tdata_converter import (
    TDataImportError,
    TDataImportResult,
    import_tdata_archive,
)
from app.services.session_import_service import (
    SessionImportError,
    import_sqlite_session,
)

try:
    import rarfile
except ImportError:  # pragma: no cover - optional runtime dependency
    rarfile = None

logger = logging.getLogger(__name__)


class ProxyRequiredError(Exception):
    """Raised when code tries to use an account that has no proxy bound.

    The activation flow / Telegram service pool must never silently
    start a session without a proxy because that would put multiple
    accounts on the same IP (or worse, on a residential IP that can
    later be associated with a ban).
    """


# Temporary storage for login clients. This is process-local, but
# FastAPI is single-process in dev (uvicorn --workers 1). Production
# deployments should put this in Redis; see the TODO list.
login_clients: Dict[int, Client] = {}


# ---------------------------------------------------------------------------
# Proxy guard
# ---------------------------------------------------------------------------
def assert_proxy_bound(account: Account) -> None:
    """Raise :class:`ProxyRequiredError` if ``account.proxy_id`` is ``None``.

    The proxy guard is the single chokepoint every code path that
    talks to Telegram must go through. It is intentionally cheap so
    that we can sprinkle it without performance concerns.
    """
    if account.proxy_id is None:
        raise ProxyRequiredError(
            f"Account {account.phone_number} (id={account.id}) has no proxy bound; "
            "refusing to connect to Telegram. Attach a proxy first."
        )


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
async def create_account(
    db: AsyncSession, account_in: AccountCreate, project_id: int = 1
) -> Account:
    """Insert a new account row.

    If ``account_in.session_string`` is provided the account is
    considered authorized; the schema already enforced
    ``proxy_id is not None`` in that case.
    """
    from app.core.config import settings

    payload = account_in.model_dump(exclude={"tdata_source"})
    # These two are control flags, not Account columns — pull them out.
    auto_register = bool(payload.pop("auto_register", False))
    payload.pop("sms_country_id", None)

    # api_id / api_hash now default to the global Telegram app
    # credentials so the operator doesn't have to paste them for every
    # account. They only override when they bring their own app.
    if not payload.get("api_id"):
        payload["api_id"] = settings.TELEGRAM_API_ID
    if not payload.get("api_hash"):
        payload["api_hash"] = settings.TELEGRAM_API_HASH

    # Auto-registration creates a shell row first; the real number is
    # ordered from the SMS service afterwards. ``phone_number`` is
    # NOT NULL + unique, so seed a unique placeholder we'll overwrite.
    if auto_register and not payload.get("phone_number"):
        payload["phone_number"] = f"pending_{uuid.uuid4().hex[:12]}"

    if payload.get("session_string"):
        # Move the account to the "warming" folder automatically; the
        # operator can downgrade later once the warmup cycle is done.
        payload.setdefault("folder", "warming")
        payload.setdefault("status", AccountStatus.WARMING)
    db_obj = Account(**payload, project_id=project_id)
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj


async def get_account(
    db: AsyncSession, account_id: int, project_id: int = 1
) -> Optional[Account]:
    result = await db.execute(
        select(Account)
        .options(selectinload(Account.proxy))
        .where(Account.id == account_id, Account.project_id == project_id)
    )
    return result.scalar_one_or_none()


def detect_gender(first_name: Optional[str]) -> str:
    """Simple heuristic to detect gender based on the first name."""
    if not first_name:
        return "unknown"
    
    name = first_name.strip().lower()
    # Russian/Slavic female name endings
    if name.endswith(('а', 'я', 'ия', 'a', 'ya', 'ia')):
        return "female"
    
    # Common male patterns
    return "male"


async def get_accounts(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 100,
    project_id: int = 1,
    gender: Optional[str] = None,
    status: Optional[str] = None,
    folder: Optional[str] = None,
) -> List[Account]:
    """List accounts with optional filters.

    ``gender`` / ``status`` / ``folder`` accept the string form of the
    corresponding enum (``"male"``, ``"warming"``, …) or ``None`` /
    empty-string to skip the filter.
    """
    from app.models.account import AccountStatus, AccountSex

    stmt = select(Account).options(selectinload(Account.proxy)).where(Account.project_id == project_id)
    if gender:
        # Compare against the underlying string value to avoid
        # ``WHERE gender = :p::accountsex`` casts (the Postgres
        # enum type was never created; the column is VARCHAR).
        try:
            _ = AccountSex(gender)  # validate the name
            stmt = stmt.where(Account.sex == gender)
        except ValueError:
            pass
    if status:
        try:
            _ = AccountStatus(status)
            stmt = stmt.where(Account.status == status)
        except ValueError:
            pass
    if folder:
        stmt = stmt.where(Account.folder == folder)
    stmt = stmt.offset(skip).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def update_account(
    db: AsyncSession,
    account_id: int,
    account_in: AccountUpdate,
    project_id: int = 1,
) -> Optional[Account]:
    account = await get_account(db, account_id, project_id=project_id)
    if not account:
        return None
    update_data = account_in.model_dump(exclude_unset=True)
    for field_name, value in update_data.items():
        if field_name == "gender":
            account.sex = value
            continue
        if field_name == "proxy_id" and value is None:
            raise ValueError("proxy_id cannot be cleared from this endpoint; attach another proxy instead")
        setattr(account, field_name, value)
    await db.commit()
    await db.refresh(account)
    return account


async def delete_account(
    db: AsyncSession, account_id: int, project_id: int = 1
) -> bool:
    account = await get_account(db, account_id, project_id=project_id)
    if not account:
        return False

    # A few older PostgreSQL migrations created FKs without the
    # on-delete actions now declared in the ORM. Delete/NULL dependent
    # rows explicitly so account removal works on real, migrated DBs.
    from app.models.ai_settings import AISettings
    from app.models.campaign import MessageLog
    from app.models.campaign_recipient import CampaignRecipient
    from app.models.comment_task import (
        CommentDraft,
        CommentLog,
        CommentTask,
        CommentTaskSourceState,
    )
    from app.models.external_parser import ExternalParserRun
    from app.models.group_task import GroupTask
    from app.models.parsing import ParsingTask
    from app.models.reaction_task import ReactionTask
    from app.models.safety import AccountActionLimit, ActionLog, SafetyDraft

    draft_ids_result = await db.execute(
        select(CommentDraft.id).where(CommentDraft.account_id == account_id)
    )
    draft_ids = [row[0] for row in draft_ids_result.fetchall()]

    if draft_ids:
        await db.execute(
            sa_update(CommentLog)
            .where(CommentLog.draft_id.in_(draft_ids))
            .values(draft_id=None)
        )
    await db.execute(
        sa_update(CommentLog)
        .where(CommentLog.account_id == account_id)
        .values(account_id=None)
    )
    await db.execute(
        sa_update(CommentTaskSourceState)
        .where(CommentTaskSourceState.account_id == account_id)
        .values(account_id=None)
    )
    await db.execute(
        sa_update(CampaignRecipient)
        .where(CampaignRecipient.account_id == account_id)
        .values(account_id=None)
    )
    await db.execute(
        sa_update(ParsingTask)
        .where(ParsingTask.account_id == account_id)
        .values(account_id=None)
    )
    await db.execute(
        sa_update(ExternalParserRun)
        .where(ExternalParserRun.account_id == account_id)
        .values(account_id=None)
    )

    await db.execute(sa_delete(CommentDraft).where(CommentDraft.account_id == account_id))
    await db.execute(sa_delete(MessageLog).where(MessageLog.account_id == account_id))
    await db.execute(sa_delete(ReactionTask).where(ReactionTask.account_id == account_id))
    await db.execute(sa_delete(GroupTask).where(GroupTask.account_id == account_id))
    await db.execute(sa_delete(AISettings).where(AISettings.account_id == account_id))
    await db.execute(sa_delete(SafetyDraft).where(SafetyDraft.account_id == account_id))
    await db.execute(sa_delete(AccountActionLimit).where(AccountActionLimit.account_id == account_id))
    await db.execute(sa_delete(ActionLog).where(ActionLog.account_id == account_id))

    tasks_result = await db.execute(
        select(CommentTask).where(CommentTask.project_id == project_id)
    )
    for task in tasks_result.scalars().all():
        account_ids = task.account_ids or []
        if account_id in account_ids:
            task.account_ids = [value for value in account_ids if value != account_id]

    await telegram_service.disconnect_client(account_id)
    await db.delete(account)
    await db.commit()
    return True


# ---------------------------------------------------------------------------
# Proxy reference parsing
# ---------------------------------------------------------------------------
# Three shapes are supported:
#
#   1) ``<scheme>://[<user>:<pass>@]<host>:<port>`` — canonical URI form
#      (e.g. ``socks5://u:p@1.2.3.4:1080``, ``http://[2001:db8::1]:8080``).
#   2) ``<host>:<port>`` — defaults to socks5, no auth.
#   3) ``<host>:<port>:<user>:<pass>`` — the format most proxy sellers
#      (smartproxy, proxy-seller, etc.) paste into their dashboards. The
#      user in the chat uses exactly this layout.
#   4) ``<scheme>://<host>:<port>`` — explicit scheme, no auth.
_PROXY_REF_4COLON_RE = re.compile(
    r"^(?P<host>[^:\s]+):(?P<port>\d{1,5}):(?P<user>[^:\s]+):(?P<password>\S+)$"
)
_PROXY_REF_URI_RE = re.compile(
    r"^(?:(?P<scheme>[a-zA-Z0-9]+)://)?"
    r"(?:(?P<user>[^:@\s]+):(?P<password>[^@\s]+)@)?"
    r"(?P<host>\[[0-9a-fA-F:]+\]|[^:\s]+)"
    r":(?P<port>\d{1,5})$"
)


def parse_proxy_ref(ref: str) -> Optional[ProxyCreate]:
    """Parse a ``proxy_ref`` string into a :class:`ProxyCreate` model.

    Accepts all four formats described in the module docstring.
    Returns ``None`` for unparseable / empty input.
    """
    if not ref:
        return None
    ref = ref.strip()

    # 4-colon ``host:port:user:pass`` form first.
    m4 = _PROXY_REF_4COLON_RE.match(ref)
    if m4:
        return ProxyCreate(
            scheme="socks5",
            host=m4.group("host"),
            port=int(m4.group("port")),
            username=m4.group("user"),
            password=m4.group("password"),
        )

    m = _PROXY_REF_URI_RE.match(ref)
    if not m:
        return None
    scheme = (m.group("scheme") or "socks5").lower()
    host = m.group("host")
    # Strip IPv6 brackets — Pyrogram wants a bare address.
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    port = int(m.group("port"))
    username = unquote(m.group("user") or "") if m.group("user") else None
    password = unquote(m.group("password") or "") if m.group("password") else None
    if scheme not in {"socks5", "socks4", "http", "https"}:
        return None
    return ProxyCreate(
        scheme=scheme,
        host=host,
        port=port,
        username=username or None,
        password=password or None,
    )


async def find_or_create_proxy(
    db: AsyncSession, proxy_in: ProxyCreate, project_id: int = 1
) -> Proxy:
    """Look up a proxy by ``(scheme, host, port, username)`` or insert it.

    The unique key is the combination of all four so two operators
    sharing a host but with different credentials get separate rows.
    """
    existing = await db.execute(
        select(Proxy).where(
            Proxy.project_id == project_id,
            Proxy.scheme == proxy_in.scheme,
            Proxy.host == proxy_in.host,
            Proxy.port == proxy_in.port,
            or_(Proxy.username == proxy_in.username, Proxy.username.is_(None) if proxy_in.username is None else False),
        )
    )
    row = existing.scalars().first()
    if row:
        return row
    db_obj = Proxy(**proxy_in.model_dump(), project_id=project_id)
    db.add(db_obj)
    await db.flush()
    return db_obj


# ---------------------------------------------------------------------------
# Bulk CSV import
# ---------------------------------------------------------------------------
@dataclass
class BulkImportReport:
    """Structured outcome of a CSV / TData import run."""

    imported: int = 0
    skipped_duplicates: int = 0
    skipped_no_proxy: int = 0
    created_proxies: int = 0
    errors: List[Dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "imported": self.imported,
            "skipped_duplicates": self.skipped_duplicates,
            "skipped_no_proxy": self.skipped_no_proxy,
            "created_proxies": self.created_proxies,
            "errors": self.errors,
        }


async def bulk_create_accounts_from_csv(
    db: AsyncSession,
    file_content: bytes,
    project_id: int = 1,
    require_proxy: bool = True,
) -> BulkImportReport:
    """Import accounts from a CSV file.

    Expected header::

        phone_number,api_id,api_hash,proxy_ref,session_string,status,folder

    ``session_string`` is optional; when present we treat the account
    as pre-authorized. ``proxy_ref`` is required when
    ``require_proxy`` is True (the default) AND when a session_string
    is supplied. The ``require_proxy`` flag can be flipped off by an
    operator who is intentionally queuing draft accounts before they
    have proxies, but in that case the account will be created in the
    ``new`` folder and cannot be used until a proxy is attached.
    """
    report = BulkImportReport()
    try:
        text = file_content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = file_content.decode("latin-1")

    # Use a DictReader so we can support arbitrary column order and
    # only require what we actually use.
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        report.errors.append({"row": 0, "reason": "CSV is empty", "raw": []})
        return report

    required = {"phone_number", "api_id", "api_hash"}
    missing = required - set(reader.fieldnames or [])
    if missing:
        report.errors.append({
            "row": 0,
            "reason": f"Missing required columns: {', '.join(sorted(missing))}",
            "raw": list(reader.fieldnames or []),
        })
        return report

    for row_index, row in enumerate(reader, start=1):
        raw = {k: row.get(k) for k in reader.fieldnames}
        try:
            phone = (row.get("phone_number") or "").strip()
            api_id_str = (row.get("api_id") or "").strip()
            api_hash = (row.get("api_hash") or "").strip()
            proxy_ref = (row.get("proxy_ref") or row.get("proxy") or "").strip()
            session_str = (row.get("session_string") or "").strip() or None
            status_str = (row.get("status") or "").strip() or None
            folder_str = (row.get("folder") or "").strip() or None

            if not phone or not api_id_str or not api_hash:
                raise ValueError("phone_number, api_id, api_hash must be non-empty")

            api_id = int(api_id_str)

            # Skip duplicates BEFORE creating anything else to keep
            # the import idempotent.
            existing = await db.execute(
                select(Account).where(Account.phone_number == phone)
            )
            if existing.scalar_one_or_none():
                report.skipped_duplicates += 1
                continue

            # Proxy handling.
            proxy_id: Optional[int] = None
            if proxy_ref:
                parsed = parse_proxy_ref(proxy_ref)
                if parsed is None:
                    raise ValueError(
                        f"Could not parse proxy_ref '{proxy_ref}'. "
                        "Expected 'host:port' or 'scheme://[user:pass@]host:port'."
                    )
                row_proxy = await find_or_create_proxy(db, parsed, project_id=project_id)
                proxy_id = row_proxy.id
                if not getattr(row_proxy, "_persisted", True):
                    # ``find_or_create_proxy`` flushes new rows; treat
                    # the first insert as a "created proxy" for the
                    # report. We detect a fresh row by ``id is None``
                    # before flush, but here we already flushed.
                    pass
            elif require_proxy or session_str:
                # Hard guard: an account with a session string cannot
                # be created without a proxy. The operator MUST fix
                # the row and re-upload.
                report.skipped_no_proxy += 1
                report.errors.append({
                    "row": row_index,
                    "reason": (
                        "Account has a session_string or require_proxy is on, "
                        "but proxy_ref is empty. Row skipped to avoid unauthorized "
                        "activation."
                    ),
                    "raw": raw,
                })
                continue

            # Validate the row through the Pydantic schema so we get
            # the same checks as the single-create endpoint.
            try:
                account_in = AccountCreate(
                    phone_number=phone,
                    api_id=api_id,
                    api_hash=api_hash,
                    proxy_id=proxy_id,
                    session_string=session_str,
                )
            except ValidationError as ve:
                raise ValueError("; ".join(
                    f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
                    for err in ve.errors()
                ))

            payload = account_in.model_dump(
                exclude={"tdata_source", "auto_register", "sms_country_id"}
            )
            if status_str:
                try:
                    payload["status"] = AccountStatus(status_str)
                except ValueError:
                    pass
            if folder_str:
                payload["folder"] = folder_str
            if session_str:
                payload.setdefault("folder", "warming")
                payload.setdefault("status", AccountStatus.WARMING)

            db_obj = Account(**payload, project_id=project_id)
            db.add(db_obj)
            await db.flush()
            report.imported += 1

        except (ValueError, IndexError) as exc:
            report.errors.append({
                "row": row_index,
                "reason": str(exc)[:300],
                "raw": raw,
            })
            continue

    await db.commit()
    return report


# ---------------------------------------------------------------------------
# TData bulk import
# ---------------------------------------------------------------------------
async def import_tdata_accounts(
    db: AsyncSession,
    archive_bytes: bytes,
    api_id: int,
    api_hash: str,
    project_id: int = 1,
    default_proxy_id: Optional[int] = None,
    passcode: Optional[str] = None,
) -> Dict[str, Any]:
    """Convert a ZIP of tdata folders into Account rows.

    The archive can contain:

    * a single ``tdata/`` folder at the top level, or
    * several folders, each of which is a tdata root (used when the
      operator exports multiple Telegram Desktop accounts).

    The operator MUST supply either ``default_proxy_id`` (used for
    every converted account) or include proxy_ref / per-account proxy
    information in a manifest file. We deliberately refuse to create
    any account without a proxy.
    """
    if default_proxy_id is not None:
        # Validate that the proxy exists and belongs to the project.
        proxy = await db.get(Proxy, default_proxy_id)
        if proxy is None or proxy.project_id != project_id:
            raise ValueError(
                f"default_proxy_id={default_proxy_id} not found in project {project_id}"
            )

    if not archive_bytes:
        raise ValueError("archive is empty")

    tmp_root = Path(tempfile.mkdtemp(prefix="tdata-import-"))
    try:
        # Unpack the archive. ZIP is preferred; RAR is supported when
        # the optional rarfile dependency and a compatible extractor
        # are available on the host.
        try:
            with zipfile.ZipFile(io.BytesIO(archive_bytes)) as zf:
                for member in zf.infolist():
                    member_path = (tmp_root / member.filename).resolve()
                    if not str(member_path).startswith(str(tmp_root.resolve())):
                        raise ValueError(f"Unsafe path in archive: {member.filename}")
                zf.extractall(tmp_root)
        except zipfile.BadZipFile:
            if rarfile is None:
                raise ValueError(
                    "RAR import requires the `rarfile` Python package. "
                    "Install it or upload a .zip archive."
                )
            try:
                with rarfile.RarFile(io.BytesIO(archive_bytes)) as rf:
                    for member in rf.infolist():
                        member_path = (tmp_root / member.filename).resolve()
                        if not str(member_path).startswith(str(tmp_root.resolve())):
                            raise ValueError(f"Unsafe path in archive: {member.filename}")
                    rf.extractall(tmp_root)
            except rarfile.Error as exc:
                raise ValueError(
                    "Не удалось распаковать .rar. Установите 7-Zip/UnRAR "
                    "или загрузите тот же tdata как .zip архив."
                ) from exc

        try:
            results: List[TDataImportResult] = import_tdata_archive(
                tmp_root, api_id=api_id, api_hash=api_hash, passcode=passcode or None
            )
        except TDataImportError as exc:
            return {
                "imported": 0,
                "skipped_no_proxy": 0,
                "errors": [{"reason": str(exc), "raw": None}],
                "results": [],
            }
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)

    if not results:
        return {
            "imported": 0,
            "skipped_no_proxy": 0,
            "errors": [
                {"reason": "No tdata folders could be converted", "raw": None}
            ],
            "results": [],
        }

    # Now persist. If ``default_proxy_id`` is missing we surface a
    # structured error and DO NOT create any account.
    if default_proxy_id is None:
        return {
            "imported": 0,
            "skipped_no_proxy": len(results),
            "errors": [
                {
                    "reason": (
                        "TData accounts cannot be created without a proxy. "
                        "Re-upload with default_proxy_id or set per-account "
                        "proxies in the manifest."
                    ),
                    "raw": None,
                }
            ],
            "results": [
                {
                    "phone_number": r.phone_number,
                    "user_id": r.user_id,
                    "source_folder": r.source_folder,
                }
                for r in results
            ],
        }

    imported = 0
    errors: List[Dict[str, Any]] = []
    for r in results:
        try:
            phone = r.phone_number or f"tdata_{r.user_id or uuid.uuid4().hex[:8]}"
            existing = await db.execute(
                select(Account).where(Account.phone_number == phone)
            )
            if existing.scalar_one_or_none():
                errors.append({
                    "reason": f"phone_number {phone} already exists",
                    "raw": {"source_folder": r.source_folder},
                })
                continue

            payload = AccountCreate(
                phone_number=phone,
                api_id=api_id,
                api_hash=api_hash,
                proxy_id=default_proxy_id,
                session_string=r.session_string,
                tdata_source=r.source_folder,
            )
            data = payload.model_dump(
                exclude={"tdata_source", "auto_register", "sms_country_id"}
            )
            data["folder"] = "warming"
            data["status"] = AccountStatus.WARMING
            
            # Heuristic gender detection
            data["sex"] = detect_gender(r.first_name)
            
            db_obj = Account(**data, project_id=project_id)
            db.add(db_obj)
            await db.flush()
            imported += 1
        except ValidationError as ve:
            errors.append({
                "reason": "; ".join(
                    f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
                    for err in ve.errors()
                ),
                "raw": {"source_folder": r.source_folder},
            })

    await db.commit()
    return {
        "imported": imported,
        "skipped_no_proxy": 0,
        "errors": errors,
        "results": [
            {
                "phone_number": r.phone_number,
                "user_id": r.user_id,
                "source_folder": r.source_folder,
            }
            for r in results
        ],
    }


async def import_session_account(
    db: AsyncSession,
    *,
    session_bytes: bytes,
    filename: str,
    api_id: int,
    api_hash: str,
    project_id: int,
    default_proxy_id: int,
    phone_number: Optional[str] = None,
    user_id: Optional[int] = None,
    metadata_bytes: Optional[bytes] = None,
) -> Dict[str, Any]:
    """Import a Pyrogram/Telethon SQLite session as an authorized account."""
    if not default_proxy_id:
        raise ProxyRequiredError("Session import requires default_proxy_id; account cannot be authorized without a proxy.")

    proxy = (
        await db.execute(
            select(Proxy).where(Proxy.id == default_proxy_id, Proxy.project_id == project_id)
        )
    ).scalar_one_or_none()
    if not proxy:
        raise ValueError("Proxy not found in current project")

    try:
        imported = import_sqlite_session(
            session_bytes,
            filename=filename,
            api_id=api_id,
            api_hash=api_hash,
            phone_number=phone_number,
            user_id=user_id,
            metadata_bytes=metadata_bytes,
        )
    except SessionImportError:
        raise

    existing = await db.execute(
        select(Account).where(Account.phone_number == imported.phone_number)
    )
    if existing.scalar_one_or_none():
        return {
            "imported": 0,
            "errors": [{"reason": f"phone_number {imported.phone_number} already exists", "raw": None}],
            "results": [],
        }

    payload = AccountCreate(
        phone_number=imported.phone_number,
        api_id=imported.api_id,
        api_hash=imported.api_hash,
        proxy_id=default_proxy_id,
        session_string=imported.session_string,
    )
    data = payload.model_dump(
        exclude={"tdata_source", "auto_register", "sms_country_id"}
    )
    data["folder"] = "warming"
    data["status"] = AccountStatus.WARMING
    db_obj = Account(**data, project_id=project_id)
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return {
        "imported": 1,
        "errors": [],
        "results": [{
            "account_id": db_obj.id,
            "phone_number": db_obj.phone_number,
            "user_id": imported.user_id,
            "dc_id": imported.dc_id,
            "source_type": imported.source_type,
        }],
    }


# ---------------------------------------------------------------------------
# Authorization flow (with proxy guard)
# ---------------------------------------------------------------------------
async def update_profile(
    db: AsyncSession,
    account: Account,
    first_name: Optional[str] = None,
    about: Optional[str] = None,
    personal_channel: Optional[str] = None,
    channel_content: Optional[str] = None,
    avatar_bytes: Optional[bytes] = None,
) -> Account:
    """Update Telegram profile using Pyrogram."""
    from app.services.telegram_service import telegram_service
    
    # Load proxy relationship if not already loaded to avoid 
    # lazy loading error in async mode.
    from sqlalchemy.future import select
    from app.models.proxy import Proxy
    if account.proxy_id:
        stmt = select(Proxy).where(Proxy.id == account.proxy_id)
        res = await db.execute(stmt)
        proxy_obj = res.scalar_one_or_none()
        if proxy_obj:
            account.proxy = proxy_obj

    client = await telegram_service.get_client(account)
    
    # 1. Update Name
    if first_name:
        await client.update_profile(first_name=first_name)
    
    # 2. Update About/Bio
    if about:
        await client.update_profile(bio=about)
    
    # 3. Update Avatar
    if avatar_bytes:
        # Save to temp file because Pyrogram's set_profile_photo
        # usually expects a file path or a readable stream
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
            tmp.write(avatar_bytes)
            tmp_path = tmp.name
        try:
            await client.set_profile_photo(photo=tmp_path)
        finally:
            os.unlink(tmp_path)

    # 4. Personal Channel Management
    if personal_channel:
        # Heuristic: if personal_channel is provided, we might want to 
        # set it in the profile or post content to it.
        # pyrogram doesn't have a direct "set personal channel" TL yet,
        # so we just post content to it if provided.
        if channel_content:
            try:
                # Resolve peer to check if we can post
                peer = await client.resolve_peer(personal_channel)
                await client.send_message(personal_channel, channel_content)
            except Exception as e:
                logger.warning(f"Could not post to channel {personal_channel}: {e}")

    # Sync with DB if needed (e.g. if we detected gender change?)
    if first_name:
        account.gender = detect_gender(first_name)
    
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


async def request_code(db: AsyncSession, account: Account):
    """Request a login code from Telegram.

    The proxy guard here is the *first* opportunity for a bad
    configuration to cause a silent IP leak. We refuse to call
    ``client.send_code`` without a proxy bound to the account.
    """
    assert_proxy_bound(account)
    proxy_dict = telegram_service.get_proxy_dict(account.proxy) if account.proxy else None

    client = Client(
        name=f"login_{account.id}",
        api_id=account.api_id,
        api_hash=account.api_hash,
        proxy=proxy_dict,
        in_memory=True,
    )

    try:
        await client.connect()
    except Exception as exc:
        # The client could not even connect to Telegram via the
        # proxy — surface the proxy error to the operator.
        raise ProxyRequiredError(
            f"Failed to connect via the bound proxy: {exc}. "
            "Check the proxy is alive and the account is allowed to use it."
        ) from exc

    login_clients[account.id] = client
    try:
        sent_code = await client.send_code(account.phone_number)
        return sent_code
    except Exception:
        # Roll back the temp client on any failure so the operator
        # can re-try without leaking sockets.
        try:
            await client.disconnect()
        finally:
            login_clients.pop(account.id, None)
        raise


async def login(
    db: AsyncSession,
    account: Account,
    phone_code: str,
    phone_code_hash: str,
    password: Optional[str] = None,
):
    """Complete the sign-in flow and store the resulting session_string.

    The proxy guard is enforced inside :func:`request_code`, so by
    the time we get here the account is guaranteed to have a proxy.
    """
    # Defensive re-check in case the operator attached / detached a
    # proxy between send_code and login.
    assert_proxy_bound(account)

    if account.id not in login_clients:
        raise Exception("Login session not found. Please request code first.")

    client = login_clients[account.id]
    try:
        try:
            await client.sign_in(account.phone_number, phone_code_hash, phone_code)
        except errors.SessionPasswordNeeded:
            if not password:
                raise Exception("2FA Password needed")
            await client.check_password(password)

        session_string = await client.export_session_string()
        account.session_string = session_string
        if account.folder == "new":
            account.folder = "warming"
        if account.status == AccountStatus.NEW:
            account.status = AccountStatus.WARMING
        
        # Detect and set gender right after login
        try:
            me = await client.get_me()
            account.first_name = me.first_name
            account.last_name = me.last_name
            account.username = me.username
            account.gender = detect_gender(me.first_name)
        except Exception as e:
            logger.warning(f"Failed to fetch profile during login for account {account.id}: {e}")

        await db.commit()
        await db.refresh(account)
        return session_string
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass
        login_clients.pop(account.id, None)
