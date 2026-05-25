"""Static quality checks for the vanilla FrontEnd bundle.

These tests intentionally avoid a browser runtime and catch regressions that
`node --check` cannot see: stale helpers, inline-style CSP bypasses and the
most important accessibility/mobile-navigation contracts.
"""

from __future__ import annotations

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
        self.assertIn("body.mobile-nav-open .sidebar", css)
        self.assertIn("mobileNavBackdrop", js)
        self.assertIn('id="modalBackdrop" role="presentation" hidden', html)
        self.assertIn('id="commandPalette" role="presentation" hidden', html)
        self.assertNotIn(
            'id="modalBackdrop" role="presentation" aria-hidden="true" hidden', html
        )
        self.assertNotIn(
            'id="commandPalette" role="presentation" aria-hidden="true" hidden', html
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
            'if (isMobile && !nextOpen && !hasNativeInert) sidebar.setAttribute("aria-hidden", "true");',
            js,
        )
        self.assertNotIn('backdrop.setAttribute("aria-hidden", "true");', js)
        self.assertNotIn('palette.setAttribute("aria-hidden", "true");', js)

    def test_frontend_update_install_guards_stale_and_unsupported_states(self) -> None:
        js = read(APP_JS)
        self.assertIn("if (state.updateInstalling) return;", js)
        self.assertIn("!release.has_asset", js)
        self.assertIn("!status.can_install", js)
        self.assertIn("if (!result.updated)", js)
        self.assertIn("Обновление не требуется", js)
        self.assertIn("disabled: installDisabled", js)

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
        result = subprocess.run(
            command, cwd=ROOT, text=True, capture_output=True, timeout=120
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_css_mobile_responsiveness_contracts(self) -> None:
        css = read(APP_CSS)
        self.assertIn("body.compact { --header-h: 52px;", css)
        self.assertIn("minmax(min(100%, 320px), 1fr)", css)
        self.assertIn("@media (pointer: coarse)", css)
        self.assertIn("min-height: 44px", css)
        self.assertIn("100dvh", css)
        self.assertIn(".help-tip:focus-visible", css)
        self.assertIn(".modal-backdrop[hidden], .command-palette-backdrop[hidden]", css)
        self.assertRegex(css, r"\.modal\.small\s*\{\s*max-width:\s*520px")
        self.assertRegex(css, r"\.modal\.wide\s*\{\s*max-width:\s*1080px")


if __name__ == "__main__":
    unittest.main()
