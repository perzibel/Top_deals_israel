import asyncio
from dataclasses import replace

from app.services.discovery_pool import (
    GADGET_KEYWORD_SET,
    KEYWORD_CATEGORY,
    STAPLE_KEYWORDS,
    keyword_wow,
    sample_keywords,
)
from app.services.engine import DealEngine, build_telegram_message
from app.services.filters import find_duplicate_title, is_good_deal, is_hidden_gem, title_similarity
from app.services.scoring import score_product
from app.storage.product_queue import (
    enqueue_product,
    get_next_queued_product,
    mark_posted,
    queued_count_for_keyword,
    recent_posted_keywords,
    select_best_diverse_product,
)

GADGET = "retro handheld game console"
STAPLE = STAPLE_KEYWORDS["phone_accessories"][0]


def test_sample_keywords_mixes_gadgets_and_staples():
    keywords = sample_keywords(20, staple_share=0.2)

    assert len(keywords) == len(set(keywords)) == 20
    assert sum(kw in GADGET_KEYWORD_SET for kw in keywords) == 16
    assert all(kw in KEYWORD_CATEGORY for kw in keywords)


def test_sample_keywords_avoids_recent_ones():
    avoid = set(list(GADGET_KEYWORD_SET)[:50])
    keywords = sample_keywords(20, staple_share=0, avoid=avoid)
    assert not avoid & set(keywords)


def test_gadgets_outscore_staples(product):
    gadget = score_product(product, wow=keyword_wow(GADGET)).score
    staple = score_product(product, wow=keyword_wow(STAPLE)).score
    plain = score_product(product).score

    assert gadget > plain > staple


def test_title_similarity_catches_relistings():
    a = "משאבת הסרת זיקוקים חזקה מפלסטיק עם ספיגת ברזל ואקום, רובה להסרת זיקוקים"
    b = "משאבת הסרת זיקוקים חזקה מפלסטיק עם ספיגת ברזל ואקום, רובה להסרת זיקוקים, עט ספיגה"
    other = "מצלמת אנדוסקופ TYPE-C ברזולוציה גבוהה עמידה במים"

    assert title_similarity(a, b) > 0.8
    assert find_duplicate_title(b, [other, a], 0.6) == a
    assert find_duplicate_title(other, [a], 0.6) is None


def test_hidden_gem_allows_few_orders_with_great_rating(product, settings):
    gem = replace(product, orders=250, rating=4.8)
    meh = replace(product, orders=250, rating=4.5)
    too_new = replace(product, orders=40, rating=4.9)

    assert is_hidden_gem(gem, settings) and is_good_deal(gem, settings)[0]
    assert not is_good_deal(meh, settings)[0]
    assert not is_good_deal(too_new, settings)[0]
    # Plenty of orders: a regular deal, not a hidden gem.
    assert not is_hidden_gem(product, settings)


def _row(keyword, score, category):
    return {"source_keyword": keyword, "source_category": category, "score": score, "created_at": "1"}


def test_selection_skips_recently_posted_keyword():
    rows = [_row("usb c hub", 95, "a"), _row("galaxy projector", 85, "b")]
    picked = select_best_diverse_product(rows, [], recent_keywords={"usb c hub"})
    assert picked["source_keyword"] == "galaxy projector"

    # Nothing else left: still post something.
    picked = select_best_diverse_product(rows[:1], [], recent_keywords={"usb c hub"})
    assert picked["source_keyword"] == "usb c hub"


def test_recent_posted_keywords():
    enqueue_product(
        product_id="p1", product_url="u", affiliate_url="a", title="t", score=90,
        source_keyword="moon lamp", source_category="lighting_vibes",
        product_data={}, enrichment_data={},
    )
    mark_posted(get_next_queued_product()["id"])
    assert recent_posted_keywords(3) == {"moon lamp"}


class _FakeSearch:
    def __init__(self, products):
        self.products = products

    async def search_products(self, keyword, limit, page_no, sort):
        return self.products


def _engine(settings, products, keywords, model_answer=None):
    settings.queue_target_size = 50
    engine = DealEngine(settings)
    engine.product_client = _FakeSearch(products)

    async def sources():
        return keywords

    engine._discovery_sources = sources

    if model_answer is not None:
        settings.use_ollama = True

        async def ask(product, search_keyword=None):
            return model_answer(product)

        engine.ollama._ask_model = ask

    return engine


def _variants(product, count):
    return [
        replace(product, product_id=f"v{i}", product_url=f"https://www.aliexpress.com/item/v{i}.html",
                title=f"Distinct gadget number {i} alpha{i} beta{i} gamma{i}")
        for i in range(count)
    ]


def test_discovery_caps_queue_per_keyword(product, settings):
    engine = _engine(settings, _variants(product, 6), [GADGET])
    asyncio.run(engine.discover_and_queue())
    assert queued_count_for_keyword(GADGET) == settings.max_queued_per_keyword


def test_discovery_skips_duplicate_titles(product, settings):
    first, second = _variants(product, 2)
    second = replace(second, title=first.title)
    engine = _engine(settings, [first, second], [GADGET])

    asyncio.run(engine.discover_and_queue())
    assert queued_count_for_keyword(GADGET) == 1


def test_discovery_drops_products_that_dont_match_the_search(product, settings):
    real, case = _variants(product, 2)
    engine = _engine(
        settings, [real, case], [GADGET],
        model_answer=lambda p: {"what_it_is": "x", "matches_search": p.product_id == real.product_id},
    )

    asyncio.run(engine.discover_and_queue())

    row = get_next_queued_product()
    assert queued_count_for_keyword(GADGET) == 1
    assert row["product_id"] == real.product_id
    assert '"wow_score": 8' in row["enrichment_json"]


def test_discovery_gives_up_on_off_target_keyword(product, settings):
    asked = []

    def answer(p):
        asked.append(p.product_id)
        return {"what_it_is": "x", "matches_search": False}

    engine = _engine(settings, _variants(product, 8), [GADGET], model_answer=answer)
    asyncio.run(engine.discover_and_queue())

    assert len(asked) == 3
    assert queued_count_for_keyword(GADGET) == 0


def test_message_highlights_gadgets_and_hidden_gems(product, settings):
    base = {"deal_score": 90, "deal_label": "x", "short_description": "תיאור קצר של המוצר", "tags": []}

    assert "גאדג'ט מגניב" in build_telegram_message(product, {**base, "wow_score": 8}, settings)
    assert "פנינה נסתרת" in build_telegram_message(product, {**base, "hidden_gem": True}, settings)
    assert "🤯" not in build_telegram_message(product, {**base, "wow_score": 4}, settings)
