import asyncio
from app.config import Settings
from app.clients.aliexpress import AliExpressClient


async def main():
    settings = Settings()
    client = AliExpressClient(settings)

    products = await client.get_hot_topic_products(limit=5)

    print(f"Got {len(products)} products")

    for product in products:
        print("----")
        print("ID:", getattr(product, "product_id", None))
        print("Title:", getattr(product, "title", None))
        print("Price:", getattr(product, "price_ils", None) or getattr(product, "price_usd", None))
        print("URL:", getattr(product, "product_url", None))


if __name__ == "__main__":
    asyncio.run(main())