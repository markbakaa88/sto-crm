import re

with open("/home/zxc/CRM/sto_crm/assets/app.js", "r", encoding="utf-8") as f:
    js = f.read()

# Orders table was overridden incorrectly, let's fix it properly utilizing our new style from previous steps. 
# Seems one old chunk was appended instead of replaced.

orders_table_replacement = """function ordersTable(orders, compact) {
    if (!orders.length) return emptyState("Заказ-нарядов не найдено", "Создайте первый заказ или измените поиск.", `<button class="btn primary" type="button" data-action="new-order">Новый заказ</button>`);
    
    if (compact) {
        return `<div class="table-wrap responsive-table-wrap">
            <table class="compact-table responsive-table modern-hover" aria-label="Таблица последних заказ-нарядов">
                <thead>${tableHead(["Номер", "Клиент и авто", "Статус", {text: "Итого", className: "money"}, ""])}</thead>
                <tbody>
                    ${orders.map(order => `
                        <tr>
                            <td data-label="Номер"><div class="cell-title"><strong>${esc(order.number)}</strong><span class="priority-dot" data-priority="${esc(order.priority)}">${esc(priorityLabels[order.priority] || order.priority)}</span></div></td>
                            <td data-label="Клиент и авто"><div class="cell-title"><strong>${esc(order.customer_name)}</strong><div class="muted">${esc(orderVehicle(order) || "Авто не выбрано")}</div></div></td>
                            <td data-label="Статус">${statusBadge(order.status)}</td>
                            <td class="money" data-label="Итого"><strong>${money(order.total)}</strong></td>
                            <td data-label="Действия">${orderRowActions(order)}</td>
                        </tr>
                    `).join("")}
                </tbody>
            </table>
        </div>`;
    }
    return `<div class="table-wrap responsive-table-wrap">
        <table class="responsive-table modern-hover" aria-label="Таблица заказ-нарядов">
            <thead>${tableHead(["Номер", "Клиент и авто", "Статус", "Срок", "Мастер", {text: "Итого", className: "money"}, {text: "К оплате", className: "money"}, ""])}</thead>
            <tbody>
                ${orders.map(order => `
                    <tr>
                        <td data-label="Номер"><div class="cell-title"><strong>${esc(order.number)}</strong><span class="priority-dot" data-priority="${esc(order.priority)}">${esc(priorityLabels[order.priority] || order.priority)}</span></div></td>
                        <td data-label="Клиент и авто"><div class="cell-title"><strong>${esc(order.customer_name)}</strong><div class="muted d-flex"><span aria-hidden="true" style="margin-right:4px;">🚗</span> ${esc(orderVehicle(order) || "Авто не выбрано")}</div></div></td>
                        <td data-label="Статус">${statusBadge(order.status)}</td>
                        <td class="nowrap" data-label="Срок"><strong>${dateOrDash(order.promised_at)}</strong></td>
                        <td data-label="Мастер"><div class="cell-title"><strong>${textOrDash(order.mechanic || order.advisor, "Не назначен")}</strong><div class="muted" style="font-size:0.85em;">Исполнитель</div></div></td>
                        <td class="money" data-label="Итого"><strong style="font-size: 1.1em;">${money(order.total)}</strong></td>
                        <td class="money" data-label="К оплате">
                            <span class="${order.due > 0 ? 'status-badge danger' : 'status-badge success'}" style="font-size:0.9em;">
                                ${order.due > 0 ? money(order.due) : 'Оплачен'}
                            </span>
                        </td>
                        <td data-label="Действия">${orderRowActions(order)}</td>
                    </tr>
                `).join("")}
            </tbody>
        </table>
    </div>`;
}"""

js = re.sub(
    r"function ordersTable\(orders, compact\) \{.+?\}\s+function renderCustomers",
    orders_table_replacement + "\n\nfunction renderCustomers",
    js,
    flags=re.DOTALL
)

with open("/home/zxc/CRM/sto_crm/assets/app.js", "w", encoding="utf-8") as f:
    f.write(js)

with open("/home/zxc/CRM/sto_crm/assets/app.css", "a", encoding="utf-8") as f:
    f.write("\n.status-badge.danger { background: var(--danger-soft); color: var(--danger); font-weight: 700; }\n")
    f.write(".status-badge.success { background: var(--ok-soft); color: var(--ok); font-weight: 700; }\n")

print("Orders table fully polished")
