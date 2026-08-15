from pathlib import Path

from backend.automation.browser_contracts import (
    BrowserSessionConfig,
    BrowserSessionConfigurationError,
    BrowserSessionLifecycleError,
    BrowserSessionMode,
    BrowserSessionState,
)
from backend.automation.seleniumbase_browser_session import (
    SeleniumBaseBrowserSession,
)


class FakeBrowser:
    pass


class FactoryProbe:
    def __init__(
        self,
        *,
        result=None,
        error=None,
    ):
        self.result = (
            result
            if result is not None
            else FakeBrowser()
        )

        self.error = error
        self.calls = []

    def __call__(
        self,
        **kwargs,
    ):
        self.calls.append(
            dict(kwargs)
        )

        if self.error is not None:
            raise self.error

        return self.result


def make_session(
    *,
    config=None,
    factory=None,
    profile_resolver=None,
):
    return SeleniumBaseBrowserSession(
        config=(
            config
            or BrowserSessionConfig(
                consumer="test",
            )
        ),
        browser_factory=(
            factory
            or FactoryProbe()
        ),
        profile_resolver=(
            profile_resolver
        ),
        session_id_factory=(
            lambda: "session-test-001"
        ),
    )


def test_initial_identity_and_state():
    session = make_session(
        config=BrowserSessionConfig(
            consumer="whatsapp",
            mode=BrowserSessionMode.PERSISTENT,
            profile_key="whatsapp_dev",
        ),
        profile_resolver=(
            lambda key:
                Path("/tmp") / key
        ),
    )

    assert (
        session.identity.session_id
        == "session-test-001"
    )

    assert (
        session.identity.consumer
        == "whatsapp"
    )

    assert (
        session.identity.mode
        == BrowserSessionMode.PERSISTENT
    )

    assert (
        session.identity.profile_key
        == "whatsapp_dev"
    )

    assert (
        session.state
        == BrowserSessionState.CREATED
    )

    assert session.browser is None
    assert session.transition_history == ()


def test_initial_health_and_snapshot():
    session = make_session()

    health = session.health()

    assert (
        health.state
        == BrowserSessionState.CREATED
    )

    assert health.browser_available is False
    assert health.control_available is False
    assert health.worker_available is None
    assert health.last_error == ""

    snapshot = session.snapshot()

    assert (
        snapshot.identity
        is session.identity
    )

    assert (
        snapshot.state
        == BrowserSessionState.CREATED
    )


def test_start_uses_existing_factory_contract():
    browser = FakeBrowser()

    factory = FactoryProbe(
        result=browser,
    )

    session = make_session(
        config=BrowserSessionConfig(
            consumer="dehu",
            headless=True,
        ),
        factory=factory,
    )

    result = session.start()

    assert result is browser
    assert session.browser is browser

    assert factory.calls == [
        {
            "headless": True,
        }
    ]

    assert (
        session.state
        == BrowserSessionState.READY
    )


def test_profile_resolution_is_explicit():
    browser = FakeBrowser()
    factory = FactoryProbe(
        result=browser,
    )

    resolver_calls = []

    def resolve(
        key,
    ):
        resolver_calls.append(
            key
        )

        return (
            Path("profiles")
            / key
        )

    session = make_session(
        config=BrowserSessionConfig(
            consumer="whatsapp",
            mode="persistent",
            profile_key="whatsapp_dev",
        ),
        factory=factory,
        profile_resolver=resolve,
    )

    assert session.start() is browser

    assert resolver_calls == [
        "whatsapp_dev"
    ]

    assert factory.calls == [
        {
            "headless": False,
            "user_data_dir":
                Path("profiles")
                / "whatsapp_dev",
        }
    ]


def test_profile_key_requires_resolver():
    factory = FactoryProbe()

    session = make_session(
        config=BrowserSessionConfig(
            consumer="whatsapp",
            mode="persistent",
            profile_key="whatsapp_dev",
        ),
        factory=factory,
    )

    try:
        session.start()
    except BrowserSessionConfigurationError:
        pass
    else:
        raise AssertionError(
            "profile_key sin resolver debería fallar"
        )

    assert factory.calls == []

    assert (
        session.state
        == BrowserSessionState.CREATED
    )

    assert session.transition_history == ()


def test_successful_start_records_transitions():
    session = make_session()

    session.start()

    transitions = (
        session.transition_history
    )

    assert len(transitions) == 2

    assert (
        transitions[0].previous_state
        == BrowserSessionState.CREATED
    )

    assert (
        transitions[0].current_state
        == BrowserSessionState.STARTING
    )

    assert (
        transitions[0].reason
        == "start_requested"
    )

    assert (
        transitions[1].previous_state
        == BrowserSessionState.STARTING
    )

    assert (
        transitions[1].current_state
        == BrowserSessionState.READY
    )

    assert (
        transitions[1].reason
        == "browser_created"
    )


def test_ready_start_is_idempotent():
    browser = FakeBrowser()

    factory = FactoryProbe(
        result=browser,
    )

    session = make_session(
        factory=factory,
    )

    first = session.start()
    second = session.start()

    assert first is browser
    assert second is browser
    assert len(factory.calls) == 1
    assert len(session.transition_history) == 2


def test_factory_failure_marks_failed():
    factory = FactoryProbe(
        error=RuntimeError(
            "chrome unavailable"
        )
    )

    session = make_session(
        factory=factory,
    )

    try:
        session.start()
    except BrowserSessionLifecycleError as exc:
        assert isinstance(
            exc.__cause__,
            RuntimeError,
        )
    else:
        raise AssertionError(
            "El fallo de factory debería propagarse "
            "como BrowserSessionLifecycleError"
        )

    assert (
        session.state
        == BrowserSessionState.FAILED
    )

    assert session.browser is None

    health = session.health()

    assert health.browser_available is False
    assert health.control_available is False

    assert (
        "chrome unavailable"
        in health.last_error
    )

    transitions = (
        session.transition_history
    )

    assert len(transitions) == 2

    assert (
        transitions[-1].current_state
        == BrowserSessionState.FAILED
    )

    assert (
        transitions[-1].reason
        == "start_failed"
    )


def test_factory_returning_none_is_failure():
    factory = FactoryProbe()

    factory.result = None

    session = make_session(
        factory=factory,
    )

    try:
        session.start()
    except BrowserSessionLifecycleError:
        pass
    else:
        raise AssertionError(
            "browser_factory=None debería fallar"
        )

    assert (
        session.state
        == BrowserSessionState.FAILED
    )


def test_failed_session_does_not_restart_implicitly():
    factory = FactoryProbe(
        error=RuntimeError(
            "first failure"
        )
    )

    session = make_session(
        factory=factory,
    )

    try:
        session.start()
    except BrowserSessionLifecycleError:
        pass

    factory.error = None

    try:
        session.start()
    except BrowserSessionLifecycleError:
        pass
    else:
        raise AssertionError(
            "FAILED no debe reiniciarse implícitamente"
        )

    assert len(factory.calls) == 1


def test_session_adapter_has_no_provider_dependency():
    path = (
        Path(__file__)
        .resolve()
        .parents[2]
        / "backend"
        / "automation"
        / "seleniumbase_browser_session.py"
    )

    text = path.read_text(
        encoding="utf-8",
    )

    forbidden = (
        "WhatsAppConnector",
        "MercurioConnector",
        "DehuConnector",
        "CommunicationService",
        "sqlite3",
        "import flet",
    )

    for token in forbidden:
        assert token not in text, token


TESTS = (
    test_initial_identity_and_state,
    test_initial_health_and_snapshot,
    test_start_uses_existing_factory_contract,
    test_profile_resolution_is_explicit,
    test_profile_key_requires_resolver,
    test_successful_start_records_transitions,
    test_ready_start_is_idempotent,
    test_factory_failure_marks_failed,
    test_factory_returning_none_is_failure,
    test_failed_session_does_not_restart_implicitly,
    test_session_adapter_has_no_provider_dependency,
)


def main():
    passed = 0

    for test in TESTS:
        test()
        passed += 1

    print(
        "SELENIUMBASE BROWSER SESSION "
        f"{passed}/{len(TESTS)} OK"
    )


if __name__ == "__main__":
    main()
