import unittest

from sto_crm.validation import item_is_billable, require_non_negative_float


class TestCoverageEdge(unittest.TestCase):
    def test_item_is_billable_edge(self):
        self.assertTrue(item_is_billable({}))
        self.assertTrue(item_is_billable({"approval_status": "approved"}))
        self.assertFalse(item_is_billable({"approval_status": "declined"}))

    def test_require_non_negative_float_edge(self):
        with self.assertRaises(ValueError):
            require_non_negative_float(-1, "test")
