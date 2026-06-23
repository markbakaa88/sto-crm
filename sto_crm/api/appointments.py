"""Appointments API routing."""

from __future__ import annotations

from typing import Any

from ..runtime import parse_int_field
from ..services.appointments import (
    create_appointment,
    delete_appointment,
    update_appointment,
)
from .base import BaseAPIHandler


def handle_appointments(
    handler: BaseAPIHandler,
    method: str,
    path_parts: list[str],
    payload: dict[str, Any],
) -> bool:
    if len(path_parts) < 2 or path_parts[1] != "appointments":
        return False

    if method == "POST":
        if len(path_parts) != 2:
            handler.send_error_json(404, "Маршрут не найден.")
            return True
        record_id = 0
    elif method in {"PUT", "DELETE"}:
        if len(path_parts) != 3:
            handler.send_error_json(404, "Маршрут не найден.")
            return True
        record_id = parse_int_field(path_parts[2], "идентификатор записи")
    else:
        handler.send_error_json(405, "Метод не поддерживается.")
        return True

    handler.route_entity(
        method,
        record_id,
        payload,
        create_appointment,
        update_appointment,
        delete_appointment,
    )
    return True
