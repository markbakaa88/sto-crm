import re

CSS_UPDATES = [
    # Remove duplicate brand title that we added earlier to keep it clean
    (r"\.brand-title \{ font-weight: 600; letter-spacing: 0.2px; color: var\(--sidebar-active\); \}",
     r".brand-title { font-weight: 800; letter-spacing: 0.2px; background: linear-gradient(135deg, var(--brand-end), var(--brand-strong)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }"),
    
    # Remove the appended brand-title block so we don't have duplicates
    (r"\.brand-title \{\s+background: linear-gradient[^{]+\}\s+", r"")
]

with open("/home/zxc/CRM/sto_crm/assets/app.css", "r", encoding="utf-8") as f:
    css = f.read()

for p, r in CSS_UPDATES:
    css = re.sub(p, r, css, flags=re.DOTALL)

with open("/home/zxc/CRM/sto_crm/assets/app.css", "w", encoding="utf-8") as f:
    f.write(css)

print("App CSS Cleaned up.")
