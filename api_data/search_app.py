"""상품명을 직접 입력하거나 한국어 음성으로 입력하는 로컬 검색 화면."""

import json
import sys
import wave
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlsplit

import streamlit as st

from direct_shipping import EBAY_COUNTRIES, search


MODEL_PATH = Path(sys.prefix) / "share/fcc-search/vosk-model-small-ko-0.22"
MARKETS = {
    "KR": "한국", "US": "미국", "JP": "일본", "CN": "중국", "DE": "독일",
    "FR": "프랑스", "GB": "영국", "IT": "이탈리아", "ES": "스페인",
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


def show_results(result):
    for field in ("errors", "shipping_errors"):
        for source, error in result.get(field, {}).items():
            st.warning(f"{source} 조회 실패: {error}")
    pending = result.get("dispatch_unverified_items", [])
    if pending:
        st.caption(f"중국 출고 여부를 확인하지 못한 상품 {len(pending)}개는 결과에서 제외했습니다.")
    items = result["items"]
    if not items:
        st.info("표시할 상품이 없습니다.")
    for item in items:
        st.text(item["title"])
        price = item.get("price")
        amount = f"{price['amount']} {price['currency']}" if price else "가격 미확인"
        if price and item.get("price_basis") == "min_variant_price":
            amount += "부터"
        shipping = item.get("shipping")
        freight = f"배송비 {shipping['amount']} {shipping['currency']}" if shipping else "배송비 미확인"
        st.caption(" / ".join(filter(None, [item.get("seller"), amount, freight])))
        if urlsplit(item["url"] or "").scheme in ("http", "https"):
            st.link_button("상품 보기", item["url"])
    links = result.get("browser_search", {})
    for key, label in (("naver", "네이버에서 검색"), ("danawa", "다나와에서 검색")):
        if links.get(key):
            st.link_button(label, links[key])


def main():
    st.set_page_config(page_title="상품 검색")
    st.title("상품 검색")
    market = st.selectbox("구매 국가", list(MARKETS), format_func=MARKETS.get)
    if MODEL_PATH.is_dir():
        st.audio_input("한국어로 말하기", sample_rate=16000, key="recording", on_change=use_recording,
                       help="녹음을 마치면 인식한 내용이 아래 검색어에 들어갑니다.")
        if st.session_state.get("voice_notice"):
            st.info(st.session_state.voice_notice)
    else:
        st.caption("한국어 음성 입력은 로컬 음성 모델을 설치하면 사용할 수 있습니다.")
    with st.form("product_search"):
        keyword = st.text_input("상품명 또는 모델명", key="keyword").strip()
        postal_code = st.text_input("한국 수령지 우편번호", max_chars=5) if market in EBAY_COUNTRIES else None
        submitted = st.form_submit_button("검색", type="primary")
    if submitted:
        st.session_state.pop("last_search", None)
        if not keyword:
            st.warning("검색할 상품명이나 모델명을 입력하세요.")
            return
        try:
            with st.spinner("상품을 찾고 있습니다."):
                result = search(market, keyword, postal_code=postal_code)
        except (URLError, TimeoutError, ValueError, RuntimeError, KeyError) as exc:
            st.error(f"검색을 완료하지 못했습니다. {exc}")
            return
        st.session_state.last_search = (market, keyword, result)
    if previous := st.session_state.get("last_search"):
        country, term, result = previous
        st.subheader(f"{MARKETS[country]} 검색 결과")
        st.text(term)
        show_results(result)


if __name__ == "__main__":
    main()
