from html import escape
import asyncio
from rich.console import Console
import random
from app.clients.aliexpress import AliExpressClient
from app.clients.ollama import OllamaClient
from app.clients.seed_products import SeedProductsClient
from app.clients.seed_urls import SeedUrlsClient
from app.clients.telegram import TelegramClient
from app.services.filters import is_good_deal
from app.storage.db import mark_posted, was_posted

from app.config import Settings

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from zoneinfo import ZoneInfo



from app.storage.product_queue import (
    enqueue_product,
    get_next_queued_product,
    get_recent_posted_categories,
    init_product_queue,
    mark_posted as mark_queue_posted,
    mark_skipped,
    queue_size,
    was_queued,
)

console = Console()


def get_product_value(product, key: str, default=None):
    if isinstance(product, dict):
        return product.get(key, default)

    return getattr(product, key, default)


def set_product_value(product, key: str, value):
    if isinstance(product, dict):
        product[key] = value
    else:
        setattr(product, key, value)


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


def score_based_verdict(score: int, ai_verdict: str) -> str:
    """
    Prevents Ollama from recommending weak products.
    The deterministic score controls the tone.
    """
    if score < 70:
        return (
            "לא הייתי ממהר לקנות. הנתונים לא מספיק חזקים ביחס לדילים אחרים "
            "באותה קטגוריה."
        )

    if score < 85:
        return ai_verdict or "דיל סביר, שווה לבדוק אם אתם באמת צריכים את המוצר."

    if score < 95:
        return ai_verdict or "דיל טוב עם נתונים חזקים יחסית למחיר."

    return ai_verdict or "דיל חזק במיוחד, שווה לבדוק לפני שנגמר."


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

    # Prefer AliExpress API discount if meaningful
    if discount_text and discount_text != "0%":
        return f"💸 <b>{price_text}</b>  (-{escape(str(discount_text))})"

    # Otherwise calculate discount only if original price is higher
    calculated_discount = _discount_percent(price, original_price)

    if original_price and calculated_discount:
        original_text = f"{currency_symbol}{float(original_price):.2f}"
        return f"💸 <b>{price_text}</b>  <s>{original_text}</s>  (-{calculated_discount}%)"

    return f"💸 <b>{price_text}</b>"


def build_telegram_message(product, enrichment: dict, settings) -> str:
    # Prefer AI display title if you add it later, otherwise use API title
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

    raw_verdict = enrichment.get("buy_verdict") or ""
    verdict = escape(score_based_verdict(score, raw_verdict))

    price_line = _format_price_line(product, settings)

    rating = get_product_value(product, "rating")
    orders = get_product_value(product, "orders")
    shipping = get_product_value(product, "shipping")
    category = get_product_value(product, "category")
    shop_name = get_product_value(product, "shop_name")
    commission_rate = get_product_value(product, "commission_rate")

    rating_line = f"⭐ <b>דירוג:</b> {rating}/5" if rating else "⭐ <b>דירוג:</b> לא ידוע"
    orders_line = f"📦 <b>נמכרו:</b> {int(orders):,}+" if orders else "📦 <b>נמכרו:</b> לא ידוע"

    if shipping and "free" in str(shipping).lower():
        shipping_text = "משלוח חינם"
    elif shipping:
        shipping_text = str(shipping)
    else:
        shipping_text = "משלוח משתנה"

    shipping_line = f"🚚 <b>{escape(shipping_text)}</b>"

    meta_lines = []
    if category:
        meta_lines.append(f"🏷️ <b>קטגוריה:</b> {escape(str(category))}")
    if shop_name:
        meta_lines.append(f"🏪 <b>חנות:</b> {escape(str(shop_name))}")

    tags = format_tags(enrichment.get("tags", []))

    lines = [
        f"🔥 <b>{title}</b>",
        "",
        f"⚡ {description}",
        "",
        score_line,
        "",
        price_line,
        rating_line,
        orders_line,
        shipping_line,
    ]

    if meta_lines:
        lines.extend(["", *meta_lines])

    lines.extend(
        [
            "",
            "🧠 <b>שורה תחתונה:</b>",
            verdict,
            "",
            tags,
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
    now = datetime.now(ZoneInfo("Asia/Jerusalem"))
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

    # Fallback to AliExpress category if available
    if product is not None:
        ali_category = get_product_value(product, "category")
        if ali_category:
            return str(ali_category).strip().lower()

    return "general"


class DealEngine:
    def __init__(self, settings: Settings):
        self.settings = settings

        self.aliexpress = AliExpressClient(settings)
        self.telegram = TelegramClient(settings)
        self.ollama = OllamaClient(settings)

        self.product_client = self._build_product_client()

    def _build_product_client(self):
        """
        Product source selection.

        Recommended now:
        PRODUCT_SOURCE=seed_urls

        seed_urls:
            data/products_seed.json contains AliExpress URLs only.
            The AliExpress API enriches them with real product data and promotion_link.

        seed:
            old manual Product JSON format.

        aliexpress_api:
            future mode for real keyword search.
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

    async def discover_and_queue(self) -> None:
        """
        Search products from AliExpress, filter, enrich, score,
        and save good candidates into product_queue.
        """
        init_product_queue()

        current_size = queue_size()
        if current_size >= self.settings.queue_target_size:
            console.print(
                f"[green]Queue already has {current_size} products. "
                f"Target is {self.settings.queue_target_size}. Skipping discovery.[/green]"
            )
            return

        queued_count = 0
        checked_count = 0

        source = (self.settings.product_source or "seed_urls").lower()

        if source in ["seed_urls", "seed"]:
            keywords = ["seed_urls"]
        else:
            keywords = list(self.settings.keyword_list)
            random.shuffle(keywords)

            if getattr(self.settings, "enable_hot_topics", False):
                hot_topic_ids = self.settings.hot_topics_topic_id_list

                if hot_topic_ids:
                    for topic_id in hot_topic_ids:
                        keywords.append(f"hot_topic:{topic_id}")
                else:
                    keywords.append("hot_topics")

        for keyword in keywords:
            if current_size >= self.settings.queue_target_size:
                console.print(
                    f"[green]Queue already has {current_size} products. "
                    f"Target is {self.settings.queue_target_size}. Skipping discovery.[/green]"
                )
                return

            if queued_count >= self.settings.discovery_max_candidates_per_run:
                console.print("Reached discovery candidate limit.")
                return

            if queue_size() >= self.settings.queue_target_size:
                console.print("Queue target reached."
                              f"Checked={checked_count}, queued={queued_count}, Wasn't queued={checked_count - queued_count}, queue_size={queue_size()}"
                              )
                return
            page_no = random.randint(1, 3)

            sort = random.choice([
                "LAST_VOLUME_DESC",
                "SALE_PRICE_DESC",
            ])

            if str(keyword).startswith("hot_topic_keyword:"):
                display_keyword = str(keyword).split(":", 1)[1]
                print(f"Discovering HOT TOPIC: {display_keyword} | page={page_no} | sort={sort}")
            else:
                print(f"Discovering: {keyword} | page={page_no} | sort={sort}")

            try:
                if str(keyword).startswith("hot_topic:"):
                    topic_id = str(keyword).split(":", 1)[1]

                    products = await self.aliexpress.search_hot_topic_products(
                        topic_id=topic_id,
                        limit=self.settings.hot_topics_limit,
                        page_no=page_no,
                    )

                elif keyword == "hot_topics":
                    products = await self.aliexpress.search_hot_topic_products(
                        topic_id=None,
                        limit=self.settings.hot_topics_limit,
                        page_no=page_no,
                    )

                else:
                    if str(keyword).startswith("hot_topic_keyword:"):
                        topic_keyword = str(keyword).split(":", 1)[1]

                        products = await self.aliexpress.get_hot_products(
                            keyword=topic_keyword,
                            limit=self.settings.hot_topics_per_request,
                            page_no=page_no,
                            sort=sort,
                        )

                    else:
                        products = await self.product_client.search_products(
                            keyword=keyword,
                            limit=50,
                            page_no=page_no,
                            sort=sort,
                        )
            except Exception as e:
                console.print(f"[red]Search failed for {keyword}: {e}[/red]")
                continue

            for product in products:
                checked_count += 1

                product_id = get_product_value(product, "product_id")
                product_url = get_product_value(product, "product_url")
                affiliate_url = get_product_value(product, "affiliate_url")
                title = get_product_value(product, "title", "AliExpress Product")

                if not product_id or not product_url:
                    continue

                if was_queued(product_id):
                    console.print(f"Already queued: {product_id}")
                    continue

                # Also avoid reposting already posted products from the old posted DB
                if was_posted(product_id):
                    console.print(f"Already posted before: {product_id}")
                    continue

                allowed, reason = is_good_deal(product, self.settings)
                if not allowed:
                    console.print(f"Skipping {product_id}: {reason}")
                    continue

                enrichment = await self.ollama.enrich_product(product)
                score = int(enrichment.get("deal_score", 0))

                if score < self.settings.min_deal_score_to_post:
                    console.print(
                        f"Skipping {product_id}: score {score} below "
                        f"{self.settings.min_deal_score_to_post}"
                    )
                    continue

                product_data = product_to_dict(product)

                if str(keyword).startswith("hot_topic:"):
                    source_category = "hot_topics"
                elif keyword == "hot_topics":
                    source_category = "hot_topics"
                else:
                    if str(keyword).startswith("hot_topic_keyword:"):
                        topic_keyword = str(keyword).split(":", 1)[1]
                        source_category = keyword_to_category(topic_keyword, product)
                    else:
                        source_category = keyword_to_category(keyword, product)
                inserted = enqueue_product(
                    product_id=str(product_id),
                    product_url=str(product_url),
                    affiliate_url=str(affiliate_url or product_url),
                    title=str(title),
                    score=score,
                    source_keyword=keyword,
                    source_category=source_category,
                    product_data=product_data,
                    enrichment_data=enrichment,
                )

                if inserted:
                    queued_count += 1
                    console.print(
                        f"[green]Queued:[/green] {product_id} "
                        f"score={score} keyword={keyword} category={source_category}"
                    )

        console.print(
            f"[bold]Discovery finished.[/bold] "
            f"Checked={checked_count}, queued={queued_count}, Wasn't queued={checked_count-queued_count}, queue_size={queue_size()}"
        )

    async def post_next_from_queue(
            self,
            force: bool = False,
            excluded_categories: set[str] | None = None,
    ) -> dict | None:
        """
        Post the highest-scoring queued product to Telegram.
        Returns the DB queue row, not the AliExpress product JSON.
        """
        init_product_queue()

        if not force and not is_active_posting_hour(self.settings):
            console.print("Outside active posting hours. Skipping post.")
            return None

        recent_categories = get_recent_posted_categories(
            self.settings.category_rotation_window
        )

        console.print(
            f"Category rotation window={self.settings.category_rotation_window} | "
            f"recent={recent_categories or 'none'}"
        )
        console.print(
            f"Recent posted categories: {recent_categories or 'none'}"
        )

        queue_row = get_next_queued_product(
            rotation_window=self.settings.category_rotation_window,
            excluded_categories=excluded_categories,
        )

        if not queue_row:
            console.print("Queue is empty. Running discovery first...")
            await self.discover_and_queue()

            queue_row = get_next_queued_product(
                rotation_window=self.settings.category_rotation_window,
                excluded_categories=excluded_categories,
            )

            if not queue_row:
                console.print("Queue still empty. Nothing to post.")
                return None

        product_data, enrichment = product_from_queue_row(queue_row)

        try:
            message = build_telegram_message(product_data, enrichment, self.settings)
            await self.telegram.send_product(product_data, message)

            mark_queue_posted(queue_row["id"])
            mark_posted(str(queue_row["product_id"]))

            console.print(
                f"[green]Posted from queue:[/green] "
                f"id={queue_row.get('id')} "
                f"product_id={queue_row.get('product_id')} "
                f"score={queue_row.get('score')} "
                f"category={queue_row.get('source_category')}"
            )

            return queue_row

        except Exception as e:
            mark_skipped(queue_row["id"], str(e))
            console.print(f"[red]Failed to post queued product: {e}[/red]")
            raise

    async def post_batch_from_queue(self, force: bool = False, dry_run: bool = False) -> None:
        """
        Post multiple queued products in one batch.
        Keeps categories diverse inside the batch.
        Example: 3 posts every 3 hours.
        """
        posts_per_batch = getattr(self.settings, "posts_per_batch", 3)

        posted = 0
        selected_categories_this_batch: set[str] = set()

        for index in range(posts_per_batch):
            console.print(
                f"[bold]Posting batch item {index + 1}/{posts_per_batch}[/bold]"
            )

            try:
                queue_row = await self.post_next_from_queue(
                    force=force,
                    excluded_categories=selected_categories_this_batch,
                )

                if not queue_row:
                    console.print("[yellow]No queued product available for this batch item.[/yellow]")
                    break

                category = queue_row.get("source_category")

                if category:
                    selected_categories_this_batch.add(category)

                posted += 1

                console.print(
                    "[cyan]Batch selected:[/cyan] "
                    f"id={queue_row.get('id')} | "
                    f"score={queue_row.get('score')} | "
                    f"category={category} | "
                    f"title={queue_row.get('title', '')[:80]}"
                )

            except Exception as e:
                console.print(f"[red]Failed posting batch item {index + 1}: {e}[/red]")
                break

            # Small delay between Telegram posts so it doesn't look spammy
            if index < posts_per_batch - 1:
                await asyncio.sleep(5)

        console.print(
            f"[green]Batch posting finished. Posted {posted}/{posts_per_batch}.[/green]"
        )

    async def run_once(self) -> None:
        """
        Manual test mode:
        Fill queue if needed, then post one product immediately.
        """
        await self.discover_and_queue()
        # await self.post_next_from_queue(force=True)
