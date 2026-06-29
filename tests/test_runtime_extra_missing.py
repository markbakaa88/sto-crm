import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from sto_crm.runtime import csv_cell, ensure_private_file_created


class TestRuntimeExtraMissing(unittest.TestCase):
    def test_ensure_private_file_created_symlink(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            real_file = Path(tmpdir) / "real.txt"
            real_file.touch()
            sym_file = Path(tmpdir) / "sym.txt"
            os.symlink(real_file, sym_file)
            with self.assertRaises(OSError) as ctx:
                ensure_private_file_created(sym_file)
            self.assertTrue(
                any(
                    phrase in str(ctx.exception)
                    for phrase in ["символической ссылкой", "reparse point"]
                )
            )

    def test_csv_cell_float_or_int(self):
        self.assertEqual(csv_cell(123), 123)
        self.assertEqual(csv_cell(45.67), 45.67)

    def test_ensure_private_file_created_symlink_parent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            real_dir = tmp_path / "real_dir"
            real_dir.mkdir()

            # Create a symlink parent
            link_parent = tmp_path / "link_parent"
            os.symlink(real_dir, link_parent, target_is_directory=True)

            # The DB file target inside symlink parent
            db_target = link_parent / "sto_crm.sqlite3"

            with self.assertRaises(OSError) as ctx:
                ensure_private_file_created(db_target)

            self.assertTrue(
                any(
                    phrase in str(ctx.exception)
                    for phrase in ["символической ссылкой", "reparse point"]
                )
            )
            # Ensure the file was not created through the symlink parent redirection
            self.assertFalse((real_dir / "sto_crm.sqlite3").exists())

    def test_ensure_private_file_created_normal_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            normal_db = Path(tmpdir) / "normal.sqlite3"
            ensure_private_file_created(normal_db)
            self.assertTrue(normal_db.exists())

    def test_windows_reparse_parent_rejected_mocked(self):
        from sto_crm.filesystem_safety import check_unsafe_path_or_parents

        mock_dir = Path("/tmp/mock_windows_junction")
        mock_stat = MagicMock()
        mock_stat.st_file_attributes = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT
        mock_stat.st_reparse_tag = 0  # Not a cloud tag (unsafe reparse point)

        db_file = mock_dir / "crm.sqlite3"

        def fake_lstat(path):
            if str(path) == str(mock_dir):
                return mock_stat
            res = MagicMock()
            res.st_file_attributes = 0
            res.st_reparse_tag = 0
            return res

        with patch("os.name", "nt"), patch("os.lstat", side_effect=fake_lstat):
            with self.assertRaises(OSError) as ctx:
                check_unsafe_path_or_parents(db_file)

            self.assertTrue(
                any(
                    phrase in str(ctx.exception)
                    for phrase in ["символической ссылкой", "reparse point"]
                )
            )

    def test_normalize_db_path_symlink_parent_rejected(self):
        from sto_crm.cli import normalize_db_path

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            real = base / "real"
            real.mkdir()
            link = base / "link_parent"
            os.symlink(real, link, target_is_directory=True)
            target = link / "crm.sqlite3"

            with self.assertRaises(OSError) as ctx:
                normalize_db_path(target)

            self.assertTrue(
                any(
                    phrase in str(ctx.exception)
                    for phrase in ["символической ссылкой", "reparse point"]
                )
            )
            # Ensure no file was created
            self.assertFalse((real / "crm.sqlite3").exists())
            self.assertFalse(target.exists())

    def test_windows_cloud_reparse_parent_not_allowed_for_db(self):
        from sto_crm.filesystem_safety import check_unsafe_path_or_parents

        mock_dir = Path("/tmp/mock_windows_onedrive")
        mock_stat = MagicMock()
        mock_stat.st_file_attributes = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT
        mock_stat.st_reparse_tag = 0x80000021  # OneDrive cloud tag

        db_file = mock_dir / "crm.sqlite3"

        def fake_lstat(path):
            if str(path) == str(mock_dir):
                return mock_stat
            res = MagicMock()
            res.st_file_attributes = 0
            res.st_reparse_tag = 0
            return res

        with patch("os.name", "nt"), patch("os.lstat", side_effect=fake_lstat):
            with self.assertRaises(OSError) as ctx:
                check_unsafe_path_or_parents(db_file, allow_cloud_reparse=False)

            self.assertTrue(
                any(
                    phrase in str(ctx.exception)
                    for phrase in ["символической ссылкой", "reparse point"]
                )
            )

    def test_windows_cloud_reparse_parent_allowed_with_flag(self):
        from sto_crm.filesystem_safety import check_unsafe_path_or_parents

        mock_dir = Path("/tmp/mock_windows_onedrive_allowed")
        mock_stat = MagicMock()
        mock_stat.st_file_attributes = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT
        mock_stat.st_reparse_tag = 0x80000021  # OneDrive cloud tag

        db_file = mock_dir / "crm.sqlite3"

        def fake_lstat(path):
            if str(path) == str(mock_dir):
                return mock_stat
            res = MagicMock()
            res.st_file_attributes = 0
            res.st_reparse_tag = 0
            return res

        with patch("os.name", "nt"), patch("os.lstat", side_effect=fake_lstat):
            check_unsafe_path_or_parents(db_file, allow_cloud_reparse=True)

    def test_inspection_failures_on_existing_parent_raise_oserror(self):
        from sto_crm.filesystem_safety import check_unsafe_path_or_parents

        mock_dir = Path("/tmp/mock_permission_error_dir")
        db_file = mock_dir / "crm.sqlite3"

        def fake_lstat(path):
            if str(path) == str(mock_dir):
                raise PermissionError("Access denied")
            res = MagicMock()
            res.st_file_attributes = 0
            res.st_reparse_tag = 0
            return res

        with patch("os.lstat", side_effect=fake_lstat):
            with self.assertRaises(OSError) as ctx:
                check_unsafe_path_or_parents(db_file)
            self.assertIn("Failed to check path safety", str(ctx.exception))

    def test_file_not_found_on_unsafe_check_passes(self):
        from sto_crm.filesystem_safety import check_unsafe_path_or_parents

        mock_dir = Path("/tmp/mock_nonexistent_dir")
        db_file = mock_dir / "crm.sqlite3"

        def fake_lstat(path):
            raise FileNotFoundError("No such file or directory")

        with patch("os.lstat", side_effect=fake_lstat):
            check_unsafe_path_or_parents(db_file)
