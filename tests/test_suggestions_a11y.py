import socket
import subprocess
import sys
import time

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


def test_suggestions_and_palette_a11y(crm_server):
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

        # 1. Проверим открытие командной палитры по Ctrl+P
        page.keyboard.press("Control+p")
        page.wait_for_selector("#commandPalette.open")

        # Инпут должен иметь фокус
        focused = page.evaluate("() => document.activeElement.id")
        assert focused == "commandSearch"

        # Проверим навигацию кнопками Home/End в палитре
        # Введем текст, чтобы отфильтровать
        page.fill("#commandSearch", "Новый")
        page.wait_for_timeout(200)

        # Home / End
        active_id = page.evaluate("""() => {
            document.dispatchEvent(new KeyboardEvent('keydown', { key: 'End' }));
            const active = document.querySelector('#commandList .command-item.active');
            return active ? active.id : '';
        }""")
        aria_active = page.evaluate(
            "() => document.getElementById('commandSearch').getAttribute('aria-activedescendant')"
        )
        assert active_id != ""
        assert aria_active == active_id

        # Escape закроет
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
        assert page.evaluate("() => document.getElementById('commandPalette').hidden")

        # 2. Глобальный поиск и его searchSuggestions
        page.click("#globalSearch")
        page.fill("#globalSearch", "Иван")  # В демо-базе должен быть Иван
        page.wait_for_timeout(200)

        # Выпадающий список предложений должен открыться
        assert not page.evaluate(
            "() => document.getElementById('searchSuggestions').hidden"
        )

        # ArrowDown
        page.keyboard.press("ArrowDown")
        active_id2 = page.evaluate("""() => {
            const active = document.querySelector('#searchSuggestions .command-item.active');
            return active ? active.id : '';
        }""")
        aria_active2 = page.evaluate(
            "() => document.getElementById('globalSearch').getAttribute('aria-activedescendant')"
        )
        assert active_id2 == "searchOption0"
        assert aria_active2 == "searchOption0"

        # Escape скроет Suggestions
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
        assert page.evaluate(
            "() => document.getElementById('searchSuggestions').hidden"
        )

        browser.close()
