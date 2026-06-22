"""Backward-compatible facade to updates that internally routes to backup and updater."""

from __future__ import annotations

import os
import sqlite3
import sys
import time
import types
from pathlib import Path
from typing import Any

# Import modules to expose functions
from sto_crm import backup as _backup
from sto_crm import database as _database
from sto_crm import runtime as _runtime
from sto_crm import updater as _updater

# Explicitly expose functions and variables for static analysis and clean exports
from sto_crm.backup import (
    MAX_BACKUP_FILES,
    MAX_BACKUP_TOTAL_BYTES,
    create_backup,
    ensure_real_backup_dir,
    ensure_real_dir,
    is_unsafe_link_or_reparse,
    latest_backup_info,
    prune_backups,
    public_backup_payload,
)
from sto_crm.database import connect
from sto_crm.runtime import (
    app_executable_path,
    parse_int,
    updater_log_path,
    user_data_dir,
)
from sto_crm.updater import (
    append_updater_log,
    install_update_from_github,
    update_status,
)
from sto_crm.updater import checker as _checker
from sto_crm.updater import installer as _installer
from sto_crm.updater.checker import (
    _content_length,
    fetch_asset_json,
    fetch_json,
    github_headers,
    is_newer_version,
    latest_release_info,
    manifest_asset_score,
    normalize_release_asset,
    read_limited_response,
    release_asset_score,
    release_info_from_manifest,
    select_release_asset,
    semantic_version_tuple,
    validate_manifest_asset_download_url,
    validate_sha256,
    validate_update_download_url,
    validate_update_response_url,
)
from sto_crm.updater.installer import (
    can_install_windows_update,
    download_release_asset,
    ensure_downloaded_executable,
    is_installable_update_asset,
    prune_updates_dir,
    schedule_windows_update,
    validate_safe_path,
    write_windows_update_script,
)

# Expose internal update install state variables as well
_UPDATE_INSTALL_IN_PROGRESS = False
_UPDATE_INSTALL_SCHEDULED = False

__all__ = [
    "MAX_BACKUP_FILES",
    "MAX_BACKUP_TOTAL_BYTES",
    "_UPDATE_INSTALL_IN_PROGRESS",
    "_UPDATE_INSTALL_SCHEDULED",
    "Path",
    "_content_length",
    "_database",
    "_runtime",
    "app_executable_path",
    "append_updater_log",
    "can_install_windows_update",
    "connect",
    "create_backup",
    "download_release_asset",
    "ensure_downloaded_executable",
    "ensure_real_backup_dir",
    "ensure_real_dir",
    "fetch_asset_json",
    "fetch_json",
    "github_headers",
    "install_update_from_github",
    "is_installable_update_asset",
    "is_newer_version",
    "is_unsafe_link_or_reparse",
    "latest_backup_info",
    "latest_release_info",
    "manifest_asset_score",
    "normalize_release_asset",
    "os",
    "parse_int",
    "prune_backups",
    "prune_updates_dir",
    "public_backup_payload",
    "read_limited_response",
    "release_asset_score",
    "release_info_from_manifest",
    "schedule_windows_update",
    "select_release_asset",
    "semantic_version_tuple",
    "sqlite3",
    "time",
    "update_status",
    "updater_log_path",
    "user_data_dir",
    "validate_manifest_asset_download_url",
    "validate_safe_path",
    "validate_sha256",
    "validate_update_download_url",
    "validate_update_response_url",
    "write_windows_update_script",
]


class _UpdatesFacade(types.ModuleType):
    """Facade module proxy that propagates monkeypatching/mocking to submodules."""

    def __getattr__(self, name: str) -> Any:
        # Route to submodules dynamically if not directly present
        if hasattr(_updater, name):
            return getattr(_updater, name)
        if hasattr(_backup, name):
            return getattr(_backup, name)
        if hasattr(_checker, name):
            return getattr(_checker, name)
        if hasattr(_installer, name):
            return getattr(_installer, name)
        raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

    def __setattr__(self, name: str, value: Any) -> None:
        # Route assignments to submodules to sync mock overrides
        for module in (_backup, _updater, _checker, _installer, _runtime, _database):
            if hasattr(module, name):
                setattr(module, name, value)
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _UpdatesFacade
