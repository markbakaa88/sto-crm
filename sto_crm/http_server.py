"""Local HTTP API and static UI server."""

from __future__ import annotations

import socket
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from typing import Any

from . import runtime as _runtime
from .api.base import BaseAPIHandler
from .config import APP_VERSION


class CRMHandler(BaseAPIHandler):
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
            import urllib.parse

            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            query = urllib.parse.parse_qs(parsed.query)
            path_parts = [p for p in path.split("/") if p]

            self.validate_local_request_context()
            self.validate_mutating_request(method)
            trusted_request = True
            if method in {"POST", "PUT"}:
                self.read_json()

            # 1. Base URL / static responses
            if method == "HEAD" and path in {"/", "/app"}:
                self.validate_local_request_context()
                from .web import index_html

                self.send_html(index_html(), write_body=False)
                return
            if method == "GET" and path in {"/", "/app"}:
                self.validate_local_request_context()
                from .web import index_html

                self.send_html(index_html())
                return
            if method in {"GET", "HEAD"} and path in {
                "/favicon.ico",
                "/favicon.svg",
            }:
                self.validate_local_request_context()
                from .web import FAVICON_SVG

                self.send_bytes(
                    FAVICON_SVG.encode("utf-8"),
                    "image/svg+xml; charset=utf-8",
                    write_body=method != "HEAD",
                )
                return
            if method == "GET" and path == "/assets/app.css":
                self.validate_local_request_context()
                from .web import read_asset

                self.send_bytes(
                    read_asset("app.css").encode("utf-8"),
                    "text/css; charset=utf-8",
                )
                return
            if method == "GET" and path == "/assets/app.js":
                self.validate_local_request_context()
                from .web import read_asset

                self.send_bytes(
                    read_asset("app.js").encode("utf-8"),
                    "application/javascript; charset=utf-8",
                )
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

            # Handlers checks
            is_api = len(path_parts) >= 1 and path_parts[0] == "api"

            # Execute /api/bootstrap BEFORE general access token checks so the shell can initialize
            if is_api and path_parts[1:2] == ["bootstrap"]:
                from .api.reports import handle_reports

                if handle_reports(self, method, path, query, path_parts):
                    return

            # require access token for other /api/* paths
            if is_api:
                # Bypass token check for health and catalog
                is_bypass = len(path_parts) >= 2 and path_parts[1] in {
                    "catalog",
                    "car-catalog",
                }
                if not is_bypass:
                    self.require_access_token()

            # 2. Delegate to reports/printing/parts/export
            from .api.reports import handle_reports

            if handle_reports(self, method, path, query, path_parts):
                return

            # 3. Delegate to updates/backup/shutdown
            from .api.updates import handle_updates

            if handle_updates(self, method, path, path_parts):
                return

            # Remaining API paths require at least /api/<entity>
            if len(path_parts) < 2 or path_parts[0] != "api":
                self.send_error_json(404, "Маршрут не найден.")
                return

            entity = path_parts[1]

            # Parse payload for mutating requests and pass it.
            # CRITICAL: We only call read_json() once.
            payload = self.read_json() if method in {"POST", "PUT"} else {}

            # 4. Delegate to CRUD modules
            if entity == "customers":
                from .api.customers import handle_customers

                if handle_customers(self, method, path_parts, payload):
                    return
            elif entity == "vehicles":
                from .api.vehicles import handle_vehicles

                if handle_vehicles(self, method, path_parts, payload):
                    return
            elif entity == "inventory":
                from .api.inventory import handle_inventory

                if handle_inventory(self, method, path_parts, payload):
                    return
            elif entity == "appointments":
                from .api.appointments import handle_appointments

                if handle_appointments(self, method, path_parts, payload):
                    return
            elif entity == "orders":
                from .api.orders import handle_orders

                if handle_orders(self, method, path_parts, payload):
                    return

            self.send_error_json(404, "Маршрут не найден.")

        except ValueError as exc:
            self.send_error_json(400, str(exc))
        except PermissionError as exc:
            self.send_error_json(403, str(exc))
        except KeyError as exc:
            self.send_error_json(404, str(exc).strip("'"))
        except TimeoutError:
            self.close_connection = True
            self.send_error_json(408, "Тело запроса не получено вовремя.")
        except BrokenPipeError:
            return
        except OSError:
            grace_flag = getattr(self.server, "graceful_shutdown_flag", False)
            if grace_flag and not isinstance(grace_flag, bool):
                grace_flag = False
            if grace_flag:
                return
            if getattr(sys, "stderr", None):
                import logging

                logging.getLogger("sto_crm").error(
                    "Unhandled Server Exception", exc_info=True
                )
            from .config import INTERNAL_ERROR_MESSAGE

            self.send_error_json(500, INTERNAL_ERROR_MESSAGE)
        except Exception:
            grace_flag = getattr(self.server, "graceful_shutdown_flag", False)
            if grace_flag and not isinstance(grace_flag, bool):
                grace_flag = False
            if grace_flag:
                return
            if getattr(sys, "stderr", None):
                import logging

                logging.getLogger("sto_crm").error(
                    "Unhandled Server Exception", exc_info=True
                )
            from .config import INTERNAL_ERROR_MESSAGE

            self.send_error_json(500, INTERNAL_ERROR_MESSAGE)
        finally:
            if not trusted_request:
                self.discard_untrusted_request_body()

    def cached_update_status(self) -> dict[str, Any]:
        from .api.updates import cached_update_status

        return cached_update_status()


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

    def shutdown(self) -> None:
        super().shutdown()
        self.wait_for_active_threads(5.0)
        from .database import close_all_connections

        close_all_connections()

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
