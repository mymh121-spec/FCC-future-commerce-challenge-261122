import os
import tempfile
import unittest
from unittest.mock import patch

import buyer_server as server


class BuyerMemoryTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        env = patch.dict(os.environ, FCC_BUYER_DB_DIR=folder.name)
        env.start()
        self.addCleanup(env.stop)
        server.initialize()
        self.product = server.product_key({"market": "KR", "seller": "test", "url": "https://example.test/item"})

    def test_update_and_delete_only_the_current_owners_records(self):
        for owner in ("first", "second"):
            server.set_preference(owner, "shoe_size_mm", 270)
            server.set_feedback(owner, self.product, "다른 상품")
        server.set_preference("first", "shoe_size_mm", 250)
        server.set_feedback("first", self.product, "찾던 상품")
        self.assertEqual(server.memory("first"), ({"shoe_size_mm": "250"}, {self.product: "찾던 상품"}))
        server.set_preference("first", "shoe_size_mm", None)
        server.set_feedback("first", self.product, None)
        self.assertEqual(server.memory("first"), ({}, {}))
        self.assertEqual(server.memory("second"), ({"shoe_size_mm": "270"}, {self.product: "다른 상품"}))

    def test_server_rejects_local_fields_and_unstructured_feedback(self):
        with self.assertRaises(ValueError):
            server.set_preference("first", "address", "example")
        with self.assertRaises(ValueError):
            server.set_feedback("first", self.product, "unstructured text")
        self.assertEqual(server.memory("first"), ({}, {}))
