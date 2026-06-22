"""Transactional customer service functions."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from ..database import write_db
from ..runtime import now_iso
from ..validation import (
    active_appointment_count_for_customer,
    active_exists,
    validate_customer,
)

logger = logging.getLogger("sto_crm")


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
        # Check if any active vehicles of the customer have active orders:
        has_vehicle_orders = conn.execute(
            """
            SELECT 1 FROM orders o
            JOIN vehicles v ON v.id = o.vehicle_id
            WHERE v.customer_id = ? AND v.deleted_at IS NULL AND o.deleted_at IS NULL
            LIMIT 1
            """,
            (record_id,),
        ).fetchone()
        if has_vehicle_orders:
            raise ValueError(
                "У клиента есть автомобили с заказ-нарядами. Сначала удалите или перенесите заказы."
            )

        # Check if any active vehicles of the customer have active appointments:
        has_vehicle_appointments = conn.execute(
            """
            SELECT 1 FROM appointments a
            JOIN vehicles v ON v.id = a.vehicle_id
            WHERE v.customer_id = ? AND v.deleted_at IS NULL AND a.deleted_at IS NULL
              AND a.status IN ('scheduled', 'confirmed', 'arrived')
            LIMIT 1
            """,
            (record_id,),
        ).fetchone()
        if has_vehicle_appointments:
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
