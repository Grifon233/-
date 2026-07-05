"""SMSFAST (https://smsfast.cc) virtual-number client.

A thin async wrapper around the SMS-Activate-compatible
``handler_api.php`` protocol that smsfast.cc exposes at
``https://smsfastapi.com/stubs/handler_api.php``. Every call is a
plain GET with an ``api_key`` and an ``action`` query parameter.

We use it to **auto-register fresh Telegram accounts**: order a
number in the same country as the account's proxy, let Telegram send
the login code to it, then poll for the code and finish the sign-in.

Protocol summary (all GET, response is plain text unless noted)
---------------------------------------------------------------
* ``getBalance``                 → ``ACCESS_BALANCE:540``
* ``getNumber&service&country``  → ``ACCESS_NUMBER:<id>:<phone>``
* ``getStatus&id``               → ``STATUS_WAIT_CODE`` /
                                   ``STATUS_OK:<code>`` / ``STATUS_CANCEL``
* ``setStatus&id&status``        → status 3 = ask for another SMS,
                                   6 = finish (success), 8 = cancel+refund
* ``getPrices&service&country``  → JSON
* ``getNumbersStatus&country``   → JSON

Error responses (any action): ``BAD_KEY``, ``ERROR_SQL``,
``BAD_ACTION``, ``NO_NUMBERS``, ``NO_BALANCE``, ``BAD_SERVICE``,
``NO_ACTIVATION``.

The Telegram service code is ``tg``.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# Telegram service short-code in the smsfast catalog.
TELEGRAM_SERVICE = "tg"

# Human-readable explanations for the protocol's error tokens so the
# operator sees a clear message instead of a cryptic code.
ERROR_MESSAGES: dict[str, str] = {
    "BAD_KEY": "Неверный API-ключ SMSFAST. Проверьте SMSFAST_API_TOKEN в .env.",
    "ERROR_SQL": "Ошибка на стороне SMSFAST (SQL). Попробуйте позже.",
    "BAD_ACTION": "Неправильный запрос к SMSFAST (внутренняя ошибка).",
    "NO_NUMBERS": "Нет доступных номеров для этой страны/сервиса. Попробуйте другую страну или позже.",
    "NO_BALANCE": "На балансе SMSFAST закончились деньги. Пополните счёт.",
    "BAD_SERVICE": "Неверный идентификатор сервиса.",
    "NO_ACTIVATION": "Активация с таким ID не найдена (возможно, уже завершена или отменена).",
    "EARLY_CANCEL_DENIED": "Провайдер пока не разрешает отменить номер. Повторим отмену позже.",
    "BAD_STATUS": "SMSFAST отклонил изменение статуса активации.",
}

# setStatus codes (per smsfast docs).
STATUS_RETRY_SMS = 3   # request another SMS for the same number
STATUS_COMPLETE = 6    # mark activation successful (keeps the number bound)
STATUS_CANCEL = 8      # cancel the activation and refund the money


class SmsFastError(RuntimeError):
    """Raised when smsfast returns an error token or an unexpected reply.

    ``code`` holds the raw protocol token (e.g. ``NO_NUMBERS``) when the
    failure is a recognised error response, else ``None``.
    """

    def __init__(self, message: str, code: Optional[str] = None) -> None:
        super().__init__(message)
        self.code = code


class NoNumbersError(SmsFastError):
    """No numbers available for the requested country/service."""


class NoBalanceError(SmsFastError):
    """The smsfast account ran out of money."""


class SmsFastService:
    """Async client for the smsfast handler_api.

    Stateless across calls; a single shared :class:`httpx.AsyncClient`
    is created lazily and reused. Calls go out over the *server's* own
    network — NOT through any Telegram proxy (this is a normal REST
    API, unrelated to the account's MTProto connection).
    """

    def __init__(self, token: Optional[str] = None, base_url: Optional[str] = None) -> None:
        self._token = token or settings.SMSFAST_API_TOKEN
        self._base_url = base_url or settings.SMSFAST_API_BASE
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def is_configured(self) -> bool:
        return bool(self._token)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=10.0),
                headers={"User-Agent": "tg-comb/1.0 (smsfast-client)"},
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _request(self, action: str, **params: Any) -> str:
        """Perform one GET call and return the raw, stripped response text.

        Raises :class:`SmsFastError` (or a subclass) when the response is
        a recognised error token.
        """
        if not self._token:
            raise SmsFastError(
                "SMSFAST_API_TOKEN не настроен. Добавьте его в backend/.env."
            )
        query = {"api_key": self._token, "action": action, **{
            k: v for k, v in params.items() if v is not None
        }}
        client = await self._get_client()
        try:
            resp = await client.get(self._base_url, params=query)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise SmsFastError(f"Сетевая ошибка при обращении к SMSFAST: {exc}") from exc

        text = (resp.text or "").strip()
        logger.debug("smsfast %s → %s", action, text)

        # Recognised error tokens come back as a bare word.
        token = text.split(":", 1)[0]
        if token in ERROR_MESSAGES:
            msg = ERROR_MESSAGES[token]
            if token == "NO_NUMBERS":
                raise NoNumbersError(msg, code=token)
            if token == "NO_BALANCE":
                raise NoBalanceError(msg, code=token)
            raise SmsFastError(msg, code=token)
        return text

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def get_balance(self) -> float:
        """Return the account balance as a float (currency per account settings)."""
        text = await self._request("getBalance")
        # ACCESS_BALANCE:540  or  ACCESS_BALANCE:211.9400
        if text.startswith("ACCESS_BALANCE:"):
            try:
                return float(text.split(":", 1)[1])
            except (ValueError, IndexError):
                pass
        raise SmsFastError(f"Не удалось разобрать баланс SMSFAST: {text!r}")

    async def get_number(
        self, country: int, service: str = TELEGRAM_SERVICE, operator: Optional[str] = None
    ) -> tuple[str, str]:
        """Order a number. Returns ``(activation_id, phone)``.

        ``phone`` is the number WITH the country code but WITHOUT a
        leading ``+`` (e.g. ``79123456789``) — exactly as smsfast
        returns it. The caller is responsible for prepending ``+``
        before handing it to Telegram.

        Raises :class:`NoNumbersError` / :class:`NoBalanceError` on the
        corresponding protocol tokens.
        """
        if operator is not None:
            operators_to_try = [operator]
        else:
            operators_to_try = ["any"]
            operators_to_try.extend(await self._discover_operator_fallbacks(country, service))

        last_no_numbers: Optional[NoNumbersError] = None
        for current_operator in self._dedupe_operators(operators_to_try):
            try:
                text = await self._request(
                    "getNumber",
                    service=service,
                    country=country,
                    operator=current_operator,
                )
            except NoNumbersError as exc:
                last_no_numbers = exc
                logger.info(
                    "smsfast getNumber: no numbers for country=%s service=%s operator=%s",
                    country,
                    service,
                    current_operator,
                )
                continue

            # ACCESS_NUMBER:234242:79123456789
            if text.startswith("ACCESS_NUMBER:"):
                parts = text.split(":")
                if len(parts) >= 3:
                    activation_id = parts[1].strip()
                    phone = parts[2].strip()
                    return activation_id, phone
            raise SmsFastError(f"Не удалось разобрать ответ getNumber: {text!r}")

        if last_no_numbers is not None:
            raise last_no_numbers
        raise NoNumbersError(
            "Нет доступных номеров для этой страны/сервиса. Попробуйте другую страну или позже.",
            code="NO_NUMBERS",
        )

    async def _discover_operator_fallbacks(
        self,
        country: int,
        service: str,
    ) -> list[str]:
        """Read available operator buckets from ``getNumbersStatus``.

        Some SMS-Activate-compatible vendors report stock in keys like
        ``tg_0`` / ``tg_3`` yet return ``NO_NUMBERS`` when ``getNumber`` is
        called without an explicit operator. In that case we try ``any``
        first, then the operator suffixes reported as available.
        """
        try:
            counts = await self.get_numbers_count(country, service=service)
        except SmsFastError as exc:
            logger.info(
                "smsfast getNumbersStatus failed while discovering operators for %s/%s: %s",
                country,
                service,
                exc,
            )
            return []

        operators: list[str] = []
        prefix = f"{service}_"
        for key, raw_count in counts.items():
            if not key.startswith(prefix):
                continue
            try:
                count = int(raw_count or 0)
            except (TypeError, ValueError):
                continue
            if count <= 0:
                continue
            suffix = key[len(prefix):].strip()
            if suffix:
                operators.append(suffix)
        return operators

    @staticmethod
    def _dedupe_operators(operators: list[Optional[str]]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for item in operators:
            if item is None:
                continue
            value = str(item).strip()
            if not value or value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result

    async def get_status(self, activation_id: str) -> tuple[str, Optional[str]]:
        """Poll the activation status.

        Returns ``(state, code)`` where ``state`` is one of:
          * ``"wait"``   — still waiting for the SMS (code is None)
          * ``"ok"``     — code received (code is the SMS code string)
          * ``"cancel"`` — the activation was cancelled (code is None)
        """
        text = await self._request("getStatus", id=activation_id)
        if text.startswith("STATUS_OK:"):
            return "ok", text.split(":", 1)[1].strip()
        if text.startswith("STATUS_WAIT"):
            return "wait", None
        if text.startswith("STATUS_CANCEL"):
            return "cancel", None
        # Unknown status — treat as still waiting but log it.
        logger.warning("smsfast getStatus unexpected reply: %r", text)
        return "wait", None

    async def set_status(self, activation_id: str, status: int) -> str:
        """Change the activation state (3=retry SMS, 6=complete, 8=cancel)."""
        return await self._request("setStatus", id=activation_id, status=status)

    async def cancel(self, activation_id: str) -> str:
        """Cancel an activation and require an explicit provider confirmation."""
        response = await self.set_status(activation_id, STATUS_CANCEL)
        if response != "ACCESS_CANCEL":
            raise SmsFastError(
                f"SMSFAST не подтвердил отмену {activation_id}: {response!r}"
            )
        return response

    async def complete(self, activation_id: str) -> None:
        """Mark the activation successful (best-effort)."""
        try:
            await self.set_status(activation_id, STATUS_COMPLETE)
        except SmsFastError as exc:
            logger.info("smsfast complete %s: %s", activation_id, exc)

    async def request_another_sms(self, activation_id: str) -> str:
        """Ask the provider to wait for another SMS on the same number."""
        return await self.set_status(activation_id, STATUS_RETRY_SMS)

    async def get_prices(
        self, country: int, service: Optional[str] = None
    ) -> dict[str, Any]:
        """Return the raw price JSON for a country (optionally one service)."""
        text = await self._request("getPrices", country=country, service=service)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise SmsFastError(f"Не удалось разобрать getPrices: {text[:120]!r}") from exc

    async def get_numbers_count(self, country: int, service: Optional[str] = None) -> dict[str, Any]:
        """Return the available-numbers JSON for a country."""
        text = await self._request("getNumbersStatus", country=country)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SmsFastError(f"Не удалось разобрать getNumbersStatus: {text[:120]!r}") from exc
        if service:
            # Keys look like "tg_0" / "tg_1" (service + operator index).
            return {k: v for k, v in data.items() if k.startswith(f"{service}_")}
        return data


# Shared singleton — mirrors tgstat_service usage.
smsfast_service = SmsFastService()
