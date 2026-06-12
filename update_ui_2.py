import re

def process_file(path, pattern, replacement):
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    new_content = re.sub(pattern, replacement, content, flags=re.DOTALL)
    if new_content != content:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
        print(f"Updated {path}")

CSS_UPDATES = [
    # Topbar modern styling
    (r"\.topbar \{([^}]+)border-bottom: 1px solid var\(--line\);([^}]+)\}",
     r".topbar {\1border-bottom: 1px solid var(--line); box-shadow: 0 4px 20px -8px rgba(0,0,0,0.08);\2}"),
    
    # Smooth inputs
    (r"input:not\(\.items-table input\), select:not\(\.items-table select\), textarea \{([^}]+)\}",
     r"input:not(.items-table input), select:not(.items-table select), textarea {\1 border-radius: var(--radius-md); transition: all 0.2s ease; }\ninput:not(.items-table input):focus, select:not(.items-table select):focus, textarea:focus { box-shadow: 0 0 0 3px var(--brand-soft); border-color: var(--brand); transform: translateY(-1px); }"),
     
    # Glassmorphism on sidebar
    (r"\.sidebar \{([^}]+)\}",
     r".sidebar {\1 background: rgba(15, 23, 42, 0.98); backdrop-filter: blur(16px); }"),
]

for p, r in CSS_UPDATES:
    process_file("/home/zxc/CRM/sto_crm/assets/app.css", p, r)

print("UI 2 Done")
