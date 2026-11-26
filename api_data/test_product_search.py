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

    def test_model_only_query_skips_translation(self):
        with patch.object(search_api, "storefront_page", return_value=([], {"EN"})), \
                patch.object(search_api, "translate_keyword") as translate:
            result = search_api.search("JP", "WH-1000XM5")
        translate.assert_not_called()
        self.assertEqual(result["translated_queries"], {})


if __name__ == "__main__":
    unittest.main()
