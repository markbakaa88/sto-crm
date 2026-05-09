from __future__ import annotations

"""Optional demonstration data seeding."""

from datetime import datetime, timedelta

from .database import write_db
from .runtime import now_iso
from .services import create_order_tx

def seed_demo_data() -> None:
    with write_db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM customers WHERE deleted_at IS NULL").fetchone()[0]
        if count:
            return
        stamp = now_iso()
        customers = [
            ("Иван Петров", "+7 900 111-22-33", "ivan@example.ru", "Рекомендация", "Постоянный клиент"),
            ("ООО Таксопарк Север", "+7 900 222-33-44", "fleet@example.ru", "Сайт", "Обслуживание парка"),
            ("Мария Соколова", "+7 900 333-44-55", "maria@example.ru", "2ГИС", ""),
        ]
        customer_ids: list[int] = []
        for item in customers:
            cur = conn.execute(
                """
                INSERT INTO customers(name, phone, email, source, notes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (*item, stamp, stamp),
            )
            customer_ids.append(int(cur.lastrowid))

        next_service_date = (datetime.now() + timedelta(days=10)).date().isoformat()
        vehicles = [
            (customer_ids[0], "Toyota", "Camry", 2018, "A123AA", "JTNB11HK303000001", 82000, next_service_date, 90000, ""),
            (customer_ids[1], "Hyundai", "Solaris", 2021, "T451TX", "Z94K241CBMR000002", 146000, "", 150000, "Такси"),
            (customer_ids[2], "Kia", "Sportage", 2020, "M777MA", "XWEPH81BDL0000003", 61000, "", 0, ""),
        ]
        vehicle_ids: list[int] = []
        for item in vehicles:
            cur = conn.execute(
                """
                INSERT INTO vehicles(customer_id, make, model, year, plate, vin, mileage, next_service_at, next_service_mileage, notes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (*item, stamp, stamp),
            )
            vehicle_ids.append(int(cur.lastrowid))

        parts = [
            ("OF-TY-041", "Фильтр масляный", "Toyota", "шт", 18, 5, 850, 520, "АвтоПартс"),
            ("OIL-5W30-4L", "Масло моторное 5W-30 4 л", "Shell", "шт", 10, 3, 3900, 2850, "МаслоСклад"),
            ("PAD-FR-211", "Колодки тормозные передние", "Nibk", "компл", 4, 2, 5200, 3600, "ТормозМаркет"),
            ("AIR-HY-001", "Фильтр воздушный", "Hyundai", "шт", 2, 4, 1200, 780, "АвтоПартс"),
            ("BATT-60", "АКБ 60 А·ч", "Mutlu", "шт", 3, 1, 8200, 6400, "ЭлектроСнаб"),
        ]
        part_ids: list[int] = []
        for item in parts:
            cur = conn.execute(
                """
                INSERT INTO inventory(sku, name, brand, unit, quantity, min_quantity, price, cost, supplier, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (*item, stamp, stamp),
            )
            part_ids.append(int(cur.lastrowid))

        promised = (datetime.now() + timedelta(days=1)).replace(microsecond=0).isoformat(timespec="minutes")
        order_id = create_order_tx(
            conn,
            {
                "customer_id": customer_ids[0],
                "vehicle_id": vehicle_ids[0],
                "status": "in_progress",
                "priority": "normal",
                "advisor": "Администратор",
                "mechanic": "Сергей",
                "promised_at": promised,
                "odometer": 82000,
                "complaint": "Плановое ТО, шум при торможении.",
                "diagnosis": "Требуется замена масла и проверка тормозной системы.",
                "recommendations": "Контрольный осмотр через 10 000 км.",
                "discount": 0,
                "tax_rate": 0,
                "paid": 0,
                "items": [
                    {"kind": "service", "title": "Замена масла и фильтра", "quantity": 1, "unit_price": 2200, "unit_cost": 0},
                    {"kind": "part", "inventory_id": part_ids[0], "title": "Фильтр масляный", "quantity": 1, "unit_price": 850, "unit_cost": 520},
                    {"kind": "part", "inventory_id": part_ids[1], "title": "Масло моторное 5W-30 4 л", "quantity": 1, "unit_price": 3900, "unit_cost": 2850},
                ],
            },
        )
        _ = order_id

        create_order_tx(
            conn,
            {
                "customer_id": customer_ids[1],
                "vehicle_id": vehicle_ids[1],
                "status": "new",
                "priority": "high",
                "advisor": "Администратор",
                "mechanic": "",
                "promised_at": (datetime.now() + timedelta(hours=5)).replace(microsecond=0).isoformat(timespec="minutes"),
                "odometer": 146000,
                "complaint": "Неравномерная работа двигателя.",
                "diagnosis": "",
                "recommendations": "",
                "discount": 0,
                "tax_rate": 0,
                "paid": 0,
                "items": [
                    {"kind": "service", "title": "Компьютерная диагностика", "quantity": 1, "unit_price": 1800, "unit_cost": 0}
                ],
            },
        )
        appointment_time = (datetime.now() + timedelta(hours=2)).replace(microsecond=0).isoformat(timespec="minutes")
        conn.execute(
            """
            INSERT INTO appointments(customer_id, vehicle_id, scheduled_at, duration_minutes, status,
                                     advisor, reason, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                customer_ids[2],
                vehicle_ids[2],
                appointment_time,
                60,
                "confirmed",
                "Администратор",
                "Диагностика подвески",
                "Подготовить подъемник и проверить историю обслуживания.",
                stamp,
                stamp,
            ),
        )
        inspection_time = datetime.now().replace(microsecond=0).isoformat(timespec="minutes")
        cur = conn.execute(
            """
            INSERT INTO inspections(customer_id, vehicle_id, order_id, status, inspector, inspected_at,
                                    summary, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                customer_ids[0],
                vehicle_ids[0],
                order_id,
                "ready",
                "Сергей",
                inspection_time,
                "Мульти-точечный осмотр перед согласованием дополнительных работ.",
                stamp,
                stamp,
            ),
        )
        inspection_id = int(cur.lastrowid)
        conn.executemany(
            """
            INSERT INTO inspection_items(inspection_id, area, title, condition_status, approval_status,
                                         recommendation, estimate, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (inspection_id, "Тормоза", "Передние тормозные колодки", "attention", "deferred", "Рекомендовать замену в ближайший визит.", 5200, stamp),
                (inspection_id, "Жидкости", "Уровень и состояние моторного масла", "ok", "approved", "Без замечаний.", 0, stamp),
                (inspection_id, "Свет", "Проверка наружного освещения", "ok", "approved", "Без замечаний.", 0, stamp),
            ],
        )
