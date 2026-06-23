import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from sto_crm import runtime as _runtime
from sto_crm.database import init_db
from sto_crm.http_server import CRMHandler


class DummyRequest:
    def __init__(self, rfile_content=b""):
        self.rfile_content = rfile_content
        self.bytes_written = b""

    def makefile(self, mode, *args, **kwargs):
        if "r" in mode:
            import io

            return io.BytesIO(self.rfile_content)
        elif "w" in mode:
            import io

            class HTTPBytesWriter(io.BytesIO):
                def __init__(self, outer):
                    super().__init__()
                    self.outer = outer

                def write(self, b):
                    self.outer.bytes_written += b
                    return len(b)

                def flush(self):
                    pass

            return HTTPBytesWriter(self)
        return None

    def sendall(self, data):
        self.bytes_written += data


class DummyServer:
    def __init__(self):
        self.graceful_shutdown_flag = False
        self.shutdown_reason = None


class TestHttpPartsRoutes(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test_http_routes.sqlite3"
        self.orig_runtime = _runtime.RUNTIME
        _runtime.RUNTIME = _runtime.Runtime(
            db_path=self.db_path,
            start_time=time.time(),
            csrf_token="test_csrf_token",
            access_token="test_access_token",
            bootstrap_token="test_bootstrap_token",
        )
        init_db(seed_demo=False)

    def tearDown(self) -> None:
        _runtime.RUNTIME = self.orig_runtime
        self.tmpdir.cleanup()

    def _make_handler(self, method, path, body=b"", headers=None) -> CRMHandler:
        if headers is None:
            headers = {}
        # Construct raw request content
        raw_req_lines = [f"{method} {path} HTTP/1.1"]
        for k, v in headers.items():
            raw_req_lines.append(f"{k}: {v}")
        raw_req_content = (
            "\r\n".join(raw_req_lines).encode("utf-8") + b"\r\n\r\n" + body
        )

        request = DummyRequest(raw_req_content)
        client_address = ("127.0.0.1", 12345)
        server = DummyServer()

        # Instantiate CRMHandler, it runs handle_one_request inside __init__ if request is setup properly,
        # but BaseHTTPRequestHandler does a lot of socket-level stuff.
        # We can mock BaseHTTPRequestHandler constructor behavior to run setup, handle, and finish manually.
        with patch(
            "http.server.BaseHTTPRequestHandler.__init__", lambda *args, **kwargs: None
        ):
            handler = CRMHandler(request, client_address, server)  # type: ignore[arg-type]
            handler.request = request  # type: ignore[assignment]
            handler.client_address = client_address
            handler.server = server  # type: ignore[assignment]
            handler.rfile = DummyRequest(body).makefile("rb")

            # Setup headers
            import http.client
            import io

            headers_raw = ""
            for k, v in headers.items():
                headers_raw += f"{k}: {v}\r\n"
            headers_raw += "\r\n"
            fp = io.BytesIO(headers_raw.encode("utf-8"))
            handler.headers = http.client.parse_headers(fp)
            handler.path = path
            handler.command = method
            handler.request_version = "HTTP/1.1"
            handler.requestline = f"{method} {path} HTTP/1.1"
            handler.wfile = request.makefile("wb")
            return handler

    @patch("sto_crm.parts_service.search_supplier_parts")
    def test_get_parts_search_route(self, mock_search):
        mock_search.return_value = [
            {
                "oem": "123",
                "brand": "CTR",
                "name": "Part A",
                "price": 100.0,
                "stock": 1,
                "delivery_days": 1,
                "supplier": "rossko",
            }
        ]

        headers = {
            "Host": "localhost:8080",
            "X-CRM-Access-Token": "test_access_token",
            "X-CSRF-Token": "test_csrf_token",
        }
        handler = self._make_handler(
            "GET", "/api/parts/search?q=123&brand=CTR", headers=headers
        )
        handler.handle_request("GET")

        # Verify call parameters
        mock_search.assert_called_once_with("123", "CTR", False)

        # Inspect response headers/body
        response_bytes = handler.request.bytes_written
        self.assertIn(b"HTTP/1.1 200 OK", response_bytes)
        self.assertIn(b"application/json", response_bytes)
        self.assertIn(b'"ok":true', response_bytes)
        self.assertIn(b'"name":"Part A"', response_bytes)
        # Content Sec Policy validation (CSP nonce rule)
        self.assertIn(b"Content-Security-Policy", response_bytes)

    @patch("sto_crm.parts_service.place_supplier_order")
    def test_post_parts_order_route(self, mock_place_order):
        mock_place_order.return_value = "TRACK-XYZ"

        body = b'{"oem": "123", "brand": "CTR", "supplier": "rossko", "quantity": 2, "price": 1000.0}'
        headers = {
            "Host": "localhost:8080",
            "X-CRM-Access-Token": "test_access_token",
            "X-CSRF-Token": "test_csrf_token",
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        }
        handler = self._make_handler(
            "POST", "/api/parts/order", body=body, headers=headers
        )
        handler.handle_request("POST")

        mock_place_order.assert_called_once_with("123", "CTR", "rossko", 2, 1000.0)

        response_bytes = handler.request.bytes_written
        self.assertIn(b"HTTP/1.1 200 OK", response_bytes)
        self.assertIn(b"TRACK-XYZ", response_bytes)

    def test_post_parts_order_route_invalid_fields(self):
        # We test that bad values return 400
        headers = {
            "Host": "localhost:8080",
            "X-CRM-Access-Token": "test_access_token",
            "X-CSRF-Token": "test_csrf_token",
            "Content-Type": "application/json",
        }

        bad_payloads = [
            # nan price
            b'{"oem": "123", "brand": "CTR", "supplier": "rossko", "quantity": 2, "price": "nan"}',
            b'{"oem": "123", "brand": "CTR", "supplier": "rossko", "quantity": 2, "price": NaN}',
            # inf price
            b'{"oem": "123", "brand": "CTR", "supplier": "rossko", "quantity": 2, "price": "inf"}',
            # too big price
            b'{"oem": "123", "brand": "CTR", "supplier": "rossko", "quantity": 2, "price": 999999999999}',
            # negative quantity
            b'{"oem": "123", "brand": "CTR", "supplier": "rossko", "quantity": -5, "price": 100.0}',
            # zero quantity
            b'{"oem": "123", "brand": "CTR", "supplier": "rossko", "quantity": 0, "price": 100.0}',
            # float quantity
            b'{"oem": "123", "brand": "CTR", "supplier": "rossko", "quantity": 2.5, "price": 100.0}',
            # overflow quantity
            b'{"oem": "123", "brand": "CTR", "supplier": "rossko", "quantity": 99999999999999999999999999, "price": 100.0}',
        ]

        for body in bad_payloads:
            hdrs = dict(headers)
            hdrs["Content-Length"] = str(len(body))
            handler = self._make_handler(
                "POST", "/api/parts/order", body=body, headers=hdrs
            )
            handler.handle_request("POST")
            response_bytes = handler.request.bytes_written
            self.assertIn(b"HTTP/1.1 400 Bad Request", response_bytes)

    @patch("sto_crm.parts_service.search_supplier_parts")
    def test_get_parts_search_route_force_no_csrf(self, mock_search):
        headers = {
            "Host": "localhost:8080",
            "X-CRM-Access-Token": "test_access_token",
            # No CSRF header or empty
        }
        handler = self._make_handler(
            "GET", "/api/parts/search?q=123&brand=CTR&force=true", headers=headers
        )
        handler.handle_request("GET")
        response_bytes = handler.request.bytes_written
        self.assertIn(b"HTTP/1.1 403 Forbidden", response_bytes)
        mock_search.assert_not_called()

    @patch("sto_crm.parts_service.search_supplier_parts")
    def test_get_parts_search_route_force_with_csrf(self, mock_search):
        mock_search.return_value = []
        headers = {
            "Host": "localhost:8080",
            "X-CRM-Access-Token": "test_access_token",
            "X-CSRF-Token": "test_csrf_token",
        }
        handler = self._make_handler(
            "GET", "/api/parts/search?q=123&brand=CTR&force=true", headers=headers
        )
        handler.handle_request("GET")
        response_bytes = handler.request.bytes_written
        self.assertIn(b"HTTP/1.1 200 OK", response_bytes)
        mock_search.assert_called_once_with("123", "CTR", True)

    @patch("sto_crm.parts_service.search_supplier_parts")
    def test_get_parts_search_route_force_debounce(self, mock_search):
        from sto_crm.parts_service import get_lock_for_query

        # Acquire lock beforehand to simulate an in-progress request
        lock = get_lock_for_query("123", "CTR")
        lock_acquired = lock.acquire(blocking=False)
        self.assertTrue(lock_acquired)

        try:
            headers = {
                "Host": "localhost:8080",
                "X-CRM-Access-Token": "test_access_token",
                "X-CSRF-Token": "test_csrf_token",
            }
            handler = self._make_handler(
                "GET", "/api/parts/search?q=123&brand=CTR&force=true", headers=headers
            )
            handler.handle_request("GET")
            response_bytes = handler.request.bytes_written
            self.assertIn(b"HTTP/1.1 429 Too Many Requests", response_bytes)
            mock_search.assert_not_called()
        finally:
            lock.release()
