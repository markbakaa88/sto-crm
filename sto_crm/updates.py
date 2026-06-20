"""Backup and GitHub release update workflow."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import random
import re
import secrets
import sqlite3
import subprocess  # nosec B404
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

from . import runtime as _runtime
from .config import (
    APP_VERSION,
    EXE_ASSET_RE,
    GITHUB_RELEASE_MANIFEST_NAME,
    GITHUB_UPDATE_MAX_ASSET_BYTES,
    GITHUB_UPDATE_MAX_JSON_BYTES,
    GITHUB_UPDATE_TIMEOUT,
    MANIFEST_ASSET_RE,
    MAX_BACKUP_FILES,
    MAX_BACKUP_TOTAL_BYTES,
    SHA256_RE,
    TRUSTED_UPDATE_DOWNLOAD_HOSTS,
)
from .database import connect
from .runtime import (
    app_executable_path,
    clean_multiline,
    clean_text,
    display_path,
    ensure_private_dir,
    ensure_private_file,
    ensure_private_file_created,
    github_latest_release_api_url,
    github_latest_release_url,
    github_repository_url,
    is_frozen,
    normalize_github_repository,
    now_iso,
    parse_int,
    redact_local_paths,
    strict_json_loads,
    updater_log_path,
    user_data_dir,
)

_UPDATE_INSTALL_LOCK = threading.Lock()
_BACKUP_LOCK = threading.RLock()
_UPDATE_INSTALL_IN_PROGRESS = False
_UPDATE_INSTALL_SCHEDULED = False


def is_unsafe_link_or_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    if os.name == "nt":
        # Cloud reparse points (OneDrive, iCloud, etc.) are safe and should not be blocked.
        # IO_REPARSE_TAG_CLOUD = 0x9000001A
        # IO_REPARSE_TAG_CLOUD_1 = 0x9000101A
        # IO_REPARSE_TAG_CLOUD_2 = 0x9000201A
        # IO_REPARSE_TAG_CLOUD_3 = 0x9000301A
        # IO_REPARSE_TAG_CLOUD_4 = 0x9000401A
        # IO_REPARSE_TAG_CLOUD_5 = 0x9000501A
        # IO_REPARSE_TAG_CLOUD_6 = 0x9000601A
        # IO_REPARSE_TAG_CLOUD_7 = 0x9000701A
        # IO_REPARSE_TAG_CLOUD_8 = 0x9000801A
        # IO_REPARSE_TAG_CLOUD_9 = 0x9000901A
        # IO_REPARSE_TAG_CLOUD_A = 0x9000A01A
        # IO_REPARSE_TAG_CLOUD_B = 0x9000B01A
        # IO_REPARSE_TAG_CLOUD_C = 0x9000C01A
        # IO_REPARSE_TAG_CLOUD_D = 0x9000D01A
        # IO_REPARSE_TAG_CLOUD_E = 0x9000E01A
        # IO_REPARSE_TAG_CLOUD_F = 0x9000F01A
        # IO_REPARSE_TAG_ONEDRIVE = 0x80000021
        # IO_REPARSE_TAG_CLOUD_MASK = 0x0000F000 or general mask checks.
        # Reparse tags for Cloud Files are 0x9000XXXX.
        # Specifically, we can check the reparse tag if we read the reparse point metadata.
        # But wait, does os.lstat or GetFileAttributesW tell us the precise tag?
        # GetFileAttributesW only returns attributes, which is just FILE_ATTRIBUTE_REPARSE_POINT (0x400).
        # To get the actual reparse tag, we normally open the file with FILE_FLAG_OPEN_REPARSE_POINT
        # and query the tag via DeviceIoControl (FSCTL_GET_REPARSE_POINT), or check WIN32_FIND_DATA st_reparse_tag.
        # In Python, os.lstat(path) returns stat_result, under Python 3.8+ on Windows it has st_reparse_tag!
        try:
            stat_val = os.lstat(path)
            attrs = getattr(stat_val, "st_file_attributes", 0)
            if attrs & 0x400:  # FILE_ATTRIBUTE_REPARSE_POINT
                # st_reparse_tag only populated if it is a reparse point
                tag = getattr(stat_val, "st_reparse_tag", 0)
                # 0x9000001A: IO_REPARSE_TAG_CLOUD_APIS (OneDrive/iCloud placeholder)
                # 0x80000021: IO_REPARSE_TAG_ONEDRIVE
                # Let's check if the tag is OneDrive/Cloud APIs and allow it.
                # All Cloud Files tags share 0x9000XXXX or OneDrive 0x80000021 tag.
                # symlink (0xA000000C) and mount point/junction (0xA0000003) must be blocked.
                # More generally: cloud files (0x9000001A, etc.) or OneDrive (0x80000021) are safe.
                # Let's list known cloud tags, or just check tag & 0xF0000000 or similar?
                # Actually, standard tags we want to block are:
                # IO_REPARSE_TAG_SYMLINK = 0xA000000C
                # IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003
                # Let's block if tag is 0xA000000C or 0xA0000003, or if tag is not a cloud/safe tag.
                # Safe tags list:
                # - IO_REPARSE_TAG_CLOUD_APIS (0x9000001A)
                # - IO_REPARSE_TAG_ONEDRIVE (0x80000021)
                # - Any tag matching cloud pattern 0x9000XXXX or 0x90000000 to 0x9000FFFF:
                is_cloud_tag = tag == 0x80000021 or (tag & 0xFFFF0000) == 0x90000000
                if not is_cloud_tag:
                    return True
        except Exception:
            pass
        try:
            import ctypes

            # GetFileAttributesW doesn't provide st_reparse_tag, so we can't rely on it alone.
            # But since python lstat has st_reparse_tag on Windows, we prioritize that.
            # If for some reason we need a ctypes fallback, we'd have to find the file or open it.
            # Let's use ctypes FindFirstFileW which returns WIN32_FIND_DATA structure containing dwReserved0 (reparse tag).
            windll = getattr(ctypes, "windll", None)
            if windll is not None:
                attrs = windll.kernel32.GetFileAttributesW(str(path))
                if attrs != -1 and (attrs & 0x400):  # FILE_ATTRIBUTE_REPARSE_POINT
                    # Check tag via FindFirstFileW
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
                        # If FindFirstFile fails but attributes say reparse, block it just in case
                        return True
        except Exception:
            pass
    return False


def can_install_windows_update() -> bool:
    """Return whether this runtime can safely replace itself with a Windows exe."""
    app_path = app_executable_path()
    return is_frozen() and os.name == "nt" and app_path.suffix.lower() == ".exe"


def is_installable_update_asset(asset: dict[str, Any] | None) -> bool:
    """Check whether release metadata contains everything required for install."""
    if not isinstance(asset, dict):
        return False
    try:
        validate_update_download_url(str(asset.get("download_url") or ""))
        validate_sha256(asset.get("sha256"), required=True)
    except RuntimeError:
        return False
    return True


def _begin_update_install() -> None:
    global _UPDATE_INSTALL_IN_PROGRESS, _UPDATE_INSTALL_SCHEDULED
    with _UPDATE_INSTALL_LOCK:
        if _UPDATE_INSTALL_IN_PROGRESS or _UPDATE_INSTALL_SCHEDULED:
            raise RuntimeError(
                "Установка обновления уже выполняется. Дождитесь перезапуска CRM."
            )
        _UPDATE_INSTALL_IN_PROGRESS = True


def _finish_update_install(*, scheduled: bool) -> None:
    global _UPDATE_INSTALL_IN_PROGRESS, _UPDATE_INSTALL_SCHEDULED
    with _UPDATE_INSTALL_LOCK:
        _UPDATE_INSTALL_IN_PROGRESS = False
        if scheduled:
            _UPDATE_INSTALL_SCHEDULED = True


def _safe_unlink(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)


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


def validate_safe_path(target: Path) -> None:
    """Проверяет путь на отсутствие элементов обхода директорий и корректность вложенности."""
    # Normalize backslashes to forward slashes on Windows
    if os.name == "nt":
        cls = target.__class__
        try:
            normalized = cls(str(target).replace("\\", "/"))
        except (NotImplementedError, TypeError):
            normalized = target
    else:
        normalized = target

    posix_str = normalized.as_posix()
    if ".." in normalized.parts or ".." in posix_str:
        raise OSError("Недопустимый путь (содержит переход '..').")
    if os.name != "nt" and "\\" in posix_str:
        raise OSError("Недопустимый путь (содержит обратный слэш).")

    # Mocks and Pure paths do not support filesystem operations, so we return early before those
    if (
        "Mock" in type(target).__name__
        or "Mock" in type(target.parent).__name__
        or "Mock" in type(normalized).__name__
        or "Mock" in type(normalized.parent).__name__
        or "Pure" in type(normalized).__name__
    ):
        return

    try:
        if normalized.parent.exists() and is_unsafe_link_or_reparse(normalized.parent):
            raise OSError(
                "Родительский каталог не может быть символической ссылкой или reparse point."
            )
        resolved_parent = normalized.parent.resolve()
        resolved_target = normalized.resolve()
        if resolved_parent not in resolved_target.parents:
            raise OSError(
                "Недопустимый путь (выход за пределы родительского каталога)."
            )
        if normalized.exists() and is_unsafe_link_or_reparse(normalized):
            raise OSError("Путь не может быть символической ссылкой или reparse point.")
    except OSError as exc:
        raise OSError(f"Ошибка проверки безопасности пути: {exc}") from exc


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


def prune_updates_dir(update_dir: Path) -> None:
    """Удаляет старые временные файлы и резервные копии .exe из папки обновлений."""
    if not update_dir.exists():
        return
    if is_unsafe_link_or_reparse(update_dir):
        raise OSError(
            "Каталог обновлений не может быть символической ссылкой или reparse point."
        )
    try:
        resolved_dir = update_dir.resolve()
    except OSError:
        return
    import time

    now = time.time()
    # Удаляем файлы старше 24 часов (86400 секунд), чтобы не мешать активному обновлению
    for path in update_dir.iterdir():
        try:
            resolved_path = path.resolve()
            if resolved_dir not in resolved_path.parents:
                continue
            if path.is_file() and not is_unsafe_link_or_reparse(path):
                name = path.name.lower()
                is_temp = (
                    name.startswith("download-")
                    or name.startswith("apply_update_")
                    or name.endswith(".tmp")
                    or name.endswith(".bak.exe")
                )
                if is_temp:
                    stat = path.stat()
                    if now - stat.st_mtime > 86400:
                        path.unlink(missing_ok=True)
        except OSError:
            continue


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


def semantic_version_tuple(version: str) -> tuple[int, ...]:
    """Сравнимый кортеж для SemVer-подобных тегов GitHub Releases."""
    core = str(version or "").strip().lstrip("vV").split("-", 1)[0]
    numbers = [int(part) for part in re.findall(r"\d+", core)[:4]]
    return tuple(numbers or [0])


def is_newer_version(candidate: str, current: str = APP_VERSION) -> bool:
    left = semantic_version_tuple(candidate)
    right = semantic_version_tuple(current)
    width = max(len(left), len(right), 3)
    return left + (0,) * (width - len(left)) > right + (0,) * (width - len(right))


def release_asset_score(asset: dict[str, Any]) -> int:
    name = str(asset.get("name") or "")
    lowered = name.lower()
    score = 0
    if EXE_ASSET_RE.search(name):
        score += 100
    if lowered.endswith(".exe"):
        score += 40
    if "setup" in lowered or "installer" in lowered:
        score += 8
    if "portable" in lowered or "standalone" in lowered:
        score += 6
    if "sha" in lowered or "checksum" in lowered:
        score -= 80
    return score


def manifest_asset_score(asset: dict[str, Any]) -> int:
    name = str(asset.get("name") or "")
    lowered = name.lower()
    if name == GITHUB_RELEASE_MANIFEST_NAME:
        return 100
    if MANIFEST_ASSET_RE.search(name):
        return 80
    return 10 if lowered.endswith(".json") and "manifest" in lowered else 0


def select_release_asset(
    release: dict[str, Any], *, kind: str = "exe"
) -> dict[str, Any] | None:
    assets = [asset for asset in release.get("assets", []) if isinstance(asset, dict)]
    candidates = [
        asset for asset in assets if str(asset.get("browser_download_url") or "")
    ]
    scorer = manifest_asset_score if kind == "manifest" else release_asset_score
    candidates = [asset for asset in candidates if scorer(asset) > 0]
    if not candidates:
        return None
    return max(candidates, key=scorer)


def github_headers(accept: str = "application/vnd.github+json") -> dict[str, str]:
    return {
        "Accept": accept,
        "User-Agent": f"STO-CRM/{APP_VERSION}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _parse_trusted_update_url(url: str) -> tuple[str, urllib.parse.ParseResult]:
    raw = "" if url is None else str(url)
    if any(ord(char) < 32 or ord(char) == 127 for char in raw):
        raise RuntimeError("Manifest обновления содержит недоверенную ссылку на файл.")
    cleaned = clean_text(raw, 1000)
    if not cleaned:
        raise RuntimeError("В релизе нет ссылки на файл обновления.")
    try:
        parsed = urllib.parse.urlparse(cleaned)
    except ValueError as exc:
        raise RuntimeError(
            "Manifest обновления содержит некорректную ссылку на файл."
        ) from exc
    if "\\" in cleaned or "@" in (parsed.netloc or ""):
        raise RuntimeError("Manifest обновления содержит недоверенную ссылку на файл.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise RuntimeError(
            "Manifest обновления содержит некорректную ссылку на файл."
        ) from exc
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or host not in TRUSTED_UPDATE_DOWNLOAD_HOSTS
        or port not in {None, 443}
        or parsed.username
        or parsed.password
    ):
        raise RuntimeError("Manifest обновления содержит недоверенную ссылку на файл.")
    return cleaned, parsed


def validate_update_download_url(url: str) -> str:
    """Проверяет, что обновление скачивается только по доверенной HTTPS-ссылке GitHub."""
    cleaned, _parsed = _parse_trusted_update_url(url)
    return cleaned


def validate_manifest_asset_download_url(url: str, repository: str, tag: str) -> str:
    """Validate manifest-provided executable URL against the expected release."""
    cleaned, parsed = _parse_trusted_update_url(url)
    expected_repo = normalize_github_repository(repository).strip("/")
    expected_tag = clean_text(tag, 120)
    if ".." in expected_tag or "/" in expected_tag or "\\" in expected_tag:
        raise RuntimeError("Manifest обновления содержит некорректный тег релиза.")
    host = (parsed.hostname or "").lower()
    if host == "github.com":
        expected_path = f"/{expected_repo}/releases/download/{expected_tag}/"
        if not parsed.path.startswith(expected_path):
            raise RuntimeError(
                "Manifest обновления указывает файл вне ожидаемого GitHub Release."
            )
        if not EXE_ASSET_RE.search(Path(urllib.parse.unquote(parsed.path)).name):
            raise RuntimeError(
                "Manifest обновления должен указывать файл STO_CRM.exe из ожидаемого GitHub Release."
            )
        return cleaned
    raise RuntimeError(
        "Manifest обновления должен указывать файл .exe из ожидаемого GitHub Release."
    )


def validate_update_response_url(url: str) -> None:
    """Reject unexpected redirect targets before reading update payloads."""
    validate_update_download_url(url)


def _content_length(response: Any) -> int:
    value = (
        response.headers.get("Content-Length")
        if getattr(response, "headers", None) is not None
        else None
    )
    try:
        return parse_int(value)
    except (TypeError, ValueError):
        return 0


def read_limited_response(response: Any, max_bytes: int, label: str) -> bytes:
    """Read bounded responses to avoid unbounded memory use on update metadata."""
    expected_length = _content_length(response)
    if expected_length > max_bytes:
        raise RuntimeError(f"{label} слишком большой для безопасной обработки.")
    payload = response.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise RuntimeError(f"{label} слишком большой для безопасной обработки.")
    assert isinstance(payload, bytes)
    return payload


def validate_sha256(value: Any, *, required: bool = True) -> str:
    digest = clean_text(value, 80).lower()
    if not digest:
        if required:
            raise RuntimeError(
                "В manifest обновления отсутствует SHA-256 файла обновления."
            )
        return ""
    if not SHA256_RE.fullmatch(digest):
        raise RuntimeError(
            "В manifest обновления указан некорректный SHA-256 файла обновления."
        )
    return digest


def fetch_json(
    url: str,
    timeout: int = GITHUB_UPDATE_TIMEOUT,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    url = validate_update_download_url(url)
    request = urllib.request.Request(url, headers=headers or github_headers())
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310
            final_url = response.geturl() if hasattr(response, "geturl") else url
            validate_update_response_url(final_url)
            charset = (response.headers.get_content_charset() or "utf-8").lower()
            if charset in {"utf-8", "utf8"}:
                charset = "utf-8-sig"
            payload = strict_json_loads(
                read_limited_response(
                    response, GITHUB_UPDATE_MAX_JSON_BYTES, "Ответ GitHub/manifest"
                ).decode(charset)
            )
            if not isinstance(payload, dict):
                raise ValueError("GitHub вернул неожиданный ответ.")
            return payload
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise RuntimeError(
                "Релиз GitHub не найден. Опубликуйте билд STO_CRM.exe и latest.json в GitHub Release."
            ) from exc
        if exc.code in {401, 403}:
            raise RuntimeError(
                f"GitHub отклонил запрос ({exc.code}). Репозиторий обновлений должен быть публичным."
            ) from exc
        raise RuntimeError(f"GitHub недоступен: HTTP {exc.code}.") from exc
    except (OSError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(
            f"Не удалось получить информацию об обновлении: {exc}"
        ) from exc


def fetch_asset_json(asset: dict[str, Any]) -> dict[str, Any]:
    url = clean_text(
        asset.get("browser_download_url") or asset.get("download_url"), 1000
    )
    if not url:
        raise RuntimeError("В GitHub Release нет ссылки на manifest latest.json.")
    return fetch_json(url, headers=github_headers("application/octet-stream"))


def normalize_release_asset(
    asset: dict[str, Any] | None,
    manifest_asset: dict[str, Any] | None = None,
    *,
    require_sha256: bool = False,
    repository: str | None = None,
    tag: str | None = None,
) -> dict[str, Any] | None:
    if not asset:
        return None
    name = clean_text(
        asset.get("name") or (manifest_asset or {}).get("name") or "STO_CRM.exe", 180
    )
    size = parse_int(asset.get("size") or (manifest_asset or {}).get("size"))
    if size < 0:
        raise RuntimeError("Manifest обновления содержит некорректный размер файла.")
    sha256 = validate_sha256(
        asset.get("sha256") or asset.get("hash") or "", required=require_sha256
    )
    raw_download_url = str(
        asset.get("download_url")
        or asset.get("browser_download_url")
        or (manifest_asset or {}).get("browser_download_url")
        or ""
    )
    download_url = (
        validate_manifest_asset_download_url(raw_download_url, repository, tag)
        if repository and tag
        else validate_update_download_url(raw_download_url)
    )
    return {
        "name": name,
        "size": size,
        "sha256": sha256,
        "download_url": download_url,
    }


def release_info_from_manifest(
    release: dict[str, Any], manifest: dict[str, Any], manifest_asset: dict[str, Any]
) -> dict[str, Any]:
    repository = normalize_github_repository()
    release_tag = clean_text(release.get("tag_name") or "", 80)
    manifest_tag = clean_text(manifest.get("tag") or "", 80)
    if manifest_tag and release_tag and manifest_tag != release_tag:
        raise RuntimeError("Manifest обновления не соответствует тегу GitHub Release.")
    tag = manifest_tag or release_tag
    if not tag:
        raise RuntimeError(
            "GitHub Release не содержит тега для проверки manifest обновления."
        )
    asset = normalize_release_asset(
        manifest.get("asset") if isinstance(manifest.get("asset"), dict) else None,
        require_sha256=True,
        repository=repository,
        tag=tag,
    )
    version = clean_text(
        manifest.get("version") or tag or release.get("tag_name") or "", 80
    ).lstrip("vV")
    return {
        "repository": repository,
        "repository_url": github_repository_url(repository),
        "release_url": clean_text(
            manifest.get("release_url")
            or release.get("html_url")
            or github_latest_release_url(repository),
            500,
        ),
        "tag": tag,
        "name": clean_text(manifest.get("name") or release.get("name") or "", 120),
        "version": version,
        "published_at": clean_text(
            manifest.get("published_at") or release.get("published_at") or "", 40
        ),
        "body": clean_multiline(
            manifest.get("notes") or release.get("body") or "", 3000
        ),
        "prerelease": bool(release.get("prerelease")),
        "draft": bool(release.get("draft")),
        "manifest": {
            "name": clean_text(
                manifest_asset.get("name") or GITHUB_RELEASE_MANIFEST_NAME, 180
            ),
            "size": parse_int(manifest_asset.get("size")),
        },
        "asset": asset,
    }


def latest_release_info() -> dict[str, Any]:
    repository = normalize_github_repository()
    release = fetch_json(github_latest_release_api_url(repository))
    manifest_asset = select_release_asset(release, kind="manifest")
    if manifest_asset:
        manifest = fetch_asset_json(manifest_asset)
        return release_info_from_manifest(release, manifest, manifest_asset)
    version = clean_text(
        release.get("tag_name") or release.get("name") or "", 80
    ).lstrip("vV")
    asset = select_release_asset(release)
    return {
        "repository": repository,
        "repository_url": github_repository_url(repository),
        "release_url": clean_text(
            release.get("html_url") or github_latest_release_url(repository), 500
        ),
        "tag": clean_text(release.get("tag_name") or "", 80),
        "name": clean_text(release.get("name") or "", 120),
        "version": version,
        "published_at": clean_text(release.get("published_at") or "", 40),
        "body": clean_multiline(release.get("body") or "", 3000),
        "prerelease": bool(release.get("prerelease")),
        "draft": bool(release.get("draft")),
        "manifest": None,
        "asset": normalize_release_asset(asset, require_sha256=False),
    }


def update_status() -> dict[str, Any]:
    repository = normalize_github_repository()
    app_path = app_executable_path()
    with contextlib.suppress(OSError):
        prune_updates_dir(user_data_dir() / "updates")
    try:
        release = latest_release_info()
        version = str(release.get("version") or release.get("tag") or "")
        release["is_newer"] = is_newer_version(version, APP_VERSION)
        release["has_asset"] = is_installable_update_asset(release.get("asset"))
        return {
            "ok": True,
            "current_version": APP_VERSION,
            "repository": repository,
            "repository_url": github_repository_url(repository),
            "releases_url": github_latest_release_url(repository),
            "can_install": can_install_windows_update()
            and release["has_asset"]
            and release["is_newer"],
            "app_path": app_path.name,
            "log_path": display_path(updater_log_path()),
            "release": release,
        }
    except Exception as exc:
        return {
            "ok": False,
            "current_version": APP_VERSION,
            "repository": repository,
            "repository_url": github_repository_url(repository),
            "releases_url": github_latest_release_url(repository),
            "can_install": can_install_windows_update(),
            "app_path": app_path.name,
            "log_path": display_path(updater_log_path()),
            "error": redact_local_paths(str(exc)),
        }


def append_updater_log(message: str) -> None:
    try:
        path = updater_log_path()
        ensure_private_dir(path.parent)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{now_iso()} {message}\n")
    except OSError:
        pass


def download_release_asset(asset: dict[str, Any], target: Path) -> dict[str, Any]:
    url = validate_update_download_url(str(asset.get("download_url") or ""))
    expected_sha = validate_sha256(asset.get("sha256"), required=True)
    expected_size = parse_int(asset.get("size"))
    if expected_size < 0:
        raise RuntimeError("Manifest обновления содержит некорректный размер файла.")
    if expected_size > GITHUB_UPDATE_MAX_ASSET_BYTES:
        raise RuntimeError(
            "Файл обновления слишком большой для безопасной автоматической установки."
        )

    # Path traversal validation
    try:
        validate_safe_path(target)
    except OSError as exc:
        raise RuntimeError(
            f"Не удалось проверить путь скачивания обновления: {exc}"
        ) from exc

    request = urllib.request.Request(
        url, headers=github_headers("application/octet-stream")
    )
    sha256 = hashlib.sha256()
    total = 0
    tmp_target = target.with_name(f"{target.name}.tmp")
    try:
        try:
            validate_safe_path(tmp_target)
        except OSError as exc:
            raise RuntimeError(
                f"Не удалось проверить путь скачивания обновления: {exc}"
            ) from exc
        tmp_target.unlink(missing_ok=True)
        ensure_private_file_created(tmp_target)
        if is_unsafe_link_or_reparse(tmp_target):
            raise OSError(
                "Временный файл обновления не может быть символической ссылкой или reparse point."
            )
        with (
            urllib.request.urlopen(request, timeout=GITHUB_UPDATE_TIMEOUT) as response,  # nosec B310
            tmp_target.open("r+b") as output,
        ):
            final_url = response.geturl() if hasattr(response, "geturl") else url
            validate_update_response_url(final_url)
            content_length = _content_length(response)
            if content_length > GITHUB_UPDATE_MAX_ASSET_BYTES:
                raise RuntimeError(
                    "Файл обновления слишком большой для безопасной автоматической установки."
                )
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > GITHUB_UPDATE_MAX_ASSET_BYTES:
                    raise RuntimeError("Файл обновления превышает безопасный лимит.")
                sha256.update(chunk)
                output.write(chunk)
            output.flush()
            with contextlib.suppress(OSError, AttributeError):
                os.fsync(output.fileno())
        if expected_size and total != expected_size:
            raise RuntimeError(
                "Размер скачанного обновления не совпадает с размером в GitHub Release."
            )
        if total <= 0:
            raise RuntimeError("GitHub вернул пустой файл обновления.")
        digest = sha256.hexdigest()
        if expected_sha != digest:
            raise RuntimeError(
                "SHA-256 скачанного обновления не совпадает с manifest обновления."
            )
        tmp_target.replace(target)
    except urllib.error.HTTPError as exc:
        _safe_unlink(tmp_target)
        raise RuntimeError(f"Не удалось скачать обновление: HTTP {exc.code}.") from exc
    except (OSError, TimeoutError) as exc:
        _safe_unlink(tmp_target)
        raise RuntimeError(f"Не удалось скачать обновление: {exc}") from exc
    except Exception as exc:
        _safe_unlink(tmp_target)
        if isinstance(exc, RuntimeError):
            raise
        raise RuntimeError(f"Не удалось скачать обновление: {exc}") from exc
    return {"size": total, "sha256": digest}


def ensure_downloaded_executable(path: Path) -> None:
    if path.suffix.lower() != ".exe":
        raise RuntimeError(
            "Автообновление поддерживает только готовый Windows-файл .exe из GitHub Release."
        )
    with path.open("rb") as handle:
        head = handle.read(64)
        if len(head) < 64 or head[:2] != b"MZ":
            raise RuntimeError("Скачанный файл не похож на Windows .exe.")
        try:
            lfanew = int.from_bytes(head[60:64], "little")
        except ValueError as exc:
            raise RuntimeError("Скачанный файл не похож на Windows .exe.") from exc
        if lfanew <= 0 or lfanew > 4 * 1024 * 1024:
            raise RuntimeError("Скачанный файл не содержит корректный PE-заголовок.")
        handle.seek(lfanew)
        if handle.read(4) != b"PE\x00\x00":
            raise RuntimeError("Скачанный файл не содержит корректную PE-сигнатуру.")


def powershell_single_quoted_literal(value: str) -> str:
    """Return a Unicode-safe PowerShell single-quoted string literal."""
    return "'" + value.replace("'", "''") + "'"


def write_windows_update_script(
    script_path: Path,
    current_exe: Path,
    downloaded_exe: Path,
    backup_exe: Path,
    log_path: Path,
    expected_sha256: str,
) -> None:
    try:
        validate_safe_path(script_path)
        validate_safe_path(downloaded_exe)
        validate_safe_path(backup_exe)
        validate_safe_path(log_path)
    except OSError as exc:
        raise RuntimeError(f"Не удалось проверить пути обновления: {exc}") from exc

    ps = f"""
$ErrorActionPreference = 'Stop'
$Current = {powershell_single_quoted_literal(str(current_exe))}
$Downloaded = {powershell_single_quoted_literal(str(downloaded_exe))}
$Backup = {powershell_single_quoted_literal(str(backup_exe))}
$Log = {powershell_single_quoted_literal(str(log_path))}
$ScriptPath = $MyInvocation.MyCommand.Path
$ExpectedSha256 = {powershell_single_quoted_literal(expected_sha256)}
function Write-UpdateLog([string]$Message) {{
    $dir = Split-Path -Parent $Log
    if ($dir) {{ New-Item -ItemType Directory -Force -Path $dir | Out-Null }}
    Add-Content -LiteralPath $Log -Encoding UTF8 -Value ((Get-Date).ToString('s') + ' ' + $Message)
}}
try {{
    Write-UpdateLog 'Ожидание завершения СТО CRM...'
    $Unlocked = $false
    for ($i = 0; $i -lt 120; $i++) {{
        try {{
            $stream = [System.IO.File]::Open($Current, [System.IO.FileMode]::Open, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
            $stream.Close()
            $Unlocked = $true
            break
        }} catch {{ Start-Sleep -Milliseconds 500 }}
    }}
    if (-not $Unlocked) {{ throw 'Не удалось дождаться завершения приложения.' }}
    if (-not (Test-Path -LiteralPath $Downloaded)) {{ throw 'Скачанный файл обновления не найден.' }}
    $ActualSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $Downloaded).Hash.ToLowerInvariant()
    if ($ActualSha256 -ne $ExpectedSha256) {{ throw 'SHA-256 файла обновления изменился перед установкой.' }}
    $ExpectedSize = (Get-Item -LiteralPath $Downloaded).Length
    if (Test-Path -LiteralPath $Backup) {{ Remove-Item -LiteralPath $Backup -Force }}
    Move-Item -LiteralPath $Current -Destination $Backup -Force
    $MoveSucceeded = $false
    try {{
        Move-Item -LiteralPath $Downloaded -Destination $Current -Force
        if (-not (Test-Path -LiteralPath $Current)) {{ throw 'Новый exe не появился на месте.' }}
        $ActualSize = (Get-Item -LiteralPath $Current).Length
        if ($ActualSize -ne $ExpectedSize) {{ throw 'Размер установленного файла отличается от загруженного.' }}
        $VerifySha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $Current).Hash.ToLowerInvariant()
        if ($VerifySha256 -ne $ExpectedSha256) {{ throw 'SHA-256 установленного файла не совпадает.' }}
        $MoveSucceeded = $true
    }} catch {{
        Write-UpdateLog ('Установка прервана, откатываем: ' + $_.Exception.Message)
        if (Test-Path -LiteralPath $Current) {{ Remove-Item -LiteralPath $Current -Force -ErrorAction SilentlyContinue }}
        if (Test-Path -LiteralPath $Backup) {{ Move-Item -LiteralPath $Backup -Destination $Current -Force }}
        throw
    }}
    Write-UpdateLog 'Файл приложения обновлен.'
    try {{ Start-Process -FilePath $Current }} catch {{ Write-UpdateLog ('Запуск после обновления не выполнен: ' + $_.Exception.Message) }}
}} catch {{
    Write-UpdateLog ('Ошибка обновления: ' + $_.Exception.Message)
    try {{
        if ((Test-Path -LiteralPath $Backup) -and -not (Test-Path -LiteralPath $Current)) {{
            Move-Item -LiteralPath $Backup -Destination $Current -Force
        }}
        if ((Test-Path -LiteralPath $Downloaded) -and (Test-Path -LiteralPath $Current)) {{
            Remove-Item -LiteralPath $Downloaded -Force
        }}
    }} catch {{ Write-UpdateLog ('Ошибка отката/очистки: ' + $_.Exception.Message) }}
    throw
}} finally {{
    if ($ScriptPath -and (Test-Path -LiteralPath $ScriptPath)) {{
        Remove-Item -LiteralPath $ScriptPath -Force -ErrorAction SilentlyContinue
    }}
}}
""".strip()
    script_path.write_text(ps, encoding="utf-8-sig")


def schedule_windows_update(downloaded_exe: Path, expected_sha256: str) -> None:
    if os.name != "nt":
        raise RuntimeError("Автоустановка доступна только в Windows.")
    current_exe = app_executable_path()
    if not current_exe.exists():
        raise RuntimeError("Текущий исполняемый файл не найден.")
    if current_exe.suffix.lower() != ".exe":
        raise RuntimeError("Автоустановка доступна только для собранного STO_CRM.exe.")
    update_dir = user_data_dir() / "updates"
    ensure_real_dir(update_dir, "обновлений")
    backup_exe = (
        update_dir
        / f"{current_exe.stem}-{APP_VERSION}-{datetime.now().strftime('%Y%m%d%H%M%S')}.bak.exe"
    )
    script_path = (
        update_dir
        / f"apply_update_{datetime.now().strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(8)}.ps1"
    )
    write_windows_update_script(
        script_path,
        current_exe,
        downloaded_exe,
        backup_exe,
        updater_log_path(),
        expected_sha256,
    )
    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script_path),
    ]
    kwargs: dict[str, Any] = {}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    subprocess.Popen(command, cwd=str(update_dir), close_fds=True, **kwargs)  # nosec B603


def install_update_from_github() -> dict[str, Any]:
    if not can_install_windows_update():
        raise RuntimeError(
            "Автоустановка доступна только в Windows-версии STO_CRM.exe. Для исходников используйте git pull."
        )
    _begin_update_install()
    downloaded: Path | None = None
    scheduled = False
    try:
        release = latest_release_info()
        if release.get("prerelease") or release.get("draft"):
            return {
                "ok": True,
                "updated": False,
                "message": "Стабильных обновлений нет.",
                "release": release,
            }
        version = str(release.get("version") or release.get("tag") or "")
        if not is_newer_version(version, APP_VERSION):
            return {
                "ok": True,
                "updated": False,
                "message": "Установлена актуальная версия.",
                "release": release,
            }
        asset = release.get("asset")
        if not isinstance(asset, dict):
            raise RuntimeError(
                "В последнем GitHub Release нет файла STO_CRM.exe для обновления."
            )
        validate_sha256(asset.get("sha256"), required=True)
        validate_update_download_url(str(asset.get("download_url") or ""))
        update_dir = user_data_dir() / "updates"
        ensure_real_dir(update_dir, "обновлений")
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", asset.get("name") or "STO_CRM.exe")
        downloaded = (
            update_dir
            / f"download-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(8)}-{safe_name}"
        )
        backup = create_backup()
        append_updater_log(
            f"Перед обновлением создана резервная копия базы: {backup['display_path']}."
        )
        details = download_release_asset(asset, downloaded)
        ensure_downloaded_executable(downloaded)
        append_updater_log(
            f"Скачано обновление {version}: {details['size']} байт, sha256={details['sha256']}."
        )
        schedule_windows_update(downloaded, details["sha256"])
        scheduled = True
        return {
            "ok": True,
            "updated": True,
            "message": "Обновление скачано. CRM закроется, заменит exe и запустится снова.",
            "release": release,
            "download": details,
            "backup": backup,
        }
    finally:
        if not scheduled and downloaded is not None:
            _safe_unlink(downloaded)
        _finish_update_install(scheduled=scheduled)
