import asyncio
import json
import logging
import random
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import aiohttp
import pytz

from bot.config import ATHLETES, CLOUDFLARE_ACCOUNT_ID, LLM_KEYS

logger = logging.getLogger(__name__)


class LLMService:
    def __init__(self):
        self.providers = ["cloudflare", "openrouter", "mistral", "cohere", "aihubmix"]
        self.request_timeout = aiohttp.ClientTimeout(total=6, connect=2, sock_read=4)
        self.max_parallel_requests = 3
        self.max_total_attempts = 6
        self.cooldown_seconds = 120
        self.provider_cooldowns: dict[tuple[str, str], datetime] = {}
        self.provider_failures: dict[tuple[str, str], int] = defaultdict(int)

    def _provider_enabled(self, provider: str) -> bool:
        if provider == "cloudflare":
            return bool(CLOUDFLARE_ACCOUNT_ID and LLM_KEYS.get(provider))
        return bool(LLM_KEYS.get(provider))

    def _get_system_prompt(self, today: str) -> str:
        athletes_list = ", ".join([f"{data['name']} ({data['full_name']})" for data in ATHLETES.values()])
        return (
            f"Ты — эксперт-координатор тренировок. Сегодня {today}.\n"
            f"Список спортсменов: {athletes_list}.\n"
            "Твоя задача: извлечь расписание из текста тренера.\n"
            "ПРАВИЛА ДАТ:\n"
            "1. 'Завтра' — это следующий день от сегодня.\n"
            "2. Если указан день недели и это тот же день, что и 'завтра', используй одну дату.\n"
            "3. Если есть интервал дат, бери ближайшую разумную дату.\n"
            "ПРАВИЛА ВРЕМЕНИ:\n"
            "1. 'без двадцати пять' -> 16:40, 'пол шестого' -> 17:30.\n"
            "2. 'после двух' -> 14:00, 'после обеда' -> 14:00.\n"
            "3. Если указан интервал (14-22), бери только время начала (14:00).\n"
            "ФОРМАТ ОТВЕТА:\n"
            "Отвечай ТОЛЬКО JSON-списком: [{\"name\": \"Фамилия\", \"date\": \"DD.MM\", \"time\": \"HH:MM\"}].\n"
            "Используй только фамилии из списка и не добавляй пояснений."
        )

    def _build_candidates(self) -> list[tuple[str, str]]:
        now = datetime.now()
        candidates: list[tuple[str, str]] = []

        for provider in self.providers:
            if not self._provider_enabled(provider):
                continue

            keys = list(LLM_KEYS.get(provider, []))
            random.shuffle(keys)

            for key in keys:
                cooldown_until = self.provider_cooldowns.get((provider, key))
                if cooldown_until and cooldown_until > now:
                    continue
                candidates.append((provider, key))

        random.shuffle(candidates)
        return candidates[: self.max_total_attempts]

    def _mark_success(self, provider: str, key: str) -> None:
        self.provider_failures[(provider, key)] = 0
        self.provider_cooldowns.pop((provider, key), None)

    def _mark_failure(self, provider: str, key: str, cooldown: bool = False) -> None:
        state_key = (provider, key)
        self.provider_failures[state_key] += 1
        failures = self.provider_failures[state_key]
        if cooldown or failures >= 2:
            self.provider_cooldowns[state_key] = datetime.now() + timedelta(seconds=self.cooldown_seconds)

    def _normalize_response_json(self, response: str) -> Optional[List[Dict[str, Any]]]:
        clean_json = response.strip()
        if "```json" in clean_json:
            clean_json = clean_json.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in clean_json:
            clean_json = clean_json.split("```", 1)[1].split("```", 1)[0].strip()

        data = json.loads(clean_json)
        if not isinstance(data, list):
            return None

        normalized: list[Dict[str, Any]] = []
        for item in data:
            if not isinstance(item, dict):
                return None

            name = str(item.get("name", "")).strip()
            date = str(item.get("date", "")).strip()
            time = str(item.get("time", "")).strip()
            if not name or not date or not time:
                return None

            telegram_id = None
            for tid, athlete in ATHLETES.items():
                if athlete["name"].lower() == name.lower():
                    telegram_id = tid
                    name = athlete["name"]
                    break

            if telegram_id is None:
                return None

            normalized.append({
                "name": name,
                "date": date,
                "time": time,
                "telegram_id": telegram_id,
            })

        return normalized or None

    async def _perform_request(
        self,
        session: aiohttp.ClientSession,
        provider: str,
        key: str,
        prompt: str,
        system: str,
    ) -> Optional[str]:
        if provider == "cloudflare":
            url = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/run/@cf/meta/llama-3-8b-instruct"
            headers = {"Authorization": f"Bearer {key}"}
            data = {"messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
        elif provider == "openrouter":
            url = "https://openrouter.ai/api/v1/chat/completions"
            headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            data = {
                "model": "meta-llama/llama-3-8b-instruct:free",
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            }
        elif provider == "mistral":
            url = "https://api.mistral.ai/v1/chat/completions"
            headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            data = {
                "model": "mistral-small-latest",
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            }
        elif provider == "cohere":
            url = "https://api.cohere.com/v2/chat"
            headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            data = {
                "model": "command-r-plus",
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            }
        elif provider == "aihubmix":
            url = "https://aihubmix.com/v1/chat/completions"
            headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            data = {
                "model": "gpt-3.5-turbo",
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            }
        else:
            return None

        try:
            async with session.post(url, headers=headers, json=data) as resp:
                if resp.status == 429:
                    self._mark_failure(provider, key, cooldown=True)
                    logger.warning("LLM provider rate-limited: %s", provider)
                    return None
                if resp.status in {401, 403}:
                    self._mark_failure(provider, key, cooldown=True)
                    logger.warning("LLM provider auth failed: %s", provider)
                    return None
                if resp.status >= 500:
                    self._mark_failure(provider, key)
                    logger.warning("LLM provider server error %s: %s", provider, resp.status)
                    return None
                if resp.status != 200:
                    self._mark_failure(provider, key)
                    body = await resp.text()
                    logger.warning("LLM provider bad status %s: %s %s", provider, resp.status, body[:200])
                    return None

                result = await resp.json()
                self._mark_success(provider, key)

                if provider == "cloudflare":
                    return result.get("result", {}).get("response")
                if provider in {"openrouter", "mistral", "aihubmix"}:
                    return result["choices"][0]["message"]["content"]
                if provider == "cohere":
                    return result["message"]["content"][0]["text"]
        except asyncio.TimeoutError:
            self._mark_failure(provider, key)
            logger.warning("LLM provider timeout: %s", provider)
        except Exception as e:
            self._mark_failure(provider, key)
            logger.error("LLM provider error %s: %s", provider, e)
        return None

    async def _request_and_parse(
        self,
        session: aiohttp.ClientSession,
        provider: str,
        key: str,
        prompt: str,
        system: str,
    ) -> Optional[List[Dict[str, Any]]]:
        response = await self._perform_request(session, provider, key, prompt, system)
        if not response:
            return None
        try:
            return self._normalize_response_json(response)
        except Exception as e:
            self._mark_failure(provider, key)
            logger.warning("LLM JSON parse error for %s: %s", provider, e)
            return None

    async def parse_schedule(self, text: str) -> Optional[List[Dict[str, Any]]]:
        today_str = datetime.now(pytz.timezone("Asia/Yekaterinburg")).strftime("%d.%m.%Y (%A)")
        system_prompt = self._get_system_prompt(today_str)
        candidates = self._build_candidates()

        if not candidates:
            logger.info("LLM routing skipped: no enabled providers")
            return None

        connector = aiohttp.TCPConnector(limit=self.max_parallel_requests, ttl_dns_cache=300)
        async with aiohttp.ClientSession(timeout=self.request_timeout, connector=connector) as session:
            pending: set[asyncio.Task] = set()
            candidate_iter = iter(candidates)

            def schedule_next() -> None:
                while len(pending) < self.max_parallel_requests:
                    try:
                        provider, key = next(candidate_iter)
                    except StopIteration:
                        return
                    task = asyncio.create_task(
                        self._request_and_parse(session, provider, key, text, system_prompt)
                    )
                    pending.add(task)

            schedule_next()

            while pending:
                done, pending = await asyncio.wait(
                    pending,
                    return_when=asyncio.FIRST_COMPLETED,
                )

                for task in done:
                    try:
                        parsed = await task
                    except Exception as e:
                        logger.error("Unexpected LLM task error: %s", e, exc_info=True)
                        parsed = None
                    if parsed:
                        for pending_task in pending:
                            pending_task.cancel()
                        if pending:
                            await asyncio.gather(*pending, return_exceptions=True)
                        return parsed

                schedule_next()

        return None


llm_service = LLMService()
