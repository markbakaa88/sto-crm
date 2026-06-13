import os
import unittest
from pathlib import Path
from typing import Any

from sto_crm.updates import (
    _content_length,
    can_install_windows_update,
    ensure_real_backup_dir,
    is_installable_update_asset,
    read_limited_response,
    validate_manifest_asset_download_url,
    validate_sha256,
    validate_update_download_url,
)
from sto_crm.validation import item_is_billable, require_non_negative_float


class TestCoverageEdge(unittest.TestCase):
    def test_item_is_billable_edge(self):
        self.assertTrue(item_is_billable({}))
        self.assertTrue(item_is_billable({"approval_status": "approved"}))
        self.assertFalse(item_is_billable({"approval_status": "declined"}))

    def test_require_non_negative_float_edge(self):
        with self.assertRaises(ValueError):
            require_non_negative_float(-1, "test")

    def test_can_install_windows_update(self):
        # Должно возвращать False в Linux окружении
        self.assertFalse(can_install_windows_update())

    def test_is_installable_update_asset_edge(self):
        self.assertFalse(is_installable_update_asset(None))
        self.assertFalse(is_installable_update_asset({}))
        self.assertFalse(is_installable_update_asset({"download_url": "invalid"}))

    def test_validate_update_download_url_invalid(self):
        # Не HTTPS
        with self.assertRaises(RuntimeError):
            validate_update_download_url("http://github.com/file")
        # Недоверенный хост
        with self.assertRaises(RuntimeError):
            validate_update_download_url("https://malicious.com/file")
        # Пользователь/пароль в URL
        with self.assertRaises(RuntimeError):
            validate_update_download_url("https://user:pass@github.com/file")
        # Нестандартный порт
        with self.assertRaises(RuntimeError):
            validate_update_download_url("https://github.com:8080/file")

    def test_validate_manifest_asset_download_url_invalid(self):
        # Не github.com
        with self.assertRaises(RuntimeError):
            validate_manifest_asset_download_url(
                "https://objects.githubusercontent.com/file",
                "markbakaa88/sto-crm",
                "v1.0.0",
            )
        # Неправильный репозиторий
        with self.assertRaises(RuntimeError):
            validate_manifest_asset_download_url(
                "https://github.com/other/repo/releases/download/v1.0.0/STO_CRM.exe",
                "markbakaa88/sto-crm",
                "v1.0.0",
            )
        # Не exe файл
        with self.assertRaises(RuntimeError):
            validate_manifest_asset_download_url(
                "https://github.com/markbakaa88/sto-crm/releases/download/v1.0.0/latest.json",
                "markbakaa88/sto-crm",
                "v1.0.0",
            )

    def test_validate_sha256_invalid(self):
        with self.assertRaises(RuntimeError):
            validate_sha256(None, required=True)
        self.assertEqual(validate_sha256("", required=False), "")
        with self.assertRaises(RuntimeError):
            validate_sha256("not-a-sha256", required=True)

    def test_content_length_invalid(self):
        class DummyResponse:
            def __init__(self) -> None:
                self.headers = {"Content-Length": "not-a-number"}

        self.assertEqual(_content_length(DummyResponse()), 0)

    def test_read_limited_response_overflow(self):
        class DummyResponse:
            def __init__(self) -> None:
                self.headers = {"Content-Length": "100"}

            def read(self, limit: int) -> bytes:
                return b"a" * 105

        with self.assertRaises(RuntimeError):
            read_limited_response(DummyResponse(), 50, "test")

    def test_ensure_real_backup_dir_symlink(self):
        if not hasattr(os, "symlink"):
            self.skipTest("symlink не поддерживается на платформе")
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            real_dir = Path(tmpdir) / "real"
            real_dir.mkdir()
            sym_dir = Path(tmpdir) / "sym"
            os.symlink(real_dir, sym_dir)
            with self.assertRaises(OSError):
                ensure_real_backup_dir(sym_dir)

    def test_is_installable_update_asset_valid(self):
        asset = {
            "download_url": "https://github.com/markbakaa88/sto-crm/releases/download/v1.0.0/STO_CRM.exe",
            "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        }
        self.assertTrue(is_installable_update_asset(asset))

    def test_prune_backups_empty_or_symlink_dir(self):
        import tempfile

        from sto_crm.updates import prune_backups

        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = Path(tmpdir) / "backups"
            backup_dir.mkdir()
            if hasattr(os, "symlink"):
                sym_dir = Path(tmpdir) / "sym_backups"
                os.symlink(backup_dir, sym_dir)
                with self.assertRaises(OSError):
                    prune_backups(sym_dir)

    def test_prune_backups_limit_file_rotation(self):
        import tempfile
        import time

        from sto_crm.updates import prune_backups

        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = Path(tmpdir)
            # Создаем 3 файла резервной копии
            f1 = backup_dir / "sto_crm_backup_1.sqlite3"
            f2 = backup_dir / "sto_crm_backup_2.sqlite3"
            f3 = backup_dir / "sto_crm_backup_3.sqlite3"

            f1.write_text("backup1")
            # Задаем разное время модификации
            os.utime(f1, (time.time() - 100, time.time() - 100))

            f2.write_text("backup2")
            os.utime(f2, (time.time() - 10, time.time() - 10))

            f3.write_text("backup3")
            os.utime(f3, (time.time(), time.time()))

            # Подменяем конфиг для лимита в тесте
            import sto_crm.updates

            orig_max_files = sto_crm.updates.MAX_BACKUP_FILES
            orig_max_bytes = sto_crm.updates.MAX_BACKUP_TOTAL_BYTES
            try:
                sto_crm.updates.MAX_BACKUP_FILES = 2
                sto_crm.updates.MAX_BACKUP_TOTAL_BYTES = 1000

                # Запускаем prune_backups с сохранением f1
                prune_backups(backup_dir, keep_path=f1)

                # Должны остаться f1 (потому что keep_path) и f3 (самый новый среди остальных)
                # Файл f2 должен быть удален (так как превышен лимит 2 файлов)
                self.assertTrue(f1.exists())
                self.assertTrue(f3.exists())
                self.assertFalse(f2.exists())
            finally:
                sto_crm.updates.MAX_BACKUP_FILES = orig_max_files
                sto_crm.updates.MAX_BACKUP_TOTAL_BYTES = orig_max_bytes

    def test_catalog_official_entries_exceptions(self):
        import sto_crm.catalog

        orig = sto_crm.catalog.OFFICIAL_CAR_CATALOG_B64
        try:
            # 1. binary error / invalid base64
            sto_crm.catalog.OFFICIAL_CAR_CATALOG_B64 = "invalid@@@"
            self.assertEqual(sto_crm.catalog.official_car_catalog_entries(), [])

            # 2. invalid zlib data
            import base64

            sto_crm.catalog.OFFICIAL_CAR_CATALOG_B64 = base64.b64encode(
                b"not-zlib-compressed"
            ).decode()
            self.assertEqual(sto_crm.catalog.official_car_catalog_entries(), [])

            # 3. valid zlib but invalid JSON
            import zlib

            bad_json = zlib.compress(b"{bad json")
            sto_crm.catalog.OFFICIAL_CAR_CATALOG_B64 = base64.b64encode(
                bad_json
            ).decode()
            self.assertEqual(sto_crm.catalog.official_car_catalog_entries(), [])

            # 4. JSON is not dict / has no 'makes' list
            bad_dict = zlib.compress(b"[]")
            sto_crm.catalog.OFFICIAL_CAR_CATALOG_B64 = base64.b64encode(
                bad_dict
            ).decode()
            self.assertEqual(sto_crm.catalog.official_car_catalog_entries(), [])

            # 5. 'makes' is not list
            bad_makes = zlib.compress(b'{"makes": 123}')
            sto_crm.catalog.OFFICIAL_CAR_CATALOG_B64 = base64.b64encode(
                bad_makes
            ).decode()
            self.assertEqual(sto_crm.catalog.official_car_catalog_entries(), [])
        finally:
            sto_crm.catalog.OFFICIAL_CAR_CATALOG_B64 = orig

    def test_catalog_payload_double_check(self):
        import sto_crm.catalog

        sto_crm.catalog._CAR_CATALOG_CACHE = None
        # Вызовем первый раз для прогрева кэша
        payload = sto_crm.catalog.car_catalog_payload()
        self.assertIn("makes", payload)

        # Для покрытия double check inside lock:
        # Мы сбрасываем кэш, но при этом лочим во втором потоке
        import threading

        sto_crm.catalog._CAR_CATALOG_CACHE = None
        results = []

        def worker():
            res = sto_crm.catalog.car_catalog_payload()
            results.append(res)

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        self.assertEqual(len(results), 2)

    def test_catalog_invalid_entries_continue(self):
        import sto_crm.catalog

        orig_catalog = sto_crm.catalog.CAR_CATALOG
        orig_cache = sto_crm.catalog._CAR_CATALOG_CACHE
        try:
            sto_crm.catalog.CAR_CATALOG = [
                {"make": ""},  # empty make -> line 821
                {
                    "make": "TestMake",
                    "models": "not-a-list",
                },  # models not list -> line 826
                {"make": "TestMake", "models": ["ModelA", " "]},  # valid path
            ]
            sto_crm.catalog._CAR_CATALOG_CACHE = None
            payload = sto_crm.catalog.car_catalog_payload()
            self.assertIn("TestMake", payload["makes"])
            self.assertEqual(payload["models"]["TestMake"], ["ModelA"])
        finally:
            sto_crm.catalog.CAR_CATALOG = orig_catalog
            sto_crm.catalog._CAR_CATALOG_CACHE = orig_cache

    def test_format_quantity_edge(self):
        from sto_crm.printing import _format_quantity

        self.assertEqual(_format_quantity(-0.00001), "-0")
        self.assertEqual(_format_quantity(0.0), "0")
        self.assertEqual(_format_quantity(1.5), "1,5")

        import sto_crm.printing

        orig = sto_crm.printing.parse_float

        class CustomFloat(float):
            def __format__(self, format_spec):
                return "-"

        def mock_parse_float(val: Any) -> float:
            return CustomFloat(val)

        sto_crm.printing.parse_float = mock_parse_float
        try:
            self.assertEqual(sto_crm.printing._format_quantity(1.0), "0")
        finally:
            sto_crm.printing.parse_float = orig

    def test_csv_export_key_error_edge(self):
        from sto_crm.export import csv_export

        with self.assertRaises(KeyError):
            csv_export("unknown_entity")

    def test_csv_export_valid_entities(self):
        from sto_crm import runtime as _runtime
        from sto_crm.database import init_db
        from sto_crm.export import csv_export
        from sto_crm.runtime import Runtime

        current_runtime = _runtime.RUNTIME
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            _runtime.RUNTIME = Runtime(
                db_path=Path(tmpdir) / "test_export.sqlite3",
                start_time=0.0,
                csrf_token="",
                access_token="",
                bootstrap_token="",
            )
            try:
                init_db(seed_demo=True)
                for entity in (
                    "customers",
                    "vehicles",
                    "inventory",
                    "appointments",
                    "orders",
                    "catalog",
                ):
                    filename, content = csv_export(entity)
                    self.assertTrue(filename.endswith(".csv"))
                    self.assertTrue(content.startswith("\ufeff"))
            finally:
                _runtime.RUNTIME = current_runtime

    def test_web_read_asset_frozen_edge(self):
        from sto_crm import web as crm_web

        orig_frozen = crm_web.is_frozen
        # Подменяем is_frozen на True прямо в пространстве имен модуля web
        crm_web.is_frozen = lambda: True
        try:
            # Вызов_read_asset должен пойти по ветке resources.files
            content = crm_web._read_asset("index.html")
            self.assertIn("СТО CRM", content)
        finally:
            crm_web.is_frozen = orig_frozen

    def test_http_server_unsupported_methods_and_errors(self):
        import tempfile
        import threading
        import time
        import urllib.error
        import urllib.request

        from sto_crm import runtime as _runtime
        from sto_crm.cli import create_server
        from sto_crm.runtime import Runtime

        current_runtime = _runtime.RUNTIME
        with tempfile.TemporaryDirectory() as tmpdir:
            _runtime.RUNTIME = Runtime(
                db_path=Path(tmpdir) / "test_http.sqlite3",
                start_time=time.time(),
                csrf_token="test_csrf",
                access_token="test_access",
                bootstrap_token="test_bootstrap",
            )
            # Инициализируем БД
            from sto_crm.database import init_db

            init_db(seed_demo=True)

            # Подменяем latest_release_info, чтобы избежать обращения к сети
            from unittest.mock import patch

            patcher = patch("sto_crm.updates.latest_release_info")
            mock_latest = patcher.start()
            mock_latest.return_value = {
                "version": "1.17.2",
                "tag": "v1.17.2",
                "name": "СТО CRM 1.17.2",
                "is_newer": False,
                "has_asset": False,
                "asset": None,
                "manifest": None,
            }

            server = create_server(0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"

            try:
                # 1. do_DELETE без токена -> 403
                delete_req = urllib.request.Request(
                    f"{base}/api/customers/1", method="DELETE"
                )
                with self.assertRaises(urllib.error.HTTPError) as err:
                    urllib.request.urlopen(delete_req, timeout=5)
                self.assertEqual(err.exception.code, 403)

                # 2. X-CSRF-Token неверный при DELETE -> 403
                delete_req = urllib.request.Request(
                    f"{base}/api/customers/1",
                    method="DELETE",
                    headers={
                        "X-CRM-Access-Token": "test_access",
                        "X-CSRF-Token": "wrong_csrf",
                    },
                )
                with self.assertRaises(urllib.error.HTTPError) as err:
                    urllib.request.urlopen(delete_req, timeout=5)
                self.assertEqual(err.exception.code, 403)

                # 3. OPTIONS запрос без токенов -> 204
                options_req = urllib.request.Request(f"{base}/", method="OPTIONS")
                with urllib.request.urlopen(options_req, timeout=5) as response:
                    self.assertEqual(response.status, 204)

                # 4. do_TRACE -> 405 Метод не поддерживается.
                trace_req = urllib.request.Request(f"{base}/", method="TRACE")
                with self.assertRaises(urllib.error.HTTPError) as err:
                    urllib.request.urlopen(trace_req, timeout=5)
                self.assertEqual(err.exception.code, 405)

                # 5. do_CONNECT -> 405 Метод не поддерживается.
                connect_req = urllib.request.Request(f"{base}/", method="CONNECT")
                with self.assertRaises(urllib.error.HTTPError) as err:
                    urllib.request.urlopen(connect_req, timeout=5)
                self.assertEqual(err.exception.code, 405)

                # 6. /print/order/1 GET без csrf -> 403
                print_req = urllib.request.Request(
                    f"{base}/print/order/1",
                    headers={"X-CRM-Access-Token": "test_access"},
                )
                with self.assertRaises(urllib.error.HTTPError) as err:
                    urllib.request.urlopen(print_req, timeout=5)
                self.assertEqual(err.exception.code, 403)

                # 7. /api/export/customers.csv GET без csrf -> 403
                export_req = urllib.request.Request(
                    f"{base}/api/export/customers.csv",
                    headers={"X-CRM-Access-Token": "test_access"},
                )
                with self.assertRaises(urllib.error.HTTPError) as err:
                    urllib.request.urlopen(export_req, timeout=5)
                self.assertEqual(err.exception.code, 403)

                # 8. POST /api/backup без токена доступа -> 403
                backup_req = urllib.request.Request(
                    f"{base}/api/backup",
                    method="POST",
                    headers={
                        "Content-Type": "application/json",
                        "Content-Length": "2",
                        "X-CSRF-Token": "test_csrf",
                    },
                    data=b"{}",
                )
                with self.assertRaises(urllib.error.HTTPError) as err:
                    urllib.request.urlopen(backup_req, timeout=5)
                self.assertEqual(err.exception.code, 403)

                # 8a. do_TRACE с плохим Origin -> 403 (validate_local_request_context failure)
                trace_req = urllib.request.Request(
                    f"{base}/",
                    method="TRACE",
                    headers={"Origin": "http://evil.example.com"},
                )
                with self.assertRaises(urllib.error.HTTPError) as err:
                    urllib.request.urlopen(trace_req, timeout=5)
                self.assertEqual(err.exception.code, 403)

                # 8b. GET HEAD / и /app
                head_req = urllib.request.Request(f"{base}/", method="HEAD")
                with urllib.request.urlopen(head_req, timeout=5) as response:
                    self.assertEqual(response.status, 200)

                # 8c. GET /api/health
                health_req = urllib.request.Request(f"{base}/api/health")
                with urllib.request.urlopen(health_req, timeout=5) as response:
                    self.assertEqual(response.status, 200)

                # 8d. GET /api/update/status дважды для кэша
                update_req = urllib.request.Request(
                    f"{base}/api/update/status",
                    headers={"X-CRM-Access-Token": "test_access"},
                )
                with urllib.request.urlopen(update_req, timeout=5) as response:
                    self.assertEqual(response.status, 200)
                with urllib.request.urlopen(update_req, timeout=5) as response:
                    self.assertEqual(response.status, 200)

                # 8e. PUT без record_id (некорректный маршрут)
                put_req = urllib.request.Request(
                    f"{base}/api/customers",
                    method="PUT",
                    headers={
                        "X-CRM-Access-Token": "test_access",
                        "X-CSRF-Token": "test_csrf",
                        "Content-Type": "application/json",
                    },
                    data=b"{}",
                )
                with self.assertRaises(urllib.error.HTTPError) as err:
                    urllib.request.urlopen(put_req, timeout=5)
                self.assertEqual(err.exception.code, 404)

                # 8f. DELETE без record_id (некорректный маршрут)
                delete_req2 = urllib.request.Request(
                    f"{base}/api/customers",
                    method="DELETE",
                    headers={
                        "X-CRM-Access-Token": "test_access",
                        "X-CSRF-Token": "test_csrf",
                    },
                )
                with self.assertRaises(urllib.error.HTTPError) as err:
                    urllib.request.urlopen(delete_req2, timeout=5)
                self.assertEqual(err.exception.code, 404)

                # 9. GET /api/update/status
                update_req = urllib.request.Request(
                    f"{base}/api/update/status",
                    headers={"X-CRM-Access-Token": "test_access"},
                )
                with urllib.request.urlopen(update_req, timeout=5) as response:
                    self.assertEqual(response.status, 200)

                # 10. GET /api/bootstrap без bootstrap_token но с access_token -> 200
                bootstrap_req = urllib.request.Request(
                    f"{base}/api/bootstrap",
                    headers={"X-CRM-Access-Token": "test_access"},
                )
                with urllib.request.urlopen(bootstrap_req, timeout=5) as response:
                    self.assertEqual(response.status, 200)

                # 11. POST /api/shutdown -> 200 и сервер выключается
                shutdown_req = urllib.request.Request(
                    f"{base}/api/shutdown",
                    method="POST",
                    headers={
                        "X-CRM-Access-Token": "test_access",
                        "X-CSRF-Token": "test_csrf",
                        "Content-Type": "application/json",
                    },
                    data=b"{}",
                )
                with urllib.request.urlopen(shutdown_req, timeout=5) as response:
                    self.assertEqual(response.status, 200)

                # Ждем выключения сервера
                thread.join(timeout=5)

            finally:
                patcher.stop()
                server.shutdown()
                server.server_close()
                _runtime.RUNTIME = current_runtime

    def test_cli_parse_args(self):
        from sto_crm.cli import candidate_ports, parse_args, server_class_for_host

        args = parse_args(
            [
                "--port",
                "9000",
                "--host",
                "127.0.0.1",
                "--db",
                "/tmp/crm_test.sqlite3",
                "--demo",
                "--no-browser",
            ]
        )
        self.assertEqual(args.port, 9000)
        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(Path(args.db).name, "crm_test.sqlite3")
        self.assertTrue(args.demo)
        self.assertTrue(args.no_browser)

        ports = list(candidate_ports(8765, attempts=2))
        self.assertEqual(ports, [8765, 8766, 0])

        with self.assertRaises(SystemExit):
            parse_args(["--port", "-1"])
        with self.assertRaises(SystemExit):
            parse_args(["--port", "70000"])
        with self.assertRaises(SystemExit):
            parse_args(["--host", "evil.com"])

        self.assertEqual(server_class_for_host("127.0.0.1").__name__, "CRMServer")
        self.assertEqual(server_class_for_host("::1").__name__, "CRMServerV6")

    def test_cli_main_execution(self):
        from unittest.mock import MagicMock, patch

        from sto_crm import cli

        with (
            patch("sto_crm.cli.create_server") as mock_create_server,
            patch("sto_crm.cli.init_db") as mock_init_db,
            patch("webbrowser.open"),
        ):
            mock_server = MagicMock()
            mock_server.server_address = ("127.0.0.1", 8765)
            mock_server.server_port = 8765
            mock_create_server.return_value = mock_server

            res = cli.main(["--port", "8765", "--no-browser"])
            self.assertEqual(res, 0)
            mock_init_db.assert_called_once()
            mock_server.serve_forever.assert_called_once()
            mock_server.server_close.assert_called_once()

    def test_database_normalized_unique_sql_invalid(self):
        from sto_crm.database import normalized_unique_sql

        with self.assertRaises(ValueError):
            normalized_unique_sql("invalid_table", "sku")

    def test_package_main_loader(self):
        import importlib.util
        import sys
        from unittest.mock import patch

        spec = importlib.util.spec_from_file_location("__main__", "sto_crm/__main__.py")
        self.assertIsNotNone(spec)
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        module.__name__ = "__main__"
        module.__package__ = "sto_crm"
        sys.modules["__main__"] = module
        try:
            with patch("sto_crm.cli.main") as mock_cli_main:
                mock_cli_main.return_value = 0
                with self.assertRaises(SystemExit) as exit_err:
                    spec.loader.exec_module(module)
                self.assertEqual(exit_err.exception.code, 0)
                mock_cli_main.assert_called_once()
        finally:
            sys.modules.pop("__main__", None)
            sys.modules.pop("sto_crm.__main__", None)

    def test_runtime_helpers(self):
        import os
        import sys
        from pathlib import Path

        from sto_crm.runtime import (
            app_dir,
            directory_writable,
            ensure_private_dir,
            ensure_private_file,
            ensure_private_file_created,
            is_frozen,
            normalize_github_repository,
            parse_float,
            parse_int,
        )

        # 1. normalize_github_repository edge cases
        self.assertEqual(
            normalize_github_repository("https://github.com/abc/def.git"), "abc/def"
        )
        self.assertEqual(
            normalize_github_repository("https://github.com/abc/def/issues"), "abc/def"
        )
        self.assertEqual(
            normalize_github_repository("invalid_format"), "markbakaa88/sto-crm"
        )
        self.assertEqual(normalize_github_repository(None), "markbakaa88/sto-crm")

        # Override env
        os.environ["STO_CRM_UPDATE_REPOSITORY"] = "custom/repo"
        self.assertEqual(normalize_github_repository(None), "custom/repo")
        os.environ.pop("STO_CRM_UPDATE_REPOSITORY")

        # 2. parse_float & parse_int
        self.assertEqual(parse_float("1 234,56"), 1234.56)
        self.assertEqual(parse_float(None), 0.0)
        self.assertEqual(parse_float(""), 0.0)
        self.assertEqual(parse_float("nan"), 0.0)
        self.assertEqual(parse_float("inf"), 0.0)
        self.assertEqual(parse_float("invalid"), 0.0)

        self.assertEqual(parse_int("1 234"), 1234)
        self.assertEqual(parse_int(None), 0)
        self.assertEqual(parse_int(""), 0)
        self.assertEqual(parse_int(True), 1)
        self.assertEqual(parse_int(False), 0)
        self.assertEqual(parse_int(123.45), 123)
        self.assertEqual(parse_int("invalid"), 0)

        # 3. is_frozen / app_dir / user_data_dir / private permissions
        self.assertFalse(is_frozen())
        orig_frozen = getattr(sys, "frozen", None)
        try:
            sys.frozen = True
            self.assertTrue(is_frozen())
            # check frozen paths
            # Sys.executable is usually Python executable or a temp name
            self.assertEqual(app_dir(), Path(sys.executable).resolve().parent)
        finally:
            if orig_frozen is not None:
                sys.frozen = orig_frozen
            else:
                try:
                    delattr(sys, "frozen")
                except AttributeError:
                    pass

        # writable, directories, chmod permissions
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "sub"
            self.assertTrue(directory_writable(p))
            ensure_private_dir(p)

            f = p / "sensitive.txt"
            f.write_text("sens")
            ensure_private_file(f)
            ensure_private_file_created(f)

    def test_fetch_json_edge_cases(self):
        import urllib.error
        from unittest.mock import MagicMock, patch

        from sto_crm.updates import fetch_json

        # 1. Successful fetch but not a dict (e.g. returns a list)
        with patch("urllib.request.urlopen") as mock_open:
            mock_resp = MagicMock()
            mock_resp.read.return_value = b"[]"
            mock_resp.headers.get_content_charset.return_value = "utf-8"
            mock_resp.geturl.return_value = "https://github.com/abc/def"
            mock_open.return_value.__enter__.return_value = mock_resp
            with self.assertRaises(RuntimeError) as ctx:
                fetch_json("https://github.com/abc/def")
            self.assertIn("GitHub вернул неожиданный ответ", str(ctx.exception))

        # 2. HTTPError 404
        with patch("urllib.request.urlopen") as mock_open:
            from email.message import Message

            mock_open.side_effect = urllib.error.HTTPError(
                "https://github.com/abc/def", 404, "Not Found", Message(), None
            )
            with self.assertRaises(RuntimeError) as ctx:
                fetch_json("https://github.com/abc/def")
            self.assertIn("Релиз GitHub не найден", str(ctx.exception))

        # 3. HTTPError 403
        with patch("urllib.request.urlopen") as mock_open:
            mock_open.side_effect = urllib.error.HTTPError(
                "https://github.com/abc/def", 403, "Forbidden", Message(), None
            )
            with self.assertRaises(RuntimeError) as ctx:
                fetch_json("https://github.com/abc/def")
            self.assertIn("GitHub отклонил запрос", str(ctx.exception))

        # 4. HTTPError 500
        with patch("urllib.request.urlopen") as mock_open:
            mock_open.side_effect = urllib.error.HTTPError(
                "https://github.com/abc/def",
                500,
                "Internal Server Error",
                Message(),
                None,
            )
            with self.assertRaises(RuntimeError) as ctx:
                fetch_json("https://github.com/abc/def")
            self.assertIn("GitHub недоступен: HTTP 500", str(ctx.exception))

    def test_schedule_windows_update_non_windows(self):
        import os

        from sto_crm.updates import schedule_windows_update

        if os.name != "nt":
            with self.assertRaises(RuntimeError) as ctx:
                schedule_windows_update(Path("dummy"), "dummy_sha")
            self.assertIn("Автоустановка доступна только в Windows", str(ctx.exception))
