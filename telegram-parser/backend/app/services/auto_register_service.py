"""Automatic Telegram account registration via the smsfast number service.

The operator picks a proxy and presses "create account automatically".
From there everything is hands-off:

1. Determine the target country (from the proxy's country, or an
   explicit override) and order a Telegram number in that country.
2. Create / update the account row with that phone, bound to the proxy,
   using the global Telegram app credentials.
3. Ask Telegram to send the login code to the number (through the proxy).
4. Poll smsfast for the incoming SMS code for up to ``CODE_WAIT_SECONDS``
   (8 minutes).
5. On code → sign in, store the session, tell smsfast the activation
   succeeded. Done.
6. On timeout (no code in 8 min) → cancel the number (smsfast refunds
   the money), order a fresh number and start over — repeating until a
   code finally arrives or ``MAX_ATTEMPTS`` is exhausted.

Progress is kept in an in-memory registry keyed by ``account_id`` so the
UI can poll a live status (ordering → number received → waiting for code
with a countdown → retrying → done/failed). This mirrors the existing
``warmup_runner`` pattern; losing progress on a server restart is
acceptable — the half-created account row stays unauthorized and the
operator can simply re-run it (smsfast auto-refunds abandoned numbers on
its own side).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from pyrogram import errors

from app.db.session import SessionLocal
from app.models.account import Account, AccountStatus
from app.services import account_service
from app.services.smsfast_service import (
    NoBalanceError,
    NoNumbersError,
    SmsFastError,
    smsfast_service,
)
from app.services.sms_countries import country_id_for_iso, country_name

logger = logging.getLogger(__name__)

# How long to wait for the SMS on a single number before giving up on it,
# cancelling (refund) and ordering a fresh one.
CODE_WAIT_SECONDS = 8 * 60
# Poll smsfast this often while waiting for the code.
POLL_INTERVAL_SECONDS = 5
# How many numbers we'll burn through before giving up on a single account.
MAX_ATTEMPTS = 30
# Never buy another number until the previous cancellation is confirmed.
CANCEL_CONFIRM_TIMEOUT_SECONDS = 10 * 60
CANCEL_RETRY_SECONDS = 10


# account_id → live job dict. Only one registration per account at a time.
_jobs: Dict[int, Dict[str, Any]] = {}
# Strong refs so background tasks aren't garbage-collected mid-run.
_tasks: Dict[int, asyncio.Task] = {}


def _new_job(account_id: int, country_id: int, project_id: int) -> Dict[str, Any]:
    return {
        "account_id": account_id,
        "running": True,
        "phase": "starting",
        "message": "Запуск автоматической регистрации…",
        "country_id": country_id,
        "country_name": country_name(country_id),
        "project_id": project_id,
        "phone": None,
        "activation_id": None,
        "attempt": 0,
        "max_attempts": MAX_ATTEMPTS,
        "code": None,
        "deadline": None,        # ISO time when the current number's window ends
        "error": None,
        "started_at": datetime.utcnow().isoformat(),
        "finished_at": None,
    }


def _set(account_id: int, **patch: Any) -> None:
    job = _jobs.get(account_id)
    if job is not None:
        job.update(patch)


def get_job(account_id: int) -> Optional[Dict[str, Any]]:
    """Public snapshot for the status endpoint (None if no job exists)."""
    return _jobs.get(account_id)


def is_running(account_id: int) -> bool:
    job = _jobs.get(account_id)
    return bool(job and job.get("running"))


def has_running_jobs(project_id: Optional[int] = None) -> bool:
    return any(
        job.get("running")
        and (project_id is None or job.get("project_id") == project_id)
        for job in _jobs.values()
    )


async def _persist_activation(
    db,
    account: Account,
    activation_id: str,
    phone: str,
    country_id: int,
) -> None:
    factors = dict(account.health_factors or {})
    factors["auto_register_activation"] = {
        "activation_id": activation_id,
        "phone": phone,
        "country_id": country_id,
        "ordered_at": datetime.utcnow().isoformat(),
    }
    account.health_factors = factors
    await db.commit()


async def _clear_persisted_activation(
    db,
    account: Account,
    *,
    restore_phone: Optional[str] = None,
) -> None:
    if restore_phone is not None:
        account.phone_number = restore_phone
    factors = dict(account.health_factors or {})
    factors.pop("auto_register_activation", None)
    account.health_factors = factors or None
    await db.commit()


async def _cancel_and_confirm(
    db,
    account: Account,
    activation_id: str,
    *,
    restore_phone: str,
) -> None:
    """Do not permit a replacement purchase until refund is confirmed."""
    deadline = datetime.utcnow() + timedelta(seconds=CANCEL_CONFIRM_TIMEOUT_SECONDS)
    last_error = ""
    while datetime.utcnow() < deadline:
        _set(
            account.id,
            phase="cancelling",
            message=(
                f"Отменяю номер и жду подтверждение возврата "
                f"(активация {activation_id})…"
            ),
        )
        try:
            state, _ = await smsfast_service.get_status(activation_id)
            if state == "cancel":
                await _clear_persisted_activation(
                    db, account, restore_phone=restore_phone
                )
                return
            await smsfast_service.cancel(activation_id)
            state, _ = await smsfast_service.get_status(activation_id)
            if state == "cancel":
                await _clear_persisted_activation(
                    db, account, restore_phone=restore_phone
                )
                return
            last_error = f"статус после отмены: {state}"
        except SmsFastError as exc:
            last_error = str(exc)
        await asyncio.sleep(CANCEL_RETRY_SECONDS)

    raise SmsFastError(
        f"SMSFAST не подтвердил возврат по активации {activation_id} "
        f"за 10 минут: {last_error}. Новые номера не заказывались."
    )


async def _cleanup_login_client(account_id: int) -> None:
    """Disconnect and drop any half-open Telegram login client.

    ``account_service.request_code`` leaves a connected client in
    ``login_clients`` for ``login`` to consume. When we abandon a number
    (timeout / reorder) before signing in, that client must be closed so
    we don't leak sockets or carry a stale connection into the next try.
    """
    client = account_service.login_clients.pop(account_id, None)
    if client is not None:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass


async def _attempt_once(db, account: Account, country_id: int, attempt: int) -> Optional[str]:
    """Run one full number→code→login attempt.

    Returns ``"success"`` on a completed sign-in, ``"retry"`` when this
    number didn't work out (already cleaned up; caller should reorder),
    or raises :class:`SmsFastError` for fatal provider errors
    (no balance, etc).
    """
    account_id = account.id
    activation_id: Optional[str] = None
    placeholder_phone = account.phone_number

    # 1) Order a number.
    _set(account_id, phase="ordering", attempt=attempt,
         message=f"Заказываю номер ({country_name(country_id)})… попытка {attempt}")
    try:
        activation_id, phone = await smsfast_service.get_number(country_id)
    except SmsFastError as exc:
        # ERROR_SQL is a transient SMSFAST server error — treat as retryable,
        # not fatal, so the outer loop picks another number instead of dying.
        if getattr(exc, "code", None) == "ERROR_SQL":
            logger.warning("SMSFAST ERROR_SQL during getNumber (attempt %s): %s", attempt, exc)
            _set(account_id, phase="retrying",
                 message="SMSFAST временно недоступен (SQL). Повторяю через 10 секунд…")
            await asyncio.sleep(10)
            return "retry"
        raise

    phone_e164 = phone if phone.startswith("+") else f"+{phone}"
    await _persist_activation(db, account, activation_id, phone_e164, country_id)
    _set(account_id, activation_id=activation_id, phone=phone_e164,
         phase="number_received",
         message=f"Получен номер {phone_e164}. Отправляю запрос кода в Telegram…")

    try:
        return await _attempt_once_inner(
            db, account, account_id, country_id, activation_id, phone_e164, attempt,
            placeholder_phone
        )
    except BaseException:
        logger.warning("Unexpected exception in attempt %s, cancelling activation %s",
                       attempt, activation_id)
        await _cancel_and_confirm(
            db, account, activation_id, restore_phone=placeholder_phone
        )
        raise


async def _attempt_once_inner(
    db, account: Account, account_id: int, country_id: int,
    activation_id: str, phone_e164: str, attempt: int, placeholder_phone: str
) -> Optional[str]:
    """Inner body of _attempt_once — runs after the number is ordered."""
    # 2) Set phone in memory so request_code can use it, but do NOT commit
    #    yet — the DB row keeps its 'pending_xxx' value until login succeeds.
    #    This way a backend restart leaves clearly-detectable orphan rows.
    account.phone_number = phone_e164

    # 3) Ask Telegram to send the login code (through the proxy).
    try:
        sent_code = await account_service.request_code(db, account)
        phone_code_hash = sent_code.phone_code_hash
    except Exception as exc:  # noqa: BLE001
        # Telegram refused this number (banned / flood / invalid). Drop it,
        # refund, and let the caller order a different one.
        logger.warning("send_code failed for %s (%s): %s", account_id, phone_e164, exc)
        _set(account_id, phase="retrying",
             message=f"Telegram отклонил номер {phone_e164}. Отменяю и беру новый…")
        await _cleanup_login_client(account_id)
        await _cancel_and_confirm(
            db, account, activation_id, restore_phone=placeholder_phone
        )
        return "retry"

    # 4) Poll for the SMS code until the 10-minute window closes.
    deadline = datetime.utcnow() + timedelta(seconds=CODE_WAIT_SECONDS)
    _set(account_id, phase="waiting_code", deadline=deadline.isoformat(),
         message=f"Жду код на {phone_e164} (до 8 минут)…")

    while datetime.utcnow() < deadline:
        if not is_running(account_id):  # operator cancelled the job
            await _cleanup_login_client(account_id)
            await _cancel_and_confirm(
                db, account, activation_id, restore_phone=placeholder_phone
            )
            return "cancelled"
        try:
            state, code = await smsfast_service.get_status(activation_id)
        except SmsFastError as exc:
            logger.warning("getStatus failed for %s: %s", activation_id, exc)
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            continue

        if state == "ok" and code:
            # 5) Got the code — finish the Telegram sign-in.
            _set(account_id, code=code, phase="logging_in",
                 message=f"Код {code} получен. Завершаю вход в Telegram…")
            try:
                await account_service.login(db, account, code, phone_code_hash)
            except errors.SessionPasswordNeeded:
                # A fresh virtual number with 2FA already set is unusable
                # for us — refund and stop (operator intervention needed).
                await _cancel_and_confirm(
                    db, account, activation_id, restore_phone=placeholder_phone
                )
                raise SmsFastError(
                    "На номере включена двухфакторная защита (2FA) — "
                    "автоматическая регистрация невозможна."
                )
            except Exception as exc:  # noqa: BLE001
                # Bad/expired code or other sign-in error → drop & reorder.
                logger.warning("login failed for %s: %s", account_id, exc)
                _set(account_id, phase="retrying",
                     message=f"Код не подошёл ({str(exc)[:60]}). Беру новый номер…")
                await _cleanup_login_client(account_id)
                await _cancel_and_confirm(
                    db, account, activation_id, restore_phone=placeholder_phone
                )
                return "retry"

            # Success → persist the real phone in DB, tell smsfast done.
            account.phone_number = phone_e164
            await db.commit()
            await smsfast_service.complete(activation_id)
            await _clear_persisted_activation(db, account)
            _set(account_id, phase="done", running=False,
                 finished_at=datetime.utcnow().isoformat(),
                 message=f"Готово! Аккаунт {phone_e164} зарегистрирован и авторизован.")
            return "success"

        if state == "cancel":
            # Provider cancelled the number — reorder.
            _set(account_id, phase="retrying",
                 message="Номер отменён провайдером. Беру новый…")
            await _cleanup_login_client(account_id)
            await _clear_persisted_activation(
                db, account, restore_phone=placeholder_phone
            )
            return "retry"

        # Still waiting — update the countdown and poll again.
        remaining = int((deadline - datetime.utcnow()).total_seconds())
        _set(account_id,
             message=f"Жду код на {phone_e164}… осталось {remaining // 60}:{remaining % 60:02d}")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)

    # 6) Timed out — refund this number and reorder.
    _set(account_id, phase="retrying",
         message=f"Код не пришёл за 8 минут. Отменяю {phone_e164} (возврат денег), беру новый…")
    await _cleanup_login_client(account_id)
    await _cancel_and_confirm(
        db, account, activation_id, restore_phone=placeholder_phone
    )
    return "retry"


async def _execute(account_id: int, country_id: int, project_id: int) -> None:
    """Top-level driver: loop attempts until success or MAX_ATTEMPTS."""
    try:
        async with SessionLocal() as db:
            account = await account_service.get_account(db, account_id, project_id=project_id)
            if account is None:
                _set(account_id, running=False, phase="failed",
                     error="account_not_found", message="Аккаунт не найден.")
                return
            if account.proxy_id is None:
                _set(account_id, running=False, phase="failed",
                     error="no_proxy",
                     message="У аккаунта не привязан прокси — регистрация запрещена.")
                return

            for attempt in range(1, MAX_ATTEMPTS + 1):
                if not is_running(account_id):
                    _set(account_id, phase="cancelled", running=False,
                         finished_at=datetime.utcnow().isoformat(),
                         message="Регистрация остановлена оператором.")
                    return
                try:
                    # Re-check funds immediately before every purchase.
                    if await smsfast_service.get_balance() <= 0:
                        raise NoBalanceError(
                            "На балансе SMSFAST закончились деньги. "
                            "Номер не заказывался.",
                            code="NO_BALANCE",
                        )
                    outcome = await _attempt_once(db, account, country_id, attempt)
                except (NoNumbersError, NoBalanceError) as exc:
                    _set(account_id, running=False, phase="failed",
                         error=getattr(exc, "code", None),
                         finished_at=datetime.utcnow().isoformat(),
                         message=str(exc))
                    return
                except SmsFastError as exc:
                    _set(account_id, running=False, phase="failed",
                         error=getattr(exc, "code", None),
                         finished_at=datetime.utcnow().isoformat(),
                         message=str(exc))
                    return
                if outcome == "success":
                    return
                if outcome == "cancelled":
                    _set(account_id, phase="cancelled", running=False,
                         finished_at=datetime.utcnow().isoformat(),
                         message="Регистрация остановлена оператором.")
                    return
                # retry is allowed only after _cancel_and_confirm returned.

            _set(account_id, running=False, phase="failed",
                 finished_at=datetime.utcnow().isoformat(),
                 message=f"Не удалось получить код за {MAX_ATTEMPTS} попыток. "
                         "Попробуйте другую страну или позже.")
    except Exception as exc:  # noqa: BLE001
        logger.exception("auto-register job failed for account %s", account_id)
        _set(account_id, running=False, phase="failed",
             error=str(exc)[:200],
             finished_at=datetime.utcnow().isoformat(),
             message=f"Регистрация завершилась с ошибкой: {str(exc)[:160]}")
    finally:
        await _cleanup_login_client(account_id)


def start(account_id: int, country_id: int, project_id: int) -> Dict[str, Any]:
    """Kick off an auto-registration job for an existing account row.

    The account must already exist with a proxy bound and the global (or
    custom) Telegram app credentials set. Returns the initial job state.
    """
    if is_running(account_id):
        return {"status": "already_running", **(_jobs.get(account_id) or {})}

    _jobs[account_id] = _new_job(account_id, country_id, project_id)
    _tasks[account_id] = asyncio.create_task(_execute(account_id, country_id, project_id))
    return {"status": "started", **_jobs[account_id]}


def stop(account_id: int) -> Dict[str, Any]:
    """Request a running job to stop after its current poll tick."""
    job = _jobs.get(account_id)
    if not job:
        return {"status": "no_job"}
    job["running"] = False
    job["message"] = "Останавливаю регистрацию…"
    return {"status": "stopping", **job}


def dismiss(account_id: int) -> Dict[str, Any]:
    """Drop a finished job from the in-memory registry.

    Used when the operator closes the progress/error window: a job that
    failed (``NO_NUMBERS``, timeout, etc.) stays in ``_jobs`` forever and
    keeps the UI thinking a batch is in progress. Refuses to drop a job
    that is still running — the caller must ``stop`` it first.
    """
    job = _jobs.get(account_id)
    if job is not None and job.get("running"):
        return {"status": "still_running"}
    _jobs.pop(account_id, None)
    _tasks.pop(account_id, None)
    return {"status": "dismissed"}


async def recover_orphaned_activations() -> None:
    """Cancel persisted SMS orders left behind by a backend restart.

    The shell account is deleted only after SMSFAST reports STATUS_CANCEL.
    This preserves the activation id across crashes and prevents an unpaid
    cleanup assumption from turning into a lost balance.
    """
    from sqlalchemy import select

    async with SessionLocal() as db:
        result = await db.execute(
            select(Account).where(Account.phone_number.like("pending_%"))
        )
        accounts = result.scalars().all()
        for account in accounts:
            activation = (account.health_factors or {}).get(
                "auto_register_activation"
            )
            activation_id = (
                str(activation.get("activation_id"))
                if activation and activation.get("activation_id")
                else None
            )
            if not activation_id:
                continue
            try:
                await _cancel_and_confirm(
                    db,
                    account,
                    activation_id,
                    restore_phone=account.phone_number,
                )
                await db.delete(account)
                await db.commit()
                logger.info(
                    "Recovered and cancelled orphan SMS activation %s",
                    activation_id,
                )
            except Exception as exc:  # noqa: BLE001
                await db.rollback()
                logger.error(
                    "Could not recover SMS activation %s: %s",
                    activation_id,
                    exc,
                )
