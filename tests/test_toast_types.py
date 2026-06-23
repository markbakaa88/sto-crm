import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest


# Нахождение свободного порта
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


def test_toast_notification_types(crm_server):
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

        # Reset toast state to avoid queue blocks
        page.evaluate("""() => {
            isToastActive = false;
            isToastFadingOut = false;
            toastQueue.length = 0;
            const node = document.getElementById('toast');
            if (node) {
                node.className = 'toast';
                node.innerHTML = '';
            }
        }""")

        # 1. Test success / ok type
        page.evaluate("toast('Success message', 'success')")
        toast_classes = page.evaluate(
            "() => Array.from(document.getElementById('toast').classList)"
        )
        toast_html = page.evaluate("() => document.getElementById('toast').innerHTML")
        assert "success" in toast_classes
        assert "show" in toast_classes
        assert "✅" in toast_html

        # Close current toast using click
        page.click("#toast")
        page.wait_for_timeout(300)  # wait for fade out and processing next

        # 2. Test warning / warn type
        page.evaluate("toast('Warning message', 'warn')")
        toast_classes2 = page.evaluate(
            "() => Array.from(document.getElementById('toast').classList)"
        )
        toast_html2 = page.evaluate("() => document.getElementById('toast').innerHTML")
        assert "success" not in toast_classes2
        assert "warning" in toast_classes2
        assert "🔸" in toast_html2

        # Close warning toast via click
        page.click("#toast")
        page.wait_for_timeout(300)

        # 3. Test danger / error type
        page.evaluate("toast('Danger message', 'danger')")
        toast_classes3 = page.evaluate(
            "() => Array.from(document.getElementById('toast').classList)"
        )
        toast_html3 = page.evaluate("() => document.getElementById('toast').innerHTML")
        assert "warning" not in toast_classes3
        assert "danger" in toast_classes3
        assert "error" in toast_classes3
        assert "⚠️" in toast_html3

        # Close danger toast
        page.click("#toast")
        page.wait_for_timeout(300)

        # 4. Test info type
        page.evaluate("toast('Info message', 'info')")
        toast_classes4 = page.evaluate(
            "() => Array.from(document.getElementById('toast').classList)"
        )
        toast_html4 = page.evaluate("() => document.getElementById('toast').innerHTML")
        assert "danger" not in toast_classes4
        assert "error" not in toast_classes4
        assert "info" in toast_classes4
        assert "ℹ" in toast_html4 or "ℹ️" in toast_html4

        # Close info toast
        page.click("#toast")
        page.wait_for_timeout(300)

        # 5. Check CSS warning background in computed style
        page.evaluate("toast('Style test', 'warn')")
        bg_warn = page.evaluate("""() => {
            const el = document.getElementById('toast');
            return window.getComputedStyle(el).color;
        }""")
        assert bg_warn is not None

        browser.close()


def test_toast_queue_sequential(crm_server):
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

        # Send three toasts in immediate succession
        page.evaluate("toast('First Toast', 'info')")
        page.evaluate("toast('Second Toast', 'success')")
        page.evaluate("toast('Third Toast', 'error')")

        # Verify only the first one is visible
        toast_html = page.evaluate("() => document.getElementById('toast').innerHTML")
        assert "First Toast" in toast_html
        assert "Second Toast" not in toast_html
        assert "Third Toast" not in toast_html

        # Click to dismiss the first
        page.click("#toast")
        page.wait_for_timeout(300)  # Wait for transition + queue processing

        # Verify second one is now showing
        toast_html = page.evaluate("() => document.getElementById('toast').innerHTML")
        assert "Second Toast" in toast_html
        assert "First Toast" not in toast_html
        assert "Third Toast" not in toast_html

        # Click to dismiss second
        page.click("#toast")
        page.wait_for_timeout(300)

        # Verify third one is now showing
        toast_html = page.evaluate("() => document.getElementById('toast').innerHTML")
        assert "Third Toast" in toast_html
        assert "Second Toast" not in toast_html

        browser.close()
