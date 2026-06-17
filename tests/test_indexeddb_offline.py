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
    # Запускаем сервер с demo-данными и без открытия браузера
    proc = subprocess.Popen(
        ["python3", "main.py", "--port", str(port), "--no-browser", "--demo"],
        cwd=str(__import__("pathlib").Path(__file__).parent.parent.absolute()),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Ждем запуска сервера
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


def test_indexeddb_offline_and_reconciliation(crm_server):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        # Используем предписанный MCP sandbox config для Chromium на Rock Pi
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

        # Шаг 1: Загрузить CRM в режиме онлайн
        page.goto(crm_server)
        page.wait_for_selector(".app")

        # Проверим, что данные успешно подгрузились (например, виден сайдбар или основной заголовок)
        page.wait_for_selector("#viewTitle")
        assert page.locator("#viewTitle").inner_text() == "Панель"

        # Дадим асинхронным операциям IndexedDB немного времени
        time.sleep(1.5)

        # Шаг 2: Симулировать отключение сети на уровне роутов (режим оффлайн в SPA)
        # block requests to /api/bootstrap
        page.route("**/api/bootstrap*", lambda route: route.abort("failed"))
        page.route("**/api/bootstrap?*", lambda route: route.abort("failed"))

        # Симулируем событие offline в браузере
        page.evaluate("window.dispatchEvent(new Event('offline'))")

        # Ждем появления баннера оффлайна
        page.wait_for_selector(".offline-banner", timeout=5000)
        banner_text = page.locator(".offline-banner").inner_text()
        assert "Данные из кэша" in banner_text

        # Шаг 4: Сделать скриншот для визуального подтверждения корректности рендеринга оффлайн-режима
        screenshot_path = "/home/zxc/CRM/offline_mode_screenshot.png"
        page.screenshot(path=screenshot_path)
        print(f"Offline status screenshot saved to: {screenshot_path}")

        # Шаг 5: Восстановить сетевое подключение (убираем блокировку маршрутов)
        page.unroute("**/api/bootstrap*")
        page.unroute("**/api/bootstrap?*")
        page.evaluate("window.dispatchEvent(new Event('online'))")

        # Ждем автоматической синхронизации при переходе в онлайн
        page.wait_for_selector(".offline-banner", state="detached", timeout=5000)

        # Даем время синхронизации
        time.sleep(1)

        browser.close()
