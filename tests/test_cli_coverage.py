import signal
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from sto_crm.cli import main


class TestCliCoverage(unittest.TestCase):
    @patch("sto_crm.cli.create_server")
    @patch("sto_crm.cli.init_db")
    @patch("webbrowser.open")
    @patch("time.sleep")
    def test_cli_shutdown_double_call(self, mock_sleep, mock_web_open, mock_init_db, mock_create_server):
        # Covers line 132 (return when shutdown double-called)
        # also covers graceful_shutdown_flag is True (151->157)
        # and wait_for_active_threads missing on server (157->159)
        
        captured_handler = None
        def mock_signal(sig, handler):
            nonlocal captured_handler
            captured_handler = handler

        mock_server = MagicMock(spec=[
            "server_address", "server_port", "serve_forever", "shutdown", "server_close", "graceful_shutdown_flag"
        ])
        mock_server.server_address = ("127.0.0.1", 8765)
        mock_server.server_port = 8765
        mock_create_server.return_value = mock_server

        def trigger_shutdown(*args, **kwargs):
            if captured_handler:
                captured_handler(signal.SIGINT, None)
                # Call second time to hit the early return
                captured_handler(signal.SIGINT, None)

        mock_server.serve_forever.side_effect = trigger_shutdown

        with (
            patch("signal.signal", side_effect=mock_signal),
            patch("threading.current_thread") as mock_curr,
            patch("threading.main_thread") as mock_main,
        ):
            t_obj = MagicMock()
            mock_curr.return_value = t_obj
            mock_main.return_value = t_obj

            res = main(["--port", "8765", "--no-browser"])
            self.assertEqual(res, 0)

    @patch("sto_crm.cli.create_server")
    @patch("sto_crm.cli.init_db")
    @patch("webbrowser.open")
    @patch("time.sleep")
    def test_cli_threading_mismatch(self, mock_sleep, mock_web_open, mock_init_db, mock_create_server):
        # Covers 137->142 (when is main_thread is False, signals are NOT registered)
        # Also covers graceful_shutdown_flag is False (151->157) since it retains False
        
        mock_server = MagicMock()
        mock_server.server_address = ("127.0.0.1", 8765)
        mock_server.server_port = 8765
        mock_server.graceful_shutdown_flag = False
        mock_create_server.return_value = mock_server
        mock_server.serve_forever.side_effect = lambda: None

        with (
            patch("signal.signal") as mock_sig_func,
            patch("threading.current_thread") as mock_curr,
            patch("threading.main_thread") as mock_main,
        ):
            # Different objects so identity "is" evaluates to False
            t_curr = MagicMock()
            t_main = MagicMock()
            mock_curr.return_value = t_curr
            mock_main.return_value = t_main

            res = main(["--port", "8765", "--no-browser"])
            self.assertEqual(res, 0)
            self.assertEqual(mock_sig_func.call_count, 0)

    @patch("sto_crm.cli.create_server")
    @patch("sto_crm.cli.init_db")
    @patch("webbrowser.open")
    @patch("time.sleep")
    def test_cli_sigterm_missing(self, mock_sleep, mock_web_open, mock_init_db, mock_create_server):
        # Covers 139->142 (if HAS_SIGTERM is False, SIGTERM skipped)
        
        mock_server = MagicMock()
        mock_server.server_address = ("127.0.0.1", 8765)
        mock_server.server_port = 8765
        mock_server.graceful_shutdown_flag = False
        mock_create_server.return_value = mock_server
        mock_server.serve_forever.side_effect = lambda: None

        orig_hasattr = hasattr
        def mock_hasattr(obj, name):
            if obj is signal and name == "SIGTERM":
                return False
            return orig_hasattr(obj, name)

        with (
            patch("threading.current_thread") as mock_curr,
            patch("threading.main_thread") as mock_main,
            patch("builtins.hasattr", side_effect=mock_hasattr),
            patch("signal.signal") as mock_sig_func,
        ):
            t_obj = MagicMock()
            mock_curr.return_value = t_obj
            mock_main.return_value = t_obj

            res = main(["--port", "8765", "--no-browser"])
            self.assertEqual(res, 0)
            
            registered_sigs = [call[0][0] for call in mock_sig_func.call_args_list if call[0]]
            self.assertIn(signal.SIGINT, registered_sigs)
            self.assertNotIn(getattr(signal, "SIGTERM", None), registered_sigs)

    @patch("sto_crm.cli.create_server")
    @patch("sto_crm.cli.init_db")
    @patch("webbrowser.open")
    @patch("time.sleep")
    def test_cli_normalize_db_path_directory(self, mock_sleep, mock_web_open, mock_init_db, mock_create_server):
        # Covers line 104 in normalize_db_path (directory path provided)
        import tempfile
        
        mock_server = MagicMock()
        mock_server.server_address = ("127.0.0.1", 8765)
        mock_server.server_port = 8765
        mock_server.graceful_shutdown_flag = False
        mock_create_server.return_value = mock_server
        mock_server.serve_forever.side_effect = lambda: None

        with tempfile.TemporaryDirectory() as tmpdir:
            # We pass a directory path (ends with slash / exists as dir)
            dir_path = Path(tmpdir)
            
            res = main(["--port", "8765", "--no-browser", "--db", str(dir_path)])
            self.assertEqual(res, 0)
            
            # Runtime was instantiated with db_path = dir_path / "sto_crm.sqlite3"
            from sto_crm.runtime import RUNTIME
            self.assertEqual(RUNTIME.db_path, dir_path / "sto_crm.sqlite3")


class TestWebCoverage(unittest.TestCase):
    def test_web_read_asset_nonexistent_file(self):
        from sto_crm.web import _read_asset
        # is_frozen is False by default during tests.
        # Calling with a nonexistent file will skip the filesystem branch and raise FileNotFoundError.
        with self.assertRaises(FileNotFoundError):
            _read_asset("nonexistent_asset_file_123.txt")

