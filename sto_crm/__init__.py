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
from . import updates as updates
from . import updater as updater
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


class _StoCrmFacade(types.ModuleType):
    """Module type that keeps legacy monkeypatching semantics intact."""

    def __getattribute__(self, name: str) -> Any:
        if name == "RUNTIME":
            return runtime.RUNTIME
        return super().__getattribute__(name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "RUNTIME":
            runtime.RUNTIME = value
        for module in _IMPLEMENTATION_MODULES:
            if hasattr(module, name):
                setattr(module, name, value)
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _StoCrmFacade

__all__ = tuple(sorted(name for name in globals() if not name.startswith("_")))
