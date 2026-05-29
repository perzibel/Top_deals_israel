from app.bot.utils import extract_aliexpress_url, extract_aliexpress_product_id


url = """https://he.aliexpress.com/item/1005012167576779.html?spm=a2g0o.tm1000029706.d1.1.645e474c7P2iIQ&sourceType=561&pvid=b73d94ea-200d-453b-aac3-03ad245ccb5c&pdp_ext_f=%7B%22ship_from%22%3A%22CN%22%2C%22sku_id%22%3A%2212000057660205833%22%7D&scm=1007.28480.478283.0&scm-url=1007.28480.478283.0&scm_id=1007.28480.478283.0&aecmd=true&gatewayAdapt=glo2isr"""

extracted = extract_aliexpress_url(url)
product_id = extract_aliexpress_product_id(url)

print("extracted:", extracted)
print("product_id:", product_id)

assert extracted is not None
assert product_id == "1005012167576779"

print("URL extraction test passed")