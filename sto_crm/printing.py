from __future__ import annotations

"""Professional printable order document rendering."""

import html
from datetime import datetime
from typing import Any

from .config import ITEM_APPROVAL_STATUSES, ORDER_STATUSES
from .runtime import money, parse_float, parse_int
from .validation import item_is_billable

def print_order_html(order: dict[str, Any]) -> str:
    vehicle = " ".join(
        str(part)
        for part in [order.get("vehicle_make"), order.get("vehicle_model"), order.get("vehicle_year"), order.get("vehicle_plate")]
        if part
    )
    status_label = ORDER_STATUSES.get(str(order.get("status") or ""), str(order.get("status") or ""))
    printed_at = datetime.now().strftime("%d.%m.%Y %H:%M")
    rows = []
    for index, item in enumerate(order.get("items", []), start=1):
        total = parse_float(item.get("quantity")) * parse_float(item.get("unit_price")) if item_is_billable(item) else 0
        approval_key = str(item.get("approval_status") or "approved")
        approval_label = ITEM_APPROVAL_STATUSES.get(approval_key, approval_key)
        approval_class = "approved" if approval_key == "approved" else "deferred" if approval_key == "deferred" else "declined" if approval_key == "declined" else "neutral"
        rows.append(
            f"""
            <tr>
                <td class="row-index">{index}</td>
                <td><strong>{html.escape(str(item.get('title') or ''))}</strong></td>
                <td>{'Работа' if item.get('kind') == 'service' else 'Запчасть'}</td>
                <td><span class="line-badge {approval_class}">{html.escape(approval_label)}</span></td>
                <td class="num">{parse_float(item.get('quantity')):g}</td>
                <td class="num">{money(item.get('unit_price'))}</td>
                <td class="num total-cell">{money(total)}</td>
            </tr>
            """
        )
    rows_html = "".join(rows) or "<tr><td colspan=\"7\" class=\"empty-row\">В заказ-наряде нет позиций.</td></tr>"
    return f"""<!doctype html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{html.escape(str(order.get("number")))} · заказ-наряд</title>
    <style>
        :root {{
            --ink: #0f172a;
            --muted: #64748b;
            --line: #dbe3ee;
            --line-strong: #cbd5e1;
            --surface: #ffffff;
            --surface-soft: #f8fafc;
            --accent: #0f766e;
            --accent-soft: #ccfbf1;
            --blue: #1d4ed8;
            --green: #047857;
            --amber: #b45309;
            --red: #b91c1c;
            --shadow: 0 24px 70px rgba(15,23,42,.14);
            color-scheme: light;
            font-family: 'Segoe UI', system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
        }}
        * {{ box-sizing: border-box; }}
        body {{
            margin: 0;
            background:
                radial-gradient(circle at 8% -10%, rgba(15,118,110,.16), transparent 34vw),
                linear-gradient(135deg, #eef4fb, #f8fafc 46%, #eef7ff);
            color: var(--ink);
            font-size: 13px;
            line-height: 1.5;
            -webkit-print-color-adjust: exact;
            print-color-adjust: exact;
        }}
        .print-toolbar {{
            position: sticky;
            top: 0;
            z-index: 3;
            display: flex;
            justify-content: flex-end;
            gap: 10px;
            padding: 14px clamp(14px, 3vw, 32px);
            background: rgba(255,255,255,.78);
            border-bottom: 1px solid rgba(203,213,225,.8);
            backdrop-filter: blur(14px);
        }}
        .print-button {{
            min-height: 40px;
            padding: 0 16px;
            border: 0;
            border-radius: 999px;
            background: linear-gradient(135deg, var(--accent), #14b8a6);
            color: #fff;
            font: inherit;
            font-weight: 800;
            cursor: pointer;
            box-shadow: 0 12px 30px rgba(15,118,110,.22);
        }}
        .document {{
            width: min(1080px, calc(100% - 32px));
            margin: 24px auto;
            padding: clamp(22px, 4vw, 42px);
            background: var(--surface);
            border: 1px solid rgba(203,213,225,.82);
            border-radius: 28px;
            box-shadow: var(--shadow);
        }}
        .doc-hero {{
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            gap: 24px;
            align-items: start;
            padding-bottom: 22px;
            border-bottom: 2px solid var(--ink);
        }}
        .brand-lockup {{ display: flex; align-items: center; gap: 14px; min-width: 0; }}
        .brand-mark {{
            width: 54px;
            height: 54px;
            border-radius: 18px;
            display: grid;
            place-items: center;
            background: linear-gradient(135deg, #0f172a, var(--accent));
            color: #fff;
            font-weight: 950;
            letter-spacing: -.05em;
            box-shadow: 0 18px 40px rgba(15,118,110,.24);
        }}
        h1 {{ margin: 0; font-size: clamp(25px, 4vw, 38px); line-height: 1; letter-spacing: -.06em; }}
        .eyebrow {{ color: var(--accent); font-weight: 900; text-transform: uppercase; letter-spacing: .08em; font-size: 11px; }}
        .muted {{ color: var(--muted); }}
        .doc-meta {{ display: grid; justify-items: end; gap: 8px; min-width: 220px; text-align: right; }}
        .status-chip {{
            display: inline-flex;
            align-items: center;
            min-height: 30px;
            padding: 0 12px;
            border-radius: 999px;
            background: var(--accent-soft);
            color: var(--accent);
            font-weight: 850;
        }}
        .summary-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin: 22px 0; }}
        .box {{
            min-width: 0;
            border: 1px solid var(--line);
            border-radius: 18px;
            padding: 16px;
            background: linear-gradient(180deg, #fff, var(--surface-soft));
        }}
        .box-title {{ display: block; margin-bottom: 8px; color: var(--muted); font-size: 11px; font-weight: 900; text-transform: uppercase; letter-spacing: .08em; }}
        .notes-grid {{ display: grid; gap: 12px; margin: 18px 0; }}
        .table-scroll {{ width:100%; overflow-x:auto; -webkit-overflow-scrolling:touch; border: 1px solid var(--line); border-radius: 18px; }}
        table {{ width:100%; border-collapse:collapse; min-width:760px; }}
        th, td {{ border-bottom:1px solid var(--line); padding:11px 12px; text-align:left; vertical-align: top; }}
        tr:last-child td {{ border-bottom: 0; }}
        th {{ background:#f1f5f9; color: #475569; font-size: 10px; text-transform: uppercase; letter-spacing: .06em; }}
        .row-index {{ width: 46px; color: var(--muted); font-weight: 800; }}
        .num {{ text-align:right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
        .total-cell {{ font-weight: 850; }}
        .line-badge {{ display: inline-flex; min-height: 24px; align-items: center; padding: 0 9px; border-radius: 999px; font-size: 11px; font-weight: 850; }}
        .line-badge.approved {{ background:#dcfce7; color: var(--green); }}
        .line-badge.deferred {{ background:#fef3c7; color: var(--amber); }}
        .line-badge.declined {{ background:#fee2e2; color: var(--red); }}
        .line-badge.neutral {{ background:#e2e8f0; color: #475569; }}
        .empty-row {{ text-align:center; color: var(--muted); padding: 24px; }}
        .totals {{
            margin: 18px 0 0 auto;
            width: min(380px, 100%);
            display: grid;
            gap: 0;
            overflow: hidden;
            border: 1px solid var(--line);
            border-radius: 18px;
            background: #fff;
        }}
        .totals div {{ display:flex; justify-content:space-between; gap:12px; padding:10px 14px; border-bottom: 1px solid var(--line); }}
        .totals div:last-child {{ border-bottom: 0; }}
        .totals .grand {{ background: #0f172a; color: #fff; font-size: 16px; font-weight: 900; }}
        .sign {{ display:grid; grid-template-columns:1fr 1fr; gap:40px; margin-top:58px; }}
        .line {{ border-top:1.5px solid var(--ink); padding-top:8px; color: var(--muted); }}
        @page {{ margin: 12mm; }}
        @media print {{
            body {{ background: #fff; font-size: 11px; }}
            .print-toolbar {{ display:none; }}
            .document {{ width: 100%; margin: 0; padding: 0; border: 0; border-radius: 0; box-shadow: none; }}
            .table-scroll {{ overflow: visible; }}
            table {{ min-width: 0; }}
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
                Пробег: {parse_int(order.get("odometer"))} км
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
    <script>document.getElementById("printButton").addEventListener("click", () => window.print());</script>
</body>
</html>"""
