import sqlite3
import unittest
from contextlib import closing
from datetime import UTC

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
        conn.execute(
            "INSERT INTO customers (id, name, deleted_at) VALUES (1, 'Customer', NULL)"
        )
        try:
            with self.assertRaisesRegex(
                ValueError, "Укажите автомобиль: марку, модель, номер или VIN"
            ):
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
        conn.execute(
            "INSERT INTO customers (id, name, deleted_at) VALUES (1, 'Customer', NULL)"
        )
        try:
            # Плохой статус
            with self.assertRaisesRegex(ValueError, "Некорректный статус заказа"):
                validate_order(conn, {"customer_id": 1, "status": "invalid_status"})

            # Плохой приоритет
            with self.assertRaisesRegex(ValueError, "Некорректный приоритет заказа"):
                validate_order(
                    conn, {"customer_id": 1, "status": "new", "priority": "invalid"}
                )

            # Items не список
            with self.assertRaisesRegex(
                ValueError, "Позиции заказ-наряда должны быть списком"
            ):
                validate_order(
                    conn,
                    {
                        "customer_id": 1,
                        "status": "new",
                        "priority": "normal",
                        "items": "not a list",
                    },
                )

            # Пустой список items
            with self.assertRaisesRegex(
                ValueError, "Добавьте хотя бы одну работу или запчасть"
            ):
                validate_order(
                    conn,
                    {
                        "customer_id": 1,
                        "status": "new",
                        "priority": "normal",
                        "items": [],
                    },
                )
        finally:
            conn.close()

    def test_validate_appointment_invalid_duration(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, deleted_at TEXT)"
        )
        conn.execute(
            "INSERT INTO customers (id, name, deleted_at) VALUES (1, 'Customer', NULL)"
        )
        try:
            payload = {
                "customer_id": 1,
                "scheduled_at": "2026-06-12T10:00",
                "duration_minutes": 5,
            }
            with self.assertRaisesRegex(
                ValueError, "Длительность записи должна быть от 15 до 480 минут"
            ):
                validate_appointment(conn, payload)
        finally:
            conn.close()

    def test_ensure_unique_active_value_invalid_check(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            with self.assertRaisesRegex(
                ValueError, "Некорректная проверка уникальности"
            ):
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
        conn.execute(
            "CREATE TABLE vehicles (id INTEGER PRIMARY KEY, customer_id INTEGER, deleted_at TEXT)"
        )
        conn.execute(
            "INSERT INTO vehicles (id, customer_id, deleted_at) VALUES (10, 2, NULL)"
        )
        try:
            with self.assertRaisesRegex(
                ValueError, "Выбранный автомобиль принадлежит другому клиенту"
            ):
                ensure_vehicle_belongs_to_customer(
                    conn, 10, 1
                )  # Vehicle belongs to customer 2, but we pass customer 1
        finally:
            conn.close()

    def test_validate_order_item_invalid_part_id(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, deleted_at TEXT)"
        )
        conn.execute(
            "INSERT INTO customers (id, name, deleted_at) VALUES (1, 'Customer', NULL)"
        )
        conn.execute(
            "CREATE TABLE inventory (id INTEGER PRIMARY KEY, name TEXT, price REAL, cost REAL, deleted_at TEXT)"
        )
        # We did not insert inventory id 99
        try:
            payload = {
                "customer_id": 1,
                "status": "new",
                "priority": "normal",
                "items": [
                    {
                        "kind": "part",
                        "inventory_id": 99,
                        "title": "Missing Part",
                        "quantity": 1,
                    }
                ],
            }
            with self.assertRaisesRegex(
                ValueError, "Выбранная складская позиция не найдена"
            ):
                validate_order(conn, payload)
        finally:
            conn.close()

    def test_validate_order_item_zero_quantity(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, deleted_at TEXT)"
        )
        conn.execute(
            "INSERT INTO customers (id, name, deleted_at) VALUES (1, 'Customer', NULL)"
        )
        try:
            payload = {
                "customer_id": 1,
                "status": "new",
                "priority": "normal",
                "items": [{"kind": "service", "title": "Labor", "quantity": 0}],
            }
            with self.assertRaisesRegex(
                ValueError, "Количество в позиции должно быть больше нуля"
            ):
                validate_order(conn, payload)
        finally:
            conn.close()

    def test_validate_order_item_small_quantity(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, deleted_at TEXT)"
        )
        conn.execute(
            "INSERT INTO customers (id, name, deleted_at) VALUES (1, 'Customer', NULL)"
        )
        try:
            payload = {
                "customer_id": 1,
                "status": "new",
                "priority": "normal",
                "items": [
                    {
                        "kind": "service",
                        "title": "Labor",
                        "quantity": 0.005,  # MIN_QUANTITY_STEP is 0.01
                    }
                ],
            }
            with self.assertRaisesRegex(
                ValueError, "Количество в позиции должно быть не меньше 0.01"
            ):
                validate_order(conn, payload)
        finally:
            conn.close()

    def test_odometer_limit(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, deleted_at TEXT)"
        )
        conn.execute(
            "INSERT INTO customers (id, name, deleted_at) VALUES (1, 'Customer', NULL)"
        )
        try:
            payload = {
                "customer_id": 1,
                "status": "new",
                "priority": "normal",
                "odometer": 10_000_001,  # limit is 10_000_000
                "items": [{"kind": "service", "title": "Labor", "quantity": 1}],
            }
            with self.assertRaisesRegex(
                ValueError, "пробег в заказе не может превышать 10 000 000"
            ):
                validate_order(conn, payload)
        finally:
            conn.close()

    def test_huge_inventory_money_limit(self):
        payload = {
            "sku": "T-HUGE",
            "name": "Huge Part",
            "quantity": 1_000_000.0,
            "min_quantity": 0,
            "price": 2_000_000.0,  # 1M * 2M = 2 Trillion (> 1 Trillion MAX_FINANCIAL_TOTAL)
            "cost": 10.0,
        }
        with self.assertRaisesRegex(
            ValueError, "Некорректное финансовое значение: стоимость остатка по цене"
        ):
            validate_inventory(payload)

    def test_timezone_aware_appointment_conflict(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, deleted_at TEXT)"
        )
        conn.execute(
            "INSERT INTO customers (id, name, deleted_at) VALUES (1, 'Customer', NULL)"
        )
        conn.execute(
            """
            CREATE TABLE appointments (
                id INTEGER PRIMARY KEY,
                customer_id INTEGER,
                vehicle_id INTEGER,
                scheduled_at TEXT,
                duration_minutes INTEGER,
                status TEXT,
                deleted_at TEXT
            )
            """
        )
        # Add conflict
        conn.execute(
            """
            INSERT INTO appointments (id, customer_id, vehicle_id, scheduled_at, duration_minutes, status, deleted_at)
            VALUES (1, 1, NULL, '2026-06-12T10:00:00+03:00', 60, 'scheduled', NULL)
            """
        )
        try:
            # Under a different timezone (e.g. UTC, if we shift scheduled_at to match 10:00 in +03:00)
            # 10:00 in +03:00 is 07:00 UTC.
            # So a new appointment at 07:00 UTC should conflict!
            # Let's pass 2026-06-12T07:00:00Z (which is 2026-06-12T07:00:00+00:00)
            with self.assertRaisesRegex(ValueError, "На это время уже есть запись"):
                from sto_crm.validation import ensure_no_appointment_conflict

                ensure_no_appointment_conflict(conn, "2026-06-12T07:00:00Z", 30)
        finally:
            conn.close()

    def test_generate_order_number_invalid_suffix_handling(self):
        from datetime import datetime
        from unittest.mock import patch

        from sto_crm.validation import generate_order_number
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, number TEXT)")
        prefix = datetime.now().strftime("СТО-%Y%m%d")
        conn.execute("INSERT INTO orders (number) VALUES (?)", (f"{prefix}-123",))
        
        class MockMatch:
            def group(self, index):
                return "abc"
        
        class MockPattern:
            def fullmatch(self, string):
                if string.startswith(prefix):
                    return MockMatch()
                return None
        
        with patch("re.compile", return_value=MockPattern()):
            num = generate_order_number(conn)
            self.assertEqual(num, f"{prefix}-001")
        conn.close()

    def test_validate_order_deleted_customer(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, deleted_at TEXT)"
        )
        conn.execute(
            "INSERT INTO customers (id, name, deleted_at) VALUES (1, 'Customer', '2026-06-12T12:00:00')"
        )
        try:
            with self.assertRaisesRegex(ValueError, "Выберите действующего клиента"):
                validate_order(conn, {"customer_id": 1})
        finally:
            conn.close()

    def test_validate_order_item_invalid_approval_status(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, deleted_at TEXT)")
        conn.execute("INSERT INTO customers (id, name, deleted_at) VALUES (1, 'Customer', NULL)")
        try:
            payload = {
                "customer_id": 1,
                "status": "new",
                "priority": "normal",
                "items": [
                    {
                        "kind": "service",
                        "title": "Labor",
                        "quantity": 1,
                        "approval_status": "invalid_status",
                    }
                ],
            }
            with self.assertRaisesRegex(ValueError, "Некорректный статус согласования позиции"):
                validate_order(conn, payload)
        finally:
            conn.close()

    def test_active_exists_invalid_table(self):
        from sto_crm.validation import active_exists
        conn = sqlite3.connect(":memory:")
        try:
            res = active_exists(conn, "invalid_table", 1)
            self.assertFalse(res)
        finally:
            conn.close()

    def test_ensure_vehicle_belongs_to_customer_deleted_or_missing(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE vehicles (id INTEGER PRIMARY KEY, customer_id INTEGER, deleted_at TEXT)")
        conn.execute("INSERT INTO vehicles (id, customer_id, deleted_at) VALUES (1, 1, '2026-06-12T12:00:00')")
        try:
            with self.assertRaisesRegex(ValueError, "Выберите действующий автомобиль"):
                ensure_vehicle_belongs_to_customer(conn, 999, 1)

            with self.assertRaisesRegex(ValueError, "Выберите действующий автомобиль"):
                ensure_vehicle_belongs_to_customer(conn, 1, 1)

            res = ensure_vehicle_belongs_to_customer(conn, 1, 1, allow_deleted_vehicle_id=1)
            self.assertEqual(res, 1)

            with self.assertRaisesRegex(ValueError, "Выбранный автомобиль принадлежит другому клиенту"):
                ensure_vehicle_belongs_to_customer(conn, 1, 2, allow_deleted_vehicle_id=1)
        finally:
            conn.close()

    def test_ensure_no_appointment_conflict_non_positive_duration(self):
        from sto_crm.validation import ensure_no_appointment_conflict
        conn = sqlite3.connect(":memory:")
        try:
            with self.assertRaisesRegex(ValueError, "Длительность записи должна быть больше нуля"):
                ensure_no_appointment_conflict(conn, "2026-06-12T10:00:00", 0)
            
            with self.assertRaisesRegex(ValueError, "Длительность записи должна быть больше нуля"):
                ensure_no_appointment_conflict(conn, "2026-06-12T10:00:00", -10)
        finally:
            conn.close()

    def test_timezone_mix_appointment_conflict_combinations(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, deleted_at TEXT)"
        )
        conn.execute(
            "INSERT INTO customers (id, name, deleted_at) VALUES (1, 'Customer', NULL)"
        )
        conn.execute(
            """
            CREATE TABLE appointments (
                id INTEGER PRIMARY KEY,
                customer_id INTEGER,
                vehicle_id INTEGER,
                scheduled_at TEXT,
                duration_minutes INTEGER,
                status TEXT,
                deleted_at TEXT
            )
            """
        )
        from sto_crm.validation import ensure_no_appointment_conflict

        def setup_existing(scheduled_at_str, duration=60):
            conn.execute("DELETE FROM appointments")
            conn.execute(
                """
                INSERT INTO appointments (id, customer_id, vehicle_id, scheduled_at, duration_minutes, status, deleted_at)
                VALUES (1, 1, NULL, ?, ?, 'scheduled', NULL)
                """,
                (scheduled_at_str, duration),
            )

        from datetime import datetime, timedelta
        existing_dt = datetime(2026, 6, 12, 10, 0, 0, tzinfo=UTC)
        local_dt_naive = existing_dt.astimezone().replace(tzinfo=None)
        
        setup_existing(existing_dt.isoformat())
        with self.assertRaisesRegex(ValueError, "На это время уже есть запись"):
            ensure_no_appointment_conflict(conn, local_dt_naive.isoformat(), 30)

        naive_str = "2026-06-12T10:00:00"
        setup_existing(naive_str)
        naive_dt = datetime.fromisoformat(naive_str)
        local_tz = datetime.now().astimezone().tzinfo
        local_aware_dt = naive_dt.replace(tzinfo=local_tz)
        with self.assertRaisesRegex(ValueError, "На это время уже есть запись"):
            ensure_no_appointment_conflict(conn, local_aware_dt.isoformat(), 30)

        # Test case where start has tz, existing does not, and there is no conflict
        local_aware_non_conflict_dt = (naive_dt + timedelta(hours=2)).replace(tzinfo=local_tz)
        ensure_no_appointment_conflict(conn, local_aware_non_conflict_dt.isoformat(), 30)

        setup_existing("2026-06-12T10:00:00")
        with self.assertRaisesRegex(ValueError, "На это время уже есть запись"):
            ensure_no_appointment_conflict(conn, "2026-06-12T10:15:00", 30)

        setup_existing("2026-06-12T10:00:00")
        ensure_no_appointment_conflict(conn, "2026-06-12T11:00:00", 30)

        setup_existing("not-a-datetime")
        ensure_no_appointment_conflict(conn, "2026-06-12T11:00:00", 30)

        conn.close()

    def test_require_non_negative_float(self):
        from sto_crm.validation import require_non_negative_float
        with self.assertRaisesRegex(ValueError, "не может быть отрицательным"):
            require_non_negative_float(-1.5, "цена")
        self.assertEqual(require_non_negative_float(5.5, "цена"), 5.5)

    def test_require_mileage_limit_valid(self):
        from sto_crm.validation import require_mileage_limit
        self.assertEqual(require_mileage_limit(5000, "пробег"), 5000)

    def test_validate_tax_rate(self):
        from sto_crm.validation import validate_tax_rate
        self.assertEqual(validate_tax_rate(5.0), 5.0)
        self.assertEqual(validate_tax_rate(-10.0), 0.0)
        self.assertEqual(validate_tax_rate(150.0), 100.0)

    def test_optional_non_negative_float(self):
        from sto_crm.validation import optional_non_negative_float
        self.assertEqual(optional_non_negative_float("", "цена", 10.0), 10.0)
        self.assertEqual(optional_non_negative_float(None, "цена", 10.0), 10.0)
        self.assertEqual(optional_non_negative_float(15.5, "цена", 10.0), 15.5)

    def test_generate_order_number_happy_path(self):
        from datetime import datetime

        from sto_crm.validation import generate_order_number
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, number TEXT)")
        prefix = datetime.now().strftime("СТО-%Y%m%d")
        
        num1 = generate_order_number(conn)
        self.assertEqual(num1, f"{prefix}-001")
        
        conn.execute("INSERT INTO orders (number) VALUES (?)", (f"{prefix}-001",))
        conn.execute("INSERT INTO orders (number) VALUES (?)", (f"{prefix}-002",))
        conn.execute("INSERT INTO orders (number) VALUES (?)", (f"{prefix}-9999999",))
        conn.execute("INSERT INTO orders (number) VALUES (?)", (f"{prefix}-legacy",))
        
        num2 = generate_order_number(conn)
        self.assertEqual(num2, f"{prefix}-003")
        conn.close()

    def test_validate_customer_happy_path(self):
        payload = {
            "name": "Иван Иванов",
            "phone": "79991112233",
            "email": "IVAN@example.com",
            "source": "Иванов",
            "preferred_channel": "messenger",
            "reminder_consent": True,
            "notes": "some notes"
        }
        res = validate_customer(payload)
        self.assertEqual(res["name"], "Иван Иванов")
        self.assertEqual(res["email"], "ivan@example.com")
        self.assertEqual(res["notes"], "some notes")

    def test_validate_vehicle_happy_path(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, deleted_at TEXT)"
        )
        conn.execute(
            "INSERT INTO customers (id, name, deleted_at) VALUES (1, 'Customer', NULL)"
        )
        try:
            payload = {
                "customer_id": 1,
                "make": "Toyota",
                "model": "Camry",
                "year": 2020,
                "plate": "а123вв77",
                "vin": "12345678901234567",
                "mileage": 50000,
                "next_service_at": "2026-12-31",
                "next_service_mileage": 60000,
                "notes": "cool car"
            }
            res = validate_vehicle(conn, payload)
            self.assertEqual(res["make"], "Toyota")
            self.assertEqual(res["plate"], "А123ВВ77")
        finally:
            conn.close()

    def test_validate_inventory_happy_path(self):
        payload = {
            "sku": "parts-123",
            "name": "Свеча зажигания",
            "brand": "NGK",
            "unit": "шт",
            "quantity": 10.0,
            "min_quantity": 2.0,
            "price": 500.0,
            "cost": 300.0,
            "supplier": "SparkLtd",
            "notes": "notes info"
        }
        res = validate_inventory(payload)
        self.assertEqual(res["sku"], "PARTS-123")
        self.assertEqual(res["price"], 500.0)

    def test_validate_appointment_deleted_customer_and_happy_path(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, deleted_at TEXT)"
        )
        conn.execute(
            "INSERT INTO customers (id, name, deleted_at) VALUES (1, 'Customer Active', NULL)"
        )
        conn.execute(
            "INSERT INTO customers (id, name, deleted_at) VALUES (2, 'Customer Deleted', '2026-06-12T12:00:00')"
        )
        conn.execute(
            "CREATE TABLE vehicles (id INTEGER PRIMARY KEY, customer_id INTEGER, deleted_at TEXT)"
        )
        conn.execute(
            "INSERT INTO vehicles (id, customer_id, deleted_at) VALUES (10, 1, NULL)"
        )
        try:
            with self.assertRaisesRegex(ValueError, "Выберите действующего клиента"):
                validate_appointment(conn, {"customer_id": 2})

            with self.assertRaisesRegex(ValueError, "Некорректный статус записи"):
                validate_appointment(conn, {
                    "customer_id": 1,
                    "scheduled_at": "2026-06-12T10:00",
                    "status": "invalid_status"
                })

            payload = {
                "customer_id": 1,
                "vehicle_id": 10,
                "scheduled_at": "2026-06-12T10:00",
                "duration_minutes": 60,
                "status": "scheduled",
                "advisor": "John",
                "reason": "oil change",
                "notes": "very clean"
            }
            res = validate_appointment(conn, payload)
            self.assertEqual(res["status"], "scheduled")
            self.assertEqual(res["advisor"], "John")
        finally:
            conn.close()

    def test_normalize_order_money_details(self):
        from sto_crm.validation import normalize_order_money
        
        order_data = {
            "items": [
                {"quantity": 2, "unit_price": 500.0, "unit_cost": 300.0, "approval_status": "approved"},
                {"quantity": 1, "unit_price": 1000.0, "unit_cost": 600.0, "approval_status": "declined"},
            ],
            "discount": 2000.0,
            "tax_rate": 150.0,
            "paid": 5000.0,
        }
        normalize_order_money(order_data)
        self.assertEqual(order_data["discount"], 1000.0)
        self.assertEqual(order_data["tax_rate"], 100.0)
        self.assertEqual(order_data["paid"], 0.0)
        
        order_data_2 = {
            "items": [
                {"quantity": 1, "unit_price": 1000.0, "unit_cost": 600.0, "approval_status": "approved"},
            ],
            "discount": 200.0,
            "tax_rate": 20.0,
            "paid": 500.0,
        }
        normalize_order_money(order_data_2)
        self.assertEqual(order_data_2["paid"], 500.0)

    def test_validate_order_item_various_errors(self):
        from sto_crm.validation import validate_order_item
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE inventory (id INTEGER PRIMARY KEY, name TEXT, price REAL, cost REAL, deleted_at TEXT)"
        )
        conn.execute(
            "INSERT INTO inventory (id, name, price, cost, deleted_at) VALUES (1, 'Spark Plug', 500.0, 300.0, NULL)"
        )
        conn.execute(
            "INSERT INTO inventory (id, name, price, cost, deleted_at) VALUES (2, 'Oil Filter', 800.0, 400.0, '2026-06-12T12:00:00')"
        )
        try:
            with self.assertRaisesRegex(ValueError, "Позиция заказ-наряда должна быть JSON-объектом"):
                validate_order_item(conn, "not-a-dict")
            
            with self.assertRaisesRegex(ValueError, "Некорректный тип позиции заказ-наряда"):
                validate_order_item(conn, {"kind": "invalid"})

            with self.assertRaisesRegex(ValueError, "Укажите наименование запчасти или работы"):
                validate_order_item(conn, {"kind": "service", "quantity": 1})

            res = validate_order_item(conn, {"kind": "service", "inventory_id": -5, "title": "Labor", "quantity": 1})
            self.assertIsNone(res["inventory_id"])

            res_part = validate_order_item(conn, {
                "kind": "part",
                "inventory_id": 2,
                "quantity": 1,
            }, allow_deleted_inventory_ids={2})
            self.assertEqual(res_part["title"], "Oil Filter")

            res_part_2 = validate_order_item(conn, {
                "kind": "part",
                "inventory_id": 1,
                "quantity": 2,
            })
            self.assertEqual(res_part_2["unit_price"], 500.0)
            self.assertEqual(res_part_2["unit_cost"], 300.0)
        finally:
            conn.close()

    def test_item_is_billable(self):
        from sto_crm.validation import item_is_billable
        self.assertTrue(item_is_billable({"approval_status": "approved"}))
        self.assertFalse(item_is_billable({"approval_status": "declined"}))

    def test_ensure_unique_active_value_checks(self):
        conn = sqlite3.connect(":memory:")
        conn.create_function("CASEFOLD", 1, lambda value: str(value or "").casefold())
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE inventory (id INTEGER PRIMARY KEY, sku TEXT, deleted_at TEXT)")
        conn.execute("INSERT INTO inventory (id, sku, deleted_at) VALUES (10, 'SKU-EXISTING', NULL)")
        try:
            ensure_unique_active_value(conn, "inventory", "sku", "", "error message")
            
            with self.assertRaisesRegex(ValueError, "error message"):
                ensure_unique_active_value(conn, "inventory", "sku", "SKU-existing", "error message")

            ensure_unique_active_value(conn, "inventory", "sku", "SKU-existing", "error message", record_id=10)
        finally:
            conn.close()

    def test_active_appointment_counters(self):
        from sto_crm.validation import (
            active_appointment_count_for_customer,
            active_appointment_count_for_vehicle,
        )
        conn = sqlite3.connect(":memory:")
        conn.execute(
            """
            CREATE TABLE appointments (
                id INTEGER PRIMARY KEY,
                customer_id INTEGER,
                vehicle_id INTEGER,
                status TEXT,
                deleted_at TEXT
            )
            """
        )
        conn.execute("INSERT INTO appointments VALUES (1, 1, 10, 'scheduled', NULL)")
        conn.execute("INSERT INTO appointments VALUES (2, 1, 10, 'confirmed', NULL)")
        conn.execute("INSERT INTO appointments VALUES (3, 1, 10, 'cancelled', NULL)")
        conn.execute("INSERT INTO appointments VALUES (4, 1, 10, 'scheduled', '2026-06-12')")
        try:
            self.assertEqual(active_appointment_count_for_customer(conn, 1), 2)
            self.assertEqual(active_appointment_count_for_vehicle(conn, 10), 2)
        finally:
            conn.close()
