import sqlite3
import threading
import time
from unittest import mock

import pytest

from sto_crm.database import connect, db, init_db


@pytest.fixture
def patch_db_path(tmp_path):
    import sto_crm.runtime

    temp_db = tmp_path / "test_locks.sqlite3"
    new_runtime = sto_crm.runtime.Runtime(
        db_path=temp_db,
        start_time=sto_crm.runtime.RUNTIME.start_time,
        csrf_token=sto_crm.runtime.RUNTIME.csrf_token,
        access_token=sto_crm.runtime.RUNTIME.access_token,
        bootstrap_token=sto_crm.runtime.RUNTIME.bootstrap_token,
    )
    with mock.patch("sto_crm.runtime.RUNTIME", new_runtime):
        yield temp_db


def test_readonly_pragma_active(patch_db_path):
    """Проверяем, что PRAGMA query_only = ON действительно активна."""
    init_db()
    with db(readonly=True) as conn:
        with pytest.raises(sqlite3.OperationalError) as excinfo:
            conn.execute("CREATE TABLE IF NOT EXISTS test_fail (id INTEGER)")
        assert "readonly" in str(excinfo.value).lower()


def test_retry_on_cursor_execute_success(patch_db_path):
    """Тестируем, что при временных блокировках execute делает ретраи и завершается успешно."""
    init_db()
    mock_execute = mock.MagicMock()
    mock_execute.side_effect = [
        sqlite3.OperationalError("database is locked"),
        sqlite3.OperationalError("database is locked"),
        mock.MagicMock(),  # Успешный результат
    ]

    with mock.patch("sto_crm.database._locked_retry_delay", return_value=0.001):
        with db(readonly=True) as conn:
            retrying_cursor = conn.cursor()
            mock_cursor = mock.MagicMock()
            mock_cursor.execute = mock_execute
            retrying_cursor._cursor = mock_cursor

            retrying_cursor.execute("SELECT 1")
            assert mock_execute.call_count == 3


def test_retry_on_cursor_execute_exhausted(patch_db_path):
    """Проверяем, что при постоянной блокировке после 5 попыток выбрасывается OperationalError."""
    init_db()
    mock_execute = mock.MagicMock(
        side_effect=sqlite3.OperationalError("database is locked")
    )

    with mock.patch("sto_crm.database._locked_retry_delay", return_value=0.001):
        with db(readonly=True) as conn:
            retrying_cursor = conn.cursor()
            mock_cursor = mock.MagicMock()
            mock_cursor.execute = mock_execute
            retrying_cursor._cursor = mock_cursor

            with pytest.raises(sqlite3.OperationalError) as excinfo:
                retrying_cursor.execute("SELECT 1")
            assert "locked" in str(excinfo.value).lower()
            assert mock_execute.call_count == 5


def test_concurrent_read_write_locks(patch_db_path):
    """Реальный конкурентный сценарий:
    Поток-писатель захватывает EXCLUSIVE транзакцию и спит.
    Основной поток-читатель заходит в db(readonly=True) и пытается сделать SELECT.
    Благодаря retry-логике, читатель дожидается завершения транзакции
    и успешно завершает запрос.
    """
    init_db()

    # Переключаем в DELETE режим для симуляции блокировки читателей
    conn = connect()
    conn.execute("PRAGMA journal_mode = DELETE")
    conn.close()

    barrier = threading.Barrier(2)
    write_finished = threading.Event()

    def writer():
        # Захватываем эксклюзивную блокировку в отдельном потоке
        w_conn = connect()
        try:
            w_conn.execute("BEGIN EXCLUSIVE")
            barrier.wait()
            time.sleep(0.15)
            w_conn.commit()
        finally:
            w_conn.close()
            write_finished.set()

    t = threading.Thread(target=writer)
    t.start()

    try:
        barrier.wait()
        # В этот момент БД эксклюзивно заблокирована писателем на 0.15 секунды.
        start_time = time.time()
        with db(readonly=True) as conn:
            # Временно выключаем busy_timeout у читателя, чтобы вызвать мгновенные OperationalError (locked)
            # на SQLite C-уровне, что заставит сработать нашу retry-логику на Python.
            conn.execute("PRAGMA busy_timeout = 0")

            res = conn.execute("SELECT 1").fetchone()[0]
            assert res == 1
        end_time = time.time()
        assert end_time - start_time >= 0.15
        assert write_finished.is_set()
    finally:
        t.join()


def test_retrying_cursor_execute_keeps_retrying_cursor_for_chained_fetch():
    raw_cursor = mock.MagicMock()
    raw_cursor.execute.return_value = raw_cursor
    raw_cursor.fetchall.side_effect = [
        sqlite3.OperationalError("database is locked"),
        [("ok",)],
    ]
    raw_cursor.fetchone.side_effect = [
        sqlite3.OperationalError("database is locked"),
        ("ok_one",),
    ]
    raw_cursor.fetchmany.side_effect = [
        sqlite3.OperationalError("database is locked"),
        [("ok_many",)],
    ]

    from sto_crm.database import RetryingCursor

    with mock.patch("sto_crm.database._locked_retry_delay", return_value=0.001):
        cursor = RetryingCursor(raw_cursor)
        # Test fetchall chained
        assert cursor.execute("SELECT 1").fetchall() == [("ok",)]
        # Test fetchone chained
        assert cursor.execute("SELECT 1").fetchone() == ("ok_one",)
        # Test fetchmany chained
        assert cursor.execute("SELECT 1").fetchmany(1) == [("ok_many",)]

    assert raw_cursor.execute.call_count == 3
    assert raw_cursor.fetchall.call_count == 2
    assert raw_cursor.fetchone.call_count == 2
    assert raw_cursor.fetchmany.call_count == 2


def test_retry_on_db_connect_success(patch_db_path):
    """Тестируем, что при блокировке БД при открытии соединения (connect/db) делаются ретраи."""
    init_db()

    mock_connect = mock.MagicMock()
    # Возвращаем OperationalError два раза, затем оригинальный connect
    mock_connect.side_effect = [
        sqlite3.OperationalError("database is locked"),
        sqlite3.OperationalError("database is locked"),
        connect(readonly=True),
    ]

    with mock.patch("sto_crm.database.connect", mock_connect):
        with mock.patch("sto_crm.database._locked_retry_delay", return_value=0.001):
            with db(readonly=True) as conn:
                res = conn.execute("SELECT 1").fetchone()[0]
                assert res == 1
            assert mock_connect.call_count == 3


def test_retry_on_db_connect_exhausted(patch_db_path):
    """Проверяем, что при постоянной блокировке при коннекте db() выбрасывает исключение после 5 попыток."""
    init_db()

    mock_connect = mock.MagicMock(
        side_effect=sqlite3.OperationalError("database is locked")
    )

    with mock.patch("sto_crm.database.connect", mock_connect):
        with mock.patch("sto_crm.database._locked_retry_delay", return_value=0.001):
            with pytest.raises(sqlite3.OperationalError) as excinfo:
                with db(readonly=True):
                    pass
            assert "locked" in str(excinfo.value).lower()
            assert mock_connect.call_count == 5


def test_init_db_wal_fallback(patch_db_path):
    """Проверяем, что при ошибке включения режима WAL в init_db() происходит fallback на DELETE."""
    # Используем собственный sub-class sqlite3.Connection через фабрику в sqlite3.connect
    class FallbackMockConnection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if "PRAGMA journal_mode = WAL" in sql:
                raise sqlite3.OperationalError("WAL is not supported on network shares")
            return super().execute(sql, *args, **kwargs)

    original_connect = sqlite3.connect

    def mock_sql_connect(*args, **kwargs):
        kwargs["factory"] = FallbackMockConnection
        return original_connect(*args, **kwargs)

    with mock.patch("sqlite3.connect", mock_sql_connect):
        init_db()

    # Проверим, что БД в итоге не WAL
    with db() as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() != "wal"


def test_connect_readonly_no_touch(patch_db_path):
    """Проверяем, что connect(readonly=True) не создает/изменяет файл БД (не вызывает ensure_private_file_created)."""
    with mock.patch("sto_crm.database.ensure_private_file_created") as mock_ensure_created:
        # Пытаемся открыть несуществующую БД в режиме readonly
        with pytest.raises(sqlite3.OperationalError):
            connect(readonly=True)
        # Убеждаемся, что touch не делался
        mock_ensure_created.assert_not_called()