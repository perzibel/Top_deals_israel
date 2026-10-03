from dataclasses import replace

from app.services.filters import is_good_deal


def test_good_product_passes(product, settings):
    assert is_good_deal(product, settings) == (True, "ok")


def test_missing_affiliate_link_rejected(product, settings):
    allowed, reason = is_good_deal(replace(product, affiliate_url=None), settings)
    assert not allowed and reason == "missing affiliate_url"


def test_low_rating_rejected(product, settings):
    allowed, reason = is_good_deal(replace(product, rating=4.2), settings)
    assert not allowed and "rating" in reason


def test_low_orders_rejected(product, settings):
    allowed, reason = is_good_deal(replace(product, orders=50), settings)
    assert not allowed and "orders" in reason


def test_price_bounds_in_ils(product, settings):
    assert not is_good_deal(replace(product, price_ils=5, original_price_ils=10), settings)[0]
    assert not is_good_deal(replace(product, price_ils=300, original_price_ils=600), settings)[0]


def test_min_discount_enforced(product, settings):
    no_discount = replace(product, original_price_ils=40.0, discount="0%")
    allowed, reason = is_good_deal(no_discount, settings)
    assert not allowed and "discount" in reason


def test_min_discount_disabled_when_zero(product, settings):
    settings.min_discount_percent = 0
    no_discount = replace(product, original_price_ils=40.0, discount="0%")
    assert is_good_deal(no_discount, settings)[0]


def test_blocked_component_terms(product, settings):
    allowed, reason = is_good_deal(replace(product, title="USB PCB board connector"), settings)
    assert not allowed and "blocked" in reason


def test_custom_blocked_terms_from_settings(product, settings):
    settings.blocked_title_terms = "Insole, shoes"
    allowed, _ = is_good_deal(replace(product, title="Orthopedic insole"), settings)
    assert not allowed


def test_works_with_queue_dicts(product, settings):
    from dataclasses import asdict

    assert is_good_deal(asdict(product), settings)[0]


def test_allowed_categories(product, settings):
    settings.allowed_category_ids = "44,13:200321150"

    assert not is_good_deal(product, settings)[0]  # no category id at all
    assert is_good_deal(replace(product, category_id="44"), settings)[0]
    assert is_good_deal(replace(product, category_id="13", sub_category_id="200321150"), settings)[0]

    allowed, reason = is_good_deal(replace(product, category_id="13", sub_category_id="200066144"), settings)
    assert not allowed and "not in allowed" in reason
    assert not is_good_deal(replace(product, category_id="322"), settings)[0]


def test_hebrew_blocked_terms(product, settings):
    settings.blocked_title_terms = "תינוק,חתול"
    assert not is_good_deal(replace(product, title="מראה לרכב לתינוק"), settings)[0]


def test_garbage_titles_rejected(product, settings):
    junk = replace(product, title="Pujiamx aa/aaaaa/aaaa/aaaa/aaaa/aaaa/aaa/aaaa")
    assert is_good_deal(junk, settings) == (False, "garbage title")
    assert is_good_deal(replace(product, title="מטען 65W GaN מהיר USB-C/USB-A"), settings)[0]
