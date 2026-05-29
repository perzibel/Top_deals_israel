import asyncio
import re
from pathlib import Path
from typing import Optional

from telethon import TelegramClient
from telethon.errors import FloodWaitError

from app.storage.affiliate_cache import (
    get_cached_affiliate_link,
    save_affiliate_link,
)


AFFIRACLE_LINK_RE = re.compile(
    r"https?://(?:www\.)?(?:affiracle\.com/s|track\.affiracle\.com/l)/[A-Za-z0-9_-]+",
    re.IGNORECASE,
)


class AffiracleTelegramClient:
    def __init__(self, settings):
        self.settings = settings

        self.api_id = int(settings.telegram_api_id)
        self.api_hash = settings.telegram_api_hash
        self.session_name = settings.telegram_user_session
        self.bot_username = settings.affiracle_bot_username
        self.timeout_seconds = settings.affiracle_bot_timeout_seconds
        self.cooldown_seconds = settings.affiracle_bot_cooldown_seconds

        Path("sessions").mkdir(exist_ok=True)
        self.session_path = str(Path("sessions") / self.session_name)

    async def generate_affiliate_link(self, product_url: str) -> dict:
        cached = get_cached_affiliate_link(product_url)
        if cached:
            return {
                "affiliate_url": cached,
                "raw": {
                    "source": "cache",
                    "product_url": product_url,
                    "affiliate_url": cached,
                },
            }

        async with TelegramClient(
            self.session_path,
            self.api_id,
            self.api_hash,
        ) as client:
            affiliate_url = await self._ask_affiracle_bot(client, product_url)

        save_affiliate_link(
            product_url=product_url,
            affiliate_url=affiliate_url,
            provider="affiracle_telegram",
        )

        await asyncio.sleep(self.cooldown_seconds)

        return {
            "affiliate_url": affiliate_url,
            "raw": {
                "source": "affiracle_telegram_bot",
                "product_url": product_url,
                "affiliate_url": affiliate_url,
            },
        }

    async def _ask_affiracle_bot(self, client: TelegramClient, product_url: str) -> str:
        try:
            bot_entity = await client.get_entity(self.bot_username)

            before_message_id = 0
            async for msg in client.iter_messages(bot_entity, limit=1):
                before_message_id = msg.id
                break

            await client.send_message(bot_entity, product_url)

            deadline = asyncio.get_event_loop().time() + self.timeout_seconds

            while asyncio.get_event_loop().time() < deadline:
                async for msg in client.iter_messages(bot_entity, limit=10):
                    if msg.id <= before_message_id:
                        continue

                    # Ignore our outgoing AliExpress link
                    if msg.out:
                        continue

                    text = msg.raw_text or ""
                    print("Affiracle bot reply text:")
                    print(text)

                    affiliate_url = self._extract_affiracle_link(text)

                    if affiliate_url:
                        return affiliate_url

                await asyncio.sleep(2)

            raise TimeoutError(
                f"Timed out waiting for @{self.bot_username} affiliate link"
            )

        except FloodWaitError as e:
            raise RuntimeError(
                f"Telegram rate limited this account. Wait {e.seconds} seconds."
            ) from e

    def _extract_affiracle_link(self, text: str) -> Optional[str]:
        match = AFFIRACLE_LINK_RE.search(text or "")
        if not match:
            return None

        return match.group(0).strip()