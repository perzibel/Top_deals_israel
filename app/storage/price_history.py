"""
Price observations per product, used to judge whether a "discount" is real.

AliExpress "original prices" are routinely inflated, so the only trustworthy
signal is how today's price compares with what we have seen before.
"""
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Optional

from app.storage.paths import get_conn

# Don't store more than one observation per product inside this window.
MIN_OBSERVATION_GAP = timedelta(hours=6)


@dataclass
class PriceStats:
    count: int
    min_price: float
    median_price: float
    max_price: float
    span_days: float


def init_price_history() -> None:
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id TEXT NOT NULL,
                price_ils REAL NOT NULL,
                original_price_ils REAL,
                seen_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_price_history_product_seen
            ON price_history(product_id, seen_at)
            """
        )


def record_price(
        product_id: str,
        price_ils: Optional[float],
        original_price_ils: Optional[float] = None,
        seen_at: Optional[datetime] = None,
) -> bool:
    """Returns True if a new observation was stored."""
    if not product_id or not price_ils:
        return False

    seen_at = seen_at or datetime.now(timezone.utc)

    with get_conn() as conn:
        last = conn.execute(
            """
            SELECT price_ils, seen_at
            FROM price_history
            WHERE product_id = ?
            ORDER BY seen_at DESC
            LIMIT 1
            """,
            (str(product_id),),
        ).fetchone()

        if last:
            last_seen = datetime.fromisoformat(last["seen_at"])
            same_price = abs(float(last["price_ils"]) - float(price_ils)) < 0.01
            if same_price and abs(seen_at - last_seen) < MIN_OBSERVATION_GAP:
                return False

        conn.execute(
            """
            INSERT INTO price_history (product_id, price_ils, original_price_ils, seen_at)
            VALUES (?, ?, ?, ?)
            """,
            (str(product_id), float(price_ils), original_price_ils, seen_at.isoformat()),
        )

    return True


def get_price_stats(product_id: str, days: int = 30) -> Optional[PriceStats]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT price_ils, seen_at
            FROM price_history
            WHERE product_id = ? AND seen_at >= ?
            ORDER BY seen_at ASC
            """,
            (str(product_id), since),
        ).fetchall()

    if not rows:
        return None

    prices = [float(row["price_ils"]) for row in rows]
    first = datetime.fromisoformat(rows[0]["seen_at"])
    last = datetime.fromisoformat(rows[-1]["seen_at"])

    return PriceStats(
        count=len(prices),
        min_price=min(prices),
        median_price=median(prices),
        max_price=max(prices),
        span_days=(last - first).total_seconds() / 86400,
    )


def backfill_from_product_queue() -> int:
    """Seed history from prices already stored in product_queue rows."""
    inserted = 0

    with get_conn() as conn:
        rows = conn.execute(
            "SELECT product_id, product_json, created_at, posted_at FROM product_queue"
        ).fetchall()

    for row in rows:
        try:
            data = json.loads(row["product_json"])
        except (TypeError, ValueError):
            continue

        seen = row["posted_at"] or row["created_at"]
        if not seen:
            continue

        if record_price(
                row["product_id"],
                data.get("price_ils"),
                data.get("original_price_ils"),
                seen_at=datetime.fromisoformat(seen),
        ):
            inserted += 1

    return inserted


init_price_history()
