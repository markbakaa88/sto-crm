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
