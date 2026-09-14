import threading
from types import SimpleNamespace

from backend.automation.browser_contracts import (
    BrowserSessionMode,
    BrowserShutdownMode,
)

from backend.services.twin_discovery_runtime_service import (
    MERCURIO_DISCOVERY_URL,
    TwinDiscoveryRuntimeService,
)


class FakeShutdownResult:
    has_error = False


class FakeSession:
    def __init__(
        self,
        *,
        config,
        profile_resolver,
    ):
        self.config = config

        self.profile_resolver = (
            profile_resolver
        )

        self.identity = (
            SimpleNamespace(
                profile_key=(
                    config.profile_key
                ),
                mode=(
                    config.mode
                ),
            )
        )

        self.browser = object()

        self.start_thread_id = None
        self.shutdown_thread_id = None
        self.shutdown_mode = None

    def start(
        self,
    ):
        self.start_thread_id = (
            threading.get_ident()
        )

        self.profile_resolver(
            self.config.profile_key
        )

        return self.browser

    def shutdown(
        self,
        mode,
    ):
        self.shutdown_thread_id = (
            threading.get_ident()
        )

        self.shutdown_mode = mode

        return FakeShutdownResult()


class FakeReporter:
    def __init__(
        self,
        *,
        browser_profile_key,
        browser_session_mode,
    ):
        self.profile_key = (
            browser_profile_key
        )

        self.mode = (
            browser_session_mode
        )

    def register(
        self,
    ):
        return True


def _service(
    *,
    sessions,
    opened,
):
    def factory(
        **kwargs,
    ):
        session = FakeSession(
            **kwargs
        )

        sessions.append(
            session
        )

        return session

    return TwinDiscoveryRuntimeService(
        browser_session_factory=factory,

        profile_resolver=(
            lambda key:
                f"/profiles/{key}"
        ),

        browser_open=(
            lambda browser, url:
                opened.append(
                    (
                        browser,
                        url,
                        threading.get_ident(),
                    )
                )
        ),

        reporter_factory=(
            FakeReporter
        ),
    )


def test_mercurio_discovery_is_site_level_persistent():
    sessions = []
    opened = []

    service = _service(
        sessions=sessions,
        opened=opened,
    )

    result = service.start(
        twin_key="mercurio"
    )

    session = sessions[0]

    assert (
        session.config.consumer
        == "auto_twin_discovery"
    )

    assert (
        session.config.mode
        == BrowserSessionMode.PERSISTENT
    )

    assert (
        session.config.profile_key
        == "twin_discovery"
    )

    assert (
        session.config.headless
        is False
    )

    assert opened[
        0
    ][0:2] == (
        session.browser,
        MERCURIO_DISCOVERY_URL,
    )

    assert (
        result[
            "status"
        ]
        == "RUNNING"
    )

    assert (
        result[
            "qcc_registered"
        ]
        is True
    )

    assert (
        result[
            "qcc_extension_mode"
        ]
        == "MANUAL_PERSISTENT"
    )

    service.stop(
        twin_key="mercurio"
    )


def test_browser_start_runs_outside_caller_thread():
    sessions = []
    opened = []

    caller_thread_id = (
        threading.get_ident()
    )

    service = _service(
        sessions=sessions,
        opened=opened,
    )

    result = service.start(
        twin_key="mercurio"
    )

    session = sessions[0]

    assert (
        result[
            "owner_thread_alive"
        ]
        is True
    )

    assert (
        session.start_thread_id
        != caller_thread_id
    )

    assert (
        result[
            "owner_thread_id"
        ]
        == session.start_thread_id
    )

    service.stop(
        twin_key="mercurio"
    )


def test_navigation_runs_on_browser_owner_thread():
    sessions = []
    opened = []

    service = _service(
        sessions=sessions,
        opened=opened,
    )

    result = service.start(
        twin_key="mercurio"
    )

    session = sessions[0]

    assert (
        opened[
            0
        ][2]
        == session.start_thread_id
    )

    assert (
        result[
            "owner_thread_id"
        ]
        == opened[
            0
        ][2]
    )

    service.stop(
        twin_key="mercurio"
    )


def test_shutdown_runs_on_same_owner_thread_as_start():
    sessions = []
    opened = []

    service = _service(
        sessions=sessions,
        opened=opened,
    )

    service.start(
        twin_key="mercurio"
    )

    result = service.stop(
        twin_key="mercurio"
    )

    session = sessions[0]

    assert (
        session.shutdown_mode
        == BrowserShutdownMode.CLOSE
    )

    assert (
        session.shutdown_thread_id
        == session.start_thread_id
    )

    assert (
        result[
            "status"
        ]
        == "STOPPED"
    )


def test_discovery_start_is_idempotent():
    sessions = []
    opened = []

    service = _service(
        sessions=sessions,
        opened=opened,
    )

    first = service.start(
        twin_key="mercurio"
    )

    second = service.start(
        twin_key="mercurio"
    )

    assert (
        len(
            sessions
        )
        == 1
    )

    assert (
        first[
            "owner_thread_id"
        ]
        == second[
            "owner_thread_id"
        ]
    )

    service.stop(
        twin_key="mercurio"
    )


def test_runtime_contains_no_procedure_configuration():
    import inspect

    source = inspect.getsource(
        TwinDiscoveryRuntimeService
    )

    forbidden = (
        "procedure_code=",
        "flow_variant=",
        "expediente_id=",
        "datos_mercurio_json",
        "mapper_codigo",
        "run_auto_with_qcc",
    )

    for token in forbidden:
        assert token not in source
