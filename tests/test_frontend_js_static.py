"""Static quality checks for the vanilla FrontEnd bundle.

These tests intentionally avoid a browser runtime and catch regressions that
`node --check` cannot see: stale helpers, inline-style CSP bypasses and the
most important accessibility/mobile-navigation contracts.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "sto_crm" / "assets" / "app.js"
APP_CSS = ROOT / "sto_crm" / "assets" / "app.css"
INDEX_HTML = ROOT / "sto_crm" / "assets" / "index.html"

BROWSER_GLOBALS = [
    "document",
    "window",
    "location",
    "history",
    "fetch",
    "URL",
    "URLSearchParams",
    "AbortController",
    "HTMLElement",
    "HTMLInputElement",
    "HTMLTextAreaElement",
    "HTMLSelectElement",
    "RadioNodeList",
    "IntersectionObserver",
    "FormData",
    "Event",
    "confirm",
    "localStorage",
    "sessionStorage",
    "console",
    "requestAnimationFrame",
    "cancelAnimationFrame",
    "setTimeout",
    "clearTimeout",
    "setInterval",
]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def eslint_command() -> list[str] | None:
    """Return a cross-platform ESLint command when the runner is available."""
    eslint = shutil.which("eslint") or shutil.which("eslint.cmd")
    if eslint:
        return [eslint]
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if npx:
        return [npx, "--yes", "eslint"]
    return None


class FrontendStaticQualityTests(unittest.TestCase):
    def test_frontend_js_has_no_obvious_dead_helpers_or_inline_styles(self) -> None:
        js = read(APP_JS)
        for name in [
            "itemApprovalBadge",
            "overdueOrderList",
            "smallOrderList",
            "appointmentList",
            "lowStockList",
        ]:
            self.assertNotIn(f"function {name}(", js)
        self.assertNotIn(".style.", js)
        self.assertNotIn("style=", js)
        self.assertNotIn("catch (_error)", js)
        self.assertNotIn("document.documentElement.style", js)
        self.assertNotIn("</script", js.lower())
        self.assertNotIn('$("#appointment_customer_id").addEventListener', js)
        self.assertNotIn('$("#order_customer_id").addEventListener', js)
        self.assertNotIn('$("#addService").addEventListener', js)
        self.assertIn('customerSelect?.addEventListener("change"', js)
        self.assertIn('$("#order_customer_id")?.addEventListener("change"', js)
        self.assertIn('$("#addService")?.addEventListener("click"', js)
        self.assertIn('$("#addPart")?.addEventListener("click"', js)

    def test_embedded_frontend_script_is_not_cut_by_html_parser(self) -> None:
        """Inline bundle must not contain a literal closing script tag."""
        page = (
            read(INDEX_HTML)
            .replace("__STO_CRM_APP_CSS__", read(APP_CSS), 1)
            .replace("__STO_CRM_APP_JS__", read(APP_JS), 1)
        )
        self.assertEqual(page.lower().count("</script>"), 2)
        self.assertIn("function safeRecordId(value)", page)

    def test_frontend_tone_and_theme_contracts_are_normalized(self) -> None:
        css = read(APP_CSS)
        js = read(APP_JS)
        html = read(INDEX_HTML)
        self.assertIn('data-initial-theme="light"', html)
        self.assertIn('document.documentElement.dataset.themeReady = "1"', html)
        self.assertIn('typeof media === "function"', js)
        self.assertIn('function toneToken(value, fallback = "info")', js)
        self.assertIn('function semanticToneClass(value, fallback = "")', js)
        self.assertIn('.metric.tone-neutral .metric-icon', css)
        self.assertIn('.context-pill.neutral', css)
        self.assertIn('.hint-chip[data-tone="success"] .hint-dot', css)
        self.assertNotRegex(css, r"calc\([^\n;{}]*\*[^\n;{}]*\)")
        self.assertNotIn(":has(", css)

    def test_frontend_mobile_nav_and_dialog_visibility_contracts(self) -> None:
        html = read(INDEX_HTML)
        js = read(APP_JS)
        css = read(APP_CSS)
        self.assertIn('id="mobileNavToggle"', html)
        self.assertIn('id="mobileNavBackdrop"', html)
        self.assertIn('id="appSidebar"', html)
        self.assertIn('aria-controls="appSidebar"', html)
        self.assertIn("function initMobileNavigation()", js)
        self.assertIn("setMobileNavOpen(false);", js)
        self.assertIn('setMobileNavOpen(false, { restoreFocus: false });', js)
        self.assertIn("body.mobile-nav-open .sidebar", css)
        self.assertIn("mobileNavBackdrop", js)
        self.assertIn('id="modalBackdrop" hidden', html)
        self.assertIn('id="commandPalette" hidden', html)
        self.assertNotIn('id="modalBackdrop" role="presentation"', html)
        self.assertNotIn('id="commandPalette" role="presentation"', html)
        self.assertNotIn(
            'id="modalBackdrop" aria-hidden="true" hidden', html
        )
        self.assertNotIn(
            'id="commandPalette" aria-hidden="true" hidden', html
        )
        self.assertIn("backdrop.hidden = false;", js)
        self.assertIn("backdrop.hidden = true;", js)
        self.assertIn("palette.hidden = false;", js)
        self.assertIn("palette.hidden = true;", js)

    def test_frontend_uses_inert_without_focusable_aria_hidden_conflicts(self) -> None:
        js = read(APP_JS)
        self.assertIn(
            'if ("inert" in app) {\n            app.removeAttribute("aria-hidden");', js
        )
        self.assertIn(
            'if (isMobile && !nextOpen) sidebar.setAttribute("aria-hidden", "true");',
            js,
        )
        self.assertIn('main.toggleAttribute("aria-hidden", nextOpen);', js)
        self.assertNotIn('backdrop.setAttribute("aria-hidden", "true");', js)
        self.assertNotIn('palette.setAttribute("aria-hidden", "true");', js)

    def test_frontend_update_install_guards_stale_and_unsupported_states(self) -> None:
        js = read(APP_JS)
        self.assertIn("if (state.updateInstalling) return;", js)
        self.assertIn("!release.has_asset", js)
        self.assertIn("!status.can_install", js)
        self.assertIn("if (!result.updated)", js)
        self.assertIn("Обновление не требуется", js)
        self.assertIn('${installDisabled ? "disabled" : ""}', js)

    def test_frontend_bootstrap_guards_and_order_route_filter_reload(self) -> None:
        js = read(APP_JS)
        self.assertIn('function ensureBootstrapReady(actionName = "действие")', js)
        self.assertIn('function isBootstrapRequestPath(path)', js)
        self.assertIn('isBootstrapRequestPath(path) ? withBootstrapToken(path) : path', js)
        self.assertNotIn('path === "/api/bootstrap" ? withBootstrapToken(path) : path', js)
        for modal, label in [
            ("openAppointmentModal", "создание записи"),
            ("openCustomerModal", "создание клиента"),
            ("openVehicleModal", "создание автомобиля"),
            ("openInventoryModal", "создание складской позиции"),
            ("openOrderModal", "создание заказ-наряда"),
        ]:
            pattern = rf"function {modal}\([^)]*\) \{{\n\s+if \(!ensureBootstrapReady\(\"{re.escape(label)}\"\)\) return;"
            self.assertRegex(js, pattern)
        self.assertIn(
            "const needsRouteFilterReload = enteringFilteredOrders || leavingFilteredOrders;",
            js,
        )
        self.assertIn('state.status = "all";', js)

    def test_frontend_backup_status_uses_server_timestamp_without_path_leak(self) -> None:
        js = read(APP_JS)
        self.assertIn('state.backupBusy = true;', js)
        self.assertIn('state.backupBusy = false;', js)
        self.assertIn('backupBtn?.toggleAttribute("disabled", state.backupBusy);', js)
        self.assertIn('backupWrap.setAttribute("aria-busy", state.backupBusy ? "true" : "false");', js)
        self.assertIn('state.lastBackupAt = result.created_at || new Date().toISOString();', js)
        self.assertIn('result.display_path || result.filename || "готово"', js)
        self.assertNotIn("result.path", js)

    def test_frontend_access_token_is_not_cached_and_is_sent_as_header(self) -> None:
        js = read(APP_JS)
        self.assertIn('function initialBootstrapToken()', js)
        self.assertIn('document.body?.dataset?.bootstrapToken', js)
        self.assertIn('delete document.body.dataset.bootstrapToken;', js)
        self.assertIn('state.bootstrapToken = "";', js)
        self.assertIn('delete cached.app.access_token;', js)
        self.assertIn('headers["X-CRM-Access-Token"] = accessToken;', js)
        self.assertNotIn('url.searchParams.get("access_token")', js)
        self.assertNotIn('url.searchParams.get("bootstrap_token")', js)

    def test_frontend_order_history_readonly_contracts(self) -> None:
        js = read(APP_JS)
        self.assertIn("function entityRecordPath(kind, id)", js)
        self.assertIn("function safeDownloadFilename(value", js)
        self.assertIn("entityCollectionPath(kind)", js)
        self.assertIn("state.orderDraftReadOnly = historicalOrder;", js)
        self.assertIn(
            'readonlyField("Follow-up", readonlyValue(inputDateValue(order.follow_up_at)))',
            js,
        )
        self.assertIn('hiddenInput("follow_up_at", inputDateValue(order.follow_up_at))', js)
        self.assertIn('if (state.orderDraftReadOnly) return;\n        markModalDirty();', js)
        self.assertIn(
            "function syncAllOrderItems() {\n    if (state.orderDraftReadOnly) return;",
            js,
        )
        self.assertIn(
            "function syncOrderItemsFromDom(event) {\n    if (state.orderDraftReadOnly) return;",
            js,
        )
        self.assertIn(
            "function syncOrderItemStateOnly(event) {\n    if (state.orderDraftReadOnly) return;",
            js,
        )
        self.assertIn("${ordersTable(recent, true)}", js)
        self.assertIn(
            "function findById(list, id) {\n    return Array.isArray(list)",
            js,
        )
        self.assertIn("function closeTransientPanels(", js)
        self.assertIn("closeTransientPanels();\n    const previousRoute = state.route;", js)

    def test_frontend_lints_without_unused_variables_when_eslint_available(
        self,
    ) -> None:
        eslint = eslint_command()
        if eslint is None:
            self.skipTest("eslint/npx is not installed")
        command = [
            *eslint,
            "--no-config-lookup",
            *[flag for name in BROWSER_GLOBALS for flag in ("--global", name)],
            "--rule",
            "no-unused-vars: error",
            "--rule",
            "no-undef: error",
            "--rule",
            "no-redeclare: error",
            str(APP_JS),
        ]
        timeout = int(os.environ.get("CRM_ESLINT_TIMEOUT", "120"))
        try:
            result = subprocess.run(
                command, cwd=ROOT, text=True, capture_output=True, timeout=timeout
            )
        except subprocess.TimeoutExpired as exc:
            self.skipTest(
                f"eslint did not finish within {timeout}s in this environment: {exc}"
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_css_mobile_responsiveness_contracts(self) -> None:
        css = read(APP_CSS)
        html = read(INDEX_HTML)
        js = read(APP_JS)
        self.assertIn("body.compact { --header-h: 52px;", css)
        self.assertIn("minmax(min(100%, 320px), 1fr)", css)
        self.assertIn("@media (pointer: coarse)", css)
        self.assertIn("min-height: 44px", css)
        self.assertIn("100dvh", css)
        self.assertIn("@media (prefers-reduced-motion: reduce)", css)
        self.assertIn("transition-delay: 0ms !important;", css)
        self.assertIn("html:focus-within { scroll-behavior: smooth; }", css)
        self.assertIn(".help-tip:focus-visible", css)
        self.assertIn(".modal-backdrop[hidden], .command-palette-backdrop[hidden]", css)
        self.assertRegex(css, r"\.modal\.small\s*\{\s*max-width:\s*520px")
        self.assertRegex(css, r"\.modal\.wide\s*\{\s*max-width:\s*1080px")
        self.assertIn("@media (max-width: 1280px) and (min-width: 1025px)", css)
        self.assertIn("body.sidebar-collapsed .nav-label { display: inline; }", css)
        self.assertIn(".cta-wrap, .system-menu { position: relative; }", css)
        self.assertIn(
            ".top-actions, .bell-wrap, .cta-wrap, .system-menu { overflow: visible; }",
            css,
        )
        self.assertIn(".sidebar { position: fixed; top: 0; left: 0; width: 260px;", css)
        self.assertIn(
            "#primaryCtaMore { width: var(--icon-size-touch); min-width: var(--icon-size-touch);",
            css,
        )
        self.assertIn(
            ".system-menu-button { width: var(--icon-size-touch); min-width: var(--icon-size-touch);",
            css,
        )
        self.assertIn(".search-clear,", css)
        self.assertIn(".search-clear[hidden] { display: none; }", css)
        self.assertIn(".quick-tile,", css)
        self.assertIn(".search input { min-height: calc(var(--interactive-min) - 2px); }", css)
        self.assertIn("body.compact .btn.icon,", css)
        self.assertIn(".breadcrumbs .crumb,", css)
        self.assertIn(".system-menu-panel { display: none !important; }", css)
        self.assertIn(".business-hints { display: grid;", css)
        self.assertIn("align-items: stretch", css)
        self.assertIn(".business-hints > * { min-width: 0; }", css)
        self.assertIn("overflow-wrap: anywhere", css)
        self.assertIn(".business-hints.has-dismiss { grid-template-columns: 1fr; }", css)
        self.assertIn(".hint-dismiss {\n    position: static;", css)
        self.assertIn(".sidebar-collapse[data-tooltip]", css)
        self.assertIn(".bell-item {\n    display: grid;", css)
        self.assertIn(".hero-stat-stack .hero-stat:last-child:nth-child(odd)", css)
        self.assertIn(".topbar [data-tooltip]::after", css)
        self.assertIn('aria-haspopup="dialog"', html)
        self.assertIn('id="bellPanel" role="dialog"', html)
        self.assertIn('id="statusbar" aria-label="Статус приложения"', html)
        self.assertNotIn('id="statusbar" role="status"', html)
        self.assertIn('aria-keyshortcuts="Control+K Meta+K"', html)
        self.assertIn('class="system-menu-icon" aria-hidden="true">⚙', html)
        self.assertIn('class="btn ghost bell-panel-close"', html)
        self.assertIn('type="button" class="help-tip" aria-label', js)
        self.assertIn('data-help-tip="true"', js)
        self.assertIn('$("#bellClose")?.addEventListener("click"', js)
        self.assertNotIn("#commandBtn,\n    #refreshBtn,", css)
        self.assertNotIn("#refreshBtn,\n    #systemMenuBtn", css)
        self.assertIn("#commandBtn, #refreshBtn { width: 44px;", css)
        self.assertIn("#commandBtn::before", css)
        self.assertIn("--topbar-offset: var(--header-h)", css)
        self.assertIn("--brand-gradient: linear-gradient(145deg", css)
        self.assertIn("background: var(--brand-gradient);", css)
        self.assertIn("top: var(--topbar-offset)", css)
        self.assertIn(
            "max-height: calc(100dvh - var(--topbar-offset) - var(--space-4))",
            css,
        )
        self.assertIn('html[data-topbar-offset="lg"] { --topbar-offset: 140px; }', css)
        self.assertIn(".breadcrumbs { padding-inline: var(--space-4); }", css)
        self.assertIn(".search-hint { display: none; }", css)
        self.assertIn("updateTopbarOffset", js)
        self.assertIn('closeTransientPanels("cta")', js)
        self.assertIn('closeTransientPanels("bell")', js)
        self.assertIn('closeTransientPanels("system")', js)
        self.assertIn("closePanel(false, { restoreFocus: true });", js)
        self.assertIn("content?.focus({ preventScroll: true });", js)
        self.assertIn('setMobileNavOpen(false, { restoreFocus: false });', js)


if __name__ == "__main__":
    unittest.main()
