import os
import sqlite3
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from sto_crm import runtime as _runtime
from sto_crm.database import db, init_db, write_db
from sto_crm.http_server import CRMServer
from sto_crm.runtime import (
    _strict_json_float,
    normalize_github_repository,
    redact_local_paths,
)
from sto_crm.services import apply_inventory_delta, create_order, update_order
from sto_crm.updates import fetch_asset_json


class TestUltraCoverage(unittest.TestCase):
    def setUp(self) -> None:
        self.orig_runtime = _runtime.RUNTIME
        import tempfile
        from pathlib import Path

        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test_ultra.sqlite3"
        _runtime.RUNTIME = _runtime.Runtime(
            db_path=self.db_path,
            start_time=0.0,
            csrf_token="ultra_csrf",
            access_token="ultra_access",
            bootstrap_token="ultra_bootstrap",
        )
        init_db(seed_demo=True)

    def tearDown(self) -> None:
        _runtime.RUNTIME = self.orig_runtime
        self.tmpdir.cleanup()

    # --- DATABASE.PY BRANCHES ---

    def test_db_in_transaction_error_handling(self):
        # We test that errors during transaction checks/commits/rollbacks/closes are caught
        class BrokenConnection:
            def __init__(self):
                pass

            @property
            def in_transaction(self):
                raise AttributeError("Attribute Error simulated")

            def commit(self):
                raise sqlite3.Error("Commit Error simulated")

            def rollback(self):
                raise sqlite3.Error("Rollback Error simulated")

            def close(self):
                raise AttributeError("Close Error simulated")

        import sto_crm.database

        orig_connect = sto_crm.database.connect
        sto_crm.database.connect = lambda: BrokenConnection()  # type: ignore

        try:
            # Entering context manager
            with db() as _:
                pass
        finally:
            sto_crm.database.connect = orig_connect

    @patch("sto_crm.database.connect")
    def test_init_db_in_transaction_error(self, mock_connect):
        class BrokenInitConnection:
            def execute(self, *args, **kwargs):
                raise sqlite3.DatabaseError("init_db failed")

            @property
            def in_transaction(self):
                raise AttributeError("simulated")

            def rollback(self):
                pass

            def close(self):
                pass

        mock_connect.return_value = BrokenInitConnection()
        with self.assertRaises(sqlite3.DatabaseError):
            init_db()

    def test_write_db_other_operational_error(self):
        conn = MagicMock()
        conn.execute.side_effect = sqlite3.OperationalError("disk I/O error")
        with patch("sto_crm.database.db") as mock_db:
            mock_db.return_value.__enter__.return_value = conn
            with self.assertRaises(sqlite3.OperationalError):
                with write_db() as _:
                    pass

    def test_write_db_locked_retry(self):
        # We simulate the busy-retry loop in write_db
        # Mock connections execute to fail with a locked error first, then succeed
        call_count = 0

        def mock_execute(sql, *args):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise sqlite3.OperationalError("database is locked")
            # Return dummy value
            m = MagicMock()
            return m

        conn = MagicMock()
        conn.execute = mock_execute

        # We construct a write_db loop manually or mock conn inside write_db
        with patch("sto_crm.database.db") as mock_db:
            mock_db.return_value.__enter__.return_value = conn
            with write_db() as _:
                self.assertEqual(call_count, 3)

    def test_write_db_locked_retry_exhausted(self):
        conn = MagicMock()
        conn.execute.side_effect = sqlite3.OperationalError("database is locked")
        with patch("sto_crm.database.db") as mock_db:
            mock_db.return_value.__enter__.return_value = conn
            with self.assertRaises(sqlite3.OperationalError):
                with write_db() as _:
                    pass

    # --- RUNTIME.PY BRANCHES ---

    def test_normalize_github_repository_empty(self):
        # Trigger line 152: if not raw: return GITHUB_REPOSITORY
        with patch.dict(os.environ, {}, clear=True):
            res = normalize_github_repository("   ")
            self.assertEqual(res, "markbakaa88/sto-crm")

    def test_redact_local_paths_url(self):
        # Trigger line 430: URL paths should not be redacted
        msg = "http://link.com?file=/usr/bin/local"
        res = redact_local_paths(msg)
        self.assertEqual(res, msg)

    def test_strict_json_float_valid(self):
        # Trigger line 453: return parsed float
        self.assertEqual(_strict_json_float("123.45"), 123.45)
        with self.assertRaises(ValueError):
            _strict_json_float("inf")

    # --- HTTP_SERVER.PY BRANCHES ---

    def test_http_server_graceful_shutdown_flag(self):
        # Trigger lines 137-138
        from sto_crm.http_server import CRMHandler

        mock_server = MagicMock()
        mock_server.graceful_shutdown_flag = True

        # Instantiate request handler with stub arguments to satisfy static checkers
        with patch.object(CRMHandler, "__init__", lambda self, *args, **kwargs: None):
            handler = CRMHandler(MagicMock(), ("127.0.0.1", 1000), mock_server)
            handler.server = mock_server
            handler.path = "/api/v1/customers"
            handler.send_error_json = MagicMock()

            # Call handle_request
            handler.handle_request("GET")
            handler.send_error_json.assert_called_once_with(
                503, "Сервер останавливается."
            )

    def test_http_server_wait_for_active_threads(self):
        # Trigger lines 681-690: wait_for_active_threads break logic
        mock_server = MagicMock()
        mock_server._active_threads_lock = threading.Lock()

        dummy_thread = threading.Thread(target=lambda: time.sleep(0.05))
        dummy_thread2 = threading.Thread(target=lambda: time.sleep(0.05))
        dummy_thread.start()
        dummy_thread2.start()

        mock_server._active_threads = {dummy_thread, dummy_thread2}
        CRMServer.wait_for_active_threads(mock_server, timeout=0.001)
        dummy_thread.join()
        dummy_thread2.join()

    def test_http_server_wait_for_active_threads_natural_exit(self):
        # Trigger natural loop exit in wait_for_active_threads
        mock_server = MagicMock()
        mock_server._active_threads_lock = threading.Lock()

        # Test with empty threads list
        mock_server._active_threads = set()
        CRMServer.wait_for_active_threads(mock_server, timeout=5.0)

    # --- SERVICES.PY BRANCHES ---

    def test_update_order_cancelled_after_closed_modify_error(self):
        # Trigger line 663: modification of order in cancelled status (where it has been closed before)
        order = create_order(
            {
                "customer_id": 1,
                "status": "closed",
                "priority": "normal",
                "items": [{"title": "Work", "quantity": "1", "unit_price": "100"}],
            }
        )
        order_cancelled = update_order(order["id"], {**order, "status": "cancelled"})
        self.assertEqual(order_cancelled["status"], "cancelled")

        # Now try to update it but modify something, which raises ValueError
        modified_payload = {
            **order_cancelled,
            "complaint": "modifying complaint, which is forbidden",
        }
        with self.assertRaises(ValueError) as ctx:
            update_order(order["id"], modified_payload)
        self.assertIn(
            "Отменённый после закрытия заказ-наряд нельзя повторно открыть или изменить",
            str(ctx.exception),
        )

    def test_update_order_cancelled_modify_error(self):
        # Trigger line 682: modifying ordinary cancelled order
        order = create_order(
            {
                "customer_id": 1,
                "status": "new",
                "priority": "normal",
                "items": [{"title": "Work", "quantity": "1", "unit_price": "100"}],
            }
        )
        order_cancelled = update_order(order["id"], {**order, "status": "cancelled"})
        self.assertEqual(order_cancelled["status"], "cancelled")

        # Try to modify items of cancelled order
        modified_payload = {
            **order_cancelled,
            "items": [{"title": "Mod Work", "quantity": "1", "unit_price": "100"}],
        }
        with self.assertRaises(ValueError) as ctx:
            update_order(order["id"], modified_payload)
        self.assertIn("Отменённый заказ-наряд нельзя изменить", str(ctx.exception))

    def test_apply_inventory_delta_epsilon(self):
        # Trigger line 1018: if abs(delta) < stock_epsilon: continue
        with db() as conn:
            # We call apply_inventory_delta with an extremely small difference
            old_items = [{"inventory_id": 1, "quantity": 1.0, "kind": "part"}]
            new_items = [
                {"inventory_id": 1, "quantity": 1.00000000000001, "kind": "part"}
            ]

            # Should run without error and bypass actual stock modification
            apply_inventory_delta(conn, "closed", "closed", old_items, new_items)

    # --- UPDATES.PY BRANCHES ---

    @patch("sto_crm.updates.fetch_json")
    def test_fetch_asset_json(self, mock_fetch):
        # Trigger line 429: fetch_asset_json octet-stream headers
        from sto_crm.updates import github_headers

        mock_fetch.return_value = {"version": "1.0.0"}
        res = fetch_asset_json(
            {"browser_download_url": "http://example.com/latest.json"}
        )
        self.assertEqual(res, {"version": "1.0.0"})
        mock_fetch.assert_called_once_with(
            "http://example.com/latest.json",
            headers=github_headers("application/octet-stream"),
        )
