"""한국 국내 배송 및 해외 직배송 상품 조회. 실행 방법은 README.md 참조."""

import argparse
import base64
import hmac
import json
import os
import re
import subprocess
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html import unescape
from http.client import HTTPException
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


def request_json(url, *, query=None, form=None, json_body=None, headers=None, timeout=15):
    if query:
        url += "?" + urlencode(query)
    data = urlencode(form).encode() if form is not None else None
    if json_body is not None:
        data = json.dumps(json_body).encode()
        headers = {"Content-Type": "application/json", **(headers or {})}
    request = Request(url, data=data, headers={"Accept": "application/json", **(headers or {})})
    try:
        with urlopen(request, timeout=timeout) as response:
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
JP_STORES = {"japanesetaste.kr": "Japanese Taste", "www.smikiejapan.com": "SmikieJapan"}
CN_STORES = {"lapsangstore.com": "LAPSANGSTORE", "stationerypal.com": "Stationery Pal"}
STOREFRONTS = {
    "KR": KR_STORES,
    "JP": JP_STORES,
    "CN": CN_STORES,
    "US": {"yosekastationery.com": "Yoseka Stationery"},
    "GB": {"cultpens.com": "Cult Pens"},
    "DE": {"www.papierundstift.de": "Papier & Stift"},
    "FR": {"www.art-du-papier.fr": "L’Art du Papier"},
    "IT": {"sanroccoitalia.it": "San Rocco Italia"},
    "ES": {"twojeys.com": "Twojeys"},
    "AU": {"www.boody.com.au": "Boody", "ozanwarehouse.com": "OZAN Warehouse"},
    "TW": {"www.ystudiostyle.com": "YSTUDIO"},
}
MARKET_LANGUAGE = {"JP": "JA", "CN": "ZH_CN", "TW": "ZH_TW", "DE": "DE", "FR": "FR",
                   "IT": "IT", "ES": "ES"}
SEARCH_ERRORS = (OSError, HTTPException, RuntimeError, ValueError, KeyError, TypeError)
KR_CATALOG_QUERY = """
query Products($query: String!, $limit: Int!, $withOrigin: Boolean!, $language: LanguageCode!) @inContext(country: KR, language: $language) {
  localization { availableLanguages { isoCode } }
  search(query: $query, first: $limit, types: [PRODUCT], unavailableProducts: HIDE) {
    nodes { ... on Product {
      title onlineStoreUrl availableForSale
      options @include(if: $withOrigin) { name values }
      priceRange { minVariantPrice { amount currencyCode } }
    } }
  }
}
"""


def mainland_dispatch(options):
    origin_names = {"ships from", "ship from", "dispatch country", "출고지", "발송지", "发货地"}
    mainland = {"cn", "mainland china", "china mainland", "중국 본토", "中国大陆", "中国内地"}
    for option in options:
        if option["name"].strip().casefold() in origin_names:
            values = {value.strip().casefold() for value in option["values"]}
            return bool(values) and values <= mainland
    return False


def storefront_page(host, seller, keyword, limit, market, language="KO"):
    response = request_json(
        f"https://{host}/api/2026-10/graphql.json",
        timeout=5 if market == "KR" else 15,
        json_body={"query": KR_CATALOG_QUERY, "variables": {"query": keyword, "limit": limit,
                  "withOrigin": market == "CN", "language": language}},
    )
    if response.get("errors") or response.get("extensions", {}).get("context", {}).get("country") != "KR":
        raise RuntimeError("한국 시장의 상품 응답을 확인할 수 없습니다.")
    checked_at = datetime.now(timezone.utc).isoformat()
    rows = []
    for product in response["data"]["search"]["nodes"]:
        price = product["priceRange"]["minVariantPrice"]
        url = product.get("onlineStoreUrl")
        currency = price["currencyCode"]
        if not product["availableForSale"] or not url or (market == "KR" and currency != "KRW"):
            continue
        row = offer(product["title"], url, money(price["amount"], currency), None,
                    "seller_check_required",
                    kr_direct_shipping="not_applicable" if market == "KR" else "unverified")
        row.update(market=market, seller=seller, price_source="seller_catalog",
                   price_basis="min_variant_price", checked_at=checked_at)
        if market == "CN" and mainland_dispatch(product.get("options", [])):
            row.update(dispatch_country="CN", dispatch_source="product_shipping_option")
        rows.append(row)
    languages = {lang["isoCode"] for lang in response["data"]["localization"]["availableLanguages"]}
    return rows, languages


def title_matches(title, keyword):
    title = unicodedata.normalize("NFKC", title).casefold()
    terms = re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", keyword).casefold())
    return bool(terms) and all(term in title for term in terms)


NIKE_STYLE = re.compile(r"\b[A-Z0-9]{2}\d{4}-\d{3}\b", re.I)


def nike_query(keyword):
    term = unicodedata.normalize("NFKC", keyword).casefold()
    term = re.sub(r"\bnike\b", "나이키", term)
    term = re.sub(r"\bair\s*force\s*(?=1)|에어\s*포스\s*(?=1)", "에어 포스 ", term)
    term = re.sub(r"\b(?:shoes?|sneakers?)\b|운동화", "신발", term)
    if re.search(r"나이키|에어 포스|신발", term) or NIKE_STYLE.search(term):
        return term


def nike_korea(keyword, limit):
    url = "https://www.nike.com/kr/w?" + urlencode({"q": keyword})
    request = Request(url, headers={"User-Agent": "FCC-catalog/1.0"})
    with urlopen(request, timeout=5) as response:
        page = response.read().decode("utf-8")
    data = re.search(r'<script\b[^>]*\bid=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', page, re.S)
    if not data:
        raise ValueError("나이키 코리아 상품 목록을 읽을 수 없습니다.")
    wall = json.loads(data[1])["props"]["pageProps"]["initialState"]["Wall"]
    groups = [group["products"] for group in wall["productGroupings"] if group.get("products")]
    codes = {code.upper() for code in NIKE_STYLE.findall(keyword)}
    checked_at = datetime.now(timezone.utc).isoformat()
    rows = []
    seen = set()
    # Show different models before additional colours of the same model.
    for variants in zip_longest(*groups):
        for product in filter(None, variants):
            code = product["productCode"]
            if code in seen or (codes and code not in codes):
                continue
            name = product["copy"]["title"]
            category = product["copy"]["subTitle"]
            color = product.get("displayColors", {}).get("colorDescription", "")
            labels = [name, category, code, color, "나이키"]
            if product.get("productType") == "FOOTWEAR":
                labels.append("신발")
            price = product["prices"]
            link = product["pdpUrl"]["url"]
            if not (title_matches(" ".join(labels), keyword) and link.startswith("https://www.nike.com/kr/t/")
                    and price["currency"] == "KRW" and price.get("currentPrice") is not None):
                continue
            seen.add(code)
            row = offer(name, link, money(price["currentPrice"], "KRW"), None,
                        "seller_check_required", kr_direct_shipping="not_applicable")
            row.update(market="KR", seller="나이키 코리아", model_code=code, color=color,
                       category=category, price_source="seller_catalog", price_basis="listed_price",
                       checked_at=checked_at)
            rows.append(row)
            if len(rows) == limit:
                return rows
    return rows


def translate_keyword(keyword, language):
    if len(keyword.encode("utf-8")) > 500:
        raise ValueError("번역할 검색어가 500바이트를 넘습니다.")
    target = language.replace("_", "-").lower()
    response = request_json("https://api.mymemory.translated.net/get",
                            query={"q": keyword, "langpair": "ko|" + target})
    if str(response.get("responseStatus")) != "200" or response.get("quotaFinished"):
        raise RuntimeError(f"MyMemory 번역 실패 (상태 {response.get('responseStatus')})")
    translated = unescape(response["responseData"]["translatedText"]).strip()
    if not translated:
        raise ValueError("번역된 검색어가 비어 있습니다.")
    # Keep Latin brand names and model codes if the translator drops or rewrites them.
    identifiers = re.findall(r"[A-Za-z0-9]+(?:[-./+][A-Za-z0-9]+)*", keyword)
    for token in identifiers:
        if token.casefold() not in translated.casefold():
            translated += " " + token
    return translated


def storefront_search(market, keyword, limit):
    if market == "OVERSEAS":
        markets = {country: stores for country, stores in STOREFRONTS.items() if country != "KR"}
    else:
        markets = STOREFRONTS if market == "ALL" else {market: STOREFRONTS[market]}
    stores = [(country, host, seller) for country, shops in markets.items() for host, seller in shops.items()]
    batches = {}
    errors = {}
    retry = {}
    translations = {}
    korean = bool(re.search(r"[가-힣]", keyword))
    with ThreadPoolExecutor(max_workers=6) as pool:
        nike_term = nike_query(keyword) if "KR" in markets else None
        nike = pool.submit(nike_korea, nike_term, limit) if nike_term else None
        first = {seller: pool.submit(storefront_page, host, seller, keyword, limit, country)
                 for country, host, seller in stores}
        for country, host, seller in stores:
            try:
                rows, languages = first[seller].result()
            except SEARCH_ERRORS as exc:
                errors[seller] = str(exc)
                continue
            if korean or country == "KR":
                rows = [row for row in rows if title_matches(row["title"], keyword)]
            batches[seller] = rows
            if rows or not korean or country == "KR":
                continue
            preferred = MARKET_LANGUAGE.get(country, "EN")
            language = preferred if preferred in languages else "EN"
            if language in languages:
                retry[seller] = (country, host, language)
                if language not in translations:
                    translations[language] = pool.submit(translate_keyword, keyword, language)

        retries = {}
        queries = {}
        for seller, (country, host, language) in retry.items():
            try:
                translated = translations[language].result()
            except SEARCH_ERRORS as exc:
                errors[seller] = f"검색어 번역 실패 ({language}) {exc}"
                continue
            if translated.casefold() == keyword.casefold():
                continue
            queries[seller] = {"language": language, "keyword": translated}
            retries[seller] = pool.submit(storefront_page, host, seller, translated, limit, country, language)
        for seller, future in retries.items():
            try:
                rows, _ = future.result()
                batches[seller] = [row for row in rows if title_matches(row["title"], queries[seller]["keyword"])]
            except SEARCH_ERRORS as exc:
                errors[seller] = str(exc)

        if nike:
            try:
                batches["나이키 코리아"] = nike.result()
            except SEARCH_ERRORS as exc:
                errors["나이키 코리아"] = str(exc)

    items = [row for group in zip_longest(*batches.values()) for row in group if row is not None]
    result = {"market": market, "destination_country": "KR", "errors": errors, "translated_queries": queries}
    if market in ("AU", "TW"):
        result["mvp_payment_scope"] = "fiat_only"
    if market == "KR":
        terms = keyword.casefold().split()
        items.sort(key=lambda row: sum(term not in row["title"].casefold() for term in terms))
        query = urlencode({"query": keyword})
        result["browser_search"] = {
            "danawa": "https://search.danawa.com/dsearch.php?" + query,
            "naver": "https://search.naver.com/search.naver?" + query,
        }
    selected = items[:limit]
    if market in ("ALL", "OVERSEAS", "CN"):
        result["dispatch_unverified_items"] = [row for row in selected
                                               if row["market"] == "CN" and row["dispatch_country"] is None]
        selected = [row for row in selected if row["market"] != "CN" or row["dispatch_country"] is not None]
    result["items"] = selected
    return result


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


def ebay_money(amount):
    original = money(amount.get("convertedFromValue"), amount.get("convertedFromCurrency"))
    return original or money(amount.get("value"), amount.get("currency"))


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
        offers.append(offer(item["title"], item["itemWebUrl"], ebay_money(price),
                            ebay_money(cost), "destination_filter", country))
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
    """선택한 판매처의 첫 검색 페이지에서 한국 배송 후보를 조회한다."""
    if not keyword.strip() or not 1 <= limit <= 30:
        raise ValueError("검색어와 1~30 사이의 조회 건수가 필요합니다.")
    if market in EBAY_COUNTRIES and postal_code is not None:
        items = ebay(market, keyword, limit, postal_code)
        result = {"market": market, "destination_country": "KR", "items": items}
        korean = bool(re.search(r"[가-힣]", keyword))
        if korean:
            result["items"] = [row for row in items if title_matches(row["title"], keyword)]
        if not result["items"] and korean:
            language = MARKET_LANGUAGE.get(market, "EN")
            try:
                translated = translate_keyword(keyword, language)
                if translated.casefold() != keyword.casefold():
                    result["translated_queries"] = {"eBay": {"language": language, "keyword": translated}}
                    rows = ebay(market, translated, limit, postal_code)
                    result["items"] = [row for row in rows if title_matches(row["title"], translated)]
            except SEARCH_ERRORS as exc:
                result["errors"] = {"eBay": str(exc)}
        return result
    if market in ("ALL", "OVERSEAS") or market in STOREFRONTS:
        return storefront_search(market, keyword, limit)
    raise ValueError(f"지원하지 않는 시장 {market}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("market", choices=("ALL", "OVERSEAS", *STOREFRONTS))
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
