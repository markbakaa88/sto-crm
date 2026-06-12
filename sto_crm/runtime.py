"""Runtime state, path resolution, parsing helpers and safe logging."""

from __future__ import annotations

import contextlib
import json
import math
import os
import re
import secrets
import sys
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import (
    GITHUB_REPOSITORY,
    GITHUB_UPDATES_CONFIG_ENV,
    MAX_NUMERIC_ABS,
    MIN_VEHICLE_YEAR,
    SENSITIVE_QUERY_RE,
    SQLITE_INTEGER_MAX,
    SQLITE_INTEGER_MIN,
    VIN_RE,
)


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def user_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "STO_CRM"
    if os.name == "nt":
        return Path.home() / "AppData" / "Local" / "STO_CRM"
    return Path.home() / ".local" / "share" / "sto_crm"


def ensure_private_dir(directory: Path) -> None:
    """Create an application data directory without exposing CRM data to other Unix users."""
    directory.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        with contextlib.suppress(OSError):
            directory.chmod(0o700)


def ensure_private_file(path: Path) -> None:
    """Tighten SQLite/backup file permissions on Unix-like systems."""
    if os.name != "nt" and path.exists():
        with contextlib.suppress(OSError):
            path.chmod(0o600)


def ensure_private_file_created(path: Path) -> None:
    """Create a sensitive local file with restrictive permissions from the first open."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        path.touch(exist_ok=True)
        return
    flags = os.O_WRONLY | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    os.close(fd)
    ensure_private_file(path)


def directory_writable(directory: Path) -> bool:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / f".sto_crm_write_test_{os.getpid()}.tmp"
        probe.write_text("ok", encoding="utf-8")
        ensure_private_file(probe)
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def is_user_data_directory(directory: Path) -> bool:
    try:
        return directory.resolve() == user_data_dir().resolve()
    except OSError:
        return False


def default_db_path() -> Path:
    candidates = (
        [user_data_dir(), app_dir()] if is_frozen() else [app_dir(), user_data_dir()]
    )
    for directory in candidates:
        if directory_writable(directory):
            if is_user_data_directory(directory):
                ensure_private_dir(directory)
            return directory / "sto_crm.sqlite3"
    fallback = user_data_dir()
    ensure_private_dir(fallback)
    return fallback / "sto_crm.sqlite3"


def display_path(path: Path) -> str:
    """Показывает путь пользователю без раскрытия имени домашнего профиля."""
    try:
        resolved = path.resolve()
        home = Path.home().resolve()
        return "~" if resolved == home else f"~/{resolved.relative_to(home).as_posix()}"
    except (OSError, ValueError):
        return path.name or str(path)


def app_executable_path() -> Path:
    """Возвращает путь к текущему исполняемому артефакту приложения."""
    if is_frozen():
        return Path(sys.executable).resolve()
    return (Path(__file__).resolve().parent.parent / "sto_crm.py").resolve()


def updater_log_path() -> Path:
    return user_data_dir() / "updater.log"


def normalize_github_repository(value: str | None = None) -> str:
    """Нормализует owner/repo из переменной окружения или URL GitHub."""
    raw = clean_text(
        value or os.environ.get(GITHUB_UPDATES_CONFIG_ENV) or GITHUB_REPOSITORY, 220
    )
    if not raw:
        return GITHUB_REPOSITORY
    if raw.startswith(("http://", "https://")):
        parsed = urllib.parse.urlparse(raw)
        parts = [part for part in parsed.path.strip("/").split("/") if part]
        if len(parts) >= 2 and (parsed.hostname or "").lower() == "github.com":
            raw = "/".join(parts[:2])
    raw = raw.removesuffix(".git").strip("/")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", raw):
        return GITHUB_REPOSITORY
    return raw


def github_repository_url(repository: str | None = None) -> str:
    return f"https://github.com/{normalize_github_repository(repository)}"


def github_latest_release_api_url(repository: str | None = None) -> str:
    return f"https://api.github.com/repos/{normalize_github_repository(repository)}/releases/latest"


def github_latest_release_url(repository: str | None = None) -> str:
    return f"{github_repository_url(repository)}/releases/latest"


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def parse_float(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        normalized = (
            str(value)
            .replace("\u00a0", "")
            .replace("\u202f", "")
            .replace(" ", "")
            .replace(",", ".")
        )
        parsed = float(normalized)
        return parsed if math.isfinite(parsed) else default
    except (TypeError, ValueError):
        return default


def parse_int(value: Any, default: int = 0) -> int:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return int(value)
    try:
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value) if math.isfinite(value) else default
        normalized = (
            str(value)
            .replace("\u00a0", "")
            .replace("\u202f", "")
            .replace(" ", "")
            .strip()
        )
        if re.fullmatch(r"[+-]?\d+", normalized):
            return int(normalized)
        if re.fullmatch(r"[+-]?\d+[\.,]\d+", normalized):
            parsed = float(normalized.replace(",", "."))
            return int(parsed) if math.isfinite(parsed) else default
        return default
    except (TypeError, ValueError, OverflowError):
        return default


def is_blank(value: Any) -> bool:
    return (
        value is None or (isinstance(value, str) and not value.strip()) or value == ""
    )


def parse_float_field(value: Any, field_name: str, default: float = 0.0) -> float:
    """Строгий парсер пользовательского денежного/количественного ввода."""
    if is_blank(value):
        return default
    try:
        normalized = (
            str(value)
            .replace("\u00a0", "")
            .replace("\u202f", "")
            .replace(" ", "")
            .replace(",", ".")
            .strip()
        )
        parsed = float(normalized)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"Некорректное число: {field_name}.") from exc
    if not math.isfinite(parsed) or abs(parsed) > MAX_NUMERIC_ABS:
        raise ValueError(f"Некорректное число: {field_name}.")
    return parsed


def parse_int_field(value: Any, field_name: str, default: int = 0) -> int:
    """Строгий парсер пользовательского целочисленного ввода."""
    if is_blank(value):
        return default
    if isinstance(value, bool):
        raise ValueError(f"Некорректное целое число: {field_name}.")
    try:
        if isinstance(value, int):
            parsed = value
        elif isinstance(value, float):
            if not math.isfinite(value) or not value.is_integer():
                raise ValueError
            parsed = int(value)
        else:
            normalized = (
                str(value)
                .replace("\u00a0", "")
                .replace("\u202f", "")
                .replace(" ", "")
                .strip()
            )
            if re.fullmatch(r"[+-]?\d+", normalized):
                parsed = int(normalized)
            elif re.fullmatch(r"[+-]?\d+[\.,]\d+", normalized):
                numeric = float(normalized.replace(",", "."))
                if not math.isfinite(numeric) or not numeric.is_integer():
                    raise ValueError
                parsed = int(numeric)
            else:
                raise ValueError
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"Некорректное целое число: {field_name}.") from exc
    if parsed < SQLITE_INTEGER_MIN or parsed > SQLITE_INTEGER_MAX:
        raise ValueError(f"Некорректное целое число: {field_name}.")
    return parsed


def clean_text(value: Any, max_len: int = 500, default: str = "") -> str:
    text = default if value is None else str(value)
    text = " ".join(text.replace("\x00", "").split())
    return text[:max_len]


def clean_multiline(value: Any, max_len: int = 4000) -> str:
    text = "" if value is None else str(value).replace("\x00", "")
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)[:max_len]


def parse_datetime_local(value: Any, field_name: str, required: bool = False) -> str:
    text = clean_text(value, 40)
    if not text:
        if required:
            raise ValueError(f"Укажите дату: {field_name}.")
        return ""
    normalized = text.replace(" ", "T")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", normalized):
        raise ValueError(f"Некорректная дата: {field_name}.")
    try:
        return datetime.fromisoformat(normalized).isoformat(timespec="minutes")
    except ValueError as exc:
        raise ValueError(f"Некорректная дата: {field_name}.") from exc


def parse_date_iso(value: Any, field_name: str, required: bool = False) -> str:
    text = clean_text(value, 40)
    if not text:
        if required:
            raise ValueError(f"Укажите дату: {field_name}.")
        return ""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        raise ValueError(f"Некорректная дата: {field_name}.")
    try:
        return datetime.fromisoformat(text).date().isoformat()
    except ValueError as exc:
        raise ValueError(f"Некорректная дата: {field_name}.") from exc


def validate_vehicle_year(value: Any) -> int:
    year = parse_int_field(value, "год автомобиля")
    if not year:
        return 0
    max_year = datetime.now().year + 1
    if year < MIN_VEHICLE_YEAR or year > max_year:
        raise ValueError(
            f"Некорректный год автомобиля. Укажите год от {MIN_VEHICLE_YEAR} до {max_year}."
        )
    return year


def validate_vin(value: str) -> str:
    vin = clean_text(value, 40).upper()
    if vin and not VIN_RE.fullmatch(vin):
        raise ValueError(
            "Некорректный VIN. VIN должен содержать 17 символов без I, O и Q."
        )
    return vin


def money(value: Any) -> str:
    amount = parse_float(value)
    return f"{amount:,.2f} ₽".replace(",", "\u202f").replace(".", ",")


def csv_cell(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    # Spreadsheet apps can hide formulas behind leading whitespace, BOMs or
    # direction/zero-width marks.  Strip those characters only for detection and
    # keep the original cell value intact for export fidelity.
    dangerous_leading = " \t\r\n\v\f\ufeff\u200b\u200c\u200d\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
    stripped = value.lstrip(dangerous_leading)
    if stripped and stripped[0] in ("=", "+", "-", "@"):
        return "'" + value
    return value


def sql_limit(limit: int | None) -> tuple[str, list[Any]]:
    if limit is None:
        return "", []
    return "LIMIT ?", [max(parse_int(limit, 1000), 1)]


def search_needle(q: str) -> str:
    """Return a LIKE pattern for a literal case-insensitive search term.

    User-entered ``%`` and ``_`` are data, not SQL wildcards.  All queries that
    use this helper must add ``ESCAPE '\\'`` to the corresponding LIKE clause.
    """
    escaped = (
        str(q or "")
        .casefold()
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    return f"%{escaped}%"


def redact_sensitive_query(message: str) -> str:
    """Маскирует токены из URL перед выводом в локальный журнал."""
    return SENSITIVE_QUERY_RE.sub(r"\1***", message)


_LOCAL_PATH_RE = re.compile(
    r"(?P<path>\\\\[^\s\"'<>|]+|[A-Za-z]:[\\/][^\s\"'<>|]+|(?<![:/])/(?:[^/\s\"'<>|]+/)+[^\s\"'<>|]+)"
)


def redact_local_paths(message: str) -> str:
    """Hide absolute local filesystem paths before text is sent to the browser."""

    def replace_path(match: re.Match[str]) -> str:
        raw = match.group("path")
        trailing = ""
        while raw and raw[-1] in ".,;:)]}":
            trailing = raw[-1] + trailing
            raw = raw[:-1]
        if not raw:
            return trailing
        if raw.startswith("\\\\") or re.match(r"^[A-Za-z]:[\\/]", raw):
            filename = raw.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
            return (filename or "локальный файл") + trailing
        return display_path(Path(raw)) + trailing

    return _LOCAL_PATH_RE.sub(replace_path, str(message))


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"JSON содержит недопустимое значение {value}.")


def _strict_json_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("JSON содержит недопустимое числовое значение.")
    return parsed


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON содержит повторяющийся ключ.")
        result[key] = value
    return result


def strict_json_loads(text: str) -> Any:
    """Parse external JSON without NaN/Infinity or duplicate object keys."""
    return json.loads(
        text,
        parse_constant=_reject_json_constant,
        parse_float=_strict_json_float,
        object_pairs_hook=_strict_json_object,
    )


def safe_log(message: str) -> None:
    stream = getattr(sys, "stdout", None)
    if not stream:
        return
    try:
        text = re.sub(
            r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]",
            "?",
            redact_sensitive_query(str(message)),
        )
        text = text.replace("\r", "\\r").replace("\n", "\\n")
        stream.write(text + "\n")
        stream.flush()
    # Логгер не должен ронять приложение, если stdout закрыт/перенаправлен в сломанное состояние.
    except Exception:  # nosec B110
        pass


@dataclass(frozen=True)
class Runtime:
    db_path: Path
    start_time: float
    csrf_token: str = ""
    access_token: str = ""
    bootstrap_token: str = ""


RUNTIME = Runtime(
    db_path=default_db_path(),
    start_time=time.time(),
    csrf_token=secrets.token_urlsafe(32),
    access_token=secrets.token_urlsafe(32),
    bootstrap_token=secrets.token_urlsafe(32),
)
