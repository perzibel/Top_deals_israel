import json
import asyncio
from pathlib import Path


class SeedUrlsClient:
    def __init__(self, aliexpress_client, path: str = "data/products_seed.json"):
        self.aliexpress_client = aliexpress_client
        self.path = Path(path)
        self._cached_products = None

    async def search_products(
            self,
            keyword: str,
            limit: int | None = None,
            page_no: int = 1,
            sort: str = "LAST_VOLUME_DESC",
    ):
        """
        For seed URL mode, keyword/page/sort are ignored.
        We load each product URL once per process run to avoid hitting API limits.
        """
        if self._cached_products is not None:
            return self._cached_products

        if not self.path.exists():
            self._cached_products = []
            return self._cached_products

        with self.path.open("r", encoding="utf-8") as f:
            rows = json.load(f)

        products = []
        seen_urls = set()

        for row in rows:
            product_url = row.get("product_url")
            if not product_url:
                continue

            if product_url in seen_urls:
                continue

            seen_urls.add(product_url)

            try:
                product = await self.aliexpress_client.get_product_detail(product_url)
                products.append(product)

                # Small delay to avoid AliExpress API frequency limit
                await asyncio.sleep(1.2)

            except Exception as e:
                print(f"Failed to fetch product from AliExpress: {product_url}")
                print(f"Error: {e}")

        if limit:
            products = products[:limit]

        self._cached_products = products
        return self._cached_products