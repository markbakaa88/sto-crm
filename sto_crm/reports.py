"""Executive dashboard and CRM action-plan report builders."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from .config import (
    APPOINTMENT_STATUSES,
    ITEM_APPROVAL_STATUSES,
    ORDER_STATUSES,
    PREFERRED_CHANNELS,
)
from .runtime import clean_text, money, parse_float, parse_int
from .validation import item_is_billable


def format_vehicle_text(make: Any, model: Any, year: Any, plate: Any) -> str:
    parts = []
    for val in [make, model, year, plate]:
        cleaned = str(val or "").strip()
        if cleaned:
            parts.append(cleaned)
    return " ".join(parts)


def order_vehicle_text(order: dict[str, Any]) -> str:
    return format_vehicle_text(
        order.get("vehicle_make"),
        order.get("vehicle_model"),
        order.get("vehicle_year"),
        order.get("vehicle_plate"),
    )


def build_reports(
    orders: list[dict[str, Any]],
    inventory: list[dict[str, Any]],
    vehicles: list[dict[str, Any]],
    appointments: list[dict[str, Any]],
    customers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    now = datetime.now()
    today = now.date()
    month_prefix = now.strftime("%Y-%m")
    active_statuses = {
        "new",
        "diagnostics",
        "estimate",
        "approved",
        "in_progress",
        "done",
    }
    active_orders = [o for o in orders if o.get("status") in active_statuses]

    def parse_local_datetime(value: Any) -> datetime | None:
        text = str(value or "").strip().replace(" ", "T")
        if not text:
            return None
        dt = None
        for fmt in (text, text[:19], text[:16], text[:10]):
            try:
                dt = datetime.fromisoformat(fmt)
                break
            except ValueError:
                continue
        if dt is not None:
            if dt.tzinfo is not None:
                dt = dt.replace(tzinfo=None)
            return dt
        return None

    def summarize_order(order: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": order.get("id"),
            "number": order.get("number"),
            "status": order.get("status"),
            "priority": order.get("priority"),
            "customer_id": order.get("customer_id"),
            "customer_name": order.get("customer_name"),
            "customer_phone": order.get("customer_phone"),
            "vehicle": order_vehicle_text(order),
            "promised_at": order.get("promised_at"),
            "advisor": order.get("advisor"),
            "mechanic": order.get("mechanic"),
            "total": round(parse_float(order.get("total")), 2),
            "due": round(parse_float(order.get("due")), 2),
            "margin": round(parse_float(order.get("margin")), 2),
            "updated_at": order.get("updated_at"),
        }

    # Использование более точного datetime-парсинга для определения закрытых заказов текущего месяца
    month_closed = []
    for o in orders:
        if o.get("status") != "closed":
            continue
        closed_dt = parse_local_datetime(o.get("closed_at"))
        if (
            closed_dt
            and closed_dt.year == today.year
            and closed_dt.month == today.month
        ):
            month_closed.append(o)

    closed_orders = [o for o in orders if o.get("status") == "closed"]
    revenue_month = sum(parse_float(o.get("total")) for o in month_closed)

    # Безопасный расчет налогооблагаемой базы
    taxable_month = sum(
        max(parse_float(o.get("subtotal")) - parse_float(o.get("discount")), 0.0)
        for o in month_closed
    )
    gross_margin_month = sum(parse_float(o.get("margin")) for o in month_closed)

    # Защита от деления на околонулевые и нулевые значения
    margin_percent_month = (
        (gross_margin_month / taxable_month * 100) if abs(taxable_month) > 1e-9 else 0.0
    )
    due_total = sum(
        max(parse_float(o.get("due")), 0.0)
        for o in orders
        if o.get("status") != "cancelled"
    )
    avg_check = revenue_month / len(month_closed) if month_closed else 0.0

    conversion_base = [
        o
        for o in orders
        if o.get("status") in {"estimate", "approved", "in_progress", "done", "closed"}
    ]
    conversion_won = [
        o
        for o in conversion_base
        if o.get("status") in {"approved", "in_progress", "done", "closed"}
    ]
    conversion_rate = (
        (len(conversion_won) / len(conversion_base) * 100) if conversion_base else 0.0
    )
    pipeline_value = sum(parse_float(o.get("total")) for o in active_orders)
    pipeline_due = sum(parse_float(o.get("due")) for o in active_orders)
    status_counts = dict.fromkeys(ORDER_STATUSES, 0)
    for order in orders:
        key = str(order.get("status") or "")
        if key in status_counts:
            status_counts[key] += 1
    low_stock = [
        p
        for p in inventory
        if parse_float(p.get("min_quantity")) > 0
        and parse_float(p.get("quantity")) <= parse_float(p.get("min_quantity"))
    ]
    inventory_value = sum(
        parse_float(p.get("quantity")) * parse_float(p.get("cost")) for p in inventory
    )

    # Использование parse_local_datetime для дат и сравнение объектов дат/времени
    promised_today = []
    overdue_orders = []
    for order in active_orders:
        promised_at = str(order.get("promised_at") or "")
        promised_dt = parse_local_datetime(promised_at)
        if promised_dt:
            if promised_dt.date() == today:
                promised_today.append(order)
            if promised_dt < now:
                overdue_orders.append(order)

    reminder_horizon = today + timedelta(days=14)
    service_reminders = []
    for vehicle in vehicles:
        if parse_int(vehicle.get("customer_reminder_consent"), 1) == 0:
            continue
        if str(vehicle.get("customer_preferred_channel") or "phone") == "none":
            continue
        next_service_at = str(vehicle.get("next_service_at") or "")
        next_service_mileage = parse_int(vehicle.get("next_service_mileage"))
        mileage = parse_int(vehicle.get("mileage"))
        due_by_date = False
        if next_service_at:
            try:
                # Извлекаем чистую дату
                clean_date = next_service_at.strip().split("T")[0].split(" ")[0]
                if len(clean_date) >= 10:
                    due_by_date = (
                        datetime.fromisoformat(clean_date[:10]).date()
                        <= reminder_horizon
                    )
            except ValueError:
                due_by_date = False
        due_by_mileage = bool(
            next_service_mileage and mileage and next_service_mileage <= mileage + 500
        )
        if due_by_date or due_by_mileage:
            service_reminders.append(
                {
                    **vehicle,
                    "due_by_date": due_by_date,
                    "due_by_mileage": due_by_mileage,
                }
            )

    followups_due = []
    for order in orders:
        follow_up_at = str(order.get("follow_up_at") or "")
        if order.get("status") != "closed" or not follow_up_at:
            continue
        try:
            # Извлекаем чистую дату
            clean_date = follow_up_at.strip().split("T")[0].split(" ")[0]
            if len(clean_date) >= 10:
                if datetime.fromisoformat(clean_date[:10]).date() <= today:
                    followups_due.append(order)
        except ValueError:
            continue

    authorizations_pending = [
        order
        for order in orders
        if order.get("status") == "estimate" and not order.get("authorized_at")
    ]
    deferred_work = []
    for order in orders:
        if order.get("status") == "cancelled":
            continue
        for item in order.get("items", []):
            approval_status = str(item.get("approval_status") or "approved")
            if approval_status in {"deferred", "declined"}:
                deferred_work.append(
                    {
                        "order_id": order.get("id"),
                        "order_number": order.get("number"),
                        "customer_name": order.get("customer_name"),
                        "customer_phone": order.get("customer_phone"),
                        "vehicle": order_vehicle_text(order),
                        "title": item.get("title"),
                        "approval_status": approval_status,
                        "amount": round(
                            parse_float(item.get("quantity"))
                            * parse_float(item.get("unit_price")),
                            2,
                        ),
                    }
                )

    appointment_active_statuses = {"scheduled", "confirmed", "arrived"}

    # Использование парсинга дат вместо .startswith() и [:10]
    appointments_today = []
    appointments_upcoming_all = []
    for appointment in appointments:
        if appointment.get("status") not in appointment_active_statuses:
            continue
        app_dt = parse_local_datetime(appointment.get("scheduled_at"))
        if app_dt:
            app_date = app_dt.date()
            if app_date == today:
                appointments_today.append(appointment)
            if app_date >= today:
                appointments_upcoming_all.append(appointment)

    appointments_upcoming = appointments_upcoming_all[:8]

    appointment_load_7_days = []
    for offset in range(7):
        day = today + timedelta(days=offset)
        day_prefix = day.isoformat()
        day_appointments = []
        for appointment in appointments:
            if appointment.get("status") not in appointment_active_statuses:
                continue
            app_dt = parse_local_datetime(appointment.get("scheduled_at"))
            if app_dt and app_dt.date() == day:
                day_appointments.append(appointment)

        appointment_load_7_days.append(
            {
                "date": day_prefix,
                "label": day.strftime("%d.%m"),
                "count": len(day_appointments),
                "appointments": day_appointments[:5],
            }
        )

    procurement_plan = []
    for part in low_stock:
        quantity = max(parse_float(part.get("quantity")), 0.0)
        min_quantity = max(parse_float(part.get("min_quantity")), 0.0)
        target_quantity = max(min_quantity * 2, min_quantity + 1, 1.0)
        reorder_quantity = max(target_quantity - quantity, 0.0)
        unit_budget = parse_float(part.get("cost")) or parse_float(part.get("price"))
        procurement_plan.append(
            {
                "id": part.get("id"),
                "sku": part.get("sku"),
                "name": part.get("name"),
                "unit": part.get("unit"),
                "quantity": round(quantity, 2),
                "min_quantity": round(min_quantity, 2),
                "reorder_quantity": round(reorder_quantity, 2),
                "budget": round(reorder_quantity * unit_budget, 2),
                "supplier": part.get("supplier"),
                "urgency": "critical" if quantity <= 0 else "low",
            }
        )
    procurement_plan.sort(
        key=lambda item: (
            0 if item["urgency"] == "critical" else 1,
            -parse_float(item.get("budget")),
        )
    )

    overdue_ids = {
        parse_int(order.get("id")) for order in overdue_orders if order.get("id")
    }
    pipeline_by_status = []
    for status, label in ORDER_STATUSES.items():
        status_orders = [order for order in orders if order.get("status") == status]
        status_overdue = [
            order
            for order in status_orders
            if parse_int(order.get("id")) in overdue_ids
        ]
        pipeline_by_status.append(
            {
                "status": status,
                "label": label,
                "count": len(status_orders),
                "total": round(
                    sum(parse_float(order.get("total")) for order in status_orders), 2
                ),
                "due": round(
                    sum(parse_float(order.get("due")) for order in status_orders), 2
                ),
                "overdue_count": len(status_overdue),
                "orders": [summarize_order(order) for order in status_orders[:6]],
            }
        )

    workload: dict[str, dict[str, Any]] = {}
    for order in active_orders:
        responsible = (
            clean_text(
                order.get("mechanic") or order.get("advisor"), 120, "Не назначен"
            )
            or "Не назначен"
        )
        bucket = workload.setdefault(
            responsible,
            {
                "name": responsible,
                "orders_count": 0,
                "total": 0.0,
                "due": 0.0,
                "overdue_count": 0,
            },
        )
        bucket["orders_count"] += 1
        bucket["total"] += parse_float(order.get("total"))
        bucket["due"] += parse_float(order.get("due"))
        if parse_int(order.get("id")) in overdue_ids:
            bucket["overdue_count"] += 1
    workload_by_responsible = sorted(
        [
            {
                **bucket,
                "total": round(parse_float(bucket.get("total")), 2),
                "due": round(parse_float(bucket.get("due")), 2),
            }
            for bucket in workload.values()
        ],
        key=lambda item: (
            parse_int(item.get("overdue_count")),
            parse_int(item.get("orders_count")),
            parse_float(item.get("total")),
        ),
        reverse=True,
    )[:8]

    service_sales: dict[str, float] = defaultdict(float)
    service_counts: dict[str, int] = defaultdict(int)
    for order in closed_orders:
        for item in order.get("items", []):
            if item.get("kind") == "service" and item_is_billable(item):
                title = str(item.get("title"))
                qty_val = parse_float(item.get("quantity"))
                price_val = parse_float(item.get("unit_price"))
                service_sales[title] += qty_val * price_val
                service_counts[title] += int(qty_val) if qty_val >= 1 else 1
    top_services = sorted(
        [
            {
                "title": title,
                "total": round(total, 2),
                "revenue": round(total, 2),
                "count": service_counts[title],
            }
            for title, total in service_sales.items()
        ],
        key=lambda x: parse_float(x["total"] or 0),
        reverse=True,
    )[:5]

    retention_by_customer: dict[int, dict[str, Any]] = {}
    for order in orders:
        if order.get("status") != "closed":
            continue
        cust_id = parse_int(order.get("customer_id"))
        if not cust_id:
            continue
        bucket = retention_by_customer.setdefault(
            cust_id,
            {
                "customer_id": cust_id,
                "customer_name": order.get("customer_name"),
                "customer_phone": order.get("customer_phone"),
                "orders_count": 0,
                "revenue": 0.0,
                "last_order_at": "",
                "_last_order_dt": None,
            },
        )
        bucket["orders_count"] += 1
        bucket["revenue"] += parse_float(order.get("total"))
        candidate_text = str(order.get("closed_at") or order.get("updated_at") or "")
        candidate_dt = parse_local_datetime(candidate_text)
        if candidate_dt and (
            bucket["_last_order_dt"] is None or candidate_dt > bucket["_last_order_dt"]
        ):
            bucket["_last_order_dt"] = candidate_dt
            bucket["last_order_at"] = candidate_text
        elif not bucket["last_order_at"]:
            bucket["last_order_at"] = candidate_text

    vip_customers = sorted(
        [
            {
                "customer_id": bucket["customer_id"],
                "customer_name": bucket.get("customer_name"),
                "customer_phone": bucket.get("customer_phone"),
                "orders_count": bucket["orders_count"],
                "revenue": round(parse_float(bucket.get("revenue")), 2),
                "last_order_at": bucket.get("last_order_at") or "",
            }
            for bucket in retention_by_customer.values()
            if parse_float(bucket.get("revenue")) > 0
            and (
                bucket["orders_count"] >= 2
                or parse_float(bucket.get("revenue")) >= 50_000
            )
        ],
        key=lambda item: (
            parse_float(item.get("revenue")),
            parse_int(item.get("orders_count")),
        ),
        reverse=True,
    )[:8]

    crm_tasks_count = (
        len(service_reminders)
        + len(followups_due)
        + len(authorizations_pending)
        + len(deferred_work)
    )
    risk_total = (
        len(overdue_orders)
        + len(low_stock)
        + len(authorizations_pending)
        + len(deferred_work)
    )
    risk_points = (
        len(overdue_orders) * 9
        + len(low_stock) * 4
        + len(authorizations_pending) * 5
        + len(deferred_work) * 3
    )
    business_health_score = max(0, min(100, 100 - risk_points))
    if business_health_score >= 85:
        business_health_label = "Отлично"
    elif business_health_score >= 70:
        business_health_label = "Контроль"
    else:
        business_health_label = "Риски"

    action_plan: list[dict[str, Any]] = []

    def add_action(
        kind: str,
        title: str,
        detail: str,
        priority: int,
        tone: str,
        route: str,
        action: str,
        record_id: Any = "",
        cta: str = "Открыть",
        customer_name: str = "",
        customer_phone: str = "",
        vehicle: str = "",
        amount: Any = 0,
        due_at: str = "",
    ) -> None:
        priority = max(0, min(100, parse_int(priority, 0)))
        if priority >= 90:
            priority_label = "Срочно"
        elif priority >= 72:
            priority_label = "Высокий"
        elif priority >= 55:
            priority_label = "Средний"
        else:
            priority_label = "Планово"
        action_plan.append(
            {
                "id": f"{kind}:{record_id or len(action_plan) + 1}:{len(action_plan) + 1}",
                "type": kind,
                "priority": priority,
                "priority_label": priority_label,
                "tone": tone,
                "title": clean_text(title, 180, "Действие CRM"),
                "detail": clean_text(detail, 260),
                "customer_name": clean_text(customer_name, 120),
                "customer_phone": clean_text(customer_phone, 80),
                "vehicle": clean_text(vehicle, 160),
                "amount": round(parse_float(amount), 2),
                "due_at": clean_text(due_at, 40),
                "route": clean_text(route, 40, "dashboard"),
                "action": clean_text(action, 60),
                "record_id": record_id or "",
                "cta": clean_text(cta, 80, "Открыть"),
            }
        )

    for order in overdue_orders:
        promised_dt = parse_local_datetime(order.get("promised_at"))
        overdue_hours = (
            int(max((now - promised_dt).total_seconds() // 3600, 0))
            if promised_dt
            else 0
        )
        base_priority = {"urgent": 100, "high": 94, "normal": 88, "low": 82}.get(
            str(order.get("priority") or "normal"), 86
        )
        add_action(
            "overdue_order",
            f"Просрочен заказ-наряд {order.get('number') or 'без номера'}",
            f"Срок прошел {overdue_hours} ч назад · статус {ORDER_STATUSES.get(str(order.get('status') or ''), order.get('status') or 'не указан')} · к оплате {money(order.get('due'))}.",
            min(100, base_priority + (2 if parse_float(order.get("due")) else 0)),
            "danger",
            "orders",
            "edit-order",
            order.get("id"),
            "Открыть заказ",
            str(order.get("customer_name") or ""),
            str(order.get("customer_phone") or ""),
            order_vehicle_text(order),
            order.get("due"),
            str(order.get("promised_at") or ""),
        )

    for order in authorizations_pending:
        add_action(
            "authorization",
            f"Согласовать смету {order.get('number') or 'без номера'}",
            f"Клиент еще не подтвердил работы на {money(order.get('total'))}. Зафиксируйте ответственного и дату согласования.",
            86,
            "warning",
            "orders",
            "edit-order",
            order.get("id"),
            "Согласовать",
            str(order.get("customer_name") or ""),
            str(order.get("customer_phone") or ""),
            order_vehicle_text(order),
            order.get("total"),
            str(order.get("updated_at") or ""),
        )

    for order in followups_due:
        add_action(
            "follow_up",
            f"Связаться после визита {order.get('number') or ''}".strip(),
            "Проверить удовлетворенность, закрыть возможные возражения и предложить следующий визит.",
            72,
            "info",
            "orders",
            "edit-order",
            order.get("id"),
            "Открыть клиента",
            str(order.get("customer_name") or ""),
            str(order.get("customer_phone") or ""),
            order_vehicle_text(order),
            0,
            str(order.get("follow_up_at") or ""),
        )

    for vehicle in service_reminders:
        vehicle_text = format_vehicle_text(
            vehicle.get("make"),
            vehicle.get("model"),
            vehicle.get("year"),
            vehicle.get("plate"),
        )
        reminder_reasons = []
        if vehicle.get("due_by_date"):
            reminder_reasons.append("по дате")
        if vehicle.get("due_by_mileage"):
            reminder_reasons.append("по пробегу")
        add_action(
            "service_reminder",
            "Напомнить о плановом сервисе",
            f"Причина: {', '.join(reminder_reasons) or 'приближается регламент'} · канал {PREFERRED_CHANNELS.get(str(vehicle.get('customer_preferred_channel') or 'phone'), 'Телефон')}.",
            64,
            "info",
            "vehicles",
            "edit-vehicle",
            vehicle.get("id"),
            "Открыть авто",
            str(vehicle.get("customer_name") or ""),
            str(vehicle.get("customer_phone") or ""),
            vehicle_text,
            0,
            str(vehicle.get("next_service_at") or ""),
        )

    for item in deferred_work:
        approval_status = str(item.get("approval_status") or "deferred")
        add_action(
            "deferred_work",
            f"Вернуть в продажу: {item.get('title') or 'отложенная работа'}",
            f"Статус клиента: {ITEM_APPROVAL_STATUSES.get(approval_status, approval_status).lower()} · потенциально {money(item.get('amount'))}.",
            66 if approval_status == "declined" else 60,
            "warning",
            "orders",
            "edit-order",
            item.get("order_id"),
            "Открыть заказ",
            str(item.get("customer_name") or ""),
            str(item.get("customer_phone") or ""),
            str(item.get("vehicle") or ""),
            item.get("amount"),
        )

    for part in procurement_plan:
        add_action(
            "procurement",
            f"Заказать склад: {part.get('name') or 'позиция'}",
            f"Остаток {part.get('quantity')} {part.get('unit') or 'шт'} при минимуме {part.get('min_quantity')} · бюджет {money(part.get('budget'))}.",
            68 if part.get("urgency") == "critical" else 54,
            "danger" if part.get("urgency") == "critical" else "info",
            "inventory",
            "edit-inventory",
            part.get("id"),
            "Открыть склад",
            "",
            "",
            "",
            part.get("budget"),
        )

    for appointment in appointments_today:
        status = str(appointment.get("status") or "scheduled")
        appointment_vehicle = format_vehicle_text(
            appointment.get("vehicle_make"),
            appointment.get("vehicle_model"),
            appointment.get("vehicle_year"),
            appointment.get("vehicle_plate"),
        )
        add_action(
            "appointment_today",
            f"Приёмка сегодня: {appointment.get('customer_name') or 'клиент'}",
            f"{APPOINTMENT_STATUSES.get(status, status)} · {appointment.get('reason') or 'причина не указана'}.",
            58 if status in {"scheduled", "confirmed"} else 50,
            "success" if status == "arrived" else "info",
            "appointments",
            "edit-appointment",
            appointment.get("id"),
            "Открыть запись",
            str(appointment.get("customer_name") or ""),
            str(appointment.get("customer_phone") or ""),
            appointment_vehicle,
            0,
            str(appointment.get("scheduled_at") or ""),
        )

    action_plan.sort(
        key=lambda item: (
            -parse_int(item.get("priority"), 0),
            str(item.get("due_at") or "9999-12-31T23:59"),
            str(item.get("title") or ""),
        )
    )
    action_plan_total = len(action_plan)
    action_plan = action_plan[:18]
    action_plan_by_tone: dict[str, int] = defaultdict(int)
    for item in action_plan:
        action_plan_by_tone[str(item.get("tone") or "info")] += 1

    revenue_by_day = defaultdict(float)
    import calendar

    days_in_month = calendar.monthrange(today.year, today.month)[1]
    for d in range(1, days_in_month + 1):
        day_key = f"{month_prefix}-{d:02d}"
        revenue_by_day[day_key] = 0.0

    # Заполнение ежедневной выручки с использованием parse_local_datetime
    for o in month_closed:
        closed_at = o.get("closed_at")
        dt = parse_local_datetime(closed_at)
        if dt:
            day_str = dt.date().isoformat()
            if day_str in revenue_by_day:
                revenue_by_day[day_str] += parse_float(o.get("total"))

    revenue_by_day_list = [
        {"date": date, "revenue": round(val, 2)}
        for date, val in sorted(revenue_by_day.items())
    ]

    orders_by_day_counts = [0] * 7
    for o in orders:
        if o.get("deleted_at"):
            continue
        created_at = o.get("created_at")
        dt = parse_local_datetime(created_at)
        if dt:
            orders_by_day_counts[dt.weekday()] += 1

    orders_by_day = [
        {"day": name, "count": count}
        for name, count in zip(["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"], orders_by_day_counts, strict=False)
    ]

    revenue_by_category = {"services": 0.0, "parts": 0.0}
    for o in orders:
        if o.get("status") != "closed" or o.get("deleted_at"):
            continue
        for item in o.get("items", []):
            if item_is_billable(item):
                qty = parse_float(item.get("quantity"))
                price = parse_float(item.get("unit_price"))
                kind = item.get("kind")
                if kind == "service":
                    revenue_by_category["services"] += qty * price
                elif kind == "part":
                    revenue_by_category["parts"] += qty * price

    revenue_by_category["services"] = round(revenue_by_category["services"], 2)
    revenue_by_category["parts"] = round(revenue_by_category["parts"], 2)

    return {
        "orders_by_day": orders_by_day,
        "revenue_by_category": revenue_by_category,
        "orders_total": len(orders),
        "active_orders": len(active_orders),
        "closed_orders_count": len(closed_orders),
        "customers_total": len(customers)
        if customers is not None
        else len(
            {parse_int(o.get("customer_id")) for o in orders if o.get("customer_id")}
        ),
        "vehicles_total": len(vehicles),
        "revenue_month": round(revenue_month, 2),
        "gross_margin_month": round(gross_margin_month, 2),
        "margin_percent_month": round(margin_percent_month, 1),
        "conversion_rate": round(conversion_rate, 1),
        "inventory_value": round(inventory_value, 2),
        "pipeline_value": round(pipeline_value, 2),
        "pipeline_due": round(pipeline_due, 2),
        "business_health_score": business_health_score,
        "business_health_label": business_health_label,
        "risk_total": risk_total,
        "due_total": round(due_total, 2),
        "avg_check": round(avg_check, 2),
        "low_stock_count": len(low_stock),
        "appointments_today_count": len(appointments_today),
        "appointments_upcoming_count": len(appointments_upcoming_all),
        "overdue_orders_count": len(overdue_orders),
        "crm_tasks_count": crm_tasks_count,
        "action_plan": action_plan,
        "action_plan_total": action_plan_total,
        "action_plan_by_tone": dict(action_plan_by_tone),
        "promised_today": promised_today[:8],
        "overdue_orders": [summarize_order(order) for order in overdue_orders[:8]],
        "appointments_today": appointments_today[:8],
        "appointments_upcoming": appointments_upcoming,
        "appointment_load_7_days": appointment_load_7_days,
        "low_stock": low_stock[:8],
        "procurement_plan": procurement_plan[:8],
        "service_reminders": service_reminders[:8],
        "followups_due": followups_due[:8],
        "authorizations_pending": authorizations_pending[:8],
        "deferred_work": deferred_work[:8],
        "vip_customers": vip_customers,
        "workload_by_responsible": workload_by_responsible,
        "pipeline_by_status": pipeline_by_status,
        "status_counts": status_counts,
        "top_services": top_services,
        "revenue_by_day": revenue_by_day_list,
    }
