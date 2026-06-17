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


def test_safe_local_storage_normal_behavior(crm_server):
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

        # Проверим, что safeLocalStorage определен и работает нормально
        assert page.evaluate("typeof safeLocalStorage !== 'undefined'")

        # Test normal set/get
        page.evaluate("safeLocalStorage.setItem('norm_key', 'hello_world')")
        val = page.evaluate("safeLocalStorage.getItem('norm_key')")
        assert val == "hello_world"

        # Test normal remove
        page.evaluate("safeLocalStorage.removeItem('norm_key')")
        val_after = page.evaluate("safeLocalStorage.getItem('norm_key')")
        assert val_after is None

        browser.close()


def test_safe_local_storage_disabled(crm_server):
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

        # Симулируем отключенный/заблокированный localStorage (выбрасывает ошибку при любом доступе)
        # Для этого переопределяем свойство window.localStorage так, чтобы обращение к нему выбрасывало исключение.
        init_js = """
        Object.defineProperty(window, 'localStorage', {
            get: function() {
                throw new Error("SecurityError: Access to 'localStorage' is denied");
            }
        });
        """
        page.add_init_script(init_js)

        page.goto(crm_server)
        page.wait_for_selector(".app")

        # Проверим, что в такой агрессивной среде обертка определена
        assert page.evaluate("typeof safeLocalStorage !== 'undefined'")

        # Проверим доступность: isAvailable должно быть false
        is_avail = page.evaluate("safeLocalStorage.isAvailable")
        assert is_avail is False

        # Проверим, что запись и чтение не падают, а переходят на fallbackStore (in-memory)
        page.evaluate("safeLocalStorage.setItem('fallback_key', 'still_works')")
        val = page.evaluate("safeLocalStorage.getItem('fallback_key')")
        assert val == "still_works"

        # И удаление тоже работает в памяти
        page.evaluate("safeLocalStorage.removeItem('fallback_key')")
        val_after = page.evaluate("safeLocalStorage.getItem('fallback_key')")
        assert val_after is None

        browser.close()


def test_safe_local_storage_quota_exceeded(crm_server):
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

        # Симулируем переполнение квоты localStorage: setItem кидает QuotaExceededError
        init_js = """
        const originalSet = window.localStorage.setItem.bind(window.localStorage);
        window.localStorage.setItem = function(key, value) {
            if (key !== '__sto_crm_storage_test__' && key !== 'sto-crm-bootstrap') {
                const err = new DOMException("Quota exceeded", "QuotaExceededError");
                throw err;
            }
            originalSet(key, value);
        };
        """
        page.add_init_script(init_js)

        page.goto(crm_server)
        page.wait_for_selector(".app")

        assert page.evaluate("typeof safeLocalStorage !== 'undefined'")

        # Пробуем записать: оригинальный localStorage выбросит QuotaExceededError
        # Наша обертка должна поймать это, записать в Map и вернуть false (или обработать fallback)
        page.evaluate("safeLocalStorage.setItem('quota_key', 'partially_saved')")
        # item должен быть доступен (из памяти)
        val = page.evaluate("safeLocalStorage.getItem('quota_key')")
        assert val == "partially_saved"

        browser.close()
