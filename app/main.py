import argparse
import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from rich.console import Console
from datetime import datetime
from zoneinfo import ZoneInfo
from app.config import Settings
from app.services.engine import DealEngine
from app.storage.product_queue import preview_next_queued_product, preview_candidate_ranking,simulate_next_posts

from app.clients.aliexpress import AliExpressClient
from app.clients.ollama import OllamaClient
from app.clients.telegram import TelegramClient
from app.storage.social_posts import init_social_posts
from app.services.social_batch_builder import build_nightly_social_posts

console = Console()


def print_next_post_time(scheduler, job_id: str = "post_batch_from_queue"):
    job = scheduler.get_job(job_id)

    if not job:
        print(f"[SCHEDULER] Job '{job_id}' was not found.")
        return

    if not job.next_run_time:
        print(f"[SCHEDULER] Job '{job_id}' has no next run time yet.")

        return

    next_run = job.next_run_time.astimezone(ZoneInfo("Asia/Jerusalem"))
    now = datetime.now(ZoneInfo("Asia/Jerusalem"))
    delta = next_run - now

    total_seconds = max(0, int(delta.total_seconds()))
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60

    print(
        f"[SCHEDULER] Next batch post at: "
        f"{next_run.strftime('%Y-%m-%d %H:%M:%S')} Israel time "
        f"(in {hours}h {minutes}m)"
    )


async def run_once():
    settings = Settings()
    engine = DealEngine(settings)
    await engine.run_once()


async def create_social_drafts_once():
    settings = Settings()

    aliexpress_client = AliExpressClient(settings)
    ollama_client = OllamaClient(settings)
    telegram_client = TelegramClient(settings)

    init_social_posts()
    drafts = await build_nightly_social_posts(
        aliexpress_client=aliexpress_client,
        ollama_client=ollama_client,
        telegram_client=telegram_client,
        posts_per_day=3,
    )

    console.print(f"Created {len(drafts)} social drafts")


async def discover_only():
    settings = Settings()
    engine = DealEngine(settings)
    await engine.discover_and_queue()


async def post_once():
    settings = Settings()
    engine = DealEngine(settings)
    await engine.post_batch_from_queue(force=True)


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

    async def scheduled_post_batch():
        console.print("[cyan][SCHEDULER] Starting scheduled post batch...[/cyan]")

        await engine.post_batch_from_queue(force=False)

        print_next_post_time(scheduler, "post_batch_from_queue")

    scheduler.add_job(
        engine.discover_and_queue,
        "interval",
        minutes=settings.discovery_interval_minutes,
        id="discover_and_queue",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    scheduler.add_job(
        scheduled_post_batch,
        "interval",
        minutes=settings.post_interval_minutes,
        id="post_batch_from_queue",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    init_social_posts()

    scheduler.add_job(
        build_nightly_social_posts,
        CronTrigger(hour=1, minute=30, timezone="Asia/Jerusalem"),
        kwargs={
            "aliexpress_client": AliExpressClient(settings),
            "ollama_client": OllamaClient(settings),
            "telegram_client": TelegramClient(settings),
            "posts_per_day": 3,
        },
        id="nightly_social_posts",
        replace_existing=True,
        max_instances=1,
    )

    scheduler.start()

    console.print("[green]Scheduler started.[/green]")
    console.print(
        f"Discovery every {settings.discovery_interval_minutes} minutes. "
        f"Posting {settings.posts_per_batch} products every "
        f"{settings.post_interval_minutes} minutes "
        f"between {settings.post_active_start_hour}:00 and "
        f"{settings.post_active_end_hour}:00 Israel time."
    )

    console.print("[cyan][STARTUP] Running initial discovery...[/cyan]")
    await engine.discover_and_queue()

    print_next_post_time(scheduler, "post_batch_from_queue")

    console.print("[cyan][STARTUP] Posting first batch now...[/cyan]")
    await engine.post_batch_from_queue(force=True)

    print_next_post_time(scheduler, "post_batch_from_queue")

    while True:
        await asyncio.sleep(60)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Discover and post one now")
    parser.add_argument("--discover", action="store_true", help="Only discover and queue")
    parser.add_argument("--post", action="store_true", help="Only post next queued product")
    parser.add_argument("--preview", action="store_true", help="Preview next product without posting")
    parser.add_argument("--preview-ranking", action="store_true", help="Preview candidate ranking without posting")
    parser.add_argument("--simulate-posts", type=int, help="Simulate next N posts without publishing")
    parser.add_argument("--post-dry-run", action="store_true", help="Run posting logic without publishing")
    parser.add_argument("--social-drafts", action="store_true", help="Create nightly social post drafts now")
    args = parser.parse_args()

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
        asyncio.run(run_scheduler())


if __name__ == "__main__":
    main()
