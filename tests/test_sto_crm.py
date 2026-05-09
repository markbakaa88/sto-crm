import codecs
import contextlib
import hashlib
import io
import json
import os
import sqlite3
import socket
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path

import sto_crm


def service_item(price=100):
    return {"kind": "service", "title": "Labor", "quantity": 1, "unit_price": price, "unit_cost": 0}

class StoCrmTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.old_runtime = sto_crm.RUNTIME
        self.old_safe_log = sto_crm.safe_log
        sto_crm.safe_log = lambda _message: None
        sto_crm.RUNTIME = sto_crm.Runtime(Path(self.tempdir.name) / "test.sqlite3", time.time(), "test-csrf-token")
        sto_crm.init_db()

    def tearDown(self):
        # Очищаем тестовую БД перед удалением временной директории
        if hasattr(self, 'tempdir'):
            try:
                sto_crm.RUNTIME = self.old_runtime
            except Exception:
                pass
        sto_crm.safe_log = self.old_safe_log
        self.tempdir.cleanup()

    def create_customer(self, name):
        return sto_crm.create_customer({"name": name, "phone": "", "email": "", "source": "", "notes": ""})

    def create_vehicle(self, customer_id, plate):
        return sto_crm.create_vehicle(
            {
                "customer_id": customer_id,
                "make": "Lada",
                "model": "Vesta",
                "year": 2024,
                "plate": plate,
                "vin": "",
                "mileage": 1000,
                "notes": "",
            }
        )

    def test_order_rejects_vehicle_from_another_customer(self):
        first = self.create_customer("First")
        second = self.create_customer("Second")
        vehicle = self.create_vehicle(first["id"], "A001AA")

        with self.assertRaisesRegex(ValueError, "другому клиенту"):
            sto_crm.create_order(
                {
                    "customer_id": second["id"],
                    "vehicle_id": vehicle["id"],
                    "status": "new",
                    "priority": "normal",
                    "items": [service_item()],
                }
            )

    def test_new_database_starts_empty_without_demo_flag(self):
        self.assertEqual(sto_crm.list_customers(""), [])
        self.assertEqual(sto_crm.list_orders("", "all"), [])
        self.assertEqual(sto_crm.list_inventory(""), [])

    def test_bootstrap_includes_ready_vehicle_catalog(self):
        payload = sto_crm.bootstrap_payload()
        catalog = payload["car_catalog"]
        self.assertGreaterEqual(catalog["stats"]["makes"], 250)
        self.assertGreaterEqual(catalog["stats"]["models"], 2500)
        self.assertGreaterEqual(catalog["stats"]["empty_makes"], 0)
        self.assertEqual(len(catalog["makes"]), len(set(make.casefold() for make in catalog["makes"])))
        self.assertIn("Lada", catalog["makes"])
        self.assertIn("Toyota", catalog["makes"])
        self.assertIn("Acura", catalog["makes"])
        self.assertIn("Ferrari", catalog["makes"])
        self.assertIn("Costin Sports Car", catalog["makes"])
        self.assertIn("Vesta", catalog["models"]["Lada"])
        self.assertIn("Camry", catalog["models"]["Toyota"])
        self.assertEqual(len(catalog["models"]["Toyota"]), len(set(model.casefold() for model in catalog["models"]["Toyota"])))
        self.assertEqual(catalog["models"]["Toyota"], sorted(catalog["models"]["Toyota"], key=str.casefold))

    def test_catalog_csv_export_includes_all_makes_and_models(self):
        filename, content = sto_crm.csv_export("catalog")
        self.assertEqual(filename, "car_catalog.csv")
        self.assertTrue(content.startswith("\ufeffmake;model"))
        self.assertFalse(content.startswith("\ufeff\ufeff"))
        self.assertIn("Toyota;Camry", content)
        self.assertIn("Lada;Vesta", content)
        self.assertIn("Costin Sports Car;", content)

    def test_crm_best_practice_tasks_and_reminders(self):
        customer = sto_crm.create_customer(
            {
                "name": "Retention Customer",
                "phone": "+7999",
                "email": "client@example.ru",
                "source": "Service",
                "preferred_channel": "sms",
                "reminder_consent": 1,
                "notes": "",
            }
        )
        vehicle = sto_crm.create_vehicle(
            {
                "customer_id": customer["id"],
                "make": "Toyota",
                "model": "Camry",
                "year": 2020,
                "plate": "R001ET",
                "vin": "",
                "mileage": 49500,
                "next_service_at": "2000-01-01",
                "next_service_mileage": 50000,
                "notes": "",
            }
        )
        estimate = sto_crm.create_order(
            {
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "status": "estimate",
                "priority": "normal",
                "items": [service_item(100)],
            }
        )
        closed = sto_crm.create_order(
            {
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "status": "closed",
                "priority": "normal",
                "follow_up_at": "2000-01-01T10:00",
                "items": [service_item(100)],
            }
        )

        payload = sto_crm.bootstrap_payload()
        reports = payload["reports"]
        self.assertEqual(customer["preferred_channel"], "sms")
        self.assertEqual(customer["reminder_consent"], 1)
        self.assertTrue(any(item["id"] == vehicle["id"] for item in reports["service_reminders"]))
        self.assertTrue(any(item["id"] == estimate["id"] for item in reports["authorizations_pending"]))
        self.assertTrue(any(item["id"] == closed["id"] for item in reports["followups_due"]))
        self.assertGreaterEqual(reports["crm_tasks_count"], 3)

    def test_declined_order_items_are_not_billed_or_consumed_and_become_crm_tasks(self):
        customer = self.create_customer("Deferred Customer")
        vehicle = self.create_vehicle(customer["id"], "D004DD")
        part = sto_crm.create_inventory({"sku": "DECL", "name": "Declined part", "quantity": 1, "price": 50, "cost": 25})

        order = sto_crm.create_order(
            {
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "status": "closed",
                "priority": "normal",
                "items": [
                    service_item(100),
                    {
                        "kind": "part",
                        "inventory_id": part["id"],
                        "title": "Declined part",
                        "approval_status": "declined",
                        "quantity": 1,
                        "unit_price": 50,
                        "unit_cost": 25,
                    },
                ],
            }
        )

        self.assertEqual(order["parts_total"], 0)
        self.assertEqual(order["total"], 100)
        with sto_crm.db() as conn:
            self.assertEqual(sto_crm.get_inventory(conn, part["id"])["quantity"], 1)
        reports = sto_crm.bootstrap_payload()["reports"]
        self.assertTrue(any(item["title"] == "Declined part" for item in reports["deferred_work"]))

    def test_appointments_reject_wrong_vehicle_and_report_today(self):
        first = self.create_customer("Appointment One")
        second = self.create_customer("Appointment Two")
        vehicle = self.create_vehicle(first["id"], "Z005ZZ")

        with self.assertRaises(ValueError):
            sto_crm.create_appointment(
                {
                    "customer_id": second["id"],
                    "vehicle_id": vehicle["id"],
                    "scheduled_at": "2099-01-01T10:00",
                    "status": "scheduled",
                }
            )

        today_slot = sto_crm.datetime.now().replace(hour=10, minute=0, second=0, microsecond=0).isoformat(timespec="minutes")
        appointment = sto_crm.create_appointment(
            {
                "customer_id": first["id"],
                "vehicle_id": vehicle["id"],
                "scheduled_at": today_slot,
                "duration_minutes": 45,
                "status": "confirmed",
                "advisor": "Admin",
                "reason": "Suspension check",
            }
        )

        payload = sto_crm.bootstrap_payload()
        self.assertTrue(any(item["id"] == appointment["id"] for item in payload["appointments"]))
        self.assertTrue(any(item["id"] == appointment["id"] for item in payload["reports"]["appointments_today"]))
        filename, content = sto_crm.csv_export("appointments")
        self.assertEqual(filename, "appointments.csv")
        self.assertIn("Suspension check", content)

    def test_digital_inspection_tracks_critical_items_and_exports(self):
        customer = self.create_customer("Inspection Customer")
        vehicle = self.create_vehicle(customer["id"], "I006II")
        order = sto_crm.create_order(
            {
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "status": "diagnostics",
                "priority": "normal",
                "items": [service_item(100)],
            }
        )

        inspection = sto_crm.create_inspection(
            {
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "order_id": order["id"],
                "status": "ready",
                "inspector": "Tech",
                "inspected_at": "2099-01-01T11:00",
                "summary": "Needs approval",
                "items": [
                    {
                        "area": "Brakes",
                        "title": "Front pads",
                        "condition_status": "critical",
                        "approval_status": "deferred",
                        "recommendation": "Replace",
                        "estimate": 500,
                    },
                    {"area": "Lights", "title": "Headlights", "condition_status": "ok"},
                ],
            }
        )

        self.assertEqual(inspection["critical_count"], 1)
        self.assertEqual(inspection["recommended_total"], 500)
        reports = sto_crm.bootstrap_payload()["reports"]
        self.assertTrue(any(item["title"] == "Front pads" for item in reports["inspection_alerts"]))
        self.assertGreaterEqual(reports["crm_tasks_count"], 1)
        filename, content = sto_crm.csv_export("inspections")
        self.assertEqual(filename, "inspections.csv")
        self.assertIn("Front pads", content)

    def test_frozen_app_uses_localappdata_for_database_by_default(self):
        old_app_dir = sto_crm.app_dir
        old_directory_writable = sto_crm.directory_writable
        old_localappdata = os.environ.get("LOCALAPPDATA")
        had_frozen = hasattr(sto_crm.sys, "frozen")
        old_frozen = getattr(sto_crm.sys, "frozen", None)
        fallback = Path(self.tempdir.name) / "LocalAppData"

        try:
            sto_crm.app_dir = lambda: Path(self.tempdir.name) / "ReadOnlyApp"
            sto_crm.directory_writable = lambda directory: str(directory).startswith(str(fallback))
            sto_crm.sys.frozen = True
            os.environ["LOCALAPPDATA"] = str(fallback)
            self.assertEqual(sto_crm.default_db_path(), fallback / "STO_CRM" / "sto_crm.sqlite3")
            self.assertTrue((fallback / "STO_CRM").is_dir())
        finally:
            sto_crm.app_dir = old_app_dir
            sto_crm.directory_writable = old_directory_writable
            if had_frozen:
                sto_crm.sys.frozen = old_frozen
            else:
                delattr(sto_crm.sys, "frozen")
            if old_localappdata is None:
                os.environ.pop("LOCALAPPDATA", None)
            else:
                os.environ["LOCALAPPDATA"] = old_localappdata

    def test_legacy_database_adds_closed_at_before_index(self):
        legacy_db = Path(self.tempdir.name) / "legacy.sqlite3"
        sto_crm.RUNTIME = sto_crm.Runtime(legacy_db, time.time(), "test-csrf-token")
        conn = sqlite3.connect(legacy_db)
        try:
            conn.execute(
                """
                CREATE TABLE orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    number TEXT NOT NULL UNIQUE,
                    customer_id INTEGER NOT NULL,
                    vehicle_id INTEGER,
                    status TEXT NOT NULL DEFAULT 'new',
                    priority TEXT NOT NULL DEFAULT 'normal',
                    advisor TEXT NOT NULL DEFAULT '',
                    mechanic TEXT NOT NULL DEFAULT '',
                    promised_at TEXT NOT NULL DEFAULT '',
                    odometer INTEGER NOT NULL DEFAULT 0,
                    complaint TEXT NOT NULL DEFAULT '',
                    diagnosis TEXT NOT NULL DEFAULT '',
                    recommendations TEXT NOT NULL DEFAULT '',
                    discount REAL NOT NULL DEFAULT 0,
                    tax_rate REAL NOT NULL DEFAULT 0,
                    paid REAL NOT NULL DEFAULT 0,
                    payment_method TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

        sto_crm.init_db()
        with sto_crm.db() as conn:
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(orders)").fetchall()}
            item_columns = {row["name"] for row in conn.execute("PRAGMA table_info(order_items)").fetchall()}
            appointment_columns = {row["name"] for row in conn.execute("PRAGMA table_info(appointments)").fetchall()}
            inspection_columns = {row["name"] for row in conn.execute("PRAGMA table_info(inspections)").fetchall()}
            inspection_item_columns = {row["name"] for row in conn.execute("PRAGMA table_info(inspection_items)").fetchall()}
            indexes = {row["name"] for row in conn.execute("PRAGMA index_list(orders)").fetchall()}
            appointment_indexes = {row["name"] for row in conn.execute("PRAGMA index_list(appointments)").fetchall()}
            inspection_indexes = {row["name"] for row in conn.execute("PRAGMA index_list(inspections)").fetchall()}
        self.assertIn("closed_at", columns)
        self.assertIn("authorized_by", columns)
        self.assertIn("authorized_at", columns)
        self.assertIn("follow_up_at", columns)
        self.assertIn("approval_status", item_columns)
        self.assertIn("scheduled_at", appointment_columns)
        self.assertIn("inspected_at", inspection_columns)
        self.assertIn("condition_status", inspection_item_columns)
        self.assertIn("idx_orders_closed_at", indexes)
        self.assertIn("idx_orders_follow_up_at", indexes)
        self.assertIn("idx_appointments_schedule", appointment_indexes)
        self.assertIn("idx_inspections_vehicle", inspection_indexes)

    def test_closed_order_tracks_closed_at_normalizes_money_and_restores_stock(self):
        customer = self.create_customer("Stock Customer")
        vehicle = self.create_vehicle(customer["id"], "B002BB")
        part = sto_crm.create_inventory(
            {
                "sku": "T-001",
                "name": "Test part",
                "brand": "",
                "unit": "шт",
                "quantity": 3,
                "min_quantity": 1,
                "price": 50,
                "cost": 20,
                "supplier": "",
                "notes": "",
            }
        )
        payload = {
            "customer_id": customer["id"],
            "vehicle_id": vehicle["id"],
            "status": "closed",
            "priority": "normal",
            "advisor": "Admin",
            "mechanic": "Mechanic",
            "promised_at": "",
            "odometer": 1000,
            "complaint": "",
            "diagnosis": "",
            "recommendations": "",
            "discount": 25,
            "tax_rate": 150,
            "paid": 9999,
            "payment_method": "",
            "items": [
                service_item(100),
                {"kind": "part", "inventory_id": part["id"], "title": "Test part", "quantity": 1, "unit_price": 50, "unit_cost": 20},
            ],
        }

        order = sto_crm.create_order(payload)
        self.assertEqual(order["status"], "closed")
        self.assertTrue(order["closed_at"])
        self.assertTrue(order["follow_up_at"])
        self.assertEqual(order["tax_rate"], 100)
        self.assertEqual(order["discount"], 25)
        self.assertEqual(order["total"], 250)
        self.assertEqual(order["paid"], 250)
        with sto_crm.db() as conn:
            self.assertEqual(sto_crm.get_inventory(conn, part["id"])["quantity"], 2)

        payload["status"] = "cancelled"
        cancelled = sto_crm.update_order(order["id"], payload)
        self.assertEqual(cancelled["closed_at"], "")
        with sto_crm.db() as conn:
            self.assertEqual(sto_crm.get_inventory(conn, part["id"])["quantity"], 3)

    def test_order_allows_external_part_without_inventory_and_does_not_consume_stock(self):
        customer = self.create_customer("External Part Customer")
        vehicle = self.create_vehicle(customer["id"], "X404XP")
        stock_part = sto_crm.create_inventory({"sku": "STOCK", "name": "Stock part", "quantity": 2, "price": 50, "cost": 20})

        order = sto_crm.create_order(
            {
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "status": "closed",
                "priority": "normal",
                "items": [
                    service_item(100),
                    {"kind": "part", "inventory_id": stock_part["id"], "title": "Stock part", "quantity": 1, "unit_price": 50, "unit_cost": 20},
                    {"kind": "part", "title": "External ordered part", "quantity": 2, "unit_price": 75, "unit_cost": 45},
                ],
            }
        )

        self.assertEqual(order["parts_total"], 200)
        self.assertEqual(order["total"], 300)
        external_item = next(item for item in order["items"] if item["title"] == "External ordered part")
        self.assertIsNone(external_item["inventory_id"])
        with sto_crm.db() as conn:
            self.assertEqual(sto_crm.get_inventory(conn, stock_part["id"])["quantity"], 1)

    def test_external_part_requires_manual_title(self):
        customer = self.create_customer("External Part Validation")
        vehicle = self.create_vehicle(customer["id"], "X405XP")

        with self.assertRaisesRegex(ValueError, "наименование запчасти"):
            sto_crm.create_order(
                {
                    "customer_id": customer["id"],
                    "vehicle_id": vehicle["id"],
                    "status": "new",
                    "priority": "normal",
                    "items": [{"kind": "part", "quantity": 1, "unit_price": 10}],
                }
            )

    def test_closed_order_shortage_rolls_back_without_partial_order(self):
        customer = self.create_customer("Shortage Customer")
        vehicle = self.create_vehicle(customer["id"], "Q009QQ")
        part = sto_crm.create_inventory({"sku": "LOW", "name": "Low stock part", "quantity": 1, "price": 10, "cost": 5})

        with self.assertRaisesRegex(ValueError, "Недостаточно"):
            sto_crm.create_order(
                {
                    "customer_id": customer["id"],
                    "vehicle_id": vehicle["id"],
                    "status": "closed",
                    "priority": "normal",
                    "items": [
                        service_item(10),
                        {"kind": "part", "inventory_id": part["id"], "title": part["name"], "quantity": 2, "unit_price": 10, "unit_cost": 5},
                    ],
                }
            )

        with sto_crm.db() as conn:
            self.assertEqual(sto_crm.get_inventory(conn, part["id"])["quantity"], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM orders WHERE deleted_at IS NULL").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM order_items").fetchone()[0], 0)

    def test_entities_with_order_history_are_not_deleted(self):
        customer = self.create_customer("History Customer")
        vehicle = self.create_vehicle(customer["id"], "C003CC")
        part = sto_crm.create_inventory({"name": "History part", "quantity": 1, "price": 10})
        order = sto_crm.create_order(
            {
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "status": "closed",
                "priority": "normal",
                "items": [
                    service_item(10),
                    {"kind": "part", "inventory_id": part["id"], "title": part["name"], "quantity": 1, "unit_price": 10, "unit_cost": 1},
                ],
            }
        )

        self.assertTrue(order["id"])
        with self.assertRaisesRegex(ValueError, "заказ"):
            sto_crm.delete_customer(customer["id"])
        with self.assertRaisesRegex(ValueError, "заказ"):
            sto_crm.delete_vehicle(vehicle["id"])
        with self.assertRaisesRegex(ValueError, "заказ"):
            sto_crm.delete_inventory(part["id"])


    def test_closed_order_must_be_cancelled_before_delete_to_make_stock_return_explicit(self):
        customer = self.create_customer("Void Customer")
        vehicle = self.create_vehicle(customer["id"], "V000ID")
        part = sto_crm.create_inventory({"name": "Void part", "quantity": 2, "price": 10, "cost": 5})
        order = sto_crm.create_order(
            {
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "status": "closed",
                "priority": "normal",
                "items": [
                    service_item(10),
                    {"kind": "part", "inventory_id": part["id"], "title": part["name"], "quantity": 1, "unit_price": 10, "unit_cost": 5},
                ],
            }
        )
        with sto_crm.db() as conn:
            self.assertEqual(sto_crm.get_inventory(conn, part["id"])["quantity"], 1)

        with self.assertRaisesRegex(ValueError, "переведите в статус"):
            sto_crm.delete_order(order["id"])
        with sto_crm.db() as conn:
            self.assertEqual(sto_crm.get_inventory(conn, part["id"])["quantity"], 1)
            self.assertEqual(sto_crm.get_order(conn, order["id"])["status"], "closed")

        payload = {
            "customer_id": customer["id"],
            "vehicle_id": vehicle["id"],
            "status": "cancelled",
            "priority": "normal",
            "items": [
                service_item(10),
                {"kind": "part", "inventory_id": part["id"], "title": part["name"], "quantity": 1, "unit_price": 10, "unit_cost": 5},
            ],
        }
        cancelled = sto_crm.update_order(order["id"], payload)
        self.assertEqual(cancelled["status"], "cancelled")
        with sto_crm.db() as conn:
            self.assertEqual(sto_crm.get_inventory(conn, part["id"])["quantity"], 2)

        self.assertEqual(sto_crm.delete_order(order["id"]), {"deleted": True})
        with sto_crm.db() as conn:
            self.assertEqual(sto_crm.get_inventory(conn, part["id"])["quantity"], 2)

    def test_delete_missing_entities_returns_not_found(self):
        with self.assertRaises(KeyError):
            sto_crm.delete_customer(999)
        with self.assertRaises(KeyError):
            sto_crm.delete_vehicle(999)
        with self.assertRaises(KeyError):
            sto_crm.delete_inventory(999)

    def test_vehicle_with_order_history_cannot_change_owner(self):
        first = self.create_customer("Owner One")
        second = self.create_customer("Owner Two")
        vehicle = self.create_vehicle(first["id"], "O111OO")
        sto_crm.create_order(
            {
                "customer_id": first["id"],
                "vehicle_id": vehicle["id"],
                "status": "new",
                "priority": "normal",
                "items": [service_item(10)],
            }
        )

        with self.assertRaisesRegex(ValueError, "Нельзя сменить клиента"):
            sto_crm.update_vehicle(
                vehicle["id"],
                {
                    "customer_id": second["id"],
                    "make": vehicle["make"],
                    "model": vehicle["model"],
                    "year": vehicle["year"],
                    "plate": vehicle["plate"],
                    "vin": vehicle["vin"],
                    "mileage": vehicle["mileage"],
                    "notes": vehicle["notes"],
                },
            )

    def test_csv_export_escapes_formula_values(self):
        sto_crm.create_customer({"name": "=cmd|' /C calc'!A0", "phone": "+7999", "email": "", "source": "  =cmd|' /C calc'!A0", "notes": "-note"})
        _filename, content = sto_crm.csv_export("customers")
        self.assertIn("'=cmd|' /C calc'!A0", content)
        self.assertIn("'+7999", content)
        self.assertIn("'=cmd|' /C calc'!A0", content)  # clean_text collapses whitespace, csv_cell escapes leading =
        self.assertIn("'-note", content)

    def test_csv_export_is_not_limited_to_visible_page_size(self):
        stamp = sto_crm.now_iso()
        with sto_crm.db() as conn:
            conn.executemany(
                """
                INSERT INTO customers(name, phone, email, source, notes, created_at, updated_at)
                VALUES (?, '', '', '', '', ?, ?)
                """,
                [(f"Bulk Customer {index:04d}", stamp, stamp) for index in range(1005)],
            )

        _filename, content = sto_crm.csv_export("customers")
        self.assertEqual(len(content.strip().splitlines()), 1006)
        self.assertIn("Bulk Customer 1004", content)

    def test_cross_origin_json_mutation_is_rejected(self):
        server = sto_crm.CRMServer(("127.0.0.1", 0), sto_crm.CRMHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}/api/backup"
        request = urllib.request.Request(
            url,
            data=json.dumps({}).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json", "Origin": "http://example.com", "X-CSRF-Token": sto_crm.RUNTIME.csrf_token},
        )

        try:
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(request, timeout=5)
            self.assertEqual(error.exception.code, 403)
            error.exception.close()
        finally:
            server.shutdown()
            server.server_close()

    def test_http_headers_and_invalid_content_length(self):
        server = sto_crm.CRMServer(("127.0.0.1", 0), sto_crm.CRMHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"

        try:
            with urllib.request.urlopen(f"{base}/", timeout=5) as response:
                self.assertEqual(response.status, 200)
                self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])
                self.assertEqual(response.headers["X-Frame-Options"], "DENY")
                self.assertEqual(response.headers["Connection"], "close")

            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(f"{base}/api/export/catalog.csv", timeout=5)
            self.assertEqual(error.exception.code, 403)
            error.exception.close()

            export_request = urllib.request.Request(
                f"{base}/api/export/catalog.csv",
                headers={"X-CSRF-Token": sto_crm.RUNTIME.csrf_token},
            )
            with urllib.request.urlopen(export_request, timeout=5) as response:
                body = response.read()
                self.assertEqual(response.status, 200)
                self.assertTrue(body.startswith(codecs.BOM_UTF8))
                self.assertFalse(body.startswith(codecs.BOM_UTF8 + codecs.BOM_UTF8))
                self.assertIn("Toyota;Camry".encode("utf-8"), body)

            with urllib.request.urlopen(f"{base}/api/catalog", timeout=5) as response:
                catalog = json.loads(response.read().decode("utf-8"))
                self.assertGreaterEqual(catalog["stats"]["makes"], 250)
                self.assertIn("Toyota", catalog["makes"])
                self.assertIn("Camry", catalog["models"]["Toyota"])

            options_request = urllib.request.Request(f"{base}/api/health", method="OPTIONS")
            with urllib.request.urlopen(options_request, timeout=5) as response:
                self.assertEqual(response.status, 204)
                self.assertEqual(response.headers["Allow"], "GET, POST, PUT, DELETE, OPTIONS")
                self.assertEqual(response.headers["Connection"], "close")

            cross_origin_options = urllib.request.Request(
                f"{base}/api/health",
                method="OPTIONS",
                headers={"Origin": "http://example.com"},
            )
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(cross_origin_options, timeout=5)
            self.assertEqual(error.exception.code, 403)
            error.exception.close()

            with socket.create_connection(("127.0.0.1", server.server_port), timeout=5) as client:
                client.sendall(
                    (
                        "GET /api/bootstrap HTTP/1.1\r\n"
                        f"Host: evil.example:{server.server_port}\r\n"
                        "Connection: close\r\n"
                        "\r\n"
                    ).encode("ascii")
                )
                response = client.recv(2048).decode("utf-8", errors="replace")
            self.assertIn("403", response.splitlines()[0])

            with socket.create_connection(("127.0.0.1", server.server_port), timeout=5) as client:
                client.sendall(
                    (
                        "POST /api/backup HTTP/1.1\r\n"
                        f"Host: 127.0.0.1:{server.server_port}\r\n"
                        "Content-Type: application/json\r\n"
                        f"X-CSRF-Token: {sto_crm.RUNTIME.csrf_token}\r\n"
                        "Content-Length: nope\r\n"
                        "Connection: close\r\n"
                        "\r\n"
                        "{}"
                    ).encode("ascii")
                )
                response = client.recv(2048).decode("utf-8", errors="replace")
            self.assertIn("400", response.splitlines()[0])

            with socket.create_connection(("127.0.0.1", server.server_port), timeout=5) as client:
                client.sendall(
                    (
                        "POST /api/backup HTTP/1.1\r\n"
                        f"Host: 127.0.0.1:{server.server_port}\r\n"
                        f"Origin: http://127.0.0.1:{server.server_port + 1}\r\n"
                        "Content-Type: application/json\r\n"
                        f"X-CSRF-Token: {sto_crm.RUNTIME.csrf_token}\r\n"
                        "Content-Length: 2\r\n"
                        "Connection: close\r\n"
                        "\r\n"
                        "{}"
                    ).encode("ascii")
                )
                response = client.recv(2048).decode("utf-8", errors="replace")
            self.assertIn("403", response.splitlines()[0])

            with socket.create_connection(("127.0.0.1", server.server_port), timeout=5) as client:
                client.sendall(
                    (
                        "POST /api/backup HTTP/1.1\r\n"
                        f"Host: 127.0.0.1:{server.server_port}\r\n"
                        f"Origin: http://[::1]:{server.server_port}\r\n"
                        "Content-Type: application/json\r\n"
                        f"X-CSRF-Token: {sto_crm.RUNTIME.csrf_token}\r\n"
                        "Content-Length: 2\r\n"
                        "Connection: close\r\n"
                        "\r\n"
                        "{}"
                    ).encode("ascii")
                )
                response = client.recv(2048).decode("utf-8", errors="replace")
            self.assertNotIn("500", response.splitlines()[0])
        finally:
            server.shutdown()
            server.server_close()

    def test_filtered_bootstrap_keeps_full_form_lookups(self):
        customer = self.create_customer("Lookup Customer")
        vehicle = self.create_vehicle(customer["id"], "L777UP")
        part = sto_crm.create_inventory({"name": "Lookup part", "quantity": 5, "price": 10})
        sto_crm.create_order(
            {
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "status": "new",
                "priority": "normal",
                "complaint": "rare-search-token",
                "items": [
                    service_item(10),
                    {"kind": "part", "inventory_id": part["id"], "title": part["name"], "quantity": 1, "unit_price": 10, "unit_cost": 1},
                ],
            }
        )

        payload = sto_crm.bootstrap_payload("rare-search-token", "all")
        self.assertEqual(len(payload["orders"]), 1)
        self.assertEqual(payload["customers"], [])
        self.assertTrue(any(item["id"] == customer["id"] for item in payload["lookups"]["customers"]))
        self.assertTrue(any(item["id"] == vehicle["id"] for item in payload["lookups"]["vehicles"]))
        self.assertTrue(any(item["id"] == part["id"] for item in payload["lookups"]["inventory"]))

    def test_active_orders_sort_before_closed_urgent_orders(self):
        customer = self.create_customer("Sort Customer")
        vehicle = self.create_vehicle(customer["id"], "S001RT")
        active = sto_crm.create_order(
            {
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "status": "new",
                "priority": "normal",
                "items": [service_item(10)],
            }
        )
        closed = sto_crm.create_order(
            {
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "status": "closed",
                "priority": "urgent",
                "items": [service_item(10)],
            }
        )

        order_ids = [order["id"] for order in sto_crm.list_orders("", "all")]
        self.assertLess(order_ids.index(active["id"]), order_ids.index(closed["id"]))

    def test_totals_clamp_legacy_negative_values(self):
        totals = sto_crm.calculate_totals(
            {"discount": -100, "tax_rate": -20, "paid": -50},
            [service_item(100)],
        )
        self.assertEqual(totals["total"], 100)
        self.assertEqual(totals["paid"], 0)

    def test_margin_is_calculated_before_tax(self):
        totals = sto_crm.calculate_totals(
            {"discount": 10, "tax_rate": 20, "paid": 0},
            [{"kind": "service", "title": "Labor", "quantity": 1, "unit_price": 100, "unit_cost": 60}],
        )
        self.assertEqual(totals["subtotal"], 100)
        self.assertEqual(totals["tax"], 18)
        self.assertEqual(totals["total"], 108)
        self.assertEqual(totals["margin"], 30)
        self.assertEqual(totals["margin_percent"], 33.3)

    def test_number_parsers_accept_russian_spacing_and_commas(self):
        self.assertEqual(sto_crm.parse_float("1 500,50"), 1500.5)
        self.assertEqual(sto_crm.parse_float("1\u00a0500,50"), 1500.5)
        self.assertEqual(sto_crm.parse_int("12 345,9"), 12345)



    def test_number_parsers_reject_non_finite_values(self):
        self.assertEqual(sto_crm.parse_float("nan", 7.5), 7.5)
        self.assertEqual(sto_crm.parse_float("inf", 7.5), 7.5)
        self.assertEqual(sto_crm.parse_float("-inf", 7.5), 7.5)
        self.assertEqual(sto_crm.parse_int("nan", 42), 42)
        self.assertEqual(sto_crm.parse_int("inf", 42), 42)

    def test_appointments_reject_overlaps_on_create_and_update(self):
        customer = self.create_customer("Conflict Customer")
        vehicle = self.create_vehicle(customer["id"], "K010KK")
        first = sto_crm.create_appointment(
            {
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "scheduled_at": "2099-01-01T10:00",
                "duration_minutes": 60,
                "status": "scheduled",
            }
        )
        second = sto_crm.create_appointment(
            {
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "scheduled_at": "2099-01-01T11:30",
                "duration_minutes": 30,
                "status": "scheduled",
            }
        )

        with self.assertRaisesRegex(ValueError, "уже есть запись"):
            sto_crm.create_appointment(
                {
                    "customer_id": customer["id"],
                    "vehicle_id": vehicle["id"],
                    "scheduled_at": "2099-01-01T10:30",
                    "duration_minutes": 30,
                    "status": "confirmed",
                }
            )

        with self.assertRaisesRegex(ValueError, "уже есть запись"):
            sto_crm.update_appointment(
                second["id"],
                {
                    "customer_id": customer["id"],
                    "vehicle_id": vehicle["id"],
                    "scheduled_at": "2099-01-01T10:45",
                    "duration_minutes": 30,
                    "status": "scheduled",
                },
            )

        unchanged = sto_crm.update_appointment(
            first["id"],
            {
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "scheduled_at": "2099-01-01T10:00",
                "duration_minutes": 60,
                "status": "confirmed",
            },
        )
        self.assertEqual(unchanged["status"], "confirmed")

    def test_inactive_appointments_do_not_block_customer_or_vehicle_deletion(self):
        customer = self.create_customer("Inactive Appointment Customer")
        vehicle = self.create_vehicle(customer["id"], "N404NO")
        sto_crm.create_appointment(
            {
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "scheduled_at": "2099-01-01T10:00",
                "status": "done",
            }
        )

        self.assertEqual(sto_crm.delete_vehicle(vehicle["id"]), {"deleted": True})
        self.assertTrue(any(item["status"] == "done" for item in sto_crm.list_appointments("", "all", None)))

        second_vehicle = self.create_vehicle(customer["id"], "N405NO")
        sto_crm.create_appointment(
            {
                "customer_id": customer["id"],
                "vehicle_id": second_vehicle["id"],
                "scheduled_at": "2099-01-02T10:00",
                "status": "cancelled",
            }
        )

        self.assertEqual(sto_crm.delete_customer(customer["id"]), {"deleted": True})
        self.assertTrue(any(item["status"] == "cancelled" for item in sto_crm.list_appointments("", "all", None)))

    def test_active_appointment_blocks_customer_and_vehicle_deletion(self):
        customer = self.create_customer("Active Appointment Customer")
        vehicle = self.create_vehicle(customer["id"], "A404AA")
        sto_crm.create_appointment(
            {
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "scheduled_at": "2099-01-01T10:00",
                "status": "scheduled",
            }
        )

        with self.assertRaisesRegex(ValueError, "активные записи"):
            sto_crm.delete_vehicle(vehicle["id"])
        with self.assertRaisesRegex(ValueError, "активные записи"):
            sto_crm.delete_customer(customer["id"])



    def test_invalid_enums_are_rejected_instead_of_silently_defaulted(self):
        customer = self.create_customer("Strict Enum Customer")
        vehicle = self.create_vehicle(customer["id"], "E001NU")

        with self.assertRaisesRegex(ValueError, "канал"):
            sto_crm.create_customer({"name": "Bad Channel", "preferred_channel": "pager"})
        with self.assertRaisesRegex(ValueError, "приоритет"):
            sto_crm.create_order({"customer_id": customer["id"], "vehicle_id": vehicle["id"], "status": "new", "priority": "panic", "items": [service_item(10)]})
        with self.assertRaisesRegex(ValueError, "статус записи"):
            sto_crm.create_appointment({"customer_id": customer["id"], "vehicle_id": vehicle["id"], "scheduled_at": "2099-03-01T10:00", "status": "maybe"})
        with self.assertRaisesRegex(ValueError, "тип позиции"):
            sto_crm.create_order({"customer_id": customer["id"], "vehicle_id": vehicle["id"], "status": "new", "priority": "normal", "items": [{"kind": "fee", "title": "Bad", "quantity": 1}]})
        with self.assertRaisesRegex(ValueError, "состояние"):
            sto_crm.create_inspection({"customer_id": customer["id"], "vehicle_id": vehicle["id"], "status": "draft", "items": [{"title": "Bad", "condition_status": "broken"}]})

    def test_malformed_items_are_rejected_as_validation_errors(self):
        customer = self.create_customer("Malformed Items")
        vehicle = self.create_vehicle(customer["id"], "M001AL")
        with self.assertRaisesRegex(ValueError, "Позиция заказ-наряда"):
            sto_crm.create_order({"customer_id": customer["id"], "vehicle_id": vehicle["id"], "status": "new", "priority": "normal", "items": [123]})
        with self.assertRaisesRegex(ValueError, "Пункт осмотра"):
            sto_crm.create_inspection({"customer_id": customer["id"], "vehicle_id": vehicle["id"], "status": "draft", "items": ["bad"]})

    def test_user_numeric_fields_reject_garbage_instead_of_defaulting(self):
        customer = self.create_customer("Strict Numbers")
        vehicle = self.create_vehicle(customer["id"], "N001UM")
        with self.assertRaisesRegex(ValueError, "скидка"):
            sto_crm.create_order({"customer_id": customer["id"], "vehicle_id": vehicle["id"], "status": "new", "priority": "normal", "discount": "abc", "items": [service_item(10)]})
        with self.assertRaisesRegex(ValueError, "длительность"):
            sto_crm.create_appointment({"customer_id": customer["id"], "vehicle_id": vehicle["id"], "scheduled_at": "2099-03-01T10:00", "duration_minutes": "abc", "status": "scheduled"})
        with self.assertRaisesRegex(ValueError, "остаток"):
            sto_crm.create_inventory({"name": "Bad number", "quantity": "not-a-number"})

    def test_order_number_uses_max_daily_suffix_not_last_id(self):
        today_prefix = sto_crm.datetime.now().strftime("СТО-%Y%m%d")
        stamp = sto_crm.now_iso()
        with sto_crm.db() as conn:
            conn.execute(
                """
                INSERT INTO customers(name, phone, email, source, notes, created_at, updated_at)
                VALUES ('Number Customer', '', '', '', '', ?, ?)
                """,
                (stamp, stamp),
            )
            customer_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
            conn.execute(
                """
                INSERT INTO orders(number, customer_id, status, priority, created_at, updated_at)
                VALUES (?, ?, 'new', 'normal', ?, ?)
                """,
                (f"{today_prefix}-099", customer_id, stamp, stamp),
            )
            conn.execute(
                """
                INSERT INTO orders(number, customer_id, status, priority, created_at, updated_at)
                VALUES (?, ?, 'new', 'normal', ?, ?)
                """,
                (f"{today_prefix}-005", customer_id, stamp, stamp),
            )
            number = sto_crm.generate_order_number(conn)
        self.assertEqual(number, f"{today_prefix}-100")

    def test_closed_order_identity_and_stock_are_protected(self):
        first = self.create_customer("Closed First")
        second = self.create_customer("Closed Second")
        vehicle = self.create_vehicle(first["id"], "C101LO")
        other_vehicle = self.create_vehicle(second["id"], "C102LO")
        part = sto_crm.create_inventory({"sku": "LOCK", "name": "Locked part", "quantity": 5, "price": 10, "cost": 5})
        payload = {
            "customer_id": first["id"],
            "vehicle_id": vehicle["id"],
            "status": "closed",
            "priority": "normal",
            "items": [service_item(10), {"kind": "part", "inventory_id": part["id"], "title": part["name"], "quantity": 1, "unit_price": 10, "unit_cost": 5}],
        }
        order = sto_crm.create_order(payload)

        changed_owner = {**payload, "customer_id": second["id"], "vehicle_id": other_vehicle["id"]}
        with self.assertRaisesRegex(ValueError, "перепривязать"):
            sto_crm.update_order(order["id"], changed_owner)

        changed_qty = {**payload, "items": [service_item(10), {"kind": "part", "inventory_id": part["id"], "title": part["name"], "quantity": 2, "unit_price": 10, "unit_cost": 5}]}
        with self.assertRaisesRegex(ValueError, "Финансовые данные"):
            sto_crm.update_order(order["id"], changed_qty)

        changed_price = {**payload, "items": [service_item(999), {"kind": "part", "inventory_id": part["id"], "title": part["name"], "quantity": 1, "unit_price": 99, "unit_cost": 5}]}
        with self.assertRaisesRegex(ValueError, "Финансовые данные"):
            sto_crm.update_order(order["id"], changed_price)
        reopened_payload = {**payload, "status": "in_progress", "items": payload["items"]}
        with self.assertRaisesRegex(ValueError, "оставить закрытым или отменить"):
            sto_crm.update_order(order["id"], reopened_payload)

        with sto_crm.db() as conn:
            unchanged = sto_crm.get_order(conn, order["id"])
            self.assertEqual(unchanged["status"], "closed")
            self.assertEqual(sto_crm.get_inventory(conn, part["id"])["quantity"], 4)
        self.assertEqual(unchanged["total"], order["total"])

        with self.assertRaisesRegex(ValueError, "закрытых заказах"):
            sto_crm.update_inventory(part["id"], {"sku": "LOCK", "name": "Locked part", "quantity": 20, "price": 10, "cost": 5})

        allowed = sto_crm.update_inventory(part["id"], {"sku": "LOCK-NEW", "name": "Locked part renamed", "quantity": 4, "price": 12, "cost": 6})
        self.assertEqual(allowed["sku"], "LOCK-NEW")
        self.assertEqual(allowed["quantity"], 4)

        cancelled_payload = {**payload, "status": "cancelled", "items": payload["items"]}
        sto_crm.update_order(order["id"], cancelled_payload)
        adjusted = sto_crm.update_inventory(part["id"], {"sku": "LOCK-NEW", "name": "Locked part renamed", "quantity": 20, "price": 12, "cost": 6})
        self.assertEqual(adjusted["quantity"], 20)

    def test_http_csrf_token_is_required_and_bootstrap_exposes_token(self):
        server = sto_crm.CRMServer(("127.0.0.1", 0), sto_crm.CRMHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            cross_origin_bootstrap = urllib.request.Request(
                f"{base}/api/bootstrap",
                headers={"Origin": "http://example.com"},
            )
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(cross_origin_bootstrap, timeout=5)
            self.assertEqual(error.exception.code, 403)
            error.exception.close()

            with urllib.request.urlopen(f"{base}/api/bootstrap", timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(payload["app"]["csrf_token"], sto_crm.RUNTIME.csrf_token)
            self.assertEqual(payload["app"]["db_path"], sto_crm.RUNTIME.db_path.name)
            self.assertEqual(payload["app"]["db_directory"], sto_crm.display_path(sto_crm.RUNTIME.db_path.parent))
            self.assertNotIn(str(sto_crm.RUNTIME.db_path.parent), payload["app"]["db_directory"])

            request = urllib.request.Request(
                f"{base}/api/backup",
                data=json.dumps({}).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(request, timeout=5)
            self.assertEqual(error.exception.code, 403)
            error.exception.close()

            request = urllib.request.Request(
                f"{base}/api/customers",
                data=json.dumps({"name": "HTTP Customer"}).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json", "X-CSRF-Token": sto_crm.RUNTIME.csrf_token},
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                created = json.loads(response.read().decode("utf-8"))
            self.assertEqual(response.status, 201)
            self.assertEqual(created["name"], "HTTP Customer")
        finally:
            server.shutdown()
            server.server_close()


    def test_sensitive_query_tokens_are_redacted_from_logs(self):
        message = 'GET /print/order/1?token=super-secret&csrf_token=other HTTP/1.1'
        redacted = sto_crm.redact_sensitive_query(message)
        self.assertNotIn("super-secret", redacted)
        self.assertNotIn("other", redacted)
        self.assertIn("token=***", redacted)
        self.assertIn("csrf_token=***", redacted)

    def test_create_server_binds_without_separate_port_probe(self):
        server = sto_crm.create_server(0)
        try:
            self.assertGreater(server.server_port, 0)
            self.assertEqual(server.server_address[0], "127.0.0.1")
        finally:
            server.server_close()

    def test_host_cli_argument_accepts_only_loopback_addresses(self):
        args = sto_crm.parse_args(["--host", "127.0.0.1", "--port", "0", "--no-browser"])
        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.port, 0)
        self.assertEqual(sto_crm.parse_args(["--host", "localhost"]).host, "127.0.0.1")
        self.assertEqual(sto_crm.parse_args(["--host", "::1"]).host, "::1")
        self.assertIs(sto_crm.server_class_for_host("127.0.0.1"), sto_crm.CRMServer)
        self.assertIs(sto_crm.server_class_for_host("::1"), sto_crm.CRMServerV6)
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                sto_crm.parse_args(["--host", "0.0.0.0"])
        for port in ("-1", "65536"):
            with self.subTest(port=port):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        sto_crm.parse_args(["--port", port, "--no-browser"])

    def test_unique_vehicle_vin_plate_and_inventory_sku_are_enforced(self):
        customer = self.create_customer("Unique Customer")
        vehicle = sto_crm.create_vehicle(
            {
                "customer_id": customer["id"],
                "make": "Toyota",
                "model": "Camry",
                "plate": "U001NI",
                "vin": "JTDKN3DU0A0000001",
            }
        )
        with self.assertRaisesRegex(ValueError, "VIN"):
            sto_crm.create_vehicle({"customer_id": customer["id"], "make": "Lexus", "plate": "U002NI", "vin": vehicle["vin"]})
        with self.assertRaisesRegex(ValueError, "госномером"):
            sto_crm.create_vehicle({"customer_id": customer["id"], "make": "Lexus", "plate": vehicle["plate"], "vin": "JTDKN3DU0A0000002"})
        first_part = sto_crm.create_inventory({"sku": "UNIQ", "name": "First unique", "quantity": 1})
        self.assertEqual(first_part["sku"], "UNIQ")
        with self.assertRaisesRegex(ValueError, "артикулом"):
            sto_crm.create_inventory({"sku": "uniq", "name": "Second unique", "quantity": 1})

    def test_legacy_duplicate_values_are_migrated_before_unique_indexes(self):
        current_runtime = sto_crm.RUNTIME
        legacy_db = Path(self.tempdir.name) / "legacy-duplicates.sqlite3"
        conn = sqlite3.connect(legacy_db)
        try:
            conn.execute(
                """
                CREATE TABLE inventory(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sku TEXT NOT NULL DEFAULT '',
                    name TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    deleted_at TEXT
                )
                """
            )
            conn.executemany(
                "INSERT INTO inventory(sku, name, deleted_at) VALUES (?, ?, NULL)",
                [("DUP", "Duplicate one"), ("dup", "Duplicate two")],
            )
            conn.commit()
        finally:
            conn.close()
        sto_crm.RUNTIME = sto_crm.Runtime(legacy_db, time.time(), "legacy-token")
        try:
            sto_crm.init_db()
            migrated = sqlite3.connect(legacy_db)
            migrated.create_function("CASEFOLD", 1, lambda value: str(value or "").casefold(), deterministic=True)
            try:
                rows = migrated.execute("SELECT sku, notes FROM inventory ORDER BY id").fetchall()
                indexes = {row[1] for row in migrated.execute("PRAGMA index_list(inventory)").fetchall()}
                duplicates = migrated.execute(
                    """
                    SELECT COUNT(*)
                    FROM inventory
                    WHERE deleted_at IS NULL AND sku <> ''
                    GROUP BY CASEFOLD(sku)
                    HAVING COUNT(*) > 1
                    """
                ).fetchall()
            finally:
                migrated.close()
            self.assertEqual(rows[0][0], "DUP")
            self.assertEqual(rows[1][0], "")
            self.assertIn("Системная миграция", rows[1][1])
            self.assertIn("ux_inventory_sku_active", indexes)
            self.assertEqual(duplicates, [])
        finally:
            sto_crm.RUNTIME = current_runtime

    def test_backup_creates_readable_sqlite_copy(self):
        customer = self.create_customer("Backup Customer")
        result = sto_crm.create_backup()
        backup_path = Path(result["path"])
        self.assertTrue(backup_path.exists())
        self.assertGreater(result["size"], 0)
        self.assertEqual(backup_path.parent.name, "backups")
        conn = sqlite3.connect(backup_path)
        try:
            row = conn.execute("SELECT name FROM customers WHERE id=?", (customer["id"],)).fetchone()
        finally:
            conn.close()
        self.assertEqual(row[0], "Backup Customer")

    def test_order_search_includes_customer_phone_email_and_vehicle_vin(self):
        customer = sto_crm.create_customer({"name": "Phone Search", "phone": "+7 999 123-45-67", "email": "phone-search@example.ru"})
        vehicle = sto_crm.create_vehicle({"customer_id": customer["id"], "make": "Toyota", "model": "Camry", "vin": "JTDKN3DU0A0000999"})
        order = sto_crm.create_order({"customer_id": customer["id"], "vehicle_id": vehicle["id"], "status": "new", "priority": "normal", "items": [service_item(10)]})
        self.assertTrue(any(item["id"] == order["id"] for item in sto_crm.list_orders("123-45-67", "all")))
        self.assertTrue(any(item["id"] == order["id"] for item in sto_crm.list_orders("phone-search@example", "all")))
        self.assertTrue(any(item["id"] == order["id"] for item in sto_crm.list_orders("0000999", "all")))

    def test_invalid_bootstrap_status_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "статус"):
            sto_crm.bootstrap_payload("", "bad-status")

    def test_zero_revenue_customers_do_not_pollute_vip_segment(self):
        customer = self.create_customer("Zero Revenue Customer")
        vehicle = self.create_vehicle(customer["id"], "Z000RO")
        for _ in range(2):
            sto_crm.create_order(
                {
                    "customer_id": customer["id"],
                    "vehicle_id": vehicle["id"],
                    "status": "new",
                    "priority": "normal",
                    "items": [{"kind": "service", "title": "Warranty check", "quantity": 1, "unit_price": 0}],
                }
            )

        reports = sto_crm.bootstrap_payload()["reports"]
        self.assertFalse(any(item["customer_id"] == customer["id"] for item in reports["vip_customers"]))

    def test_crud_writes_persist_after_reopening_connection(self):
        customer = sto_crm.create_customer({"name": "Persistent Customer", "phone": "+7000"})
        vehicle = sto_crm.create_vehicle({"customer_id": customer["id"], "make": "Toyota", "model": "Camry"})
        part = sto_crm.create_inventory({"name": "Persistent Part", "quantity": 2, "price": 10})
        order = sto_crm.create_order(
            {
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "status": "new",
                "priority": "normal",
                "items": [service_item(10), {"kind": "part", "inventory_id": part["id"], "quantity": 1}],
            }
        )

        conn = sto_crm.connect()
        try:
            self.assertEqual(conn.execute("SELECT name FROM customers WHERE id=?", (customer["id"],)).fetchone()["name"], "Persistent Customer")
            self.assertEqual(conn.execute("SELECT make FROM vehicles WHERE id=?", (vehicle["id"],)).fetchone()["make"], "Toyota")
            self.assertEqual(conn.execute("SELECT name FROM inventory WHERE id=?", (part["id"],)).fetchone()["name"], "Persistent Part")
            self.assertEqual(conn.execute("SELECT number FROM orders WHERE id=?", (order["id"],)).fetchone()["number"], order["number"])
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM order_items WHERE order_id=?", (order["id"],)).fetchone()[0], 2)
        finally:
            conn.close()

    def test_reports_expose_executive_pipeline_workload_and_procurement(self):
        customer = self.create_customer("Executive Customer")
        vehicle = self.create_vehicle(customer["id"], "E111EE")
        part = sto_crm.create_inventory(
            {"sku": "LOW-EXEC", "name": "Low executive part", "quantity": 0, "min_quantity": 2, "price": 100, "cost": 60}
        )
        order = sto_crm.create_order(
            {
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "status": "in_progress",
                "priority": "urgent",
                "mechanic": "Мастер А",
                "promised_at": "2000-01-01T09:00",
                "items": [service_item(250)],
            }
        )
        appointment = sto_crm.create_appointment(
            {
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "scheduled_at": (sto_crm.datetime.now() + sto_crm.timedelta(days=2)).replace(hour=9, minute=0, second=0, microsecond=0).isoformat(timespec="minutes"),
                "status": "confirmed",
            }
        )

        reports = sto_crm.bootstrap_payload()["reports"]
        self.assertGreaterEqual(reports["business_health_score"], 0)
        self.assertIn(reports["business_health_label"], {"Отлично", "Контроль", "Риски"})
        self.assertGreaterEqual(reports["pipeline_value"], order["total"])
        self.assertTrue(any(item["id"] == order["id"] for item in reports["overdue_orders"]))
        self.assertTrue(any(column["status"] == "in_progress" and column["count"] >= 1 for column in reports["pipeline_by_status"]))
        self.assertTrue(any(item["name"] == "Мастер А" and item["overdue_count"] >= 1 for item in reports["workload_by_responsible"]))
        self.assertTrue(any(item["id"] == part["id"] and item["reorder_quantity"] >= 2 for item in reports["procurement_plan"]))
        self.assertTrue(any(day["appointments"] and day["appointments"][0]["id"] == appointment["id"] for day in reports["appointment_load_7_days"]))
        self.assertGreaterEqual(reports["action_plan_total"], 2)
        self.assertTrue(any(item["type"] == "overdue_order" and item["record_id"] == order["id"] for item in reports["action_plan"]))
        self.assertTrue(any(item["type"] == "procurement" and item["record_id"] == part["id"] for item in reports["action_plan"]))
        self.assertTrue(all("priority_label" in item and "route" in item and "cta" in item for item in reports["action_plan"]))

    def test_reports_include_orders_beyond_lookup_limit(self):
        old_lookup_limit = sto_crm.LOOKUP_LIMIT
        sto_crm.LOOKUP_LIMIT = 3
        stamp = sto_crm.now_iso()
        try:
            with sto_crm.db() as conn:
                conn.execute(
                    """
                    INSERT INTO customers(name, phone, email, source, notes, created_at, updated_at)
                    VALUES ('Report Customer', '', '', '', '', ?, ?)
                    """,
                    (stamp, stamp),
                )
                customer_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
                rows = [
                    (
                        f"BULK-{index:05d}",
                        customer_id,
                        "closed",
                        100,
                        stamp,
                        stamp,
                        stamp,
                    )
                    for index in range(sto_crm.LOOKUP_LIMIT + 2)
                ]
                conn.executemany(
                    """
                    INSERT INTO orders(number, customer_id, status, paid, closed_at, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
                cur = conn.execute("SELECT id FROM orders ORDER BY id")
                order_ids = [row["id"] for row in cur.fetchall()]
                conn.executemany(
                    """
                    INSERT INTO order_items(order_id, kind, title, approval_status, quantity, unit_price, unit_cost, created_at)
                    VALUES (?, 'service', 'Bulk service', 'approved', 1, 100, 0, ?)
                    """,
                    [(order_id, stamp) for order_id in order_ids],
                )

            reports = sto_crm.bootstrap_payload()["reports"]
            self.assertEqual(reports["revenue_month"], (sto_crm.LOOKUP_LIMIT + 2) * 100)
            self.assertEqual(reports["status_counts"]["closed"], sto_crm.LOOKUP_LIMIT + 2)
        finally:
            sto_crm.LOOKUP_LIMIT = old_lookup_limit

    def test_invalid_datetime_fields_are_rejected(self):
        customer = self.create_customer("Date Customer")
        vehicle = self.create_vehicle(customer["id"], "D777TE")

        with self.assertRaisesRegex(ValueError, "Некорректная дата"):
            sto_crm.create_appointment(
                {
                    "customer_id": customer["id"],
                    "vehicle_id": vehicle["id"],
                    "scheduled_at": "2026-05-06T10:00 мусор",
                    "status": "scheduled",
                }
            )

        with self.assertRaisesRegex(ValueError, "Некорректная дата"):
            sto_crm.create_order(
                {
                    "customer_id": customer["id"],
                    "vehicle_id": vehicle["id"],
                    "status": "new",
                    "priority": "normal",
                    "promised_at": "2026-05-06T10:00 garbage",
                    "items": [service_item(10)],
                }
            )

    def test_vehicle_year_and_vin_are_validated(self):
        customer = self.create_customer("Vehicle Quality")
        with self.assertRaisesRegex(ValueError, "год"):
            sto_crm.create_vehicle(
                {
                    "customer_id": customer["id"],
                    "make": "Toyota",
                    "model": "Camry",
                    "year": 3000,
                    "plate": "",
                    "vin": "",
                }
            )
        with self.assertRaisesRegex(ValueError, "VIN"):
            sto_crm.create_vehicle(
                {
                    "customer_id": customer["id"],
                    "make": "Toyota",
                    "model": "Camry",
                    "year": 2020,
                    "plate": "",
                    "vin": "BADVINIOQ1234567",
                }
            )

    def test_print_route_rejects_cross_origin_even_with_valid_token(self):
        customer = self.create_customer("Print Security")
        vehicle = self.create_vehicle(customer["id"], "P001RT")
        order = sto_crm.create_order(
            {
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "status": "new",
                "priority": "normal",
                "items": [service_item(10)],
            }
        )
        server = sto_crm.CRMServer(("127.0.0.1", 0), sto_crm.CRMHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/print/order/{order['id']}?token={sto_crm.RUNTIME.csrf_token}",
            headers={"Origin": "http://example.com"},
        )
        try:
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(request, timeout=5)
            self.assertEqual(error.exception.code, 403)
            error.exception.close()
        finally:
            server.shutdown()
            server.server_close()

    def test_empty_json_body_is_rejected_before_business_validation(self):
        server = sto_crm.CRMServer(("127.0.0.1", 0), sto_crm.CRMHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/api/customers",
            data=b"",
            method="POST",
            headers={"Content-Type": "application/json", "X-CSRF-Token": sto_crm.RUNTIME.csrf_token},
        )
        try:
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(request, timeout=5)
            self.assertEqual(error.exception.code, 400)
            body = error.exception.read().decode("utf-8")
            self.assertIn("Пустое тело", body)
            self.assertNotIn("Укажите имя", body)
            error.exception.close()
        finally:
            server.shutdown()
            server.server_close()

    def test_integer_fields_reject_fractional_values(self):
        customer = self.create_customer("Fractional Integers")
        vehicle = self.create_vehicle(customer["id"], "F001RA")
        with self.assertRaisesRegex(ValueError, "целое"):
            sto_crm.parse_int_field("10.5", "длительность")
        with self.assertRaisesRegex(ValueError, "целое"):
            sto_crm.create_appointment(
                {
                    "customer_id": customer["id"],
                    "vehicle_id": vehicle["id"],
                    "scheduled_at": "2099-04-01T10:00",
                    "duration_minutes": "30.5",
                    "status": "scheduled",
                }
            )

    def test_vehicle_owner_change_ignores_inactive_appointments_but_blocks_active(self):
        first = self.create_customer("Transfer First")
        second = self.create_customer("Transfer Second")
        vehicle = self.create_vehicle(first["id"], "T001RF")
        sto_crm.create_appointment(
            {
                "customer_id": first["id"],
                "vehicle_id": vehicle["id"],
                "scheduled_at": "2099-05-01T10:00",
                "status": "done",
            }
        )
        transferred = sto_crm.update_vehicle(
            vehicle["id"],
            {
                "customer_id": second["id"],
                "make": vehicle["make"],
                "model": vehicle["model"],
                "year": vehicle["year"],
                "plate": vehicle["plate"],
                "vin": vehicle["vin"],
                "mileage": vehicle["mileage"],
                "notes": vehicle["notes"],
            },
        )
        self.assertEqual(transferred["customer_id"], second["id"])
        sto_crm.create_appointment(
            {
                "customer_id": second["id"],
                "vehicle_id": vehicle["id"],
                "scheduled_at": "2099-05-02T10:00",
                "status": "scheduled",
            }
        )
        with self.assertRaisesRegex(ValueError, "активными записями"):
            sto_crm.update_vehicle(
                vehicle["id"],
                {
                    "customer_id": first["id"],
                    "make": vehicle["make"],
                    "model": vehicle["model"],
                    "year": vehicle["year"],
                    "plate": vehicle["plate"],
                    "vin": vehicle["vin"],
                    "mileage": vehicle["mileage"],
                    "notes": vehicle["notes"],
                },
            )

    def test_delete_order_with_linked_inspection_is_blocked(self):
        customer = self.create_customer("Inspection Link")
        vehicle = self.create_vehicle(customer["id"], "I001LK")
        order = sto_crm.create_order(
            {
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "status": "new",
                "priority": "normal",
                "items": [service_item(10)],
            }
        )
        sto_crm.create_inspection(
            {
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "order_id": order["id"],
                "status": "draft",
                "items": [{"area": "Test", "title": "Linked", "condition_status": "ok"}],
            }
        )
        with self.assertRaisesRegex(ValueError, "осмотры"):
            sto_crm.delete_order(order["id"])
        with sto_crm.db() as conn:
            self.assertEqual(sto_crm.get_order(conn, order["id"])["id"], order["id"])

    def test_inventory_quantity_can_change_when_closed_history_is_not_billable(self):
        customer = self.create_customer("Non Billable Inventory")
        vehicle = self.create_vehicle(customer["id"], "B001NB")
        part = sto_crm.create_inventory({"sku": "NOBILL", "name": "Not billable", "quantity": 5, "price": 20, "cost": 10})
        order = sto_crm.create_order(
            {
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "status": "closed",
                "priority": "normal",
                "items": [
                    service_item(10),
                    {"kind": "part", "inventory_id": part["id"], "title": part["name"], "approval_status": "deferred", "quantity": 1, "unit_price": 20, "unit_cost": 10},
                ],
            }
        )
        self.assertEqual(order["parts_total"], 0)
        updated = sto_crm.update_inventory(part["id"], {"sku": "NOBILL", "name": "Not billable", "quantity": 7, "price": 20, "cost": 10})
        self.assertEqual(updated["quantity"], 7)

    def test_list_status_filters_are_strict(self):
        with self.assertRaisesRegex(ValueError, "статус"):
            sto_crm.list_appointments("", "bad-status")
        with self.assertRaisesRegex(ValueError, "статус"):
            sto_crm.list_inspections("", "bad-status")

    def test_home_page_has_professional_accessibility_and_dirty_state_hooks(self):
        html = sto_crm.INDEX_HTML
        self.assertIn('function labeledField(', html)
        self.assertIn('function tableHead(', html)
        self.assertIn('function inputField(', html)
        self.assertIn('function selectField(', html)
        self.assertIn('function textareaField(', html)
        self.assertIn('scope="col"', html)
        self.assertIn('aria-label="Таблица заказ-нарядов"', html)
        self.assertNotIn('<div class="field"><label>', html)
        self.assertIn('inputField("customer", "name"', html)
        self.assertIn('selectField("order", "customer_id"', html)
        self.assertIn('selectField("inspection", "customer_id"', html)
        self.assertIn('modalDirty', html)
        self.assertIn('pipelineBoard(r.pipeline_by_status || [])', html)
        self.assertIn('appointmentTimeline(r.appointment_load_7_days || [])', html)
        self.assertIn('procurementList(r.procurement_plan || [])', html)
        self.assertIn('workloadList(r.workload_by_responsible || [])', html)
        self.assertIn('actionPlanList(r.action_plan || [])', html)
        self.assertIn('action-center', html)
        self.assertIn('data-route-target=', html)
        self.assertIn('findAppointmentById(id)', html)
        self.assertIn('findInspectionById(id)', html)
        self.assertIn('findCustomerById(id)', html)
        self.assertIn('findVehicleById(id)', html)
        self.assertIn('findInventoryById(id)', html)
        self.assertIn('healthMetric(r)', html)
        self.assertIn('confirm("Закрыть окно без сохранения изменений?")', html)
        self.assertIn('shouldKeepModalForEscape', html)
        self.assertIn('modalSize = allowedSizes.has(size) ? size : ""', html)
        self.assertIn('setSaveButtonsBusy', html)
        self.assertIn('Вне склада / заказная', html)
        self.assertIn('Источник запчасти', html)
        self.assertIn('discountPreview', html)
        self.assertIn('aria-label="Удалить позицию заказ-наряда"', html)
        self.assertIn('aria-label="Удалить пункт осмотра"', html)
        self.assertIn('id="appStatus"', html)
        self.assertIn('<a class="skip-link" href="#content">К основному содержанию</a>', html)
        self.assertIn('function contextStripHtml()', html)
        self.assertIn('class="context-strip"', html)
        self.assertIn('function updateNavigationBadges()', html)
        self.assertIn('data-nav-badge="dashboard"', html)
        self.assertIn('data-nav-badge="updates"', html)
        self.assertIn('lastLoadedAt', html)
        self.assertIn('content.innerHTML = `${offlineBannerHtml()}${errorBannerHtml()}${contextStripHtml()}${renderers[state.route]()}`;', html)
        self.assertIn('function announce(message', html)
        self.assertIn('function errorBannerHtml()', html)
        self.assertIn('data-action="dismiss-error"', html)
        self.assertIn('scroll-hint-sr', html)
        self.assertIn('aria-describedby', html)
        self.assertIn('function classToken(', html)
        self.assertIn('aria-label="Тип позиции"', html)
        self.assertIn('aria-label="Зона осмотра"', html)
        self.assertIn('aria-label="Фильтр по марке или модели"', html)
        self.assertIn('role="group" aria-label="Фильтр заказов по статусу"', html)
        self.assertIn('aria-pressed="${state.status === status ? "true" : "false"}"', html)
        self.assertIn('state.data.app.csrf_token', html)
        self.assertIn('function exportUrl(entity)', html)
        self.assertIn('async function downloadCsv(entity)', html)
        self.assertIn('data-action="export-csv"', html)
        self.assertIn('<button class="btn ghost" type="button" data-action="export-csv"', html)
        self.assertNotIn('<a class="btn ghost" href="#" data-action="export-csv"', html)
        self.assertNotIn('?token=${token}', html)
        self.assertIn('openPrintOrder(id)', html)
        self.assertIn('data-action="duplicate-order"', html)
        self.assertIn('Прокрутите вправо', html)
        self.assertNotIn('overflow-x: hidden;', html)
        self.assertNotIn('id="content" aria-live="polite"', html)

    def test_home_page_wires_inline_form_errors_to_save_failures(self):
        html = sto_crm.INDEX_HTML
        self.assertIn('function applyFormError(error)', html)
        self.assertIn('function clearFormError(target)', html)
        self.assertIn('applyFormError(error);', html)
        self.assertIn('target.setAttribute("aria-invalid", "true")', html)
        self.assertIn('field-error', html)
        self.assertIn('clearAllFormErrors(form)', html)
        self.assertEqual(html.count('applyFormError('), 2)

    def test_github_update_helpers_select_and_compare_release_assets(self):
        release = {
            "assets": [
                {"name": "checksums.sha256", "browser_download_url": "https://github.com/owner/repo/releases/download/v1.20.0/checksums.sha256", "size": 100},
                {"name": "latest.json", "browser_download_url": "https://github.com/owner/repo/releases/download/v1.20.0/latest.json", "size": 321},
                {"name": "STO_CRM.exe", "browser_download_url": "https://github.com/owner/repo/releases/download/v1.20.0/STO_CRM.exe", "size": 123},
            ]
        }
        self.assertTrue(sto_crm.is_newer_version("v1.18.0", "1.17.0"))
        self.assertFalse(sto_crm.is_newer_version("1.17.0", "1.17.0"))
        self.assertEqual(sto_crm.select_release_asset(release)["name"], "STO_CRM.exe")
        self.assertEqual(sto_crm.select_release_asset(release, kind="manifest")["name"], "latest.json")
        self.assertEqual(sto_crm.normalize_github_repository("https://github.com/owner/repo.git"), "owner/repo")

    def test_release_manifest_drives_update_asset_metadata(self):
        release = {"tag_name": "v1.20.0", "html_url": "https://github.com/owner/repo/releases/tag/v1.20.0"}
        manifest = {
            "version": "1.20.0",
            "asset": {
                "name": "STO_CRM.exe",
                "size": 123,
                "sha256": "A" * 64,
                "download_url": "https://github.com/owner/repo/releases/download/v1.20.0/STO_CRM.exe",
            },
        }
        info = sto_crm.release_info_from_manifest(release, manifest, {"name": "latest.json", "size": 100})
        self.assertEqual(info["version"], "1.20.0")
        self.assertEqual(info["asset"]["sha256"], "a" * 64)
        self.assertEqual(info["manifest"]["name"], "latest.json")

    def test_update_manifest_rejects_missing_hash_and_untrusted_download_url(self):
        release = {"tag_name": "v1.20.0", "html_url": "https://github.com/owner/repo/releases/tag/v1.20.0"}
        trusted_asset = {
            "name": "STO_CRM.exe",
            "size": 123,
            "sha256": "b" * 64,
            "download_url": "https://github.com/owner/repo/releases/download/v1.20.0/STO_CRM.exe",
        }
        with self.assertRaisesRegex(RuntimeError, "SHA-256"):
            sto_crm.release_info_from_manifest(release, {"asset": {**trusted_asset, "sha256": ""}}, {"name": "latest.json"})
        untrusted_urls = [
            "https://example.test/STO_CRM.exe",
            "http://github.com/owner/repo/releases/download/v1.20.0/STO_CRM.exe",
            "https://github.com.evil.test/owner/repo/releases/download/v1.20.0/STO_CRM.exe",
            "https://user:pass@github.com/owner/repo/releases/download/v1.20.0/STO_CRM.exe",
            "https://github.com:444/owner/repo/releases/download/v1.20.0/STO_CRM.exe",
        ]
        for url in untrusted_urls:
            with self.subTest(url=url):
                with self.assertRaisesRegex(RuntimeError, "недоверенную"):
                    sto_crm.release_info_from_manifest(release, {"asset": {**trusted_asset, "download_url": url}}, {"name": "latest.json"})
        with self.assertRaisesRegex(RuntimeError, "некорректную"):
            sto_crm.release_info_from_manifest(
                release,
                {"asset": {**trusted_asset, "download_url": "https://github.com:bad/owner/repo/releases/download/v1.20.0/STO_CRM.exe"}},
                {"name": "latest.json"},
            )

    def test_download_release_asset_requires_verified_hash_and_keeps_existing_target_on_failure(self):
        old_urlopen = urllib.request.urlopen
        try:
            target = Path(self.tempdir.name) / "STO_CRM.exe"
            target.write_bytes(b"old-good-file")
            payload = b"MZnew-executable"
            asset = {
                "name": "STO_CRM.exe",
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "download_url": "https://github.com/owner/repo/releases/download/v1.20.0/STO_CRM.exe",
            }

            class FakeResponse:
                def __init__(self, body: bytes):
                    self._stream = io.BytesIO(body)
                    self.headers = Message()

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

                def geturl(self):
                    return "https://github.com/owner/repo/releases/download/v1.20.0/STO_CRM.exe"

                def read(self, size: int = -1) -> bytes:
                    return self._stream.read(size)

            bad_payload = b"bad-content".ljust(len(payload), b"!")
            urllib.request.urlopen = lambda *_args, **_kwargs: FakeResponse(bad_payload)
            with self.assertRaisesRegex(RuntimeError, "SHA-256"):
                sto_crm.download_release_asset(asset, target)
            self.assertEqual(target.read_bytes(), b"old-good-file")
            self.assertFalse(target.with_name(f"{target.name}.tmp").exists())

            urllib.request.urlopen = lambda *_args, **_kwargs: FakeResponse(b"short")
            with self.assertRaisesRegex(RuntimeError, "Размер"):
                sto_crm.download_release_asset(asset, target)
            self.assertEqual(target.read_bytes(), b"old-good-file")
            self.assertFalse(target.with_name(f"{target.name}.tmp").exists())

            urllib.request.urlopen = lambda *_args, **_kwargs: FakeResponse(b"")
            empty_asset = {**asset, "size": 0}
            with self.assertRaisesRegex(RuntimeError, "пустой"):
                sto_crm.download_release_asset(empty_asset, target)
            self.assertEqual(target.read_bytes(), b"old-good-file")
            self.assertFalse(target.with_name(f"{target.name}.tmp").exists())

            urllib.request.urlopen = lambda *_args, **_kwargs: FakeResponse(payload)
            details = sto_crm.download_release_asset(asset, target)
            self.assertEqual(details["size"], len(payload))
            self.assertEqual(details["sha256"], hashlib.sha256(payload).hexdigest())
            self.assertEqual(target.read_bytes(), payload)

            missing_hash_asset = {**asset, "sha256": ""}
            with self.assertRaisesRegex(RuntimeError, "SHA-256"):
                sto_crm.download_release_asset(missing_hash_asset, target)
        finally:
            urllib.request.urlopen = old_urlopen

    def test_update_json_and_redirects_are_bounded_and_validated(self):
        old_urlopen = urllib.request.urlopen
        try:
            class FakeHeaders(Message):
                def get_content_charset(self):
                    return "utf-8"

            class FakeResponse:
                def __init__(self, body: bytes, final_url: str = "https://github.com/owner/repo/releases/download/v1.20.0/latest.json", content_length: int | None = None):
                    self._stream = io.BytesIO(body)
                    self._final_url = final_url
                    self.headers = FakeHeaders()
                    if content_length is not None:
                        self.headers["Content-Length"] = str(content_length)

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

                def geturl(self):
                    return self._final_url

                def read(self, size: int = -1) -> bytes:
                    return self._stream.read(size)

            urllib.request.urlopen = lambda *_args, **_kwargs: FakeResponse(b'{"ok": true}')
            self.assertEqual(sto_crm.fetch_json("https://api.github.com/repos/owner/repo/releases/latest"), {"ok": True})

            urllib.request.urlopen = lambda *_args, **_kwargs: FakeResponse(b"{}", "https://example.test/latest.json")
            with self.assertRaisesRegex(RuntimeError, "недоверенную"):
                sto_crm.fetch_json("https://github.com/owner/repo/releases/download/v1.20.0/latest.json")

            urllib.request.urlopen = lambda *_args, **_kwargs: FakeResponse(b"{}", content_length=sto_crm.GITHUB_UPDATE_MAX_JSON_BYTES + 1)
            with self.assertRaisesRegex(RuntimeError, "слишком большой"):
                sto_crm.fetch_json("https://github.com/owner/repo/releases/download/v1.20.0/latest.json")

            target = Path(self.tempdir.name) / "redirect.exe"
            asset = {
                "name": "STO_CRM.exe",
                "size": 2,
                "sha256": hashlib.sha256(b"MZ").hexdigest(),
                "download_url": "https://github.com/owner/repo/releases/download/v1.20.0/STO_CRM.exe",
            }
            urllib.request.urlopen = lambda *_args, **_kwargs: FakeResponse(b"MZ", "https://example.test/STO_CRM.exe")
            with self.assertRaisesRegex(RuntimeError, "недоверенную"):
                sto_crm.download_release_asset(asset, target)
            self.assertFalse(target.exists())
        finally:
            urllib.request.urlopen = old_urlopen

    def test_update_status_reports_release_lookup_failures_without_crashing(self):
        old_fetch_json = sto_crm.fetch_json
        try:
            sto_crm.fetch_json = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("offline"))
            status = sto_crm.update_status()
        finally:
            sto_crm.fetch_json = old_fetch_json
        self.assertFalse(status["ok"])
        self.assertEqual(status["current_version"], sto_crm.APP_VERSION)
        self.assertIn("offline", status["error"])

    def test_home_page_exposes_github_updates_ui_and_api_hooks(self):
        html = sto_crm.INDEX_HTML
        self.assertIn('data-route="updates"', html)
        self.assertIn('function renderUpdates()', html)
        self.assertIn('/api/update/status', html)
        self.assertIn('/api/update/install', html)
        self.assertIn('data-action="check-update"', html)
        self.assertIn('data-action="install-update"', html)
        self.assertIn('STO_CRM.exe', html)
        self.assertIn('latest.json', html)
        self.assertIn('release-only', html)

    def test_home_page_exposes_theme_route_and_modal_accessibility_hooks(self):
        html = sto_crm.INDEX_HTML
        self.assertIn('id="themeToggle"', html)
        self.assertIn('themeToggle.addEventListener("click"', html)
        self.assertIn('id="densityToggle"', html)
        self.assertIn('function applyDensity(', html)
        self.assertIn('function toggleDensity()', html)
        self.assertIn('sto-crm-density', html)
        self.assertIn('body.compact .metric', html)
        self.assertIn('id="commandPalette"', html)
        self.assertIn('function commandItems()', html)
        self.assertIn('function openCommandPalette()', html)
        self.assertIn('data-command-index', html)
        self.assertIn('Ctrl+K', html)
        self.assertIn('aria-pressed', html)
        self.assertIn('history.pushState', html)
        self.assertIn('window.addEventListener("popstate"', html)
        self.assertIn('lastFocusedElement', html)
        self.assertIn('appTabbableSnapshot', html)
        self.assertIn('bindModalSubmitHandlers', html)
        self.assertIn('safeStorageGet', html)
        self.assertIn('nextThemePreference', html)
        self.assertIn('localStorage.removeItem(key)', html)
        self.assertIn('handleModalKeydown', html)
        self.assertIn('aria-label="Печать заказ-наряда', html)
        self.assertIn('id="clearSearch"', html)
        self.assertIn('type="email"', html)
        self.assertIn('title="VIN должен содержать 17 символов без I, O и Q"', html)

    def test_home_page_has_premium_dashboard_and_view_headings(self):
        html = sto_crm.INDEX_HTML
        self.assertIn('function sectionIntro(title, text, options = {})', html)
        self.assertIn('"section-card hero-card"', html)
        self.assertIn('hero-stat-stack', html)
        self.assertIn('metric-icon', html)
        self.assertIn('insight-icon', html)
        self.assertIn('--content-max: 1680px;', html)
        self.assertIn('Premium workspace', html)
        self.assertIn('Управляйте сменой автосервиса без хаоса', html)
        self.assertIn('function viewHeading(', html)
        self.assertIn('view-heading-actions', html)
        self.assertIn('Календарь приемки', html)
        self.assertIn('Digital Vehicle Inspection', html)
        self.assertIn('Заказ-наряды', html)
        self.assertIn('Каталог автомобилей', html)
        self.assertIn('Отчеты и аналитика', html)
        self.assertIn('data-action="open-action-plan"', html)
        self.assertIn('linear-gradient(160deg, var(--brand-start), var(--brand-mid) 54%, var(--brand-end))', html)
        self.assertIn('grid-template-columns: 292px minmax(0, 1fr)', html)
        self.assertIn('workspace-grid', html)
        self.assertIn('function riskRadar(report)', html)
        self.assertIn('function quickActions()', html)
        self.assertIn('function miniLedger(report)', html)

    def test_print_order_html_uses_professional_document_design(self):
        order = {
            "number": "WO-001",
            "status": "approved",
            "customer_name": "Design Client",
            "customer_phone": "+7999",
            "vehicle_make": "Toyota",
            "vehicle_model": "Camry",
            "vehicle_year": 2022,
            "vehicle_plate": "A001AA",
            "mechanic": "Master",
            "authorized_by": "Client",
            "items": [
                {"kind": "service", "title": "Premium labor", "approval_status": "approved", "quantity": 1, "unit_price": 1000},
                {"kind": "part", "title": "Deferred part", "approval_status": "deferred", "quantity": 1, "unit_price": 500},
            ],
            "service_total": 1000,
            "parts_total": 0,
            "discount": 0,
            "tax": 0,
            "total": 1000,
            "paid": 200,
            "due": 800,
        }
        html = sto_crm.print_order_html(order)
        self.assertIn('class="document" aria-label="Печатная форма заказ-наряда"', html)
        self.assertIn('class="print-toolbar"', html)
        self.assertIn('class="doc-hero"', html)
        self.assertIn('class="status-chip"', html)
        self.assertIn('class="line-badge approved"', html)
        self.assertIn('class="line-badge deferred"', html)
        self.assertIn('print-color-adjust: exact', html)
        self.assertIn('@media print', html)
        self.assertIn('СТО CRM · заказ-наряд', html)

    def test_frontend_error_retry_and_network_helpers_are_robust(self):
        html = sto_crm.INDEX_HTML
        self.assertIn('bindViewActions(content);', html)
        self.assertIn('error.retryable = response.status >= 500;', html)
        self.assertIn('const retryable = error?.retryable === true || !Number(error?.status || 0);', html)
        self.assertIn('if (attempt === maxRetries || !retryable) throw error;', html)
        self.assertIn('window.setTimeout(() => URL.revokeObjectURL(url), 1000);', html)
        self.assertNotIn('URL.revokeObjectURL(url);\n    toast("CSV экспортирован")', html)


if __name__ == "__main__":
    unittest.main()
