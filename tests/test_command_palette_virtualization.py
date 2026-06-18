import socket
import subprocess
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
        ["python3", "main.py", "--port", str(port), "--no-browser", "--demo"],
        cwd=str(Path(__file__).parent.parent.absolute()),
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


def test_command_palette_rendering_limit(crm_server):
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
        page.wait_for_function("() => typeof state !== 'undefined' && state.data")

        # 1. Проверим командную палитру
        page.keyboard.press("Control+p")
        page.wait_for_selector("#commandPalette.open")

        # В демо палитре всего ~13 фиксированных команд. Но давайте отфильтруем пустым или коротким вводом.
        # Поскольку команд всего 13, а лимит 20, индикатор еще не должен рендериться.
        items_count = page.evaluate("() => document.querySelectorAll('#commandList .command-item').length")
        assert items_count <= 20
        assert not page.locator(".commands-more").is_visible()

        # Закроем командную палитру перед переходом к глобальному поиску
        page.keyboard.press("Escape")
        page.wait_for_selector("#commandPalette:not(.open)", state="hidden")

        # 2. Глобальный поиск. Заполним базу фейковыми клиентами/авто, чтобы вызвать превышение 20 элементов.
        # Внедрим более 25 фейковых клиентов/автомобилей или деталей.
        page.evaluate("""() => {
            state.data.customers = [];
            for (let i = 0; i < 30; i++) {
                state.data.customers.push({
                    id: 1000 + i,
                    name: `Клиент ${i} Иван`,
                    phone: `+7 900 111-22-${String(i).padStart(2, '0')}`,
                    email: `ivan_${i}@example.ru`
                });
            }
            state.data.vehicles = [];
            state.data.orders = [];
            state.data.inventory = [];
        }""")

        page.click("#globalSearch")
        page.fill("#globalSearch", "Иван")
        page.wait_for_selector("#searchSuggestions:not([hidden])")

        suggestions_count = page.evaluate("() => document.querySelectorAll('#searchSuggestions .command-item').length")
        assert suggestions_count == 20

        # Должен быть индикатор "+ еще N позиций"
        more_indicator = page.locator(".suggestions-more")
        assert more_indicator.is_visible()
        indicator_text = more_indicator.text_content()
        assert "+ еще 10 позиций" in indicator_text

        # Проверим навигацию кнопками ArrowUp/ArrowDown по усеченному списку
        page.keyboard.press("ArrowDown")
        active_id = page.evaluate("() => document.activeElement.getAttribute('aria-activedescendant')")
        assert active_id == "searchOption0"

        # Долистаем до 20-го элемента (индекс 19)
        for _ in range(19):
            page.keyboard.press("ArrowDown")

        active_id_last = page.evaluate("() => document.activeElement.getAttribute('aria-activedescendant')")
        assert active_id_last == "searchOption19"

        # Еще одно нажатие ArrowDown перенесет обратно на 0
        page.keyboard.press("ArrowDown")
        active_id_loop = page.evaluate("() => document.activeElement.getAttribute('aria-activedescendant')")
        assert active_id_loop == "searchOption0"

        browser.close()
