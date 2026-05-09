from __future__ import annotations

"""Strict input normalization and business-rule validation."""

import sqlite3
from datetime import datetime, timedelta
from typing import Any

from .config import (
    APPOINTMENT_STATUSES,
    BILLABLE_ITEM_STATUSES,
    EMAIL_RE,
    INSPECTION_CONDITIONS,
    INSPECTION_STATUSES,
    ITEM_APPROVAL_STATUSES,
    ORDER_PRIORITIES,
    ORDER_STATUSES,
    PREFERRED_CHANNELS,
)
from .runtime import (
    clean_multiline,
    clean_text,
    parse_date_iso,
    parse_datetime_local,
    parse_float,
    parse_float_field,
    parse_int,
    parse_int_field,
    validate_vehicle_year,
    validate_vin,
)

def generate_order_number(conn: sqlite3.Connection) -> str:
    """Генерирует уникальный номер заказ-наряда."""
    prefix = datetime.now().strftime("СТО-%Y%m%d")
    rows = conn.execute(
        "SELECT number FROM orders WHERE number LIKE ?",
        (f"{prefix}-%",),
    ).fetchall()
    max_suffix = 0
    for row in rows:
        try:
            max_suffix = max(max_suffix, int(str(row["number"]).rsplit("-", 1)[1]))
        except (IndexError, ValueError):
            continue
    return f"{prefix}-{max_suffix + 1:03d}"


def validate_customer(payload: dict[str, Any]) -> dict[str, Any]:
    name = clean_text(payload.get("name"), 180)
    if not name:
        raise ValueError("Укажите имя клиента.")
    preferred_channel = clean_text(payload.get("preferred_channel"), 30, "phone")
    if preferred_channel not in PREFERRED_CHANNELS:
        raise ValueError("Некорректный канал связи клиента.")
    phone = clean_text(payload.get("phone"), 80)
    email = clean_text(payload.get("email"), 180).lower()
    if email and not EMAIL_RE.fullmatch(email):
        raise ValueError("Некорректный email клиента.")
    return {
        "name": name,
        "phone": phone,
        "email": email,
        "source": clean_text(payload.get("source"), 120),
        "preferred_channel": preferred_channel,
        "reminder_consent": 1 if parse_int_field(payload.get("reminder_consent"), "согласие на напоминания", 1) else 0,
        "notes": clean_multiline(payload.get("notes"), 2000),
    }


def validate_vehicle(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    customer_id = parse_int_field(payload.get("customer_id"), "клиент")
    if not customer_id or not active_exists(conn, "customers", customer_id):
        raise ValueError("Выберите действующего клиента.")
    make = clean_text(payload.get("make"), 120)
    model = clean_text(payload.get("model"), 120)
    plate = clean_text(payload.get("plate"), 40).upper()
    vin = validate_vin(payload.get("vin"))
    if not (make or model or plate or vin):
        raise ValueError("Укажите автомобиль: марку, модель, номер или VIN.")
    return {
        "customer_id": customer_id,
        "make": make,
        "model": model,
        "year": validate_vehicle_year(payload.get("year")),
        "plate": plate,
        "vin": vin,
        "mileage": max(parse_int_field(payload.get("mileage"), "пробег"), 0),
        "next_service_at": parse_date_iso(payload.get("next_service_at"), "дата следующего сервиса"),
        "next_service_mileage": max(parse_int_field(payload.get("next_service_mileage"), "сервисный пробег"), 0),
        "notes": clean_multiline(payload.get("notes"), 2000),
    }


def validate_inventory(payload: dict[str, Any]) -> dict[str, Any]:
    name = clean_text(payload.get("name"), 220)
    if not name:
        raise ValueError("Укажите название позиции склада.")
    return {
        "sku": clean_text(payload.get("sku"), 100).upper(),
        "name": name,
        "brand": clean_text(payload.get("brand"), 140),
        "unit": clean_text(payload.get("unit"), 30, "шт") or "шт",
        "quantity": max(parse_float_field(payload.get("quantity"), "остаток"), 0),
        "min_quantity": max(parse_float_field(payload.get("min_quantity"), "минимальный остаток"), 0),
        "price": max(parse_float_field(payload.get("price"), "цена"), 0),
        "cost": max(parse_float_field(payload.get("cost"), "себестоимость"), 0),
        "supplier": clean_text(payload.get("supplier"), 180),
        "notes": clean_multiline(payload.get("notes"), 2000),
    }


def validate_order(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    customer_id = parse_int_field(payload.get("customer_id"), "клиент")
    if not customer_id or not active_exists(conn, "customers", customer_id):
        raise ValueError("Выберите действующего клиента.")

    vehicle_id_raw = parse_int_field(payload.get("vehicle_id"), "автомобиль") or None
    vehicle_id = ensure_vehicle_belongs_to_customer(conn, vehicle_id_raw, customer_id)

    status = clean_text(payload.get("status"), 40, "new")
    if status not in ORDER_STATUSES:
        raise ValueError("Некорректный статус заказа.")

    priority = clean_text(payload.get("priority"), 20, "normal")
    if priority not in ORDER_PRIORITIES:
        raise ValueError("Некорректный приоритет заказа.")

    raw_items = payload.get("items") or []
    if not isinstance(raw_items, list):
        raise ValueError("Позиции заказ-наряда должны быть списком.")
    items = [validate_order_item(conn, item) for item in raw_items]
    items = [item for item in items if item["title"]]
    if not items:
        raise ValueError("Добавьте хотя бы одну работу или запчасть.")

    data = {
        "customer_id": customer_id,
        "vehicle_id": vehicle_id,
        "status": status,
        "priority": priority,
        "advisor": clean_text(payload.get("advisor"), 120),
        "mechanic": clean_text(payload.get("mechanic"), 120),
        "promised_at": parse_datetime_local(payload.get("promised_at"), "срок заказа"),
        "odometer": max(parse_int_field(payload.get("odometer"), "пробег в заказе"), 0),
        "complaint": clean_multiline(payload.get("complaint"), 3000),
        "diagnosis": clean_multiline(payload.get("diagnosis"), 3000),
        "recommendations": clean_multiline(payload.get("recommendations"), 3000),
        "discount": max(parse_float_field(payload.get("discount"), "скидка"), 0),
        "tax_rate": min(max(parse_float_field(payload.get("tax_rate"), "налог"), 0), 100),
        "paid": max(parse_float_field(payload.get("paid"), "оплачено"), 0),
        "payment_method": clean_text(payload.get("payment_method"), 80),
        "authorized_by": clean_text(payload.get("authorized_by"), 120),
        "authorized_at": parse_datetime_local(payload.get("authorized_at"), "дата согласования"),
        "follow_up_at": parse_datetime_local(payload.get("follow_up_at"), "follow-up"),
        "items": items,
    }
    normalize_order_money(data)
    return data


def validate_appointment(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    customer_id = parse_int_field(payload.get("customer_id"), "клиент")
    if not customer_id or not active_exists(conn, "customers", customer_id):
        raise ValueError("Выберите действующего клиента.")

    vehicle_id_raw = parse_int_field(payload.get("vehicle_id"), "автомобиль") or None
    vehicle_id = ensure_vehicle_belongs_to_customer(conn, vehicle_id_raw, customer_id)

    scheduled_at = parse_datetime_local(payload.get("scheduled_at"), "дата и время записи", required=True)

    duration_minutes = parse_int_field(payload.get("duration_minutes"), "длительность записи", 60)
    duration_minutes = min(max(duration_minutes, 15), 480)
    status = clean_text(payload.get("status"), 30, "scheduled")
    if status not in APPOINTMENT_STATUSES:
        raise ValueError("Некорректный статус записи.")

    return {
        "customer_id": customer_id,
        "vehicle_id": vehicle_id,
        "scheduled_at": scheduled_at,
        "duration_minutes": duration_minutes,
        "status": status,
        "advisor": clean_text(payload.get("advisor"), 120),
        "reason": clean_text(payload.get("reason"), 220),
        "notes": clean_multiline(payload.get("notes"), 2000),
    }


def validate_inspection(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    customer_id = parse_int_field(payload.get("customer_id"), "клиент")
    if not customer_id or not active_exists(conn, "customers", customer_id):
        raise ValueError("Выберите действующего клиента.")

    vehicle_id_raw = parse_int_field(payload.get("vehicle_id"), "автомобиль") or None
    vehicle_id = ensure_vehicle_belongs_to_customer(conn, vehicle_id_raw, customer_id)

    order_id = parse_int_field(payload.get("order_id"), "заказ-наряд") or None
    if order_id:
        order = conn.execute(
            """
            SELECT customer_id, vehicle_id
            FROM orders
            WHERE id = ? AND deleted_at IS NULL
            """,
            (order_id,),
        ).fetchone()
        if not order:
            raise ValueError("Выберите действующий заказ-наряд.")
        if int(order["customer_id"]) != customer_id:
            raise ValueError("Выбранный заказ-наряд принадлежит другому клиенту.")
        if vehicle_id and order["vehicle_id"] and int(order["vehicle_id"]) != vehicle_id:
            raise ValueError("Заказ-наряд привязан к другому автомобилю.")
        if not vehicle_id and order["vehicle_id"]:
            vehicle_id = ensure_vehicle_belongs_to_customer(conn, int(order["vehicle_id"]), customer_id, required=True)

    status = clean_text(payload.get("status"), 30, "draft")
    if status not in INSPECTION_STATUSES:
        raise ValueError("Некорректный статус осмотра.")

    inspected_at = parse_datetime_local(payload.get("inspected_at"), "дата осмотра")
    if not inspected_at:
        inspected_at = datetime.now().replace(microsecond=0).isoformat(timespec="minutes")

    raw_items = payload.get("items") or []
    if not isinstance(raw_items, list):
        raise ValueError("Пункты осмотра должны быть списком.")
    items = [validate_inspection_item(item) for item in raw_items]
    items = [item for item in items if item["title"]]
    if not items:
        raise ValueError("Добавьте хотя бы один пункт осмотра.")

    return {
        "customer_id": customer_id,
        "vehicle_id": vehicle_id,
        "order_id": order_id,
        "status": status,
        "inspector": clean_text(payload.get("inspector"), 120),
        "inspected_at": inspected_at,
        "summary": clean_multiline(payload.get("summary"), 2500),
        "items": items,
    }


def validate_inspection_item(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Пункт осмотра должен быть JSON-объектом.")
    condition_status = clean_text(payload.get("condition_status"), 30, "ok")
    if condition_status not in INSPECTION_CONDITIONS:
        raise ValueError("Некорректное состояние пункта осмотра.")
    default_approval = "approved" if condition_status == "ok" else "deferred"
    approval_status = clean_text(payload.get("approval_status"), 30, default_approval)
    if approval_status not in ITEM_APPROVAL_STATUSES:
        raise ValueError("Некорректный статус согласования пункта осмотра.")
    return {
        "area": clean_text(payload.get("area"), 120),
        "title": clean_text(payload.get("title"), 220),
        "condition_status": condition_status,
        "approval_status": approval_status,
        "recommendation": clean_multiline(payload.get("recommendation"), 2000),
        "estimate": max(parse_float_field(payload.get("estimate"), "оценка пункта осмотра"), 0),
    }


def normalize_order_money(order_data: dict[str, Any]) -> None:
    items = order_data.get("items", [])
    subtotal = sum(
        parse_float(item.get("quantity")) * parse_float(item.get("unit_price"))
        for item in items
        if item_is_billable(item)
    )
    order_data["discount"] = min(parse_float(order_data.get("discount")), subtotal)
    tax_rate = min(parse_float(order_data.get("tax_rate")), 100)
    order_data["tax_rate"] = tax_rate
    total = max(subtotal - order_data["discount"], 0) * (1 + tax_rate / 100)
    order_data["paid"] = min(parse_float(order_data.get("paid")), total)


def validate_order_item(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Позиция заказ-наряда должна быть JSON-объектом.")
    kind = clean_text(payload.get("kind"), 20, "service")
    if kind not in {"service", "part"}:
        raise ValueError("Некорректный тип позиции заказ-наряда.")
    inventory_id = parse_int_field(payload.get("inventory_id"), "складская позиция") if kind == "part" else None
    if inventory_id is not None and inventory_id <= 0:
        inventory_id = None
    title = clean_text(payload.get("title"), 220)
    unit_price = max(parse_float_field(payload.get("unit_price"), "цена позиции"), 0) if "unit_price" in payload else 0
    unit_cost = max(parse_float_field(payload.get("unit_cost"), "себестоимость позиции"), 0) if "unit_cost" in payload else 0
    approval_status = clean_text(payload.get("approval_status"), 30, "approved")
    if approval_status not in ITEM_APPROVAL_STATUSES:
        raise ValueError("Некорректный статус согласования позиции заказ-наряда.")

    if kind == "part" and inventory_id:
        part = conn.execute(
            "SELECT id, name, price, cost FROM inventory WHERE id = ? AND deleted_at IS NULL",
            (inventory_id,),
        ).fetchone()
        if not part:
            raise ValueError("Выбранная складская позиция не найдена.")
        if not title:
            title = str(part["name"])
        if unit_price == 0:
            unit_price = parse_float(part["price"])
        if unit_cost == 0:
            unit_cost = parse_float(part["cost"])
    elif kind == "service":
        inventory_id = None

    if not title:
        raise ValueError("Укажите наименование запчасти или работы.")

    quantity = max(parse_float_field(payload.get("quantity"), "количество позиции", 1), 0)
    if quantity <= 0:
        raise ValueError("Количество в позиции должно быть больше нуля.")

    return {
        "kind": kind,
        "inventory_id": inventory_id,
        "title": title,
        "approval_status": approval_status,
        "quantity": quantity,
        "unit_price": unit_price,
        "unit_cost": unit_cost,
    }


def item_is_billable(item: dict[str, Any]) -> bool:
    return str(item.get("approval_status") or "approved") in BILLABLE_ITEM_STATUSES


def active_exists(conn: sqlite3.Connection, table: str, record_id: int) -> bool:
    if table not in {"customers", "vehicles", "inventory", "orders", "appointments", "inspections"}:
        return False
    row = conn.execute(f"SELECT 1 FROM {table} WHERE id = ? AND deleted_at IS NULL", (record_id,)).fetchone()
    return row is not None


def ensure_unique_active_value(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    value: str,
    message: str,
    record_id: int | None = None,
) -> None:
    if not value:
        return
    allowed_columns = {
        ("inventory", "sku"),
        ("vehicles", "vin"),
        ("vehicles", "plate"),
    }
    if (table, column) not in allowed_columns:
        raise ValueError("Некорректная проверка уникальности.")
    query = f"SELECT id FROM {table} WHERE CASEFOLD({column}) = CASEFOLD(?) AND deleted_at IS NULL"
    params: list[Any] = [value]
    if record_id:
        query += " AND id <> ?"
        params.append(record_id)
    if conn.execute(query, params).fetchone():
        raise ValueError(message)


def ensure_vehicle_belongs_to_customer(
    conn: sqlite3.Connection,
    vehicle_id: int | None,
    customer_id: int,
    *,
    required: bool = False,
) -> int | None:
    if not vehicle_id:
        if required:
            raise ValueError("Выберите действующий автомобиль.")
        return None
    vehicle_owner = conn.execute(
        "SELECT customer_id FROM vehicles WHERE id = ? AND deleted_at IS NULL",
        (vehicle_id,),
    ).fetchone()
    if not vehicle_owner:
        raise ValueError("Выберите действующий автомобиль.")
    if int(vehicle_owner["customer_id"]) != customer_id:
        raise ValueError("Выбранный автомобиль принадлежит другому клиенту.")
    return vehicle_id


def ensure_no_appointment_conflict(
    conn: sqlite3.Connection,
    scheduled_at: str,
    duration_minutes: int,
    *,
    record_id: int | None = None,
) -> None:
    start = datetime.fromisoformat(scheduled_at)
    end = start + timedelta(minutes=duration_minutes)
    if end <= start:
        raise ValueError("Длительность записи должна быть больше нуля.")
    window_start = (start - timedelta(days=1)).isoformat(timespec="minutes")
    window_end = end.isoformat(timespec="minutes")

    rows = conn.execute(
        """
        SELECT a.id, a.scheduled_at, a.duration_minutes, c.name AS customer_name
        FROM appointments a
        JOIN customers c ON c.id = a.customer_id
        WHERE a.deleted_at IS NULL
          AND a.status IN ('scheduled', 'confirmed', 'arrived')
          AND a.scheduled_at >= ?
          AND a.scheduled_at < ?
          AND (? IS NULL OR a.id <> ?)
        """,
        (window_start, window_end, record_id, record_id),
    ).fetchall()
    for row in rows:
        try:
            existing_start = datetime.fromisoformat(str(row["scheduled_at"]))
        except ValueError:
            continue
        existing_end = existing_start + timedelta(minutes=max(parse_int(row["duration_minutes"], 60), 15))
        if start < existing_end and end > existing_start:
            when = existing_start.strftime("%d.%m.%Y %H:%M")
            raise ValueError(f"На это время уже есть запись: {row['customer_name']} в {when}.")


def active_appointment_count_for_customer(conn: sqlite3.Connection, customer_id: int) -> int:
    return int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM appointments
            WHERE customer_id = ?
              AND deleted_at IS NULL
              AND status IN ('scheduled', 'confirmed', 'arrived')
            """,
            (customer_id,),
        ).fetchone()[0]
    )


def active_appointment_count_for_vehicle(conn: sqlite3.Connection, vehicle_id: int) -> int:
    return int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM appointments
            WHERE vehicle_id = ?
              AND deleted_at IS NULL
              AND status IN ('scheduled', 'confirmed', 'arrived')
            """,
            (vehicle_id,),
        ).fetchone()[0]
    )
