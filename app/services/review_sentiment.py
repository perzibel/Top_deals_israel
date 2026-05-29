from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass
class ReviewSentimentResult:
    sentiment: str
    score_modifier: int
    reason: str
    comments_used: int


GOOD_WORDS = [
    "good",
    "great",
    "excellent",
    "perfect",
    "fast",
    "quality",
    "recommend",
    "works",
    "satisfied",
    "amazing",
    "nice",
    "love",
    "best",
    "מעולה",
    "טוב",
    "איכותי",
    "מהיר",
    "ממליץ",
    "מרוצה",
    "מצוין",
    "שווה",
]

BAD_WORDS = [
    "bad",
    "poor",
    "broken",
    "damaged",
    "fake",
    "slow",
    "late",
    "refund",
    "not working",
    "doesn't work",
    "dont work",
    "do not work",
    "terrible",
    "waste",
    "scam",
    "גרוע",
    "שבור",
    "לא עובד",
    "לא הגיע",
    "איטי",
    "פגום",
    "זבל",
    "מאכזב",
    "החזר",
]


def normalize_comment(comment: Any) -> str:
    if comment is None:
        return ""

    if isinstance(comment, str):
        return comment.strip()

    if isinstance(comment, dict):
        for key in ["text", "comment", "review", "content", "feedback"]:
            value = comment.get(key)
            if value:
                return str(value).strip()

    return str(comment).strip()


def set_product_value(product: Any, key: str, value: Any) -> None:
    """
    Safely set a value on either:
    - dict product
    - Product object
    """

    if product is None:
        return

    if isinstance(product, dict):
        product[key] = value
        return

    setattr(product, key, value)


def extract_latest_comments(product: dict[str, Any], limit: int = 5) -> list[str]:
    """
    Tries to extract latest comments from different possible product structures.

    This is defensive because AliExpress responses may differ depending on endpoint/SDK.
    """

    possible_keys = [
        "latest_comments",
        "latest_reviews",
        "reviews",
        "comments",
        "feedback",
        "buyer_comments",
    ]

    comments: list[str] = []

    for key in possible_keys:
        value = get_product_value(product, key)

        if not value:
            continue

        if isinstance(value, str):
            # Sometimes comments may arrive as JSON string or plain text
            parsed = try_parse_json(value)
            if isinstance(parsed, list):
                comments.extend(normalize_comment(item) for item in parsed)
            else:
                comments.append(value)

        elif isinstance(value, list):
            comments.extend(normalize_comment(item) for item in value)

        elif isinstance(value, dict):
            nested_items = (
                value.get("items")
                or value.get("data")
                or value.get("reviews")
                or value.get("comments")
                or []
            )

            if isinstance(nested_items, list):
                comments.extend(normalize_comment(item) for item in nested_items)

    clean_comments = [
        comment for comment in comments
        if comment and len(comment.strip()) >= 3
    ]

    return clean_comments[:limit]


def try_parse_json(value: str) -> Any:
    try:
        return json.loads(value)
    except Exception:
        return None

def get_product_value(product: Any, key: str, default: Any = None) -> Any:
    """
    Safely get a value from either:
    - dict product
    - dataclass / normal Product object
    """

    if product is None:
        return default

    if isinstance(product, dict):
        return product.get(key, default)

    return getattr(product, key, default)


def classify_reviews_simple(comments: Iterable[str]) -> ReviewSentimentResult:
    comments_list = [comment for comment in comments if comment]

    if not comments_list:
        return ReviewSentimentResult(
            sentiment="unknown",
            score_modifier=0,
            reason="No recent comments found.",
            comments_used=0,
        )

    combined = " ".join(comments_list).lower()

    good_hits = count_keyword_hits(combined, GOOD_WORDS)
    bad_hits = count_keyword_hits(combined, BAD_WORDS)

    if bad_hits > good_hits:
        return ReviewSentimentResult(
            sentiment="bad",
            score_modifier=-10,
            reason=f"Recent comments look negative. Bad signals: {bad_hits}, good signals: {good_hits}.",
            comments_used=len(comments_list),
        )

    if good_hits > bad_hits:
        return ReviewSentimentResult(
            sentiment="good",
            score_modifier=10,
            reason=f"Recent comments look positive. Good signals: {good_hits}, bad signals: {bad_hits}.",
            comments_used=len(comments_list),
        )

    return ReviewSentimentResult(
        sentiment="mixed",
        score_modifier=0,
        reason=f"Recent comments are mixed or unclear. Good signals: {good_hits}, bad signals: {bad_hits}.",
        comments_used=len(comments_list),
    )


def count_keyword_hits(text: str, keywords: list[str]) -> int:
    hits = 0

    for keyword in keywords:
        pattern = re.escape(keyword.lower())
        hits += len(re.findall(pattern, text))

    return hits


def get_review_sentiment_for_product(product: dict[str, Any]) -> ReviewSentimentResult:
    latest_comments = extract_latest_comments(product)
    return classify_reviews_simple(latest_comments)