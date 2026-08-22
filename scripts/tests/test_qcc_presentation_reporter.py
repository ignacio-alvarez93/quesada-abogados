from backend.qcc.bridge.server import (
    QccBridgeServer,
)
from backend.qcc.client.presentation_reporter import (
    QccPresentationReporter,
)


def _reporter(
    server,
):
    return QccPresentationReporter(
        session_id="qcc-reporter-001",
        expedient_id=1842,
        client_id=321,
        procedure=(
            "REAGRUPACION_FAMILIAR_INICIAL"
        ),
        provider="MERCURIO",
        runtime="SELENIUMBASE_ASSISTED",
        bridge_base_url=(
            f"http://{server.host}:"
            f"{server.port}"
        ),
    )


def test_reporter_publishes_started_session():
    server = QccBridgeServer(
        port=0,
    )

    server.start()

    try:
        reporter = _reporter(
            server
        )

        assert reporter.started() is True

        snapshot = (
            server.context_store
            .snapshot()
        )

        assert snapshot["active"] is True

        active = snapshot[
            "active_session"
        ]

        assert (
            active["session_id"]
            == "qcc-reporter-001"
        )

        assert (
            active["runtime"]
            == "SELENIUMBASE_ASSISTED"
        )

    finally:
        server.close()


def test_reporter_tracks_human_transition():
    server = QccBridgeServer(
        port=0,
    )

    server.start()

    try:
        reporter = _reporter(
            server
        )

        assert reporter.waiting_user(
            step="CERTIFICATE",
            progress=15,
            message=(
                "Seleccione certificado"
            ),
        ) is True

        active = (
            server.context_store
            .snapshot()[
                "active_session"
            ]
        )

        assert (
            active["status"]
            == "WAITING_USER"
        )

        assert (
            active[
                "requires_user_action"
            ]
            is True
        )

        assert (
            reporter
            .user_action_detected(
                step="CERTIFICATE",
                progress=18,
            )
            is True
        )

        active = (
            server.context_store
            .snapshot()[
                "active_session"
            ]
        )

        assert (
            active["status"]
            == "USER_ACTION_DETECTED"
        )

    finally:
        server.close()


def test_reporter_tracks_completion():
    server = QccBridgeServer(
        port=0,
    )

    server.start()

    try:
        reporter = _reporter(
            server
        )

        reporter.started()

        assert (
            reporter.completed()
            is True
        )

        active = (
            server.context_store
            .snapshot()[
                "active_session"
            ]
        )

        assert (
            active["status"]
            == "COMPLETED"
        )

        assert (
            active["progress"]
            == 100
        )

    finally:
        server.close()


def test_reporter_is_fail_open_without_bridge():
    server = QccBridgeServer(
        port=0,
    )

    port = server.port

    server.close()

    reporter = (
        QccPresentationReporter(
            session_id=(
                "qcc-no-bridge-001"
            ),
            expedient_id=1842,
            client_id=321,
            procedure="TEST",
            provider="MERCURIO",
            runtime=(
                "SELENIUMBASE_ASSISTED"
            ),
            bridge_base_url=(
                "http://127.0.0.1:"
                f"{port}"
            ),
            timeout=0.1,
        )
    )

    # Fundamental:
    # QCC caído NO rompe el runtime.
    assert (
        reporter.started()
        is False
    )

    assert (
        reporter.automating(
            step="TEST",
            progress=20,
            message="Continuando",
        )
        is False
    )
