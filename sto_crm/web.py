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


def load_index_html() -> str:
    template = _read_asset("index.html")
    return template.replace(_CSS_MARKER, _read_asset("app.css"), 1).replace(
        _JS_MARKER, _read_asset("app.js"), 1
    )


INDEX_HTML = load_index_html()


def index_html() -> str:
    html = INDEX_HTML if is_frozen() else load_index_html()
    return html.replace(
        "__STO_CRM_BOOTSTRAP_TOKEN__", _runtime.RUNTIME.bootstrap_token
    )
