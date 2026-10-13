import inspect
import json
import os
import sqlite3
import stat
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from backend.repositories import instagram_collector_settings_repository as repository_module
from database.connection import get_existing_connection
from backend.repositories.instagram_collector_settings_repository import (
    SQLiteInstagramCollectorSettingsRepository,
    SettingsStoreUnavailable,
)
from backend.services.instagram_collector_configuration_service import SETTINGS_KEY
from backend.services.instagram_collector_control_service import InstagramCollectorControlService


def store(tmp_path, with_table=True):
    path = tmp_path / "config.db"
    conn = sqlite3.connect(path)
    if with_table:
        conn.execute("CREATE TABLE config_global (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("INSERT INTO config_global (key, value) VALUES ('OTHER', 'keep')")
    conn.commit()
    conn.close()
    return path


def rows(path):
    conn = sqlite3.connect(path)
    try:
        return dict(conn.execute("SELECT key, value FROM config_global").fetchall())
    finally:
        conn.close()


def schema(path):
    conn = sqlite3.connect(path)
    try:
        return sorted(conn.execute("SELECT type, name, sql FROM sqlite_master").fetchall())
    finally:
        conn.close()


def test_existing_store_upsert_and_repeated_save_updates_row(tmp_path):
    path = store(tmp_path)
    repository = SQLiteInstagramCollectorSettingsRepository(path)
    repository.save(SETTINGS_KEY, json.dumps(dict(enabled=False)))
    repository.save(SETTINGS_KEY, json.dumps(dict(enabled=True)))
    assert rows(path) == {"OTHER": "keep", SETTINGS_KEY: json.dumps(dict(enabled=True))}


def test_nonexistent_file_is_not_created(tmp_path):
    path = tmp_path / "missing.db"
    with pytest.raises(SettingsStoreUnavailable):
        SQLiteInstagramCollectorSettingsRepository(path).save(SETTINGS_KEY, "{}")
    assert not path.exists()
    assert list(tmp_path.iterdir()) == []


def test_missing_table_is_not_created(tmp_path):
    path = store(tmp_path, with_table=False)
    with pytest.raises(SettingsStoreUnavailable):
        SQLiteInstagramCollectorSettingsRepository(path).save(SETTINGS_KEY, "{}")
    assert schema(path) == []


def test_no_migration_side_effects(tmp_path):
    path = store(tmp_path)
    before = schema(path)
    SQLiteInstagramCollectorSettingsRepository(path).save(SETTINGS_KEY, "{}")
    assert schema(path) == before


@pytest.mark.parametrize("key, value", [
    ("", "{}"), (None, "{}"), (SETTINGS_KEY, None), (SETTINGS_KEY, "not json"), (SETTINGS_KEY, "[]"),
])
def test_invalid_key_value_contract_does_not_persist(tmp_path, key, value):
    path = store(tmp_path)
    with pytest.raises(ValueError):
        SQLiteInstagramCollectorSettingsRepository(path).save(key, value)
    assert rows(path) == {"OTHER": "keep"}


def test_failed_write_is_rolled_back(tmp_path):
    path = store(tmp_path)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TRIGGER reject BEFORE INSERT ON config_global WHEN NEW.key = 'BAD' "
                 "BEGIN SELECT RAISE(ABORT, 'rejected'); END")
    conn.commit()
    conn.close()
    with pytest.raises(sqlite3.DatabaseError):
        SQLiteInstagramCollectorSettingsRepository(path).save("BAD", "{}")
    assert rows(path) == {"OTHER": "keep"}
    SQLiteInstagramCollectorSettingsRepository(path).save(SETTINGS_KEY, "{}")
    assert rows(path)[SETTINGS_KEY] == "{}"


def test_read_only_file_fails_closed(tmp_path):
    path = store(tmp_path)
    os.chmod(path, stat.S_IREAD)
    try:
        with pytest.raises(sqlite3.DatabaseError):
            SQLiteInstagramCollectorSettingsRepository(path).save(SETTINGS_KEY, "{}")
    finally:
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
    assert rows(path) == {"OTHER": "keep"}


def test_uses_canonical_existing_connection_helper(tmp_path, monkeypatch):
    path = store(tmp_path)
    opened = []

    def spy(db_path=None, timeout=30):
        connection = get_existing_connection(db_path, timeout)
        opened.append((db_path, connection))
        return connection

    monkeypatch.setattr(repository_module, "get_existing_connection", spy)
    SQLiteInstagramCollectorSettingsRepository(path).save(SETTINGS_KEY, "{}")
    assert [db_path for db_path, _ in opened] == [path]
    source = inspect.getsource(repository_module)
    for forbidden in ("sqlite3.connect", "sqlite_master", "BEGIN IMMEDIATE", "CREATE ", "ALTER "):
        assert forbidden not in source


def test_missing_file_relies_on_open_not_stat(tmp_path, monkeypatch):
    path = tmp_path / "missing.db"

    def forbidden(*args, **kwargs):
        raise AssertionError("existence pre-check")

    monkeypatch.setattr(Path, "exists", forbidden)
    monkeypatch.setattr(Path, "is_file", forbidden)
    monkeypatch.setattr(os.path, "exists", forbidden)
    with pytest.raises(SettingsStoreUnavailable):
        SQLiteInstagramCollectorSettingsRepository(path).save(SETTINGS_KEY, "{}")
    monkeypatch.undo()
    assert list(tmp_path.iterdir()) == []


def test_malformed_data_rejected_before_db_access(tmp_path, monkeypatch):
    opener = Mock()
    monkeypatch.setattr(repository_module, "get_existing_connection", opener)
    for key, value in [("", "{}"), (SETTINGS_KEY, "[]"), (SETTINGS_KEY, "nope"), (SETTINGS_KEY, b"{}")]:
        with pytest.raises(ValueError):
            SQLiteInstagramCollectorSettingsRepository(tmp_path / "x.db").save(key, value)
    opener.assert_not_called()


@pytest.mark.parametrize("with_table", [True, False])
def test_connection_closed_on_success_and_failure(tmp_path, monkeypatch, with_table):
    path = store(tmp_path, with_table=with_table)
    opened = []

    def spy(db_path=None, timeout=30):
        opened.append(get_existing_connection(db_path, timeout))
        return opened[-1]

    monkeypatch.setattr(repository_module, "get_existing_connection", spy)
    try:
        SQLiteInstagramCollectorSettingsRepository(path).save(SETTINGS_KEY, "{}")
    except SettingsStoreUnavailable:
        assert not with_table
    with pytest.raises(sqlite3.ProgrammingError):
        opened[0].execute("SELECT 1")


def test_invalid_config_from_service_does_not_persist(tmp_path):
    path = store(tmp_path)
    value = dict(enabled=False, source_code="UNKNOWN", domain_code=None,
                 profile_key="it_instagram_collector", accounts=[])
    lookup = Mock(get_config=Mock(return_value=json.dumps(value)),
                  get_source_by_code=Mock(return_value=None), get_domain_by_code=Mock(return_value=None))
    service = InstagramCollectorControlService(
        lookup=lookup, repository=Mock(), runtime_factory=Mock(),
        save_setting=SQLiteInstagramCollectorSettingsRepository(path).save,
    )
    for enabled, accounts, limit in [(False, ["bad/account"], 2), (False, ["ok"], 0), (True, ["ok"], 2)]:
        with pytest.raises(ValueError):
            service.save(enabled, accounts, limit)
    assert rows(path) == {"OTHER": "keep"}
    service.save(False, ["ok"], 2)
    assert json.loads(rows(path)[SETTINGS_KEY])["accounts"] == [dict(account="ok", limit=2)]
    service.runtime_factory.assert_not_called()


def test_composition_uses_repository_without_touching_database(tmp_path, monkeypatch):
    import backend.services.config_service as config_service
    from backend.services import instagram_collector_control_service as module

    path = tmp_path / "absent.db"
    monkeypatch.setattr(config_service, "DB_PATH", path)
    service = module.create_crm_instagram_control()
    assert isinstance(service.save_setting.__self__, SQLiteInstagramCollectorSettingsRepository)
    with pytest.raises(SettingsStoreUnavailable):
        service.save_setting(SETTINGS_KEY, "{}")
    assert not path.exists()
    assert not hasattr(module, "sqlite3")
