import unittest
import urllib.error
import urllib.request
from datetime import datetime
from email.message import Message
from pathlib import Path
from unittest.mock import MagicMock, patch

import sto_crm
from sto_crm import runtime as _runtime
from sto_crm.database import init_db
from sto_crm.reports import build_reports
from sto_crm.services import (
    apply_inventory_delta,
    ensure_inventory_available_for_order,
    reconcile_vehicle_mileage_after_order_change,
    update_order,
)
from sto_crm.updates import (
    APP_VERSION,
    download_release_asset,
    ensure_downloaded_executable,
    fetch_asset_json,
    install_update_from_github,
    latest_release_info,
    read_limited_response,
    validate_manifest_asset_download_url,
)


class MockDatetime:
    @classmethod
    def now(cls):
        m = MagicMock()
        m.date.return_value = datetime(2026, 6, 13).date()
        m.strftime.return_value = ""
        m.year = 2026
        m.month = 6
        return m

    @classmethod
    def fromisoformat(cls, val):
        return datetime.fromisoformat(val)


class FakeHead:
    def __len__(self):
        return 64

    def __getitem__(self, item):
        if isinstance(item, slice):
            if item.start is None and item.stop == 2:
                return b"MZ"
            if item.start == 60 and item.stop == 64:
                return [256, 0, 0, 0]
        return b"\x00"


class TestCoverageEdgeCases(unittest.TestCase):
    def setUp(self) -> None:
        self.orig_runtime = _runtime.RUNTIME
        import tempfile

        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test_edges.sqlite3"
        _runtime.RUNTIME = _runtime.Runtime(
            db_path=self.db_path,
            start_time=0.0,
            csrf_token="edge_csrf",
            access_token="edge_access",
            bootstrap_token="edge_bootstrap",
        )
        init_db(seed_demo=True)

    def tearDown(self) -> None:
        _runtime.RUNTIME = self.orig_runtime
        self.tmpdir.cleanup()
        import sto_crm.updater
        import sto_crm.updates
        sto_crm.updates._UPDATE_INSTALL_IN_PROGRESS = False
        sto_crm.updates._UPDATE_INSTALL_SCHEDULED = False
        sto_crm.updater._UPDATE_INSTALL_IN_PROGRESS = False
        sto_crm.updater._UPDATE_INSTALL_SCHEDULED = False

    # --- REPORTS.PY TESTS ---

    def test_reports_invalid_date_follow_up_at(self):
        # reports.py lines 176-177
        orders = [
            {
                "id": 1,
                "status": "closed",
                "follow_up_at": "invalid_date_format",
            }
        ]
        result = build_reports(
            orders=orders, inventory=[], vehicles=[], appointments=[]
        )
        self.assertEqual(result["active_orders"], 0)

    def test_reports_business_health_score_labels(self):
        # reports.py lines 428-431
        orders_pending = [
            {
                "id": i,
                "status": "estimate",
                "authorized_at": "",
                "total": "100.0",
                "due": "100.0",
                "margin": "10.0",
            }
            for i in range(4)
        ]
        result = build_reports(
            orders=orders_pending, inventory=[], vehicles=[], appointments=[]
        )
        self.assertEqual(result["business_health_label"], "Контроль")

        orders_risky = [
            {
                "id": i,
                "status": "estimate",
                "authorized_at": "",
                "total": "100.0",
                "due": "100.0",
                "margin": "10.0",
            }
            for i in range(8)
        ]
        result_risky = build_reports(
            orders=orders_risky, inventory=[], vehicles=[], appointments=[]
        )
        self.assertEqual(result_risky["business_health_label"], "Риски")

    @patch("sto_crm.reports.data.datetime", MockDatetime)
    def test_reports_month_closed_no_closed_at(self):
        # reports.py line 664->662
        orders = [
            {
                "id": 1,
                "status": "closed",
                "closed_at": None,
                "total": "150.0",
                "subtotal": "150.0",
                "discount": "0.0",
                "margin": "50.0",
                "due": "0.0",
            }
        ]
        result = build_reports(
            orders=orders, inventory=[], vehicles=[], appointments=[]
        )
        self.assertIn("orders_total", result)

    # --- SERVICES.PY TESTS ---

    def test_services_reconcile_vehicle_mileage_early_return(self):
        # services.py line 555
        with sto_crm.database.db() as conn:
            conn.execute(
                """
                INSERT INTO vehicles (id, customer_id, make, model, year, plate, vin, mileage, mileage_order_id, mileage_manual, created_at, updated_at)
                VALUES (12345, 1, 'Make', 'Model', 2020, 'PLATE123', 'VIN12345', 1000, 777, 0, '2026-06-13T12:00:00', '2026-06-13T12:00:00')
                """
            )
            conn.execute(
                """
                INSERT INTO orders (id, customer_id, vehicle_id, number, status, odometer, discount, created_at, updated_at)
                VALUES (777, 1, 12345, '777', 'approved', 1000, 0, '2026-06-13T12:00:00', '2026-06-13T12:00:00')
                """
            )
            reconcile_vehicle_mileage_after_order_change(
                conn, 12345, previous_order_id=777, previous_odometer=1000
            )

    def test_services_update_cancelled_after_closed_error(self):
        # services.py line 659
        with sto_crm.database.db() as conn:
            conn.execute(
                """
                INSERT INTO orders (id, customer_id, vehicle_id, number, status, closed_at, discount, created_at, updated_at)
                VALUES (777, 1, 1, '777', 'cancelled', '2026-06-13T12:00:00', 0, '2026-06-13T12:00:00', '2026-06-13T12:00:00')
                """
            )
            conn.execute(
                """
                INSERT INTO order_items (id, order_id, kind, title, quantity, unit_price, unit_cost, created_at)
                VALUES (77701, 777, 'service', 'Labor', 1, 100, 0, '2026-06-13T12:00:00')
                """
            )
        with self.assertRaises(ValueError) as ctx:
            update_order(
                777,
                {
                    "customer_id": 1,
                    "vehicle_id": 1,
                    "number": "777",
                    "status": "approved",
                    "closed_at": "2026-06-13T12:00:00",
                    "total": 100,
                    "subtotal": 100,
                    "discount": 0,
                    "margin": 50,
                    "due": 0,
                    "items": [
                        {
                            "kind": "service",
                            "title": "Labor",
                            "quantity": 1,
                            "unit_price": 100,
                            "unit_cost": 0,
                            "approval_status": "approved",
                        }
                    ],
                },
            )
        self.assertIn(
            "Отменённый после закрытия заказ-наряд нельзя повторно открыть",
            str(ctx.exception),
        )

    def test_services_update_cancelled_normal_error(self):
        # services.py line 678
        with sto_crm.database.db() as conn:
            conn.execute(
                """
                INSERT INTO orders (id, customer_id, vehicle_id, number, status, closed_at, discount, created_at, updated_at)
                VALUES (888, 1, 1, '888', 'cancelled', '', 0, '2026-06-13T12:00:00', '2026-06-13T12:00:00')
                """
            )
            conn.execute(
                """
                INSERT INTO order_items (id, order_id, kind, title, quantity, unit_price, unit_cost, created_at)
                VALUES (88801, 888, 'service', 'Labor', 1, 100, 0, '2026-06-13T12:00:00')
                """
            )
        with self.assertRaises(ValueError) as ctx:
            update_order(
                888,
                {
                    "customer_id": 1,
                    "vehicle_id": 1,
                    "number": "888",
                    "status": "approved",
                    "closed_at": "",
                    "total": 100,
                    "subtotal": 100,
                    "discount": 0,
                    "margin": 50,
                    "due": 0,
                    "items": [
                        {
                            "kind": "service",
                            "title": "Labor",
                            "quantity": 1,
                            "unit_price": 100,
                            "unit_cost": 0,
                            "approval_status": "approved",
                        }
                    ],
                },
            )
        self.assertIn(
            "Отменённый заказ-наряд нельзя повторно открыть", str(ctx.exception)
        )

    def test_services_inventory_not_found(self):
        # services.py line 881
        with sto_crm.database.db() as conn:
            with self.assertRaises(ValueError) as ctx:
                ensure_inventory_available_for_order(
                    conn, [{"kind": "part", "inventory_id": 999999, "quantity": 1}]
                )
            self.assertIn(
                "Складская позиция для резервирования не найдена", str(ctx.exception)
            )

    def test_services_inventory_deleted(self):
        # services.py line 883
        with sto_crm.database.db() as conn:
            conn.execute(
                """
                INSERT INTO inventory (id, sku, name, quantity, cost, price, min_quantity, deleted_at, created_at, updated_at)
                VALUES (54321, 'SKU54321', 'Deleted Part', 10, 5, 10, 0, '2026-06-13T12:00:00', '2026-06-13T12:00:00', '2026-06-13T12:00:00')
                """
            )
        with sto_crm.database.db() as conn:
            with self.assertRaises(ValueError) as ctx:
                ensure_inventory_available_for_order(
                    conn, [{"kind": "part", "inventory_id": 54321, "quantity": 1}]
                )
            self.assertIn("Складская позиция недоступна", str(ctx.exception))

    def test_services_change_financials_on_closed_cancel(self):
        # services.py line 988
        with sto_crm.database.db() as conn:
            conn.execute(
                """
                INSERT INTO orders (id, customer_id, vehicle_id, number, status, closed_at, discount, created_at, updated_at)
                VALUES (999, 1, 1, '999', 'closed', '2026-06-13T12:00:00', 0, '2026-06-13T12:00:00', '2026-06-13T12:00:00')
                """
            )
            conn.execute(
                """
                INSERT INTO order_items (id, order_id, kind, title, quantity, unit_price, unit_cost, created_at)
                VALUES (99901, 999, 'service', 'Labor', 1, 100, 0, '2026-06-13T12:00:00')
                """
            )
        with self.assertRaises(ValueError) as ctx:
            update_order(
                999,
                {
                    "customer_id": 1,
                    "vehicle_id": 1,
                    "number": "999",
                    "status": "cancelled",
                    "closed_at": "2026-06-13T12:00:00",
                    "total": 150,
                    "subtotal": 150,
                    "discount": 0,
                    "margin": 50,
                    "due": 0,
                    "items": [
                        {
                            "kind": "service",
                            "title": "Labor",
                            "quantity": 1,
                            "unit_price": 150,  # changed unit price
                            "unit_cost": 0,
                            "approval_status": "approved",
                        }
                    ],
                },
            )
        self.assertIn(
            "При отмене закрытого заказа нельзя менять финансовые данные",
            str(ctx.exception),
        )

    def test_services_apply_inventory_delta_continue(self):
        # services.py line 1014
        with sto_crm.database.db() as conn:
            apply_inventory_delta(
                conn,
                "approved",
                "approved",
                [{"part_id": 1, "quantity": 1.0}],
                [{"part_id": 1, "quantity": 1.0 + 1e-10}],
            )

    # --- UPDATES.PY TESTS ---

    def test_updates_validate_manifest_url_invalid_tag(self):
        # updates.py line 323
        with self.assertRaises(RuntimeError) as ctx:
            validate_manifest_asset_download_url(
                "https://github.com/a/b/releases/download/v1..0/file.exe",
                "a/b",
                "v1..0",
            )
        self.assertIn(
            "Manifest обновления содержит некорректный тег релиза", str(ctx.exception)
        )

    def test_updates_read_limited_response_payload_limit(self):
        # updates.py line 365
        mock_resp = MagicMock()
        mock_resp.info.return_value = {}
        mock_resp.read.return_value = b"12345678901"
        with self.assertRaises(RuntimeError) as ctx:
            read_limited_response(mock_resp, max_bytes=10, label="test")
        self.assertIn("слишком большой для безопасной обработки", str(ctx.exception))

    def test_updates_fetch_asset_json_missing_url(self):
        # updates.py lines 424-429
        with self.assertRaises(RuntimeError) as ctx:
            fetch_asset_json({})
        self.assertIn(
            "В GitHub Release нет ссылки на manifest latest.json", str(ctx.exception)
        )

    @patch("sto_crm.updates.fetch_json")
    @patch("sto_crm.updates.fetch_asset_json")
    def test_updates_latest_release_info_with_manifest(
        self, mock_fetch_asset, mock_fetch_json
    ):
        # updates.py lines 527-528
        mock_fetch_json.return_value = {
            "tag_name": "v1.2.3",
            "assets": [
                {
                    "name": "latest.json",
                    "browser_download_url": "https://github.com/markbakaa88/sto-crm/releases/download/v1.2.3/latest.json",
                }
            ],
        }
        mock_fetch_asset.return_value = {
            "version": "1.2.3",
            "tag": "v1.2.3",
            "asset": {
                "name": "STO_CRM.exe",
                "download_url": "https://github.com/markbakaa88/sto-crm/releases/download/v1.2.3/STO_CRM.exe",
                "sha256": "a" * 64,
                "size": 1000,
            },
        }
        info = latest_release_info()
        self.assertEqual(info["version"], "1.2.3")

    def test_updates_download_asset_expected_size_too_large(self):
        # updates.py line 601
        asset = {
            "download_url": "https://github.com/markbakaa88/sto-crm/releases/download/v1.0.0/file.exe",
            "sha256": "a" * 64,
            "size": 300 * 1024 * 1024,
        }
        with self.assertRaises(RuntimeError) as ctx:
            download_release_asset(asset, Path("dummy"))
        self.assertIn("Файл обновления слишком большой", str(ctx.exception))

    @patch("urllib.request.urlopen")
    def test_updates_download_asset_read_too_large(self, mock_urlopen):
        # updates.py line 629
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.info.return_value = {}
        mock_resp.geturl.return_value = (
            "https://github.com/markbakaa88/sto-crm/releases/download/v1.0.0/file.exe"
        )
        mock_resp.read.side_effect = [b"x" * (260 * 1024 * 1024)]
        mock_urlopen.return_value = mock_resp

        asset = {
            "download_url": "https://github.com/markbakaa88/sto-crm/releases/download/v1.0.0/file.exe",
            "sha256": "a" * 64,
            "size": 1000,
        }
        with self.assertRaises(RuntimeError) as ctx:
            download_release_asset(asset, Path("dummy"))
        self.assertIn("Файл обновления превышает безопасный лимит", str(ctx.exception))

    @patch("urllib.request.urlopen")
    def test_updates_download_asset_http_error(self, mock_urlopen):
        # updates.py lines 648-649
        mock_fp = MagicMock()
        hdrs = Message()
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="http://test.com", code=404, msg="Not Found", hdrs=hdrs, fp=mock_fp
        )
        asset = {
            "download_url": "https://github.com/markbakaa88/sto-crm/releases/download/v1.0.0/file.exe",
            "sha256": "a" * 64,
            "size": 1000,
        }
        target = Path(self.tmpdir.name) / "test_download.exe"
        with self.assertRaises(RuntimeError) as ctx:
            download_release_asset(asset, target)
        self.assertIn("HTTP 404", str(ctx.exception))
        self.assertFalse(target.with_name(f"{target.name}.tmp").exists())

    @patch("urllib.request.urlopen")
    def test_updates_download_asset_os_error(self, mock_urlopen):
        # updates.py lines 651-652
        mock_urlopen.side_effect = OSError("Connection refused")
        asset = {
            "download_url": "https://github.com/markbakaa88/sto-crm/releases/download/v1.0.0/file.exe",
            "sha256": "a" * 64,
            "size": 1000,
        }
        target = Path(self.tmpdir.name) / "test_download8.exe"
        with self.assertRaises(RuntimeError) as ctx:
            download_release_asset(asset, target)
        self.assertIn("Connection refused", str(ctx.exception))
        self.assertFalse(target.with_name(f"{target.name}.tmp").exists())

    @patch("urllib.request.urlopen")
    def test_updates_download_asset_generic_error(self, mock_urlopen):
        # updates.py line 657
        mock_urlopen.side_effect = Exception("Generic connection failure")
        asset = {
            "download_url": "https://github.com/markbakaa88/sto-crm/releases/download/v1.0.0/file.exe",
            "sha256": "a" * 64,
            "size": 1000,
        }
        target = Path(self.tmpdir.name) / "test_download9.exe"
        with self.assertRaises(RuntimeError) as ctx:
            download_release_asset(asset, target)
        self.assertIn("Generic connection failure", str(ctx.exception))
        self.assertFalse(target.with_name(f"{target.name}.tmp").exists())

    @patch("pathlib.Path.open")
    def test_updates_ensure_downloaded_exe_val_error(self, mock_open):
        # updates.py lines 672-673
        mock_file = MagicMock()
        mock_file.__enter__.return_value = mock_file
        mock_file.read.return_value = FakeHead()
        mock_open.return_value = mock_file

        with self.assertRaises(RuntimeError) as ctx:
            ensure_downloaded_executable(Path("dummy.exe"))
        self.assertIn("Скачанный файл не похож на Windows .exe", str(ctx.exception))

    @patch("sto_crm.updates.can_install_windows_update", return_value=True)
    @patch("sto_crm.updates.latest_release_info")
    def test_updates_install_already_actual(self, mock_latest, mock_can_install):
        # updates.py line 818
        mock_latest.return_value = {
            "prerelease": False,
            "draft": False,
            "version": APP_VERSION,
        }
        res = install_update_from_github()
        self.assertTrue(res["ok"])
        self.assertFalse(res["updated"])
        self.assertEqual(res["message"], "Установлена актуальная версия.")

    @patch("sto_crm.updates.can_install_windows_update", return_value=True)
    @patch("sto_crm.updates.latest_release_info")
    def test_updates_install_no_asset_dict(self, mock_latest, mock_can_install):
        # updates.py line 826
        mock_latest.return_value = {
            "prerelease": False,
            "draft": False,
            "version": "99.9.9",
            "asset": None,
        }
        with self.assertRaises(RuntimeError) as ctx:
            install_update_from_github()
        self.assertIn("нет файла STO_CRM.exe для обновления", str(ctx.exception))

    @patch("sto_crm.updates.can_install_windows_update", return_value=True)
    @patch("sto_crm.updates.latest_release_info")
    @patch("sto_crm.updates.create_backup")
    @patch("sto_crm.updates.download_release_asset")
    @patch("sto_crm.updates.ensure_downloaded_executable")
    @patch("sto_crm.updates.schedule_windows_update")
    def test_updates_install_success(
        self,
        mock_schedule,
        mock_ensure_exe,
        mock_download,
        mock_backup,
        mock_latest,
        mock_can_install,
    ):
        # updates.py lines 844-849
        mock_latest.return_value = {
            "prerelease": False,
            "draft": False,
            "version": "99.9.9",
            "asset": {
                "name": "STO_CRM.exe",
                "download_url": "https://github.com/markbakaa88/sto-crm/releases/download/v99.9.9/STO_CRM.exe",
                "sha256": "b" * 64,
                "size": 2000,
            },
        }
        mock_backup.return_value = {"display_path": "backup.sqlite3"}
        mock_download.return_value = {"size": 2000, "sha256": "b" * 64}

        res = install_update_from_github()
        self.assertTrue(res["ok"])
        self.assertTrue(res["updated"])
        self.assertIn("Обновление скачано", res["message"])

    @patch("sto_crm.updates.can_install_windows_update", return_value=True)
    @patch("sto_crm.updates.latest_release_info")
    @patch("sto_crm.updates.create_backup")
    @patch("sto_crm.updates.download_release_asset")
    @patch("sto_crm.updates.ensure_downloaded_executable")
    def test_updates_install_finally_cleanup(
        self, mock_ensure_exe, mock_download, mock_backup, mock_latest, mock_can_install
    ):
        # updates.py finally block when downloaded but not scheduled
        mock_latest.return_value = {
            "prerelease": False,
            "draft": False,
            "version": "99.9.9",
            "asset": {
                "name": "STO_CRM.exe",
                "download_url": "https://github.com/markbakaa88/sto-crm/releases/download/v99.9.9/STO_CRM.exe",
                "sha256": "b" * 64,
                "size": 2000,
            },
        }
        mock_backup.return_value = {"display_path": "backup.sqlite3"}
        mock_download.return_value = {"size": 2000, "sha256": "b" * 64}
        mock_ensure_exe.side_effect = RuntimeError("Invalid MZ header simulated")

        with self.assertRaises(RuntimeError) as ctx:
            install_update_from_github()
        self.assertIn("Invalid MZ header simulated", str(ctx.exception))
