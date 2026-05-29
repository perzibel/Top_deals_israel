import json

import httpx


def get_product_value(product, key: str, default=None):
    if isinstance(product, dict):
        return product.get(key, default)

    return getattr(product, key, default)


class TelegramClient:
    def __init__(self, settings):
        self.settings = settings
        self.base_url = f"https://api.telegram.org/bot{settings.telegram_bot_token}"

    async def send_product(self, product, message: str):
        deal_url = (
            get_product_value(product, "affiliate_url")
            or get_product_value(product, "product_url")
        )

        image_url = get_product_value(product, "image_url")

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
            if image_url:
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

                print("Telegram photo status:", photo_response.status_code)
                print("Telegram photo response:", photo_response.text)

                if photo_response.status_code == 200:
                    return

                print("Photo failed. Falling back to text message...")

            text_response = await client.post(
                f"{self.base_url}/sendMessage",
                data={
                    "chat_id": self.settings.telegram_channel_id,
                    "text": message,
                    "parse_mode": "HTML",
                    "reply_markup": json.dumps(reply_markup),
                    "disable_web_page_preview": False,
                },
            )

        print("Telegram text status:", text_response.status_code)
        print("Telegram text response:", text_response.text)
        text_response.raise_for_status()

async def send_message(self, text: str) -> None:
    """
    Send a plain text message to the configured Telegram chat/channel.
    Used for social draft previews.
    """
    import httpx

    bot_token = (
        getattr(self.settings, "telegram_bot_token", None)
        or getattr(self.settings, "TELEGRAM_BOT_TOKEN", None)
        or getattr(self.settings, "telegram_token", None)
    )

    chat_id = (
        getattr(self.settings, "telegram_chat_id", None)
        or getattr(self.settings, "TELEGRAM_CHAT_ID", None)
        or getattr(self.settings, "telegram_approval_chat_id", None)
    )

    if not bot_token:
        raise RuntimeError("Missing Telegram bot token in settings")

    if not chat_id:
        raise RuntimeError("Missing Telegram chat id in settings")

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": False,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(url, json=payload)

    if response.status_code >= 400:
        raise RuntimeError(
            f"Telegram sendMessage failed: {response.status_code} {response.text}"
        )