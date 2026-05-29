def get_product_value(product, key: str, default=None):
    if isinstance(product, dict):
        return product.get(key, default)

    return getattr(product, key, default)


def is_good_deal(product, settings):
    product_id = get_product_value(product, "product_id", "unknown")

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

    # ILS price filters
    if price_ils is not None:
        price_ils = float(price_ils)

        if hasattr(settings, "min_price_ils") and price_ils < float(settings.min_price_ils):
            return False, f"price ₪{price_ils} below minimum ₪{settings.min_price_ils}"

        if hasattr(settings, "max_price_ils") and price_ils > float(settings.max_price_ils):
            return False, f"price ₪{price_ils} above maximum ₪{settings.max_price_ils}"

    # USD fallback price filters
    elif price_usd is not None:
        price_usd = float(price_usd)

        if hasattr(settings, "min_price_usd") and price_usd < float(settings.min_price_usd):
            return False, f"price ${price_usd} below minimum ${settings.min_price_usd}"

        if hasattr(settings, "max_price_usd") and price_usd > float(settings.max_price_usd):
            return False, f"price ${price_usd} above maximum ${settings.max_price_usd}"

    else:
        return False, "missing price"

    # Avoid obvious parts/components that are not consumer-friendly deals
    blocked_title_terms = [
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

    for term in blocked_title_terms:
        if term in title:
            return False, f"blocked component/repair term: {term}"

    return True, "ok"