import re

with open("/home/zxc/CRM/sto_crm/assets/index.html", "r", encoding="utf-8") as f:
    html = f.read()

# Make search and nav cleaner
html = html.replace(
    '<button type="button" class="btn ghost system-menu-button"',
    '<button type="button" class="btn ghost system-menu-button" style="border-radius:var(--radius-xl);"'
)
html = html.replace('<header class="topbar">', '<header class="topbar sticky">')

with open("/home/zxc/CRM/sto_crm/assets/index.html", "w", encoding="utf-8") as f:
    f.write(html)

with open("/home/zxc/CRM/sto_crm/assets/app.css", "r", encoding="utf-8") as f:
    css = f.read()

# Sticky topbar CSS
css += """
.topbar.sticky {
    position: sticky;
    top: 0;
    z-index: var(--z-topbar);
}
"""

with open("/home/zxc/CRM/sto_crm/assets/app.css", "w", encoding="utf-8") as f:
    f.write(css)

print("Navbar UI updated")
