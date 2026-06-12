import re


def process_file(path, pattern, replacement):
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    new_content = re.sub(pattern, replacement, content, flags=re.DOTALL)
    if new_content != content:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
        print(f"Updated {path}")
    else:
        print(f"No changes in {path}")


# app.css changes
CSS_UPDATES = [
    # Enhance KPI grid cards
    (
        r"\.metric \{ transition:([^;]+);([^}]+)\}",
        r".metric { transition: \1;\2 border-radius: var(--radius-lg); box-shadow: var(--shadow-sm); }\n.metric:hover { transform: translateY(-2px); box-shadow: var(--shadow-md); border-color: var(--brand-mid); }",
    ),
    # Improve table styles for better readability
    (
        r"\.table \{ width: 100%; border-collapse: separate; border-spacing: 0; \}",
        r".table { width: 100%; border-collapse: separate; border-spacing: 0; background: var(--surface); border-radius: var(--radius-md); overflow: hidden; box-shadow: var(--shadow-sm); }",
    ),
    (
        r"\.table th, \.table td \{ padding: var\(--space-3\) var\(--space-4\);",
        r".table th, .table td { padding: var(--space-4) var(--space-5);",
    ),
    # Better buttons
    (
        r"\.btn \{([^}]+)\}",
        r".btn {\1 border-radius: var(--radius-md); font-weight: 500; letter-spacing: 0.2px; transition: all var(--dur-fast) ease-in-out; }",
    ),
]

# Apply CSS updates
for p, r in CSS_UPDATES:
    process_file("/home/zxc/CRM/sto_crm/assets/app.css", p, r)

print("Done")
