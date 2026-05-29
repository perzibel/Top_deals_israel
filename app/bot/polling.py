import re
from typing import Any
from html import escape
import os
from dotenv import load_dotenv
from iop.base import IopRequest, IopClient, IopResponse
from deep_translator import GoogleTranslator
import json
import requests
from langdetect import detect

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from app.config import Settings
from app.clients.aliexpress import AliExpressClient
from app.bot.queue import enqueue_request, init_queue_db
from app.bot.utils import extract_aliexpress_url

TELEGRAM_BOT_TOKEN = ""

OLLAMA_URL = "http://localhost:11434/api/generate"
translate_MODEL = "qwen3:1.7b"
OLLAMA_MODEL = "qwen2.5:1.5b"


search_cache = {}

GENERIC_CONTEXT_WORDS = {
    # Hebrew grammar / filler words only
    "ל", "של", "עם", "על", "את", "או", "ו", "ב", "מ", "מן",
    "אל", "כי", "אם", "גם", "כל", "לא", "כן",
    "עבור", "בשביל", "כולל", "ללא",

    # Common shopping noise words
    "מתאים", "מתאימה", "מותאם", "מותאמת",
    "חדש", "חדשה", "מקורי", "מקורית",
    "איכותי", "איכותית", "פרימיום",
    "סט", "ערכת", "ערכה", "יחידות", "יחידה",
    "דגם", "סוג", "צבע", "גודל",

    # English grammar / filler words only
    "for", "with", "and", "or", "the", "a", "an",
    "to", "of", "in", "on", "by", "from",
    "compatible", "include", "includes", "without",

    # English shopping noise words
    "new", "original", "premium", "quality",
    "set", "kit", "pcs", "piece", "pieces",
    "model", "type", "size", "color",
}

PRODUCT_TYPE_SYNONYMS = {
    "stand_holder": {
        "terms": {
            "מעמד", "מחזיק", "סטנד",
            "stand", "holder", "mount", "bracket"
        },
        "conflicts": {
            "מטען", "טעינה", "כבל", "מתאם", "ספק", "חשמל",
            "charger", "charging", "cable", "adapter", "power",
            "כיסוי", "קייס", "case", "cover",
            "מגן מסך", "זכוכית", "screen protector", "glass", "film",
        },
    },

    "charger": {
        "terms": {
            "מטען", "טעינה", "charger", "charging", "power adapter"
        },
        "conflicts": {
            "מעמד", "מחזיק", "סטנד", "stand", "holder", "mount",
            "כיסוי", "case", "cover",
            "מגן מסך", "screen protector",
        },
    },

    "cable": {
        "terms": {
            "כבל", "cable", "cord"
        },
        "conflicts": {
            "מטען", "charger",
            "מעמד", "stand", "holder",
            "כיסוי", "case", "cover",
        },
    },

    "case_cover": {
        "terms": {
            "כיסוי", "קייס", "case", "cover", "bumper"
        },
        "conflicts": {
            "מטען", "charger",
            "כבל", "cable",
            "מעמד", "stand", "holder",
            "מגן מסך", "screen protector", "glass",
        },
    },

    "screen_protector": {
        "terms": {
            "מגן מסך", "זכוכית מחוסמת", "זכוכית",
            "screen protector", "tempered glass", "protective film", "glass film"
        },
        "conflicts": {
            "כיסוי", "case", "cover",
            "מטען", "charger",
            "כבל", "cable",
            "מעמד", "stand", "holder",
        },
    },

    "speaker": {
        "terms": {
            "רמקול", "speaker", "loudspeaker"
        },
        "conflicts": {
            "אוזניות", "earphones", "headphones", "earbuds", "headset"
        },
    },

    "headphones": {
        "terms": {
            "אוזניות", "headphones", "earphones", "earbuds", "headset"
        },
        "conflicts": {
            "רמקול", "speaker", "loudspeaker"
        },
    },

    "watch": {
        "terms": {
            "שעון", "watch", "smartwatch", "smart watch"
        },
        "conflicts": {
            "רצועה", "strap", "band",
            "מטען", "charger",
            "מגן מסך", "screen protector",
        },
    },

    "strap_band": {
        "terms": {
            "רצועה", "רצועת", "strap", "band"
        },
        "conflicts": {
            "שעון חכם", "smartwatch", "smart watch"
        },
    },

    "filter": {
        "terms": {
            "פילטר", "מסנן", "filter"
        },
        "conflicts": set(),
    },

    "brush": {
        "terms": {
            "מברשת", "brush"
        },
        "conflicts": set(),
    },

    "bag": {
        "terms": {
            "תיק", "תיק גב", "bag", "backpack"
        },
        "conflicts": {
            "כיסוי", "cover",
            "רצועה", "strap"
        },
    },

    "lamp_light": {
        "terms": {
            "מנורה", "תאורה", "פנס", "אור",
            "lamp", "light", "flashlight", "lantern"
        },
        "conflicts": set(),
    },
}


async def new_cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    user = update.effective_user

    if not user:
        return

    keyword = " ".join(context.args).strip()

    if not keyword:
        await update.message.reply_text(
            "שלחו כך:\n/search <keyword>\n\nלדוגמה:\n/search מצלמת אבטחה"
        )
        return

    await update.message.reply_text(
        f"🔎 מחפש מוצרים עבור: <b>{escape(keyword)}</b>",
        parse_mode=ParseMode.HTML,
    )

    # Set env variables

    load_dotenv()
    appkey = os.getenv("ALIEXPRESS_APP_KEY")
    appSecret = os.getenv("ALIEXPRESS_APP_SECRET")
    from langdetect import detect

    url = "https://api-sg.aliexpress.com/sync"
    if detect(keyword) == 'he':
        print('he')
        keyword = GoogleTranslator(source='iw', target='en').translate(keyword)

    # Pull product info based on Key word
    client = IopClient(url, appkey, appSecret)
    request = IopRequest('aliexpress.affiliate.product.query')
    request.add_api_param('keywords', keyword)
    request.add_api_param('target_currency', 'ILS')
    request.add_api_param('ship_to_country', 'IL')
    request.add_api_param('sort', 'LAST_VOLUME_DESC')
    response = client.execute(request)
    print(response.type)

    def check_internal_related_with_ollama(first: str, category: str, product_title: str) -> dict:

        prompt = f"""
    You are an AI agent checking whether an AliExpress product matches a user search keyword.

    You will receive:
    - First: the original keyword/search phrase used to search products.
    - Product Title: the actual product title returned from AliExpress.
    - Product Category: the first-level category returned from AliExpress.

    Your task:
    Decide if the Product Title + Product Category are related to the original search keyword.

    Important:
    - The keyword may be broad, such as "PC Gadgets", "LED Light", "Gaming Accessories", or "Phone Accessories".
    - Use both the product title and category together.
    - Product Title is usually more important than Product Category.
    - Category alone is not enough if the product title clearly does not match.
    - If the title clearly matches the searched keyword, mark it related even if the category is broad.
    - If the category sounds related but the product title is about something else, mark it not_related or maybe_related.
    - Do not mark products as related only because they are general consumer products.

    Decision rules:
    - "related": the product clearly matches the search keyword, is a subcategory, or is commonly used with it.
    - "maybe_related": the product could match depending on usage/context, but the connection is not clear enough.
    - "not_related": the product does not match the search keyword or belongs to a different shopping intent.

    Sub-result options:
    - "same_category"
    - "specific_item_in_category"
    - "compatible_use"
    - "compatible_categories"
    - "broad_category"
    - "different_category"
    - "ambiguous"
    - "ambiguous_word"
    - "ambiguous_word_resolved"
    - "title_matches_keyword"
    - "title_conflicts_with_category"
    - "category_too_broad"

    Examples:
    First: "PC Gadgets" Product Title: "USB 3.0 Hub Splitter for Laptop PC" Product Category: "Computer Accessories" result: "related" sub_result: "specific_item_in_category"
    First: "PC Gadgets" Product Title: "Wireless Gaming Mouse RGB Rechargeable" Product Category: "Computer Accessories" result: "related" sub_result: "specific_item_in_category"
    First: "PC Gadgets" Product Title: "Phone Case for iPhone 15 Pro Max" Product Category: "Phone Accessories" result: "not_related" sub_result: "different_category"
    First: "PC Gadgets" Product Title: "USB Hub Type-C Adapter for MacBook Laptop" Product Category: "Consumer Electronics" result: "related" sub_result: "compatible_use"
    First: "PC Gadgets" Product Title: "RGB Gaming Keyboard Wrist Rest Pad" Product Category: "Gaming Accessories" result: "related" sub_result: "compatible_categories"
    First: "PC Gadgets" Product Title: "Kitchen Garlic Press Stainless Steel" Product Category: "Home & Garden" result: "not_related" sub_result: "different_category"
    First: "PC Gadgets" Product Title: "Cable Organizer Clips for Desk Setup" Product Category: "Office Accessories" result: "maybe_related" sub_result: "compatible_use"

    First: "LED Light" Product Title: "USB LED Strip Light for TV Backlight" Product Category: "Home Accessories" result: "related" sub_result: "title_matches_keyword"
    First: "LED Light" Product Title: "LED Desk Lamp with Touch Control" Product Category: "Lighting" result: "related" sub_result: "specific_item_in_category"
    First: "LED Light" Product Title: "Car Interior LED Ambient Light Strip" Product Category: "Automotive" result: "maybe_related" sub_result: "compatible_use"
    First: "LED Light" Product Title: "Phone Case with Glitter Design" Product Category: "Phone Accessories" result: "not_related" sub_result: "different_category"

    First: "Mouse" Product Title: "Wireless Mouse 2.4GHz for Laptop" Product Category: "Computer Accessories" result: "related" sub_result: "ambiguous_word_resolved"
    First: "Mouse" Product Title: "Cat Toy Fake Mouse Plush" Product Category: "Pet Accessories" result: "not_related" sub_result: "ambiguous_word"
    First: "Mouse" Product Title: "Gaming Mouse Pad XXL RGB" Product Category: "Computer Accessories" result: "related" sub_result: "compatible_use"

    First: "Phone Accessories" Product Title: "USB-C Fast Charging Cable for Samsung Xiaomi" Product Category: "Phone Accessories" result: "related" sub_result: "specific_item_in_category"
    First: "Phone Accessories" Product Title: "Laptop Cooling Stand with Fan" Product Category: "Computer Accessories" result: "not_related" sub_result: "different_category"
    First: "Phone Accessories" Product Title: "Bluetooth Earbuds Wireless Headphones" Product Category: "Consumer Electronics" result: "maybe_related" sub_result: "compatible_use"

    Return ONLY valid JSON.
    Do not explain.
    Do not use markdown.
    Do not add extra text.

    Return ONLY valid JSON in this exact structure:
    {{
      "first": "{first}",
      "second": "{product_title}",
      "result": "Choose ONLY one from: related | maybe_related | not_related",
      "sub_result": "short reason category"
    }}

    Input:
    First: {first}
    product title: {product_title}
    second: {category}

    """.strip()

        payload = {
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0,
                "num_predict": 120,
            },
        }

        response = requests.post(OLLAMA_URL, json=payload, timeout=120)

        if response.status_code != 200:
            raise RuntimeError(
                f"Ollama error. Status={response.status_code}, Body={response.text[:1000]}"
            )

        raw_model_response = response.json().get("response", "").strip()

        try:
            return json.loads(raw_model_response)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Ollama returned invalid JSON:\n{raw_model_response}"
            ) from e

    related_list = []
    print(len(response.body['aliexpress_affiliate_product_query_response']['resp_result']['result']['products']['product']))
    for i in response.body['aliexpress_affiliate_product_query_response']['resp_result']['result']['products']['product']:
        res = check_internal_related_with_ollama(keyword, i['first_level_category_name'], i['product_title'])
        if res['result'] != 'related':
            continue
        item = {
            "product": i,
            "orders": int(i.get("lastest_volume") or 0),
            "discount_percent": int(str(i.get("discount", "0")).replace("%", "") or 0),
            "affiliate_url": i.get("promotion_link") or i.get("product_detail_url"),
        }

        related_list.append(item)

        # Stop at 5 related products
        if len(related_list) >= 5:
            break

    text_parts = [
        "מצאתי כמה מוצרים חזקים לפי כמות הזמנות והנחה.\n",
        "אתם יכולים להיכנס למוצרים ולבדוק בעצמכם,",
        "או ללחוץ על הכפתור של המוצר הכי קרוב כדי לקבל AI Review.\n",
    ]

    keyboard = []

    for index, item in enumerate(related_list, start=1):
        product = item["product"]
        orders = item["orders"]
        discount_percent = item["discount_percent"]
        affiliate_url = item["affiliate_url"]

        title = product.get("product_title") or "AliExpress Product"
        short_title = title[:80] + "..." if len(title) > 80 else title

        price_ils = product.get("target_sale_price") or product.get("target_app_sale_price")
        price_usd = product.get("sale_price")

        if price_ils:
            price_text = f"₪{float(price_ils):.2f}"
        elif price_usd:
            price_text = f"${float(price_usd):.2f}"
        else:
            price_text = "לא ידוע"

        rating_text = product.get("evaluate_rate") or "לא ידוע"
        shop_text = product.get("shop_name") or "לא ידוע"

        cache_key = f"{user.id}:{index}"
        context.bot_data.setdefault("search_cache", {})
        context.bot_data["search_cache"][cache_key] = affiliate_url

        text_parts.append(
            (
                f"<b>{index}. {escape(short_title)}</b>\n"
                f"מחיר: <b>{escape(price_text)}</b>\n"
                f"הזמנות: <b>{orders:,}</b>\n"
                f"הנחה: <b>{discount_percent}%</b>\n"
                f"דירוג: <b>{escape(str(rating_text))}</b>\n"
                f"חנות: <b>{escape(shop_text)}</b>\n"
            )
        )

        keyboard.append(
            [
                InlineKeyboardButton(
                    text=f"🔗 לפתוח מוצר {index}",
                    url=affiliate_url,
                )
            ]
        )

    await update.message.reply_text(
        "\n".join(text_parts),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True,
    )


def translate_with_ollama(text):
    prompt = f"""
    You are a translator with the following task:
    You will receive a hebrew text from a user, he needs you help
    1. Make sure the hebrew was written correctly 
    2. translate the test to common speak english 
        
    Output:
    Should be ONLY the following Json:
    
    {{
        "received keyword" : "<text exact text that was received as the input >",
        "translation": "<The translation of the keyword>",
        "confidence": "between 0.0 and 1.0, how direct translate is it"
    }}    
    
    instructions:
    1. Do not remove words from the text input
    2. you want to find a words that are as close as possible to the user request
    3. do not analys the text, only translate.
    4. do not add words to the text
    
    Example:
    1. received: "תאורת לד למרפסת " output 
        "received keyword" : "תאורת לד למרפסת ",
        "translation": "balcony led light",
        "confidence": "1.0"
    2. received: "תאורת אווירה לרכב" output
        "received keyword" : "תאורת אווירה לרכב",
        "translation": "Car environment lighting",
        "confidence": "1.0"
    3. received: "מעמד לטלפון" output
        "received keyword" : "מעמד לטלפון",
        "translation": "phone stand",
        "confidence": "1.0"
    
    here is your hebrew text to translate:
    {text}
    
    
    """

    payload = {
        "model": translate_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": 500
        }
    }

    response = requests.post(OLLAMA_URL, json=payload, timeout=120)
    response.raise_for_status()
    return response.json().get("response", "").strip()


def relevance_check_with_ollama(first: str, category: str, product_title: str):
    prompt = f"""
    You are an AI agent checking whether an AliExpress product matches a user search keyword.

    You will receive:
    - First: the original keyword/search phrase used to search products.
    - Product Title: the actual product title returned from AliExpress.
    - Product Category: the first-level category returned from AliExpress.

    Your task:
    Decide if the Product Title + Product Category are related to the original search keyword.

    Important:
    - The keyword may be broad, such as "PC Gadgets", "LED Light", "Gaming Accessories", or "Phone Accessories".
    - Use both the product title and category together.
    - Product Title is usually more important than Product Category.
    - Category alone is not enough if the product title clearly does not match.
    - If the title clearly matches the searched keyword, mark it related even if the category is broad.
    - If the category sounds related but the product title is about something else, mark it not_related or maybe_related.
    - Do not mark products as related only because they are general consumer products.

    Decision rules:
    - "related": the product clearly matches the search keyword, is a subcategory, or is commonly used with it.
    - "maybe_related": the product could match depending on usage/context, but the connection is not clear enough.
    - "not_related": the product does not match the search keyword or belongs to a different shopping intent.

    Sub-result options:
    - "same_category"
    - "specific_item_in_category"
    - "compatible_use"
    - "compatible_categories"
    - "broad_category"
    - "different_category"
    - "ambiguous"
    - "ambiguous_word"
    - "ambiguous_word_resolved"
    - "title_matches_keyword"
    - "title_conflicts_with_category"
    - "category_too_broad"

    Examples:
    First: "PC Gadgets" Product Title: "USB 3.0 Hub Splitter for Laptop PC" Product Category: "Computer Accessories" result: "related" sub_result: "specific_item_in_category"
    First: "PC Gadgets" Product Title: "Wireless Gaming Mouse RGB Rechargeable" Product Category: "Computer Accessories" result: "related" sub_result: "specific_item_in_category"
    First: "PC Gadgets" Product Title: "Phone Case for iPhone 15 Pro Max" Product Category: "Phone Accessories" result: "not_related" sub_result: "different_category"
    First: "PC Gadgets" Product Title: "USB Hub Type-C Adapter for MacBook Laptop" Product Category: "Consumer Electronics" result: "related" sub_result: "compatible_use"
    First: "PC Gadgets" Product Title: "RGB Gaming Keyboard Wrist Rest Pad" Product Category: "Gaming Accessories" result: "related" sub_result: "compatible_categories"
    First: "PC Gadgets" Product Title: "Kitchen Garlic Press Stainless Steel" Product Category: "Home & Garden" result: "not_related" sub_result: "different_category"
    First: "PC Gadgets" Product Title: "Cable Organizer Clips for Desk Setup" Product Category: "Office Accessories" result: "maybe_related" sub_result: "compatible_use"

    First: "LED Light" Product Title: "USB LED Strip Light for TV Backlight" Product Category: "Home Accessories" result: "related" sub_result: "title_matches_keyword"
    First: "LED Light" Product Title: "LED Desk Lamp with Touch Control" Product Category: "Lighting" result: "related" sub_result: "specific_item_in_category"
    First: "LED Light" Product Title: "Car Interior LED Ambient Light Strip" Product Category: "Automotive" result: "maybe_related" sub_result: "compatible_use"
    First: "LED Light" Product Title: "Phone Case with Glitter Design" Product Category: "Phone Accessories" result: "not_related" sub_result: "different_category"

    First: "Mouse" Product Title: "Wireless Mouse 2.4GHz for Laptop" Product Category: "Computer Accessories" result: "related" sub_result: "ambiguous_word_resolved"
    First: "Mouse" Product Title: "Cat Toy Fake Mouse Plush" Product Category: "Pet Accessories" result: "not_related" sub_result: "ambiguous_word"
    First: "Mouse" Product Title: "Gaming Mouse Pad XXL RGB" Product Category: "Computer Accessories" result: "related" sub_result: "compatible_use"

    First: "Phone Accessories" Product Title: "USB-C Fast Charging Cable for Samsung Xiaomi" Product Category: "Phone Accessories" result: "related" sub_result: "specific_item_in_category"
    First: "Phone Accessories" Product Title: "Laptop Cooling Stand with Fan" Product Category: "Computer Accessories" result: "not_related" sub_result: "different_category"
    First: "Phone Accessories" Product Title: "Bluetooth Earbuds Wireless Headphones" Product Category: "Consumer Electronics" result: "maybe_related" sub_result: "compatible_use"

    Return ONLY valid JSON.
    Do not explain.
    Do not use markdown.
    Do not add extra text.

    Return ONLY valid JSON in this exact structure:
    {{
      "first": "{first}",
      "second": "{product_title}",
      "result": "Choose ONLY one from: related | maybe_related | not_related",
      "sub_result": "short reason category"
    }}

    Input:
    First: {first}
    product title: {product_title}
    second: {category}

    """.strip()
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0,
            "num_predict": 120,
        },
    }

    response = requests.post(OLLAMA_URL, json=payload, timeout=120)
    if response.status_code != 200:
        raise RuntimeError(
            f"Ollama error. Status={response.status_code}, Body={response.text[:1000]}"
        )
    raw_model_response = response.json().get("response", "").strip()
    try:
        js_raw = json.loads(raw_model_response)
        if js_raw['result'] == 'related':
            return True
        else:
            return False
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Ollama returned invalid JSON:\n{raw_model_response}"
        ) from e


def translate_hebrew_to_english(text):
    """Translates Hebrew text to English using Google Translator."""
    translated = translate_with_ollama(text)
    return json.loads(translated).get('translation')


def parse_discount_percent(value) -> int:
    if value is None:
        return 0

    try:
        return int(float(str(value).replace("%", "").strip()))
    except Exception:
        return 0


def normalize_text(value: str | None) -> str:
    if not value:
        return ""

    value = (
        value.lower()
        .replace("-", " ")
        .replace("_", " ")
        .replace("/", " ")
        .replace("|", " ")
        .replace(",", " ")
        .replace(".", " ")
        .replace(":", " ")
        .replace(";", " ")
        .replace("(", " ")
        .replace(")", " ")
    )

    return re.sub(r"\s+", " ", value).strip()


def text_contains_term(text: str, term: str) -> bool:
    text = normalize_text(text)
    term = normalize_text(term)

    if not text or not term:
        return False

    if " " in term:
        return term in text

    return term in text.split()


def contains_any(text: str, terms: set[str] | list[str]) -> bool:
    return any(text_contains_term(text, term) for term in terms)


def keyword_tokens(keyword: str) -> list[str]:
    text = normalize_text(keyword)

    return [
        token
        for token in text.split()
        if token not in GENERIC_CONTEXT_WORDS and len(token) > 1
    ]


def detect_product_type(text: str) -> str | None:
    normalized = normalize_text(text)

    # Prefer longer phrases first, like "מגן מסך" before "מגן"
    sorted_types = sorted(
        PRODUCT_TYPE_SYNONYMS.items(),
        key=lambda item: max(len(term) for term in item[1]["terms"]),
        reverse=True,
    )

    for product_type, config in sorted_types:
        if contains_any(normalized, config["terms"]):
            return product_type

    return None


def get_product_type_terms(product_type: str) -> set[str]:
    if not product_type:
        return set()

    return {
        normalize_text(term)
        for term in PRODUCT_TYPE_SYNONYMS[product_type]["terms"]
    }


def remove_product_type_terms(tokens: list[str], product_type: str | None) -> list[str]:
    if not product_type:
        return tokens

    product_terms = get_product_type_terms(product_type)

    return [
        token
        for token in tokens
        if token not in product_terms]


def get_keyword_tokens(keyword: str) -> list[str]:
    return [
        token.strip()
        for token in normalize_text(keyword).split()
        if len(token.strip()) >= 2
    ]


def is_relevant_product(product, base_keyword: str, keyword: str) -> bool:
    """
    Generic relevance filter.
    No hardcoded keyword mappings.
    It only checks if the user's keyword words appear in the product title/category/shop.
    """
    title = normalize_text(getattr(product, "title", ""))
    category = normalize_text(getattr(product, "category", ""))
    shop_name = normalize_text(getattr(product, "shop_name", ""))

    searchable_text = f"{title} {category} {shop_name}"

    tokens = get_keyword_tokens(keyword)

    if not tokens:
        return False

    matched_tokens = [
        token
        for token in tokens
        if token in searchable_text
    ]

    if len(tokens) == 1:
        return len(matched_tokens) == 1

    required_matches = max(1, round(len(tokens) * 0.5))

    return len(matched_tokens) >= required_matches


def keyword_tokens(keyword: str) -> list[str]:
    tokens = []

    for token in normalize_text(keyword).split():
        token = token.strip()

        if len(token) >= 2:
            tokens.append(token)

    return tokens


SEARCH_SYNONYMS = {
    "מצלמת אבטחה": [
        "מצלמת אבטחה",
        "מצלמה אבטחה",
        "security camera",
        "surveillance camera",
        "ip camera",
        "wifi camera",
        "cctv",
        "camera",
        "מצלמה",
    ],
    "מצלמה": [
        "camera",
        "מצלמה",
        "ip camera",
        "wifi camera",
    ],
}


def is_relevant_product(product: Any, keyword: str) -> bool:
    title = normalize_text(getattr(product, "title", ""))
    category = normalize_text(getattr(product, "category", ""))
    shop_name = normalize_text(getattr(product, "shop_name", ""))

    searchable_text = f"{title} {category} {shop_name}".strip()
    raw_keyword = normalize_text(keyword)

    if not raw_keyword or not searchable_text:
        return False

    keyword_product_type = detect_product_type(raw_keyword)
    title_product_type = detect_product_type(searchable_text)

    keyword_all_tokens = keyword_tokens(keyword)
    keyword_context_tokens = remove_product_type_terms(
        keyword_all_tokens,
        keyword_product_type
    )

    # 1. If both sides have known product types, they must match.
    if keyword_product_type and title_product_type:
        if keyword_product_type != title_product_type:
            return False

        # Product type matches.
        # Now check context/object tokens when available.
        if keyword_context_tokens:
            matched_context = [
                token for token in keyword_context_tokens
                if text_contains_term(searchable_text, token)
            ]

            # Require at least one context token.
            # Example:
            # keyword: "מעמד לטלפון"
            # title: "מעמד למחשב"
            # This should probably be false.
            return len(matched_context) >= 1

        return True

    # 2. If keyword has known product type but title does not,
    # require product type terms to appear in title.
    if keyword_product_type:
        config = PRODUCT_TYPE_SYNONYMS[keyword_product_type]

        if contains_any(searchable_text, config["conflicts"]):
            return False

        if not contains_any(searchable_text, config["terms"]):
            return False

        if keyword_context_tokens:
            matched_context = [
                token for token in keyword_context_tokens
                if text_contains_term(searchable_text, token)
            ]
            return len(matched_context) >= 1

        return True

    # 3. Direct phrase match for unknown product types.
    if raw_keyword in searchable_text:
        return True

    # 4. Synonym match if you already have SEARCH_SYNONYMS.
    synonyms = SEARCH_SYNONYMS.get(keyword.strip(), [])

    for synonym in synonyms:
        if normalize_text(synonym) in searchable_text:
            return True

    # 5. Strict token fallback.
    if not keyword_all_tokens:
        return False

    matched_tokens = [
        token for token in keyword_all_tokens
        if text_contains_term(searchable_text, token)
    ]

    if len(keyword_all_tokens) == 1:
        return len(matched_tokens) == 1

    return len(matched_tokens) == len(keyword_all_tokens)


def parse_discount_percent(value) -> int:
    if value is None:
        return 0

    try:
        return int(float(str(value).replace("%", "").strip()))
    except Exception:
        return 0


def enqueue_scan_for_user(
        *,
        user_id: int,
        chat_id: int,
        username: str | None,
        message_text: str,
        product_url: str,
) -> tuple[int, int, int]:
    priority_users = get_priority_user_ids()
    priority = 10 if user_id in priority_users else 0

    request_id, position = enqueue_request(
        user_id=user_id,
        chat_id=chat_id,
        username=username,
        message_text=message_text,
        product_url=product_url,
        priority=priority,
    )

    return request_id, position, priority


def validate_env() -> None:
    global TELEGRAM_BOT_TOKEN

    load_dotenv()

    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN")


def init_db() -> None:
    init_queue_db()


def get_priority_user_ids() -> set[int]:
    raw = os.getenv("PRIORITY_USER_IDS", "").strip()
    if not raw:
        return set()

    ids = set()
    for item in raw.split(","):
        item = item.strip()
        if item.isdigit():
            ids.add(int(item))

    return ids


async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    user = update.effective_user
    chat = update.effective_chat

    if not user or not chat:
        return

    raw_text = " ".join(context.args).strip()

    if not raw_text:
        await update.message.reply_text(
            "שלחו כך:\n/scan <AliExpress product link>"
        )
        return

    product_url = extract_aliexpress_url(raw_text)

    if not product_url:
        await update.message.reply_text(
            "לא מצאתי קישור תקין למוצר מ-AliExpress."
        )
        return

    request_id, position, priority = enqueue_scan_for_user(
        user_id=user.id,
        chat_id=chat.id,
        username=user.username,
        message_text=f"/scan {product_url}",
        product_url=product_url,
    )

    priority_text = "\nקיבלתם עדיפות בתור ⭐" if priority > 0 else ""

    await update.message.reply_text(
        (
            f"✅ קיבלתי את הבקשה.\n"
            f"אתם מספר <b>{position}</b> בתור.\n"
            f"אני אנתח את המוצר ואחזיר תשובה בקרוב."
            f"{priority_text}"
        ),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


def check_related_with_ollama(first: str, category: str, product_title: str) -> dict:
    prompt = f"""
You are an AI agent checking whether an AliExpress product matches a user search keyword.

You will receive:
- First: the original keyword/search phrase used to search products.
- Product Title: the actual product title returned from AliExpress.
- Product Category: the first-level category returned from AliExpress.

Your task:
Decide if the Product Title + Product Category are related to the original search keyword.

Important:
- The keyword may be broad, such as "PC Gadgets", "LED Light", "Gaming Accessories", or "Phone Accessories".
- Use both the product title and category together.
- Product Title is usually more important than Product Category.
- Category alone is not enough if the product title clearly does not match.
- If the title clearly matches the searched keyword, mark it related even if the category is broad.
- If the category sounds related but the product title is about something else, mark it not_related or maybe_related.
- Do not mark products as related only because they are general consumer products.

Decision rules:
- "related": the product clearly matches the search keyword, is a subcategory, or is commonly used with it.
- "maybe_related": the product could match depending on usage/context, but the connection is not clear enough.
- "not_related": the product does not match the search keyword or belongs to a different shopping intent.

Sub-result options:
- "same_category"
- "specific_item_in_category"
- "compatible_use"
- "compatible_categories"
- "broad_category"
- "different_category"
- "ambiguous"
- "ambiguous_word"
- "ambiguous_word_resolved"
- "title_matches_keyword"
- "title_conflicts_with_category"
- "category_too_broad"

Examples:
First: "PC Gadgets" Product Title: "USB 3.0 Hub Splitter for Laptop PC" Product Category: "Computer Accessories" result: "related" sub_result: "specific_item_in_category"
First: "PC Gadgets" Product Title: "Wireless Gaming Mouse RGB Rechargeable" Product Category: "Computer Accessories" result: "related" sub_result: "specific_item_in_category"
First: "PC Gadgets" Product Title: "Phone Case for iPhone 15 Pro Max" Product Category: "Phone Accessories" result: "not_related" sub_result: "different_category"
First: "PC Gadgets" Product Title: "USB Hub Type-C Adapter for MacBook Laptop" Product Category: "Consumer Electronics" result: "related" sub_result: "compatible_use"
First: "PC Gadgets" Product Title: "RGB Gaming Keyboard Wrist Rest Pad" Product Category: "Gaming Accessories" result: "related" sub_result: "compatible_categories"
First: "PC Gadgets" Product Title: "Kitchen Garlic Press Stainless Steel" Product Category: "Home & Garden" result: "not_related" sub_result: "different_category"
First: "PC Gadgets" Product Title: "Cable Organizer Clips for Desk Setup" Product Category: "Office Accessories" result: "maybe_related" sub_result: "compatible_use"

First: "LED Light" Product Title: "USB LED Strip Light for TV Backlight" Product Category: "Home Accessories" result: "related" sub_result: "title_matches_keyword"
First: "LED Light" Product Title: "LED Desk Lamp with Touch Control" Product Category: "Lighting" result: "related" sub_result: "specific_item_in_category"
First: "LED Light" Product Title: "Car Interior LED Ambient Light Strip" Product Category: "Automotive" result: "maybe_related" sub_result: "compatible_use"
First: "LED Light" Product Title: "Phone Case with Glitter Design" Product Category: "Phone Accessories" result: "not_related" sub_result: "different_category"

First: "Mouse" Product Title: "Wireless Mouse 2.4GHz for Laptop" Product Category: "Computer Accessories" result: "related" sub_result: "ambiguous_word_resolved"
First: "Mouse" Product Title: "Cat Toy Fake Mouse Plush" Product Category: "Pet Accessories" result: "not_related" sub_result: "ambiguous_word"
First: "Mouse" Product Title: "Gaming Mouse Pad XXL RGB" Product Category: "Computer Accessories" result: "related" sub_result: "compatible_use"

First: "Phone Accessories" Product Title: "USB-C Fast Charging Cable for Samsung Xiaomi" Product Category: "Phone Accessories" result: "related" sub_result: "specific_item_in_category"
First: "Phone Accessories" Product Title: "Laptop Cooling Stand with Fan" Product Category: "Computer Accessories" result: "not_related" sub_result: "different_category"
First: "Phone Accessories" Product Title: "Bluetooth Earbuds Wireless Headphones" Product Category: "Consumer Electronics" result: "maybe_related" sub_result: "compatible_use"

Return ONLY valid JSON.
Do not explain.
Do not use markdown.
Do not add extra text.

Return ONLY valid JSON in this exact structure:
{{
  "first": "{first}",
  "second": "{product_title}",
  "result": "Choose ONLY one from: related | maybe_related | not_related",
  "sub_result": "short reason category"
}}

Input:
First: {first}
product title: {product_title}
second: {category}

""".strip()

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0,
            "num_predict": 120,
        },
    }

    response = requests.post(OLLAMA_URL, json=payload, timeout=120)

    if response.status_code != 200:
        raise RuntimeError(
            f"Ollama error. Status={response.status_code}, Body={response.text[:1000]}"
        )

    raw_model_response = response.json().get("response", "").strip()

    try:
        return json.loads(raw_model_response)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Ollama returned invalid JSON:\n{raw_model_response}"
        ) from e


async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    user = update.effective_user

    if not user:
        return

    keyword = " ".join(context.args).strip()

    if not keyword:
        await update.message.reply_text(
            "שלחו כך:\n/search <keyword>\n\nלדוגמה:\n/search מצלמת אבטחה"
        )
        return

    await update.message.reply_text(
        f"🔎 מחפש מוצרים עבור: <b>{escape(keyword)}</b>",
        parse_mode=ParseMode.HTML,
    )

    settings = Settings()
    client = AliExpressClient(settings)

    try:
        products = await client.search_products(
            keyword=keyword,
            limit=50,
        )
    except Exception as exc:
        print(f"AliExpress search failed: {exc}")
        await update.message.reply_text(
            "לא הצלחתי לחפש כרגע מוצרים באלי אקספרס. נסו שוב עוד מעט."
        )
        return

    min_orders = int(os.getenv("SEARCH_MIN_ORDERS", "50"))
    min_discount = int(os.getenv("SEARCH_MIN_DISCOUNT_PERCENT", "10"))
    max_results = int(os.getenv("SEARCH_MAX_RESULTS", "5"))

    filtered_products = []

    for product in products:
        orders = int(product.orders or 0)
        discount_percent = parse_discount_percent(product.discount)
        affiliate_url = product.affiliate_url or product.product_url
        category = normalize_text(getattr(product, "category", ""))

        if not affiliate_url:
            continue

        if not is_relevant_product(product, keyword):
            print(f"Skipping irrelevant product for '{keyword}': {product.title}")
            continue

        if orders < min_orders:
            continue

        if discount_percent < min_discount:
            continue

        filtered_products.append(
            {
                "product": product,
                "orders": orders,
                "discount_percent": discount_percent,
                "affiliate_url": affiliate_url,
            }
        )

    def product_search_score(item: dict) -> float:
        product = item["product"]

        orders = item["orders"]
        discount = item["discount_percent"]
        rating = float(product.rating or 0)

        score = 0.0

        if orders >= 10000:
            score += 40
        elif orders >= 5000:
            score += 30
        elif orders >= 1000:
            score += 20
        elif orders >= 100:
            score += 10
        elif orders >= 50:
            score += 5

        score += min(discount, 60) * 0.5

        if rating >= 4.8:
            score += 20
        elif rating >= 4.5:
            score += 12
        elif rating >= 4.0:
            score += 5

        return score

    filtered_products.sort(
        key=product_search_score,
        reverse=True,
    )

    top_products = filtered_products[:max_results]

    if not top_products:
        det_key = detect(keyword)
        if det_key == "he":
            en_keyword = translate_hebrew_to_english(keyword)
            try:
                products = await client.search_products(
                    keyword=en_keyword,
                    limit=50,
                )
            except Exception as exc:
                print(f"AliExpress search failed: {exc}")
                await update.message.reply_text(
                    "לא הצלחתי לחפש כרגע מוצרים באלי אקספרס. נסו שוב עוד מעט."
                )
                return

            filtered_products = []

            for product in products:
                orders = int(product.orders or 0)
                discount_percent = parse_discount_percent(product.discount)
                affiliate_url = product.affiliate_url or product.product_url

                if not affiliate_url:
                    continue

                if not is_relevant_product(product, en_keyword):
                    print(f"Skipping irrelevant product for '{keyword}': {product.title}")
                    continue

                if orders < min_orders:
                    continue

                if discount_percent < min_discount:
                    continue

                filtered_products.append(
                    {
                        "product": product,
                        "orders": orders,
                        "discount_percent": discount_percent,
                        "affiliate_url": affiliate_url,
                    }
                )
            filtered_products.sort(
                key=product_search_score,
                reverse=True,
            )
            top_products = filtered_products[:max_results]
            if not top_products:
                await update.message.reply_text(
                    (
                        "לא מצאתי כרגע מוצרים מספיק קשורים וחזקים לפי החיפוש הזה.\n\n"
                        f"מילת חיפוש: <b>{escape(en_keyword)}</b>\n"
                        f"הזמנות מינימום: <b>{min_orders}</b>\n"
                        f"הנחה מינימום: <b>{min_discount}%</b>\n\n"
                        "נסו מילת חיפוש אחרת או כללית יותר."
                    ),
                    parse_mode=ParseMode.HTML,
                )
                return
        else:
            await update.message.reply_text(
                (
                    "לא מצאתי כרגע מוצרים מספיק קשורים וחזקים לפי החיפוש הזה.\n\n"
                    f"מילת חיפוש: <b>{escape(keyword)}</b>\n"
                    f"הזמנות מינימום: <b>{min_orders}</b>\n"
                    f"הנחה מינימום: <b>{min_discount}%</b>\n\n"
                    "נסו מילת חיפוש אחרת או כללית יותר."
                ),
                parse_mode=ParseMode.HTML,
            )
            return

    search_cache = context.bot_data.setdefault("search_results", {})

    text_parts = [
        "מצאתי כמה מוצרים חזקים לפי כמות הזמנות והנחה.\n",
        "אתם יכולים להיכנס למוצרים ולבדוק בעצמכם,",
        "או ללחוץ על הכפתור של המוצר הכי קרוב כדי לקבל AI Review.\n",
    ]

    keyboard = []

    for index, item in enumerate(top_products, start=1):
        product = item["product"]
        orders = item["orders"]
        discount_percent = item["discount_percent"]
        affiliate_url = item["affiliate_url"]

        title = product.title or "AliExpress Product"
        short_title = title[:80] + "..." if len(title) > 80 else title

        if product.price_ils:
            price_text = f"₪{product.price_ils:.2f}"
        elif product.price_usd:
            price_text = f"${product.price_usd:.2f}"
        else:
            price_text = "לא ידוע"

        rating_text = f"{product.rating}/5" if product.rating else "לא ידוע"
        shop_text = product.shop_name or "לא ידוע"

        cache_key = f"{user.id}:{index}"
        search_cache[cache_key] = affiliate_url

        text_parts.append(
            (
                f"<b>{index}. {escape(short_title)}</b>\n"
                f"מחיר: <b>{escape(price_text)}</b>\n"
                f"הזמנות: <b>{orders:,}</b>\n"
                f"הנחה: <b>{discount_percent}%</b>\n"
                f"דירוג: <b>{escape(rating_text)}</b>\n"
                f"חנות: <b>{escape(shop_text)}</b>\n"
            )
        )

        keyboard.append(
            [
                InlineKeyboardButton(
                    text=f"🔗 לפתוח מוצר {index}",
                    url=affiliate_url,
                )
            ]
        )

        keyboard.append(
            [
                InlineKeyboardButton(
                    text=f"🤖 AI Review למוצר {index}",
                    callback_data=f"scan_search:{cache_key}",
                )
            ]
        )

    await update.message.reply_text(
        "\n".join(text_parts),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True,
    )


async def handle_search_scan_button(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
) -> None:
    query = update.callback_query

    if not query:
        return

    await query.answer()

    user = query.from_user
    message = query.message

    if not message:
        return

    data = query.data or ""

    if not data.startswith("scan_search:"):
        return

    cache_key = data.replace("scan_search:", "", 1)

    search_cache = context.bot_data.get("search_results", {})
    affiliate_url = search_cache.get(cache_key)

    if not affiliate_url:
        await message.reply_text(
            "הקישור כבר לא זמין בזיכרון של הבוט. נסו להריץ /search שוב."
        )
        return

    request_id, position, priority = enqueue_scan_for_user(
        user_id=user.id,
        chat_id=message.chat.id,
        username=user.username,
        message_text=f"/scan {affiliate_url}",
        product_url=affiliate_url,
    )

    priority_text = "\nקיבלתם עדיפות בתור ⭐" if priority > 0 else ""

    await message.reply_text(
        (
            f"✅ קיבלתי את הבקשה ל-AI Review.\n"
            f"אתם מספר <b>{position}</b> בתור.\n"
            f"אני אנתח את המוצר ואחזיר תשובה בקרוב."
            f"{priority_text}"
        ),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    await update.message.reply_text(
        "שלחו לי לינק למוצר מ-AliExpress ואני אנתח אם שווה לקנות אותו 👇"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    message = update.message
    text = message.text or ""

    user = update.effective_user
    chat = update.effective_chat

    if not user or not chat:
        return

    product_url = extract_aliexpress_url(text)

    print("Incoming text:", text)
    print("Extracted product_url:", product_url)

    if not product_url:
        await message.reply_text(
            "שלחו לי קישור למוצר מ-AliExpress ואבדוק אם הוא דיל טוב."
        )
        return

    request_id, position, priority = enqueue_scan_for_user(
        user_id=user.id,
        chat_id=chat.id,
        username=user.username,
        message_text=text,
        product_url=product_url,
    )

    priority_text = "\nקיבלתם עדיפות בתור ⭐" if priority > 0 else ""

    await message.reply_text(
        (
            f"✅ קיבלתי את הבקשה.\n"
            f"אתם מספר <b>{position}</b> בתור.\n"
            f"אני אנתח את המוצר ואחזיר תשובה בקרוב."
            f"{priority_text}"
        ),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


def main() -> None:
    validate_env()
    init_db()

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("scan", cmd_scan))
    app.add_handler(CommandHandler("search", new_cmd_search))

    app.add_handler(
        CallbackQueryHandler(
            handle_search_scan_button,
            pattern=r"^scan_search:",
        )
    )

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot is running.")
    print("Send /start to the bot.")
    print("Send /scan <AliExpress link> to scan one product.")
    print("Send /search <keyword> to search AliExpress products.")
    print("Send a regular AliExpress product link to enqueue it.")

    app.run_polling()


if __name__ == "__main__":
    main()
