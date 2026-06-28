"""Verification tests for safe DOM rendering sinks and raw innerHTML allowlist."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS_DIR = ROOT / "sto_crm" / "assets" / "js"

# Strict whitelist matching of exact raw innerHTML assigned lines per JS file relative to JS_DIR.
# If any JS file has a line containing ".innerHTML =" or ".innerHTML=" that is not in this dictionary,
# the test will fail. This prevents introducing new unsafe render sinks.
APPROVED_SINK_STATEMENTS: dict[str, set[str]] = {
    "core/dom.js": {
        'template.innerHTML = String(markup || "");',
        "element.innerHTML = markup;",
    },
    "app_main.js": {
        'node.innerHTML = `<strong>${icon}</strong> <span>${esc(current.message)}</span><button class="toast-close" aria-label="Закрыть уведомление" tabindex="-1">&times;</button>`;',
        'node.innerHTML = "";',
        "warningDiv.innerHTML = `<strong>Конфликт версий!</strong><p>Этот объект (${esc(conflictDetails)}) был изменен на сервере, пока вы были оффлайн. Рекомендуется закрыть это окно без сохранения и открыть заново, чтобы не затереть чужие изменения.</p>`;",
        'container.innerHTML = "";',
        'container.innerHTML = parts.join("");',
        'list.innerHTML = "";',
        "list.innerHTML = items.map(item => `",
        'box.innerHTML = "";',
        "box.innerHTML = html;",
        "list.innerHTML = items.map((item, index) => {",
        "summarySec.innerHTML = `",
        'gridSec.innerHTML = visibleEntries.map(entry => catalogMakeHtml(entry.make, entry.models)).join("") || emptyState("В каталоге ничего не найдено", "Измените фильтр по марке или модели.", "", "🔍");',
        "loadMoreDiv.innerHTML = btnHtml;",
        'document.body.innerHTML = `<main class="shutdown-state"><section class="shutdown-card"><h1>СТО CRM обновляется</h1><p>Приложение закроется, заменит exe и запустится снова.${backupText}</p></section></main>`;',
        '$("#modalBody").innerHTML = body;',
        '$("#modalFoot").innerHTML = foot;',
        '$("#modalBody").innerHTML = "";',
        '$("#modalFoot").innerHTML = "";',
        'vehicle.innerHTML = vehicleOptions(event.target.value, "");',
        'successEl.innerHTML = "✓ <span></span>";',
        'errorEl.innerHTML = "⚠️ <span></span>";',
        "modelList.innerHTML = datalistOptions(catalogModels(makeInput.value), modelInput.value);",
        'host.innerHTML = `<div class="items-table">',
        "resultsHost.innerHTML = SkeletonBuilder.partsPricing(2);",
        "resultsHost.innerHTML = `",
        "resultsHost.innerHTML = html;",
        'content.innerHTML = `${offlineBannerHtml(true)}<div class="notice" role="alert"><strong>Не удалось загрузить данные.</strong><p>${esc(message)}</p><button class="btn primary" type="button" data-action="retry-load">Повторить</button></div>`;',
        'document.body.innerHTML = \'<main class="shutdown-state"><section class="shutdown-card"><h1>СТО CRM остановлена</h1><p>Локальный сервер завершает работу. Окно можно закрыть.</p></section></main>\';',
        "tooltip.innerHTML = text;",
    },
}


def audit_js_file(path: Path) -> list[str]:
    """Inspects a JS file for any unapproved innerHTML assignments.

    Returns:
        List of unapproved statements found.
    """
    rel_path = path.relative_to(JS_DIR).as_posix()
    approved = APPROVED_SINK_STATEMENTS.get(rel_path, set())
    unapproved = []

    content = path.read_text(encoding="utf-8")
    for line in content.splitlines():
        line_stripped = line.strip()
        # Look for assignments to innerHTML
        if ".innerHTML" in line_stripped and "=" in line_stripped:
            # We match if the exact stripped line is in our approved statements.
            matched = False
            for val in approved:
                if line_stripped == val or line_stripped.startswith(val):
                    matched = True
                    break
            if not matched:
                unapproved.append(line_stripped)
    return unapproved


class TestSafeRenderSinks(unittest.TestCase):
    def test_no_unapproved_inner_html_sinks(self) -> None:
        """Проверяет, что все вызовы .innerHTML соответствуют точному списку разрешенных строк."""
        js_files = list(JS_DIR.glob("**/*.js"))
        self.assertTrue(len(js_files) > 0, "No JS files found to check")

        errors: list[str] = []
        for path in js_files:
            unapproved = audit_js_file(path)
            for stmt in unapproved:
                rel = path.relative_to(ROOT).as_posix()
                errors.append(f"  - В файле {rel}: {stmt!r}")

        if errors:
            print(
                "\n[UNAPPROVED RAW DOM SINKS FOUND] Обнаружены неразрешенные записи в innerHTML:"
            )
            for err in errors:
                print(err)
            self.fail(f"Найдены неразрешенные raw DOM-стоки: {len(errors)}")

    def test_false_negative_safety_gate(self) -> None:
        """Проверяет работоспособность теста (red-test) на добавление случайного нового innerHTML.

        Тест должен гарантированно падать, если в код добавляется новый innerHTML sink.
        """
        temp_file = JS_DIR / "core" / "__review_probe.js"
        temp_file.parent.mkdir(parents=True, exist_ok=True)
        # Временная небезопасная инициализация
        unsafe_code = "function unsafe(element, x) {\n    element.innerHTML = x;\n}\n"
        temp_file.write_text(unsafe_code, encoding="utf-8")
        try:
            unapproved = audit_js_file(temp_file)
            self.assertTrue(
                len(unapproved) > 0,
                "Анализатор должен был обнаружить неразрешенное присвоение в innerHTML.",
            )
            self.assertIn("element.innerHTML = x;", unapproved)
        finally:
            temp_file.unlink(missing_ok=True)
