import asyncio
import hashlib
from datetime import datetime
from typing import Any, Optional
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
import httpx
from app.models import Product


def ali_timestamp() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")


def sign_top_request(params: dict, app_secret: str) -> str:
    """
    TOP-style MD5 signature:
    secret + sorted(key + value) + secret
    """
    sorted_items = sorted(params.items())
    base = app_secret + "".join(f"{k}{v}" for k, v in sorted_items) + app_secret
    return hashlib.md5(base.encode("utf-8")).hexdigest().upper()


def extract_product_id(product_url: str) -> str:
    path = urlparse(product_url).path

    if "/item/" not in path:
        raise ValueError(f"Could not extract product ID from URL: {product_url}")

    return path.split("/item/")[-1].split(".html")[0]


def parse_float(value):
    if value is None:
        return None

    try:
        return float(str(value).replace("%", "").strip())
    except Exception:
        return None


def parse_int(value):
    if value is None:
        return None

    try:
        return int(float(str(value).replace(",", "").strip()))
    except Exception:
        return None


def parse_rating_from_evaluate_rate(value):
    """
    AliExpress returns evaluate_rate like "94.8%".
    Convert it to a 5-star rating:
    94.8% -> 4.74/5
    """
    percentage = parse_float(value)

    if percentage is None:
        return None

    return round(percentage / 20, 2)


def get_nested(data: dict, path: list[str], default=None):
    current = data

    for key in path:
        if not isinstance(current, dict):
            return default

        current = current.get(key)

        if current is None:
            return default

    return current


class AliExpressClient:
    def __init__(self, settings):
        self.settings = settings
        self.endpoint = settings.aliexpress_api_endpoint

    async def _call_api(self, method: str, params: dict, retry_count: int = 0) -> dict:
        base_params = {
            "method": method,
            "app_key": self.settings.aliexpress_app_key,
            "timestamp": ali_timestamp(),
            "format": "json",
            "v": "2.0",
            "sign_method": "md5",
        }

        request_params = {
            **base_params,
            **params,
        }

        request_params["sign"] = sign_top_request(
            request_params,
            self.settings.aliexpress_app_secret,
        )

        async with httpx.AsyncClient(timeout=40) as client:
            response = await client.post(
                self.endpoint,
                data=request_params,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded;charset=utf-8"
                },
            )

        print("AliExpress status:", response.status_code)
        response.raise_for_status()

        data = response.json()

        if "error_response" in data:
            error = data["error_response"]
            code = error.get("code")
            message = error.get("msg", "")

            if code == "ApiCallLimit" and retry_count < 3:
                wait_seconds = 2 + retry_count
                print(
                    f"AliExpress rate limit hit. Waiting {wait_seconds} seconds "
                    f"and retrying... ({message})"
                )
                await asyncio.sleep(wait_seconds)
                return await self._call_api(method, params, retry_count + 1)

            raise RuntimeError(f"AliExpress API error: {error}")

        return data

    async def get_product_detail(self, product_url: str) -> Product:
        product_id = extract_product_id(product_url)

        data = await self._call_api(
            method="aliexpress.affiliate.productdetail.get",
            params={
                "product_ids": product_id,
                "target_currency": "ILS",
                "target_language": "HE",
            },
        )

        return self._parse_product_detail(data)

    async def get_hot_topic_products(
            self,
            topic_id: Optional[str] = None,
            limit: Optional[int] = None,
            page_no: int = 1,
            keywords: Optional[str] = None,
            max_sale_price: Optional[float] = None,
    ) -> list[Product]:
        """
        AliExpress hot topic products discovery.

        Uses:
        aliexpress.affiliate.hot.topic.products.get

        This is good for pulling products from AliExpress trend/topic collections.
        """
        limit = limit or getattr(self.settings, "hot_topics_per_request", 50)

        params = {
            "page_no": page_no,
            "page_size": limit,
            "target_currency": "ILS",
            "target_language": "HE",
            "ship_to_country": "IL",
        }

        if keywords:
            params["keywords"] = keywords

        if max_sale_price:
            params["max_sale_price"] = str(max_sale_price)

        if topic_id:
            params["topic_id"] = str(topic_id)

        data = await self._call_api(
            method="aliexpress.affiliate.hotproduct.query",
            params=params,
        )

        products = self._parse_product_query(data)

        for product in products:
            setattr(product, "source", "hot_topics")
            setattr(product, "source_topic_id", topic_id)

        return products

    def _extract_products_from_affiliate_response(self, data: dict) -> list[dict]:
        """
        Extract product list from different AliExpress affiliate API response shapes.

        Supports:
        - aliexpress.affiliate.product.query
        - aliexpress.affiliate.hotproduct.query
        - aliexpress.affiliate.featuredpromo.products.get
        """
        if not data:
            return []

        possible_response_keys = [
            "aliexpress_affiliate_product_query_response",
            "aliexpress_affiliate_hotproduct_query_response",
            "aliexpress_affiliate_featuredpromo_products_get_response",
        ]

        response_data = None

        for key in possible_response_keys:
            if key in data:
                response_data = data[key]
                break

        if not response_data:
            response_data = data

        # Common AliExpress shape:
        # response -> resp_result -> result -> products -> product
        resp_result = response_data.get("resp_result", response_data)
        result = resp_result.get("result", resp_result)
        products = result.get("products", {})

        if isinstance(products, dict):
            product_list = products.get("product", [])
        elif isinstance(products, list):
            product_list = products
        else:
            product_list = []

        if isinstance(product_list, dict):
            return [product_list]

        return product_list or []

    async def get_featured_promo_products(
            self,
            promotion_name: Optional[str] = None,
            category_id: Optional[str | int] = None,
            limit: Optional[int] = None,
            page_no: int = 1,
            sort: str = "LAST_VOLUME_DESC",
    ) -> list[Product]:
        """
        AliExpress featured promo products discovery.

        Uses:
        aliexpress.affiliate.featuredpromo.products.get

        This pulls products from a specific AliExpress promotion campaign.
        """
        limit = limit or getattr(self.settings, "featured_promo_products_per_request", 50)

        keywords = getattr(
            self.settings,
            "hot_products_keywords",
            "gaming,tech,phone accessories,gadgets,smart home,desk setup",
        )

        max_price = getattr(self.settings, "hot_products_max_price_ils", 250)

        params = {
            "page_no": page_no,
            "page_size": limit,
            "target_currency": "ILS",
            "target_language": "HE",
            "ship_to_country": "IL",

            # AliExpress-side filtering
            "max_sale_price": str(max_price),
            "keywords": keywords,
        }

        if category_id:
            params["category_id"] = str(category_id)

        data = await self._call_api(
            method="aliexpress.affiliate.featuredpromo.products.get",
            params=params,
        )

        return self._parse_product_query(data)

    async def get_hot_products(
            self,
            keyword: Optional[str] = None,
            category_ids: Optional[list[str] | str] = None,
            limit: Optional[int] = None,
            page_no: int = 1,
            sort: str = "LAST_VOLUME_DESC",
    ) -> list[Product]:
        """
        AliExpress hot products discovery.

        Uses:
        aliexpress.affiliate.hotproduct.query

        This is good for pulling trending / high-volume products without relying
        only on keyword search.
        """
        limit = limit or getattr(self.settings, "hot_products_per_request", 50)

        params = {
            "page_no": page_no,
            "page_size": limit,
            "target_currency": "ILS",
            "target_language": "HE",
            "ship_to_country": "IL",
            "platform_product_type": "ALL",
            "max_sale_price": 150,
            "sort": sort,
        }

        if keyword:
            params["keywords"] = keyword

        if category_ids:
            if isinstance(category_ids, list):
                params["category_ids"] = ",".join(str(category_id) for category_id in category_ids)
            else:
                params["category_ids"] = str(category_ids)

        data = await self._call_api(
            method="aliexpress.affiliate.hotproduct.query",
            params=params,
        )

        return self._parse_product_query(data)

    async def search_products(
            self,
            keyword: str,
            limit: Optional[int] = None,
            page_no: int = 1,
            sort: str = "LAST_VOLUME_DESC",
    ) -> list[Product]:
        limit = limit or getattr(self.settings, "search_products_per_keyword", 20)

        data = await self._call_api(
            method="aliexpress.affiliate.product.query",
            params={
                "keywords": keyword,
                "page_no": page_no,
                "page_size": limit,
                "target_currency": "ILS",
                "target_language": "HE",
                "ship_to_country": "IL",
                "sort": sort,
            },
        )

        return self._parse_product_query(data)

    def _parse_product_detail(self, data: dict) -> Product:
        try:
            product = (
                data["aliexpress_affiliate_productdetail_get_response"]
                ["resp_result"]
                ["result"]
                ["products"]
                ["product"][0]
            )
        except Exception as e:
            raise RuntimeError(
                f"Could not parse AliExpress product detail response: {data}"
            ) from e

        return self._product_from_api_dict(product)

    def _parse_product_query(self, data: dict) -> list[Product]:
        raw_products = self._extract_products_from_affiliate_response(data)

        products: list[Product] = []

        for item in raw_products:
            try:
                products.append(self._product_from_api_dict(item))
            except Exception as exc:
                print(f"Failed to parse AliExpress product: {exc}")

        return products

    def _product_from_api_dict(self, product: dict[str, Any]) -> Product:
        image_url = product.get("product_main_image_url")

        if not image_url:
            small_images = product.get("product_small_image_urls") or {}
            if isinstance(small_images, dict):
                image_list = small_images.get("string") or []
                if image_list:
                    image_url = image_list[0]

        product_url = (
                product.get("product_detail_url")
                or product.get("product_url")
                or ""
        )

        affiliate_url = (
                product.get("promotion_link")
                or product.get("product_affiliate_url")
                or product_url
        )

        rating = parse_rating_from_evaluate_rate(product.get("evaluate_rate"))

        product_id = (
                product.get("product_id")
                or product.get("item_id")
                or None
        )

        if not product_id and product_url:
            try:
                product_id = extract_product_id(product_url)
            except Exception:
                product_id = None

        title = (
                product.get("product_title")
                or product.get("title")
                or "AliExpress Product"
        )

        orders = (
                parse_int(product.get("lastest_volume"))
                or parse_int(product.get("volume"))
                or parse_int(product.get("orders"))
                or 0
        )

        return Product(
            product_id=str(product_id),
            title=title,
            product_url=product_url,
            affiliate_url=affiliate_url,

            price_usd=parse_float(product.get("sale_price")),
            original_price_usd=parse_float(product.get("original_price")),

            price_ils=parse_float(product.get("target_sale_price")),
            original_price_ils=parse_float(product.get("target_original_price")),

            currency=product.get("sale_price_currency") or "USD",
            rating=rating,
            orders=orders,

            shipping="משלוח משתנה",
            category=(
                    product.get("second_level_category_name")
                    or product.get("first_level_category_name")
            ),

            image_url=image_url,
            discount=product.get("discount"),
            shop_name=product.get("shop_name"),
            commission_rate=product.get("commission_rate"),
        )
