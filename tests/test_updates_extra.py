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

        # 1. file not exists
        mock_current = MagicMock(spec=Path)
        mock_current.exists.return_value = False
        mock_app_path.return_value = mock_current
        with patch("os.name", "nt"):
            with self.assertRaises(RuntimeError) as ctx:
                schedule_windows_update(Path("dummy"), "sha")
            self.assertIn("Текущий исполняемый файл не найден", str(ctx.exception))

        # 2. file suffix is not .exe
        mock_current = MagicMock(spec=Path)
        mock_current.exists.return_value = True
        mock_current.suffix = ".py"
        mock_app_path.return_value = mock_current
        with patch("os.name", "nt"):
            with self.assertRaises(RuntimeError) as ctx:
                schedule_windows_update(Path("dummy"), "sha")
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
        from sto_crm.updates import validate_safe_path
        import tempfile
        import shutil

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
                self.assertIn("Путь не может быть символической ссылкой", str(ctx.exception))
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
                self.assertIn("Родительский каталог не может быть символической ссылкой", str(ctx.exception))
            except (OSError, NotImplementedError):
                pass

    def test_ensure_real_dir_validation_errors(self):
        from sto_crm.updates import ensure_real_dir
        import tempfile

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
            self.assertIn("Путь к каталогу занятого пути занят файлом", str(ctx.exception))

            # Directory is a symlink
            sym_dir = base / "sym_dir"
            try:
                sym_dir.symlink_to(directory, target_is_directory=True)
                with self.assertRaises(OSError) as ctx:
                    ensure_real_dir(sym_dir, "символической ссылки")
                self.assertIn("Каталог символической ссылки не может быть символической ссылкой", str(ctx.exception))
            except (OSError, NotImplementedError):
                pass

    def test_prune_backups_error_handling(self):
        from sto_crm.updates import prune_backups
        import tempfile

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
            with patch("sto_crm.updates.MAX_BACKUP_FILES", 2), patch("sto_crm.updates.MAX_BACKUP_TOTAL_BYTES", 0):
                prune_backups(backup_dir)
                # One of them should be removed since we have 3 but limit is 2
                remaining = list(backup_dir.glob("sto_crm_backup_*.sqlite3"))
                self.assertEqual(len(remaining), 2)


