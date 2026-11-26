"""법정통화 한 단위와 스테이블코인 한 개의 원화 참고 가격을 조회한다."""

import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


KST = timezone(timedelta(hours=9))
# ECOS 731Y001 항목 코드와 고시 단위. 원/위안 매매기준율은 서울 역외시장 기준이다.
ECOS_ITEMS = {
    "CNH": ("0000053", 1),
    "JPY": ("0000002", 100),
    "EUR": ("0000003", 1),
    "USD": ("0000001", 1),
}
TOKENS = {"JPYC": "JPY", "EURC": "EUR", "USDC": "USD", "USDT": "USD"}


def fetch(url):
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=15) as response:
        return json.load(response, parse_float=Decimal)


def positive_price(value):
    if not isinstance(value, (Decimal, int, str)) or isinstance(value, bool):
        return None
    try:
        price = Decimal(value)
    except InvalidOperation:
        return None
    return price if price.is_finite() and price > 0 else None


def fiat_rates(currencies=ECOS_ITEMS):
    key = quote(os.environ.get("ECOS_API_KEY") or "sample", safe="")
    today = datetime.now(KST).date()
    start = today - timedelta(days=9)
    period = f"{start:%Y%m%d}/{today:%Y%m%d}"
    base = f"https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/10/731Y001/D/{period}"
    rates = {code: {"krw_per_unit": None, "rate_date": None} for code in currencies}
    for code in rates:
        item, units = ECOS_ITEMS[code]
        data = fetch(f"{base}/{item}")
        result = data.get("RESULT", {})
        if result.get("CODE") == "INFO-200":
            continue
        if "StatisticSearch" not in data:
            raise ValueError("한국은행 ECOS 조회 실패 (" + str(result.get("CODE", "응답 형식 오류")) + ")")
        for row in sorted(data["StatisticSearch"]["row"], key=lambda r: r["TIME"], reverse=True):
            price = positive_price(row.get("DATA_VALUE"))
            if row.get("ITEM_CODE1") == item and price is not None:
                date = datetime.strptime(row["TIME"], "%Y%m%d").date()
                rates[code] = {"krw_per_unit": format(price / units, "f"), "rate_date": date.isoformat()}
                break
    return rates


def stablecoin_prices():
    rows = fetch("https://api.upbit.com/v1/ticker/all?quote_currencies=KRW")
    if not isinstance(rows, list) or not rows:
        raise ValueError("업비트 원화 마켓 현재가 목록을 읽을 수 없습니다.")
    quotes = {symbol: {"peg_currency": peg, "krw_per_unit": None, "updated_at": None}
              for symbol, peg in TOKENS.items()}
    for row in rows:
        currency, _, symbol = row["market"].partition("-")
        if currency != "KRW" or symbol not in quotes:
            continue
        price = positive_price(row.get("trade_price"))
        timestamp = row.get("trade_timestamp")
        if price is not None and isinstance(timestamp, int) and timestamp > 0:
            quotes[symbol]["krw_per_unit"] = format(price, "f")
            quotes[symbol]["updated_at"] = datetime.fromtimestamp(timestamp / 1000, timezone.utc).isoformat()
    return quotes


def get_market_rates():
    result = {"quote_currency": "KRW", "sources": {"fiat": "한국은행 ECOS", "stablecoins": "업비트 KRW"}, "errors": {}}
    for name, lookup in (("fiat", fiat_rates), ("stablecoins", stablecoin_prices)):
        try:
            result[name] = lookup()
        except (URLError, OSError, ValueError, KeyError) as exc:
            result[name] = None
            result["errors"][name] = str(exc)
    return result


if __name__ == "__main__":
    snapshot = get_market_rates()
    print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    raise SystemExit(1 if snapshot["errors"] else 0)
