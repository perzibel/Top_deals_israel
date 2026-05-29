import asyncio

from app.clients.aliexpress import AliExpressClient
from app.config import Settings  # adjust if your settings import is different


async def main():
    settings = Settings()
    aliexpress = AliExpressClient(settings)

    hot_products = await aliexpress.get_hot_products(
        keyword="",
        limit=15,
        page_no=1,
        sort="SALE_PRICE_DESC",
    )
    for product in hot_products:
        print("-" * 80)
        print(product.title)
        print(product.price_ils)
        print(product.affiliate_url or product.product_url)


if __name__ == "__main__":
    asyncio.run(main())
