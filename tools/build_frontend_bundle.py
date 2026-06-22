#!/usr/bin/env python3
"""Deterministic frontend bundle tool.

Собирает sto_crm/assets/app.js из модулей в sto_crm/assets/js/ или проверяет
их идентичность в режиме --check. В данной фазе C1 мы создаем scaffold:
все наши JS-файлы пока лежат в app.js, но мы готовим manifest и инструменты.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS_DIR = ROOT / "sto_crm" / "assets"
JS_DIR = ASSETS_DIR / "js"
APP_JS = ASSETS_DIR / "app.js"


def get_ordered_modules() -> list[Path]:
    """Возвращает список файлов модулей в порядке следования для сборки.

    Для фазы C1 все исходники временно остаются в самом app.js, а в js/* пока пусто.
    Если js/* пуст или не существует, сборщик/чекер считает, что app.js является единственным
    источником, и просто проходит проверку. Это гарантирует green-to-green на этапе C1.
    """
    if not JS_DIR.is_dir():
        return []

    # В будущем здесь будет чтение манифеста или упорядоченный обход js/**/*.js
    # На фазе C1 мы просто возвращаем пустой список или файлы, если они есть.
    modules = sorted(JS_DIR.glob("**/*.js"))
    return modules


def build_bundle() -> str:
    """Собирает JS код из модулей или возвращает текущий app.js, если модулей нет."""
    modules = get_ordered_modules()
    if not modules:
        if APP_JS.exists():
            return APP_JS.read_text(encoding="utf-8")
        return ""

    parts = []
    parts.append("// STO CRM Generated Bundle - DO NOT EDIT DIRECTLY\n")
    for mod in modules:
        parts.append(f"// === Module: {mod.relative_to(ASSETS_DIR).as_posix()} ===\n")
        parts.append(mod.read_text(encoding="utf-8"))
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
            print("ERROR: app.js не существует")
            return 1
        current = APP_JS.read_text(encoding="utf-8")
        if current.strip() != generated.strip():
            print("ERROR: app.js не совпадает с генерируемым бандлом!")
            return 1
        print("OK: app.js полностью соответствует исходным модулям.")
        return 0

    # Запись бандла (только если есть из чего собирать)
    if get_ordered_modules():
        APP_JS.write_text(generated, encoding="utf-8")
        print("Бандл успешно пересобран.")
    else:
        print("Модули не найдены. Оставляем app.js нетронутым.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
