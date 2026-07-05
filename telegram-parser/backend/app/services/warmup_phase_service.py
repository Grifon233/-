"""Phase-based warmup service.

State machine (accounts.warmup_phase):
  NULL → start_warmup() → phase=0, next_at=now+24h, locked=True
  0 → tick (24h) → profile setup → phase=1, next_at=now+24h
  1 → tick (24h) → join 10 channels + DM → phase=2, next_at=now+24h
  2 → tick (24h) → personal channel + 10 more joins + DM → phase=3, next_at=now+48h
  3 → tick (48h) → phase=4, locked=False, status=production

Rules:
  - warmup_locked=True: account skipped by commenting/campaign tasks.
  - DM conversations: exactly 1 pair (2 accounts) per phase.
  - Channel pool and personal channel are OPTIONAL — skipped when not set.
  - Tick is called on server startup and every 30 minutes by the background loop.
"""
from __future__ import annotations

import asyncio
import logging
import random
import string
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified

from app.db.session import SessionLocal
from app.models.account import Account, AccountStatus
from app.models.telegram_source import TelegramSource
from app.services.telegram_service import extract_join_target, telegram_service

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Name / username generators
# ---------------------------------------------------------------------------

_NAMES: dict[tuple[str, str], dict] = {
    ("ru", "male"): {
        "first": [
            "Алексей", "Дмитрий", "Иван", "Михаил", "Андрей", "Сергей",
            "Николай", "Артём", "Денис", "Кирилл", "Роман", "Антон",
            "Илья", "Максим", "Павел", "Владислав", "Евгений", "Тимур",
            "Глеб", "Никита",
        ],
        "last": [
            "Волков", "Соколов", "Морозов", "Лебедев", "Козлов",
            "Новиков", "Зайцев", "Орлов", "Петров", "Зимин",
            "Белов", "Захаров", "Смирнов", "Кузнецов", "Попов",
        ],
        "cities": [
            "Москва", "Санкт-Петербург", "Екатеринбург", "Казань",
            "Новосибирск", "Нижний Новгород", "Самара", "Челябинск",
        ],
        "bio": [
            "Привет! Просто живу и радуюсь жизни.",
            "Занимаюсь своим делом. Интересуюсь технологиями.",
            "Люблю путешествовать и открывать новые места.",
            "Работаю, учусь, развиваюсь. Всё как у людей.",
            "Жизнь коротка — трать её на то, что нравится.",
        ],
    },
    ("ru", "female"): {
        "first": [
            "Анна", "Мария", "Елена", "Ольга", "Наталья", "Татьяна",
            "Светлана", "Екатерина", "Ирина", "Юлия", "Виктория",
            "Дарья", "Алина", "Валерия", "Ксения", "Алёна", "Полина",
            "Кристина", "Людмила", "Вероника",
        ],
        "last": [
            "Волкова", "Соколова", "Морозова", "Лебедева", "Козлова",
            "Новикова", "Зайцева", "Орлова", "Петрова", "Зимина",
            "Белова", "Захарова", "Смирнова", "Кузнецова", "Попова",
        ],
        "cities": [
            "Москва", "Санкт-Петербург", "Екатеринбург", "Казань",
            "Новосибирск", "Нижний Новгород", "Краснодар", "Ростов-на-Дону",
        ],
        "bio": [
            "Привет! Люблю кофе и хорошие разговоры.",
            "Живу в своё удовольствие. Всё будет хорошо.",
            "Обожаю путешествия, фотографию и вкусную еду.",
            "Работа, друзья, хорошее настроение — вот и всё.",
            "Просто ищу своё место в этом мире.",
        ],
    },
    ("en", "male"): {
        "first": [
            "Alex", "James", "Michael", "David", "John", "Robert",
            "Chris", "Daniel", "Matt", "Ryan", "Kevin", "Brian",
            "Andrew", "Jason", "Eric", "Mark", "Paul", "Scott",
        ],
        "last": [
            "Miller", "Smith", "Johnson", "Williams", "Brown",
            "Jones", "Davis", "Wilson", "Moore", "Taylor",
            "Anderson", "Thomas", "Jackson", "White", "Harris",
        ],
        "cities": [
            "New York", "London", "Los Angeles", "Chicago",
            "Toronto", "Sydney", "Melbourne", "Vancouver",
        ],
        "bio": [
            "Hey! Just enjoying life and exploring the world.",
            "Tech enthusiast. Coffee lover. Always learning.",
            "Living my best life. Love to travel and meet new people.",
            "Work hard, play harder. Simple as that.",
            "Exploring new places and new ideas every day.",
        ],
    },
    ("en", "female"): {
        "first": [
            "Emma", "Anna", "Kate", "Sarah", "Julia", "Lisa",
            "Amy", "Laura", "Rachel", "Megan", "Nicole", "Ashley",
            "Jessica", "Stephanie", "Jennifer", "Natalie", "Olivia",
        ],
        "last": [
            "Miller", "Smith", "Johnson", "Williams", "Brown",
            "Jones", "Davis", "Wilson", "Moore", "Taylor",
            "Anderson", "Thomas", "Jackson", "White", "Harris",
        ],
        "cities": [
            "New York", "London", "Los Angeles", "Chicago",
            "Toronto", "Sydney", "Melbourne", "Vancouver",
        ],
        "bio": [
            "Hey there! Coffee and good vibes only.",
            "Travel lover. Bookworm. Always smiling.",
            "Exploring life one day at a time.",
            "Coffee, sunsets and good music. That's my life.",
            "Living for the little moments that matter.",
        ],
    },
}


def _translit(s: str) -> str:
    tbl = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e',
        'ё': 'yo', 'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k',
        'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r',
        'с': 's', 'т': 't', 'у': 'u', 'ф': 'f', 'х': 'h', 'ц': 'ts',
        'ч': 'ch', 'ш': 'sh', 'щ': 'sch', 'ъ': '', 'ы': 'y', 'ь': '',
        'э': 'e', 'ю': 'yu', 'я': 'ya',
    }
    return ''.join(tbl.get(c.lower(), c.lower() if c.isalpha() else '') for c in s)


def generate_profile(language: str, gender: str) -> dict:
    """Return {first_name, last_name, username, bio, location}."""
    key = (language, gender)
    pool = _NAMES.get(key, _NAMES[("ru", "male")])
    first = random.choice(pool["first"])
    last = random.choice(pool["last"])
    city = random.choice(pool["cities"])
    bio = random.choice(pool["bio"])
    suffix = ''.join(random.choices(string.digits, k=3))

    if language == "ru":
        base = _translit(first[:5]) + _translit(last[:3])
    else:
        base = first[:5].lower() + last[:3].lower()
    username = ''.join(c for c in base if c.isalnum()) + suffix
    username = username[:28]

    return {
        "first_name": first,
        "last_name": last,
        "username": username,
        "bio": bio,
        "location": city,
    }


# ---------------------------------------------------------------------------
# Phase action runners
# ---------------------------------------------------------------------------

async def _run_profile_setup(account: Account, db: AsyncSession) -> dict:
    """Phase 0→1: set name, username, bio; optionally set avatar."""
    lang = account.warmup_language or "ru"
    gender = account.gender or "male"
    profile = generate_profile(lang, gender)
    result = {"profile": profile, "name": False, "username": False, "bio": False, "avatar": False}

    try:
        client = await asyncio.wait_for(telegram_service.get_client(account), timeout=30)
    except Exception as exc:
        logger.warning("phase1 connect failed acc %s: %s", account.id, exc)
        return result

    # Set name
    try:
        await client.update_profile(
            first_name=profile["first_name"],
            last_name=profile["last_name"],
        )
        result["name"] = True
        account.first_name = profile["first_name"]
        account.last_name = profile["last_name"]
    except Exception as exc:
        logger.warning("phase1 name acc %s: %s", account.id, exc)
    await asyncio.sleep(random.uniform(12, 28))

    # Set bio
    try:
        await client.update_profile(bio=profile["bio"])
        result["bio"] = True
        account.bio = profile["bio"]
    except Exception as exc:
        logger.warning("phase1 bio acc %s: %s", account.id, exc)
    await asyncio.sleep(random.uniform(10, 20))

    # Set username — retry on collision; handle FloodWait; log every step
    uname = profile["username"]
    logger.info("phase1 username acc %s: trying @%s", account.id, uname)
    for attempt in range(5):
        try:
            await client.set_username(uname)
            result["username"] = True
            account.username = uname
            logger.info("phase1 username acc %s: set @%s (attempt %d)", account.id, uname, attempt + 1)
            break
        except Exception as exc:
            from pyrogram import errors as _pyrogram_errors
            msg = str(exc)
            if isinstance(exc, _pyrogram_errors.FloodWait):
                wait = getattr(exc, "value", 30)
                logger.warning("phase1 username acc %s: FloodWait %ds on @%s, waiting", account.id, wait, uname)
                await asyncio.sleep(wait + 2)
            elif "USERNAME_OCCUPIED" in msg or "USERNAME_INVALID" in msg:
                new_uname = uname[:22] + ''.join(random.choices(string.digits, k=4))
                logger.info("phase1 username acc %s: @%s taken/invalid → trying @%s", account.id, uname, new_uname)
                uname = new_uname
                await asyncio.sleep(random.uniform(5, 10))
            elif "USERNAME_NOT_MODIFIED" in msg:
                result["username"] = True
                account.username = uname
                logger.info("phase1 username acc %s: @%s already set", account.id, uname)
                break
            else:
                logger.warning("phase1 username acc %s: unexpected error on @%s: %s", account.id, uname, exc)
                break
    else:
        logger.warning("phase1 username acc %s: all retries exhausted, username not set", account.id)

    # Avatar from warmup_avatars/<lang>_<gender>/ directory (optional)
    avatar_dir = Path(f"warmup_avatars/{lang}_{gender}")
    if avatar_dir.exists():
        photos = list(avatar_dir.glob("*.jpg")) + list(avatar_dir.glob("*.png"))
        if photos:
            chosen = random.choice(photos)
            try:
                await client.set_profile_photo(photo=str(chosen))
                result["avatar"] = True
            except Exception as exc:
                logger.warning("phase1 avatar acc %s: %s", account.id, exc)

    return result


async def _run_joins(account: Account, db: AsyncSession, count: int = 10) -> int:
    """Join up to `count` channels from warmup_pool_ids (or all project sources)."""
    pool_ids: list[int] = account.warmup_pool_ids or []
    already_joined: list[int] = list(account.joined_source_ids or [])

    if pool_ids:
        q = select(TelegramSource).where(
            TelegramSource.id.in_(pool_ids),
            TelegramSource.is_enabled.is_(True),
        )
    else:
        q = select(TelegramSource).where(
            TelegramSource.project_id == account.project_id,
            TelegramSource.is_enabled.is_(True),
        )
    result = await db.execute(q)
    candidates = [s for s in result.scalars().all()
                  if s.id not in already_joined and s.normalized_link]
    random.shuffle(candidates)
    to_join = candidates[:count]
    if not to_join:
        return 0

    try:
        client = await asyncio.wait_for(telegram_service.get_client(account), timeout=30)
    except Exception as exc:
        logger.warning("join connect failed acc %s: %s", account.id, exc)
        return 0

    joined = 0
    for source in to_join:
        try:
            await client.join_chat(extract_join_target(source.normalized_link))
            already_joined.append(source.id)
            joined += 1
            logger.info("acc %s joined %s", account.id, source.normalized_link)
        except Exception as exc:
            logger.warning("acc %s join %s: %s", account.id, source.normalized_link, exc)
        # Long pause between joins — 3-8 minutes
        await asyncio.sleep(random.uniform(180, 480))

    account.joined_source_ids = already_joined
    flag_modified(account, "joined_source_ids")
    return joined


async def _run_dm_chat(account: Account, db: AsyncSession) -> bool:
    """Exchange a scripted DM conversation with exactly 1 partner account."""
    # Find 1 other account also in phase warmup, with username + session + proxy
    result = await db.execute(
        select(Account)
        .where(
            Account.id != account.id,
            Account.project_id == account.project_id,
            Account.warmup_phase.isnot(None),
            Account.warmup_phase < 4,
            Account.username.isnot(None),
            Account.session_string.isnot(None),
            Account.proxy_id.isnot(None),
        )
        .options(selectinload(Account.proxy))
        .limit(10)
    )
    candidates = result.scalars().all()
    if not candidates:
        logger.info("acc %s: no DM partner found (warmup)", account.id)
        return False

    partner = random.choice(candidates)
    if not account.username:
        logger.info("acc %s has no username yet, skip DM", account.id)
        return False

    from app.services.warmup_conversations import CONVERSATION_SCRIPTS, _send_humanized
    script = random.choice(CONVERSATION_SCRIPTS)

    try:
        client_a = await asyncio.wait_for(telegram_service.get_client(account), timeout=30)
        client_b = await asyncio.wait_for(telegram_service.get_client(partner), timeout=30)
    except Exception as exc:
        logger.warning("DM connect failed: %s", exc)
        return False

    sent = 0
    for speaker, text in script:
        try:
            if speaker == "a":
                ok = await _send_humanized(client_a, partner.username, text, account)
            else:
                ok = await _send_humanized(client_b, account.username, text, partner)
            if ok:
                sent += 1
        except Exception as exc:
            logger.warning("DM send: %s", exc)
        await asyncio.sleep(random.uniform(8, 25))

    logger.info("acc %s DM with %s: %d messages", account.id, partner.id, sent)
    return sent > 0


async def _run_personal_channel(account: Account, db: AsyncSession) -> bool:
    """Create personal channel from template (optional — skip if not configured)."""
    if not account.personal_channel_template_id:
        return False
    if account.personal_channel_id:
        return True  # already exists

    from app.services import profile_service
    try:
        # Note: the template should ideally be fetched, but for now we just create a generic channel
        # since the real template logic applies later or we need to pass the title.
        await profile_service.create_personal_channel(db, account, title=account.first_name or "Канал")
        return True
    except Exception as exc:
        logger.warning("acc %s personal channel: %s", account.id, exc)
        return False


# ---------------------------------------------------------------------------
# Main tick — called on startup and every 30 min
# ---------------------------------------------------------------------------

PHASE_SLEEP_HOURS = {0: 24, 1: 24, 2: 24, 3: 48}

_tick_task: Optional[asyncio.Task] = None
_tick_state: dict = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "advanced": 0,
    "error": None,
}


async def _run_tick_background() -> None:
    global _tick_state
    _tick_state = {
        "running": True,
        "started_at": datetime.utcnow().isoformat(),
        "finished_at": None,
        "advanced": 0,
        "error": None,
    }
    try:
        advanced = await tick_all()
        _tick_state.update(
            running=False,
            finished_at=datetime.utcnow().isoformat(),
            advanced=advanced,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("phase warmup background tick failed")
        _tick_state.update(
            running=False,
            finished_at=datetime.utcnow().isoformat(),
            error=str(exc)[:300],
        )


def start_tick_background() -> dict:
    """Start phase warmup tick without blocking the HTTP request."""
    global _tick_task
    if _tick_task is not None and not _tick_task.done():
        return {"status": "already_running", **_tick_state}

    _tick_task = asyncio.create_task(_run_tick_background())
    return {
        "status": "started",
        "running": True,
        "started_at": datetime.utcnow().isoformat(),
    }


def get_tick_state() -> dict:
    return dict(_tick_state)


async def tick_all() -> int:
    """Advance all accounts in phase warmup where the sleep period has elapsed.

    Returns the number of accounts that were advanced.
    """
    now = datetime.utcnow()
    advanced = 0

    async with SessionLocal() as db_ids:
        result = await db_ids.execute(
            select(Account.id)
            .where(Account.warmup_phase.isnot(None), Account.warmup_phase < 4)
        )
        account_ids = result.scalars().all()

    for acc_id in account_ids:
        async with SessionLocal() as db:
            result = await db.execute(
                select(Account).where(Account.id == acc_id).options(selectinload(Account.proxy))
            )
            account = result.scalars().first()
            if not account:
                continue

            if account.warmup_next_phase_at and now < account.warmup_next_phase_at:
                continue  # still sleeping

            phase = account.warmup_phase
            logger.info("Warmup tick: acc %s phase %s → running", account.id, phase)

            try:
                if phase == 0:
                    await _run_profile_setup(account, db)
                    account.warmup_phase = 1
                    account.warmup_next_phase_at = datetime.utcnow() + timedelta(hours=24)

                elif phase == 1:
                    has_pool = bool(account.warmup_pool_ids)
                    if has_pool:
                        await _run_joins(account, db, count=10)
                    await _run_dm_chat(account, db)
                    account.warmup_phase = 2
                    account.warmup_next_phase_at = datetime.utcnow() + timedelta(hours=24)

                elif phase == 2:
                    await _run_personal_channel(account, db)
                    has_pool = bool(account.warmup_pool_ids)
                    if has_pool:
                        await _run_joins(account, db, count=10)
                    await _run_dm_chat(account, db)
                    account.warmup_phase = 3
                    account.warmup_next_phase_at = datetime.utcnow() + timedelta(hours=48)

                elif phase == 3:
                    account.warmup_phase = 4
                    account.warmup_locked = False
                    account.warmup_next_phase_at = None
                    if account.status != AccountStatus.PRODUCTION:
                        account.status = AccountStatus.PRODUCTION
                    logger.info("acc %s warmup DONE → production", account.id)

                await db.commit()
                advanced += 1

            except Exception as exc:
                logger.error("tick error acc %s phase %s: %s", account.id, phase, exc, exc_info=True)
                await db.rollback()

    return advanced


# ---------------------------------------------------------------------------
# Start warmup for a batch of accounts
# ---------------------------------------------------------------------------

async def start_warmup(
    account_ids: list[int],
    language: str,
    gender: str,
    pool_ids: list[int],
    channel_template_id: Optional[int],
) -> dict:
    """Initialize phase warmup for the given accounts.

    Accounts already in warmup (phase 0-3) are skipped.
    """
    now = datetime.utcnow()
    started = 0
    skipped = 0

    async with SessionLocal() as db:
        result = await db.execute(
            select(Account).where(Account.id.in_(account_ids))
        )
        accounts = result.scalars().all()

        for account in accounts:
            if account.warmup_phase is not None and account.warmup_phase < 4:
                skipped += 1
                continue

            account.warmup_phase = 0
            account.warmup_next_phase_at = now + timedelta(hours=24)
            account.warmup_language = language
            account.warmup_locked = True
            account.warmup_pool_ids = pool_ids or []
            if channel_template_id:
                account.personal_channel_template_id = channel_template_id
            account.gender = gender
            if account.status != AccountStatus.BANNED:
                account.status = AccountStatus.WARMING
            started += 1

        await db.commit()

    return {"started": started, "skipped": skipped}


# ---------------------------------------------------------------------------
# Status helpers
# ---------------------------------------------------------------------------

PHASE_LABELS = {
    None: "Не в прогреве",
    0: "Ожидание 24ч",
    1: "Настройка профиля ✓ — сон 24ч",
    2: "Вступления ✓ — сон 24ч",
    3: "Канал ✓ — сон 48ч",
    4: "Готов",
}


def get_phase_label(phase: Optional[int]) -> str:
    return PHASE_LABELS.get(phase, "—")


# Cumulative warmup hours completed *before* entering each phase.
# Derived from PHASE_SLEEP_HOURS (24+24+24+48 = 120h ≈ 5 суток total).
PHASE_CUMULATIVE_HOURS = {0: 0, 1: 24, 2: 48, 3: 72, 4: 120}
TOTAL_WARMUP_HOURS = 120


def warmup_progress(phase: Optional[int], hours_left: float) -> dict:
    """Compute an overall warmup progress (percent + days elapsed).

    We do not store a "warmup started at" timestamp, so progress is
    reconstructed from the current phase plus how far we are into the
    current phase's sleep window (phase_duration - hours_remaining).
    """
    if phase is None:
        return {"progress_percent": 0, "days_elapsed": 0.0, "total_days": 5}
    if phase >= 4:
        return {"progress_percent": 100, "days_elapsed": 5.0, "total_days": 5}

    duration = PHASE_SLEEP_HOURS.get(phase, 24)
    elapsed_in_phase = max(0.0, duration - hours_left)
    elapsed_total = PHASE_CUMULATIVE_HOURS.get(phase, 0) + elapsed_in_phase
    percent = min(100, round(elapsed_total / TOTAL_WARMUP_HOURS * 100))
    return {
        "progress_percent": percent,
        "days_elapsed": round(elapsed_total / 24, 1),
        "total_days": 5,
    }


def phase_status(account: Account) -> dict:
    now = datetime.utcnow()
    nxt = account.warmup_next_phase_at
    hours_left = max(0.0, round((nxt - now).total_seconds() / 3600, 1)) if nxt and nxt > now else 0.0
    proxy = account.proxy if "proxy" in account.__dict__ else None
    return {
        "id": account.id,
        "phone_number": account.phone_number,
        "status": account.status.value if hasattr(account.status, "value") else account.status,
        "warmup_phase": account.warmup_phase,
        "phase_label": get_phase_label(account.warmup_phase),
        "warmup_language": account.warmup_language,
        "warmup_gender": account.gender,
        "warmup_locked": bool(account.warmup_locked),
        "next_phase_at": nxt.isoformat() if nxt else None,
        "hours_remaining": hours_left,
        "has_pool": bool(account.warmup_pool_ids),
        "pool_count": len(account.warmup_pool_ids or []),
        "has_channel_template": bool(account.personal_channel_template_id),
        "proxy_id": account.proxy_id,
        "proxy_country": (proxy.country.upper() if proxy and proxy.country else None),
        "proxy_label": (f"{proxy.host}:{proxy.port}" if proxy else None),
        "has_session": bool(account.session_string),
        "first_name": account.first_name,
        "username": account.username,
        **warmup_progress(account.warmup_phase, hours_left),
    }
