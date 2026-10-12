"""Principal CRM contracts, using temporary storage and no live providers."""
import ast
import json
from pathlib import Path
import sqlite3
import threading
from unittest.mock import Mock, patch

import pytest

from backend.repositories.sqlite_trend_intelligence_repository import (
    SQLiteTrendIntelligenceRepository,
)
from backend.services import config_service
from backend.services.instagram_collector_configuration_service import (
    SETTINGS_KEY, create_crm_instagram_runtime,
)
from backend.services import instagram_collector_runtime_service as runtime_module
from backend.trend_intelligence.service import TrendIntelligenceService
from backend.trend_intelligence.sources import (
    InstagramRawObservation, InstagramTrendSourceAdapter, normalize_instagram_post,
    ManualTrendSourceAdapter, TrendObservationInput, TrendSourceAdapter,
)
from backend.trend_intelligence.sources.instagram_browser import (
    InstagramCollectionConfig, InstagramCollectionTarget,
)


def raw():
    return InstagramRawObservation(
        source_account='crm_test', external_id='CRM123',
        canonical_url='https://www.instagram.com/p/CRM123/',
        content_type='POST', observed_at='2026-10-12T10:00:00Z', caption='Fixture',
    )


def test_package_exports_preserve_existing_adapter_contract():
    from backend.trend_intelligence import sources
    from backend.trend_intelligence.sources import instagram, base, manual

    expected = dict(
        InstagramRawObservation=instagram.InstagramRawObservation,
        InstagramTrendSourceAdapter=instagram.InstagramTrendSourceAdapter,
        normalize_instagram_post=instagram.normalize_instagram_post,
        ManualTrendSourceAdapter=manual.ManualTrendSourceAdapter,
        TrendObservationInput=base.TrendObservationInput,
        TrendSourceAdapter=base.TrendSourceAdapter,
    )
    for name, value in expected.items():
        assert name in sources.__all__
        assert getattr(sources, name) is value
    assert isinstance(next(iter(InstagramTrendSourceAdapter('CRM', [raw()]).collect())),
                      TrendObservationInput)


@pytest.fixture
def crm_store(tmp_path, monkeypatch):
    path = tmp_path / 'crm # contract.db'
    monkeypatch.setattr(config_service, 'DB_PATH', path)
    repository = SQLiteTrendIntelligenceRepository(path)
    service = TrendIntelligenceService(repository)
    service.ensure_schema()
    service.create_source(code='CRM_IG', name='Fixture', source_type='SOCIAL',
                          provider='Instagram', collection_mode='SELENIUM')
    domain = service.create_domain(code='CRM_TEST', name='Fixture')
    # Supply the existing settings schema; skip unrelated expedient migrations.
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE config_global (key TEXT PRIMARY KEY, value TEXT, '
                     'updated_at TEXT DEFAULT CURRENT_TIMESTAMP)')
    settings = json.dumps(dict(
        enabled=True, source_code='CRM_IG', domain_code='CRM_TEST',
        profile_key='it_instagram_collector', headless=True,
        accounts=[dict(account='crm_test', limit=2)],
    ))
    with patch.object(config_service, 'ensure_config_runtime_schema'):
        config_service.set_config(SETTINGS_KEY, settings)
        assert config_service.get_config(SETTINGS_KEY) == settings
    return path, repository, domain


def test_real_crm_composition_replays_without_schema_or_registry_writes(crm_store, monkeypatch):
    path, repository, domain = crm_store
    ui_thread = threading.get_ident()
    worker_threads = []
    connect = sqlite3.connect
    statements = []

    def guarded_connect(database, *args, **kwargs):
        # Reject any accidental access to the production store, including URIs.
        assert str(database) in {str(path), path.resolve().as_uri() + '?mode=ro'}
        conn = connect(database, *args, **kwargs)
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(sqlite3, 'connect', guarded_connect)
    for owner, name in [(SQLiteTrendIntelligenceRepository, 'ensure_schema'),
                        (TrendIntelligenceService, 'create_source'),
                        (TrendIntelligenceService, 'create_domain'),
                        (config_service, 'ensure_config_runtime_schema')]:
        monkeypatch.setattr(owner, name, Mock(side_effect=AssertionError('startup mutation')))

    def worker_call(*args, **kwargs):
        worker_threads.append(threading.get_ident())

    fake = Mock()
    fake.start.side_effect = worker_call
    fake.collect_account.side_effect = lambda *a, **kw: (worker_call(), [raw()])[1]
    fake.shutdown.side_effect = worker_call
    factory = Mock(return_value=fake)
    monkeypatch.setattr(runtime_module, 'InstagramBrowserCollector', factory)
    reports = []
    for _ in range(2):
        count = len(statements)
        runtime = create_crm_instagram_runtime()
        assert len(statements) == count  # Composition itself performs no I/O.
        try:
            future = runtime.start()
            assert runtime.start() is future
            reports.append(future.result(5))
            assert runtime.snapshot.status == 'SUCCESS'
        finally:
            assert runtime.close().result(5) is True
        assert runtime.start() is future  # Closed sessions cannot redispatch.

    assert [r.created for r in reports] == [1, 0]
    assert [r.duplicates for r in reports] == [0, 1]
    assert reports[0].observation_ids == reports[1].observation_ids
    observation_id = reports[0].observation_ids[0]
    assert repository.get_observation(observation_id).author == 'crm_test'
    assert repository.list_observation_domains(observation_id)[0].domain_id == domain.id
    assert factory.call_count == fake.start.call_count == fake.shutdown.call_count == 2
    fake.collect_account.assert_called_with('crm_test', limit=2)
    assert all(t != ui_thread for t in worker_threads)
    assert len(set(worker_threads[:3])) == len(set(worker_threads[3:])) == 1
    forbidden = ('CREATE ', 'ALTER ', 'DROP ', 'INSERT INTO TI_SOURCES',
                 'UPDATE TI_SOURCES', 'INSERT INTO TI_DOMAINS')
    assert not any(s.strip().upper().startswith(forbidden) for s in statements)


@pytest.mark.parametrize('headless', ['false', 0, None])
def test_invalid_direct_configuration_is_inert(headless):
    factory = Mock()
    runtime = runtime_module.InstagramCollectorRuntimeService(
        enabled=True, ingestion_service=Mock(), collector_factory=factory,
        config=InstagramCollectionConfig('CRM', (InstagramCollectionTarget('test'),),
                                         headless=headless),
    )
    assert runtime.snapshot.status == 'NOT_CONFIGURED'
    assert runtime.start() is None
    assert runtime.close() is None
    factory.assert_not_called()


def test_instagram_dispatch_failure_does_not_interrupt_authenticated_callback():
    tree = ast.parse(Path('app/main.py').read_text(encoding='utf-8'))
    callback = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == 'on_login_success')
    order = []
    names = ['navigate', 'start_icpplus_warning_watch',
             'maybe_start_icpplus_warning_ui_smoke', 'start_whatsapp_session_services',
             'maybe_start_global_call_ui_smoke', 'maybe_start_post_call_ui_smoke']
    namespace = {name: Mock(side_effect=lambda *a, _name=name: order.append(_name))
                 for name in names}
    namespace.update(current_user={}, instagram_runtime=Mock(
        start=Mock(side_effect=RuntimeError('dispatch unavailable'))))
    exec(compile(ast.Module(body=[callback], type_ignores=[]), '<crm-login>', 'exec'), namespace)
    namespace['on_login_success']({'id': 123})
    assert namespace['current_user']['value'] == {'id': 123}
    assert order == names
