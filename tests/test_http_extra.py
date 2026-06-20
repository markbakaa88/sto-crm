import json
import sqlite3
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

from sto_crm import runtime as _runtime
from sto_crm.cli import create_server
from sto_crm.database import init_db
from sto_crm.runtime import Runtime


class FakeHeaders(dict):
    def get(self, key, default=None):  # type: ignore
        for k, v in self.items():
            if k.lower() == key.lower():
                return v
        return default

    def get_all(self, name, failobj=None):
        val = self.get(name)
        if val is None:
            return failobj if failobj is not None else []
        if isinstance(val, list):
            return val
        return [val]


class TestHttpServerExtra(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.runtime_db = Path(self.tmpdir.name) / "test_http_extra.sqlite3"
        self.orig_runtime = _runtime.RUNTIME
        _runtime.RUNTIME = Runtime(
            db_path=self.runtime_db,
            start_time=time.time(),
            csrf_token="test_csrf_token",
            access_token="test_access_token",
            bootstrap_token="test_bootstrap_token",
        )
        init_db(seed_demo=True)
        # Mock latest_release_info to avoid GitHub api call
        self.patcher = patch("sto_crm.updates.latest_release_info")
        self.mock_latest = self.patcher.start()
        self.mock_latest.return_value = {
            "version": "1.17.2",
            "tag": "v1.17.2",
            "name": "СТО CRM 1.17.2",
            "is_newer": False,
            "has_asset": False,
            "asset": None,
            "manifest": None,
        }
        self.server = create_server(0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.patcher.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        _runtime.RUNTIME = self.orig_runtime
        self.tmpdir.cleanup()

    def test_print_order_success(self):
        # /print/order/1 с валидными access_token и csrf
        req = urllib.request.Request(
            f"{self.base}/print/order/1",
            headers={
                "X-CRM-Access-Token": "test_access_token",
                "X-CSRF-Token": "test_csrf_token",
            },
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            self.assertEqual(response.status, 200)
            body = response.read().decode("utf-8")
            self.assertIn("Toyota Camry", body)

    def test_csv_export_success(self):
        req = urllib.request.Request(
            f"{self.base}/api/export/customers.csv",
            headers={
                "X-CRM-Access-Token": "test_access_token",
                "X-CSRF-Token": "test_csrf_token",
            },
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            self.assertEqual(response.status, 200)
            body = response.read().decode("utf-8")
            self.assertTrue(body.startswith("\ufeff"))

    def test_api_car_catalog(self):
        req = urllib.request.Request(
            f"{self.base}/api/car-catalog",
            headers={"X-CRM-Access-Token": "test_access_token"},
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            self.assertEqual(response.status, 200)
            data = json.loads(response.read().decode("utf-8"))
            self.assertIn("makes", data)

    def test_backup_post_success(self):
        req = urllib.request.Request(
            f"{self.base}/api/backup",
            method="POST",
            headers={
                "X-CRM-Access-Token": "test_access_token",
                "X-CSRF-Token": "test_csrf_token",
                "Content-Type": "application/json",
            },
            data=b"{}",
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            self.assertEqual(response.status, 200)
            data = json.loads(response.read().decode("utf-8"))
            self.assertIn("filename", data)

    def test_invalid_json_post(self):
        req = urllib.request.Request(
            f"{self.base}/api/customers",
            method="POST",
            headers={
                "X-CRM-Access-Token": "test_access_token",
                "X-CSRF-Token": "test_csrf_token",
                "Content-Type": "application/json",
            },
            data=b"{invalid-json",
        )
        with self.assertRaises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(err.exception.code, 400)

    def test_http_exceptions_handling(self):
        # 1. KeyError (например, несуществующий клиент)
        req = urllib.request.Request(
            f"{self.base}/api/customers/9999",
            method="PUT",
            headers={
                "X-CRM-Access-Token": "test_access_token",
                "X-CSRF-Token": "test_csrf_token",
                "Content-Type": "application/json",
            },
            data=json.dumps(
                {
                    "name": "New Name",
                    "phone": "123",
                    "reminder_consent": True,
                    "preferred_channel": "sms",
                }
            ).encode("utf-8"),
        )
        with self.assertRaises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(err.exception.code, 404)

        # 2. IntegrityError (например, некорректный внешний ключ или дубликат VIN)
        # Попробуем создать машинку с уже существующим VIN
        req_vehicle = urllib.request.Request(
            f"{self.base}/api/vehicles",
            method="POST",
            headers={
                "X-CRM-Access-Token": "test_access_token",
                "X-CSRF-Token": "test_csrf_token",
                "Content-Type": "application/json",
            },
            # Дубликат VIN-номер и клиент №1
            data=json.dumps(
                {
                    "vin": "JTNB11HK303000001",
                    "make": "Toyota",
                    "model": "Camry",
                    "year": 2018,
                    "plate": "A123AA99",
                    "mileage": 82000,
                    "customer_id": 1,
                }
            ).encode("utf-8"),
        )
        # validation.py или django-подобное вызовет ValueError на дубликат VIN
        # но мы можем спровоцировать IntegrityError напрямую в API с помощью mock на create_vehicle
        with patch(
            "sto_crm.http_server.create_vehicle",
            side_effect=sqlite3.IntegrityError("Conflict"),
        ):
            req_integrity = urllib.request.Request(
                f"{self.base}/api/vehicles",
                method="POST",
                headers={
                    "X-CRM-Access-Token": "test_access_token",
                    "X-CSRF-Token": "test_csrf_token",
                    "Content-Type": "application/json",
                },
                data=json.dumps(
                    {
                        "vin": "JTNB11HK303000007",
                        "make": "Toyota",
                        "model": "Camry",
                        "year": 2018,
                        "plate": "A999AA99",
                        "mileage": 8000,
                        "customer_id": 1,
                    }
                ).encode("utf-8"),
            )
            with self.assertRaises(urllib.error.HTTPError) as err:
                urllib.request.urlopen(req_integrity, timeout=5)
            self.assertEqual(err.exception.code, 409)

        # 3. RuntimeError
        with patch(
            "sto_crm.http_server.create_vehicle",
            side_effect=RuntimeError("Runtime Err"),
        ):
            with self.assertRaises(urllib.error.HTTPError) as err:
                urllib.request.urlopen(req_vehicle, timeout=5)
            self.assertEqual(err.exception.code, 500)

    def test_invalid_api_routes(self):
        # GET /api (length < 2) with token
        req = urllib.request.Request(
            f"{self.base}/api", headers={"X-CRM-Access-Token": "test_access_token"}
        )
        with self.assertRaises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(err.exception.code, 404)

        # GET /other/route (parts[0] != "api")
        req = urllib.request.Request(
            f"{self.base}/other/route",
        )
        with self.assertRaises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(err.exception.code, 404)

        # GET /api/non_existent (entity not in entity_routes)
        req = urllib.request.Request(
            f"{self.base}/api/non_existent",
            headers={"X-CRM-Access-Token": "test_access_token"},
        )
        with self.assertRaises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(err.exception.code, 404)

        # POST /api/customers/1 (method POST, parts length != 2)
        req = urllib.request.Request(
            f"{self.base}/api/customers/1",
            method="POST",
            headers={
                "X-CRM-Access-Token": "test_access_token",
                "X-CSRF-Token": "test_csrf_token",
                "Content-Type": "application/json",
            },
            data=b"{}",
        )
        with self.assertRaises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(err.exception.code, 404)

        # PUT /api/customers (method PUT, parts length != 3)
        req = urllib.request.Request(
            f"{self.base}/api/customers",
            method="PUT",
            headers={
                "X-CRM-Access-Token": "test_access_token",
                "X-CSRF-Token": "test_csrf_token",
                "Content-Type": "application/json",
            },
            data=b"{}",
        )
        with self.assertRaises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(err.exception.code, 404)

        # OPTIONS /
        req = urllib.request.Request(f"{self.base}/", method="OPTIONS")
        with urllib.request.urlopen(req, timeout=5) as response:
            self.assertEqual(response.status, 204)
            self.assertEqual(
                response.headers.get("Allow"), "GET, HEAD, POST, PUT, DELETE, OPTIONS"
            )

        # PATCH /
        req = urllib.request.Request(f"{self.base}/", method="PATCH")
        with self.assertRaises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(err.exception.code, 405)

    def test_unsupported_methods(self):
        # GET /api/customers -> returns 405 because GET is unsupported for that entity route
        req = urllib.request.Request(
            f"{self.base}/api/customers",
            method="GET",
            headers={"X-CRM-Access-Token": "test_access_token"},
        )
        with self.assertRaises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(err.exception.code, 405)

        # DELETE /api/customers/0 -> returns 405 via route_entity check
        req = urllib.request.Request(
            f"{self.base}/api/customers/0",
            method="DELETE",
            headers={
                "X-CRM-Access-Token": "test_access_token",
                "X-CSRF-Token": "test_csrf_token",
            },
        )
        with self.assertRaises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(err.exception.code, 405)

        # PUT /api/customers/0 -> returns 405 via route_entity check
        req = urllib.request.Request(
            f"{self.base}/api/customers/0",
            method="PUT",
            headers={
                "X-CRM-Access-Token": "test_access_token",
                "X-CSRF-Token": "test_csrf_token",
                "Content-Type": "application/json",
            },
            data=b"{}",
        )
        with self.assertRaises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(err.exception.code, 405)

    @patch("http.server.BaseHTTPRequestHandler.handle")
    def test_unsupported_method_permission_error(self, mock_handle):
        mock_server = MagicMock()
        mock_server.server_port = 8080
        mock_request = MagicMock()
        from sto_crm.http_server import CRMHandler

        handler = CRMHandler(mock_request, ("127.0.0.1", 12345), mock_server)
        handler.request_version = "HTTP/1.1"
        handler.requestline = "OPTIONS / HTTP/1.1"
        handler.command = "OPTIONS"
        handler.headers = FakeHeaders({"Host": "127.0.0.1:8080"})

        with patch.object(
            handler,
            "validate_local_request_context",
            side_effect=PermissionError("Forbidden context"),
        ):
            with patch.object(handler, "send_error_json") as mock_send_err:
                handler.do_OPTIONS()
                mock_send_err.assert_called_once_with(403, "Forbidden context")

        with patch.object(
            handler,
            "validate_local_request_context",
            side_effect=PermissionError("Forbidden context"),
        ):
            with patch.object(handler, "send_error_json") as mock_send_err:
                handler.do_PATCH()
                mock_send_err.assert_called_once_with(403, "Forbidden context")

    @patch("http.server.BaseHTTPRequestHandler.handle")
    def test_shutdown_and_update_reboot(self, mock_handle):
        mock_server = MagicMock()
        mock_server.server_port = 8080
        mock_request = MagicMock()
        from sto_crm.http_server import CRMHandler

        handler = CRMHandler(mock_request, ("127.0.0.1", 12345), mock_server)
        handler.request_version = "HTTP/1.1"
        handler.headers = FakeHeaders(
            {
                "Host": "127.0.0.1:8080",
                "X-CRM-Access-Token": "test_access_token",
                "X-CSRF-Token": "test_csrf_token",
                "Content-Type": "application/json",
                "Content-Length": "2",
            }
        )
        handler.path = "/api/shutdown"
        handler.requestline = "POST /api/shutdown HTTP/1.1"
        handler.command = "POST"
        handler.rfile = MagicMock()
        handler.rfile.read.return_value = b"{}"

        # Test isinstance(mock_server, CRMServer) -> False, triggering else path
        with patch("threading.Timer") as mock_timer:
            with patch("sto_crm.database.close_all_connections"):
                handler.handle_request("POST")
                mock_timer.assert_called_once()
                self.assertEqual(mock_timer.call_args[0][0], 0.3)
                self.assertEqual(mock_timer.call_args[0][1], mock_server.shutdown)
                self.assertTrue(getattr(mock_server, "graceful_shutdown_flag", False))
                self.assertEqual(
                    getattr(mock_server, "shutdown_reason", None), "offline"
                )

        # Test isinstance(mock_server, CRMServer) -> True, triggering if path
        mock_server_class = mock_server.__class__
        with patch("sto_crm.http_server.CRMServer", mock_server_class):
            mock_server.graceful_shutdown_flag = False
            mock_server.shutdown_reason = None
            with patch("threading.Timer") as mock_timer:
                with patch("sto_crm.database.close_all_connections"):
                    handler.handle_request("POST")
                    mock_timer.assert_called_once()
                    self.assertTrue(mock_server.graceful_shutdown_flag)
                    self.assertEqual(mock_server.shutdown_reason, "offline")

        # Test update install path with backup dict
        handler.path = "/api/update/install"
        handler.requestline = "POST /api/update/install HTTP/1.1"
        mock_server.graceful_shutdown_flag = False

        with patch("sto_crm.http_server.CRMServer", mock_server_class):
            with patch(
                "sto_crm.http_server.install_update_from_github",
                return_value={
                    "backup": {"filename": "foo.db", "display_path": "foo/display"},
                    "updated": True,
                },
            ):
                with patch("threading.Timer") as mock_timer:
                    with patch.object(handler, "send_json") as mock_send_json:
                        handler.handle_request("POST")
                        mock_timer.assert_called_once()
                        self.assertTrue(mock_server.graceful_shutdown_flag)
                        mock_send_json.assert_called_once()
                        res_payload = mock_send_json.call_args[0][0]
                        self.assertEqual(
                            res_payload.get("backup"),
                            {"filename": "foo.db", "display_path": "foo/display"},
                        )
                        self.assertTrue(res_payload.get("updated"))

        # Test update install else path (isinstance not CRMServer)
        mock_server.graceful_shutdown_flag = False
        with patch(
            "sto_crm.http_server.install_update_from_github",
            return_value={"updated": True},
        ):
            with patch("threading.Timer") as mock_timer:
                handler.handle_request("POST")
                mock_timer.assert_called_once()
                self.assertTrue(mock_server.graceful_shutdown_flag)

    @patch("http.server.BaseHTTPRequestHandler.handle")
    def test_handler_validation_details(self, mock_handle):
        mock_server = MagicMock()
        mock_server.server_port = 8080
        mock_request = MagicMock()
        from sto_crm.http_server import CRMHandler

        handler = CRMHandler(mock_request, ("127.0.0.1", 12345), mock_server)
        handler.request_version = "HTTP/1.1"
        handler.requestline = "POST /api HTTP/1.1"
        handler.command = "POST"

        # 1. reject_ambiguous_body_framing with Transfer-Encoding
        mock_headers_te = MagicMock()
        mock_headers_te.get.side_effect = lambda k, default=None: (
            "chunked" if k == "Transfer-Encoding" else default
        )
        handler.headers = mock_headers_te
        with self.assertRaises(ValueError) as ctx:
            handler.reject_ambiguous_body_framing()
        self.assertIn("Transfer-Encoding не поддерживается.", str(ctx.exception))

        # 2. reject_ambiguous_body_framing with multiple Content-Lengths
        def get_all_side_effect(k, default=None):
            if k == "Content-Length":
                return ["10", "20"]
            return default or []

        mock_headers_cl = MagicMock()
        mock_headers_cl.get.side_effect = lambda k, default=None: (
            "10" if k == "Content-Length" else default
        )
        mock_headers_cl.get_all.side_effect = get_all_side_effect
        handler.headers = mock_headers_cl
        with self.assertRaises(ValueError) as ctx:
            handler.reject_ambiguous_body_framing()
        self.assertIn("Некорректная длина запроса.", str(ctx.exception))

        # Reset headers to standard dict-like mock for validate_local_request_context
        # 3. is_allowed_origin invalid port raising ValueError
        handler.headers = FakeHeaders(
            {
                "Host": "127.0.0.1:8080",
                "Origin": "http://localhost:99999999",
                "Sec-Fetch-Site": "same-origin",
            }
        )
        self.assertFalse(handler.is_allowed_origin("http://localhost:999999999"))

        # 4. is_allowed_origin invalid scheme
        self.assertFalse(handler.is_allowed_origin("https://localhost:8080"))

        # 5. is_allowed_origin invalid url raising ValueError
        self.assertFalse(handler.is_allowed_origin("http://localhost\u0000"))
        # 5b. is_allowed_origin IPv6 URL raising ValueError
        self.assertFalse(handler.is_allowed_origin("http://[::1]]"))

        # 6. is_allowed_origin with DynamicTruth to reach getattr(self.server, "server_port")
        class DynamicTruth:
            def __init__(self):
                self.val = True

            def __bool__(self):
                ret = self.val
                self.val = False
                return ret

        mock_parsed = MagicMock()
        mock_parsed.scheme = "http"
        mock_parsed.hostname = "localhost"
        mock_parsed.port = DynamicTruth()
        with patch("urllib.parse.urlparse", return_value=mock_parsed):
            self.assertTrue(handler.is_allowed_origin("http://localhost"))

        # 7. is_allowed_host_header: None host
        self.assertFalse(handler.is_allowed_host_header(None))

        # 8. is_allowed_host_header: invalid URL host raising ValueError
        self.assertFalse(handler.is_allowed_host_header("127.0.0.1\u0000"))
        # 8b. is_allowed_host_header: IPv6 host raising ValueError
        self.assertFalse(handler.is_allowed_host_header("[::1]]"))

        # 9. is_allowed_host_header: port raising ValueError
        self.assertFalse(handler.is_allowed_host_header("127.0.0.1:999999999"))

        # 10. is_allowed_host_header: no port (port is falsy -> 80)
        mock_server.server_port = 80
        self.assertTrue(handler.is_allowed_host_header("127.0.0.1"))
        mock_server.server_port = 8080  # restore

        # 11. validate_local_request_context: Origin present but Sec-Fetch-Site is cross-site
        handler.headers = FakeHeaders(
            {
                "Host": "127.0.0.1:8080",
                "Origin": "http://127.0.0.1:8080",
                "Sec-Fetch-Site": "cross-site",
            }
        )
        with self.assertRaises(PermissionError) as ctx:
            handler.validate_local_request_context()
        self.assertIn(
            "Запрос отклонен: внешний сайт не имеет доступа", str(ctx.exception)
        )

        # 12. validate_local_request_context: Origin missing, Sec-Fetch-Site is cross-site
        handler.headers = FakeHeaders(
            {"Host": "127.0.0.1:8080", "Sec-Fetch-Site": "cross-site"}
        )
        with self.assertRaises(PermissionError) as ctx:
            handler.validate_local_request_context()
        self.assertIn(
            "Запрос отклонен: внешний источник не имеет доступа", str(ctx.exception)
        )

        # 13. require_json_content_type invalid content type
        handler.headers = FakeHeaders({"Content-Type": "text/plain"})
        with self.assertRaises(ValueError) as ctx:
            handler.require_json_content_type()
        self.assertIn(
            "Для изменений требуется Content-Type: application/json.",
            str(ctx.exception),
        )

        # 14. validate_mutating_request: negative content length
        handler.headers = FakeHeaders(
            {
                "Host": "127.0.0.1:8080",
                "Sec-Fetch-Site": "same-origin",
                "Content-Length": "-1",
            }
        )
        with self.assertRaises(ValueError) as ctx:
            handler.validate_mutating_request("POST")
        self.assertIn("Некорректная длина запроса.", str(ctx.exception))

        # 15. validate_mutating_request: zero content length
        handler.headers = FakeHeaders(
            {
                "Host": "127.0.0.1:8080",
                "Sec-Fetch-Site": "same-origin",
                "Content-Length": "0",
            }
        )
        with self.assertRaises(ValueError) as ctx:
            handler.validate_mutating_request("POST")
        self.assertIn("Пустое тело JSON-запроса.", str(ctx.exception))

        # 16. validate_mutating_request: too large content length
        handler.headers = FakeHeaders(
            {
                "Host": "127.0.0.1:8080",
                "Sec-Fetch-Site": "same-origin",
                "Content-Length": str(2000000 + 1),
            }
        )
        with self.assertRaises(ValueError) as ctx:
            handler.validate_mutating_request("POST")
        self.assertIn("Слишком большой запрос.", str(ctx.exception))

    @patch("http.server.BaseHTTPRequestHandler.handle")
    def test_json_parsing_and_complexity(self, mock_handle):
        mock_server = MagicMock()
        mock_server.server_port = 8080
        mock_request = MagicMock()
        from sto_crm.http_server import CRMHandler

        handler = CRMHandler(mock_request, ("127.0.0.1", 12345), mock_server)
        handler.request_version = "HTTP/1.1"
        handler.requestline = "POST /api/customers HTTP/1.1"
        handler.command = "POST"

        # 1. Non-numeric Content-Length
        handler.headers = FakeHeaders({"Content-Length": "abc"})
        with self.assertRaises(ValueError) as ctx:
            handler.read_json()
        self.assertIn("Некорректная длина запроса.", str(ctx.exception))

        # 2. Negative Content-Length
        handler.headers = FakeHeaders({"Content-Length": "-10"})
        with self.assertRaises(ValueError) as ctx:
            handler.read_json()
        self.assertIn("Некорректная длина запроса.", str(ctx.exception))

        # 3. Content-Length too large
        handler.headers = FakeHeaders({"Content-Length": str(10 * 1024 * 1024)})
        with self.assertRaises(ValueError) as ctx:
            handler.read_json()
        self.assertIn("Слишком большой запрос.", str(ctx.exception))

        # 4. Zero Content-Length
        handler.headers = FakeHeaders({"Content-Length": "0"})
        with self.assertRaises(ValueError) as ctx:
            handler.read_json()
        self.assertIn("Пустое тело JSON-запроса.", str(ctx.exception))

        # 5. Non-dict JSON (returns a list)
        handler.headers = FakeHeaders({"Content-Length": "7"})
        handler.rfile = MagicMock()
        handler.rfile.read.return_value = b"[1,2,3]"
        with self.assertRaises(ValueError) as ctx:
            handler.read_json()
        self.assertIn("Ожидался JSON-объект.", str(ctx.exception))

        # 6. JSON complexity > 20000 nodes seen
        nested = {"a": [0] * 20001}
        with self.assertRaises(ValueError) as ctx:
            handler.ensure_json_is_utf8_encodable(nested)
        self.assertIn("JSON слишком сложный для обработки.", str(ctx.exception))

        # 7. Non-utf-8 encodable strings inside JSON
        bad_json = {"key": "hello \ud800 world"}
        with self.assertRaises(ValueError) as ctx:
            handler.ensure_json_is_utf8_encodable(bad_json)
        self.assertIn("Некорректные символы в JSON.", str(ctx.exception))

    @patch("http.server.BaseHTTPRequestHandler.handle")
    def test_direct_exception_handling(self, mock_handle):
        mock_server = MagicMock()
        mock_server.server_port = 8080
        mock_request = MagicMock()
        from sto_crm.http_server import INTERNAL_ERROR_MESSAGE, CRMHandler

        handler = CRMHandler(mock_request, ("127.0.0.1", 12345), mock_server)
        handler.request_version = "HTTP/1.1"
        handler.path = "/api/health"
        handler.requestline = "GET /api/health HTTP/1.1"
        handler.command = "GET"
        handler.headers = FakeHeaders(
            {"Host": "127.0.0.1:8080", "Sec-Fetch-Site": "same-origin"}
        )

        # 1. BrokenPipeError handling in send_bytes
        handler.wfile = MagicMock()
        handler.wfile.write.side_effect = ConnectionResetError("Reset")
        with self.assertRaises(BrokenPipeError):
            handler.send_bytes(b"hello", "text/plain")

        # 2. BrokenPipeError caught in handle_request
        with patch.object(
            handler, "validate_local_request_context", side_effect=BrokenPipeError
        ):
            self.assertIsNone(handler.handle_request("GET"))

        # 3. TimeoutError in handle_request
        with patch.object(
            handler,
            "validate_local_request_context",
            side_effect=TimeoutError("timeout"),
        ):
            with patch.object(handler, "send_error_json") as mock_send_err:
                handler.handle_request("GET")
                self.assertTrue(handler.close_connection)
                mock_send_err.assert_called_once_with(
                    408, "Тело запроса не получено вовремя."
                )

        # 4. OSError in handle_request with stderr present
        with patch.object(
            handler, "validate_local_request_context", side_effect=OSError("OS error")
        ):
            with patch.object(handler, "send_error_json") as mock_send_err:
                handler.handle_request("GET")
                mock_send_err.assert_called_once_with(500, INTERNAL_ERROR_MESSAGE)

        # 5. OSError in handle_request with stderr None
        with patch.object(
            handler, "validate_local_request_context", side_effect=OSError("OS error")
        ):
            with patch.object(handler, "send_error_json") as mock_send_err:
                with patch("sys.stderr", None):
                    handler.handle_request("GET")
                    mock_send_err.assert_called_once_with(500, INTERNAL_ERROR_MESSAGE)

        # 6. Generic Exception in handle_request with stderr present
        with patch.object(
            handler,
            "validate_local_request_context",
            side_effect=Exception("Generic error"),
        ):
            with patch.object(handler, "send_error_json") as mock_send_err:
                handler.handle_request("GET")
                mock_send_err.assert_called_once_with(500, INTERNAL_ERROR_MESSAGE)

        # 7. Generic Exception in handle_request with stderr None
        with patch.object(
            handler,
            "validate_local_request_context",
            side_effect=Exception("Generic error"),
        ):
            with patch.object(handler, "send_error_json") as mock_send_err:
                with patch("sys.stderr", None):
                    handler.handle_request("GET")
                    mock_send_err.assert_called_once_with(500, INTERNAL_ERROR_MESSAGE)

    @patch("http.server.BaseHTTPRequestHandler.handle")
    def test_double_checked_cache(self, mock_handle):
        mock_server = MagicMock()
        mock_server.server_port = 8080
        mock_request = MagicMock()
        from sto_crm.http_server import CRMHandler

        handler = CRMHandler(mock_request, ("127.0.0.1", 12345), mock_server)
        handler.request_version = "HTTP/1.1"
        handler.requestline = "GET /api/update/status HTTP/1.1"
        handler.command = "GET"

        class DoubleCheckCache:
            def __init__(self):
                self.call_count = 0

            def __iter__(self):
                self.call_count += 1
                payload = None if self.call_count == 1 else {"some": "status"}
                yield time.monotonic() + 100.0
                yield payload

        fake_cache = DoubleCheckCache()
        with patch("sto_crm.http_server._UPDATE_STATUS_CACHE", fake_cache):
            res = handler.cached_update_status()
            self.assertEqual(res, {"some": "status"})

    def test_routes_delete_entity(self):
        req = urllib.request.Request(
            f"{self.base}/api/customers/1",
            method="DELETE",
            headers={
                "X-CRM-Access-Token": "test_access_token",
                "X-CSRF-Token": "test_csrf_token",
            },
        )
        with self.assertRaises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(err.exception.code, 400)
