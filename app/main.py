import argparse
import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.clients.aliexpress import AliExpressClient
from app.clients.ollama import OllamaClient
from app.clients.telegram import TelegramClient
from app.config import Settings
from app.logging_setup import setup_logging
from app.services.engine import DealEngine
from app.services.social_batch_builder import build_nightly_social_posts
from app.storage.paths import LOG_DIR
from app.storage.product_queue import (
    last_post_time,
    preview_candidate_ranking,
    preview_next_queued_product,
    simulate_next_posts,
)
from app.storage.social_posts import init_social_posts

log = logging.getLogger("app.main")


def print_next_post_time(scheduler, job_id: str = "post_batch_from_queue"):
    job = scheduler.get_job(job_id)

    if not job or not job.next_run_time:
        log.info("[SCHEDULER] Job '%s' has no next run time yet.", job_id)
        return

    next_run = job.next_run_time.astimezone(ZoneInfo("Asia/Jerusalem"))
    now = datetime.now(ZoneInfo("Asia/Jerusalem"))
    total_seconds = max(0, int((next_run - now).total_seconds()))

    log.info(
        "[SCHEDULER] Next batch post at: %s Israel time (in %dh %dm)",
        next_run.strftime("%Y-%m-%d %H:%M:%S"),
        total_seconds // 3600,
        (total_seconds % 3600) // 60,
    )


async def run_once():
    engine = DealEngine(Settings())
    await engine.run_once()


async def create_social_drafts_once():
    settings = Settings()

    init_social_posts()
    drafts = await build_nightly_social_posts(
        aliexpress_client=AliExpressClient(settings),
        ollama_client=OllamaClient(settings),
        telegram_client=TelegramClient(settings),
        posts_per_day=3,
    )

    log.info("Created %d social drafts", len(drafts))


async def discover_only():
    engine = DealEngine(Settings())
    await engine.discover_and_queue()


async def post_once():
    engine = DealEngine(Settings())
    await engine.post_batch_from_queue(force=True)


async def post_dry_run():
    engine = DealEngine(Settings())
    await engine.post_batch_from_queue(force=True, dry_run=True)


async def run_scheduler():
    settings = Settings()
    engine = DealEngine(settings)

    scheduler = AsyncIOScheduler(
        timezone="Asia/Jerusalem",
        job_defaults={
            "coalesce": True,
            "max_instances": 1,
            "misfire_grace_time": 300,
        },
    )

    async def guarded(name: str, coro_factory):
        # An exception inside an APScheduler job is only logged; also alert on it.
        try:
            await coro_factory()
        except Exception as e:
            log.exception("Scheduled job %s failed", name)
            await engine.telegram.send_alert(f"Job '{name}' failed: {type(e).__name__}: {e}")

    async def scheduled_discovery():
        await guarded("discover_and_queue", engine.discover_and_queue)

    async def scheduled_post_batch():
        log.info("[SCHEDULER] Starting scheduled post batch...")
        await guarded("post_batch_from_queue", lambda: engine.post_batch_from_queue(force=False))
        print_next_post_time(scheduler, "post_batch_from_queue")

    async def scheduled_social_posts():
        await guarded(
            "nightly_social_posts",
            lambda: build_nightly_social_posts(
                aliexpress_client=engine.aliexpress,
                ollama_client=engine.ollama,
                telegram_client=engine.telegram,
                posts_per_day=3,
            ),
        )

    scheduler.add_job(
        scheduled_discovery,
        "interval",
        minutes=settings.discovery_interval_minutes,
        id="discover_and_queue",
    )

    scheduler.add_job(
        scheduled_post_batch,
        "interval",
        minutes=settings.post_interval_minutes,
        id="post_batch_from_queue",
    )

    init_social_posts()

    scheduler.add_job(
        scheduled_social_posts,
        CronTrigger(hour=1, minute=30, timezone="Asia/Jerusalem"),
        id="nightly_social_posts",
        replace_existing=True,
    )

    scheduler.start()

    log.info(
        "Scheduler started. Discovery every %d minutes. Posting %d products every %d minutes "
        "between %d:00 and %d:00 Israel time.%s",
        settings.discovery_interval_minutes,
        settings.posts_per_batch,
        settings.post_interval_minutes,
        settings.post_active_start_hour,
        settings.post_active_end_hour,
        " DRY RUN - nothing will be published." if settings.dry_run else "",
    )

    log.info("[STARTUP] Running initial discovery...")
    await guarded("startup_discovery", engine.discover_and_queue)

    # A restart (crash recovery, reboot) must not spam the channel: only post on
    # startup inside posting hours and if the last batch is older than one interval.
    last = last_post_time()
    since_last = datetime.now(timezone.utc) - last if last else None

    if since_last is not None and since_last < timedelta(minutes=settings.post_interval_minutes):
        log.info("[STARTUP] Last post was %d minutes ago; waiting for the schedule.", since_last.total_seconds() // 60)
    else:
        log.info("[STARTUP] Posting first batch...")
        await guarded("startup_post_batch", lambda: engine.post_batch_from_queue(force=False))

    print_next_post_time(scheduler, "post_batch_from_queue")

    while True:
        await asyncio.sleep(60)


def acquire_single_instance_lock():
    """
    Returns an open lock file handle, or None if another scheduler already runs.
    Two scheduled tasks can launch the bot; only one may post. The OS releases
    the lock when the process dies, however it dies.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    handle = open(LOG_DIR / "scheduler.lock", "a+")

    try:
        if sys.platform == "win32":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None

    return handle


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Run discovery once")
    parser.add_argument("--discover", action="store_true", help="Only discover and queue")
    parser.add_argument("--post", action="store_true", help="Post one batch now")
    parser.add_argument("--preview", action="store_true", help="Preview next product without posting")
    parser.add_argument("--preview-ranking", action="store_true", help="Preview candidate ranking without posting")
    parser.add_argument("--simulate-posts", type=int, help="Simulate next N posts without publishing")
    parser.add_argument("--post-dry-run", action="store_true", help="Run posting logic without publishing")
    parser.add_argument("--social-drafts", action="store_true", help="Create nightly social post drafts now")
    args = parser.parse_args()

    setup_logging()

    if args.once:
        asyncio.run(run_once())
    elif args.discover:
        asyncio.run(discover_only())
    elif args.post:
        asyncio.run(post_once())
    elif args.preview:
        preview_next_queued_product()
    elif args.preview_ranking:
        preview_candidate_ranking()
    elif args.simulate_posts:
        simulate_next_posts(args.simulate_posts)
    elif args.post_dry_run:
        asyncio.run(post_dry_run())
    elif args.social_drafts:
        asyncio.run(create_social_drafts_once())
    else:
        lock = acquire_single_instance_lock()
        if lock is None:
            log.info("Another scheduler instance is already running. Exiting.")
            return

        try:
            asyncio.run(run_scheduler())
        except KeyboardInterrupt:
            log.info("Stopped.")
        except Exception as e:
            log.exception("Scheduler crashed")
            # Last-ditch alert; the scheduled task restarts the process.
            asyncio.run(TelegramClient(Settings()).send_alert(f"Scheduler crashed: {type(e).__name__}: {e}"))
            raise


if __name__ == "__main__":
    main()
