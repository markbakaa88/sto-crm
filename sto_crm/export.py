"""Bootstrap payload and CSV export endpoints."""

from __future__ import annotations

import csv
import io
from typing import Any

from . import runtime as _runtime
from .catalog import car_catalog_payload
from .config import (
    APP_NAME,
    APP_VERSION,
    APPOINTMENT_STATUSES,
    INSPECTION_CONDITIONS,
    INSPECTION_STATUSES,
    ITEM_APPROVAL_STATUSES,
    LOOKUP_LIMIT,
    ORDER_PRIORITIES,
    ORDER_STATUSES,
    PREFERRED_CHANNELS,
)
from .queries import list_appointments, list_customers, list_inspections, list_inventory, list_orders, list_vehicles
from .reports import build_reports
from .runtime import (
    clean_text,
    csv_cell,
    display_path,
    github_latest_release_url,
    github_repository_url,
    is_frozen,
    normalize_github_repository,
)

def bootstrap_payload(q: str = "", status: str = "all") -> dict[str, Any]:
    status = clean_text(status, 40, "all") or "all"
    if status not in {"all", *ORDER_STATUSES}:
        raise ValueError("Некорректный статус заказа.")
    customers = list_customers(q)
    vehicles = list_vehicles(q)
    inventory = list_inventory(q)
    appointments = list_appointments(q)
    inspections = list_inspections(q)
    orders = list_orders(q, status)
    lookup_customers = list_customers("", LOOKUP_LIMIT)
    lookup_vehicles = list_vehicles("", LOOKUP_LIMIT)
    lookup_inventory = list_inventory("", LOOKUP_LIMIT)
    lookup_orders = list_orders("", "all", LOOKUP_LIMIT)
    all_orders = list_orders("", "all", None)
    all_inventory = list_inventory("", None)
    all_vehicles = list_vehicles("", None)
    all_appointments = list_appointments("", "all", None)
    all_inspections = list_inspections("", "all", None)
    lookup_appointments = all_appointments[:LOOKUP_LIMIT]
    lookup_inspections = all_inspections[:LOOKUP_LIMIT]
    reports = build_reports(
        all_orders, all_inventory, all_vehicles, all_appointments, all_inspections
    )
    return {
        "app": {
            "name": APP_NAME,
            "version": APP_VERSION,
            "db_path": _runtime.RUNTIME.db_path.name,
            "db_directory": display_path(_runtime.RUNTIME.db_path.parent),
            "csrf_token": _runtime.RUNTIME.csrf_token,
            "repository": normalize_github_repository(),
            "repository_url": github_repository_url(),
            "releases_url": github_latest_release_url(),
            "can_install_update": is_frozen(),
        },
        "statuses": ORDER_STATUSES,
        "appointment_statuses": APPOINTMENT_STATUSES,
        "item_approval_statuses": ITEM_APPROVAL_STATUSES,
        "inspection_statuses": INSPECTION_STATUSES,
        "inspection_conditions": INSPECTION_CONDITIONS,
        "customers": customers,
        "vehicles": vehicles,
        "inventory": inventory,
        "appointments": appointments,
        "inspections": inspections,
        "orders": orders,
        "car_catalog": car_catalog_payload(),
        "lookups": {
            "customers": lookup_customers,
            "vehicles": lookup_vehicles,
            "inventory": lookup_inventory,
            "orders": lookup_orders,
            "appointments": lookup_appointments,
            "inspections": lookup_inspections,
        },
        "reports": reports,
        "preferred_channels": PREFERRED_CHANNELS,
        "priorities": ORDER_PRIORITIES,
    }


def csv_export(entity: str) -> tuple[str, str]:
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    if entity == "customers":
        rows = list_customers("", None)
        headers = ["id", "name", "phone", "email", "source", "preferred_channel", "reminder_consent", "vehicles_count", "orders_count", "notes"]
    elif entity == "vehicles":
        rows = list_vehicles("", None)
        headers = ["id", "customer_name", "make", "model", "year", "plate", "vin", "mileage", "next_service_at", "next_service_mileage", "notes"]
    elif entity == "inventory":
        rows = list_inventory("", None)
        headers = ["id", "sku", "name", "brand", "unit", "quantity", "min_quantity", "price", "cost", "supplier", "notes"]
    elif entity == "appointments":
        rows = list_appointments("", "all", None)
        headers = [
            "id", "scheduled_at", "duration_minutes", "status", "customer_name", "customer_phone",
            "vehicle_plate", "vehicle_make", "vehicle_model", "advisor", "reason", "notes",
        ]
    elif entity == "inspections":
        rows = []
        inspection_fields = [
            "id", "inspected_at", "status", "customer_name", "customer_phone",
            "vehicle_plate", "vehicle_make", "vehicle_model", "order_number", "inspector",
        ]
        for inspection in list_inspections("", "all", None):
            items = inspection.get("items", []) or []
            if not items:
                rows.append(
                    {
                        **{k: inspection.get(k, "") for k in inspection_fields},
                        "area": "",
                        "item_title": "",
                        "condition_status": "",
                        "approval_status": "",
                        "recommendation": "",
                        "estimate": "",
                    }
                )
                continue
            for item in items:
                rows.append(
                    {
                        **{k: inspection.get(k, "") for k in inspection_fields},
                        "area": item.get("area", ""),
                        "item_title": item.get("title", ""),
                        "condition_status": item.get("condition_status", ""),
                        "approval_status": item.get("approval_status", ""),
                        "recommendation": item.get("recommendation", ""),
                        "estimate": item.get("estimate", ""),
                    }
                )
        headers = [
            "id", "inspected_at", "status", "customer_name", "customer_phone", "vehicle_plate",
            "vehicle_make", "vehicle_model", "order_number", "inspector", "area", "item_title",
            "condition_status", "approval_status", "recommendation", "estimate",
        ]
    elif entity == "orders":
        rows = list_orders("", "all", None)
        headers = [
            "id", "number", "status", "customer_name", "vehicle_plate", "vehicle_make", "vehicle_model",
            "authorized_by", "authorized_at", "follow_up_at", "total", "paid", "due", "created_at", "updated_at",
        ]
    elif entity in {"catalog", "car_catalog"}:
        catalog = car_catalog_payload()
        rows = [
            {"make": make, "model": model}
            for make in catalog["makes"]
            for model in (catalog["models"].get(make) or [""])
        ]
        headers = ["make", "model"]
        entity = "car_catalog"
    else:
        raise KeyError("Неизвестный экспорт.")
    writer.writerow(headers)
    for row in rows:
        writer.writerow([csv_cell(row.get(header, "")) for header in headers])
    return f"{entity}.csv", "\ufeff" + output.getvalue()
