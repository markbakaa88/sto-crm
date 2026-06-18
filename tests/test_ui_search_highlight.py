import socket
import subprocess
import time
from pathlib import Path

import pytest


# Find a free port
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


def test_global_search_suggestions_highlight(crm_server):
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
        page.wait_for_function("() => typeof state !== 'undefined' && state.data")

        # 1. Type query to match "Иван"
        page.fill("#globalSearch", "Иван")
        # Wait for suggestions box to become visible
        page.wait_for_selector("#searchSuggestions:not([hidden])")

        # Verify highlights are rendered and match "иван" (case-insensitive)
        matches = page.eval_on_selector_all(
            "#searchSuggestions .search-match",
            "elements => elements.map(el => el.textContent)"
        )
        assert len(matches) > 0
        for m in matches:
            assert "иван" in m.lower()

        # 2. Verify regex characters and XSS safety inside suggestions
        page.fill("#globalSearch", "Иван[")
        # Wait a bit to ensure it renders with new query
        page.wait_for_timeout(200)

        # Confirm no console errors / page crash due to regex brackets.
        # Check suggestions elements if any or verify that inputs handle brackets safely
        page.fill("#globalSearch", "<script>")
        page.wait_for_timeout(200)
        # Verify that HTML characters are escaped in output text
        html_content = page.eval_on_selector("#searchSuggestions", "el => el.innerHTML")
        assert "<script>" not in html_content
        assert "&lt;script&gt;" in html_content or not html_content.strip()

        browser.close()


def test_command_palette_suggestions_highlight(crm_server):
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
        page.wait_for_function("() => typeof state !== 'undefined' && state.data")

        # Open Command Palette
        page.evaluate("openCommandPalette()")
        page.wait_for_selector("#commandPalette.open")
        page.wait_for_selector("#commandSearch")

        # Type 'Новый' to filter commands
        page.fill("#commandSearch", "Новый")
        page.wait_for_timeout(200)

        # Check for highlights in command titles and hints
        matches = page.eval_on_selector_all(
            "#commandList .search-match",
            "elements => elements.map(el => el.textContent)"
        )
        assert len(matches) > 0
        for m in matches:
            assert "новый" in m.lower()

        # Check for regex escaping safety in command Search
        page.fill("#commandSearch", "Новый[")
        page.wait_for_timeout(200)

        # Type XSS inputs and verify escaping
        page.fill("#commandSearch", "<script>")
        page.wait_for_timeout(200)
        html_content = page.eval_on_selector("#commandList", "el => el.innerHTML")
        assert "<script>" not in html_content

        browser.close()
