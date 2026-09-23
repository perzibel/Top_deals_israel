"""
One-off migration: merge the legacy root-level deal_engine.sqlite3 (product_queue)
and data/app.db (social_posts) into app/storage/deal_engine.sqlite3.

Safe to run more than once: rows are matched on their natural unique keys.
Run with the scheduler stopped:  python -m scripts.migrate_to_single_db
"""
import sqlite3

from app.storage.paths import DB_PATH, PROJECT_ROOT
from app.storage.product_queue import init_product_queue
from app.storage.social_posts import init_social_posts

LEGACY_QUEUE_DB = PROJECT_ROOT / "deal_engine.sqlite3"
LEGACY_SOCIAL_DB = PROJECT_ROOT / "data" / "app.db"


def copy_table(src_path, table: str, unique_hint: str) -> None:
    if not src_path.exists():
        print(f"skip {table}: {src_path} not found")
        return

    src = sqlite3.connect(src_path)
    src.row_factory = sqlite3.Row
    if not src.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone():
        print(f"skip {table}: not in {src_path}")
        return

    dst = sqlite3.connect(DB_PATH)
    dst_cols = {r[1] for r in dst.execute(f"PRAGMA table_info({table})")}
    rows = src.execute(f"SELECT * FROM {table}").fetchall()

    inserted = 0
    for row in rows:
        data = {k: row[k] for k in row.keys() if k in dst_cols and k != "id"}
        cols = ", ".join(data)
        marks = ", ".join("?" for _ in data)
        cur = dst.execute(
            f"INSERT OR IGNORE INTO {table} ({cols}) VALUES ({marks})",
            tuple(data.values()),
        )
        inserted += cur.rowcount

    dst.commit()
    print(f"{table}: {inserted}/{len(rows)} rows copied from {src_path} (dedup on {unique_hint})")


def main() -> None:
    init_product_queue()
    init_social_posts()
    copy_table(LEGACY_QUEUE_DB, "product_queue", "product_id")
    copy_table(LEGACY_SOCIAL_DB, "social_posts", "product_id, media_type")


if __name__ == "__main__":
    main()
