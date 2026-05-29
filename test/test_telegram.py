import asyncio
import os

import httpx
from dotenv import load_dotenv


async def main():
    load_dotenv()

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHANNEL_ID")

    if not token:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN in .env")

    if not chat_id:
        raise RuntimeError("Missing TELEGRAM_CHANNEL_ID in .env")

    text = "✅ Telegram test from AliExpress Deal Engine"

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            url,
            json={
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": False,
            },
        )

    print("Status:", response.status_code)
    print("Response:", response.text)

    response.raise_for_status()


if __name__ == "__main__":
    asyncio.run(main())