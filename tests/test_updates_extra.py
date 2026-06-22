import os
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestUpdatesWindowsMock(unittest.TestCase):
    @patch("sto_crm.updates.app_executable_path")
    @patch("subprocess.Popen")
    def test_schedule_windows_update_mocked_win(self, mock_popen, mock_app_path):
        from sto_crm.updates import schedule_windows_update

        # Подготовим моки
        mock_current = MagicMock(spec=Path)
        mock_current.exists.return_value = True
        mock_current.suffix = ".exe"
        mock_current.stem = "STO_CRM"
        mock_current.name = "STO_CRM.exe"
        mock_current.__str__.return_value = "C:\\path\\to\\STO_CRM.exe"
        mock_app_path.return_value = mock_current

        mock_downloaded = MagicMock(spec=Path)
        mock_downloaded.name = "downloaded.exe"
        mock_downloaded.__str__.return_value = "C:\\path\\to\\downloaded.exe"

        # Временная директория для записи скрипта
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            with (
                patch("sto_crm.updates.user_data_dir", return_value=tmp_path),
                patch(
                    "sto_crm.updates.updater_log_path",
                    return_value=tmp_path / "updater.log",
                ),
                patch("os.name", "nt"),
            ):
                # Должен записать скрипт и вызвать Popen
                schedule_windows_update(mock_downloaded, "validsha256" * 8)

                # Проверим, что Popen вызван
                self.assertTrue(mock_popen.called)
                args_called = mock_popen.call_args[0][0]
                self.assertEqual(args_called[0], "powershell.exe")
                self.assertEqual(args_called[1], "-NoProfile")

                # Проверим, что переданы корректные flags (creationflags) для скрытия консольного окна на Windows
                kwargs_called = mock_popen.call_args[1]
                self.assertEqual(kwargs_called.get("close_fds"), True)
                self.assertIn("creationflags", kwargs_called)
                import subprocess

                self.assertEqual(
                    kwargs_called["creationflags"],
                    getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
                )

                # Проверим, что какой-то файл скрипта .ps1 был записан в tmp_path / "updates"
                updates_dir = tmp_path / "updates"
                ps1_files = list(updates_dir.glob("*.ps1"))
                self.assertEqual(len(ps1_files), 1)
                script_content = ps1_files[0].read_text(encoding="utf-8-sig")
                self.assertIn("validsha256", script_content)
                self.assertIn("downloaded.exe", script_content)

    @patch("sto_crm.updates.app_executable_path")
    def test_schedule_windows_update_failures(self, mock_app_path):
        from sto_crm.updates import schedule_windows_update

        dummy_path = Path("dummy")

        # 1. file not exists
        mock_current = MagicMock(spec=Path)
        mock_current.exists.return_value = False
        mock_app_path.return_value = mock_current
        with patch("os.name", "nt"):
            with self.assertRaises(RuntimeError) as ctx:
                schedule_windows_update(dummy_path, "sha")
            self.assertIn("Текущий исполняемый файл не найден", str(ctx.exception))

        # 2. file suffix is not .exe
        mock_current = MagicMock(spec=Path)
        mock_current.exists.return_value = True
        mock_current.suffix = ".py"
        mock_app_path.return_value = mock_current
        with patch("os.name", "nt"):
            with self.assertRaises(RuntimeError) as ctx:
                schedule_windows_update(dummy_path, "sha")
            self.assertIn(
                "Автоустановка доступна только для собранного", str(ctx.exception)
            )

    @patch("sto_crm.updates.can_install_windows_update", return_value=False)
    def test_install_update_from_github_non_windows(self, mock_can_install):
        from sto_crm.updates import install_update_from_github

        with self.assertRaises(RuntimeError) as ctx:
            install_update_from_github()
        self.assertIn(
            "Автоустановка доступна только в Windows-версии", str(ctx.exception)
        )

    @patch("sto_crm.updates.can_install_windows_update", return_value=True)
    @patch("sto_crm.updates._begin_update_install")
    @patch("sto_crm.updates.latest_release_info")
    @patch("sto_crm.updates._finish_update_install")
    def test_install_update_from_github_prerelease(
        self, mock_finish, mock_latest, mock_begin, mock_can_install
    ):
        from sto_crm.updates import install_update_from_github

        # release with prerelease=True
        mock_latest.return_value = {"prerelease": True, "draft": False}
        res = install_update_from_github()
        self.assertTrue(res["ok"])
        self.assertFalse(res["updated"])
        self.assertEqual(res["message"], "Стабильных обновлений нет.")
        mock_finish.assert_called_once()

    def test_validate_safe_path_failures(self):
        import tempfile

        from sto_crm.updates import validate_safe_path

        # 1. contains ".." or "\\"
        with self.assertRaises(OSError) as ctx:
            validate_safe_path(Path("foo/../bar"))
        self.assertIn("Недопустимый путь", str(ctx.exception))

        with self.assertRaises(OSError) as ctx:
            validate_safe_path(Path("foo\\bar"))
        self.assertIn("Недопустимый путь", str(ctx.exception))

        # 2. Target or Parent is a symlink, or escapes parent
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir).resolve()
            parent = base / "parent"
            parent.mkdir()
            target = parent / "file.txt"
            target.write_text("hello", encoding="utf-8")

            # should pass for regular file inside parent
            validate_safe_path(target)

            # Target is a symlink
            sym_target = parent / "sym_target.txt"
            try:
                sym_target.symlink_to(target)
                with self.assertRaises(OSError) as ctx:
                    validate_safe_path(sym_target)
                self.assertIn(
                    "Путь не может быть символической ссылкой", str(ctx.exception)
                )
            except (OSError, NotImplementedError):
                # Symlinks might not be supported on some Windows test runners without admin privileges
                pass

            # Parent is a symlink
            sym_parent = base / "sym_parent"
            try:
                sym_parent.symlink_to(parent, target_is_directory=True)
                sym_target2 = sym_parent / "file2.txt"
                with self.assertRaises(OSError) as ctx:
                    validate_safe_path(sym_target2)
                self.assertIn(
                    "Родительский каталог не может быть символической ссылкой",
                    str(ctx.exception),
                )
            except (OSError, NotImplementedError):
                pass

    def test_ensure_real_dir_validation_errors(self):
        import tempfile

        from sto_crm.updates import ensure_real_dir

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir).resolve()
            directory = base / "test_dir"
            ensure_real_dir(directory, "тестовой папки")
            self.assertTrue(directory.is_dir())

            # Path occupied by a file
            file_path = base / "occupied"
            file_path.write_text("content", encoding="utf-8")
            with self.assertRaises(OSError) as ctx:
                ensure_real_dir(file_path, "занятого пути")
            self.assertIn(
                "Путь к каталогу занятого пути занят файлом", str(ctx.exception)
            )

            # Directory is a symlink
            sym_dir = base / "sym_dir"
            try:
                sym_dir.symlink_to(directory, target_is_directory=True)
                with self.assertRaises(OSError) as ctx:
                    ensure_real_dir(sym_dir, "символической ссылки")
                self.assertIn(
                    "Каталог символической ссылки не может быть символической ссылкой",
                    str(ctx.exception),
                )
            except (OSError, NotImplementedError):
                pass

    def test_prune_backups_error_handling(self):
        import tempfile

        from sto_crm.updates import prune_backups

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir).resolve()
            backup_dir = base / "backups"
            backup_dir.mkdir()

            # write three normal backup files
            f1 = backup_dir / "sto_crm_backup_1.sqlite3"
            f2 = backup_dir / "sto_crm_backup_2.sqlite3"
            f3 = backup_dir / "sto_crm_backup_3.sqlite3"
            f1.write_text("db1", encoding="utf-8")
            f2.write_text("db2", encoding="utf-8")
            f3.write_text("db3", encoding="utf-8")

            # Pruning backups with MAX_BACKUP_FILES = 2 override via mock/patch
            with (
                patch("sto_crm.updates.MAX_BACKUP_FILES", 2),
                patch("sto_crm.updates.MAX_BACKUP_TOTAL_BYTES", 0),
            ):
                prune_backups(backup_dir)
                # One of them should be removed since we have 3 but limit is 2
                remaining = list(backup_dir.glob("sto_crm_backup_*.sqlite3"))
                self.assertEqual(len(remaining), 2)

    @patch("sto_crm.updates.time.sleep")
    @patch("sto_crm.updates.connect")
    @patch("sto_crm.updates.sqlite3.connect")
    @patch("sto_crm.updates.ensure_real_backup_dir")
    @patch("sto_crm.updates.ensure_private_file_created")
    @patch("sto_crm.updates.ensure_private_file")
    @patch("sto_crm.updates.prune_backups")
    @patch("sto_crm.updates.Path.stat")
    @patch("sto_crm.updates.Path.lstat")
    def test_create_backup_retry_success(
        self,
        mock_lstat,
        mock_stat,
        mock_prune,
        mock_ensure_private,
        mock_ensure_created,
        mock_ensure_real,
        mock_sql_connect,
        mock_connect,
        mock_sleep,
    ):
        from sto_crm.updates import create_backup

        # Setup mock stat & lstat
        mock_stat_res = MagicMock()
        mock_stat_res.st_size = 100
        mock_stat_res.st_mode = 0o100644
        mock_stat_res.st_mtime = 123456789.0
        mock_stat.return_value = mock_stat_res
        mock_lstat.return_value = mock_stat_res

        # Setup source and destination connections
        mock_source = MagicMock()
        mock_destination = MagicMock()

        # Connect throws locked twice, then returns mock_source
        mock_connect.side_effect = [
            sqlite3.OperationalError("database is locked"),
            sqlite3.OperationalError("database is locked"),
            mock_source,
        ]
        mock_sql_connect.return_value = mock_destination

        res = create_backup()

        # Check connect has been called 3 times
        self.assertEqual(mock_connect.call_count, 3)
        # Check source.backup has been called on the third attempt
        mock_source.backup.assert_called_once_with(mock_destination)
        # Check that sleep (backoff) was called twice
        self.assertEqual(mock_sleep.call_count, 2)
        # Check output metadata
        self.assertEqual(res["size"], 100)

    @patch("sto_crm.updates.time.sleep")
    @patch("sto_crm.updates.connect")
    @patch("sto_crm.updates.sqlite3.connect")
    @patch("sto_crm.updates.ensure_real_backup_dir")
    @patch("sto_crm.updates.ensure_private_file_created")
    @patch("sto_crm.updates.ensure_private_file")
    @patch("sto_crm.updates.prune_backups")
    def test_create_backup_retry_exhausted(
        self,
        mock_prune,
        mock_ensure_private,
        mock_ensure_created,
        mock_ensure_real,
        mock_sql_connect,
        mock_connect,
        mock_sleep,
    ):
        from sto_crm.updates import create_backup

        # Connect always throws locked
        mock_connect.side_effect = sqlite3.OperationalError("database is locked")

        with self.assertRaises(RuntimeError) as ctx:
            create_backup()

        self.assertIn("Не удалось создать резервную копию базы", str(ctx.exception))
        # Check that it tried 5 times
        self.assertEqual(mock_connect.call_count, 5)
        # Check sleep called 4 times
        self.assertEqual(mock_sleep.call_count, 4)

    @patch("sto_crm.updates.time.sleep")
    @patch("sto_crm.updates.connect")
    @patch("sto_crm.updates.sqlite3.connect")
    @patch("sto_crm.updates.ensure_real_backup_dir")
    @patch("sto_crm.updates.ensure_private_file_created")
    @patch("sto_crm.updates.ensure_private_file")
    @patch("sto_crm.updates.prune_backups")
    @patch("sto_crm.updates.Path.stat")
    @patch("sto_crm.updates.Path.lstat")
    def test_create_backup_backup_raises_locked(
        self,
        mock_lstat,
        mock_stat,
        mock_prune,
        mock_ensure_private,
        mock_ensure_created,
        mock_ensure_real,
        mock_sql_connect,
        mock_connect,
        mock_sleep,
    ):
        from sto_crm.updates import create_backup

        # Setup mock stat & lstat
        mock_stat_res = MagicMock()
        mock_stat_res.st_size = 200
        mock_stat_res.st_mode = 0o100644
        mock_stat_res.st_mtime = 123456789.0
        mock_stat.return_value = mock_stat_res
        mock_lstat.return_value = mock_stat_res

        mock_source_1 = MagicMock()
        mock_source_1.backup.side_effect = sqlite3.OperationalError(
            "database is locked"
        )

        mock_source_2 = MagicMock()  # succeeds on retry

        # connect succeeds twice
        mock_connect.side_effect = [mock_source_1, mock_source_2]

        mock_destination = MagicMock()
        mock_sql_connect.return_value = mock_destination

        res = create_backup()

        # Connect called twice
        self.assertEqual(mock_connect.call_count, 2)
        # Sleep called once
        self.assertEqual(mock_sleep.call_count, 1)
        # Check size
        self.assertEqual(res["size"], 200)

    @patch("sto_crm.updates.time.sleep")
    @patch("sto_crm.updates.connect")
    @patch("sto_crm.updates.sqlite3.connect")
    @patch("sto_crm.updates.ensure_real_backup_dir")
    @patch("sto_crm.updates.ensure_private_file_created")
    @patch("sto_crm.updates.ensure_private_file")
    @patch("sto_crm.updates.prune_backups")
    def test_create_backup_other_operational_error(
        self,
        mock_prune,
        mock_ensure_private,
        mock_ensure_created,
        mock_ensure_real,
        mock_sql_connect,
        mock_connect,
        mock_sleep,
    ):
        from sto_crm.updates import create_backup

        # Throws some other operational error, e.g., disk full
        mock_connect.side_effect = sqlite3.OperationalError("some other database error")

        with self.assertRaises(RuntimeError) as ctx:
            create_backup()

        self.assertIn("Не удалось создать резервную копию базы", str(ctx.exception))
        # Should fail on first attempt without retrying
        self.assertEqual(mock_connect.call_count, 1)
        self.assertEqual(mock_sleep.call_count, 0)

    @patch("os.name", "nt")
    @patch("os.lstat")
    def test_is_unsafe_link_or_reparse_lstat_win(self, mock_lstat):
        from sto_crm.updates import is_unsafe_link_or_reparse

        res_mock = MagicMock()
        res_mock.st_file_attributes = 0x400
        res_mock.st_reparse_tag = 0  # not a cloud/onedrive tag
        mock_lstat.return_value = res_mock

        path_mock = MagicMock(spec=Path)
        path_mock.is_symlink.return_value = False

        self.assertTrue(is_unsafe_link_or_reparse(path_mock))

        # Check cloud/onedrive tags are permitted (return False)
        # OneDrive tag 0x80000021
        res_mock.st_reparse_tag = 0x80000021
        self.assertFalse(is_unsafe_link_or_reparse(path_mock))

        # Cloud API tag 0x9000001A
        res_mock.st_reparse_tag = 0x9000001A
        self.assertFalse(is_unsafe_link_or_reparse(path_mock))

    @patch("os.name", "nt")
    @patch("os.lstat")
    @patch("ctypes.windll", create=True)
    def test_is_unsafe_link_or_reparse_ctypes_win(self, mock_windll, mock_lstat):
        from sto_crm.updates import is_unsafe_link_or_reparse

        original_lstat = os.lstat

        def lstat_side_effect(path, *args, **kwargs):
            if isinstance(path, MagicMock) or (
                hasattr(path, "__str__") and "junction" in str(path)
            ):
                raise Exception("error")
            # Простейшая защита по имени файла/пути без вызова inspect.stack
            try:
                p_str = str(path)
                if "coverage" in p_str or "pytest" in p_str or "unittest" in p_str:
                    return original_lstat(path, *args, **kwargs)
            except Exception:
                pass
            raise Exception("error")

        mock_lstat.side_effect = lstat_side_effect

        mock_windll.kernel32.GetFileAttributesW.return_value = 0x400
        # Mock FindFirstFileW structure
        mock_windll.kernel32.FindFirstFileW.return_value = 12345

        # We need FindFirstFileW to write 0 st_reparse_tag value into find_data structure
        # to trigger true-positives for junctions/symlinks
        # dwReserved0 is st_reparse_tag
        def find_first_side_effect(path, find_data_ref, *args):
            find_data_ref._obj.dwReserved0 = 0  # not a cloud/onedrive tag
            return 12345

        mock_windll.kernel32.FindFirstFileW.side_effect = find_first_side_effect

        path_mock = MagicMock(spec=Path)
        path_mock.is_symlink.return_value = False
        path_mock.__str__.return_value = "C:\\path\\junction"

        self.assertTrue(is_unsafe_link_or_reparse(path_mock))
        mock_windll.kernel32.GetFileAttributesW.assert_called_once_with(
            "C:\\path\\junction"
        )

        # check that cloud api behaves correctly on ctypes path
        def find_first_cloud_side_effect(path, find_data_ref, *args):
            find_data_ref._obj.dwReserved0 = 0x9000001A
            return 12345

        mock_windll.kernel32.FindFirstFileW.side_effect = find_first_cloud_side_effect
        self.assertFalse(is_unsafe_link_or_reparse(path_mock))


class TestUpdatesFacadeRegression(unittest.TestCase):
    def test_facade_monkeypatch_restoration(self):
        import sto_crm.updates
        from sto_crm import backup, updater
        from sto_crm.updater import installer

        # 1. ensure_real_dir
        orig_backup_dir = backup.ensure_real_dir
        orig_installer_dir = installer.ensure_real_dir
        self.assertIsNot(orig_backup_dir, orig_installer_dir)

        # 2. is_unsafe_link_or_reparse
        orig_backup_reparse = backup.is_unsafe_link_or_reparse
        orig_installer_reparse = installer.is_unsafe_link_or_reparse
        self.assertIsNot(orig_backup_reparse, orig_installer_reparse)

        # 3. _safe_unlink
        orig_updater_unlink = updater._safe_unlink
        orig_installer_unlink = installer._safe_unlink
        self.assertIsNot(orig_updater_unlink, orig_installer_unlink)

        # Apply monkeypatches via facade
        def dummy_ensure_real_dir(d: Path, n: str) -> None:
            return None

        def dummy_is_unsafe(p: Path) -> bool:
            return False

        def dummy_unlink(p: Path) -> None:
            return None

        sto_crm.updates.ensure_real_dir = dummy_ensure_real_dir
        sto_crm.updates.is_unsafe_link_or_reparse = dummy_is_unsafe
        sto_crm.updates._safe_unlink = dummy_unlink

        # Verify they got patched globally on all associated submodules
        self.assertIs(backup.ensure_real_dir, dummy_ensure_real_dir)
        self.assertIs(installer.ensure_real_dir, dummy_ensure_real_dir)

        self.assertIs(backup.is_unsafe_link_or_reparse, dummy_is_unsafe)
        self.assertIs(installer.is_unsafe_link_or_reparse, dummy_is_unsafe)

        self.assertIs(updater._safe_unlink, dummy_unlink)
        self.assertIs(installer._safe_unlink, dummy_unlink)

        # Delete them from facade
        del sto_crm.updates.ensure_real_dir
        del sto_crm.updates.is_unsafe_link_or_reparse
        del sto_crm.updates._safe_unlink

        # Verify they are restored to their OWN original implementations
        self.assertIs(backup.ensure_real_dir, orig_backup_dir)
        self.assertIs(installer.ensure_real_dir, orig_installer_dir)

        self.assertIs(backup.is_unsafe_link_or_reparse, orig_backup_reparse)
        self.assertIs(installer.is_unsafe_link_or_reparse, orig_installer_reparse)

        self.assertIs(updater._safe_unlink, orig_updater_unlink)
        self.assertIs(installer._safe_unlink, orig_installer_unlink)
