import unittest
from pathlib import Path


class TestUpdatesPruneCoverage(unittest.TestCase):
    def test_prune_backups_no_limits(self):
        import sto_crm.updates
        from sto_crm.updates import prune_backups

        # Запомним оригинальные лимиты
        orig_max_files = sto_crm.updates.MAX_BACKUP_FILES
        orig_max_bytes = sto_crm.updates.MAX_BACKUP_TOTAL_BYTES
        try:
            # Установим лимиты в 0, чтобы сработал ранний return
            sto_crm.updates.MAX_BACKUP_FILES = 0
            sto_crm.updates.MAX_BACKUP_TOTAL_BYTES = 0

            # Должно завершиться мгновенно без ошибок даже для несуществующего пути
            prune_backups(Path("/nonexistent_prune_path_12345/"))
        finally:
            sto_crm.updates.MAX_BACKUP_FILES = orig_max_files
            sto_crm.updates.MAX_BACKUP_TOTAL_BYTES = orig_max_bytes

    def test_prune_backups_unresolvable_keep_path(self):
        import tempfile

        from sto_crm.updates import prune_backups

        # Создаем временную директорию с одним бэкапом
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = Path(tmpdir)
            f = backup_dir / "sto_crm_backup_1.sqlite3"
            f.write_text("content")

            # Передадим keep_path, разрешить который невозможно (например, некорректный путь для st_mode)
            # В Unix path.resolve() для несуществующего пути с некорректной вложенностью
            # или путь, выбрасывающий OSError. Но мы можем симулировать non-existent keep_path
            bad_keep_path = Path("/nonexistent/subdirectory/file.sqlite3")

            # Вызов не должен ломаться
            prune_backups(backup_dir, keep_path=bad_keep_path)
            self.assertTrue(f.exists())

    def test_prune_backups_glob_io_error(self):
        # Передадим директорию, stat() файлов в которой вызовет OSError
        # Для этого создадим файл, который удалим непосредственно перед циклом, либо замокаем path.stat
        import tempfile
        from unittest.mock import patch

        from sto_crm.updates import prune_backups

        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = Path(tmpdir)

            # Создаем файл
            f = backup_dir / "sto_crm_backup_2.sqlite3"
            f.write_text("data")

            # Мокаем stat у Path, чтобы бросать OSError
            orig_stat = Path.stat

            def mock_stat(self_obj, *args, **kwargs):
                if (
                    "sto_code_backup" in self_obj.name
                    or "sto_crm_backup" in self_obj.name
                ):
                    raise OSError("Stat failed")
                return orig_stat(self_obj, *args, **kwargs)

            with patch.object(Path, "stat", mock_stat):
                # Должен корректно пропустить этот бэкап и не упасть
                prune_backups(backup_dir)

    def test_prune_updates_dir_coverage(self):
        import tempfile
        import time
        from sto_crm.updates import prune_updates_dir

        with tempfile.TemporaryDirectory() as tmpdir:
            update_dir = Path(tmpdir)
            f1 = update_dir / "download-old-123"
            f2 = update_dir / "download-new-123"
            f3 = update_dir / "unrelated.txt"
            f1.touch()
            f2.touch()
            f3.touch()

            # Set mtime for f1 to be 2 days ago
            old_time = time.time() - (86400 * 2)
            import os
            os.utime(f1, (old_time, old_time))

            prune_updates_dir(update_dir)

            self.assertFalse(f1.exists())
            self.assertTrue(f2.exists())
            self.assertTrue(f3.exists())

            # Test nonexistent directory
            nonexistent = Path(tmpdir) / "nonexistent"
            prune_updates_dir(nonexistent)

