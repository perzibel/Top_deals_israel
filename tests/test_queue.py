from datetime import datetime, timedelta, timezone

from app.storage.paths import get_conn
from app.storage.product_queue import (
    enqueue_product,
    expire_stale_queued,
    get_next_queued_product,
    mark_posted,
    queue_size,
    select_best_diverse_product,
    was_queued,
)


def _enqueue(product_id, score, category, price=40.0):
    return enqueue_product(
        product_id=product_id,
        product_url=f"https://www.aliexpress.com/item/{product_id}.html",
        affiliate_url="https://s.click.aliexpress.com/e/x",
        title=f"Product {product_id}",
        score=score,
        source_keyword="kw",
        source_category=category,
        product_data={"product_id": product_id, "price_ils": price},
        enrichment_data={"deal_score": score},
    )


def test_selection_prefers_fresh_category():
    rows = [
        {"source_category": "car", "score": 95, "created_at": "2"},
        {"source_category": "pets", "score": 85, "created_at": "1"},
    ]
    picked = select_best_diverse_product(rows, recent_categories=["car"], rotation_window=3)
    assert picked["source_category"] == "pets"


def test_selection_respects_batch_exclusions():
    rows = [
        {"source_category": "car", "score": 95, "created_at": "2"},
        {"source_category": "pets", "score": 85, "created_at": "1"},
        {"source_category": "travel", "score": 80, "created_at": "1"},
    ]
    picked = select_best_diverse_product(rows, [], excluded_categories={"car", "pets"})
    assert picked["source_category"] == "travel"


def test_selection_falls_back_to_anything():
    rows = [{"source_category": "car", "score": 90, "created_at": "1"}]
    assert select_best_diverse_product(rows, ["car"], excluded_categories={"car"}) is rows[0]


def test_duplicate_enqueue_is_ignored_while_queued():
    assert _enqueue("a", 90, "car")
    assert not _enqueue("a", 95, "car")
    assert queue_size() == 1


def test_posted_product_can_be_requeued():
    _enqueue("a", 90, "car")
    row = get_next_queued_product()
    mark_posted(row["id"])
    assert not was_queued("a")

    assert _enqueue("a", 92, "car", price=30.0)
    assert was_queued("a")


def test_per_category_cap():
    for i in range(5):
        assert _enqueue(f"p{i}", 90, "car")
    assert not _enqueue("p5", 99, "car")


def test_expire_stale_queued():
    _enqueue("old", 90, "car")
    _enqueue("new", 90, "pets")

    old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    with get_conn() as conn:
        conn.execute("UPDATE product_queue SET created_at = ? WHERE product_id = 'old'", (old,))

    assert expire_stale_queued(3) == 1
    assert not was_queued("old")
    assert was_queued("new")
