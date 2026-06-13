import sqlite3
import unittest
from contextlib import closing

from sto_crm.validation import (
    ensure_unique_active_value,
    ensure_vehicle_belongs_to_customer,
    parse_bool_field,
    require_non_negative_int,
    validate_appointment,
    validate_customer,
    validate_inventory,
    validate_order,
    validate_vehicle,
)


class TestValidationExtra(unittest.TestCase):
    def test_validate_customer_missing_name(self):
        with self.assertRaisesRegex(ValueError, "имя клиента"):
            validate_customer({})

    def test_validate_customer_invalid_channel(self):
        with self.assertRaisesRegex(ValueError, "канал связи"):
            validate_customer({"name": "Test", "preferred_channel": "pigeon"})

    def test_validate_customer_invalid_email(self):
        with self.assertRaisesRegex(ValueError, "email"):
            validate_customer({"name": "Test", "email": "not-an-email"})

    def test_validate_vehicle_missing_customer(self):
        with closing(sqlite3.connect(":memory:")) as conn:
            conn.row_factory = sqlite3.Row
            with self.assertRaisesRegex(ValueError, "Выберите действующего клиента"):
                validate_vehicle(conn, {})

    def test_require_non_negative_int_negative(self):
        with self.assertRaisesRegex(ValueError, "не может быть отрицательным"):
            require_non_negative_int(-10, "тест")

    def test_parse_bool_field_variations(self):
        self.assertEqual(parse_bool_field(True, "test"), 1)
        self.assertEqual(parse_bool_field(False, "test"), 0)
        self.assertEqual(parse_bool_field(1, "test"), 1)
        self.assertEqual(parse_bool_field(0, "test"), 0)
        self.assertEqual(parse_bool_field("да", "test"), 1)
        self.assertEqual(parse_bool_field("нет", "test"), 0)
        self.assertEqual(parse_bool_field("true", "test"), 1)
        self.assertEqual(parse_bool_field("false", "test"), 0)
        self.assertEqual(parse_bool_field(None, "test", default=True), 1)
        self.assertEqual(parse_bool_field(None, "test", default=False), 0)

        with self.assertRaisesRegex(ValueError, "Некорректное значение"):
            parse_bool_field(2, "test")
        with self.assertRaisesRegex(ValueError, "Некорректное значение"):
            parse_bool_field("invalid", "test")
        with self.assertRaisesRegex(ValueError, "Некорректное значение"):
            parse_bool_field([], "test")

    def test_validate_vehicle_no_details(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, deleted_at TEXT)"
        )
        conn.execute("INSERT INTO customers (id, name, deleted_at) VALUES (1, 'Customer', NULL)")
        try:
            with self.assertRaisesRegex(ValueError, "Укажите автомобиль: марку, модель, номер или VIN"):
                validate_vehicle(conn, {"customer_id": 1})
        finally:
            conn.close()

    def test_validate_inventory_missing_name(self):
        with self.assertRaisesRegex(ValueError, "Укажите название позиции склада"):
            validate_inventory({})

    def test_validate_order_missing_customer(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            with self.assertRaisesRegex(ValueError, "Выберите действующего клиента"):
                validate_order(conn, {})
        finally:
            conn.close()

    def test_validate_order_invalid_status_or_items(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, deleted_at TEXT)"
        )
        conn.execute("INSERT INTO customers (id, name, deleted_at) VALUES (1, 'Customer', NULL)")
        try:
            # Плохой статус
            with self.assertRaisesRegex(ValueError, "Некорректный статус заказа"):
                validate_order(conn, {"customer_id": 1, "status": "invalid_status"})
            
            # Плохой приоритет
            with self.assertRaisesRegex(ValueError, "Некорректный приоритет заказа"):
                validate_order(conn, {"customer_id": 1, "status": "new", "priority": "invalid"})
            
            # Items не список
            with self.assertRaisesRegex(ValueError, "Позиции заказ-наряда должны быть списком"):
                validate_order(conn, {"customer_id": 1, "status": "new", "priority": "normal", "items": "not a list"})

            # Пустой список items
            with self.assertRaisesRegex(ValueError, "Добавьте хотя бы одну работу или запчасть"):
                validate_order(conn, {"customer_id": 1, "status": "new", "priority": "normal", "items": []})
        finally:
            conn.close()

    def test_validate_appointment_invalid_duration(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, deleted_at TEXT)"
        )
        conn.execute("INSERT INTO customers (id, name, deleted_at) VALUES (1, 'Customer', NULL)")
        try:
            payload = {
                "customer_id": 1,
                "scheduled_at": "2026-06-12T10:00",
                "duration_minutes": 5,
            }
            with self.assertRaisesRegex(ValueError, "Длительность записи должна быть от 15 до 480 минут"):
                validate_appointment(conn, payload)
        finally:
            conn.close()

    def test_ensure_unique_active_value_invalid_check(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            with self.assertRaisesRegex(ValueError, "Некорректная проверка уникальности"):
                ensure_unique_active_value(conn, "invalid_table", "sku", "val", "msg")
        finally:
            conn.close()

    def test_ensure_vehicle_belongs_to_customer_required(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            with self.assertRaisesRegex(ValueError, "Выберите действующий автомобиль"):
                ensure_vehicle_belongs_to_customer(conn, None, 1, required=True)
        finally:
            conn.close()

    def test_vehicle_belongs_to_other_customer(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE vehicles (id INTEGER PRIMARY KEY, customer_id INTEGER, deleted_at TEXT)")
        conn.execute("INSERT INTO vehicles (id, customer_id, deleted_at) VALUES (10, 2, NULL)")
        try:
            with self.assertRaisesRegex(ValueError, "Выбранный автомобиль принадлежит другому клиенту"):
                ensure_vehicle_belongs_to_customer(conn, 10, 1) # Vehicle belongs to customer 2, but we pass customer 1
        finally:
            conn.close()

    def test_validate_order_item_invalid_part_id(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, deleted_at TEXT)")
        conn.execute("INSERT INTO customers (id, name, deleted_at) VALUES (1, 'Customer', NULL)")
        conn.execute("CREATE TABLE inventory (id INTEGER PRIMARY KEY, name TEXT, price REAL, cost REAL, deleted_at TEXT)")
        # We did not insert inventory id 99
        try:
            payload = {
                "customer_id": 1,
                "status": "new",
                "priority": "normal",
                "items": [{
                    "kind": "part",
                    "inventory_id": 99,
                    "title": "Missing Part",
                    "quantity": 1
                }]
            }
            with self.assertRaisesRegex(ValueError, "Выбранная складская позиция не найдена"):
                validate_order(conn, payload)
        finally:
            conn.close()

    def test_validate_order_item_zero_quantity(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, deleted_at TEXT)")
        conn.execute("INSERT INTO customers (id, name, deleted_at) VALUES (1, 'Customer', NULL)")
        try:
            payload = {
                "customer_id": 1,
                "status": "new",
                "priority": "normal",
                "items": [{
                    "kind": "service",
                    "title": "Labor",
                    "quantity": 0
                }]
            }
            with self.assertRaisesRegex(ValueError, "Количество в позиции должно быть больше нуля"):
                validate_order(conn, payload)
        finally:
            conn.close()

    def test_validate_order_item_small_quantity(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, deleted_at TEXT)")
        conn.execute("INSERT INTO customers (id, name, deleted_at) VALUES (1, 'Customer', NULL)")
        try:
            payload = {
                "customer_id": 1,
                "status": "new",
                "priority": "normal",
                "items": [{
                    "kind": "service",
                    "title": "Labor",
                    "quantity": 0.005 # MIN_QUANTITY_STEP is 0.01
                }]
            }
            with self.assertRaisesRegex(ValueError, "Количество в позиции должно быть не меньше 0.01"):
                validate_order(conn, payload)
        finally:
            conn.close()
