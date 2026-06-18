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


def test_order_items_keyboard_navigation(crm_server):
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

        # Ждем, пока загрузятся данные CRM (state.data)
        page.wait_for_function("() => typeof state !== 'undefined' && state.data")

        # 1. Открываем модальное окно заказа через openOrderModal
        page.evaluate("openOrderModal()")
        page.wait_for_selector("#modalBackdrop.open")
        page.wait_for_selector("#itemsHost")

        # Проверяем начальное состояние: должна быть 1 строка позиций
        row_count = page.evaluate("() => document.querySelectorAll('#itemsHost tr[data-index]').length")
        assert row_count == 1

        # 2. Добавим вторую позицию (+ Работа), чтобы было больше одной строки
        page.click("#addService")
        page.wait_for_timeout(400) # Даем кнопке разблокироваться/отрисоваться
        row_count2 = page.evaluate("() => document.querySelectorAll('#itemsHost tr[data-index]').length")
        assert row_count2 == 2

        # 3. Фокусируемся на первом поле ввода названия в первой строке (data-index="0")
        title0_xpath = 'tr[data-index="0"] input[data-item="title"]'
        page.focus(title0_xpath)

        # 4. Проверяем, что нажатие Enter в не-последней строке не закрывает модалку и не добавляет строки
        page.keyboard.press("Enter")
        page.wait_for_timeout(200)

        # Модалка должна быть открыта, строк должно остаться 2
        assert page.evaluate("() => document.getElementById('modalBackdrop').classList.contains('open')")
        assert page.evaluate("() => document.querySelectorAll('#itemsHost tr[data-index]').length") == 2

        # 5. Проверяем клавишу ArrowDown (переход на аналогичный input в строке ниже)
        page.keyboard.press("ArrowDown")
        page.wait_for_timeout(200)

        # Фокус должен переместиться на title в строке 1
        is_focused_title1 = page.evaluate(
            "() => document.activeElement === document.querySelector('tr[data-index=\"1\"] input[data-item=\"title\"]')"
        )
        assert is_focused_title1 is True

        # 6. Проверяем клавишу ArrowUp (переход обратно в строку 0)
        page.keyboard.press("ArrowUp")
        page.wait_for_timeout(200)

        is_focused_title0 = page.evaluate(
            "() => document.activeElement === document.querySelector('tr[data-index=\"0\"] input[data-item=\"title\"]')"
        )
        assert is_focused_title0 is True

        # 7. Проверяем перемещение фокуса в выпадающем списке (kind select)
        page.focus('tr[data-index="0"] select[data-item="kind"]')
        page.keyboard.press("ArrowDown")
        page.wait_for_timeout(200)

        is_focused_kind1 = page.evaluate(
            "() => document.activeElement === document.querySelector('tr[data-index=\"1\"] select[data-item=\"kind\"]')"
        )
        assert is_focused_kind1 is True

        # 8. Проверяем клавишу Enter на последней строке (data-index="1")
        # Фокусируем последнее поле ввода (например, себестоимость unit_cost в строке 1)
        page.focus('tr[data-index="1"] input[data-item="unit_cost"]')
        page.keyboard.press("Enter")
        page.wait_for_timeout(400) # Даем сработать добавлению и отрисовке

        # Должна появиться 3-я строка (data-index="2")
        assert page.evaluate("() => document.querySelectorAll('#itemsHost tr[data-index]').length") == 3

        # Фокус должен быть на первом поле третьей строки (select data-item="kind")
        is_focused_new_kind = page.evaluate(
            "() => document.activeElement === document.querySelector('tr[data-index=\"2\"] select[data-item=\"kind\"]')"
        )
        assert is_focused_new_kind is True

        browser.close()
