import re
from urllib.parse import urlparse


ALIEXPRESS_URL_RE = re.compile(
    r"https?://[^\s<>\"']+",
    re.IGNORECASE,
)


def is_aliexpress_url(url: str) -> bool:
    if not url:
        return False

    try:
        parsed = urlparse(url.strip())
    except Exception:
        return False

    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").lower()

    valid_hosts = (
        "aliexpress.com",
        "www.aliexpress.com",
        "he.aliexpress.com",
        "s.click.aliexpress.com",
        "a.aliexpress.com",
    )

    if host in valid_hosts or host.endswith(".aliexpress.com"):
        return "/item/" in path or "s.click.aliexpress.com" in host or "a.aliexpress.com" in host

    return False


def extract_aliexpress_url(text: str) -> str | None:
    if not text:
        return None

    matches = ALIEXPRESS_URL_RE.findall(text)

    for raw_url in matches:
        # Telegram/user text may include punctuation at the end
        url = raw_url.strip().rstrip(".,)]}>")

        if is_aliexpress_url(url):
            return url

    return None


def extract_aliexpress_product_id(url: str) -> str | None:
    if not url:
        return None

    patterns = [
        r"/item/(\d+)\.html",
        r"/item/(\d+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)

    return None


def is_aliexpress_link(text: str) -> bool:
    if not text:
        return False

    text = text.lower()

    return (
        "aliexpress.com/item/" in text
        or "s.click.aliexpress.com" in text
        or "a.aliexpress.com" in text
    )