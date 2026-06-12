import re

with open("/home/zxc/CRM/sto_crm/assets/app.css", "r", encoding="utf-8") as f:
    css = f.read()

# Enhance brand colors to be more distinct and modern
colors = [
    (r"--brand-start: #0f766e;", r"--brand-start: #005f73;"),
    (r"--brand-mid: #0f6f86;", r"--brand-mid: #0a9396;"),
    (r"--brand-end: #1f4f7a;", r"--brand-end: #94d2bd;"),
    (r"--brand: #0f766e;", r"--brand: #0a9396;"),
    (r"--brand-strong: #115e59;", r"--brand-strong: #005f73;"),
    (r"--brand-soft: #e7f5f3;", r"--brand-soft: #e9f5f5;"),
    # Update radius for smoother edges
    (r"--radius-md: 10px;", r"--radius-md: 12px;"),
    (r"--radius-lg: 14px;", r"--radius-lg: 16px;"),
    # Add backdrop filter variables
    (r"--overlay-backdrop: rgba\(15, 23, 42, 0.55\);", r"--overlay-backdrop: rgba(15, 23, 42, 0.65);\n    --backdrop-blur: blur(8px);"),
]

for p, r_val in colors:
    css = re.sub(p, r_val, css)

# Make topbar and sidebar blur
css = re.sub(r"(\.topbar\s*\{[^}]+)background:", r"\1 backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px); background:", css)

with open("/home/zxc/CRM/sto_crm/assets/app.css", "w", encoding="utf-8") as f:
    f.write(css)

print("Vars updated")
