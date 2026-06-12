import json
import sqlite3
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from sto_crm import runtime as _runtime
from sto_crm.cli import create_server
from sto_crm.database import init_db
from sto_crm.runtime import Runtime


class TestHttpServerExtra(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.runtime_db = Path(self.tmpdir.name) / "test_http_extra.sqlite3"
        self.orig_runtime = _runtime.RUNTIME
        _runtime.RUNTIME = Runtime(
            db_path=self.runtime_db,
            start_time=time.time(),
            csrf_token="test_csrf_token",
            access_token="test_access_token",
            bootstrap_token="test_bootstrap_token"
        )
        init_db(seed_demo=True)
        # Mock latest_release_info to avoid GitHub api call
        self.patcher = patch("sto_crm.updates.latest_release_info")
        self.mock_latest = self.patcher.start()
        self.mock_latest.return_value = {
            "version": "1.17.2",
            "tag": "v1.17.2",
            "name": "СТО CRM 1.17.2",
            "is_newer": False,
            "has_asset": False,
            "asset": None,
            "manifest": None,
        }
        self.server = create_server(0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.patcher.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        _runtime.RUNTIME = self.orig_runtime
        self.tmpdir.cleanup()

    def test_print_order_success(self):
        # /print/order/1 с валидными access_token и csrf
        req = urllib.request.Request(
            f"{self.base}/print/order/1",
            headers={
                "X-CRM-Access-Token": "test_access_token",
                "X-CSRF-Token": "test_csrf_token"
            }
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            self.assertEqual(response.status, 200)
            body = response.read().decode("utf-8")
            self.assertIn("Toyota Camry", body)

    def test_csv_export_success(self):
        req = urllib.request.Request(
            f"{self.base}/api/export/customers.csv",
            headers={
                "X-CRM-Access-Token": "test_access_token",
                "X-CSRF-Token": "test_csrf_token"
            }
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            self.assertEqual(response.status, 200)
            body = response.read().decode("utf-8")
            self.assertTrue(body.startswith("\ufeff"))

    def test_api_car_catalog(self):
        req = urllib.request.Request(
            f"{self.base}/api/car-catalog",
            headers={
                "X-CRM-Access-Token": "test_access_token"
            }
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            self.assertEqual(response.status, 200)
            data = json.loads(response.read().decode("utf-8"))
            self.assertIn("makes", data)

    def test_backup_post_success(self):
        req = urllib.request.Request(
            f"{self.base}/api/backup",
            method="POST",
            headers={
                "X-CRM-Access-Token": "test_access_token",
                "X-CSRF-Token": "test_csrf_token",
                "Content-Type": "application/json"
            },
            data=b"{}"
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            self.assertEqual(response.status, 200)
            data = json.loads(response.read().decode("utf-8"))
            self.assertIn("filename", data)

    def test_invalid_json_post(self):
        req = urllib.request.Request(
            f"{self.base}/api/customers",
            method="POST",
            headers={
                "X-CRM-Access-Token": "test_access_token",
                "X-CSRF-Token": "test_csrf_token",
                "Content-Type": "application/json"
            },
            data=b"{invalid-json"
        )
        with self.assertRaises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(err.exception.code, 400)

    def test_http_exceptions_handling(self):
        # 1. KeyError (например, несуществующий клиент)
        req = urllib.request.Request(
            f"{self.base}/api/customers/9999",
            method="PUT",
            headers={
                "X-CRM-Access-Token": "test_access_token",
                "X-CSRF-Token": "test_csrf_token",
                "Content-Type": "application/json"
            },
            data=json.dumps({"name": "New Name", "phone": "123", "reminder_consent": True, "preferred_channel": "sms"}).encode("utf-8")
        )
        with self.assertRaises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(err.exception.code, 404)

        # 2. IntegrityError (например, некорректный внешний ключ или дубликат VIN)
        # Попробуем создать машинку с уже существующим VIN
        req_vehicle = urllib.request.Request(
            f"{self.base}/api/vehicles",
            method="POST",
            headers={
                "X-CRM-Access-Token": "test_access_token",
                "X-CSRF-Token": "test_csrf_token",
                "Content-Type": "application/json"
            },
            # Дубликат VIN-номер и клиент №1
            data=json.dumps({
                "vin": "JTNB11HK303000001",
                "make": "Toyota",
                "model": "Camry",
                "year": 2018,
                "plate": "A123AA99",
                "mileage": 82000,
                "customer_id": 1
            }).encode("utf-8")
        )
        # validation.py или django-подобное вызовет ValueError на дубликат VIN
        # но мы можем спровоцировать IntegrityError напрямую в API с помощью mock на create_vehicle
        with patch("sto_crm.http_server.create_vehicle", side_effect=sqlite3.IntegrityError("Conflict")):
            req_integrity = urllib.request.Request(
                f"{self.base}/api/vehicles",
                method="POST",
                headers={
                    "X-CRM-Access-Token": "test_access_token",
                    "X-CSRF-Token": "test_csrf_token",
                    "Content-Type": "application/json"
                },
                data=json.dumps({
                    "vin": "JTNB11HK303000007",
                    "make": "Toyota",
                    "model": "Camry",
                    "year": 2018,
                    "plate": "A999AA99",
                    "mileage": 8000,
                    "customer_id": 1
                }).encode("utf-8")
            )
            with self.assertRaises(urllib.error.HTTPError) as err:
                urllib.request.urlopen(req_integrity, timeout=5)
            self.assertEqual(err.exception.code, 409)

        # 3. RuntimeError
        with patch("sto_crm.http_server.create_vehicle", side_effect=RuntimeError("Runtime Err")):
            with self.assertRaises(urllib.error.HTTPError) as err:
                urllib.request.urlopen(req_vehicle, timeout=5)
            self.assertEqual(err.exception.code, 500)
