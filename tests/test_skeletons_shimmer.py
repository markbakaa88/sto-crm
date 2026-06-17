import socket
import subprocess
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


def test_skeletons_loading_rendering(crm_server):
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

        # 1. Проверяем, что SkeletonBuilder определен и генерирует скелетоны с aria-hidden="true"
        skeletons_ok = page.evaluate("""() => {
            if (typeof SkeletonBuilder !== 'object') return 'SkeletonBuilder not defined';
            const appts = SkeletonBuilder.appointments(3);
            if (!appts.includes('aria-hidden="true"')) return 'appointments skeleton missing aria-hidden';
            if (!appts.includes('skeleton-shimmer')) return 'appointments skeleton missing skeleton-shimmer';
            
            const ords = SkeletonBuilder.orders(3, false);
            if (!ords.includes('aria-hidden="true"')) return 'orders skeleton missing aria-hidden';
            
            const custs = SkeletonBuilder.customers(3);
            if (!custs.includes('aria-hidden="true"')) return 'customers skeleton missing aria-hidden';
            
            const inv = SkeletonBuilder.inventory(3);
            if (!inv.includes('aria-hidden="true"')) return 'inventory skeleton missing aria-hidden';
            
            return 'OK';
        }""")
        assert skeletons_ok == "OK"

        # 2. Переводим состояние в loading и проверяем, отображаются ли скелетоны на вкладке Заказы
        page.click("button[data-route='orders']")
        page.wait_for_selector("table[aria-label='Таблица заказ-нарядов']")

        # Имитируем loading=true
        page.evaluate("setLoadingState(true)")

        # Проверяем, что в таблице заказов отображаются строки скелетонов
        has_skeletons = page.locator("[data-view='orders'] tr.skeleton-row").count()
        assert has_skeletons > 0

        # Проверяем, что на роуте клиентов тоже отображаются клиенты в виде скелетонов
        page.click("button[data-route='customers']")
        assert page.locator("[data-view='customers'] tr.skeleton-row").count() > 0

        # Возвращаем loading=false
        page.evaluate("setLoadingState(false)")
        assert page.locator("[data-view='customers'] tr.skeleton-row").count() == 0

        browser.close()
