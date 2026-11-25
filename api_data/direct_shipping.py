"""한국 국내 배송 및 해외 직배송 상품 조회. 실행 방법은 README.md 참조."""

import argparse
import base64
import hmac
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from itertools import zip_longest
from time import time_ns
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen


EBAY_COUNTRIES = ("US", "DE", "FR", "GB", "IT", "ES")


def credential(name):
    value = os.getenv(name)
    if value:
        return value
    try:
        result = subprocess.run(
            ["secret-tool", "lookup", "service", "fcc-commerce", "name", name],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, timeout=15,
        )
    except FileNotFoundError:
        raise ValueError(f"{name} 환경변수를 설정하거나 secret-tool을 설치해 키링에 저장하세요.") from None
    except subprocess.TimeoutExpired:
        raise ValueError(f"키링 응답 시간이 초과되었습니다. 잠금 상태를 확인하세요 ({name}).") from None
    secret = result.stdout.rstrip("\n")
    if result.returncode or not secret:
        raise ValueError(f"키링에서 {name}을 읽을 수 없습니다. 잠금 상태와 등록 이름을 확인하세요.")
    return secret


def request_json(url, *, query=None, form=None, json_body=None, headers=None):
    if query:
        url += "?" + urlencode(query)
    data = urlencode(form).encode() if form is not None else None
    if json_body is not None:
        data = json.dumps(json_body).encode()
        headers = {"Content-Type": "application/json", **(headers or {})}
    request = Request(url, data=data, headers={"Accept": "application/json", **(headers or {})})
    try:
        with urlopen(request, timeout=15) as response:
            return json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"{request.host} HTTP {exc.code}") from exc


def money(amount, currency):
    if amount is None or amount == "" or not currency:
        return None
    return {"amount": str(amount), "currency": currency}


def offer(title, url, price, shipping, status, dispatch=None, *, kr_direct_shipping="unverified"):
    return {
        "title": title, "url": url, "price": price, "shipping": shipping,
        "shipping_status": status, "dispatch_country": dispatch,
        "kr_direct_shipping": kr_direct_shipping,
    }


KR_STORES = {"yokorea.store": "Yo! Korea", "pesado585.co.kr": "Pesado Korea"}
KR_CATALOG_QUERY = """
query Products($query: String!, $limit: Int!) @inContext(country: KR, language: KO) {
  search(query: $query, first: $limit, types: [PRODUCT], unavailableProducts: HIDE) {
    nodes { ... on Product {
      title onlineStoreUrl availableForSale
      priceRange { minVariantPrice { amount currencyCode } }
    } }
  }
}
"""


def korean_store_offers(host, keyword, limit):
    response = request_json(
        f"https://{host}/api/2026-10/graphql.json",
        json_body={"query": KR_CATALOG_QUERY, "variables": {"query": keyword, "limit": limit}},
    )
    if response.get("errors") or response.get("extensions", {}).get("context", {}).get("country") != "KR":
        raise RuntimeError("한국 시장의 상품 응답을 확인할 수 없습니다.")
    checked_at = datetime.now(timezone.utc).isoformat()
    rows = []
    for product in response["data"]["search"]["nodes"]:
        price = product["priceRange"]["minVariantPrice"]
        url = product.get("onlineStoreUrl")
        if not product["availableForSale"] or not url or price["currencyCode"] != "KRW":
            continue
        row = offer(product["title"], url, money(price["amount"], "KRW"), None,
                    "seller_check_required", kr_direct_shipping="not_applicable")
        row.update(seller=KR_STORES[host], price_source="seller_catalog",
                   price_basis="min_variant_price", checked_at=checked_at)
        rows.append(row)
    return rows


def korean_search(keyword, limit):
    # Keep each shop's relevance order and give both shops room in the result.
    batches = []
    errors = {}
    for host, seller in KR_STORES.items():
        try:
            batches.append(korean_store_offers(host, keyword, limit))
        except (URLError, TimeoutError, RuntimeError, ValueError, KeyError, TypeError) as exc:
            errors[seller] = str(exc)
    items = [row for group in zip_longest(*batches) for row in group if row is not None]
    terms = keyword.casefold().split()
    items.sort(key=lambda row: sum(term not in row["title"].casefold() for term in terms))
    query = urlencode({"query": keyword})
    return {"market": "KR", "destination_country": "KR", "items": items[:limit],
            "errors": errors, "browser_search": {
                "danawa": "https://search.danawa.com/dsearch.php?" + query,
                "naver": "https://search.naver.com/search.naver?" + query,
            }}


def naver_web_search(keyword, limit):
    if not keyword.strip() or not 1 <= limit <= 30:
        raise ValueError("검색어와 1~30 사이의 조회 건수가 필요합니다.")
    response = request_json(
        "https://naverapihub.apigw.ntruss.com/search/v1/webkr",
        query={"query": keyword, "display": limit},
        headers={"X-NCP-APIGW-API-KEY-ID": credential("NAVER_HUB_CLIENT_ID"),
                 "X-NCP-APIGW-API-KEY": credential("NAVER_HUB_CLIENT_SECRET")},
    )
    return {"source": "NAVER 웹문서 검색", "results": response["items"]}


def confirmed_offer(title, url, price, shipping):
    if not title.strip():
        raise ValueError("선택한 상품명을 입력하세요.")
    link = urlsplit(url)
    if link.scheme != "https" or not link.hostname or link.username is not None or link.password is not None:
        raise ValueError("판매처의 HTTPS 상품 주소를 입력하세요.")
    if price < 0 or (shipping is not None and shipping < 0):
        raise ValueError("원화 금액은 0 이상이어야 합니다.")
    row = offer(title, url, money(price, "KRW"), money(shipping, "KRW"), "seller_check_required")
    row.update(seller=link.hostname, price_source="buyer_confirmed",
               checked_at=datetime.now(timezone.utc).isoformat())
    return {"market": "KR", "destination_country": "KR", "items": [row]}


def rakuten(keyword, limit):
    headers = {"accessKey": credential("RAKUTEN_ACCESS_KEY")}
    if origin := os.getenv("RAKUTEN_ORIGIN"):
        headers["Origin"] = origin
        headers["Referer"] = origin.rstrip("/") + "/"
    result = request_json(
        "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260701",
        query={"applicationId": credential("RAKUTEN_APP_ID"), "keyword": keyword,
               "hits": limit, "format": "json", "formatVersion": 2,
               "shipOverseasFlag": 1, "shipOverseasArea": "KR"},
        headers=headers,
    )
    items = result["items"] if "items" in result else result["Items"]
    return [offer(item["itemName"], item["itemUrl"], money(item["itemPrice"], "JPY"),
                  None, "destination_filter") for item in items]


def ebay(country, keyword, limit, postal_code):
    if not re.fullmatch(r"[0-9]{5}", postal_code or ""):
        raise ValueError("eBay 조회에는 한국 우편번호 5자리가 필요합니다.")
    credentials = credential("EBAY_CLIENT_ID") + ":" + credential("EBAY_CLIENT_SECRET")
    basic = base64.b64encode(credentials.encode()).decode()
    token = request_json(
        "https://api.ebay.com/identity/v1/oauth2/token",
        form={"grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope"},
        headers={"Authorization": "Basic " + basic},
    )["access_token"]
    location = quote(f"country=KR,zip={postal_code}", safe="")
    filters = f"itemLocationCountry:{country},deliveryCountry:KR,deliveryPostalCode:{postal_code}"
    result = request_json(
        "https://api.ebay.com/buy/browse/v1/item_summary/search",
        query={"q": keyword, "limit": limit, "filter": filters},
        headers={"Authorization": "Bearer " + token, "X-EBAY-C-MARKETPLACE-ID": f"EBAY_{country}",
                 "X-EBAY-C-ENDUSERCTX": "contextualLocation=" + location},
    )
    if result.get("warnings"):
        codes = [str(w.get("errorId")) for w in result["warnings"]]
        raise RuntimeError("eBay 조회 조건 확인 필요 (" + ", ".join(codes) + ")")
    offers = []
    for item in result.get("itemSummaries", []):
        if item.get("itemLocation", {}).get("country") != country:
            continue
        options = item.get("shippingOptions") or []
        cost = next((s["shippingCost"] for s in options if s.get("shippingCost")), {})
        price = item["price"]
        offers.append(offer(item["title"], item["itemWebUrl"], money(price["value"], price["currency"]),
                            money(cost.get("value"), cost.get("currency")), "destination_filter", country))
    return offers


def aliexpress_call(method, **params):
    params.update(method=method, app_key=credential("ALIEXPRESS_APP_KEY"), v="2.0",
                  format="json", sign_method="sha256", simplify="true", timestamp=time_ns() // 1_000_000)
    # TOP includes the method as a sorted parameter, without a path prefix.
    payload = "".join(key + str(params[key]) for key in sorted(params))
    secret = credential("ALIEXPRESS_APP_SECRET").encode()
    params["sign"] = hmac.new(secret, payload.encode(), "sha256").hexdigest().upper()
    response = request_json("https://api-sg.aliexpress.com/sync", query={"method": method}, form=params)
    if "error_response" in response or str(response.get("code", "0")) != "0":
        error = response.get("error_response") or response
        raise RuntimeError(f"AliExpress {method}: {error.get('sub_code') or error.get('code')}")
    body = response.get(method.replace(".", "_") + "_response", response)
    result = body["resp_result"]
    if str(result["resp_code"]) != "200":
        raise RuntimeError(f"AliExpress {method}: {result['resp_code']}")
    return result.get("result") or {}


def aliexpress_search(keyword, limit):
    destination = {"ship_to_country": "KR", "target_language": "KO", "target_currency": "KRW"}
    result = aliexpress_call("aliexpress.affiliate.product.query", keywords=keyword,
                             page_no=1, page_size=limit, **destination)
    offers = []
    pending = []
    errors = {}
    products = result.get("products") or []
    if isinstance(products, dict):
        products = products.get("product") or []
    for item in products[:limit]:
        price = money(item.get("target_sale_price"), item.get("target_sale_price_currency"))
        row = offer(item["product_title"], item["product_detail_url"], price, None, "destination_filter")
        required = ("product_id", "sku_id", "tax_rate", "target_sale_price")
        if any(item.get(key) in (None, "") for key in required) or not price or price["currency"] != "KRW":
            pending.append(row)
            continue
        try:
            route = aliexpress_call("aliexpress.affiliate.product.shipping.get",
                                    **{key: item[key] for key in required}, **destination)
        except (RuntimeError, URLError, TimeoutError, ValueError, KeyError) as exc:
            errors[str(item["product_id"])] = str(exc)
            pending.append(row)
            continue
        origin = (route.get("ship_from_country") or "").strip().upper()
        if not origin:
            pending.append(row)
        elif origin == "CN":
            row.update(dispatch_country=origin,
                       shipping=money(route.get("shipping_fee"), destination["target_currency"]))
            if row["shipping"] is not None:
                row["shipping_status"] = "freight_quote"
            offers.append(row)
    return {"market": "CN", "destination_country": "KR", "items": offers,
            "dispatch_unverified_items": pending, "shipping_errors": errors}


def aliexpress(keyword, limit):
    """중국 출고가 확인된 한국 배송 후보를 반환한다."""
    return aliexpress_search(keyword, limit)["items"]


def search(market, keyword, limit=5, postal_code=None):
    """한 시장의 첫 검색 페이지에서 한국 배송 후보를 조회한다."""
    if not keyword.strip() or not 1 <= limit <= 30:
        raise ValueError("검색어와 1~30 사이의 조회 건수가 필요합니다.")
    if market == "KR":
        return korean_search(keyword, limit)
    if market == "CN":
        return aliexpress_search(keyword, limit)
    if market in EBAY_COUNTRIES:
        items = ebay(market, keyword, limit, postal_code)
    elif market == "JP":
        items = rakuten(keyword, limit)
    else:
        raise ValueError(f"지원하지 않는 시장 {market}")
    return {"market": market, "destination_country": "KR", "items": items}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("market", choices=("KR", *EBAY_COUNTRIES, "JP", "CN"))
    parser.add_argument("keyword")
    parser.add_argument("--postal-code", help="한국 수령지 우편번호 (eBay 필수)")
    parser.add_argument("--limit", type=int, default=5)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--naver-web", action="store_true", help="네이버 웹문서 검색 결과 보기 (KR)")
    modes.add_argument("--selected-url", help="직접 확인한 판매처 상품 링크 (KR)")
    parser.add_argument("--confirmed-price-krw", type=int, help="선택한 상품의 확인 가격(원)")
    parser.add_argument("--shipping-krw", type=int, help="확인한 배송비(원)")
    args = parser.parse_args()
    if (args.naver_web or args.selected_url is not None) and args.market != "KR":
        parser.error("웹검색과 선택 상품 입력은 KR에서 사용할 수 있습니다.")
    if (args.selected_url is not None) != (args.confirmed_price_krw is not None):
        parser.error("--selected-url과 --confirmed-price-krw를 함께 입력하세요.")
    if args.shipping_krw is not None and args.selected_url is None:
        parser.error("--shipping-krw에는 --selected-url이 필요합니다.")
    try:
        if args.naver_web:
            result = naver_web_search(args.keyword, args.limit)
        elif args.selected_url is not None:
            result = confirmed_offer(args.keyword, args.selected_url, args.confirmed_price_krw, args.shipping_krw)
        else:
            result = search(args.market, args.keyword, args.limit, args.postal_code)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, KeyError, RuntimeError, URLError, TimeoutError) as error:
        parser.exit(1, f"조회 실패: {error}\n")
