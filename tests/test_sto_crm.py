import codecs
import contextlib
import hashlib
import io
import json
import math
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
    return {
        "kind": "service",
        "title": "Labor",
        "quantity": 1,
        "unit_price": price,
        "unit_cost": 0,
    }


def recv_http_response(client, limit=65536):
    chunks = []
    total = 0
    client.settimeout(5)
    while True:
        try:
            chunk = client.recv(4096)
        except socket.timeout:
            break
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total >= limit:
            break
    return b"".join(chunks).decode("utf-8", errors="replace")


class StoCrmTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.old_runtime = sto_crm.RUNTIME
        self.old_safe_log = sto_crm.safe_log
        sto_crm.safe_log = lambda _message: None
        sto_crm.RUNTIME = sto_crm.Runtime(
            Path(self.tempdir.name) / "test.sqlite3",
            time.time(),
            "test-csrf-token",
            "test-access-token",
            "test-bootstrap-token",
        )
        sto_crm.init_db()

    def tearDown(self):
        # Очищаем тестовую БД перед удалением временной директории
        if hasattr(self, "tempdir"):
            try:
                sto_crm.RUNTIME = self.old_runtime
            except Exception:
                pass
        sto_crm.safe_log = self.old_safe_log
        self.tempdir.cleanup()

    def create_customer(self, name):
        return sto_crm.create_customer(
            {"name": name, "phone": "", "email": "", "source": "", "notes": ""}
        )

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

    def order_payload_from_record(self, order):
        return {
            key: order.get(key)
            for key in [
                "customer_id",
                "vehicle_id",
                "status",
                "priority",
                "advisor",
                "mechanic",
                "promised_at",
                "odometer",
                "complaint",
                "diagnosis",
                "recommendations",
                "discount",
                "tax_rate",
                "paid",
                "payment_method",
                "authorized_by",
                "authorized_at",
                "follow_up_at",
            ]
        } | {
            "items": [
                {
                    key: item.get(key)
                    for key in [
                        "kind",
                        "inventory_id",
                        "title",
                        "approval_status",
                        "quantity",
                        "unit_price",
                        "unit_cost",
                    ]
                }
                for item in order["items"]
            ]
        }

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
        self.assertEqual(
            len(catalog["makes"]),
            len(set(make.casefold() for make in catalog["makes"])),
        )
        self.assertIn("Lada", catalog["makes"])
        self.assertIn("Toyota", catalog["makes"])
        self.assertIn("Acura", catalog["makes"])
        self.assertIn("Ferrari", catalog["makes"])
        self.assertIn("Costin Sports Car", catalog["makes"])
        self.assertIn("Vesta", catalog["models"]["Lada"])
        self.assertIn("Camry", catalog["models"]["Toyota"])
        self.assertEqual(
            len(catalog["models"]["Toyota"]),
            len(set(model.casefold() for model in catalog["models"]["Toyota"])),
        )
        self.assertEqual(
            catalog["models"]["Toyota"],
            sorted(catalog["models"]["Toyota"], key=str.casefold),
        )

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
        self.assertTrue(
            any(item["id"] == vehicle["id"] for item in reports["service_reminders"])
        )
        self.assertTrue(
            any(
                item["id"] == estimate["id"]
                for item in reports["authorizations_pending"]
            )
        )
        self.assertTrue(
            any(item["id"] == closed["id"] for item in reports["followups_due"])
        )
        self.assertGreaterEqual(reports["crm_tasks_count"], 3)

        muted_customer = sto_crm.create_customer(
            {
                "name": "Do Not Contact",
                "preferred_channel": "none",
                "reminder_consent": 1,
            }
        )
        muted_vehicle = sto_crm.create_vehicle(
            {
                "customer_id": muted_customer["id"],
                "make": "Lada",
                "model": "Vesta",
                "plate": "N000ON",
                "next_service_at": "2000-01-01",
            }
        )
        muted_reports = sto_crm.bootstrap_payload()["reports"]
        self.assertFalse(
            any(
                item["id"] == muted_vehicle["id"]
                for item in muted_reports["service_reminders"]
            )
        )
        self.assertFalse(
            any(
                item["type"] == "service_reminder"
                and item["record_id"] == muted_vehicle["id"]
                for item in muted_reports["action_plan"]
            )
        )

    def test_declined_order_items_are_not_billed_or_consumed_and_become_crm_tasks(self):
        customer = self.create_customer("Deferred Customer")
        vehicle = self.create_vehicle(customer["id"], "D004DD")
        part = sto_crm.create_inventory(
            {
                "sku": "DECL",
                "name": "Declined part",
                "quantity": 1,
                "price": 50,
                "cost": 25,
            }
        )

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
        self.assertTrue(
            any(item["title"] == "Declined part" for item in reports["deferred_work"])
        )

    def test_tiny_order_item_quantity_is_rejected_before_stock_delta(self):
        customer = self.create_customer("Tiny Quantity Customer")
        part = sto_crm.create_inventory(
            {"sku": "TINY", "name": "Tiny part", "quantity": 0, "price": 10}
        )

        with self.assertRaisesRegex(ValueError, "не меньше 0.01"):
            sto_crm.create_order(
                {
                    "customer_id": customer["id"],
                    "status": "closed",
                    "priority": "normal",
                    "items": [
                        {
                            "kind": "part",
                            "inventory_id": part["id"],
                            "title": "Tiny part",
                            "quantity": 0.000001,
                            "unit_price": 10,
                        }
                    ],
                }
            )
        with sto_crm.db() as conn:
            self.assertEqual(sto_crm.get_inventory(conn, part["id"])["quantity"], 0)

    def test_cancelled_order_noop_allows_its_deleted_inventory_reference(self):
        customer = self.create_customer("Cancelled Stock Customer")
        part = sto_crm.create_inventory(
            {
                "sku": "CANCELLED-STOCK",
                "name": "Cancelled stock",
                "quantity": 1,
                "price": 10,
            }
        )
        order = sto_crm.create_order(
            {
                "customer_id": customer["id"],
                "status": "cancelled",
                "priority": "normal",
                "items": [
                    {
                        "kind": "part",
                        "inventory_id": part["id"],
                        "title": part["name"],
                        "quantity": 1,
                        "unit_price": 10,
                    }
                ],
            }
        )
        self.assertEqual(sto_crm.delete_inventory(part["id"]), {"deleted": True})

        noop = sto_crm.update_order(order["id"], self.order_payload_from_record(order))
        self.assertEqual(noop["status"], "cancelled")

        changed = self.order_payload_from_record(order)
        changed["items"][0]["quantity"] = 2
        with self.assertRaisesRegex(ValueError, "нельзя изменить"):
            sto_crm.update_order(order["id"], changed)

    def test_fractional_stock_exact_sum_does_not_false_fail(self):
        customer = self.create_customer("Fractional Stock Customer")
        part = sto_crm.create_inventory(
            {"sku": "FRACTIONAL", "name": "Bulk fluid", "quantity": 0.3, "price": 10}
        )

        order = sto_crm.create_order(
            {
                "customer_id": customer["id"],
                "status": "closed",
                "priority": "normal",
                "items": [
                    {
                        "kind": "part",
                        "inventory_id": part["id"],
                        "title": "Bulk fluid 0.1",
                        "quantity": 0.1,
                        "unit_price": 10,
                    },
                    {
                        "kind": "part",
                        "inventory_id": part["id"],
                        "title": "Bulk fluid 0.2",
                        "quantity": 0.2,
                        "unit_price": 10,
                    },
                ],
            }
        )
        self.assertEqual(order["status"], "closed")
        with sto_crm.db() as conn:
            self.assertEqual(sto_crm.get_inventory(conn, part["id"])["quantity"], 0)

    def test_closed_order_rejects_sub_cent_financial_change(self):
        customer = self.create_customer("Sub-cent Closed Customer")
        order = sto_crm.create_order(
            {
                "customer_id": customer["id"],
                "status": "closed",
                "priority": "normal",
                "items": [
                    {
                        "kind": "service",
                        "title": "Bulk service",
                        "quantity": 1000,
                        "unit_price": 10,
                        "unit_cost": 1,
                    }
                ],
            }
        )

        changed_price = self.order_payload_from_record(order)
        changed_price["items"][0]["unit_price"] = 10.004
        with self.assertRaisesRegex(ValueError, "Финансовые данные"):
            sto_crm.update_order(order["id"], changed_price)

        changed_tax = self.order_payload_from_record(order)
        changed_tax["tax_rate"] = 0.004
        with self.assertRaisesRegex(ValueError, "Финансовые данные"):
            sto_crm.update_order(order["id"], changed_tax)

    def test_legacy_closed_order_noop_uses_same_money_normalization(self):
        customer = self.create_customer("Legacy Closed Money Customer")
        order = sto_crm.create_order(
            {
                "customer_id": customer["id"],
                "status": "closed",
                "priority": "normal",
                "paid": 0,
                "items": [service_item(100)],
            }
        )
        with sto_crm.db() as conn:
            conn.execute(
                "UPDATE orders SET paid = ?, discount = ? WHERE id = ?",
                (999, 999, order["id"]),
            )
            legacy = sto_crm.get_order(conn, order["id"])

        self.assertEqual(legacy["paid"], 0)
        self.assertEqual(legacy["total"], 0)
        noop = sto_crm.update_order(order["id"], self.order_payload_from_record(legacy))
        self.assertEqual(noop["status"], "closed")
        self.assertEqual(noop["paid"], 0)

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

        today_slot = (
            sto_crm.datetime.now()
            .replace(hour=10, minute=0, second=0, microsecond=0)
            .isoformat(timespec="minutes")
        )
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
        self.assertTrue(
            any(item["id"] == appointment["id"] for item in payload["appointments"])
        )
        self.assertTrue(
            any(
                item["id"] == appointment["id"]
                for item in payload["reports"]["appointments_today"]
            )
        )
        filename, content = sto_crm.csv_export("appointments")
        self.assertEqual(filename, "appointments.csv")
        self.assertIn("Suspension check", content)

    def test_appointment_conflict_checks_all_prior_overlapping_records(self):
        customer = self.create_customer("Long Calendar")
        vehicle = self.create_vehicle(customer["id"], "L480NG")
        sto_crm.create_appointment(
            {
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "scheduled_at": "2025-03-20T08:00",
                "duration_minutes": 480,
                "status": "scheduled",
            }
        )
        with self.assertRaisesRegex(ValueError, "уже есть запись"):
            sto_crm.create_appointment(
                {
                    "customer_id": customer["id"],
                    "vehicle_id": vehicle["id"],
                    "scheduled_at": "2025-03-20T15:59",
                    "duration_minutes": 30,
                    "status": "scheduled",
                }
            )

    def test_frozen_app_uses_localappdata_for_database_by_default(self):
        old_app_dir = sto_crm.app_dir
        old_directory_writable = sto_crm.directory_writable
        old_localappdata = os.environ.get("LOCALAPPDATA")
        had_frozen = hasattr(sto_crm.sys, "frozen")
        old_frozen = getattr(sto_crm.sys, "frozen", None)
        fallback = Path(self.tempdir.name) / "LocalAppData"

        try:
            sto_crm.app_dir = lambda: Path(self.tempdir.name) / "ReadOnlyApp"
            sto_crm.directory_writable = lambda directory: str(directory).startswith(
                str(fallback)
            )
            sto_crm.sys.frozen = True
            os.environ["LOCALAPPDATA"] = str(fallback)
            self.assertEqual(
                sto_crm.default_db_path(), fallback / "STO_CRM" / "sto_crm.sqlite3"
            )
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

    def test_legacy_database_adds_missing_columns_before_indexes(self):
        legacy_db = Path(self.tempdir.name) / "legacy.sqlite3"
        sto_crm.RUNTIME = sto_crm.Runtime(
            legacy_db,
            time.time(),
            "test-csrf-token",
            "test-access-token",
            "test-bootstrap-token",
        )
        conn = sqlite3.connect(legacy_db)
        try:
            conn.executescript(
                """
                CREATE TABLE customers(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL);
                CREATE TABLE vehicles(id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER NOT NULL);
                CREATE TABLE orders(id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT);
                CREATE TABLE order_items(id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL);
                CREATE TABLE appointments(id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER NOT NULL);
                CREATE TABLE inspections(id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER NOT NULL, vehicle_id INTEGER NOT NULL);
                CREATE TABLE inspection_items(id INTEGER PRIMARY KEY AUTOINCREMENT, inspection_id INTEGER NOT NULL, title TEXT NOT NULL);
                INSERT INTO orders(customer_id, created_at, updated_at, deleted_at) VALUES (1, '2020-01-01T10:00', '2020-01-01T11:00', NULL);
                INSERT INTO order_items(title) VALUES ('Legacy service');
                INSERT INTO inspections(customer_id, vehicle_id) VALUES (1, 1);
                INSERT INTO inspection_items(inspection_id, title) VALUES (1, 'Legacy check');
                """
            )
            conn.commit()
        finally:
            conn.close()

        sto_crm.init_db()
        with sto_crm.db() as conn:
            customer_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(customers)").fetchall()
            }
            vehicle_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(vehicles)").fetchall()
            }
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(orders)").fetchall()
            }
            item_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(order_items)").fetchall()
            }
            appointment_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(appointments)").fetchall()
            }
            indexes = {
                row["name"]
                for row in conn.execute("PRAGMA index_list(orders)").fetchall()
            }
            customer_indexes = {
                row["name"]
                for row in conn.execute("PRAGMA index_list(customers)").fetchall()
            }
            vehicle_indexes = {
                row["name"]
                for row in conn.execute("PRAGMA index_list(vehicles)").fetchall()
            }
            item_indexes = {
                row["name"]
                for row in conn.execute("PRAGMA index_list(order_items)").fetchall()
            }
            appointment_indexes = {
                row["name"]
                for row in conn.execute("PRAGMA index_list(appointments)").fetchall()
            }
            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            migrated_number = conn.execute(
                "SELECT number FROM orders WHERE id = 1"
            ).fetchone()["number"]
            archived_inspection = conn.execute(
                "SELECT customer_id, vehicle_id FROM archived_inspections"
            ).fetchone()
            archived_inspection_item = conn.execute(
                "SELECT inspection_id, title FROM archived_inspection_items"
            ).fetchone()
        self.assertIn("phone", customer_columns)
        self.assertIn("idx_customers_phone", customer_indexes)
        self.assertIn("plate", vehicle_columns)
        self.assertIn("mileage_manual", vehicle_columns)
        self.assertIn("idx_vehicles_plate", vehicle_indexes)
        self.assertIn("number", columns)
        self.assertTrue(migrated_number.startswith("СТО-LEGACY-"))
        self.assertIn("closed_at", columns)
        self.assertIn("authorized_by", columns)
        self.assertIn("authorized_at", columns)
        self.assertIn("follow_up_at", columns)
        self.assertIn("order_id", item_columns)
        self.assertIn("inventory_id", item_columns)
        self.assertIn("approval_status", item_columns)
        self.assertIn("idx_order_items_inventory", item_indexes)
        self.assertIn("scheduled_at", appointment_columns)
        self.assertIn("vehicle_id", appointment_columns)
        self.assertIn("idx_orders_closed_at", indexes)
        self.assertIn("idx_orders_follow_up_at", indexes)
        self.assertIn("idx_appointments_schedule", appointment_indexes)
        self.assertNotIn("inspections", tables)
        self.assertNotIn("inspection_items", tables)
        self.assertIn("archived_inspections", tables)
        self.assertIn("archived_inspection_items", tables)
        self.assertEqual(dict(archived_inspection), {"customer_id": 1, "vehicle_id": 1})
        self.assertEqual(
            dict(archived_inspection_item),
            {"inspection_id": 1, "title": "Legacy check"},
        )

    def test_order_mileage_sync_reconciles_removed_max_odometer_without_overwriting_manual_mileage(
        self,
    ):
        customer = self.create_customer("Mileage Customer")
        vehicle = self.create_vehicle(customer["id"], "M001LG")
        low = sto_crm.create_order(
            {
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "status": "new",
                "priority": "normal",
                "odometer": 1500,
                "items": [service_item(10)],
            }
        )
        high = sto_crm.create_order(
            {
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "status": "new",
                "priority": "normal",
                "odometer": 2500,
                "items": [service_item(10)],
            }
        )
        with sto_crm.db() as conn:
            self.assertEqual(sto_crm.get_vehicle(conn, vehicle["id"])["mileage"], 2500)

        stale_card_payload = {
            "customer_id": customer["id"],
            "make": vehicle["make"],
            "model": vehicle["model"],
            "year": vehicle["year"],
            "plate": vehicle["plate"],
            "vin": vehicle["vin"],
            "mileage": vehicle["mileage"],
            "notes": "stale tab note",
        }
        stale_saved = sto_crm.update_vehicle(vehicle["id"], stale_card_payload)
        self.assertEqual(stale_saved["mileage"], 2500)
        self.assertEqual(stale_saved["mileage_manual"], vehicle["mileage"])
        self.assertEqual(stale_saved["mileage_order_id"], high["id"])
        self.assertEqual(stale_saved["notes"], "stale tab note")

        sto_crm.delete_order(high["id"])
        with sto_crm.db() as conn:
            self.assertEqual(sto_crm.get_vehicle(conn, vehicle["id"])["mileage"], 1500)

        sto_crm.update_vehicle(
            vehicle["id"],
            {
                "customer_id": customer["id"],
                "make": vehicle["make"],
                "model": vehicle["model"],
                "year": vehicle["year"],
                "plate": vehicle["plate"],
                "vin": vehicle["vin"],
                "mileage": 3000,
                "notes": vehicle["notes"],
            },
        )
        sto_crm.delete_order(low["id"])
        with sto_crm.db() as conn:
            self.assertEqual(sto_crm.get_vehicle(conn, vehicle["id"])["mileage"], 3000)

        baseline_vehicle = self.create_vehicle(customer["id"], "M002LG")
        baseline_order = sto_crm.create_order(
            {
                "customer_id": customer["id"],
                "vehicle_id": baseline_vehicle["id"],
                "status": "new",
                "priority": "normal",
                "odometer": 5000,
                "items": [service_item(10)],
            }
        )
        sto_crm.delete_order(baseline_order["id"])
        with sto_crm.db() as conn:
            self.assertEqual(
                sto_crm.get_vehicle(conn, baseline_vehicle["id"])["mileage"],
                baseline_vehicle["mileage"],
            )

        equal_vehicle = self.create_vehicle(customer["id"], "M003LG")
        equal_first = sto_crm.create_order(
            {
                "customer_id": customer["id"],
                "vehicle_id": equal_vehicle["id"],
                "status": "new",
                "priority": "normal",
                "odometer": 5000,
                "items": [service_item(10)],
            }
        )
        equal_second = sto_crm.create_order(
            {
                "customer_id": customer["id"],
                "vehicle_id": equal_vehicle["id"],
                "status": "new",
                "priority": "normal",
                "odometer": 5000,
                "items": [service_item(10)],
            }
        )
        sto_crm.delete_order(equal_first["id"])
        with sto_crm.db() as conn:
            equal_after_first_delete = sto_crm.get_vehicle(conn, equal_vehicle["id"])
        self.assertEqual(equal_after_first_delete["mileage"], 5000)
        self.assertEqual(
            equal_after_first_delete["mileage_order_id"], equal_second["id"]
        )

        sto_crm.delete_order(equal_second["id"])
        with sto_crm.db() as conn:
            equal_after_second_delete = sto_crm.get_vehicle(conn, equal_vehicle["id"])
        self.assertEqual(equal_after_second_delete["mileage"], equal_vehicle["mileage"])
        self.assertIsNone(equal_after_second_delete["mileage_order_id"])

        manual_vehicle = self.create_vehicle(customer["id"], "M004LG")
        manual_order = sto_crm.create_order(
            {
                "customer_id": customer["id"],
                "vehicle_id": manual_vehicle["id"],
                "status": "new",
                "priority": "normal",
                "odometer": manual_vehicle["mileage"],
                "items": [service_item(10)],
            }
        )
        sto_crm.update_order(
            manual_order["id"],
            {
                "customer_id": customer["id"],
                "vehicle_id": 0,
                "status": "new",
                "priority": "normal",
                "odometer": manual_vehicle["mileage"],
                "items": [service_item(10)],
            },
        )
        with sto_crm.db() as conn:
            self.assertEqual(
                sto_crm.get_vehicle(conn, manual_vehicle["id"])["mileage"],
                manual_vehicle["mileage"],
            )

        confirmed_vehicle = self.create_vehicle(customer["id"], "M005LG")
        confirmed_order = sto_crm.create_order(
            {
                "customer_id": customer["id"],
                "vehicle_id": confirmed_vehicle["id"],
                "status": "new",
                "priority": "normal",
                "odometer": 10000,
                "items": [service_item(10)],
            }
        )
        with sto_crm.db() as conn:
            synced = sto_crm.get_vehicle(conn, confirmed_vehicle["id"])
        self.assertEqual(synced["mileage"], 10000)
        sto_crm.update_vehicle(
            confirmed_vehicle["id"],
            {
                "customer_id": customer["id"],
                "make": synced["make"],
                "model": synced["model"],
                "year": synced["year"],
                "plate": synced["plate"],
                "vin": synced["vin"],
                "mileage": synced["mileage"],
                "notes": synced["notes"],
            },
        )
        sto_crm.delete_order(confirmed_order["id"])
        with sto_crm.db() as conn:
            self.assertEqual(
                sto_crm.get_vehicle(conn, confirmed_vehicle["id"])["mileage"], 10000
            )

    def test_active_orders_reserve_inventory_until_closed_or_cancelled(self):
        customer = self.create_customer("Reservation Customer")
        vehicle = self.create_vehicle(customer["id"], "R555SV")
        part = sto_crm.create_inventory(
            {
                "sku": "RESERVE",
                "name": "Reserved part",
                "quantity": 2,
                "price": 10,
                "cost": 4,
            }
        )
        first = sto_crm.create_order(
            {
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "status": "approved",
                "priority": "normal",
                "items": [
                    {
                        "kind": "part",
                        "inventory_id": part["id"],
                        "title": part["name"],
                        "quantity": 2,
                        "unit_price": 10,
                        "unit_cost": 4,
                    }
                ],
            }
        )

        with self.assertRaisesRegex(ValueError, "свободного остатка"):
            sto_crm.create_order(
                {
                    "customer_id": customer["id"],
                    "vehicle_id": vehicle["id"],
                    "status": "approved",
                    "priority": "normal",
                    "items": [
                        {
                            "kind": "part",
                            "inventory_id": part["id"],
                            "title": part["name"],
                            "quantity": 1,
                            "unit_price": 10,
                            "unit_cost": 4,
                        }
                    ],
                }
            )
        with self.assertRaisesRegex(ValueError, "зарезервированного"):
            sto_crm.update_inventory(
                part["id"],
                {
                    "sku": "RESERVE",
                    "name": part["name"],
                    "quantity": 1,
                    "price": 10,
                    "cost": 4,
                },
            )

        payload = self.order_payload_from_record(first)
        sto_crm.update_order(first["id"], {**payload, "status": "cancelled"})
        second = sto_crm.create_order(
            {
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "status": "approved",
                "priority": "normal",
                "items": [
                    {
                        "kind": "part",
                        "inventory_id": part["id"],
                        "title": part["name"],
                        "quantity": 2,
                        "unit_price": 10,
                        "unit_cost": 4,
                    }
                ],
            }
        )
        self.assertEqual(second["status"], "approved")

    def test_closed_order_cannot_consume_stock_reserved_by_another_active_order(self):
        customer = self.create_customer("Reserved Close Customer")
        vehicle = self.create_vehicle(customer["id"], "R001CL")
        part = sto_crm.create_inventory(
            {
                "sku": "RESERVED-CLOSE",
                "name": "Reserved close part",
                "quantity": 1,
                "price": 10,
                "cost": 5,
            }
        )
        part_item = {
            "kind": "part",
            "inventory_id": part["id"],
            "title": part["name"],
            "quantity": 1,
            "unit_price": 10,
            "unit_cost": 5,
        }

        sto_crm.create_order(
            {
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "status": "approved",
                "priority": "normal",
                "items": [part_item],
            }
        )

        closed_payload = {
            "customer_id": customer["id"],
            "vehicle_id": vehicle["id"],
            "status": "closed",
            "priority": "normal",
            "items": [part_item],
        }
        with self.assertRaisesRegex(ValueError, "свободного остатка"):
            sto_crm.create_order(closed_payload)

        draft = sto_crm.create_order({**closed_payload, "status": "new"})
        draft_payload = self.order_payload_from_record(draft)
        draft_payload["status"] = "closed"
        with self.assertRaisesRegex(ValueError, "свободного остатка"):
            sto_crm.update_order(draft["id"], draft_payload)

        with sto_crm.db() as conn:
            self.assertEqual(sto_crm.get_inventory(conn, part["id"])["quantity"], 1)
            self.assertEqual(sto_crm.get_order(conn, draft["id"])["status"], "new")

    def test_order_can_consume_its_own_active_reservation_when_closed(self):
        customer = self.create_customer("Own Reservation Customer")
        vehicle = self.create_vehicle(customer["id"], "R002CL")
        part = sto_crm.create_inventory(
            {
                "sku": "OWN-RESERVE",
                "name": "Own reserved part",
                "quantity": 1,
                "price": 10,
                "cost": 5,
            }
        )
        order = sto_crm.create_order(
            {
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "status": "approved",
                "priority": "normal",
                "items": [
                    {
                        "kind": "part",
                        "inventory_id": part["id"],
                        "title": part["name"],
                        "quantity": 1,
                        "unit_price": 10,
                        "unit_cost": 5,
                    }
                ],
            }
        )

        payload = self.order_payload_from_record(order)
        payload["status"] = "closed"
        closed = sto_crm.update_order(order["id"], payload)

        self.assertEqual(closed["status"], "closed")
        with sto_crm.db() as conn:
            self.assertEqual(sto_crm.get_inventory(conn, part["id"])["quantity"], 0)

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
                {
                    "kind": "part",
                    "inventory_id": part["id"],
                    "title": "Test part",
                    "quantity": 1,
                    "unit_price": 50,
                    "unit_cost": 20,
                },
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
        self.assertTrue(cancelled["closed_at"])
        with sto_crm.db() as conn:
            self.assertEqual(sto_crm.get_inventory(conn, part["id"])["quantity"], 3)

        # Повторное сохранение cancelled-after-closed заказа без изменений должно
        # пройти без ошибки, а попытка повторно открыть (перевести в любой другой
        # статус) — по-прежнему блокируется.
        noop = sto_crm.update_order(order["id"], payload)
        self.assertEqual(noop["status"], "cancelled")
        self.assertEqual(sto_crm.delete_inventory(part["id"]), {"deleted": True})
        noop_after_deleted_part = sto_crm.update_order(order["id"], payload)
        self.assertEqual(noop_after_deleted_part["status"], "cancelled")

        reopened = dict(payload)
        reopened["status"] = "in_progress"
        with self.assertRaises(ValueError):
            sto_crm.update_order(order["id"], reopened)
        changed_deleted_part = dict(payload)
        changed_deleted_part["items"] = [
            service_item(100),
            {
                "kind": "part",
                "inventory_id": part["id"],
                "title": "Test part",
                "quantity": 2,
                "unit_price": 50,
                "unit_cost": 20,
            },
        ]
        with self.assertRaisesRegex(ValueError, "повторно открыть или изменить"):
            sto_crm.update_order(order["id"], changed_deleted_part)

        deleted_before_cancel_part = sto_crm.create_inventory(
            {"name": "Legacy deleted stock", "quantity": 1, "price": 30, "cost": 10}
        )
        deleted_before_cancel_order = sto_crm.create_order(
            {
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "status": "closed",
                "priority": "normal",
                "items": [
                    {
                        "kind": "part",
                        "inventory_id": deleted_before_cancel_part["id"],
                        "title": deleted_before_cancel_part["name"],
                        "quantity": 0.5,
                        "unit_price": 30,
                        "unit_cost": 10,
                    },
                ],
            }
        )
        with sto_crm.db() as conn:
            conn.execute(
                "UPDATE inventory SET deleted_at = ? WHERE id = ?",
                (sto_crm.now_iso(), deleted_before_cancel_part["id"]),
            )
        cancel_deleted_payload = {
            "customer_id": customer["id"],
            "vehicle_id": vehicle["id"],
            "status": "cancelled",
            "priority": "normal",
            "items": [
                {
                    "kind": "part",
                    "inventory_id": deleted_before_cancel_part["id"],
                    "title": deleted_before_cancel_part["name"],
                    "quantity": 0.5,
                    "unit_price": 30,
                    "unit_cost": 10,
                },
            ],
        }
        with self.assertRaisesRegex(ValueError, "Восстановите позицию склада"):
            sto_crm.update_order(
                deleted_before_cancel_order["id"], cancel_deleted_payload
            )

    def test_closed_order_survives_when_vehicle_is_soft_deleted(self):
        customer = self.create_customer("Orphan Customer")
        vehicle = self.create_vehicle(customer["id"], "S700SO")
        order = sto_crm.create_order(
            {
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "status": "closed",
                "priority": "normal",
                "items": [service_item(500)],
            }
        )
        # Перевод в отмену освобождает авто от активных заказов на уровне проверок
        # удаления, но закрытый/отменённый заказ должен продолжать открываться.
        sto_crm.update_order(
            order["id"],
            {
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "status": "cancelled",
                "priority": "normal",
                "items": [service_item(500)],
            },
        )
        with sto_crm.db() as conn:
            conn.execute(
                "UPDATE vehicles SET deleted_at = ? WHERE id = ?",
                (sto_crm.now_iso(), vehicle["id"]),
            )
            fetched = sto_crm.get_order(conn, order["id"])
        self.assertEqual(fetched["id"], order["id"])
        self.assertEqual(fetched.get("vehicle_deleted"), 1)
        self.assertIsNone(fetched.get("vehicle_plate"))
        listed = [
            item for item in sto_crm.list_orders("", "all") if item["id"] == order["id"]
        ]
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0].get("vehicle_deleted"), 1)
        self.assertIsNone(listed[0].get("vehicle_plate"))

        # Legacy/manual databases can contain historical orders whose vehicle was
        # soft-deleted outside normal UI rules. Such protected orders must still
        # allow a no-op save so the operator is not trapped in an unreadable card.
        noop = sto_crm.update_order(
            order["id"],
            {
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "status": "cancelled",
                "priority": "normal",
                "items": [service_item(500)],
            },
        )
        self.assertEqual(noop["status"], "cancelled")
        self.assertEqual(noop.get("vehicle_deleted"), 1)

    def test_order_allows_external_part_without_inventory_and_does_not_consume_stock(
        self,
    ):
        customer = self.create_customer("External Part Customer")
        vehicle = self.create_vehicle(customer["id"], "X404XP")
        stock_part = sto_crm.create_inventory(
            {
                "sku": "STOCK",
                "name": "Stock part",
                "quantity": 2,
                "price": 50,
                "cost": 20,
            }
        )

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
                        "inventory_id": stock_part["id"],
                        "title": "Stock part",
                        "quantity": 1,
                        "unit_price": 50,
                        "unit_cost": 20,
                    },
                    {
                        "kind": "part",
                        "title": "External ordered part",
                        "quantity": 2,
                        "unit_price": 75,
                        "unit_cost": 45,
                    },
                ],
            }
        )

        self.assertEqual(order["parts_total"], 200)
        self.assertEqual(order["total"], 300)
        external_item = next(
            item for item in order["items"] if item["title"] == "External ordered part"
        )
        self.assertIsNone(external_item["inventory_id"])
        with sto_crm.db() as conn:
            self.assertEqual(
                sto_crm.get_inventory(conn, stock_part["id"])["quantity"], 1
            )

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
        part = sto_crm.create_inventory(
            {
                "sku": "LOW",
                "name": "Low stock part",
                "quantity": 1,
                "price": 10,
                "cost": 5,
            }
        )

        with self.assertRaisesRegex(ValueError, "Недостаточно"):
            sto_crm.create_order(
                {
                    "customer_id": customer["id"],
                    "vehicle_id": vehicle["id"],
                    "status": "closed",
                    "priority": "normal",
                    "items": [
                        service_item(10),
                        {
                            "kind": "part",
                            "inventory_id": part["id"],
                            "title": part["name"],
                            "quantity": 2,
                            "unit_price": 10,
                            "unit_cost": 5,
                        },
                    ],
                }
            )

        with sto_crm.db() as conn:
            self.assertEqual(sto_crm.get_inventory(conn, part["id"])["quantity"], 1)
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM orders WHERE deleted_at IS NULL"
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM order_items").fetchone()[0], 0
            )

    def test_deleting_entity_soft_deletes_inactive_appointments(self):
        customer = self.create_customer("Inactive Appointment Customer")
        vehicle = self.create_vehicle(customer["id"], "A404PT")
        appointment = sto_crm.create_appointment(
            {
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "scheduled_at": "2099-01-01T10:00",
                "duration_minutes": 60,
                "status": "done",
                "reason": "archived appointment",
            }
        )

        self.assertEqual(sto_crm.delete_vehicle(vehicle["id"]), {"deleted": True})
        self.assertFalse(
            any(
                item["id"] == appointment["id"]
                for item in sto_crm.list_appointments("", "all")
            )
        )
        with sto_crm.db() as conn:
            self.assertTrue(
                conn.execute(
                    "SELECT deleted_at FROM appointments WHERE id = ?",
                    (appointment["id"],),
                ).fetchone()["deleted_at"]
            )

        other_customer = self.create_customer("Inactive Appointment Customer 2")
        other_vehicle = self.create_vehicle(other_customer["id"], "A405PT")
        other_appointment = sto_crm.create_appointment(
            {
                "customer_id": other_customer["id"],
                "vehicle_id": other_vehicle["id"],
                "scheduled_at": "2099-01-02T10:00",
                "duration_minutes": 60,
                "status": "cancelled",
                "reason": "customer archived appointment",
            }
        )
        self.assertEqual(
            sto_crm.delete_customer(other_customer["id"]), {"deleted": True}
        )
        with sto_crm.db() as conn:
            self.assertTrue(
                conn.execute(
                    "SELECT deleted_at FROM appointments WHERE id = ?",
                    (other_appointment["id"],),
                ).fetchone()["deleted_at"]
            )

    def test_entities_with_order_history_are_not_deleted(self):
        customer = self.create_customer("History Customer")
        vehicle = self.create_vehicle(customer["id"], "C003CC")
        part = sto_crm.create_inventory(
            {"name": "History part", "quantity": 1, "price": 10}
        )
        order = sto_crm.create_order(
            {
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "status": "closed",
                "priority": "normal",
                "items": [
                    service_item(10),
                    {
                        "kind": "part",
                        "inventory_id": part["id"],
                        "title": part["name"],
                        "quantity": 1,
                        "unit_price": 10,
                        "unit_cost": 1,
                    },
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

    def test_cancelled_open_order_cannot_be_reopened(self):
        customer = self.create_customer("Cancelled Flow")
        vehicle = self.create_vehicle(customer["id"], "K777AN")
        order = sto_crm.create_order(
            {
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "status": "cancelled",
                "priority": "normal",
                "items": [service_item(25)],
            }
        )
        with self.assertRaisesRegex(ValueError, "нельзя повторно открыть"):
            sto_crm.update_order(
                order["id"],
                {
                    "customer_id": customer["id"],
                    "vehicle_id": vehicle["id"],
                    "status": "in_progress",
                    "priority": "normal",
                    "items": [service_item(25)],
                },
            )
        with self.assertRaisesRegex(ValueError, "нельзя изменить"):
            sto_crm.update_order(
                order["id"],
                {
                    "customer_id": customer["id"],
                    "vehicle_id": vehicle["id"],
                    "status": "cancelled",
                    "priority": "normal",
                    "items": [service_item(30)],
                },
            )
        unchanged = sto_crm.update_order(
            order["id"],
            {
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "status": "cancelled",
                "priority": "normal",
                "items": [service_item(25)],
            },
        )
        self.assertEqual(unchanged["status"], "cancelled")

    def test_order_status_regression_is_rejected(self):
        customer = self.create_customer("Status Flow")
        vehicle = self.create_vehicle(customer["id"], "K778AN")
        order = sto_crm.create_order(
            {
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "status": "done",
                "priority": "normal",
                "items": [service_item(25)],
            }
        )
        with self.assertRaisesRegex(ValueError, "Некорректный переход"):
            sto_crm.update_order(
                order["id"],
                {
                    "customer_id": customer["id"],
                    "vehicle_id": vehicle["id"],
                    "status": "diagnostics",
                    "priority": "normal",
                    "items": [service_item(25)],
                },
            )

    def test_closed_order_must_be_cancelled_before_delete_to_make_stock_return_explicit(
        self,
    ):
        customer = self.create_customer("Void Customer")
        vehicle = self.create_vehicle(customer["id"], "V000ID")
        part = sto_crm.create_inventory(
            {"name": "Void part", "quantity": 2, "price": 10, "cost": 5}
        )
        order = sto_crm.create_order(
            {
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "status": "closed",
                "priority": "normal",
                "items": [
                    service_item(10),
                    {
                        "kind": "part",
                        "inventory_id": part["id"],
                        "title": part["name"],
                        "quantity": 1,
                        "unit_price": 10,
                        "unit_cost": 5,
                    },
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
                {
                    "kind": "part",
                    "inventory_id": part["id"],
                    "title": part["name"],
                    "quantity": 1,
                    "unit_price": 10,
                    "unit_cost": 5,
                },
            ],
        }
        cancelled = sto_crm.update_order(order["id"], payload)
        self.assertEqual(cancelled["status"], "cancelled")
        with sto_crm.db() as conn:
            self.assertEqual(sto_crm.get_inventory(conn, part["id"])["quantity"], 2)

        with self.assertRaisesRegex(ValueError, "нельзя повторно открыть"):
            sto_crm.update_order(order["id"], {**payload, "status": "closed"})
        with sto_crm.db() as conn:
            self.assertEqual(sto_crm.get_inventory(conn, part["id"])["quantity"], 2)

        with self.assertRaisesRegex(ValueError, "закрытой финансовой историей"):
            sto_crm.delete_order(order["id"])
        with sto_crm.db() as conn:
            self.assertEqual(sto_crm.get_inventory(conn, part["id"])["quantity"], 2)
            self.assertEqual(
                sto_crm.get_order(conn, order["id"])["status"], "cancelled"
            )

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
        sto_crm.create_customer(
            {
                "name": "=cmd|' /C calc'!A0",
                "phone": "+7999",
                "email": "",
                "source": "  =cmd|' /C calc'!A0",
                "notes": "-note",
            }
        )
        sto_crm.create_customer({"name": "\u200b =hidden", "phone": "\ufeff =hidden"})
        _filename, content = sto_crm.csv_export("customers")
        self.assertIn("'=cmd|' /C calc'!A0", content)
        self.assertIn("'+7999", content)
        self.assertIn(
            "'=cmd|' /C calc'!A0", content
        )  # clean_text collapses whitespace, csv_cell escapes leading =
        self.assertIn("'-note", content)
        self.assertEqual(sto_crm.csv_cell("\ufeff=hidden"), "'\ufeff=hidden")
        self.assertEqual(sto_crm.csv_cell("\u200b=hidden"), "'\u200b=hidden")
        self.assertEqual(sto_crm.csv_cell("\u200b =hidden"), "'\u200b =hidden")
        self.assertEqual(sto_crm.csv_cell("\ufeff =hidden"), "'\ufeff =hidden")

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
            headers={
                "Content-Type": "application/json",
                "Origin": "http://example.com",
                "X-CSRF-Token": sto_crm.RUNTIME.csrf_token,
                "X-CRM-Access-Token": sto_crm.RUNTIME.access_token,
            },
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
                csp = response.headers["Content-Security-Policy"]
                body = response.read().decode("utf-8")
                self.assertIn("default-src 'self'", csp)
                self.assertIn("style-src 'self' 'nonce-", csp)
                self.assertNotIn("'unsafe-inline'", csp)
                self.assertIn('style nonce="', body)
                self.assertIn(
                    f'data-bootstrap-token="{sto_crm.RUNTIME.bootstrap_token}"', body
                )
                self.assertNotIn("?bootstrap_token=", body)
                self.assertEqual(response.headers["X-Frame-Options"], "DENY")
                self.assertNotIn("Python", response.headers["Server"])
                self.assertEqual(response.headers["Connection"], "close")

            with urllib.request.urlopen(f"{base}/favicon.ico", timeout=5) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(
                    response.headers["Content-Type"], "image/svg+xml; charset=utf-8"
                )
                self.assertIn(b"<svg", response.read())

            favicon_head_request = urllib.request.Request(
                f"{base}/favicon.svg", method="HEAD"
            )
            with urllib.request.urlopen(favicon_head_request, timeout=5) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(
                    response.headers["Content-Type"], "image/svg+xml; charset=utf-8"
                )
                self.assertEqual(response.read(), b"")

            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(f"{base}/api/export/catalog.csv", timeout=5)
            self.assertEqual(error.exception.code, 403)
            error.exception.close()

            export_request = urllib.request.Request(
                f"{base}/api/export/catalog.csv",
                headers={
                    "X-CSRF-Token": sto_crm.RUNTIME.csrf_token,
                    "X-CRM-Access-Token": sto_crm.RUNTIME.access_token,
                },
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

            head_request = urllib.request.Request(f"{base}/api/health", method="HEAD")
            with urllib.request.urlopen(head_request, timeout=5) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(
                    response.headers["Content-Type"], "application/json; charset=utf-8"
                )
                self.assertEqual(response.read(), b"")

            options_request = urllib.request.Request(
                f"{base}/api/health", method="OPTIONS"
            )
            with urllib.request.urlopen(options_request, timeout=5) as response:
                self.assertEqual(response.status, 204)
                self.assertEqual(
                    response.headers["Allow"], "GET, HEAD, POST, PUT, DELETE, OPTIONS"
                )
                self.assertEqual(response.headers["Connection"], "close")

            patch_request = urllib.request.Request(f"{base}/api/health", method="PATCH")
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(patch_request, timeout=5)
            self.assertEqual(error.exception.code, 405)
            self.assertIn("application/json", error.exception.headers["Content-Type"])
            self.assertNotIn("Python", error.exception.headers["Server"])
            error.exception.close()

            cross_origin_options = urllib.request.Request(
                f"{base}/api/health",
                method="OPTIONS",
                headers={"Origin": "http://example.com"},
            )
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(cross_origin_options, timeout=5)
            self.assertEqual(error.exception.code, 403)
            error.exception.close()

            with socket.create_connection(
                ("127.0.0.1", server.server_port), timeout=5
            ) as client:
                client.sendall(
                    (
                        "GET /api/bootstrap HTTP/1.1\r\n"
                        f"Host: evil.example:{server.server_port}\r\n"
                        "Connection: close\r\n"
                        "\r\n"
                    ).encode("ascii")
                )
                response = recv_http_response(client)
            self.assertIn("403", response.splitlines()[0])

            with socket.create_connection(
                ("127.0.0.1", server.server_port), timeout=5
            ) as client:
                client.sendall(
                    (
                        "GET / HTTP/1.1\r\n"
                        f"Host: evil.example:{server.server_port}\r\n"
                        "Connection: close\r\n"
                        "\r\n"
                    ).encode("ascii")
                )
                response = recv_http_response(client)
            self.assertIn("403", response.splitlines()[0])

            with socket.create_connection(
                ("127.0.0.1", server.server_port), timeout=5
            ) as client:
                client.sendall(
                    (
                        "POST /api/backup HTTP/1.1\r\n"
                        f"Host: 127.0.0.1:{server.server_port}\r\n"
                        "Content-Type: application/json\r\n"
                        f"X-CSRF-Token: {sto_crm.RUNTIME.csrf_token}\r\n"
                        f"X-CRM-Access-Token: {sto_crm.RUNTIME.access_token}\r\n"
                        "Content-Length: nope\r\n"
                        "Connection: close\r\n"
                        "\r\n"
                        "{}"
                    ).encode("ascii")
                )
                response = recv_http_response(client)
            self.assertIn("400", response.splitlines()[0])

            with socket.create_connection(
                ("127.0.0.1", server.server_port), timeout=5
            ) as client:
                client.sendall(
                    (
                        "POST /api/backup HTTP/1.1\r\n"
                        f"Host: 127.0.0.1:{server.server_port}\r\n"
                        f"Origin: http://127.0.0.1:{server.server_port + 1}\r\n"
                        "Content-Type: application/json\r\n"
                        f"X-CSRF-Token: {sto_crm.RUNTIME.csrf_token}\r\n"
                        f"X-CRM-Access-Token: {sto_crm.RUNTIME.access_token}\r\n"
                        "Content-Length: 2\r\n"
                        "Connection: close\r\n"
                        "\r\n"
                        "{}"
                    ).encode("ascii")
                )
                response = recv_http_response(client)
            self.assertIn("403", response.splitlines()[0])

            with socket.create_connection(
                ("127.0.0.1", server.server_port), timeout=5
            ) as client:
                client.sendall(
                    (
                        "POST /api/customers HTTP/1.1\r\n"
                        f"Host: 127.0.0.1:{server.server_port}\r\n"
                        "Content-Type: application/json\r\n"
                        f"X-CSRF-Token: {sto_crm.RUNTIME.csrf_token}\r\n"
                        f"X-CRM-Access-Token: {sto_crm.RUNTIME.access_token}\r\n"
                        "Content-Length: 1\r\n"
                        "Connection: close\r\n"
                        "\r\n"
                    ).encode("ascii")
                    + b"\xff"
                )
                response = recv_http_response(client)
            self.assertIn("400", response.splitlines()[0])
            self.assertIn("Некорректный JSON", response)
            self.assertNotIn("codec", response)

            lone_surrogate_body = b'{"name":"\\ud800"}'
            with socket.create_connection(
                ("127.0.0.1", server.server_port), timeout=5
            ) as client:
                client.sendall(
                    (
                        "POST /api/customers HTTP/1.1\r\n"
                        f"Host: 127.0.0.1:{server.server_port}\r\n"
                        "Content-Type: application/json\r\n"
                        f"X-CSRF-Token: {sto_crm.RUNTIME.csrf_token}\r\n"
                        f"X-CRM-Access-Token: {sto_crm.RUNTIME.access_token}\r\n"
                        f"Content-Length: {len(lone_surrogate_body)}\r\n"
                        "Connection: close\r\n"
                        "\r\n"
                    ).encode("ascii")
                    + lone_surrogate_body
                )
                response = recv_http_response(client)
            self.assertIn("400", response.splitlines()[0])
            self.assertIn("Некорректные символы", response)
            self.assertNotIn("codec", response)

            with socket.create_connection(
                ("127.0.0.1", server.server_port), timeout=5
            ) as client:
                client.sendall(
                    (
                        "POST /api/backup HTTP/1.1\r\n"
                        f"Host: 127.0.0.1:{server.server_port}\r\n"
                        f"Origin: http://[::1]:{server.server_port}\r\n"
                        "Content-Type: application/json\r\n"
                        f"X-CSRF-Token: {sto_crm.RUNTIME.csrf_token}\r\n"
                        f"X-CRM-Access-Token: {sto_crm.RUNTIME.access_token}\r\n"
                        "Content-Length: 2\r\n"
                        "Connection: close\r\n"
                        "\r\n"
                        "{}"
                    ).encode("ascii")
                )
                response = recv_http_response(client)
            self.assertNotIn("500", response.splitlines()[0])

            with socket.create_connection(
                ("127.0.0.1", server.server_port), timeout=5
            ) as client:
                body = json.dumps({"name": "Wrong route"}).encode("utf-8")
                client.sendall(
                    (
                        "POST /api/customers/999/extra HTTP/1.1\r\n"
                        f"Host: 127.0.0.1:{server.server_port}\r\n"
                        "Content-Type: application/json\r\n"
                        f"X-CSRF-Token: {sto_crm.RUNTIME.csrf_token}\r\n"
                        f"X-CRM-Access-Token: {sto_crm.RUNTIME.access_token}\r\n"
                        f"Content-Length: {len(body)}\r\n"
                        "Connection: close\r\n"
                        "\r\n"
                    ).encode("ascii")
                    + body
                )
                response = recv_http_response(client)
            self.assertIn("404", response.splitlines()[0])
            self.assertFalse(
                any(
                    customer["name"] == "Wrong route"
                    for customer in sto_crm.list_customers("")
                )
            )

            with socket.create_connection(
                ("127.0.0.1", server.server_port), timeout=5
            ) as client:
                ambiguous_body = json.dumps({"name": "Ambiguous body"}).encode("utf-8")
                client.sendall(
                    (
                        "POST /api/customers HTTP/1.1\r\n"
                        f"Host: 127.0.0.1:{server.server_port}\r\n"
                        "Content-Type: application/json\r\n"
                        f"X-CSRF-Token: {sto_crm.RUNTIME.csrf_token}\r\n"
                        f"X-CRM-Access-Token: {sto_crm.RUNTIME.access_token}\r\n"
                        "Transfer-Encoding: chunked\r\n"
                        f"Content-Length: {len(ambiguous_body)}\r\n"
                        "Connection: close\r\n"
                        "\r\n"
                    ).encode("ascii")
                    + ambiguous_body
                )
                response = recv_http_response(client)
            self.assertIn("400", response.splitlines()[0])
            self.assertIn("Transfer-Encoding", response)
            self.assertFalse(
                any(
                    customer["name"] == "Ambiguous body"
                    for customer in sto_crm.list_customers("")
                )
            )

            with socket.create_connection(
                ("127.0.0.1", server.server_port), timeout=5
            ) as client:
                body = json.dumps({"name": "Missing id"}).encode("utf-8")
                client.sendall(
                    (
                        "PUT /api/customers HTTP/1.1\r\n"
                        f"Host: 127.0.0.1:{server.server_port}\r\n"
                        "Content-Type: application/json\r\n"
                        f"X-CSRF-Token: {sto_crm.RUNTIME.csrf_token}\r\n"
                        f"X-CRM-Access-Token: {sto_crm.RUNTIME.access_token}\r\n"
                        f"Content-Length: {len(body)}\r\n"
                        "Connection: close\r\n"
                        "\r\n"
                    ).encode("ascii")
                    + body
                )
                response = recv_http_response(client)
            self.assertIn("404", response.splitlines()[0])
        finally:
            server.shutdown()
            server.server_close()

    def test_filtered_bootstrap_keeps_full_form_lookups(self):
        customer = self.create_customer("Lookup Customer")
        vehicle = self.create_vehicle(customer["id"], "L777UP")
        part = sto_crm.create_inventory(
            {"name": "Lookup part", "quantity": 5, "price": 10}
        )
        sto_crm.create_order(
            {
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "status": "new",
                "priority": "normal",
                "complaint": "rare-search-token",
                "items": [
                    service_item(10),
                    {
                        "kind": "part",
                        "inventory_id": part["id"],
                        "title": part["name"],
                        "quantity": 1,
                        "unit_price": 10,
                        "unit_cost": 1,
                    },
                ],
            }
        )

        payload = sto_crm.bootstrap_payload("rare-search-token", "all")
        self.assertEqual(len(payload["orders"]), 1)
        self.assertEqual(payload["customers"], [])
        self.assertTrue(
            any(
                item["id"] == customer["id"] for item in payload["lookups"]["customers"]
            )
        )
        self.assertTrue(
            any(item["id"] == vehicle["id"] for item in payload["lookups"]["vehicles"])
        )
        self.assertTrue(
            any(item["id"] == part["id"] for item in payload["lookups"]["inventory"])
        )

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
            [
                {
                    "kind": "service",
                    "title": "Labor",
                    "quantity": 1,
                    "unit_price": 100,
                    "unit_cost": 60,
                }
            ],
        )
        self.assertEqual(totals["subtotal"], 100)
        self.assertEqual(totals["tax"], 18)
        self.assertEqual(totals["total"], 108)
        self.assertEqual(totals["margin"], 30)
        self.assertEqual(totals["margin_percent"], 33.3)

    def test_number_parsers_accept_russian_spacing_and_commas(self):
        self.assertEqual(sto_crm.parse_float("1 500,50"), 1500.5)
        self.assertEqual(sto_crm.parse_float("1\u00a0500,50"), 1500.5)
        self.assertEqual(sto_crm.parse_float("1\u202f500,50"), 1500.5)
        self.assertEqual(sto_crm.parse_float_field("1\u202f500,50", "сумма"), 1500.5)
        self.assertEqual(sto_crm.parse_int("12 345,9"), 12345)
        self.assertEqual(sto_crm.parse_int_field("12\u202f345", "пробег"), 12345)

    def test_integer_field_rejects_bool_values(self):
        customer = self.create_customer("Bool IDs")
        for value in (True, False):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "клиент"):
                    sto_crm.create_vehicle({"customer_id": value, "make": "BoolCar"})
        with self.assertRaisesRegex(ValueError, "целое"):
            sto_crm.parse_int_field(True, "идентификатор")
        self.assertEqual(sto_crm.parse_bool_field(True, "согласие"), 1)
        self.assertTrue(customer["id"])

    def test_numeric_fields_reject_sqlite_overflow_and_financial_overflow(self):
        with self.assertRaisesRegex(ValueError, "целое"):
            sto_crm.parse_int_field(str(2**63), "идентификатор")
        with self.assertRaisesRegex(ValueError, "число"):
            sto_crm.parse_float_field("1e309", "сумма")
        with self.assertRaisesRegex(ValueError, "число"):
            sto_crm.parse_float_field("1e13", "сумма")

        customer = self.create_customer("Huge Numbers")
        vehicle = self.create_vehicle(customer["id"], "H999UG")
        with self.assertRaisesRegex(ValueError, "финансовое"):
            sto_crm.create_order(
                {
                    "customer_id": customer["id"],
                    "vehicle_id": vehicle["id"],
                    "status": "new",
                    "priority": "normal",
                    "items": [
                        {
                            "kind": "service",
                            "title": "Huge",
                            "quantity": 1_000_000_000_000,
                            "unit_price": 10,
                        }
                    ],
                }
            )
        with self.assertRaisesRegex(ValueError, "себестоимость"):
            sto_crm.create_order(
                {
                    "customer_id": customer["id"],
                    "vehicle_id": vehicle["id"],
                    "status": "new",
                    "priority": "normal",
                    "items": [
                        {
                            "kind": "service",
                            "title": "Huge cost",
                            "quantity": 1_000_000_000_000,
                            "unit_price": 0.01,
                            "unit_cost": 1_000_000_000_000,
                        }
                    ],
                }
            )

        totals = sto_crm.calculate_totals(
            {},
            [
                {
                    "kind": "service",
                    "title": "Legacy huge",
                    "quantity": math.inf,
                    "unit_price": 1,
                }
            ],
        )
        self.assertEqual(totals["total"], 0)

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
        self.assertFalse(
            any(
                item["status"] == "done"
                for item in sto_crm.list_appointments("", "all", None)
            )
        )

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
        self.assertFalse(
            any(
                item["status"] == "cancelled"
                for item in sto_crm.list_appointments("", "all", None)
            )
        )

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
            sto_crm.create_customer(
                {"name": "Bad Channel", "preferred_channel": "pager"}
            )
        for consent in (-1, 2, "2", "maybe"):
            with self.subTest(consent=consent):
                with self.assertRaisesRegex(ValueError, "согласие"):
                    sto_crm.create_customer(
                        {"name": "Bad Consent", "reminder_consent": consent}
                    )
        with self.assertRaisesRegex(ValueError, "приоритет"):
            sto_crm.create_order(
                {
                    "customer_id": customer["id"],
                    "vehicle_id": vehicle["id"],
                    "status": "new",
                    "priority": "panic",
                    "items": [service_item(10)],
                }
            )
        with self.assertRaisesRegex(ValueError, "статус записи"):
            sto_crm.create_appointment(
                {
                    "customer_id": customer["id"],
                    "vehicle_id": vehicle["id"],
                    "scheduled_at": "2099-03-01T10:00",
                    "status": "maybe",
                }
            )
        with self.assertRaisesRegex(ValueError, "тип позиции"):
            sto_crm.create_order(
                {
                    "customer_id": customer["id"],
                    "vehicle_id": vehicle["id"],
                    "status": "new",
                    "priority": "normal",
                    "items": [{"kind": "fee", "title": "Bad", "quantity": 1}],
                }
            )

    def test_malformed_items_are_rejected_as_validation_errors(self):
        customer = self.create_customer("Malformed Items")
        vehicle = self.create_vehicle(customer["id"], "M001AL")
        with self.assertRaisesRegex(ValueError, "Позиция заказ-наряда"):
            sto_crm.create_order(
                {
                    "customer_id": customer["id"],
                    "vehicle_id": vehicle["id"],
                    "status": "new",
                    "priority": "normal",
                    "items": [123],
                }
            )

    def test_user_numeric_fields_reject_garbage_instead_of_defaulting(self):
        customer = self.create_customer("Strict Numbers")
        vehicle = self.create_vehicle(customer["id"], "N001UM")
        with self.assertRaisesRegex(ValueError, "скидка"):
            sto_crm.create_order(
                {
                    "customer_id": customer["id"],
                    "vehicle_id": vehicle["id"],
                    "status": "new",
                    "priority": "normal",
                    "discount": "abc",
                    "items": [service_item(10)],
                }
            )
        with self.assertRaisesRegex(ValueError, "длительность"):
            sto_crm.create_appointment(
                {
                    "customer_id": customer["id"],
                    "vehicle_id": vehicle["id"],
                    "scheduled_at": "2099-03-01T10:00",
                    "duration_minutes": "abc",
                    "status": "scheduled",
                }
            )
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
            conn.execute(
                """
                INSERT INTO orders(number, customer_id, status, priority, created_at, updated_at)
                VALUES (?, ?, 'new', 'normal', ?, ?)
                """,
                (f"{today_prefix}-9999999", customer_id, stamp, stamp),
            )
            conn.execute(
                """
                INSERT INTO orders(number, customer_id, status, priority, created_at, updated_at)
                VALUES (?, ?, 'new', 'normal', ?, ?)
                """,
                (f"{today_prefix}-100", customer_id, stamp, stamp),
            )
            number = sto_crm.generate_order_number(conn)
        self.assertEqual(number, f"{today_prefix}-101")

    def test_order_number_skips_legacy_seven_digit_collision(self):
        today_prefix = sto_crm.datetime.now().strftime("СТО-%Y%m%d")
        stamp = sto_crm.now_iso()
        with sto_crm.db() as conn:
            conn.execute(
                """
                INSERT INTO customers(name, phone, email, source, notes, created_at, updated_at)
                VALUES ('Number Collision Customer', '', '', '', '', ?, ?)
                """,
                (stamp, stamp),
            )
            customer_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
            conn.executemany(
                """
                INSERT INTO orders(number, customer_id, status, priority, created_at, updated_at)
                VALUES (?, ?, 'new', 'normal', ?, ?)
                """,
                [
                    (f"{today_prefix}-999999", customer_id, stamp, stamp),
                    (f"{today_prefix}-1000000", customer_id, stamp, stamp),
                ],
            )
            number = sto_crm.generate_order_number(conn)
        self.assertEqual(number, f"{today_prefix}-1000001")

    def test_order_search_does_not_match_soft_deleted_vehicle_fields(self):
        customer = self.create_customer("Deleted Vehicle Search")
        vehicle = self.create_vehicle(customer["id"], "H777ID")
        order = sto_crm.create_order(
            {
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "status": "closed",
                "priority": "normal",
                "items": [service_item(10)],
            }
        )
        with sto_crm.db() as conn:
            conn.execute(
                "UPDATE vehicles SET deleted_at = ? WHERE id = ?",
                (sto_crm.now_iso(), vehicle["id"]),
            )
        self.assertEqual(sto_crm.list_orders("H777ID", "all"), [])
        listed = [
            item
            for item in sto_crm.list_orders("Deleted Vehicle Search", "all")
            if item["id"] == order["id"]
        ]
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["vehicle_deleted"], 1)
        self.assertIsNone(listed[0]["vehicle_plate"])

    def test_closed_order_identity_and_stock_are_protected(self):
        first = self.create_customer("Closed First")
        second = self.create_customer("Closed Second")
        vehicle = self.create_vehicle(first["id"], "C101LO")
        other_vehicle = self.create_vehicle(second["id"], "C102LO")
        part = sto_crm.create_inventory(
            {
                "sku": "LOCK",
                "name": "Locked part",
                "quantity": 5,
                "price": 10,
                "cost": 5,
            }
        )
        payload = {
            "customer_id": first["id"],
            "vehicle_id": vehicle["id"],
            "status": "closed",
            "priority": "normal",
            "items": [
                service_item(10),
                {
                    "kind": "part",
                    "inventory_id": part["id"],
                    "title": part["name"],
                    "quantity": 1,
                    "unit_price": 10,
                    "unit_cost": 5,
                },
            ],
        }
        order = sto_crm.create_order(payload)

        changed_owner = {
            **payload,
            "customer_id": second["id"],
            "vehicle_id": other_vehicle["id"],
        }
        with self.assertRaisesRegex(ValueError, "перепривязать"):
            sto_crm.update_order(order["id"], changed_owner)

        changed_qty = {
            **payload,
            "items": [
                service_item(10),
                {
                    "kind": "part",
                    "inventory_id": part["id"],
                    "title": part["name"],
                    "quantity": 2,
                    "unit_price": 10,
                    "unit_cost": 5,
                },
            ],
        }
        with self.assertRaisesRegex(ValueError, "Финансовые данные"):
            sto_crm.update_order(order["id"], changed_qty)

        changed_price = {
            **payload,
            "items": [
                service_item(999),
                {
                    "kind": "part",
                    "inventory_id": part["id"],
                    "title": part["name"],
                    "quantity": 1,
                    "unit_price": 99,
                    "unit_cost": 5,
                },
            ],
        }
        with self.assertRaisesRegex(ValueError, "Финансовые данные"):
            sto_crm.update_order(order["id"], changed_price)
        reopened_payload = {
            **payload,
            "status": "in_progress",
            "items": payload["items"],
        }
        with self.assertRaisesRegex(ValueError, "оставить закрытым или отменить"):
            sto_crm.update_order(order["id"], reopened_payload)

        with sto_crm.db() as conn:
            unchanged = sto_crm.get_order(conn, order["id"])
            self.assertEqual(unchanged["status"], "closed")
            self.assertEqual(sto_crm.get_inventory(conn, part["id"])["quantity"], 4)
        self.assertEqual(unchanged["total"], order["total"])

        with self.assertRaisesRegex(ValueError, "закрытых заказах"):
            sto_crm.update_inventory(
                part["id"],
                {
                    "sku": "LOCK",
                    "name": "Locked part",
                    "quantity": 20,
                    "price": 10,
                    "cost": 5,
                },
            )

        allowed = sto_crm.update_inventory(
            part["id"],
            {
                "sku": "LOCK-NEW",
                "name": "Locked part renamed",
                "quantity": 4,
                "price": 12,
                "cost": 6,
            },
        )
        self.assertEqual(allowed["sku"], "LOCK-NEW")
        self.assertEqual(allowed["quantity"], 4)

        cancelled_payload = {
            **payload,
            "status": "cancelled",
            "items": payload["items"],
        }
        sto_crm.update_order(order["id"], cancelled_payload)
        adjusted = sto_crm.update_inventory(
            part["id"],
            {
                "sku": "LOCK-NEW",
                "name": "Locked part renamed",
                "quantity": 20,
                "price": 12,
                "cost": 6,
            },
        )
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

            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(f"{base}/api/bootstrap", timeout=5)
            self.assertEqual(error.exception.code, 403)
            error.exception.close()

            with urllib.request.urlopen(
                f"{base}/api/bootstrap?bootstrap_token={sto_crm.RUNTIME.bootstrap_token}",
                timeout=5,
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(payload["app"]["csrf_token"], sto_crm.RUNTIME.csrf_token)
            self.assertEqual(
                payload["app"]["access_token"], sto_crm.RUNTIME.access_token
            )
            self.assertNotEqual(
                payload["app"]["access_token"], sto_crm.RUNTIME.bootstrap_token
            )
            self.assertEqual(payload["app"]["db_path"], sto_crm.RUNTIME.db_path.name)
            self.assertEqual(
                payload["app"]["db_directory"],
                sto_crm.display_path(sto_crm.RUNTIME.db_path.parent),
            )
            self.assertNotIn(
                str(sto_crm.RUNTIME.db_path.parent), payload["app"]["db_directory"]
            )

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
                f"{base}/api/backup",
                data=json.dumps({}).encode("utf-8"),
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "X-CSRF-Token": sto_crm.RUNTIME.csrf_token,
                    "X-CRM-Access-Token": sto_crm.RUNTIME.access_token,
                },
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                backup_payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(response.status, 200)
            self.assertNotIn("path", backup_payload)
            self.assertIn("display_path", backup_payload)
            self.assertIn("filename", backup_payload)
            self.assertIn("created_at", backup_payload)

            request = urllib.request.Request(
                f"{base}/api/customers",
                data=json.dumps({"name": "HTTP Customer"}).encode("utf-8"),
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "X-CSRF-Token": sto_crm.RUNTIME.csrf_token,
                    "X-CRM-Access-Token": sto_crm.RUNTIME.access_token,
                },
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                created = json.loads(response.read().decode("utf-8"))
            self.assertEqual(response.status, 201)
            self.assertEqual(created["name"], "HTTP Customer")
        finally:
            server.shutdown()
            server.server_close()

    def test_sensitive_query_tokens_are_redacted_from_logs(self):
        message = "GET /print/order/1?token=super-secret&csrf_token=other HTTP/1.1"
        redacted = sto_crm.redact_sensitive_query(message)
        self.assertNotIn("super-secret", redacted)
        self.assertNotIn("other", redacted)
        self.assertIn("token=***", redacted)
        self.assertIn("csrf_token=***", redacted)
        self.assertNotIn(
            "url-secret",
            sto_crm.redact_sensitive_query("GET /?bootstrap_token=url-secret HTTP/1.1"),
        )
        self.assertNotIn(
            "api-secret",
            sto_crm.redact_sensitive_query("GET /?access_token=api-secret HTTP/1.1"),
        )

    def test_create_server_binds_without_separate_port_probe(self):
        server = sto_crm.create_server(0)
        try:
            self.assertGreater(server.server_port, 0)
            self.assertEqual(server.server_address[0], "127.0.0.1")
        finally:
            server.server_close()

    def test_host_cli_argument_accepts_only_loopback_addresses(self):
        args = sto_crm.parse_args(
            ["--host", "127.0.0.1", "--port", "0", "--no-browser"]
        )
        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.port, 0)
        old_parse_args = sto_crm.parse_args
        try:
            captured = []
            sto_crm.parse_args = lambda argv: (
                captured.append(list(argv))
                or (_ for _ in ()).throw(RuntimeError("stop"))
            )
            with self.assertRaisesRegex(RuntimeError, "stop"):
                sto_crm.main([])
            self.assertEqual(captured, [[]])
        finally:
            sto_crm.parse_args = old_parse_args
        self.assertEqual(sto_crm.parse_args(["--host", "localhost"]).host, "127.0.0.1")
        self.assertEqual(sto_crm.parse_args(["--host", "::1"]).host, "::1")
        explicit_db = Path(self.tempdir.name) / "explicit.sqlite3"
        self.assertEqual(sto_crm.parse_args(["--db", str(explicit_db)]).db, explicit_db)
        self.assertEqual(
            sto_crm.parse_args(["--db", self.tempdir.name]).db,
            Path(self.tempdir.name) / "sto_crm.sqlite3",
        )
        self.assertEqual(
            sto_crm.parse_args(["--db", f"{self.tempdir.name}/new-dir/"]).db,
            Path(self.tempdir.name) / "new-dir" / "sto_crm.sqlite3",
        )
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
            sto_crm.create_vehicle(
                {
                    "customer_id": customer["id"],
                    "make": "Lexus",
                    "plate": "U002NI",
                    "vin": vehicle["vin"],
                }
            )
        with self.assertRaisesRegex(ValueError, "госномером"):
            sto_crm.create_vehicle(
                {
                    "customer_id": customer["id"],
                    "make": "Lexus",
                    "plate": vehicle["plate"],
                    "vin": "JTDKN3DU0A0000002",
                }
            )
        first_part = sto_crm.create_inventory(
            {"sku": "UNIQ", "name": "First unique", "quantity": 1}
        )
        self.assertEqual(first_part["sku"], "UNIQ")
        with self.assertRaisesRegex(ValueError, "артикулом"):
            sto_crm.create_inventory(
                {"sku": "uniq", "name": "Second unique", "quantity": 1}
            )

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
        sto_crm.RUNTIME = sto_crm.Runtime(
            legacy_db,
            time.time(),
            "legacy-token",
            "legacy-access-token",
            "legacy-bootstrap-token",
        )
        try:
            sto_crm.init_db()
            migrated = sqlite3.connect(legacy_db)
            migrated.create_function(
                "CASEFOLD",
                1,
                lambda value: str(value or "").casefold(),
                deterministic=True,
            )
            try:
                rows = migrated.execute(
                    "SELECT sku, notes FROM inventory ORDER BY id"
                ).fetchall()
                indexes = {
                    row[1]
                    for row in migrated.execute(
                        "PRAGMA index_list(inventory)"
                    ).fetchall()
                }
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

    def test_legacy_order_number_migration_avoids_second_order_collision(self):
        current_runtime = sto_crm.RUNTIME
        legacy_db = Path(self.tempdir.name) / "legacy-order-number-collision.sqlite3"
        conn = sqlite3.connect(legacy_db)
        try:
            conn.execute(
                """
                CREATE TABLE customers(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    deleted_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE orders(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    number TEXT NOT NULL DEFAULT '',
                    customer_id INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'new',
                    priority TEXT NOT NULL DEFAULT 'normal',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    deleted_at TEXT
                )
                """
            )
            conn.execute("INSERT INTO customers(id, name) VALUES (1, 'Legacy')")
            conn.executemany(
                "INSERT INTO orders(id, number, customer_id) VALUES (?, ?, 1)",
                [(1, "DUP"), (2, "DUP"), (3, "DUP-000002")],
            )
            conn.commit()
        finally:
            conn.close()
        sto_crm.RUNTIME = sto_crm.Runtime(
            legacy_db,
            time.time(),
            "legacy-token",
            "legacy-access-token",
            "legacy-bootstrap-token",
        )
        try:
            sto_crm.init_db()
            migrated = sqlite3.connect(legacy_db)
            try:
                numbers = [
                    row[0]
                    for row in migrated.execute(
                        "SELECT number FROM orders ORDER BY id"
                    ).fetchall()
                ]
                duplicate_count = migrated.execute(
                    """
                    SELECT COUNT(*)
                    FROM (
                        SELECT number FROM orders GROUP BY number HAVING COUNT(*) > 1
                    )
                    """
                ).fetchone()[0]
            finally:
                migrated.close()
            self.assertEqual(numbers, ["DUP", "DUP-000002-2", "DUP-000002"])
            self.assertEqual(duplicate_count, 0)
        finally:
            sto_crm.RUNTIME = current_runtime

    def test_backup_creates_readable_sqlite_copy(self):
        customer = self.create_customer("Backup Customer")
        result = sto_crm.create_backup()
        backup_path = Path(result["path"])
        self.assertTrue(backup_path.exists())
        self.assertGreater(result["size"], 0)
        self.assertEqual(backup_path.parent.name, "backups")
        if os.name != "nt":
            self.assertEqual(backup_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(backup_path.parent.stat().st_mode & 0o777, 0o700)
        conn = sqlite3.connect(backup_path)
        try:
            row = conn.execute(
                "SELECT name FROM customers WHERE id=?", (customer["id"],)
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row[0], "Backup Customer")

    def test_bootstrap_backup_metadata_does_not_expose_absolute_path(self):
        result = sto_crm.create_backup()
        payload = sto_crm.bootstrap_payload()
        backup = payload["app"]["last_backup"]
        self.assertIsNotNone(backup)
        self.assertNotIn("path", backup)
        self.assertEqual(backup["filename"], Path(result["path"]).name)
        self.assertEqual(payload["app"]["last_backup_at"], backup["created_at"])
        self.assertNotIn(str(Path(self.tempdir.name)), backup["display_path"])

    def test_backup_retention_prunes_oldest_files(self):
        backup_dir = Path(self.tempdir.name) / "backups"
        backup_dir.mkdir()
        for index in range(sto_crm.config.MAX_BACKUP_FILES + 2):
            backup = backup_dir / f"sto_crm_backup_20240101_0000{index:02d}.sqlite3"
            backup.write_bytes(b"old")
            os.utime(backup, (index, index))

        sto_crm.updates.prune_backups(backup_dir)

        backups = sorted(backup_dir.glob("sto_crm_backup_*.sqlite3"))
        self.assertLessEqual(len(backups), sto_crm.config.MAX_BACKUP_FILES)
        self.assertFalse(
            (backup_dir / "sto_crm_backup_20240101_000000.sqlite3").exists()
        )

    def test_backup_metadata_ignores_symlink_backups(self):
        if not hasattr(os, "symlink"):
            self.skipTest("symlink is not available on this platform")
        backup_dir = Path(self.tempdir.name) / "backups"
        backup_dir.mkdir()
        outside = Path(self.tempdir.name) / "outside.sqlite3"
        outside.write_bytes(b"not a real backup")
        symlink = backup_dir / "sto_crm_backup_20990101_000000_000000.sqlite3"
        try:
            os.symlink(outside, symlink)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlink creation is not available: {exc}")

        self.assertIsNone(sto_crm.latest_backup_info())
        sto_crm.updates.prune_backups(backup_dir)
        self.assertTrue(symlink.is_symlink())
        self.assertTrue(outside.exists())

    def test_backup_creation_rejects_symlink_backup_directory(self):
        if not hasattr(os, "symlink"):
            self.skipTest("symlink is not available on this platform")
        backup_dir = Path(self.tempdir.name) / "backups"
        outside = Path(self.tempdir.name) / "outside-backups"
        outside.mkdir()
        try:
            os.symlink(outside, backup_dir)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlink creation is not available: {exc}")

        with self.assertRaisesRegex(RuntimeError, "резервную копию"):
            sto_crm.create_backup()
        self.assertEqual(list(outside.iterdir()), [])

    def test_backup_reports_filesystem_errors_as_runtime_error(self):
        old_runtime = sto_crm.RUNTIME
        blocker = Path(self.tempdir.name) / "not-a-directory"
        blocker.write_text("blocked", encoding="utf-8")
        sto_crm.RUNTIME = sto_crm.Runtime(
            blocker / "db.sqlite3",
            time.time(),
            "test-csrf-token",
            "test-access-token",
            "test-bootstrap-token",
        )
        try:
            with self.assertRaisesRegex(RuntimeError, "резервную копию"):
                sto_crm.create_backup()
        finally:
            sto_crm.RUNTIME = old_runtime

    def test_order_search_includes_customer_phone_email_and_vehicle_vin(self):
        customer = sto_crm.create_customer(
            {
                "name": "Search Customer",
                "phone": "123-45-67",
                "email": "phone-search@example.ru",
            }
        )
        vehicle = sto_crm.create_vehicle(
            {
                "customer_id": customer["id"],
                "make": "Toyota",
                "model": "Camry",
                "vin": "JTDKN3DU0A0000999",
            }
        )
        order = sto_crm.create_order(
            {
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "status": "new",
                "priority": "normal",
                "items": [service_item(10)],
            }
        )
        self.assertTrue(
            any(
                item["id"] == order["id"]
                for item in sto_crm.list_orders("123-45-67", "all")
            )
        )
        self.assertTrue(
            any(
                item["id"] == order["id"]
                for item in sto_crm.list_orders("phone-search@example", "all")
            )
        )
        self.assertTrue(
            any(
                item["id"] == order["id"]
                for item in sto_crm.list_orders("0000999", "all")
            )
        )

    def test_search_treats_like_wildcards_as_literal_text(self):
        percent_customer = sto_crm.create_customer({"name": "Literal 100% Customer"})
        underscore_customer = sto_crm.create_customer(
            {"name": "Literal ABC_DEF Customer"}
        )
        plain_customer = sto_crm.create_customer({"name": "Literal Plain Customer"})

        percent_ids = {customer["id"] for customer in sto_crm.list_customers("100%")}
        underscore_ids = {
            customer["id"] for customer in sto_crm.list_customers("ABC_DEF")
        }

        self.assertIn(percent_customer["id"], percent_ids)
        self.assertNotIn(plain_customer["id"], percent_ids)
        self.assertIn(underscore_customer["id"], underscore_ids)
        self.assertNotIn(plain_customer["id"], underscore_ids)

    def test_invalid_bootstrap_status_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "статус"):
            sto_crm.bootstrap_payload("", "bad-status")

    def test_open_order_revenue_does_not_pollute_vip_segment(self):
        customer = self.create_customer("Zero Revenue Customer")
        vehicle = self.create_vehicle(customer["id"], "Z000RO")
        for _ in range(2):
            sto_crm.create_order(
                {
                    "customer_id": customer["id"],
                    "vehicle_id": vehicle["id"],
                    "status": "new",
                    "priority": "normal",
                    "items": [
                        {
                            "kind": "service",
                            "title": "Pipeline check",
                            "quantity": 1,
                            "unit_price": 100000,
                        }
                    ],
                }
            )

        reports = sto_crm.bootstrap_payload()["reports"]
        self.assertFalse(
            any(
                item["customer_id"] == customer["id"]
                for item in reports["vip_customers"]
            )
        )

        for _ in range(2):
            sto_crm.create_order(
                {
                    "customer_id": customer["id"],
                    "vehicle_id": vehicle["id"],
                    "status": "closed",
                    "priority": "normal",
                    "items": [
                        {
                            "kind": "service",
                            "title": "Paid service",
                            "quantity": 1,
                            "unit_price": 100,
                        }
                    ],
                }
            )
        reports = sto_crm.bootstrap_payload()["reports"]
        self.assertTrue(
            any(
                item["customer_id"] == customer["id"]
                for item in reports["vip_customers"]
            )
        )

    def test_reports_count_all_upcoming_appointments_not_only_preview(self):
        customer = self.create_customer("Upcoming Count Customer")
        tomorrow = (sto_crm.datetime.now() + sto_crm.timedelta(days=1)).replace(
            microsecond=0
        )
        for index in range(10):
            sto_crm.create_appointment(
                {
                    "customer_id": customer["id"],
                    "scheduled_at": (
                        tomorrow + sto_crm.timedelta(hours=index)
                    ).isoformat(timespec="minutes"),
                    "duration_minutes": 30,
                    "status": "scheduled",
                }
            )

        reports = sto_crm.bootstrap_payload()["reports"]
        self.assertEqual(reports["appointments_upcoming_count"], 10)
        self.assertEqual(len(reports["appointments_upcoming"]), 8)

    def test_reports_count_all_customers_and_top_services_use_closed_sales(self):
        customer_with_open_order = self.create_customer("Open report customer")
        customer_without_orders = self.create_customer("No orders report customer")
        vehicle = self.create_vehicle(customer_with_open_order["id"], "R001PT")
        sto_crm.create_order(
            {
                "customer_id": customer_with_open_order["id"],
                "vehicle_id": vehicle["id"],
                "status": "new",
                "priority": "normal",
                "items": [
                    {
                        "kind": "service",
                        "title": "Draft-only service",
                        "quantity": 1,
                        "unit_price": 999,
                    }
                ],
            }
        )
        sto_crm.create_order(
            {
                "customer_id": customer_with_open_order["id"],
                "vehicle_id": vehicle["id"],
                "status": "closed",
                "priority": "normal",
                "items": [
                    {
                        "kind": "service",
                        "title": "Closed service",
                        "quantity": 1,
                        "unit_price": 100,
                    }
                ],
            }
        )

        reports = sto_crm.bootstrap_payload()["reports"]
        self.assertGreaterEqual(reports["customers_total"], 2)
        self.assertEqual(
            reports["customers_total"],
            len([customer_with_open_order, customer_without_orders]),
        )
        top_service_titles = [item["title"] for item in reports["top_services"]]
        self.assertIn("Closed service", top_service_titles)
        self.assertNotIn("Draft-only service", top_service_titles)

    def test_crud_writes_persist_after_reopening_connection(self):
        customer = sto_crm.create_customer(
            {"name": "Persistent Customer", "phone": "+7000"}
        )
        vehicle = sto_crm.create_vehicle(
            {"customer_id": customer["id"], "make": "Toyota", "model": "Camry"}
        )
        part = sto_crm.create_inventory(
            {"name": "Persistent Part", "quantity": 2, "price": 10}
        )
        order = sto_crm.create_order(
            {
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "status": "new",
                "priority": "normal",
                "items": [
                    service_item(10),
                    {"kind": "part", "inventory_id": part["id"], "quantity": 1},
                ],
            }
        )

        conn = sto_crm.connect()
        try:
            self.assertEqual(
                conn.execute(
                    "SELECT name FROM customers WHERE id=?", (customer["id"],)
                ).fetchone()["name"],
                "Persistent Customer",
            )
            self.assertEqual(
                conn.execute(
                    "SELECT make FROM vehicles WHERE id=?", (vehicle["id"],)
                ).fetchone()["make"],
                "Toyota",
            )
            self.assertEqual(
                conn.execute(
                    "SELECT name FROM inventory WHERE id=?", (part["id"],)
                ).fetchone()["name"],
                "Persistent Part",
            )
            self.assertEqual(
                conn.execute(
                    "SELECT number FROM orders WHERE id=?", (order["id"],)
                ).fetchone()["number"],
                order["number"],
            )
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM order_items WHERE order_id=?", (order["id"],)
                ).fetchone()[0],
                2,
            )
        finally:
            conn.close()

    def test_reports_expose_executive_pipeline_workload_and_procurement(self):
        customer = self.create_customer("Executive Customer")
        vehicle = self.create_vehicle(customer["id"], "E111EE")
        part = sto_crm.create_inventory(
            {
                "sku": "LOW-EXEC",
                "name": "Low executive part",
                "quantity": 0,
                "min_quantity": 2,
                "price": 100,
                "cost": 60,
            }
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
                "scheduled_at": (sto_crm.datetime.now() + sto_crm.timedelta(days=2))
                .replace(hour=9, minute=0, second=0, microsecond=0)
                .isoformat(timespec="minutes"),
                "status": "confirmed",
            }
        )

        ignored_part = sto_crm.create_inventory(
            {
                "sku": "ZERO-MIN",
                "name": "Zero minimum part",
                "quantity": 0,
                "min_quantity": 0,
                "price": 50,
                "cost": 25,
            }
        )

        reports = sto_crm.bootstrap_payload()["reports"]
        listed_inventory = {
            item["id"]: item for item in sto_crm.list_inventory("", None)
        }
        self.assertEqual(listed_inventory[ignored_part["id"]]["is_low"], 0)
        self.assertFalse(
            any(
                item["id"] == ignored_part["id"] for item in reports["procurement_plan"]
            )
        )
        self.assertGreaterEqual(reports["business_health_score"], 0)
        self.assertIn(
            reports["business_health_label"], {"Отлично", "Контроль", "Риски"}
        )
        self.assertGreaterEqual(reports["pipeline_value"], order["total"])
        self.assertTrue(
            any(item["id"] == order["id"] for item in reports["overdue_orders"])
        )
        self.assertTrue(
            any(
                column["status"] == "in_progress" and column["count"] >= 1
                for column in reports["pipeline_by_status"]
            )
        )
        self.assertTrue(
            any(
                item["name"] == "Мастер А" and item["overdue_count"] >= 1
                for item in reports["workload_by_responsible"]
            )
        )
        self.assertTrue(
            any(
                item["id"] == part["id"] and item["reorder_quantity"] >= 2
                for item in reports["procurement_plan"]
            )
        )
        self.assertTrue(
            any(
                day["appointments"]
                and day["appointments"][0]["id"] == appointment["id"]
                for day in reports["appointment_load_7_days"]
            )
        )
        self.assertGreaterEqual(reports["action_plan_total"], 2)
        self.assertTrue(
            any(
                item["type"] == "overdue_order" and item["record_id"] == order["id"]
                for item in reports["action_plan"]
            )
        )
        self.assertTrue(
            any(
                item["type"] == "procurement" and item["record_id"] == part["id"]
                for item in reports["action_plan"]
            )
        )
        self.assertTrue(
            all(
                "priority_label" in item and "route" in item and "cta" in item
                for item in reports["action_plan"]
            )
        )

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
                customer_id = int(
                    conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                )
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
            self.assertEqual(
                reports["status_counts"]["closed"], sto_crm.LOOKUP_LIMIT + 2
            )
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
            f"http://127.0.0.1:{server.server_port}/print/order/{order['id']}",
            headers={
                "Origin": "http://example.com",
                "X-CSRF-Token": sto_crm.RUNTIME.csrf_token,
                "X-CRM-Access-Token": sto_crm.RUNTIME.access_token,
            },
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
            headers={
                "Content-Type": "application/json",
                "X-CSRF-Token": sto_crm.RUNTIME.csrf_token,
                "X-CRM-Access-Token": sto_crm.RUNTIME.access_token,
            },
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

    def test_truncated_json_body_is_rejected_before_mutation(self):
        server = sto_crm.CRMServer(("127.0.0.1", 0), sto_crm.CRMHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with socket.create_connection(
                ("127.0.0.1", server.server_port), timeout=5
            ) as client:
                client.sendall(
                    (
                        "POST /api/backup HTTP/1.1\r\n"
                        f"Host: 127.0.0.1:{server.server_port}\r\n"
                        "Content-Type: application/json\r\n"
                        f"X-CSRF-Token: {sto_crm.RUNTIME.csrf_token}\r\n"
                        f"X-CRM-Access-Token: {sto_crm.RUNTIME.access_token}\r\n"
                        "Content-Length: 100\r\n"
                        "Connection: close\r\n"
                        "\r\n"
                        "{}"
                    ).encode("ascii")
                )
                client.shutdown(socket.SHUT_WR)
                response = recv_http_response(client)
            self.assertIn("408", response.splitlines()[0])
            self.assertIsNone(sto_crm.latest_backup_info())
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

    def test_inventory_quantity_can_change_when_closed_history_is_not_billable(self):
        customer = self.create_customer("Non Billable Inventory")
        vehicle = self.create_vehicle(customer["id"], "B001NB")
        part = sto_crm.create_inventory(
            {
                "sku": "NOBILL",
                "name": "Not billable",
                "quantity": 5,
                "price": 20,
                "cost": 10,
            }
        )
        order = sto_crm.create_order(
            {
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "status": "closed",
                "priority": "normal",
                "items": [
                    service_item(10),
                    {
                        "kind": "part",
                        "inventory_id": part["id"],
                        "title": part["name"],
                        "approval_status": "deferred",
                        "quantity": 1,
                        "unit_price": 20,
                        "unit_cost": 10,
                    },
                ],
            }
        )
        self.assertEqual(order["parts_total"], 0)
        updated = sto_crm.update_inventory(
            part["id"],
            {
                "sku": "NOBILL",
                "name": "Not billable",
                "quantity": 7,
                "price": 20,
                "cost": 10,
            },
        )
        self.assertEqual(updated["quantity"], 7)
        with self.assertRaisesRegex(ValueError, "активных"):
            sto_crm.delete_inventory(part["id"])
        sto_crm.update_order(
            order["id"],
            {
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "status": "cancelled",
                "priority": "normal",
                "items": [
                    service_item(10),
                    {
                        "kind": "part",
                        "inventory_id": part["id"],
                        "title": part["name"],
                        "approval_status": "deferred",
                        "quantity": 1,
                        "unit_price": 20,
                        "unit_cost": 10,
                    },
                ],
            },
        )
        self.assertEqual(sto_crm.delete_inventory(part["id"]), {"deleted": True})

    def test_explicit_zero_price_for_inventory_part_is_preserved(self):
        customer = self.create_customer("Warranty Customer")
        vehicle = self.create_vehicle(customer["id"], "W001AR")
        part = sto_crm.create_inventory(
            {
                "sku": "WARRANTY",
                "name": "Warranty part",
                "quantity": 2,
                "price": 100,
                "cost": 40,
            }
        )
        order = sto_crm.create_order(
            {
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "status": "new",
                "priority": "normal",
                "items": [
                    service_item(10),
                    {
                        "kind": "part",
                        "inventory_id": part["id"],
                        "title": part["name"],
                        "quantity": 1,
                        "unit_price": 0,
                        "unit_cost": 0,
                    },
                ],
            }
        )
        warranty_line = next(item for item in order["items"] if item["kind"] == "part")
        self.assertEqual(warranty_line["unit_price"], 0)
        self.assertEqual(warranty_line["unit_cost"], 0)
        self.assertEqual(order["parts_total"], 0)

    def test_list_status_filters_are_strict(self):
        with self.assertRaisesRegex(ValueError, "статус"):
            sto_crm.list_orders("", "bad-status")
        with self.assertRaisesRegex(ValueError, "статус"):
            sto_crm.list_appointments("", "bad-status")

    def test_home_page_has_professional_accessibility_and_dirty_state_hooks(self):
        html = sto_crm.INDEX_HTML
        self.assertIn("function labeledField(", html)
        self.assertIn("function tableHead(", html)
        self.assertIn("function inputField(", html)
        self.assertIn("function selectField(", html)
        self.assertIn("function textareaField(", html)
        self.assertIn('scope="col"', html)
        self.assertIn('aria-label="Таблица заказ-нарядов"', html)
        self.assertNotIn('<div class="field"><label>', html)
        self.assertIn('inputField("customer", "name"', html)
        self.assertIn('selectField("order", "customer_id"', html)
        self.assertIn("modalDirty", html)
        self.assertIn("pipelineBoard(r.pipeline_by_status || [])", html)
        self.assertIn("appointmentTimeline(r.appointment_load_7_days || [])", html)
        self.assertIn("procurementList(r.procurement_plan || [])", html)
        self.assertIn("workloadList(r.workload_by_responsible || [])", html)
        self.assertIn("actionPlanList(r.action_plan || [])", html)
        self.assertIn("action-center", html)
        self.assertIn("data-route-target=", html)
        self.assertIn("findAppointmentById(id)", html)
        self.assertIn("findCustomerById(id)", html)
        self.assertIn("findVehicleById(id)", html)
        self.assertIn("findInventoryById(id)", html)
        self.assertIn('function requireRecord(record, label = "Запись")', html)
        self.assertIn(
            'if (requireRecord(customer, "Клиент")) openCustomerModal(customer);', html
        )
        self.assertIn(
            'if (requireRecord(part, "Складская позиция")) openInventoryModal(part);',
            html,
        )
        self.assertIn(
            "if (!vehicle?.id) return vehicleOptions(selectedCustomer, order.vehicle_id);",
            html,
        )
        self.assertIn(
            "if (vehicle.deleted_at || vehicle.deleted_at === 1 || vehicle.vehicle_deleted) {",
            html,
        )
        self.assertIn("healthMetric(r)", html)
        self.assertIn('confirm("Закрыть окно без сохранения изменений?")', html)
        self.assertIn("shouldKeepModalForEscape", html)
        self.assertIn("function handleCommandPaletteTab(event)", html)
        self.assertIn("lastFocusedElement.focus({ preventScroll: true });", html)
        self.assertIn('modalSize = allowedSizes.has(size) ? size : ""', html)
        self.assertIn("setSaveButtonsBusy", html)
        self.assertIn("Вне склада / заказная", html)
        self.assertIn("Источник запчасти", html)
        self.assertIn("discountPreview", html)
        self.assertIn('aria-label="Удалить позицию заказ-наряда"', html)
        self.assertIn('id="appStatus"', html)
        self.assertIn(
            '<a class="skip-link" href="#content">К основному содержанию</a>', html
        )
        self.assertIn("function contextStripHtml()", html)
        self.assertIn('class="context-strip"', html)
        self.assertIn("function updateNavigationBadges()", html)
        self.assertIn('data-nav-badge="dashboard"', html)
        self.assertIn('data-nav-badge="updates"', html)
        self.assertNotIn('data-route="inspections"', html)
        self.assertNotIn("new-inspection", html)
        self.assertNotIn("openInspectionModal", html)
        self.assertIn("lastLoadedAt", html)
        self.assertIn("try {", html)
        self.assertIn("viewHtml = renderers[state.route]();", html)
        self.assertIn(
            "content.innerHTML = `${offlineBannerHtml()}${errorBannerHtml()}${contextStripHtml()}${viewHtml}`;",
            html,
        )
        self.assertIn('if (!force && !state.offlineMode) return "";', html)
        self.assertIn("offlineBannerHtml(true)", html)
        self.assertIn("Не удалось отрисовать раздел.", html)
        self.assertIn("function announce(message", html)
        self.assertIn("function errorBannerHtml()", html)
        self.assertIn('data-action="dismiss-error"', html)
        self.assertIn("scroll-hint-sr", html)
        self.assertIn("aria-describedby", html)
        self.assertIn('aria-label="Запись"', html)
        self.assertIn('aria-label="Открыть клиента ${esc(c.name || c.id)}"', html)
        self.assertIn("function classToken(", html)
        self.assertIn('aria-label="Тип позиции"', html)
        self.assertIn('aria-label="Фильтр по марке или модели"', html)
        self.assertIn('role="group" aria-label="Фильтр заказов по статусу"', html)
        self.assertIn('role="option" data-command-index', html)
        self.assertIn('role="menuitem"', html)
        self.assertIn('aria-haspopup="menu"', html)
        self.assertIn(
            'aria-pressed="${state.status === status ? "true" : "false"}"', html
        )
        self.assertIn("const nextStatus = source.dataset.status;", html)
        self.assertIn("state.data.app.csrf_token", html)
        self.assertIn('function requiresFreshCsrf(actionName = "это действие")', html)
        self.assertIn(
            "Сессия безопасности устарела. Обновите данные CRM и повторите действие.",
            html,
        )
        self.assertIn(
            'const requestStatus = state.route === "orders" ? state.status : "all";',
            html,
        )
        self.assertIn("const leavingFilteredOrders = hasOrderFilter", html)
        self.assertIn("const enteringFilteredOrders = hasOrderFilter", html)
        self.assertIn('data-reload-before-action="1"', html)
        self.assertIn("function exportUrl(entity)", html)
        self.assertIn("function entityRecordPath(kind, id)", html)
        self.assertIn("function safeDownloadFilename(value", html)
        self.assertIn("async function downloadCsv(entity)", html)
        self.assertIn('data-action="export-csv"', html)
        self.assertIn(
            '<button class="btn ghost" type="button" data-action="export-csv"', html
        )
        self.assertNotIn('<a class="btn ghost" href="#" data-action="export-csv"', html)
        self.assertNotIn("?token=${token}", html)
        self.assertIn("openPrintOrder(id)", html)
        self.assertIn('window.open("about:blank", "_blank", "noopener")', html)
        self.assertNotIn("printWindow.opener = null;", html)
        self.assertNotIn('window.open("about:blank", "_blank", "noreferrer")', html)
        self.assertIn('data-action="duplicate-order"', html)
        self.assertIn('aria-label="Печать заказ-наряда', html)
        self.assertIn("Прокрутите вправо", html)
        self.assertIn("overflow-x: hidden; overflow-x: clip;", html)
        self.assertNotIn('id="content" aria-live="polite"', html)

    def test_home_page_wires_inline_form_errors_to_save_failures(self):
        html = sto_crm.INDEX_HTML
        self.assertIn("function applyFormError(error)", html)
        self.assertIn("function clearFormError(target)", html)
        self.assertIn("applyFormError(error);", html)
        self.assertIn('target.setAttribute("aria-invalid", "true")', html)
        self.assertIn("field-error", html)
        self.assertIn("clearAllFormErrors(form)", html)
        self.assertIn('min="0.01" required value="${esc(item.quantity || 1)}"', html)
        self.assertIn(
            'const invalidItems = state.orderDraftItems.filter(item => !String(item.title || "").trim() || num(item.quantity, 0) <= 0);',
            html,
        )
        self.assertEqual(html.count("applyFormError("), 4)

    def test_github_update_helpers_select_and_compare_release_assets(self):
        release = {
            "assets": [
                {
                    "name": "checksums.sha256",
                    "browser_download_url": "https://github.com/owner/repo/releases/download/v1.20.0/checksums.sha256",
                    "size": 100,
                },
                {
                    "name": "latest.json",
                    "browser_download_url": "https://github.com/owner/repo/releases/download/v1.20.0/latest.json",
                    "size": 321,
                },
                {
                    "name": "STO_CRM.exe",
                    "browser_download_url": "https://github.com/owner/repo/releases/download/v1.20.0/STO_CRM.exe",
                    "size": 123,
                },
            ]
        }
        self.assertTrue(sto_crm.is_newer_version("v1.18.0", "1.17.0"))
        self.assertFalse(sto_crm.is_newer_version("1.17.0", "1.17.0"))
        self.assertEqual(sto_crm.select_release_asset(release)["name"], "STO_CRM.exe")
        self.assertEqual(
            sto_crm.select_release_asset(release, kind="manifest")["name"],
            "latest.json",
        )
        self.assertEqual(
            sto_crm.normalize_github_repository("https://github.com/owner/repo.git"),
            "owner/repo",
        )

    def test_release_manifest_drives_update_asset_metadata(self):
        release = {
            "tag_name": "v1.20.0",
            "html_url": "https://github.com/markbakaa88/sto-crm/releases/tag/v1.20.0",
        }
        manifest = {
            "version": "1.20.0",
            "asset": {
                "name": "STO_CRM.exe",
                "size": 123,
                "sha256": "A" * 64,
                "download_url": "https://github.com/markbakaa88/sto-crm/releases/download/v1.20.0/STO_CRM.exe",
            },
        }
        info = sto_crm.release_info_from_manifest(
            release, manifest, {"name": "latest.json", "size": 100}
        )
        self.assertEqual(info["version"], "1.20.0")
        self.assertEqual(info["asset"]["sha256"], "a" * 64)
        self.assertEqual(info["manifest"]["name"], "latest.json")
        with self.assertRaisesRegex(RuntimeError, "тегу"):
            sto_crm.release_info_from_manifest(
                release,
                {**manifest, "tag": "v1.19.0"},
                {"name": "latest.json", "size": 100},
            )
        for bad_asset in (
            {
                **manifest["asset"],
                "name": "latest.json",
                "download_url": "https://github.com/markbakaa88/sto-crm/releases/download/v1.20.0/latest.json",
            },
            {**manifest["asset"], "size": -1},
        ):
            with self.subTest(asset=bad_asset):
                with self.assertRaises(RuntimeError):
                    sto_crm.release_info_from_manifest(
                        release,
                        {**manifest, "asset": bad_asset},
                        {"name": "latest.json", "size": 100},
                    )

    def test_update_manifest_rejects_missing_hash_and_untrusted_download_url(self):
        release = {
            "tag_name": "v1.20.0",
            "html_url": "https://github.com/markbakaa88/sto-crm/releases/tag/v1.20.0",
        }
        trusted_asset = {
            "name": "STO_CRM.exe",
            "size": 123,
            "sha256": "b" * 64,
            "download_url": "https://github.com/markbakaa88/sto-crm/releases/download/v1.20.0/STO_CRM.exe",
        }
        with self.assertRaisesRegex(RuntimeError, "SHA-256"):
            sto_crm.release_info_from_manifest(
                release,
                {"asset": {**trusted_asset, "sha256": ""}},
                {"name": "latest.json"},
            )
        untrusted_urls = [
            "https://example.test/STO_CRM.exe",
            "http://github.com/markbakaa88/sto-crm/releases/download/v1.20.0/STO_CRM.exe",
            "https://github.com.evil.test/markbakaa88/sto-crm/releases/download/v1.20.0/STO_CRM.exe",
            "https://user:pass@github.com/markbakaa88/sto-crm/releases/download/v1.20.0/STO_CRM.exe",
            "https://github.com:444/markbakaa88/sto-crm/releases/download/v1.20.0/STO_CRM.exe",
            "https://github.com/markbakaa88/sto-crm/releases/download/v1.20.0/STO_CRM.exe\nhttps://example.test/payload.exe",
        ]
        for url in untrusted_urls:
            with self.subTest(url=url):
                with self.assertRaisesRegex(RuntimeError, "недоверенную"):
                    sto_crm.release_info_from_manifest(
                        release,
                        {"asset": {**trusted_asset, "download_url": url}},
                        {"name": "latest.json"},
                    )
        manifest_only_urls = [
            "https://github.com/markbakaa88/sto-crm/releases/download/v1.19.0/STO_CRM.exe",
            "https://github.com/other/repo/releases/download/v1.20.0/STO_CRM.exe",
            "https://objects.githubusercontent.com/github-production-release-asset-2e65be/123/STO_CRM.exe",
        ]
        for url in manifest_only_urls:
            with self.subTest(url=url):
                with self.assertRaisesRegex(RuntimeError, "ожидаемого GitHub Release"):
                    sto_crm.release_info_from_manifest(
                        release,
                        {"asset": {**trusted_asset, "download_url": url}},
                        {"name": "latest.json"},
                    )
        with self.assertRaisesRegex(RuntimeError, "некорректную"):
            sto_crm.release_info_from_manifest(
                release,
                {
                    "asset": {
                        **trusted_asset,
                        "download_url": "https://github.com:bad/markbakaa88/sto-crm/releases/download/v1.20.0/STO_CRM.exe",
                    }
                },
                {"name": "latest.json"},
            )

    def test_download_release_asset_requires_verified_hash_and_keeps_existing_target_on_failure(
        self,
    ):
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

            negative_size_asset = {**asset, "size": -1}
            with self.assertRaisesRegex(RuntimeError, "размер"):
                sto_crm.download_release_asset(negative_size_asset, target)
            self.assertEqual(target.read_bytes(), payload)
        finally:
            urllib.request.urlopen = old_urlopen

    def test_update_json_and_redirects_are_bounded_and_validated(self):
        old_urlopen = urllib.request.urlopen
        try:

            class FakeHeaders(Message):
                def get_content_charset(self):
                    return "utf-8"

            class FakeResponse:
                def __init__(
                    self,
                    body: bytes,
                    final_url: str = "https://github.com/owner/repo/releases/download/v1.20.0/latest.json",
                    content_length: int | None = None,
                ):
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

            urllib.request.urlopen = lambda *_args, **_kwargs: FakeResponse(
                b'{"ok": true}'
            )
            self.assertEqual(
                sto_crm.fetch_json(
                    "https://api.github.com/repos/owner/repo/releases/latest"
                ),
                {"ok": True},
            )

            urllib.request.urlopen = lambda *_args, **_kwargs: FakeResponse(
                codecs.BOM_UTF8 + b'{"ok": true}'
            )
            self.assertEqual(
                sto_crm.fetch_json(
                    "https://api.github.com/repos/owner/repo/releases/latest"
                ),
                {"ok": True},
            )

            urllib.request.urlopen = lambda *_args, **_kwargs: FakeResponse(
                b"{}", "https://example.test/latest.json"
            )
            with self.assertRaisesRegex(RuntimeError, "недоверенную"):
                sto_crm.fetch_json(
                    "https://github.com/owner/repo/releases/download/v1.20.0/latest.json"
                )

            urllib.request.urlopen = lambda *_args, **_kwargs: FakeResponse(
                b"{}",
                content_length=getattr(
                    sto_crm, "GITHUB_UPDATE_MAX_JSON_BYTES", 1024 * 1024 * 10
                )
                + 1,
            )
            with self.assertRaisesRegex(RuntimeError, "слишком большой"):
                sto_crm.fetch_json(
                    "https://github.com/owner/repo/releases/download/v1.20.0/latest.json"
                )

            target = Path(self.tempdir.name) / "redirect.exe"
            asset = {
                "name": "STO_CRM.exe",
                "size": 2,
                "sha256": hashlib.sha256(b"MZ").hexdigest(),
                "download_url": "https://github.com/owner/repo/releases/download/v1.20.0/STO_CRM.exe",
            }
            urllib.request.urlopen = lambda *_args, **_kwargs: FakeResponse(
                b"MZ", "https://example.test/STO_CRM.exe"
            )
            with self.assertRaisesRegex(RuntimeError, "недоверенную"):
                sto_crm.download_release_asset(asset, target)
            self.assertFalse(target.exists())
        finally:
            urllib.request.urlopen = old_urlopen

    def test_update_status_reports_release_lookup_failures_without_crashing(self):
        old_fetch_json = sto_crm.fetch_json
        try:
            sto_crm.fetch_json = lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("offline")
            )
            status = sto_crm.update_status()
        finally:
            sto_crm.fetch_json = old_fetch_json
        self.assertFalse(status["ok"])
        self.assertEqual(status["current_version"], sto_crm.APP_VERSION)
        self.assertIn("offline", status["error"])

    def test_windows_update_script_rechecks_sha256_before_replacing_exe(self):
        script_path = Path(self.tempdir.name) / "apply_update.ps1"
        expected_sha256 = "a" * 64

        sto_crm.write_windows_update_script(
            script_path,
            Path("C:/Users/Иван O'Connor/AppData/Local/STO CRM/STO_CRM.exe"),
            Path(self.tempdir.name) / "скачанное обновление.exe",
            Path(self.tempdir.name) / "backup O'Connor.exe",
            Path(self.tempdir.name) / "журнал обновления.log",
            expected_sha256,
        )

        self.assertTrue(script_path.read_bytes().startswith(codecs.BOM_UTF8))
        script = script_path.read_text(encoding="utf-8-sig")
        self.assertIn(
            "$Current = 'C:/Users/Иван O''Connor/AppData/Local/STO CRM/STO_CRM.exe'",
            script,
        )
        self.assertIn("скачанное обновление.exe'", script)
        self.assertIn("backup O''Connor.exe'", script)
        self.assertNotIn("\\u0418", script)
        self.assertNotIn('"C:/Users', script)
        self.assertIn("$ExpectedSha256", script)
        self.assertIn(expected_sha256, script)
        self.assertIn("if (-not (Test-Path -LiteralPath $Downloaded))", script)
        self.assertIn("Get-FileHash -Algorithm SHA256 -LiteralPath $Downloaded", script)
        self.assertIn("$ActualSha256 -ne $ExpectedSha256", script)
        self.assertIn("SHA-256 файла обновления изменился перед установкой", script)
        self.assertLess(
            script.index("Get-FileHash -Algorithm SHA256 -LiteralPath $Downloaded"),
            script.index("Move-Item -LiteralPath $Current -Destination $Backup -Force"),
        )

    def test_build_smoke_test_uses_windows_powershell_compatible_process_args(self):
        build_script = (Path(__file__).resolve().parents[1] / "build.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn("function Join-ProcessArguments", build_script)
        self.assertIn("$startInfo.Arguments = Join-ProcessArguments", build_script)
        self.assertIn("$startInfo.CreateNoWindow = $true", build_script)
        self.assertNotIn("$startInfo.ArgumentList", build_script)
        self.assertNotIn("[void]$startInfo.ArgumentList.Add", build_script)

    def test_update_status_requires_installable_hash_before_enabling_install(self):
        old_latest = sto_crm.latest_release_info
        old_frozen = sto_crm.is_frozen
        old_app_executable_path = sto_crm.app_executable_path
        try:
            sto_crm.is_frozen = lambda: True
            sto_crm.app_executable_path = lambda: Path("C:/CRM/STO_CRM.exe")
            sto_crm.latest_release_info = lambda: {
                "version": "99.0.0",
                "tag": "v99.0.0",
                "asset": {
                    "name": "STO_CRM.exe",
                    "size": 123,
                    "download_url": "https://github.com/markbakaa88/sto-crm/releases/download/v99.0.0/STO_CRM.exe",
                },
            }
            status = sto_crm.update_status()
            self.assertTrue(status["ok"])
            self.assertFalse(status["release"]["has_asset"])
            self.assertFalse(status["can_install"])
        finally:
            sto_crm.latest_release_info = old_latest
            sto_crm.is_frozen = old_frozen
            sto_crm.app_executable_path = old_app_executable_path

    def test_install_update_serializes_concurrent_requests_and_cleans_failed_download(
        self,
    ):
        old_latest = sto_crm.latest_release_info
        old_frozen = sto_crm.is_frozen
        old_app_executable_path = sto_crm.app_executable_path
        old_create_backup = sto_crm.create_backup
        old_download = sto_crm.download_release_asset
        old_ensure = sto_crm.ensure_downloaded_executable
        old_schedule = sto_crm.schedule_windows_update
        old_can_install = sto_crm.updates.can_install_windows_update
        lock_path = Path(self.tempdir.name) / "download.lock"
        cleanup_path_holder = {}
        release = {
            "version": "99.0.0",
            "tag": "v99.0.0",
            "prerelease": False,
            "draft": False,
            "asset": {
                "name": "STO_CRM.exe",
                "size": 123,
                "sha256": "c" * 64,
                "download_url": "https://github.com/markbakaa88/sto-crm/releases/download/v99.0.0/STO_CRM.exe",
            },
        }

        def stuck_download(_asset, target):
            cleanup_path_holder["path"] = target
            target.write_bytes(b"partial")
            lock_path.write_text("started", encoding="utf-8")
            time.sleep(0.2)
            raise RuntimeError("network failed")

        try:
            sto_crm.is_frozen = lambda: True
            sto_crm.updates.can_install_windows_update = lambda: True
            sto_crm.app_executable_path = lambda: Path("C:/CRM/STO_CRM.exe")
            sto_crm.latest_release_info = lambda: release
            sto_crm.create_backup = lambda: {"display_path": "backup.sqlite3"}
            sto_crm.download_release_asset = stuck_download
            sto_crm.ensure_downloaded_executable = lambda _path: None
            sto_crm.schedule_windows_update = lambda _path, _sha: None
            errors = []

            def run_install():
                try:
                    sto_crm.install_update_from_github()
                except RuntimeError as exc:
                    errors.append(str(exc))

            first = threading.Thread(target=run_install)
            first.start()
            deadline = time.time() + 2
            while not lock_path.exists() and time.time() < deadline:
                time.sleep(0.01)
            with self.assertRaisesRegex(RuntimeError, "уже выполняется"):
                sto_crm.install_update_from_github()
            first.join(timeout=2)
            self.assertFalse(first.is_alive())
            self.assertIn("network failed", errors)
            self.assertFalse(cleanup_path_holder["path"].exists())

            sto_crm.download_release_asset = lambda _asset, target: (
                target.write_bytes(b"MZ"),
                {"size": 2, "sha256": "c" * 64},
            )[1]
            sto_crm.ensure_downloaded_executable = old_ensure
            with self.assertRaisesRegex(RuntimeError, "Windows .exe"):
                sto_crm.install_update_from_github()
        finally:
            sto_crm.latest_release_info = old_latest
            sto_crm.is_frozen = old_frozen
            sto_crm.app_executable_path = old_app_executable_path
            sto_crm.create_backup = old_create_backup
            sto_crm.download_release_asset = old_download
            sto_crm.ensure_downloaded_executable = old_ensure
            sto_crm.schedule_windows_update = old_schedule
            sto_crm.updates.can_install_windows_update = old_can_install
            sto_crm.updates._finish_update_install(scheduled=False)

    def test_home_page_exposes_github_updates_ui_and_api_hooks(self):
        html = sto_crm.INDEX_HTML
        self.assertIn('data-route="updates"', html)
        self.assertIn("function renderUpdates()", html)
        self.assertIn("/api/update/status", html)
        self.assertIn("/api/update/install", html)
        self.assertIn('data-action="check-update"', html)
        self.assertIn('data-action="install-update"', html)
        self.assertIn("STO_CRM.exe", html)
        self.assertIn("latest.json", html)
        self.assertIn("GitHub Releases", html)

    def test_update_install_route_reaches_update_service_without_parsing_install_as_id(
        self,
    ):
        server = sto_crm.CRMServer(("127.0.0.1", 0), sto_crm.CRMHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        original_install = sto_crm.install_update_from_github
        try:
            sto_crm.install_update_from_github = lambda: {
                "ok": True,
                "updated": False,
                "message": "stub",
            }
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/api/update/install",
                data=json.dumps({}).encode("utf-8"),
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "X-CSRF-Token": sto_crm.RUNTIME.csrf_token,
                    "X-CRM-Access-Token": sto_crm.RUNTIME.access_token,
                },
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["message"], "stub")
        finally:
            sto_crm.install_update_from_github = original_install
            server.shutdown()
            server.server_close()

    def test_home_page_exposes_theme_route_and_modal_accessibility_hooks(self):
        html = sto_crm.INDEX_HTML
        self.assertIn('id="themeToggle"', html)
        self.assertIn('data-initial-theme="light"', html)
        self.assertIn('document.documentElement.dataset.themeReady = "1"', html)
        self.assertIn('themeToggle.addEventListener("click"', html)
        self.assertIn('id="densityToggle"', html)
        self.assertIn("function applyDensity(", html)
        self.assertIn("if (!node) {", html)
        self.assertIn("function toggleDensity()", html)
        self.assertIn("sto-crm-density", html)
        self.assertIn("body.compact .metric", html)
        self.assertIn('id="commandPalette"', html)
        self.assertIn("function commandItems()", html)
        self.assertIn("function openCommandPalette()", html)
        self.assertIn("data-command-index", html)
        self.assertIn("Ctrl+K", html)
        self.assertIn("aria-pressed", html)
        self.assertIn("history.pushState", html)
        self.assertIn('window.addEventListener("popstate"', html)
        self.assertIn("lastFocusedElement", html)
        self.assertIn("appTabbableSnapshot", html)
        self.assertIn("bindModalSubmitHandlers", html)
        self.assertIn("safeStorageGet", html)
        self.assertIn("nextThemePreference", html)
        self.assertIn("localStorage.removeItem(key)", html)
        self.assertIn("handleModalKeydown", html)
        self.assertIn('aria-label="Печать заказ-наряда', html)
        self.assertIn('id="clearSearch"', html)
        self.assertIn('type="email"', html)
        self.assertIn('title="VIN должен содержать 17 символов без I, O и Q"', html)

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
                {
                    "kind": "service",
                    "title": "Premium labor",
                    "approval_status": "approved",
                    "quantity": 1,
                    "unit_price": 1000,
                },
                {
                    "kind": "part",
                    "title": "Deferred part",
                    "approval_status": "deferred",
                    "quantity": 1,
                    "unit_price": 500,
                },
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
        self.assertIn("print-color-adjust: exact", html)
        self.assertIn("@media print", html)
        self.assertIn("СТО CRM · заказ-наряд", html)
        self.assertIn("style-src 'nonce-__STO_CRM_CSP_NONCE__'", html)
        self.assertIn('<style nonce="__STO_CRM_CSP_NONCE__">', html)
        self.assertNotIn("style-src 'unsafe-inline'", html)

    def test_frontend_error_retry_and_network_helpers_are_robust(self):
        html = sto_crm.INDEX_HTML
        self.assertIn("bindViewActions(content);", html)
        self.assertIn(
            "error.retryable = response.status >= 500 || [408, 425, 429].includes(response.status);",
            html,
        )
        self.assertIn(
            "const retryable = error?.retryable === true || !Number(error?.status || 0);",
            html,
        )
        self.assertIn("if (attempt === maxRetries || !retryable) throw error;", html)
        self.assertIn('if (method !== "GET" && !state.data?.app?.csrf_token)', html)
        self.assertIn("function readCachedBootstrap() {", html)
        self.assertIn("sessionStorage can be unavailable or contain stale data", html)
        self.assertIn("if (state.updateLoading) return;", html)
        self.assertIn("state.updateCheckScheduled = true;", html)
        self.assertIn('const content = $("#content");\n    if (!content) return;', html)
        self.assertIn("window.setTimeout(() => URL.revokeObjectURL(url), 1000);", html)
        self.assertNotIn(
            'URL.revokeObjectURL(url);\n    toast("CSV экспортирован")', html
        )

    def test_ensure_downloaded_executable_validates_full_pe_header(self):
        good = Path(self.tempdir.name) / "good.exe"
        lfanew = 0x80
        payload = bytearray(b"MZ" + b"\x00" * (lfanew - 2) + b"PE\x00\x00" + b"rest")
        payload[60:64] = lfanew.to_bytes(4, "little")
        good.write_bytes(bytes(payload))
        sto_crm.ensure_downloaded_executable(good)

        bad_magic = Path(self.tempdir.name) / "bad-magic.exe"
        bad_magic.write_bytes(b"XZ" + b"\x00" * 200)
        with self.assertRaisesRegex(RuntimeError, "Windows .exe"):
            sto_crm.ensure_downloaded_executable(bad_magic)

        short = Path(self.tempdir.name) / "short.exe"
        short.write_bytes(b"MZ")
        with self.assertRaisesRegex(RuntimeError, "Windows .exe"):
            sto_crm.ensure_downloaded_executable(short)

        bad_pe = Path(self.tempdir.name) / "no-pe.exe"
        stub = bytearray(b"MZ" + b"\x00" * 126)
        stub[60:64] = (0x40).to_bytes(4, "little")
        stub += b"ZZZZ"
        bad_pe.write_bytes(bytes(stub))
        with self.assertRaisesRegex(RuntimeError, "PE-сигнатуру"):
            sto_crm.ensure_downloaded_executable(bad_pe)

        wrong_extension = Path(self.tempdir.name) / "file.dll"
        wrong_extension.write_bytes(bytes(payload))
        with self.assertRaisesRegex(RuntimeError, "готовый Windows-файл"):
            sto_crm.ensure_downloaded_executable(wrong_extension)

    def test_install_update_rejects_prerelease_and_draft_builds(self):
        saved_release = {
            "version": "99.0.0",
            "tag": "v99.0.0",
            "prerelease": True,
            "asset": {},
        }

        old_latest = sto_crm.latest_release_info
        old_is_frozen = sto_crm.is_frozen
        old_can_install = sto_crm.updates.can_install_windows_update
        try:
            sto_crm.is_frozen = lambda: True
            sto_crm.updates.can_install_windows_update = lambda: True
            sto_crm.latest_release_info = lambda: saved_release
            result = sto_crm.install_update_from_github()
            self.assertTrue(result["ok"])
            self.assertFalse(result["updated"])
            self.assertIn("Стабильных обновлений", result["message"])

            saved_release = {
                "version": "99.0.0",
                "tag": "v99.0.0",
                "draft": True,
                "asset": {},
            }
            result = sto_crm.install_update_from_github()
            self.assertFalse(result["updated"])
        finally:
            sto_crm.latest_release_info = old_latest
            sto_crm.is_frozen = old_is_frozen
            sto_crm.updates.can_install_windows_update = old_can_install


if __name__ == "__main__":
    unittest.main()
