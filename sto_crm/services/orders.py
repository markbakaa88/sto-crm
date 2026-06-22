"""Transactional order service functions."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from ..config import (
    CONSUMING_STATUSES,
    ORDER_STATUS_TRANSITIONS,
)
from ..database import RetryingConnection, write_db
from ..runtime import now_iso, parse_float, parse_int
from ..validation import (
    generate_order_number,
    normalize_order_money,
    validate_order,
)
from .inventory import apply_inventory_delta, ensure_inventory_available_for_order
from .vehicles import (
    reconcile_vehicle_mileage_after_order_change,
    sync_vehicle_mileage_from_order,
)

logger = logging.getLogger("sto_crm")


def _query_get_order(conn: sqlite3.Connection, record_id: int) -> dict[str, Any]:
    # Lazy import разрывает цикл queries → services.
    from ..queries import get_order

    return get_order(conn, record_id)


def create_order(payload: dict[str, Any]) -> dict[str, Any]:
    with write_db() as conn:
        order_id = create_order_tx(conn, payload)
        return _query_get_order(conn, order_id)


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
        if (
            str(old["closed_at"] or "")
            and old_status == "cancelled"
            and new_status != "cancelled"
        ):
            raise ValueError(
                "Отменённый после закрытия заказ-наряд нельзя повторно открыть или изменить. Создайте новый корректирующий заказ."
            )
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
    preserved_timestamps: dict[tuple[Any, ...], str] | None = None,
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


def list_order_items(
    conn: sqlite3.Connection | RetryingConnection, order_id: int
) -> list[dict[str, Any]]:
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


def status_reserves_inventory(status: str) -> bool:
    return status in {"approved", "in_progress", "done"}


def status_needs_inventory_availability_check(old_status: str, new_status: str) -> bool:
    return status_reserves_inventory(new_status) or (
        new_status in CONSUMING_STATUSES and old_status not in CONSUMING_STATUSES
    )


def closed_signature_number(value: Any) -> float:
    return round(parse_float(value), 9)


def closed_item_signature(item: dict[str, Any]) -> tuple[Any, ...]:
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
        parse_int(order["odometer"]),
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
