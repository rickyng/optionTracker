"""Async DBAPI wrapper for libsql_experimental (Turso).

Provides a self-contained SQLAlchemy async dialect for Turso/libSQL without
depending on the broken sqlalchemy-libsql package.  Uses await_only() +
asyncio.to_thread() to run blocking I/O in a thread pool, satisfying
SQLAlchemy's greenlet machinery.

Thread safety: each connection is checked out exclusively by NullPool, so
concurrent access within a single connection is not expected.
"""

import asyncio
import contextlib
import logging
import os
import urllib.parse

import libsql_experimental as _sync
from sqlalchemy import util as sa_util
from sqlalchemy.dialects.sqlite.pysqlite import SQLiteDialect_pysqlite
from sqlalchemy.util._concurrency_py3k import await_only

_logger = logging.getLogger(__name__)

# Re-export DBAPI attributes that SQLAlchemy's SQLite dialect expects
paramstyle = _sync.paramstyle
sqlite_version_info = getattr(_sync, "sqlite_version_info", (3, 39, 0))
Error = _sync.Error
LEGACY_TRANSACTION_CONTROL = getattr(_sync, "LEGACY_TRANSACTION_CONTROL", False)

# Transient Turso errors that resolve on retry with a fresh connection
_TRANSIENT_SUBSTRS = ("stream not found", "Hrana")


def _is_transient(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(s in msg for s in _TRANSIENT_SUBSTRS)


def connect(database, **kwargs):
    """Create an async-compatible connection (called inside a greenlet)."""
    sync_conn = await_only(asyncio.to_thread(_sync.connect, database, **kwargs))
    return _AsyncConn(sync_conn, connect_args=(database, kwargs))


class _AsyncConn:
    """Wraps a sync libsql_experimental.Connection for greenlet compatibility."""

    def __init__(self, conn, connect_args=None):
        self._conn = conn
        self._connect_args = connect_args  # (database, kwargs) for reconnection

    def cursor(self):
        return _AsyncCursor(self._conn.cursor(), self)

    def commit(self):
        for attempt in range(3):
            try:
                await_only(asyncio.to_thread(self._conn.commit))
                return
            except Exception as exc:
                if not _is_transient(exc) or attempt >= 2:
                    raise
                _logger.warning("Transient Turso error on commit, attempt %d/3: %s", attempt + 1, exc)
                try:
                    self._reconnect()
                except Exception as recon_exc:
                    _logger.warning("Reconnect failed on attempt %d: %s", attempt + 1, recon_exc)

    def _reconnect(self):
        """Replace the dead underlying connection with a fresh one."""
        if not self._connect_args:
            _logger.warning("Cannot reconnect: no connect_args stored")
            return
        database, kwargs = self._connect_args
        with contextlib.suppress(Exception):
            await_only(asyncio.to_thread(self._conn.close))
        # Brief backoff before reconnecting to let Turso clean up the dead stream
        await_only(asyncio.sleep(0.5))
        self._conn = await_only(asyncio.to_thread(_sync.connect, database, **kwargs))
        _logger.info("Reconnected to Turso after transient error")

    def rollback(self):
        try:
            await_only(asyncio.to_thread(self._conn.rollback))
        except Exception as exc:
            if _is_transient(exc):
                _logger.warning("Transient Turso error on rollback: %s", exc)
                try:
                    self._reconnect()
                except Exception as recon_exc:
                    _logger.warning("Reconnect failed after rollback error: %s", recon_exc)
            else:
                raise

    def close(self):
        await_only(asyncio.to_thread(self._conn.close))

    @property
    def isolation_level(self):
        return self._conn.isolation_level

    @isolation_level.setter
    def isolation_level(self, value):
        with contextlib.suppress(AttributeError):
            self._conn.isolation_level = value

    def execute(self, sql, params=None):
        raw_cursor = self._conn.cursor()
        try:
            await_only(asyncio.to_thread(raw_cursor.execute, sql, params or ()))
        except Exception as exc:
            if not _is_transient(exc):
                raise
            _logger.warning("Transient Turso error on conn execute: %s", exc)
            self._reconnect()
            raw_cursor = self._conn.cursor()
            await_only(asyncio.to_thread(raw_cursor.execute, sql, params or ()))
        return _AsyncCursor(raw_cursor, conn=self)

    def executemany(self, sql, params_seq):
        raw_cursor = self._conn.cursor()
        try:
            await_only(asyncio.to_thread(raw_cursor.executemany, sql, params_seq))
        except Exception as exc:
            if not _is_transient(exc):
                raise
            _logger.warning("Transient Turso error on conn executemany: %s", exc)
            self._reconnect()
            raw_cursor = self._conn.cursor()
            await_only(asyncio.to_thread(raw_cursor.executemany, sql, params_seq))
        return _AsyncCursor(raw_cursor, conn=self)


class _AsyncCursor:
    """Wraps a sync libsql_experimental.Cursor for greenlet compatibility."""

    def __init__(self, cursor, conn=None):
        self._cursor = cursor
        self._conn = conn

    @property
    def description(self):
        return self._cursor.description

    @property
    def rowcount(self):
        return self._cursor.rowcount

    @property
    def lastrowid(self):
        return self._cursor.lastrowid

    def _retry_cursor_op(self, op, *args):
        """Run a cursor operation (execute/executemany) with transient retry."""
        for attempt in range(3):
            try:
                await_only(asyncio.to_thread(getattr(self._cursor, op), *args))
                return
            except Exception as exc:
                if not _is_transient(exc) or attempt >= 2:
                    raise
                _logger.warning("Transient Turso error on cursor %s, attempt %d/3: %s", op, attempt + 1, exc)
                try:
                    self._conn._reconnect()
                    self._cursor = self._conn._conn.cursor()
                except Exception as recon_exc:
                    _logger.warning("Reconnect failed on cursor attempt %d: %s", attempt + 1, recon_exc)
                    # Get a fresh cursor from whatever connection state we have
                    if self._conn and self._conn._conn:
                        self._cursor = self._conn._conn.cursor()

    def execute(self, sql, params=None):
        self._retry_cursor_op("execute", sql, params or ())
        return self

    def executemany(self, sql, params_seq):
        self._retry_cursor_op("executemany", sql, params_seq)
        return self

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchmany(self, size=None):
        return self._cursor.fetchmany(size)

    def fetchall(self):
        return self._cursor.fetchall()

    def close(self):
        self._cursor.close()

    async def _async_soft_close(self):
        # Do NOT close the underlying cursor. SQLAlchemy's _ensure_sync_result
        # calls this BEFORE returning the result to the caller. The cursor's
        # internal result buffer must stay alive for result iteration. Cleanup
        # happens later when CursorResult._soft_close() is called by the framework.
        pass

    def setinputsizes(self, sizes):
        pass

    def setoutputsize(self, size, column=None):
        pass

    @property
    def arraysize(self):
        return self._cursor.arraysize

    @arraysize.setter
    def arraysize(self, value):
        self._cursor.arraysize = value

    @property
    def connection(self):
        return self._conn


# ---------------------------------------------------------------------------
# Self-contained SQLAlchemy dialect (no sqlalchemy-libsql dependency)
# ---------------------------------------------------------------------------


def _build_connection_url(url, query, secure):
    """Build the libsql connection URL from SQLAlchemy URL components."""
    query_str = urllib.parse.urlencode(sorted(query.items()))
    scheme = "https" if secure else "http"

    if url.username and url.password:
        netloc = f"{url.username}:{url.password}@{url.host}"
    elif url.username:
        netloc = f"{url.username}@{url.host}"
    else:
        netloc = url.host

    if url.port:
        netloc += f":{url.port}"

    return urllib.parse.urlunsplit((scheme, netloc, url.database or "", query_str, ""))


class AsyncLibSQLDialect(SQLiteDialect_pysqlite):
    """Self-contained async libsql dialect for Turso.

    Inherits from SQLiteDialect_pysqlite (like sqlalchemy-libsql did)
    but uses our own async DBAPI wrapper and inlined URL building.
    """

    is_async = True
    driver = "libsql_async"
    supports_statement_cache = SQLiteDialect_pysqlite.supports_statement_cache

    @classmethod
    def import_dbapi(cls):
        from app import db_libsql_async

        return db_libsql_async

    def on_connect(self):
        # Skip pysqlite connection hooks that expect raw sqlite3 connections
        return None

    def create_connect_args(self, url):
        """Build connection args from URL — handles both local and remote libsql."""
        pysqlite_args = (
            ("uri", bool),
            ("timeout", float),
            ("isolation_level", str),
            ("detect_types", int),
            ("check_same_thread", bool),
            ("cached_statements", int),
            ("secure", bool),
        )
        opts = url.query
        libsql_opts = {}
        for key, type_ in pysqlite_args:
            sa_util.coerce_kw_type(opts, key, type_, dest=libsql_opts)

        if url.host:
            libsql_opts["uri"] = True

        if libsql_opts.get("uri", False):
            uri_opts = dict(opts)
            for key, _type in pysqlite_args:
                uri_opts.pop(key, None)

            secure = libsql_opts.pop("secure", False)
            connect_url = _build_connection_url(url, uri_opts, secure)
        else:
            connect_url = url.database or ":memory:"
            if connect_url != ":memory:":
                connect_url = os.path.abspath(connect_url)

        libsql_opts.setdefault("check_same_thread", not self._is_url_file_db(url))

        return ([connect_url], libsql_opts)


dialect = AsyncLibSQLDialect
