from dataclasses import dataclass
from typing import Optional


@dataclass
class Product:
    product_id: str
    title: str
    product_url: str

    price_usd: Optional[float] = None
    original_price_usd: Optional[float] = None

    price_ils: Optional[float] = None
    original_price_ils: Optional[float] = None

    currency: str = "USD"
    rating: Optional[float] = None
    orders: Optional[int] = None
    shipping: Optional[str] = None
    category: Optional[str] = None

    image_url: Optional[str] = None
    affiliate_url: Optional[str] = None

    discount: Optional[str] = None
    shop_name: Optional[str] = None
    commission_rate: Optional[str] = None