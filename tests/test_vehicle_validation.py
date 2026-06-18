import socket
import subprocess
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
        ["python3", "main.py", "--port", str(port), "--no-browser", "--demo"],
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


def test_vehicle_vin_validation(crm_server):
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

        # Open vehicle modal
        page.evaluate("openVehicleModal()")
        page.wait_for_selector("#vehicle_vin")

        vin = page.locator("#vehicle_vin")

        # Test case 1: Empty state (neutral)
        assert not page.evaluate("document.getElementById('vehicle_vin').classList.contains('valid')")
        assert not page.evaluate("document.getElementById('vehicle_vin').classList.contains('invalid')")

        # Test case 2: Incomplete VIN length (less than 17 chars)
        vin.fill("123456789012345")
        page.wait_for_timeout(50)
        assert page.evaluate("document.getElementById('vehicle_vin').classList.contains('invalid')")
        assert not page.evaluate("document.getElementById('vehicle_vin').classList.contains('valid')")
        assert page.evaluate("document.getElementById('vehicle_vin').getAttribute('aria-invalid') === 'true'")
        error_msg = page.locator(".field:has(#vehicle_vin) .field-error").text_content()
        assert "должен содержать ровно 17 символов" in error_msg

        # Test case 3: Invalid characters (I, O, Q)
        vin.fill("1234567890123456I")
        page.wait_for_timeout(50)
        assert page.evaluate("document.getElementById('vehicle_vin').classList.contains('invalid')")
        error_msg = page.locator(".field:has(#vehicle_vin) .field-error").text_content()
        assert "за исключением I, O, Q" in error_msg

        # Test case 4: Valid VIN with automatic uppercasing
        # 'a-z' letters should be converted to 'A-Z'
        vin.fill("1234567890abcdefg")
        page.wait_for_timeout(50)
        assert vin.input_value() == "1234567890ABCDEFG"
        assert page.evaluate("document.getElementById('vehicle_vin').classList.contains('valid')")
        assert not page.evaluate("document.getElementById('vehicle_vin').classList.contains('invalid')")
        assert page.evaluate("document.getElementById('vehicle_vin').getAttribute('aria-invalid') === 'false'")
        success_msg = page.locator(".field:has(#vehicle_vin) .field-success").text_content()
        assert "VIN-код корректен" in success_msg

        # Test case 5: Clear field back to neutral
        vin.fill("")
        page.wait_for_timeout(50)
        assert not page.evaluate("document.getElementById('vehicle_vin').classList.contains('valid')")
        assert not page.evaluate("document.getElementById('vehicle_vin').classList.contains('invalid')")

        browser.close()


def test_vehicle_plate_validation(crm_server):
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

        # Open vehicle modal
        page.evaluate("openVehicleModal()")
        page.wait_for_selector("#vehicle_plate")

        plate = page.locator("#vehicle_plate")

        # Test case 1: Empty state (neutral)
        assert not page.evaluate("document.getElementById('vehicle_plate').classList.contains('valid')")
        assert not page.evaluate("document.getElementById('vehicle_plate').classList.contains('invalid')")

        # Test case 2: Incomplete Госномер (less than 4 chars)
        plate.fill("А12")
        page.wait_for_timeout(50)
        assert page.evaluate("document.getElementById('vehicle_plate').classList.contains('invalid')")
        assert not page.evaluate("document.getElementById('vehicle_plate').classList.contains('valid')")
        assert page.evaluate("document.getElementById('vehicle_plate').getAttribute('aria-invalid') === 'true'")
        error_msg = page.locator(".field:has(#vehicle_plate) .field-error").text_content()
        assert "не менее 4 символов" in error_msg

        # Test case 3: Special characters
        plate.fill("А123А@77")
        page.wait_for_timeout(50)
        assert page.evaluate("document.getElementById('vehicle_plate').classList.contains('invalid')")
        error_msg = page.locator(".field:has(#vehicle_plate) .field-error").text_content()
        assert "не должен содержать специальных символов" in error_msg

        # Test case 4: Valid Госномер with automatic uppercasing
        plate.fill("a123aa77")
        page.wait_for_timeout(50)
        assert plate.input_value() == "A123AA77"
        assert page.evaluate("document.getElementById('vehicle_plate').classList.contains('valid')")
        assert not page.evaluate("document.getElementById('vehicle_plate').classList.contains('invalid')")
        assert page.evaluate("document.getElementById('vehicle_plate').getAttribute('aria-invalid') === 'false'")
        success_msg = page.locator(".field:has(#vehicle_plate) .field-success").text_content()
        assert "Госномер корректен" in success_msg

        # Test case 5: Clear field back to neutral
        plate.fill("")
        page.wait_for_timeout(50)
        assert not page.evaluate("document.getElementById('vehicle_plate').classList.contains('valid')")
        assert not page.evaluate("document.getElementById('vehicle_plate').classList.contains('invalid')")

        browser.close()
