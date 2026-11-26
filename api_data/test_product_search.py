import io
import json
import unittest
from collections import Counter
from threading import Barrier
from unittest.mock import patch

import direct_shipping as search_api


class ProductSearchTests(unittest.TestCase):
    def test_parallel_fallback_is_shared_and_preserves_shipping_groups(self):
        shops = {"JP": {"a": "A", "b": "B"}, "CN": {"c": "C"}, "TW": {"d": "D"}}
        started = Barrier(4, timeout=4)
        calls = []

        def page(host, seller, keyword, limit, market, language="KO"):
            calls.append((seller, keyword))
            if language == "KO":
                started.wait()
                if seller == "D":
                    raise RuntimeError("unavailable")
                title = "검은 만년필" if seller == "A" else "Unrelated result"
            else:
                title = "Blue fountain pen"
            return [{"title": title, "market": market, "seller": seller, "dispatch_country": None}], {"EN"}

        with patch.object(search_api, "STOREFRONTS", shops), patch.object(search_api, "storefront_page", page), \
                patch.object(search_api, "translate_keyword", return_value="fountain pen") as translate:
            result = search_api.search("ALL", "만년필", 3)
        translate.assert_called_once_with("만년필", "EN")
        self.assertEqual(Counter(seller for seller, _ in calls), {"A": 1, "B": 2, "C": 2, "D": 1})
        self.assertEqual([item["seller"] for item in result["items"]], ["A", "B"])
        self.assertEqual([item["seller"] for item in result["dispatch_unverified_items"]], ["C"])
        self.assertEqual(set(result["errors"]), {"D"})

    def test_translation_failure_preserves_other_results(self):
        def page(host, seller, keyword, limit, market, language="KO"):
            if seller == "A":
                return [{"market": market, "title": "빨간 펜"}], {"KO"}
            return [], {"JA", "EN"}

        with patch.object(search_api, "STOREFRONTS", {"JP": {"a": "A", "b": "B"}}), \
                patch.object(search_api, "storefront_page", page), \
                patch.object(search_api, "translate_keyword", side_effect=ValueError("quota")) as translate:
            result = search_api.search("JP", "펜")
        translate.assert_called_once_with("펜", "JA")
        self.assertEqual(result["items"][0]["title"], "빨간 펜")
        self.assertIn("quota", result["errors"]["B"])

    def test_model_query_preserves_original_identifier(self):
        response = {"responseStatus": 200, "responseData": {"translatedText": "headphones"}}
        with patch.object(search_api, "request_json", return_value=response):
            self.assertEqual(search_api.translate_keyword("WH-1000XM5 헤드폰", "EN"), "headphones WH-1000XM5")

    def test_korean_model_search_uses_exact_style_and_source_price(self):
        def product(code):
            return {"productCode": code, "productType": "FOOTWEAR",
                    "copy": {"title": "테스트 신발", "subTitle": "남성 신발"},
                    "prices": {"currentPrice": 100, "currency": "KRW"},
                    "pdpUrl": {"url": "https://www.nike.com/kr/t/test/" + code}}

        variants = [product("AA1234-002"), product("AA1234-001")]
        wall = {"productGroupings": [{"products": variants}]}
        data = {"props": {"pageProps": {"initialState": {"Wall": wall}}}}
        page = '<script id="__NEXT_DATA__" type="application/json">' + json.dumps(data) + "</script>"
        with patch.object(search_api, "urlopen", return_value=io.BytesIO(page.encode())), \
                patch.object(search_api, "storefront_page", return_value=([], {"KO"})):
            result = search_api.search("KR", "aa1234-001")
        self.assertEqual(result["errors"], {})
        self.assertEqual([item["model_code"] for item in result["items"]], ["AA1234-001"])
        self.assertEqual(result["items"][0]["price"], {"amount": "100", "currency": "KRW"})

    def test_domestic_english_search_hides_unrelated_product_on_nike_failure(self):
        rows = [{"title": "에스프레소 커피 부품"}]
        with patch.object(search_api, "storefront_page", return_value=(rows, {"KO"})), \
                patch.object(search_api, "nike_korea", side_effect=TimeoutError("timeout")) as nike:
            result = search_api.search("KR", "Nike Air Force 1")
        nike.assert_called_once_with("나이키 에어 포스 1", 5)
        self.assertEqual(result["items"], [])
        self.assertIn("나이키 코리아", result["errors"])

    def test_expanding_abroad_only_calls_overseas_stores(self):
        shops = {"KR": {"local": "국내"}, "CN": {"abroad": "해외"}}
        rows = [{"market": "CN", "title": "신발", "dispatch_country": None}]
        with patch.object(search_api, "STOREFRONTS", shops), \
                patch.object(search_api, "storefront_page", return_value=(rows, {"KO"})) as page, \
                patch.object(search_api, "nike_korea") as nike:
            result = search_api.search("OVERSEAS", "신발")
        page.assert_called_once_with("abroad", "해외", "신발", 5, "CN")
        nike.assert_not_called()
        self.assertEqual(result["dispatch_unverified_items"], rows)

    def test_model_only_query_skips_translation(self):
        with patch.object(search_api, "storefront_page", return_value=([], {"EN"})), \
                patch.object(search_api, "translate_keyword") as translate:
            result = search_api.search("JP", "WH-1000XM5")
        translate.assert_not_called()
        self.assertEqual(result["translated_queries"], {})


if __name__ == "__main__":
    unittest.main()
