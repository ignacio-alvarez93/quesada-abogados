import json
import threading
from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import Mock, PropertyMock

import pytest

from backend.services.instagram_collector_control_service import InstagramCollectorControlService
from backend.services.instagram_collector_configuration_service import (
    InstagramStartupConfiguration, InvalidInstagramConfiguration,
)


def done(value=True):
    future = Future()
    future.set_result(value)
    return future


def controller():
    lookup = Mock(get_config=Mock(return_value=None))
    runtime = Mock(start=Mock(return_value=done(None)), close=Mock(return_value=done()))
    runtime.snapshot = SimpleNamespace(status='SUCCESS', result=None)
    factory = Mock(return_value=runtime)
    service = InstagramCollectorControlService(lookup=lookup, save_setting=Mock(), repository=Mock(), runtime_factory=factory)
    service.configuration = Mock(load=Mock(return_value=InstagramStartupConfiguration('IDLE')))
    return service, runtime, factory


def test_read_and_save_disabled_never_create_browser():
    service, runtime, factory = controller()
    service.state()
    service.save(False, ['public_account'], 3)
    factory.assert_not_called()
    saved = json.loads(service.save_setting.call_args.args[1])
    assert saved == dict(enabled=False, accounts=[dict(account='public_account', limit=3)])


def test_disabled_execution():
    service, runtime, factory = controller()
    service.configuration.load.return_value = InstagramStartupConfiguration('DISABLED')
    service.execute().result(2)
    factory.assert_not_called()
    assert service.state()['status'] == 'DISABLED'


def test_single_flight_autostart_and_rerun():
    service, runtime, factory = controller()
    gate = Future()
    runtime.start.return_value = gate
    first = service.start()
    for _ in range(10):
        assert service.execute() is first
        assert service.start() is first
    gate.set_result(None)
    first.result(2)
    assert factory.call_count == 1
    assert service.start() is first
    service.execute().result(2)
    assert factory.call_count == 2
    assert runtime.close.call_count == 2


def test_cleanup_failure_retains_owner_until_retry():
    service, runtime, factory = controller()
    runtime.close.return_value = done(False)
    first = service.execute()
    first.result(2)
    assert service.state()['status'] == 'CLEANUP_REQUIRED'
    assert service.execute() is first
    assert factory.call_count == 1
    runtime.close.return_value = done(True)
    assert service.retry_cleanup().result(2) is True
    service.execute().result(2)
    assert factory.call_count == 2


def test_error_is_safe_traceable_and_releases():
    service, runtime, factory = controller()
    runtime.start.side_effect = RuntimeError('secret cookie and local path')
    service.execute().result(2)
    state = service.state()
    assert state['latest']['error'] == 'COLLECTION_FAILED'
    assert state['latest']['id']
    assert 'secret' not in str(state)
    assert not state['retained']


def test_close_during_run_and_no_more_starts():
    service, runtime, factory = controller()
    gate = Future()
    runtime.start.return_value = gate
    started = threading.Event()
    runtime.start.side_effect = lambda: (started.set(), gate)[1]
    first = service.execute()
    assert started.wait(2)
    service.close()
    gate.set_result(None)
    first.result(2)
    service.execute()
    assert factory.call_count == 1
    runtime.close.assert_called_once()


def test_real_results_and_empty_state():
    service, runtime, factory = controller()
    assert service.state()['rows'] == []
    observation = SimpleNamespace(id=12)
    runtime.snapshot.result = SimpleNamespace(observation_ids=(12, 12), created=1, duplicates=1)
    service.repository.get_observation.return_value = observation
    service.execute().result(2)
    assert service.state()['rows'] == [observation]
    service.repository.get_observation.assert_called_once_with(12)


def test_invalid_save_does_not_write():
    import pytest
    service, _, _ = controller()
    for accounts, limit in [(['bad/account'], 2), (['valid'], 0)]:
        with pytest.raises(ValueError):
            service.save(False, accounts, limit)
    service.save_setting.assert_not_called()

def test_enabled_save_preserves_registered_configuration():
    from backend.services.instagram_collector_configuration_service import InstagramCollectorConfigurationService
    service, _, _ = controller()
    value = dict(enabled=True, source_code='IG', domain_code=None,
                 profile_key='it_instagram_collector', headless=True,
                 accounts=[dict(account='old', limit=2)])
    service.lookup.get_config.side_effect = lambda key: json.dumps(value)
    service.lookup.get_source_by_code.return_value = SimpleNamespace(
        is_active=True, source_type='SOCIAL', collection_mode='SELENIUM',
        provider='Instagram', base_url='https://www.instagram.com')
    service.save_setting.side_effect = lambda key, raw: value.update(json.loads(raw))
    service.save(True, ['new_account'], 4)
    effective = InstagramCollectorConfigurationService(service.lookup).load()
    assert effective.status == 'IDLE'
    assert effective.config.targets[0].account == 'new_account'
    assert effective.config.targets[0].limit == 4
    assert effective.config.profile_key == 'it_instagram_collector'


def test_parallel_clicks_share_one_future():
    from concurrent.futures import ThreadPoolExecutor
    service, runtime, factory = controller()
    gate = Future()
    runtime.start.return_value = gate
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = list(pool.map(lambda _: service.execute(), range(24)))
    assert all(f is futures[0] for f in futures)
    gate.set_result(None)
    futures[0].result(2)
    assert factory.call_count == 1


# TI-4C.3E3A2: after_collection runs once per run, after SUCCESS and release.

PROJECTION = dict(status='OK', provisional=True, trend_scoring='NOT_COMPUTED', domain_code='IT_DOMAIN',
                  run=dict(observations=2, classified=1, unmatched=1))


def ordered_controller(order, *, close_result=True, status='SUCCESS', analysis=PROJECTION):
    service, runtime, factory = controller()
    service.configuration.load.return_value = InstagramStartupConfiguration('IDLE', domain_code='IT_DOMAIN')
    runtime.start.side_effect = lambda: (order.append('start'), done(None))[1]
    snapshot = SimpleNamespace(status=status, result=SimpleNamespace(observation_ids=(7, 8, 7)))
    type(runtime).snapshot = PropertyMock(side_effect=lambda: (order.append('snapshot'), snapshot)[1])
    runtime.close.side_effect = lambda: (order.append('close'), done(close_result))[1]
    events = []

    def after(event):
        order.append('classify')
        events.append(event)
        if isinstance(analysis, Exception):
            raise analysis
        return analysis

    service.after_collection = Mock(side_effect=after)
    return service, runtime, factory, events


def test_default_controller_has_no_hook_and_unchanged_state():
    service, runtime, factory = controller()
    assert service.after_collection is None
    service.execute().result(2)
    state = service.state()
    assert state['status'] == 'SUCCESS'
    assert state['analysis'] == dict(status=None, result=None)
    assert state['latest']['analysis_status'] is None


def test_classification_only_after_success_and_released_browser():
    order = []
    service, runtime, factory, events = ordered_controller(order)
    service.execute().result(2)
    assert order == ['start', 'snapshot', 'close', 'classify']
    assert events == [dict(run_id=service.state()['latest']['id'], collection_status='SUCCESS',
                           browser_released=True, domain_code='IT_DOMAIN', observation_ids=(7, 8, 7))]
    state = service.state()
    assert (state['status'], state['latest']['status'], state['latest']['error']) == ('SUCCESS', 'SUCCESS', None)
    assert state['analysis'] == dict(status='OK', result=PROJECTION)
    assert not state['retained'] and not state['busy']


def test_cleanup_failure_never_classifies_and_retains_owner():
    order = []
    service, runtime, factory, events = ordered_controller(order, close_result=False)
    service.execute().result(2)
    service.after_collection.assert_not_called()
    state = service.state()
    assert (state['status'], state['retained']) == ('CLEANUP_REQUIRED', True)
    assert state['analysis'] == dict(status='SKIPPED', result=None)
    runtime.close.side_effect = None
    runtime.close.return_value = done(True)
    assert service.retry_cleanup().result(2) is True
    service.after_collection.assert_not_called()


def test_cleanup_exception_never_classifies():
    order = []
    service, runtime, factory, events = ordered_controller(order)
    runtime.close.side_effect = RuntimeError('profile path')
    service.execute().result(2)
    service.after_collection.assert_not_called()
    assert service.state()['status'] == 'CLEANUP_REQUIRED'


@pytest.mark.parametrize('status', ['ERROR', 'BLOCKED', 'NOT_CONFIGURED'])
def test_failed_collection_never_classifies(status):
    order = []
    service, runtime, factory, events = ordered_controller(order, status=status)
    service.execute().result(2)
    service.after_collection.assert_not_called()
    assert service.state()['latest']['analysis_status'] == 'SKIPPED'


def test_start_exception_never_classifies():
    order = []
    service, runtime, factory, events = ordered_controller(order)
    runtime.start.side_effect = RuntimeError('secret')
    service.execute().result(2)
    service.after_collection.assert_not_called()
    assert service.state()['status'] == 'ERROR'


@pytest.mark.parametrize('startup', ['DISABLED', 'NOT_CONFIGURED'])
def test_disabled_or_not_configured_never_classifies(startup):
    order = []
    service, runtime, factory, events = ordered_controller(order)
    service.configuration.load.return_value = InstagramStartupConfiguration(startup)
    service.execute().result(2)
    factory.assert_not_called()
    service.after_collection.assert_not_called()


def test_invalid_configuration_never_classifies():
    order = []
    service, runtime, factory, events = ordered_controller(order)
    service.configuration.load.side_effect = InvalidInstagramConfiguration('bad')
    service.execute().result(2)
    service.after_collection.assert_not_called()
    assert service.state()['status'] == 'NOT_CONFIGURED'


def test_analysis_failure_keeps_collection_success_and_hides_details():
    order = []
    service, runtime, factory, events = ordered_controller(
        order, analysis=RuntimeError('caption secreta https://www.instagram.com/p/x C:/secret'))
    service.execute().result(2)
    state = service.state()
    assert (state['status'], state['latest']['status'], state['latest']['error']) == ('SUCCESS', 'SUCCESS', None)
    assert state['analysis'] == dict(status='ERROR', result=dict(status='ERROR', error_type='RuntimeError'))
    assert 'secret' not in str(state) and 'instagram.com' not in str(state)
    assert factory.call_count == 1 and runtime.close.call_count == 1


@pytest.mark.parametrize('analysis,expected', [
    (dict(status='BUSY', provisional=True), 'BUSY'),
    (dict(status='LOCK_ERROR', error_type='PermissionError'), 'LOCK_ERROR'),
    (dict(status='NO_STORE'), 'NO_STORE'),
    (dict(status='https://www.instagram.com/p/x'), 'ERROR'),
    ('not a mapping', 'ERROR'),
    (None, 'ERROR'),
])
def test_analysis_status_is_published_independently(analysis, expected):
    order = []
    service, runtime, factory, events = ordered_controller(order, analysis=analysis)
    service.execute().result(2)
    state = service.state()
    assert (state['status'], state['analysis']['status']) == ('SUCCESS', expected)


def test_analysis_projection_is_sanitized_and_copied():
    order = []
    leaky = {'status': 'OK', 'caption': 'texto con espacios', 'url': 'https://www.instagram.com/p/x/',
             'nested': dict(account_url='https://x', count=3, flag=True, ratio=0.5),
             'codes': ['ARRAIGO', 'C:/secret'], 'bad key': 1}
    service, runtime, factory, events = ordered_controller(order, analysis=leaky)
    service.execute().result(2)
    result = service.state()['analysis']['result']
    assert result == dict(status='OK', caption=None, url=None,
                          nested=dict(account_url=None, count=3, flag=True, ratio=None), codes=['ARRAIGO', None])
    result['status'] = 'MUTATED'
    assert service.state()['analysis']['result']['status'] == 'OK'


def test_single_flight_clicks_during_analysis_share_one_run():
    from concurrent.futures import ThreadPoolExecutor
    order = []
    service, runtime, factory, events = ordered_controller(order)
    entered, gate = threading.Event(), threading.Event()
    service.after_collection.side_effect = lambda event: (events.append(event), entered.set(), gate.wait(5),
                                                          PROJECTION)[-1]
    first = service.execute()
    assert entered.wait(2)
    state = service.state()
    assert (state['busy'], state['status'], state['analysis']['status']) == (True, 'SUCCESS', 'RUNNING')
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = list(pool.map(lambda _: service.execute(), range(16)))
    assert all(f is first for f in futures) and service.start() is first
    with pytest.raises(ValueError):
        service.save(False, ['public_account'], 2)
    gate.set()
    first.result(2)
    assert (factory.call_count, service.after_collection.call_count) == (1, 1)
    service.execute().result(2)
    assert (factory.call_count, service.after_collection.call_count) == (2, 2)
    assert events[0]['run_id'] != events[1]['run_id']
    assert [r['analysis_status'] for r in service.state()['history']] == ['OK', 'OK']


def test_a_run_id_never_triggers_twice():
    order = []
    service, runtime, factory, events = ordered_controller(order)
    service.execute().result(2)
    record = service._history[-1]
    with service._lock:
        assert service._claim_analysis(record, True) is False
    assert service.after_collection.call_count == 1


def test_autostart_classifies_once_per_session():
    order = []
    service, runtime, factory, events = ordered_controller(order)
    service.start().result(2)
    assert service.start().done()
    assert (factory.call_count, service.after_collection.call_count) == (1, 1)


def test_close_during_collection_skips_analysis():
    order = []
    service, runtime, factory, events = ordered_controller(order)
    gate, started = Future(), threading.Event()
    runtime.start.side_effect = lambda: (started.set(), gate)[1]
    first = service.execute()
    assert started.wait(2)
    service.close()
    gate.set_result(None)
    first.result(2)
    service.after_collection.assert_not_called()
    assert service.state()['latest']['analysis_status'] == 'SKIPPED'
    assert service.execute() is None
    assert factory.call_count == 1


def test_close_during_analysis_waits_for_the_same_worker():
    order = []
    service, runtime, factory, events = ordered_controller(order)
    entered, gate = threading.Event(), threading.Event()
    service.after_collection.side_effect = lambda event: (entered.set(), gate.wait(5), PROJECTION)[-1]
    first = service.execute()
    assert entered.wait(2)
    assert service.close() is first
    gate.set()
    first.result(2)
    assert runtime.close.call_count == 1
    assert service.retry_cleanup() is None
    assert service.state()['analysis']['status'] == 'OK'


def test_state_and_settings_have_no_side_effects():
    order = []
    service, runtime, factory, events = ordered_controller(order)
    for _ in range(5):
        service.state()
        service.settings()
    service.save(False, ['public_account'], 2)
    factory.assert_not_called()
    service.after_collection.assert_not_called()
    assert order == []
