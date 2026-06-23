"""Logics for rendering SVG charts, sparklines, and visual analytics."""

from __future__ import annotations

import html
import re

SAFE_COLOR_PATTERN = re.compile(
    r"^([a-zA-Z\-]+|var\(\-\-[a-zA-Z0-9\-]+\)|#[0-9a-fA-F]{3,8}|rgba?\([0-9\s,%.]+\))$"
)


def render_sparkline(
    values: list[float | int],
    aria_label: str = "",
    color: str = "var(--brand)",
) -> str:
    """Render dynamic vector (SVG) sparkline path safely with attribute protection."""
    # Validate color to prevent SVG attribute injection / XSS
    if not SAFE_COLOR_PATTERN.match(color):
        color = "var(--brand)"

    # Escape aria_label and color to block any quote breakout
    escaped_label = html.escape(aria_label, quote=True)
    escaped_color = html.escape(color, quote=True)

    width = 100
    height = 20
    padding = 2

    # Draw flat line if empty or single value
    if not values or len(values) < 2:
        path_data = f"M 0 {height // 2} L {width} {height // 2}"
    else:
        # Scale values to fit in the box
        min_v = float(min(values))
        max_v = float(max(values))
        range_v = max_v - min_v
        if range_v < 1e-9:
            range_v = 1.0

        points = []
        for i, val in enumerate(values):
            x = (i / (len(values) - 1)) * width
            y = height - padding - ((float(val) - min_v) / range_v) * (height - 2 * padding)
            points.append(f"{x:.1f},{y:.1f}")

        path_data = "M " + " L ".join(points)

    svg = (
        f'<svg class="sparkline" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'role="img" aria-label="{escaped_label}" preserveAspectRatio="none">'
        f'<path class="sparkline-path" d="{path_data}" fill="none" stroke="{escaped_color}" '
        f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"></path>'
        f'</svg>'
    )
    return svg
