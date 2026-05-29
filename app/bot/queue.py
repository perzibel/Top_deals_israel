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


def init_queue_db() -> None:
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                username TEXT,
                message_text TEXT NOT NULL,
                product_url TEXT,
                status TEXT NOT NULL DEFAULT 'queued',
                priority INTEGER NOT NULL DEFAULT 0,
                result_score INTEGER,
                error TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT
            )
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_user_requests_status_priority
            ON user_requests(status, priority DESC, created_at ASC)
            """
        )


def enqueue_request(
    user_id: int,
    chat_id: int,
    username: Optional[str],
    message_text: str,
    product_url: str,
    priority: int = 0,
) -> tuple[int, int]:
    """
    Returns: (request_id, queue_position)
    """
    init_queue_db()

    with get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO user_requests (
                user_id,
                chat_id,
                username,
                message_text,
                product_url,
                status,
                priority,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, 'queued', ?, ?)
            """,
            (
                user_id,
                chat_id,
                username,
                message_text,
                product_url,
                priority,
                now_iso(),
            ),
        )

        request_id = cursor.lastrowid

        queue_position = conn.execute(
            """
            SELECT COUNT(*) AS position
            FROM user_requests
            WHERE status = 'queued'
              AND (
                    priority > ?
                    OR (priority = ? AND id <= ?)
                  )
            """,
            (priority, priority, request_id),
        ).fetchone()["position"]

        return request_id, queue_position


def get_next_request():
    init_queue_db()

    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM user_requests
            WHERE status = 'queued'
            ORDER BY priority DESC, created_at ASC
            LIMIT 1
            """
        ).fetchone()

        if not row:
            return None

        conn.execute(
            """
            UPDATE user_requests
            SET status = 'processing',
                started_at = ?
            WHERE id = ?
            """,
            (now_iso(), row["id"]),
        )

        return dict(row)


def mark_done(request_id: int, score: Optional[int] = None) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE user_requests
            SET status = 'done',
                result_score = ?,
                finished_at = ?
            WHERE id = ?
            """,
            (score, now_iso(), request_id),
        )


def mark_failed(request_id: int, error: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE user_requests
            SET status = 'failed',
                error = ?,
                finished_at = ?
            WHERE id = ?
            """,
            (error[:1000], now_iso(), request_id),
        )


def get_queue_length() -> int:
    init_queue_db()

    with get_conn() as conn:
        return conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM user_requests
            WHERE status = 'queued'
            """
        ).fetchone()["count"]