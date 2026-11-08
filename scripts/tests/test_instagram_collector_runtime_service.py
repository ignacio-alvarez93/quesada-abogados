"""Offline tests; all browser sessions and ingestion are fakes."""
from concurrent.futures import ThreadPoolExecutor
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from backend.services.instagram_collector_runtime_service import InstagramCollectorRuntimeService
from backend.trend_intelligence.sources.instagram_browser import (
    InstagramAccessBlockedError, InstagramBrowserCollector,
    InstagramCollectionConfig, InstagramCollectionTarget,
)


def configured(**kwargs):
    options = dict(enabled=True, config=InstagramCollectionConfig(
        source_code="TEST", targets=(InstagramCollectionTarget("test_account"),),
    ), ingestion_service=Mock())
    options.update(kwargs)
    return InstagramCollectorRuntimeService(**options)


def collector():
    return Mock(shutdown=Mock(return_value=SimpleNamespace(control_released=True)),
                collect_account=Mock(return_value=[]))


def finish(runtime):
    future = runtime.close()
    if future is not None:
        assert future.result(timeout=5)


def test_construction_disabled_unconfigured_no_side_effects():
    with patch('backend.services.instagram_collector_runtime_service.ThreadPoolExecutor') as executor:
        for options, status in [({}, 'DISABLED'), ({'enabled': True}, 'NOT_CONFIGURED')]:
            factory = Mock()
            runtime = InstagramCollectorRuntimeService(collector_factory=factory, **options)
            assert runtime.snapshot.status == status
            assert runtime.start() is None
            assert runtime.close() is None
            factory.assert_not_called()
        executor.assert_not_called()


@pytest.mark.parametrize('options', [
    {'ingestion_service': None}, {'config': None},
    {'config': InstagramCollectionConfig(source_code='TEST', targets=(InstagramCollectionTarget('../bad'),))},
    {'config': InstagramCollectionConfig(source_code='TEST', targets=(InstagramCollectionTarget('test'),), profile_key='../bad')},
])
def test_invalid_configuration_never_dispatches(options):
    factory = Mock()
    runtime = configured(collector_factory=factory, **options)
    assert runtime.snapshot.status == 'NOT_CONFIGURED'
    assert runtime.start() is None
    factory.assert_not_called()


def test_concurrent_start_one_worker_and_orderly_close():
    entered, release = threading.Event(), threading.Event()
    threads = []
    fake = collector()
    def start():
        threads.append(threading.get_ident())
        entered.set()
        assert release.wait(5)
    fake.start.side_effect = start
    fake.collect_account.side_effect = lambda *a, **k: threads.append(threading.get_ident()) or []
    fake.shutdown.side_effect = lambda: threads.append(threading.get_ident()) or SimpleNamespace(control_released=True)
    factory = Mock(return_value=fake)
    runtime = configured(collector_factory=factory)
    assert runtime.snapshot.status == 'IDLE'
    factory.assert_not_called()
    try:
        with ThreadPoolExecutor(max_workers=8) as callers:
            futures = list(callers.map(lambda _: runtime.start(), range(32)))
        assert all(f is futures[0] for f in futures)
        assert entered.wait(5)
        assert runtime.snapshot.status == 'RUNNING'
        closing = runtime.close()
        assert not closing.done()
        assert runtime.start() is futures[0]
        fake.shutdown.assert_not_called()
    finally:
        release.set()
        finish(runtime)
    assert runtime.snapshot.result is futures[0].result(timeout=5)
    assert runtime.snapshot.status == 'SUCCESS'
    factory.assert_called_once()
    fake.start.assert_called_once()
    fake.collect_account.assert_called_once()
    fake.shutdown.assert_called_once()
    assert len(set(threads)) == 1 and threads[0] != threading.get_ident()
    assert runtime.close() is closing


@pytest.mark.parametrize('error,status', [
    (InstagramAccessBlockedError('login/checkpoint'), 'BLOCKED'),
    (TimeoutError('navigation'), 'ERROR'), (RuntimeError('DOM failed'), 'ERROR'),
])
def test_error_identity_and_no_ingestion(error, status):
    fake = collector()
    fake.collect_account.side_effect = error
    ingestion = Mock()
    runtime = configured(collector_factory=Mock(return_value=fake), ingestion_service=ingestion)
    try:
        future = runtime.start()
        with pytest.raises(type(error)) as caught:
            future.result(timeout=5)
        assert caught.value is runtime.snapshot.error is error
        assert error.__traceback__ is not None
        assert runtime.snapshot.status == status
        assert runtime.snapshot.result is None
        ingestion.ingest.assert_not_called()
        assert runtime.start() is future
    finally:
        finish(runtime)
    fake.shutdown.assert_called_once()


def test_cleanup_failure_preserves_blocked_error_and_owner():
    fake = collector()
    original = InstagramAccessBlockedError('challenge')
    cleanup = RuntimeError('owner loop unavailable')
    fake.collect_account.side_effect = original
    fake.shutdown.side_effect = [cleanup, SimpleNamespace(control_released=True)]
    factory = Mock(return_value=fake)
    runtime = configured(collector_factory=factory)
    with pytest.raises(InstagramAccessBlockedError):
        runtime.start().result(timeout=5)
    assert runtime.snapshot.error is original
    assert runtime.snapshot.cleanup_error is cleanup
    assert runtime.snapshot.status == 'BLOCKED'
    finish(runtime)
    assert fake.shutdown.call_count == 2
    factory.assert_called_once()


def test_failed_cleanup_retry():
    fake = collector()
    fake.shutdown.side_effect = [SimpleNamespace(control_released=False),
                                RuntimeError('still owned'), SimpleNamespace(control_released=True)]
    runtime = configured(collector_factory=Mock(return_value=fake))
    runtime.start().result(timeout=5)
    assert runtime.snapshot.status == 'ERROR'
    assert runtime.close().result(timeout=5) is False
    finish(runtime)
    assert fake.shutdown.call_count == 3


def test_close_before_start():
    factory = Mock()
    runtime = configured(collector_factory=factory)
    assert runtime.close() is None
    assert runtime.start() is None
    factory.assert_not_called()


def test_close_during_discovery_never_acquires_browser():
    entered, release = threading.Event(), threading.Event()
    config = InstagramCollectionConfig(
        source_code="TEST", targets=(InstagramCollectionTarget("test"),),
    )

    def load():
        entered.set()
        assert release.wait(5)
        return SimpleNamespace(status="IDLE", config=config, domain_code=None)

    factory = Mock()
    runtime = configured(configuration_service=Mock(load=load), collector_factory=factory)
    try:
        starting = runtime.start()
        assert entered.wait(5)
        closing = runtime.close()
        assert not closing.done()
        release.set()
        assert starting.result(5) is None
        assert closing.result(5) is True
        assert runtime.snapshot.status == "CLOSED"
        factory.assert_not_called()
    finally:
        release.set()
        finish(runtime)


@pytest.mark.parametrize('failure', ['navigation', 'dom', 'login', 'checkpoint'])
def test_real_collector_boundary_no_fabricated_success(failure):
    browser = Mock()
    browser.url = 'https://www.instagram.com/test_account/'
    if failure == 'navigation':
        browser.open.side_effect = TimeoutError('navigation failed')
    elif failure == 'dom':
        browser.find_elements.side_effect = RuntimeError('DOM failed')
    else:
        browser.url = 'https://www.instagram.com/' + ('accounts/login/' if failure == 'login' else 'checkpoint/')
    session = Mock(start=Mock(return_value=browser), shutdown=Mock(return_value=SimpleNamespace(control_released=True)))
    sessions = Mock(return_value=session)
    def factory(**kwargs):
        return InstagramBrowserCollector(**kwargs, browser_session_factory=sessions, profile_resolver=Mock())
    ingestion = Mock()
    runtime = configured(collector_factory=factory, ingestion_service=ingestion)
    try:
        future = runtime.start()
        with pytest.raises(Exception):
            future.result(timeout=5)
        assert runtime.snapshot.status == ('BLOCKED' if failure in ('login', 'checkpoint') else 'ERROR')
        ingestion.ingest.assert_not_called()
        assert runtime.start() is future
    finally:
        finish(runtime)
    sessions.assert_called_once()
    session.start.assert_called_once()
    session.shutdown.assert_called_once()


def test_start_failure_preserves_cause():
    fake = collector()
    cause = RuntimeError('profile already owned')
    error = RuntimeError('session start failed')
    error.__cause__ = cause
    fake.start.side_effect = error
    runtime = configured(collector_factory=Mock(return_value=fake))
    try:
        with pytest.raises(RuntimeError):
            runtime.start().result(timeout=5)
        assert runtime.snapshot.error.__cause__ is cause
        fake.collect_account.assert_not_called()
    finally:
        finish(runtime)
