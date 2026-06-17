"""Strict input normalization and business-rule validation."""

from __future__ import annotations

import math
import re
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from .config import (
    APPOINTMENT_STATUSES,
    BILLABLE_ITEM_STATUSES,
    EMAIL_RE,
    ITEM_APPROVAL_STATUSES,
    MAX_FINANCIAL_TOTAL,
    MIN_QUANTITY_STEP,
    ORDER_PRIORITIES,
    ORDER_STATUSES,
    PREFERRED_CHANNELS,
)
from .runtime import (
    clean_multiline,
    clean_text,
    is_blank,
    parse_date_iso,
    parse_datetime_local,
    parse_float,
    parse_float_field,
    parse_int,
    parse_int_field,
    validate_vehicle_year,
    validate_vin,
)


def require_non_negative_float(
    value: Any, field_name: str, default: float = 0.0
) -> float:
    parsed = parse_float_field(value, field_name, default)
    if parsed < 0:
        raise ValueError(f"{field_name} не может быть отрицательным.")
    return parsed


def require_non_negative_int(value: Any, field_name: str, default: int = 0) -> int:
    parsed = parse_int_field(value, field_name, default)
    if parsed < 0:
        raise ValueError(f"{field_name} не может быть отрицательным.")
    return parsed


def ensure_finite_money(value: float, field_name: str) -> float:
    if not math.isfinite(value) or abs(value) > MAX_FINANCIAL_TOTAL:
        raise ValueError(f"Некорректное финансовое значение: {field_name}.")
    return value


def require_mileage_limit(value: int, field_name: str) -> int:
    if value > 10_000_000:
        raise ValueError(
            f"Недопустимое значение: {field_name} не может превышать 10 000 000."
        )
    return value


def validate_tax_rate(value: float) -> float:
    return min(max(value, 0.0), 100.0)


def optional_non_negative_float(
    value: Any, field_name: str, default: float = 0.0
) -> float:
    return (
        default
        if is_blank(value)
        else require_non_negative_float(value, field_name, default)
    )


def generate_order_number(conn: sqlite3.Connection) -> str:
    """Генерирует уникальный номер заказ-наряда.

    Намеренно игнорируем legacy-номера с суффиксом вне диапазона 3-6 цифр,
    чтобы случайный импорт/ручная правка с аномальным суффиксом не ломали
    ежедневный инкремент. При редкой коллизии с таким legacy-номером счетчик
    продвигается дальше до первого свободного номера.
    """
    prefix = datetime.now().strftime("СТО-%Y%m%d")
    pattern = re.compile(rf"^{re.escape(prefix)}-(\d{{3,6}})$")
    rows = conn.execute(
        "SELECT number FROM orders WHERE number LIKE ?",
        (f"{prefix}-%",),
    ).fetchall()
    max_suffix = 0
    for row in rows:
        match = pattern.fullmatch(str(row["number"] or ""))
        if not match:
            continue
        try:
            suffix = int(match.group(1))
        except (TypeError, ValueError):
            continue
        max_suffix = max(max_suffix, suffix)
    existing_numbers = {str(row["number"] or "") for row in rows}
    next_suffix = max_suffix + 1
    while True:
        number = f"{prefix}-{next_suffix:03d}"
        if number not in existing_numbers:
            return number
        next_suffix += 1


def parse_bool_field(value: Any, field_name: str, default: bool = False) -> int:
    """Strictly normalize UI/API booleans stored as SQLite 0/1 integers."""
    if is_blank(value):
        return 1 if default else 0
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, int) and not isinstance(value, bool):
        if value in {0, 1}:
            return value
        raise ValueError(f"Некорректное значение: {field_name}.")
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"1", "true", "yes", "on", "да"}:
            return 1
        if normalized in {"0", "false", "no", "off", "нет"}:
            return 0
    raise ValueError(f"Некорректное значение: {field_name}.")


def validate_customer(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Некорректный формат данных.")
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
        "reminder_consent": parse_bool_field(
            payload.get("reminder_consent"), "согласие на напоминания", True
        ),
        "notes": clean_multiline(payload.get("notes"), 2000),
    }


def validate_vehicle(
    conn: sqlite3.Connection, payload: dict[str, Any]
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Некорректный формат данных.")
    customer_id = parse_int_field(payload.get("customer_id"), "клиент")
    if not customer_id or not active_exists(conn, "customers", customer_id):
        raise ValueError("Выберите действующего клиента.")
    make = clean_text(payload.get("make"), 120)
    model = clean_text(payload.get("model"), 120)
    plate = clean_text(payload.get("plate"), 40).upper()
    vin = validate_vin(str(payload.get("vin") or ""))
    if not (make or model or plate or vin):
        raise ValueError("Укажите автомобиль: марку, модель, номер или VIN.")
    return {
        "customer_id": customer_id,
        "make": make,
        "model": model,
        "year": validate_vehicle_year(payload.get("year")),
        "plate": plate,
        "vin": vin,
        "mileage": require_mileage_limit(
            require_non_negative_int(payload.get("mileage"), "пробег"), "пробег"
        ),
        "next_service_at": parse_date_iso(
            payload.get("next_service_at"), "дата следующего сервиса"
        ),
        "next_service_mileage": require_mileage_limit(
            require_non_negative_int(
                payload.get("next_service_mileage"), "сервисный пробег"
            ),
            "сервисный пробег",
        ),
        "notes": clean_multiline(payload.get("notes"), 2000),
    }


def validate_inventory(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Некорректный формат данных.")
    name = clean_text(payload.get("name"), 220)
    if not name:
        raise ValueError("Укажите название позиции склада.")
    quantity = require_non_negative_float(payload.get("quantity"), "остаток")
    min_quantity = require_non_negative_float(
        payload.get("min_quantity"), "минимальный остаток"
    )
    price = require_non_negative_float(payload.get("price"), "цена")
    cost = require_non_negative_float(payload.get("cost"), "себестоимость")

    ensure_finite_money(quantity * price, "стоимость остатка по цене")
    ensure_finite_money(quantity * cost, "стоимость остатка по себестоимости")

    return {
        "sku": clean_text(payload.get("sku"), 100).upper(),
        "name": name,
        "brand": clean_text(payload.get("brand"), 140),
        "unit": clean_text(payload.get("unit"), 30, "шт") or "шт",
        "quantity": quantity,
        "min_quantity": min_quantity,
        "price": price,
        "cost": cost,
        "supplier": clean_text(payload.get("supplier"), 180),
        "notes": clean_multiline(payload.get("notes"), 2000),
    }


def validate_order(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
    *,
    allow_deleted_inventory_ids: set[int] | None = None,
    allow_deleted_vehicle_id: int | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Некорректный формат данных.")
    customer_id = parse_int_field(payload.get("customer_id"), "клиент")
    if not customer_id or not active_exists(conn, "customers", customer_id):
        raise ValueError("Выберите действующего клиента.")

    vehicle_id_raw = parse_int_field(payload.get("vehicle_id"), "автомобиль") or None
    vehicle_id = ensure_vehicle_belongs_to_customer(
        conn,
        vehicle_id_raw,
        customer_id,
        allow_deleted_vehicle_id=allow_deleted_vehicle_id,
    )

    status = clean_text(payload.get("status"), 40, "new")
    if status not in ORDER_STATUSES:
        raise ValueError("Некорректный статус заказа.")

    priority = clean_text(payload.get("priority"), 20, "normal")
    if priority not in ORDER_PRIORITIES:
        raise ValueError("Некорректный приоритет заказа.")

    raw_items = payload.get("items") or []
    if not isinstance(raw_items, list):
        raise ValueError("Позиции заказ-наряда должны быть списком.")

    # Pre-fetch inventory records to avoid N+1 query loop in validate_order_item
    parts_map = {}
    part_ids = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        kind = clean_text(item.get("kind"), 20, "service")
        if kind == "part":
            inventory_id = parse_int_field(
                item.get("inventory_id"), "складская позиция"
            )
            if inventory_id is not None and inventory_id > 0:
                part_ids.append(inventory_id)
    if part_ids:
        placeholders = ",".join("?" for _ in part_ids)
        rows = conn.execute(
            f"SELECT id, name, price, cost, deleted_at FROM inventory WHERE id IN ({placeholders})",
            part_ids,
        ).fetchall()
        parts_map = {row["id"]: row for row in rows}

    items = [
        validate_order_item(
            conn,
            item,
            allow_deleted_inventory_ids=allow_deleted_inventory_ids,
            parts_map=parts_map,
        )
        for item in raw_items
    ]
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
        "odometer": require_mileage_limit(
            require_non_negative_int(payload.get("odometer"), "пробег в заказе"),
            "пробег в заказе",
        ),
        "complaint": clean_multiline(payload.get("complaint"), 3000),
        "diagnosis": clean_multiline(payload.get("diagnosis"), 3000),
        "recommendations": clean_multiline(payload.get("recommendations"), 3000),
        "discount": require_non_negative_float(payload.get("discount"), "скидка"),
        "tax_rate": validate_tax_rate(
            require_non_negative_float(payload.get("tax_rate"), "налог")
        ),
        "paid": require_non_negative_float(payload.get("paid"), "оплачено"),
        "payment_method": clean_text(payload.get("payment_method"), 80),
        "authorized_by": clean_text(payload.get("authorized_by"), 120),
        "authorized_at": parse_datetime_local(
            payload.get("authorized_at"), "дата согласования"
        ),
        "follow_up_at": parse_datetime_local(payload.get("follow_up_at"), "follow-up"),
        "items": items,
    }
    normalize_order_money(data)
    return data


def validate_appointment(
    conn: sqlite3.Connection, payload: dict[str, Any]
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Некорректный формат данных.")
    customer_id = parse_int_field(payload.get("customer_id"), "клиент")
    if not customer_id or not active_exists(conn, "customers", customer_id):
        raise ValueError("Выберите действующего клиента.")

    vehicle_id_raw = parse_int_field(payload.get("vehicle_id"), "автомобиль") or None
    vehicle_id = ensure_vehicle_belongs_to_customer(conn, vehicle_id_raw, customer_id)

    scheduled_at = parse_datetime_local(
        payload.get("scheduled_at"), "дата и время записи", required=True
    )

    duration_minutes = parse_int_field(
        payload.get("duration_minutes"), "длительность записи", 60
    )
    if duration_minutes < 15 or duration_minutes > 480:
        raise ValueError("Длительность записи должна быть от 15 до 480 минут.")
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


def normalize_order_money(order_data: dict[str, Any]) -> None:
    items = order_data.get("items", [])
    subtotal = ensure_finite_money(
        sum(
            ensure_finite_money(
                parse_float(item.get("quantity")) * parse_float(item.get("unit_price")),
                "сумма позиции",
            )
            for item in items
            if item_is_billable(item)
        ),
        "сумма заказ-наряда",
    )
    ensure_finite_money(
        sum(
            ensure_finite_money(
                parse_float(item.get("quantity")) * parse_float(item.get("unit_cost")),
                "себестоимость позиции",
            )
            for item in items
            if item_is_billable(item)
        ),
        "себестоимость заказ-наряда",
    )
    order_data["discount"] = min(parse_float(order_data.get("discount")), subtotal)
    tax_rate = min(parse_float(order_data.get("tax_rate")), 100)
    order_data["tax_rate"] = tax_rate
    total = ensure_finite_money(
        max(subtotal - order_data["discount"], 0) * (1 + tax_rate / 100),
        "итог заказ-наряда",
    )
    order_data["paid"] = min(parse_float(order_data.get("paid")), total)


def validate_order_item(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
    *,
    allow_deleted_inventory_ids: set[int] | None = None,
    parts_map: dict[int, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Позиция заказ-наряда должна быть JSON-объектом.")
    kind = clean_text(payload.get("kind"), 20, "service")
    if kind not in {"service", "part"}:
        raise ValueError("Некорректный тип позиции заказ-наряда.")
    inventory_id = (
        parse_int_field(payload.get("inventory_id"), "складская позиция")
        if kind == "part"
        else None
    )
    if inventory_id is not None and inventory_id <= 0:
        inventory_id = None
    title = clean_text(payload.get("title"), 220)
    has_unit_price = "unit_price" in payload and not is_blank(payload.get("unit_price"))
    has_unit_cost = "unit_cost" in payload and not is_blank(payload.get("unit_cost"))
    unit_price = (
        optional_non_negative_float(payload.get("unit_price"), "цена позиции")
        if has_unit_price
        else 0
    )
    unit_cost = (
        optional_non_negative_float(payload.get("unit_cost"), "себестоимость позиции")
        if has_unit_cost
        else 0
    )
    approval_status = clean_text(payload.get("approval_status"), 30, "approved")
    if approval_status not in ITEM_APPROVAL_STATUSES:
        raise ValueError("Некорректный статус согласования позиции заказ-наряда.")

    if kind == "part" and inventory_id:
        if parts_map is not None and inventory_id in parts_map:
            part = parts_map.get(inventory_id)
        else:
            part = conn.execute(
                "SELECT id, name, price, cost, deleted_at FROM inventory WHERE id = ?",
                (inventory_id,),
            ).fetchone()
        allowed_deleted = inventory_id in (allow_deleted_inventory_ids or set())
        if not part or (part["deleted_at"] and not allowed_deleted):
            raise ValueError("Выбранная складская позиция не найдена.")
        if not title:
            title = str(part["name"])
        if not has_unit_price:
            unit_price = parse_float(part["price"])
        if not has_unit_cost:
            unit_cost = parse_float(part["cost"])
    elif kind == "service":
        inventory_id = None

    if not title:
        raise ValueError("Укажите наименование запчасти или работы.")

    quantity = require_non_negative_float(
        payload.get("quantity"), "количество позиции", 1
    )
    if quantity <= 0:
        raise ValueError("Количество в позиции должно быть больше нуля.")
    if quantity < MIN_QUANTITY_STEP:
        raise ValueError(
            f"Количество в позиции должно быть не меньше {MIN_QUANTITY_STEP:g}."
        )

    ensure_finite_money(quantity * unit_price, "сумма позиции")
    ensure_finite_money(quantity * unit_cost, "себестоимость позиции")

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
    if table not in {"customers", "vehicles", "inventory", "orders", "appointments"}:
        return False
    row = conn.execute(
        f"SELECT 1 FROM {table} WHERE id = ? AND deleted_at IS NULL",  # nosec B608
        (record_id,),  # nosec B608
    ).fetchone()
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
    query = f"SELECT id FROM {table} WHERE CASEFOLD(TRIM({column})) = CASEFOLD(TRIM(?)) AND deleted_at IS NULL"  # nosec B608
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
    allow_deleted_vehicle_id: int | None = None,
) -> int | None:
    if not vehicle_id:
        if required:
            raise ValueError("Выберите действующий автомобиль.")
        return None
    if allow_deleted_vehicle_id is not None and vehicle_id == allow_deleted_vehicle_id:
        vehicle_owner = conn.execute(
            "SELECT customer_id FROM vehicles WHERE id = ?",
            (vehicle_id,),
        ).fetchone()
    else:
        vehicle_owner = conn.execute(
            "SELECT customer_id FROM vehicles WHERE id = ? AND deleted_at IS NULL",
            (vehicle_id,),
        ).fetchone()
    if not vehicle_owner:
        raise ValueError("Выберите действующий автомобиль.")
    if vehicle_owner["customer_id"] != customer_id:
        raise ValueError("Выбранный автомобиль принадлежит другому клиенту.")
    return vehicle_id


def ensure_no_appointment_conflict(
    conn: sqlite3.Connection,
    scheduled_at: str,
    duration_minutes: int,
    *,
    record_id: int | None = None,
) -> None:
    start_raw = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
    if start_raw.tzinfo is not None:
        # Normalize timezone-aware inputs to UTC for comparison, and do the same for stored timezone-aware values.
        # But wait! If the stored scheduled_at is '2026-06-12T10:00:00+03:00', fromisoformat parses it with a tzinfo too.
        # Let's convert both to timezone-aware UTC datetime objects to compare their absolute moments in time!
        start = start_raw.astimezone(datetime.now().astimezone().tzinfo)
    else:
        start = start_raw
    end = start + timedelta(minutes=duration_minutes)
    if end <= start:
        raise ValueError("Длительность записи должна быть больше нуля.")

    start_date = start.date()
    min_date = (start_date - timedelta(days=2)).isoformat()
    max_date = (start_date + timedelta(days=2)).isoformat()

    # Since we can query with UTC or local timezone-aware formats, let's load active entries within a small window
    # around the target date and compare them in memory. This avoids loading the entire historic calendar.
    rows = conn.execute(
        """
        SELECT a.id, a.scheduled_at, a.duration_minutes, c.name AS customer_name
        FROM appointments a
        JOIN customers c ON c.id = a.customer_id
        WHERE a.deleted_at IS NULL
          AND a.status IN ('scheduled', 'confirmed', 'arrived')
          AND a.scheduled_at >= ?
          AND a.scheduled_at <= ?
          AND (? IS NULL OR a.id <> ?)
        """,
        (min_date, max_date, record_id, record_id),
    ).fetchall()

    for row in rows:
        try:
            existing_start_raw = datetime.fromisoformat(
                str(row["scheduled_at"]).replace("Z", "+00:00")
            )
        except ValueError:
            continue

        if existing_start_raw.tzinfo is not None and start.tzinfo is not None:
            existing_start = existing_start_raw.astimezone(start.tzinfo)
        elif existing_start_raw.tzinfo is not None:
            # Existing has tz, start does not. Assume start is in local time.
            existing_start = existing_start_raw.astimezone().replace(tzinfo=None)
        elif start.tzinfo is not None:
            # Start has tz, existing does not. Assume existing is in local time.
            existing_start = existing_start_raw
            start_compare = start.astimezone().replace(tzinfo=None)
            end_compare = end.astimezone().replace(tzinfo=None)
            existing_end = existing_start + timedelta(
                minutes=max(parse_int(row["duration_minutes"], 60), 15)
            )
            if start_compare < existing_end and end_compare > existing_start:
                when = existing_start.strftime("%d.%m.%Y %H:%M")
                raise ValueError(
                    f"На это время уже есть запись: {row['customer_name']} в {when}."
                )
            continue
        else:
            existing_start = existing_start_raw

        existing_end = existing_start + timedelta(
            minutes=max(parse_int(row["duration_minutes"], 60), 15)
        )
        if start < existing_end and end > existing_start:
            # Format when to local/configured tz if tzinfo is present
            when = existing_start.strftime("%d.%m.%Y %H:%M")
            raise ValueError(
                f"На это время уже есть запись: {row['customer_name']} в {when}."
            )


def active_appointment_count_for_customer(
    conn: sqlite3.Connection, customer_id: int
) -> int:
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


def active_appointment_count_for_vehicle(
    conn: sqlite3.Connection, vehicle_id: int
) -> int:
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
