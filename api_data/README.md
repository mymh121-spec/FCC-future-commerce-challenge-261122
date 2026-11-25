# 한국 배송 상품 및 원화 시세 조회 API

[direct_shipping.py](./direct_shipping.py)는 Python 표준 라이브러리로 시장 한 곳의 상품을 검색한다. 해외 배송 목적지는 한국으로 고정한다.

| 시장 코드 | 데이터 출처 | 한국 배송 범위 |
| --- | --- | --- |
| KR | [네이버 쇼핑 검색](https://developers.naver.com/docs/serviceapi/search/shopping/shopping.md) | 해외직구와 구매대행 분류를 제외한 국내 쇼핑 검색 결과다. 판매처에서 배송 가능 여부와 배송비를 확인해야 한다. |
| US | [eBay Browse](https://developer.ebay.com/api-docs/buy/static/ref-buy-browse-filters.html) | 미국 소재 상품을 한국 수령지 우편번호로 필터링해 직배송 후보를 조회한다. |
| DE, FR, GB, IT, ES | [eBay 유럽 마켓](https://developer.ebay.com/api-docs/buy/static/ref-marketplace-supported.html) | 독일, 프랑스, 영국, 이탈리아, 스페인을 각각 조회한다. 선택한 마켓 국가에 있는 상품에 미국과 같은 배송 조건을 적용한다. |
| JP | [라쿠텐 이치바 상품 검색](https://webservice.rakuten.co.jp/documentation/ichiba-item-search) | 해외 배송 플래그와 [한국 배송 지역 코드](https://webservice.rakuten.co.jp/documentation/areacode/shipoverseasarea)를 함께 적용한다. 해외 배송비는 판매처에서 확인한다. |
| CN | [AliExpress 제휴 상품 검색](https://open.alitrip.com/doc2/apiDetail.htm?apiId=45803), [상품 운임 조회](https://developer.alibaba.com/doc2/apiDetail.htm?apiId=48730) | 한국을 목적지로 검색한 후 상품 1개 기준 중국발 한국행 운임을 조회한다. 응답에서 중국 출고와 배송사를 확인한 상품을 반환한다. |

## 실행

Python 3.8 이상에서 저장소 루트를 기준으로 실행한다. 해당 시장의 운영 자격 증명을 환경변수로 설정한다.

| 시장 | 환경변수 |
| --- | --- |
| KR | `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` |
| US 및 유럽 | `EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET`. [Browse 운영 접근 승인](https://developer.ebay.com/api-docs/buy/static/buy-requirements.html)이 필요하다. |
| JP | `RAKUTEN_APP_ID`, `RAKUTEN_ACCESS_KEY`. 앱에 허용한 웹사이트를 지정할 때는 `RAKUTEN_ORIGIN`에 해당 사이트의 origin을 넣는다. |
| CN | `ALIEXPRESS_APP_KEY`, `ALIEXPRESS_APP_SECRET`. TOP에서 제휴 상품 검색과 상품 운임 조회를 모두 호출할 수 있는 앱 키를 사용한다. |

```text
python3 api_data/direct_shipping.py 시장코드 "검색어" [--postal-code 한국우편번호] [--limit 조회건수]
```

eBay는 한국 수령지 우편번호 5자리가 필수다. 조회 건수는 기본 5개이며 중국은 각 검색 결과에 운임 조회가 한 번씩 추가된다.

## 응답 해석

- `kr_direct_shipping`은 상품별 한국 직배송 확인 상태다. 해외 실물 상품은 `unverified`(확인 필요)로 표시한다. 한국 배송 필터를 통과하거나 운임 견적이 있어도 선택한 옵션과 수량을 실제 한국 주소로 받을 수 있는지는 판매처에서 확인해야 한다. 국내 쇼핑 검색 결과와 배송이 필요 없는 상품에는 `not_applicable`을 사용한다.
- `seller_check_required`는 판매처에서 배송 가능 여부를 확인해야 하는 상품이다. `destination_filter`는 한국 배송 조건으로 검색된 후보이며, `freight_quote`는 운임 조회에서 배송편을 확인한 후보다.
- `price`와 `shipping`에는 금액과 통화를 각각 담는다. 배송비가 없으면 `null`, 무료 배송을 명시한 응답은 금액 `"0"`이다. 상품가에 배송비나 세금이 모두 포함됐다고 가정하지 않는다.
- `market`은 검색 시장이다. 출고국을 확인할 수 없는 응답에서는 `dispatch_country`를 `null`로 둔다. 특정 옵션이나 수량의 최종 결제액은 판매처에서 확인한다.

## 법정통화 환율과 스테이블코인 시세

`python3 api_data/market_rates.py`를 실행하면 통화 한 단위와 토큰 한 개의 원화 참고 가격을 JSON으로 출력한다. 서버 코드에서는 [market_rates.py](./market_rates.py)의 `get_market_rates()`를 호출한다.

| 법정통화 | 스테이블코인 | 기준 |
| --- | --- | --- |
| CNY |  | ECOS 원/중국위안. 최근 공시가 없으면 미제공 |
| CNH |  | 서울 역외시장의 원/위안 매매기준율 |
| JPY | JPYC | 100엔당 고시값을 100으로 나눈 원/엔 환율과 JPYC 원화 체결가 |
| EUR | EURC | 유로 환율과 EURC 시세 |
| USD | USDC, USDT | 달러 환율과 두 토큰 각각의 시세 |

법정통화는 한국은행 ECOS의 일별 통계표 `731Y001`에서 조회한다. 한국 시간 기준 최근 10일 중 통화별로 가장 최근에 공시된 값을 사용하고 `rate_date`에 실제 기준일을 기록한다. 프로토타입은 공개 `sample` 키로 실행할 수 있으며 발급받은 키는 환경변수 `ECOS_API_KEY`에 설정한다. [한국은행 ECOS Open API](https://ecos.bok.or.kr/api/)

스테이블코인은 업비트 원화 마켓의 최근 체결가를 사용한다. `updated_at`은 UTC 체결 시각이다. 원화 거래쌍이 없으면 해당 토큰의 시세는 `null`이다. 조회에는 인증키가 필요 없다. [업비트 마켓 단위 현재가 조회](https://docs.upbit.com/kr/reference/list-quote-tickers)

금액은 십진 문자열이다. 공급원이 가격을 제공하지 않으면 `krw_per_unit`은 `null`이다. 공급원 요청이 실패하면 해당 그룹을 `null`로 두고 `errors`에 이유를 담는다. 환전 수수료, 네트워크 수수료, 판매처의 토큰 결제 지원 여부는 별도로 확인한다.

## 스테이블코인 결제 판매처

[stablecoin_shops.py](./stablecoin_shops.py)는 공개 API에서 상품 또는 권종별 견적을 조회한다. 아래 명령은 API 키 없이 실행할 수 있다.

| 판매처 | 토큰 | API와 한국 구매 범위 |
| --- | --- | --- |
| [Coinbase Shop](https://coinbaseshop.com/collections/all-products) | USDC | 의류와 잡화의 재고 및 표시 가격을 조회한다. Coinbase는 Base 네트워크의 USDC 결제를 안내한다. 판매처는 국제 배송을 안내하지만 상품별 한국 직배송과 배송비는 미확인이다. [USDC 결제 안내](https://www.coinbase.com/en-ca/blog/coinbase-and-shopify-bring-usdc-payments-on-base-to-millions-of-merchants-worldwide), [판매처 배송 FAQ](https://coinbaseshop.com/pages/faqs), [Shopify 검색 API](https://shopify.dev/docs/api/ajax/reference/predictive-search) |
| JPYC EC | JPYC | 상품 피드에서 실판매 상품과 JPYC 가격 범위를 가져온다. 한국 직배송은 미확인 상태다. 배송 필요 여부가 거짓인 경우에도 수령 방법을 상품 페이지에서 확인한다. [상품 및 결제 API 명세](https://ec.jpyc-service.com/api/v1/openapi.yaml), [배송 및 지원 체인 안내](https://ec.jpyc-service.com/faq) |
| Cryptorefills 기프트카드 | EURC, USDC, USDT | 한국에서 사용할 수 있는 이메일 상품권을 조회한다. 권종별 토큰 금액과 결제 경로는 API 응답값을 사용한다. EURC의 공급사 코드는 `EUROC`다. 상품권을 살 때 토큰을 받는 곳은 Cryptorefills다. [카탈로그 API](https://www.cryptorefills.com/en/ai-agents), [한국 기프트카드 목록](https://www.cryptorefills.com/en/south_korea/gift_cards) |

```sh
python3 api_data/stablecoin_shops.py coinbase-shop "world tour"
python3 api_data/stablecoin_shops.py jpyc コーヒー
python3 api_data/stablecoin_shops.py cryptorefills Emart --token EURC
```

Coinbase Shop은 상품 가격을 USD로 표시한다. USDC 결제 금액은 결제창에서 확인한다. JPYC EC 주문은 상품 페이지에서 지원 체인을 확인한 뒤 지갑 서명이 필요하다. Cryptorefills의 주문 확정 절차는 [결제 API 문서](https://www.cryptorefills.com/en/api-docs/developers)에서 확인할 수 있다.

### Cryptorefills 수집 범위

MVP에서는 Cryptorefills를 항공권, 기프트카드, 숙박에만 사용한다. 기프트카드 조회 결과에는 `category: gift_card`를 표시한다. 항공사나 호텔 브랜드가 발행한 상품권도 이 분류에 속한다.

항공권 운임과 좌석은 [항공권 검색](https://www.cryptorefills.com/en/flights)에서, 숙박 요금과 빈 객실은 [숙박 검색](https://www.cryptorefills.com/en/stays)에서 확인한다. 두 항목의 실시간 데이터는 파트너 연동이 필요해 MVP에서는 공식 검색 링크만 제공한다. 항공권과 숙박 예약은 배송 대상이 아니다. 기프트카드의 `redemption_country`는 사용 국가를 뜻한다. [파트너 연동 안내](https://www.cryptorefills.com/en/wallets-and-exchanges)

### 한국 수령 시 배대지가 필요한 판매처

[판매처 목록(JSON)](./forwarding_required_shops.json)에서 두 곳 모두 `requires_forwarder_for_kr`를 `true`로 표시한다.

| 판매처 | 결제 수단 | 한국 수령 조건 |
| --- | --- | --- |
| [일본직판(日本直販)](https://www.666-666.jp/) | JPYC (Polygon, 시범 도입) | **배대지 필요**. 일본 국내 주소로만 배송한다. [결제 공지](https://corporate.666-666.jp/news/20261119_notice/), [배송 FAQ](https://www.666-666.jp/view/page/faq) |
| [kstore](https://kstore.ee/en) | EURC (Ethereum, Base, Solana) | **배대지 필요**. 판매처가 배송하는 유럽 국가의 주소가 필요하다. [결제 안내](https://kstore.ee/en/page/cryptocurrency-payments), [배송 국가 목록](https://kstore.ee/en/page/shipping) |
