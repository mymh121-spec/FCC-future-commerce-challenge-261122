# 한국 배송 상품 및 원화 시세 조회 API

[direct_shipping.py](./direct_shipping.py)는 Python 표준 라이브러리로 시장 한 곳의 상품을 검색한다. 해외 배송 목적지는 한국으로 고정한다.

| 시장 코드 | 데이터 출처 | 한국 배송 범위 |
| --- | --- | --- |
| KR | [네이버 쇼핑 검색](https://developers.naver.com/docs/serviceapi/search/shopping/shopping.md) | 해외직구와 구매대행 분류를 제외한 국내 쇼핑 검색 결과다. 판매처에서 배송 가능 여부와 배송비를 확인해야 한다. |
| US | [eBay Browse](https://developer.ebay.com/api-docs/buy/static/ref-buy-browse-filters.html) | 미국에 있는 상품 중 한국 수령지 우편번호로 배송되는 상품을 조회한다. |
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

- `seller_check_required`는 판매처 확인이 필요한 국내 후보다. `destination_filter`는 한국 배송 조건으로 검색된 후보이며, `freight_quote`는 운임 조회에서 배송편을 확인한 후보다.
- `price`와 `shipping`에는 금액과 통화를 각각 담는다. 배송비가 없으면 `null`, 무료 배송을 명시한 응답은 금액 `"0"`이다. 상품가에 배송비나 세금이 모두 포함됐다고 가정하지 않는다.
- `market`은 검색 시장이다. 출고국을 확인할 수 없는 응답에서는 `dispatch_country`를 `null`로 둔다. 특정 옵션이나 수량의 최종 결제액은 판매처에서 확인한다.

## 법정통화 환율과 스테이블코인 시세

`python3 api_data/market_rates.py`를 실행하면 통화 한 단위와 토큰 한 개의 원화 참고 가격을 JSON으로 출력한다. 서버 코드에서는 [market_rates.py](./market_rates.py)의 `get_market_rates()`를 호출한다.

| 법정통화 | 스테이블코인 | 기준 |
| --- | --- | --- |
| CNY |  | 중국 본토 위안화 환율 |
| CNH |  | 역외 위안화 환율 |
| JPY | JPYC | 엔화 환율과 현행 JPYC 시세. [발행사 계약 주소](https://github.com/jpycoin)와 일치하는 [CoinGecko ID](https://www.coingecko.com/en/coins/jpycoin)를 사용한다. |
| EUR | EURC | 유로 환율과 EURC 시세 |
| USD | USDC, USDT | 달러 환율과 두 토큰 각각의 시세 |

[Frankfurter](https://frankfurter.dev/javascript/)에서 원화 기준 일별 환율을 한 번에 받아 역수로 환산한다. `fiat`에는 통화별 기준일을 기록한다. [CoinGecko](https://docs.coingecko.com/reference/simple-price)에서 토큰별 원화 시세와 갱신 시각을 받아 `stablecoins`에 기록한다. Demo 키가 있으면 `COINGECKO_DEMO_API_KEY` 환경변수로 전달할 수 있다.

금액은 십진 문자열이다. 공급원이 가격을 제공하지 않으면 `krw_per_unit`은 `null`이다. 공급원 요청이 실패하면 해당 그룹을 `null`로 두고 `errors`에 이유를 담는다. 환전 수수료, 네트워크 수수료, 판매처의 토큰 결제 지원 여부는 별도로 확인한다.

## 스테이블코인 결제 판매처

[stablecoin_shops.py](./stablecoin_shops.py)는 공개 API에서 상품 또는 권종별 견적을 조회한다. 아래 명령은 API 키 없이 실행할 수 있다.

| 판매처 | 토큰 | API와 한국 구매 범위 |
| --- | --- | --- |
| SEASE | USDC, USDT | 한국 마켓의 실물 상품을 검색한다. 판매처가 한국 배송과 LUNU 결제를 명시한다. 상품 URL에서 옵션과 주소를 선택한 뒤 최종 운임, 토큰, 네트워크를 확인한다. [한국 결제 및 배송 안내](https://sease.live/ko-kr/pages/faq), [Shopify 검색 API](https://shopify.dev/docs/api/ajax/reference/predictive-search) |
| JPYC EC | JPYC | 상품 피드에서 실판매 상품과 JPYC 가격 범위를 가져온다. 한국 직배송은 미확인 상태다. 배송 필요 여부가 거짓인 경우에도 수령 방법을 상품 페이지에서 확인한다. [상품 및 결제 API 명세](https://ec.jpyc-service.com/api/v1/openapi.yaml), [배송 및 지원 체인 안내](https://ec.jpyc-service.com/faq) |
| Cryptorefills | EURC, USDC, USDT | 공개 카탈로그에서 한국용 이메일 상품권을 조회한다. 권종별 토큰 금액과 결제 경로는 API 응답값을 사용한다. EURC의 공급사 코드는 `EUROC`다. 토큰을 받는 판매처는 상품권 발행 브랜드와 별개인 Cryptorefills다. [카탈로그 API](https://www.cryptorefills.com/en/ai-agents), [한국 상품 페이지](https://www.cryptorefills.com/en/south_korea/gift_cards/emart) |

```sh
python3 api_data/stablecoin_shops.py sease jacket
python3 api_data/stablecoin_shops.py jpyc コーヒー
python3 api_data/stablecoin_shops.py cryptorefills Emart --token EURC
```

SEASE의 표시 가격은 한국 마켓의 법정통화 금액이다. 결제창에서 지갑을 선택하면 토큰 금액이 표시된다. JPYC EC 주문은 상품 페이지에서 지원 체인을 확인한 뒤 지갑 서명이 필요하다. Cryptorefills의 주문 확정 절차는 [결제 API 문서](https://www.cryptorefills.com/en/api-docs/developers)에서 확인할 수 있다.
