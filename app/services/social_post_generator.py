import json
import re
from typing import Any

from app.services.social_media_picker import get_value, pick_best_image, pick_best_video


def safe_json_loads(text: str) -> dict:
    import json
    import re

    if not text or not text.strip():
        raise ValueError("Model returned empty text")

    cleaned = text.strip()

    # Remove markdown fences if model uses them.
    cleaned = cleaned.replace("```json", "").replace("```", "").strip()

    # First try direct JSON.
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Then try extracting JSON object.
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise ValueError(f"Model did not return JSON. Raw text: {text[:1000]}")

    return json.loads(match.group(0))


def build_product_payload(product: Any) -> dict:
    return {
        "product_id": str(
            get_value(product, "product_id")
            or get_value(product, "item_id")
            or get_value(product, "id")
        ),
        "title": get_value(product, "product_title") or get_value(product, "title"),
        "price": get_value(product, "target_sale_price") or get_value(product, "sale_price"),
        "currency": "ILS",
        "rating": get_value(product, "evaluate_rate") or get_value(product, "rating"),
        "orders": get_value(product, "orders") or get_value(product, "volume"),
        "category": get_value(product, "category_name") or get_value(product, "category"),
        "commission_rate": get_value(product, "commission_rate"),
        "product_url": get_value(product, "product_detail_url"),
        "affiliate_url": get_value(product, "promotion_link") or get_value(product, "affiliate_url"),
        "image_url": pick_best_image(product),
        "video_url": pick_best_video(product),
    }


async def generate_social_post(ollama_client, product: Any, media_type: str) -> dict:
    payload = build_product_payload(product)

    product_id = str(payload.get("product_id") or "")
    forced_product_code = f"TD{product_id[-5:]}" if product_id else "TD00000"

    prompt = f"""
    You a Senior media content creator specialist.
    You are working for the Telegram Channel Top Deals Israel who is one of most up coming channels for ali express deals
    
    Post instructions:
    You will receive a product and need to create a social media post for it, to publish in on Instagram showing our followers
    the good deals we provide.
    
    The post needs to be in hebrew only and needs to be devided into the following flow:
    1. Punch line - A short line in hebrew pulling people to the channel, 
        For example: 1. עוד דיל מצויין שמצאנו, אל תפספסו.
                     2. אם לא היינו משתמשים ב AI כנראה שהיינו מספםפסים את זה.
                     3. מסוג הדברים שחיוש ידני לא תמיד רואה
    2. product summary based on the product data section
    3. Post ending:
     לדילים נוספים הצטרפו לערוץ שלנו https://t.me/Top_deals_israel
     מצאתם דיל ולא בטוחים אם הוא באמת שווה? תשלחו הודעה ל- @Top_Deals_Israel_Bot
     זה בחינם ;) 
     
    Product data:
    {json.dumps(payload, ensure_ascii=False)}

    Use this exact product code:
    {forced_product_code}

    Return exactly this shape, filled with real values:
    {{
      "score": 75,
      "should_publish": true,
      "reason": "הסבר קצר בעברית",
      "short_title_he": "שם מוצר קצר בעברית",
      "caption_he": " טקסט פוסט בעברית טבעית עד 700 תווים לפי ההוראות שניתנו",
      "category": "קטגוריה קצרה בעברית",
    }}
    
         
    Return ONLY a JSON object.
    The JSON object MUST include all required keys.
    Do not return an empty object.
    Do not return only product_code.
    Do not use markdown.
    
    Caption rules:
    - Natural Israeli Hebrew.
    - Never write: הלוואי
    - Never write: 댓
    - Do not invent specs.
    - Do not mention low orders as a positive thing.
    - End with: רוצים קישור? כתבו בתגובה את הקוד: {forced_product_code}
    - Don't translate directl to hebrew, recreate the post in hebrew.
    - Use only the information available.
    - Separate facts from assumptions
    - Everything scored over 85 is a great deal , over 95 is incredible and shouldn't be missed.
    """

    result = await ollama_client.generate(prompt)

    print(f"[OLLAMA RAW RESULT] {result[:1500]}")

    data = safe_json_loads(result)

    if not data or list(data.keys()) == ["product_code"]:
        print("[SOCIAL DEBUG] model returned empty/invalid JSON, retrying once")

        retry_prompt = prompt + """

    IMPORTANT:
    Your previous answer was invalid.
    Return a FULL JSON object with score, should_publish, reason, short_title_he, caption_he, and category.
    Do not return {}.
    """

        result = await ollama_client.generate(retry_prompt)
        print(f"[OLLAMA RAW RETRY RESULT] {result[:1500]}")
        data = safe_json_loads(result)

    product_id = str(payload.get("product_id") or "")
    product_code = f"TD{product_id[-5:]}" if product_id else "TD00000"
    data["product_code"] = product_code

    required_keys = [
        "score",
        "should_publish",
        "reason",
        "short_title_he",
        "caption_he",
        "category",
    ]

    missing_keys = [key for key in required_keys if key not in data]

    if missing_keys:
        raise ValueError(
            f"Model JSON missing required keys: {missing_keys}. "
            f"Returned JSON: {data}"
        )

    product_id = str(payload.get("product_id") or "")
    product_code = f"TD{product_id[-5:]}" if product_id else "TD00000"
    data["product_code"] = product_code
    data["media_type"] = media_type
    data["image_url"] = payload.get("image_url")
    data["video_url"] = payload.get("video_url")
    data["product_url"] = payload.get("product_url")
    data["affiliate_url"] = payload.get("affiliate_url")
    data["product_id"] = payload.get("product_id")
    data["raw_product"] = payload
    caption = data.get("caption_he", "")

    bad_terms = ["הלוואי", "댓", "דאט", "קודד"]
    for term in bad_terms:
        caption = caption.replace(term, "")

    caption = caption.replace("  ", " ").strip()
    data["caption_he"] = caption

    return data