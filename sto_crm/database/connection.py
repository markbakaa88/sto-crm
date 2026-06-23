"""SQLite connection handling and transaction wrappers with locked-retry logic."""

from __future__ import annotations

import random
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager as ContextManager
from contextlib import contextmanager
from typing import Any, Literal, TypeVar, overload

from sto_crm import runtime as _runtime
from sto_crm.runtime import (
    ensure_private_file,
    ensure_private_file_created,
)

T = TypeVar("T")


def _locked_retry_delay(attempt: int, base_delay: float = 0.05) -> float:
    return base_delay * (1.5**attempt) + random.uniform(0, 0.02)


def _retry_locked(
    operation: Callable[[], T], max_retries: int = 5, base_delay: float = 0.05
) -> T:
    last_exc = None
    for attempt in range(max_retries):
        try:
            return operation()
        except sqlite3.OperationalError as exc:
            last_exc = exc
            if "locked" in str(exc).lower() and attempt < max_retries - 1:
                time.sleep(_locked_retry_delay(attempt, base_delay))
                continue
            raise
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Unreachable")


class RetryingCursor:
    def __init__(self, cursor: sqlite3.Cursor):
        self._cursor = cursor

    def execute(self, sql: str, parameters: Any = ()) -> RetryingCursor:
        _retry_locked(lambda: self._cursor.execute(sql, parameters))
        return self

    def executemany(self, sql: str, seq_of_parameters: Any) -> RetryingCursor:
        _retry_locked(lambda: self._cursor.executemany(sql, seq_of_parameters))
        return self

    def executescript(self, sql_script: str) -> RetryingCursor:
        _retry_locked(lambda: self._cursor.executescript(sql_script))
        return self

    def fetchone(self) -> Any:
        return _retry_locked(lambda: self._cursor.fetchone())

    def fetchall(self) -> list[Any]:
        return _retry_locked(lambda: self._cursor.fetchall())

    def fetchmany(self, size: int | None = None) -> list[Any]:
        if size is None:
            return _retry_locked(lambda: self._cursor.fetchmany())
        return _retry_locked(lambda: self._cursor.fetchmany(size))

    def __iter__(self) -> RetryingIterator:
        return RetryingIterator(self._cursor)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._cursor, name)


class RetryingIterator:
    def __init__(self, cursor: sqlite3.Cursor):
        self._cursor = cursor
        self._iter = iter(cursor)

    def __next__(self) -> Any:
        return _retry_locked(lambda: next(self._iter))

    def __iter__(self) -> RetryingIterator:
        return self


class RetryingConnection:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def cursor(self) -> RetryingCursor:
        return RetryingCursor(self._conn.cursor())

    def execute(self, sql: str, parameters: Any = ()) -> RetryingCursor:
        return _retry_locked(
            lambda: RetryingCursor(self._conn.execute(sql, parameters))
        )

    def executemany(self, sql: str, seq_of_parameters: Any) -> RetryingCursor:
        return _retry_locked(
            lambda: RetryingCursor(self._conn.executemany(sql, seq_of_parameters))
        )

    def executescript(self, sql_script: str) -> RetryingCursor:
        return _retry_locked(
            lambda: RetryingCursor(self._conn.executescript(sql_script))
        )

    def commit(self) -> Any:
        return _retry_locked(lambda: self._conn.commit())

    def rollback(self) -> Any:
        return _retry_locked(lambda: self._conn.rollback())

    def __enter__(self) -> RetryingConnection:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


_open_connections: set[sqlite3.Connection] = set()
_open_connections_lock = threading.Lock()


def close_all_connections() -> None:
    """Close all tracked SQLite connections.

    If close fails, the connection remains in _open_connections to prevent
    silent leaks of untracked open database files.
    """
    with _open_connections_lock:
        for conn in list(_open_connections):
            try:
                conn.close()
                _open_connections.discard(conn)
            except Exception:
                pass


def connect(readonly: bool = False) -> sqlite3.Connection:
    # check_same_thread=False is used because SQLite connections are thread-local
    # (created, used, and closed within the same request thread via db() context manager).
    # Setting it to False allows the main/shutdown thread to safely call conn.close()
    # on active connections from worker threads during server shutdown, ensuring that
    # SQLite file handles are released. This is crucial on Windows, where open file
    # handles block deletion, updates, or modifications of SQLite files (DB, WAL, SHM).
    if readonly:
        db_uri = _runtime.RUNTIME.db_path.resolve(strict=False).as_uri() + "?mode=ro"
        conn = sqlite3.connect(
            db_uri,
            uri=True,
            timeout=30,
            isolation_level="DEFERRED",
            check_same_thread=False,
        )
    else:
        ensure_private_file_created(_runtime.RUNTIME.db_path)
        conn = sqlite3.connect(
            _runtime.RUNTIME.db_path,
            timeout=30,
            isolation_level="DEFERRED",
            check_same_thread=False,
        )
    with _open_connections_lock:
        _open_connections.add(conn)
    conn.row_factory = sqlite3.Row
    try:
        conn.create_function(
            "CASEFOLD", 1, lambda value: str(value or "").casefold(), deterministic=True
        )
    except sqlite3.NotSupportedError:
        conn.create_function("CASEFOLD", 1, lambda value: str(value or "").casefold())
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA temp_store = MEMORY")
    if readonly:
        conn.execute("PRAGMA query_only = ON")
    else:
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA mmap_size = 30000000000")
        conn.execute("PRAGMA page_size = 4096")
        ensure_private_file(_runtime.RUNTIME.db_path)
    return conn


@overload
def db(readonly: Literal[False] = False) -> ContextManager[sqlite3.Connection]: ...


@overload
def db(readonly: Literal[True]) -> ContextManager[RetryingConnection]: ...


@overload
def db(readonly: bool) -> ContextManager[sqlite3.Connection | RetryingConnection]: ...


@contextmanager
def db(readonly: bool = False) -> Iterator[Any]:
    import sto_crm.database
    conn: sqlite3.Connection | RetryingConnection | None = None
    for attempt in range(5):
        try:
            if readonly:
                c = sto_crm.database.connect(readonly=True)
                conn = RetryingConnection(c)
            else:
                conn = sto_crm.database.connect()
            break
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc).lower() and attempt < 4:
                time.sleep(_locked_retry_delay(attempt, 0.05))
                continue
            raise
    if conn is None:
        raise sqlite3.OperationalError("database is locked")
    try:
        yield conn
        in_trans = False
        try:
            in_trans = conn.in_transaction
        except (sqlite3.Error, AttributeError):
            pass
        if in_trans:
            try:
                conn.commit()
            except (sqlite3.Error, AttributeError):
                pass
    except BaseException:
        in_trans = False
        try:
            in_trans = conn.in_transaction
        except (sqlite3.Error, AttributeError):
            pass
        if in_trans:
            try:
                conn.rollback()
            except (sqlite3.Error, AttributeError):
                pass
        raise
    finally:
        try:
            conn.close()
        except (sqlite3.Error, AttributeError):
            pass
        if conn is not None:
            raw_conn = (
                conn
                if isinstance(conn, sqlite3.Connection)
                else getattr(conn, "_conn", None)
            )
            if raw_conn is not None:
                with _open_connections_lock:
                    _open_connections.discard(raw_conn)


@contextmanager
def write_db() -> Iterator[sqlite3.Connection]:
    """Open a write transaction early to serialize check-then-write business rules."""
    import sto_crm.database
    with sto_crm.database.db(readonly=False) as conn:
        max_retries = 5
        base_delay = 0.05
        for attempt in range(max_retries):
            try:
                conn.execute("BEGIN IMMEDIATE")
                break
            except sqlite3.OperationalError as exc:
                if "locked" in str(exc).lower() and attempt < max_retries - 1:
                    time.sleep(_locked_retry_delay(attempt, base_delay))
                    continue
                raise
        yield conn
