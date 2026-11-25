"""법정통화 한 단위와 스테이블코인 한 개의 원화 참고 가격을 조회한다."""

import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


FIAT = ("CNY", "CNH", "JPY", "EUR", "USD")
# CoinGecko IDs identify the asset even when multiple tokens share a ticker.
TOKENS = {
    "JPYC": ("jpycoin", "JPY"),
    "EURC": ("euro-coin", "EUR"),
    "USDC": ("usd-coin", "USD"),
    "USDT": ("tether", "USD"),
}


def fetch(url, params, headers=None):
    request = Request(url + "?" + urlencode(params), headers=headers or {})
    with urlopen(request, timeout=15) as response:
        return json.load(response, parse_float=Decimal)


def positive_price(value):
    if isinstance(value, bool) or not isinstance(value, (Decimal, int)):
        return None
    price = Decimal(value)
    return price if price.is_finite() and price > 0 else None


def fiat_rates():
    rows = fetch("https://api.frankfurter.dev/v2/rates",
                 {"base": "KRW", "quotes": ",".join(FIAT)})
    if not isinstance(rows, list):
        raise ValueError("Frankfurter 환율 목록을 읽을 수 없습니다.")
    rates = {code: {"krw_per_unit": None, "rate_date": None} for code in FIAT}
    for row in rows:
        code = row.get("quote")
        if row.get("base") != "KRW" or code not in rates:
            continue
        rate = positive_price(row.get("rate"))
        if rate is not None and row.get("date"):
            rates[code] = {"krw_per_unit": format(1 / rate, ".12f"), "rate_date": row["date"]}
    return rates


def stablecoin_prices():
    params = {"ids": ",".join(coin_id for coin_id, _ in TOKENS.values()),
              "vs_currencies": "krw", "include_last_updated_at": "true", "precision": "full"}
    key = os.getenv("COINGECKO_DEMO_API_KEY")
    prices = fetch("https://api.coingecko.com/api/v3/simple/price", params,
                   {"x-cg-demo-api-key": key} if key else {})
    if not isinstance(prices, dict) or "error" in prices or "status" in prices:
        raise ValueError("CoinGecko 시세를 읽을 수 없습니다.")
    quotes = {}
    for symbol, (coin_id, peg) in TOKENS.items():
        row = prices.get(coin_id) or {}
        price = positive_price(row.get("krw"))
        timestamp = row.get("last_updated_at")
        updated_at = None
        if isinstance(timestamp, int) and timestamp > 0:
            updated_at = datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
        quotes[symbol] = {"peg_currency": peg, "krw_per_unit": str(price) if price else None,
                          "updated_at": updated_at}
    return quotes


def get_market_rates():
    result = {"quote_currency": "KRW", "errors": {}}
    for name, lookup in (("fiat", fiat_rates), ("stablecoins", stablecoin_prices)):
        try:
            result[name] = lookup()
        except (URLError, OSError, ValueError) as exc:
            result[name] = None
            result["errors"][name] = str(exc)
    return result


if __name__ == "__main__":
    snapshot = get_market_rates()
    print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    raise SystemExit(1 if snapshot["errors"] else 0)
