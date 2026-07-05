from typing import Any, List, Dict
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Response
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.db.session import get_db
from app.schemas.proxy import Proxy, ProxyBulkPasteRequest, ProxyCreate, ProxyUpdate
from app.services import proxy_service
from app.api.deps import get_project_id

router = APIRouter()

@router.post("", response_model=Proxy, status_code=status.HTTP_201_CREATED)
async def create_proxy(
    proxy_in: ProxyCreate,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    return await proxy_service.create_proxy(db, proxy_in, project_id=project_id)

@router.post("/bulk-upload", status_code=status.HTTP_201_CREATED)
async def bulk_upload_proxies(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    content = await file.read()
    report = await proxy_service.bulk_create_proxies_from_csv(
        db, content, project_id=project_id
    )
    return {"status": "success", **report}

@router.post("/paste", status_code=status.HTTP_201_CREATED)
async def paste_proxies(
    payload: ProxyBulkPasteRequest,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    """Bulk-import proxies from a multi-line pasted blob.

    Each line may be in any of these formats:
    ``host:port:user:pass``, ``host:port``,
    ``scheme://user:pass@host:port``,
    ``scheme://user:pass@[ipv6]:port``.

    Duplicates (by host/port/username) and unparseable lines are
    surfaced in the structured report.
    """
    report = await proxy_service.bulk_create_proxies_from_paste(
        db,
        payload.text,
        project_id=project_id,
        default_source=payload.default_source,
        default_vendor=payload.default_vendor,
    )
    return {"status": "success", **report.as_dict()}

@router.get("/webshare/info")
async def get_webshare_info() -> Any:
    # Legacy compatibility for older frontend code. The service was
    # renamed from "webshare" to proxy6.net, but the old route still
    # exists in the UI.
    from app.api.endpoints import proxy_vendor
    return await proxy_vendor.get_balance()

@router.post("/webshare/sync")
async def sync_webshare_proxies(
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    from app.api.endpoints import proxy_vendor
    return await proxy_vendor.import_all(db=db, project_id=project_id)

@router.post("/bulk-paste")
async def bulk_paste_proxies(
    data: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    text = data.get("text", "")
    use_for_accounts = data.get("use_for_accounts", True)
    if not text:
        return {"status": "error", "message": "No text provided"}
    
    added = 0
    errors = []
    lines = text.strip().split("\n")
    
    for line in lines:
        line = line.strip()
        if not line: continue
        
        try:
            # Clean possible BOM or whitespace
            line = line.replace('\ufeff', '')
            
            if "@" in line:
                # user:pass@host:port
                auth, netloc = line.split("@")
                user, pwd = auth.split(":")
                host, port = netloc.split(":")
                p_in = ProxyCreate(scheme="socks5", host=host, port=int(port), username=user, password=pwd, use_for_accounts=use_for_accounts)
            else:
                parts = line.split(":")
                if len(parts) == 2: # host:port
                    p_in = ProxyCreate(scheme="socks5", host=parts[0], port=int(parts[1]), use_for_accounts=use_for_accounts)
                elif len(parts) == 4: # host:port:user:pass
                    p_in = ProxyCreate(scheme="socks5", host=parts[0], port=int(parts[1]), username=parts[2], password=parts[3], use_for_accounts=use_for_accounts)
                else:
                    errors.append(f"Invalid format: {line}")
                    continue
            
            await proxy_service.create_proxy(db, p_in, project_id=project_id)
            added += 1
        except Exception as e:
            errors.append(f"Error parsing {line}: {str(e)}")
            
    return {"status": "success", "added": added, "errors": errors}

@router.get("", response_model=List[Proxy])
async def read_proxies(
    skip: int = 0,
    limit: int = 10000,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    from app.models.account import Account as AccountModel
    proxies = await proxy_service.get_proxies(db, skip=skip, limit=limit, project_id=project_id)
    proxy_ids = [p.id for p in proxies]
    counts: dict[int, int] = {}
    if proxy_ids:
        rows = await db.execute(
            select(AccountModel.proxy_id, func.count(AccountModel.id).label("cnt"))
            .where(AccountModel.proxy_id.in_(proxy_ids))
            .group_by(AccountModel.proxy_id)
        )
        counts = {row.proxy_id: row.cnt for row in rows}
    result = []
    for proxy in proxies:
        proxy.account_count = counts.get(proxy.id, 0)  # type: ignore[attr-defined]
        result.append(proxy)
    return result

@router.get("/{proxy_id}", response_model=Proxy)
async def read_proxy(
    proxy_id: int,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    proxy = await proxy_service.get_proxy(db, proxy_id, project_id=project_id)
    if not proxy:
        raise HTTPException(status_code=404, detail="Proxy not found")
    return proxy

@router.put("/{proxy_id}", response_model=Proxy)
async def update_proxy(
    proxy_id: int,
    proxy_in: ProxyUpdate,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    proxy = await proxy_service.update_proxy(db, proxy_id, proxy_in, project_id=project_id)
    if not proxy:
        raise HTTPException(status_code=404, detail="Proxy not found")
    return proxy

@router.delete("/{proxy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_proxy(
    proxy_id: int,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
):
    success = await proxy_service.delete_proxy(db, proxy_id, project_id=project_id)
    if not success:
        raise HTTPException(status_code=404, detail="Proxy not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.post("/{proxy_id}/check")
async def check_proxy(
    proxy_id: int,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    from app.services import health_service
    proxy = await proxy_service.get_proxy(db, proxy_id, project_id=project_id)
    if not proxy:
        raise HTTPException(status_code=404, detail="Proxy not found")
    
    is_active, response_time_ms = await health_service.check_proxy_health(proxy)
    proxy.is_active = is_active
    proxy.response_time_ms = response_time_ms
    await db.commit()
    return {"is_active": is_active, "response_time_ms": response_time_ms}
