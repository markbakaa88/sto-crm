"""Regression test for parts order via real socket HTTP connections."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class TestPartsSocketRegression(unittest.TestCase):
    def test_parts_order_via_real_socket(self) -> None:
        port = get_free_port()
        proc = subprocess.Popen(
            [sys.executable, "main.py", "--port", str(port), "--no-browser", "--demo"],
            cwd=str(Path(__file__).parent.parent.absolute()),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        url = f"http://127.0.0.1:{port}/"
        connected = False
        for _ in range(30):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    connected = True
                    break
            except OSError:
                time.sleep(0.2)

        if not connected:
            proc.terminate()
            proc.wait()
            self.fail("Server failed to start")

        try:
            # 1. Fetch `/` to get data-bootstrap-token
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=5) as response:
                html = response.read().decode("utf-8")

            # Extract token
            marker = 'data-bootstrap-token="'
            idx = html.find(marker)
            self.assertNotEqual(idx, -1, "Could not find bootstrap token marker in HTML")
            start = idx + len(marker)
            end = html.find('"', start)
            bootstrap_token = html[start:end]
            self.assertTrue(bootstrap_token, "Bootstrap token must not be empty")

            # 2. Call `/api/bootstrap?bootstrap_token=...`
            bootstrap_url = f"{url}api/bootstrap?bootstrap_token={bootstrap_token}"
            req = urllib.request.Request(bootstrap_url)
            with urllib.request.urlopen(req, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))

            app_data = payload.get("app", {})
            access_token = app_data.get("access_token")
            csrf_token = app_data.get("csrf_token")
            self.assertTrue(access_token, "Access token not found in bootstrap")
            self.assertTrue(csrf_token, "CSRF token not found in bootstrap")

            # 3. POST to `/api/parts/order` with valid headers/tokens
            order_url = f"{url}api/parts/order"
            body = {
                "oem": "123",
                "brand": "CTR",
                "supplier": "rossko",
                "quantity": 2,
                "price": 1000.0,
            }
            body_bytes = json.dumps(body).encode("utf-8")

            req = urllib.request.Request(
                order_url,
                data=body_bytes,
                headers={
                    "Content-Type": "application/json",
                    "X-CRM-Access-Token": access_token,
                    "X-CSRF-Token": csrf_token,
                },
                method="POST",
            )

            # We expect a normal response (either 200 OK, or 400 Bad Request, or 500 error, but NEVER a timeout/hang)
            try:
                with urllib.request.urlopen(req, timeout=5) as response:
                    status = response.status
            except urllib.error.HTTPError as err:
                status = err.code

            self.assertIn(status, {200, 400, 500})
            self.assertNotEqual(status, 408)

        finally:
            proc.terminate()
            proc.wait()
