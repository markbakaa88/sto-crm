"""Professional printable order document rendering."""

from __future__ import annotations

import html
from datetime import datetime
from typing import Any

from .config import ITEM_APPROVAL_STATUSES, ORDER_STATUSES
from .runtime import money, parse_float, parse_int
from .validation import item_is_billable


def _format_quantity(value: Any) -> str:
    """Форматирует количество без экспоненты и с русской десятичной запятой."""
    amount = parse_float(value)
    # Не используем ':g' — для больших/малых значений он даёт экспоненту.
    text = f"{amount:.4f}".rstrip("0").rstrip(".")
    if not text or text == "-":
        text = "0"
    return text.replace(".", ",")


def print_order_html(order: dict[str, Any]) -> str:
    vehicle = " ".join(
        str(part)
        for part in [
            order.get("vehicle_make"),
            order.get("vehicle_model"),
            order.get("vehicle_year"),
            order.get("vehicle_plate"),
        ]
        if part
    )
    status_label = ORDER_STATUSES.get(
        str(order.get("status") or ""), str(order.get("status") or "")
    )
    printed_at = datetime.now().strftime("%d.%m.%Y %H:%M")
    odometer = parse_int(order.get("odometer"))
    odometer_text = f"{odometer} км" if odometer > 0 else "—"
    rows = []
    for index, item in enumerate(order.get("items", []), start=1):
        total = (
            parse_float(item.get("quantity")) * parse_float(item.get("unit_price"))
            if item_is_billable(item)
            else 0
        )
        approval_key = str(item.get("approval_status") or "approved")
        approval_label = ITEM_APPROVAL_STATUSES.get(approval_key, approval_key)
        approval_class = (
            "approved"
            if approval_key == "approved"
            else "deferred"
            if approval_key == "deferred"
            else "declined"
            if approval_key == "declined"
            else "neutral"
        )
        rows.append(
            f"""
            <tr>
                <td class="row-index">{index}</td>
                <td><strong>{html.escape(str(item.get("title") or ""))}</strong></td>
                <td>{"Работа" if item.get("kind") == "service" else "Запчасть"}</td>
                <td><span class="line-badge {approval_class}">{html.escape(approval_label)}</span></td>
                <td class="num">{_format_quantity(item.get("quantity"))}</td>
                <td class="num">{money(item.get("unit_price"))}</td>
                <td class="num total-cell">{money(total)}</td>
            </tr>
            """
        )
    rows_html = (
        "".join(rows)
        or '<tr><td colspan="7" class="empty-row">В заказ-наряде нет позиций.</td></tr>'
    )
    return f"""<!doctype html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'nonce-__STO_CRM_CSP_NONCE__'; script-src 'nonce-__STO_CRM_CSP_NONCE__'; img-src data:; base-uri 'none'; form-action 'none'">
    <title>{html.escape(str(order.get("number")))} · заказ-наряд</title>
    <style nonce="__STO_CRM_CSP_NONCE__">
        :root {{
            --ink: #101828;
            --muted: #667085;
            --line: #d8dee8;
            --line-strong: #b9c3d0;
            --surface: #ffffff;
            --surface-soft: #f8fafc;
            --accent: #0f766e;
            --accent-soft: #e5f3f1;
            --green: #17633b;
            --amber: #725116;
            --red: #8f2b22;
            --shadow: none;
            color-scheme: light;
            font-family: 'Segoe UI', system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
        }}
        * {{ box-sizing: border-box; }}
        body {{
            margin: 0;
            background: #f5f7fa;
            color: var(--ink);
            font-size: 12px;
            line-height: 1.42;
            -webkit-print-color-adjust: exact;
            print-color-adjust: exact;
        }}
        .print-toolbar {{
            position: sticky;
            top: 0;
            z-index: 3;
            display: flex;
            justify-content: flex-end;
            gap: 8px;
            padding: 10px clamp(12px, 3vw, 24px);
            background: #fff;
            border-bottom: 1px solid var(--line);
        }}
        .print-button {{
            min-height: 34px;
            padding: 0 12px;
            border: 0;
            border-radius: 6px;
            background: var(--accent);
            color: #fff;
            font: inherit;
            font-weight: 700;
            cursor: pointer;
            box-shadow: none;
        }}
        .document {{
            width: min(1040px, calc(100% - 24px));
            margin: 16px auto;
            padding: clamp(18px, 3vw, 30px);
            background: var(--surface);
            border: 1px solid var(--line);
            border-radius: 10px;
            box-shadow: var(--shadow);
        }}
        .doc-hero {{
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            gap: 18px;
            align-items: start;
            padding-bottom: 16px;
            border-bottom: 2px solid var(--ink);
        }}
        .brand-lockup {{ display: flex; align-items: center; gap: 10px; min-width: 0; }}
        .brand-mark {{
            width: 40px;
            height: 40px;
            border-radius: 8px;
            display: grid;
            place-items: center;
            background: var(--accent);
            color: #fff;
            font-weight: 800;
            letter-spacing: 0;
            box-shadow: none;
        }}
        h1 {{ margin: 0; font-size: clamp(22px, 3vw, 30px); line-height: 1.05; letter-spacing: 0; }}
        .eyebrow {{ color: var(--accent); font-weight: 800; text-transform: uppercase; letter-spacing: .05em; font-size: 10px; }}
        .muted {{ color: var(--muted); }}
        .doc-meta {{ display: grid; justify-items: end; gap: 6px; min-width: 200px; text-align: right; }}
        .status-chip {{
            display: inline-flex;
            align-items: center;
            min-height: 26px;
            padding: 0 10px;
            border-radius: 6px;
            background: var(--accent-soft);
            color: var(--accent);
            font-weight: 700;
        }}
        .summary-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 16px 0; }}
        .box {{
            min-width: 0;
            border: 1px solid var(--line);
            border-radius: 8px;
            padding: 12px;
            background: var(--surface);
        }}
        .box-title {{ display: block; margin-bottom: 6px; color: var(--muted); font-size: 10px; font-weight: 800; text-transform: uppercase; letter-spacing: .05em; }}
        .notes-grid {{ display: grid; gap: 10px; margin: 14px 0; }}
        .table-scroll {{ width:100%; overflow-x:auto; -webkit-overflow-scrolling:touch; border: 1px solid var(--line); border-radius: 8px; }}
        table {{ width:100%; border-collapse:collapse; min-width:720px; }}
        th, td {{ border-bottom:1px solid var(--line); padding:8px 10px; text-align:left; vertical-align: top; }}
        tr:last-child td {{ border-bottom: 0; }}
        th {{ background:var(--surface-soft); color: #475467; font-size: 10px; text-transform: uppercase; letter-spacing: .04em; }}
        .row-index {{ width: 40px; color: var(--muted); font-weight: 700; }}
        .num {{ text-align:right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
        .total-cell {{ font-weight: 800; }}
        .line-badge {{ display: inline-flex; min-height: 22px; align-items: center; padding: 0 8px; border-radius: 6px; font-size: 10px; font-weight: 700; }}
        .line-badge.approved {{ background:#e8f3ed; color: var(--green); }}
        .line-badge.deferred {{ background:#f7efe1; color: var(--amber); }}
        .line-badge.declined {{ background:#f8e7e5; color: var(--red); }}
        .line-badge.neutral {{ background:#eef2f7; color: #475467; }}
        .empty-row {{ text-align:center; color: var(--muted); padding: 18px; }}
        .totals {{
            margin: 14px 0 0 auto;
            width: min(340px, 100%);
            display: grid;
            gap: 0;
            overflow: hidden;
            border: 1px solid var(--line);
            border-radius: 8px;
            background: #fff;
        }}
        .totals div {{ display:flex; justify-content:space-between; gap:10px; padding:8px 12px; border-bottom: 1px solid var(--line); }}
        .totals div:last-child {{ border-bottom: 0; }}
        .totals .grand {{ background: #101828; color: #fff; font-size: 14px; font-weight: 800; }}
        .sign {{ display:grid; grid-template-columns:1fr 1fr; gap:32px; margin-top:44px; }}
        .line {{ border-top:1.5px solid var(--ink); padding-top:7px; color: var(--muted); }}
        @page {{ margin: 12mm; }}
        @media print {{
            body {{ background: #fff; font-size: 11px; }}
            .print-toolbar {{ display:none; }}
            .document {{ width: 100%; margin: 0; padding: 0; border: 0; border-radius: 0; box-shadow: none; }}
            .table-scroll {{ overflow: visible; }}
            table {{ min-width: 0; }}
            th, td {{ padding: 6px 8px; }}
            .summary-grid, .notes-grid {{ gap: 8px; margin: 10px 0; }}
            .box {{ break-inside: avoid; }}
            .totals, .sign {{ break-inside: avoid; }}
        }}
        @media (max-width: 720px) {{
            .document {{ width: min(100% - 20px, 1080px); margin: 10px auto; border-radius: 18px; }}
            .doc-hero, .summary-grid, .sign {{ grid-template-columns: 1fr; }}
            .doc-meta {{ justify-items: start; text-align: left; min-width: 0; }}
            table {{ font-size: 12px; }}
        }}
    </style>
</head>
<body>
    <div class="print-toolbar"><button type="button" class="print-button" id="printButton" aria-label="Печать заказ-наряда">⎙ Печать</button></div>
    <noscript>Для кнопки печати включите JavaScript или используйте Ctrl+P.</noscript>
    <main class="document" aria-label="Печатная форма заказ-наряда">
        <header class="doc-hero">
            <div class="brand-lockup">
                <div class="brand-mark" aria-hidden="true">CRM</div>
                <div>
                    <div class="eyebrow">СТО CRM · заказ-наряд</div>
                    <h1>{html.escape(str(order.get("number") or ""))}</h1>
                    <div class="muted">Сформировано: {printed_at}</div>
                </div>
            </div>
            <div class="doc-meta">
                <span class="status-chip">{html.escape(status_label)}</span>
                <div><strong>Мастер:</strong> {html.escape(str(order.get("mechanic") or order.get("advisor") or "—"))}</div>
                <div><strong>Согласовал:</strong> {html.escape(str(order.get("authorized_by") or "—"))}</div>
            </div>
        </header>
        <section class="summary-grid" aria-label="Клиент и автомобиль">
            <div class="box">
                <span class="box-title">Клиент</span>
                <strong>{html.escape(str(order.get("customer_name") or ""))}</strong><br>
                {html.escape(str(order.get("customer_phone") or ""))}<br>
                {html.escape(str(order.get("customer_email") or ""))}
            </div>
            <div class="box">
                <span class="box-title">Автомобиль</span>
                <strong>{html.escape(vehicle or "Автомобиль не выбран")}</strong><br>
                VIN: {html.escape(str(order.get("vehicle_vin") or "—"))}<br>
                Пробег: {html.escape(odometer_text)}
            </div>
        </section>
        <section class="notes-grid" aria-label="Описание работ">
            <div class="box"><span class="box-title">Жалоба клиента</span>{html.escape(str(order.get("complaint") or "—"))}</div>
            <div class="box"><span class="box-title">Диагностика</span>{html.escape(str(order.get("diagnosis") or "—"))}</div>
            <div class="box"><span class="box-title">Рекомендации</span>{html.escape(str(order.get("recommendations") or "—"))}</div>
        </section>
        <div class="table-scroll" role="region" aria-label="Позиции заказ-наряда" tabindex="0">
            <table>
                <thead><tr><th scope="col">№</th><th scope="col">Наименование</th><th scope="col">Тип</th><th scope="col">Согласование</th><th scope="col">Кол-во</th><th scope="col">Цена</th><th scope="col">Сумма</th></tr></thead>
                <tbody>{rows_html}</tbody>
            </table>
        </div>
        <section class="totals" aria-label="Итоги заказ-наряда">
            <div><span>Работы</span><strong>{money(order.get("service_total"))}</strong></div>
            <div><span>Запчасти</span><strong>{money(order.get("parts_total"))}</strong></div>
            <div><span>Скидка</span><strong>{money(order.get("discount"))}</strong></div>
            <div><span>Налог</span><strong>{money(order.get("tax"))}</strong></div>
            <div><span>Итого</span><strong>{money(order.get("total"))}</strong></div>
            <div><span>Оплачено</span><strong>{money(order.get("paid"))}</strong></div>
            <div class="grand"><span>К оплате</span><strong>{money(order.get("due"))}</strong></div>
        </section>
        <section class="sign" aria-label="Подписи сторон">
            <div class="line">Представитель сервиса</div>
            <div class="line">Клиент</div>
        </section>
    </main>
    <script nonce="__STO_CRM_CSP_NONCE__">document.getElementById("printButton").addEventListener("click", () => window.print());</script>
</body>
</html>"""
