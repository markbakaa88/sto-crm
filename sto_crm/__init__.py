"""Public compatibility facade for STO CRM.

Historically the project exposed almost everything from one `sto_crm.py` module.
The implementation is now split by responsibility, while this package keeps the
old `import sto_crm` API stable for tests, scripts and local integrations.

All standard-library symbols that used to live at module level (``sto_crm.os``,
``sto_crm.datetime``, ``sto_crm.sys`` и т.д.) публикуются автоматически через
``_publish_module_symbols`` из сабмодулей, поэтому дублирующие
``import foo as foo`` здесь не нужны и только засоряют линтеров.
"""

from __future__ import annotations

import sys
import types
from typing import Any

from . import backup as backup
from . import catalog as catalog
from . import cli as cli
from . import config as config
from . import database as database
from . import export as export
from . import http_server as http_server
from . import logging_config as logging_config
from . import printing as printing
from . import queries as queries
from . import reports as reports
from . import runtime as runtime
from . import seed as seed
from . import services as services
from . import updater as updater
from . import updates as updates
from . import validation as validation
from . import web as web

_IMPLEMENTATION_MODULES = (
    config,
    runtime,
    catalog,
    database,
    validation,
    services,
    queries,
    reports,
    export,
    backup,
    updates,
    updater,
    printing,
    web,
    http_server,
    cli,
    seed,
    logging_config,
)


def _publish_module_symbols() -> None:
    for module in _IMPLEMENTATION_MODULES:
        for name, value in vars(module).items():
            if name.startswith("_"):
                continue
            globals()[name] = value


_publish_module_symbols()


_SENTINEL = object()


class _StoCrmFacade(types.ModuleType):
    """Module type that keeps legacy monkeypatching semantics intact."""

    def __getattribute__(self, name: str) -> Any:
        if name == "RUNTIME":
            return runtime.RUNTIME
        if name == "INDEX_HTML":
            return web.load_test_index_html()
        return super().__getattribute__(name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "RUNTIME":
            runtime.RUNTIME = value
        if name != "_originals" and name not in self.__dict__.setdefault("_originals", {}):
            # Pre-record sub-facades first using their current values before first mutation
            for m in _IMPLEMENTATION_MODULES:
                if type(m) is not types.ModuleType:
                    try:
                        if hasattr(m, name):
                            current_val = getattr(m, name)
                            setattr(m, name, current_val)
                    except Exception:
                        pass

            facade_orig = self.__dict__.get(name, _SENTINEL)
            modules_orig = {}
            for module in _IMPLEMENTATION_MODULES:
                if hasattr(module, name):
                    modules_orig[module] = getattr(module, name)
            self.__dict__["_originals"][name] = {
                "facade": facade_orig,
                "modules": modules_orig,
            }

        for module in _IMPLEMENTATION_MODULES:
            if hasattr(module, name):
                setattr(module, name, value)
        super().__setattr__(name, value)

    def __delattr__(self, name: str) -> None:
        originals = self.__dict__.setdefault("_originals", {})
        if name in originals:
            orig_data = originals[name]
            if name == "RUNTIME":
                runtime.RUNTIME = orig_data["modules"].get(runtime, orig_data["facade"])
            for module, orig_val in orig_data["modules"].items():
                if type(module) is not types.ModuleType:
                    try:
                        delattr(module, name)
                    except AttributeError:
                        pass
                else:
                    setattr(module, name, orig_val)

            facade_orig = orig_data["facade"]
            del originals[name]
            if facade_orig is _SENTINEL:
                try:
                    super().__delattr__(name)
                except AttributeError:
                    pass
            else:
                super().__setattr__(name, facade_orig)
        else:
            try:
                super().__delattr__(name)
            except AttributeError:
                pass


sys.modules[__name__].__class__ = _StoCrmFacade

__all__ = tuple(sorted(name for name in globals() if not name.startswith("_")))
