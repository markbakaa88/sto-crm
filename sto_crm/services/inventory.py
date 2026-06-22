"""Transactional inventory service functions."""

from __future__ import annotations

import logging
import sqlite3
from collections import defaultdict
from typing import Any

from ..config import CONSUMING_STATUSES
from ..database import write_db
from ..runtime import now_iso, parse_float
from ..validation import (
    active_exists,
    ensure_unique_active_value,
    item_is_billable,
    validate_inventory,
)

logger = logging.getLogger("sto_crm")


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
    if not requested:
        return

    part_ids = list(requested.keys())
    placeholders = ",".join("?" for _ in part_ids)

    parts = conn.execute(
        f"SELECT id, name, quantity, deleted_at FROM inventory WHERE id IN ({placeholders})",
        part_ids,
    ).fetchall()
    parts_map = {row["id"]: row for row in parts}

    params = part_ids.copy()
    exclude_sql = ""
    if exclude_order_id:
        exclude_sql = " AND o.id <> ?"
        params.append(exclude_order_id)

    reserved_rows = conn.execute(
        f"""
        SELECT oi.inventory_id, COALESCE(SUM(oi.quantity), 0) AS reserved
        FROM order_items oi
        JOIN orders o ON o.id = oi.order_id
        WHERE oi.inventory_id IN ({placeholders})
          AND oi.kind = 'part'
          AND oi.approval_status = 'approved'
          AND o.status IN ('approved', 'in_progress', 'done')
          AND o.deleted_at IS NULL
          {exclude_sql}
        GROUP BY oi.inventory_id
        """,
        params,
    ).fetchall()
    reserved_map = {
        row["inventory_id"]: parse_float(row["reserved"]) for row in reserved_rows
    }

    for part_id, quantity in requested.items():
        if part_id not in parts_map:
            raise ValueError("Складская позиция для резервирования не найдена.")
        part = parts_map[part_id]
        if part["deleted_at"]:
            raise ValueError(f"Складская позиция недоступна: {part['name']}.")
        available = parse_float(part["quantity"]) - reserved_map.get(part_id, 0.0)
        if available + 1e-9 < quantity:
            raise ValueError(
                f"Недостаточно свободного остатка: {part['name']}. Доступно {available:g}, требуется {quantity:g}."
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

    # Calculate deltas and filter for non-zero changes
    delta_parts = {}
    for part_id in all_part_ids:
        delta = new_consumed.get(part_id, 0.0) - old_consumed.get(part_id, 0.0)
        if abs(delta) >= stock_epsilon:
            delta_parts[part_id] = delta

    if not delta_parts:
        return

    part_ids = list(delta_parts.keys())
    placeholders = ",".join("?" for _ in part_ids)
    parts = conn.execute(
        f"SELECT id, name, quantity, deleted_at FROM inventory WHERE id IN ({placeholders})",
        part_ids,
    ).fetchall()
    parts_map = {row["id"]: row for row in parts}

    for part_id, delta in delta_parts.items():
        if part_id not in parts_map:
            raise ValueError("Складская позиция для списания не найдена.")
        part = parts_map[part_id]
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
