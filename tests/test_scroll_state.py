import socket
import subprocess
import time

import pytest


# Попробуем найти свободный порт
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


def test_scroll_position_saved(crm_server):
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

        # Перейдем в Клиенты
        page.click("button[data-route='customers']")
        page.wait_for_selector(
            ".route-view[data-view='customers'] table, .route-view[data-view='customers'] .empty-state"
        )

        # Симулируем большую высоту документа и контента, чтобы страница точно скроллилась
        page.evaluate("""
            document.documentElement.style.scrollBehavior = 'auto';
            const spacer = document.createElement('div');
            spacer.style.height = '5000px';
            document.body.appendChild(spacer);
        """)

        # Проскроллим страницу вниз
        page.evaluate("window.scrollTo(0, 500)")
        scroll1 = page.evaluate("window.scrollY")
        assert scroll1 > 400

        # Переключим вкладку на Склад
        page.evaluate(
            "document.querySelector(\"button[data-route='inventory']\").click()"
        )
        page.wait_for_selector(
            ".route-view[data-view='inventory'] table, .route-view[data-view='inventory'] .empty-state"
        )

        # Проверим, что скролл сбросился или ушел наверх для новой страницы
        # Переключим обратно на Клиенты
        page.evaluate(
            "document.querySelector(\"button[data-route='customers']\").click()"
        )
        page.wait_for_selector(
            ".route-view[data-view='customers'] table, .route-view[data-view='customers'] .empty-state"
        )

        # Скролл должен восстановиться
        scroll2 = page.evaluate("window.scrollY")
        assert scroll2 == scroll1

        browser.close()
