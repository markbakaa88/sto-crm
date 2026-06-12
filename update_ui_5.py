import re

with open("/home/zxc/CRM/sto_crm/assets/index.html", "r", encoding="utf-8") as f:
    html = f.read()

# Make breadcrumbs nicer
html = html.replace('<nav class="breadcrumbs"', '<nav class="breadcrumbs" style="background: var(--surface-subtle); padding: var(--space-2) var(--space-4); border-radius: var(--radius-md); box-shadow: var(--shadow-sm); margin: var(--space-3);"')

with open("/home/zxc/CRM/sto_crm/assets/index.html", "w", encoding="utf-8") as f:
    f.write(html)
