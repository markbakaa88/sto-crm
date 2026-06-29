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

    def test_non_existent_attribute_fallback_to_facade(self):
        # Setting a completely new attribute not present in submodules
        self.assertFalse(hasattr(updates, "totally_new_attr_unused"))
        updates.totally_new_attr_unused = "hello_world"
        self.assertEqual(updates.totally_new_attr_unused, "hello_world")

        # Ensure it didn't leak/patch onto submodules
        self.assertFalse(hasattr(_backup, "totally_new_attr_unused"))
        self.assertFalse(hasattr(_updater, "totally_new_attr_unused"))

        # Deleting it must restore it to non-existent state
        del updates.totally_new_attr_unused
        self.assertFalse(hasattr(updates, "totally_new_attr_unused"))

    def test_mocked_submodule_preserves_monkeypatch_flow(self):
        # Replace _updater temporarily with a MagicMock (non-ModuleType)
        import sto_crm.updates as updates_mod

        orig_updater_ref = updates_mod._updater
        mock_updater = MagicMock(spec=["mocked_attr_on_updater"])
        mock_updater.mocked_attr_on_updater = "original_mock_val"

        # Inject mock_updater into updates facade namespace
        updates_mod._updater = mock_updater
        try:
            # Patch mocked_attr_on_updater via facade
            updates.mocked_attr_on_updater = "patched_mock_val"
            self.assertEqual(mock_updater.mocked_attr_on_updater, "patched_mock_val")
            self.assertEqual(updates.mocked_attr_on_updater, "patched_mock_val")

            # Restore via delattr
            del updates.mocked_attr_on_updater
            self.assertEqual(mock_updater.mocked_attr_on_updater, "original_mock_val")
        finally:
            updates_mod._updater = orig_updater_ref

    def test_per_submodule_setattr_recording(self):
        # 1) __setattr__ patching and recording originals only for submodules containing the attribute.
        from sto_crm.updater import checker as _checker

        attr_name = "test_submodule_attr_setattr"

        # Ensure it doesn't exist on submodules beforehand
        for m in (_backup, _updater, _checker, _installer):
            if hasattr(m, attr_name):
                delattr(m, attr_name)

        # Set attribute only on _backup and _updater
        _backup.test_submodule_attr_setattr = "orig_backup"
        _updater.test_submodule_attr_setattr = "orig_updater"

        try:
            # Set attribute via facade
            updates.test_submodule_attr_setattr = "new_val"

            # Check that _originals records only the submodules containing the attribute
            originals = getattr(updates, "_originals", {})
            self.assertIn(attr_name, originals)
            modules_orig = originals[attr_name]["modules"]

            self.assertIn(_backup, modules_orig)
            self.assertIn(_updater, modules_orig)
            self.assertNotIn(_checker, modules_orig)
            self.assertNotIn(_installer, modules_orig)

            self.assertEqual(modules_orig[_backup], "orig_backup")
            self.assertEqual(modules_orig[_updater], "orig_updater")

            # Check that setting attribute mutated only the submodules that had it
            self.assertEqual(_backup.test_submodule_attr_setattr, "new_val")
            self.assertEqual(_updater.test_submodule_attr_setattr, "new_val")
            self.assertFalse(hasattr(_checker, attr_name))
            self.assertFalse(hasattr(_installer, attr_name))

        finally:
            if hasattr(updates, attr_name):
                try:
                    delattr(updates, attr_name)
                except AttributeError:
                    pass
            for m in (_backup, _updater, _checker, _installer):
                if hasattr(m, attr_name):
                    delattr(m, attr_name)

    def test_per_submodule_delattr_restoration(self):
        # 2) __delattr__ restoring the correct original value to each respective submodule.
        from sto_crm.updater import checker as _checker

        attr_name = "test_submodule_attr_delattr"

        for m in (_backup, _updater, _checker, _installer):
            if hasattr(m, attr_name):
                delattr(m, attr_name)

        _backup.test_submodule_attr_delattr = "orig_backup_val"
        _updater.test_submodule_attr_delattr = "orig_updater_val"

        try:
            # Patch via facade
            updates.test_submodule_attr_delattr = "patched_val"

            # Verify both submodules are patched
            self.assertEqual(_backup.test_submodule_attr_delattr, "patched_val")
            self.assertEqual(_updater.test_submodule_attr_delattr, "patched_val")

            # Restore via delattr
            delattr(updates, attr_name)

            # Check original values are restored
            self.assertEqual(_backup.test_submodule_attr_delattr, "orig_backup_val")
            self.assertEqual(_updater.test_submodule_attr_delattr, "orig_updater_val")

            # And check updates facade doesn't have it anymore (was sentinel/not present originally)
            self.assertNotIn(attr_name, updates.__dict__)

        finally:
            if hasattr(updates, attr_name):
                try:
                    delattr(updates, attr_name)
                except AttributeError:
                    pass
            for m in (_backup, _updater, _checker, _installer):
                if hasattr(m, attr_name):
                    delattr(m, attr_name)

    def test_per_submodule_delattr_deletes_when_no_original(self):
        # 3) __delattr__ deleting the attribute from submodules where it didn't exist originally.
        from sto_crm.updater import checker as _checker

        attr_name = "test_submodule_attr_no_original"

        for m in (_backup, _updater, _checker, _installer):
            if hasattr(m, attr_name):
                delattr(m, attr_name)

        try:
            # Set via facade
            updates.test_submodule_attr_no_original = "facade_val"

            # Simulate the attribute being dynamically set on _checker during active patch
            _checker.test_submodule_attr_no_original = "unexpected_val"

            # Delete via facade
            delattr(updates, attr_name)

            # None of the submodules should have it now
            self.assertFalse(hasattr(_checker, attr_name))
            self.assertFalse(hasattr(_backup, attr_name))
            self.assertFalse(hasattr(_updater, attr_name))
            self.assertFalse(hasattr(_installer, attr_name))
            self.assertNotIn(attr_name, updates.__dict__)

        finally:
            if hasattr(updates, attr_name):
                try:
                    delattr(updates, attr_name)
                except AttributeError:
                    pass
            for m in (_backup, _updater, _checker, _installer):
                if hasattr(m, attr_name):
                    delattr(m, attr_name)
