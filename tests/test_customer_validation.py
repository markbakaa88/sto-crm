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


def test_customer_phone_masking(crm_server):
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

        # Open customer modal
        page.evaluate("openCustomerModal()")
        page.wait_for_selector("#customer_phone")

        phone = page.locator("#customer_phone")

        # Test case 1: Empty state (neutral)
        assert not page.evaluate("document.getElementById('customer_phone').classList.contains('valid')")
        assert not page.evaluate("document.getElementById('customer_phone').classList.contains('invalid')")

        # Test case 2: Typing digit sequence without international prefix
        phone.fill("9031234567")
        page.wait_for_timeout(50)
        assert phone.input_value() == "+7 (903) 123-45-67"
        assert page.evaluate("document.getElementById('customer_phone').classList.contains('valid')")
        assert not page.evaluate("document.getElementById('customer_phone').classList.contains('invalid')")

        # Test case 3: Slicing backspace trap
        # Clear field and type incomplete number (should be invalid)
        phone.fill("")
        phone.type("903")
        page.wait_for_timeout(50)
        assert phone.input_value() == "+7 (903)"
        assert page.evaluate("document.getElementById('customer_phone').classList.contains('invalid')")
        assert not page.evaluate("document.getElementById('customer_phone').classList.contains('valid')")

        # Type to complete, then hit Backspace
        phone.fill("")
        phone.type("9031")
        page.wait_for_timeout(50)
        assert phone.input_value() == "+7 (903) 1"
        phone.press("Backspace")
        page.wait_for_timeout(50)
        # Since '1' was at the end, standard backspace deleted '1', leaving +7 (903) which gets formatted/masked
        assert phone.input_value() == "+7 (903)"
        
        # Hit Backspace again: the char before cursor is ')' (mask character).
        # Our keydown handler intercepts backspace and deletes '3' (the digit before ')').
        # Value becomes +7 (90 and formats to "+7 (90".
        phone.press("Backspace")
        page.wait_for_timeout(50)
        assert phone.input_value() == "+7 (90"

        # Test case 4: Typing with 8-prefix
        phone.fill("")
        phone.type("89001112233")
        page.wait_for_timeout(50)
        assert phone.input_value() == "+7 (900) 111-22-33"
        assert page.evaluate("document.getElementById('customer_phone').classList.contains('valid')")

        # Test case 5: Typing with +7-prefix
        phone.fill("")
        phone.type("+79001112233")
        page.wait_for_timeout(50)
        assert phone.input_value() == "+7 (900) 111-22-33"
        assert page.evaluate("document.getElementById('customer_phone').classList.contains('valid')")

        browser.close()


def test_customer_email_validation(crm_server):
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

        # Open customer modal
        page.evaluate("openCustomerModal()")
        page.wait_for_selector("#customer_email")

        email = page.locator("#customer_email")

        # Testcase 1: Empty state (neutral)
        assert not page.evaluate("document.getElementById('customer_email').classList.contains('valid')")
        assert not page.evaluate("document.getElementById('customer_email').classList.contains('invalid')")

        # Testcase 2: Typing invalid email
        email.fill("invalid-email")
        page.wait_for_timeout(50)
        assert page.evaluate("document.getElementById('customer_email').classList.contains('invalid')")
        assert not page.evaluate("document.getElementById('customer_email').classList.contains('valid')")
        # Check warning message
        error_msg = page.locator(".field:has(#customer_email) .field-error").text_content()
        assert "Некорректный формат email" in error_msg

        # Testcase 3: Typing valid email
        email.fill("correct@example.com")
        page.wait_for_timeout(50)
        assert page.evaluate("document.getElementById('customer_email').classList.contains('valid')")
        assert not page.evaluate("document.getElementById('customer_email').classList.contains('invalid')")
        # Check success message
        success_msg = page.locator(".field:has(#customer_email) .field-success").text_content()
        assert "Email корректен" in success_msg

        # Testcase 4: Clearing the field
        email.fill("")
        page.wait_for_timeout(50)
        assert not page.evaluate("document.getElementById('customer_email').classList.contains('valid')")
        assert not page.evaluate("document.getElementById('customer_email').classList.contains('invalid')")

        browser.close()
