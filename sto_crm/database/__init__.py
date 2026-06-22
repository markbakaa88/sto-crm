"""Database package exposing connection and migration APIs with backward compatibility."""

from __future__ import annotations

import sys
import types
from typing import Any

from sto_crm import runtime as _runtime

# Also explicitly import ensure_private_file_created so it's statically exposed at package scope if needed
from sto_crm.runtime import ensure_private_file_created

from . import connection as _connection
from . import migrations as _migrations
from .connection import (
    RetryingConnection,
    RetryingCursor,
    RetryingIterator,
    close_all_connections,
    connect,
    db,
    write_db,
)
from .migrations import ensure_schema, init_db

__all__ = [
    "RetryingConnection",
    "RetryingCursor",
    "RetryingIterator",
    "close_all_connections",
    "connect",
    "db",
    "ensure_schema",
    "init_db",
    "write_db",
]


class _DatabaseFacade(types.ModuleType):
    """Facade module proxy that propagates monkeypatching/mocking to submodules."""

    def __getattr__(self, name: str) -> Any:
        if name == "_locked_retry_delay":
            return _connection._locked_retry_delay
        # Route to submodules dynamically if not directly present
        if hasattr(_connection, name):
            return getattr(_connection, name)
        if hasattr(_migrations, name):
            return getattr(_migrations, name)
        if name == "ensure_private_file_created":
            return ensure_private_file_created
        raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

    def __setattr__(self, name: str, value: Any) -> None:
        if name != "_originals" and name not in self.__dict__.setdefault("_originals", {}):
            orig = None
            for module in (_connection, _migrations, _runtime):
                if hasattr(module, name):
                    orig = getattr(module, name)
                    break
            if name == "ensure_private_file_created":
                orig = ensure_private_file_created
            self.__dict__["_originals"][name] = orig

        # Route assignments to submodules to sync mock overrides
        for module in (_connection, _migrations, _runtime):
            if hasattr(module, name):
                setattr(module, name, value)
        if name == "ensure_private_file_created":
            setattr(_runtime, name, value)
            setattr(_connection, name, value)
            setattr(_migrations, name, value)
        super().__setattr__(name, value)

    def __delattr__(self, name: str) -> None:
        originals = self.__dict__.setdefault("_originals", {})
        if name in originals:
            orig_val = originals[name]
            for module in (_connection, _migrations, _runtime):
                if hasattr(module, name):
                    if orig_val is None:
                        try:
                            delattr(module, name)
                        except AttributeError:
                            pass
                    else:
                        setattr(module, name, orig_val)
            if name == "ensure_private_file_created":
                setattr(_runtime, name, orig_val)
                setattr(_connection, name, orig_val)
                setattr(_migrations, name, orig_val)
            del originals[name]
        try:
            super().__delattr__(name)
        except AttributeError:
            pass


sys.modules[__name__].__class__ = _DatabaseFacade
