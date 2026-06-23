"""Updates API routing."""

from __future__ import annotations

import threading
import time
from typing import Any

from .. import updates
from ..config import UPDATE_STATUS_CACHE_SECONDS
from ..runtime import safe_log
from .base import BaseAPIHandler

_UPDATE_STATUS_CACHE: tuple[float, dict[str, Any] | None] = (0.0, None)
_UPDATE_STATUS_LOCK = threading.Lock()


def cached_update_status() -> dict[str, Any]:
    global _UPDATE_STATUS_CACHE
    now = time.monotonic()
    expires_at, cached = _UPDATE_STATUS_CACHE
    if cached is not None and now < expires_at:
        assert isinstance(cached, dict)
        return cached
    with _UPDATE_STATUS_LOCK:
        now = time.monotonic()
        expires_at, cached = _UPDATE_STATUS_CACHE
        if cached is not None and now < expires_at:
            assert isinstance(cached, dict)
            return cached
        payload = updates.update_status()
        _UPDATE_STATUS_CACHE = (now + UPDATE_STATUS_CACHE_SECONDS, payload)
        assert isinstance(payload, dict)
        return payload


def handle_updates(
    handler: BaseAPIHandler,
    method: str,
    path: str,
    path_parts: list[str],
) -> bool:
    if len(path_parts) < 2 or path_parts[0] != "api":
        return False

    entity = path_parts[1]

    if entity == "update" and path_parts[2:3] == ["status"]:
        if method != "GET":
            handler.send_error_json(405, "Метод не поддерживается.")
            return True
        handler.validate_local_request_context()
        handler.require_access_token()
        handler.send_json(cached_update_status())
        return True

    if entity == "backup":
        if len(path_parts) != 2 or method != "POST":
            handler.send_error_json(405, "Метод не поддерживается.")
            return True
        handler.validate_local_request_context()
        handler.require_access_token()
        backup = updates.create_backup()
        handler.send_json(updates.public_backup_payload(backup) or {})
        return True

    if entity == "update" and path_parts[2:3] == ["install"]:
        if method != "POST":
            handler.send_error_json(405, "Метод не поддерживается.")
            return True
        handler.validate_local_request_context()
        handler.require_access_token()
        result = updates.install_update_from_github()
        if isinstance(result.get("backup"), dict):
            result = {
                **result,
                "backup": updates.public_backup_payload(result["backup"]) or {},
            }
        handler.send_json(result)
        if result.get("updated"):
            safe_log(
                "Получена команда перезагрузки для установки обновлений. Планирование мягкого завершения работы..."
            )
            server_reboot: Any = handler.server
            server_reboot.graceful_shutdown_flag = True
            server_reboot.shutdown_reason = "reboot"
            timer = threading.Timer(0.3, handler.server.shutdown)
            timer.daemon = True
            timer.start()
        return True

    if entity == "shutdown":
        if len(path_parts) != 2 or method != "POST":
            handler.send_error_json(405, "Метод не поддерживается.")
            return True
        handler.validate_local_request_context()
        handler.require_access_token()
        handler.send_json({"ok": True})
        safe_log(
            "Получена команда перехода в оффлайн. Планирование мягкого завершения работы..."
        )
        server_offline: Any = handler.server
        server_offline.graceful_shutdown_flag = True
        server_offline.shutdown_reason = "offline"
        timer = threading.Timer(0.3, handler.server.shutdown)
        timer.daemon = True
        timer.start()
        return True

    return False
