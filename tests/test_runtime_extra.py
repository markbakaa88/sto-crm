import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestRuntimeExtra(unittest.TestCase):
    def test_user_data_dir_windows_mocked(self):
        from sto_crm import runtime

        # Вместо присвоения os.name = "nt", протестируем логику через mock самого os.environ.get
        # но так как на Linux Path("C:\\...") бросает ошибку при инстанциировании, если os.name == "nt" (в Python 3.13 WindowsPath не может быть создан на Linux).
        # Давайте протестируем ветку Linux/macOS с LOCALAPPDATA и без нее.
        with patch.dict(os.environ, {"LOCALAPPDATA": "/tmp/test_localappdata"}):
            self.assertEqual(
                runtime.user_data_dir(), Path("/tmp/test_localappdata/STO_CRM")
            )

        with patch.dict(os.environ, {}, clear=True):
            orig_os_name = os.name
            try:
                os.name = "posix"
                with patch("pathlib.Path.home", return_value=Path("/home/user")):
                    self.assertEqual(
                        runtime.user_data_dir(),
                        Path("/home/user/.local/share/sto_crm"),
                    )
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
            safe_log("Test message")  # Should proceed silently without exception

        # Mock sys.stdout to throw exception on write
        class BadStdout:
            def write(self, s):
                raise OSError("Stdout is broken")

            def flush(self):
                pass

        with patch("sys.stdout", BadStdout()):
            safe_log(
                "Test message 2"
            )  # Should suppress the exception and return normally

    def test_user_data_dir_windows_os_name(self):
        import os
        from unittest.mock import MagicMock, patch

        with patch("sto_crm.runtime.Path") as mock_path:
            mock_home = MagicMock()
            mock_path.home.return_value = mock_home
            orig_os_name = os.name
            try:
                os.name = "nt"
                from sto_crm import runtime

                with patch.dict(os.environ, {}, clear=True):
                    runtime.user_data_dir()
                mock_path.home.assert_called_once()
                mock_home.__truediv__.assert_called_with("AppData")
            finally:
                os.name = orig_os_name

    def test_ensure_private_file_nonexistent(self):
        from sto_crm.runtime import ensure_private_file

        ensure_private_file(Path("/nonexistent/file/path/123"))

    def test_ensure_private_file_created_windows(self):
        import os

        from sto_crm.runtime import ensure_private_file_created

        orig_os_name = os.name
        try:
            os.name = "nt"
            mock_path = MagicMock()
            # on NT it should call path.touch(exist_ok=True)
            ensure_private_file_created(mock_path)
            mock_path.touch.assert_called_once_with(exist_ok=True)
        finally:
            os.name = orig_os_name

    def test_ensure_private_file_created_no_nofollow(self):
        import os

        from sto_crm.runtime import ensure_private_file_created

        orig_o_nofollow = getattr(os, "O_NOFOLLOW", None)
        if hasattr(os, "O_NOFOLLOW"):
            delattr(os, "O_NOFOLLOW")
        # create a temporary file
        import tempfile

        tmp = tempfile.NamedTemporaryFile(delete=False)
        tmp.close()
        try:
            ensure_private_file_created(Path(tmp.name))
        finally:
            if orig_o_nofollow is not None:
                os.O_NOFOLLOW = orig_o_nofollow  # type: ignore[misc]
            os.unlink(tmp.name)

    def test_app_executable_path_frozen(self):
        import sys

        from sto_crm.runtime import app_executable_path

        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "executable", "/tmp/fake_exec"),
        ):
            self.assertEqual(app_executable_path(), Path("/tmp/fake_exec").resolve())

    def test_normalize_github_repository_variants(self):
        from sto_crm.runtime import normalize_github_repository

        # raw is empty or None
        self.assertEqual(normalize_github_repository(""), "markbakaa88/sto-crm")
        # non-github domain
        self.assertEqual(
            normalize_github_repository("https://gitlab.com/foo/bar"),
            "markbakaa88/sto-crm",
        )
        # parts < 2
        self.assertEqual(
            normalize_github_repository("https://github.com/foo"), "markbakaa88/sto-crm"
        )

    def test_parse_int_error_handling(self):
        from sto_crm.runtime import parse_int

        class BadObject:
            def __str__(self):
                raise ValueError("Bad")

        self.assertEqual(parse_int(BadObject(), default=999), 999)

    def test_parse_int_field_float_and_float_str(self):
        from sto_crm.runtime import parse_int_field

        # float input
        self.assertEqual(parse_int_field(5.0, "field"), 5)
        # string representing float
        self.assertEqual(parse_int_field("5.0", "field"), 5)
        self.assertEqual(parse_int_field("5,0", "field"), 5)

    def test_redact_sensitive_query_exception_and_empty_runtime(self):
        import sto_crm.runtime as runtime_mod
        from sto_crm.runtime import redact_sensitive_query

        orig_runtime = runtime_mod.RUNTIME
        try:
            # Empty / None runtime
            runtime_mod.RUNTIME = None  # type: ignore
            res = redact_sensitive_query("some_query")
            self.assertEqual(res, "some_query")

            # Runtime raises exception on attribute access
            class BadRuntimeObj:
                @property
                def csrf_token(self):
                    raise ValueError("Blocked")

            runtime_mod.RUNTIME = BadRuntimeObj()  # type: ignore
            res = redact_sensitive_query("some_query")
            self.assertEqual(res, "some_query")
        finally:
            runtime_mod.RUNTIME = orig_runtime

    def test_redact_local_paths_url_and_empty_raw(self):
        from sto_crm.runtime import redact_local_paths

        # URL path preservation
        msg = "Go to https://example.com/usr/local/bin/prog for detail"
        self.assertEqual(redact_local_paths(msg), msg)

        # Empty raw after stripping (mocked pattern to return ":::")
        with patch("sto_crm.runtime._LOCAL_PATH_RE") as mock_re:
            mock_match = MagicMock()
            mock_match.group.return_value = ":::"
            mock_match.start.return_value = 5
            mock_re.sub.side_effect = lambda repl, text: repl(mock_match)
            res = redact_local_paths("some message")
            self.assertEqual(res, ":::")

    def test_strict_json_loads_large_float(self):
        from sto_crm.runtime import strict_json_loads

        with self.assertRaises(ValueError):
            strict_json_loads('{"val": 1e1000}')
