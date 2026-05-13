"""Read/query helpers and aggregate total calculations."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from typing import Any

from .config import APPOINTMENT_STATUSES, ORDER_STATUSES
from .database import db
from .runtime import parse_float, search_needle, sql_limit
from .services import list_order_items
from .validation import item_is_billable

_ORDER_VEHICLE_FIELDS = (
    "vehicle_make",
    "vehicle_model",
    "vehicle_year",
    "vehicle_plate",
    "vehicle_vin",
    "vehicle_mileage",
)


def _mask_deleted_order_vehicle(order: dict[str, Any]) -> dict[str, Any]:
    """Keep historical orders visible while hiding soft-deleted vehicle data."""
    if order.pop("vehicle_deleted_at", None):
        for key in _ORDER_VEHICLE_FIELDS:
            if key in order:
                order[key] = None
        order["vehicle_deleted"] = 1
    else:
        order["vehicle_deleted"] = 0
    return order


def list_customers(q: str = "", limit: int | None = 1000) -> list[dict[str, Any]]:
    with db() as conn:
        params: list[Any] = []
        where = "WHERE c.deleted_at IS NULL"
        if q:
            where += " AND (CASEFOLD(c.name) LIKE ? ESCAPE '\\' OR CASEFOLD(c.phone) LIKE ? ESCAPE '\\' OR CASEFOLD(c.email) LIKE ? ESCAPE '\\')"
            needle = search_needle(q)
            params.extend([needle, needle, needle])
        limit_sql, limit_params = sql_limit(limit)
        params.extend(limit_params)
        rows = conn.execute(
            f"""
            SELECT c.*,
                   COUNT(DISTINCT v.id) AS vehicles_count,
                   COUNT(DISTINCT o.id) AS orders_count,
                   MAX(o.updated_at) AS last_order_at
            FROM customers c
            LEFT JOIN vehicles v ON v.customer_id = c.id AND v.deleted_at IS NULL
            LEFT JOIN orders o ON o.customer_id = c.id AND o.deleted_at IS NULL
            {where}
            GROUP BY c.id
            ORDER BY c.updated_at DESC, c.id DESC
            {limit_sql}
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]


def list_vehicles(q: str = "", limit: int | None = 1000) -> list[dict[str, Any]]:
    with db() as conn:
        params: list[Any] = []
        where = "WHERE v.deleted_at IS NULL AND c.deleted_at IS NULL"
        if q:
            where += """
                AND (CASEFOLD(v.make) LIKE ? ESCAPE '\\' OR CASEFOLD(v.model) LIKE ? ESCAPE '\\' OR CASEFOLD(v.plate) LIKE ? ESCAPE '\\'
                     OR CASEFOLD(v.vin) LIKE ? ESCAPE '\\' OR CASEFOLD(c.name) LIKE ? ESCAPE '\\')
            """
            needle = search_needle(q)
            params.extend([needle, needle, needle, needle, needle])
        limit_sql, limit_params = sql_limit(limit)
        params.extend(limit_params)
        rows = conn.execute(
            f"""
            SELECT v.*, c.name AS customer_name, c.phone AS customer_phone,
                   c.preferred_channel AS customer_preferred_channel,
                   c.reminder_consent AS customer_reminder_consent
            FROM vehicles v
            JOIN customers c ON c.id = v.customer_id
            {where}
            ORDER BY v.updated_at DESC, v.id DESC
            {limit_sql}
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]


def list_inventory(q: str = "", limit: int | None = 1000) -> list[dict[str, Any]]:
    with db() as conn:
        params: list[Any] = []
        where = "WHERE deleted_at IS NULL"
        if q:
            where += " AND (CASEFOLD(sku) LIKE ? ESCAPE '\\' OR CASEFOLD(name) LIKE ? ESCAPE '\\' OR CASEFOLD(brand) LIKE ? ESCAPE '\\' OR CASEFOLD(supplier) LIKE ? ESCAPE '\\')"
            needle = search_needle(q)
            params.extend([needle, needle, needle, needle])
        limit_sql, limit_params = sql_limit(limit)
        params.extend(limit_params)
        rows = conn.execute(
            f"""
            SELECT *,
                   CASE WHEN min_quantity > 0 AND quantity <= min_quantity THEN 1 ELSE 0 END AS is_low
            FROM inventory
            {where}
            ORDER BY is_low DESC, updated_at DESC, id DESC
            {limit_sql}
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]


def list_appointments(q: str = "", status: str = "all", limit: int | None = 1000) -> list[dict[str, Any]]:
    if status not in {"all", *APPOINTMENT_STATUSES}:
        raise ValueError("Некорректный статус записи.")
    with db() as conn:
        params: list[Any] = []
        where = "WHERE a.deleted_at IS NULL AND c.deleted_at IS NULL AND (a.vehicle_id IS NULL OR v.deleted_at IS NULL)"
        if status and status != "all":
            where += " AND a.status = ?"
            params.append(status)
        if q:
            where += """
                AND (CASEFOLD(c.name) LIKE ? ESCAPE '\\' OR CASEFOLD(c.phone) LIKE ? ESCAPE '\\' OR CASEFOLD(c.email) LIKE ? ESCAPE '\\'
                     OR CASEFOLD(v.plate) LIKE ? ESCAPE '\\' OR CASEFOLD(v.vin) LIKE ? ESCAPE '\\' OR CASEFOLD(v.make) LIKE ? ESCAPE '\\'
                     OR CASEFOLD(v.model) LIKE ? ESCAPE '\\' OR CASEFOLD(a.reason) LIKE ? ESCAPE '\\' OR CASEFOLD(a.advisor) LIKE ? ESCAPE '\\')
            """
            needle = search_needle(q)
            params.extend([needle, needle, needle, needle, needle, needle, needle, needle, needle])
        limit_sql, limit_params = sql_limit(limit)
        params.extend(limit_params)
        rows = conn.execute(
            f"""
            SELECT a.*, c.name AS customer_name, c.phone AS customer_phone,
                   v.make AS vehicle_make, v.model AS vehicle_model, v.year AS vehicle_year,
                   v.plate AS vehicle_plate, v.vin AS vehicle_vin
            FROM appointments a
            JOIN customers c ON c.id = a.customer_id
            LEFT JOIN vehicles v ON v.id = a.vehicle_id
            {where}
            ORDER BY
                CASE WHEN a.status IN ('done', 'no_show', 'cancelled') THEN 1 ELSE 0 END,
                a.scheduled_at,
                a.id
            {limit_sql}
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]


def list_orders(q: str = "", status: str = "", limit: int | None = 1000) -> list[dict[str, Any]]:
    if status and status != "all" and status not in ORDER_STATUSES:
        raise ValueError("Некорректный статус заказа.")
    with db() as conn:
        params: list[Any] = []
        where = "WHERE o.deleted_at IS NULL AND c.deleted_at IS NULL"
        if status and status != "all":
            where += " AND o.status = ?"
            params.append(status)
        if q:
            where += """
                AND (CASEFOLD(o.number) LIKE ? ESCAPE '\\' OR CASEFOLD(c.name) LIKE ? ESCAPE '\\' OR CASEFOLD(c.phone) LIKE ? ESCAPE '\\'
                     OR CASEFOLD(c.email) LIKE ? ESCAPE '\\' OR CASEFOLD(v.plate) LIKE ? ESCAPE '\\' OR CASEFOLD(v.vin) LIKE ? ESCAPE '\\'
                     OR CASEFOLD(v.make) LIKE ? ESCAPE '\\' OR CASEFOLD(v.model) LIKE ? ESCAPE '\\' OR CASEFOLD(o.complaint) LIKE ? ESCAPE '\\')
            """
            needle = search_needle(q)
            params.extend([needle, needle, needle, needle, needle, needle, needle, needle, needle])
        limit_sql, limit_params = sql_limit(limit)
        params.extend(limit_params)
        rows = conn.execute(
            f"""
            SELECT o.*, c.name AS customer_name, c.phone AS customer_phone,
                   v.make AS vehicle_make, v.model AS vehicle_model, v.year AS vehicle_year,
                   v.plate AS vehicle_plate, v.vin AS vehicle_vin, v.mileage AS vehicle_mileage,
                   v.deleted_at AS vehicle_deleted_at
            FROM orders o
            JOIN customers c ON c.id = o.customer_id
            LEFT JOIN vehicles v ON v.id = o.vehicle_id
            {where}
            ORDER BY
                CASE
                    WHEN o.status IN ('closed', 'cancelled') THEN 1
                    ELSE 0
                END,
                CASE o.priority
                    WHEN 'urgent' THEN 0
                    WHEN 'high' THEN 1
                    WHEN 'normal' THEN 2
                    WHEN 'low' THEN 3
                    ELSE 4
                END,
                CASE o.status
                    WHEN 'new' THEN 1
                    WHEN 'diagnostics' THEN 2
                    WHEN 'estimate' THEN 3
                    WHEN 'approved' THEN 4
                    WHEN 'in_progress' THEN 5
                    WHEN 'done' THEN 6
                    WHEN 'closed' THEN 7
                    ELSE 8
                END,
                o.updated_at DESC,
                o.id DESC
            {limit_sql}
            """,
            params,
        ).fetchall()
        orders = [_mask_deleted_order_vehicle(dict(row)) for row in rows]
        attach_items_and_totals(conn, orders)
        return orders


def get_order(conn: sqlite3.Connection, record_id: int) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT o.*, c.name AS customer_name, c.phone AS customer_phone, c.email AS customer_email,
               v.make AS vehicle_make, v.model AS vehicle_model, v.year AS vehicle_year,
               v.plate AS vehicle_plate, v.vin AS vehicle_vin, v.mileage AS vehicle_mileage,
               v.deleted_at AS vehicle_deleted_at
        FROM orders o
        JOIN customers c ON c.id = o.customer_id
        LEFT JOIN vehicles v ON v.id = o.vehicle_id
        WHERE o.id = ?
          AND o.deleted_at IS NULL
          AND c.deleted_at IS NULL
        """,
        (record_id,),
    ).fetchone()
    if not row:
        raise KeyError("Заказ-наряд не найден.")
    order = dict(row)
    # Если автомобиль был soft-deleted, НЕ скрываем сам заказ (иначе редактирование/закрытие
    # закрытого заказа становится невозможным), но очищаем поля авто, чтобы фронт получил
    # консистентные NULL вместо данных удаленного автомобиля.
    _mask_deleted_order_vehicle(order)
    order["items"] = list_order_items(conn, record_id)
    order.update(calculate_totals(order, order["items"]))
    return order


def attach_items_and_totals(conn: sqlite3.Connection, orders: list[dict[str, Any]]) -> None:
    if not orders:
        return
    order_ids = [int(order["id"]) for order in orders]
    placeholders = ",".join("?" for _ in order_ids)
    rows = conn.execute(
        f"""
        SELECT oi.*, i.sku AS inventory_sku, i.name AS inventory_name, i.deleted_at AS inventory_deleted_at
        FROM order_items oi
        LEFT JOIN inventory i ON i.id = oi.inventory_id
        WHERE oi.order_id IN ({placeholders})
        ORDER BY oi.id
        """,
        order_ids,
    ).fetchall()
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[int(row["order_id"])].append(dict(row))
    for order in orders:
        items = grouped.get(int(order["id"]), [])
        order["items"] = items
        order.update(calculate_totals(order, items))


def calculate_totals(order: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, float]:
    billable_items = [item for item in items if item_is_billable(item)]
    service_total = sum(parse_float(i.get("quantity")) * parse_float(i.get("unit_price")) for i in billable_items if i.get("kind") == "service")
    parts_total = sum(parse_float(i.get("quantity")) * parse_float(i.get("unit_price")) for i in billable_items if i.get("kind") == "part")
    cost_total = sum(parse_float(i.get("quantity")) * parse_float(i.get("unit_cost")) for i in billable_items)
    subtotal = service_total + parts_total
    discount = min(max(parse_float(order.get("discount")), 0), subtotal)
    taxable = max(subtotal - discount, 0)
    tax_rate = min(max(parse_float(order.get("tax_rate")), 0), 100)
    tax = taxable * tax_rate / 100
    total = taxable + tax
    paid = min(max(parse_float(order.get("paid")), 0), total)
    due = max(total - paid, 0)
    gross_margin = taxable - cost_total
    margin_percent = (gross_margin / taxable * 100) if taxable else 0
    return {
        "service_total": round(service_total, 2),
        "parts_total": round(parts_total, 2),
        "cost_total": round(cost_total, 2),
        "subtotal": round(subtotal, 2),
        "tax": round(tax, 2),
        "total": round(total, 2),
        "paid": round(paid, 2),
        "due": round(due, 2),
        "margin": round(gross_margin, 2),
        "margin_percent": round(margin_percent, 1),
    }
