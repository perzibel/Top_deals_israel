from typing import Any


def get_product_value(product: Any, key: str, default: Any = None) -> Any:
    """Read a field from a Product dataclass or a plain dict (queue rows are dicts)."""
    if isinstance(product, dict):
        return product.get(key, default)

    return getattr(product, key, default)


def set_product_value(product: Any, key: str, value: Any) -> None:
    if isinstance(product, dict):
        product[key] = value
    else:
        setattr(product, key, value)
