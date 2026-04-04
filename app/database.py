import contextlib
from pathlib import Path

from sqlalchemy.dialects import registry
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.config import settings

# Register the self-contained async libsql dialect. This must happen before
# create_async_engine is called. The class lives in db_libsql_async to avoid
# circular imports (SQLAlchemy lazy-loads dialect classes via this registry).
registry.register("sqlite.libsql_async", "app.db_libsql_async", "AsyncLibSQLDialect")


def _validate_db_url(url: str) -> None:
    """Basic validation for Turso/libSQL URLs to catch misconfiguration early."""
    for prefix in ("libsql://", "libsql+ws://", "libsql+http://"):
        if url.startswith(prefix):
            host = url[len(prefix) :].split("/")[0].split("?")[0]
            if not host or "." not in host:
                raise ValueError(
                    f"IBKR_DB_URL has no valid hostname: {url!r}  Expected format: libsql://<db-name>-<org>.turso.io"
                )
            return
    raise ValueError(f"IBKR_DB_URL must start with libsql://, libsql+ws://, or libsql+http://, got: {url!r}")


def _convert_db_url(db_url: str) -> str:
    """Convert a libsql:// URL to the sqlalchemy-compatible sqlite+libsql_async:// form."""
    _validate_db_url(db_url)
    # Strip any +ws or +http qualifier — the dialect handles secure/https
    if db_url.startswith("libsql+ws://"):
        url = "sqlite+libsql_async://" + db_url[len("libsql+ws://") :]
    elif db_url.startswith("libsql+http://"):
        url = "sqlite+libsql_async://" + db_url[len("libsql+http://") :]
    else:  # libsql://
        url = "sqlite+libsql_async://" + db_url[len("libsql://") :]
    # The dialect uses `secure` query param to select https vs http.
    # Without it, it defaults to http and Turso returns 308 Permanent Redirect.
    if "secure=" not in url:
        url += ("&" if "?" in url else "?") + "secure=true"
    return url


def _build_engine():
    """Create the async engine — Turso/libSQL if db_url is set, else local SQLite."""
    db_url = settings.db_url.strip()
    if db_url:
        connect_args = {}
        if settings.db_auth_token:
            connect_args["auth_token"] = settings.db_auth_token
        url = _convert_db_url(db_url)
        # NullPool: each checkout opens a fresh connection.  Turso uses stateless
        # HTTP/WebSocket and handles connection pooling server-side, so a local
        # pool adds overhead without benefit.
        return create_async_engine(url, connect_args=connect_args, poolclass=NullPool, echo=False)

    # Local SQLite via aiosqlite
    path = Path(settings.db_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    return create_async_engine(f"sqlite+aiosqlite:///{path}", echo=False)


engine = _build_engine()
async_session = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db() -> None:
    # Ensure all models are imported so Base.metadata knows about every table
    import app.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Add multiplier column to existing tables that lack it
        await _migrate_add_multiplier(conn)
        # Add user_id column to accounts for per-user data isolation
        await _migrate_add_user_id_to_accounts(conn)


async def _migrate_add_multiplier(conn) -> None:
    """Add multiplier column to open_options if it doesn't exist (existing DBs).

    Uses contextlib.suppress because PRAGMA-based checks are unreliable
    across the async wrapper. SQLite/libSQL-specific.
    """
    from sqlalchemy import text

    with contextlib.suppress(Exception):
        await conn.execute(text("ALTER TABLE open_options ADD COLUMN multiplier INTEGER DEFAULT 100 NOT NULL"))


async def _migrate_add_user_id_to_accounts(conn) -> None:
    """Add user_id column to accounts if it doesn't exist (existing DBs).

    Uses contextlib.suppress because PRAGMA-based checks are unreliable
    across the async wrapper. SQLite/libSQL-specific.
    """
    from sqlalchemy import text

    with contextlib.suppress(Exception):
        await conn.execute(
            text("ALTER TABLE accounts ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE SET NULL")
        )
