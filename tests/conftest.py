import os
import tempfile
from pathlib import Path

# Must be set before any app.storage module is imported.
_TEST_DB = Path(tempfile.mkdtemp(prefix="tdi_tests_")) / "test.sqlite3"
os.environ["TDI_DB_PATH"] = str(_TEST_DB)

import pytest  # noqa: E402

from app.config import Settings  # noqa: E402
from app.models import Product  # noqa: E402
from app.storage.paths import get_conn  # noqa: E402


@pytest.fixture(autouse=True)
def clean_db():
    from app.storage.db import init_db
    from app.storage.price_history import init_price_history
    from app.storage.product_queue import init_product_queue

    init_db()
    init_price_history()
    init_product_queue()

    with get_conn() as conn:
        for table in ["product_queue", "posted_products", "price_history"]:
            conn.execute(f"DELETE FROM {table}")
    yield


@pytest.fixture
def settings():
    # _env_file=None: tests must not depend on the real .env.
    return Settings(
        _env_file=None,
        min_rating=4.4,
        min_orders=1000,
        min_price_ils=10,
        max_price_ils=250,
        min_discount_percent=5,
        usd_to_ils=3.7,
        use_ollama=False,
        dry_run=True,
    )


@pytest.fixture
def product():
    return Product(
        product_id="1005001",
        title="65W GaN USB C Charger",
        product_url="https://www.aliexpress.com/item/1005001.html",
        affiliate_url="https://s.click.aliexpress.com/e/abc",
        price_ils=40.0,
        original_price_ils=80.0,
        rating=4.8,
        orders=6000,
        image_url="https://ae01.alicdn.com/kf/x.jpg",
        category="Chargers",
        discount="50%",
    )
