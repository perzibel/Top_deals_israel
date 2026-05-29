import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


DB_PATH = Path("deal_engine.sqlite3")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_affiliate_cache() -> None:
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS affiliate_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_url TEXT NOT NULL UNIQUE,
                affiliate_url TEXT NOT NULL,
                provider TEXT NOT NULL DEFAULT 'affiracle_telegram',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )


def get_cached_affiliate_link(product_url: str) -> Optional[str]:
    init_affiliate_cache()

    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT affiliate_url
            FROM affiliate_links
            WHERE product_url = ?
            """,
            (product_url,),
        ).fetchone()

    return row["affiliate_url"] if row else None


def save_affiliate_link(
    product_url: str,
    affiliate_url: str,
    provider: str = "affiracle_telegram",
) -> None:
    init_affiliate_cache()

    timestamp = now_iso()

    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO affiliate_links (
                product_url,
                affiliate_url,
                provider,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(product_url)
            DO UPDATE SET
                affiliate_url = excluded.affiliate_url,
                provider = excluded.provider,
                updated_at = excluded.updated_at
            """,
            (
                product_url,
                affiliate_url,
                provider,
                timestamp,
                timestamp,
            ),
        )