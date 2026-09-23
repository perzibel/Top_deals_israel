import os
import sqlite3
from pathlib import Path

# Single source of truth for on-disk locations. Paths are anchored to the
# code, not the current working directory, so the scheduled task, the bot and
# ad-hoc scripts all read and write the same database.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
# TDI_DB_PATH lets tests point at a throwaway database.
DB_PATH = Path(os.getenv("TDI_DB_PATH") or Path(__file__).resolve().parent / "deal_engine.sqlite3")
LOG_DIR = PROJECT_ROOT / "logs"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    # WAL lets the scheduler and the Telegram bot use the DB concurrently.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn
