"""Account-to-account warm-up conversations.

Real accounts that DM each other look far more human to Telegram than
accounts that only read channels. This module holds 25 short, natural
Russian chat scripts and a runner that makes two of the operator's own
accounts actually exchange those messages — through the proxy, the
shared rate limiter, and with typing/▶ delays so it reads like a person.

"Each with each", not pairs
---------------------------
``run_warmup_conversations`` rotates partners so that over successive
runs every account talks to a different account (not the same fixed
pair). With ``round`` advancing each invocation, N accounts cover all
N-1 partners over N-1 rounds.
"""
from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime
from typing import Optional

from pyrogram.errors import FloodWait
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.core.rate_limiter import NewbornAccountError, RateLimitExceeded, rate_limiter
from app.core.safety_guidelines import effective_account_age_days, phase_for_age_days
from app.db.session import SessionLocal
from app.models.account import Account, AccountStatus
from app.services.telegram_service import telegram_service

logger = logging.getLogger(__name__)


# Each script is an ordered list of (speaker, text). "a" is whoever
# started the chat, "b" is the partner. Kept short, casual and varied so
# 50 accounts don't all send identical text. No links, no marketing.
CONVERSATION_SCRIPTS: list[list[tuple[str, str]]] = [
    [("a", "привет) как ты?"), ("b", "привет! да норм, ты как"), ("a", "тоже хорошо, отдыхаю")],
    [("a", "о, давно не виделись"), ("b", "ага, я закрутился совсем"), ("a", "понимаю, сам так же"), ("b", "надо чаще списываться")],
    [("a", "ты сегодня занят?"), ("b", "вечером свободен, а что"), ("a", "да думал прогуляться"), ("b", "можно, погода норм")],
    [("a", "видел какая погода?"), ("b", "да, наконец потеплело"), ("a", "вот и я думаю выйти")],
    [("a", "что по планам на выходные"), ("b", "пока без планов"), ("a", "поехали за город?"), ("b", "идея норм, обсудим")],
    [("a", "ты кофе любишь?"), ("b", "не могу без него утром"), ("a", "о, родственная душа"), ("b", "давай как-нибудь зайдём в кофейню")],
    [("a", "посоветуй фильм на вечер"), ("b", "недавно смотрел один, зашёл"), ("a", "что за"), ("b", "потом скину название, на телефоне нет")],
    [("a", "как работа?"), ("b", "много задач, но справляюсь"), ("a", "держись там"), ("b", "спасибо, и ты)")],
    [("a", "ты в зал ходишь?"), ("b", "стараюсь три раза в неделю"), ("a", "красава, я ленюсь"), ("b", "пошли вместе, веселее")],
    [("a", "что слушаешь сейчас?"), ("b", "да старое в основном"), ("a", "о, я тоже за классику"), ("b", "скинь плейлист потом")],
    [("a", "обедал уже?"), ("b", "только собираюсь"), ("a", "приятного)"), ("b", "спс)")],
    [("a", "как настроение?"), ("b", "бодрое сегодня"), ("a", "это хорошо")],
    [("a", "ты откуда родом?"), ("b", "из небольшого города"), ("a", "о, я тоже не из столицы"), ("b", "земляки почти)")],
    [("a", "котов любишь?"), ("b", "обожаю, у меня два"), ("a", "вот это да"), ("b", "потом фото покажу")],
    [("a", "планируешь отпуск?"), ("b", "думаю про море"), ("a", "самое то сейчас"), ("b", "лишь бы время найти")],
    [("a", "ты раньше вставал сегодня?"), ("b", "да, не спалось"), ("a", "бывает, я тоже сова")],
    [("a", "что нового?"), ("b", "да всё по-старому"), ("a", "стабильность это хорошо)")],
    [("a", "помоги советом потом"), ("b", "конечно, что такое"), ("a", "да мелочь, спишемся вечером"), ("b", "ок, на связи")],
    [("a", "ты завтракаешь обычно?"), ("b", "редко, чаще просто кофе"), ("a", "врачи бы поругали нас)"), ("b", "ха, это точно")],
    [("a", "как дорога была?"), ("b", "пробки, но доехал"), ("a", "главное добрался")],
    [("a", "читаешь что-нибудь сейчас?"), ("b", "начал одну книгу"), ("a", "интересная?"), ("b", "пока втягиваюсь")],
    [("a", "спортом не занялся ещё?"), ("b", "бегаю по утрам недавно"), ("a", "уважаю"), ("b", "присоединяйся)")],
    [("a", "ты где пропадал?"), ("b", "да дела семейные"), ("a", "понимаю, бывает"), ("b", "сейчас посвободнее")],
    [("a", "какие планы на лето?"), ("b", "хочу больше гулять"), ("a", "поддерживаю идею")],
    [("a", "доброе утро)"), ("b", "доброе! выспался?"), ("a", "не очень, но кофе спасёт"), ("b", "классика наша")],
]


def _target_handle(account: Account) -> Optional[str]:
    """A peer the *other* account can resolve. Public username preferred."""
    if account.username:
        return account.username
    return None


def _age_days(account: Account) -> int:
    # Status-aware so imported aged/production accounts aren't treated as
    # newborn (and thus excluded from warm-up chats).
    return effective_account_age_days(account)


async def _send_humanized(client, target: str, text: str, account: Account) -> bool:
    """Send one message through the rate limiter with typing simulation."""
    try:
        await rate_limiter.acquire("send", account.id, account_age_days=_age_days(account))
    except (NewbornAccountError, RateLimitExceeded) as exc:
        logger.info("warmup chat skip for account %s: %s", account.id, exc)
        return False
    try:
        try:
            await client.send_chat_action(target, "typing")
            await asyncio.sleep(min(len(text) * 0.08, 6) + random.uniform(0.5, 2.0))
        except Exception:  # noqa: BLE001
            pass
        await client.send_message(target, text)
        return True
    except FloodWait as e:
        logger.warning("warmup chat FloodWait acc %s: %ss", account.id, e.value)
        await asyncio.sleep(e.value)
        return False
    except Exception as e:  # noqa: BLE001
        logger.warning("warmup chat send failed acc %s -> %s: %s", account.id, target, e)
        return False


async def run_conversation(account_a: Account, account_b: Account, script=None) -> dict:
    """Run one scripted dialogue between two of the operator's accounts."""
    result = {
        "account_a": account_a.id,
        "account_b": account_b.id,
        "messages_sent": 0,
        "errors": [],
    }
    target_a = _target_handle(account_a)
    target_b = _target_handle(account_b)
    if not target_a or not target_b:
        result["errors"].append("one of the accounts has no public username to DM")
        return result

    script = script or random.choice(CONVERSATION_SCRIPTS)
    try:
        client_a = await asyncio.wait_for(telegram_service.get_client(account_a), timeout=45)
        client_b = await asyncio.wait_for(telegram_service.get_client(account_b), timeout=45)
    except Exception as e:  # noqa: BLE001
        result["errors"].append(f"connect failed: {e}")
        return result

    for speaker, text in script:
        if speaker == "a":
            ok = await _send_humanized(client_a, target_b, text, account_a)
        else:
            ok = await _send_humanized(client_b, target_a, text, account_b)
        if ok:
            result["messages_sent"] += 1
        # Human-like pause between turns (reading + thinking).
        await asyncio.sleep(random.uniform(8, 25))
    return result


def _rotate_pairs(accounts: list[Account], round_index: int) -> list[tuple[Account, Account]]:
    """Round-robin pairing so each round pairs everyone with a NEW partner.

    Classic circle method: fix the first account, rotate the rest. With
    ``round_index`` advancing, N accounts cover all N-1 partners over
    N-1 rounds — i.e. "each talks to each", not the same pair twice.
    """
    n = len(accounts)
    if n < 2:
        return []
    arr = accounts[:]
    if n % 2 == 1:
        arr.append(None)  # bye
        n += 1
    fixed = arr[0]
    rest = arr[1:]
    r = round_index % (n - 1)
    rest = rest[r:] + rest[:r]
    ring = [fixed] + rest
    pairs = []
    for i in range(n // 2):
        x, y = ring[i], ring[n - 1 - i]
        if x is not None and y is not None:
            pairs.append((x, y))
    return pairs


async def run_warmup_conversations(
    project_id: int = 1,
    round_index: int = 0,
    max_pairs: Optional[int] = None,
) -> dict:
    """Pair up eligible accounts and have each pair run a random dialogue.

    Eligible = WARMING/PRODUCTION, authorised (session), proxy bound,
    public username, past the newborn window.
    """
    async with SessionLocal() as db:
        accounts = (
            await db.execute(
                select(Account)
                .options(selectinload(Account.proxy))
                .where(
                    Account.project_id == project_id,
                    Account.status.in_([AccountStatus.WARMING, AccountStatus.PRODUCTION]),
                    Account.session_string.isnot(None),
                    Account.session_string != "",
                )
            )
        ).scalars().all()

    now = datetime.utcnow()
    eligible = [
        acc
        for acc in accounts
        if acc.proxy_id
        and acc.username
        # Phase check via effective age (handles imported production accounts correctly).
        and phase_for_age_days(_age_days(acc)).name not in ("newborn", "infant")
        # Real DB age check: account must have existed in our database for 7+ days.
        # effective_account_age_days() returns 30 for PRODUCTION accounts even if
        # imported today — this guard prevents those fresh imports from immediately
        # DMing each other, which Telegram's ML flags as coordinated bot activity.
        and (now - (acc.created_at or now)).days >= 7
    ]
    if len(eligible) < 2:
        return {"status": "skipped", "reason": "need at least 2 eligible accounts (7+ real days in DB, past infant phase)", "eligible": len(eligible)}

    pairs = _rotate_pairs(eligible, round_index)
    # Cap at 3 pairs per run regardless of max_pairs — too many simultaneous
    # account conversations at the same time is a correlated-bot signal.
    cap = min(max_pairs, 3) if max_pairs else 3
    pairs = pairs[:cap]

    results = []
    for a, b in pairs:
        results.append(await run_conversation(a, b))
        # Longer pause between pairs — accounts shouldn't all finish conversations
        # at the same timestamp.
        await asyncio.sleep(random.uniform(60, 180))

    return {
        "status": "completed",
        "round": round_index,
        "eligible": len(eligible),
        "pairs": len(pairs),
        "messages_sent": sum(r["messages_sent"] for r in results),
        "results": results,
    }
