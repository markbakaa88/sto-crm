import re

with open("/home/zxc/CRM/sto_crm/assets/app.js", "r", encoding="utf-8") as f:
    js = f.read()

# Enhance notifications logic for better visual cue inside toaster
toast_mod = """function toast(message, type = "info") {
    const isError = type === "error";
    const node = $("#toast");
    if (!node) {
        announce(message, isError);
        return;
    }
    // Professional icon injection based on type
    const icon = isError ? "⚠️ " : "✅ ";
    node.innerHTML = `<strong>${icon}</strong> <span>${esc(message)}</span>`;
    node.classList.toggle("error", isError);
    node.setAttribute("aria-live", isError ? "assertive" : "polite");
    node.setAttribute("aria-atomic", "true");
    node.classList.add("show");
    
    // Provide tactile animation reset
    node.style.animation = 'none';
    node.offsetHeight; /* trigger reflow */
    node.style.animation = null;
    
    announce(message, isError);
    clearTimeout(node.timer);
    node.timer = setTimeout(() => {
        node.classList.remove("show");
        node.innerHTML = "";
    }, isError ? 6000 : 3500);
}"""

js = re.sub(
    r"function toast\(message, type = \"info\"\).*?\}, isError \? 5200 \: 3200\);\n\}",
    toast_mod,
    js,
    flags=re.DOTALL
)

with open("/home/zxc/CRM/sto_crm/assets/app.js", "w", encoding="utf-8") as f:
    f.write(js)

with open("/home/zxc/CRM/sto_crm/assets/app.css", "r", encoding="utf-8") as f:
    css = f.read()

css = re.sub(
    r"\.toast \{([^}]+)\}",
    r".toast {\1 display: flex; align-items: center; gap: 8px; font-weight: 500; font-size: var(--font-size-sm); border-radius: var(--radius-md); box-shadow: var(--shadow-lg), 0 0 0 1px inset rgba(255,255,255,0.1); padding: 12px 18px; }",
    css
)

with open("/home/zxc/CRM/sto_crm/assets/app.css", "w", encoding="utf-8") as f:
    f.write(css)

print("Toaster enhanced")
