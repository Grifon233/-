import asyncio
import logging
from collections import OrderedDict
from typing import Optional, Dict
from pyrogram import Client, errors

from app.models.account import Account
from app.models.proxy import Proxy

logger = logging.getLogger(__name__)


class ProxyRequiredError(RuntimeError):
    """Raised by :meth:`TelegramService.get_client` when an account
    has no proxy bound. Callers (warmup, messaging, comment) should
    let this bubble up to the API layer as a 400 response."""


def extract_join_target(link: str) -> str:
    """Turn a stored ``t.me`` link into what ``Client.join_chat()`` needs.

    Pyrogram's own invite-hash regex (``t.me/+xxx``, ``t.me/joinchat/xxx``)
    matches full URLs fine and must be passed through unchanged. But for a
    plain public link (``https://t.me/username``), ``join_chat`` falls
    through to ``resolve_peer``, which only strips ``@``/``+``/whitespace —
    NOT the URL scheme and domain. Passing the raw URL there sends
    Telegram a "username" of ``https://t.me/username``, which is not a
    valid username and always fails with ``USERNAME_INVALID``, even for a
    perfectly live group. So: strip down to the bare username ourselves
    for anything that isn't an invite-hash link.
    """
    if "t.me/+" in link or "t.me/joinchat/" in link:
        return link
    return link.rstrip("/").rsplit("/", 1)[-1].lstrip("@")


class TelegramService:
    def __init__(self, max_clients: int = 20):
        self.clients: OrderedDict[int, Client] = OrderedDict()
        self.client_loops: Dict[int, asyncio.AbstractEventLoop] = {}
        self.locks: Dict[int, asyncio.Lock] = {}
        self.max_clients = max_clients
        self.global_lock = asyncio.Lock()

    def get_proxy_dict(self, proxy: Proxy) -> Optional[dict]:
        if not proxy:
            return None
        
        proxy_dict = {
            "scheme": proxy.scheme,
            "hostname": proxy.host,
            "port": proxy.port,
        }
        if proxy.username:
            proxy_dict["username"] = proxy.username
        if proxy.password:
            proxy_dict["password"] = proxy.password
            
        return proxy_dict

    async def get_client(self, account: Account) -> Client:
        # Imported here to avoid a circular import: account_service
        # imports telegram_service at module load time.
        from app.services.account_service import assert_proxy_bound

        try:
            assert_proxy_bound(account)
            if account.proxy and getattr(account.proxy, "is_active", True) is False:
                raise ProxyRequiredError(
                    f"Proxy for account {account.phone_number} is marked as inactive/dead. "
                    "Failing stop to protect account."
                )
        except Exception as exc:
            raise ProxyRequiredError(str(exc)) from exc

        async with self.global_lock:
            if account.id not in self.locks:
                self.locks[account.id] = asyncio.Lock()
            lock = self.locks[account.id]

        async with lock:
            current_loop = asyncio.get_running_loop()
            if account.id in self.clients:
                client = self.clients[account.id]
                if self.client_loops.get(account.id) is current_loop and client.is_connected:
                    self.clients.move_to_end(account.id)
                    return client
                try:
                    if client.is_connected:
                        await client.disconnect()
                except Exception:
                    pass
                self.clients.pop(account.id, None)
                self.client_loops.pop(account.id, None)

            # Evict oldest if limit exceeded
            if len(self.clients) >= self.max_clients:
                oldest_id = next(iter(self.clients))
                logger.info(f"Evicting client for account {oldest_id} from TelegramService pool due to limit ({self.max_clients})")
                oldest_client = self.clients.pop(oldest_id)
                self.client_loops.pop(oldest_id, None)
                try:
                    if oldest_client.is_connected:
                        await oldest_client.disconnect()
                except Exception as e:
                    logger.warning(f"Error disconnecting evicted client {oldest_id}: {e}")

            proxy_dict = self.get_proxy_dict(account.proxy) if account.proxy else None
            
            client = Client(
                name=f"account_{account.id}",
                api_id=account.api_id,
                api_hash=account.api_hash,
                session_string=account.session_string,
                proxy=proxy_dict,
                in_memory=True
            )
            
            await client.connect()
            self.clients[account.id] = client
            self.client_loops[account.id] = current_loop
            return client

    async def disconnect_client(self, account_id: int):
        async with self.global_lock:
            lock = self.locks.get(account_id)
        if lock:
            async with lock:
                if account_id in self.clients:
                    client = self.clients[account_id]
                    try:
                        if client.is_connected:
                            await client.disconnect()
                    except Exception as e:
                        logger.warning(f"Error disconnecting client {account_id}: {e}")
                    self.clients.pop(account_id, None)
                    self.client_loops.pop(account_id, None)

    async def disconnect_clients(self, account_ids: list[int]) -> None:
        """Disconnect a batch of cached clients, best-effort."""
        for account_id in account_ids:
            await self.disconnect_client(account_id)

    async def send_message(self, account: Account, chat_id: str, text: str, humanize: bool = True):
        client = await self.get_client(account)
        try:
            if humanize:
                try:
                    await client.send_chat_action(chat_id, "typing")
                    await asyncio.sleep(min(len(text) * 0.05, 5))
                except Exception:
                    pass
            
            await client.send_message(chat_id, text)
            return True
        except errors.FloodWait as e:
            logger.warning(f"FloodWait for account {account.id}: {e.value} seconds")
            raise e 
        except Exception as e:
            logger.error(f"Error sending message from account {account.id}: {e}")
            return False

telegram_service = TelegramService()
