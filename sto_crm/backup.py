"""Database backup operations for STO CRM."""

from __future__ import annotations

import contextlib
import os
import random
import sqlite3
import threading
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

from . import runtime as _runtime
from .config import (
    MAX_BACKUP_FILES,
    MAX_BACKUP_TOTAL_BYTES,
)
from .database import connect
from .runtime import (
    display_path,
    ensure_private_dir,
    ensure_private_file,
    ensure_private_file_created,
)

_BACKUP_LOCK = threading.RLock()


def is_unsafe_link_or_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    if os.name == "nt":
        # Cloud reparse points (OneDrive, iCloud, etc.) are safe and should not be blocked.
        try:
            stat_val = os.lstat(path)
            attrs = getattr(stat_val, "st_file_attributes", 0)
            if attrs & 0x400:  # FILE_ATTRIBUTE_REPARSE_POINT
                tag = getattr(stat_val, "st_reparse_tag", 0)
                is_cloud_tag = tag == 0x80000021 or (tag & 0xFFFF0000) == 0x90000000
                if not is_cloud_tag:
                    return True
        except Exception:
            pass
        try:
            import ctypes

            windll = getattr(ctypes, "windll", None)
            if windll is not None:
                attrs = windll.kernel32.GetFileAttributesW(str(path))
                if attrs != -1 and (attrs & 0x400):  # FILE_ATTRIBUTE_REPARSE_POINT

                    class WIN32_FIND_DATAW(ctypes.Structure):
                        _fields_ = [
                            ("dwFileAttributes", ctypes.c_ulong),
                            ("ftCreationTime", ctypes.c_ulonglong),
                            ("ftLastAccessTime", ctypes.c_ulonglong),
                            ("ftLastWriteTime", ctypes.c_ulonglong),
                            ("nFileSizeHigh", ctypes.c_ulong),
                            ("nFileSizeLow", ctypes.c_ulong),
                            ("dwReserved0", ctypes.c_ulong),  # st_reparse_tag
                            ("dwReserved1", ctypes.c_ulong),
                            ("cFileName", ctypes.c_wchar * 260),
                            ("cAlternateFileName", ctypes.c_wchar * 14),
                        ]

                    find_data = WIN32_FIND_DATAW()
                    handle = windll.kernel32.FindFirstFileW(
                        str(path), ctypes.byref(find_data)
                    )
                    if handle != -1:
                        windll.kernel32.FindClose(handle)
                        tag = find_data.dwReserved0
                        is_cloud_tag = (
                            tag == 0x80000021 or (tag & 0xFFFF0000) == 0x90000000
                        )
                        if not is_cloud_tag:
                            return True
                    else:
                        return True
        except Exception:
            pass
    return False


def ensure_real_dir(directory: Path, name: str) -> None:
    """Создаёт и валидирует директорию, защищая от атак с символическими ссылками."""
    if directory.exists():
        if is_unsafe_link_or_reparse(directory):
            raise OSError(
                f"Каталог {name} не может быть символической ссылкой или reparse point."
            )
        if not directory.is_dir():
            raise OSError(f"Путь к каталогу {name} занят файлом.")
    ensure_private_dir(directory)
    if is_unsafe_link_or_reparse(directory):
        raise OSError(
            f"Каталог {name} не может быть символической ссылкой или reparse point."
        )
    if not directory.is_dir():
        raise OSError(f"Каталог {name} не является директорией.")


def ensure_real_backup_dir(backup_dir: Path) -> None:
    """Create and validate the backup directory without following link attacks."""
    ensure_real_dir(backup_dir, "резервных копий")


def prune_backups(backup_dir: Path, keep_path: Path | None = None) -> None:
    """Keep automatic SQLite backups bounded so manual backup spam cannot fill the disk."""
    with _BACKUP_LOCK:
        if MAX_BACKUP_FILES <= 0 and MAX_BACKUP_TOTAL_BYTES <= 0:
            return
        keep_resolved = None
        if keep_path is not None:
            with contextlib.suppress(OSError):
                keep_resolved = keep_path.resolve()
        if backup_dir.exists() and is_unsafe_link_or_reparse(backup_dir):
            raise OSError(
                "Каталог резервных копий не может быть символической ссылкой или reparse point."
            )
        try:
            resolved_dir = backup_dir.resolve()
        except OSError:
            return
        backups: list[tuple[float, int, Path, bool]] = []
        for path in backup_dir.glob("sto_crm_backup_*.sqlite3"):
            try:
                stat = path.stat()
                resolved = path.resolve()
                if resolved_dir not in resolved.parents:
                    continue
            except OSError:
                continue
            if path.is_file() and not is_unsafe_link_or_reparse(path):
                backups.append(
                    (stat.st_mtime, stat.st_size, path, resolved == keep_resolved)
                )
        backups.sort(key=lambda row: (row[3], row[0]), reverse=True)

        total = 0
        for index, (_mtime, size, path, is_keep_path) in enumerate(backups):
            total += size
            too_many = MAX_BACKUP_FILES > 0 and index >= MAX_BACKUP_FILES
            too_large = MAX_BACKUP_TOTAL_BYTES > 0 and total > MAX_BACKUP_TOTAL_BYTES
            if not is_keep_path and (too_many or too_large):
                with contextlib.suppress(OSError):
                    path.unlink(missing_ok=True)


def create_backup() -> dict[str, Any]:
    with _BACKUP_LOCK:
        backup_dir = _runtime.RUNTIME.db_path.parent / "backups"
        target = (
            backup_dir
            / f"sto_crm_backup_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.sqlite3"
        )
        try:
            ensure_real_backup_dir(backup_dir)
            resolved_dir = backup_dir.resolve()
            resolved_target = target.resolve()
            if resolved_dir not in resolved_target.parents:
                raise OSError("Недопустимый путь к файлу резервной копии.")
            if target.exists() and is_unsafe_link_or_reparse(target):
                raise OSError(
                    "Файл резервной копии не может быть символической ссылкой или reparse point."
                )
            ensure_private_file_created(target)
            if is_unsafe_link_or_reparse(target):
                raise OSError(
                    "Файл резервной копии не может быть символической ссылкой или reparse point."
                )
            max_retries = 5
            base_delay = 0.05
            for attempt in range(max_retries):
                try:
                    with (
                        closing(connect()) as source,
                        closing(sqlite3.connect(target, timeout=30)) as destination,
                    ):
                        destination.execute("PRAGMA busy_timeout = 30000")
                        source.backup(destination)
                    break
                except sqlite3.OperationalError as exc:
                    if "locked" in str(exc).lower() and attempt < max_retries - 1:
                        delay = base_delay * (1.5**attempt) + random.uniform(0, 0.02)
                        time.sleep(delay)
                        continue
                    raise
            ensure_private_file(target)
            size = target.stat().st_size
            prune_backups(backup_dir, keep_path=target)
        except (OSError, sqlite3.Error) as exc:
            with contextlib.suppress(OSError):
                target.unlink(missing_ok=True)
            raise RuntimeError(
                f"Не удалось создать резервную копию базы: {exc}"
            ) from exc
        return {
            "path": str(target),
            "display_path": display_path(target),
            "filename": target.name,
            "size": size,
            "created_at": datetime.fromtimestamp(target.stat().st_mtime).isoformat(
                timespec="minutes"
            ),
        }


def latest_backup_info() -> dict[str, Any] | None:
    with _BACKUP_LOCK:
        backup_dir = _runtime.RUNTIME.db_path.parent / "backups"
        try:
            if backup_dir.exists() and is_unsafe_link_or_reparse(backup_dir):
                raise OSError(
                    "Каталог резервных копий не может быть символической ссылкой или reparse point."
                )
            resolved_dir = backup_dir.resolve()
            backups = []
            for path in backup_dir.glob("sto_crm_backup_*.sqlite3"):
                try:
                    resolved_path = path.resolve()
                    if resolved_dir not in resolved_path.parents:
                        continue
                    if path.is_file() and not is_unsafe_link_or_reparse(path):
                        backups.append(path)
                except OSError:
                    continue
            if not backups:
                return None
            latest = max(backups, key=lambda path: path.stat().st_mtime)
            stat = latest.stat()
        except OSError:
            return None
        return {
            "path": str(latest),
            "display_path": display_path(latest),
            "filename": latest.name,
            "size": stat.st_size,
            "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(
                timespec="minutes"
            ),
        }


def public_backup_payload(info: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return backup metadata that is safe to expose to the browser UI."""
    if not info:
        return None
    return {
        key: info[key]
        for key in ("display_path", "filename", "size", "created_at")
        if key in info
    }
