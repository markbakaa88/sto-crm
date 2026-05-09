from __future__ import annotations

"""Embedded frontend asset loader."""

from importlib import resources
from pathlib import Path

_ASSET_PACKAGE = f"{__package__}.assets"
_ASSET_DIR = Path(__file__).resolve().parent / "assets"
_CSS_MARKER = "__STO_CRM_APP_CSS__"
_JS_MARKER = "__STO_CRM_APP_JS__"


def _read_asset(name: str) -> str:
    filesystem_asset = _ASSET_DIR / name
    if filesystem_asset.is_file():
        return filesystem_asset.read_text(encoding="utf-8")
    return resources.files(_ASSET_PACKAGE).joinpath(name).read_text(encoding="utf-8")


def load_index_html() -> str:
    template = _read_asset("index.html")
    return template.replace(_CSS_MARKER, _read_asset("app.css"), 1).replace(_JS_MARKER, _read_asset("app.js"), 1)


INDEX_HTML = load_index_html()
