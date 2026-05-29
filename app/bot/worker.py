import asyncio
import os
from html import escape

import httpx
from dotenv import load_dotenv

from app.bot.queue import get_next_request, mark_done, mark_failed, init_queue_db
from app.clients.aliexpress import AliExpressClient
from app.clients.ollama import OllamaClient
from app.config import Settings
from app.services.engine import build_telegram_message, get_product_value, set_product_value
from app.services.manual_product_analyzer import ManualProductAnalyzer


def build_manual_review_message(product, enrichment: dict, reasons: list[str], settings: Settings) -> str:
    title = escape(str(get_product_value(product, "title", "מוצר מאליאקספרס")))
    score = int(enrichment.get("deal_score", 0))
    rating = get_product_value(product, "rating")
    orders = get_product_value(product, "orders")
    price_ils = get_product_value(product, "price_ils")
    short_description = escape(str(enrichment.get("short_description", "")))
    verdict = escape(str(enrichment.get("buy_verdict", "")))

    reason_text = "\n".join(
        f"• {escape(str(reason))}" for reason in reasons
    ) or "• לא נמצאה סיבה ברורה."

    price_line = f"מחיר: ₪{float(price_ils):.2f}" if price_ils else "מחיר: לא ידוע"
    rating_line = f"דירוג: {rating}/5" if rating else "דירוג: לא ידוע"
    orders_line = f"הזמנות: {int(orders):,}+" if orders else "הזמנות: לא ידוע"

    if score >= settings.min_deal_score_to_post:
        headline = "✅ <b>בדיקת מוצר: נראה כמו דיל טוב</b>"
    else:
        headline = "⚠️ <b>בדיקת מוצר: נראה חלש יחסית</b>"

    return (
        f"{headline}\n\n"
        f"<b>{title}</b>\n\n"
        f"{short_description}\n\n"
        f"ציון: <b>{score}/100</b>\n"
        f"{price_line}\n"
        f"{rating_line}\n"
        f"{orders_line}\n\n"
        f"<b>סיבת הבדיקה:</b>\n"
        f"{reason_text}\n\n"
        f"<b>שורה תחתונה:</b>\n"
        f"{verdict or 'שווה לבדוק בזהירות לפי הצורך והמחיר בפועל.'}"
    )


def build_alternatives_message(alternatives: list[dict]) -> tuple[str, dict | None]:
    if not alternatives:
        return (
            "לא מצאתי כרגע חלופות מספיק רלוונטיות וטובות למוצר הזה.",
            None,
        )

    lines = [
        "🔁 <b>מצאתי חלופות רלוונטיות יותר:</b>",
        "",
    ]

    buttons = []

    for index, alt in enumerate(alternatives, start=1):
        title = escape(str(alt.get("title", "AliExpress Product")))
        score = int(alt.get("score", 0))
        url = alt.get("url")

        lines.extend(
            [
                f"{index}. <b>{title}</b>",
                f"ציון: <b>{score}/100</b>",
                "",
            ]
        )

        if url:
            buttons.append(
                [
                    {
                        "text": f"🛒 צפייה בחלופה {index}",
                        "url": url,
                    }
                ]
            )

    reply_markup = {"inline_keyboard": buttons} if buttons else None

    return "\n".join(lines), reply_markup


async def send_message(token: str, chat_id: int, text: str, reply_markup=None) -> None:
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }

    if reply_markup:
        import json
        data["reply_markup"] = json.dumps(reply_markup)

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=data,
        )

    print("send result:", response.status_code, response.text)
    response.raise_for_status()


def build_private_result_message(product, enrichment: dict, settings: Settings) -> str:
    base_message = build_telegram_message(product, enrichment, settings)

    score = int(enrichment.get("deal_score", 0))

    if score < 70:
        warning = (
            "\n\n"
            "⚠️ <b>המלצה:</b>\n"
            "הציון נמוך יחסית, אז לא הייתי ממהר לקנות את המוצר הזה.\n"
            "בשלב הבא נוכל לחפש אלטרנטיבה טובה יותר לפי הקטגוריה והתגיות."
        )
    else:
        warning = (
            "\n\n"
            "✅ <b>המלצה:</b>\n"
            "נראה כמו דיל ששווה לבדוק, במיוחד אם זה מוצר שבאמת הייתם קונים גם בלי ההנחה."
        )

    return base_message + warning


async def analyze_request(request: dict, settings: Settings, token: str):
    aliexpress = AliExpressClient(settings)
    ollama = OllamaClient(settings)

    analyzer = ManualProductAnalyzer(
        settings=settings,
        aliexpress_client=aliexpress,
        ollama_client=ollama,
    )

    product_url = request["product_url"]

    result = await analyzer.analyze_link(product_url)

    if result["status"] == "error":
        raise RuntimeError(result.get("reason", "Unknown analysis error"))

    product = result["product"]
    enrichment = result["enrichment"]
    score = int(result.get("score", 0))

    if result["status"] == "good":
        message = build_manual_review_message(
            product=product,
            enrichment=enrichment,
            reasons=result.get("reasons", []),
            settings=settings,
        )

        deal_url = (
                get_product_value(product, "affiliate_url")
                or get_product_value(product, "product_url")
                or product_url
        )

        reply_markup = {
            "inline_keyboard": [
                [
                    {
                        "text": "🛒 לצפייה בדיל",
                        "url": deal_url,
                    }
                ]
            ]
        }

        await send_message(
            token=token,
            chat_id=request["chat_id"],
            text=message,
            reply_markup=reply_markup,
        )

        return score

    # Bad product flow
    reasons = result.get("reasons", [])
    alternatives = result.get("alternatives", [])

    deal_url = (
            get_product_value(product, "affiliate_url")
            or get_product_value(product, "product_url")
            or product_url
    )

    review_reply_markup = {
        "inline_keyboard": [
            [
                {
                    "text": "🛒 צפייה במוצר המקורי",
                    "url": deal_url,
                }
            ]
        ]
    }

    review_message = build_manual_review_message(
        product=product,
        enrichment=enrichment,
        reasons=reasons,
        settings=settings,
    )

    await send_message(
        token=token,
        chat_id=request["chat_id"],
        text=review_message,
        reply_markup=review_reply_markup,
    )

    if alternatives:
        alternatives_message, alternatives_markup = build_alternatives_message(alternatives)

        await send_message(
            token=token,
            chat_id=request["chat_id"],
            text=alternatives_message,
            reply_markup=alternatives_markup,
        )
    else:
        await send_message(
            token=token,
            chat_id=request["chat_id"],
            text="לא מצאתי כרגע חלופות מספיק רלוונטיות וטובות למוצר הזה.",
        )

    return score

    reason_text = "\n".join(
        f"• {escape(str(reason))}" for reason in reasons
    ) or "• לא ידוע"

    title = escape(str(get_product_value(product, "title", "מוצר מאליאקספרס")))

    message = (
        f"⚠️ <b>המוצר הזה נראה חלש יחסית</b>\n\n"
        f"<b>{title}</b>\n\n"
        f"ציון: <b>{score}/100</b>\n\n"
        f"<b>למה?</b>\n"
        f"{reason_text}\n"
    )

    if alternatives:
        message += "\n<b>מצאתי חלופות טובות יותר:</b>\n\n"

        for index, alt in enumerate(alternatives, start=1):
            alt_title = escape(str(alt.get("title", "AliExpress Product")))
            alt_score = int(alt.get("score", 0))
            alt_url = escape(str(alt.get("url", "")))

            message += (
                f"{index}. <b>{alt_title}</b>\n"
                f"ציון: <b>{alt_score}/100</b>\n"
                f"{alt_url}\n\n"
            )
    else:
        message += "\nלא מצאתי כרגע חלופות מספיק טובות."

    await send_message(
        token=token,
        chat_id=request["chat_id"],
        text=message,
    )

    return score


async def main():
    load_dotenv()
    init_queue_db()

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN")

    cooldown = int(os.getenv("QUEUE_COOLDOWN_SECONDS", "30"))
    settings = Settings()

    print("Queue worker started...")

    while True:
        request = get_next_request()

        if not request:
            await asyncio.sleep(5)
            continue

        request_id = request["id"]

        try:
            await send_message(
                token,
                request["chat_id"],
                "🔎 התחלתי לנתח את המוצר שלכם. זה יכול לקחת כמה רגעים...",
            )

            score = await analyze_request(request, settings, token)
            mark_done(request_id, score=score)

        except Exception as e:
            print(f"Request {request_id} failed:", e)
            mark_failed(request_id, str(e))

            await send_message(
                token,
                request["chat_id"],
                (
                    "מצטער, לא הצלחתי לנתח את המוצר הזה כרגע.\n"
                    "אפשר לנסות שוב בעוד כמה דקות."
                ),
            )

        print(f"Cooling down for {cooldown} seconds...")
        await asyncio.sleep(cooldown)


if __name__ == "__main__":
    asyncio.run(main())
