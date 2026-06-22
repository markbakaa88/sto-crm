"""Transactional appointment service functions."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from ..config import APPOINTMENT_ACTIVE_STATUSES
from ..database import write_db
from ..runtime import now_iso
from ..validation import (
    active_exists,
    ensure_no_appointment_conflict,
    validate_appointment,
)

logger = logging.getLogger("sto_crm")


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
