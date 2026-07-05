from typing import Any, List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, Form, HTTPException, status, Response, UploadFile, File
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.db.session import get_db
from app.core.config import settings
from app.schemas.account import Account, AccountCreate, AccountUpdate
from app.services import account_service
from app.services.session_import_service import SessionImportError
from app.api.deps import get_project_id
from app.models.proxy import Proxy

router = APIRouter()

class AccountLoginRequest(BaseModel):
    phone_code: str
    phone_code_hash: str
    password: Optional[str] = None


class AccountIdsRequest(BaseModel):
    account_ids: List[int] = Field(..., min_length=1, max_length=200)


class SavedMessageRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4096)


class DirectMessageRequest(BaseModel):
    target: str = Field(..., min_length=2, max_length=128)
    text: str = Field(..., min_length=1, max_length=4096)


def friendly_telegram_error(exc: Exception) -> str:
    """Translate common Telegram / account-limitation errors into a clear
    Russian message for operator-facing actions (e.g. sending a message).

    The raw Telegram codes (PEER_FLOOD, USER_RESTRICTED, …) are accurate but
    unreadable for a non-technical operator, so we map the frequent ones to
    plain language with a concrete next step. Unknown errors fall through
    with their original text so nothing is silently hidden.
    """
    raw = f"{getattr(exc, 'MESSAGE', '') or ''} {exc}"
    low = raw.lower()
    if "peer_flood" in low:
        return (
            "Telegram временно ограничил этот аккаунт за подозрение в спаме "
            "(PEER_FLOOD): он не может писать незнакомым или новым собеседникам. "
            "Что делать: напишите боту @SpamBot с этого аккаунта и проверьте статус, "
            "снизьте активность, дайте аккаунту прогреться и повторите позже."
        )
    if "user_restricted" in low:
        return (
            "Telegram ограничил этот аккаунт (USER_RESTRICTED) — он сейчас не может "
            "выполнять это действие. Проверьте аккаунт через @SpamBot и дайте ему прогреться."
        )
    if "floodwait" in low or "flood_wait" in low:
        secs = getattr(exc, "value", None)
        if secs:
            return f"Telegram просит подождать {secs}с перед следующим действием (FloodWait). Повторите позже."
        return "Telegram просит подождать перед следующим действием (FloodWait). Повторите позже."
    if "user_privacy_restricted" in low or "privacy_restricted" in low:
        return "Получатель закрыл приём сообщений настройками приватности — написать ему нельзя."
    if "user_is_blocked" in low or "blocked" in low:
        return "Получатель заблокировал этот аккаунт — сообщение не доставить."
    if "peer_id_invalid" in low or "username_not_occupied" in low or "username_invalid" in low:
        return "Получатель не найден: проверьте @username, ссылку t.me/… или номер телефона."
    if "auth_key_unregistered" in low or "session is no longer valid" in low:
        return "Сессия аккаунта недействительна — авторизуйте аккаунт заново."
    if "newborn" in low or "слишком молод" in low:
        return "Аккаунт ещё слишком новый для отправки сообщений — дайте ему прогреться и повторите."
    if "ratelimit" in low or "rate limit" in low or "лимит" in low:
        return "Достигнут лимит отправки для этого аккаунта — попробуйте позже."
    return f"Не удалось отправить: {exc}"


def _restriction_reason(exc: Exception) -> Optional[str]:
    """Return a short restriction code if the error means the ACCOUNT itself
    is limited by Telegram (spam-flag), else None. PEER_FLOOD / USER_RESTRICTED
    survive a normal health check (get_me still works), so we persist the fact
    as a flag the UI can show with a clear badge."""
    low = f"{getattr(exc, 'MESSAGE', '') or ''} {exc}".lower()
    if "peer_flood" in low:
        return "PEER_FLOOD"
    if "user_restricted" in low:
        return "USER_RESTRICTED"
    return None


def _set_account_restriction(account, reason: Optional[str]) -> None:
    """Persist (reason set) or clear (reason None) the restriction marker in
    ``health_factors`` — merge-safe so other health data is preserved."""
    factors = dict(account.health_factors or {})
    if reason:
        factors["restriction"] = {"reason": reason, "at": datetime.utcnow().isoformat()}
    else:
        factors.pop("restriction", None)
    account.health_factors = factors

# NOTE: Routes without path parameters MUST be defined BEFORE routes with {account_id}
# Otherwise FastAPI will match "warmup-status" to {account_id} and fail to parse it as int

@router.get("/warmup-status")
async def get_warmup_status_all(
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    """Get warmup status for all accounts."""
    from app.tasks.warmup import get_warmup_schedule

    accounts = await account_service.get_accounts(db, skip=0, limit=100, project_id=project_id)
    schedule = get_warmup_schedule()

    return {
        "accounts": [
            {
                "id": acc.id,
                "phone_number": acc.phone_number,
                "status": acc.status.value if hasattr(acc.status, 'value') else acc.status,
                "folder": acc.folder,
                "has_session": bool(acc.session_string),
                "proxy_id": acc.proxy_id,
                "warmup_level": acc.warmup_level or 0,
                "days_active": (datetime.utcnow() - acc.created_at).days if acc.created_at else 0,
                "health_score": acc.health_score,
                "warmup_phase": acc.warmup_phase,
                "warmup_locked": bool(acc.warmup_locked) if acc.warmup_locked is not None else False,
                "first_name": acc.first_name,
                "username": acc.username,
                "proxy_country": (acc.proxy.country.upper() if acc.proxy and acc.proxy.country else None),
                "proxy_label": (f"{acc.proxy.host}:{acc.proxy.port}" if acc.proxy else None),
            }
            for acc in accounts
        ],
        "schedule": schedule
    }

@router.post("/warmup-all")
async def run_warmup_all(
    project_id: int = Depends(get_project_id),
) -> Any:
    """Start warm-up for all accounts that need it — IN THE BACKGROUND.

    Warm-up (especially the account-to-account conversation step) can take
    several minutes. Running it inside the request blew past the browser's
    30s timeout, so we launch it as a background job and return at once.
    The frontend polls ``GET /warmup-job`` for the result.
    """
    from app.services import warmup_runner

    return warmup_runner.start("all", project_id)


@router.post("/warmup-conversations")
async def run_warmup_conversations_endpoint(
    project_id: int = Depends(get_project_id),
) -> Any:
    """Start account-to-account warm-up chats IN THE BACKGROUND.

    Pairs eligible accounts (rotating partners so every account eventually
    talks to every other) and runs a random human-like dialogue per pair,
    through each account's proxy + the rate limiter. Returns immediately;
    poll ``GET /warmup-job`` for the result.
    """
    from app.services import warmup_runner

    return warmup_runner.start("conversations", project_id)


@router.post("/warmup-selected")
async def run_warmup_selected(
    payload: AccountIdsRequest,
    project_id: int = Depends(get_project_id),
) -> Any:
    """Start a warm-up cycle for selected accounts — IN THE BACKGROUND."""
    from app.services import warmup_runner

    return warmup_runner.start("selected", project_id, account_ids=payload.account_ids)


class AssignWarmupPoolRequest(BaseModel):
    account_ids: List[int] = Field(..., min_length=1, max_length=200)
    source_group_id: int = Field(..., gt=0)


@router.post("/assign-warmup-pool")
async def assign_warmup_pool(
    payload: AssignWarmupPoolRequest,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    """Distribute sources from a source group evenly across selected accounts.

    Each account gets a slice of the sources (round-robin). The assignment is
    stored in account.warmup_assignment and used by the warmup task to
    pre-join those specific groups/channels. When an account is banned and
    replaced, assign the same pool to the new account — it will join the
    same or remaining sources automatically.
    """
    from app.models.account import Account as AccountModel
    from app.models.telegram_source import TelegramSource
    from sqlalchemy.orm.attributes import flag_modified

    # Load sources in the chosen group.
    sources_result = await db.execute(
        select(TelegramSource).where(
            TelegramSource.project_id == project_id,
            TelegramSource.group_id == payload.source_group_id,
            TelegramSource.is_enabled.is_(True),
        )
    )
    sources = sources_result.scalars().all()
    if not sources:
        raise HTTPException(status_code=404, detail="Группа источников не найдена или пуста")

    # Load selected accounts.
    accounts_result = await db.execute(
        select(AccountModel).where(
            AccountModel.project_id == project_id,
            AccountModel.id.in_(payload.account_ids),
        )
    )
    accounts = accounts_result.scalars().all()
    if not accounts:
        raise HTTPException(status_code=404, detail="Аккаунты не найдены")

    # Distribute sources evenly across accounts (round-robin).
    source_ids = [s.id for s in sources]
    assignments: dict[int, list[int]] = {acc.id: [] for acc in accounts}
    for i, sid in enumerate(source_ids):
        target_account = accounts[i % len(accounts)]
        assignments[target_account.id].append(sid)

    # Persist assignment to each account.
    for account in accounts:
        account.warmup_assignment = {
            "source_group_id": payload.source_group_id,
            "source_ids": assignments[account.id],
        }
        flag_modified(account, "warmup_assignment")

    await db.commit()

    return {
        "assigned": len(accounts),
        "sources_total": len(source_ids),
        "assignments": {
            str(acc_id): sid_list
            for acc_id, sid_list in assignments.items()
        },
    }


@router.get("/warmup-job")
async def get_warmup_job(
    project_id: int = Depends(get_project_id),
) -> Any:
    """Current state of the background warm-up job (for the UI to poll)."""
    from app.services import warmup_runner

    return warmup_runner.get_state()


class WarmupSchedulerSettingsRequest(BaseModel):
    enabled: Optional[bool] = None
    interval_min_hours: Optional[float] = None
    interval_max_hours: Optional[float] = None
    active_hours_start: Optional[int] = None
    active_hours_end: Optional[int] = None
    skip_chance: Optional[float] = None


@router.get("/warmup-scheduler")
async def get_warmup_scheduler(
    project_id: int = Depends(get_project_id),
) -> Any:
    """Return current auto-warmup scheduler settings and status."""
    from app.services import warmup_scheduler
    return warmup_scheduler.get_status()


@router.post("/warmup-scheduler")
async def update_warmup_scheduler(
    payload: WarmupSchedulerSettingsRequest,
    project_id: int = Depends(get_project_id),
) -> Any:
    """Enable/disable or reconfigure the continuous auto-warmup scheduler."""
    from app.services import warmup_scheduler
    patch = {k: v for k, v in payload.model_dump().items() if v is not None}
    patch["project_id"] = project_id
    return warmup_scheduler.update_settings(patch)


@router.post("/check-all")
async def check_all_accounts(
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    """Verify all project accounts. Also launches @SpamBot check in background."""
    from app.services import health_service, spambot_runner

    accounts = await account_service.get_accounts(db, skip=0, limit=10000, project_id=project_id)
    results = []
    for account in accounts:
        if not account.session_string:
            results.append({
                "account_id": account.id,
                "phone_number": account.phone_number,
                "is_healthy": False,
                "status": account.status.value if hasattr(account.status, "value") else account.status,
                "message": "no_session",
            })
            continue
        if not account.proxy_id:
            results.append({
                "account_id": account.id,
                "phone_number": account.phone_number,
                "is_healthy": False,
                "status": account.status.value if hasattr(account.status, "value") else account.status,
                "message": "no_proxy",
            })
            continue
        try:
            is_healthy = await health_service.check_account_health(db, account)
            await db.refresh(account)
            results.append({
                "account_id": account.id,
                "phone_number": account.phone_number,
                "is_healthy": is_healthy,
                "status": account.status.value if hasattr(account.status, "value") else account.status,
                "message": "ok" if is_healthy else "check_failed",
            })
        except Exception as exc:  # noqa: BLE001
            results.append({
                "account_id": account.id,
                "phone_number": account.phone_number,
                "is_healthy": False,
                "status": account.status.value if hasattr(account.status, "value") else account.status,
                "message": str(exc)[:200],
            })
    # Also launch background @SpamBot check (non-blocking — doesn't affect response).
    spambot_runner.start(project_id)
    return {"results": results, "total": len(results), "spambot_check": "started"}


@router.post("/spambot-check-all")
async def spambot_check_all(
    project_id: int = Depends(get_project_id),
) -> Any:
    """Launch @SpamBot background check for all accounts with session+proxy."""
    from app.services import spambot_runner
    return spambot_runner.start(project_id)


@router.get("/spambot-job")
async def get_spambot_job(
    project_id: int = Depends(get_project_id),
) -> Any:
    """Current state of the @SpamBot background check job."""
    from app.services import spambot_runner
    return spambot_runner.get_state()

@router.post("", response_model=Account, status_code=status.HTTP_201_CREATED)
async def create_account(
    account_in: AccountCreate,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    if account_in.proxy_id:
        proxy = await db.execute(select(Proxy.id).where(Proxy.id == account_in.proxy_id, Proxy.project_id == project_id))
        if proxy.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Proxy not found in current project")
    return await account_service.create_account(db, account_in, project_id=project_id)

class AutoRegisterRequest(BaseModel):
    """Order a number and auto-register one or more fresh Telegram accounts.

    The number is ordered in the proxy's country unless ``country_id``
    explicitly overrides it. ``api_id`` / ``api_hash`` are optional and
    default to the global Telegram app credentials. ``count`` registers
    several accounts on the same proxy — capped server-side to the
    proxy's remaining capacity (``max_accounts - current accounts``).
    """
    proxy_id: int = Field(..., gt=0)
    country_id: Optional[int] = Field(default=None, ge=0)
    api_id: Optional[int] = Field(default=None, gt=0, lt=2**31)
    api_hash: Optional[str] = Field(default=None, min_length=8, max_length=64)
    count: int = Field(default=1, ge=1, le=10)


@router.get("/sms-balance")
async def get_sms_balance(
    project_id: int = Depends(get_project_id),
) -> Any:
    """Return the smsfast account balance (for the create-account modal)."""
    from app.services.smsfast_service import smsfast_service, SmsFastError
    if not smsfast_service.is_configured:
        return {"configured": False, "balance": None}
    try:
        balance = await smsfast_service.get_balance()
        return {"configured": True, "balance": balance}
    except SmsFastError as exc:
        return {"configured": True, "balance": None, "error": str(exc)}


@router.get("/sms-countries")
async def get_sms_countries(
    project_id: int = Depends(get_project_id),
) -> Any:
    """List smsfast countries (id + Russian name) for the country dropdown."""
    from app.services.sms_countries import SMSFAST_COUNTRY_NAMES
    return {
        "countries": [
            {"id": cid, "name": name}
            for cid, name in sorted(SMSFAST_COUNTRY_NAMES.items(), key=lambda kv: kv[1])
        ]
    }


@router.post("/auto-register", status_code=status.HTTP_201_CREATED)
async def auto_register_account(
    payload: AutoRegisterRequest,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    """Create a shell account and start the automatic SMS registration.

    Flow: order a number in the proxy's country → send Telegram code →
    auto-pull the SMS code → sign in. On a 10-minute timeout the number
    is cancelled (refund) and a new one is ordered, repeating until a
    code arrives. Poll ``GET /accounts/{id}/auto-register/job`` for live
    progress.
    """
    from app.services.smsfast_service import smsfast_service
    from app.services.sms_countries import country_id_for_iso, country_name
    from app.services import auto_register_service

    if not smsfast_service.is_configured:
        raise HTTPException(status_code=400, detail="SMS-сервис не настроен (нет SMSFAST_API_TOKEN).")

    try:
        balance = await smsfast_service.get_balance()
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Не удалось проверить баланс SMSFAST: {exc}",
        )
    if balance <= 0:
        raise HTTPException(
            status_code=400,
            detail="На балансе SMSFAST нет средств. Номера не заказывались.",
        )

    # Validate proxy belongs to the project and grab its country.
    proxy_row = await db.execute(
        select(Proxy).where(Proxy.id == payload.proxy_id, Proxy.project_id == project_id)
    )
    proxy = proxy_row.scalar_one_or_none()
    if proxy is None:
        raise HTTPException(status_code=404, detail="Прокси не найден в текущем проекте.")

    # Resolve the smsfast country id: explicit override → proxy country.
    country_id = payload.country_id
    if country_id is None:
        country_id = country_id_for_iso(getattr(proxy, "country", None))
    if country_id is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Не удалось определить страну для заказа номера: у прокси не задана "
                "страна или она не поддерживается. Выберите страну вручную."
            ),
        )

    # Cap ``count`` to the proxy's remaining capacity so we never exceed
    # the operator's "max accounts per proxy" rule. NB: ``Account`` at the
    # top of this module is the Pydantic *schema* — use the ORM model here.
    from sqlalchemy import func as _func
    from app.models.account import Account as AccountModel
    used_row = await db.execute(
        select(_func.count(AccountModel.id)).where(AccountModel.proxy_id == proxy.id)
    )
    used = int(used_row.scalar() or 0)
    max_accounts = getattr(proxy, "max_accounts", None)
    if max_accounts is not None:
        remaining = max(0, int(max_accounts) - used)
        if remaining <= 0:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"На этом прокси уже {used} аккаунтов из {max_accounts} — "
                    "свободных слотов нет. Увеличьте лимит прокси или выберите другой."
                ),
            )
        count = min(payload.count, remaining)
    else:
        count = payload.count

    # Create ``count`` shell accounts and start a job for each.
    account_ids: list[int] = []
    jobs: list[dict] = []
    for _ in range(count):
        account_in = AccountCreate(
            proxy_id=payload.proxy_id,
            auto_register=True,
            sms_country_id=country_id,
            api_id=payload.api_id,
            api_hash=payload.api_hash,
            note=f"Авто-регистрация · {country_name(country_id)}",
        )
        account = await account_service.create_account(db, account_in, project_id=project_id)
        account_ids.append(account.id)
        jobs.append(auto_register_service.start(account.id, country_id, project_id))

    return {
        "account_ids": account_ids,
        "count": count,
        "requested": payload.count,
        "country_id": country_id,
        "country_name": country_name(country_id),
        "jobs": jobs,
        "queue_mode": "sequential",
        "max_parallel_paid_activations": 1,
        # Back-compat single-account fields.
        "account_id": account_ids[0] if account_ids else None,
        "job": jobs[0] if jobs else None,
    }


@router.post("/bulk-upload", status_code=status.HTTP_201_CREATED)
async def bulk_upload_accounts(
    file: UploadFile = File(...),
    require_proxy: bool = Form(default=True),
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    """Bulk-import accounts from a CSV file.

    Expected columns:
    ``phone_number,api_id,api_hash,proxy_ref,session_string,status,folder``

    The ``proxy_ref`` column is required when ``require_proxy`` is
    ``true`` (the default) OR when the row has a pre-baked
    ``session_string``. Rows that violate this are reported in the
    structured ``errors`` array so the operator can fix the CSV and
    re-upload — no row is ever silently authorized.
    """
    content = await file.read()
    report = await account_service.bulk_create_accounts_from_csv(
        db, content, project_id=project_id, require_proxy=require_proxy
    )
    return {"status": "success", **report.as_dict()}


@router.post("/import-tdata", status_code=status.HTTP_201_CREATED)
async def import_tdata_accounts(
    file: UploadFile = File(..., description="ZIP archive of tdata folders"),
    api_id: Optional[int] = Form(default=None, gt=0, lt=2**31),
    api_hash: Optional[str] = Form(default=None, min_length=8, max_length=64),
    default_proxy_id: Optional[int] = Form(default=None, gt=0),
    passcode: Optional[str] = Form(default=None, max_length=256),
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    """Bulk-import accounts from a Telegram Desktop ``tdata`` ZIP archive.

    The ZIP can contain one or several tdata folders. Each folder
    becomes a new ``Account`` row with a freshly converted Pyrogram
    ``session_string``. The operator MUST supply either a
    ``default_proxy_id`` that will be attached to every converted
    account, or attach proxies later — but the conversion will
    refuse to create any account without a proxy.
    """
    content = await file.read()
    effective_api_id = api_id or settings.TELEGRAM_API_ID
    effective_api_hash = api_hash or settings.TELEGRAM_API_HASH
    try:
        return await account_service.import_tdata_accounts(
            db,
            archive_bytes=content,
            api_id=effective_api_id,
            api_hash=effective_api_hash,
            project_id=project_id,
            default_proxy_id=default_proxy_id,
            passcode=passcode,
        )
    except account_service.ProxyRequiredError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/import-session", status_code=status.HTTP_201_CREATED)
async def import_session_account(
    file: UploadFile = File(..., description="Pyrogram or Telethon .session SQLite file"),
    metadata: Optional[UploadFile] = File(default=None, description="Optional JSON metadata"),
    api_id: Optional[int] = Form(default=None, gt=0, lt=2**31),
    api_hash: Optional[str] = Form(default=None, min_length=8, max_length=64),
    default_proxy_id: int = Form(..., gt=0),
    phone_number: Optional[str] = Form(default=None, max_length=32),
    user_id: Optional[int] = Form(default=None, gt=0),
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    """Import an existing Pyrogram/Telethon SQLite session.

    This is an offline conversion to a Pyrogram session string. The
    account is created only with a proxy bound; the endpoint never
    starts Telegram without that proxy.
    """
    content = await file.read()
    metadata_content = await metadata.read() if metadata else None
    effective_api_id = api_id or settings.TELEGRAM_API_ID
    effective_api_hash = api_hash or settings.TELEGRAM_API_HASH
    try:
        return await account_service.import_session_account(
            db,
            session_bytes=content,
            filename=file.filename or "account.session",
            api_id=effective_api_id,
            api_hash=effective_api_hash,
            project_id=project_id,
            default_proxy_id=default_proxy_id,
            phone_number=phone_number,
            user_id=user_id,
            metadata_bytes=metadata_content,
        )
    except account_service.ProxyRequiredError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except SessionImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@router.get("", response_model=List[Account])
async def read_accounts(
    skip: int = 0,
    limit: int = 10000,
    gender: Optional[str] = None,
    status: Optional[str] = None,
    folder: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    return await account_service.get_accounts(
        db,
        skip=skip,
        limit=limit,
        project_id=project_id,
        gender=gender or None,
        status=status or None,
        folder=folder or None,
    )

@router.post("/{account_id}/profile-legacy-form", response_model=Account)
async def update_account_profile_legacy_form(
    account_id: int,
    first_name: Optional[str] = Form(None),
    about: Optional[str] = Form(None),
    personal_channel: Optional[str] = Form(None),
    channel_content: Optional[str] = Form(None),
    avatar: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    """Legacy form endpoint for profile info, bio, and avatar.

    The JSON profile editor uses ``POST /accounts/{account_id}/profile`` from
    ``profile.py``. Keeping the old route under a different path prevents
    FastAPI from routing the new JSON payload to this Form/File handler.
    """
    account = await account_service.get_account(db, account_id, project_id=project_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    avatar_bytes = await avatar.read() if avatar else None
    
    try:
        updated = await account_service.update_profile(
            db,
            account,
            first_name=first_name,
            about=about,
            personal_channel=personal_channel,
            channel_content=channel_content,
            avatar_bytes=avatar_bytes,
        )
        return updated
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{account_id}", response_model=Account)
async def read_account(
    account_id: int,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    account = await account_service.get_account(db, account_id, project_id=project_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


@router.get("/{account_id}/avatar")
async def get_account_avatar(
    account_id: int,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
):
    """Serve the cached profile photo so the account card can show the real
    avatar instead of a generic status dot."""
    from pathlib import Path as _Path
    from fastapi.responses import FileResponse

    account = await account_service.get_account(db, account_id, project_id=project_id)
    if not account or not account.avatar_path:
        raise HTTPException(status_code=404, detail="No avatar")
    path = _Path(account.avatar_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Avatar file missing")
    return FileResponse(str(path), media_type="image/jpeg")

@router.put("/{account_id}", response_model=Account)
async def update_account(
    account_id: int,
    account_in: AccountUpdate,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    if account_in.proxy_id:
        proxy = await db.execute(select(Proxy.id).where(Proxy.id == account_in.proxy_id, Proxy.project_id == project_id))
        if proxy.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Proxy not found in current project")
    try:
        account = await account_service.update_account(db, account_id, account_in, project_id=project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account

@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    account_id: int,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
):
    success = await account_service.delete_account(db, account_id, project_id=project_id)
    if not success:
        raise HTTPException(status_code=404, detail="Account not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.get("/{account_id}/auto-register/job")
async def get_auto_register_job(
    account_id: int,
    project_id: int = Depends(get_project_id),
) -> Any:
    """Live status of an account's automatic SMS registration."""
    from app.services import auto_register_service
    job = auto_register_service.get_job(account_id)
    if job is None:
        return {"exists": False}
    return {"exists": True, **job}


@router.post("/{account_id}/auto-register/stop")
async def stop_auto_register_job(
    account_id: int,
    project_id: int = Depends(get_project_id),
) -> Any:
    """Ask a running auto-registration job to stop."""
    from app.services import auto_register_service
    return auto_register_service.stop(account_id)


@router.post("/{account_id}/auto-register/dismiss")
async def dismiss_auto_register_job(
    account_id: int,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    """Close a finished auto-registration: drop the job and delete the shell.

    When the operator presses "Закрыть" on a failed/finished registration,
    we remove the job from the live registry AND delete the leftover
    placeholder account (``pending_*`` phone, no session) so it stops
    resurfacing as an in-progress batch in the UI. Authorized accounts
    (real phone + session) are never touched.
    """
    from app.services import auto_register_service

    result = auto_register_service.dismiss(account_id)
    if result.get("status") == "still_running":
        raise HTTPException(
            status_code=409,
            detail="Регистрация ещё выполняется — сначала остановите её.",
        )

    account = await account_service.get_account(db, account_id, project_id=project_id)
    if (
        account is not None
        and not account.session_string
        and (account.phone_number or "").startswith("pending_")
    ):
        await account_service.delete_account(db, account_id, project_id=project_id)
        result["deleted_account"] = True
    return result


@router.post("/{account_id}/send-code")
async def send_code(
    account_id: int,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    account = await account_service.get_account(db, account_id, project_id=project_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    # Refuse to send the Telegram code if no proxy is bound. The
    # whole point of running a fleet of 50+ accounts is to keep them
    # on different IPs, so an accidental ``proxy_id = NULL`` would
    # collapse every account onto the operator's own IP and almost
    # certainly trigger a flood ban.
    if account.proxy_id is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "У аккаунта не привязан прокси. Сначала назначьте прокси, "
                "а потом авторизуйте аккаунт."
            ),
        )

    try:
        sent_code = await account_service.request_code(db, account)
        return {"phone_code_hash": sent_code.phone_code_hash}
    except account_service.ProxyRequiredError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{account_id}/login")
async def login_account(
    account_id: int,
    login_request: AccountLoginRequest,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    account = await account_service.get_account(db, account_id, project_id=project_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    if account.proxy_id is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Нельзя завершить вход без привязанного прокси. "
                "Сначала назначьте аккаунту прокси."
            ),
        )

    try:
        session_string = await account_service.login(
            db,
            account,
            login_request.phone_code,
            login_request.phone_code_hash,
            login_request.password,
        )
        return {"message": "Вход в аккаунт выполнен"}
    except account_service.ProxyRequiredError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{account_id}/check")
async def check_account(
    account_id: int,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    from app.services import health_service
    account = await account_service.get_account(db, account_id, project_id=project_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    is_healthy = await health_service.check_account_health(db, account)
    return {"is_healthy": is_healthy, "status": account.status}


@router.post("/{account_id}/send-saved-message")
async def send_saved_message(
    account_id: int,
    payload: SavedMessageRequest,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    """Send a test message from the account to its own Saved Messages."""
    from app.services.telegram_service import telegram_service

    account = await account_service.get_account(db, account_id, project_id=project_id)
    if not account:
        raise HTTPException(status_code=404, detail="Аккаунт не найден")
    if not account.session_string:
        raise HTTPException(status_code=400, detail="У аккаунта нет активной сессии")
    if not account.proxy_id:
        raise HTTPException(status_code=400, detail="У аккаунта не привязан прокси")
    try:
        client = await telegram_service.get_client(account)
        message = await client.send_message("me", payload.text)
        return {"status": "sent", "message_id": message.id}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{account_id}/send-direct-message")
async def send_direct_message(
    account_id: int,
    payload: DirectMessageRequest,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    """Send one operator-triggered dialog message from this account."""
    from app.core.rate_limiter import rate_limiter
    from app.services.telegram_service import telegram_service

    account = await account_service.get_account(db, account_id, project_id=project_id)
    if not account:
        raise HTTPException(status_code=404, detail="Аккаунт не найден")
    if not account.session_string:
        raise HTTPException(status_code=400, detail="У аккаунта нет активной сессии")
    if not account.proxy_id:
        raise HTTPException(status_code=400, detail="У аккаунта не привязан прокси")
    try:
        created_days = (datetime.utcnow() - account.created_at).days if account.created_at else 0
        status_value = account.status.value if hasattr(account.status, "value") else account.status
        age_days = max(created_days, 30 if status_value == "production" else (account.warmup_level or 0))
        await rate_limiter.acquire("send", account.id, account_age_days=age_days)
        target = payload.target.strip()
        if target.startswith("https://t.me/"):
            target = target.rsplit("/", 1)[-1]
        if target.startswith("@"):
            target = target[1:]
        client = await telegram_service.get_client(account)
        message = await client.send_message(target, payload.text)
        # The send worked → if we'd flagged this account as restricted before,
        # clear that flag now (it can message again).
        if (account.health_factors or {}).get("restriction"):
            _set_account_restriction(account, None)
            await db.commit()
        return {"status": "sent", "message_id": message.id, "target": target}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        # Account-level limitation (spam-flag)? Persist a marker so the UI can
        # show an "ограничен" badge — a normal health check can't detect this.
        reason = _restriction_reason(exc)
        if reason:
            _set_account_restriction(account, reason)
            await db.commit()
        raise HTTPException(status_code=400, detail=friendly_telegram_error(exc))

@router.post("/{account_id}/ggr-check")
async def ggr_check_account(
    account_id: int,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    """Run detailed GGR (GramGPT Rating) health check with 16+ factors."""
    from app.services.ggr_service import run_ggr_check
    result = await run_ggr_check(db, account_id, project_id=project_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result

@router.post("/ggr-check-all")
async def ggr_check_all_accounts(
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    """Run GGR check on all accounts."""
    from app.services.ggr_service import run_ggr_check_all
    results = await run_ggr_check_all(db, project_id=project_id)
    return {"results": results, "total": len(results)}

@router.post("/{account_id}/warmup")
async def run_warmup(
    account_id: int,
    db: AsyncSession = Depends(get_db),
    project_id: int = Depends(get_project_id),
) -> Any:
    """Run warmup cycle for an account."""
    from app.tasks.warmup import run_account_warmup

    account = await account_service.get_account(db, account_id, project_id=project_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    result = await run_account_warmup(db, account)
    return result
