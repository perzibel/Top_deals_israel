import asyncio
import json
import logging
import random
import re
from typing import Any
from urllib import error, request

import httpx

from app.services.scoring import ScoreResult, label_for_score, score_product
from app.storage.price_history import get_price_stats
from app.utils import get_product_value

log = logging.getLogger(__name__)

# Hebrew copy per product type: (short_description, buy_verdict).
PRODUCT_TYPE_COPY: dict[str, tuple[str, str]] = {
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

# Checked in order; first match wins.
PRODUCT_TYPE_TERMS: list[tuple[str, list[str]]] = [
    ("car_vacuum", ["car vacuum"]),
    ("power_bank", ["power bank", "powerbank"]),
    ("charger", ["charger", "gan ", "charging"]),
    ("smart_home_sensor", ["sensor", "zigbee", "aqara"]),
    ("storage_organizer", ["organizer", "storage", "rack"]),
    ("headphones", ["earbuds", "headphone", "headset", "earphone"]),
    ("car_accessory", ["car ", "dash cam", "tire inflator"]),
    ("kitchen_tool", ["kitchen", "chopper", "oil spray", "air fryer"]),
    ("toy", ["toy", "lego", "building blocks"]),
]

DEFAULT_DESCRIPTIONS = [
    "מוצר שימושי עם דירוג טוב וכמות הזמנות יפה.",
    "מוצר פופולרי שקיבל ביקורות מצוינות.",
    "מצאנו מוצר מעניין שיכול לשדרג לכם את השגרה.",
    "המוצר הזה צובר תאוצה וביקורות חיוביות.",
    "פתרון חכם ופשוט ליומיום במחיר משתלם.",
    "בחירה מצוינת למי שמחפש איכות ומחיר טוב.",
]

# Verdicts by score band, so a weak deal is never hyped.
VERDICTS_BY_BAND: list[tuple[int, list[str]]] = [
    (95, [
        "דיל חזק במיוחד, שווה לבדוק לפני שנגמר.",
        "מחיר נמוך במיוחד עם נתונים מצוינים - לא הייתי מחכה.",
        "אחד הדילים הטובים שראינו לאחרונה בקטגוריה.",
    ]),
    (85, [
        "דיל טוב עם נתונים חזקים יחסית למחיר.",
        "בחירה מצוינת למי שמחפש איכות ומחיר טוב.",
        "מוצר פופולרי שקיבל ביקורות מצוינות.",
        "המוצר הזה צובר תאוצה וביקורות חיוביות.",
    ]),
    (70, [
        "דיל סביר, שווה לבדוק אם אתם באמת צריכים את המוצר.",
        "שווה בדיקה אם זה משהו שחיפשתם.",
        "מוצר שימושי עם דירוג טוב וכמות הזמנות יפה.",
    ]),
    (0, [
        "לא הייתי ממהר לקנות. הנתונים לא מספיק חזקים ביחס לדילים אחרים באותה קטגוריה.",
    ]),
]

HEBREW_CHARS = re.compile(r"[֐-׿]")
LATIN_CHARS = re.compile(r"[A-Za-z]")
# Letters from any script other than Hebrew and Latin (Arabic, CJK, Cyrillic, ...).
FOREIGN_SCRIPT_CHARS = re.compile(r"[^\W\d_A-Za-z֐-׿]")


def detect_product_type(title: str) -> str | None:
    title = f" {(title or '').lower()} "
    for product_type, terms in PRODUCT_TYPE_TERMS:
        if any(term in title for term in terms):
            return product_type
    return None


def verdict_for_score(score: int) -> str:
    for threshold, options in VERDICTS_BY_BAND:
        if score >= threshold:
            return random.choice(options)
    return VERDICTS_BY_BAND[-1][1][0]


def is_usable_hebrew(text: Any, max_len: int) -> bool:
    """Reject empty, over-long, mostly-English, or CJK-polluted model output."""
    if not isinstance(text, str):
        return False

    text = text.strip()
    if not text or len(text) > max_len or "<think" in text.lower():
        return False

    if FOREIGN_SCRIPT_CHARS.search(text):
        return False

    hebrew = len(HEBREW_CHARS.findall(text))
    latin = len(LATIN_CHARS.findall(text))
    return hebrew >= 8 and hebrew >= latin * 2


def clean_tags(tags: Any) -> list[str]:
    if not isinstance(tags, list):
        return []

    cleaned = []
    for tag in tags:
        tag = re.sub(r"[^a-zA-Z0-9_\-]", "", str(tag).replace("#", ""))
        if tag and tag not in cleaned:
            cleaned.append(tag)

    return cleaned[:5]


class OllamaClient:
    def __init__(self, settings):
        self.settings = settings
        self.base_url = settings.ollama_base_url.rstrip("/")
        self.model = settings.ollama_model

    async def generate(self, prompt: str, model: str | None = None) -> str:
        """
        Generic Ollama text generation method.
        Used by the social post generator.
        """
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
            "think": False,
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

    @staticmethod
    def score(product) -> ScoreResult:
        """Deterministic score; cheap, so callers check it before paying for the model."""
        product_id = get_product_value(product, "product_id")
        history = get_price_stats(str(product_id)) if product_id else None
        return score_product(product, history)

    async def enrich_product(
            self,
            product,
            result: ScoreResult | None = None,
            use_model: bool = True,
    ) -> dict[str, Any]:
        """
        Returns:
        - deal_score / deal_label: deterministic, from app.services.scoring
        - short_description / buy_verdict: Hebrew copy (model output if usable, else templates)
        - tags: English hashtags
        - lowest_price_seen / real_drop_percent: price-history signals for the post
        """
        result = result or self.score(product)

        enrichment = self._template_copy(product, result.score)
        enrichment.update(
            deal_score=result.score,
            deal_label=label_for_score(result.score),
            score_breakdown=result.breakdown,
            lowest_price_seen=result.lowest_price_seen,
            real_drop_percent=(
                round(result.real_drop_percent) if result.real_drop_percent is not None else None
            ),
        )

        if not use_model or not getattr(self.settings, "use_ollama", False):
            return enrichment

        try:
            parsed = await self._ask_model(product)
        except Exception as e:
            log.warning("Ollama enrichment failed, using templates: %s", e)
            return enrichment

        tags = clean_tags(parsed.get("tags"))
        if tags:
            enrichment["tags"] = tags

        if getattr(self.settings, "use_ai_copy", True):
            description = parsed.get("short_description")
            if is_usable_hebrew(description, 160):
                enrichment["short_description"] = description.strip()

            # The model may only set the tone for deals the score says are good.
            verdict = parsed.get("buy_verdict")
            if result.score >= 70 and is_usable_hebrew(verdict, 180):
                enrichment["buy_verdict"] = verdict.strip()

        return enrichment

    async def _ask_model(self, product) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": self._build_prompt(product),
                    "stream": False,
                    "format": "json",
                    # qwen3 is a reasoning model; without this it "thinks" before answering.
                    "think": False,
                    "options": {
                        "temperature": 0.1,
                        "top_p": 0.8,
                        "num_predict": 400,
                    },
                },
            )

        response.raise_for_status()
        return self._parse_json(response.json().get("response", ""))

    def _build_prompt(self, product) -> str:
        price = get_product_value(product, "price_ils")
        original_price = get_product_value(product, "original_price_ils")

        discount_text = "unknown"
        if price and original_price and original_price > price:
            discount_text = f"{round((original_price - price) / original_price * 100)}%"

        return f"""
You are a deal analyst for an Israeli Telegram channel called Top Deals Israel.
Analyze this AliExpress product and return ONLY a JSON object.

Product:
- Title: {get_product_value(product, "title")}
- Category: {get_product_value(product, "category")}
- Price ILS: {price}
- Original Price ILS: {original_price}
- Discount: {discount_text}
- Rating: {get_product_value(product, "rating")}
- Orders: {get_product_value(product, "orders")}

Your job:
1. short_description: what the product is and who it is for, in natural Hebrew. Max 18 words.
2. tags: up to 5 English tags, no spaces, no # symbol.
3. buy_verdict: a short buying recommendation in natural Hebrew. Max 18 words.
4. Do not invent price, rating, orders, shipping, discount, or product features.

Return exactly:
{{"short_description": "...", "tags": ["Tag1", "Tag2"], "buy_verdict": "..."}}
""".strip()

    def _parse_json(self, text: str) -> dict[str, Any]:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Fallback if the model wraps JSON in text/code fences
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError(f"No JSON object found in Ollama response: {text[:300]}")

        return json.loads(match.group(0))

    def _template_copy(self, product, score: int) -> dict[str, Any]:
        title = get_product_value(product, "title", "") or ""
        product_type = detect_product_type(title)

        if product_type:
            description, _ = PRODUCT_TYPE_COPY[product_type]
        else:
            description = random.choice(DEFAULT_DESCRIPTIONS)

        tags = ["AliExpressDeals", "Gadgets"]
        lowered = title.lower()
        if "charger" in lowered or "usb-c" in lowered or "gan" in lowered:
            tags = ["Charging", "USBC", "Gadgets", "Travel", "DeskSetup"]
        elif "power bank" in lowered:
            tags = ["PowerBank", "Charging", "Travel", "Gadgets", "Battery"]
        elif "sensor" in lowered or "aqara" in lowered:
            tags = ["SmartHome", "Sensor", "Automation", "HomeKit", "Gadgets"]

        return {
            "short_description": description,
            "tags": tags,
            "buy_verdict": verdict_for_score(score),
        }
