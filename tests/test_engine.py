import asyncio
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone

from app.services.engine import DealEngine, build_telegram_message, keyword_to_category
from app.storage.db import mark_posted as mark_product_posted
from app.storage.paths import get_conn
from app.storage.product_queue import enqueue_product, get_next_queued_product, mark_posted


def _enrichment(score=90, **extra):
    return {
        "short_description": "מטען מהיר וקומפקטי לבית ולנסיעות.",
        "deal_score": score,
        "deal_label": "דיל מעולה",
        "buy_verdict": "דיל טוב עם נתונים חזקים יחסית למחיר.",
        "tags": ["Charging", "USB C"],
        **extra,
    }


def test_message_uses_ils_and_escapes_html(product, settings):
    message = build_telegram_message(replace(product, title="Charger <65W> & more"), _enrichment(), settings)

    assert "₪40.00" in message
    assert "<s>₪80.00</s>" in message
    assert "&lt;65W&gt; &amp; more" in message
    assert "#USBC" in message


def test_message_includes_verdict_from_enrichment(product, settings):
    message = build_telegram_message(product, _enrichment(), settings)
    assert "דיל טוב עם נתונים חזקים יחסית למחיר." in message


def test_weak_score_gets_cautious_verdict_when_none_given(product, settings):
    enrichment = _enrichment(score=60)
    enrichment.pop("buy_verdict")
    message = build_telegram_message(product, enrichment, settings)
    assert "לא הייתי ממהר לקנות" in message


def test_message_shows_price_history_and_coupon(product, settings):
    coupon = replace(product, promo_code="IL5", promo_code_value="₪5", promo_code_min_spend="₪30")
    message = build_telegram_message(coupon, _enrichment(lowest_price_seen=True, real_drop_percent=25), settings)

    assert "המחיר הכי נמוך שראינו" in message
    assert "<code>IL5</code>" in message


def test_message_omits_unknown_shipping(product, settings):
    assert "🚚" not in build_telegram_message(product, _enrichment(), settings)


def test_keyword_to_category():
    assert keyword_to_category("65w gan charger") == "phone_accessories"
    assert keyword_to_category("", {"category": "Shoes"}) == "shoes"
    assert keyword_to_category("", {"category": "טלפון נייד", "category_id": "202192403"}) == "phone_accessories"
    assert keyword_to_category("") == "general"


def _posted(engine, product, price_ils, posted_days_ago):
    enqueue_product(
        product_id=product.product_id,
        product_url=product.product_url,
        affiliate_url=product.affiliate_url,
        title=product.title,
        score=90,
        source_keyword="kw",
        source_category="phone_accessories",
        product_data=asdict(replace(product, price_ils=price_ils)),
        enrichment_data={},
    )
    mark_posted(get_next_queued_product()["id"])
    mark_product_posted(product.product_id)

    ts = (datetime.now(timezone.utc) - timedelta(days=posted_days_ago)).strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        conn.execute("UPDATE posted_products SET posted_at = ?", (ts,))


def test_repost_requires_cooldown_and_price_drop(product, settings):
    engine = DealEngine(settings)

    _posted(engine, product, price_ils=50.0, posted_days_ago=5)
    assert not engine._repost_allowed(product.product_id, 30.0)[0]

    with get_conn() as conn:
        old = (datetime.now(timezone.utc) - timedelta(days=40)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("UPDATE posted_products SET posted_at = ?", (old,))

    assert not engine._repost_allowed(product.product_id, 48.0)[0]
    assert engine._repost_allowed(product.product_id, 40.0)[0]


class _FakeAliExpress:
    def __init__(self, fresh):
        self.fresh = fresh

    async def get_product_detail(self, url):
        return self.fresh


class _FakeTelegram:
    def __init__(self):
        self.sent = []
        self.alerts = []

    async def send_product(self, product, message):
        self.sent.append((product, message))

    async def send_alert(self, text):
        self.alerts.append(text)


def _queue(product):
    enqueue_product(
        product_id=product.product_id,
        product_url=product.product_url,
        affiliate_url=product.affiliate_url,
        title=product.title,
        score=90,
        source_keyword="kw",
        source_category="phone_accessories",
        product_data=asdict(product),
        enrichment_data=_enrichment(),
    )


def test_post_uses_refreshed_price(product, settings):
    settings.dry_run = False
    engine = DealEngine(settings)
    engine.aliexpress = _FakeAliExpress(replace(product, price_ils=35.0, affiliate_url=None))
    engine.telegram = _FakeTelegram()
    _queue(product)

    row = asyncio.run(engine.post_next_from_queue(force=True))

    assert row is not None
    posted_product, message = engine.telegram.sent[0]
    assert posted_product["price_ils"] == 35.0
    # Detail endpoint returned no promotion link; the queued one is kept.
    assert posted_product["affiliate_url"] == product.affiliate_url
    assert "₪35.00" in message


def test_post_skips_product_that_went_bad(product, settings):
    settings.dry_run = False
    engine = DealEngine(settings)
    engine.aliexpress = _FakeAliExpress(replace(product, price_ils=400.0, original_price_ils=800.0))
    engine.telegram = _FakeTelegram()
    engine.discover_and_queue = _no_discovery
    _queue(product)

    assert asyncio.run(engine.post_next_from_queue(force=True)) is None
    assert engine.telegram.sent == []

    with get_conn() as conn:
        status, reason = conn.execute("SELECT status, skipped_reason FROM product_queue").fetchone()
    assert status == "skipped" and reason.startswith("stale:")


def test_empty_batch_sends_alert(settings):
    settings.dry_run = False
    engine = DealEngine(settings)
    engine.telegram = _FakeTelegram()
    engine.discover_and_queue = _no_discovery

    assert asyncio.run(engine.post_batch_from_queue(force=True)) == 0
    assert engine.telegram.alerts


async def _no_discovery():
    return None


def test_dry_run_batch_never_repeats_a_product(product, settings):
    engine = DealEngine(settings)
    engine.discover_and_queue = _no_discovery
    for i, category in enumerate(["car", "pets"]):
        enqueue_product(
            product_id=f"p{i}",
            product_url=f"https://www.aliexpress.com/item/{i}.html",
            affiliate_url="https://s.click.aliexpress.com/e/x",
            title=f"Product {i}",
            score=90,
            source_keyword="kw",
            source_category=category,
            product_data=asdict(replace(product, product_id=f"p{i}")),
            enrichment_data=_enrichment(),
        )

    # Two products, batch of three: the third slot must come up empty, not repeat.
    assert asyncio.run(engine.post_batch_from_queue(force=True, dry_run=True)) == 2
