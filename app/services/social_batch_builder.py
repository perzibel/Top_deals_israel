from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.storage.social_posts import save_social_post
from app.services.social_post_generator import generate_social_post
from app.services.social_media_picker import choose_media_type

from app.services.hot_product_filters import is_target_hot_product


ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")


def get_product_value(product, key: str, default=None):
    if isinstance(product, dict):
        return product.get(key, default)

    return getattr(product, key, default)


def product_identity(product) -> str:
    return str(
        get_product_value(product, "product_id")
        or get_product_value(product, "item_id")
        or get_product_value(product, "id")
        or ""
    )


def diversity_key(product) -> str:
    return str(
        get_product_value(product, "category_name")
        or get_product_value(product, "category")
        or get_product_value(product, "source_topic_id")
        or "unknown"
    )


async def build_nightly_social_posts(
    *,
    aliexpress_client,
    ollama_client,
    telegram_client=None,
    posts_per_day: int = 3,
) -> list[dict]:
    if not hasattr(ollama_client, "generate"):
        raise RuntimeError(
            "OllamaClient is missing generate(prompt). "
            "Add the generic generate method to app/clients/ollama.py"
        )
    all_products = []

    # Pull several pages to get enough variety.
    hot_keywords = [
        "gaming accessories",
        "phone accessories",
        "gadgets",
        "smart home",
        "desk setup",
        "usb charger",
        "type c cable",
        "rgb light",
        "keyboard mouse",
        "phone stand",
        "smart plug",
        "desk mat",
        "monitor light",
        "gadget",
        "Home gadgets"
    ]

    for keyword in hot_keywords:
        products = await aliexpress_client.get_hot_topic_products(
            limit=100,
            page_no=1,
            keywords=keyword,
            max_sale_price=250,
        )

        print(f"[SOCIAL DEBUG] keyword={keyword} products={len(products)}")
        all_products.extend(products)

    candidates = []

    for index, product in enumerate(all_products[:40], start=1):
        is_allowed, filter_reason = is_target_hot_product(
            product,
            max_price_ils=getattr(aliexpress_client.settings, "hot_products_max_price_ils", 250),
        )

        if not is_allowed:
            print(f"[SOCIAL DEBUG] skipped by filter: {filter_reason}")
            continue

        actual_media = choose_media_type(product, "either")

        if actual_media == "missing":
            print("[SOCIAL DEBUG] skipped: missing media")
            continue

        try:
            draft = await generate_social_post(
                ollama_client=ollama_client,
                product=product,
                media_type=actual_media,
            )
        except Exception as e:
            print(
                f"[SOCIAL DEBUG] generation failed for "
                f"product_id={product_identity(product)}: {type(e).__name__}: {e}"
            )
            continue

        score = float(draft.get("score", 0) or 0)
        should_publish = bool(draft.get("should_publish"))

        print(
            f"[SOCIAL DEBUG] product_id={draft.get('product_id')} "
            f"score={score} "
            f"should_publish={should_publish} "
            f"media={draft.get('media_type')} "
            f"title={draft.get('short_title_he')} "
            f"reason={draft.get('reason')}"
        )

        # Temporary debug threshold
        if score >= 60:
            draft["_diversity_key"] = diversity_key(product)
            candidates.append(draft)

        if len(candidates) >= 12:
            print("[SOCIAL DEBUG] enough candidates collected, stopping AI calls")
            break

    # Sort by score, highest first.
    candidates.sort(key=lambda x: float(x.get("score", 0)), reverse=True)

    selected = []
    used_categories = set()
    used_products = set()
    required_media = ["image", "video", "either"]

    for wanted_media in required_media:
        for candidate in candidates:
            product_id = candidate.get("product_id")
            category = candidate.get("_diversity_key")
            media_type = candidate.get("media_type")

            if product_id in used_products:
                continue

            if category in used_categories:
                continue

            if wanted_media == "video" and media_type != "video":
                continue

            if wanted_media == "image" and media_type != "image":
                continue

            selected.append(candidate)
            used_products.add(product_id)
            used_categories.add(category)
            break

    # Fill missing slots with best remaining.
    for candidate in candidates:
        if len(selected) >= posts_per_day:
            break

        product_id = candidate.get("product_id")
        if product_id in used_products:
            continue

        selected.append(candidate)
        used_products.add(product_id)

    print(f"[SOCIAL DEBUG] total_products={len(all_products)}")
    print(f"[SOCIAL DEBUG] candidates_after_ai={len(candidates)}")
    print(f"[SOCIAL DEBUG] selected_count={len(selected)}")

    tomorrow = datetime.now(ISRAEL_TZ).date() + timedelta(days=1)
    schedule_times = ["10:30", "15:00", "20:30"]

    for idx, draft in enumerate(selected[:posts_per_day]):
        scheduled_for = f"{tomorrow}T{schedule_times[idx]}:00+03:00"

        save_social_post(
            product_id=draft["product_id"],
            product_url=draft.get("product_url"),
            affiliate_url=draft.get("affiliate_url"),
            product_title=draft.get("short_title_he"),
            product_code=draft.get("product_code"),
            score=float(draft.get("score", 0)),
            category=draft.get("category"),
            media_type=draft.get("media_type"),
            image_url=draft.get("image_url"),
            video_url=draft.get("video_url"),
            caption_he=draft.get("caption_he"),
            model_reason=draft.get("reason"),
            scheduled_for=scheduled_for,
            raw=draft,
        )

    print(f"[SOCIAL DEBUG] total_products={len(all_products)}")
    print(f"[SOCIAL DEBUG] candidates_after_ai={len(candidates)}")
    print(f"[SOCIAL DEBUG] selected_count={len(selected)}")

    if telegram_client:
        for draft in selected[:posts_per_day]:
            message = f"""
🆕 טיוטת פוסט חדשה

ציון: {draft.get("score")}/100
קטגוריה: {draft.get("category")}
מדיה: {draft.get("media_type")}

{draft.get("caption_he")}

סיבה:
{draft.get("reason")}

תמונה:
{draft.get("image_url")}

וידאו:
{draft.get("video_url") or "אין וידאו"}
"""
            await telegram_client.send_message(message)

    return selected[:posts_per_day]