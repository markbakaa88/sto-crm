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
        print(f"No match for {pattern}")

JS_UPDATES = [
    # Enhance the health metrics / UI components
    (r"`<div class=\"hero-eyebrow\">[^<]+</div>`", r'`<div class="hero-eyebrow" style="opacity:0.8; font-weight:600; text-transform:uppercase;">${esc(options.eyebrow)}</div>`'),
]

for p, r in JS_UPDATES:
    process_file("/home/zxc/CRM/sto_crm/assets/app.js", p, r)

print("JS processed.")
