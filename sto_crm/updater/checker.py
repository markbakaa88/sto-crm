"""GitHub releases update checker logic."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from ..config import (
    APP_VERSION,
    EXE_ASSET_RE,
    GITHUB_RELEASE_MANIFEST_NAME,
    GITHUB_UPDATE_MAX_JSON_BYTES,
    GITHUB_UPDATE_TIMEOUT,
    MANIFEST_ASSET_RE,
    SHA256_RE,
    TRUSTED_UPDATE_DOWNLOAD_HOSTS,
)
from ..runtime import (
    clean_multiline,
    clean_text,
    github_latest_release_api_url,
    github_latest_release_url,
    github_repository_url,
    normalize_github_repository,
    parse_int,
    strict_json_loads,
)


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
    if EXE_ASSET_RE.fullmatch(name):
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
        from pathlib import Path

        if not EXE_ASSET_RE.fullmatch(Path(urllib.parse.unquote(parsed.path)).name):
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

    size_raw = asset.get("size") or (manifest_asset or {}).get("size")
    size = None
    if size_raw is not None and size_raw != "":
        try:
            if isinstance(size_raw, (int, float)):
                size = int(size_raw)
            else:
                cleaned_size = (
                    str(size_raw).replace(" ", "").replace("\xa0", "").strip()
                )
                if re.fullmatch(r"[+-]?\d+", cleaned_size):
                    size = int(cleaned_size)
                else:
                    raise ValueError()
        except (ValueError, TypeError, OverflowError) as exc:
            raise RuntimeError(
                "Manifest обновления содержит некорректный размер файла."
            ) from exc
        if size < 0:
            raise RuntimeError(
                "Manifest обновления содержит некорректный размер файла."
            )
        if size == 0:
            if repository and tag:
                raise RuntimeError(
                    "Manifest обновления содержит некорректный размер файла."
                )
    else:
        if repository and tag:
            raise RuntimeError(
                "Manifest обновления содержит некорректный размер файла."
            )
        size = None

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
