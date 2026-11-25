"""스테이블코인 결제를 지원하는 판매처의 상품과 표시 가격을 조회한다."""

import argparse
import json
from urllib.error import URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen


SEASE = "https://www.sease.live"
JPYC_EC = "https://ec.jpyc-service.com"
CR_CATALOG = "https://api.cryptorefills.com/mcp/http"
CR_TOKENS = {"EURC": "EUROC", "USDC": "USDC", "USDT": "USDT"}


def read_json(url, params=None, *, rpc=None):
    headers = {"Accept": "application/json", "User-Agent": "FCC-catalog/1.0"}
    data = None
    if params:
        url += "?" + urlencode(params)
    if rpc is not None:
        headers.update({"Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
        data = json.dumps(rpc).encode()
    with urlopen(Request(url, data=data, headers=headers), timeout=20) as response:
        return json.load(response)


def sease(keyword, limit=5):
    """한국 마켓의 재고 있는 상품을 조회한다. 결제 수단은 판매처 공시 기준이다."""
    result = read_json(SEASE + "/en-kr/search/suggest.json", {
        "q": keyword, "resources[type]": "product", "resources[limit]": limit,
        "resources[options][unavailable_products]": "hide",
    })
    products = result["resources"]["results"]["products"]
    if not products:
        return []
    currency = read_json(SEASE + "/en-kr/cart.js")["currency"]
    return [{"title": p["title"], "url": urljoin(SEASE, p["url"]),
             "listed_amount": p["price"], "listed_currency": currency,
             "merchant_tokens": ["USDC", "USDT"], "shipping_status": "merchant_lists_KR",
             "kr_direct_shipping": "unverified", "shipping_fee": None} for p in products if p.get("available")]


def jpyc_ec(keyword, limit=5):
    """상품 링크, 결제 가능 여부와 배송 필요 여부를 제공하는 공식 피드를 읽는다."""
    feed = read_json(JPYC_EC + "/api/v1/feed/products")["data"]
    found = []
    for item in feed["items"]:
        info = item["jpyc_ec"]
        if info.get("is_demo") or not info.get("online_purchase_available"):
            continue
        if item.get("availability") != "in_stock":
            continue
        search_text = " ".join([item["title"], item.get("seller_name") or ""])
        if keyword.casefold() not in search_text.casefold():
            continue
        found.append({"title": item["title"], "url": item["link"], "seller": item.get("seller_name"),
                      "merchant_tokens": ["JPYC"], "price_min_jpyc": info.get("price_jpyc_min"),
                      "price_max_jpyc": info.get("price_jpyc_max"),
                      "requires_shipping": info.get("requires_shipping"),
                      "kr_direct_shipping": "not_applicable" if info.get("requires_shipping") is False else "unverified",
                      "shipping_status": "check_fulfillment_with_seller", "shipping_fee": None})
        if len(found) == limit:
            break
    return found


def cryptorefills(brand, token, limit=5):
    """한국용 이메일 상품권에 반환된 지정 토큰의 권종별 견적을 조회한다."""
    coin = CR_TOKENS[token]
    rpc = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
           "params": {"name": "listProductsForCountry",
                      "arguments": {"country_code": "KR", "family_name": brand,
                                    "coin": coin, "lang": "en"}}}
    reply = read_json(CR_CATALOG, rpc=rpc)
    if "error" in reply or reply["result"].get("isError"):
        raise ValueError("Cryptorefills 상품 조회 실패")
    brands = reply["result"]["structuredContent"]["result"]
    found = []
    for family in brands:
        if family["country_code"] != "KR" or family["kind"] != "giftcard" or family.get("is_out_of_stock"):
            continue
        for item in family["products"]:
            if item.get("coin") != coin or item.get("delivery_type") != "by_email":
                continue
            found.append({"category": "gift_card", "brand": family["brand"], "product_id": item["product_id"],
                          "face_value": item["face_value"], "denomination": item["denomination"],
                          "payment_token": token, "token_amount": item.get("coin_amount"),
                          "payment_method": item.get("payment_method"),
                          "redemption_country": "KR", "delivery": "email", "kr_direct_shipping": "not_applicable"})
            if len(found) == limit:
                return found
    return found


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("site", choices=("sease", "jpyc", "cryptorefills"))
    parser.add_argument("query", help="상품 검색어 또는 Cryptorefills의 브랜드명")
    parser.add_argument("--token", choices=CR_TOKENS, help="Cryptorefills 견적 통화 (기본 USDC)")
    parser.add_argument("--limit", type=int, choices=range(1, 11), default=5)
    args = parser.parse_args()
    if not args.query.strip():
        parser.error("검색어 또는 브랜드명을 입력하세요.")
    if args.token and args.site != "cryptorefills":
        parser.error("--token은 Cryptorefills의 권종별 견적에 사용합니다.")
    try:
        if args.site == "cryptorefills":
            rows = cryptorefills(args.query, args.token or "USDC", args.limit)
        elif args.site == "sease":
            rows = sease(args.query, args.limit)
        else:
            rows = jpyc_ec(args.query, args.limit)
        print(json.dumps({"site": args.site, "items": rows}, ensure_ascii=False, indent=2))
    except (URLError, OSError, ValueError, KeyError) as error:
        parser.exit(1, f"조회 실패: {error}\n")
