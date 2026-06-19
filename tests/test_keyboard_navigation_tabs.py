import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest


def get_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def crm_server():
    port = get_free_port()
    proc = subprocess.Popen(
        [sys.executable, "main.py", "--port", str(port), "--no-browser", "--demo"],
        cwd=str(Path(__file__).parent.parent.absolute()),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    url = f"http://127.0.0.1:{port}/"
    for _ in range(30):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.2)
    else:
        proc.terminate()
        proc.wait()
        raise RuntimeError("Server failed to start")

    yield url

    proc.terminate()
    proc.wait()


def test_keyboard_navigation_tabs(crm_server):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="chrome-for-testing",
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-setuid-sandbox",
            ],
        )
        context = browser.new_context()
        page = context.new_page()

        page.goto(crm_server)
        page.wait_for_selector(".app")

        # Wait for data bootstrap to complete
        page.evaluate("() => new Promise(resolve => { if (state.data) return resolve(); const check = setInterval(() => { if (state.data) { clearInterval(check); resolve(); } }, 50); })")

        # 1. Check early state
        assert page.evaluate("state.route") == "dashboard"

        # 2. Check alt hints are present on the correct 7 buttons
        hints = page.evaluate("""() => {
            return Array.from(document.querySelectorAll('#nav button[data-route]')).map(btn => {
                const hint = btn.querySelector('.alt-hint');
                return {
                    route: btn.dataset.route,
                    hint: hint ? hint.textContent : null
                };
            }).filter(x => x.hint !== null);
        }""")

        expected_hints = {
            "dashboard": "1",
            "appointments": "2",
            "orders": "3",
            "customers": "4",
            "vehicles": "5",
            "inventory": "6",
            "catalog": "7"
        }

        assert len(hints) == 7
        for item in hints:
            assert expected_hints[item["route"]] == item["hint"]

        # 3. Test Alt + 1-7 transitions
        # Alt + 2 -> Appointments
        page.keyboard.down("Alt")
        page.keyboard.press("2")
        page.keyboard.up("Alt")
        page.wait_for_timeout(50)
        assert page.evaluate("state.route") == "appointments"

        # Alt + 3 -> Orders
        page.keyboard.down("Alt")
        page.keyboard.press("3")
        page.keyboard.up("Alt")
        page.wait_for_timeout(50)
        assert page.evaluate("state.route") == "orders"

        # Alt + 4 -> Customers
        page.keyboard.down("Alt")
        page.keyboard.press("4")
        page.keyboard.up("Alt")
        page.wait_for_timeout(50)
        assert page.evaluate("state.route") == "customers"

        # Alt + 5 -> Vehicles
        page.keyboard.down("Alt")
        page.keyboard.press("5")
        page.keyboard.up("Alt")
        page.wait_for_timeout(50)
        assert page.evaluate("state.route") == "vehicles"

        # Alt + 6 -> Inventory
        page.keyboard.down("Alt")
        page.keyboard.press("6")
        page.keyboard.up("Alt")
        page.wait_for_timeout(50)
        assert page.evaluate("state.route") == "inventory"

        # Alt + 7 -> Catalog
        page.keyboard.down("Alt")
        page.keyboard.press("7")
        page.keyboard.up("Alt")
        page.wait_for_timeout(50)
        assert page.evaluate("state.route") == "catalog"

        # Alt + 1 -> Dashboard
        page.keyboard.down("Alt")
        page.keyboard.press("1")
        page.keyboard.up("Alt")
        page.wait_for_timeout(50)
        assert page.evaluate("state.route") == "dashboard"

        # 4. Test Alt hold toggles alt-pressed class on body
        page.keyboard.down("Alt")
        page.wait_for_timeout(50)
        assert page.evaluate("document.body.classList.contains('alt-pressed')")

        page.keyboard.up("Alt")
        page.wait_for_timeout(50)
        assert not page.evaluate("document.body.classList.contains('alt-pressed')")

        # 5. Test first keyboard navigation event (Tab) toggles keyboard-navigation class
        assert not page.evaluate("document.body.classList.contains('keyboard-navigation')")
        page.keyboard.press("Tab")
        page.wait_for_timeout(50)
        assert page.evaluate("document.body.classList.contains('keyboard-navigation')")

        browser.close()
