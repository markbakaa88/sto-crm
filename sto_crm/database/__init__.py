"""Database package exposing connection and migration APIs with backward compatibility."""

from __future__ import annotations

import sys
import types
from typing import Any

from sto_crm import runtime as _runtime
from sto_crm.runtime import (
    clean_multiline,
    ensure_private_dir,
    ensure_private_file,
    ensure_private_file_created,
    now_iso,
    parse_int,
    safe_log,
)

from . import connection as _connection
from . import migrations as _migrations
from .connection import (
    RetryingConnection,
    RetryingCursor,
    RetryingIterator,
    _locked_retry_delay,
    _open_connections,
    _open_connections_lock,
    _retry_locked,
    close_all_connections,
    connect,
    db,
    write_db,
)
from .migrations import (
    _next_archive_table_name,
    _seed_demo_data,
    _table_exists,
    active_duplicate_values,
    archive_removed_table,
    drop_removed_tables,
    ensure_column,
    ensure_schema,
    ensure_unique_index,
    init_db,
    normalize_legacy_unique_values,
    normalized_unique_sql,
    resolve_active_duplicate_values,
    unique_order_number_for_migration,
)

__all__ = [
    "RetryingConnection",
    "RetryingCursor",
    "RetryingIterator",
    "_locked_retry_delay",
    "_next_archive_table_name",
    "_open_connections",
    "_open_connections_lock",
    "_retry_locked",
    "_seed_demo_data",
    "_table_exists",
    "active_duplicate_values",
    "archive_removed_table",
    "clean_multiline",
    "close_all_connections",
    "connect",
    "db",
    "drop_removed_tables",
    "ensure_column",
    "ensure_private_dir",
    "ensure_private_file",
    "ensure_private_file_created",
    "ensure_schema",
    "ensure_unique_index",
    "init_db",
    "normalize_legacy_unique_values",
    "normalized_unique_sql",
    "now_iso",
    "parse_int",
    "resolve_active_duplicate_values",
    "safe_log",
    "unique_order_number_for_migration",
    "write_db",
]


class _DatabaseFacade(types.ModuleType):
    """Facade module proxy that propagates monkeypatching/mocking to submodules."""

    def __getattr__(self, name: str) -> Any:
        # Route to submodules dynamically if not directly present
        if name in (
            "ensure_private_dir",
            "ensure_private_file_created",
            "ensure_private_file",
            "now_iso",
            "parse_int",
            "safe_log",
            "clean_multiline",
        ):
            return getattr(_runtime, name)
        if hasattr(_connection, name):
            return getattr(_connection, name)
        if hasattr(_migrations, name):
            return getattr(_migrations, name)
        raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

    def __setattr__(self, name: str, value: Any) -> None:
        # Route assignments to submodules to sync mock overrides
        for module in (_connection, _migrations, _runtime):
            if hasattr(module, name):
                setattr(module, name, value)
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _DatabaseFacade
