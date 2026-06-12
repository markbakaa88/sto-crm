import re

with open("/home/zxc/CRM/sto_crm/assets/app.js", "r", encoding="utf-8") as f:
    js = f.read()

# Implement optimized debouncing for search
debounce_code = """
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}
"""

if "function debounce" not in js:
    js = re.sub(
        r'const state = \{',
        debounce_code + '\nconst state = {',
        js
    )

# Fix search handler to use 450ms for better DB load
# We already run timeout in app.js, let's just increase it.
js = js.replace('state.searchTimer = setTimeout(() => loadData().catch(showError), 260);', 'state.searchTimer = setTimeout(() => loadData().catch(showError), 450);')

with open("/home/zxc/CRM/sto_crm/assets/app.js", "w", encoding="utf-8") as f:
    f.write(js)

print("Debounce timing optimized")
