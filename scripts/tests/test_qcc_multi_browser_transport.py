from types import SimpleNamespace

from backend.qcc.bridge.server import (
    QccBridgeServer,
)
from backend.qcc.client.presentation_reporter import (
    QccPresentationReporter,
)

from app import run_presentacion_asistida as runner


def _bridge_url(
    bridge,
):
    return (
        f"http://{bridge.host}:"
        f"{bridge.port}"
    )


def _reporter(
    bridge,
    *,
    session_id,
    profile_key=None,
):
    return QccPresentationReporter(
        session_id=session_id,
        expedient_id=1,
        client_id=1,
        procedure="TEST",
        provider="TEST",
        runtime="SELENIUMBASE",
        browser_profile_key=profile_key,
        bridge_base_url=(
            _bridge_url(
                bridge
            )
        ),
    )


def test_reporter_registers_exact_browser_profile():
    bridge = QccBridgeServer(
        port=0,
    )

    bridge.start()

    try:
        reporter = _reporter(
            bridge,
            session_id="session-a",
            profile_key="profile-a",
        )

        assert reporter.started() is True

        snapshot = (
            bridge.browser_registry
            .snapshot(
                "profile-a"
            )
        )

        assert snapshot["active"] is True

        assert (
            snapshot["active_session"][
                "session_id"
            ]
            == "session-a"
        )

        assert (
            snapshot[
                "browser_profile_key"
            ]
            == "profile-a"
        )

    finally:
        bridge.close()


def test_two_reporters_remain_active_in_two_profiles():
    bridge = QccBridgeServer(
        port=0,
    )

    bridge.start()

    try:
        first = _reporter(
            bridge,
            session_id="session-a",
            profile_key="profile-a",
        )

        second = _reporter(
            bridge,
            session_id="session-b",
            profile_key="profile-b",
        )

        assert first.started() is True
        assert second.started() is True

        first_snapshot = (
            bridge.browser_registry
            .snapshot(
                "profile-a"
            )
        )

        second_snapshot = (
            bridge.browser_registry
            .snapshot(
                "profile-b"
            )
        )

        assert (
            first_snapshot[
                "active_session"
            ]["session_id"]
            == "session-a"
        )

        assert (
            second_snapshot[
                "active_session"
            ]["session_id"]
            == "session-b"
        )

        # Legacy sigue siendo una proyección
        # backward-compatible de la última
        # sesión publicada.
        legacy = (
            bridge.context_store
            .snapshot()
        )

        assert (
            legacy[
                "active_session"
            ]["session_id"]
            == "session-b"
        )

    finally:
        bridge.close()


def test_updating_second_profile_does_not_remove_first():
    bridge = QccBridgeServer(
        port=0,
    )

    bridge.start()

    try:
        first = _reporter(
            bridge,
            session_id="session-a",
            profile_key="profile-a",
        )

        second = _reporter(
            bridge,
            session_id="session-b",
            profile_key="profile-b",
        )

        assert first.started() is True
        assert second.started() is True

        assert second.automating(
            step="SECOND_UPDATE",
            progress=25,
            message="Actualización B",
        ) is True

        snapshot_a = (
            bridge.browser_registry
            .snapshot(
                "profile-a"
            )
        )

        snapshot_b = (
            bridge.browser_registry
            .snapshot(
                "profile-b"
            )
        )

        assert (
            snapshot_a[
                "active_session"
            ]["session_id"]
            == "session-a"
        )

        assert (
            snapshot_b[
                "active_session"
            ]["session_id"]
            == "session-b"
        )

        assert (
            snapshot_b[
                "active_session"
            ]["progress"]
            == 25
        )

    finally:
        bridge.close()


def test_legacy_reporter_without_profile_remains_supported():
    bridge = QccBridgeServer(
        port=0,
    )

    bridge.start()

    try:
        reporter = _reporter(
            bridge,
            session_id="legacy-session",
            profile_key=None,
        )

        assert reporter.started() is True

        legacy = (
            bridge.context_store
            .snapshot()
        )

        assert (
            legacy[
                "active_session"
            ]["session_id"]
            == "legacy-session"
        )

        assert (
            bridge.browser_registry
            .profile_keys()
            == ()
        )

    finally:
        bridge.close()


def test_runner_passes_browser_profile_key_to_reporter(
    tmp_path,
):
    args = SimpleNamespace(
        qcc_session_id="runner-session",
        expediente_id="1842",
        cliente_id="321",
        tipo="TEST",
        browser_profile_key=(
            "qcc_assisted"
        ),
    )

    reporter = (
        runner.build_qcc_reporter(
            args,
            str(tmp_path),
        )
    )

    assert reporter is not None

    assert (
        reporter.browser_profile_key
        == "qcc_assisted"
    )


def test_runner_keeps_reporter_compatible_without_profile(
    tmp_path,
):
    args = SimpleNamespace(
        qcc_session_id="runner-legacy",
        expediente_id="1842",
        cliente_id="321",
        tipo="TEST",
    )

    reporter = (
        runner.build_qcc_reporter(
            args,
            str(tmp_path),
        )
    )

    assert reporter is not None

    assert (
        reporter.browser_profile_key
        is None
    )
