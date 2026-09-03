from types import SimpleNamespace

import pytest

from app import run_presentacion_asistida as runner
from backend.qcc.bridge.server import (
    QccBridgeServer,
)
from backend.qcc.client.presentation_reporter import (
    QccPresentationReporter,
)
from backend.qcc.context.browser_registry import (
    QccBrowserRegistry,
)


def _bridge_url(
    bridge,
):
    return (
        f"http://{bridge.host}:"
        f"{bridge.port}"
    )


def test_registry_accepts_explicit_modes():
    registry = QccBrowserRegistry()

    for mode in (
        "ASSISTED",
        "PERSISTENT",
        "EPHEMERAL",
    ):
        registry.set_profile_mode(
            profile_key=f"profile-{mode}",
            mode=mode,
        )

        assert (
            registry.get_profile_mode(
                f"profile-{mode}"
            )
            == mode
        )


def test_registry_rejects_unknown_mode():
    registry = QccBrowserRegistry()

    with pytest.raises(
        ValueError,
        match="QCC_BROWSER_SESSION_MODE_INVALID",
    ):
        registry.set_profile_mode(
            profile_key="profile-a",
            mode="MONITOR",
        )


def test_reporter_transports_mode_to_registry():
    bridge = QccBridgeServer(
        port=0
    )

    bridge.start()

    try:
        reporter = QccPresentationReporter(
            session_id="session-a",
            expedient_id=1,
            client_id=1,
            procedure="TEST",
            provider="TEST",
            runtime="SELENIUMBASE",
            browser_profile_key="profile-a",
            browser_session_mode="ASSISTED",
            bridge_base_url=_bridge_url(
                bridge
            ),
        )

        assert reporter.started() is True

        snapshot = (
            bridge.browser_registry
            .snapshot(
                "profile-a"
            )
        )

        assert (
            snapshot[
                "browser_session_mode"
            ]
            == "ASSISTED"
        )

    finally:
        bridge.close()


def test_runner_declares_mercurio_assisted(
    tmp_path,
):
    args = SimpleNamespace(
        qcc_session_id="runner-session",
        expediente_id="1842",
        cliente_id="321",
        tipo="TEST",
        browser_profile_key="qcc_assisted",
    )

    reporter = runner.build_qcc_reporter(
        args,
        str(tmp_path),
    )

    assert reporter is not None

    assert (
        reporter.browser_session_mode
        == "ASSISTED"
    )


def test_legacy_reporter_remains_supported():
    reporter = QccPresentationReporter(
        session_id="legacy",
        expedient_id=1,
        client_id=1,
        procedure="TEST",
        provider="TEST",
        runtime="SELENIUMBASE",
    )

    assert (
        reporter.browser_session_mode
        is None
    )


def test_browser_list_exposes_session_mode():
    from pathlib import Path

    source = Path(
        "backend/qcc/bridge/server.py"
    ).read_text(
        encoding="utf-8"
    )

    start = source.index(
        'if path == "/qcc/browsers":'
    )

    end = source.index(
        'if path == "/qcc/context"',
        start,
    ) if (
        'if path == "/qcc/context"'
        in source[start:]
    ) else start + 7000

    block = source[
        start:end
    ]

    assert (
        '"browser_session_mode"'
        in block
    )
