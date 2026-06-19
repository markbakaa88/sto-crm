"""Bootstrap payload and CSV export endpoints."""

from __future__ import annotations

import csv
import io
from collections.abc import Generator
from typing import Any

from . import runtime as _runtime
from .catalog import car_catalog_payload
from .config import (
    APP_NAME,
    APP_VERSION,
    APPOINTMENT_STATUSES,
    ITEM_APPROVAL_STATUSES,
    LOOKUP_LIMIT,
    ORDER_PRIORITIES,
    ORDER_STATUSES,
    PREFERRED_CHANNELS,
)
from .queries import (
    _mask_deleted_order_vehicle,
    attach_items_and_totals,
    list_appointments,
    list_customers,
    list_inventory,
    list_orders,
    list_vehicles,
)
from .reports import build_reports
from .runtime import (
    clean_text,
    csv_cell,
    display_path,
    github_latest_release_url,
    github_repository_url,
    normalize_github_repository,
)
from .updates import (
    can_install_windows_update,
    latest_backup_info,
    public_backup_payload,
)


def bootstrap_payload(q: str = "", status: str = "all") -> dict[str, Any]:
    status = clean_text(status, 40, "all") or "all"
    if status not in {"all", *ORDER_STATUSES}:
        raise ValueError("Некорректный статус заказа.")
    customers = list_customers(q)
    vehicles = list_vehicles(q)
    inventory = list_inventory(q)
    appointments = list_appointments(q)
    orders = list_orders(q, status)
    lookup_customers = list_customers("", LOOKUP_LIMIT)
    lookup_vehicles = list_vehicles("", LOOKUP_LIMIT)
    lookup_inventory = list_inventory("", LOOKUP_LIMIT)
    lookup_orders = list_orders("", "all", LOOKUP_LIMIT)
    all_orders = list_orders("", "all", None)
    all_inventory = list_inventory("", None)
    all_vehicles = list_vehicles("", None)
    all_appointments = list_appointments("", "all", None)
    all_customers = list_customers("", None)
    lookup_appointments = all_appointments[:LOOKUP_LIMIT]
    reports = build_reports(
        all_orders, all_inventory, all_vehicles, all_appointments, all_customers
    )
    last_backup = public_backup_payload(latest_backup_info())
    return {
        "app": {
            "name": APP_NAME,
            "version": APP_VERSION,
            "db_path": _runtime.RUNTIME.db_path.name,
            "db_directory": display_path(_runtime.RUNTIME.db_path.parent),
            "csrf_token": _runtime.RUNTIME.csrf_token,
            "access_token": _runtime.RUNTIME.access_token,
            "repository": normalize_github_repository(),
            "repository_url": github_repository_url(),
            "releases_url": github_latest_release_url(),
            "can_install_update": can_install_windows_update(),
            "last_backup_at": last_backup.get("created_at", "") if last_backup else "",
            "last_backup": last_backup,
        },
        "statuses": ORDER_STATUSES,
        "appointment_statuses": APPOINTMENT_STATUSES,
        "item_approval_statuses": ITEM_APPROVAL_STATUSES,
        "customers": customers,
        "vehicles": vehicles,
        "inventory": inventory,
        "appointments": appointments,
        "orders": orders,
        "car_catalog": car_catalog_payload(),
        "lookups": {
            "customers": lookup_customers,
            "vehicles": lookup_vehicles,
            "inventory": lookup_inventory,
            "orders": lookup_orders,
            "appointments": lookup_appointments,
        },
        "reports": reports,
        "preferred_channels": PREFERRED_CHANNELS,
        "priorities": ORDER_PRIORITIES,
    }


def csv_export(entity: str) -> tuple[str, Generator[str]]:
    if entity == "customers":
        headers = [
            "id",
            "name",
            "phone",
            "email",
            "source",
            "preferred_channel",
            "reminder_consent",
            "vehicles_count",
            "orders_count",
            "notes",
        ]
        query = """
            SELECT c.*,
                   (SELECT COUNT(*) FROM vehicles v WHERE v.customer_id = c.id AND v.deleted_at IS NULL) AS vehicles_count,
                   (SELECT COUNT(*) FROM orders o WHERE o.customer_id = c.id AND o.deleted_at IS NULL) AS orders_count
            FROM customers c
            WHERE c.deleted_at IS NULL
            ORDER BY c.updated_at DESC, c.id DESC
        """
    elif entity == "vehicles":
        headers = [
            "id",
            "customer_name",
            "make",
            "model",
            "year",
            "plate",
            "vin",
            "mileage",
            "next_service_at",
            "next_service_mileage",
            "notes",
        ]
        query = """
            SELECT v.*, c.name AS customer_name, c.phone AS customer_phone,
                   c.preferred_channel AS customer_preferred_channel,
                   c.reminder_consent AS customer_reminder_consent
            FROM vehicles v
            JOIN customers c ON c.id = v.customer_id
            WHERE v.deleted_at IS NULL AND c.deleted_at IS NULL
            ORDER BY v.updated_at DESC, v.id DESC
        """
    elif entity == "inventory":
        headers = [
            "id",
            "sku",
            "name",
            "brand",
            "unit",
            "quantity",
            "min_quantity",
            "price",
            "cost",
            "supplier",
            "notes",
        ]
        query = """
            SELECT *,
                   CASE WHEN min_quantity > 0 AND quantity <= min_quantity THEN 1 ELSE 0 END AS is_low
            FROM inventory
            WHERE deleted_at IS NULL
            ORDER BY is_low DESC, updated_at DESC, id DESC
        """
    elif entity == "appointments":
        headers = [
            "id",
            "scheduled_at",
            "duration_minutes",
            "status",
            "customer_name",
            "customer_phone",
            "vehicle_plate",
            "vehicle_make",
            "vehicle_model",
            "advisor",
            "reason",
            "notes",
        ]
        query = """
            SELECT a.*, c.name AS customer_name, c.phone AS customer_phone,
                   v.make AS vehicle_make, v.model AS vehicle_model, v.year AS vehicle_year,
                   v.plate AS vehicle_plate, v.vin AS vehicle_vin
            FROM appointments a
            JOIN customers c ON c.id = a.customer_id
            LEFT JOIN vehicles v ON v.id = a.vehicle_id
            WHERE a.deleted_at IS NULL AND c.deleted_at IS NULL AND (a.vehicle_id IS NULL OR v.deleted_at IS NULL)
            ORDER BY
                CASE WHEN a.status IN ('done', 'no_show', 'cancelled') THEN 1 ELSE 0 END,
                a.scheduled_at,
                a.id
        """
    elif entity == "orders":
        headers = [
            "id",
            "number",
            "status",
            "customer_name",
            "vehicle_plate",
            "vehicle_make",
            "vehicle_model",
            "authorized_by",
            "authorized_at",
            "follow_up_at",
            "total",
            "paid",
            "due",
            "created_at",
            "updated_at",
        ]
        query = """
            SELECT o.*, c.name AS customer_name, c.phone AS customer_phone,
                   v.make AS vehicle_make, v.model AS vehicle_model, v.year AS vehicle_year,
                   v.plate AS vehicle_plate, v.vin AS vehicle_vin, v.mileage AS vehicle_mileage,
                   v.deleted_at AS vehicle_deleted_at
            FROM orders o
            JOIN customers c ON c.id = o.customer_id
            LEFT JOIN vehicles v ON v.id = o.vehicle_id
            WHERE o.deleted_at IS NULL AND c.deleted_at IS NULL
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
        """
    elif entity in {"catalog", "car_catalog"}:
        headers = ["make", "model"]
        query = None
        entity = "car_catalog"
    else:
        raise KeyError("Неизвестный экспорт.")

    filename = f"{entity}.csv"

    def generator() -> Generator[str]:
        # Yield UTF-8 BOM
        yield "\ufeff"

        # Headers
        output = io.StringIO()
        writer = csv.writer(output, delimiter=";")
        writer.writerow(headers)
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)

        if query is None:
            # Special case for catalog/car_catalog
            catalog = car_catalog_payload()
            for make in catalog["makes"]:
                for model in catalog["models"].get(make) or [""]:
                    row = {"make": make, "model": model}
                    writer.writerow(
                        [csv_cell(row.get(header, "")) for header in headers]
                    )
                    yield output.getvalue()
                    output.seek(0)
                    output.truncate(0)
            return

        # Query database in batches
        from .database import db

        batch_size = 200
        with db(readonly=True) as conn:
            cursor = conn.execute(query)
            while True:
                rows = cursor.fetchmany(batch_size)
                if not rows:
                    break

                # Convert rows to dicts
                dict_rows = [dict(r) for r in rows]

                # Post-process if order
                if entity == "orders":
                    dict_rows = [_mask_deleted_order_vehicle(r) for r in dict_rows]
                    attach_items_and_totals(conn, dict_rows)  # type: ignore[arg-type]

                for row in dict_rows:
                    writer.writerow(
                        [csv_cell(row.get(header, "")) for header in headers]
                    )
                    yield output.getvalue()
                    output.seek(0)
                    output.truncate(0)

    return filename, generator()
