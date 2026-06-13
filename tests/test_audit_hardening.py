import logging
import os
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from sto_crm import runtime as _runtime
from sto_crm.database import db
from sto_crm.logging_config import RedactingFormatter
from sto_crm.runtime import (
    ensure_private_dir,
    ensure_private_file_created,
    redact_sensitive_query,
)


class TestAuditHardening(unittest.TestCase):
    def test_ensure_private_dir_chmod_fails(self):
        """Test ensure_private_dir handles chmod failures gracefully (e.g. host rules/containers)."""
        with patch("os.chmod") as mock_chmod, patch("os.umask") as mock_umask:
            mock_chmod.side_effect = OSError("Operation not permitted")

            # Should not raise exception
            path = Path("/tmp/nonexistent_test_dir_audit")
            with patch.object(Path, "mkdir") as mock_mkdirClass:
                ensure_private_dir(path)

                # Should attempt to make directory and set chmod
                mock_mkdirClass.assert_called_once()
                if os.name != "nt":
                    mock_chmod.assert_called_once()
                    mock_umask.assert_any_call(0o077)

    def test_ensure_private_file_created_umask(self):
        """Test ensure_private_file_created applies 0o077 umask and handles chmod fails."""
        with (
            patch("os.open") as mock_open,
            patch("os.close"),
            patch("os.chmod") as mock_chmod,
            patch("os.umask") as mock_umask,
        ):
            mock_open.return_value = 10
            mock_chmod.side_effect = OSError("Operation not permitted")

            path = Path("/tmp/nonexistent_file_audit.db")
            with (
                patch("sto_crm.runtime.ensure_private_dir") as mock_epd,
                patch.object(Path, "exists", return_value=True),
            ):
                ensure_private_file_created(path)

                mock_epd.assert_called_once_with(path.parent)
                if os.name != "nt":
                    mock_umask.assert_any_call(0o077)
                    self.assertTrue(mock_chmod.called)

    def test_db_rollback_safety_on_base_exception(self):
        """Test SQL transaction rollback is safe even when connection is closed/raises errors on rollback."""
        mock_conn = MagicMock(spec=sqlite3.Connection)
        mock_conn.in_transaction = True
        mock_conn.rollback.side_effect = sqlite3.ProgrammingError(
            "Cannot operate on a closed database."
        )
        mock_conn.close.side_effect = sqlite3.Error("Close failed")

        with patch("sto_crm.database.connect", return_value=mock_conn):
            # Verify that context manager propagates the original BaseException (e.g. KeyboardInterrupt)
            # and does not crash on the errors raised during rollback/close.
            with self.assertRaises(KeyboardInterrupt):
                with db() as conn:
                    self.assertEqual(conn, mock_conn)
                    raise KeyboardInterrupt("Thread interrupted")

            # Verify mock calls were attempted
            self.assertTrue(mock_conn.rollback.called or not mock_conn.in_transaction)
            mock_conn.close.assert_called_once()

    def test_db_commit_handles_closed_db_gracefully(self):
        """Test db commit handles connection closed/interrupted state safely."""
        mock_conn = MagicMock(spec=sqlite3.Connection)
        mock_conn.in_transaction = True
        mock_conn.commit.side_effect = sqlite3.ProgrammingError("Connection is closed")

        with patch("sto_crm.database.connect", return_value=mock_conn):
            # Should complete without throwing committing exceptions
            with db() as conn:
                self.assertEqual(conn, mock_conn)

            mock_conn.commit.assert_called_once()
            mock_conn.close.assert_called_once()

    def test_redact_sensitive_query_masks_active_tokens(self):
        """Test redact_sensitive_query masks all RUNTIME tokens and inline keys."""
        # Save original runtime tokens

        try:
            # Inject known values
            test_csrf = "T0K3N_CSRF_12345678"
            test_access = "T0K3N_ACCESS_ABCDEF"
            test_bootstrap = "T0K3N_BOOTSTRAP_XYZ"

            # Modify RUNTIME properties using patch or direct assignment since RUNTIME is @dataclass(frozen=True)
            # wait, since RUNTIME is frozen, we can patch it or assign it to globals or recreate it
            new_runtime = _runtime.Runtime(
                db_path=_runtime.RUNTIME.db_path,
                start_time=_runtime.RUNTIME.start_time,
                csrf_token=test_csrf,
                access_token=test_access,
                bootstrap_token=test_bootstrap,
            )
            with patch("sto_crm.runtime.RUNTIME", new_runtime):
                msg = f"Data: csrf={test_csrf}, access={test_access}, boot={test_bootstrap}"
                redacted = redact_sensitive_query(msg)
                self.assertNotIn(test_csrf, redacted)
                self.assertNotIn(test_access, redacted)
                self.assertNotIn(test_bootstrap, redacted)
                self.assertEqual(redacted.count("***"), 3)

                # Test json / key-value redaction
                json_msg = '{"csrf_token": "some_other_value", "token": "value2"}'
                json_redacted = redact_sensitive_query(json_msg)
                self.assertIn('"csrf_token": "***"', json_redacted)
                self.assertIn('"token": "***"', json_redacted)

                # Test headers / cookies
                header_msg = (
                    "X-CSRF-Token: some_value_here\nCookie: csrf_token=cookie_val"
                )
                header_redacted = redact_sensitive_query(header_msg)
                self.assertIn("X-CSRF-Token: ***", header_redacted)
                self.assertIn("csrf_token=***", header_redacted)
        finally:
            pass

    def test_redacting_formatter(self):
        """Test RedactingFormatter formats and redacts logging records."""
        formatter = RedactingFormatter("%(message)s")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="User request: csrf_token=abcdef",
            args=(),
            exc_info=None,
        )
        formatted = formatter.format(record)
        self.assertEqual(formatted, "User request: csrf_token=***")
