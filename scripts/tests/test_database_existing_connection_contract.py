import inspect
import os
import sqlite3
from pathlib import Path

import pytest

import database.connection as connection_module
from database.connection import get_connection, get_existing_connection, initialize_database


def existing_db(tmp_path, name="existing.db"):
    path = tmp_path / name
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, label TEXT)")
    conn.execute("INSERT INTO sample (label) VALUES ('kept')")
    conn.commit()
    conn.close()
    return path


def schema(path):
    conn = sqlite3.connect(path)
    try:
        return sorted(conn.execute("SELECT type, name, sql FROM sqlite_master").fetchall())
    finally:
        conn.close()


def test_signature_contract():
    params = inspect.signature(get_existing_connection).parameters
    assert list(params) == ["db_path", "timeout"]
    assert params["db_path"].default is None
    assert params["timeout"].default == 30


def test_missing_db_is_never_created(tmp_path):
    path = tmp_path / "missing.db"
    with pytest.raises(sqlite3.OperationalError):
        get_existing_connection(path)
    assert list(tmp_path.iterdir()) == []


def test_missing_db_does_not_use_existence_precheck(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("existence pre-check")

    monkeypatch.setattr(Path, "exists", forbidden)
    monkeypatch.setattr(Path, "is_file", forbidden)
    monkeypatch.setattr(os.path, "exists", forbidden)
    with pytest.raises(sqlite3.OperationalError):
        get_existing_connection(tmp_path / "missing.db")
    monkeypatch.undo()
    assert list(tmp_path.iterdir()) == []


def test_existing_db_connects_with_row_factory_and_read_write(tmp_path):
    path = existing_db(tmp_path)
    conn = get_existing_connection(str(path))
    try:
        assert conn.row_factory is sqlite3.Row
        row = conn.execute("SELECT label FROM sample").fetchone()
        assert row["label"] == "kept"
        conn.execute("INSERT INTO sample (label) VALUES ('new')")
        conn.commit()
    finally:
        conn.close()
    conn = sqlite3.connect(path)
    try:
        assert [r[0] for r in conn.execute("SELECT label FROM sample ORDER BY id")] == ["kept", "new"]
    finally:
        conn.close()


def test_opens_with_uri_rw_mode_and_timeout(tmp_path, monkeypatch):
    path = existing_db(tmp_path)
    calls = []
    real_connect = sqlite3.connect

    def spy(*args, **kwargs):
        calls.append((args, kwargs))
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(connection_module.sqlite3, "connect", spy)
    get_existing_connection(path).close()
    get_existing_connection(path, timeout=5).close()
    (uri,), kwargs = calls[0]
    assert uri.startswith("file:") and uri.endswith("?mode=rw")
    assert kwargs == dict(uri=True, timeout=30)
    assert calls[1][1]["timeout"] == 5


def test_default_path_uses_module_db_path(tmp_path, monkeypatch):
    path = existing_db(tmp_path, "default.db")
    monkeypatch.setattr(connection_module, "DB_PATH", str(path))
    conn = connection_module.get_existing_connection()
    try:
        assert conn.execute("SELECT label FROM sample").fetchone()["label"] == "kept"
    finally:
        conn.close()


def test_default_path_missing_is_not_created(tmp_path, monkeypatch):
    path = tmp_path / "default-missing.db"
    monkeypatch.setattr(connection_module, "DB_PATH", str(path))
    with pytest.raises(sqlite3.OperationalError):
        connection_module.get_existing_connection()
    assert not path.exists()


def test_no_schema_initialization_or_migration(tmp_path):
    path = tmp_path / "empty.db"
    sqlite3.connect(path).close()
    before = schema(path)
    get_existing_connection(path).close()
    assert schema(path) == before == []
    path = existing_db(tmp_path)
    before = schema(path)
    get_existing_connection(path).close()
    assert schema(path) == before


def test_get_connection_backwards_compatible(tmp_path, monkeypatch):
    path = tmp_path / "legacy.db"
    monkeypatch.setattr(connection_module, "DB_PATH", str(path))
    conn = get_connection()
    try:
        assert conn.row_factory is sqlite3.Row
    finally:
        conn.close()
    # Legacy behaviour intentionally preserved: plain connect creates the file.
    assert path.exists()


def test_initialize_database_backwards_compatible(tmp_path, monkeypatch):
    path = tmp_path / "init.db"
    monkeypatch.setattr(connection_module, "DB_PATH", str(path))
    initialize_database()
    assert schema(path) != []
