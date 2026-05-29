from typing import Any, Optional


def get_value(product: Any, key: str, default=None):
    if isinstance(product, dict):
        return product.get(key, default)
    return getattr(product, key, default)


def pick_best_image(product: Any) -> Optional[str]:
    candidates = []

    for key in [
        "product_main_image_url",
        "product_small_image_urls",
        "product_detail_image_urls",
        "image_url",
    ]:
        value = get_value(product, key)

        if isinstance(value, str):
            candidates.append(value)

        if isinstance(value, list):
            candidates.extend([x for x in value if isinstance(x, str)])

    candidates = [
        url for url in candidates
        if url and url.startswith("http")
    ]

    return candidates[0] if candidates else None


def pick_best_video(product: Any) -> Optional[str]:
    for key in [
        "product_video_url",
        "video_url",
        "product_video_urls",
        "media_video_url",
    ]:
        value = get_value(product, key)

        if isinstance(value, str) and value.startswith("http"):
            return value

        if isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.startswith("http"):
                    return item

    return None


def choose_media_type(product: Any, preferred: str) -> str:
    image = pick_best_image(product)
    video = pick_best_video(product)

    if preferred == "video" and video:
        return "video"

    if preferred == "either" and video:
        return "video"

    if image:
        return "image"

    return "missing"