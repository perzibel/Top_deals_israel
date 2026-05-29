import httpx


class AffiracleClient:
    def __init__(self, settings):
        self.settings = settings
        self.base_url = settings.affiracle_base_url.rstrip("/")
        self.token = settings.affiracle_api_token

    async def generate_affiliate_link(self, product_url: str) -> dict:
        if not self.token:
            raise RuntimeError("Missing AFFIRACLE_API_TOKEN in .env")

        endpoint = f"{self.base_url}/aliexpress/generate-link"

        payload = {
            "url": product_url,
        }

        auth_variants = [
            {
                "name": "Bearer token",
                "headers": {"Authorization": f"Bearer {self.token}"},
            },
            {
                "name": "Raw Authorization token",
                "headers": {"Authorization": self.token},
            },
            {
                "name": "X-API-Token",
                "headers": {"X-API-Token": self.token},
            },
            {
                "name": "X-Api-Key",
                "headers": {"X-Api-Key": self.token},
            },
            {
                "name": "api-token",
                "headers": {"api-token": self.token},
            },
        ]

        last_response = None

        async with httpx.AsyncClient(timeout=30) as client:
            for variant in auth_variants:
                headers = {
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    **variant["headers"],
                }

                response = await client.post(
                    endpoint,
                    headers=headers,
                    json=payload,
                )

                print("\nTried auth:", variant["name"])
                print("Affiracle status:", response.status_code)
                print("Affiracle response:", response.text)

                if response.status_code == 200:
                    data = response.json()

                    affiliate_url = (
                        data.get("affiliate_url")
                        or data.get("short_url")
                        or data.get("tracking_url")
                        or data.get("link")
                        or data.get("url")
                    )

                    if not affiliate_url:
                        raise RuntimeError(
                            f"Could not find affiliate URL in response: {data}"
                        )

                    return {
                        "affiliate_url": affiliate_url,
                        "raw": data,
                    }

                last_response = response

        # If all auth methods failed, raise the last error
        if last_response is not None:
            last_response.raise_for_status()

        raise RuntimeError("Affiracle request failed before receiving a response")