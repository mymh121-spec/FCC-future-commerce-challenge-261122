# 한국 배송 상품 조회 API

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
