"""Regression tests for deterministic bundle validation and manifest check."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE_SCRIPT = ROOT / "tools" / "build_frontend_bundle.py"
APP_JS = ROOT / "sto_crm" / "assets" / "app.js"
SOURCE_JS = ROOT / "sto_crm" / "assets" / "js" / "app_main.js"


class TestBundleScaffold(unittest.TestCase):
    def test_bundle_check_fails_on_drift(self) -> None:
        # 1. Проверяем, что исходный чекер проходит успешно
        res = subprocess.run(
            [sys.executable, str(BUNDLE_SCRIPT), "--check"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0, f"Baseline check failed: {res.stderr}")

        # Сохраняем исходное содержимое для отката
        app_js_original = APP_JS.read_text(encoding="utf-8")
        src_js_original = SOURCE_JS.read_text(encoding="utf-8")

        try:
            # 2. Модифицируем runtime app.js
            APP_JS.write_text(
                app_js_original + "\n// drift probe comment\n", encoding="utf-8"
            )
            res_drift_app = subprocess.run(
                [sys.executable, str(BUNDLE_SCRIPT), "--check"],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(
                res_drift_app.returncode,
                0,
                "Changer should fail when runtime app.js is manually modified",
            )

            # Восстанавливаем app.js
            APP_JS.write_text(app_js_original, encoding="utf-8")

            # 3. Модифицируем исходный модуль source js
            SOURCE_JS.write_text(
                src_js_original + "\n// drift source comment\n", encoding="utf-8"
            )
            res_drift_src = subprocess.run(
                [sys.executable, str(BUNDLE_SCRIPT), "--check"],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(
                res_drift_src.returncode,
                0,
                "Changer should fail when source module is modified without being rebuilt",
            )

        finally:
            # Гарантируем откат изменений
            APP_JS.write_text(app_js_original, encoding="utf-8")
            SOURCE_JS.write_text(src_js_original, encoding="utf-8")

        # 4. Проверяем, что после отката всё чисто
        res_after = subprocess.run(
            [sys.executable, str(BUNDLE_SCRIPT), "--check"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res_after.returncode, 0)

    def test_legacy_checker_fails_on_broken_legacy_bundle(self) -> None:
        # Проверяем, что check_frontend_contracts.py падает, если лишить его контрактов через load_test_index_html
        drift_code = """
import importlib.util
from pathlib import Path
import sys

p = Path("tests/check_frontend_contracts.py")
spec = importlib.util.spec_from_file_location("contract_check_under_test", p)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mod.load_test_index_html = lambda: ''
sys.exit(mod.main())
"""
        res = subprocess.run(
            [sys.executable, "-c", drift_code],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        self.assertEqual(
            res.returncode,
            1,
            "check_frontend_contracts.py should fail when load_test_index_html is empty",
        )
        self.assertIn("[MISSING LEGACY BUNDLE]", res.stdout)
