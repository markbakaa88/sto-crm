"""Transactional create/update/delete operations for CRM entities."""

from __future__ import annotations

import logging
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from .config import (
    APPOINTMENT_ACTIVE_STATUSES,
    CONSUMING_STATUSES,
    ORDER_STATUS_TRANSITIONS,
)
from .database import write_db
from .runtime import now_iso, parse_float, parse_int
from .validation import (
    active_appointment_count_for_customer,
    active_appointment_count_for_vehicle,
    active_exists,
    ensure_no_appointment_conflict,
    ensure_unique_active_value,
    generate_order_number,
    item_is_billable,
    normalize_order_money,
    validate_appointment,
    validate_customer,
    validate_inventory,
    validate_order,
    validate_vehicle,
)

logger = logging.getLogger("sto_crm")

def _query_get_order(conn: sqlite3.Connection, record_id: int) -> dict[str, Any]:
    # Lazy import разрывает цикл queries → services.
    from .queries import get_order

    return get_order(conn, record_id)


def create_customer(payload: dict[str, Any]) -> dict[str, Any]:
    logger.info("Creating a new customer")
    data = validate_customer(payload)
    stamp = now_iso()
    with write_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO customers(name, phone, email, source, preferred_channel, reminder_consent, notes, created_at, updated_at)
            VALUES (:name, :phone, :email, :source, :preferred_channel, :reminder_consent, :notes, :created_at, :updated_at)
            """,
            {**data, "created_at": stamp, "updated_at": stamp},
        )
        return get_customer(conn, int(cur.lastrowid or 0))


def update_customer(record_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    data = validate_customer(payload)
    with write_db() as conn:
        if not active_exists(conn, "customers", record_id):
            raise KeyError("Клиент не найден.")
        conn.execute(
            """
            UPDATE customers
            SET name=:name, phone=:phone, email=:email, source=:source, preferred_channel=:preferred_channel,
                reminder_consent=:reminder_consent, notes=:notes, updated_at=:updated_at
            WHERE id=:id AND deleted_at IS NULL
            """,
            {**data, "updated_at": now_iso(), "id": record_id},
        )
        return get_customer(conn, record_id)


def delete_customer(record_id: int) -> dict[str, Any]:
    with write_db() as conn:
        if not active_exists(conn, "customers", record_id):
            raise KeyError("Клиент не найден.")
        orders_count = conn.execute(
            """
            SELECT COUNT(*) FROM orders
            WHERE customer_id = ? AND deleted_at IS NULL
            """,
            (record_id,),
        ).fetchone()[0]
        if orders_count:
            raise ValueError(
                "У клиента есть заказ-наряды. Сначала удалите или перенесите связанные заказы."
            )
        appointments_count = active_appointment_count_for_customer(conn, record_id)
        if appointments_count:
            raise ValueError(
                "У клиента есть активные записи в календаре. Завершите или отмените их перед удалением клиента."
            )
        stamp = now_iso()
        for vehicle in conn.execute(
            "SELECT id FROM vehicles WHERE customer_id = ? AND deleted_at IS NULL",
            (record_id,),
        ).fetchall():
            vid = vehicle["id"]
            if conn.execute(
                "SELECT COUNT(*) FROM orders WHERE vehicle_id = ? AND deleted_at IS NULL",
                (vid,),
            ).fetchone()[0]:
                raise ValueError(
                    "У клиента есть автомобили с заказ-нарядами. Сначала удалите или перенесите заказы."
                )
            if active_appointment_count_for_vehicle(conn, vid):
                raise ValueError(
                    "У клиента есть автомобили с активными записями в календаре. Завершите или отмените их перед удалением."
                )
        conn.execute(
            "UPDATE customers SET deleted_at=?, updated_at=? WHERE id=? AND deleted_at IS NULL",
            (stamp, stamp, record_id),
        )
        conn.execute(
            "UPDATE appointments SET deleted_at=?, updated_at=? WHERE customer_id=? AND deleted_at IS NULL",
            (stamp, stamp, record_id),
        )
        conn.execute(
            "UPDATE vehicles SET deleted_at=?, updated_at=? WHERE customer_id=? AND deleted_at IS NULL",
            (stamp, stamp, record_id),
        )
        return {"deleted": True}


def get_customer(conn: sqlite3.Connection, record_id: int) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM customers WHERE id = ? AND deleted_at IS NULL", (record_id,)
    ).fetchone()
    if not row:
        raise KeyError("Клиент не найден.")
    return dict(row)


def create_vehicle(payload: dict[str, Any]) -> dict[str, Any]:
    logger.info("Creating a new vehicle")
    with write_db() as conn:
        data = validate_vehicle(conn, payload)
        ensure_unique_active_value(
            conn,
            "vehicles",
            "vin",
            data["vin"],
            "Автомобиль с таким VIN уже есть в базе.",
        )
        ensure_unique_active_value(
            conn,
            "vehicles",
            "plate",
            data["plate"],
            "Автомобиль с таким госномером уже есть в базе.",
        )
        stamp = now_iso()
        cur = conn.execute(
            """
            INSERT INTO vehicles(customer_id, make, model, year, plate, vin, mileage, mileage_manual, next_service_at,
                                 next_service_mileage, notes, created_at, updated_at)
            VALUES (:customer_id, :make, :model, :year, :plate, :vin, :mileage, :mileage, :next_service_at,
                    :next_service_mileage, :notes, :created_at, :updated_at)
            """,
            {**data, "created_at": stamp, "updated_at": stamp},
        )
        return get_vehicle(conn, int(cur.lastrowid or 0))


def update_vehicle(record_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    with write_db() as conn:
        old = conn.execute(
            "SELECT customer_id FROM vehicles WHERE id = ? AND deleted_at IS NULL",
            (record_id,),
        ).fetchone()
        if not old:
            raise KeyError("Автомобиль не найден.")
        data = validate_vehicle(conn, payload)
        ensure_unique_active_value(
            conn,
            "vehicles",
            "vin",
            data["vin"],
            "Автомобиль с таким VIN уже есть в базе.",
            record_id,
        )
        ensure_unique_active_value(
            conn,
            "vehicles",
            "plate",
            data["plate"],
            "Автомобиль с таким госномером уже есть в базе.",
            record_id,
        )
        if int(old["customer_id"]) != int(data["customer_id"]):
            orders_count = conn.execute(
                "SELECT COUNT(*) FROM orders WHERE vehicle_id = ? AND deleted_at IS NULL",
                (record_id,),
            ).fetchone()[0]
            if orders_count:
                raise ValueError(
                    "Нельзя сменить клиента у автомобиля с заказ-нарядами."
                )
            if active_appointment_count_for_vehicle(conn, record_id):
                raise ValueError(
                    "Нельзя сменить клиента у автомобиля с активными записями в календаре."
                )
        manual_mileage = parse_int(data["mileage"])
        order_mileage_id, order_mileage = vehicle_order_mileage_source(conn, record_id)
        visible_mileage = max(manual_mileage, order_mileage)
        # Значение из формы сохраняем как ручной baseline, но видимый пробег не
        # опускаем ниже максимального актуального одометра из заказ-нарядов. Это
        # защищает от stale-save: старая вкладка может сохранить заметку/план ТО
        # со старым пробегом, но не должна откатывать свежую историю автомобиля.
        mileage_order_id = order_mileage_id if order_mileage > manual_mileage else None
        conn.execute(
            """
            UPDATE vehicles
            SET customer_id=:customer_id, make=:make, model=:model, year=:year, plate=:plate,
                vin=:vin, mileage=:visible_mileage, mileage_manual=:manual_mileage,
                mileage_order_id=:mileage_order_id, next_service_at=:next_service_at,
                next_service_mileage=:next_service_mileage, notes=:notes, updated_at=:updated_at
            WHERE id=:id AND deleted_at IS NULL
            """,
            {
                **data,
                "visible_mileage": visible_mileage,
                "manual_mileage": manual_mileage,
                "mileage_order_id": mileage_order_id,
                "updated_at": now_iso(),
                "id": record_id,
            },
        )
        return get_vehicle(conn, record_id)


def delete_vehicle(record_id: int) -> dict[str, Any]:
    with write_db() as conn:
        if not active_exists(conn, "vehicles", record_id):
            raise KeyError("Автомобиль не найден.")
        orders_count = conn.execute(
            """
            SELECT COUNT(*) FROM orders
            WHERE vehicle_id = ? AND deleted_at IS NULL
            """,
            (record_id,),
        ).fetchone()[0]
        if orders_count:
            raise ValueError(
                "По автомобилю есть заказ-наряды. Сначала удалите или измените связанные заказы."
            )
        appointments_count = active_appointment_count_for_vehicle(conn, record_id)
        if appointments_count:
            raise ValueError(
                "По автомобилю есть активные записи в календаре. Завершите или отмените их перед удалением автомобиля."
            )
        stamp = now_iso()
        conn.execute(
            "UPDATE vehicles SET deleted_at=?, updated_at=? WHERE id=? AND deleted_at IS NULL",
            (stamp, stamp, record_id),
        )
        conn.execute(
            "UPDATE appointments SET deleted_at=?, updated_at=? WHERE vehicle_id=? AND deleted_at IS NULL",
            (stamp, stamp, record_id),
        )
        return {"deleted": True}


def get_vehicle(conn: sqlite3.Connection, record_id: int) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT v.*, c.name AS customer_name
        FROM vehicles v
        JOIN customers c ON c.id = v.customer_id
        WHERE v.id = ? AND v.deleted_at IS NULL
        """,
        (record_id,),
    ).fetchone()
    if not row:
        raise KeyError("Автомобиль не найден.")
    return dict(row)


def create_appointment(payload: dict[str, Any]) -> dict[str, Any]:
    logger.info("Creating a new appointment")
    with write_db() as conn:
        data = validate_appointment(conn, payload)
        if data["status"] in APPOINTMENT_ACTIVE_STATUSES:
            ensure_no_appointment_conflict(
                conn, data["scheduled_at"], data["duration_minutes"]
            )
        stamp = now_iso()
        cur = conn.execute(
            """
            INSERT INTO appointments(customer_id, vehicle_id, scheduled_at, duration_minutes, status,
                                     advisor, reason, notes, created_at, updated_at)
            VALUES (:customer_id, :vehicle_id, :scheduled_at, :duration_minutes, :status,
                    :advisor, :reason, :notes, :created_at, :updated_at)
            """,
            {**data, "created_at": stamp, "updated_at": stamp},
        )
        return get_appointment(conn, int(cur.lastrowid or 0))


def update_appointment(record_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    with write_db() as conn:
        if not active_exists(conn, "appointments", record_id):
            raise KeyError("Запись не найдена.")
        data = validate_appointment(conn, payload)
        if data["status"] in APPOINTMENT_ACTIVE_STATUSES:
            ensure_no_appointment_conflict(
                conn,
                data["scheduled_at"],
                data["duration_minutes"],
                record_id=record_id,
            )
        conn.execute(
            """
            UPDATE appointments
            SET customer_id=:customer_id, vehicle_id=:vehicle_id, scheduled_at=:scheduled_at,
                duration_minutes=:duration_minutes, status=:status, advisor=:advisor,
                reason=:reason, notes=:notes, updated_at=:updated_at
            WHERE id=:id AND deleted_at IS NULL
            """,
            {**data, "updated_at": now_iso(), "id": record_id},
        )
        return get_appointment(conn, record_id)


def delete_appointment(record_id: int) -> dict[str, Any]:
    with write_db() as conn:
        if not active_exists(conn, "appointments", record_id):
            raise KeyError("Запись не найдена.")
        stamp = now_iso()
        conn.execute(
            "UPDATE appointments SET deleted_at=?, updated_at=? WHERE id=? AND deleted_at IS NULL",
            (stamp, stamp, record_id),
        )
        return {"deleted": True}


def get_appointment(conn: sqlite3.Connection, record_id: int) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT a.*, c.name AS customer_name, c.phone AS customer_phone,
               v.make AS vehicle_make, v.model AS vehicle_model, v.year AS vehicle_year,
               v.plate AS vehicle_plate, v.vin AS vehicle_vin
        FROM appointments a
        JOIN customers c ON c.id = a.customer_id
        LEFT JOIN vehicles v ON v.id = a.vehicle_id
        WHERE a.id = ?
          AND a.deleted_at IS NULL
          AND c.deleted_at IS NULL
          AND (a.vehicle_id IS NULL OR v.deleted_at IS NULL)
        """,
        (record_id,),
    ).fetchone()
    if not row:
        raise KeyError("Запись не найдена.")
    return dict(row)


def create_inventory(payload: dict[str, Any]) -> dict[str, Any]:
    data = validate_inventory(payload)
    stamp = now_iso()
    with write_db() as conn:
        ensure_unique_active_value(
            conn,
            "inventory",
            "sku",
            data["sku"],
            "Складская позиция с таким артикулом уже есть в базе.",
        )
        cur = conn.execute(
            """
            INSERT INTO inventory(sku, name, brand, unit, quantity, min_quantity, price, cost, supplier, notes, created_at, updated_at)
            VALUES (:sku, :name, :brand, :unit, :quantity, :min_quantity, :price, :cost, :supplier, :notes, :created_at, :updated_at)
            """,
            {**data, "created_at": stamp, "updated_at": stamp},
        )
        return get_inventory(conn, int(cur.lastrowid or 0))


def update_inventory(record_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    data = validate_inventory(payload)
    with write_db() as conn:
        current = get_inventory(conn, record_id)
        ensure_unique_active_value(
            conn,
            "inventory",
            "sku",
            data["sku"],
            "Складская позиция с таким артикулом уже есть в базе.",
            record_id,
        )
        closed_usage = conn.execute(
            """
            SELECT 1
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id
            WHERE oi.inventory_id = ?
              AND oi.approval_status = 'approved'
              AND o.status = 'closed'
              AND o.deleted_at IS NULL
            LIMIT 1
            """,
            (record_id,),
        ).fetchone()
        if (
            closed_usage
            and abs(parse_float(data["quantity"]) - parse_float(current["quantity"]))
            > 0.000001
        ):
            raise ValueError(
                "Остаток позиции участвует в закрытых заказах. Создайте отдельную складскую корректировку или отмените связанный закрытый заказ без изменения его позиций."
            )
        if parse_float(data["quantity"]) + 0.000001 < reserved_quantity(
            conn, record_id
        ):
            raise ValueError(
                "Остаток позиции меньше уже зарезервированного количества в активных заказах. Сначала измените активные заказ-наряды."
            )
        conn.execute(
            """
            UPDATE inventory
            SET sku=:sku, name=:name, brand=:brand, unit=:unit, quantity=:quantity, min_quantity=:min_quantity,
                price=:price, cost=:cost, supplier=:supplier, notes=:notes, updated_at=:updated_at
            WHERE id=:id AND deleted_at IS NULL
            """,
            {**data, "updated_at": now_iso(), "id": record_id},
        )
        return get_inventory(conn, record_id)


def delete_inventory(record_id: int) -> dict[str, Any]:
    with write_db() as conn:
        if not active_exists(conn, "inventory", record_id):
            raise KeyError("Складская позиция не найдена.")
        protected_usage = conn.execute(
            """
            SELECT 1
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id
            WHERE oi.inventory_id = ?
              AND o.deleted_at IS NULL
              AND o.status <> 'cancelled'
            LIMIT 1
            """,
            (record_id,),
        ).fetchone()
        if protected_usage:
            raise ValueError(
                "Позиция используется в активных или закрытых заказ-нарядах. Сначала удалите или измените активные заказы либо явно отмените закрытые."
            )
        stamp = now_iso()
        conn.execute(
            "UPDATE inventory SET deleted_at=?, updated_at=? WHERE id=? AND deleted_at IS NULL",
            (stamp, stamp, record_id),
        )
        return {"deleted": True}


def get_inventory(conn: sqlite3.Connection, record_id: int) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM inventory WHERE id = ? AND deleted_at IS NULL", (record_id,)
    ).fetchone()
    if not row:
        raise KeyError("Складская позиция не найдена.")
    return dict(row)


def create_order(payload: dict[str, Any]) -> dict[str, Any]:
    with write_db() as conn:
        order_id = create_order_tx(conn, payload)
        return _query_get_order(conn, order_id)


def sync_vehicle_mileage_from_order(
    conn: sqlite3.Connection, vehicle_id: int | None, order_id: int, odometer: int
) -> None:
    """Raise the vehicle card mileage when an order contains a newer reading."""
    if not vehicle_id or not order_id or odometer <= 0:
        return
    stamp = now_iso()
    conn.execute(
        """
        UPDATE vehicles
        SET mileage_manual = CASE
                WHEN mileage_order_id IS NULL AND mileage > mileage_manual THEN mileage
                ELSE mileage_manual
            END,
            mileage = CASE WHEN mileage < ? THEN ? ELSE mileage END,
            mileage_order_id = CASE WHEN mileage < ? THEN ? ELSE mileage_order_id END,
            updated_at = CASE WHEN mileage < ? THEN ? ELSE updated_at END
        WHERE id = ? AND deleted_at IS NULL
        """,
        (odometer, odometer, odometer, order_id, odometer, stamp, vehicle_id),
    )


def vehicle_order_mileage_source(
    conn: sqlite3.Connection, vehicle_id: int | None
) -> tuple[int | None, int]:
    """Return the highest active order odometer and its source order id."""
    if not vehicle_id:
        return None, 0
    row = conn.execute(
        """
        SELECT id, odometer
        FROM orders
        WHERE vehicle_id = ?
          AND deleted_at IS NULL
          AND status <> 'cancelled'
          AND odometer > 0
        ORDER BY odometer DESC, id DESC
        LIMIT 1
        """,
        (vehicle_id,),
    ).fetchone()
    if not row:
        return None, 0
    return int(row["id"]), parse_int(row["odometer"])


def reconcile_vehicle_mileage_after_order_change(
    conn: sqlite3.Connection,
    vehicle_id: int | None,
    *,
    previous_order_id: int,
    previous_odometer: int = 0,
) -> None:
    """Repoint or lower stale order-synced mileage after an order changes.

    Manual mileage entered directly on the vehicle card is preserved. We only
    touch the card when it still equals the previous order reading and explicitly
    points to that order as the source of the synchronized mileage. If another
    active order has the same highest odometer, transfer the source pointer to it
    instead of leaving a stale reference to the changed or deleted order.
    """
    if not vehicle_id or not previous_order_id or previous_odometer <= 0:
        return
    row = conn.execute(
        "SELECT mileage, mileage_manual, mileage_order_id FROM vehicles WHERE id = ? AND deleted_at IS NULL",
        (vehicle_id,),
    ).fetchone()
    if (
        not row
        or parse_int(row["mileage"]) != previous_odometer
        or parse_int(row["mileage_order_id"]) != previous_order_id
    ):
        return
    manual_odometer = parse_int(row["mileage_manual"])
    max_order_id, max_order_odometer = vehicle_order_mileage_source(conn, vehicle_id)
    target_odometer = max(manual_odometer, max_order_odometer)
    target_order_id = max_order_id if max_order_odometer >= manual_odometer else None
    if target_odometer == previous_odometer and target_order_id == previous_order_id:
        return
    stamp = now_iso()
    conn.execute(
        """
        UPDATE vehicles
        SET mileage = ?, mileage_order_id = ?, updated_at = ?
        WHERE id = ? AND deleted_at IS NULL AND mileage = ?
        """,
        (target_odometer, target_order_id, stamp, vehicle_id, previous_odometer),
    )


def create_order_tx(conn: sqlite3.Connection, payload: dict[str, Any]) -> int:
    logger.info("Creating new order transaction")
    data = validate_order(conn, payload)
    stamp = now_iso()
    number = generate_order_number(conn)
    if data["status"] == "closed" and not data["follow_up_at"]:
        data["follow_up_at"] = (
            (datetime.now() + timedelta(days=1))
            .replace(microsecond=0)
            .isoformat(timespec="minutes")
        )
    if status_needs_inventory_availability_check("", data["status"]):
        ensure_inventory_available_for_order(conn, data["items"])
    apply_inventory_delta(conn, "", data["status"], [], data["items"])
    cur = conn.execute(
        """
        INSERT INTO orders(number, customer_id, vehicle_id, status, priority, advisor, mechanic, promised_at,
                           odometer, complaint, diagnosis, recommendations, discount, tax_rate, paid,
                           payment_method, authorized_by, authorized_at, follow_up_at, closed_at, created_at, updated_at)
        VALUES (:number, :customer_id, :vehicle_id, :status, :priority, :advisor, :mechanic, :promised_at,
                :odometer, :complaint, :diagnosis, :recommendations, :discount, :tax_rate, :paid,
                :payment_method, :authorized_by, :authorized_at, :follow_up_at, :closed_at, :created_at, :updated_at)
        """,
        {
            **{k: v for k, v in data.items() if k != "items"},
            "number": number,
            "closed_at": stamp if data["status"] == "closed" else "",
            "created_at": stamp,
            "updated_at": stamp,
        },
    )
    order_id = int(cur.lastrowid or 0)
    insert_order_items(conn, order_id, data["items"])
    if data["status"] != "cancelled":
        sync_vehicle_mileage_from_order(
            conn, data["vehicle_id"], order_id, data["odometer"]
        )
    return order_id


def update_order(record_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    logger.info(f"Updating order {record_id}")
    with write_db() as conn:
        old = conn.execute(
            "SELECT * FROM orders WHERE id=? AND deleted_at IS NULL", (record_id,)
        ).fetchone()
        if not old:
            raise KeyError("Заказ-наряд не найден.")
        old_items = list_order_items(conn, record_id)
        old_status = str(old["status"])
        old_deleted_inventory_ids = {
            int(item["inventory_id"])
            for item in old_items
            if item.get("inventory_id")
            and item.get("inventory_deleted_at")
            and (str(old["closed_at"] or "") or old_status in {"closed", "cancelled"})
        }
        old_deleted_vehicle_id = (
            int(old["vehicle_id"] or 0) if old["vehicle_id"] else None
        )
        if old_deleted_vehicle_id:
            old_vehicle = conn.execute(
                "SELECT deleted_at FROM vehicles WHERE id = ?",
                (old_deleted_vehicle_id,),
            ).fetchone()
            if (
                not old_vehicle
                or not old_vehicle["deleted_at"]
                or not (old_status == "closed" or str(old["closed_at"] or ""))
            ):
                old_deleted_vehicle_id = None
        data = validate_order(
            conn,
            payload,
            allow_deleted_inventory_ids=old_deleted_inventory_ids,
            allow_deleted_vehicle_id=old_deleted_vehicle_id,
        )
        new_status = data["status"]
        ensure_order_status_transition(old_status, new_status)
        closed_at = compute_closed_at(
            old_status, str(old["closed_at"] or ""), new_status
        )
        if data["status"] == "closed" and not data["follow_up_at"]:
            data["follow_up_at"] = str(old["follow_up_at"] or "") or (
                datetime.now() + timedelta(days=1)
            ).replace(microsecond=0).isoformat(timespec="minutes")
        if old_status == "closed":
            ensure_closed_order_not_changed(old, old_items, data)
        elif str(old["closed_at"] or "") and old_status == "cancelled":
            # Отменённый после закрытия заказ-наряд: финансы заморожены,
            # разрешаем только noop-сохранение в статусе cancelled.
            if new_status != "cancelled":
                raise ValueError(
                    "Отменённый после закрытия заказ-наряд нельзя повторно открыть или изменить. Создайте новый корректирующий заказ."
                )
            # Для проверки noop нормализуем обе стороны: статус уже 'cancelled' → 'cancelled',
            # а ensure_closed_order_not_changed ожидает старую запись в 'closed' и
            # маппит новую 'cancelled' в 'closed'. Нам нужно, чтобы обе стороны сравнивались
            # одинаково, поэтому сравниваем содержимое без поля status напрямую.
            old_payload_signature = closed_order_signature(
                dict(old) | {"status": "cancelled"}, old_items
            )
            new_payload_signature = closed_order_signature(
                {**data, "status": "cancelled"}, data["items"]
            )
            if old_payload_signature != new_payload_signature:
                raise ValueError(
                    "Отменённый после закрытия заказ-наряд нельзя повторно открыть или изменить. Создайте новый корректирующий заказ."
                )
        elif old_status == "cancelled":
            if new_status != "cancelled":
                raise ValueError(
                    "Отменённый заказ-наряд нельзя повторно открыть. Создайте новый заказ."
                )
            if closed_order_signature(old, old_items) != closed_order_signature(
                data, data["items"]
            ):
                raise ValueError(
                    "Отменённый заказ-наряд нельзя изменить. Создайте новый заказ."
                )
        if status_needs_inventory_availability_check(old_status, new_status):
            ensure_inventory_available_for_order(
                conn, data["items"], exclude_order_id=record_id
            )
        apply_inventory_delta(conn, old_status, new_status, old_items, data["items"])
        conn.execute(
            """
            UPDATE orders
            SET customer_id=:customer_id, vehicle_id=:vehicle_id, status=:status, priority=:priority,
                advisor=:advisor, mechanic=:mechanic, promised_at=:promised_at, odometer=:odometer,
                complaint=:complaint, diagnosis=:diagnosis, recommendations=:recommendations,
                discount=:discount, tax_rate=:tax_rate, paid=:paid, payment_method=:payment_method,
                authorized_by=:authorized_by, authorized_at=:authorized_at, follow_up_at=:follow_up_at,
                closed_at=:closed_at, updated_at=:updated_at
            WHERE id=:id AND deleted_at IS NULL
            """,
            {
                **{k: v for k, v in data.items() if k != "items"},
                "closed_at": closed_at,
                "updated_at": now_iso(),
                "id": record_id,
            },
        )
        conn.execute("DELETE FROM order_items WHERE order_id=?", (record_id,))
        preserved_item_stamps = {
            closed_item_signature(item): str(item.get("created_at") or "")
            for item in old_items
            if item.get("created_at")
        }
        insert_order_items(
            conn, record_id, data["items"], preserved_timestamps=preserved_item_stamps
        )
        old_vehicle_id = int(old["vehicle_id"] or 0) or None
        old_odometer = parse_int(old["odometer"])
        if data["status"] != "cancelled":
            sync_vehicle_mileage_from_order(
                conn, data["vehicle_id"], record_id, data["odometer"]
            )
        reconcile_vehicle_mileage_after_order_change(
            conn,
            old_vehicle_id,
            previous_order_id=record_id,
            previous_odometer=old_odometer,
        )
        return _query_get_order(conn, record_id)


def ensure_order_status_transition(old_status: str, new_status: str) -> None:
    if old_status == new_status or old_status == "closed":
        # Closed orders have stricter financial/stock checks in
        # ensure_closed_order_not_changed(), including the user-facing message
        # for forbidden reopen attempts.
        return
    allowed = ORDER_STATUS_TRANSITIONS.get(old_status, set())
    if new_status in allowed:
        return
    if old_status == "cancelled":
        raise ValueError(
            "Отменённый заказ-наряд нельзя повторно открыть. Создайте новый заказ."
        )
    raise ValueError("Некорректный переход статуса заказ-наряда.")


def compute_closed_at(old_status: str, old_closed_at: str, new_status: str) -> str:
    # Ранее закрытый заказ: сохраняем исходную дату закрытия и при отмене,
    # чтобы финансовая история и защита от повторного открытия не терялись.
    if old_closed_at and (old_status == "closed" or new_status == "cancelled"):
        return old_closed_at
    if new_status != "closed":
        return ""
    return now_iso()


def delete_order(record_id: int) -> dict[str, Any]:
    logger.info(f"Deleting order {record_id}")
    with write_db() as conn:
        old = conn.execute(
            "SELECT * FROM orders WHERE id=? AND deleted_at IS NULL", (record_id,)
        ).fetchone()
        if not old:
            raise KeyError("Заказ-наряд не найден.")
        if str(old["status"]) in CONSUMING_STATUSES:
            raise ValueError(
                "Закрытый заказ-наряд сначала переведите в статус «Отменён», "
                "чтобы возврат складских остатков был явным."
            )
        if str(old["closed_at"] or ""):
            raise ValueError(
                "Заказ-наряд с закрытой финансовой историей нельзя удалить. "
                "Оставьте его отменённым или создайте корректирующий заказ."
            )
        old_items = list_order_items(conn, record_id)
        apply_inventory_delta(conn, str(old["status"]), "", old_items, [])
        stamp = now_iso()
        conn.execute(
            "UPDATE orders SET deleted_at=?, updated_at=? WHERE id=? AND deleted_at IS NULL",
            (stamp, stamp, record_id),
        )
        reconcile_vehicle_mileage_after_order_change(
            conn,
            int(old["vehicle_id"] or 0) or None,
            previous_order_id=record_id,
            previous_odometer=parse_int(old["odometer"]),
        )
        return {"deleted": True}


def insert_order_items(
    conn: sqlite3.Connection,
    order_id: int,
    items: list[dict[str, Any]],
    *,
    preserved_timestamps: dict[tuple, str] | None = None,
) -> None:
    stamp = now_iso()
    preserved = preserved_timestamps or {}
    rows = []
    for item in items:
        signature = closed_item_signature(item)
        created_at = preserved.get(signature) or stamp
        rows.append({**item, "order_id": order_id, "created_at": created_at})
    conn.executemany(
        """
        INSERT INTO order_items(order_id, kind, inventory_id, title, approval_status, quantity, unit_price, unit_cost, created_at)
        VALUES (:order_id, :kind, :inventory_id, :title, :approval_status, :quantity, :unit_price, :unit_cost, :created_at)
        """,
        rows,
    )


def list_order_items(conn: sqlite3.Connection, order_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT oi.*, i.sku AS inventory_sku, i.name AS inventory_name, i.deleted_at AS inventory_deleted_at
        FROM order_items oi
        LEFT JOIN inventory i ON i.id = oi.inventory_id
        WHERE oi.order_id=?
        ORDER BY oi.id
        """,
        (order_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def part_quantities(items: list[dict[str, Any]]) -> dict[int, float]:
    result: dict[int, float] = defaultdict(float)
    for item in items:
        if (
            item.get("kind") == "part"
            and item.get("inventory_id")
            and item_is_billable(item)
        ):
            result[int(item["inventory_id"])] += parse_float(item.get("quantity"))
    return dict(result)


def reserved_quantity(
    conn: sqlite3.Connection, inventory_id: int, *, exclude_order_id: int | None = None
) -> float:
    params: list[Any] = [inventory_id]
    exclude_sql = ""
    if exclude_order_id:
        exclude_sql = " AND o.id <> ?"
        params.append(exclude_order_id)
    row = conn.execute(
        f"""
        SELECT COALESCE(SUM(oi.quantity), 0) AS reserved
        FROM order_items oi
        JOIN orders o ON o.id = oi.order_id
        WHERE oi.inventory_id = ?
          AND oi.kind = 'part'
          AND oi.approval_status = 'approved'
          AND o.status IN ('approved', 'in_progress', 'done')
          AND o.deleted_at IS NULL
          {exclude_sql}
        """,
        params,
    ).fetchone()
    return parse_float(row["reserved"] if row else 0)


def ensure_inventory_available_for_order(
    conn: sqlite3.Connection,
    items: list[dict[str, Any]],
    *,
    exclude_order_id: int | None = None,
) -> None:
    requested = part_quantities(items)
    for part_id, quantity in requested.items():
        part = conn.execute(
            "SELECT name, quantity, deleted_at FROM inventory WHERE id = ?",
            (part_id,),
        ).fetchone()
        if not part:
            raise ValueError("Складская позиция для резервирования не найдена.")
        if part["deleted_at"]:
            raise ValueError(f"Складская позиция недоступна: {part['name']}.")
        available = parse_float(part["quantity"]) - reserved_quantity(
            conn, part_id, exclude_order_id=exclude_order_id
        )
        if available + 1e-9 < quantity:
            raise ValueError(
                f"Недостаточно свободного остатка: {part['name']}. Доступно {available:g}, требуется {quantity:g}."
            )


def status_reserves_inventory(status: str) -> bool:
    return status in {"approved", "in_progress", "done"}


def status_needs_inventory_availability_check(old_status: str, new_status: str) -> bool:
    """Return whether new order items must respect free stock reservations.

    Active orders reserve inventory; closed orders consume it immediately. Closing
    an active order must be allowed to consume its own reservation, but neither a
    newly closed order nor an order being closed from a non-reserving status may
    consume stock already reserved by other active orders.
    """
    return status_reserves_inventory(new_status) or (
        new_status in CONSUMING_STATUSES and old_status not in CONSUMING_STATUSES
    )


def closed_signature_number(value: Any) -> float:
    """Канонизирует числа для защиты закрытых заказов от скрытых правок."""
    return round(parse_float(value), 9)


def closed_item_signature(item: dict[str, Any]) -> tuple[Any, ...]:
    """Стабильный финансовый снимок строки закрытого заказ-наряда."""
    return (
        str(item.get("kind") or ""),
        int(item.get("inventory_id") or 0),
        str(item.get("title") or ""),
        str(item.get("approval_status") or "approved"),
        closed_signature_number(item.get("quantity")),
        closed_signature_number(item.get("unit_price")),
        closed_signature_number(item.get("unit_cost")),
    )


def canonical_closed_order(
    order: dict[str, Any] | sqlite3.Row, items: list[dict[str, Any]]
) -> dict[str, Any]:
    canonical = {
        "discount": parse_float(order["discount"]),
        "tax_rate": parse_float(order["tax_rate"]),
        "paid": parse_float(order["paid"]),
        "items": items,
    }
    normalize_order_money(canonical)
    return canonical


def closed_order_signature(
    order: dict[str, Any] | sqlite3.Row, items: list[dict[str, Any]]
) -> tuple[Any, ...]:
    canonical = canonical_closed_order(order, items)
    return (
        str(order["status"]),
        int(order["customer_id"]),
        int(order["vehicle_id"] or 0),
        str(order["priority"] or ""),
        str(order["advisor"] or ""),
        str(order["mechanic"] or ""),
        str(order["promised_at"] or ""),
        int(parse_int(order["odometer"])),
        str(order["complaint"] or ""),
        str(order["diagnosis"] or ""),
        str(order["recommendations"] or ""),
        closed_signature_number(canonical["discount"]),
        closed_signature_number(canonical["tax_rate"]),
        closed_signature_number(canonical["paid"]),
        str(order["payment_method"] or ""),
        str(order["authorized_by"] or ""),
        str(order["authorized_at"] or ""),
        tuple(closed_item_signature(item) for item in items),
    )


def ensure_closed_order_not_changed(
    old: sqlite3.Row, old_items: list[dict[str, Any]], data: dict[str, Any]
) -> None:
    if (
        int(old["customer_id"]) != data["customer_id"]
        or (old["vehicle_id"] or None) != data["vehicle_id"]
    ):
        raise ValueError(
            "Закрытый заказ нельзя перепривязать к другому клиенту или автомобилю."
        )
    if data["status"] not in {"closed", "cancelled"}:
        raise ValueError(
            "Закрытый заказ можно только оставить закрытым или отменить без изменения финансовых данных."
        )
    comparable_data = {k: v for k, v in data.items() if k != "items"}
    if data["status"] == "cancelled":
        comparable_data["status"] = "closed"
    if closed_order_signature(old, old_items) != closed_order_signature(
        comparable_data, data["items"]
    ):
        if data["status"] == "cancelled":
            raise ValueError(
                "При отмене закрытого заказа нельзя менять финансовые данные и позиции."
            )
        raise ValueError(
            "Финансовые данные и позиции закрытого заказа нельзя изменить после закрытия. Создайте отдельный корректирующий заказ."
        )


def apply_inventory_delta(
    conn: sqlite3.Connection,
    old_status: str,
    new_status: str,
    old_items: list[dict[str, Any]],
    new_items: list[dict[str, Any]],
) -> None:
    stock_epsilon = 1e-9
    old_consumed = (
        part_quantities(old_items) if old_status in CONSUMING_STATUSES else {}
    )
    new_consumed = (
        part_quantities(new_items) if new_status in CONSUMING_STATUSES else {}
    )
    all_part_ids = sorted(set(old_consumed) | set(new_consumed))
    for part_id in all_part_ids:
        delta = new_consumed.get(part_id, 0.0) - old_consumed.get(part_id, 0.0)
        if abs(delta) < stock_epsilon:
            continue
        part = conn.execute(
            "SELECT id, name, quantity, deleted_at FROM inventory WHERE id=?",
            (part_id,),
        ).fetchone()
        if not part:
            raise ValueError("Складская позиция для списания не найдена.")
        if part["deleted_at"]:
            if delta > 0:
                raise ValueError(
                    f"Складская позиция недоступна для списания: {part['name']}."
                )
            raise ValueError(
                f"Восстановите позицию склада «{part['name']}» перед возвратом остатков отменённого заказа."
            )
        current_qty = parse_float(part["quantity"])
        if delta > 0 and current_qty + stock_epsilon < delta:
            raise ValueError(
                f"Недостаточно на складе: {part['name']}. Доступно {current_qty:g}, требуется {delta:g}."
            )
        new_quantity = current_qty - delta
        if abs(new_quantity) < stock_epsilon:
            new_quantity = 0.0
        conn.execute(
            "UPDATE inventory SET quantity = ?, updated_at = ? WHERE id = ?",
            (new_quantity, now_iso(), part_id),
        )
