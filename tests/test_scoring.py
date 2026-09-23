from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from app.services.scoring import label_for_score, listed_discount_percent, score_product
from app.storage.price_history import get_price_stats, record_price


def test_listed_discount_from_ils_prices(product):
    assert listed_discount_percent(product) == 50


def test_listed_discount_falls_back_to_api_field(product):
    assert listed_discount_percent(replace(product, original_price_ils=None, discount="30%")) == 30


def test_score_without_history(product):
    result = score_product(product)
    # base 40 + rating 4.8 (17) + orders 6000 (11) + price <=60 (2) + listed 50% (13)
    assert result.score == 83
    assert result.real_drop_percent is None
    assert not result.lowest_price_seen


def test_score_is_clamped(product):
    perfect = replace(product, rating=5.0, orders=50000, price_ils=10, original_price_ils=100, promo_code="X")
    assert score_product(perfect).score <= 100


def test_inflated_list_price_is_worth_less_than_a_real_drop(product):
    now = datetime.now(timezone.utc)
    for days_ago in [20, 12, 6]:
        record_price(product.product_id, 60.0, 120.0, seen_at=now - timedelta(days=days_ago))

    history = get_price_stats(product.product_id)
    # Today's 40 ILS vs a steady 60 ILS: a real 33% drop, and the lowest we've seen.
    result = score_product(product, history)

    assert result.real_drop_percent == pytest.approx(100 * (60 - 40) / 60)
    assert result.lowest_price_seen
    assert result.breakdown["discount"] == 20
    assert result.breakdown["lowest_price"] == 4


def test_no_real_drop_means_no_discount_points(product):
    now = datetime.now(timezone.utc)
    for days_ago in [20, 12, 6]:
        record_price(product.product_id, 40.0, 80.0, seen_at=now - timedelta(days=days_ago))

    # AliExpress claims 50% off, but it has always been 40 ILS.
    result = score_product(product, get_price_stats(product.product_id))
    assert result.breakdown["discount"] == 0


def test_short_history_is_not_trusted(product):
    record_price(product.product_id, 60.0, seen_at=datetime.now(timezone.utc) - timedelta(days=1))
    result = score_product(product, get_price_stats(product.product_id))
    assert result.real_drop_percent is None


def test_record_price_dedupes_within_window():
    now = datetime.now(timezone.utc)
    assert record_price("p1", 10.0, seen_at=now)
    assert not record_price("p1", 10.0, seen_at=now + timedelta(hours=1))
    assert record_price("p1", 9.0, seen_at=now + timedelta(hours=2))
    assert get_price_stats("p1").count == 2


def test_labels():
    assert label_for_score(96) == "לא לפספס"
    assert label_for_score(60) == "דיל חלש"
