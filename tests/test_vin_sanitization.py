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
    project_root = Path(__file__).parent.parent.absolute()
    proc = subprocess.Popen(
        [sys.executable, str(project_root / "main.py"), "--port", str(port), "--no-browser", "--demo"],
        cwd=str(project_root),
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


def test_vin_sanitization_and_decoding(crm_server):
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

        # Wait for data bootstrap
        page.evaluate(
            "() => new Promise(resolve => { if (state.data) return resolve(); const check = setInterval(() => { if (state.data) { clearInterval(check); resolve(); } }, 50); })"
        )

        # Open vehicle modal
        page.evaluate("openVehicleModal()")
        page.wait_for_selector("#vehicle_vin")

        vin = page.locator("#vehicle_vin")
        decoder = page.locator(".vin-decoder")

        # Verify initial decoder state (empty value -> 0 / 17 символов)
        assert decoder.is_visible()
        length_el = decoder.locator(".vin-decoder-length")
        assert "0 / 17 символов" in (length_el.text_content() or "")

        # Test case 1: Auto-typing conversion to upper case and cutting out I, O, Q
        vin.fill("abc")
        page.wait_for_timeout(50)
        assert vin.input_value() == "ABC"
        assert "3 / 17 символов" in (length_el.text_content() or "")

        # Standard inputs with I, O, Q mixed in
        vin.fill("jIaObQc123")
        page.wait_for_timeout(50)
        assert vin.input_value() == "JABC123"
        assert "7 / 17 символов" in (length_el.text_content() or "")

        # Test case 2: Country decoding by WMI
        # "JAA" -> Япония
        vin.fill("JAA")
        page.wait_for_timeout(50)
        assert vin.input_value() == "JAA"
        country_el = decoder.locator(".vin-decoder-country")
        assert (country_el.text_content() or "") == "Япония"

        # "WUA" -> Германия
        vin.fill("WUA")
        page.wait_for_timeout(50)
        assert (country_el.text_content() or "") == "Германия"

        # "1AD" -> США
        vin.fill("1AD")
        page.wait_for_timeout(50)
        assert (country_el.text_content() or "") == "США"

        # "L5Y" -> Китай
        vin.fill("L5Y")
        page.wait_for_timeout(50)
        assert (country_el.text_content() or "") == "Китай"

        # "VF3" -> Франция
        vin.fill("VF3")
        page.wait_for_timeout(50)
        assert (country_el.text_content() or "") == "Франция"

        # "YS3" -> Швеция
        vin.fill("YS3")
        page.wait_for_timeout(50)
        assert (country_el.text_content() or "") == "Швеция"

        # "VSS" -> Испания
        vin.fill("VSS")
        page.wait_for_timeout(50)
        assert (country_el.text_content() or "") == "Испания"

        # "TMB" -> Чехия
        vin.fill("TMB")
        page.wait_for_timeout(50)
        assert (country_el.text_content() or "") == "Чехия"

        # "9AB" -> Unknown (Неизвестно)
        vin.fill("9AB")
        page.wait_for_timeout(50)
        unknown_el = decoder.locator(".vin-decoder-unknown")
        assert (unknown_el.text_content() or "") == "Неизвестно"

        # Less than 3 chars should not show country wrap at all
        vin.fill("WA")
        page.wait_for_timeout(50)
        assert not decoder.locator(".vin-decoder-country-wrap").is_visible()

        browser.close()
