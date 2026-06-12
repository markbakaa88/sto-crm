import re

with open("/home/zxc/CRM/sto_crm/assets/app.css", "r", encoding="utf-8") as f:
    css = f.read()

# Add a sweet loading animation for the table and panels
css += """
@keyframes highlight-pulse {
    0% { background-color: var(--brand-soft); }
    100% { background-color: transparent; }
}

.table tbody tr {
    transition: background-color var(--dur-fast) ease, transform var(--dur-fast) ease;
}

.table tbody tr:hover {
    background-color: var(--surface-subtle);
    transform: scale(1.002);
}

.nav-section button {
    transition: background-color var(--dur-fast) ease, padding-left var(--dur-fast) ease, font-weight 0.2s;
}

.nav-section button.active {
    font-weight: 600;
}

/* Modern inputs floating label (if adapted later, base rules) */
.form-group input, .form-group select {
    box-shadow: 0 1px 2px rgba(0,0,0,0.02) inset;
}

"""

with open("/home/zxc/CRM/sto_crm/assets/app.css", "w", encoding="utf-8") as f:
    f.write(css)

print("UI 3 Extra CSS added.")
