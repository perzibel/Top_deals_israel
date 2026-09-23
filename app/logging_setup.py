import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from app.storage.paths import LOG_DIR


def setup_logging(level: int | str | None = None) -> None:
    level = level or os.getenv("LOG_LEVEL", "INFO").upper()
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    # UTF-8 file so Hebrew titles are readable (the Windows console codepage mangles them).
    file_handler = RotatingFileHandler(
        LOG_DIR / "top_deals.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers[:] = [file_handler, console_handler]

    # Third-party request logs are noise at INFO.
    for noisy in ["httpx", "httpcore", "apscheduler.executors", "telethon"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)
