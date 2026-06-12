import tempfile
import time
import unittest
from pathlib import Path

from sto_crm import runtime as _runtime
from sto_crm.database import connect, init_db
from sto_crm.runtime import Runtime
from sto_crm.services import (
    create_appointment,
    create_customer,
    create_vehicle,
    delete_appointment,
    delete_customer,
    get_appointment,
    get_customer,
    get_vehicle,
    update_appointment,
    update_customer,
)


class TestServicesExtra(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.runtime_db = Path(self.tmpdir.name) / "test_services_extra.sqlite3"
        self.orig_runtime = _runtime.RUNTIME
        _runtime.RUNTIME = Runtime(
            db_path=self.runtime_db,
            start_time=time.time(),
            csrf_token="test_csrf",
            access_token="test_access",
            bootstrap_token="test_bootstrap"
        )
        init_db(seed_demo=True)

    def tearDown(self) -> None:
        _runtime.RUNTIME = self.orig_runtime
        self.tmpdir.cleanup()

    def test_update_customer_success(self):
        c = create_customer({"name": "Initial Name", "phone": "1112223344", "reminder_consent": True})
        updated = update_customer(c["id"], {"name": "Updated Name", "phone": "1112223344", "reminder_consent": False})
        self.assertEqual(updated["name"], "Updated Name")
        self.assertEqual(updated["reminder_consent"], 0)

    def test_update_customer_failures(self):
        # 1. Non-existent customer
        with self.assertRaises(KeyError):
            update_customer(9999, {"name": "Nonexistent", "phone": "123", "reminder_consent": True})

    def test_delete_customer_failures_with_vehicles_and_orders(self):
        # Добавим клиента
        c = create_customer({"name": "Test Cust", "phone": "9998887766", "reminder_consent": True})
        cid = c["id"]
        # Добавим ему машинку
        v = create_vehicle({
            "vin": "JTNB11HK303000999",
            "make": "Toyota",
            "model": "RAV4",
            "year": 2020,
            "plate": "B999BB99",
            "mileage": 1000,
            "customer_id": cid
        })
        vid = v["id"]
        
        # Создадим заказ-наряд на ЭТОГО КЛИЕНТА напрямую через sqlite
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO orders(customer_id, vehicle_id, status, priority, number, created_at, updated_at)
                VALUES (?, ?, 'new', 'normal', 'TEST-001', '2026-06-12T10:00', '2026-06-12T10:00')
                """,
                (cid, vid)
            )
            conn.commit()

        # Попытка удалить клиента должна выбросить ValueError, т.к. у него есть заказы
        with self.assertRaises(ValueError) as ctx:
            delete_customer(cid)
        self.assertIn("У клиента есть заказ-наряды", str(ctx.exception))

    def test_delete_customer_failures_with_only_vehicle_having_orders(self):
        # Добавим клиента 1
        c1 = create_customer({"name": "Client One", "phone": "9998887761", "reminder_consent": True})
        cid1 = c1["id"]
        # Добавим клиента 2
        c2 = create_customer({"name": "Client Two", "phone": "9998887762", "reminder_consent": True})
        cid2 = c2["id"]

        # Машина принадлежит c1
        v = create_vehicle({
            "vin": "JTNB11HK303000111",
            "make": "Toyota",
            "model": "RAV4",
            "year": 2020,
            "plate": "B111BB99",
            "mileage": 1000,
            "customer_id": cid1
        })
        vid = v["id"]

        # Но заказ оформлен на c2!
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO orders(customer_id, vehicle_id, status, priority, number, created_at, updated_at)
                VALUES (?, ?, 'new', 'normal', 'TEST-002', '2026-06-12T10:00', '2026-06-12T10:00')
                """,
                (cid2, vid)
            )
            conn.commit()

        # У c1 лично нет orders (он без заказов на своё имя), но у его машины есть заказ!
        with self.assertRaises(ValueError) as ctx:
            delete_customer(cid1)
        self.assertIn("автомобили с заказ-нарядами", str(ctx.exception))

    def test_delete_customer_failures_with_vehicles_and_appointments(self):
        # Добавим клиента
        c = create_customer({"name": "Test Cust 2", "phone": "9998887722", "reminder_consent": True})
        cid = c["id"]
        # Добавим машинку
        v = create_vehicle({
            "vin": "JTNB11HK303000888",
            "make": "Toyota",
            "model": "RAV4",
            "year": 2020,
            "plate": "B888BB99",
            "mileage": 1000,
            "customer_id": cid
        })
        vid = v["id"]

        # Создадим запись в календаре на эту машинку
        create_appointment({
            "customer_id": cid,
            "vehicle_id": vid,
            "scheduled_at": "2026-06-15T12:00",
            "duration_minutes": 60,
            "status": "scheduled"
        })

        # Попытка удалить клиента должна выбросить ValueError, т.к. у его авто есть активные записи
        with self.assertRaises(ValueError) as ctx:
            delete_customer(cid)
        self.assertIn("активные записи в календаре", str(ctx.exception))

    def test_delete_customer_failures_with_vehicle_appointed_to_other_customer(self):
        # Добавим клиента c1
        c1 = create_customer({"name": "Client App1", "phone": "9998887751", "reminder_consent": True})
        cid1 = c1["id"]
        # Добавим клиента c2
        c2 = create_customer({"name": "Client App2", "phone": "9998887752", "reminder_consent": True})
        cid2 = c2["id"]

        # Машина принадлежит c1
        v = create_vehicle({
            "vin": "JTNB11HK303000881",
            "make": "Toyota",
            "model": "RAV4",
            "year": 2020,
            "plate": "B881BB99",
            "mileage": 1000,
            "customer_id": cid1
        })
        vid = v["id"]

        # Но запись в календаре оформлена на c2 и машину c1! Вставим напрямую через БД
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO appointments(customer_id, vehicle_id, scheduled_at, duration_minutes, status, created_at, updated_at)
                VALUES (?, ?, '2026-06-16T10:00', 60, 'scheduled', '2026-06-12T10:00', '2026-06-12T10:00')
                """,
                (cid2, vid)
            )
            conn.commit()

        # Проверим строку 110:
        # У клиента c1 лично нет active_appointment, но его машина vid имеет встречу!
        with self.assertRaises(ValueError) as ctx:
            delete_customer(cid1)
        self.assertIn("активными записями в календаре. Завершите или отмените их", str(ctx.exception))

    def test_update_appointment_success(self):
        # Создаем клиента и машинку
        c = create_customer({"name": "Cust", "phone": "1312312312", "reminder_consent": True})
        v = create_vehicle({
            "vin": "JTNB11HK303000889",
            "make": "Toyota",
            "model": "RAV4",
            "year": 2020,
            "plate": "B889BB99",
            "mileage": 1000,
            "customer_id": c["id"]
        })
        app = create_appointment({
            "customer_id": c["id"],
            "vehicle_id": v["id"],
            "scheduled_at": "2026-06-17T12:00",
            "duration_minutes": 60,
            "status": "scheduled"
        })
        # Обновим время
        updated = update_appointment(app["id"], {
            "customer_id": c["id"],
            "vehicle_id": v["id"],
            "scheduled_at": "2026-06-17T15:00",
            "duration_minutes": 45,
            "status": "scheduled"
        })
        self.assertEqual(updated["scheduled_at"], "2026-06-17T15:00")
        self.assertEqual(updated["duration_minutes"], 45)

        # Удалим запись (покроем delete_appointment)
        res = delete_appointment(app["id"])
        self.assertTrue(res["deleted"])

    def test_update_appointment_not_found(self):
        with self.assertRaises(KeyError):
            update_appointment(9999, {
                "customer_id": 1,
                "scheduled_at": "2026-06-15T12:00",
                "duration_minutes": 60,
                "status": "scheduled"
            })

    def test_delete_appointment_not_found(self):
        with self.assertRaises(KeyError):
            delete_appointment(9999)

    def test_get_appointment_not_found(self):
        with connect() as conn:
            with self.assertRaises(KeyError):
                get_appointment(conn, 9999)

    def test_get_customer_not_found(self):
        with connect() as conn:
            with self.assertRaises(KeyError):
                get_customer(conn, 9999)

    def test_get_vehicle_not_found(self):
        with connect() as conn:
            with self.assertRaises(KeyError):
                get_vehicle(conn, 9999)
