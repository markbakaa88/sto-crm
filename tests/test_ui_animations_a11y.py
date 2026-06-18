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


def test_ui_animations_a11y(crm_server):
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

        # 1. Locate system menu button and verify initial state
        btn = page.locator("#systemMenuBtn")
        menu = page.locator("#systemMenu")

        assert btn.get_attribute("aria-expanded") == "false"
        assert not menu.is_visible()

        # 2. Click system menu button and check if active/focused
        btn.click()
        page.wait_for_timeout(100) # wait for open animations

        assert btn.get_attribute("aria-expanded") == "true"
        assert menu.is_visible()

        # 3. Ensure role="menu", role="menuitemcheckbox", and role="menuitem" are correct
        assert menu.get_attribute("role") == "menu"
        
        # Check toggles roles
        theme_toggle = page.locator("#themeToggle")
        density_toggle = page.locator("#densityToggle")
        audio_toggle = page.locator("#audioToggle")

        assert theme_toggle.get_attribute("role") == "menuitemcheckbox"
        assert density_toggle.get_attribute("role") == "menuitemcheckbox"
        assert audio_toggle.get_attribute("role") == "menuitemcheckbox"

        # Check default action roles
        backup_btn = page.locator("#backupBtn")
        shutdown_btn = page.locator("#shutdownBtn")
        
        assert backup_btn.get_attribute("role") == "menuitem"
        assert shutdown_btn.get_attribute("role") == "menuitem"

        # Check aria-checked or aria-pressed
        aria_checked_audio = audio_toggle.get_attribute("aria-checked")
        assert aria_checked_audio in ["true", "false"]

        # Press Escape and verify that menu is closed and focus is returned to the button
        page.keyboard.press("Escape")
        page.wait_for_timeout(100) # wait for close animations

        assert btn.get_attribute("aria-expanded") == "false"
        assert not menu.is_visible()

        # Focus should return to #systemMenuBtn
        is_focused = page.evaluate("document.activeElement.id === 'systemMenuBtn'")
        assert is_focused

        browser.close()
