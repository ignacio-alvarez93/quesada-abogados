import json
import threading
from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import Mock

from backend.services.instagram_collector_control_service import InstagramCollectorControlService
from backend.services.instagram_collector_configuration_service import InstagramStartupConfiguration


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
