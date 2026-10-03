import asyncio
import json
import logging
import random
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
from html import escape
from zoneinfo import ZoneInfo

from app.clients.aliexpress import AliExpressClient
from app.clients.ollama import OllamaClient, verdict_for_score
from app.clients.seed_products import SeedProductsClient
from app.clients.seed_urls import SeedUrlsClient
from app.clients.telegram import TelegramClient
from app.config import Settings
from app.services.discovery_pool import GADGET_WOW, KEYWORD_CATEGORY, keyword_wow, sample_keywords
from app.services.filters import find_duplicate_title, is_good_deal, is_hidden_gem
from app.storage.db import last_posted_at, mark_posted, was_posted
from app.storage.price_history import record_price
from app.storage.product_queue import (
    enqueue_product,
    expire_stale_queued,
    get_next_queued_product,
    get_queue_row,
    get_recent_posted_categories,
    init_product_queue,
    mark_posted as mark_queue_posted,
    mark_skipped,
    MAX_QUEUED_PER_CATEGORY,
    queue_size,
    queued_count_for_category,
    queued_count_for_keyword,
    recent_posted_keywords,
    recent_titles,
    update_queued_product,
    was_queued,
)
from app.utils import get_product_value, set_product_value

log = logging.getLogger(__name__)

ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")

# Off-target results (per the model) after which a keyword's remaining results are skipped.
MAX_KEYWORD_MISMATCHES = 3

# AliExpress first-level category ID -> rotation category, for products found
# through hot products / promo campaigns rather than a keyword search.
ALI_CATEGORY_ID_TO_CATEGORY = {
    "202192403": "phone_accessories",
    "509": "phone_accessories",
    "44": "electronics",
    "7": "gaming_pc",
    "34": "car",
    "30": "smart_home",
    "39": "smart_home",
    "13": "smart_home",
    "1420": "tools_diy",
}


def _discount_percent(price, original_price):
    if not price or not original_price or float(original_price) <= float(price):
        return None

    return round(((float(original_price) - float(price)) / float(original_price)) * 100)


def score_visual(score: int, label: str) -> str:
    if score > 94:
        return f"🌈💃 <b>ציון דיל: {score}/100</b>\n<b>{escape(label)}</b>"
    if score >= 85:
        return f"🟢 <b>ציון דיל: {score}/100</b>\n<b>{escape(label)}</b>"
    if score >= 70:
        return f"⚪ <b>ציון דיל: {score}/100</b>\n<b>{escape(label)}</b>"

    return f"🔴 <b>ציון דיל: {score}/100</b>\n<b>{escape(label)}</b>"


def format_tags(tags: list[str]) -> str:
    clean = []

    for tag in tags[:5]:
        tag = str(tag).replace("#", "").replace(" ", "").strip()
        if tag:
            clean.append(f"#{escape(tag)}")

    return " ".join(clean)


def _format_price_line(product, settings) -> str:
    price_ils = get_product_value(product, "price_ils")
    original_price_ils = get_product_value(product, "original_price_ils")

    price_usd = get_product_value(product, "price_usd")
    original_price_usd = get_product_value(product, "original_price_usd")

    discount_text = get_product_value(product, "discount")

    if price_ils:
        price_text = f"₪{float(price_ils):.2f}"
        original_price = original_price_ils
        price = price_ils
        currency_symbol = "₪"
    elif price_usd:
        approx_ils = round(float(price_usd) * settings.usd_to_ils)
        price_text = f"${float(price_usd):.2f} / ~₪{approx_ils}"
        original_price = original_price_usd
        price = price_usd
        currency_symbol = "$"
    else:
        return "💸 <b>בדקו מחיר עדכני</b>"

    calculated_discount = _discount_percent(price, original_price)

    if original_price and calculated_discount:
        original_text = f"{currency_symbol}{float(original_price):.2f}"
        return f"💸 <b>{price_text}</b>  <s>{original_text}</s>  (-{calculated_discount}%)"

    if discount_text and discount_text != "0%":
        return f"💸 <b>{price_text}</b>  (-{escape(str(discount_text))})"

    return f"💸 <b>{price_text}</b>"


def _price_history_line(enrichment: dict) -> str | None:
    drop = enrichment.get("real_drop_percent")

    if enrichment.get("lowest_price_seen") and drop:
        return f"📉 <b>המחיר הכי נמוך שראינו</b> ({drop}% מתחת למחיר הרגיל)"

    if drop and drop >= 7:
        return f"📉 <b>{drop}% מתחת למחיר הרגיל שלו</b>"

    return None


def _highlight_line(enrichment: dict) -> str | None:
    if enrichment.get("hidden_gem"):
        return "💎 <b>פנינה נסתרת</b> - דירוג מעולה ועוד לא כולם גילו"

    if (enrichment.get("wow_score") or 0) >= GADGET_WOW:
        return "🤯 <b>גאדג'ט מגניב</b>"

    return None


def _coupon_line(product) -> str | None:
    code = get_product_value(product, "promo_code")
    if not code:
        return None

    value = get_product_value(product, "promo_code_value")
    min_spend = get_product_value(product, "promo_code_min_spend")

    line = f"🎟️ <b>קופון:</b> <code>{escape(str(code))}</code>"
    if value:
        line += f" ({escape(str(value))}"
        line += f" בקנייה מעל {escape(str(min_spend))})" if min_spend else ")"

    return line


def build_telegram_message(product, enrichment: dict, settings) -> str:
    raw_title = (
            enrichment.get("display_title")
            or get_product_value(product, "title", "מוצר מאליאקספרס")
    )
    title = escape(str(raw_title))

    description = escape(
        enrichment.get("short_description")
        or "מוצר מאליאקספרס עם נתונים שכדאי לבדוק לפני רכישה."
    )

    score = int(enrichment.get("deal_score", 70))
    label = enrichment.get("deal_label", "דיל טוב")
    score_line = score_visual(score, label)

    verdict = escape(enrichment.get("buy_verdict") or verdict_for_score(score))

    price_line = _format_price_line(product, settings)

    rating = get_product_value(product, "rating")
    orders = get_product_value(product, "orders")
    shipping = get_product_value(product, "shipping")
    category = get_product_value(product, "category")
    shop_name = get_product_value(product, "shop_name")

    rating_line = f"⭐ <b>דירוג:</b> {rating}/5" if rating else "⭐ <b>דירוג:</b> לא ידוע"
    orders_line = f"📦 <b>נמכרו:</b> {int(orders):,}+" if orders else "📦 <b>נמכרו:</b> לא ידוע"

    lines = [
        f"🔥 <b>{title}</b>",
        "",
        f"⚡ {description}",
        "",
        score_line,
    ]

    highlight_line = _highlight_line(enrichment)
    if highlight_line:
        lines.append(highlight_line)

    lines.extend(["", price_line])

    history_line = _price_history_line(enrichment)
    if history_line:
        lines.append(history_line)

    coupon_line = _coupon_line(product)
    if coupon_line:
        lines.append(coupon_line)

    lines.extend([rating_line, orders_line])

    # The affiliate API does not report shipping, so only show it when a source does.
    if shipping:
        shipping_text = "משלוח חינם" if "free" in str(shipping).lower() else str(shipping)
        lines.append(f"🚚 <b>{escape(shipping_text)}</b>")

    meta_lines = []
    if category:
        meta_lines.append(f"🏷️ <b>קטגוריה:</b> {escape(str(category))}")
    if shop_name:
        meta_lines.append(f"🏪 <b>חנות:</b> {escape(str(shop_name))}")

    if meta_lines:
        lines.extend(["", *meta_lines])

    lines.extend(
        [
            "",
            "🧠 <b>שורה תחתונה:</b>",
            verdict,
            "",
            format_tags(enrichment.get("tags", [])),
            "",
            "👇 <b>לצפייה בדיל לחצו על הכפתור למטה</b>",
        ]
    )

    return "\n".join(lines)


def product_to_dict(product) -> dict:
    if isinstance(product, dict):
        return product

    if is_dataclass(product):
        return asdict(product)

    return dict(product.__dict__)


def product_from_queue_row(row: dict):
    product_data = json.loads(row["product_json"])
    enrichment_data = json.loads(row["enrichment_json"])
    return product_data, enrichment_data


def is_active_posting_hour(settings) -> bool:
    now = datetime.now(ISRAEL_TZ)
    return settings.post_active_start_hour <= now.hour < settings.post_active_end_hour


def keyword_to_category(keyword: str, product=None) -> str:
    keyword_lower = (keyword or "").lower()

    category_rules = {
        "car": [
            "car", "dash cam", "tire", "magsafe car", "trunk", "seat gap",
            "sun shade", "wireless car"
        ],
        "pets": [
            "pet", "dog", "cat"
        ],
        "home_kitchen": [
            "kitchen", "drawer", "air fryer", "oil spray", "vegetable",
            "spice", "sink", "bathroom", "closet", "vacuum storage"
        ],
        "baby_kids": [
            "baby", "stroller", "kids", "child"
        ],
        "beauty_grooming": [
            "makeup", "mirror", "hair trimmer", "beard", "manicure",
            "shaver", "grooming"
        ],
        "cleaning": [
            "vacuum", "cleaning", "lint", "microfiber", "mop", "dust"
        ],
        "desk_office": [
            "monitor", "laptop stand", "desk", "vertical mouse",
            "cable organizer"
        ],
        "travel": [
            "travel", "packing", "passport", "luggage"
        ],
        "phone_accessories": [
            "usb c", "gan charger", "charger", "power bank", "ugreen",
            "baseus", "magsafe"
        ],
        "smart_home": [
            "smart plug", "zigbee", "security camera", "led strip",
            "aqara", "temperature sensor"
        ],
        "gaming_pc": [
            "keyboard", "mechanical", "ps5", "gaming", "pc"
        ],
        "tools_diy": [
            "screwdriver", "laser level", "tool", "drill"
        ],
    }

    for category, terms in category_rules.items():
        if any(term in keyword_lower for term in terms):
            return category

    # Fallback to AliExpress category if available. IDs first: the names are
    # localized (Hebrew), which breaks category rotation.
    if product is not None:
        category_id = str(get_product_value(product, "category_id") or "")
        if category_id in ALI_CATEGORY_ID_TO_CATEGORY:
            return ALI_CATEGORY_ID_TO_CATEGORY[category_id]

        ali_category = get_product_value(product, "category")
        if ali_category:
            return str(ali_category).strip().lower()

    return "general"


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(str(value).replace(" ", "T"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


class DealEngine:
    def __init__(self, settings: Settings):
        self.settings = settings

        self.aliexpress = AliExpressClient(settings)
        self.telegram = TelegramClient(settings)
        self.ollama = OllamaClient(settings)

        self.product_client = self._build_product_client()

    def _build_product_client(self):
        """
        PRODUCT_SOURCE:
        - aliexpress_api: keyword search through the affiliate API (normal mode)
        - seed_urls: data/products_seed.json lists AliExpress URLs, enriched via the API
        - seed: legacy manual Product JSON
        """
        source = (self.settings.product_source or "seed_urls").lower()

        if source == "seed_urls":
            return SeedUrlsClient(
                aliexpress_client=self.aliexpress,
                path=self.settings.seed_products_path,
            )

        if source == "seed":
            return SeedProductsClient(self.settings.seed_products_path)

        if source == "aliexpress_api":
            return self.aliexpress

        raise RuntimeError(f"Unsupported PRODUCT_SOURCE: {self.settings.product_source}")

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    async def _discovery_sources(self) -> list[str]:
        """
        Source tokens, fetched in random order:
        - "<keyword>": keyword search
        - "hot_topic_keyword:<kw>": hot products for a trending keyword
        - "hot_topic:<id>" / "hot_topics": hot products by topic
        - "promo:<name>": products in a running AliExpress promotion campaign
        """
        source = (self.settings.product_source or "seed_urls").lower()

        if source in ["seed_urls", "seed"]:
            return ["seed_urls"]

        if self.settings.use_gadget_pool:
            sources = sample_keywords(
                self.settings.discovery_keywords_per_run,
                self.settings.staple_keyword_share,
                avoid=recent_posted_keywords(self.settings.keyword_cooldown_days),
            )
        else:
            sources = list(self.settings.keyword_list)

        if self.settings.enable_hot_products:
            sources.extend(f"hot_topic_keyword:{kw}" for kw in self.settings.hot_topic_keyword_list)

        if self.settings.enable_hot_topics:
            topic_ids = self.settings.hot_topics_topic_id_list
            if topic_ids:
                sources.extend(f"hot_topic:{topic_id}" for topic_id in topic_ids)
            else:
                sources.append("hot_topics")

        if self.settings.enable_featured_promos:
            sources.extend(f"promo:{name}" for name in await self._pick_featured_promos())

        random.shuffle(sources)
        return sources

    async def _pick_featured_promos(self) -> list[str]:
        try:
            promos = await self.aliexpress.list_featured_promos()
        except Exception as e:
            log.warning("Could not list featured promos: %s", e)
            return []

        patterns = self.settings.featured_promo_pattern_list
        matching = [
            promo["promo_name"]
            for promo in promos
            if promo.get("promo_name")
               and any(pattern in promo["promo_name"].lower() for pattern in patterns)
        ]

        random.shuffle(matching)
        picked = matching[: self.settings.featured_promos_per_run]
        log.info("Featured promos picked: %s (of %d matching)", picked, len(matching))
        return picked

    async def _fetch_source(self, token: str, page_no: int, sort: str) -> list:
        if token.startswith("hot_topic:"):
            return await self.aliexpress.get_hot_topic_products(
                topic_id=token.split(":", 1)[1],
                limit=self.settings.hot_topics_limit,
                page_no=page_no,
            )

        if token == "hot_topics":
            return await self.aliexpress.get_hot_topic_products(
                topic_id=None,
                limit=self.settings.hot_topics_limit,
                page_no=page_no,
            )

        if token.startswith("hot_topic_keyword:"):
            return await self.aliexpress.get_hot_products(
                keyword=token.split(":", 1)[1],
                limit=self.settings.hot_topics_per_request,
                page_no=page_no,
                sort=sort,
            )

        if token.startswith("promo:"):
            return await self.aliexpress.get_featured_promo_products(
                promotion_name=token.split(":", 1)[1],
                page_no=page_no,
                sort=sort,
            )

        return await self.product_client.search_products(
            keyword=token,
            limit=50,
            page_no=page_no,
            sort=sort,
        )

    @staticmethod
    def _source_category(token: str, product) -> str:
        if token.startswith("hot_topic:") or token == "hot_topics":
            return "hot_topics"

        if token.startswith("hot_topic_keyword:"):
            return keyword_to_category(token.split(":", 1)[1], product)

        if token.startswith("promo:"):
            # Campaign names say nothing about the product; use its own category.
            return keyword_to_category("", product)

        if token in KEYWORD_CATEGORY:
            return KEYWORD_CATEGORY[token]

        return keyword_to_category(token, product)

    def _repost_allowed(self, product_id: str, price_ils) -> tuple[bool, str]:
        """
        A posted product may return after a cooldown if it got meaningfully cheaper.
        """
        last = _parse_ts(last_posted_at(product_id))
        if last and datetime.now(timezone.utc) - last < timedelta(days=self.settings.repost_cooldown_days):
            return False, f"posted {(datetime.now(timezone.utc) - last).days}d ago"

        row = get_queue_row(product_id)
        if not row or not price_ils:
            return False, "no previous price to compare"

        try:
            previous_price = json.loads(row["product_json"]).get("price_ils")
        except (TypeError, ValueError):
            previous_price = None

        if not previous_price:
            return False, "no previous price to compare"

        drop = (float(previous_price) - float(price_ils)) / float(previous_price) * 100
        if drop < self.settings.repost_min_drop_percent:
            return False, f"price drop {drop:.0f}% below {self.settings.repost_min_drop_percent:.0f}%"

        return True, f"price dropped {drop:.0f}% since last post (₪{previous_price} -> ₪{price_ils})"

    async def discover_and_queue(self) -> None:
        """
        Search products from AliExpress, filter, enrich, score,
        and save good candidates into product_queue.
        """
        init_product_queue()

        expired = expire_stale_queued(self.settings.queue_max_age_days)
        if expired:
            log.info("Expired %d stale queued products", expired)

        if queue_size() >= self.settings.queue_target_size:
            log.info(
                "Queue already has %d products (target %d). Skipping discovery.",
                queue_size(), self.settings.queue_target_size,
            )
            return

        queued_count = 0
        checked_count = 0
        known_titles = recent_titles(self.settings.duplicate_title_lookback_days)

        for token in await self._discovery_sources():
            if queued_count >= self.settings.discovery_max_candidates_per_run:
                log.info("Reached discovery candidate limit.")
                break

            if queue_size() >= self.settings.queue_target_size:
                log.info("Queue target reached.")
                break

            page_no = random.randint(self.settings.discovery_page_min, self.settings.discovery_page_max)
            # Price-sorted results are almost all unrated or out of price range
            # (measured: 0 usable products); best sellers are where the deals are.
            sort = "LAST_VOLUME_DESC"

            log.info("Discovering: %s | page=%s | sort=%s", token, page_no, sort)

            try:
                products = await self._fetch_source(token, page_no, sort)
            except Exception as e:
                log.error("Search failed for %s: %s", token, e)
                continue

            mismatches = 0

            for product in products:
                if queued_count >= self.settings.discovery_max_candidates_per_run:
                    break

                # A keyword whose results keep being something else isn't worth more model calls.
                if mismatches >= MAX_KEYWORD_MISMATCHES:
                    log.info("Giving up on %s after %d off-target results", token, mismatches)
                    break

                if queued_count_for_keyword(token) >= self.settings.max_queued_per_keyword:
                    break

                checked_count += 1

                product_id = get_product_value(product, "product_id")
                product_url = get_product_value(product, "product_url")
                affiliate_url = get_product_value(product, "affiliate_url")
                title = get_product_value(product, "title", "AliExpress Product")
                price_ils = get_product_value(product, "price_ils")

                if not product_id or not product_url:
                    continue

                # Every sighting feeds the price history, whether or not we queue it.
                record_price(
                    str(product_id),
                    price_ils,
                    get_product_value(product, "original_price_ils"),
                )

                if was_queued(product_id):
                    continue

                if was_posted(product_id):
                    allowed, reason = self._repost_allowed(str(product_id), price_ils)
                    if not allowed:
                        log.debug("Already posted %s: %s", product_id, reason)
                        continue
                    log.info("Repost candidate %s: %s", product_id, reason)

                allowed, reason = is_good_deal(product, self.settings)
                if not allowed:
                    log.debug("Skipping %s: %s", product_id, reason)
                    continue

                source_category = self._source_category(token, product)
                if queued_count_for_category(source_category) >= MAX_QUEUED_PER_CATEGORY:
                    log.debug("Skipping %s: category %s is full", product_id, source_category)
                    continue

                duplicate_of = find_duplicate_title(
                    str(title), known_titles, self.settings.duplicate_title_similarity,
                )
                if duplicate_of:
                    log.debug("Skipping %s: looks like %r", product_id, duplicate_of[:60])
                    continue

                # Score first: it's deterministic and free, the model call is not.
                wow = keyword_wow(token)
                result = self.ollama.score(product, wow=wow)
                score = result.score

                if score < self.settings.min_deal_score_to_post:
                    log.debug(
                        "Skipping %s: score %s below %s",
                        product_id, score, self.settings.min_deal_score_to_post,
                    )
                    continue

                search_keyword = token if token in KEYWORD_CATEGORY else None
                enrichment = await self.ollama.enrich_product(product, result, search_keyword=search_keyword)

                # A "geiger counter" search also returns EMF meters and cases; only the real thing counts.
                if enrichment.get("matches_search") is False:
                    mismatches += 1
                    log.info(
                        "Skipping %s: not a %s (%s)",
                        product_id, token, enrichment.get("what_it_is") or str(title)[:60],
                    )
                    continue

                enrichment["wow_score"] = wow
                enrichment["hidden_gem"] = is_hidden_gem(product, self.settings)

                inserted = enqueue_product(
                    product_id=str(product_id),
                    product_url=str(product_url),
                    affiliate_url=str(affiliate_url or product_url),
                    title=str(title),
                    score=score,
                    source_keyword=token,
                    source_category=source_category,
                    product_data=product_to_dict(product),
                    enrichment_data=enrichment,
                )

                if inserted:
                    queued_count += 1
                    known_titles.append(str(title))
                    log.info(
                        "Queued: %s score=%s wow=%s source=%s category=%s",
                        product_id, score, wow, token, source_category,
                    )

        log.info(
            "Discovery finished. Checked=%d, queued=%d, queue_size=%d",
            checked_count, queued_count, queue_size(),
        )

    # ------------------------------------------------------------------
    # Posting
    # ------------------------------------------------------------------

    async def _refresh_before_posting(self, queue_row: dict) -> tuple[dict, dict] | None:
        """
        Re-fetch the product so we never post a stale price or a dead listing.
        Returns fresh (product_data, enrichment), or None if it should be skipped
        (the row is marked skipped here).
        """
        product_data, enrichment = product_from_queue_row(queue_row)

        try:
            fresh = await self.aliexpress.get_product_detail(queue_row["product_url"])
        except Exception as e:
            # Transient API trouble shouldn't block posting; fall back to queued data.
            log.warning("Re-validation fetch failed for %s, posting queued data: %s", queue_row["product_id"], e)
            return product_data, enrichment

        # productdetail.get doesn't always include a promotion link; keep the queued one.
        if not fresh.affiliate_url:
            fresh.affiliate_url = queue_row.get("affiliate_url") or product_data.get("affiliate_url")

        # Fields that only the discovery source provides, or that the detail
        # endpoint sometimes leaves empty.
        for key in [
            "source", "promo_code", "promo_code_value", "promo_code_min_spend",
            "rating", "orders", "image_url", "category", "category_id", "sub_category_id",
        ]:
            if not get_product_value(fresh, key) and product_data.get(key):
                set_product_value(fresh, key, product_data[key])

        record_price(str(fresh.product_id), fresh.price_ils, fresh.original_price_ils)

        allowed, reason = is_good_deal(fresh, self.settings)
        if not allowed:
            mark_skipped(queue_row["id"], f"stale: {reason}")
            log.info("Skipping queued %s at post time: %s", queue_row["product_id"], reason)
            return None

        result = self.ollama.score(fresh, wow=enrichment.get("wow_score"))
        score = result.score

        if score < self.settings.min_deal_score_to_post:
            mark_skipped(queue_row["id"], f"stale: score dropped to {score}")
            log.info("Skipping queued %s at post time: score dropped to %s", queue_row["product_id"], score)
            return None

        # Numbers only: the queued copy text is reused below, so no model call here.
        fresh_enrichment = await self.ollama.enrich_product(fresh, result, use_model=False)
        fresh_enrichment["hidden_gem"] = is_hidden_gem(fresh, self.settings)

        # Keep the queued copy text (it may be model-written); refresh the numbers.
        for key in ["short_description", "tags", "wow_score", "what_it_is", "matches_search"]:
            if enrichment.get(key) is not None:
                fresh_enrichment[key] = enrichment[key]
        if score >= 70 and enrichment.get("buy_verdict"):
            fresh_enrichment["buy_verdict"] = enrichment["buy_verdict"]

        fresh_data = product_to_dict(fresh)
        update_queued_product(queue_row["id"], fresh_data, fresh_enrichment, score)
        return fresh_data, fresh_enrichment

    async def post_next_from_queue(
            self,
            force: bool = False,
            excluded_categories: set[str] | None = None,
            dry_run: bool = False,
            excluded_ids: set[int] | None = None,
            excluded_keywords: set[str] | None = None,
    ) -> dict | None:
        """
        Post the best queued product to Telegram.
        Returns the DB queue row, not the AliExpress product JSON.
        """
        init_product_queue()

        if not force and not is_active_posting_hour(self.settings):
            log.info("Outside active posting hours. Skipping post.")
            return None

        excluded_keywords = (excluded_keywords or set()) | recent_posted_keywords(
            self.settings.keyword_post_spacing_days
        )

        log.info(
            "Category rotation window=%s | recent=%s",
            self.settings.category_rotation_window,
            get_recent_posted_categories(self.settings.category_rotation_window) or "none",
        )

        expire_stale_queued(self.settings.queue_max_age_days)

        # Candidates can be skipped at post time; try a few before giving up.
        for _ in range(5):
            queue_row = get_next_queued_product(
                rotation_window=self.settings.category_rotation_window,
                excluded_categories=excluded_categories,
                excluded_ids=excluded_ids,
                excluded_keywords=excluded_keywords,
            )

            if not queue_row:
                log.info("Queue is empty. Running discovery first...")
                await self.discover_and_queue()

                queue_row = get_next_queued_product(
                    rotation_window=self.settings.category_rotation_window,
                    excluded_categories=excluded_categories,
                    excluded_ids=excluded_ids,
                    excluded_keywords=excluded_keywords,
                )

                if not queue_row:
                    log.warning("Queue still empty. Nothing to post.")
                    return None

            if dry_run:
                product_data, enrichment = product_from_queue_row(queue_row)
            else:
                refreshed = await self._refresh_before_posting(queue_row)
                if refreshed is None:
                    continue
                product_data, enrichment = refreshed

            message = build_telegram_message(product_data, enrichment, self.settings)

            if dry_run:
                log.info("[DRY RUN] Would post queue id=%s:\n%s", queue_row["id"], message)
                return queue_row

            try:
                await self.telegram.send_product(product_data, message)
            except Exception as e:
                mark_skipped(queue_row["id"], str(e))
                log.error("Failed to post queued product %s: %s", queue_row["product_id"], e)
                raise

            if not self.settings.dry_run:
                mark_queue_posted(queue_row["id"])
                mark_posted(str(queue_row["product_id"]))

            log.info(
                "Posted from queue: id=%s product_id=%s score=%s category=%s",
                queue_row.get("id"), queue_row.get("product_id"),
                enrichment.get("deal_score"), queue_row.get("source_category"),
            )

            return queue_row

        log.warning("Every candidate was skipped at post time.")
        return None

    async def post_batch_from_queue(self, force: bool = False, dry_run: bool = False) -> int:
        """
        Post multiple queued products in one batch, keeping categories diverse.
        Returns how many were posted.
        """
        posts_per_batch = self.settings.posts_per_batch

        posted = 0
        failures = []
        selected_categories_this_batch: set[str] = set()
        selected_ids_this_batch: set[int] = set()
        selected_keywords_this_batch: set[str] = set()

        for index in range(posts_per_batch):
            try:
                queue_row = await self.post_next_from_queue(
                    force=force,
                    excluded_categories=selected_categories_this_batch,
                    dry_run=dry_run,
                    excluded_ids=selected_ids_this_batch,
                    excluded_keywords=selected_keywords_this_batch,
                )
            except Exception as e:
                # One bad product shouldn't cancel the rest of the batch.
                failures.append(str(e))
                log.error("Failed posting batch item %d: %s", index + 1, e)
                continue

            if not queue_row:
                break

            selected_ids_this_batch.add(queue_row["id"])
            if queue_row.get("source_keyword"):
                selected_keywords_this_batch.add(queue_row["source_keyword"])
            category = queue_row.get("source_category")
            if category:
                selected_categories_this_batch.add(category)

            posted += 1

            # Small delay between Telegram posts so it doesn't look spammy
            if index < posts_per_batch - 1 and not dry_run:
                await asyncio.sleep(5)

        log.info("Batch posting finished. Posted %d/%d.", posted, posts_per_batch)

        in_active_hours = force or is_active_posting_hour(self.settings)
        if not dry_run and in_active_hours and posted == 0:
            detail = f"\nErrors: {failures[:3]}" if failures else ""
            await self.telegram.send_alert(
                f"Batch posted 0/{posts_per_batch} products. Queue size: {queue_size()}.{detail}"
            )

        return posted

    async def run_once(self) -> None:
        """
        Manual test mode: fill the queue if needed.
        """
        await self.discover_and_queue()
        # await self.post_next_from_queue(force=True)
