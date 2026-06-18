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

def test_highlight_text_helper_unit(crm_server):
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

        # Test base cases
        res = page.evaluate("highlightText('Привет Мир', 'мир')")
        assert res == 'Привет <mark class="search-match">Мир</mark>'

        res = page.evaluate("highlightText('Особый [текст] здесь', '[текст]')")
        assert res == 'Особый <mark class="search-match">[текст]</mark> здесь'

        res = page.evaluate("highlightText('Hello World', '')")
        assert res == 'Hello World'

        res = page.evaluate("highlightText('Hello World', '   ')")
        assert res == 'Hello World'

        # Test XSS vectors in text
        res = page.evaluate("highlightText('<script>alert(1)</script>', 'alert')")
        assert res == '&lt;script&gt;<mark class="search-match">alert</mark>(1)&lt;/script&gt;'

        # Test XSS vectors in query
        res = page.evaluate("highlightText('Hello World', '<script>alert</g>')")
        assert res == 'Hello World'

        res = page.evaluate("highlightText('Hello <script>', '<script>')")
        assert res == 'Hello <mark class="search-match">&lt;script&gt;</mark>'

        browser.close()

def test_highlight_search_results_in_tables(crm_server):
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

        # 1. Test Customer Table Highlight
        # Click on customers tab (👥 Клиенты)
        page.click("button[data-route='customers']")
        page.wait_for_selector("table[aria-label='Таблица клиентов']")

        # Enter customer name query from demo dataset
        page.fill("#globalSearch", "Иван")
        page.wait_for_timeout(600)  # Wait for loadData debounce (450ms)

        # Check that highlight occurs on match in the table
        page.wait_for_selector("[data-view='customers'] .search-match")
        matches = page.eval_on_selector_all("[data-view='customers'] .search-match", "elements => elements.map(el => el.textContent)")
        assert len(matches) > 0
        for m in matches:
            assert "иван" in m.lower()

        # 2. Test Vehicles Table Highlight
        page.click("button[data-route='vehicles']")
        page.wait_for_selector("table[aria-label='Таблица автомобилей']")

        # Clean search first
        page.fill("#globalSearch", "")
        page.wait_for_timeout(600)

        # Enter vehicle name/plate/vin query from demo dataset
        page.fill("#globalSearch", "Toyota")
        page.wait_for_timeout(600)

        page.wait_for_selector("[data-view='vehicles'] .search-match")
        veh_matches = page.eval_on_selector_all("[data-view='vehicles'] .search-match", "elements => elements.map(el => el.textContent)")
        assert len(veh_matches) > 0
        for m in veh_matches:
            assert "toyota" in m.lower() or "camry" in m.lower() or "rav4" in m.lower()

        # 3. Test Inventory Table Highlight
        page.click("button[data-route='inventory']")
        page.wait_for_selector("table[aria-label='Таблица складских позиций']")

        # Clean search first
        page.fill("#globalSearch", "")
        page.wait_for_timeout(600)

        # Search inventory item by SKU
        page.fill("#globalSearch", "OF-TY")
        page.wait_for_timeout(600)

        page.wait_for_selector("[data-view='inventory'] .search-match")
        inv_matches = page.eval_on_selector_all("[data-view='inventory'] .search-match", "elements => elements.map(el => el.textContent)")
        assert len(inv_matches) > 0
        for m in inv_matches:
            assert "of" in m.lower() or "ty" in m.lower() or "фильтр" in m.lower()

        browser.close()
