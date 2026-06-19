import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest


# Попробуем найти свободный порт
def get_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def crm_server(tmp_path):
    port = get_free_port()
    db_file = tmp_path / "test_sto_crm_analytics.sqlite3"
    project_root = Path(__file__).parent.parent.absolute()
    
    # Запускаем сервер с временной базой, чтобы demo-данные сидировались с нуля
    proc = subprocess.Popen(
        [sys.executable, str(project_root / "main.py"), "--port", str(port), "--no-browser", "--demo", "--db", str(db_file)],
        cwd=str(project_root),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
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


def test_analytics_charts_and_tooltips(crm_server):
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

        console_errors = []
        page.on("console", lambda msg: console_errors.append(msg.text) if (
            msg.type == "error" or
            "CSP" in msg.text or
            "Content-Security-Policy" in msg.text or
            "violate" in msg.text or
            "refused" in msg.text
        ) else None)
        page.on("pageerror", lambda err: console_errors.append(f"PAGE ERROR: {err}"))
        page.goto(crm_server)
        page.wait_for_selector(".app")
        # Wait for data bootstrap to complete
        page.wait_for_function("() => typeof state !== 'undefined' && state.data")

        # Перейдем в раздел Отчетов
        page.click("button[data-route='reports']")
        page.wait_for_selector(".orders-by-day-chart-svg")
        page.wait_for_selector(".revenue-by-category-chart-svg")

        # Дадим асинхронным процессам/репорту немного времени на прогрузку и обнаружение CSP
        page.wait_for_timeout(500)
        assert len(console_errors) == 0, f"CSP or console errors after loading reports: {console_errors}"

        # 1. Проверим, что графики отрисовались
        bar_rects = page.locator(".bar-rect")
        donut_segments = page.locator(".donut-segment")

        assert bar_rects.count() == 7
        assert donut_segments.count() == 2

        # 2. Проверим интерактивность и тултип для Bar Chart
        first_bar = bar_rects.nth(0)
        first_bar.hover()
        tooltip = page.locator("#chart-tooltip")
        page.wait_for_selector("#chart-tooltip.visible", timeout=3000)

        tooltip_text_hover = tooltip.inner_html()
        assert "Пн" in tooltip_text_hover or "заезд" in tooltip_text_hover

        # Скрываем тултип
        page.mouse.move(0, 0)
        page.wait_for_selector("#chart-tooltip:not(.visible)", timeout=3000)

        # Фокусируемся с клавиатуры
        first_bar.focus()
        page.wait_for_selector("#chart-tooltip.visible", timeout=3000)
        tooltip_text_focus = tooltip.inner_html()
        assert tooltip_text_focus == tooltip_text_hover

        # Размываем фокус
        first_bar.blur()
        page.wait_for_selector("#chart-tooltip:not(.visible)", timeout=3000)

        # 3. Проверим интерактивность и тултип для Donut Chart
        first_segment = donut_segments.nth(0)
        first_segment.hover()
        page.wait_for_selector("#chart-tooltip.visible", timeout=3000)

        segment_tooltip_text = tooltip.inner_html()
        assert "Услуги" in segment_tooltip_text or "Запчасти" in segment_tooltip_text

        # Убираем
        page.mouse.move(0, 0)
        page.wait_for_selector("#chart-tooltip:not(.visible)", timeout=3000)

        # Проверка итоговой чистоты консоли
        assert len(console_errors) == 0, f"Found console/CSP or page errors at the end: {console_errors}"

        browser.close()
