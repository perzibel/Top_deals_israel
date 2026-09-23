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

    if int(orders) < int(settings.min_orders):
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

    for term in BLOCKED_TITLE_TERMS + list(getattr(settings, "blocked_title_term_list", [])):
        if term and term in title:
            return False, f"blocked title term: {term}"

    return True, "ok"
