from typing import Any


DEFAULT_ALLOWED_KEYWORDS = [
    "gaming",
    "gamer",
    "gamepad",
    "controller",
    "keyboard",
    "mouse",
    "headset",
    "rgb",
    "led",
    "tech",
    "usb",
    "type-c",
    "type c",
    "charger",
    "charging",
    "cable",
    "adapter",
    "hub",
    "dock",
    "phone",
    "iphone",
    "android",
    "case",
    "screen protector",
    "stand",
    "holder",
    "mount",
    "magnetic",
    "magsafe",
    "gadget",
    "smart",
    "smart home",
    "smart plug",
    "sensor",
    "wifi",
    "zigbee",
    "desk",
    "desk setup",
    "desk mat",
    "monitor",
    "lamp",
    "light bar",
]

BLOCKED_KEYWORDS = [
    "bikini",
    "swimsuit",
    "sexy",
    "lingerie",
    "dress",
    "blouse",
    "shirt",
    "pants",
    "skirt",
    "shoes",
    "pergola",
    "gazebo",
    "roof",
    "window",
    "door",
    "cabinet",
    "wardrobe",
    "sofa",
    "chair",
    "table",
    "furniture",
]


def get_product_value(product: Any, key: str, default=None):
    if isinstance(product, dict):
        return product.get(key, default)

    return getattr(product, key, default)


def parse_price_ils(product: Any) -> float | None:
    price_keys = [
        "target_sale_price",
        "sale_price",
        "app_sale_price",
        "target_original_price",
        "original_price",
    ]

    for key in price_keys:
        value = get_product_value(product, key)

        if value is None:
            continue

        try:
            cleaned = str(value).replace("₪", "").replace(",", "").strip()
            return float(cleaned)
        except ValueError:
            continue

    return None


def product_text(product: Any) -> str:
    fields = [
        "product_title",
        "title",
        "category_name",
        "category",
        "second_level_category_name",
        "first_level_category_name",
    ]

    return " ".join(
        str(get_product_value(product, field, "") or "")
        for field in fields
    ).lower()


def is_target_hot_product(
    product: Any,
    *,
    max_price_ils: float = 250,
    allowed_keywords: list[str] | None = None,
) -> tuple[bool, str]:
    allowed_keywords = allowed_keywords or DEFAULT_ALLOWED_KEYWORDS

    text = product_text(product)
    price = parse_price_ils(product)

    if price is not None and price > max_price_ils:
        return False, f"price too high: {price}"

    if any(blocked in text for blocked in BLOCKED_KEYWORDS):
        return False, "blocked keyword"

    if not any(keyword.lower() in text for keyword in allowed_keywords):
        return False, "no target keyword match"

    return True, "matched"