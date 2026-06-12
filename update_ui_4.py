import re

with open("/home/zxc/CRM/sto_crm/assets/app.css", "r", encoding="utf-8") as f:
    css = f.read()

# Make modal animations smoother
css = re.sub(
    r"\.modal-backdrop(?:\[hidden\]|\.hidden)\{([^}]+)\}", 
    r".modal-backdrop[hidden] { display: none !important; opacity: 0; pointer-events: none; }\n.modal-backdrop {\n  transition: opacity 0.3s ease-out;\n}\n",
    css
)

css += """
.modal-backdrop:not([hidden]) {
    animation: fadeIn 0.2s ease-out forwards;
}

@keyframes fadeIn {
    from { opacity: 0; }
    to { opacity: 1; }
}

.modal {
    transform: translateY(20px) scale(0.95);
    opacity: 0;
    transition: transform 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275), opacity 0.3s ease-out;
}

.modal-backdrop:not([hidden]) .modal {
    transform: translateY(0) scale(1);
    opacity: 1;
}

/* Beautiful custom scrollbars */
::-webkit-scrollbar {
    width: 6px;
    height: 6px;
}
::-webkit-scrollbar-track {
    background: transparent;
}
::-webkit-scrollbar-thumb {
    background: var(--line-strong);
    border-radius: 10px;
}
::-webkit-scrollbar-thumb:hover {
    background: var(--brand-mid);
}

/* Enhancing active navigation item */
.nav-section button.active {
    background: var(--brand-soft);
    color: var(--brand-strong);
    border-right: 3px solid var(--brand);
}

.brand-title {
    background: linear-gradient(135deg, var(--brand-end), var(--brand-strong));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    font-weight: 800;
}
"""

with open("/home/zxc/CRM/sto_crm/assets/app.css", "w", encoding="utf-8") as f:
    f.write(css)

print("Modal animations & scrollbars upgraded.")
