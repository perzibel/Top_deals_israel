from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv
import os

load_dotenv()



def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)

    if value is None:
        return default

    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)

    if value is None or value.strip() == "":
        return default

    return int(value)


def env_list(name: str) -> list[str]:
    value = os.getenv(name, "")

    if not value.strip():
        return []

    return [
        item.strip()
        for item in value.split(",")
        if item.strip()
    ]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    dry_run: bool = True
    post_interval_minutes: int = 180
    max_posts_per_run: int = 3
    posts_per_batch: int = 3
    discovery_interval_minutes: int = 360

    aliexpress_app_key: str = ""
    aliexpress_app_secret: str = ""
    aliexpress_tracking_id: str = "telegram_main"
    aliexpress_api_endpoint: str = "https://api-sg.aliexpress.com/sync"
    aliexpress_search_method: str = "aliexpress.affiliate.product.query"
    aliexpress_link_method: str = "aliexpress.affiliate.link.generate"

    hot_products_max_price_ils: float = 250
    hot_products_keywords: str = (
        "gaming,tech,phone accessories,gadgets,smart home,desk setup,"
        "keyboard,mouse,usb,charger,"
        "controller,headset,earbuds,desk mat"
    )

    telegram_bot_token: str = ""
    telegram_channel_id: str = ""
    telegram_chat_id: str = 2060881995

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:8b"
    use_ollama: bool = False
    social_model: str = "qwen3:14b"
    ollama_host: str = "http://localhost:11434"
    usd_to_ils: float = 3.0

    min_rating: float = 4.4
    min_orders: int = 1000
    max_price_usd: float = 150.0
    keywords: str = "smart home,usb c,keyboard,mouse,ssd,charger,power bank,earbuds"

    telegram_api_id: int = 0
    telegram_api_hash: str = ""
    telegram_user_session: str = "affiracle_user_session"

    affiracle_bot_username: str = "affiracle_affiliates_bot"
    affiracle_bot_timeout_seconds: int = 60
    affiracle_bot_cooldown_seconds: int = 15

    affiliate_backend: str = "affiracle_telegram"

    product_source: str = "seed_urls"
    seed_products_path: str = "data/products_seed.json"

    search_products_per_keyword: int = 20

    min_deal_score_to_post: int = 80

    min_price_ils: float = 10
    max_price_ils: float = 250
    min_price_usd: float = 3

    post_interval_hours: int = 3
    discovery_interval_hours: int = 6
    post_active_start_hour: int = 9
    post_active_end_hour: int = 22
    queue_target_size: int = 50
    discovery_max_candidates_per_run: int = 100

    category_rotation_window: int = 4

    enable_hot_products: bool = True
    enable_hot_topics: bool = False

    hot_products_limit: int = 50
    hot_topics_limit: int = 50
    hot_topics_topic_ids: str = ""
    hot_topics_per_request: int = 50
    hot_topic_keywords: str = ""
    @property
    def keyword_list(self) -> list[str]:
        return [k.strip() for k in self.keywords.split(",") if k.strip()]

    @property
    def hot_topics_topic_id_list(self) -> list[str]:
        if not self.hot_topics_topic_ids:
            return []

        return [
            topic_id.strip()
            for topic_id in self.hot_topics_topic_ids.split(",")
            if topic_id.strip()
        ]

    @property
    def hot_topic_keyword_list(self) -> list[str]:
        if not self.hot_topic_keywords:
            return []

        return [
            keyword.strip()
            for keyword in self.hot_topic_keywords.split(",")
            if keyword.strip()
        ]

@lru_cache
def get_settings() -> Settings:
    return Settings()


# =========================
# Discovery source settings
# =========================

SOURCE_HOT_PRODUCTS = "hot_products"
SOURCE_HOT_TOPICS = "hot_topics"
SOURCE_FEATURED_PROMOTIONS = "featured_promotions"

ENABLE_HOT_PRODUCTS = env_bool("ENABLE_HOT_PRODUCTS", True)
ENABLE_HOT_TOPICS = env_bool("ENABLE_HOT_TOPICS", False)

HOT_PRODUCTS_LIMIT = env_int("HOT_PRODUCTS_LIMIT", 50)
HOT_TOPICS_LIMIT = env_int("HOT_TOPICS_LIMIT", 50)

HOT_TOPICS_TOPIC_IDS = env_list("HOT_TOPICS_TOPIC_IDS")