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


def test_catalog_expand_collapse(crm_server):
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

        # Клик по вкладке Каталог авто
        page.click("button[data-route='catalog']")
        page.wait_for_selector(".catalog-make")

        # Проверяем, что в демо-данных есть марки с большим количеством моделей
        # Например, Toyota, Hyundai или Kia
        # В сид-данных нет большого списка моделей для одной марки, поэтому давайте
        # добавим дополнительные модели прямо на лету в `state.data.catalog` через page.evaluate
        # или просто проверим наличие действий.
        # Давайте добавим в каталог марку "TestMake" со 20 моделями через page.evaluate
        page.evaluate("""
            state.data.car_catalog.makes.unshift("TestMake");
            state.data.car_catalog.models["TestMake"] = Array.from({length: 20}, (_, i) => "Model " + (i + 1));
            render();
        """)

        # Убедимся, что кнопка "Показать ещё" существует для TestMake
        btn_selector = "button[data-action='expand-make'][data-make='TestMake']"
        page.wait_for_selector(btn_selector)

        # Клик по "Показать ещё"
        page.click(btn_selector)

        # Кнопка должна смениться на "Свернуть"
        collapse_selector = "button[data-action='collapse-make'][data-make='TestMake']"
        page.wait_for_selector(collapse_selector)

        # Клик по "Свернуть"
        page.click(collapse_selector)

        # Кнопка должна снова стать "Показать ещё"
        page.wait_for_selector(btn_selector)

        browser.close()
