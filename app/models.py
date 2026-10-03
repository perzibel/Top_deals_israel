from dataclasses import dataclass
from typing import Optional


@dataclass
class Product:
    product_id: str
    title: str
    product_url: str

    # USD values are derived from the ILS prices (settings.usd_to_ils).
    # The AliExpress API's own sale_price/original_price are in CNY, not USD.
    price_usd: Optional[float] = None
    original_price_usd: Optional[float] = None

    price_ils: Optional[float] = None
    original_price_ils: Optional[float] = None

    currency: str = "ILS"
    rating: Optional[float] = None
    orders: Optional[int] = None
    shipping: Optional[str] = None
    category: Optional[str] = None
    # AliExpress category IDs (language independent), used for interest filtering.
    category_id: Optional[str] = None
    sub_category_id: Optional[str] = None

    image_url: Optional[str] = None
    affiliate_url: Optional[str] = None

    discount: Optional[str] = None
    shop_name: Optional[str] = None
    shop_id: Optional[str] = None
    commission_rate: Optional[str] = None
    video_url: Optional[str] = None

    # Coupon attached to the product by the affiliate API, if any.
    promo_code: Optional[str] = None
    promo_code_value: Optional[str] = None
    promo_code_min_spend: Optional[str] = None

    # Discovery source, e.g. "search", "hot_products", "promo:<name>".
    source: Optional[str] = None
