import sqlite3
from pathlib import Path
DB_PATH = Path("deal_engine.sqlite3")


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS posted_products (
                product_id TEXT PRIMARY KEY,
                posted_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        con.execute(
            """
            CREATE TABLE IF NOT EXISTS user_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                username TEXT,
                message_text TEXT,
                product_url TEXT,
                priority INTEGER DEFAULT 0,
                status TEXT DEFAULT 'queued',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                started_at TEXT,
                completed_at TEXT,
                error TEXT
            )
            """
        )

        rows = con.execute("PRAGMA table_info(user_requests)").fetchall()

        print("user_requests columns:")
        for row in rows:
            print(row)

        con.commit()


def was_posted(product_id: str) -> bool:
    with sqlite3.connect(DB_PATH) as con:
        row = con.execute(
            "SELECT 1 FROM posted_products WHERE product_id = ? LIMIT 1",
            (product_id,),
        ).fetchone()
    return row is not None


def mark_posted(product_id: str) -> None:
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            "INSERT OR IGNORE INTO posted_products(product_id) VALUES (?)",
            (product_id,),
        )
        con.commit()
