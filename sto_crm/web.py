"""Embedded frontend asset loader."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from . import runtime as _runtime
from .runtime import is_frozen

_ASSET_PACKAGE = f"{__package__}.assets"
_ASSET_DIR = Path(__file__).resolve().parent / "assets"
_CSS_MARKER = "__STO_CRM_APP_CSS__"
_JS_MARKER = "__STO_CRM_APP_JS__"
FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="16" fill="#0f766e"/><path d="M17 34h30M23 24h18M24 44h16" stroke="white" stroke-width="5" stroke-linecap="round"/></svg>"""


def _read_asset(name: str) -> str:
    # В собранном exe читаем ТОЛЬКО упакованные ресурсы,
    # чтобы нельзя было подменить app.js/app.css файлом рядом с exe.
    if not is_frozen():
        filesystem_asset = _ASSET_DIR / name
        if filesystem_asset.is_file():
            return filesystem_asset.read_text(encoding="utf-8")
    return resources.files(_ASSET_PACKAGE).joinpath(name).read_text(encoding="utf-8")


read_asset = _read_asset


# В web.py больше нет константы INDEX_HTML, так как она приводила к drift контрактов.
# Вместо нее для тестов можно собирать тестовую страницу (bundled HTML с инлайненными CSS/JS)
# с помощью функции load_test_index_html().


def load_test_index_html() -> str:
    template = _read_asset("index.html")
    css = _read_asset("app.css")
    js = _read_asset("app.js")
    return template.replace(
        '<link rel="stylesheet" href="/assets/app.css">',
        f'<style nonce="__STO_CRM_CSP_NONCE__">{css}</style>',
        1,
    ).replace(
        '<script src="/assets/app.js" nonce="__STO_CRM_CSP_NONCE__" defer></script>',
        f'<script nonce="__STO_CRM_CSP_NONCE__">{js}</script>',
        1,
    )


def index_html() -> str:
    html = _read_asset("index.html")
    return html.replace("__STO_CRM_BOOTSTRAP_TOKEN__", _runtime.RUNTIME.bootstrap_token)
