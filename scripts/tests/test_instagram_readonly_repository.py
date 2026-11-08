"""Read-only discovery uses temporary stores exclusively."""
import sqlite3
from unittest.mock import patch

import pytest

from backend.repositories.sqlite_trend_intelligence_repository import (
    SQLiteTrendIntelligenceReadOnlyLookup, SQLiteTrendIntelligenceRepository,
)
from backend.trend_intelligence.service import TrendIntelligenceService


@pytest.fixture
def store(tmp_path):
    path = tmp_path / 'config #%.db'
    repository = SQLiteTrendIntelligenceRepository(path)
    service = TrendIntelligenceService(repository)
    service.ensure_schema()
    service.create_source(code='IG_TEST', name='Test', source_type='SOCIAL', collection_mode='SELENIUM')
    service.create_domain(code='TEST', name='Test')
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE config_global (key TEXT PRIMARY KEY, value TEXT)')
    return path, repository


def test_missing_database_remains_missing(tmp_path):
    path = tmp_path / 'missing.db'
    lookup = SQLiteTrendIntelligenceReadOnlyLookup(path)
    assert lookup.get_config('test') is None
    assert lookup.get_source_by_code('test') is None
    assert lookup.get_domain_by_code('test') is None
    assert not path.exists()
    assert list(tmp_path.iterdir()) == []


def test_missing_tables_do_not_migrate(tmp_path):
    path = tmp_path / 'empty.db'
    sqlite3.connect(path).close()
    before = path.read_bytes()
    lookup = SQLiteTrendIntelligenceReadOnlyLookup(path)
    with patch.object(SQLiteTrendIntelligenceRepository, 'ensure_schema', side_effect=AssertionError):
        assert lookup.get_config('test') is None
        assert lookup.get_source_by_code('test') is None
        assert lookup.get_domain_by_code('test') is None
    assert path.read_bytes() == before


def test_existing_lookups_preserve_schema_and_bytes(store):
    path, _ = store
    with sqlite3.connect(path) as conn:
        conn.execute('INSERT INTO config_global VALUES (?, ?)', ('test', 'value'))
        schema = conn.execute('SELECT * FROM sqlite_master').fetchall()
    before = path.read_bytes()
    lookup = SQLiteTrendIntelligenceReadOnlyLookup(path)
    assert lookup.get_source_by_code('IG_TEST').code == 'IG_TEST'
    assert lookup.get_domain_by_code('TEST').code == 'TEST'
    assert lookup.get_config('test') == 'value'
    assert lookup.get_source_by_code('missing') is None
    assert lookup.get_domain_by_code('missing') is None
    with sqlite3.connect(path) as conn:
        assert conn.execute('SELECT * FROM sqlite_master').fetchall() == schema
    assert path.read_bytes() == before


def test_connection_is_enforced_readonly(store):
    path, _ = store
    connect = sqlite3.connect
    def checked(*args, **kwargs):
        assert args[0].endswith('?mode=ro') and kwargs['uri'] is True
        conn = connect(*args, **kwargs)
        with pytest.raises(sqlite3.OperationalError, match='readonly'):
            conn.execute('CREATE TABLE forbidden (id INTEGER)')
        return conn
    with patch('backend.repositories.sqlite_trend_intelligence_repository.sqlite3.connect', side_effect=checked):
        assert SQLiteTrendIntelligenceReadOnlyLookup(path).get_source_by_code('IG_TEST')
