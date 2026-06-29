import unittest
from unittest.mock import MagicMock, patch

from sto_crm.api.base import BaseAPIHandler

from sto_crm import runtime as _runtime
from sto_crm.config import APP_VERSION
from sto_crm.runtime import Runtime


class FakeHeaders(dict):
    def get(self, key, default=None):
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


class TestBaseAPIHandler(unittest.TestCase):
    def setUp(self):
        self.orig_runtime = _runtime.RUNTIME
        _runtime.RUNTIME = Runtime(
            db_path=None,  # type: ignore
            start_time=123456789.0,
            csrf_token="test_csrf_token",
            access_token="test_access_token",
            bootstrap_token="test_bootstrap_token",
        )

    def tearDown(self):
        _runtime.RUNTIME = self.orig_runtime

    @patch("http.server.BaseHTTPRequestHandler.handle")
    def create_handler(self, mock_handle, headers=None, command="GET", path="/"):
        mock_server = MagicMock()
        mock_server.server_port = 8080
        mock_request = MagicMock()

        # We manually construct the handler
        with patch(
            "http.server.BaseHTTPRequestHandler.__init__", lambda *a, **kw: None
        ):
            handler = BaseAPIHandler(mock_request, ("127.0.0.1", 12345), mock_server)
            handler.server = mock_server
            handler.request = mock_request
            handler.client_address = ("127.0.0.1", 12345)
            handler.connection = MagicMock()
            handler.headers = headers if headers is not None else FakeHeaders({})  # type: ignore
            handler.command = command
            handler.path = path

            # Simple MagicMocks to let Python dynamic attributes work
            wfile_mock = MagicMock()
            wfile_mock.write = MagicMock()
            handler.wfile = wfile_mock

            rfile_mock = MagicMock()
            rfile_mock.read = MagicMock()
            handler.rfile = rfile_mock

            # Run setup manually since we mocked init
            handler.setup()
            return handler

    def test_setup_and_version(self):
        handler = self.create_handler()
        self.assertIsNone(handler._parsed_payload)
        self.assertEqual(handler.version_string(), f"STO-CRM/{APP_VERSION}")

    @patch("sto_crm.api.base.safe_log")
    def test_log_message(self, mock_safe_log):
        handler = self.create_handler()
        handler.log_date_time_string = lambda: "2026-06-29 00:00:00"
        handler.log_message("Request %s for %s", "GET", "/api/data?secret=xyz")
        mock_safe_log.assert_called_once()
        log_call = mock_safe_log.call_args[0][0]
        self.assertIn(
            "2026-06-29 00:00:00 - Request GET for /api/data?secret=xyz", log_call
        )

    def test_send_json(self):
        handler = self.create_handler()
        handler.send_bytes = MagicMock()

        handler.send_json({"ok": True})
        handler.send_bytes.assert_called_once()
        body, content_type = handler.send_bytes.call_args[0][:2]
        self.assertEqual(body, b'{"ok":true}')
        self.assertEqual(content_type, "application/json; charset=utf-8")

    def test_send_html(self):
        handler = self.create_handler()
        handler.send_bytes = MagicMock()

        handler.send_html("<html>nonce:__STO_CRM_CSP_NONCE__</html>")
        handler.send_bytes.assert_called_once()
        body, content_type = handler.send_bytes.call_args[0][:2]
        kwargs = handler.send_bytes.call_args[1]

        self.assertNotIn(b"__STO_CRM_CSP_NONCE__", body)
        self.assertEqual(content_type, "text/html; charset=utf-8")
        self.assertTrue("script_nonce" in kwargs)
        self.assertTrue("style_nonce" in kwargs)

    def test_send_error_json(self):
        handler = self.create_handler(command="GET")
        handler.send_json = MagicMock()

        handler.send_error_json(
            400, "Error in /home/zxc/test.py: path /secret/?token=123"
        )
        handler.send_json.assert_called_once()
        payload = handler.send_json.call_args[0][0]
        kwargs = handler.send_json.call_args[1]
        status = kwargs.get("status")
        write_body = kwargs.get("write_body")

        self.assertEqual(status, 400)
        self.assertTrue(write_body)
        self.assertNotIn("/home/zxc", payload["error"])
        # Paths should be redacted by redact_local_paths
        self.assertNotIn("token=123", payload["error"])

    def test_send_error_json_head(self):
        handler = self.create_handler(command="HEAD")
        handler.send_json = MagicMock()

        handler.send_error_json(404, "Not Found")
        kwargs = handler.send_json.call_args[1]
        write_body = kwargs.get("write_body")
        self.assertFalse(write_body)

    def test_send_bytes_errors(self):
        handler = self.create_handler()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()

        # mock wfile.write as a dummy mock function so we can assign side_effect
        write_mock = MagicMock()
        write_mock.side_effect = ConnectionResetError("Reset")
        handler.wfile = MagicMock()
        handler.wfile.write = write_mock

        with self.assertRaises(BrokenPipeError):
            handler.send_bytes(b"data", "text/plain", status=200)
        self.assertTrue(handler.close_connection)

    def test_route_entity(self):
        handler = self.create_handler()
        handler.send_json = MagicMock()
        handler.send_error_json = MagicMock()

        create_fn = MagicMock(return_value={"id": 1, "created": True})
        update_fn = MagicMock(return_value={"id": 2, "updated": True})
        delete_fn = MagicMock(return_value={"deleted": True})

        # POST
        handler.route_entity(
            "POST", 0, {"name": "Test"}, create_fn, update_fn, delete_fn
        )
        handler.send_json.assert_any_call({"id": 1, "created": True}, 201)

        # PUT
        handler.route_entity(
            "PUT", 2, {"name": "Test"}, create_fn, update_fn, delete_fn
        )
        handler.send_json.assert_any_call({"id": 2, "updated": True})

        # DELETE
        handler.route_entity("DELETE", 3, {}, create_fn, update_fn, delete_fn)
        handler.send_json.assert_any_call({"deleted": True})

        # Unsupported method
        handler.route_entity("GET", 0, {}, create_fn, update_fn, delete_fn)
        handler.send_error_json.assert_called_with(405, "Метод не поддерживается.")

    def test_validate_mutating_request_success(self):
        handler = self.create_handler(
            command="POST",
            headers=FakeHeaders(
                {
                    "Host": "127.0.0.1:8080",
                    "Sec-Fetch-Site": "same-origin",
                    "X-CSRF-Token": "test_csrf_token",
                    "Content-Type": "application/json",
                    "Content-Length": "20",
                }
            ),
        )
        handler.validate_mutating_request("POST")  # Should not raise any error

    def test_validate_mutating_request_invalid_methods(self):
        handler = self.create_handler(command="GET")
        handler.validate_mutating_request("GET")  # No validation occurs for GET

    def test_validate_mutating_request_missing_content_length(self):
        handler = self.create_handler(
            command="POST",
            headers=FakeHeaders(
                {
                    "Host": "127.0.0.1:8080",
                    "Sec-Fetch-Site": "same-origin",
                    "X-CSRF-Token": "test_csrf_token",
                    "Content-Type": "application/json",
                }
            ),
        )
        with self.assertRaises(ValueError) as ctx:
            handler.validate_mutating_request("POST")
        self.assertIn("Пустое тело JSON-запроса.", str(ctx.exception))

    def test_validate_mutating_request_non_int_content_length(self):
        handler = self.create_handler(
            command="POST",
            headers=FakeHeaders(
                {
                    "Host": "127.0.0.1:8080",
                    "Sec-Fetch-Site": "same-origin",
                    "X-CSRF-Token": "test_csrf_token",
                    "Content-Type": "application/json",
                    "Content-Length": "abc",
                }
            ),
        )
        with self.assertRaises(ValueError) as ctx:
            handler.validate_mutating_request("POST")
        self.assertIn("Некорректная длина запроса.", str(ctx.exception))

    def test_reject_ambiguous_body_framing(self):
        # Transfer-encoding check
        handler = self.create_handler(
            headers=FakeHeaders({"Transfer-Encoding": "chunked"})
        )
        with self.assertRaises(ValueError) as ctx:
            handler.reject_ambiguous_body_framing()
        self.assertIn("Transfer-Encoding не поддерживается.", str(ctx.exception))

        # Different Content-Lengths check
        handler = self.create_handler(
            headers=FakeHeaders({"Content-Length": ["10", "20"]})
        )
        with self.assertRaises(ValueError) as ctx:
            handler.reject_ambiguous_body_framing()
        self.assertIn("Некорректная длина запроса.", str(ctx.exception))

    def test_validate_local_request_context(self):
        # Invalid host header
        handler = self.create_handler(headers=FakeHeaders({"Host": "evil.com"}))
        with self.assertRaises(PermissionError) as ctx:
            handler.validate_local_request_context()
        self.assertIn("внешний хост не имеет доступа", str(ctx.exception))

        # Allowed host but untrusted origin
        handler = self.create_handler(
            headers=FakeHeaders({"Host": "127.0.0.1:8080", "Origin": "http://evil.com"})
        )
        with self.assertRaises(PermissionError) as ctx:
            handler.validate_local_request_context()
        self.assertIn("внешний источник не имеет доступа", str(ctx.exception))

        # Allowed host, no origin, bad Sec-Fetch-Site
        handler = self.create_handler(
            headers=FakeHeaders(
                {"Host": "127.0.0.1:8080", "Sec-Fetch-Site": "cross-site"}
            )
        )
        with self.assertRaises(PermissionError) as ctx:
            handler.validate_local_request_context()
        self.assertIn("внешний источник не имеет доступа", str(ctx.exception))

        # Sec-Fetch-Site cross-site directly
        handler = self.create_handler(
            headers=FakeHeaders(
                {
                    "Host": "127.0.0.1:8080",
                    "Origin": "http://127.0.0.1:8080",
                    "Sec-Fetch-Site": "cross-site",
                }
            )
        )
        with self.assertRaises(PermissionError) as ctx:
            handler.validate_local_request_context()
        self.assertIn("внешний сайт не имеет доступа", str(ctx.exception))

    def test_require_access_token(self):
        # Correct token
        handler = self.create_handler(
            headers=FakeHeaders({"X-CRM-Access-Token": "test_access_token"})
        )
        handler.require_access_token()  # Should not raise Error

        # Missing token
        handler = self.create_handler()
        with self.assertRaises(PermissionError) as ctx:
            handler.require_access_token()
        self.assertIn("откройте CRM из локального стартового окна", str(ctx.exception))

        # Wrong token
        handler = self.create_handler(
            headers=FakeHeaders({"X-CRM-Access-Token": "wrong"})
        )
        with self.assertRaises(PermissionError) as ctx:
            handler.require_access_token()
        self.assertIn("откройте CRM из локального стартового окна", str(ctx.exception))

    def test_require_csrf_token(self):
        # Correct CSRF
        handler = self.create_handler(
            headers=FakeHeaders({"X-CSRF-Token": "test_csrf_token"})
        )
        handler.require_csrf_token()

        # Alternate headers
        handler = self.create_handler(
            headers=FakeHeaders({"X-CRM-CSRF-Token": "test_csrf_token"})
        )
        handler.require_csrf_token()

        # Missing CSRF
        handler = self.create_handler()
        with self.assertRaises(PermissionError) as ctx:
            handler.require_csrf_token()
        self.assertIn("обновите страницу CRM и повторите действие", str(ctx.exception))

    def test_require_json_content_type(self):
        # Correct content type with chartset
        handler = self.create_handler(
            headers=FakeHeaders({"Content-Type": "application/json; charset=utf-8"})
        )
        handler.require_json_content_type()

        # Incorrect
        handler = self.create_handler(
            headers=FakeHeaders({"Content-Type": "text/html"})
        )
        with self.assertRaises(ValueError) as ctx:
            handler.require_json_content_type()
        self.assertIn(
            "Для изменений требуется Content-Type: application/json.",
            str(ctx.exception),
        )

    def test_is_allowed_origin(self):
        handler = self.create_handler()
        # Invalid url formats
        self.assertFalse(handler.is_allowed_origin("http:///"))
        self.assertFalse(
            handler.is_allowed_origin("https://localhost")
        )  # HTTPS is not supported here
        self.assertFalse(handler.is_allowed_origin("http://evil.com"))

        # Valid localhost/127.0.0.1
        self.assertTrue(handler.is_allowed_origin("http://localhost:8080"))
        self.assertTrue(handler.is_allowed_origin("http://127.0.0.1:8080"))

        # Port validation failure / ValueError in parsed.port
        # We can simulate this with patching
        mock_parsed = MagicMock()
        mock_parsed.scheme = "http"
        mock_parsed.hostname = "localhost"
        type(mock_parsed).port = MagicMock(side_effect=ValueError("bad port"))
        with patch("urllib.parse.urlparse", return_value=mock_parsed):
            self.assertFalse(handler.is_allowed_origin("http://localhost:999999999"))

    def test_is_allowed_host_header(self):
        handler = self.create_handler()
        self.assertFalse(handler.is_allowed_host_header(None))
        self.assertFalse(handler.is_allowed_host_header("evil.com"))

        # Port check
        self.assertTrue(handler.is_allowed_host_header("127.0.0.1:8080"))

        # Port value error
        self.assertFalse(handler.is_allowed_host_header("127.0.0.1:99999999999"))

    def test_discard_untrusted_request_body(self):
        handler = self.create_handler(headers=FakeHeaders({"Content-Length": "100"}))
        handler._parsed_payload = {"already": "parsed"}
        handler.discard_untrusted_request_body()
        handler.rfile.read.assert_not_called()

        handler._parsed_payload = None
        handler.discard_untrusted_request_body()
        handler.rfile.read.assert_called_once()

    def test_read_json_success(self):
        handler = self.create_handler(headers=FakeHeaders({"Content-Length": "15"}))
        handler.rfile.read.return_value = b'{"name":"test"}'

        data = handler.read_json()
        self.assertEqual(data, {"name": "test"})
        # Cached payload works on subsequent calls
        self.assertEqual(handler.read_json(), {"name": "test"})

    def test_read_json_error(self):
        # Empty body
        handler = self.create_handler(headers=FakeHeaders({"Content-Length": "0"}))
        with self.assertRaises(ValueError) as ctx:
            handler.read_json()
        self.assertIn("Пустое тело JSON-запроса.", str(ctx.exception))

        # Too short body read
        handler = self.create_handler(headers=FakeHeaders({"Content-Length": "15"}))
        handler.rfile.read.return_value = b'{"name"'
        # Make read response 7 bytes while length is 15.
        # Ensure getvalue does not exist, or also returns 7 bytes.
        handler.rfile.getvalue = None
        with self.assertRaises(TimeoutError) as ctx:
            handler.read_json()
        self.assertIn("Тело запроса получено не полностью.", str(ctx.exception))

        # Invalid JSON
        handler = self.create_handler(headers=FakeHeaders({"Content-Length": "14"}))
        handler.rfile.read.return_value = b'{"name": test}'
        with self.assertRaises(ValueError) as ctx:
            handler.read_json()
        self.assertIn("Некорректный JSON.", str(ctx.exception))

        # Non-object JSON
        handler = self.create_handler(headers=FakeHeaders({"Content-Length": "5"}))
        handler.rfile.read.return_value = b"[1,2]"
        with self.assertRaises(ValueError) as ctx:
            handler.read_json()
        self.assertIn("Ожидался JSON-объект.", str(ctx.exception))

    def test_ensure_json_is_utf8_encodable(self):
        handler = self.create_handler()

        with self.assertRaises(ValueError) as ctx:
            handler.ensure_json_is_utf8_encodable({"name": "test\ud800"})
        self.assertIn("Некорректные символы в JSON.", str(ctx.exception))

        # Nodes complexity limit
        nested_dict = {}
        curr = nested_dict
        # We need more than 20_000 nodes total. A dictionary of 10001 keys and 10001 values will exceed 20000 nodes.
        for i in range(10005):
            curr[f"key_{i}"] = "val"
        with self.assertRaises(ValueError) as ctx:
            handler.ensure_json_is_utf8_encodable(nested_dict)
        self.assertIn("JSON слишком сложный для обработки.", str(ctx.exception))
