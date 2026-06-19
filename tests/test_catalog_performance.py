import socket
import subprocess
import sys
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


def test_catalog_search_debounce_and_infinite_scroll(crm_server):
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
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        page.goto(crm_server)
        page.wait_for_selector(".app")

        # Перейти в каталог авто
        page.click("button[data-route='catalog']")
        page.wait_for_selector("#catalogFilter")

        # На лету добавим 150 тестовых марок, чтобы проверить infinite scroll и дебаунс
        page.evaluate("""
            state.data.car_catalog.makes = Array.from({length: 150}, (_, i) => "TestMake_" + (i + 1));
            state.data.car_catalog.models = {};
            state.data.car_catalog.makes.forEach(make => {
                state.data.car_catalog.models[make] = Array.from({length: 20}, (_, k) => "Model " + (k + 1));
            });
            state.data.car_catalog_stats = {
                makes: 150,
                models: 3000,
                empty_makes: 0
            };
            render();
        """)

        # Проверим, что изначально отображены 60 элементов
        page.wait_for_selector(".catalog-make")
        initial_count = page.locator(".catalog-make").count()
        assert initial_count == 60, f"Expected 60 initial items, got {initial_count}"

        # 1. Проверяем дебаунс при вводе
        # Вводим текст в фильтр
        page.fill("#catalogFilter", "TestMake_150")

        # Сразу после ввода поисковый таймер должен быть активен
        timer_active = page.evaluate("state.catalogSearchTimer !== null")
        assert timer_active, "Search timer should be set"

        # Ждем 250мс (180мс дебаунс + запас)
        page.wait_for_timeout(300)

        # После применения фильтра количество марок должно уменьшиться
        filtered_count = page.locator(".catalog-make").count()
        assert filtered_count == 1, (
            f"Filtered count should be exactly 1, got {filtered_count}"
        )

        # Очистим фильтр
        page.fill("#catalogFilter", "")
        page.wait_for_timeout(300)

        reset_count = page.locator(".catalog-make").count()
        assert reset_count == 60, f"Expected count reset to 60, got {reset_count}"

        # 2. Проверяем infinite scroll
        # Прокручиваем страницу вниз
        page.evaluate(
            "window.scrollTo({top: document.body.scrollHeight, behavior: 'instant'})"
        )
        page.wait_for_timeout(
            200
        )  # даем время отработать requestAnimationFrame и скролл-событию

        # После скролла лимит должен увеличиться до 120
        scrolled_count = page.locator(".catalog-make").count()
        assert scrolled_count == 120, (
            f"Expected 120 items after scroll, got {scrolled_count}"
        )

        # Прокручиваем вниз еще раз
        page.evaluate(
            "window.scrollTo({top: document.body.scrollHeight, behavior: 'instant'})"
        )
        page.wait_for_timeout(200)

        # Должно отобразиться все 150 элементов
        scrolled_count_2 = page.locator(".catalog-make").count()
        assert scrolled_count_2 == 150, (
            f"Expected 150 items after second scroll, got {scrolled_count_2}"
        )

        browser.close()
