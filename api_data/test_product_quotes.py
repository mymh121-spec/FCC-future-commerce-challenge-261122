import os
import tempfile
import unittest
from unittest.mock import patch

import buyer_server
import product_quotes as quotes


class QuoteTests(unittest.TestCase):
    def setUp(self):
        self.item = dict(title="신발", model_code="AB1234-001", market="KR", seller="나이키 코리아",
                         url="https://www.nike.com/kr/t/shoe/AB1234-001")
        product = dict(styleColor="AB1234-001", groupKey="group", productType="FOOTWEAR",
                       prices={"currency": "KRW", "currentPrice": 100}, sizes=[
                           {"merchSkuId": "s", "localizedLabel": "270", "status": "ACTIVE"}])
        self.page = {"marketPlace": "KR", "selectedProduct": product, "messages": {"KR": {
            "shippingMessage": "<p>• 배송 지역: 국내(일부 지역 제외)</p><p>• 배송비: 무료 배송</p>"}}}
        self.feed = {"marketplace": "KR", "groupKey": "group", "sizes": [
            {"productCode": "AB1234-001", "merchSkuId": "s", "availability": {"ship": "HIGH", "isAvailable": True}},
            {"productCode": "AB1234-002", "merchSkuId": "s", "availability": {"ship": "OOS", "isAvailable": False}}]}
        self.enterContext(patch.object(quotes, "nike_page_props", return_value=self.page))

    def lookup(self):
        with patch.object(quotes, "request_json", return_value=self.feed):
            return quotes.lookup(self.item)["s"]

    def test_exact_sku_and_conditional_delivery_quote(self):
        q = self.lookup()
        self.assertEqual((q["option"], q["stock"], q["shipping"], q["estimated_total"], q["price_status"]),
                         ("270 mm", "available", "0", "100", "estimated"))

    def test_missing_inventory_or_conditional_shipping_is_not_zero_or_sold_out(self):
        self.page["messages"]["KR"]["shippingMessage"] = "<p>배송비: 무료 배송 (회원 한정)</p>"
        self.feed["sizes"].pop(0)
        q = self.lookup()
        self.assertEqual((q["stock"], q["shipping"], q["estimated_total"]), ("unknown", None, None))
        with patch.object(quotes, "request_json", side_effect=TimeoutError):
            self.assertEqual(quotes.lookup(self.item)["s"]["stock"], "unknown")

    def test_persistent_quotes_are_scoped_and_save_is_idempotent(self):
        folder = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.dict(os.environ, FCC_BUYER_DB_DIR=folder))
        buyer_server.initialize()
        q = self.lookup()
        buyer_server.save_quote("first", "id", q)
        buyer_server.save_quote("first", "id", dict(q, price="999"))
        self.assertEqual(buyer_server.saved_quotes("first"), [("id", q)])
        self.assertEqual(buyer_server.saved_quotes("second"), [])
        self.feed["sizes"][0]["availability"] = {"ship": "OOS", "isAvailable": False}
        with self.assertRaises(ValueError):
            buyer_server.save_quote("second", "id", self.lookup())

    def test_storefront_uses_selected_variant_price_and_retains_currency(self):
        item = dict(title="item", url="https://www.boody.com.au/products/item", seller="Boody", market="AU",
                    product_id="gid://shopify/Product/1", storefront_host="www.boody.com.au")
        def page(first):
            sku = "S" if first else "M"
            return {"extensions": {"context": {"country": "KR"}}, "data": {"product": {
                "id": item["product_id"], "variants": {"nodes": [{"id": sku, "title": sku, "availableForSale": first,
                "price": {"amount": "42.50" if first else "39.99", "currencyCode": "AUD"}}],
                "pageInfo": {"hasNextPage": first, "endCursor": "next" if first else None}}}}}
        with patch.object(quotes, "request_json", side_effect=[page(True), page(False)]):
            q = quotes.lookup(item)
        self.assertEqual(q["S"]["stock"], "for_sale")
        self.assertEqual((q["S"]["price"], q["M"]["stock"], q["S"]["currency"], q["S"]["estimated_total"]),
                         ("42.50", "unavailable", "AUD", None))

    def test_single_variant_refresh_checks_variant_and_parent_in_one_request(self):
        item = dict(title="pen", url="https://www.boody.com.au/products/pen", seller="Boody", market="AU",
                    product_id="product", storefront_host="www.boody.com.au")
        variant = dict(id="v", product={"id": "product"}, title="M", availableForSale=True,
                       currentlyNotInStock=True, price=dict(amount="9.95", currencyCode="AUD"))
        for node, expected in [(variant, {"v"}), (dict(variant, product={"id": "other"}), set()),
                               (dict(variant, id="other"), set()), (None, set())]:
            with self.subTest(node=node), patch.object(quotes, "request_json", return_value={
                "extensions": {"context": {"country": "KR"}}, "data": {"node": node}
            }) as request:
                refreshed = quotes.lookup(item, variant_id="v")
                self.assertEqual(set(refreshed), expected)
                request.assert_called_once()
                self.assertEqual(request.call_args.kwargs["json_body"]["variables"], {"id": "v"})
                if expected:
                    self.assertEqual(refreshed["v"]["stock"], "backorder")

    def test_malformed_stock_row_preserves_valid_sku(self):
        self.feed["sizes"].extend([None, {"productCode": "AB1234-001", "merchSkuId": "s", "availability": None}])
        self.assertEqual(self.lookup()["stock"], "available")
        with patch.object(quotes, "request_json", return_value=self.feed):
            self.assertEqual(quotes.lookup(self.item, variant_id="removed"), {})
