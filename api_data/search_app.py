"""상품명을 직접 입력하거나 한국어 음성으로 입력하는 로컬 검색 화면."""

import json
import sqlite3
import sys
import wave
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo
from urllib.error import URLError
from urllib.parse import urlsplit

import streamlit as st

import buyer_server
import product_quotes
from direct_shipping import EBAY_COUNTRIES, SEARCH_ERRORS, search


MODEL_PATH = Path(sys.prefix) / "share/fcc-search/vosk-model-small-ko-0.22"
MARKETS = {
    "KR": "한국", "ALL": "전체 국가", "US": "미국", "JP": "일본", "CN": "중국", "DE": "독일",
    "FR": "프랑스", "GB": "영국", "IT": "이탈리아", "ES": "스페인",
    "AU": "호주", "TW": "대만",
}


@st.cache_resource
def speech_model():
    from vosk import Model
    try:
        return Model(str(MODEL_PATH))
    except Exception as exc:
        # The Vosk binding raises a base Exception for an invalid model.
        raise RuntimeError("한국어 음성 모델을 열 수 없습니다.") from exc


def transcribe(recording):
    from vosk import KaldiRecognizer

    recording.seek(0)
    parts = []
    with wave.open(recording, "rb") as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or wav.getcomptype() != "NONE":
            raise ValueError("녹음 형식을 읽을 수 없습니다.")
        recognizer = KaldiRecognizer(speech_model(), wav.getframerate())
        while chunk := wav.readframes(4000):
            if recognizer.AcceptWaveform(chunk):
                parts.append(json.loads(recognizer.Result())["text"])
        parts.append(json.loads(recognizer.FinalResult())["text"])
    return " ".join(part.strip() for part in parts if part.strip())


def use_recording():
    recording = st.session_state.recording
    st.session_state.voice_notice = ""
    if recording is None:
        return
    try:
        keyword = transcribe(recording)
    except (ImportError, OSError, EOFError, ValueError, wave.Error, RuntimeError):
        st.session_state.voice_notice = "음성을 읽지 못했습니다. 다시 녹음하거나 검색어를 입력하세요."
        return
    if keyword:
        st.session_state.keyword = keyword
    else:
        st.session_state.voice_notice = "말소리를 인식하지 못했습니다. 다시 녹음하거나 검색어를 입력하세요."


def account_panel(owner):
    with st.sidebar:
        prefs, ratings = buyer_server.memory(owner)
        with st.expander("내 구매 선호"):
            names = {"신발 사이즈 (mm)": "shoe_size_mm", "표시 선호 통화": "currency", "배송 우선순위": "priority"}
            label = st.selectbox("저장할 항목", list(names))
            field = names[label]
            current = prefs.get(field)
            st.caption(f"저장된 값  {current or '없음'}")
            if field == "shoe_size_mm":
                value = st.number_input("사이즈 (mm)", 100, 400, int(current) if current else None)
            else:
                options = buyer_server.CURRENCIES if field == "currency" else buyer_server.PRIORITIES
                value = st.selectbox(label, options, index=options.index(current) if current in options else None)
            if st.button("다음에도 사용", disabled=value is None):
                buyer_server.set_preference(owner, field, value)
                st.rerun()
            if st.button("저장한 선호 삭제", disabled=current is None):
                buyer_server.set_preference(owner, field, None)
                st.rerun()
    return ratings


def feedback_form(owner, items, ratings, group):
    if owner is None or not items:
        return
    products = {buyer_server.product_key(item): item for item in items}
    with st.expander("검색 결과 피드백"):
        key = st.selectbox("평가할 상품", list(products), key=f"product_{group}",
                           format_func=lambda k: f"{products[k].get('seller') or ''} {products[k]['title']}")
        current = ratings.get(key)
        reason = st.selectbox("피드백", buyer_server.FEEDBACK, key=f"rating_{group}_{key}",
                              index=buyer_server.FEEDBACK.index(current) if current else None)
        if st.button("피드백 저장", key=f"save_{group}", disabled=reason is None):
            buyer_server.set_feedback(owner, key, reason)
            st.rerun()
        if st.button("피드백 삭제", key=f"delete_{group}", disabled=current is None):
            buyer_server.set_feedback(owner, key, None)
            st.rerun()


def show_product(item):
    st.text(item["title"])
    price = item.get("price")
    amount = f"상품 표시가 {price['amount']} {price['currency']}" if price else "가격 미확인"
    if price and item.get("price_basis") == "min_variant_price":
        amount += "부터"
    shipping = item.get("shipping")
    freight = f"배송비 {shipping['amount']} {shipping['currency']}" if shipping else "배송비 미확인"
    details = [MARKETS.get(item.get("market")), item.get("seller"), item.get("model_code"),
               item.get("color"), amount, freight]
    if item.get("market") in ("AU", "TW"):
        details.append("법정통화 결제")
    if item.get("kr_direct_shipping") == "unverified":
        details.append("한국 직배송 미확인")
    st.caption(" / ".join(filter(None, details)))
    if urlsplit(item["url"] or "").scheme in ("http", "https"):
        st.link_button("상품 보기", item["url"])


def display_quote(q):
    def money(value):
        return f"{Decimal(value):,f} {q['currency']}" if value is not None else "미확인"

    st.text(f"{q['seller']} / {q.get('model_code') or q['title']} / {q['option']} / {q['quantity']}개")
    if q.get("destination_label"):
        st.text(f"테스트 수령지 {q['destination_label']}")
    stock = product_quotes.STOCK_LABEL[q["stock"]]
    st.text(f"{stock} ({q['stock_level']})" if q["stock_level"] else stock)
    st.text(f"상품 표시가 {money(q['price'])}")
    if q["shipping"] is None:
        st.text("배송비 미확인")
    elif q.get("shipping_status") == "address_rate":
        st.text(f"서울역 직배송비 {money(q['shipping'])} ({q['shipping_basis']}, 판매처 견적)")
    else:
        st.text(f"예상 배송비 {money(q['shipping'])} ({q['shipping_basis']})")
    st.text(f"예상 합계 {money(q['estimated_total'])}" if q["estimated_total"] is not None
            else "예상 합계 산출 전")
    checked = datetime.fromisoformat(q["checked_at"]).astimezone(ZoneInfo("Asia/Seoul"))
    st.caption(f"판매처 조회 {checked:%Y-%m-%d %H:%M:%S} KST / 결제 시 금액과 재고가 달라질 수 있습니다.")


def quote_panel(items, owner, group):
    products = {buyer_server.product_key(item): item for item in items if product_quotes.supports(item)}
    if not products:
        return
    with st.expander("사이즈 선택 및 견적"):
        product = st.selectbox("견적 상품", list(products), key=f"quote_product_{group}",
                               format_func=lambda k: f"{products[k]['seller']} / {products[k]['title']} {products[k].get('model_code') or ''}")
        state_key = f"quote_preview_{group}"
        saved_key = f"quote_saved_{group}"
        state = st.session_state.get(state_key)
        if st.button("옵션별 재고와 배송비 조회", key=f"lookup_{group}"):
            st.session_state.pop(state_key, None)
            try:
                options = product_quotes.lookup(products[product])
            except SEARCH_ERRORS as exc:
                st.warning(f"판매처 옵션을 조회할 수 없습니다. {exc}")
                return
            state = st.session_state[state_key] = (product, options, uuid4().hex)
            st.session_state[saved_key] = set()
        if not state or state[0] != product:
            return
        _, options, revision = state
        sku = st.selectbox("사이즈 또는 옵션", list(options), key=f"variant_{group}_{product}",
                           format_func=lambda k: options[k]["option"])
        quote = options[sku] = product_quotes.station_delivery(products[product], options[sku])
        display_quote(quote)
        if not owner:
            st.caption("구매자별 저장은 개인용 실행 환경에서 사용할 수 있습니다.")
            return
        quote_id = f"{revision}:{sku}"
        if quote_id in st.session_state.get(saved_key, ()):
            st.caption("이 옵션의 견적을 저장했습니다.")
            return
        if st.button("내 견적 저장", key=f"quote_save_{group}", disabled=quote["stock"] in product_quotes.UNAVAILABLE):
            try:
                fresh = product_quotes.lookup(products[product], variant_id=sku)
            except SEARCH_ERRORS as exc:
                st.warning(f"저장 전 판매처 재조회에 실패했습니다. 다시 조회하세요. {exc}")
                return
            latest = fresh.get(sku)
            if latest is None:
                del st.session_state[state_key]
                st.session_state.quote_notice = "판매처에서 선택한 옵션을 찾을 수 없습니다. 옵션 목록을 다시 조회하세요."
                st.rerun()
            latest = product_quotes.station_delivery(products[product], latest)
            if any(quote[k] != latest[k] for k in quote if k != "checked_at"):
                options[sku] = latest
                st.session_state.quote_notice = "판매처 정보가 바뀌었습니다. 새 견적을 확인한 뒤 저장하세요."
                st.rerun()
            buyer_server.save_quote(owner, quote_id, latest)
            options[sku] = latest
            st.session_state.setdefault(saved_key, set()).add(quote_id)
            st.session_state.quote_notice = "선택한 옵션의 견적을 저장했습니다."
            st.rerun()


def quote_history(owner):
    with st.sidebar.expander("내 저장 견적"):
        history = dict(buyer_server.saved_quotes(owner))
        if not history:
            st.caption("저장된 견적이 없습니다.")
            return

        def history_label(key):
            q = history[key]
            when = datetime.fromisoformat(q["checked_at"]).astimezone(ZoneInfo("Asia/Seoul"))
            return f"{q.get('model_code') or q['title']} / {q['option']} / {when:%m-%d %H:%M:%S}"
        selected = st.selectbox("저장된 견적 (최근 50건)", list(history), format_func=history_label)
        display_quote(history[selected])


def show_results(result, owner, ratings):
    if result.get("mvp_payment_scope") == "fiat_only":
        st.caption("이 판매처는 법정통화 결제만 안내합니다. 스테이블코인 직접 결제는 미확인입니다.")
    if result.get("translated_queries"):
        with st.expander("판매처별 재검색어"):
            for seller, query in result["translated_queries"].items():
                st.text(f"{seller} ({query['language']})  {query['keyword']}")
    for field in ("errors", "shipping_errors"):
        for source, error in result.get(field, {}).items():
            st.warning(f"{source} 조회 실패: {error}")
    items = result["items"]
    pending = result.get("dispatch_unverified_items", [])
    if not items and not pending:
        st.info("표시할 상품이 없습니다.")
    if items and result["market"] == "CN":
        st.subheader("중국 본토 출고 확인")

    def relevance(item):
        reason = ratings.get(buyer_server.product_key(item)) if ratings else None
        return {"찾던 상품": -1, "다른 상품": 1}.get(reason, 0)

    for item in sorted(items, key=relevance):
        show_product(item)
    if pending:
        st.subheader("중국 본토 출고 미확인")
        for item in sorted(pending, key=relevance):
            show_product(item)
    quote_panel(items + pending, owner, result["market"])
    feedback_form(owner, items + pending, ratings, result["market"])
    links = result.get("browser_search", {})
    for key, label in (("naver", "네이버에서 검색"), ("danawa", "다나와에서 검색")):
        if links.get(key):
            st.link_button(label, links[key])


def main():
    st.set_page_config(page_title="상품 검색")
    st.title("상품 검색")
    # The owner comes from server configuration, never from a browser parameter.
    owner = None
    ratings = {}
    if st.get_option("server.address") in ("127.0.0.1", "::1", "localhost"):
        owner = "local-owner"
        try:
            buyer_server.initialize()
            ratings = account_panel(owner)
            quote_history(owner)
        except (OSError, sqlite3.Error):
            owner = None
            st.sidebar.warning("개인 메모리를 열 수 없습니다. 검색은 계속 사용할 수 있습니다.")
    if notice := st.session_state.pop("quote_notice", None):
        st.info(notice)
    market = st.selectbox("구매 국가", list(MARKETS), format_func=MARKETS.get)
    if MODEL_PATH.is_dir():
        st.audio_input("한국어로 말하기", sample_rate=16000, key="recording", on_change=use_recording,
                       help="녹음을 마치면 인식한 내용이 아래 검색어에 들어갑니다.")
        if st.session_state.get("voice_notice"):
            st.info(st.session_state.voice_notice)
    else:
        st.caption("한국어 음성 입력은 로컬 음성 모델을 설치하면 사용할 수 있습니다.")
    use_ebay = market in EBAY_COUNTRIES and st.checkbox("eBay에서 검색")
    if market != "KR":
        st.caption("한국어 검색어와 일치하는 상품명이 없는 해외 판매처는 검색어를 MyMemory로 번역해 다시 조회합니다.")
    st.caption(f"기본 테스트 수령지  {product_quotes.SEOUL_STATION}")
    with st.form("product_search"):
        keyword = st.text_input("상품명 또는 모델명", key="keyword").strip()
        postal_code = st.text_input("한국 수령지 우편번호", value=product_quotes.SEOUL_STATION_ZIP, max_chars=5) if use_ebay else None
        submitted = st.form_submit_button("검색", type="primary")
    if submitted:
        for key in list(st.session_state):
            if key.startswith(("quote_preview_", "quote_saved_")):
                del st.session_state[key]
        st.session_state.pop("last_search", None)
        st.session_state.pop("overseas_search", None)
        if not keyword:
            st.warning("검색할 상품명이나 모델명을 입력하세요.")
            return
        try:
            with st.spinner("상품을 찾고 있습니다."):
                result = search(market, keyword, limit=20 if market == "ALL" else 5, postal_code=postal_code)
        except (URLError, TimeoutError, ValueError, RuntimeError, KeyError) as exc:
            st.error(f"검색을 완료하지 못했습니다. {exc}")
            return
        st.session_state.last_search = (market, keyword, result)
    if previous := st.session_state.get("last_search"):
        country, term, result = previous
        st.subheader(f"{MARKETS[country]} 검색 결과")
        st.text(term)
        show_results(result, owner, ratings)
        if country == "KR":
            if st.button("같은 검색어로 해외 판매처 조회"):
                with st.spinner("해외 판매처에서 상품을 찾고 있습니다."):
                    st.session_state.overseas_search = search("OVERSEAS", term, limit=20)
            if overseas := st.session_state.get("overseas_search"):
                st.subheader("해외 검색 결과")
                show_results(overseas, owner, ratings)


if __name__ == "__main__":
    try:
        main()
    except sqlite3.Error:
        st.error("고객 저장소를 사용할 수 없습니다. 연결 상태를 확인한 뒤 다시 시도하세요.")
