import io
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sto_crm import runtime as _runtime
from sto_crm.database import init_db, write_db
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
    def test_rossko_error_handling_timeout(self, mock_urlopen):
        with patch.dict(os.environ, {"ROSSKO_KEY1": "key1", "ROSSKO_KEY2": "key2"}):
            import sto_crm.config
            sto_crm.config.ROSSKO_KEY1 = "key1"
            sto_crm.config.ROSSKO_KEY2 = "key2"

            mock_urlopen.side_effect = urllib.error.URLError("timeout")
            adapter = RosskoAdapter()
            self.assertEqual(adapter.search_parts("555", "CTR"), [])
            with self.assertRaises(RuntimeError):
                adapter.order_part("555", "CTR", 1)

            mock_urlopen.side_effect = socket.timeout("timed out")
            self.assertEqual(adapter.search_parts("555", "CTR"), [])
            with self.assertRaises(RuntimeError):
                adapter.order_part("555", "CTR", 1)

    @patch("urllib.request.urlopen")
    def test_rossko_error_handling_auth(self, mock_urlopen):
        with patch.dict(os.environ, {"ROSSKO_KEY1": "key1", "ROSSKO_KEY2": "key2"}):
            import sto_crm.config
            sto_crm.config.ROSSKO_KEY1 = "key1"
            sto_crm.config.ROSSKO_KEY2 = "key2"

            mock_urlopen.side_effect = urllib.error.HTTPError(
                "http://example.com/api", 401, "Unauthorized", None, io.BytesIO(b"")
            )
            adapter = RosskoAdapter()
            self.assertEqual(adapter.search_parts("555", "CTR"), [])
            with self.assertRaises(RuntimeError):
                adapter.order_part("555", "CTR", 1)

            mock_urlopen.side_effect = urllib.error.HTTPError(
                "http://example.com/api", 403, "Forbidden", None, io.BytesIO(b"")
            )
            self.assertEqual(adapter.search_parts("555", "CTR"), [])
            with self.assertRaises(RuntimeError):
                adapter.order_part("555", "CTR", 1)

    @patch("urllib.request.urlopen")
    def test_rossko_error_handling_server_error(self, mock_urlopen):
        with patch.dict(os.environ, {"ROSSKO_KEY1": "key1", "ROSSKO_KEY2": "key2"}):
            import sto_crm.config
            sto_crm.config.ROSSKO_KEY1 = "key1"
            sto_crm.config.ROSSKO_KEY2 = "key2"

            mock_urlopen.side_effect = urllib.error.HTTPError(
                "http://example.com/api", 500, "Internal Server Error", None, io.BytesIO(b"")
            )
            adapter = RosskoAdapter()
            self.assertEqual(adapter.search_parts("555", "CTR"), [])
            with self.assertRaises(RuntimeError):
                adapter.order_part("555", "CTR", 1)

            mock_urlopen.side_effect = urllib.error.HTTPError(
                "http://example.com/api", 502, "Bad Gateway", None, io.BytesIO(b"")
            )
            self.assertEqual(adapter.search_parts("555", "CTR"), [])
            with self.assertRaises(RuntimeError):
                adapter.order_part("555", "CTR", 1)

    @patch("urllib.request.urlopen")
    def test_rossko_error_handling_rate_limit(self, mock_urlopen):
        with patch.dict(os.environ, {"ROSSKO_KEY1": "key1", "ROSSKO_KEY2": "key2"}):
            import sto_crm.config
            sto_crm.config.ROSSKO_KEY1 = "key1"
            sto_crm.config.ROSSKO_KEY2 = "key2"

            mock_urlopen.side_effect = urllib.error.HTTPError(
                "http://example.com/api", 429, "Too Many Requests", None, io.BytesIO(b"")
            )
            adapter = RosskoAdapter()
            self.assertEqual(adapter.search_parts("555", "CTR"), [])
            with self.assertRaises(RuntimeError):
                adapter.order_part("555", "CTR", 1)

            mock_urlopen.side_effect = urllib.error.HTTPError(
                "http://example.com/api", 503, "Service Unavailable", None, io.BytesIO(b"")
            )
            self.assertEqual(adapter.search_parts("555", "CTR"), [])
            with self.assertRaises(RuntimeError):
                adapter.order_part("555", "CTR", 1)

    @patch("urllib.request.urlopen")
    def test_rossko_bad_json_parsing(self, mock_urlopen):
        with patch.dict(os.environ, {"ROSSKO_KEY1": "key1", "ROSSKO_KEY2": "key2"}):
            import sto_crm.config
            sto_crm.config.ROSSKO_KEY1 = "key1"
            sto_crm.config.ROSSKO_KEY2 = "key2"

            mock_response = MagicMock()
            mock_response.read.return_value = b"{invalid_json"
            mock_urlopen.return_value.__enter__.return_value = mock_response

            adapter = RosskoAdapter()
            self.assertEqual(adapter.search_parts("555", "CTR"), [])
            with self.assertRaises(RuntimeError):
                adapter.order_part("555", "CTR", 1)

    @patch("urllib.request.urlopen")
    def test_rossko_missing_fields_parsing(self, mock_urlopen):
        with patch.dict(os.environ, {"ROSSKO_KEY1": "key1", "ROSSKO_KEY2": "key2"}):
            import sto_crm.config
            sto_crm.config.ROSSKO_KEY1 = "key1"
            sto_crm.config.ROSSKO_KEY2 = "key2"

            mock_response = MagicMock()
            mock_response.read.return_value = b'{"success": true, "parts": [{"price": 1000.0}]}'
            mock_urlopen.return_value.__enter__.return_value = mock_response

            adapter = RosskoAdapter()
            results = adapter.search_parts("555", "CTR")
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["oem"], "555")
            self.assertEqual(results[0]["brand"], "CTR")
            self.assertEqual(results[0]["name"], "Запчасть Rossko")
            self.assertEqual(results[0]["price"], 1000.0)
            self.assertEqual(results[0]["stock"], 0)
            self.assertEqual(results[0]["delivery_days"], 1)

            mock_response_fail = MagicMock()
            mock_response_fail.read.return_value = b'{"success": false, "parts": []}'
            mock_urlopen.return_value.__enter__.return_value = mock_response_fail
            self.assertEqual(adapter.search_parts("555", "CTR"), [])

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
    def test_mxgroup_error_handling_timeout(self, mock_urlopen):
        with patch.dict(os.environ, {"MX_GROUP_TOKEN": "token"}):
            import sto_crm.config
            sto_crm.config.MX_GROUP_TOKEN = "token"

            mock_urlopen.side_effect = urllib.error.URLError("timeout")
            adapter = MXGroupAdapter()
            self.assertEqual(adapter.search_parts("555", "CTR"), [])
            with self.assertRaises(RuntimeError):
                adapter.order_part("555", "CTR", 1)

            mock_urlopen.side_effect = socket.timeout("timed out")
            self.assertEqual(adapter.search_parts("555", "CTR"), [])
            with self.assertRaises(RuntimeError):
                adapter.order_part("555", "CTR", 1)

    @patch("urllib.request.urlopen")
    def test_mxgroup_error_handling_auth(self, mock_urlopen):
        with patch.dict(os.environ, {"MX_GROUP_TOKEN": "token"}):
            import sto_crm.config
            sto_crm.config.MX_GROUP_TOKEN = "token"

            mock_urlopen.side_effect = urllib.error.HTTPError(
                "http://example.com/api", 401, "Unauthorized", None, io.BytesIO(b"")
            )
            adapter = MXGroupAdapter()
            self.assertEqual(adapter.search_parts("555", "CTR"), [])
            with self.assertRaises(RuntimeError):
                adapter.order_part("555", "CTR", 1)

    @patch("urllib.request.urlopen")
    def test_mxgroup_error_handling_server_error(self, mock_urlopen):
        with patch.dict(os.environ, {"MX_GROUP_TOKEN": "token"}):
            import sto_crm.config
            sto_crm.config.MX_GROUP_TOKEN = "token"

            mock_urlopen.side_effect = urllib.error.HTTPError(
                "http://example.com/api", 500, "Internal Server Error", None, io.BytesIO(b"")
            )
            adapter = MXGroupAdapter()
            self.assertEqual(adapter.search_parts("555", "CTR"), [])
            with self.assertRaises(RuntimeError):
                adapter.order_part("555", "CTR", 1)

    @patch("urllib.request.urlopen")
    def test_mxgroup_error_handling_rate_limit(self, mock_urlopen):
        with patch.dict(os.environ, {"MX_GROUP_TOKEN": "token"}):
            import sto_crm.config
            sto_crm.config.MX_GROUP_TOKEN = "token"

            mock_urlopen.side_effect = urllib.error.HTTPError(
                "http://example.com/api", 429, "Too Many Requests", None, io.BytesIO(b"")
            )
            adapter = MXGroupAdapter()
            self.assertEqual(adapter.search_parts("555", "CTR"), [])
            with self.assertRaises(RuntimeError):
                adapter.order_part("555", "CTR", 1)

    @patch("urllib.request.urlopen")
    def test_mxgroup_bad_json_parsing(self, mock_urlopen):
        with patch.dict(os.environ, {"MX_GROUP_TOKEN": "token"}):
            import sto_crm.config
            sto_crm.config.MX_GROUP_TOKEN = "token"

            mock_response = MagicMock()
            mock_response.read.return_value = b"{invalid_json"
            mock_urlopen.return_value.__enter__.return_value = mock_response

            adapter = MXGroupAdapter()
            self.assertEqual(adapter.search_parts("555", "CTR"), [])
            with self.assertRaises(RuntimeError):
                adapter.order_part("555", "CTR", 1)

    @patch("urllib.request.urlopen")
    def test_mxgroup_missing_fields_parsing(self, mock_urlopen):
        with patch.dict(os.environ, {"MX_GROUP_TOKEN": "token"}):
            import sto_crm.config
            sto_crm.config.MX_GROUP_TOKEN = "token"

            mock_response = MagicMock()
            mock_response.read.return_value = b'{"items": [{"price": 1000.0}]}'
            mock_urlopen.return_value.__enter__.return_value = mock_response

            adapter = MXGroupAdapter()
            results = adapter.search_parts("555", "CTR")
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["oem"], "555")
            self.assertEqual(results[0]["brand"], "CTR")
            self.assertEqual(results[0]["name"], "Запчасть MX Group")
            self.assertEqual(results[0]["price"], 1000.0)
            self.assertEqual(results[0]["stock"], 0)
            self.assertEqual(results[0]["delivery_days"], 1)

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

    @patch("urllib.request.urlopen")
    def test_tmparts_error_handling_timeout(self, mock_urlopen):
        with patch.dict(os.environ, {"TM_PARTS_KEY": "apikey"}):
            import sto_crm.config
            sto_crm.config.TM_PARTS_KEY = "apikey"

            mock_urlopen.side_effect = urllib.error.URLError("timeout")
            adapter = TMPartsAdapter()
            self.assertEqual(adapter.search_parts("555", "CTR"), [])
            with self.assertRaises(RuntimeError):
                adapter.order_part("555", "CTR", 1)

            mock_urlopen.side_effect = socket.timeout("timed out")
            self.assertEqual(adapter.search_parts("555", "CTR"), [])
            with self.assertRaises(RuntimeError):
                adapter.order_part("555", "CTR", 1)

    @patch("urllib.request.urlopen")
    def test_tmparts_error_handling_auth(self, mock_urlopen):
        with patch.dict(os.environ, {"TM_PARTS_KEY": "apikey"}):
            import sto_crm.config
            sto_crm.config.TM_PARTS_KEY = "apikey"

            mock_urlopen.side_effect = urllib.error.HTTPError(
                "http://example.com/api", 401, "Unauthorized", None, io.BytesIO(b"")
            )
            adapter = TMPartsAdapter()
            self.assertEqual(adapter.search_parts("555", "CTR"), [])
            with self.assertRaises(RuntimeError):
                adapter.order_part("555", "CTR", 1)

    @patch("urllib.request.urlopen")
    def test_tmparts_error_handling_server_error(self, mock_urlopen):
        with patch.dict(os.environ, {"TM_PARTS_KEY": "apikey"}):
            import sto_crm.config
            sto_crm.config.TM_PARTS_KEY = "apikey"

            mock_urlopen.side_effect = urllib.error.HTTPError(
                "http://example.com/api", 500, "Internal Server Error", None, io.BytesIO(b"")
            )
            adapter = TMPartsAdapter()
            self.assertEqual(adapter.search_parts("555", "CTR"), [])
            with self.assertRaises(RuntimeError):
                adapter.order_part("555", "CTR", 1)

    @patch("urllib.request.urlopen")
    def test_tmparts_error_handling_rate_limit(self, mock_urlopen):
        with patch.dict(os.environ, {"TM_PARTS_KEY": "apikey"}):
            import sto_crm.config
            sto_crm.config.TM_PARTS_KEY = "apikey"

            mock_urlopen.side_effect = urllib.error.HTTPError(
                "http://example.com/api", 429, "Too Many Requests", None, io.BytesIO(b"")
            )
            adapter = TMPartsAdapter()
            self.assertEqual(adapter.search_parts("555", "CTR"), [])
            with self.assertRaises(RuntimeError):
                adapter.order_part("555", "CTR", 1)

    @patch("urllib.request.urlopen")
    def test_tmparts_bad_json_parsing(self, mock_urlopen):
        with patch.dict(os.environ, {"TM_PARTS_KEY": "apikey"}):
            import sto_crm.config
            sto_crm.config.TM_PARTS_KEY = "apikey"

            mock_response = MagicMock()
            mock_response.read.return_value = b"{invalid_json"
            mock_urlopen.return_value.__enter__.return_value = mock_response

            adapter = TMPartsAdapter()
            self.assertEqual(adapter.search_parts("555", "CTR"), [])
            with self.assertRaises(RuntimeError):
                adapter.order_part("555", "CTR", 1)

    @patch("urllib.request.urlopen")
    def test_tmparts_missing_fields_parsing(self, mock_urlopen):
        with patch.dict(os.environ, {"TM_PARTS_KEY": "apikey"}):
            import sto_crm.config
            sto_crm.config.TM_PARTS_KEY = "apikey"

            mock_response = MagicMock()
            mock_response.read.return_value = b'[{"price": 1000.0}]'
            mock_urlopen.return_value.__enter__.return_value = mock_response

            adapter = TMPartsAdapter()
            results = adapter.search_parts("555", "CTR")
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["oem"], "555")
            self.assertEqual(results[0]["brand"], "CTR")
            self.assertEqual(results[0]["name"], "Запчасть TM Parts")
            self.assertEqual(results[0]["price"], 1000.0)
            self.assertEqual(results[0]["stock"], 0)
            self.assertEqual(results[0]["delivery_days"], 1)

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

    def test_cache_hit_miss_and_force_refresh(self):
        self.assertEqual(_get_cached_parts("555", "CTR"), [])

        with patch("sto_crm.parts_api.rossko.RosskoAdapter.search_parts") as mock_rossko, \
             patch("sto_crm.parts_api.mxgroup.MXGroupAdapter.search_parts") as mock_mx, \
             patch("sto_crm.parts_api.tmparts.TMPartsAdapter.search_parts") as mock_tm:

            mock_rossko.return_value = [{"oem": "555", "brand": "CTR", "name": "Joint", "price": 10.0, "stock": 1, "delivery_days": 1, "supplier": "rossko"}]
            mock_mx.return_value = []
            mock_tm.return_value = []

            # 1. Search is performed, it's a MISS
            res1 = search_supplier_parts("555", "CTR")
            self.assertEqual(len(res1), 1)
            mock_rossko.assert_called_once_with("555", "CTR")
            mock_mx.assert_called_once_with("555", "CTR")
            mock_tm.assert_called_once_with("555", "CTR")

            mock_rossko.reset_mock()
            mock_mx.reset_mock()
            mock_tm.reset_mock()

            # 2. Search again: it should be a HIT, not triggering adapter queries
            res2 = search_supplier_parts("555", "CTR")
            self.assertEqual(len(res2), 1)
            self.assertEqual(res2[0]["name"], "Joint")
            mock_rossko.assert_not_called()
            mock_mx.assert_not_called()
            mock_tm.assert_not_called()

            # 3. Search with force_refresh=True: it should force adapter query (MISS logic)
            res3 = search_supplier_parts("555", "CTR", force_refresh=True)
            self.assertEqual(len(res3), 1)
            mock_rossko.assert_called_once_with("555", "CTR")
            mock_mx.assert_called_once_with("555", "CTR")
            mock_tm.assert_called_once_with("555", "CTR")

    def test_cache_ttl_expiration_and_stale_cleanup(self):
        past_time = (datetime.now() - timedelta(hours=3)).replace(microsecond=0).isoformat()
        with write_db() as conn:
            conn.execute(
                """
                INSERT INTO supplier_parts_cache (oem, brand, name, price, stock, delivery_days, supplier, cached_at)
                VALUES ('555', 'CTR', 'Expired joint', 100.0, 5, 2, 'rossko', ?)
                """,
                (past_time,)
            )

        cached = _get_cached_parts("555", "CTR")
        self.assertEqual(len(cached), 1)
        self.assertEqual(cached[0]["name"], "Expired joint")

        with patch("sto_crm.parts_api.rossko.RosskoAdapter.search_parts") as mock_rossko, \
             patch("sto_crm.parts_api.mxgroup.MXGroupAdapter.search_parts") as mock_mx, \
             patch("sto_crm.parts_api.tmparts.TMPartsAdapter.search_parts") as mock_tm:

            mock_rossko.return_value = [{"oem": "555", "brand": "CTR", "name": "Fresh joint", "price": 120.0, "stock": 10, "delivery_days": 1, "supplier": "rossko"}]
            mock_mx.return_value = []
            mock_tm.return_value = []

            results = search_supplier_parts("555", "CTR")
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["name"], "Fresh joint")
            mock_rossko.assert_called_once_with("555", "CTR")

            cached_after = _get_cached_parts("555", "CTR")
            self.assertEqual(len(cached_after), 1)
            self.assertEqual(cached_after[0]["name"], "Fresh joint")

    def test_database_locking_retry_robustness(self):
        import sqlite3
        import threading

        lock_acquired = threading.Event()
        release_lock = threading.Event()
        lock_error = []

        def lock_db():
            try:
                conn = sqlite3.connect(self.db_path, timeout=5)
                conn.execute("BEGIN IMMEDIATE")
                lock_acquired.set()
                if not release_lock.wait(timeout=5):
                    pass
                conn.rollback()
                conn.close()
            except Exception as e:
                lock_error.append(e)
                lock_acquired.set()

        t = threading.Thread(target=lock_db)
        t.start()

        lock_acquired.wait(timeout=2)
        if lock_error:
            self.fail(f"Failed to acquire background database lock: {lock_error[0]}")

        def release_after_delay():
            time.sleep(0.15)
            release_lock.set()

        timer = threading.Thread(target=release_after_delay)
        timer.start()

        with patch("sto_crm.parts_api.rossko.RosskoAdapter.search_parts") as mock_search_rossko, \
             patch("sto_crm.parts_api.mxgroup.MXGroupAdapter.search_parts") as mock_search_mx, \
             patch("sto_crm.parts_api.tmparts.TMPartsAdapter.search_parts") as mock_search_tm:

            mock_search_rossko.return_value = [{"oem": "555", "brand": "CTR", "name": "B", "price": 10.0, "stock": 1, "delivery_days": 1, "supplier": "rossko"}]
            mock_search_mx.return_value = []
            mock_search_tm.return_value = []

            results = search_supplier_parts("555", "CTR")
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["oem"], "555")

        t.join(timeout=2)
        timer.join(timeout=2)


def get_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def crm_server():
    port = get_free_port()
    proc = subprocess.Popen(
        [sys.executable, "main.py", "--port", str(port), "--no-browser", "--demo"],
        cwd=str(Path(__file__).parent.parent.absolute()),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    url = f"http://127.0.0.1:{port}/"
    for _ in range(30):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.2)
    else:
        proc.terminate()
        proc.wait()
        raise RuntimeError("Server failed to start")

    yield url

    proc.terminate()
    proc.wait()


def test_parts_playwright_e2e(crm_server):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="chrome-for-testing",
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-setuid-sandbox",
            ],
        )
        context = browser.new_context()
        page = context.new_page()

        console_messages = []
        page.on("console", lambda msg: console_messages.append(msg.text))
        page.on("pageerror", lambda err: console_messages.append(str(err)))

        saved_routes = []
        page.route("**/api/parts/search?*", lambda route: saved_routes.append(route))

        page.goto(crm_server)
        page.wait_for_selector(".app")

        page.click("button[aria-label='Создать заказ-наряд']")
        page.wait_for_selector("#orderForm")

        page.click("#btnTabPartsLookup")

        assert page.is_visible("#partsLookupOem")
        assert page.is_visible("#partsLookupBrand")

        page.fill("#partsLookupOem", "555")
        page.fill("#partsLookupBrand", "CTR")

        page.click("#btnPartsLookupSearch")

        # Verify Shimmer animation/skeleton visible immediately
        shimmer = page.locator(".skeleton-shimmer").first
        shimmer.wait_for(state="attached")
        assert page.locator(".skeleton-shimmer").count() > 0

        # Fulfill the saved route to complete the request
        assert len(saved_routes) == 1
        saved_routes[0].fulfill(
            status=200,
            content_type="application/json",
            body='{"ok":true,"parts":['
                 '{"oem":"555","brand":"CTR","name":"Наконечник рулевой (E2E)","price":1250.0,"stock":5,"delivery_days":2,"supplier":"rossko"}'
                 ']}'
        )

        page.wait_for_selector(".parts-pricing-group")

        supplier_titles = page.locator(".parts-pricing-supplier-title h3").all_text_contents()
        assert any("Rossko" in title for title in supplier_titles)

        style_attrs = page.evaluate("""() => {
            const elements = document.querySelectorAll("#partsLookupResults *");
            const bad = [];
            for (const el of elements) {
                if (el.hasAttribute("style")) {
                    bad.push(el.tagName + ": " + el.getAttribute("style"));
                }
            }
            return bad;
        }""")
        assert len(style_attrs) == 0, f"Found style attributes: {style_attrs}"

        first_btn = page.locator(".btn-select-part").first
        first_btn.click()

        assert page.is_visible("#itemsHost")
        assert page.is_hidden("#orderTabPartsLookup")

        item_titles = [el.get_attribute("value") or "" for el in page.locator("#itemsHost td[data-label='Наименование'] input").all()]
        assert any("[CTR 555] Наконечник рулевой (E2E)" in title for title in item_titles)

        for msg in console_messages:
            assert "Content Security Policy" not in msg, f"Found CSP error in console logs: {msg}"

        browser.close()
