"""Tests for database.py URL validation and engine building."""

import pytest

from app.database import _convert_db_url, _validate_db_url

# --- _validate_db_url ---


def test_validate_db_url_accepts_libsql():
    _validate_db_url("libsql://my-db-my-org.turso.io")


def test_validate_db_url_accepts_libsql_ws():
    _validate_db_url("libsql+ws://my-db-my-org.turso.io")


def test_validate_db_url_accepts_libsql_http():
    _validate_db_url("libsql+http://my-db-my-org.turso.io")


def test_validate_db_url_rejects_no_host():
    with pytest.raises(ValueError, match="no valid hostname"):
        _validate_db_url("libsql://")


def test_validate_db_url_rejects_no_dot_in_host():
    with pytest.raises(ValueError, match="no valid hostname"):
        _validate_db_url("libsql://localhost")


def test_validate_db_url_rejects_bad_scheme():
    with pytest.raises(ValueError, match="must start with"):
        _validate_db_url("postgres://my-db.turso.io")


# --- _convert_db_url ---


def test_convert_db_url_libsql():
    url = _convert_db_url("libsql://my-db.turso.io")
    assert url == "sqlite+libsql_async://my-db.turso.io?secure=true"


def test_convert_db_url_preserves_existing_secure():
    url = _convert_db_url("libsql://my-db.turso.io?secure=false")
    assert url == "sqlite+libsql_async://my-db.turso.io?secure=false"


def test_convert_db_url_libsql_ws():
    url = _convert_db_url("libsql+ws://my-db.turso.io")
    assert url == "sqlite+libsql_async://my-db.turso.io?secure=true"


def test_convert_db_url_libsql_http():
    url = _convert_db_url("libsql+http://my-db.turso.io")
    assert url == "sqlite+libsql_async://my-db.turso.io?secure=true"


def test_convert_db_url_with_existing_query():
    url = _convert_db_url("libsql://my-db.turso.io?foo=bar")
    assert url == "sqlite+libsql_async://my-db.turso.io?foo=bar&secure=true"
