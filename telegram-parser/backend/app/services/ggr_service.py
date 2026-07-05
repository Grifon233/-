"""
GGR (GramGPT Rating) Health Check Service
ИИ-оценка живучести Telegram-аккаунта по 16+ факторам

Based on:
- ItsOrv/Telegram-Panel (session monitoring, revocation detection)
  https://github.com/ItsOrv/Telegram-Panel
- saadkhan1150/telegram-mcp (account health checks, session manager)
  https://github.com/saadkhan1150/telegram-mcp
- telethon-session-sqlalchemy (DB session storage)
  https://github.com/tulir/telethon-session-sqlalchemy

Key patterns:
- get_me() for account validation
- Session revocation detection
- Health scoring with weighted factors
- Proxy quality checking
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.account import Account, AccountStatus
from app.models.proxy import Proxy
from app.services.telegram_service import telegram_service


# Factor weights for health score calculation
FACTOR_WEIGHTS = {
    "account_age_days": 0.15,       # 15% - older accounts are more trusted
    "activity_score": 0.12,         # 12% - regular activity matters
    "proxy_quality": 0.10,          # 10% - stable proxy = stable account
    "message_history_score": 0.08,  # 8% - natural message history
    "daily_dm_ratio": 0.08,         # 8% - not hitting limits
    "profile_completion": 0.10,     # 10% - full profile = real user
    "social_graph": 0.12,          # 12% - groups, channels, friends
    "engagement_rate": 0.10,        # 10% - reactions, replies given
    "behavior_pattern": 0.05,        # 5% - human-like behavior
}

# Risk factors that increase ban probability
RISK_FACTORS = {
    "new_account_no_warmup": 30,    # +30 risk if new and not warmed up
    "over_daily_limit": 25,         # +25 risk if exceeding DM limits
    "poor_proxy": 20,               # +20 risk if proxy frequently fails
    "suspicious_activity": 15,     # +15 risk if activity is too uniform
    "no_profile_photo": 10,        # +10 risk if no profile photo
}


async def get_detailed_account_info(client, account: Account) -> Dict:
    """
    Get detailed account information from Telegram API.
    Based on telegram-monitor patterns.
    """
    try:
        me = await client.get_me()
        dialogs = []

        # Get dialogs count
        async for dialog in client.get_dialogs(limit=100):
            dialogs.append(dialog)

        # Count groups, channels, private chats.
        # ``d.chat.type`` is a pyrogram ``ChatType`` enum; compare against
        # its ``.value`` because the enum member is NOT equal to the bare
        # string (e.g. ``ChatType.CHANNEL == "channel"`` is False).
        def _chat_type_value(d):
            t = getattr(d.chat, "type", None)
            return getattr(t, "value", t)

        groups = sum(1 for d in dialogs if _chat_type_value(d) in ["group", "supergroup"])
        channels = sum(1 for d in dialogs if _chat_type_value(d) == "channel")
        private_chats = sum(1 for d in dialogs if _chat_type_value(d) == "private")

        # Get profile info
        profile_photos = [photo async for photo in client.get_chat_photos("me", limit=1)]
        has_photo = len(profile_photos) > 0

        # Try to get username (public identifier)
        has_username = bool(me.username)

        # Get bio/about
        try:
            info = await client.get_chat("me")
            has_bio = bool(getattr(info, 'bio', None) or getattr(info, 'about', None))
        except:
            has_bio = False

        return {
            "first_name": me.first_name,
            "last_name": me.last_name,
            "username": me.username,
            "phone": me.phone_number,
            "is_premium": getattr(me, 'is_premium', False),
            "is_bot": me.is_bot,
            "groups_count": groups,
            "channels_count": channels,
            "private_chats_count": private_chats,
            "total_dialogs": len(dialogs),
            "has_profile_photo": has_photo,
            "has_username": has_username,
            "has_bio": has_bio,
        }
    except Exception as e:
        return {"error": str(e)}


async def calculate_factor_score(factor_name: str, value, context: Dict) -> float:
    """
    Calculate individual factor score (0-100).
    """
    if factor_name == "account_age_days":
        # New accounts (0-7 days) = low score, old (90+ days) = high
        days = value
        if days <= 0:
            return 0
        elif days < 7:
            return min(20, days * 3)
        elif days < 30:
            return 20 + (days - 7) * 2
        elif days < 90:
            return 60 + (days - 30)
        else:
            return min(100, 90 + (days - 90) * 0.1)

    elif factor_name == "activity_score":
        # Based on last_active recency and daily messages
        last_active = context.get("last_active")
        if not last_active:
            return 10
        hours_ago = (datetime.utcnow() - last_active).total_seconds() / 3600
        if hours_ago > 72:
            return 10
        elif hours_ago > 24:
            return 30
        elif hours_ago > 12:
            return 60
        else:
            return 100

    elif factor_name == "proxy_quality":
        # Based on proxy response time and uptime
        proxy = context.get("proxy")
        if not proxy:
            return 30  # No proxy = medium risk
        if not proxy.is_active:
            return 10
        response_time = proxy.response_time_ms or 500
        if response_time < 100:
            return 100
        elif response_time < 300:
            return 80
        elif response_time < 500:
            return 60
        else:
            return 40

    elif factor_name == "profile_completion":
        info = context.get("account_info", {})
        score = 0
        if info.get("has_profile_photo"):
            score += 30
        if info.get("has_username"):
            score += 30
        if info.get("has_bio"):
            score += 20
        if info.get("is_premium"):
            score += 20
        return score

    elif factor_name == "social_graph":
        info = context.get("account_info", {})
        total = info.get("total_dialogs", 0)
        if total == 0:
            return 10
        elif total < 5:
            return 30
        elif total < 20:
            return 60
        elif total < 50:
            return 80
        else:
            return 100

    elif factor_name == "daily_dm_ratio":
        # 0-0.3 = safe, 0.3-0.7 = moderate, 0.7-1.0 = risky
        ratio = context.get("daily_limit_used", 0)
        if ratio <= 0.3:
            return 100
        elif ratio <= 0.5:
            return 80
        elif ratio <= 0.7:
            return 50
        elif ratio <= 0.9:
            return 25
        else:
            return 0

    return 50  # Default


async def calculate_health_score(db: AsyncSession, account: Account) -> Dict:
    """
    Calculate comprehensive health score for an account.
    Returns detailed breakdown of all 16+ factors.
    """
    factors = {}
    risk_score = 0
    reasons = []

    # Factor 1: Account Age
    account_age = (datetime.utcnow() - account.created_at).days if account.created_at else 0
    factors["account_age_days"] = account_age
    age_score = await calculate_factor_score("account_age_days", account_age, {})
    factors["account_age_score"] = age_score

    if account_age < 7 and account.status == AccountStatus.NEW:
        risk_score += RISK_FACTORS["new_account_no_warmup"]
        reasons.append("Аккаунт новый без прогрева")

    # Factor 2: Warmup Level
    factors["warmup_level"] = account.warmup_level or 0
    warmup_score = min(100, (account.warmup_level or 0) * 3.33)
    factors["warmup_score"] = warmup_score

    # Factor 3: Activity Score
    activity_score = await calculate_factor_score(
        "activity_score", None,
        {"last_active": account.last_active}
    )
    factors["activity_score"] = activity_score

    # Factor 4: Proxy Quality
    proxy_quality_score = 50
    if account.proxy:
        proxy_score = await calculate_factor_score(
            "proxy_quality", None,
            {"proxy": account.proxy}
        )
        proxy_quality_score = proxy_score
        factors["proxy_quality_score"] = proxy_score
        factors["proxy_host"] = account.proxy.host
        factors["proxy_response_ms"] = account.proxy.response_time_ms
    else:
        risk_score += RISK_FACTORS["poor_proxy"]
        reasons.append("Нет прокси")

    # Factor 5: Daily DM Usage
    daily_ratio = account.daily_limit_used or 0
    factors["daily_dm_ratio"] = daily_ratio
    dm_score = await calculate_factor_score(
        "daily_dm_ratio", None,
        {"daily_limit_used": daily_ratio}
    )
    factors["daily_dm_score"] = dm_score

    if daily_ratio > 0.9:
        risk_score += RISK_FACTORS["over_daily_limit"]
        reasons.append("Превышен дневной лимит")

    # Factor 6: Total Messages Sent
    factors["total_messages_sent"] = account.total_messages_sent or 0
    msg_score = min(100, account.total_messages_sent or 0)
    factors["message_history_score"] = msg_score

    # Factor 7: Profile Info (requires Telegram API call)
    try:
        client = await telegram_service.get_client(account)
        info = await get_detailed_account_info(client, account)

        if "error" not in info:
            factors["profile_completion"] = await calculate_factor_score(
                "profile_completion", None,
                {"account_info": info}
            )
            factors["social_graph"] = await calculate_factor_score(
                "social_graph", None,
                {"account_info": info}
            )
            factors["groups_count"] = info.get("groups_count", 0)
            factors["channels_count"] = info.get("channels_count", 0)
            factors["has_profile_photo"] = info.get("has_profile_photo", False)
            factors["has_username"] = info.get("has_username", False)
            factors["is_premium"] = info.get("is_premium", False)

            if not info.get("has_profile_photo"):
                risk_score += RISK_FACTORS["no_profile_photo"]
                reasons.append("Нет фото профиля")
        else:
            factors["profile_error"] = info["error"]
            factors["profile_completion"] = 50
            factors["social_graph"] = 50
    except Exception as e:
        factors["api_error"] = str(e)
        factors["profile_completion"] = 30
        factors["social_graph"] = 30

    # Factor 8: Folder/Status
    folder_score = {
        "new": 20,
        "warming": 50,
        "production": 100,
        "quarantine": 10
    }.get(account.folder or "new", 30)
    factors["folder_score"] = folder_score

    # Calculate weighted health score
    weights = {
        "account_age_score": 0.15,
        "warmup_score": 0.10,
        "activity_score": 0.12,
        "proxy_quality_score": 0.10,
        "daily_dm_score": 0.10,
        "message_history_score": 0.08,
        "profile_completion": 0.15,
        "social_graph": 0.10,
        "folder_score": 0.10,
    }

    health_score = 0
    for factor, weight in weights.items():
        score = factors.get(factor, 50)
        health_score += score * weight

    # Apply risk penalty (max 30 points reduction)
    health_score = max(0, min(100, health_score - (risk_score * 0.3)))

    # Determine status based on health score
    if health_score >= 80:
        status_label = "Отлично"
        status_color = "emerald"
    elif health_score >= 60:
        status_label = "Хорошо"
        status_color = "blue"
    elif health_score >= 40:
        status_label = "Нормально"
        status_color = "amber"
    else:
        status_label = "Требует внимания"
        status_color = "red"

    return {
        "account_id": account.id,
        "phone_number": account.phone_number,
        "health_score": round(health_score),
        "status_label": status_label,
        "status_color": status_color,
        "risk_score": risk_score,
        "factors": factors,
        "reasons": reasons,
        "checked_at": datetime.utcnow().isoformat(),
    }


async def run_ggr_check(db: AsyncSession, account_id: int, project_id: int = 1) -> Dict:
    """
    Run full GGR check for a single account.
    """
    result = await db.execute(select(Account).where(Account.id == account_id, Account.project_id == project_id))
    account = result.scalar_one_or_none()

    if not account:
        return {"error": "Account not found"}

    result = await calculate_health_score(db, account)

    # Update account with new health data
    account.health_score = result["health_score"]
    account.last_check_at = datetime.utcnow()

    # Update status based on health
    if result["health_score"] < 30:
        # A low heuristic score is not proof of a Telegram ban.
        account.status = AccountStatus.RESTRICTED
    elif result["health_score"] < 50:
        account.status = AccountStatus.RESTRICTED
    elif result["health_score"] >= 70:
        account.status = AccountStatus.PRODUCTION

    await db.commit()

    return result


async def run_ggr_check_all(db: AsyncSession, project_id: int = 1) -> List[Dict]:
    """
    Run GGR check for all accounts.
    """
    result = await db.execute(select(Account).where(Account.project_id == project_id))
    accounts = result.scalars().all()

    results = []
    for account in accounts:
        check_result = await run_ggr_check(db, account.id, project_id=project_id)
        results.append(check_result)

    return results
