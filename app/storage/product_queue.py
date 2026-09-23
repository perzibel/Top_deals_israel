import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.storage.paths import get_conn

log = logging.getLogger(__name__)

# Keeps one popular keyword from filling the whole queue.
MAX_QUEUED_PER_CATEGORY = 5


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(row["name"] == column_name for row in rows)


def init_product_queue() -> None:
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS product_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id TEXT NOT NULL UNIQUE,
                product_url TEXT NOT NULL,
                affiliate_url TEXT,
                title TEXT NOT NULL,
                score INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                source_keyword TEXT,
                source_category TEXT,
                product_json TEXT NOT NULL,
                enrichment_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                posted_at TEXT,
                skipped_reason TEXT
            )
            """
        )

        # Migration for existing DBs
        if not _column_exists(conn, "product_queue", "source_category"):
            conn.execute(
                """
                ALTER TABLE product_queue
                ADD COLUMN source_category TEXT
                """
            )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_product_queue_status_score
            ON product_queue(status, score DESC, created_at ASC)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_product_queue_posted_category
            ON product_queue(status, posted_at, source_category)
            """
        )


def queue_size() -> int:
    init_product_queue()

    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM product_queue
            WHERE status = 'queued'
            """
        ).fetchone()

    return int(row["count"])


def queued_count_for_category(source_category: str) -> int:
    init_product_queue()

    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM product_queue
            WHERE status = 'queued'
              AND source_category = ?
            """,
            (source_category,),
        ).fetchone()

    return int(row["count"])


def was_queued(product_id: str) -> bool:
    """True if the product is currently waiting in the queue."""
    init_product_queue()

    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT id
            FROM product_queue
            WHERE product_id = ?
              AND status = 'queued'
            """,
            (product_id,),
        ).fetchone()

    return row is not None


def enqueue_product(
        product_id: str,
        product_url: str,
        affiliate_url: str,
        title: str,
        score: int,
        source_keyword: str,
        source_category: str,
        product_data: dict,
        enrichment_data: dict,
) -> bool:
    """
    Returns True if inserted, False if already exists.
    """
    init_product_queue()

    if source_category and queued_count_for_category(source_category) >= MAX_QUEUED_PER_CATEGORY:
        log.debug("Skipping %s: too many queued products in category %s", product_id, source_category)
        return False

    try:
        with get_conn() as conn:
            # A product that was posted or skipped before can come back (e.g. a
            # repost after a price drop); only a row that is still queued blocks it.
            cursor = conn.execute(
                """
                INSERT INTO product_queue (
                    product_id,
                    product_url,
                    affiliate_url,
                    title,
                    score,
                    status,
                    source_keyword,
                    source_category,
                    product_json,
                    enrichment_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?)
                ON CONFLICT(product_id) DO UPDATE SET
                    product_url = excluded.product_url,
                    affiliate_url = excluded.affiliate_url,
                    title = excluded.title,
                    score = excluded.score,
                    status = 'queued',
                    source_keyword = excluded.source_keyword,
                    source_category = excluded.source_category,
                    product_json = excluded.product_json,
                    enrichment_json = excluded.enrichment_json,
                    created_at = excluded.created_at,
                    skipped_reason = NULL
                WHERE product_queue.status != 'queued'
                """,
                (
                    product_id,
                    product_url,
                    affiliate_url,
                    title,
                    int(score),
                    source_keyword,
                    source_category,
                    json.dumps(product_data, ensure_ascii=False),
                    json.dumps(enrichment_data, ensure_ascii=False),
                    now_iso(),
                ),
            )

        return cursor.rowcount > 0

    except sqlite3.IntegrityError:
        return False


def last_post_time() -> Optional[datetime]:
    init_product_queue()

    with get_conn() as conn:
        row = conn.execute(
            "SELECT MAX(posted_at) AS last FROM product_queue WHERE status = 'posted'"
        ).fetchone()

    return datetime.fromisoformat(row["last"]) if row and row["last"] else None


def get_queue_row(product_id: str) -> Optional[dict]:
    init_product_queue()

    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM product_queue WHERE product_id = ?",
            (str(product_id),),
        ).fetchone()

    return dict(row) if row else None


def expire_stale_queued(max_age_days: int) -> int:
    """Skip queued products older than max_age_days. Returns how many were expired."""
    init_product_queue()

    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()

    with get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE product_queue
            SET status = 'skipped',
                skipped_reason = ?
            WHERE status = 'queued'
              AND created_at < ?
            """,
            (f"expired: queued more than {max_age_days} days", cutoff),
        )

    return cursor.rowcount


def update_queued_product(queue_id: int, product_data: dict, enrichment_data: dict, score: int) -> None:
    """Refresh a queued row with re-fetched product data before posting."""
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE product_queue
            SET product_json = ?,
                enrichment_json = ?,
                score = ?
            WHERE id = ?
            """,
            (
                json.dumps(product_data, ensure_ascii=False),
                json.dumps(enrichment_data, ensure_ascii=False),
                int(score),
                queue_id,
            ),
        )


def select_best_diverse_product(
    rows: list[sqlite3.Row],
    recent_categories: list[str],
    rotation_window: int = 5,
    excluded_categories: set[str] | None = None,
) -> Optional[sqlite3.Row]:
    excluded_categories = excluded_categories or set()

    if not rows:
        return None

    recent_set = set(recent_categories[:rotation_window])
    last_category = recent_categories[0] if recent_categories else None

    # 1. Best case:
    # Category was not recently posted and not already selected in this batch.
    fresh_candidates = [
        row for row in rows
        if row["source_category"]
        and row["source_category"] not in recent_set
        and row["source_category"] not in excluded_categories
    ]

    if fresh_candidates:
        return max(
            fresh_candidates,
            key=lambda row: (int(row["score"]), row["created_at"])
        )

    # 2. Fallback:
    # Avoid same category as last post and avoid categories already selected in batch.
    fallback_candidates = [
        row for row in rows
        if row["source_category"] != last_category
        and row["source_category"] not in excluded_categories
    ]

    if fallback_candidates:
        return max(
            fallback_candidates,
            key=lambda row: (int(row["score"]), row["created_at"])
        )

    # 3. Final fallback:
    # Anything goes.
    return max(
        rows,
        key=lambda row: (int(row["score"]), row["created_at"])
    )


def simulate_next_posts(count: int = 10, rotation_window: int = 5) -> None:
    """
    Simulates future posts without updating the DB.
    Uses strict category rotation.
    """
    init_product_queue()

    # newest first
    recent_categories = get_recent_posted_categories(rotation_window)

    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM product_queue
            WHERE status = 'queued'
            ORDER BY score DESC, created_at ASC
            """
        ).fetchall()

    simulated_queue = [dict(row) for row in rows]
    simulated_posts = []

    for i in range(count):
        if not simulated_queue:
            break

        recent_set = set(recent_categories[:rotation_window])
        last_category = recent_categories[0] if recent_categories else None

        # Best option: category not used recently
        fresh_candidates = [
            p for p in simulated_queue
            if p.get("source_category")
            and p.get("source_category") not in recent_set
        ]

        # Fallback: avoid only the latest category
        if not fresh_candidates:
            fresh_candidates = [
                p for p in simulated_queue
                if p.get("source_category") != last_category
            ]

        # Final fallback: anything
        if not fresh_candidates:
            fresh_candidates = simulated_queue

        selected = max(
            fresh_candidates,
            key=lambda p: (
                int(p.get("score", 0)),
                p.get("created_at", "")
            )
        )

        simulated_queue.remove(selected)
        simulated_posts.append(selected)

        if selected.get("source_category"):
            recent_categories.insert(0, selected["source_category"])

    print("\n=== SIMULATED NEXT POSTS ===")
    for index, product in enumerate(simulated_posts, start=1):
        print(
            f"{index:>2}. "
            f"{product['id']} | "
            f"{product['score']}/100 | "
            f"{product['source_category']} | "
            f"{product['title'][:80]}"
        )


def get_recent_posted_categories(limit: int = 3) -> list[str]:
    init_product_queue()

    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT source_category
            FROM product_queue
            WHERE status = 'posted'
              AND source_category IS NOT NULL
              AND source_category != ''
            ORDER BY posted_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [row["source_category"] for row in rows]


def get_next_queued_product(
    rotation_window: int = 5,
    excluded_categories: set[str] | None = None,
    excluded_ids: set[int] | None = None,
) -> Optional[dict]:
    init_product_queue()

    recent_categories = get_recent_posted_categories(rotation_window)

    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM product_queue
            WHERE status = 'queued'
            ORDER BY score DESC, created_at DESC
            LIMIT 200
            """
        ).fetchall()

    if excluded_ids:
        rows = [row for row in rows if row["id"] not in excluded_ids]

    selected = select_best_diverse_product(
        rows=rows,
        recent_categories=recent_categories,
        rotation_window=rotation_window,
        excluded_categories=excluded_categories,
    )

    return dict(selected) if selected else None


def preview_next_queued_product(rotation_window: int = 3) -> Optional[dict]:
    """
    Test-only preview.
    Picks the same next product, but does not update DB and does not publish.
    """
    product = get_next_queued_product(rotation_window=rotation_window)

    if not product:
        print("No queued product found.")
        return None

    print("\n=== NEXT PRODUCT PREVIEW ===")
    print(f"Queue ID: {product.get('id')}")
    print(f"Product ID: {product.get('product_id')}")
    print(f"Score: {product.get('score')}/100")
    print(f"Category: {product.get('source_category')}")
    print(f"Keyword: {product.get('source_keyword')}")
    print(f"Title: {product.get('title')}")
    print(f"URL: {product.get('affiliate_url') or product.get('product_url')}")
    print("============================\n")

    return product


def preview_candidate_ranking(rotation_window: int = 3, limit: int = 20) -> None:
    """
    Debug preview.
    Shows top queued products and recent posted categories.
    Does not publish or update anything.
    """
    init_product_queue()

    recent_categories_list = get_recent_posted_categories(rotation_window)
    recent_categories = set(recent_categories_list)
    last_category = recent_categories_list[0] if recent_categories_list else None

    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM product_queue
            WHERE status = 'queued'
            ORDER BY score DESC, created_at ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    print("\n=== RECENT POSTED CATEGORIES ===")
    print(recent_categories_list)

    print("\n=== TOP QUEUED CANDIDATES ===")

    for row in rows:
        category = row["source_category"]
        reason = "eligible"

        if category == last_category:
            reason = "same as last category"
        elif category in recent_categories:
            reason = "recent category"

        print(
            f"{row['id']:>4} | "
            f"{row['score']:>3}/100 | "
            f"{category or 'no-category':<20} | "
            f"{reason:<22} | "
            f"{row['title'][:80]}"
        )

    selected = get_next_queued_product(rotation_window=rotation_window)

    print("\n=== SELECTED ===")
    if selected:
        print(
            f"{selected['id']} | "
            f"{selected['score']}/100 | "
            f"{selected['source_category']} | "
            f"{selected['title']}"
        )
    else:
        print("No product selected.")


def mark_posted(queue_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE product_queue
            SET status = 'posted',
                posted_at = ?
            WHERE id = ?
            """,
            (now_iso(), queue_id),
        )


def mark_skipped(queue_id: int, reason: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE product_queue
            SET status = 'skipped',
                skipped_reason = ?
            WHERE id = ?
            """,
            (reason[:500], queue_id),
        )
