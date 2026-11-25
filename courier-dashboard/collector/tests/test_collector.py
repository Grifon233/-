import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from python_socks import ProxyType
from telethon.errors import InviteRequestSentError
from telethon.network.connection.connection import Connection
from telethon.tl import types
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import CheckChatInviteRequest, ImportChatInviteRequest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main as collector


ACCOUNT = {"name": "courier", "session": "sessions/courier", "api_id": 12345, "api_hash": "a" * 32,
           "proxy": {"type": "socks5", "host": "example.test", "port": "1080"}}
SOURCE = {"assigned_account": "courier", "city": "Москва", "invite": "@publicsource"}
NOW = datetime(2026, 11, 25, 10, 0, tzinfo=timezone.utc)


def channel(*, left=None, noforwards=None):
    return types.Channel(1234567890, "Test source", types.ChatPhotoEmpty(), NOW, left=left,
                         noforwards=noforwards, access_hash=2345, username="publicsource")


class ConfigTests(unittest.TestCase):
    def test_declared_proxy_dependency_is_compatible_with_telethon(self):
        proxy = collector._build_proxy(ACCOUNT["proxy"])
        self.assertEqual(Connection._parse_proxy(**proxy),
                         (ProxyType.SOCKS5, "example.test", 1080, None, None, True))

    def test_proxy_validation_does_not_fall_back_to_connecting_directly(self):
        for data in (None, {**ACCOUNT["proxy"], "type": "typo"}, {**ACCOUNT["proxy"], "port": 0},
                     {**ACCOUNT["proxy"], "username": "user", "password": ""}):
            with self.subTest(data=data), self.assertRaises(collector.CollectorError):
                collector._build_proxy(data)

    def _configs(self, path, accounts, sources):
        accounts_file = Path(path) / "accounts.yml"
        sources_file = Path(path) / "sources.yml"
        accounts_file.write_text(yaml.safe_dump({"accounts": accounts}), encoding="utf-8")
        sources_file.write_text(yaml.safe_dump({"sources": sources}), encoding="utf-8")
        return collector._load_configs(accounts_file, sources_file)

    def test_config_resolves_sessions_and_preserves_invite_hash_case(self):
        with TemporaryDirectory() as directory:
            accounts, sources = self._configs(directory, [ACCOUNT], [{**SOURCE, "invite": "https://t.me/+AbC-deF"}])
            self.assertEqual(accounts["courier"]["session"], Path(directory).resolve() / "sessions/courier.session")
            self.assertEqual(sources["courier"], [(1, "AbC-deF", True, "Москва")])

    def test_config_rejects_shared_sessions_duplicates_and_unassigned_sources(self):
        with TemporaryDirectory() as directory:
            with self.assertRaisesRegex(collector.CollectorError, r"accounts\[2\]"):
                self._configs(directory, [ACCOUNT, {**ACCOUNT, "name": "other", "session": "sessions/courier.session"}], [SOURCE])
            with self.assertRaisesRegex(collector.CollectorError, r"sources\[1\]"):
                self._configs(directory, [ACCOUNT], [{**SOURCE, "assigned_account": "none"}])
            with self.assertRaisesRegex(collector.CollectorError, r"sources\[2\]"):
                self._configs(directory, [ACCOUNT], [SOURCE, {**SOURCE, "invite": "https://t.me/PublicSource"}])

    def test_errors_do_not_expose_malformed_config_contents(self):
        with TemporaryDirectory() as directory:
            filename = Path(directory) / "accounts.yml"
            filename.write_text("accounts: [secret-content", encoding="utf-8")
            with self.assertRaisesRegex(collector.CollectorError, "неверный YAML") as error:
                collector._load_yaml(filename, "accounts")
        self.assertNotIn("secret-content", str(error.exception))

    def test_backend_settings_require_key_except_explicit_local_demo(self):
        with patch.dict(os.environ, {"INGEST_ALLOW_UNAUTHENTICATED": "1"}, clear=True):
            self.assertEqual(collector._load_settings().backend_url, "http://127.0.0.1:8000")
            self.assertIsNone(collector._load_settings().dead_letter_file)
        for env in ({}, {"INGEST_ALLOW_UNAUTHENTICATED": "1", "BACKEND_URL": "https://example.test"},
                    {"INGEST_API_KEY": "not ascii секрет"}):
            with self.subTest(env=env), patch.dict(os.environ, env, clear=True), self.assertRaises(collector.CollectorError):
                collector._load_settings()
        for url in ("ftp://example.test", "https://user:password@example.test", "https://example.test?", "https://example.test:99999"):
            with self.subTest(url=url), patch.dict(os.environ, {"BACKEND_URL": url, "INGEST_API_KEY": "key"}, clear=True):
                with self.assertRaisesRegex(collector.CollectorError, "BACKEND_URL"):
                    collector._load_settings()
        with patch.dict(os.environ, {"BACKEND_URL": "http://example.test", "INGEST_API_KEY": "key"}, clear=True):
            with self.assertRaisesRegex(collector.CollectorError, "требуется HTTPS"):
                collector._load_settings()
        with patch.dict(os.environ, {"BACKEND_URL": "https://example.test/backend/", "INGEST_API_KEY": "key"}, clear=True):
            self.assertEqual(collector._load_settings().backend_url, "https://example.test/backend")


class EventTests(unittest.TestCase):
    def event(self, **kwargs):
        return SimpleNamespace(**{"chat_id": -1001234567890, "id": 123, "chat": None,
                                    "message": SimpleNamespace(date=NOW), "raw_text": "  Пушкина, проверка  ", **kwargs})

    def test_public_and_private_links_do_not_contain_invites(self):
        data = collector._event_payload(self.event(), "Москва", "publicsource")
        self.assertEqual(data["message_link"], "https://t.me/publicsource/123")
        self.assertEqual(data["ts"], "2026-11-25T10:00:00+00:00")
        self.assertEqual(data["text"], "Пушкина, проверка")
        private = collector._event_payload(self.event(chat=SimpleNamespace(username=None)), "Москва", "oldpublicsource")
        self.assertEqual(private["message_link"], "chat:-1001234567890/123")

    def test_blank_protected_and_invalid_events_are_not_forwarded(self):
        for event in (self.event(raw_text="   "), self.event(id=0), self.event(raw_text="t" * 10001),
                      self.event(message=SimpleNamespace(date=NOW.replace(tzinfo=None))),
                      self.event(message=SimpleNamespace(date=NOW, noforwards=True)),
                      self.event(chat=SimpleNamespace(username="publicsource", noforwards=True))):
            self.assertIsNone(collector._event_payload(event, "Москва", None))


class CollectorAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_private_member_does_not_rejoin(self):
        entity = channel()
        client = AsyncMock(return_value=types.ChatInviteAlready(entity))
        self.assertIs(await collector._join(client, "privateHash", True), entity)
        self.assertEqual(client.await_count, 1)
        self.assertIsInstance(client.await_args.args[0], CheckChatInviteRequest)

    async def test_private_join_confirms_membership_and_does_not_treat_pending_as_success(self):
        entity = channel()
        client = AsyncMock(side_effect=[object(), object(), types.ChatInviteAlready(entity)])
        self.assertIs(await collector._join(client, "privateHash", True), entity)
        self.assertEqual([type(call.args[0]) for call in client.await_args_list],
                         [CheckChatInviteRequest, ImportChatInviteRequest, CheckChatInviteRequest])
        pending = AsyncMock(side_effect=[object(), InviteRequestSentError(request=None)])
        with self.assertRaises(InviteRequestSentError):
            await collector._join(pending, "privateHash", True)

    async def test_public_channel_joins_only_if_not_member(self):
        client = AsyncMock()
        client.get_entity = AsyncMock(side_effect=[channel(), channel(left=True), object()])
        await collector._join(client, "publicsource", False)
        client.assert_not_awaited()
        await collector._join(client, "publicsource", False)
        self.assertIsInstance(client.await_args.args[0], JoinChannelRequest)
        with self.assertRaises(collector.CollectorError):
            await collector._join(client, "a_user", False)

    async def test_retry_temporary_failures_respect_retry_after_and_validate_response(self):
        attempts = []

        def handler(request):
            attempts.append(request)
            if len(attempts) == 1:
                return httpx.Response(429, headers={"Retry-After": "5"})
            if len(attempts) == 2:
                raise httpx.ConnectError("internal debug text", request=request)
            return httpx.Response(200, json={"accepted": False, "reason": "not_a_sighting"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), headers={"X-API-Key": "key"}) as http:
            with patch.object(collector.asyncio, "sleep", new_callable=AsyncMock) as wait:
                self.assertIsNone(await collector._post_ingest(http, "https://example.test/ingest", {"x": 1}))
        self.assertEqual([call.args[0] for call in wait.await_args_list], [5, 2])
        self.assertTrue(all(r.headers["X-API-Key"] == "key" for r in attempts))
        self.assertEqual(json.loads(attempts[0].content), {"x": 1})

    async def test_do_not_retry_permanent_errors_html_success_or_a_long_rate_limit(self):
        for response, label in ((httpx.Response(401), "HTTP 401"), (httpx.Response(422), "HTTP 422"),
                                (httpx.Response(200, text="<html>"), "не JSON"),
                                (httpx.Response(200, json={"accepted": "true"}), "нет поля accepted"),
                                (httpx.Response(429, headers={"Retry-After": "120"}), "HTTP 429"),
                                (httpx.Response(429, headers={"Retry-After": "9" * 20}), "HTTP 429")):
            with self.subTest(expected=label):
                requests = []

                def handler(request):
                    requests.append(request)
                    return response

                async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
                    self.assertIn(label, await collector._post_ingest(http, "https://example.test/ingest", {}))
                self.assertEqual(len(requests), 1)

    async def test_delivery_queue_is_bounded_and_failed_message_spool_is_explicit(self):
        with TemporaryDirectory() as directory:
            spool = Path(directory) / "failures.jsonl"
            http = AsyncMock()
            delivery = collector.Delivery(http, collector.Config("https://example.test", "key", False, spool))
            first = {"source_chat": "-1", "message_id": 1, "text": "первый"}
            second = {"source_chat": "-1", "message_id": 2, "text": "второй"}
            delivery.queue = asyncio.Queue(maxsize=1)
            delivery.submit(first)
            with self.assertLogs(collector.logger, "ERROR") as logs:
                delivery.submit(second)
            self.assertIn("переполнена", logs.output[0])
            self.assertNotIn(second["text"], logs.output[0])
            self.assertEqual(json.loads(spool.read_text(encoding="utf-8")), second)
            with patch.object(collector, "_post_ingest", new_callable=AsyncMock, return_value=None) as post:
                worker = asyncio.create_task(delivery.worker())
                await delivery.close([worker])
            post.assert_awaited_once_with(http, "https://example.test/ingest", first)

    async def test_one_bad_or_protected_source_does_not_disconnect_good_source(self):
        with TemporaryDirectory() as directory:
            client = AsyncMock()
            handle = None

            def register(_event):
                def decorator(function):
                    nonlocal handle
                    handle = function
                    return function
                return decorator

            client.on = register
            client.is_user_authorized.return_value = True
            test_event = EventTests().event()

            async def listen():
                await handle(test_event)

            client.run_until_disconnected.side_effect = listen
            account = {**ACCOUNT, "session": Path(directory) / "sessions/test.session"}
            config = collector.Config("https://example.test", "key", False, None)
            delivery = SimpleNamespace(submit=unittest.mock.Mock())
            sources = [(1, "bad", False, "Москва"), (2, "protected", False, "Москва"),
                       (3, "good", False, "Казань")]
            with patch.object(collector, "TelegramClient", return_value=client), \
                 patch.object(collector.asyncio, "sleep", new_callable=AsyncMock), \
                 patch.object(collector, "_join", new_callable=AsyncMock,
                              side_effect=[ValueError("private data"), channel(noforwards=True), channel()]), \
                 self.assertLogs(collector.logger, "WARNING") as logs:
                await collector._run_account("courier", account, sources, config, delivery, asyncio.Lock())

            client.disconnect.assert_awaited_once()
            self.assertTrue(account["session"].parent.is_dir())
            delivery.submit.assert_called_once()
            self.assertEqual(delivery.submit.call_args.args[0]["city"], "Казань")
            self.assertNotIn("private data", "\n".join(logs.output))

    async def test_unauthorized_session_is_not_prompted_and_is_closed(self):
        with TemporaryDirectory() as directory:
            client = AsyncMock()
            client.on = lambda _: lambda handler: handler
            client.is_user_authorized.return_value = False
            account = {**ACCOUNT, "session": Path(directory) / "test.session"}
            config = collector.Config("https://example.test", "key", False, None)
            with patch.object(collector, "TelegramClient", return_value=client):
                with self.assertRaisesRegex(collector.CollectorError, "ALLOW_INTERACTIVE_LOGIN=1"):
                    await collector._run_account("courier", account, [], config, None, asyncio.Lock())
            client.start.assert_not_called()
            client.run_until_disconnected.assert_not_called()
            client.disconnect.assert_awaited_once()

    async def test_service_fails_instead_of_exiting_successfully_when_no_account_survives(self):
        config = collector.Config("https://example.test", "key", False, None)
        with patch.object(collector, "_run_account", side_effect=RuntimeError("secret-text")), \
             self.assertLogs(collector.logger, "ERROR") as logs:
            with self.assertRaisesRegex(collector.CollectorError, "ни один аккаунт"):
                await collector._run({"courier": ACCOUNT}, {"courier": []}, config)
        self.assertNotIn("secret-text", "\n".join(logs.output))
