import json
import re
from typing import Any
from app.services.review_sentiment import get_review_sentiment_for_product, set_product_value
import httpx
import asyncio
from urllib import request


def _hebrew_copy_from_intent(self, product_type: str, main_use: str, audience: str) -> tuple[str, str]:
    templates = {
        "car_vacuum": (
            "שואב אבק קומפקטי לניקוי מהיר ונוח ברכב.",
            "דיל חזק אם חיפשתם פתרון קטן לניקיון ברכב.",
        ),
        "charger": (
            "מטען קומפקטי ושימושי לבית, לעבודה ולנסיעות.",
            "שווה בדיקה אם אתם צריכים מטען נוסף.",
        ),
        "power_bank": (
            "סוללת גיבוי ניידת לשימוש יומיומי ונסיעות.",
            "בחירה טובה למי שנמצא הרבה מחוץ לבית.",
        ),
        "smart_home_sensor": (
            "חיישן שימושי לאוטומציות וניהול בית חכם.",
            "מתאים למי שבונה מערכת בית חכם.",
        ),
        "storage_organizer": (
            "פתרון פשוט ונוח לאחסון וארגון בבית.",
            "שווה בדיקה אם חיפשתם דרך קלה לעשות סדר.",
        ),
        "headphones": (
            "אוזניות אלחוטיות לשימוש יומיומי, ספורט ונסיעות.",
            "דיל נחמד אם אתם צריכים אוזניות נוספות.",
        ),
        "car_accessory": (
            "אביזר שימושי לרכב לשדרוג קטן ביום־יום.",
            "שווה בדיקה אם אתם אוהבים גאדג׳טים לרכב.",
        ),
        "kitchen_tool": (
            "כלי שימושי למטבח שיכול לחסוך זמן והתעסקות.",
            "דיל נחמד למי שאוהב פתרונות קטנים למטבח.",
        ),
        "toy": (
            "צעצוע נחמד לילדים במחיר משתלם.",
            "שווה בדיקה אם חיפשתם משהו קטן לילדים.",
        ),
    }

    return templates.get(
        product_type,
        (
            "מוצר שימושי עם דירוג טוב וכמות הזמנות יפה.",
            "שווה בדיקה אם זה משהו שחיפשתם.",
        ),
    )


class OllamaClient:
    def __init__(self, settings):
        self.settings = settings
        self.base_url = settings.ollama_base_url.rstrip("/")
        self.model = settings.ollama_model

    def _hebrew_copy_from_intent(self, product_type: str, main_use: str, audience: str) -> tuple[str, str]:
        templates = {
            "car_vacuum": (
                "שואב אבק קומפקטי לניקוי מהיר ונוח ברכב.",
                "דיל חזק אם חיפשתם פתרון קטן לניקיון ברכב.",
            ),
            "charger": (
                "מטען קומפקטי ושימושי לבית, לעבודה ולנסיעות.",
                "שווה בדיקה אם אתם צריכים מטען נוסף.",
            ),
            "power_bank": (
                "סוללת גיבוי ניידת לשימוש יומיומי ונסיעות.",
                "בחירה טובה למי שנמצא הרבה מחוץ לבית.",
            ),
            "smart_home_sensor": (
                "חיישן שימושי לאוטומציות וניהול בית חכם.",
                "מתאים למי שבונה מערכת בית חכם.",
            ),
            "storage_organizer": (
                "פתרון פשוט ונוח לאחסון וארגון בבית.",
                "שווה בדיקה אם חיפשתם דרך קלה לעשות סדר.",
            ),
            "headphones": (
                "אוזניות אלחוטיות לשימוש יומיומי, ספורט ונסיעות.",
                "דיל נחמד אם אתם צריכים אוזניות נוספות.",
            ),
            "car_accessory": (
                "אביזר שימושי לרכב לשדרוג קטן ביום־יום.",
                "שווה בדיקה אם אתם אוהבים גאדג׳טים לרכב.",
            ),
            "kitchen_tool": (
                "כלי שימושי למטבח שיכול לחסוך זמן והתעסקות.",
                "דיל נחמד למי שאוהב פתרונות קטנים למטבח.",
            ),
            "toy": (
                "צעצוע נחמד לילדים במחיר משתלם.",
                "שווה בדיקה אם חיפשתם משהו קטן לילדים.",
            ),
        }

        return templates.get(
            product_type,
            (
                "מוצר שימושי עם דירוג טוב וכמות הזמנות יפה.",
                "שווה בדיקה אם זה משהו שחיפשתם.",
            ),
        )

    async def generate(self, prompt: str, model: str | None = None) -> str:
        """
        Generic Ollama text generation method.
        Used by the social post generator.
        """

        import asyncio
        import json
        from urllib import request, error

        selected_model = (
                model
                or getattr(self.settings, "social_model", None)
                or getattr(self.settings, "ollama_model", None)
                or "qwen3:14b"
        )

        ollama_host = (
                getattr(self.settings, "ollama_host", None)
                or getattr(self.settings, "ollama_base_url", None)
                or "http://localhost:11434"
        ).rstrip("/")

        payload = {
            "model": selected_model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.2,
                "num_ctx": 3072,
                "num_predict": 700,
            },
        }

        def _call_ollama() -> str:
            req = request.Request(
                url=f"{ollama_host}/api/generate",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            try:
                with request.urlopen(req, timeout=600) as response:
                    raw_body = response.read().decode("utf-8")

                if not raw_body.strip():
                    raise RuntimeError("Ollama returned an empty HTTP response body")

                data = json.loads(raw_body)

                generated_text = data.get("response", "")

                if not generated_text.strip():
                    raise RuntimeError(
                        f"Ollama returned empty response text. Full response: {raw_body[:1000]}"
                    )

                return generated_text

            except error.HTTPError as e:
                body = e.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"Ollama HTTP error {e.code}: {body}") from e

            except error.URLError as e:
                raise RuntimeError(f"Could not connect to Ollama at {ollama_host}: {e}") from e

        return await asyncio.to_thread(_call_ollama)

    async def enrich_product(self, product) -> dict[str, Any]:
        """
        Returns AI-generated product enrichment:
        - short_description
        - tags
        - deal_score
        - deal_label
        - buy_verdict
        """

        if not getattr(self.settings, "use_ollama", False):
            return self._fallback_enrichment(product)

        prompt = self._build_prompt(product)

        try:
            async with httpx.AsyncClient(timeout=90) as client:
                response = await client.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {
                            "temperature": 0.1,
                            "top_p": 0.8,
                            "num_predict": 250,
                        },
                    },
                )

            response.raise_for_status()
            data = response.json()

            raw_text = data.get("response", "")
            parsed = self._parse_json(raw_text)

            return self._normalize_enrichment(parsed, product)

        except Exception as e:
            print(f"Ollama enrichment failed, using fallback. Error: {e}")
            return self._fallback_enrichment(product)

    def _build_prompt(self, product) -> str:
        price = getattr(product, "price_usd", None)
        original_price = getattr(product, "original_price_usd", None)
        rating = getattr(product, "rating", None)
        orders = getattr(product, "orders", None)
        shipping = getattr(product, "shipping", None)
        category = getattr(product, "category", None)

        discount_text = "unknown"
        if price and original_price and original_price > price:
            discount = round(((original_price - price) / original_price) * 100)
            discount_text = f"{discount}%"

        return f"""
        You are a deal analyst for an Israeli Telegram channel called Top Deals Israel.

        Analyze this AliExpress product and return ONLY valid JSON.

        Product:
        - Title: {product.title}
        - Category: {category}
        - Price USD: {price}
        - Original Price USD: {original_price}
        - Discount: {discount_text}
        - Rating: {rating}
        - Orders: {orders}
        - Shipping: {shipping}

        Your job:
        1. Write a short product description in Hebrew. Max 18 words.
        2. Create up to 5 product-related tags in English only.
        3. Write a short buy verdict in Hebrew. Max 18 words.
        4. Do not calculate the deal score. The system calculates it separately.
        5. Do not invent price, rating, orders, shipping, discount, or product features.

        Tag rules:
        - Tags must be English.
        - No spaces inside tags.
        - Do not include the # symbol.
        - Max 5 tags.

        Return this exact JSON structure:
        {{
          "short_description": "תיאור קצר בעברית",
          "tags": ["Tag1", "Tag2", "Tag3"],
          "buy_verdict": "המלצת קנייה קצרה בעברית"
        }}
        """.strip()

    def _parse_json(self, text: str) -> dict[str, Any]:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Fallback if the model wraps JSON in text/code fences
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError(f"No JSON object found in Ollama response: {text}")

        return json.loads(match.group(0))

    def _normalize_enrichment(self, parsed: dict[str, Any], product) -> dict[str, Any]:
        fallback = self._fallback_enrichment(product)

        product_type = parsed.get("product_type", "unknown")
        main_use = parsed.get("main_use", "unknown")
        audience = parsed.get("audience", "unknown")

        short_description, buy_verdict = self._hebrew_copy_from_intent(
            product_type=product_type,
            main_use=main_use,
            audience=audience,
        )

        tags = parsed.get("tags") or fallback["tags"]
        if not isinstance(tags, list):
            tags = fallback["tags"]

        clean_tags = []
        for tag in tags:
            tag = str(tag).strip()
            tag = tag.replace("#", "")
            tag = re.sub(r"[^a-zA-Z0-9_\-\s]", "", tag)
            tag = tag.replace(" ", "")
            if tag:
                clean_tags.append(tag)

        clean_tags = clean_tags[:5]

        deal_score = self._basic_score(product)
        deal_label = self._label_for_score(deal_score)

        return {
            "short_description": short_description[:160],
            "tags": clean_tags or fallback["tags"],
            "deal_score": deal_score,
            "deal_label": deal_label,
            "buy_verdict": buy_verdict[:180],
        }

    def _fallback_enrichment(self, product) -> dict[str, Any]:
        title = (product.title or "").lower()

        tags = ["AliExpressDeals", "Gadgets"]
        description = "Popular tech product with solid reviews and order volume."
        verdict = "Worth checking if the price matches your current need."

        if "charger" in title or "usb-c" in title or "gan" in title:
            tags = ["Charging", "USBC", "Gadgets", "Travel", "DeskSetup"]
            description = "Compact fast charger for phones, tablets, laptops, and travel."
            verdict = "Good buy if you need one charger for multiple devices."

        elif "power bank" in title:
            tags = ["PowerBank", "Charging", "Travel", "Gadgets", "Battery"]
            description = "Portable high-capacity charging for travel, work, and daily use."
            verdict = "Good pick if you often need backup power outside."

        elif "sensor" in title or "aqara" in title:
            tags = ["SmartHome", "Sensor", "Automation", "HomeKit", "Gadgets"]
            description = "Useful smart-home sensor for monitoring and automation routines."
            verdict = "Good buy if you are building a smart-home setup."

        score = self._basic_score(product)
        label = self._label_for_score(score)

        return {
            "short_description": description,
            "tags": tags[:5],
            "deal_score": score,
            "deal_label": label,
            "buy_verdict": verdict,
        }

    def _basic_score(self, product) -> int:
        score = 40

        rating = getattr(product, "rating", None)
        orders = getattr(product, "orders", None)
        price = getattr(product, "price_usd", None)
        original = getattr(product, "original_price_usd", None)
        shipping = (getattr(product, "shipping", "") or "").lower()

        # Rating score: max 20
        if rating:
            if rating >= 4.9:
                score += 20
            elif rating >= 4.8:
                score += 17
            elif rating >= 4.7:
                score += 14
            elif rating >= 4.6:
                score += 10
            elif rating >= 4.5:
                score += 7

        # Orders score: max 15
        if orders:
            if orders >= 10000:
                score += 20
            elif orders >= 8000:
                score += 13
            elif orders >= 5000:
                score += 11
            elif orders >= 3000:
                score += 8
            elif orders >= 1000:
                score += 5
            elif orders >= 100:
                score += 2

        # Discount score: max 20
        if price and original and original > price:
            discount = ((original - price) / original) * 100

            if discount >= 70:
                score += 20
            elif discount >= 50:
                score += 16
            elif discount >= 40:
                score += 12
            elif discount >= 30:
                score += 9
            elif discount >= 15:
                score += 5
            elif discount >= 5:
                score += 2

        # Free shipping bonus
        if "free" in shipping:
            score += 5

        # Small price/value bonus
        if price:
            if price <= 15:
                score += 4
            elif price <= 30:
                score += 2

        review_sentiment = get_review_sentiment_for_product(product)
        score += review_sentiment.score_modifier

        set_product_value(product, "review_sentiment", review_sentiment.sentiment)
        set_product_value(product, "review_score_modifier", review_sentiment.score_modifier)
        set_product_value(product, "review_sentiment_reason", review_sentiment.reason)
        set_product_value(product, "review_comments_used", review_sentiment.comments_used)

        return max(1, min(100, score))

    def _label_for_score(self, score: int) -> str:
        if score > 94:
            return "לא לפספס"
        if score >= 85:
            return "דיל מעולה 🎉"
        if score >= 70:
            return "דיל טוב"
        return "דיל חלש"
