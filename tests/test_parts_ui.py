import socket
import subprocess
import sys
import time

import pytest


# Find free port helper
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
        cwd=str(__import__("pathlib").Path(__file__).parent.parent.absolute()),
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


def test_parts_pricing_lookup_and_selection(crm_server):
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

        # Mock supplier pricing search API response using route
        page.route(
            "**/api/parts/search?*",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body='{"ok":true,"parts":['
                '{"oem":"555","brand":"CTR","name":"Наконечник рулевой","price":1200.0,"stock":5,"delivery_days":2,"supplier":"rossko"},'
                '{"oem":"555","brand":"CTR","name":"Наконечник рулевой MX","price":1300.0,"stock":10,"delivery_days":1,"supplier":"mx_group"}'
                "]}",
            ),
        )

        page.goto(crm_server)
        page.wait_for_selector(".app")

        # 1. Click "+ Новый заказ" button to open Order Modal
        page.click("button[aria-label='Создать заказ-наряд']")
        page.wait_for_selector("#orderForm")

        # 2. Click "+ Проценка" tab button
        page.click("#btnTabPartsLookup")

        # 3. Assert search form and inputs are visible and accessible
        assert page.is_visible("#partsLookupOem")
        assert page.is_visible("#partsLookupBrand")
        assert page.is_visible("#btnPartsLookupSearch")

        # 4. Fill OEM search field
        page.fill("#partsLookupOem", "555")
        page.fill("#partsLookupBrand", "CTR")

        # 5. Click search button
        page.click("#btnPartsLookupSearch")

        # 6. Wait for results to render (grouped by supplier)
        page.wait_for_selector(".parts-pricing-group")

        # 7. Check grouping and sorting
        groups_count = page.locator(".parts-pricing-group").count()
        assert groups_count > 0

        # Assert supplier names header exist
        supplier_titles = page.locator(
            ".parts-pricing-supplier-title h3"
        ).all_text_contents()
        assert any(
            "Rossko" in title or "MX Group" in title or "TM Parts" in title
            for title in supplier_titles
        )

        # Assert no style="..." (CSP compliant checks on dynamically generated elements)
        style_attrs = page.evaluate("""() => {
            const elements = document.querySelectorAll("#partsLookupResults *");
            const bad = [];
            for (const el of elements) {
                if (el.hasAttribute("style")) {
                    bad.push(el.tagName + ": " + el.getAttribute("style"));
                }
            }
            return bad;
        }""")
        assert len(style_attrs) == 0, f"Found style attributes: {style_attrs}"

        # 8. Click "Выбрать" on one of the search results
        first_btn = page.locator(".btn-select-part").first
        first_btn.click()

        # 9. Verifying that we switched back to Items Tab
        assert page.is_visible("#itemsHost")
        assert page.is_hidden("#orderTabPartsLookup")

        # 10. Verify order items table has our new added item
        item_titles = [
            el.get_attribute("value") or ""
            for el in page.locator(
                "#itemsHost td[data-label='Наименование'] input"
            ).all()
        ]
        assert any("[CTR 555]" in title for title in item_titles)

        browser.close()
