#!/usr/bin/env python3
"""Проверка текстовых контрактов для sto_crm.INDEX_HTML.

Собирает INDEX_HTML так же, как sto_crm.web (index.html с вставленными app.css
и app.js), и сверяет списки обязательных/запрещённых подстрок из
tests/_frontend_contracts.js.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "tests" / "_frontend_contracts.js"
ASSETS = ROOT / "sto_crm" / "assets"

# Парсер JS-строкового литерала: " ... " или ' ... ' с эскейпами \\, \", \', \n, \t и т.п.
_STR_RE = re.compile(
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

_ESCAPES = {
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


def _unescape(raw: str) -> str:
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
            out.append(_ESCAPES.get(nxt, nxt))
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _extract_array(text: str, name: str) -> list[str]:
    match = re.search(rf"const {name} = \[(.*?)\];", text, flags=re.DOTALL)
    if not match:
        raise SystemExit(f"Не нашёл массив {name} в {CONTRACTS}")
    body = match.group(1)
    body = re.sub(r"//[^\n]*", "", body)
    result: list[str] = []
    for m in _STR_RE.finditer(body):
        result.append(_unescape(m.group("body")))
    return result


def main() -> int:
    contracts = CONTRACTS.read_text(encoding="utf-8")
    required = _extract_array(contracts, "REQUIRED_SUBSTRINGS")
    forbidden = _extract_array(contracts, "FORBIDDEN_SUBSTRINGS")

    template = (ASSETS / "index.html").read_text(encoding="utf-8")
    css = (ASSETS / "app.css").read_text(encoding="utf-8")
    js = (ASSETS / "app.js").read_text(encoding="utf-8")
    page = template.replace("__STO_CRM_APP_CSS__", css, 1).replace(
        "__STO_CRM_APP_JS__", js, 1
    )

    missing = [s for s in required if s not in page]
    leaked = [s for s in forbidden if s in page]

    if missing:
        print(f"[MISSING] {len(missing)}/{len(required)}")
        for s in missing:
            print("  -", repr(s))
    if leaked:
        print(f"[FORBIDDEN STILL PRESENT] {len(leaked)}/{len(forbidden)}")
        for s in leaked:
            print("  !", repr(s))
    if not missing and not leaked:
        print(
            f"OK: {len(required)} обязательных подстрок, {len(forbidden)} запрещённых отсутствуют."
        )
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
