import logging
import os
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

from sto_crm import runtime as _runtime
from sto_crm.database import db
from sto_crm.logging_config import RedactingFormatter
from sto_crm.runtime import (
    ensure_private_dir,
    ensure_private_file_created,
    redact_sensitive_query,
)


class TestAuditHardening(unittest.TestCase):
    def setUp(self):
        import tempfile
        import time

        from sto_crm import runtime
        from sto_crm.database import init_db

        self.tempdir = tempfile.TemporaryDirectory()
        self.old_runtime = runtime.RUNTIME
        runtime.RUNTIME = runtime.Runtime(
            Path(self.tempdir.name) / "test.sqlite3",
            time.time(),
            "test-csrf-token",
            "test-access-token",
            "test-bootstrap-token",
        )
        init_db()

    def tearDown(self):
        from sto_crm import runtime

        if hasattr(self, "tempdir"):
            try:
                runtime.RUNTIME = self.old_runtime
            except Exception:
                pass
            self.tempdir.cleanup()

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

    def test_database_connect_not_supported_error(self):
        """Test NotSupportedError handling during SQLite create_function."""
        import tempfile

        from sto_crm.database import connect

        class MockConnection(sqlite3.Connection):
            def create_function(self, *args, **kwargs):
                if kwargs.get("deterministic") or (len(args) >= 4 and args[3] is True):
                    raise sqlite3.NotSupportedError(
                        "Mocked deterministic not supported"
                    )
                return super().create_function(*args, **kwargs)

        orig_connect = sqlite3.connect

        def mock_connect(*args, **kwargs):
            kwargs["factory"] = MockConnection
            return orig_connect(*args, **kwargs)

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_db = Path(tmpdir) / "temp_empty.sqlite3"
            new_runtime = _runtime.Runtime(
                db_path=temp_db,
                start_time=_runtime.RUNTIME.start_time,
                csrf_token=_runtime.RUNTIME.csrf_token,
                access_token=_runtime.RUNTIME.access_token,
                bootstrap_token=_runtime.RUNTIME.bootstrap_token,
            )
            with patch("sto_crm.runtime.RUNTIME", new_runtime):
                with patch("sqlite3.connect", side_effect=mock_connect):
                    conn = connect()
                    conn.close()

    def test_db_in_transaction_raises_error_normal(self):
        """Test AttributeError fallback when checking in_transaction on normal exit of db()."""
        from sto_crm.database import db

        mock_conn = MagicMock(spec=sqlite3.Connection)
        type(mock_conn).in_transaction = PropertyMock(
            side_effect=AttributeError("no property")
        )

        with patch("sto_crm.database.connect", return_value=mock_conn):
            with db() as conn:
                self.assertEqual(conn, mock_conn)

    def test_db_in_transaction_raises_sqlite_error_exception_path(self):
        """Test sqlite3.Error fallback when checking in_transaction in exception path of db()."""
        from sto_crm.database import db

        mock_conn = MagicMock(spec=sqlite3.Connection)
        type(mock_conn).in_transaction = PropertyMock(
            side_effect=sqlite3.Error("mock sqlite error")
        )

        with patch("sto_crm.database.connect", return_value=mock_conn):
            with self.assertRaises(ValueError):
                with db():
                    raise ValueError("test exception")

    def test_write_db_immediate_locked_retry(self):
        """Test write_db BEGIN IMMEDIATE retries on locked database and succeeds."""
        from sto_crm.database import write_db

        mock_conn = MagicMock(spec=sqlite3.Connection)
        call_count = 0

        def mock_execute(sql, *args, **kwargs):
            nonlocal call_count
            if sql == "BEGIN IMMEDIATE":
                call_count += 1
                if call_count == 1:
                    raise sqlite3.OperationalError("database is locked")
            return MagicMock()

        mock_conn.execute.side_effect = mock_execute

        with (
            patch("sto_crm.database.connect", return_value=mock_conn),
            patch("time.sleep") as mock_sleep,
        ):
            with write_db() as conn:
                self.assertEqual(conn, mock_conn)
            self.assertEqual(call_count, 2)
            mock_sleep.assert_called_once()

    def test_write_db_immediate_locked_exhausted(self):
        """Test write_db BEGIN IMMEDIATE retries on locked database, exhausts retries and raises error."""
        from sto_crm.database import write_db

        mock_conn = MagicMock(spec=sqlite3.Connection)

        def mock_execute(sql, *args, **kwargs):
            if sql == "BEGIN IMMEDIATE":
                raise sqlite3.OperationalError("database is locked")
            return MagicMock()

        mock_conn.execute.side_effect = mock_execute

        with (
            patch("sto_crm.database.connect", return_value=mock_conn),
            patch("time.sleep") as mock_sleep,
        ):
            with self.assertRaises(sqlite3.OperationalError):
                with write_db():
                    pass
            self.assertEqual(mock_sleep.call_count, 4)

    def test_init_db_in_transaction_raises_error_exception_path(self):
        """Test init_db handling AttributeError on in_transaction property on schema failure."""
        from contextlib import contextmanager

        from sto_crm.database import init_db

        mock_conn = MagicMock(spec=sqlite3.Connection)
        type(mock_conn).in_transaction = PropertyMock(
            side_effect=AttributeError("no property")
        )

        @contextmanager
        def mock_db():
            yield mock_conn

        with (
            patch("sto_crm.database.db", side_effect=mock_db),
            patch(
                "sto_crm.database.ensure_schema",
                side_effect=ValueError("schema failure"),
            ),
            patch("sto_crm.database.ensure_private_dir"),
        ):
            with self.assertRaises(ValueError) as ctx:
                init_db()
            self.assertEqual(str(ctx.exception), "schema failure")

    def test_init_db_rollback_raises_error_exception_path(self):
        """Test init_db handling sqlite3.Error on rollback() on schema failure."""
        from contextlib import contextmanager

        from sto_crm.database import init_db

        mock_conn = MagicMock(spec=sqlite3.Connection)
        type(mock_conn).in_transaction = PropertyMock(return_value=True)
        mock_conn.rollback.side_effect = sqlite3.Error("rollback error")

        @contextmanager
        def mock_db():
            yield mock_conn

        with (
            patch("sto_crm.database.db", side_effect=mock_db),
            patch(
                "sto_crm.database.ensure_schema",
                side_effect=ValueError("schema failure"),
            ),
            patch("sto_crm.database.ensure_private_dir"),
        ):
            with self.assertRaises(ValueError) as ctx:
                init_db()
            self.assertEqual(str(ctx.exception), "schema failure")
            mock_conn.rollback.assert_called_once()

    def test_normalize_legacy_unique_values_duplicate_continue(self):
        """Test search for duplicates in normalize_legacy_unique_values triggers continue on existing match."""
        from sto_crm.database import db, normalize_legacy_unique_values

        with db() as conn:
            conn.execute("DROP INDEX IF EXISTS ux_vehicles_vin_active")
            conn.execute(
                "INSERT OR IGNORE INTO customers (id, name, created_at, updated_at) VALUES (9999, 'Test Cust', '', '')"
            )
            conn.execute(
                "INSERT INTO vehicles (customer_id, make, model, vin, created_at, updated_at) VALUES (9999, 'Test', 'T', 'ABC', '', '')"
            )
            conn.execute(
                "INSERT INTO vehicles (customer_id, make, model, vin, created_at, updated_at) VALUES (9999, 'Test', 'T', 'ABC ', '', '')"
            )
            conn.execute(
                "INSERT INTO vehicles (customer_id, make, model, vin, created_at, updated_at) VALUES (9999, 'Test', 'T', 'DEF ', '', '')"
            )

            normalize_legacy_unique_values(conn, "vehicles", "vin")

            rows = conn.execute(
                "SELECT vin FROM vehicles WHERE customer_id = 9999 ORDER BY id"
            ).fetchall()
            self.assertEqual(rows[0]["vin"], "ABC")
            self.assertEqual(rows[1]["vin"], "ABC ")
            self.assertEqual(rows[2]["vin"], "DEF")

            conn.execute("DELETE FROM vehicles WHERE customer_id = 9999")
            conn.execute("DELETE FROM customers WHERE id = 9999")
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_vehicles_vin_active ON vehicles(CASEFOLD(TRIM(vin))) WHERE deleted_at IS NULL AND TRIM(vin) <> ''"
            )

    def test_redact_local_paths_windows_spaces(self):
        """Test redact_local_paths correctly masks absolute Windows paths containing spaces."""
        from sto_crm.runtime import redact_local_paths

        log_msg = (
            r"Failed to open C:\Program Files\STO CRM\sto_crm.sqlite3 database file!"
        )
        redacted = redact_local_paths(log_msg)
        self.assertNotIn("Program Files", redacted)
        self.assertNotIn("STO CRM", redacted)
        self.assertIn("sto_crm.sqlite3 database file!", redacted)

        # UNC path with spaces
        log_unc = r"Backup failed to \\Network Share\Folder With Spaces\file.db"
        redacted_unc = redact_local_paths(log_unc)
        self.assertNotIn("Folder With Spaces", redacted_unc)
        self.assertIn("file.db", redacted_unc)

    def test_validate_safe_path_windows_backslash(self):
        """Test validate_safe_path with backslash paths behaves correctly on Windows/mocked Windows."""
        from pathlib import PureWindowsPath

        from sto_crm.updates import validate_safe_path

        with patch("os.name", "nt"):
            # Should pass: normal absolute Windows path
            validate_safe_path(
                PureWindowsPath(r"C:\Users\User\AppData\Local\STO_CRM\db.sqlite3")
            )
            # Should pass: relative windows path
            validate_safe_path(PureWindowsPath(r"subfolder\file.txt"))

            # Should raise: path traversal with backslashes
            with self.assertRaises(OSError):
                validate_safe_path(PureWindowsPath(r"subfolder\..\..\other.txt"))
