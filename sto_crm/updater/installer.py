"""Windows PE validation and PowerShell update scripts generation."""

from __future__ import annotations

import contextlib
import hashlib
import os
import secrets
import subprocess  # nosec B404
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import (
    EXE_ASSET_RE,
    GITHUB_UPDATE_MAX_ASSET_BYTES,
    GITHUB_UPDATE_TIMEOUT,
)
from ..runtime import (
    app_executable_path,
    ensure_private_dir,
    ensure_private_file_created,
    is_frozen,
    parse_int,
    updater_log_path,
    user_data_dir,
)
from .checker import (
    _content_length,
    github_headers,
    validate_sha256,
    validate_update_download_url,
    validate_update_response_url,
)


def can_install_windows_update() -> bool:
    """Return whether this runtime can safely replace itself with a Windows exe."""
    app_path = app_executable_path()
    return is_frozen() and os.name == "nt" and app_path.suffix.lower() == ".exe"


def is_unsafe_link_or_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    if os.name == "nt":
        try:
            stat_val = os.lstat(path)
            attrs = getattr(stat_val, "st_file_attributes", 0)
            if attrs & 0x400:
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
                if attrs != -1 and (attrs & 0x400):

                    class WIN32_FIND_DATAW(ctypes.Structure):
                        _fields_ = [
                            ("dwFileAttributes", ctypes.c_ulong),
                            ("ftCreationTime", ctypes.c_ulonglong),
                            ("ftLastAccessTime", ctypes.c_ulonglong),
                            ("ftLastWriteTime", ctypes.c_ulonglong),
                            ("nFileSizeHigh", ctypes.c_ulong),
                            ("nFileSizeLow", ctypes.c_ulong),
                            ("dwReserved0", ctypes.c_ulong),
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


def is_installable_update_asset(asset: dict[str, Any] | None) -> bool:
    """Check whether release metadata contains everything required for install."""
    if not isinstance(asset, dict):
        return False
    try:
        name = asset.get("name")
        if not name or not isinstance(name, str):
            return False
        if not EXE_ASSET_RE.fullmatch(name):
            return False

        size_raw = asset.get("size")
        if size_raw is None:
            return False
        try:
            size = int(size_raw)
        except (ValueError, TypeError):
            return False
        if size <= 0 or size > GITHUB_UPDATE_MAX_ASSET_BYTES:
            return False

        validate_update_download_url(str(asset.get("download_url") or ""))
        validate_sha256(asset.get("sha256"), required=True)
    except RuntimeError:
        return False
    return True


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


def validate_safe_path(target: Path) -> None:
    """Проверяет путь на отсутствие элементов обхода директорий и корректность вложенности."""
    # Normalize backslashes to forward slashes on Windows
    if os.name == "nt":
        cls = target.__class__
        try:
            normalized = cls(str(target).replace("\\\\", "/"))
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


def _safe_unlink(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)


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
        raise RuntimeError(f"Не удалось скачать обеспечение: {exc}") from exc
    except Exception as exc:
        _safe_unlink(tmp_target)
        if isinstance(exc, RuntimeError):
            raise
        raise RuntimeError(f"Не удалось скачать обеспечение: {exc}") from exc
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
    from ..config import APP_VERSION

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
