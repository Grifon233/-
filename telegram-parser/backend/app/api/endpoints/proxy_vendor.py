"""Vendor (proxy6.net) integration endpoints.

These endpoints proxy the operator's account on proxy6.net so the
UI can show:
* the current balance;
* the list of proxies the operator owns (with expiration);
* a one-click "buy" that purchases and immediately imports the new
  proxy into the local ``proxies`` table.

All money-spending endpoints require ``confirm: true`` in the
request body.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.db.session import get_db
from app.api.deps import get_project_id
from app.models.proxy import Proxy
from app.schemas.proxy import Proxy as ProxySchema
from app.services import proxy_service
from app.services.proxy6_service import (
    Proxy6Account,
    Proxy6Error,
    Proxy6Proxy,
    Proxy6Service,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_service() -> Proxy6Service:
    try:
        return Proxy6Service()
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


# ── Reads ────────────────────────────────────────────────────────────
@router.get("/balance")
async def get_balance() -> Any:
    """Current proxy6.net account balance."""
    svc = _get_service()
    try:
        bal: Proxy6Account = await svc.get_balance()
        return {
            "available": True,
            "user_id": bal.user_id,
            "email": bal.email,
            "balance": bal.balance,
            "balance_ref": bal.balance_ref,
            "currency": bal.currency,
            "balance_str": bal.balance_str,
        }
    except Proxy6Error as exc:
        logger.warning("proxy vendor balance unavailable: %s", exc)
        return {
            "available": False,
            "detail": str(exc),
            "user_id": None,
            "email": None,
            "balance": None,
            "balance_ref": None,
            "currency": None,
            "balance_str": "Недоступно",
        }
    finally:
        await svc.aclose()


@router.get("/list")
async def list_vendor_proxies() -> Any:
    """Proxies the operator owns on proxy6.net (raw vendor view)."""
    svc = _get_service()
    try:
        items: list[Proxy6Proxy] = await svc.list_proxies()
        return [
            {
                "id": p.id,
                "ip": p.ip,
                "port": p.port,
                "user": p.user,
                "pass": p.passwd,
                "type": p.type_,
                "country": p.country,
                "date": p.date.isoformat(),
                "date_end": p.date_end.isoformat(),
                "is_ipv6": p.is_ipv6,
            }
            for p in items
        ]
    except Proxy6Error as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    finally:
        await svc.aclose()


@router.post("/import-all", status_code=status.HTTP_201_CREATED)
async def import_all(
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    """Re-import every proxy owned on proxy6.net into the local
    ``proxies`` table. Idempotent: existing rows are matched by
    ``(vendor_name='proxy6', vendor_proxy_id)`` and refreshed, not
    duplicated.
    """
    svc = _get_service()
    try:
        items: list[Proxy6Proxy] = await svc.list_proxies()
    except Proxy6Error as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    finally:
        await svc.aclose()

    imported: list[int] = []
    updated: list[int] = []
    for p in items:
        # Match by vendor_proxy_id first, then fall back to host:port to avoid
        # duplicates when the proxy was added manually before the first sync.
        existing = (
            await db.execute(
                select(Proxy).where(
                    Proxy.project_id == project_id,
                    Proxy.vendor_name == "proxy6",
                    Proxy.vendor_proxy_id == p.id,
                )
            )
        ).scalars().first()
        if not existing:
            existing = (
                await db.execute(
                    select(Proxy).where(
                        Proxy.project_id == project_id,
                        Proxy.host == p.ip,
                        Proxy.port == p.port,
                    )
                )
            ).scalars().first()
            if existing:
                # Adopt the manually-added row into the vendor bookkeeping.
                existing.vendor_name = "proxy6"
                existing.vendor_proxy_id = p.id
        if existing:
            existing.host = p.ip
            existing.port = p.port
            existing.username = p.user
            existing.password = p.passwd
            existing.scheme = "socks5"
            existing.country = p.country
            existing.expires_at = p.date_end
            existing.is_active = True
            updated.append(existing.id)
        else:
            db.add(
                Proxy(
                    project_id=project_id,
                    scheme="socks5",
                    host=p.ip,
                    port=p.port,
                    username=p.user,
                    password=p.passwd,
                    source="vendor",
                    vendor_name="proxy6",
                    vendor_proxy_id=p.id,
                    country=p.country,
                    expires_at=p.date_end,
                    is_active=True,
                )
            )
            await db.flush()
            imported.append(p.id)
    await db.commit()
    return {"imported": len(imported), "updated": len(updated)}


# ── Money-spending actions ──────────────────────────────────────────
class BuyRequest(BaseModel):
    country: str = Field(..., min_length=2, max_length=4, description="ISO 3166-1 alpha-2 (e.g. us, de)")
    count: int = Field(default=1, ge=1, le=100)
    period: int = Field(default=30, ge=1, le=365, description="days")
    version: str = Field(default="4", pattern=r"^[46]$")
    type_: str = Field(default="socks", pattern=r"^(socks|http)$")
    confirm: bool = Field(default=False, description="must be true to spend money")
    auto_import: bool = Field(default=True, description="import new proxies into local DB")


@router.post("/buy")
async def buy(
    req: BuyRequest,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    if not req.confirm:
        raise HTTPException(
            status_code=400,
            detail=(
                "refusing to buy without confirm=true; this endpoint spends real money. "
                "Pass {\"confirm\": true, ...} to proceed."
            ),
        )
    svc = _get_service()
    try:
        new_proxies: list[Proxy6Proxy] = await svc.buy(
            country=req.country,
            count=req.count,
            period=req.period,
            version=req.version,
            type_=req.type_,
            confirm=True,
        )
    except Proxy6Error as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    finally:
        await svc.aclose()

    if req.auto_import:
        for p in new_proxies:
            db.add(
                Proxy(
                    project_id=project_id,
                    scheme="socks5",
                    host=p.ip,
                    port=p.port,
                    username=p.user,
                    password=p.passwd,
                    source="vendor",
                    vendor_name="proxy6",
                    vendor_proxy_id=p.id,
                    country=p.country,
                    expires_at=p.date_end,
                    is_active=True,
                )
            )
        await db.commit()

    return {
        "bought": len(new_proxies),
        "auto_imported": req.auto_import,
        "proxies": [
            {"id": p.id, "ip": p.ip, "port": p.port, "country": p.country,
             "date_end": p.date_end.isoformat()}
            for p in new_proxies
        ],
    }


class RenewRequest(BaseModel):
    proxy_id: str
    period: int = Field(default=30, ge=1, le=365)
    confirm: bool = False


@router.post("/renew")
async def renew(
    req: RenewRequest,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    if not req.confirm:
        raise HTTPException(
            status_code=400,
            detail="refusing to renew without confirm=true; this spends money",
        )
    svc = _get_service()
    try:
        result = await svc.renew(req.proxy_id, req.period, confirm=True)
    except Proxy6Error as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    finally:
        await svc.aclose()
    row = (
        await db.execute(
            select(Proxy).where(
                Proxy.project_id == project_id,
                Proxy.vendor_name == "proxy6",
                Proxy.vendor_proxy_id == req.proxy_id,
            )
        )
    ).scalars().first()
    renewed = (result.get("list") or {}).get(str(req.proxy_id)) if isinstance(result, dict) else None
    if row and renewed and renewed.get("date_end"):
        try:
            row.expires_at = datetime.strptime(str(renewed["date_end"]), "%Y-%m-%d %H:%M:%S")
            row.is_active = True
            await db.commit()
        except ValueError:
            logger.warning("proxy6 renew returned unparseable date_end: %s", renewed.get("date_end"))
    return result


@router.get("/countries")
async def countries(version: str = "4") -> Any:
    if version not in {"4", "6"}:
        raise HTTPException(status_code=400, detail="Поддерживаются только обычные IPv4 или IPv6. IPv4 Shared и MTProto запрещены.")
    svc = _get_service()
    try:
        return {"version": version, "countries": await svc.get_countries(version)}
    except Proxy6Error as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    finally:
        await svc.aclose()


class DeleteRequest(BaseModel):
    proxy_id: str


@router.post("/delete")
async def delete(req: DeleteRequest, db: AsyncSession = Depends(get_db)) -> Any:
    svc = _get_service()
    try:
        result = await svc.delete(req.proxy_id)
    except Proxy6Error as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    finally:
        await svc.aclose()
    # Also delete the local row (by vendor id).
    row = (
        await db.execute(
            select(Proxy).where(
                Proxy.vendor_name == "proxy6",
                Proxy.vendor_proxy_id == req.proxy_id,
            )
        )
    ).scalars().first()
    if row:
        await db.delete(row)
        await db.commit()
    return result
