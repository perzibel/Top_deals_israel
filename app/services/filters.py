import re

from app.services.scoring import listed_discount_percent
from app.utils import get_product_value

# Obvious parts/components that are not consumer-friendly deals.
BLOCKED_TITLE_TERMS = [
    "pcb",
    "connector",
    "plug socket",
    "socket connector",
    "2pin",
    "4pin",
    "pin header",
    "male plug",
    "female socket",
    "repair part",
    "replacement part",
]


# AliExpress sometimes returns spam titles like "aa/aaaaa/aaaa/aaaaaa/...".
REPEATED_CHAR_RUN = re.compile(r"(\w)\1{4,}")


def is_garbage_title(title: str) -> bool:
    if len(title.strip()) < 10:
        return True
    return bool(REPEATED_CHAR_RUN.search(title)) or title.count("/") >= 5


TITLE_WORD = re.compile(r"\w{2,}")


def _title_words(title: str) -> set[str]:
    return set(TITLE_WORD.findall((title or "").lower()))


def title_similarity(a: str, b: str) -> float:
    """Word overlap (Jaccard, 0-1). Sellers relist the same item with near-identical titles."""
    words_a, words_b = _title_words(a), _title_words(b)
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / len(words_a | words_b)


def find_duplicate_title(title: str, others: list[str], threshold: float) -> str | None:
    for other in others:
        if title_similarity(title, other) >= threshold:
            return other
    return None


def is_hidden_gem(product, settings) -> bool:
    """Not many orders yet, but buyers love it: worth showing before everyone finds it."""
    rating = get_product_value(product, "rating")
    orders = get_product_value(product, "orders")
    if rating is None or orders is None:
        return False

    min_orders = int(getattr(settings, "hidden_gem_min_orders", 0) or 0)
    if not min_orders:
        return False

    return (
        min_orders <= int(orders) < int(settings.min_orders)
        and float(rating) >= float(settings.hidden_gem_min_rating)
    )


def is_good_deal(product, settings):
    rating = get_product_value(product, "rating")
    orders = get_product_value(product, "orders")

    price_usd = get_product_value(product, "price_usd")
    price_ils = get_product_value(product, "price_ils")

    image_url = get_product_value(product, "image_url")
    affiliate_url = get_product_value(product, "affiliate_url")
    product_url = get_product_value(product, "product_url")

    title = (get_product_value(product, "title", "") or "").lower()

    # Required basics
    if not product_url:
        return False, "missing product_url"

    if not affiliate_url:
        return False, "missing affiliate_url"

    if not image_url:
        return False, "missing image_url"

    # Rating
    if rating is None:
        return False, "missing rating"

    if float(rating) < float(settings.min_rating):
        return False, f"rating {rating} below {settings.min_rating}"

    # Orders / volume
    if orders is None:
        return False, "missing orders"

    if int(orders) < int(settings.min_orders) and not is_hidden_gem(product, settings):
        return False, f"orders {orders} below {settings.min_orders}"

    # Price: ILS is the real price; USD only for legacy seed data without ILS.
    if price_ils is not None:
        price_ils = float(price_ils)

        if price_ils < float(settings.min_price_ils):
            return False, f"price ₪{price_ils} below minimum ₪{settings.min_price_ils}"

        if price_ils > float(settings.max_price_ils):
            return False, f"price ₪{price_ils} above maximum ₪{settings.max_price_ils}"

    elif price_usd is not None:
        price_usd = float(price_usd)

        if price_usd < float(settings.min_price_usd):
            return False, f"price ${price_usd} below minimum ${settings.min_price_usd}"

        if price_usd > float(settings.max_price_usd):
            return False, f"price ${price_usd} above maximum ${settings.max_price_usd}"

    else:
        return False, "missing price"

    min_discount = float(getattr(settings, "min_discount_percent", 0) or 0)
    if min_discount > 0:
        discount = listed_discount_percent(product) or 0
        if discount < min_discount:
            return False, f"discount {discount:.0f}% below {min_discount:.0f}%"

    allowed_whole, allowed_pairs = settings.allowed_category_rules
    if allowed_whole or allowed_pairs:
        category_id = str(get_product_value(product, "category_id") or "")
        sub_category_id = str(get_product_value(product, "sub_category_id") or "")

        if not category_id:
            return False, "missing category_id"

        if category_id not in allowed_whole and (category_id, sub_category_id) not in allowed_pairs:
            return False, f"category {category_id}:{sub_category_id} not in allowed categories"

    if is_garbage_title(title):
        return False, "garbage title"

    for term in BLOCKED_TITLE_TERMS + list(getattr(settings, "blocked_title_term_list", [])):
        if term and term in title:
            return False, f"blocked title term: {term}"

    return True, "ok"
