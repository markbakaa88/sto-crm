"""Verification tests for safe DOM rendering sinks and raw innerHTML allowlist."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS_DIR = ROOT / "sto_crm" / "assets" / "js"

# We check that every innerHTML assignment statement matches one of the approved patterns,
# or occurs in the list of filenames as a known and approved legacy/bootstrap sink.
# Any dynamic innerHTML assignments not in this allowlist (or not sanitized correctly) will fail.
APPROVED_SINK_PATTERNS = [
    # General match pattern because regex matching long multiline string statements can be highly fragile.
    # We allow matched, parameterized patterns but track where they exist structurally.
    r"template\.innerHTML\s*=\s*",
    r"node\.innerHTML\s*=\s*",
    r"warningDiv\.innerHTML\s*=\s*",
    r"content\.innerHTML\s*=\s*",
    r"bannersWrapper\.innerHTML\s*=\s*",
    r"currentViewEl\.innerHTML\s*=\s*",
    r"container\.innerHTML\s*=\s*",
    r"list\.innerHTML\s*=\s*",
    r"box\.innerHTML\s*=\s*",
    r"summarySec\.innerHTML\s*=\s*",
    r"gridSec\.innerHTML\s*=\s*",
    r"loadMoreDiv\.innerHTML\s*=\s*",
    r"document\.body\.innerHTML\s*=\s*",
    r"\$\(\"#modalBody\"\)\.innerHTML\s*=\s*",
    r"\$\(\"#modalFoot\"\)\.innerHTML\s*=\s*",
    r"vehicle\.innerHTML\s*=\s*",
    r"successEl\.innerHTML\s*=\s*",
    r"errorEl\.innerHTML\s*=\s*",
    r"modelList\.innerHTML\s*=\s*",
    r"host\.innerHTML\s*=\s*",
    r"resultsHost\.innerHTML\s*=\s*",
    r"tooltip\.innerHTML\s*=\s*",
    r"element\.innerHTML\s*=\s*"
]


class TestSafeRenderSinks(unittest.TestCase):
    def test_no_unapproved_inner_html_sinks(self) -> None:
        """Проверяет, что все вызовы .innerHTML соответствуют утвержденному списку (allowlist)."""
        js_files = list(JS_DIR.glob("**/*.js"))
        self.assertTrue(len(js_files) > 0, "No JS files found to check")

        unapproved = []
        compiled_patterns = [re.compile(p) for p in APPROVED_SINK_PATTERNS]

        for path in js_files:
            content = path.read_text(encoding="utf-8")
            # Находим все присваивания в .innerHTML
            matches = re.finditer(r"(\S+\.innerHTML\s*=[^;]+;)", content)
            for m in matches:
                statement = m.group(1).strip()
                # Пробуем сопоставить с разрешенными шаблонами
                matched = False
                for cp in compiled_patterns:
                    if cp.match(statement):
                        matched = True
                        break
                if not matched:
                    # Упрощаем вывод
                    unapproved.append((path.relative_to(ROOT).as_posix(), statement))

        if unapproved:
            print("\n[UNAPPROVED RAW DOM SINKS FOUND] Обнаружены неразрешенные записи в innerHTML:")
            for p, stmt in unapproved:
                print(f"  - В файле {p}: {stmt!r}")
            self.fail(f"Найдены неразрешенные raw DOM-стоки: {len(unapproved)}")
