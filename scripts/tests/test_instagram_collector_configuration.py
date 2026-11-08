"""Offline binding and enabled CRM worker integration."""
from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from scripts.tests.test_instagram_readonly_repository import store as unregistered_store
from backend.repositories.sqlite_trend_intelligence_repository import SQLiteTrendIntelligenceReadOnlyLookup
from backend.services.instagram_collector_configuration_service import (
    InstagramCollectorConfigurationService, InvalidInstagramConfiguration, SETTINGS_KEY,
    create_crm_instagram_runtime,
)
from backend.services.instagram_collector_runtime_service import InstagramCollectorRuntimeService
from backend.trend_intelligence.sources.instagram import InstagramRawObservation


@pytest.fixture
def store(unregistered_store):
    path, repository = unregistered_store
    # Existing test registry has no provider; explicitly register provenance.
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE ti_sources SET provider = ?", ('Instagram',))
    return path, repository


def settings(**changes):
    value = dict(enabled=True, source_code='IG_TEST', domain_code='TEST',
                 accounts=[dict(account='test_account', limit=2)],
                 profile_key='it_instagram_collector', headless=True)
    value.update(changes)
    return value


def save(path, value):
    with sqlite3.connect(path) as conn:
        conn.execute('INSERT OR REPLACE INTO config_global VALUES (?, ?)', (SETTINGS_KEY, json.dumps(value)))


@pytest.mark.parametrize('changes', [
    {'source_code': None}, {'source_code': 'missing'}, {'source_code': 4},
    {'domain_code': 'missing'}, {'domain_code': ''}, {'enabled': 1},
    {'headless': 'false'}, {'profile_key': '../bad'}, {'accounts': []},
    {'accounts': [{'account': 'test', 'limit': True}]},
    {'accounts': [{'account': 'test', 'limit': 0}]},
    {'accounts': [{'account': '../bad', 'limit': 2}]},
])
def test_invalid_configuration(store, changes):
    path, _ = store
    save(path, settings(**changes))
    with pytest.raises(InvalidInstagramConfiguration):
        InstagramCollectorConfigurationService(SQLiteTrendIntelligenceReadOnlyLookup(path)).load()


@pytest.mark.parametrize('value,status', [(None, 'NOT_CONFIGURED'), ({}, 'DISABLED'),
    ({'enabled': False}, 'DISABLED'), ([], 'NOT_CONFIGURED'),
    ('{invalid', 'NOT_CONFIGURED'), (settings(enabled='true'), 'NOT_CONFIGURED'),
    (settings(headless='false'), 'NOT_CONFIGURED'),
    (settings(accounts=[{'account': 'test', 'limit': True}]), 'NOT_CONFIGURED'),
    (settings(source_code='missing'), 'NOT_CONFIGURED')])
def test_unconfigured_or_disabled_never_opens_chrome(store, value, status):
    path, _ = store
    if value is not None:
        save(path, value)
    before = path.read_bytes()
    factory = Mock()
    runtime = InstagramCollectorRuntimeService(
        configuration_service=InstagramCollectorConfigurationService(SQLiteTrendIntelligenceReadOnlyLookup(path)),
        collector_factory=factory)
    try:
        runtime.start().result(5)
        assert runtime.snapshot.status == status
        factory.assert_not_called()
        assert path.read_bytes() == before
    finally:
        runtime.close().result(5)


def test_enabled_composition_background_once_with_real_ingestion(store):
    path, repository = store
    save(path, settings())
    before = path.read_bytes()
    with sqlite3.connect(path) as conn:
        schema = conn.execute('SELECT * FROM sqlite_master').fetchall()
    entered, release = threading.Event(), threading.Event()
    threads = []
    original = SQLiteTrendIntelligenceReadOnlyLookup.get_config
    def read(self, *args):
        threads.append(threading.get_ident())
        entered.set()
        assert release.wait(5)
        return original(self, *args)
    fake = Mock(shutdown=Mock(return_value=SimpleNamespace(control_released=True)))
    fake.collect_account.return_value = [InstagramRawObservation(
        source_account='test_account', external_id='ABC123',
        canonical_url='https://www.instagram.com/p/ABC123/', content_type='POST',
        observed_at='2026-10-11T10:00:00+00:00', caption='Test')]
    fake.start.side_effect = lambda: threads.append(threading.get_ident())
    fake.shutdown.side_effect = lambda: threads.append(threading.get_ident()) or SimpleNamespace(control_released=True)
    with patch('backend.services.config_service.DB_PATH', path), patch(
        'backend.services.instagram_collector_runtime_service.InstagramBrowserCollector', return_value=fake
    ) as factory, patch.object(SQLiteTrendIntelligenceReadOnlyLookup, 'get_config', read):
        with patch('sqlite3.connect', side_effect=AssertionError('constructor opened storage')):
            runtime = create_crm_instagram_runtime()
        assert path.read_bytes() == before
        factory.assert_not_called()
        try:
            with ThreadPoolExecutor(max_workers=8) as callers:
                futures = list(callers.map(lambda _: runtime.start(), range(32)))
            assert entered.wait(5)
            assert all(f is futures[0] for f in futures)
            factory.assert_not_called()
            release.set()
            futures[0].result(5)
            assert runtime.snapshot.status == 'SUCCESS'
            factory.assert_called_once_with(profile_key='it_instagram_collector', headless=True)
            fake.collect_account.assert_called_once()
            fake.shutdown.assert_called_once()
            assert len(set(threads)) == 1 and threads[0] != threading.get_ident()
            with sqlite3.connect(path) as conn:
                assert conn.execute('SELECT COUNT(*) FROM ti_observations').fetchone()[0] == 1
                assert conn.execute('SELECT * FROM sqlite_master').fetchall() == schema
        finally:
            release.set()
            runtime.close().result(5)


def test_discovery_failure_preserves_exception():
    error = RuntimeError('storage unavailable')
    factory = Mock()
    runtime = InstagramCollectorRuntimeService(
        configuration_service=Mock(load=Mock(side_effect=error)), collector_factory=factory)
    try:
        with pytest.raises(RuntimeError) as caught:
            runtime.start().result(5)
        assert caught.value is runtime.snapshot.error is error
        assert runtime.snapshot.status == 'ERROR'
        factory.assert_not_called()
    finally:
        runtime.close().result(5)


def test_missing_database_crm_startup_does_not_create_store(tmp_path):
    path = tmp_path / 'missing.db'
    with patch('backend.services.config_service.DB_PATH', path), patch(
        'backend.services.instagram_collector_runtime_service.InstagramBrowserCollector'
    ) as factory:
        runtime = create_crm_instagram_runtime()
        try:
            runtime.start().result(5)
            assert runtime.snapshot.status == 'NOT_CONFIGURED'
            factory.assert_not_called()
            assert not path.exists()
        finally:
            runtime.close().result(5)


def test_null_domain_and_malformed_json(store):
    path, _ = store
    service = InstagramCollectorConfigurationService(SQLiteTrendIntelligenceReadOnlyLookup(path))
    save(path, settings(domain_code=None))
    assert service.load().domain_code is None
    with sqlite3.connect(path) as conn:
        conn.execute('UPDATE config_global SET value = ?', ('{invalid',))
    with pytest.raises(InvalidInstagramConfiguration):
        service.load()
