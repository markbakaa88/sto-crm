import re

with open("/home/zxc/CRM/sto_crm/assets/app.js", "r", encoding="utf-8") as f:
    js = f.read()

# Enhance order status rendering
js = re.sub(
    r'\<span class="\$\{esc\(statusConfig\.className\)\}">\$\{esc\(statusConfig\.label\)\}<\/span>',
    r'<span class="${esc(statusConfig.className)}" style="box-shadow: inset 0 0 0 1px rgba(0,0,0,0.1); font-weight:700;">${esc(statusConfig.label)}</span>',
    js
)

with open("/home/zxc/CRM/sto_crm/assets/app.js", "w", encoding="utf-8") as f:
    f.write(js)

with open("/home/zxc/CRM/sto_crm/assets/app.css", "r", encoding="utf-8") as f:
    css = f.read()

# Enhance tooltip shadows and animations to be more solid
css = re.sub(
    r"\.command-palette \{([^}]+)\}",
    r".command-palette {\1 box-shadow: var(--shadow-lg), 0 0 0 1px var(--line-subtle); border-radius: var(--radius-xl); backdrop-filter: blur(20px); background: rgba(255,255,255,0.95); }",
    css
)

css = css.replace('html[data-initial-theme="dark"] .command-palette { background: var(--surface); }',
                  'html[data-initial-theme="dark"] .command-palette { background: rgba(15,23,42,0.95); }')

with open("/home/zxc/CRM/sto_crm/assets/app.css", "w", encoding="utf-8") as f:
    f.write(css)

print("Command Palette and statuses upgraded")
