import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from sto_crm import runtime as _runtime
from sto_crm.database import init_db
from sto_crm.parts_api.mxgroup import MXGroupAdapter
from sto_crm.parts_api.rossko import RosskoAdapter
from sto_crm.parts_api.tmparts import TMPartsAdapter
from sto_crm.parts_service import (
    _get_cached_parts,
    place_supplier_order,
    search_supplier_parts,
)


class TestSupplierPartsIntegration(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test_parts.sqlite3"
        self.orig_runtime = _runtime.RUNTIME
        _runtime.RUNTIME = _runtime.Runtime(
            db_path=self.db_path,
            start_time=time.time(),
            csrf_token="test_csrf_token",
            access_token="test_access_token",
            bootstrap_token="test_bootstrap_token",
        )
        init_db(seed_demo=False)

    def tearDown(self) -> None:
        _runtime.RUNTIME = self.orig_runtime
        self.tmpdir.cleanup()

    @patch("urllib.request.urlopen")
    def test_rossko_adapter(self, mock_urlopen):
        # Configure env variables for API
        with patch.dict(os.environ, {"ROSSKO_KEY1": "key1", "ROSSKO_KEY2": "key2"}):
            import sto_crm.config
            sto_crm.config.ROSSKO_KEY1 = "key1"
            sto_crm.config.ROSSKO_KEY2 = "key2"

            mock_response = MagicMock()
            mock_response.read.return_value = b'{"success": true, "parts": [{"oem": "555", "brand": "CTR", "name": "Ball joint", "price": 1200.0, "stock": 5, "delivery_days": 2}]}'
            mock_urlopen.return_value.__enter__.return_value = mock_response

            adapter = RosskoAdapter()
            results = adapter.search_parts("555", "CTR")
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["oem"], "555")
            self.assertEqual(results[0]["brand"], "CTR")
            self.assertEqual(results[0]["price"], 1200.0)

            # Test order
            mock_response_order = MagicMock()
            mock_response_order.read.return_value = b'{"success": true, "order_id": "ROSSKO-12345"}'
            mock_urlopen.return_value.__enter__.return_value = mock_response_order

            order_id = adapter.order_part("555", "CTR", 2)
            self.assertEqual(order_id, "ROSSKO-12345")

    @patch("urllib.request.urlopen")
    def test_mxgroup_adapter(self, mock_urlopen):
        with patch.dict(os.environ, {"MX_GROUP_TOKEN": "token"}):
            import sto_crm.config
            sto_crm.config.MX_GROUP_TOKEN = "token"

            mock_response = MagicMock()
            mock_response.read.return_value = b'{"items": [{"oem": "555", "brand": "CTR", "name": "Ball joint MX", "price": 1300.0, "quantity": 10, "days": 1}]}'
            mock_urlopen.return_value.__enter__.return_value = mock_response

            adapter = MXGroupAdapter()
            results = adapter.search_parts("555", "CTR")
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["price"], 1300.0)
            self.assertEqual(results[0]["supplier"], "mx_group")

            # Test order
            mock_response_order = MagicMock()
            mock_response_order.read.return_value = b'{"order_id": "MX-999"}'
            mock_urlopen.return_value.__enter__.return_value = mock_response_order
            order_id = adapter.order_part("555", "CTR", 1)
            self.assertEqual(order_id, "MX-999")

    @patch("urllib.request.urlopen")
    def test_tmparts_adapter(self, mock_urlopen):
        with patch.dict(os.environ, {"TM_PARTS_KEY": "apikey"}):
            import sto_crm.config
            sto_crm.config.TM_PARTS_KEY = "apikey"

            mock_response = MagicMock()
            mock_response.read.return_value = b'[{"oem": "555", "brand": "CTR", "name": "Ball joint TM", "price": 1100.0, "stock": 3, "delivery_days": 3}]'
            mock_urlopen.return_value.__enter__.return_value = mock_response

            adapter = TMPartsAdapter()
            results = adapter.search_parts("555", "CTR")
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["price"], 1100.0)

            # Test order
            mock_response_order = MagicMock()
            mock_response_order.read.return_value = b'{"id": "TM-888"}'
            mock_urlopen.return_value.__enter__.return_value = mock_response_order
            order_id = adapter.order_part("555", "CTR", 1)
            self.assertEqual(order_id, "TM-888")

    @patch("sto_crm.parts_api.rossko.RosskoAdapter.search_parts")
    @patch("sto_crm.parts_api.mxgroup.MXGroupAdapter.search_parts")
    @patch("sto_crm.parts_api.tmparts.TMPartsAdapter.search_parts")
    def test_aggregator_and_parts_service(self, mock_search_tm, mock_search_mx, mock_search_rossko):
        # Prepare mock return values
        mock_search_rossko.return_value = [
            {"oem": "555", "brand": "CTR", "name": "Rossko CTR", "price": 1000.0, "stock": 2, "delivery_days": 1, "supplier": "rossko"}
        ]
        mock_search_mx.return_value = [
            {"oem": "555", "brand": "CTR", "name": "MX CTR", "price": 1050.0, "stock": 4, "delivery_days": 2, "supplier": "mx_group"}
        ]
        mock_search_tm.return_value = []

        # Perform search (this should hit APIs and fill cache)
        results = search_supplier_parts("555", "CTR")
        self.assertEqual(len(results), 2)

        # Verify db cache
        cached = _get_cached_parts("555", "CTR")
        self.assertEqual(len(cached), 2)

        # Second search should return cached results (mock is not called again)
        mock_search_rossko.reset_mock()
        mock_search_mx.reset_mock()

        results2 = search_supplier_parts("555", "CTR")
        self.assertEqual(len(results2), 2)
        mock_search_rossko.assert_not_called()
        mock_search_mx.assert_not_called()

        # Try ordering a part from cache
        with patch("sto_crm.parts_api.rossko.RosskoAdapter.order_part") as mock_order:
            mock_order.return_value = "ORDER-100"
            order_id = place_supplier_order("555", "CTR", "rossko", 1, 1000.0)
            self.assertEqual(order_id, "ORDER-100")
            mock_order.assert_called_once_with("555", "CTR", 1)

            # Check that quantities have been updated in cache
            cached_after = _get_cached_parts("555", "CTR")
            rossko_item = next(c for c in cached_after if c["supplier"] == "rossko")
            self.assertEqual(rossko_item["stock"], 1) # 2 - 1 = 1

    def test_empty_config_status(self):
        import sto_crm.config
        sto_crm.config.ROSSKO_KEY1 = ""
        sto_crm.config.ROSSKO_KEY2 = ""
        sto_crm.config.MX_GROUP_TOKEN = ""
        sto_crm.config.TM_PARTS_KEY = ""

        # Test logging output does not raise
        from sto_crm.config import log_configuration_status
        log_configuration_status()
