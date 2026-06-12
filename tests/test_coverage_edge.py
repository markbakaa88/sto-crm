import os
import unittest
from pathlib import Path

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
            "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        }
        self.assertTrue(is_installable_update_asset(asset))

    def test_prune_backups_empty_or_symlink_dir(self):
        from sto_crm.updates import prune_backups
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = Path(tmpdir) / "backups"
            backup_dir.mkdir()
            if hasattr(os, "symlink"):
                sym_dir = Path(tmpdir) / "sym_backups"
                os.symlink(backup_dir, sym_dir)
                with self.assertRaises(OSError):
                    prune_backups(sym_dir)

    def test_prune_backups_limit_file_rotation(self):
        from sto_crm.updates import prune_backups
        import tempfile
        import time
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

