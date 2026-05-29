# -*- coding: utf-8 -*-
import os
from dotenv import load_dotenv
import requests
from iop.base import IopRequest, IopClient, IopResponse
from deep_translator import GoogleTranslator

import json
import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:1.5b"
# Set env variables


load_dotenv()
appkey = os.getenv("ALIEXPRESS_APP_KEY")
appSecret = os.getenv("ALIEXPRESS_APP_SECRET")
from langdetect import detect

url = "https://api-sg.aliexpress.com/sync"
keyword = 'technology superdeals'

# Pull product info based on Key word
client = IopClient(url, appkey, appSecret)
request = IopRequest('aliexpress.affiliate.hotproduct.query')
request.add_api_param('target_currency', 'ILS')
request.add_api_param('ship_to_country', 'IL')
request.add_api_param('min_sale_price', '1500')
request.add_api_param('max_sale_pricemax_sale_price', '25000')
request.add_api_param('sort', 'LAST_VOLUME_DESC')
request.add_api_param('platform_product_type', 'ALL')
request.add_api_param('target_language', 'HE')
request.add_api_param('page_size', '50')
request.add_api_param('page_no', '1')
request.add_api_param('keywords', 'gaming OR rgb OR headset OR mechanical keyboard OR security camera OR earbuds')
request.add_api_param('fields', "product_title,product_main_image_url,sale_price,original_price,evaluate_rate,last_volume_us_30d,commission_rate")
response = client.execute(request)
print(response.type)


def check_related_with_ollama(first: str, category: str, product_title: str) -> dict:
    if detect(first) == 'he':
        print('he')
        first = GoogleTranslator(source='iw', target='en').translate(first)

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


def check_should_with_ollama(first: str) -> dict:
    if detect(first) == 'he':
        print('he')
        first = GoogleTranslator(source='iw', target='en').translate(first)

    prompt = prompt = f"""
You are an expert category analyst for a Cybersecurity, Gaming & High-Tech influencer.
Your boss only posts AliExpress bestsellers and super deals that appeal to gamers, cybersecurity pros, tech enthusiasts, and gadget lovers (electronics, computers, phones, smart devices, accessories, components, security products, etc.).

Task:
Analyze the category name and decide if it's worth posting about.

Be decisive. Do not default to "maybe".

Decision Rules:
- "should" → Clear relevance to tech, gaming, cybersecurity, electronics, gadgets, phone/computer accessories, smart home, PC components, networking, security devices, etc.
- "maybe"  → Vague, promotional, or mixed category that *might* contain relevant items but is not clearly tech-focused.
- "dont"   → No meaningful connection to tech/gaming/cyber (clothing, beauty, general toys, home goods, cars, pets, etc.).

Sub-result options (choose the best one):
- "exact_match"
- "related"
- "close_enough"
- "specific_item_in_category"
- "compatible_use"
- "compatible_categories"
- "different_category"
- "ambiguous"
- "ambiguous_word"
- "ambiguous_word_resolved"
- "title_matches_keyword"
- "title_conflicts_with_category"
- "not_related"
- "promotional_event"

Examples:
- "ConsumerElectronics" → "should", "exact_match"
- "AEB_ ComputerAccessories_EG" → "should", "exact_match"
- "AEB_ PhoneAccessories_EG" → "should", "exact_match"
- "Security topsellers" → "should", "related"
- "PhoneAccessories" → "should", "specific_item_in_category"
- "AEB_ SummerProducts_EG" → "maybe", "specific_item_in_category"
- "DS_Automobile&Accessories_bestsellers" → "dont", "not_related"
- "AEB_SHOPLAZZA_MenClothing" → "dont", "not_related"
- "0518-0522 Sunshine Savings - Bestsellers" → "maybe", "promotional_event"
- "0203-Knasta-202602-PE" → "maybe", "ambiguous"

Return ONLY valid JSON. No explanations, no markdown, no extra text.

{{
  "category": "{first}",
  "result": "should | maybe | dont",
  "sub_result": "one_of_the_options_above"
}}
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


"""
 NEED TO FIX
 Check Should with Ollama
 The code should find posts to publish on instagram.

++++++++++++++++++++++++++++++++++++++++++++
++++++++++++++++++++++++++++++++++++++++++++
++++++++++++++++++++++++++++++++++++++++++++
++++++++++++++++++++++++++++++++++++++++++++

"""
promos = response.body['aliexpress_affiliate_hotproduct_query_response']['resp_result']["result"]

related_list = []
related_category = []
print("=-=-=--="*100)
for promo in promos["products"]["product"]:
    print(promo)
    """ver = check_should_with_ollama(promo["promo_name"])
    print(ver)
    if len(related_category) >= 5:
        break
    if ver['result'] == "should":
        related_category.append(ver["category"])"""

[print(i) for i in related_list]
[print(i) for i in related_category]

# Pull product info based on Key word
client = IopClient(url, appkey, appSecret)
request = IopRequest('aliexpress.affiliate.featuredpromo.products.get')
request.add_api_param('target_currency', 'ILS')
request.add_api_param('country', 'IL')
request.add_api_param('min_sale_price', '15')
request.add_api_param('sort', 'ratingDesc,volumeDesc')
request.add_api_param('promotion_name', 'DS_ConsumerElectronics_bestsellers')
response = client.execute(request)

"""
print(response.type)

print(response.body['aliexpress_affiliate_featuredpromo_products_get_response']['resp_result']["result"])
"""
