"""
Deterministic deal score (1-100).

Everything is priced in ILS. When we have our own price history for a product
the discount is measured against it; otherwise we fall back to AliExpress's
listed discount, which is worth less because list prices are often inflated.
"""
from dataclasses import dataclass, field
from typing import Any, Optional

from app.storage.price_history import PriceStats

# Minimum history needed before we trust our own price data over AliExpress's.
MIN_HISTORY_POINTS = 3
MIN_HISTORY_SPAN_DAYS = 3


def _value(product: Any, key: str, default=None):
    if isinstance(product, dict):
        return product.get(key, default)
    return getattr(product, key, default)


def listed_discount_percent(product: Any) -> Optional[float]:
    price = _value(product, "price_ils")
    original = _value(product, "original_price_ils")

    if price and original and float(original) > float(price):
        return (float(original) - float(price)) / float(original) * 100

    raw = _value(product, "discount")
    if raw:
        try:
            return float(str(raw).replace("%", "").strip())
        except ValueError:
            return None

    return None


@dataclass
class ScoreResult:
    score: int
    breakdown: dict[str, int] = field(default_factory=dict)
    # True when the price is at or below the lowest price we have recorded.
    lowest_price_seen: bool = False
    # Drop versus our own median price, in percent, when history is available.
    real_drop_percent: Optional[float] = None


def _rating_points(rating) -> int:
    if not rating:
        return 0
    rating = float(rating)
    for threshold, points in [(4.9, 20), (4.8, 17), (4.7, 14), (4.6, 10), (4.5, 7)]:
        if rating >= threshold:
            return points
    return 0


def _orders_points(orders) -> int:
    if not orders:
        return 0
    orders = int(orders)
    for threshold, points in [(10000, 20), (8000, 13), (5000, 11), (3000, 8), (1000, 5), (100, 2)]:
        if orders >= threshold:
            return points
    return 0


def _listed_discount_points(discount: Optional[float]) -> int:
    if not discount:
        return 0
    for threshold, points in [(70, 16), (50, 13), (40, 10), (30, 7), (15, 4), (5, 2)]:
        if discount >= threshold:
            return points
    return 0


def _real_drop_points(drop_percent: float) -> int:
    for threshold, points in [(30, 20), (20, 16), (12, 12), (7, 8), (3, 4)]:
        if drop_percent >= threshold:
            return points
    return 0


def _price_points(price_ils) -> int:
    if not price_ils:
        return 0
    price_ils = float(price_ils)
    if price_ils <= 30:
        return 4
    if price_ils <= 60:
        return 2
    return 0


def wow_points(wow: Optional[int]) -> int:
    """Model-rated wow factor (1-10): a cool gadget gains up to 15, a dull one loses up to 12."""
    if not wow:
        return 0
    return (max(1, min(10, int(wow))) - 5) * 3


def score_product(product: Any, history: Optional[PriceStats] = None, wow: Optional[int] = None) -> ScoreResult:
    breakdown = {
        "base": 40,
        "rating": _rating_points(_value(product, "rating")),
        "orders": _orders_points(_value(product, "orders")),
        "price": _price_points(_value(product, "price_ils")),
        "coupon": 2 if _value(product, "promo_code") else 0,
        "wow": wow_points(wow),
    }

    price = _value(product, "price_ils")
    trusted_history = (
            history is not None
            and price
            and history.count >= MIN_HISTORY_POINTS
            and history.span_days >= MIN_HISTORY_SPAN_DAYS
    )

    lowest = False
    real_drop = None

    if trusted_history:
        real_drop = max(0.0, (history.median_price - float(price)) / history.median_price * 100)
        breakdown["discount"] = _real_drop_points(real_drop)

        lowest = float(price) <= history.min_price + 0.01
        if lowest and real_drop >= 3:
            breakdown["lowest_price"] = 4
    else:
        breakdown["discount"] = _listed_discount_points(listed_discount_percent(product))

    score = max(1, min(100, sum(breakdown.values())))

    return ScoreResult(
        score=score,
        breakdown=breakdown,
        lowest_price_seen=lowest,
        real_drop_percent=real_drop,
    )


def label_for_score(score: int) -> str:
    if score > 94:
        return "לא לפספס"
    if score >= 85:
        return "דיל מעולה 🎉"
    if score >= 70:
        return "דיל טוב"
    return "דיל חלש"
