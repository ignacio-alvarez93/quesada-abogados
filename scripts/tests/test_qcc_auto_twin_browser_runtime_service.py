from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.automation.browser_contracts import (
    BrowserSessionMode,
)
from backend.services.twin_browser_runtime_service import (
    TwinBrowserRuntimeService,
)


class FakeLocalRuntime:
    def __init__(self):
        self.running = None
        self.stops = 0

    def get_status(
        self,
        *,
        twin_key,
    ):
        if self.running is None:
            return {
                "twin_key": twin_key,
                "status": "STOPPED",
                "revision_id": None,
                "base_url": None,
            }

        return dict(
            self.running
        )

    def start(
        self,
        *,
        twin_key,
        revision_id,
    ):
        self.running = {
            "twin_key":
                twin_key,

            "status":
                "RUNNING",

            "revision_id":
                revision_id,

            "base_url":
                "http://127.0.0.1:45678",
        }

        return dict(
            self.running
        )

    def stop(
        self,
        *,
        twin_key,
    ):
        self.stops += 1
        self.running = None

        return {
            "twin_key":
                twin_key,

            "status":
                "STOPPED",
        }


class FakeShutdownResult:
    has_error = False
    error = None


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

        self.identity = SimpleNamespace(
            profile_key=(
                config.profile_key
            ),
            mode=config.mode,
        )

        self.browser = object()
        self.shutdown_modes = []

    def start(self):
        return self.browser

    def shutdown(
        self,
        mode,
    ):
        self.shutdown_modes.append(
            mode
        )

        return FakeShutdownResult()


class FakeReporter:
    def __init__(
        self,
        **kwargs,
    ):
        self.kwargs = kwargs

    def register(self):
        return True


def _revision(
    root,
):
    revision = (
        root
        / "red_sara"
        / "matrev-test-v2"
    )

    registry = (
        revision
        / "runtime"
        / "registry.json"
    )

    registry.parent.mkdir(
        parents=True
    )

    registry.write_text(
        """{
  "states": [
    {
      "state_id": "AUTO_A",
      "pathname": "/es/",
      "runtime_entry": "states/00-AUTO_A/runtime/index.html"
    },
    {
      "state_id": "AUTO_B",
      "pathname": "/es/nuevo-registro",
      "runtime_entry": "states/01-AUTO_B/runtime/index.html"
    },
    {
      "state_id": "AUTO_C",
      "pathname": "/es/nuevo-registro",
      "runtime_entry": "states/02-AUTO_C/runtime/index.html"
    }
  ]
}
""",
        encoding="utf-8",
    )

    return revision


def test_twin_browser_runtime_uses_seleniumbase_persistent_owner(
    tmp_path,
):
    _revision(
        tmp_path
    )

    local = FakeLocalRuntime()

    opened = []
    sessions = []

    def session_factory(
        *,
        config,
        profile_resolver,
    ):
        session = FakeSession(
            config=config,
            profile_resolver=(
                profile_resolver
            ),
        )

        sessions.append(
            session
        )

        return session

    def browser_open(
        browser,
        url,
    ):
        opened.append(
            (
                browser,
                url,
            )
        )

    service = TwinBrowserRuntimeService(
        materialized_root=tmp_path,
        local_runtime_service=local,
        browser_session_factory=(
            session_factory
        ),
        profile_resolver=(
            lambda key:
                tmp_path
                / "profiles"
                / key
        ),
        browser_open=browser_open,
        reporter_factory=FakeReporter,
    )

    result = service.start(
        twin_key="red_sara",
        revision_id="matrev-test-v2",
        pathname="/es/nuevo-registro",
    )

    assert result[
        "status"
    ] == "RUNNING"

    assert result[
        "revision_id"
    ] == "matrev-test-v2"

    assert result[
        "pathname"
    ] == "/es/nuevo-registro"

    assert result[
        "profile_key"
    ] == "twin_runtime_red_sara"

    assert result[
        "browser_session_mode"
    ] == "PERSISTENT"

    assert result[
        "qcc_registered"
    ] is True

    assert len(
        sessions
    ) == 1

    assert (
        sessions[0]
        .config
        .mode
        == BrowserSessionMode.PERSISTENT
    )

    assert (
        sessions[0]
        .config
        .consumer
        == "auto_twin_runtime"
    )

    assert opened[
        0
    ][1] == (
        "http://127.0.0.1:45678/"
        "states/01-AUTO_B/runtime/index.html"
    )

    stopped = service.stop(
        twin_key="red_sara"
    )

    assert stopped[
        "status"
    ] == "STOPPED"

    assert local.stops == 1


def test_twin_browser_runtime_rejects_unknown_pathname(
    tmp_path,
):
    _revision(
        tmp_path
    )

    service = TwinBrowserRuntimeService(
        materialized_root=tmp_path,
        local_runtime_service=(
            FakeLocalRuntime()
        ),
        profile_resolver=(
            lambda key:
                tmp_path
                / "profiles"
                / key
        ),
    )

    try:
        service.start(
            twin_key="red_sara",
            revision_id="matrev-test-v2",
            pathname="/no-existe",
        )

    except KeyError as exc:
        assert (
            "QCC_AUTO_TWIN_BROWSER_PATHNAME_NOT_FOUND"
            in str(exc)
        )

    else:
        raise AssertionError(
            "Expected KeyError"
        )


def _exact_state_runtime_service(
    tmp_path,
    opened,
):
    local = FakeLocalRuntime()

    def session_factory(
        *,
        config,
        profile_resolver,
    ):
        return FakeSession(
            config=config,
            profile_resolver=profile_resolver,
        )

    def browser_open(
        browser,
        url,
    ):
        opened.append(
            url
        )

    return TwinBrowserRuntimeService(
        materialized_root=tmp_path,
        local_runtime_service=local,
        browser_session_factory=session_factory,
        profile_resolver=(
            lambda key:
                tmp_path
                / "profiles"
                / key
        ),
        browser_open=browser_open,
        reporter_factory=FakeReporter,
    )


def test_twin_browser_runtime_state_id_selects_exact_physical_state(
    tmp_path,
):
    _revision(
        tmp_path
    )

    opened = []

    service = (
        _exact_state_runtime_service(
            tmp_path,
            opened,
        )
    )

    try:
        result = service.start(
            twin_key="red_sara",
            revision_id="matrev-test-v2",
            state_id="AUTO_C",
        )

        assert result[
            "status"
        ] == "RUNNING"

        assert result[
            "pathname"
        ] == "/es/nuevo-registro"

        assert opened == [
            (
                "http://127.0.0.1:45678/"
                "states/02-AUTO_C/runtime/index.html"
            )
        ]

    finally:
        service.stop(
            twin_key="red_sara"
        )


def test_twin_browser_runtime_state_id_pathname_mismatch_fails_closed(
    tmp_path,
):
    _revision(
        tmp_path
    )

    service = (
        _exact_state_runtime_service(
            tmp_path,
            [],
        )
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_BROWSER_"
            "STATE_ID_PATHNAME_MISMATCH"
        ),
    ):
        service.start(
            twin_key="red_sara",
            revision_id="matrev-test-v2",
            state_id="AUTO_C",
            pathname="/es/",
        )


def test_twin_browser_runtime_same_pathname_different_state_id_not_idempotent(
    tmp_path,
):
    _revision(
        tmp_path
    )

    service = (
        _exact_state_runtime_service(
            tmp_path,
            [],
        )
    )

    try:
        service.start(
            twin_key="red_sara",
            revision_id="matrev-test-v2",
            state_id="AUTO_B",
        )

        with pytest.raises(
            RuntimeError,
            match=(
                "QCC_AUTO_TWIN_BROWSER_"
                "ALREADY_RUNNING"
            ),
        ):
            service.start(
                twin_key="red_sara",
                revision_id="matrev-test-v2",
                state_id="AUTO_C",
            )

    finally:
        service.stop(
            twin_key="red_sara"
        )
