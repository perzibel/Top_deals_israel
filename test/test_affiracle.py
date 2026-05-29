import asyncio
from dotenv import load_dotenv

from app.config import Settings
from app.clients.affiracle import AffiracleClient


async def main():
    load_dotenv()

    settings = Settings()
    client = AffiracleClient(settings)

    product_url = (
        "https://he.aliexpress.com/item/1005012161078447.html"
        "?spm=a2g0o.tm1000029706.d2.1.33de474ckkKWM0"
    )

    result = await client.generate_affiliate_link(product_url)

    print("\nAffiliate URL:")
    print(result["affiliate_url"])


if __name__ == "__main__":
    asyncio.run(main())