from pydantic_settings import BaseSettings, SettingsConfigDict

from app.storage.paths import PROJECT_ROOT


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


class Settings(BaseSettings):
    # Anchored to the project so the scheduled task finds .env regardless of cwd.
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # When true, nothing is sent to Telegram; messages are logged instead.
    dry_run: bool = False
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
    # Private chat for drafts and operational alerts (not the public channel).
    telegram_chat_id: str = ""

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:8b"
    use_ollama: bool = False
    # Use the model's Hebrew description/verdict when it passes validation.
    use_ai_copy: bool = True
    social_model: str = "qwen3:14b"
    ollama_host: str = "http://localhost:11434"
    usd_to_ils: float = 3.7

    min_rating: float = 4.4
    min_orders: int = 1000
    max_price_usd: float = 150.0
    min_discount_percent: float = 0
    keywords: str = "smart home,usb c,keyboard,mouse,ssd,charger,power bank,earbuds"
    # Extra comma-separated title terms to reject, e.g. "shoes,insole,dress".
    blocked_title_terms: str = ""

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

    # Result pages sampled per discovery source (random in [min, max]).
    discovery_page_min: int = 1
    discovery_page_max: int = 3

    # Queued products older than this are dropped instead of posted.
    queue_max_age_days: int = 3
    # A posted product may be posted again after this many days...
    repost_cooldown_days: int = 30
    # ...but only if it is at least this much cheaper than when last posted.
    repost_min_drop_percent: float = 10

    enable_hot_products: bool = True
    enable_hot_topics: bool = False

    hot_products_limit: int = 50
    hot_topics_limit: int = 50
    hot_topics_topic_ids: str = ""
    hot_topics_per_request: int = 50
    hot_topic_keywords: str = ""

    # AliExpress featured promotion campaigns (Brand Day, Big Save, 11.11 ...).
    enable_featured_promos: bool = True
    # Only campaigns whose name contains one of these (case-insensitive).
    featured_promo_patterns: str = "big save,bestseller,top brands,superdeal,choice,11.11,sale"
    featured_promos_per_run: int = 2

    @property
    def keyword_list(self) -> list[str]:
        return split_csv(self.keywords)

    @property
    def hot_topics_topic_id_list(self) -> list[str]:
        return split_csv(self.hot_topics_topic_ids)

    @property
    def hot_topic_keyword_list(self) -> list[str]:
        return split_csv(self.hot_topic_keywords)

    @property
    def blocked_title_term_list(self) -> list[str]:
        return [term.lower() for term in split_csv(self.blocked_title_terms)]

    @property
    def featured_promo_pattern_list(self) -> list[str]:
        return [pattern.lower() for pattern in split_csv(self.featured_promo_patterns)]
