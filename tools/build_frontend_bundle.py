#!/usr/bin/env python3
"""Deterministic frontend bundle tool.

Собирает sto_crm/assets/app.js из модулей, указанных в sto_crm/assets/js/manifest.json.
В режиме --check проверяет идентичность собранного бандла и committed sto_crm/assets/app.js.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS_DIR = ROOT / "sto_crm" / "assets"
JS_DIR = ASSETS_DIR / "js"
MANIFEST_FILE = JS_DIR / "manifest.json"
APP_JS = ASSETS_DIR / "app.js"


def get_ordered_modules() -> list[Path]:
    """Читает manifest.json и возвращает список путей к исходным модулям."""
    if not MANIFEST_FILE.is_file():
        print(f"ERROR: Файл манифеста {MANIFEST_FILE} не найден.", file=sys.stderr)
        sys.exit(1)

    try:
        with open(MANIFEST_FILE, encoding="utf-8") as f:
            files = json.load(f)
    except Exception as e:
        print(f"ERROR: Ошибка чтения {MANIFEST_FILE}: {e}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(files, list):
        print(f"ERROR: Манифест {MANIFEST_FILE} должен содержать массив строк.", file=sys.stderr)
        sys.exit(1)

    paths = []
    for item in files:
        if not isinstance(item, str):
            print(f"ERROR: Элемент манифеста {item} не является строкой.", file=sys.stderr)
            sys.exit(1)
        mod_path = JS_DIR / item
        if not mod_path.is_file():
            print(f"ERROR: Модуль {mod_path} не найден.", file=sys.stderr)
            sys.exit(1)
        paths.append(mod_path)

    return paths


def build_bundle() -> str:
    """Собирает JS код из модулей."""
    modules = get_ordered_modules()
    parts = []
    parts.append("// STO CRM Generated Bundle - DO NOT EDIT DIRECTLY\n")
    for mod in modules:
        parts.append(f"// === Module: {mod.relative_to(JS_DIR).as_posix()} ===\n")
        parts.append(mod.read_text(encoding="utf-8").rstrip("\r\n"))
        parts.append("\n")
    return "".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="Проверить соответствие собранного бандла и app.js",
    )
    args = parser.parse_args()

    generated = build_bundle()

    if args.check:
        if not APP_JS.exists():
            print("ERROR: app.js не существует", file=sys.stderr)
            return 1
        current = APP_JS.read_text(encoding="utf-8")
        if current.strip() != generated.strip():
            print("ERROR: app.js не совпадает с генерируемым бандлом! Выполните сборку без флага --check.", file=sys.stderr)
            return 1
        print("OK: app.js полностью соответствует исходным модулям.")
        return 0

    # Запись бандла
    APP_JS.write_text(generated, encoding="utf-8")
    print("Бандл успешно пересобран.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
