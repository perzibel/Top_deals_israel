from __future__ import annotations
import asyncio
from dataclasses import asdict, is_dataclass
from typing import Any

from app.services.filters import is_good_deal
from app.services.engine import keyword_to_category
from app.storage.product_queue import was_queued
from app.storage.db import was_posted


def normalize_text(value: str) -> str:
    return str(value or "").lower().replace("-", " ").replace("_", " ")


def get_product_value(product: Any, key: str, default=None):
    if isinstance(product, dict):
        return product.get(key, default)

    return getattr(product, key, default)


def set_product_value(product: Any, key: str, value: Any):
    if isinstance(product, dict):
        product[key] = value
    else:
        setattr(product, key, value)


def product_to_dict(product: Any) -> dict:
    if isinstance(product, dict):
        return product

    if is_dataclass(product):
        return asdict(product)

    return dict(product.__dict__)


def normalize_text(value: str) -> str:
    return str(value or "").lower().replace("-", " ").replace("_", " ")


def is_relevant_alternative(original_product: Any, candidate: Any, search_keyword: str) -> bool:
    """
    Prevent unrelated alternatives.

    Example:
    Original = power bank
    Reject = BBQ thermometer / toothbrush
    Accept = power bank / portable charger / battery pack
    """

    original_title = normalize_text(get_product_value(original_product, "title", ""))
    candidate_title = normalize_text(get_product_value(candidate, "title", ""))
    keyword = normalize_text(search_keyword)

    combined_original = f"{original_title} {keyword}"
    combined_candidate = candidate_title

    relevance_rules = {
        "power bank": [
            "power bank",
            "powerbank",
            "portable charger",
            "external battery",
            "battery pack",
            "mah",
            "magsafe power",
        ],
        "usb c charger": [
            "usb c charger",
            "gan charger",
            "wall charger",
            "charger adapter",
            "pd charger",
            "type c",
            "fast charger",
        ],
        "gaming keyboard": [
            "keyboard",
            "mechanical",
            "rgb keyboard",
            "hot swappable",
        ],
        "gaming mouse": [
            "mouse",
            "wireless mouse",
            "gaming mouse",
            "bluetooth mouse",
        ],
        "ps5 accessories": [
            "ps5",
            "playstation",
            "dualsense",
            "dual sense",
            "controller",
        ],
        "baby silicone bib": [
            "baby",
            "bib",
            "silicone bib",
            "feeding",
        ],
        "dash cam": [
            "dash cam",
            "car camera",
            "driving recorder",
            "dvr",
        ],
        "smart plug": [
            "smart plug",
            "wifi plug",
            "zigbee plug",
            "tuya",
        ],
    }

    for product_type, signals in relevance_rules.items():
        if product_type in keyword or any(signal in combined_original for signal in signals):
            return any(signal in combined_candidate for signal in signals)

    keyword_parts = [
        part for part in keyword.split()
        if len(part) >= 4
    ]

    if not keyword_parts:
        return False

    return any(part in combined_candidate for part in keyword_parts)


class ManualProductAnalyzer:
    def __init__(self, settings, aliexpress_client, ollama_client):
        self.settings = settings
        self.aliexpress = aliexpress_client
        self.ollama = ollama_client

    async def analyze_link(self, product_url: str) -> dict:
        """
        Analyze a product link manually sent to the bot.

        Returns a structured result:
        {
            "status": "good" | "bad" | "error",
            "product": ...,
            "enrichment": ...,
            "score": int,
            "reasons": [...],
            "alternatives": [...]
        }
        """

        try:
            product = await self.aliexpress.get_product_detail(product_url)
        except Exception as e:
            return {
                "status": "error",
                "reason": f"Failed to fetch product details: {e}",
                "product_url": product_url,
            }

        product_id = get_product_value(product, "product_id")
        title = get_product_value(product, "title", "AliExpress Product")

        reasons = []

        if product_id and was_queued(str(product_id)):
            reasons.append("Product is already queued.")

        if product_id and was_posted(str(product_id)):
            reasons.append("Product was already posted before.")

        allowed, filter_reason = is_good_deal(product, self.settings)

        if not allowed:
            reasons.append(filter_reason)

        try:
            enrichment = await self.ollama.enrich_product(product)
        except Exception as e:
            enrichment = {
                "deal_score": 0,
                "deal_label": "בדיקה נכשלה",
                "short_description": "לא הצלחנו לנתח את המוצר עם AI.",
                "buy_verdict": str(e),
                "tags": [],
            }
            reasons.append(f"Ollama enrichment failed: {e}")

        score = int(enrichment.get("deal_score", 0))

        if score < self.settings.min_deal_score_to_post:
            reasons.append(
                f"Score {score} below minimum {self.settings.min_deal_score_to_post}."
            )

        if allowed and score >= self.settings.min_deal_score_to_post:
            return {
                "status": "good",
                "product": product,
                "product_data": product_to_dict(product),
                "enrichment": enrichment,
                "score": score,
                "reasons": reasons,
                "alternatives": [],
            }

        try:
            await asyncio.sleep(3)
            alternatives = await self.find_alternatives(product, limit=2)
        except Exception as e:
            print(f"[MANUAL_ANALYZER] Alternatives search failed: {e}")
            alternatives = []

        return {
            "status": "bad",
            "product": product,
            "product_data": product_to_dict(product),
            "enrichment": enrichment,
            "score": score,
            "reasons": reasons,
            "alternatives": alternatives,
            "title": title,
        }

    async def find_alternatives(self, original_product: Any, limit: int = 3) -> list[dict]:
        """
        Find better alternatives for a weak manually submitted product.

        Current method:
        - Use title/category keywords
        - Search AliExpress product query
        - Filter/scoring
        - Return top 3
        """

        title = get_product_value(original_product, "title", "")
        category = get_product_value(original_product, "category", "")

        keyword = self._build_search_keyword(title, category)
        print("[MANUAL_ANALYZER] Original title:", title)
        print("[MANUAL_ANALYZER] Original category:", category)
        print("[MANUAL_ANALYZER] Alternative search keyword:", keyword)

        if not keyword:
            return []

        try:
            candidates = await self.aliexpress.search_products(
                keyword=keyword,
                limit=8,
                page_no=1,
                sort="LAST_VOLUME_DESC",
            )
        except Exception as e:
            print(f"[MANUAL_ANALYZER] Failed to search alternatives: {e}")
            return []

        alternatives = []

        original_product_id = str(get_product_value(original_product, "product_id", ""))

        for candidate in candidates:
            product_id = str(get_product_value(candidate, "product_id", ""))

            if not product_id:
                continue

            if product_id == original_product_id:
                continue

            if not is_relevant_alternative(original_product, candidate, keyword):
                print(
                    "[MANUAL_ANALYZER] Rejecting unrelated alternative:",
                    get_product_value(candidate, "title", "unknown"),
                )
                continue

            if was_queued(product_id) or was_posted(product_id):
                continue

            allowed, reason = is_good_deal(candidate, self.settings)
            if not allowed:
                continue

            try:
                await asyncio.sleep(1.5)
                enrichment = await self.ollama.enrich_product(candidate)
            except Exception as e:
                print(f"[MANUAL_ANALYZER] Alternative enrichment failed: {e}")
                continue

            score = int(enrichment.get("deal_score", 0))

            if score < self.settings.min_deal_score_to_post:
                continue

            alternatives.append(
                {
                    "product": candidate,
                    "product_data": product_to_dict(candidate),
                    "enrichment": enrichment,
                    "score": score,
                    "product_id": product_id,
                    "title": get_product_value(candidate, "title", "AliExpress Product"),
                    "url": get_product_value(candidate, "affiliate_url")
                    or get_product_value(candidate, "product_url"),
                    "category": keyword_to_category(keyword, candidate),
                }
            )

            if len(alternatives) >= limit:
                break

        alternatives.sort(key=lambda item: item["score"], reverse=True)

        return alternatives[:limit]

    def _build_search_keyword(self, title: str, category: str) -> str:
        """
        Extract a focused AliExpress search keyword from the original product.

        Goal:
        - Search for the same product type, not just any strong product.
        """

        title_lower = normalize_text(title)
        category_lower = normalize_text(category)

        product_type_rules = [
            {
                "keyword": "power bank",
                "signals": [
                    "power bank",
                    "powerbank",
                    "portable charger",
                    "external battery",
                    "battery pack",
                    "30000mah",
                    "20000mah",
                    "10000mah",
                    "magsafe power",
                    "fast charging bank",
                ],
            },
            {
                "keyword": "usb c charger",
                "signals": [
                    "usb c charger",
                    "gan charger",
                    "fast charger",
                    "wall charger",
                    "charger adapter",
                    "pd charger",
                    "type c charger",
                ],
            },
            {
                "keyword": "gaming keyboard",
                "signals": [
                    "gaming keyboard",
                    "mechanical keyboard",
                    "rgb keyboard",
                    "hot swappable",
                    "ajazz",
                    "ak820",
                ],
            },
            {
                "keyword": "gaming mouse",
                "signals": [
                    "gaming mouse",
                    "wireless mouse",
                    "rgb mouse",
                    "bluetooth mouse",
                    "paw3311",
                    "k snake",
                ],
            },
            {
                "keyword": "ps5 accessories",
                "signals": [
                    "ps5",
                    "playstation 5",
                    "dual sense",
                    "dualsense",
                    "controller charger",
                ],
            },
            {
                "keyword": "baby silicone bib",
                "signals": [
                    "baby bib",
                    "silicone bib",
                    "feeding bib",
                    "baby feeding",
                ],
            },
            {
                "keyword": "dash cam",
                "signals": [
                    "dash cam",
                    "car camera",
                    "dvr camera",
                    "driving recorder",
                ],
            },
            {
                "keyword": "smart plug",
                "signals": [
                    "smart plug",
                    "wifi plug",
                    "zigbee plug",
                    "tuya plug",
                ],
            },
        ]

        combined = f"{title_lower} {category_lower}"

        for rule in product_type_rules:
            if any(signal in combined for signal in rule["signals"]):
                return rule["keyword"]

        words = [
            word.strip()
            for word in title_lower.split()
            if len(word.strip()) >= 4
        ]

        # Avoid very generic words
        stop_words = {
            "with",
            "for",
            "from",
            "this",
            "that",
            "high",
            "fast",
            "sale",
            "free",
            "shipping",
            "original",
            "portable",
            "electric",
            "smart",
            "new",
        }

        clean_words = [word for word in words if word not in stop_words]

        return " ".join(clean_words[:3])

    def is_relevant_alternative(original_product: Any, candidate: Any, search_keyword: str) -> bool:
        """
        Prevent unrelated alternatives.

        Example:
        Original = power bank
        Reject = BBQ thermometer / toothbrush
        Accept = power bank / portable charger / battery pack
        """

        original_title = normalize_text(get_product_value(original_product, "title", ""))
        candidate_title = normalize_text(get_product_value(candidate, "title", ""))
        keyword = normalize_text(search_keyword)

        combined_original = f"{original_title} {keyword}"
        combined_candidate = candidate_title

        relevance_rules = {
            "power bank": [
                "power bank",
                "powerbank",
                "portable charger",
                "external battery",
                "battery pack",
                "mah",
            ],
            "usb c charger": [
                "usb c charger",
                "gan charger",
                "wall charger",
                "charger adapter",
                "pd charger",
                "type c",
            ],
            "gaming keyboard": [
                "keyboard",
                "mechanical",
                "rgb keyboard",
                "hot swappable",
            ],
            "gaming mouse": [
                "mouse",
                "wireless mouse",
                "gaming mouse",
                "bluetooth mouse",
            ],
            "ps5 accessories": [
                "ps5",
                "playstation",
                "dualsense",
                "controller",
            ],
            "baby silicone bib": [
                "baby",
                "bib",
                "silicone bib",
                "feeding",
            ],
            "dash cam": [
                "dash cam",
                "car camera",
                "driving recorder",
                "dvr",
            ],
            "smart plug": [
                "smart plug",
                "wifi plug",
                "zigbee plug",
                "tuya",
            ],
        }

        for product_type, signals in relevance_rules.items():
            if product_type in keyword or any(signal in combined_original for signal in signals):
                return any(signal in combined_candidate for signal in signals)

        keyword_parts = [part for part in keyword.split() if len(part) >= 4]

        if not keyword_parts:
            return False

        # Require at least one meaningful keyword part in the candidate title.
        return any(part in combined_candidate for part in keyword_parts)