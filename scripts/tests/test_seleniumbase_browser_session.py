import ast
import asyncio
from pathlib import Path

from backend.automation.browser_contracts import (
    BrowserSessionConfig,
    BrowserSessionConfigurationError,
    BrowserSessionLifecycleError,
    BrowserSessionMode,
    BrowserSessionState,
    BrowserShutdownMode,
)
from backend.automation.seleniumbase_browser_session import (
    SeleniumBaseBrowserSession,
)


class FakeBrowser:
    pass


class FakeWebSocket:
    def __init__(
        self,
        loop,
    ):
        self.loop = loop


class FakeConnection:
    def __init__(
        self,
        loop,
    ):
        self.websocket = (
            FakeWebSocket(
                loop
            )
        )

        self.closed = False
        self.close_loop = None

    async def aclose(
        self,
    ):
        self.close_loop = (
            asyncio.get_running_loop()
        )

        self.closed = True


class FakeProcessTransport:
    def __init__(
        self,
        loop,
    ):
        self._loop = loop


class FakeProcess:
    def __init__(
        self,
        loop,
    ):
        self._transport = (
            FakeProcessTransport(
                loop
            )
        )

        self.pid = 12345
        self.returncode = None
        self.terminated = False
        self.killed = False
        self.wait_loop = None

    def terminate(
        self,
    ):
        self.terminated = True

    def kill(
        self,
    ):
        self.killed = True

    async def wait(
        self,
    ):
        self.wait_loop = (
            asyncio.get_running_loop()
        )

        self.returncode = 1

        return self.returncode


class FakeDriver:
    def __init__(
        self,
        root_loop,
        page,
    ):
        self.connection = (
            FakeConnection(
                root_loop
            )
        )

        self._process = (
            FakeProcess(
                root_loop
            )
        )

        self.page = page
        self.main_tab = page
        self.targets = [
            page,
        ]
        self.tabs = [
            page,
        ]


class GovernedFakeBrowser:
    def __init__(
        self,
    ):
        self.root_loop = (
            asyncio.new_event_loop()
        )

        self.wrapper_loop = (
            asyncio.new_event_loop()
        )

        self.page = FakeConnection(
            self.wrapper_loop
        )

        self.driver = FakeDriver(
            self.root_loop,
            self.page,
        )

    def dispose_test_loops(
        self,
    ):
        for loop in (
            self.wrapper_loop,
            self.root_loop,
        ):
            if not loop.is_closed():
                loop.close()


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


def test_shutdown_close_uses_resource_owner_loops():
    browser = GovernedFakeBrowser()

    factory = FactoryProbe(
        result=browser,
    )

    session = make_session(
        factory=factory,
    )

    try:
        assert (
            session.start()
            is browser
        )

        result = session.shutdown(
            BrowserShutdownMode.CLOSE
        )

        assert result.has_error is False

        assert (
            result.mode
            == BrowserShutdownMode.CLOSE
        )

        assert (
            result.state_before
            == BrowserSessionState.READY
        )

        assert (
            result.state_after
            == BrowserSessionState.CLOSED
        )

        assert result.control_released is True
        assert result.browser_closed is True
        assert result.process_terminated is True

        assert browser.page.closed is True

        assert (
            browser.page.close_loop
            is browser.wrapper_loop
        )

        assert (
            browser.driver.connection.closed
            is True
        )

        assert (
            browser.driver.connection.close_loop
            is browser.root_loop
        )

        assert (
            browser.driver._process.terminated
            is True
        )

        assert (
            browser.driver._process.wait_loop
            is browser.root_loop
        )

        assert (
            session.state
            == BrowserSessionState.CLOSED
        )

        assert session.browser is None

        health = session.health()

        assert (
            health.state
            == BrowserSessionState.CLOSED
        )

        assert (
            health.browser_available
            is False
        )

        assert (
            health.control_available
            is False
        )

    finally:
        browser.dispose_test_loops()


def test_shutdown_close_records_transitions():
    browser = GovernedFakeBrowser()

    session = make_session(
        factory=FactoryProbe(
            result=browser,
        )
    )

    try:
        session.start()

        session.shutdown()

        transitions = (
            session.transition_history
        )

        assert [
            transition.current_state
            for transition in transitions
        ] == [
            BrowserSessionState.STARTING,
            BrowserSessionState.READY,
            BrowserSessionState.STOPPING,
            BrowserSessionState.CLOSED,
        ]

        assert (
            transitions[-2].reason
            == "shutdown_requested"
        )

        assert (
            transitions[-1].reason
            == "shutdown_completed"
        )

    finally:
        browser.dispose_test_loops()


def test_shutdown_close_is_idempotent():
    browser = GovernedFakeBrowser()

    session = make_session(
        factory=FactoryProbe(
            result=browser,
        )
    )

    try:
        session.start()

        first = session.shutdown()
        second = session.shutdown()

        assert second is first

        assert (
            session.state
            == BrowserSessionState.CLOSED
        )

        assert len(
            session.transition_history
        ) == 4

    finally:
        browser.dispose_test_loops()


def test_shutdown_without_start_closes_logically():
    session = make_session()

    result = session.shutdown()

    assert (
        result.state_before
        == BrowserSessionState.CREATED
    )

    assert (
        result.state_after
        == BrowserSessionState.CLOSED
    )

    assert (
        session.state
        == BrowserSessionState.CLOSED
    )

    assert session.browser is None


def test_shutdown_rejects_unimplemented_modes():
    session = make_session()

    for mode in (
        BrowserShutdownMode.DETACH,
        BrowserShutdownMode.KILL,
    ):
        try:
            session.shutdown(
                mode
            )
        except BrowserSessionLifecycleError:
            pass
        else:
            raise AssertionError(
                f"{mode.value} debería rechazarse todavía"
            )


def test_failed_shutdown_can_retry_with_preserved_browser():
    browser = GovernedFakeBrowser()

    session = make_session(
        factory=FactoryProbe(
            result=browser,
        )
    )

    try:
        session.start()

        original_validate = (
            session
            ._validate_shutdown_topology
        )

        calls = {
            "count": 0,
        }

        def flaky_validate(
            target_browser,
        ):
            calls["count"] += 1

            if calls["count"] == 1:
                raise RuntimeError(
                    "transient shutdown failure"
                )

            return original_validate(
                target_browser
            )

        session._validate_shutdown_topology = (
            flaky_validate
        )

        first = session.shutdown(
            BrowserShutdownMode.CLOSE
        )

        assert first.has_error is True

        assert (
            first.state_after
            == BrowserSessionState.FAILED
        )

        assert (
            session.state
            == BrowserSessionState.FAILED
        )

        # Ownership físico debe seguir disponible.
        assert session.browser is browser

        health = session.health()

        assert health.browser_available is True
        assert health.control_available is False

        second = session.shutdown(
            BrowserShutdownMode.CLOSE
        )

        assert second.has_error is False

        assert (
            second.state_before
            == BrowserSessionState.FAILED
        )

        assert (
            second.state_after
            == BrowserSessionState.CLOSED
        )

        assert second.control_released is True
        assert second.browser_closed is True
        assert second.process_terminated is True

        assert (
            session.state
            == BrowserSessionState.CLOSED
        )

        assert session.browser is None

        reasons = [
            transition.reason
            for transition
            in session.transition_history
        ]

        assert (
            "shutdown_failed"
            in reasons
        )

        assert (
            "shutdown_retry_requested"
            in reasons
        )

        assert (
            reasons[-1]
            == "shutdown_completed"
        )

        assert calls["count"] == 2

    finally:
        browser.dispose_test_loops()


def test_start_failure_is_not_shutdown_retryable():
    session = make_session(
        factory=FactoryProbe(
            error=RuntimeError(
                "chrome unavailable"
            )
        )
    )

    try:
        session.start()

    except BrowserSessionLifecycleError:
        pass

    else:
        raise AssertionError(
            "El startup debía fallar"
        )

    assert (
        session.state
        == BrowserSessionState.FAILED
    )

    assert session.browser is None

    try:
        session.shutdown(
            BrowserShutdownMode.CLOSE
        )

    except BrowserSessionLifecycleError:
        pass

    else:
        raise AssertionError(
            "FAILED por start_failed no debe "
            "ser shutdown-retryable"
        )


def test_shutdown_topology_rejects_missing_driver():
    class BrowserWithoutDriver:
        pass

    factory = FactoryProbe(
        result=BrowserWithoutDriver()
    )

    session = make_session(
        factory=factory,
    )

    session.start()

    result = session.shutdown()

    assert result.has_error is True

    assert (
        result.state_after
        == BrowserSessionState.FAILED
    )

    assert (
        "browser"
        in result.error
    )

    assert (
        "driver"
        in result.error
    )


def test_shutdown_topology_rejects_missing_process_transport():
    browser = GovernedFakeBrowser()

    browser.driver._process._transport = None

    session = make_session(
        factory=FactoryProbe(
            result=browser,
        )
    )

    try:
        session.start()

        result = session.shutdown()

        assert result.has_error is True

        assert (
            result.state_after
            == BrowserSessionState.FAILED
        )

        assert (
            "_transport"
            in result.error
        )

    finally:
        browser.dispose_test_loops()


def test_shutdown_topology_rejects_connection_without_aclose():
    class ConnectionWithoutClose:
        def __init__(
            self,
            loop,
        ):
            self.websocket = (
                FakeWebSocket(
                    loop
                )
            )

    browser = GovernedFakeBrowser()

    browser.driver.connection = (
        ConnectionWithoutClose(
            browser.root_loop
        )
    )

    session = make_session(
        factory=FactoryProbe(
            result=browser,
        )
    )

    try:
        session.start()

        result = session.shutdown()

        assert result.has_error is True

        assert (
            "aclose"
            in result.error
        )

    finally:
        browser.dispose_test_loops()


def test_session_adapter_never_calls_stop():
    """
    Regression guard del bug nativo investigado.

    El source puede documentar ``driver.stop()`` en
    docstrings, por lo que el guard debe inspeccionar AST
    y no buscar texto en bruto.
    """

    source_path = (
        Path(__file__)
        .resolve()
        .parents[2]
        / "backend"
        / "automation"
        / "seleniumbase_browser_session.py"
    )

    tree = ast.parse(
        source_path.read_text(
            encoding="utf-8",
        )
    )

    forbidden_calls = []

    for node in ast.walk(
        tree
    ):
        if not isinstance(
            node,
            ast.Call,
        ):
            continue

        function = node.func

        if (
            isinstance(
                function,
                ast.Attribute,
            )
            and function.attr == "stop"
        ):
            forbidden_calls.append(
                node.lineno
            )

    assert forbidden_calls == [], (
        "SeleniumBaseBrowserSession no debe llamar "
        f"a .stop(); líneas: {forbidden_calls}"
    )


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
    test_shutdown_close_uses_resource_owner_loops,
    test_shutdown_close_records_transitions,
    test_shutdown_close_is_idempotent,
    test_shutdown_without_start_closes_logically,
    test_shutdown_rejects_unimplemented_modes,
    test_failed_shutdown_can_retry_with_preserved_browser,
    test_start_failure_is_not_shutdown_retryable,
    test_shutdown_topology_rejects_missing_driver,
    test_shutdown_topology_rejects_missing_process_transport,
    test_shutdown_topology_rejects_connection_without_aclose,
    test_session_adapter_never_calls_stop,
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
