"""Public facade for files reporting subsystems."""

from __future__ import annotations

from .charts import render_sparkline
from .data import build_reports, format_vehicle_text, order_vehicle_text

__all__ = [
    "build_reports",
    "format_vehicle_text",
    "order_vehicle_text",
    "render_sparkline",
]
