"""판매처의 옵션별 온라인 재고와 한국 일반배송 예상 견적."""
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import quote, urlsplit

from direct_shipping import SEARCH_ERRORS, STOREFRONTS, nike_page_props, request_json

NIKE_CHANNEL = "d9a5bc42-4b9c-4976-858a-f159cf99c647"
STOCK_LABEL = {
    "available": "온라인 재고 있음", "sold_out": "온라인 품절", "unknown": "재고 미확인",
    "for_sale": "판매 가능 (배송 재고 미확인)", "backorder": "재고 소진 후 주문 접수 가능",
    "unavailable": "판매 불가",
}
UNAVAILABLE = {"sold_out", "unavailable"}
VARIANT_FIELDS = """
fragment QuoteFields on ProductVariant {
  id title availableForSale currentlyNotInStock price { amount currencyCode }
}
"""
SHOP_VARIANT = """
query SelectedOption($id: ID!) @inContext(country: KR) {
  node(id: $id) { ... on ProductVariant { ...QuoteFields product { id } } }
}
""" + VARIANT_FIELDS
SHOP_VARIANTS = """
query Options($id: ID!, $after: String) @inContext(country: KR) {
  product(id: $id) { id variants(first: 100, after: $after) {
    nodes { ...QuoteFields }
    pageInfo { hasNextPage endCursor }
  } }
}
""" + VARIANT_FIELDS


def supports(item):
    return (item.get("seller") == "나이키 코리아" or
            bool(item.get("product_id") and item.get("storefront_host") in STOREFRONTS.get(item.get("market"), {})))


def amount(value):
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    return format(number, "f") if number.is_finite() and number >= 0 else None


def nike_options(item, variant_id):
    link = urlsplit(item["url"])
    if (link.scheme, link.netloc) != ("https", "www.nike.com") or not link.path.startswith("/kr/t/"):
        raise ValueError("나이키 코리아 상품 주소를 확인하세요.")
    page = nike_page_props("https://www.nike.com" + quote(link.path, safe="/%"))
    product = page["selectedProduct"]
    code = item["model_code"]
    if page["marketPlace"] != "KR" or product["styleColor"] != code or product["prices"]["currency"] != "KRW":
        raise ValueError("판매처 상품의 품번 또는 통화가 변경되었습니다.")
    group = product["groupKey"]
    url = (f"https://api.nike.com/discover/product_details_availability/v1/marketplace/KR/language/ko/"
           f"consumerChannelId/{NIKE_CHANNEL}/groupKey/{quote(group, safe='')}")
    stocks = {}
    try:
        inventory = request_json(url, headers={"nike-api-caller-id": "fcc-commerce"}, timeout=6)
        if isinstance(inventory, dict) and inventory.get("marketplace") == "KR" and inventory.get("groupKey") == group:
            for entry in inventory["sizes"]:
                if isinstance(entry, dict) and entry.get("productCode") == code and isinstance(entry.get("availability"), dict):
                    stocks[entry.get("merchSkuId")] = entry["availability"]
    except SEARCH_ERRORS:
        stocks.clear()

    message = page.get("messages", {}).get("KR", {}).get("shippingMessage", "")
    lines = [re.sub("<[^>]+>", "", p).strip(" •") for p in re.findall(r"<p>(.*?)</p>", message, re.S)]
    domestic_free = "배송비: 무료 배송" in lines and "배송 지역: 국내(일부 지역 제외)" in lines
    options = []
    price = amount(product["prices"].get("currentPrice"))
    for size in product["sizes"]:
        sku = size.get("merchSkuId")
        label = size.get("localizedLabel")
        if not sku or not label or (variant_id is not None and sku != variant_id):
            continue
        info = stocks.get(sku, {})
        stock = "unknown"
        if info.get("isAvailable") is True and info.get("ship") in ("LOW", "MEDIUM", "HIGH"):
            stock = "available"
        elif info.get("isAvailable") is False and info.get("ship") == "OOS":
            stock = "sold_out"
        if product.get("productType") == "FOOTWEAR" and str(label).isdigit():
            label = f"{label} mm"
        options.append(dict(variant_id=sku, option=label, stock=stock,
                            stock_level=info.get("ship") if stock != "unknown" else None,
                            price=price, currency="KRW"))
    return options, "0" if domestic_free else None, "국내 기본 배송 안내 기준, 일부 지역 제외" if domestic_free else None


def storefront_options(item, variant_id):
    url = f"https://{item['storefront_host']}/api/2026-10/graphql.json"

    def fetch(query, variables):
        response = request_json(url, timeout=8, json_body={"query": query, "variables": variables})
        if response.get("errors") or response.get("extensions", {}).get("context", {}).get("country") != "KR":
            raise ValueError("한국 기준 옵션을 확인할 수 없습니다.")
        return response["data"]

    if variant_id is not None:
        variant = fetch(SHOP_VARIANT, {"id": variant_id})["node"]
        if variant and variant.get("id") == variant_id and variant["product"]["id"] == item["product_id"]:
            yield variant
        return

    cursor = None
    seen = set()
    while True:
        product = fetch(SHOP_VARIANTS, {"id": item["product_id"], "after": cursor})["product"]
        if not product or product["id"] != item["product_id"]:
            raise ValueError("판매처에서 상품을 찾을 수 없습니다.")
        variants = product["variants"]
        yield from variants["nodes"]
        if not variants["pageInfo"]["hasNextPage"]:
            break
        cursor = variants["pageInfo"]["endCursor"]
        if not cursor or cursor in seen:
            raise ValueError("판매처 옵션 목록을 끝까지 확인할 수 없습니다.")
        seen.add(cursor)


def storefront_quote_option(variant):
    stock = {True: "for_sale", False: "unavailable"}.get(variant.get("availableForSale"), "unknown")
    if stock == "for_sale" and variant.get("currentlyNotInStock") is True:
        stock = "backorder"
    return dict(variant_id=variant["id"], option=variant["title"], stock=stock,
                stock_level=None, price=amount(variant["price"]["amount"]),
                currency=variant["price"]["currencyCode"])


def lookup(item, variant_id=None):
    if not supports(item):
        raise ValueError("이 판매처는 옵션별 견적을 지원하지 않습니다.")
    if item["seller"] == "나이키 코리아":
        options, shipping, basis = nike_options(item, variant_id)
    else:
        shipping = basis = None
        options = map(storefront_quote_option, storefront_options(item, variant_id))
    quotes = {}
    for variant in options:
        price = variant["price"]
        total = format(Decimal(price) + Decimal(shipping), "f") if price is not None and shipping is not None else None
        quotes[variant["variant_id"]] = {
            **variant, "seller": item["seller"], "title": item["title"], "url": item["url"],
            "model_code": item.get("model_code"), "quantity": 1, "destination": "KR",
            "shipping": shipping, "shipping_basis": basis, "estimated_total": total,
            "price_status": "estimated", "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
    if not quotes and variant_id is None:
        raise ValueError("판매처에 표시된 옵션이 없습니다.")
    return quotes
