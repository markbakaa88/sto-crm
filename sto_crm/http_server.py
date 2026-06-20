"""Local HTTP API and static UI server."""

from __future__ import annotations

import contextlib
import json
import secrets
import socket
import sqlite3
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from . import runtime as _runtime
from .catalog import car_catalog_payload
from .config import (
    APP_VERSION,
    INTERNAL_ERROR_MESSAGE,
    MAX_BODY_BYTES,
    REQUEST_READ_TIMEOUT_SECONDS,
    UPDATE_STATUS_CACHE_SECONDS,
)
from .database import db
from .export import bootstrap_payload, csv_export
from .printing import print_order_html
from .queries import get_order
from .runtime import (
    clean_text,
    parse_int_field,
    redact_sensitive_query,
    safe_log,
    strict_json_loads,
)
from .services import (
    create_appointment,
    create_customer,
    create_inventory,
    create_order,
    create_vehicle,
    delete_appointment,
    delete_customer,
    delete_inventory,
    delete_order,
    delete_vehicle,
    update_appointment,
    update_customer,
    update_inventory,
    update_order,
    update_vehicle,
)
from .updates import (
    create_backup,
    install_update_from_github,
    public_backup_payload,
    update_status,
)
from .web import FAVICON_SVG, index_html, read_asset

_UPDATE_STATUS_CACHE: tuple[float, dict[str, Any] | None] = (0.0, None)
_UPDATE_STATUS_LOCK = threading.Lock()


class CRMHandler(BaseHTTPRequestHandler):
    server_version = f"STO-CRM/{APP_VERSION}"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(REQUEST_READ_TIMEOUT_SECONDS)

    def version_string(self) -> str:
        return self.server_version

    def log_message(self, fmt: str, *args: Any) -> None:
        safe_log(
            f"{self.log_date_time_string()} - {redact_sensitive_query(fmt % args)}"
        )

    def do_GET(self) -> None:
        self.handle_request("GET")

    def do_HEAD(self) -> None:
        self.handle_request("HEAD")

    def do_POST(self) -> None:
        self.handle_request("POST")

    def do_PUT(self) -> None:
        self.handle_request("PUT")

    def do_DELETE(self) -> None:
        self.handle_request("DELETE")

    def do_OPTIONS(self) -> None:
        try:
            self.validate_local_request_context()
            self.send_bytes(
                b"",
                "text/plain; charset=utf-8",
                status=204,
                headers={"Allow": "GET, HEAD, POST, PUT, DELETE, OPTIONS"},
            )
        except PermissionError as exc:
            self.close_connection = True
            self.send_error_json(403, str(exc))
        finally:
            self.discard_untrusted_request_body()

    def do_PATCH(self) -> None:
        self.reject_unsupported_method()

    def do_TRACE(self) -> None:
        self.reject_unsupported_method()

    def do_CONNECT(self) -> None:
        self.reject_unsupported_method()

    def reject_unsupported_method(self) -> None:
        try:
            self.validate_local_request_context()
            self.send_error_json(405, "Метод не поддерживается.")
        except PermissionError as exc:
            self.send_error_json(403, str(exc))
        finally:
            self.discard_untrusted_request_body()

    def handle_request(self, method: str) -> None:
        graceful = getattr(self.server, "graceful_shutdown_flag", False)
        if graceful and not isinstance(graceful, bool):
            graceful = False
        if graceful:
            self.send_error_json(503, "Сервер останавливается.")
            return
        trusted_request = False
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            query = urllib.parse.parse_qs(parsed.query)
            self.validate_local_request_context()
            self.validate_mutating_request(method)
            trusted_request = True

            if method == "HEAD" and path in {"/", "/app"}:
                self.validate_local_request_context()
                self.send_html(index_html(), write_body=False)
                return
            if method == "HEAD" and path == "/api/health":
                self.validate_local_request_context()
                self.send_json(
                    {
                        "ok": True,
                        "version": APP_VERSION,
                        "uptime": round(time.time() - _runtime.RUNTIME.start_time, 1),
                    },
                    write_body=False,
                )
                return

            if method == "GET" and path in {"/", "/app"}:
                self.validate_local_request_context()
                self.send_html(index_html())
                return
            if method in {"GET", "HEAD"} and path in {"/favicon.ico", "/favicon.svg"}:
                self.validate_local_request_context()
                self.send_bytes(
                    FAVICON_SVG.encode("utf-8"),
                    "image/svg+xml; charset=utf-8",
                    write_body=method != "HEAD",
                )
                return
            if method == "GET" and path == "/assets/app.css":
                self.validate_local_request_context()
                self.send_bytes(
                    read_asset("app.css").encode("utf-8"),
                    "text/css; charset=utf-8",
                )
                return
            if method == "GET" and path == "/assets/app.js":
                self.validate_local_request_context()
                self.send_bytes(
                    read_asset("app.js").encode("utf-8"),
                    "application/javascript; charset=utf-8",
                )
                return
            if method == "GET" and path.startswith("/print/order/"):
                self.validate_local_request_context()
                self.require_access_token()
                token = (
                    self.headers.get("X-CSRF-Token")
                    or self.headers.get("X-CRM-CSRF-Token")
                    or ""
                )
                if not token or not secrets.compare_digest(
                    token, _runtime.RUNTIME.csrf_token
                ):
                    raise PermissionError(
                        "Печатная форма доступна только из интерфейса CRM."
                    )
                order_id = parse_int_field(
                    path.rsplit("/", 1)[-1], "номер заказ-наряда"
                )
                with db(readonly=True) as conn:
                    self.send_html(print_order_html(get_order(conn, order_id)))
                return
            if method == "GET" and path == "/api/health":
                self.validate_local_request_context()
                self.send_json(
                    {
                        "ok": True,
                        "version": APP_VERSION,
                        "uptime": round(time.time() - _runtime.RUNTIME.start_time, 1),
                    }
                )
                return
            if method == "GET" and path.startswith("/api/parts/search"):
                self.validate_local_request_context()
                self.require_access_token()

                # OEM query parameter is required
                q_vals = query.get("q", [])
                if not q_vals or not q_vals[0].strip():
                    self.send_error_json(400, "Параметр поиска q (OEM номер) является обязательным.")
                    return
                oem = q_vals[0]

                brand_vals = query.get("brand", [])
                brand = brand_vals[0] if brand_vals else None

                # Check for optional force cache refresh query parameter
                force_vals = query.get("force", [])
                force_refresh = force_vals[0] == "true" if force_vals else False

                from .parts_service import search_supplier_parts
                try:
                    parts = search_supplier_parts(oem, brand, force_refresh)
                    self.send_json({"ok": True, "parts": parts})
                except Exception as exc:
                    self.send_error_json(500, f"Ошибка при проценке запчастей: {exc}")
                return

            if method == "POST" and path == "/api/parts/order":
                self.validate_local_request_context()
                self.require_access_token()

                # Check CSRF since it is a mutating request but not automatically validated
                # under validate_mutating_request (since that only knows route entities map)
                self.require_csrf_token()
                self.require_json_content_type()

                payload = self.read_json()

                oem = payload.get("oem")
                brand = payload.get("brand")
                supplier = payload.get("supplier")
                quantity_raw = payload.get("quantity")
                price_raw = payload.get("price")

                if not oem or not brand or not supplier or quantity_raw is None or price_raw is None:
                    self.send_error_json(400, "Поля oem, brand, supplier, quantity и price являются обязательными.")
                    return

                try:
                    quantity = int(quantity_raw)
                    if quantity <= 0:
                        raise ValueError
                except (ValueError, TypeError):
                    self.send_error_json(400, "Количество должно быть положительным целым числом.")
                    return

                try:
                    price = float(price_raw)
                    if price < 0:
                        raise ValueError
                except (ValueError, TypeError):
                    self.send_error_json(400, "Цена должна быть неотрицательным числом.")
                    return

                from .parts_service import place_supplier_order
                try:
                    order_tracking_id = place_supplier_order(oem, brand, supplier, quantity, price)
                    self.send_json({"ok": True, "order_tracking_id": order_tracking_id})
                except ValueError as exc:
                    self.send_error_json(400, str(exc))
                except Exception as exc:
                    self.send_error_json(500, f"Ошибка при оформлении заказа: {exc}")
                return

            if method == "GET" and path == "/api/bootstrap":
                self.validate_local_request_context()
                if query.get("bootstrap_token") != [_runtime.RUNTIME.bootstrap_token]:
                    self.require_access_token()
                q = clean_text((query.get("q") or [""])[0], 120)
                status = clean_text((query.get("status") or ["all"])[0], 40, "all")
                self.send_json(bootstrap_payload(q, status))
                return
            if method == "GET" and path in {"/api/catalog", "/api/car-catalog"}:
                self.validate_local_request_context()
                self.send_json(car_catalog_payload())
                return
            if method == "GET" and path == "/api/update/status":
                self.validate_local_request_context()
                self.require_access_token()
                self.send_json(self.cached_update_status())
                return
            if method == "GET" and path.startswith("/api/export/"):
                self.validate_local_request_context()
                self.require_access_token()
                token = (
                    self.headers.get("X-CSRF-Token")
                    or self.headers.get("X-CRM-CSRF-Token")
                    or ""
                )
                if not secrets.compare_digest(token, _runtime.RUNTIME.csrf_token):
                    raise PermissionError("Экспорт доступен только из интерфейса CRM.")
                entity = path.rsplit("/", 1)[-1].removesuffix(".csv")
                try:
                    filename, generator = csv_export(entity)
                except KeyError:
                    self.send_error_json(400, "Некорректная сущность экспорта.")
                    return
                self.close_connection = True
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Transfer-Encoding", "chunked")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header(
                    "Permissions-Policy", "geolocation=(), camera=(), microphone=()"
                )
                self.send_header("Cross-Origin-Opener-Policy", "same-origin")
                self.send_header("Cross-Origin-Resource-Policy", "same-origin")
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
                )
                self.send_header("Connection", "close")
                self.send_header(
                    "Content-Disposition", f'attachment; filename="{filename}"'
                )
                self.end_headers()

                try:
                    for chunk in generator:
                        data = chunk.encode("utf-8")
                        if not data:
                            continue
                        self.wfile.write(f"{len(data):X}\r\n".encode("ascii"))
                        self.wfile.write(data)
                        self.wfile.write(b"\r\n")
                    self.wfile.write(b"0\r\n\r\n")
                except (
                    BrokenPipeError,
                    ConnectionResetError,
                    ConnectionAbortedError,
                ) as err:
                    self.close_connection = True
                    raise BrokenPipeError from err
                return

            payload = self.read_json() if method in {"POST", "PUT"} else {}
            parts = [p for p in path.split("/") if p]
            if parts and parts[0] == "api":
                self.require_access_token()
            if len(parts) < 2 or parts[0] != "api":
                self.send_error_json(404, "Маршрут не найден.")
                return
            entity = parts[1]

            if entity == "backup" and len(parts) == 2 and method == "POST":
                backup = create_backup()
                self.send_json(public_backup_payload(backup) or {})
                return
            if (
                entity == "update"
                and len(parts) == 3
                and parts[2] == "install"
                and method == "POST"
            ):
                result = install_update_from_github()
                if isinstance(result.get("backup"), dict):
                    result = {
                        **result,
                        "backup": public_backup_payload(result["backup"]) or {},
                    }
                self.send_json(result)
                if result.get("updated"):
                    safe_log(
                        "Получена команда перезагрузки для установки обновлений. Планирование мягкого завершения работы..."
                    )
                    if isinstance(self.server, CRMServer):
                        self.server.graceful_shutdown_flag = True
                        self.server.shutdown_reason = "reboot"
                    else:
                        server_any: Any = self.server
                        server_any.graceful_shutdown_flag = True
                        server_any.shutdown_reason = "reboot"
                    # Shutdown gracefully via delay/lag
                    timer = threading.Timer(0.3, self.server.shutdown)
                    timer.daemon = True
                    timer.start()
                return
            if entity == "shutdown" and len(parts) == 2 and method == "POST":
                self.send_json({"ok": True})
                safe_log(
                    "Получена команда перехода в оффлайн. Планирование мягкого завершения работы..."
                )
                if isinstance(self.server, CRMServer):
                    self.server.graceful_shutdown_flag = True
                    self.server.shutdown_reason = "offline"
                else:
                    server_any_shutdown: Any = self.server
                    server_any_shutdown.graceful_shutdown_flag = True
                    server_any_shutdown.shutdown_reason = "offline"
                timer = threading.Timer(0.3, self.server.shutdown)
                timer.daemon = True
                timer.start()
                return

            entity_routes = {
                "customers": (create_customer, update_customer, delete_customer),
                "vehicles": (create_vehicle, update_vehicle, delete_vehicle),
                "inventory": (create_inventory, update_inventory, delete_inventory),
                "appointments": (
                    create_appointment,
                    update_appointment,
                    delete_appointment,
                ),
                "orders": (create_order, update_order, delete_order),
            }
            route = entity_routes.get(entity)
            if not route:
                self.send_error_json(404, "Маршрут не найден.")
                return
            if method == "POST":
                if len(parts) != 2:
                    self.send_error_json(404, "Маршрут не найден.")
                    return
                record_id = 0
            elif method in {"PUT", "DELETE"}:
                if len(parts) != 3:
                    self.send_error_json(404, "Маршрут не найден.")
                    return
                record_id = parse_int_field(parts[2], "идентификатор записи")
            else:
                self.send_error_json(405, "Метод не поддерживается.")
                return
            self.route_entity(method, record_id, payload, *route)
        except ValueError as exc:
            self.send_error_json(400, str(exc))
        except PermissionError as exc:
            self.send_error_json(403, str(exc))
        except KeyError as exc:
            self.send_error_json(404, str(exc).strip("'"))
        except sqlite3.IntegrityError:
            self.send_error_json(
                409,
                "Запись конфликтует с существующими данными. Обновите страницу и повторите действие.",
            )
        except RuntimeError as exc:
            import logging

            logging.getLogger("sto_crm").error(
                f"HTTP runtime error: {redact_sensitive_query(str(exc))}", exc_info=True
            )
            self.send_error_json(500, INTERNAL_ERROR_MESSAGE)
        except BrokenPipeError:
            return
        except TimeoutError:
            self.close_connection = True
            self.send_error_json(408, "Тело запроса не получено вовремя.")
        except OSError:
            graceful = getattr(self.server, "graceful_shutdown_flag", False)
            if graceful and not isinstance(graceful, bool):
                graceful = False
            if graceful:
                return
            if getattr(sys, "stderr", None):
                import logging

                logging.getLogger("sto_crm").error(
                    "Unhandled Server Exception", exc_info=True
                )
            self.send_error_json(500, INTERNAL_ERROR_MESSAGE)
        except Exception:
            graceful = getattr(self.server, "graceful_shutdown_flag", False)
            if graceful and not isinstance(graceful, bool):
                graceful = False
            if graceful:
                return
            if getattr(sys, "stderr", None):
                import logging

                logging.getLogger("sto_crm").error(
                    "Unhandled Server Exception", exc_info=True
                )
            self.send_error_json(500, INTERNAL_ERROR_MESSAGE)
        finally:
            if not trusted_request:
                self.discard_untrusted_request_body()

    def cached_update_status(self) -> dict[str, Any]:
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
            payload = update_status()
            _UPDATE_STATUS_CACHE = (now + UPDATE_STATUS_CACHE_SECONDS, payload)
            assert isinstance(payload, dict)
            return payload

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
            # При отсутствии Origin требуем явный same-origin-сигнал браузера.
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
        self.send_json(
            {"ok": False, "error": message},
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
            f"script-src 'self' 'nonce-{script_nonce}'"
            if script_nonce
            else "script-src 'self'"
        )
        style_src = (
            f"style-src 'self' 'nonce-{style_nonce}'"
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


class CRMServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.graceful_shutdown_flag = False
        self.shutdown_reason: str | None = None
        self._active_threads: set[threading.Thread] = set()
        self._active_requests: set[Any] = set()
        self._active_threads_lock = threading.Lock()

    def process_request(self, request: Any, client_address: Any) -> None:
        t = threading.Thread(
            target=self.process_request_thread,
            args=(request, client_address),
        )
        t.daemon = self.daemon_threads
        with self._active_threads_lock:
            self._active_threads.add(t)
            self._active_requests.add(request)
        t.start()

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        current_thr = threading.current_thread()
        with self._active_threads_lock:
            self._active_threads.add(current_thr)
            self._active_requests.add(request)
        try:
            super().process_request_thread(request, client_address)
        finally:
            with self._active_threads_lock:
                self._active_threads.discard(current_thr)
                self._active_requests.discard(request)

    def wait_for_active_threads(self, timeout: float = 5.0) -> None:
        start_time = time.monotonic()
        current = threading.current_thread()
        with self._active_threads_lock:
            threads = [t for t in self._active_threads if t is not current]
        for t in threads:
            elapsed = time.monotonic() - start_time
            rem = max(0.0, timeout - elapsed)
            if rem <= 0:
                break
            t.join(timeout=rem)

        # Force terminate remaining sockets
        with self._active_threads_lock:
            remaining_sockets = list(self._active_requests)
            remaining_threads = [
                t for t in self._active_threads if t is not current and t.is_alive()
            ]

        for sock in remaining_sockets:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass

        for t in remaining_threads:
            t.join(timeout=1.0)


class CRMServerV6(CRMServer):
    address_family = socket.AF_INET6
