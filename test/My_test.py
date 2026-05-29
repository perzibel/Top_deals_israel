import os
import json
from dotenv import load_dotenv

from iop import IopClient, IopRequest


load_dotenv()


ALIEXPRESS_API_URL = os.getenv("ALIEXPRESS_API_URL")
ALIEXPRESS_APP_KEY = os.getenv("ALIEXPRESS_APP_KEY")
ALIEXPRESS_APP_SECRET = os.getenv("ALIEXPRESS_APP_SECRET")
ALIEXPRESS_TRACKING_ID = os.getenv("ALIEXPRESS_TRACKING_ID")
ALIEXPRESS_APP_SIGNATURE = os.getenv("ALIEXPRESS_APP_SIGNATURE", "")


def get_featured_promo_products(
    category_id: str,
    promotion_name: str,
    page_no: int = 1,
    page_size: int = 50,
):
    client = IopClient(
        ALIEXPRESS_API_URL,
        ALIEXPRESS_APP_KEY,
        ALIEXPRESS_APP_SECRET,
    )

    request = IopRequest(
        "aliexpress.affiliate.featuredpromo.products.get"
    )

    params = {
        "app_signature": ALIEXPRESS_APP_SIGNATURE,
        "category_id": category_id,
        "fields": "product_id,product_title,product_detail_url,promotion_link,sale_price,commission_rate",
        "page_no": str(page_no),
        "page_size": str(page_size),
        "promotion_name": promotion_name,
        "sort": "commissionAsc",
        "target_currency": "USD",
        "target_language": "EN",
        "tracking_id": ALIEXPRESS_TRACKING_ID,
        "country": "US",
    }

    for key, value in params.items():
        if value:
            request.add_api_param(key, value)

    response = client.execute(request)

    return {
        "type": response.type,
        "body": response.body,
    }


if __name__ == "__main__":
    result = get_featured_promo_products(
        category_id="111",
        promotion_name="singles day big sale",
        page_no=1,
        page_size=50,
    )

    print("Response type:")
    print(result["type"])

    print("\nResponse body:")
    print(json.dumps(result["body"], indent=2, ensure_ascii=False))