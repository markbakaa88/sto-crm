"""Application constants and enum dictionaries for STO CRM."""

from __future__ import annotations

import os
import re

APP_NAME = "СТО CRM"
APP_VERSION = "1.17.2"
DEFAULT_PORT = 8765
MAX_BODY_BYTES = 2_000_000
REQUEST_READ_TIMEOUT_SECONDS = 10
LOOKUP_LIMIT = 5_000
SQLITE_INTEGER_MIN = -(2**63)
SQLITE_INTEGER_MAX = 2**63 - 1
MAX_NUMERIC_ABS = 1_000_000_000_000.0
MAX_FINANCIAL_TOTAL = 1_000_000_000_000.0
MIN_QUANTITY_STEP = 0.01
UPDATE_STATUS_CACHE_SECONDS = 60


def _get_env_int(key: str, default: int) -> int:
    val = os.environ.get(key)
    if val is None:
        return default
    try:
        parsed = int(val)
        return parsed if parsed >= 0 else default
    except ValueError:
        return default


MAX_BACKUP_FILES = _get_env_int("STO_CRM_MAX_BACKUP_FILES", 30)
MAX_BACKUP_TOTAL_BYTES = _get_env_int(
    "STO_CRM_MAX_BACKUP_TOTAL_BYTES", 5 * 1024 * 1024 * 1024
)
INTERNAL_ERROR_MESSAGE = (
    "Внутренняя ошибка сервера. Подробности записаны в журнал приложения."
)
GITHUB_REPOSITORY = "markbakaa88/sto-crm"
GITHUB_UPDATES_CONFIG_ENV = "STO_CRM_UPDATE_REPOSITORY"
GITHUB_UPDATE_TIMEOUT = 15
GITHUB_UPDATE_MAX_JSON_BYTES = 2 * 1024 * 1024
GITHUB_UPDATE_MAX_ASSET_BYTES = 250 * 1024 * 1024
GITHUB_RELEASE_MANIFEST_NAME = "latest.json"
EXE_ASSET_RE = re.compile(
    r"(?:^|[-_.])STO[-_]?CRM(?:[-_.]|$).*\.exe$|^STO_CRM\.exe$", re.IGNORECASE
)
MANIFEST_ASSET_RE = re.compile(
    r"(?:^|[-_.])latest(?:[-_.]|$).*\.json$|^latest\.json$", re.IGNORECASE
)
VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SENSITIVE_QUERY_RE = re.compile(
    r"([?&](?:token|access_token|bootstrap_token|csrf|csrf_token)=)([^&\s]+)",
    re.IGNORECASE,
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
TRUSTED_UPDATE_DOWNLOAD_HOSTS = {
    "api.github.com",
    "github.com",
    "github-releases.githubusercontent.com",
    "objects.githubusercontent.com",
}
MIN_VEHICLE_YEAR = 1900
PREFERRED_CHANNELS = {
    "phone": "Телефон",
    "sms": "SMS",
    "email": "Email",
    "messenger": "Мессенджер",
    "none": "Не писать",
}
ORDER_PRIORITIES = {
    "low": "Низкий",
    "normal": "Обычный",
    "high": "Высокий",
    "urgent": "Срочно",
}

ORDER_STATUSES = {
    "new": "Новый",
    "diagnostics": "Диагностика",
    "estimate": "Смета",
    "approved": "Согласован",
    "in_progress": "В работе",
    "done": "Готов",
    "closed": "Закрыт",
    "cancelled": "Отменён",
}
CONSUMING_STATUSES = {"closed"}
ORDER_STATUS_TRANSITIONS = {
    "new": {
        "diagnostics",
        "estimate",
        "approved",
        "in_progress",
        "done",
        "closed",
        "cancelled",
    },
    "diagnostics": {
        "estimate",
        "approved",
        "in_progress",
        "done",
        "closed",
        "cancelled",
    },
    "estimate": {"approved", "in_progress", "done", "closed", "cancelled"},
    "approved": {"in_progress", "done", "closed", "cancelled"},
    "in_progress": {"done", "closed", "cancelled"},
    "done": {"closed", "cancelled"},
    "closed": {"cancelled"},
    "cancelled": set(),
}

APPOINTMENT_STATUSES = {
    "scheduled": "Запланирована",
    "confirmed": "Подтверждена",
    "arrived": "Клиент приехал",
    "done": "Завершена",
    "no_show": "Не приехал",
    "cancelled": "Отменена",
}
APPOINTMENT_ACTIVE_STATUSES = {"scheduled", "confirmed", "arrived"}

ITEM_APPROVAL_STATUSES = {
    "approved": "Согласовано",
    "deferred": "Отложено",
    "declined": "Отказ",
}
BILLABLE_ITEM_STATUSES = {"approved"}

# API Rossko, MX Group, TM Parts settings
ROSSKO_KEY1 = os.environ.get("ROSSKO_KEY1", "")
ROSSKO_KEY2 = os.environ.get("ROSSKO_KEY2", "")
ROSSKO_API_URL = os.environ.get("ROSSKO_API_URL", "https://api.rossko.ru")

MX_GROUP_TOKEN = os.environ.get("MX_GROUP_TOKEN", "")
MX_GROUP_API_URL = os.environ.get("MX_GROUP_API_URL", "https://api.mxgroup.ru")

TM_PARTS_KEY = os.environ.get("TM_PARTS_KEY", "")
TM_PARTS_API_URL = os.environ.get("TM_PARTS_API_URL", "https://api.tmparts.ru")

# Default TTL of cache is 2 hours (7200 seconds)
PARTS_CACHE_TTL_HOURS = 2
PARTS_CACHE_TTL_SECONDS = PARTS_CACHE_TTL_HOURS * 3600
PARTS_API_TIMEOUT = _get_env_int("PARTS_API_TIMEOUT", 10)


def log_configuration_status() -> None:
    """Log which supplier APIs are initialized based on env vars."""
    from .runtime import safe_log
    suppliers = []
    if ROSSKO_KEY1 and ROSSKO_KEY2:
        suppliers.append("Rossko")
    if MX_GROUP_TOKEN:
        suppliers.append("MX Group")
    if TM_PARTS_KEY:
        suppliers.append("TM Parts")

    if suppliers:
        safe_log(f"Настройки внешних API автозапчастей загружены для: {', '.join(suppliers)}")
    else:
        safe_log("Настройки внешних API автозапчастей не обнаружены/не заданы в переменных окружения")
