from app.storage.paths import get_conn


def init_db() -> None:
    with get_conn() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS posted_products (
                product_id TEXT PRIMARY KEY,
                posted_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def was_posted(product_id: str) -> bool:
    with get_conn() as con:
        row = con.execute(
            "SELECT 1 FROM posted_products WHERE product_id = ? LIMIT 1",
            (product_id,),
        ).fetchone()
    return row is not None


def mark_posted(product_id: str) -> None:
    with get_conn() as con:
        # REPLACE refreshes posted_at so repost cooldowns count from the latest post.
        con.execute(
            "INSERT OR REPLACE INTO posted_products(product_id, posted_at) "
            "VALUES (?, CURRENT_TIMESTAMP)",
            (product_id,),
        )


def last_posted_at(product_id: str) -> str | None:
    with get_conn() as con:
        row = con.execute(
            "SELECT posted_at FROM posted_products WHERE product_id = ?",
            (product_id,),
        ).fetchone()
    return row["posted_at"] if row else None


init_db()
