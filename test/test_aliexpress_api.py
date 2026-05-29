import asyncio
import hashlib
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv

from aliexpress_deal_engine.app.config import Settings


def ali_timestamp() -> str:
    # AliExpress/TOP docs commonly expect GMT+8 timestamp format.
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")


def sign_top_request(params: dict, app_secret: str) -> str:
    """
    TOP-style MD5 signature:
    secret + sorted(key + value) + secret
    """
    sorted_items = sorted(params.items())
    base = app_secret + "".join(f"{k}{v}" for k, v in sorted_items) + app_secret
    return hashlib.md5(base.encode("utf-8")).hexdigest().upper()


async def main():
    load_dotenv()
    settings = Settings()

    product_id = "1005006770992968"

    params = {
        "method": "aliexpress.affiliate.productdetail.get",
        "app_key": settings.aliexpress_app_key,
        "timestamp": ali_timestamp(),
        "format": "json",
        "v": "2.0",
        "sign_method": "md5",
        "product_ids": product_id,
        "target_currency": "ILS",
        "target_language": "HE",
    }

    params["sign"] = sign_top_request(params, settings.aliexpress_app_secret)

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            settings.aliexpress_api_endpoint,
            data=params,
            headers={
                "Content-Type": "application/x-www-form-urlencoded;charset=utf-8"
            },
        )

    print("Status:", response.status_code)
    print("Response:")
    print(response.text)


if __name__ == "__main__":
    asyncio.run(main())