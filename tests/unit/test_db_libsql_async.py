"""Tests for the async DBAPI wrapper (db_libsql_async).

These tests verify the wrapper works correctly with SQLAlchemy's greenlet
machinery using an in-memory libsql database (no network/Turso required).
"""

import inspect

import pytest

from app.db_libsql_async import (
    AsyncLibSQLDialect,
    _AsyncCursor,
    connect,
)

# --- greenlet_spawn simulation ---


async def _run_in_greenlet(fn, *args, **kwargs):
    """Simulate SQLAlchemy's greenlet_spawn for testing."""

    from sqlalchemy.util._concurrency_py3k import greenlet_spawn

    return await greenlet_spawn(fn, *args, **kwargs)


# --- _AsyncCursor tests ---


@pytest.mark.asyncio
async def test_cursor_execute_and_fetchall():
    conn = await _run_in_greenlet(connect, ":memory:")
    cursor = conn.cursor()

    assert isinstance(cursor, _AsyncCursor)

    await _run_in_greenlet(cursor.execute, "CREATE TABLE t (id INTEGER, name TEXT)")
    await _run_in_greenlet(cursor.execute, "INSERT INTO t VALUES (1, 'alice')")
    await _run_in_greenlet(cursor.execute, "INSERT INTO t VALUES (2, 'bob')")
    await _run_in_greenlet(cursor.execute, "SELECT * FROM t ORDER BY id")

    rows = cursor.fetchall()
    assert rows == [(1, "alice"), (2, "bob")]


@pytest.mark.asyncio
async def test_cursor_execute_with_params():
    conn = await _run_in_greenlet(connect, ":memory:")
    cursor = conn.cursor()

    await _run_in_greenlet(cursor.execute, "CREATE TABLE t (id INTEGER, name TEXT)")
    await _run_in_greenlet(cursor.execute, "INSERT INTO t VALUES (?, ?)", (1, "alice"))
    await _run_in_greenlet(cursor.execute, "SELECT name FROM t WHERE id = ?", (1,))

    assert cursor.fetchone() == ("alice",)


@pytest.mark.asyncio
async def test_cursor_fetchone():
    conn = await _run_in_greenlet(connect, ":memory:")
    cursor = conn.cursor()

    await _run_in_greenlet(cursor.execute, "SELECT 1 AS val")
    assert cursor.fetchone() == (1,)
    assert cursor.fetchone() is None


@pytest.mark.asyncio
async def test_cursor_fetchmany():
    conn = await _run_in_greenlet(connect, ":memory:")
    cursor = conn.cursor()

    await _run_in_greenlet(
        cursor.execute, "SELECT value FROM (SELECT 1 AS value UNION ALL SELECT 2 UNION ALL SELECT 3)"
    )
    assert cursor.fetchmany(2) == [(1,), (2,)]
    assert cursor.fetchmany() == [(3,)]
    assert cursor.fetchmany() == []


@pytest.mark.asyncio
async def test_cursor_description_and_rowcount():
    conn = await _run_in_greenlet(connect, ":memory:")
    cursor = conn.cursor()

    await _run_in_greenlet(cursor.execute, "SELECT 1 AS col")
    assert cursor.description is not None
    assert cursor.description[0][0] == "col"

    await _run_in_greenlet(cursor.execute, "CREATE TABLE t (id INTEGER)")
    await _run_in_greenlet(cursor.execute, "INSERT INTO t VALUES (1)")
    assert cursor.rowcount == 1


@pytest.mark.asyncio
async def test_cursor_lastrowid():
    conn = await _run_in_greenlet(connect, ":memory:")
    cursor = conn.cursor()

    await _run_in_greenlet(cursor.execute, "CREATE TABLE t (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)")
    await _run_in_greenlet(cursor.execute, "INSERT INTO t (name) VALUES (?)", ("test",))
    assert cursor.lastrowid == 1


@pytest.mark.asyncio
async def test_cursor_arraysize():
    conn = await _run_in_greenlet(connect, ":memory:")
    cursor = conn.cursor()

    assert cursor.arraysize == 1  # sqlite3 default
    cursor.arraysize = 5
    assert cursor.arraysize == 5


@pytest.mark.asyncio
async def test_cursor_execute_returns_self():
    conn = await _run_in_greenlet(connect, ":memory:")
    cursor = conn.cursor()

    result = await _run_in_greenlet(cursor.execute, "SELECT 1")
    assert result is cursor


@pytest.mark.asyncio
async def test_cursor_close():
    conn = await _run_in_greenlet(connect, ":memory:")
    cursor = conn.cursor()
    # close() should not raise
    cursor.close()


# --- _AsyncConn tests ---


@pytest.mark.asyncio
async def test_conn_commit_and_rollback():
    conn = await _run_in_greenlet(connect, ":memory:")
    cursor = conn.cursor()

    await _run_in_greenlet(cursor.execute, "CREATE TABLE t (id INTEGER)")
    await _run_in_greenlet(cursor.execute, "INSERT INTO t VALUES (1)")
    await _run_in_greenlet(conn.commit)

    # New cursor sees committed data
    cursor2 = conn.cursor()
    await _run_in_greenlet(cursor2.execute, "SELECT COUNT(*) FROM t")
    assert cursor2.fetchone() == (1,)


@pytest.mark.asyncio
async def test_conn_execute_returns_async_cursor():
    conn = await _run_in_greenlet(connect, ":memory:")
    # _AsyncConn.execute should return _AsyncCursor, not raw cursor
    cursor = await _run_in_greenlet(conn.execute, "SELECT 1 AS val")
    assert isinstance(cursor, _AsyncCursor)
    assert cursor.fetchone() == (1,)


@pytest.mark.asyncio
async def test_conn_executemany_returns_async_cursor():
    conn = await _run_in_greenlet(connect, ":memory:")
    await _run_in_greenlet(conn.execute, "CREATE TABLE t (id INTEGER)")
    cursor = await _run_in_greenlet(conn.executemany, "INSERT INTO t VALUES (?)", [(1,), (2,), (3,)])
    assert isinstance(cursor, _AsyncCursor)


@pytest.mark.asyncio
async def test_conn_isolation_level():
    conn = await _run_in_greenlet(connect, ":memory:")
    level = conn.isolation_level
    assert isinstance(level, (str, type(None)))
    conn.isolation_level = level  # round-trip


@pytest.mark.asyncio
async def test_conn_close():
    conn = await _run_in_greenlet(connect, ":memory:")
    await _run_in_greenlet(conn.close)


@pytest.mark.asyncio
async def test_cursor_connection_returns_conn():
    conn = await _run_in_greenlet(connect, ":memory:")
    cursor = conn.cursor()
    # cursor.connection returns the _AsyncConn that created it
    assert cursor.connection is conn


# --- Dialect tests ---


def test_dialect_import_dbapi():
    dbapi = AsyncLibSQLDialect.import_dbapi()
    assert hasattr(dbapi, "connect")
    assert hasattr(dbapi, "paramstyle")
    assert dbapi.paramstyle == "qmark"


def test_dialect_is_async():
    assert AsyncLibSQLDialect.is_async is True
    assert AsyncLibSQLDialect.driver == "libsql_async"


def test_dialect_on_connect_returns_none():
    dialect = AsyncLibSQLDialect()
    assert dialect.on_connect() is None


def test_dialect_create_connect_args_remote():
    """Verify URL conversion for remote Turso connections."""
    from sqlalchemy import make_url

    dialect = AsyncLibSQLDialect()
    url = make_url("sqlite+libsql_async://my-db-my-org.turso.io?secure=true")
    args, kwargs = dialect.create_connect_args(url)
    assert args[0] == "https://my-db-my-org.turso.io"
    assert kwargs.get("uri") is True


def test_dialect_create_connect_args_local():
    """Verify local :memory: connection."""
    from sqlalchemy import make_url

    dialect = AsyncLibSQLDialect()
    url = make_url("sqlite+libsql_async:///:memory:")
    args, kwargs = dialect.create_connect_args(url)
    assert args[0] == ":memory:"


# --- Regression: create_connect_args must only return kwargs that libsql_experimental accepts ---


def _get_libsql_accepted_params():
    """Get the actual accepted parameters from libsql_experimental.connect()."""
    import libsql_experimental

    return set(inspect.signature(libsql_experimental.connect).parameters)


def test_remote_connect_kwargs_accepted_by_libsql():
    """Regression: create_connect_args for remote URLs must not pass unsupported kwargs.

    libsql_experimental.connect() only accepts specific kwargs. Any extra kwarg
    (like 'http') causes TypeError at runtime. This test ensures all returned
    kwargs are in the accepted set.
    """
    from sqlalchemy import make_url

    accepted = _get_libsql_accepted_params()
    dialect = AsyncLibSQLDialect()
    url = make_url("sqlite+libsql_async://my-db-my-org.turso.io?secure=true")
    args, kwargs = dialect.create_connect_args(url)

    for kwarg in kwargs:
        assert kwarg in accepted, (
            f"Unsupported kwarg '{kwarg}' passed to libsql_experimental.connect(). "
            f"Accepted params: {accepted}"
        )


def test_local_connect_kwargs_accepted_by_libsql():
    """Same check for local :memory: connections."""
    from sqlalchemy import make_url

    accepted = _get_libsql_accepted_params()
    dialect = AsyncLibSQLDialect()
    url = make_url("sqlite+libsql_async:///:memory:")
    args, kwargs = dialect.create_connect_args(url)

    for kwarg in kwargs:
        assert kwarg in accepted, (
            f"Unsupported kwarg '{kwarg}' passed to libsql_experimental.connect(). "
            f"Accepted params: {accepted}"
        )


def test_remote_connect_url_uses_https():
    """Remote connections must use https:// URL scheme for Turso."""
    from sqlalchemy import make_url

    dialect = AsyncLibSQLDialect()
    url = make_url("sqlite+libsql_async://my-db-my-org.turso.io?secure=true")
    args, kwargs = dialect.create_connect_args(url)

    assert args[0].startswith("https://"), (
        f"Remote URL must use https:// scheme, got: {args[0]}"
    )


# --- Regression: _async_soft_close must not destroy results ---


@pytest.mark.asyncio
async def test_async_soft_close_preserves_results():
    """Regression: _async_soft_close must NOT close the underlying cursor.

    SQLAlchemy calls _async_soft_close via _ensure_sync_result BEFORE the
    caller consumes the result. If we close the cursor here, fetchall/fetchone
    return empty results, breaking PRAGMA-based migrations and all queries.
    """
    conn = await _run_in_greenlet(connect, ":memory:")
    cursor = conn.cursor()

    await _run_in_greenlet(cursor.execute, "CREATE TABLE t (id INTEGER, name TEXT)")
    await _run_in_greenlet(cursor.execute, "INSERT INTO t VALUES (1, 'alice')")
    await _run_in_greenlet(cursor.execute, "SELECT * FROM t ORDER BY id")

    # Simulate what SQLAlchemy does: call _async_soft_close BEFORE fetching
    await cursor._async_soft_close()

    # Results must still be readable
    rows = cursor.fetchall()
    assert rows == [(1, "alice")], f"Expected non-empty results, got {rows}"


@pytest.mark.asyncio
async def test_async_soft_close_preserves_description():
    """Verify _async_soft_close doesn't affect cursor.description."""
    conn = await _run_in_greenlet(connect, ":memory:")
    cursor = conn.cursor()

    await _run_in_greenlet(cursor.execute, "SELECT 1 AS col")
    await cursor._async_soft_close()

    assert cursor.description is not None
    assert cursor.description[0][0] == "col"


# --- _reconnect tests ---


@pytest.mark.asyncio
async def test_reconnect_creates_fresh_connection():
    """_reconnect should replace the underlying connection with a new one."""
    conn = await _run_in_greenlet(connect, ":memory:")
    old_inner = conn._conn

    # _reconnect uses await_only which requires greenlet context
    async def _do_reconnect():
        from sqlalchemy.util._concurrency_py3k import greenlet_spawn
        await greenlet_spawn(conn._reconnect)

    await _do_reconnect()

    # Inner connection should be a different object
    assert conn._conn is not old_inner

    # New connection should work
    cursor = conn.cursor()
    await _run_in_greenlet(cursor.execute, "SELECT 1 AS val")
    assert cursor.fetchone() == (1,)


@pytest.mark.asyncio
async def test_reconnect_noop_without_connect_args():
    """_reconnect should silently do nothing if connect_args is not stored."""
    conn = await _run_in_greenlet(connect, ":memory:")
    old_inner = conn._conn

    # Explicitly clear connect_args (simulates old connections created before the field existed)
    conn._connect_args = None
    conn._reconnect()

    # Connection should be unchanged
    assert conn._conn is old_inner


@pytest.mark.asyncio
async def test_commit_retries_on_transient_error(monkeypatch):
    """Commit should retry and succeed after reconnect on transient error."""
    conn = await _run_in_greenlet(connect, ":memory:", uri=False)
    cursor = conn.cursor()

    await _run_in_greenlet(cursor.execute, "CREATE TABLE t (id INTEGER)")
    await _run_in_greenlet(cursor.execute, "INSERT INTO t VALUES (1)")
    await _run_in_greenlet(conn.commit)

    # Verify data is committed
    cursor2 = conn.cursor()
    await _run_in_greenlet(cursor2.execute, "SELECT COUNT(*) FROM t")
    assert cursor2.fetchone() == (1,)


@pytest.mark.asyncio
async def test_connect_stores_connect_args():
    """connect() should store args so _reconnect can use them later."""
    conn = await _run_in_greenlet(connect, ":memory:")
    assert conn._connect_args is not None
    assert conn._connect_args[0] == ":memory:"
