"""Proxy CRUD + bulk paste import + vendor sync.

Two key entry points:
* :func:`bulk_create_proxies_from_paste` — the operator pastes a
  blob of ``host:port:user:pass`` / ``scheme://...`` lines; each
  line is parsed and inserted.
* :func:`bulk_create_proxies_from_csv` — legacy CSV path used by
  the old ``/proxies/bulk-upload`` endpoint.

The plain CRUD functions (``create_proxy``, ``update_proxy`` etc.)
are also kept here so the REST endpoints in
:mod:`app.api.endpoints.proxies` keep working after the
2026-06-07 refactor.
"""
from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass, field
from typing import Any, List, Optional

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import or_

from app.models.proxy import Proxy
from app.schemas.proxy import ProxyCreate, ProxyUpdate
from app.services.account_service import parse_proxy_ref

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
async def create_proxy(
    db: AsyncSession, proxy_in: ProxyCreate, project_id: int = 1
) -> Proxy:
    db_obj = Proxy(**proxy_in.model_dump(), project_id=project_id)
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj


async def get_proxy(
    db: AsyncSession, proxy_id: int, project_id: int = 1
) -> Optional[Proxy]:
    result = await db.execute(
        select(Proxy).where(Proxy.id == proxy_id, Proxy.project_id == project_id)
    )
    return result.scalar_one_or_none()


async def get_proxies(
    db: AsyncSession, skip: int = 0, limit: int = 100, project_id: int = 1
) -> list[Proxy]:
    result = await db.execute(
        select(Proxy).where(Proxy.project_id == project_id).offset(skip).limit(limit)
    )
    return list(result.scalars().all())


async def update_proxy(
    db: AsyncSession,
    proxy_id: int,
    proxy_in: ProxyUpdate,
    project_id: int = 1,
) -> Optional[Proxy]:
    proxy = await get_proxy(db, proxy_id, project_id=project_id)
    if not proxy:
        return None
    update_data = proxy_in.model_dump(exclude_unset=True)
    for field_name, value in update_data.items():
        setattr(proxy, field_name, value)
    await db.commit()
    await db.refresh(proxy)
    return proxy


async def delete_proxy(
    db: AsyncSession, proxy_id: int, project_id: int = 1
) -> bool:
    proxy = await get_proxy(db, proxy_id, project_id=project_id)
    if not proxy:
        return False
    await db.delete(proxy)
    await db.commit()
    return True


@dataclass
class ProxyBulkReport:
    imported: int = 0
    duplicates: int = 0
    errors: List[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "imported": self.imported,
            "duplicates": self.duplicates,
            "errors": self.errors,
        }


async def _find_existing_proxy(
    db: AsyncSession,
    *,
    scheme: str,
    host: str,
    port: int,
    username: Optional[str],
    project_id: int,
) -> Optional[Proxy]:
    """Match a proxy by (scheme, host, port, username).

    First tries an exact match including username/scheme.  If that fails,
    falls back to host+port only so that pasting a proxy without credentials
    doesn't duplicate a row that was previously imported via vendor sync
    (which adds a username).
    """
    q = select(Proxy).where(
        Proxy.project_id == project_id,
        Proxy.scheme == scheme,
        Proxy.host == host,
        Proxy.port == port,
    )
    if username:
        q = q.where(Proxy.username == username)
    else:
        q = q.where(or_(Proxy.username.is_(None), Proxy.username == ""))
    result = (await db.execute(q)).scalars().first()
    if result:
        return result
    # Fallback: match by host+port only to prevent duplicates when the
    # same proxy was previously imported with different credentials.
    return (await db.execute(
        select(Proxy).where(
            Proxy.project_id == project_id,
            Proxy.host == host,
            Proxy.port == port,
        )
    )).scalars().first()


async def bulk_create_proxies_from_paste(
    db: AsyncSession,
    text: str,
    project_id: int = 1,
    *,
    default_source: str = "pasted",
    default_vendor: Optional[str] = None,
) -> ProxyBulkReport:
    """Parse ``text`` (one proxy per line) and insert each row.

    Supported formats are exactly the ones :func:`parse_proxy_ref`
    understands; lines that fail to parse are collected in the
    ``errors`` array of the returned report.
    """
    report = ProxyBulkReport()
    seen_keys: set[tuple[str, str, int, Optional[str]]] = set()

    for index, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            parsed = parse_proxy_ref(line)
        except Exception:
            parsed = None
        if parsed is None:
            report.errors.append({
                "row": index,
                "reason": f"could not parse line: {line!r}",
                "raw": line,
            })
            continue

        dedup_key = (parsed.scheme, parsed.host, parsed.port, parsed.username)
        if dedup_key in seen_keys:
            report.duplicates += 1
            continue
        seen_keys.add(dedup_key)

        existing = await _find_existing_proxy(
            db,
            scheme=parsed.scheme,
            host=parsed.host,
            port=parsed.port,
            username=parsed.username,
            project_id=project_id,
        )
        if existing:
            report.duplicates += 1
            continue

        db.add(
            Proxy(
                project_id=project_id,
                scheme=parsed.scheme,
                host=parsed.host,
                port=parsed.port,
                username=parsed.username,
                password=parsed.password,
                source=default_source,
                vendor_name=default_vendor,
                is_active=True,
            )
        )
        await db.flush()
        report.imported += 1

    await db.commit()
    return report


async def bulk_create_proxies_from_csv(
    db: AsyncSession,
    file_content: bytes,
    project_id: int = 1,
) -> dict[str, Any]:
    """Legacy CSV bulk import (proxies with no auth or 1:1 with rows)."""
    try:
        text = file_content.decode("utf-8")
    except UnicodeDecodeError:
        text = file_content.decode("latin-1")

    stream = io.StringIO(text)
    reader = csv.reader(stream)
    new_rows: list[Proxy] = []
    errors: list[dict[str, Any]] = []
    for row_index, row in enumerate(reader, start=1):
        if not row or len(row) < 3:
            errors.append({
                "row": row_index,
                "reason": f"Need at least scheme,host,port — got {len(row)} columns",
                "raw": row,
            })
            continue
        try:
            proxy_in = ProxyCreate(
                scheme=row[0].strip(),
                host=row[1].strip(),
                port=int(row[2].strip()),
                username=row[3].strip() if len(row) > 3 and row[3].strip() else None,
                password=row[4].strip() if len(row) > 4 and row[4].strip() else None,
            )
        except (ValueError, IndexError, ValidationError) as e:
            errors.append({
                "row": row_index,
                "reason": str(e)[:200] if not isinstance(e, ValidationError)
                else "; ".join(
                    f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
                    for err in e.errors()
                ),
                "raw": row,
            })
            continue
        new_rows.append(Proxy(**proxy_in.model_dump(exclude_none=False), project_id=project_id))

    if new_rows:
        db.add_all(new_rows)
        await db.commit()

    return {
        "imported": len(new_rows),
        "skipped_empty": 0,
        "errors": errors,
        "total_in_file": len(new_rows) + len(errors),
    }

