# AliExpress Deal Engine

Starter Python engine for a Telegram AliExpress affiliate deals channel.

It supports:

- Dry-run mode while waiting for AliExpress approval
- Product search adapter
- Affiliate link generation adapter
- Product quality filters
- Optional Ollama post rewriting
- Telegram posting
- SQLite deduplication so you do not repost the same product

## Setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env
python -m app.main --once
```

## After AliExpress approval

Fill these in `.env`:

```env
ALIEXPRESS_APP_KEY=...
ALIEXPRESS_APP_SECRET=...
ALIEXPRESS_TRACKING_ID=telegram_main
DRY_RUN=false
```

Then confirm the exact method names and endpoint from your AliExpress Open Platform dashboard.
They are configurable in `.env` so the code does not need a rewrite.
