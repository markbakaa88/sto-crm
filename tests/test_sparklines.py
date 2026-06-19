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


def test_sparklines_dashboard_rendering(crm_server):
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
        page.wait_for_selector("article.metric:has-text('Выручка за 7 дней')")

        # 1. Проверяем, что на дашборде появились карточки
        revenue_card_text = page.locator("article.metric:has-text('Выручка за 7 дней')")
        orders_card_text = page.locator("article.metric:has-text('Заказы за 7 дней')")

        assert revenue_card_text.count() == 1
        assert orders_card_text.count() == 1

        # 2. Проверяем наличие SVG sparklines
        revenue_svg = page.locator(
            "article.metric:has-text('Выручка за 7 дней') svg.sparkline-revenue"
        )
        orders_svg = page.locator(
            "article.metric:has-text('Заказы за 7 дней') svg.sparkline-orders"
        )

        assert revenue_svg.count() == 1
        assert orders_svg.count() == 1

        # 3. Проверяем a11y атрибуты
        assert revenue_svg.get_attribute("role") == "img"
        assert "Динамика выручки" in revenue_svg.get_attribute("aria-label")

        assert orders_svg.get_attribute("role") == "img"
        assert "Динамика заказов" in orders_svg.get_attribute("aria-label")

        # 4. Проверяем структуру элементов SVG (путь для рисования и заливки)
        assert revenue_svg.locator("path.sparkline-area").count() == 1
        assert revenue_svg.locator("path.sparkline-path").count() == 1
        assert orders_svg.locator("path.sparkline-area").count() == 1
        assert orders_svg.locator("path.sparkline-path").count() == 1

        # 5. Проверяем JS-функцию агрегации getDailyStatsLast7Days
        stats = page.evaluate("getDailyStatsLast7Days()")
        assert isinstance(stats, list)
        assert len(stats) == 7
        for day in stats:
            assert "date" in day
            assert "ordersCount" in day
            assert "revenue" in day
            assert isinstance(day["ordersCount"], int)
            assert isinstance(day["revenue"], (int, float))

        browser.close()
