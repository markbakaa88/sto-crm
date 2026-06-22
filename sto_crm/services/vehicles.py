"""Transactional vehicle service functions."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from ..database import write_db
from ..runtime import now_iso, parse_int
from ..validation import (
    active_appointment_count_for_vehicle,
    active_exists,
    ensure_unique_active_value,
    validate_vehicle,
)

logger = logging.getLogger("sto_crm")


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
    """Repoint or lower stale order-synced mileage after an order changes."""
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
