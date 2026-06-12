import os
import unittest
from pathlib import Path
from unittest.mock import patch


class TestRuntimeExtra(unittest.TestCase):
    def test_user_data_dir_windows_mocked(self):
        from sto_crm import runtime
        
        # Вместо присвоения os.name = "nt", протестируем логику через mock самого os.environ.get
        # но так как на Linux Path("C:\\...") бросает ошибку при инстанциировании, если os.name == "nt" (в Python 3.13 WindowsPath не может быть создан на Linux).
        # Давайте протестируем ветку Linux/macOS с LOCALAPPDATA и без нее.
        with patch.dict(os.environ, {"LOCALAPPDATA": "/tmp/test_localappdata"}):
            self.assertEqual(runtime.user_data_dir(), Path("/tmp/test_localappdata/STO_CRM"))
        
        with patch.dict(os.environ, {}, clear=True):
            orig_os_name = os.name
            try:
                os.name = "posix"
                self.assertEqual(runtime.user_data_dir(), Path.home() / ".local" / "share" / "sto_crm")
            finally:
                os.name = orig_os_name

    def test_display_path_relative_failure(self):
        from sto_crm.runtime import display_path
        # display_path(p) для путей вне домашнего каталога возвращает relative_to-fail ветку, которая делает path.name
        # но так как p имеет name, self.assertEqual(res, "some_child_file")!
        p = Path("/nonexistent_base_directory_123456/some_child_file")
        res = display_path(p)
        self.assertEqual(res, "some_child_file")

        # Но если у нас путь без name (например, root "/"):
        p_root = Path("/")
        res_root = display_path(p_root)
        self.assertEqual(res_root, "/")

    def test_redact_local_paths_regex_patterns(self):
        from sto_crm.runtime import redact_local_paths
        
        # Test windows path style
        msg = "Error in C:\\Users\\Name\\file.txt, try again."
        self.assertEqual(redact_local_paths(msg), "Error in file.txt, try again.")
        
        # Test empty trailing path edge cases
        msg_dots = "File at /test/file.txt..."
        self.assertIn("file.txt...", redact_local_paths(msg_dots))

    def test_strict_json_loads_constants_and_finite(self):
        from sto_crm.runtime import strict_json_loads
        
        with self.assertRaises(ValueError):
            strict_json_loads('{"val": NaN}')
        with self.assertRaises(ValueError):
            strict_json_loads('{"val": Infinity}')
        with self.assertRaises(ValueError):
            strict_json_loads('{"val": -Infinity}')
        with self.assertRaises(ValueError):
            strict_json_loads('{"dup": 1, "dup": 2}')

    def test_safe_log_no_stdout_or_failure(self):
        from sto_crm.runtime import safe_log
        
        # Mock sys.stdout to be None
        with patch("sys.stdout", None):
            safe_log("Test message") # Should proceed silently without exception
            
        # Mock sys.stdout to throw exception on write
        class BadStdout:
            def write(self, s):
                raise OSError("Stdout is broken")
            def flush(self):
                pass
        
        with patch("sys.stdout", BadStdout()):
            safe_log("Test message 2") # Should suppress the exception and return normally
