"""Updater package interface exposing update_status and install_update_from_github."""

from __future__ import annotations

import contextlib
import re
import secrets
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from ..backup import create_backup
from ..config import APP_VERSION
from ..runtime import (
    app_executable_path,
    display_path,
    ensure_private_dir,
    github_latest_release_url,
    github_repository_url,
    normalize_github_repository,
    now_iso,
    redact_local_paths,
    updater_log_path,
    user_data_dir,
)
from .checker import (
    is_newer_version,
    latest_release_info,
    validate_sha256,
    validate_update_download_url,
)
from .installer import (
    can_install_windows_update,
    download_release_asset,
    ensure_downloaded_executable,
    ensure_real_dir,
    is_installable_update_asset,
    prune_updates_dir,
    schedule_windows_update,
)

_UPDATE_INSTALL_LOCK = threading.Lock()
_UPDATE_INSTALL_IN_PROGRESS = False
_UPDATE_INSTALL_SCHEDULED = False


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


def append_updater_log(message: str) -> None:
    try:
        path = updater_log_path()
        ensure_private_dir(path.parent)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{now_iso()} {message}\n")
    except OSError:
        pass


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
