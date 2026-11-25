"""한국 국내 배송 및 해외 직배송 상품 조회. 실행 방법은 README.md 참조."""

import argparse
import base64
import hmac
import json
import os
import re
from datetime import datetime, timedelta, timezone
from html import unescape
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


EBAY_COUNTRIES = ("US", "DE", "FR", "GB", "IT", "ES")


def credential(name):
    value = os.getenv(name)
    if not value:
        raise ValueError(f"환경변수 {name} 설정이 필요합니다.")
    return value


def request_json(url, *, query=None, form=None, headers=None):
    if query:
        url += "?" + urlencode(query)
    data = urlencode(form).encode() if form is not None else None
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


def offer(title, url, price, shipping, status, dispatch=None):
    return {
        "title": title, "url": url, "price": price, "shipping": shipping,
        "shipping_status": status, "dispatch_country": dispatch,
    }


def naver(keyword, limit):
    result = request_json(
        "https://openapi.naver.com/v1/search/shop.json",
        query={"query": keyword, "display": limit, "exclude": "cbshop"},
        headers={"X-Naver-Client-Id": credential("NAVER_CLIENT_ID"),
                 "X-Naver-Client-Secret": credential("NAVER_CLIENT_SECRET")},
    )
    offers = []
    for item in result["items"]:
        title = unescape(re.sub(r"</?b>", "", item["title"]))
        price = item.get("lprice")
        offers.append(offer(title, item["link"], money(price, "KRW") if price not in (0, "0") else None,
                            None, "seller_check_required"))
    return offers


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
    # TOP signs the sorted, unescaped parameter names and values before form encoding.
    params.update(method=method, app_key=credential("ALIEXPRESS_APP_KEY"), v="2.0",
                  format="json", sign_method="hmac",
                  timestamp=datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S"))
    payload = "".join(key + str(params[key]) for key in sorted(params))
    secret = credential("ALIEXPRESS_APP_SECRET").encode()
    params["sign"] = hmac.new(secret, payload.encode(), "md5").hexdigest().upper()
    response = request_json("https://eco.taobao.com/router/rest", form=params)
    if "error_response" in response:
        error = response["error_response"]
        raise RuntimeError(f"AliExpress {method}: {error.get('sub_code') or error.get('code')}")
    return response[method.replace(".", "_") + "_response"]


def aliexpress(keyword, limit):
    search = aliexpress_call("aliexpress.affiliate.product.query", keywords=keyword,
                             ship_to_country="KR", target_currency="USD", page_no=1, page_size=limit)
    result = search["resp_result"]
    if str(result["resp_code"]) != "200":
        raise RuntimeError(f"AliExpress 검색 오류 ({result['resp_code']})")
    products = (result["result"].get("products") or {}).get("product", [])
    offers = []
    for item in products[:limit]:
        freight = aliexpress_call("aliexpress.social.product.freight.query", product_id=item["product_id"],
                                  quantity=1, ship_from_country="CN", ship_to_country="KR", currency="USD")
        route = freight.get("result") or {}
        origin = (route.get("send_goods_country_full_name") or "").strip().casefold()
        if not route.get("company") or origin not in {"cn", "china", "中国"}:
            continue
        offers.append(offer(item["product_title"], item["product_detail_url"],
                            money(item.get("sale_price"), item.get("sale_price_currency")),
                            money(route.get("freight_amount"), route.get("currency")), "freight_quote", "CN"))
    return offers


def search(market, keyword, limit=5, postal_code=None):
    """한 시장의 첫 검색 페이지에서 한국 배송 후보를 조회한다."""
    if not keyword.strip() or not 1 <= limit <= 30:
        raise ValueError("검색어와 1~30 사이의 조회 건수가 필요합니다.")
    if market in EBAY_COUNTRIES:
        items = ebay(market, keyword, limit, postal_code)
    else:
        providers = {"KR": naver, "JP": rakuten, "CN": aliexpress}
        if market not in providers:
            raise ValueError(f"지원하지 않는 시장 {market}")
        items = providers[market](keyword, limit)
    return {"market": market, "destination_country": "KR", "items": items}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("market", choices=("KR", *EBAY_COUNTRIES, "JP", "CN"))
    parser.add_argument("keyword")
    parser.add_argument("--postal-code", help="한국 수령지 우편번호 (eBay 필수)")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    try:
        print(json.dumps(search(args.market, args.keyword, args.limit, args.postal_code),
                         ensure_ascii=False, indent=2))
    except (ValueError, KeyError, RuntimeError, URLError, TimeoutError) as error:
        parser.exit(1, f"조회 실패: {error}\n")
