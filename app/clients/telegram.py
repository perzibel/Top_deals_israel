import json
import logging

import httpx

from app.utils import get_product_value

log = logging.getLogger(__name__)

# Telegram limits: photo captions 1024 chars, text messages 4096.
CAPTION_LIMIT = 1024
MESSAGE_LIMIT = 4096


class TelegramClient:
    def __init__(self, settings):
        self.settings = settings
        self.base_url = f"https://api.telegram.org/bot{settings.telegram_bot_token}"

    async def send_product(self, product, message: str) -> None:
        deal_url = (
                get_product_value(product, "affiliate_url")
                or get_product_value(product, "product_url")
        )

        image_url = get_product_value(product, "image_url")

        if self.settings.dry_run:
            log.info("[DRY RUN] Would post to %s:\n%s\n%s", self.settings.telegram_channel_id, message, deal_url)
            return

        reply_markup = {
            "inline_keyboard": [
                [
                    {
                        "text": "🛒 לצפייה בדיל",
                        "url": deal_url,
                    }
                ]
            ]
        }

        async with httpx.AsyncClient(timeout=30) as client:
            if image_url and len(message) <= CAPTION_LIMIT:
                photo_response = await client.post(
                    f"{self.base_url}/sendPhoto",
                    data={
                        "chat_id": self.settings.telegram_channel_id,
                        "photo": image_url,
                        "caption": message,
                        "parse_mode": "HTML",
                        "reply_markup": json.dumps(reply_markup),
                    },
                )

                if photo_response.status_code == 200:
                    return

                log.warning(
                    "sendPhoto failed (%s): %s. Falling back to text message.",
                    photo_response.status_code,
                    photo_response.text[:500],
                )

            text_response = await client.post(
                f"{self.base_url}/sendMessage",
                data={
                    "chat_id": self.settings.telegram_channel_id,
                    "text": message[:MESSAGE_LIMIT],
                    "parse_mode": "HTML",
                    "reply_markup": json.dumps(reply_markup),
                    "disable_web_page_preview": False,
                },
            )

        if text_response.status_code != 200:
            raise RuntimeError(
                f"Telegram sendMessage failed: {text_response.status_code} {text_response.text[:500]}"
            )

    async def send_message(self, text: str, chat_id: str | None = None) -> None:
        """
        Send a plain text message to the private chat (TELEGRAM_CHAT_ID) by default.
        Used for social draft previews and alerts.
        """
        chat_id = chat_id or self.settings.telegram_chat_id

        if not self.settings.telegram_bot_token:
            raise RuntimeError("Missing Telegram bot token in settings")

        if not chat_id:
            raise RuntimeError("Missing TELEGRAM_CHAT_ID in settings")

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self.base_url}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text[:MESSAGE_LIMIT],
                    "disable_web_page_preview": False,
                },
            )

        if response.status_code >= 400:
            raise RuntimeError(
                f"Telegram sendMessage failed: {response.status_code} {response.text[:500]}"
            )

    async def send_alert(self, text: str) -> None:
        """Best-effort operational alert to the private chat. Never raises."""
        if not self.settings.telegram_chat_id:
            log.warning("Alert not sent (TELEGRAM_CHAT_ID not set): %s", text)
            return

        try:
            await self.send_message(f"⚠️ Top Deals Israel\n{text}")
        except Exception as e:
            log.error("Failed to send alert: %s", e)
