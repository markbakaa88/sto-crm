import re

with open("/home/zxc/CRM/sto_crm/assets/app.js", "r", encoding="utf-8") as f:
    js = f.read()

# Enhance sync chip feedback
sync_replacement = """function updateSyncChip() {
    const chip = $("#syncChip");
    if (!chip) return;
    const offline = state.offlineMode;
    chip.dataset.state = offline ? "offline" : (state.loading ? "syncing" : "online");
    const text = $(".sync-text", chip);
    if (text) text.textContent = offline ? "Офлайн" : (state.loading ? "Синхронизация..." : "Актуально");
    
    // Animate the icon
    const dot = $(".dot", chip);
    if (dot) {
        if (state.loading) {
            dot.style.animation = "pulse 1s infinite alternate";
        } else {
            dot.style.animation = "none";
        }
    }
}"""

js = re.sub(
    r"function updateSyncChip\(\) \{.+?\}\s*function renderBrandMark\(\)",
    sync_replacement + "\n\nfunction renderBrandMark()",
    js,
    flags=re.DOTALL
)

with open("/home/zxc/CRM/sto_crm/assets/app.js", "w", encoding="utf-8") as f:
    f.write(js)

with open("/home/zxc/CRM/sto_crm/assets/app.css", "a", encoding="utf-8") as f:
    f.write("""
@keyframes pulse {
    0% { transform: scale(0.8); opacity: 0.5; }
    100% { transform: scale(1.2); opacity: 1; }
}
""")

print("Sync UI modified")
