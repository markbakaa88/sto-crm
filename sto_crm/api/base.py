"""Base HTTP routing and API common infrastructure."""

from __future__ import annotations

import contextlib
import json
import secrets
import urllib.parse
from http.server import BaseHTTPRequestHandler
from typing import Any

from .. import runtime as _runtime
from ..config import (
    APP_VERSION,
    MAX_BODY_BYTES,
    REQUEST_READ_TIMEOUT_SECONDS,
)
from ..runtime import (
    redact_local_paths,
    redact_sensitive_query,
    safe_log,
    strict_json_loads,
)


class BaseAPIHandler(BaseHTTPRequestHandler):
    server_version = f"STO-CRM/{APP_VERSION}"
    sys_version = ""
    protocol_version = "HTTP/1.1"
    _parsed_payload: dict[str, Any] | None = None

    def setup(self) -> None:
        self._parsed_payload = None
        super().setup()
        self.connection.settimeout(REQUEST_READ_TIMEOUT_SECONDS)

    def version_string(self) -> str:
        return self.server_version

    def log_message(self, format: str, *args: Any) -> None:
        safe_log(
            f"{self.log_date_time_string()} - {redact_sensitive_query(format % args)}"
        )

    def send_json(
        self, payload: Any, status: int = 200, *, write_body: bool = True
    ) -> None:
        body = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        self.send_bytes(
            body,
            "application/json; charset=utf-8",
            status=status,
            write_body=write_body,
        )

    def send_html(
        self, content: str, status: int = 200, *, write_body: bool = True
    ) -> None:
        nonce = secrets.token_urlsafe(16)
        html = content.replace("__STO_CRM_CSP_NONCE__", nonce)
        self.send_bytes(
            html.encode("utf-8"),
            "text/html; charset=utf-8",
            status=status,
            write_body=write_body,
            script_nonce=nonce,
            style_nonce=nonce,
        )

    def send_error_json(self, status: int, message: str) -> None:
        redacted = redact_local_paths(redact_sensitive_query(message))
        self.send_json(
            {"ok": False, "error": redacted},
            status=status,
            write_body=self.command.upper() != "HEAD",
        )

    def send_bytes(
        self,
        body: bytes,
        content_type: str,
        status: int = 200,
        headers: dict[str, str] | None = None,
        write_body: bool = True,
        script_nonce: str = "",
        style_nonce: str = "",
    ) -> None:
        self.close_connection = True
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Permissions-Policy", "geolocation=(), camera=(), microphone=()"
        )
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        script_src = (
            f"script-src 'self' 'nonce-{script_nonce}' 'strict-dynamic' 'unsafe-inline'"
            if script_nonce
            else "script-src 'self'"
        )
        style_src = (
            f"style-src 'self' 'nonce-{style_nonce}' 'unsafe-inline'"
            if style_nonce
            else "style-src 'self'"
        )
        self.send_header(
            "Content-Security-Policy",
            f"default-src 'self'; {style_src}; "
            f"{script_src}; "
            "connect-src 'self'; "
            "img-src 'self' data:; object-src 'none'; base-uri 'none'; "
            "form-action 'self'; frame-ancestors 'none'",
        )
        self.send_header("Connection", "close")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        try:
            self.end_headers()
            if write_body:
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError) as err:
            self.close_connection = True
            raise BrokenPipeError from err

    def route_entity(
        self,
        method: str,
        record_id: int,
        payload: dict[str, Any],
        create_fn: Any,
        update_fn: Any,
        delete_fn: Any,
    ) -> None:
        if method == "POST":
            self.send_json(create_fn(payload), 201)
        elif method == "PUT" and record_id:
            self.send_json(update_fn(record_id, payload))
        elif method == "DELETE" and record_id:
            self.send_json(delete_fn(record_id))
        else:
            self.send_error_json(405, "Метод не поддерживается.")

    def validate_mutating_request(self, method: str) -> None:
        if method not in {"POST", "PUT", "DELETE"}:
            return
        self.validate_local_request_context()
        if method in {"POST", "PUT"}:
            self.reject_ambiguous_body_framing()
            raw_length = self.headers.get("Content-Length")
            try:
                length = int(raw_length or "0")
            except ValueError as exc:
                raise ValueError("Некорректная длина запроса.") from exc
            if length < 0:
                raise ValueError("Некорректная длина запроса.")
            if length == 0:
                raise ValueError("Пустое тело JSON-запроса.")
            if length > MAX_BODY_BYTES:
                raise ValueError("Слишком большой запрос.")
        self.require_csrf_token()
        if method in {"POST", "PUT"}:
            self.require_json_content_type()

    def reject_ambiguous_body_framing(self) -> None:
        transfer_encoding = self.headers.get("Transfer-Encoding")
        if transfer_encoding:
            raise ValueError("Transfer-Encoding не поддерживается.")
        content_lengths = self.headers.get_all("Content-Length", [])
        if len({value.strip() for value in content_lengths}) > 1:
            raise ValueError("Некорректная длина запроса.")

    def validate_local_request_context(self) -> None:
        if not self.is_allowed_host_header(self.headers.get("Host")):
            raise PermissionError(
                "Запрос отклонен: внешний хост не имеет доступа к локальной CRM."
            )
        origin = self.headers.get("Origin")
        fetch_site = (self.headers.get("Sec-Fetch-Site") or "").lower()
        if origin:
            if not self.is_allowed_origin(origin):
                raise PermissionError(
                    "Запрос отклонен: внешний источник не имеет доступа к локальной CRM."
                )
        elif fetch_site and fetch_site not in {"same-origin", "none"}:
            raise PermissionError(
                "Запрос отклонен: внешний источник не имеет доступа к локальной CRM."
            )
        if fetch_site and fetch_site not in {"same-origin", "same-site", "none"}:
            raise PermissionError(
                "Запрос отклонен: внешний сайт не имеет доступа к локальной CRM."
            )

    def require_access_token(self) -> None:
        token = self.headers.get("X-CRM-Access-Token") or ""
        expected = _runtime.RUNTIME.access_token or ""
        if not expected or not secrets.compare_digest(token, expected):
            raise PermissionError(
                "Запрос отклонен: откройте CRM из локального стартового окна и повторите действие."
            )

    def require_csrf_token(self) -> None:
        token = self.headers.get("X-CSRF-Token") or self.headers.get("X-CRM-CSRF-Token")
        if not token or not secrets.compare_digest(token, _runtime.RUNTIME.csrf_token):
            raise PermissionError(
                "Запрос отклонен: обновите страницу CRM и повторите действие."
            )

    def require_json_content_type(self) -> None:
        content_type = (
            self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        )
        if content_type != "application/json":
            raise ValueError("Для изменений требуется Content-Type: application/json.")

    def is_allowed_origin(self, origin: str) -> bool:
        try:
            parsed = urllib.parse.urlparse(origin)
        except ValueError:
            return False
        if parsed.scheme != "http":
            return False
        host = (parsed.hostname or "").lower()
        if host not in {"127.0.0.1", "localhost", "::1"}:
            return False
        try:
            port = parsed.port or 80
        except ValueError:
            return False
        if not port:
            port = getattr(self.server, "server_port", 8080)
        return port == getattr(self.server, "server_port", 8080)

    def is_allowed_host_header(self, host_header: str | None) -> bool:
        if not host_header:
            return False
        try:
            parsed = urllib.parse.urlparse(f"//{host_header}")
        except ValueError:
            return False
        host = (parsed.hostname or "").lower()
        if host not in {"127.0.0.1", "localhost", "::1"}:
            return False
        try:
            port = parsed.port
        except ValueError:
            return False
        if not port:
            port = 80
        return port == getattr(self.server, "server_port", 8080)

    def discard_untrusted_request_body(self) -> None:
        if self._parsed_payload is not None:
            return
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length or "0")
        except ValueError:
            length = 0
        if length <= 0:
            return
        with contextlib.suppress(OSError, ValueError):
            self.rfile.read(min(length, MAX_BODY_BYTES + 1))

    def read_json(self) -> dict[str, Any]:
        if self._parsed_payload is not None:
            return self._parsed_payload
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length or "0")
        except ValueError as exc:
            raise ValueError("Некорректная длина запроса.") from exc
        if length < 0:
            raise ValueError("Некорректная длина запроса.")
        if length > MAX_BODY_BYTES:
            raise ValueError("Слишком большой запрос.")
        if length == 0:
            raise ValueError("Пустое тело JSON-запроса.")
        raw = self.rfile.read(length)
        if len(raw) != length:
            getvalue = getattr(self.rfile, "getvalue", None)
            if getvalue is not None:
                raw = getvalue()
            if len(raw) != length:
                raise TimeoutError("Тело запроса получено не полностью.")
        try:
            text = raw.decode("utf-8")
            data = strict_json_loads(text)
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            ValueError,
            RecursionError,
        ) as exc:
            raise ValueError("Некорректный JSON.") from exc
        if not isinstance(data, dict):
            raise ValueError("Ожидался JSON-объект.")
        self.ensure_json_is_utf8_encodable(data)
        self._parsed_payload = data
        return data

    def ensure_json_is_utf8_encodable(self, value: Any) -> None:
        stack: list[Any] = [value]
        nodes_seen = 0
        while stack:
            item = stack.pop()
            nodes_seen += 1
            if nodes_seen > 20_000:
                raise ValueError("JSON слишком сложный для обработки.")
            if isinstance(item, str):
                try:
                    item.encode("utf-8")
                except UnicodeEncodeError as exc:
                    raise ValueError("Некорректные символы в JSON.") from exc
            elif isinstance(item, dict):
                stack.extend(item.keys())
                stack.extend(item.values())
            elif isinstance(item, list):
                stack.extend(item)
