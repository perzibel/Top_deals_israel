# Top Deals Israel

Finds high-quality AliExpress deals and posts them to a Telegram channel.

Every few hours the scheduler:

1. **Discovers** products from keyword searches, hot products, and running AliExpress
   promotion campaigns (Brand Day, Big Save, 11.11 ...).
2. **Filters** them (rating, orders, ₪ price range, minimum discount, blocked terms).
3. **Scores** them (1-100). Discounts are judged against our own price history, because
   AliExpress "original prices" are usually inflated. Only products scoring
   `MIN_DEAL_SCORE_TO_POST` or more are queued.
4. **Posts** a batch of 3, rotating categories. Each product is re-fetched right before
   posting so the price is current, and dropped if it no longer qualifies.

A posted product can be posted again after `REPOST_COOLDOWN_DAYS` if it became at least
`REPOST_MIN_DROP_PERCENT` cheaper.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env            # then fill it in
```

Ollama (`USE_OLLAMA=true`) writes the Hebrew description and hashtags. Without it the bot
uses built-in Hebrew templates. The deal score never depends on the model.

## Running

| Command | What it does |
| --- | --- |
| `run_bot.cmd` | Start the scheduler (what the Windows scheduled task runs) |
| `python -m app.main --discover` | Fill the queue once |
| `python -m app.main --post-dry-run` | Show the next batch without publishing |
| `python -m app.main --preview-ranking` | Show queued candidates and which is next |
| `python -m app.main --post` | Post one batch now (ignores posting hours) |
| `python -m app.main --social-drafts` | Build tomorrow's social drafts now |

Set `DRY_RUN=true` to run everything without publishing to Telegram.

Logs: `logs/top_deals.log` (UTF-8, rotated). `LOG_LEVEL=DEBUG` shows why each product
was skipped. Failures and empty batches are sent to `TELEGRAM_CHAT_ID`.

All data lives in `app/storage/deal_engine.sqlite3`.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Tests use a temporary database and never call AliExpress, Telegram or Ollama.
The scripts in `test/` are manual checks against the live APIs.
