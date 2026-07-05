import os
import logging
from logging.handlers import RotatingFileHandler
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, APIRouter, Depends
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.deps import require_admin_token
from app.api.endpoints import (
    accounts, proxies, contacts, templates, campaigns,
    parsing, reactions, ai_settings, groups, video,
    kb, analytics, projects, telegram_sources,
    comment_tasks, safety, profile, proxy_vendor,
    personal_channel_templates, warmup_phases,
    external_parsers, join_pool,
)

# Ensure logs directory exists
Path("logs").mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    handlers=[
        RotatingFileHandler(
            'logs/app.log',
            maxBytes=10 * 1024 * 1024,
            backupCount=3,
            encoding='utf-8',
        ),
        logging.StreamHandler()
    ]
)
# httpx logs full query strings. SMSFAST authenticates via a query parameter,
# so INFO logging would write the API key to disk.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def _reap_zombie_parsing_tasks():
    """Mark parsing tasks stuck in RUNNING/PENDING as FAILED on startup.

    Parsing runs as an ``asyncio.create_task`` inside *this* uvicorn
    process — there is no external queue. When the process is
    restarted (deploy, crash, manual restart) any in-flight task dies
    but its DB row stays ``running`` forever, so the UI shows a
    spinner that never resolves. On startup we know nothing can still
    be running, so we flip those rows to ``failed`` with a clear
    reason the operator can act on (just re-run the task).
    """
    from datetime import datetime
    from sqlalchemy import select
    from app.db.session import SessionLocal
    from app.models.parsing import ParsingStatus, ParsingTask

    try:
        async with SessionLocal() as db:
            result = await db.execute(
                select(ParsingTask).where(
                    ParsingTask.status.in_(
                        [ParsingStatus.RUNNING, ParsingStatus.PENDING]
                    )
                )
            )
            stuck = result.scalars().all()
            for task in stuck:
                task.status = ParsingStatus.FAILED
                task.finished_at = datetime.utcnow()
                _p = {**(task.params or {})}
                _p.pop("progress", None)
                _p["last_error"] = (
                    "interrupted: задача была прервана перезапуском сервера. "
                    "Запустите её заново."
                )
                task.params = _p
            if stuck:
                await db.commit()
                logger.info(
                    "Reaped %d zombie parsing task(s) on startup", len(stuck)
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not reap zombie parsing tasks: %s", exc)


async def _reap_zombie_external_parser_runs():
    """Mark external-parser runs stuck in RUNNING/PENDING as STOPPED.

    Like parsing, these run as asyncio tasks inside this process. After a
    restart the task is gone but the row stays RUNNING, so the UI would
    show a live parser that isn't. Flip them to STOPPED on startup.
    """
    from datetime import datetime
    from sqlalchemy import select
    from app.db.session import SessionLocal
    from app.models.external_parser import ExternalParserRun, ExternalParserStatus

    try:
        async with SessionLocal() as db:
            result = await db.execute(
                select(ExternalParserRun).where(
                    ExternalParserRun.status.in_(
                        [ExternalParserStatus.RUNNING, ExternalParserStatus.PENDING]
                    )
                )
            )
            stuck = result.scalars().all()
            for run in stuck:
                run.status = ExternalParserStatus.STOPPED
                run.finished_at = datetime.utcnow()
                run.last_error = (
                    "interrupted: запуск был прерван перезапуском сервера. "
                    "Запустите парсер заново."
                )
            if stuck:
                await db.commit()
                logger.info(
                    "Reaped %d zombie external-parser run(s) on startup", len(stuck)
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not reap zombie external-parser runs: %s", exc)


async def _reap_zombie_comment_tasks():
    """Mark comment tasks stuck in RUNNING as STOPPED on startup.

    Comment tasks run as asyncio background tasks inside the uvicorn process.
    On restart those tasks die but their DB rows stay RUNNING, blocking
    any attempt to re-start them (409). Flip them to STOPPED so the
    operator can re-launch immediately.
    """
    from datetime import datetime
    from sqlalchemy import select, update
    from app.db.session import SessionLocal
    from app.models.comment_task import (
        CommentTask,
        CommentTaskStatus,
        CommentTaskSourceState,
        CommentSourceStateStatus,
    )

    try:
        async with SessionLocal() as db:
            result = await db.execute(
                select(CommentTask).where(CommentTask.status == CommentTaskStatus.RUNNING)
            )
            stuck = result.scalars().all()
            for task in stuck:
                task.status = CommentTaskStatus.STOPPED
                task.finished_at = datetime.utcnow()

            # A task that died mid-source leaves its CommentTaskSourceState in
            # IN_PROGRESS. The run loop only re-selects PENDING/FAILED/
            # JOIN_REQUESTED, so without this reset the source would be silently
            # dropped forever. Return it to PENDING so a re-run picks it up.
            reset_states = await db.execute(
                update(CommentTaskSourceState)
                .where(
                    CommentTaskSourceState.status
                    == CommentSourceStateStatus.IN_PROGRESS
                )
                .values(
                    status=CommentSourceStateStatus.PENDING,
                    account_id=None,
                    last_error="interrupted_by_restart_reset_to_pending",
                )
            )
            if stuck or reset_states.rowcount:
                await db.commit()
                logger.info(
                    "Reaped %d zombie comment task(s) and reset %d stuck source state(s) on startup",
                    len(stuck),
                    reset_states.rowcount or 0,
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not reap zombie comment tasks: %s", exc)


async def _reap_zombie_campaign_recipients():
    """Return campaign recipients stuck in SENDING to the retry pool.

    ``_claim_recipient`` flips a row to SENDING before the network send.
    If the worker/process dies between claim and send, the row stays
    SENDING forever — the batch query only picks PENDING/FAILED_RETRY,
    so that recipient would never be messaged and the campaign could
    never reach COMPLETED. On startup nothing can still be sending, so
    move them to FAILED_RETRY for a clean re-attempt.
    """
    from sqlalchemy import update
    from app.db.session import SessionLocal
    from app.models.campaign_recipient import CampaignRecipient, RecipientStatus

    try:
        async with SessionLocal() as db:
            result = await db.execute(
                update(CampaignRecipient)
                .where(CampaignRecipient.status == RecipientStatus.SENDING)
                .values(
                    status=RecipientStatus.FAILED_RETRY,
                    last_error="interrupted_by_restart_requeued",
                )
            )
            if result.rowcount:
                await db.commit()
                logger.info(
                    "Requeued %d campaign recipient(s) stuck in SENDING on startup",
                    result.rowcount,
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not reap stuck campaign recipients: %s", exc)


async def _reap_pending_auto_register_accounts():
    """Delete account rows with 'pending_*' phone numbers on startup.

    These are shell accounts created by the auto-register flow whose jobs
    were killed by a server restart before the phone number was assigned.
    They are useless (no real phone, no session) and would just clutter
    the accounts list.
    """
    from app.db.session import SessionLocal
    from app.models.account import Account
    from sqlalchemy import select

    try:
        async with SessionLocal() as db:
            result = await db.execute(
                select(Account).where(Account.phone_number.like("pending_%"))
            )
            orphans = result.scalars().all()
            deletable = []
            recoverable = []
            for acct in orphans:
                activation = (acct.health_factors or {}).get(
                    "auto_register_activation"
                )
                if activation and activation.get("activation_id"):
                    recoverable.append(acct)
                else:
                    deletable.append(acct)
                    await db.delete(acct)
            if deletable:
                await db.commit()
                logger.info(
                    "Deleted %d orphan pending auto-register account(s) on startup",
                    len(deletable),
                )
            if recoverable:
                logger.warning(
                    "Found %d pending SMS activation(s); scheduling refund recovery",
                    len(recoverable),
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not clean up pending auto-register accounts: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    from datetime import datetime
    from app.services.warmup_scheduler import start_scheduler, stop_scheduler
    from app.services.warmup_phase_service import tick_all

    await _reap_zombie_parsing_tasks()
    await _reap_zombie_external_parser_runs()
    await _reap_zombie_comment_tasks()
    await _reap_zombie_campaign_recipients()
    await _reap_pending_auto_register_accounts()

    start_scheduler()
    from app.services.auto_register_service import recover_orphaned_activations
    recovery_task = asyncio.create_task(recover_orphaned_activations())

    # Run phase-warmup tick on startup (non-blocking)
    asyncio.create_task(tick_all())

    # Background loop: phase-warmup tick every 30 minutes
    async def _phase_warmup_loop():
        while True:
            await asyncio.sleep(30 * 60)
            try:
                advanced = await tick_all()
                if advanced:
                    logger.info("Phase warmup tick: %d accounts advanced", advanced)
            except Exception as exc:
                logger.warning("Phase warmup loop error: %s", exc)

    loop_task = asyncio.create_task(_phase_warmup_loop())

    # Background loop: progressive channel-joining, checked every 10-20 min.
    # Full nightly stop 00:00-08:00 Yekaterinburg time (accounts "sleep" —
    # no ticks fire at all, so no episode can start during that window).
    # The tick itself is just a "is anyone due?" poll — each account's own
    # randomized join_next_episode_at (see channel_joiner_service, ~every
    # half hour) decides whether it actually does anything on a given tick,
    # so this only needs to be frequent enough to notice those promptly.
    async def _channel_join_loop():
        import random
        from datetime import timezone
        while True:
            wait_secs = random.uniform(10 * 60, 20 * 60)
            await asyncio.sleep(wait_secs)
            try:
                from app.services import channel_joiner_runner as _cjr
                yekt_hour = (datetime.now(timezone.utc).hour + 5) % 24
                if not (8 <= yekt_hour < 24):
                    logger.debug("channel_joiner_loop: night phase (%d YEKT), skip", yekt_hour)
                    continue
                if _cjr.is_running():
                    logger.debug("channel_joiner_loop: already running, skip")
                    continue
                logger.info("channel_joiner_loop: triggering join session")
                # project_id=None → cover every project's pool, not just id=1.
                _cjr.start(project_id=None)
            except Exception as exc:
                logger.warning("channel_joiner_loop error: %s", exc)

    join_loop_task = asyncio.create_task(_channel_join_loop())

    yield
    stop_scheduler()
    loop_task.cancel()
    join_loop_task.cancel()
    recovery_task.cancel()


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)

# CORS setup
_frontend_origin = os.getenv("FRONTEND_ORIGIN", "http://localhost:5177")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        _frontend_origin,
        "http://localhost:5177",
        "http://127.0.0.1:5177",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ],
    allow_origin_regex=(
        r"^https?://("
        r"localhost|"
        r"127\.0\.0\.1|"
        r"0\.0\.0\.0|"
        r"\[::1\]|"
        r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
        r"192\.168\.\d{1,3}\.\d{1,3}|"
        r"172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}"
        r"):\d+$"
    ),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=600,
)

api_router = APIRouter(dependencies=[Depends(require_admin_token)])
api_router.include_router(accounts.router, prefix="/accounts", tags=["accounts"])
api_router.include_router(proxies.router, prefix="/proxies", tags=["proxies"])
api_router.include_router(contacts.router, prefix="/contacts", tags=["contacts"])
api_router.include_router(templates.router, prefix="/templates", tags=["templates"])
api_router.include_router(campaigns.router, prefix="/campaigns", tags=["campaigns"])
api_router.include_router(parsing.router, prefix="/parsing", tags=["parsing"])
api_router.include_router(external_parsers.router, prefix="/external-parsers", tags=["external-parsers"])
api_router.include_router(reactions.router, prefix="/reactions", tags=["reactions"])
api_router.include_router(groups.router, prefix="/groups", tags=["groups"])
api_router.include_router(video.router, prefix="/video", tags=["video"])
api_router.include_router(kb.router, prefix="/kb", tags=["kb"])
api_router.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
api_router.include_router(ai_settings.router, prefix="/ai", tags=["ai"])
api_router.include_router(projects.router, prefix="/projects", tags=["projects"])
api_router.include_router(telegram_sources.router, prefix="/telegram-sources", tags=["telegram-sources"])
api_router.include_router(comment_tasks.router, prefix="/comment-tasks", tags=["comment-tasks"])
api_router.include_router(safety.router, prefix="/safety", tags=["safety"])
api_router.include_router(profile.router, prefix="/accounts", tags=["accounts-profile"])
api_router.include_router(proxy_vendor.router, prefix="/proxy-vendor", tags=["proxy-vendor"])
api_router.include_router(warmup_phases.router, prefix="/phase-warmup", tags=["warmup-phases"])
api_router.include_router(personal_channel_templates.router, prefix="/personal-channel-templates", tags=["personal-channel-templates"])
api_router.include_router(join_pool.router, prefix="/join-pool", tags=["join-pool"])

app.include_router(api_router, prefix=settings.API_V1_STR)

@app.get("/")
def root():
    return {"message": "Welcome to Telegram Comb API"}

@app.get("/api/health")
def health():
    return {"status": "ok"}

@app.get("/api/v1/health")
def health_v1():
    return {"status": "ok"}
