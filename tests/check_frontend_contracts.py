#!/usr/bin/env python3
"""Проверка текстовых контрактов для actual served shell/assets.

Сверяет списки обязательных/запрещённых подстрок из tests/_frontend_contracts.js
с компонентами actual served shell/assets (index.html, app.css, app.js),
а также с результирующим выводом index_html() страницы (с bootstrap токеном).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Добавим пути sto_crm, чтобы импортировать index_html() и runtime напрямую
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# fmt: off
from sto_crm.runtime import RUNTIME  # noqa: E402
from sto_crm.web import index_html, load_test_index_html, read_asset  # noqa: E402

# fmt: on

CONTRACTS = ROOT / "tests" / "_frontend_contracts.js"


def _extract_array(text: str, name: str) -> list[str]:
    # Парсер JS-строкового литерала
    str_re = re.compile(
        r"""
        (?<!\\)            # не часть экранирования
        (?P<q>["'])        # открывающая кавычка
        (?P<body>          # тело строки
            (?:\\.|(?!(?P=q)).)*
        )
        (?P=q)             # закрывающая кавычка
        """,
        re.DOTALL | re.VERBOSE,
    )
    escapes = {
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "b": "\b",
        "f": "\f",
        "v": "\v",
        "0": "\0",
        "\\": "\\",
        '"': '"',
        "'": "'",
        "`": "`",
        "/": "/",
    }

    def unescape(raw: str) -> str:
        out = []
        i = 0
        while i < len(raw):
            ch = raw[i]
            if ch == "\\" and i + 1 < len(raw):
                nxt = raw[i + 1]
                if nxt == "x" and i + 3 < len(raw):
                    try:
                        out.append(chr(int(raw[i + 2 : i + 4], 16)))
                        i += 4
                        continue
                    except ValueError:
                        pass
                if nxt == "u" and i + 5 < len(raw):
                    try:
                        out.append(chr(int(raw[i + 2 : i + 6], 16)))
                        i += 6
                        continue
                    except ValueError:
                        pass
                out.append(escapes.get(nxt, nxt))
                i += 2
                continue
            out.append(ch)
            i += 1
        return "".join(out)

    match = re.search(rf"const {name} = \[(.*?)\];", text, flags=re.DOTALL)
    if not match:
        raise SystemExit(f"Не нашёл массив {name} в {CONTRACTS}")
    body = match.group(1)
    body = re.sub(r"//[^\n]*", "", body)
    result: list[str] = []
    for m in str_re.finditer(body):
        result.append(unescape(m.group("body")))
    return result


def main() -> int:
    contracts = CONTRACTS.read_text(encoding="utf-8")
    required_html = _extract_array(contracts, "REQUIRED_HTML_SHELL")
    required_js = _extract_array(contracts, "REQUIRED_JS_PUBLIC_HOOKS")
    required_css = _extract_array(contracts, "REQUIRED_CSS_HOOKS")
    forbidden = _extract_array(contracts, "FORBIDDEN_SECURITY_PATTERNS")

    # Инициализируем рантайм токен, если он не задан
    if not RUNTIME.bootstrap_token:
        # Для mypy обходим read-only
        RUNTIME.__dict__["bootstrap_token"] = "TEST_BOOTSTRAP_TOKEN"

    # Загружаем actual served shell
    served_shell = index_html()

    # Загружаем assets напрямую через read_asset
    app_css = read_asset("app.css")
    app_js = read_asset("app.js")

    # Объединяем контент для проверки
    full_served_page = served_shell + "\n" + app_css + "\n" + app_js

    # Секционные проверки
    missing_html = [s for s in required_html if s not in served_shell]
    missing_js = [s for s in required_js if s not in app_js]
    missing_css = [s for s in required_css if s not in app_css]

    # Также проверим legacy/test bundle для уверенности сохранности обратной совместимости
    legacy_bundle = load_test_index_html()
    missing_legacy = []
    for s in (required_html + required_js + required_css):
        if s not in legacy_bundle:
            missing_legacy.append(s)

    leaked = [s for s in forbidden if s in full_served_page]

    failed = False

    if missing_legacy:
        print(f"[MISSING LEGACY BUNDLE] {len(missing_legacy)} подстрок:")
        for s in missing_legacy:
            print("  -", repr(s))
        failed = True

    if missing_html:
        print(f"[MISSING HTML SHELL] {len(missing_html)} подстрок:")
        for s in missing_html:
            print("  -", repr(s))
        failed = True

    if missing_js:
        print(f"[MISSING JS HOOKS] {len(missing_js)} подстрок:")
        for s in missing_js:
            print("  -", repr(s))
        failed = True

    if missing_css:
        print(f"[MISSING CSS HOOKS] {len(missing_css)} подстрок:")
        for s in missing_css:
            print("  -", repr(s))
        failed = True

    if leaked:
        print(f"[FORBIDDEN PATTERNS DETECTED] {len(leaked)} подстрок:")
        for s in leaked:
            print("  !", repr(s))
        failed = True

    if failed:
        return 1

    print(
        f"OK: actual served shell ({len(required_html)}), "
        f"app.js ({len(required_js)}), app.css ({len(required_css)}) "
        f"соответствуют контрактам. Запрещенных шаблонов ({len(forbidden)}) не обнаружено."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
