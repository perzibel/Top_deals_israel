from app.clients.aliexpress import AliExpressClient, ils_to_api_price
from app.clients.ollama import clean_tags, detect_product_type, is_usable_hebrew, verdict_for_score

RAW_PRODUCT = {
    "product_id": 1005012569395259,
    "product_title": "65W GaN Charger",
    "product_detail_url": "https://www.aliexpress.com/item/1005012569395259.html",
    "promotion_link": "https://s.click.aliexpress.com/s/abc",
    "product_main_image_url": "https://ae-pic-a1.aliexpress-media.com/kf/x.jpg",
    "sale_price": "97.90",
    "sale_price_currency": "CNY",
    "original_price": "195.80",
    "target_sale_price": "44.90",
    "target_original_price": "89.80",
    "target_sale_price_currency": "ILS",
    "evaluate_rate": "96.0%",
    "lastest_volume": 2202,
    "discount": "50%",
    "second_level_category_name": "Chargers",
    "shop_id": 1105667537,
    "promo_code_info": {"promo_code": "IL5", "code_value": "5 ILS", "code_mini_spend": "30 ILS"},
}


def test_parser_uses_ils_not_cny(settings):
    product = AliExpressClient(settings)._product_from_api_dict(RAW_PRODUCT)

    assert product.price_ils == 44.90
    assert product.original_price_ils == 89.80
    assert product.currency == "ILS"
    # Derived from ILS, not the CNY sale_price.
    assert product.price_usd == round(44.90 / 3.7, 2)
    assert product.rating == 4.8
    assert product.orders == 2202
    assert product.promo_code == "IL5"
    assert product.shipping is None


def test_parser_does_not_fake_affiliate_link(settings):
    raw = {k: v for k, v in RAW_PRODUCT.items() if k != "promotion_link"}
    assert AliExpressClient(settings)._product_from_api_dict(raw).affiliate_url is None


def test_api_price_is_in_agorot():
    assert ils_to_api_price(250) == "25000"


def test_hebrew_validation():
    assert is_usable_hebrew("מטען מהיר וקומפקטי לבית ולנסיעות.", 160)
    assert not is_usable_hebrew("Fast compact charger for home", 160)
    assert not is_usable_hebrew("מטען 快速充电器", 160)
    assert not is_usable_hebrew("<think>hmm</think> מטען מהיר וקומפקטי", 160)
    assert not is_usable_hebrew("א" * 200, 160)
    assert not is_usable_hebrew(None, 160)


def test_verdict_bands_never_hype_weak_deals():
    assert "לא הייתי ממהר" in verdict_for_score(50)
    assert "לא הייתי ממהר" not in verdict_for_score(90)


def test_detect_product_type():
    assert detect_product_type("Baseus 20000mAh Power Bank") == "power_bank"
    assert detect_product_type("Random widget") is None


def test_clean_tags():
    assert clean_tags(["#USB C", "Charging!", "USBC", 5]) == ["USBC", "Charging", "5"]
    assert clean_tags("not a list") == []


def test_hebrew_validation_rejects_other_scripts():
    assert not is_usable_hebrew("מתאים למטבחים עם חסרים בتنظيم.", 160)
    assert not is_usable_hebrew("מטען מהיר и компактный", 160)
