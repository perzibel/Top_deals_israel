import json
from datetime import datetime, timezone
from typing import Optional

from app.storage.paths import get_conn


def init_social_posts() -> None:
    with get_conn() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS social_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id TEXT NOT NULL,
            product_url TEXT,
            affiliate_url TEXT,
            product_title TEXT,
            product_code TEXT,
            score REAL,
            category TEXT,
            media_type TEXT,
            image_url TEXT,
            video_url TEXT,
            caption_he TEXT,
            model_reason TEXT,
            status TEXT DEFAULT 'draft',
            created_at TEXT NOT NULL,
            scheduled_for TEXT,
            published_at TEXT,
            raw_json TEXT
        )
        """)

        conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_social_posts_product_media
        ON social_posts(product_id, media_type)
        """)


def save_social_post(
    *,
    product_id: str,
    product_url: Optional[str],
    affiliate_url: Optional[str],
    product_title: str,
    product_code: str,
    score: float,
    category: Optional[str],
    media_type: str,
    image_url: Optional[str],
    video_url: Optional[str],
    caption_he: str,
    model_reason: str,
    scheduled_for: Optional[str],
    raw: dict,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO social_posts (
                product_id,
                product_url,
                affiliate_url,
                product_title,
                product_code,
                score,
                category,
                media_type,
                image_url,
                video_url,
                caption_he,
                model_reason,
                status,
                created_at,
                scheduled_for,
                raw_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?)
            """,
            (
                product_id,
                product_url,
                affiliate_url,
                product_title,
                product_code,
                score,
                category,
                media_type,
                image_url,
                video_url,
                caption_he,
                model_reason,
                datetime.now(timezone.utc).isoformat(),
                scheduled_for,
                json.dumps(raw, ensure_ascii=False),
            ),
        )