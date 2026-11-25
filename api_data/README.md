# 한국 배송 상품 및 원화 시세 조회 API

[direct_shipping.py](./direct_shipping.py)는 Python 표준 라이브러리로 시장 한 곳의 상품을 검색한다. 해외 배송 목적지는 한국으로 고정한다.

| 시장 코드 | 데이터 출처 | 한국 배송 범위 |
| --- | --- | --- |
| KR | [Yo! Korea](https://yokorea.store/ko), [Pesado Korea](https://pesado585.co.kr/collections/all) | 한국 시장에 판매 중인 상품의 옵션 최저 표시가와 구매 링크를 조회한다. 배송비와 개별 주소의 배송 가능 여부는 판매처에서 확인한다. |
| US | [eBay Browse](https://developer.ebay.com/api-docs/buy/static/ref-buy-browse-filters.html) | 미국 소재 상품을 한국 수령지 우편번호로 필터링해 직배송 후보를 조회한다. |
| DE, FR, GB, IT, ES | [eBay 유럽 마켓](https://developer.ebay.com/api-docs/buy/static/ref-marketplace-supported.html) | 독일, 프랑스, 영국, 이탈리아, 스페인을 각각 조회한다. 선택한 마켓 국가에 있는 상품에 미국과 같은 배송 조건을 적용한다. |
| JP | [라쿠텐 이치바 상품 검색](https://webservice.rakuten.co.jp/documentation/ichiba-item-search) | 해외 배송 플래그와 [한국 배송 지역 코드](https://webservice.rakuten.co.jp/documentation/areacode/shipoverseasarea)를 함께 적용한다. 해외 배송비는 판매처에서 확인한다. |
| CN | [AliExpress 제휴 상품 검색](https://openservice.aliexpress.com/doc/api.htm#/api?cid=21407&path=aliexpress.affiliate.product.query&methodType=GET%2FPOST), [상품 운임 조회](https://openservice.aliexpress.com/doc/api.htm#/api?cid=21407&path=aliexpress.affiliate.product.shipping.get&methodType=GET%2FPOST) | 한국 수령 조건으로 검색한 뒤 상품 옵션별 배송 정보를 조회한다. 중국 출고가 확인된 상품은 `items`에, 출고국을 확인할 수 없는 검색 결과는 `dispatch_unverified_items`에 담는다. |

## 실행

Python 3.8 이상에서 저장소 루트를 기준으로 실행한다. 판매처 인증 정보는 환경변수에서 먼저 읽고, 값이 없으면 Linux 데스크톱 키링에서 같은 이름으로 찾는다.

| 시장 | 환경변수 |
| --- | --- |
| US 및 유럽 | `EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET`. [Browse 운영 접근 승인](https://developer.ebay.com/api-docs/buy/static/buy-requirements.html)이 필요하다. |
| JP | `RAKUTEN_APP_ID`, `RAKUTEN_ACCESS_KEY`. 앱에 허용한 웹사이트를 지정할 때는 `RAKUTEN_ORIGIN`에 해당 사이트의 origin을 넣는다. |
| CN | `ALIEXPRESS_APP_KEY`, `ALIEXPRESS_APP_SECRET`. TOP에서 제휴 상품 검색과 상품 운임 조회를 모두 호출할 수 있는 앱 키를 사용한다. |

```text
python3 api_data/direct_shipping.py 시장코드 "검색어" [--postal-code 한국우편번호] [--limit 조회건수]
```

eBay는 한국 수령지 우편번호 5자리가 필수다. 조회 건수는 기본 5개이며 중국은 옵션 ID, 세율과 원화 가격이 있는 후보마다 배송 정보를 한 번 더 조회한다. 옵션 정보가 부족하거나 배송 호출이 실패해도 출고 미확인 후보에 상품명과 링크를 남긴다. 상품별 배송 조회 오류는 `shipping_errors`에 기록한다. 중국 이외 국가에서 출고되는 상품은 제외한다.

### 국내 상품 검색

저장소 루트에서 다음 명령을 실행하면 두 판매처의 공개 카탈로그를 API 키 없이 조회한다. 생활용품과 의류는 Yo! Korea에서, 커피 도구는 Pesado Korea에서 찾을 수 있다. [Shopify 공개 검색 명세](https://shopify.dev/docs/api/storefront/latest/queries/search)

```sh
python3 api_data/direct_shipping.py KR "커피" --limit 5
```

`items`에는 판매처명과 원화 표시가, 상품 링크, 조회 시각이 담긴다. `price_basis=min_variant_price`는 상품 옵션 중 가장 낮은 표시가다. 판매처별 요청 실패는 `errors`에 기록한다. 두 곳에 상품이 없어도 `browser_search`의 다나와와 네이버 검색 링크로 다른 판매처를 찾아볼 수 있다. 링크를 만드는 데에는 외부 API 호출이나 요금이 발생하지 않는다.

기존 네이버 쇼핑 검색 API는 2026년 7월 31일에 종료됐다. [네이버 공식 공지](https://developers.naver.com/notice/article/32564)

네이버 API HUB에서 웹문서 검색을 신청했다면 `NAVER_HUB_CLIENT_ID`와 `NAVER_HUB_CLIENT_SECRET`을 환경변수 또는 로컬 키링에 등록하고 아래 명령을 사용한다. 응답의 `results`는 네이버가 반환한 순서대로 문서 제목과 주소, 요약문을 담는다. 네이버 웹검색 결과는 출처를 표시해 독립적으로 노출한다. [웹문서 검색 명세](https://api.ncloud-docs.com/docs/naver-api-hub-search-webkr)

```sh
python3 api_data/direct_shipping.py KR "커피잔" --naver-web
```

다른 판매처의 가격을 비교에 쓸 때는 구매자가 상품 옵션과 가격을 확인한 뒤 아래 형식으로 입력한다. 결과에는 `price_source=buyer_confirmed`와 입력 시각이 기록된다. 링크는 입력한 그대로 출력한다. 배송비를 모르면 `--shipping-krw`를 생략하고 무료배송을 확인했을 때만 0을 입력한다.

```text
python3 api_data/direct_shipping.py KR "선택한 상품명과 옵션" --selected-url "판매처 HTTPS 상품 주소" --confirmed-price-krw 원화가격 [--shipping-krw 배송비]
```

### 로컬 API 키 보관

Ubuntu 데스크톱에서는 잠금이 설정된 로그인 키링에 키를 보관한다. Secret Service와 이를 호출하는 `secret-tool` 명령이 필요하다. Ubuntu의 명령 패키지는 `libsecret-tools`다. 아래 명령을 터미널에서 한 줄씩 실행하고 입력 프롬프트가 뜨면 해당 값을 붙여 넣는다. 키 자체는 명령줄이나 프로젝트 파일에 쓰지 않는다.

```bash
secret-tool store --label="FCC 라쿠텐 App ID" service fcc-commerce name RAKUTEN_APP_ID
secret-tool store --label="FCC 라쿠텐 Access Key" service fcc-commerce name RAKUTEN_ACCESS_KEY
```

eBay와 AliExpress도 위 표의 키 이름으로 각각 등록한다. 키를 교체할 때는 같은 이름으로 다시 저장한다. 서버 배포 시에는 배포 환경의 비밀 저장소에서 같은 환경변수로 주입한다. [secret-tool 사용법](https://manpages.ubuntu.com/manpages/noble/man1/secret-tool.1.html)

## 응답 해석

- `kr_direct_shipping`은 상품별 한국 직배송 확인 상태다. 해외 실물 상품은 `unverified`(확인 필요)로 표시한다. 한국 배송 필터를 통과하거나 운임 견적이 있어도 선택한 옵션과 수량을 실제 한국 주소로 받을 수 있는지는 판매처에서 확인해야 한다. 국내 쇼핑 검색 결과와 배송이 필요 없는 상품에는 `not_applicable`을 사용한다.
- `seller_check_required`는 판매처에서 배송 가능 여부를 확인해야 하는 상품이다. `destination_filter`는 한국 배송 조건으로 검색된 후보이며, `freight_quote`는 운임 조회에서 배송편을 확인한 후보다.
- `price`와 `shipping`에는 금액과 통화를 각각 담는다. 배송비가 없으면 `null`, 무료 배송을 명시한 응답은 금액 `"0"`이다. 상품가에 배송비나 세금이 모두 포함됐다고 가정하지 않는다.
- `market`은 검색 시장이다. 출고국을 확인할 수 없는 응답에서는 `dispatch_country`를 `null`로 둔다. 특정 옵션이나 수량의 최종 결제액은 판매처에서 확인한다.

## 법정통화 환율과 스테이블코인 시세

`python3 api_data/market_rates.py`를 실행하면 통화 한 단위와 토큰 한 개의 원화 참고 가격을 JSON으로 출력한다. 서버 코드에서는 [market_rates.py](./market_rates.py)의 `get_market_rates()`를 호출한다.

| 법정통화 | 스테이블코인 | 기준 |
| --- | --- | --- |
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

kstore는 로그인이나 API 키 없이 재고가 있는 상품을 검색할 수 있다. 아래 명령은 상품명과 링크, 유로 표시 가격, 배대지 필요 여부를 반환한다. 배송비는 미확인 값인 `null`로 둔다. [공식 카탈로그 API 명세](https://kstore.ee/api/catalog/v1/openapi.json)

```sh
python3 api_data/stablecoin_shops.py kstore SSD --limit 3
```

일본직판은 로그인 없이 공개 상품 RSS를 읽는다. 아래 명령은 최근 등록 또는 수정된 상품 최대 10개의 제목과 링크를 반환한다. 제목을 검색하려면 판매처 이름 뒤에 일본어 검색어를 넣는다. 가격과 재고는 상품 페이지에서 확인한다. 전체 상품 조회용 MakeShop API에는 별도 인증이 필요하다. [일본직판 상품 RSS](https://www.666-666.jp/RSS/brand_rss.html), [MakeShop 개발자 안내](https://developers.makeshop.jp/api/)

```sh
python3 api_data/stablecoin_shops.py nihon-chokuhan --limit 10
```

## 글과 음성으로 상품 검색

프로젝트 최상위 폴더에서 아래 명령을 실행한다. 직접 입력과 한국어 받아쓰기는 같은 상품 검색 함수를 사용한다. 녹음한 내용은 로컬에서 글로 변환하며 검색어는 전송 전에 수정할 수 있다. 검색 버튼을 누르면 선택한 국가의 판매처에 검색어를 보낸다.

```sh
python3 -m venv .venv-search
.venv-search/bin/python -m pip install -r api_data/requirements-search.txt
```

음성을 사용하려면 [Vosk 한국어 소형 모델](https://alphacephei.com/vosk/models)을 한 번 설치한다. 글로만 검색할 때는 이 단계를 건너뛴다.

```sh
curl -fL https://alphacephei.com/vosk/models/vosk-model-small-ko-0.22.zip -o .venv-search/ko-model.zip
.venv-search/bin/python -m zipfile -e .venv-search/ko-model.zip .venv-search/share/fcc-search
```

```sh
.venv-search/bin/python -m streamlit run api_data/search_app.py --server.address=127.0.0.1 --server.headless=true --browser.gatherUsageStats=false
```

터미널에 표시되는 로컬 주소를 연다. 음성 입력을 쓸 때만 브라우저의 마이크 권한을 허용한다. 음성 인식에는 API 키가 필요 없으며 해외 상품 검색에는 위에 설명한 판매처별 키가 필요하다.
