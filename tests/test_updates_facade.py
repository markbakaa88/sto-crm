import unittest
from unittest.mock import MagicMock

import sto_crm.updates as updates
from sto_crm import backup as _backup
from sto_crm import runtime as _runtime
from sto_crm import updater as _updater
from sto_crm.updater import installer as _installer


class TestUpdatesFacadeMonkeypatch(unittest.TestCase):
    def test_monkeypatch_ensure_real_dir(self):
        orig_backup_func = _backup.ensure_real_dir
        orig_installer_func = _installer.ensure_real_dir

        self.assertIsNot(orig_backup_func, orig_installer_func)

        # Let's monkeypatch it on the updates facade
        mock_val = MagicMock()
        updates.ensure_real_dir = mock_val

        # Check that facade and submodules all have the mock
        self.assertIs(updates.ensure_real_dir, mock_val)
        self.assertIs(_backup.ensure_real_dir, mock_val)
        self.assertIs(_installer.ensure_real_dir, mock_val)

        # Now delete the attribute to restore original values
        del updates.ensure_real_dir

        # Check they are correctly restored to their respective original implementations
        self.assertIs(updates.ensure_real_dir, orig_backup_func)
        self.assertIs(_backup.ensure_real_dir, orig_backup_func)
        self.assertIs(_installer.ensure_real_dir, orig_installer_func)

    def test_monkeypatch_isolation_and_cleanup(self):
        orig_runtime_func = _runtime.app_executable_path
        orig_updater_func = _updater.app_executable_path
        orig_installer_func = _installer.app_executable_path

        mock_val = MagicMock()

        # Patch a symbol on updates facade
        updates.app_executable_path = mock_val

        # Facade and inner update modules (the submodules) should get patched
        self.assertIs(updates.app_executable_path, mock_val)
        self.assertIs(_updater.app_executable_path, mock_val)
        self.assertIs(_installer.app_executable_path, mock_val)

        # The source module (runtime) MUST NOT be mutated (isolation constraint)
        self.assertIs(_runtime.app_executable_path, orig_runtime_func)

        # Now delattr
        del updates.app_executable_path

        # Everything must be restored
        self.assertIs(updates.app_executable_path, orig_runtime_func)
        self.assertIs(_updater.app_executable_path, orig_updater_func)
        self.assertIs(_installer.app_executable_path, orig_installer_func)
        self.assertIs(_runtime.app_executable_path, orig_runtime_func)

    def test_regression_ensure_real_dir_restoration(self):
        # ensure_real_dir exists in both sto_crm.backup and sto_crm.updater.installer
        orig_backup_dir = _backup.ensure_real_dir
        orig_installer_dir = _installer.ensure_real_dir
        self.assertIsNot(orig_backup_dir, orig_installer_dir)

        mock_func = MagicMock()
        updates.ensure_real_dir = mock_func

        self.assertIs(_backup.ensure_real_dir, mock_func)
        self.assertIs(_installer.ensure_real_dir, mock_func)

        del updates.ensure_real_dir

        self.assertIs(_backup.ensure_real_dir, orig_backup_dir)
        self.assertIs(_installer.ensure_real_dir, orig_installer_dir)

    def test_regression_is_unsafe_link_or_reparse_restoration(self):
        # is_unsafe_link_or_reparse exists in sto_crm.backup and sto_crm.updater.installer
        orig_backup_reparse = _backup.is_unsafe_link_or_reparse
        orig_installer_reparse = _installer.is_unsafe_link_or_reparse
        self.assertIsNot(orig_backup_reparse, orig_installer_reparse)

        # Confirm both are indeed different original objects originally
        # (they should be different functions, wrapped local delegates)
        self.assertIsNot(orig_backup_reparse, orig_installer_reparse)

        mock_func = MagicMock()
        updates.is_unsafe_link_or_reparse = mock_func

        self.assertIs(_backup.is_unsafe_link_or_reparse, mock_func)
        self.assertIs(_installer.is_unsafe_link_or_reparse, mock_func)

        del updates.is_unsafe_link_or_reparse

        self.assertIs(_backup.is_unsafe_link_or_reparse, orig_backup_reparse)
        self.assertIs(_installer.is_unsafe_link_or_reparse, orig_installer_reparse)

    def test_regression_safe_unlink_restoration(self):
        # _safe_unlink exists in sto_crm.updater and sto_crm.updater.installer
        orig_updater_unlink = _updater._safe_unlink
        orig_installer_unlink = _installer._safe_unlink
        self.assertIsNot(orig_updater_unlink, orig_installer_unlink)

        mock_func = MagicMock()
        updates._safe_unlink = mock_func

        self.assertIs(_updater._safe_unlink, mock_func)
        self.assertIs(_installer._safe_unlink, mock_func)

        delattr(updates, "_safe_unlink")

        self.assertIs(_updater._safe_unlink, orig_updater_unlink)
        self.assertIs(_installer._safe_unlink, orig_installer_unlink)
