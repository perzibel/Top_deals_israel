import json
from pathlib import Path

from app.models import Product


class SeedProductsClient:
    def __init__(self, path: str = "data/products_seed.json"):
        self.path = Path(path)

    async def search_products(self, keyword: str):
        if not self.path.exists():
            return []

        with self.path.open("r", encoding="utf-8") as f:
            raw_products = json.load(f)

        products = []

        for item in raw_products:
            category = (item.get("category") or "").lower()
            title = (item.get("title") or "").lower()
            keyword_lower = keyword.lower()

            # Basic keyword/category match. If no match, still allow all for now.
            if keyword_lower not in title and keyword_lower not in category:
                pass

            products.append(
                Product(
                    product_id=str(item["product_id"]),
                    title=item["title"],
                    product_url=item["product_url"],
                    price_usd=item.get("price_usd"),
                    original_price_usd=item.get("original_price_usd"),
                    currency=item.get("currency", "USD"),
                    rating=item.get("rating"),
                    orders=item.get("orders"),
                    shipping=item.get("shipping"),
                    category=item.get("category"),
                    image_url=item.get("image_url"),
                )
            )

        return products