import asyncio
from dotenv import load_dotenv

from app.config import Settings
from app.clients.affiracle_telegram import AffiracleTelegramClient


async def main():
    load_dotenv()

    settings = Settings()
    client = AffiracleTelegramClient(settings)

    product_url = input("AliExpress product URL: ").strip()

    result = await client.generate_affiliate_link(product_url)

    print("\nAffiliate URL:")
    print(result["affiliate_url"])
    print("\nRaw:")
    print(result["raw"])


if __name__ == "__main__":
    asyncio.run(main())