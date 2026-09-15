from pathlib import Path

from backend.qcc.bridge.server import (
    QccBridgeServer,
)
from backend.qcc.client.browser_profile_reporter import (
    QccBrowserProfileReporter,
)
from backend.qcc.context.browser_registry import (
    QccBrowserRegistry,
)


ROOT = Path(__file__).resolve().parents[2]


def _bridge_url(
    bridge,
):
    return (
        f"http://{bridge.host}:"
        f"{bridge.port}"
    )


def test_profile_reporter_registers_persistent_profile():
    bridge = QccBridgeServer(
        port=0
    )

    bridge.start()

    try:
        reporter = QccBrowserProfileReporter(
            browser_profile_key=
                "whatsapp-test",

            browser_session_mode=
                "PERSISTENT",

            bridge_base_url=
                _bridge_url(
                    bridge
                ),
        )

        assert reporter.register() is True

        snapshot = (
            bridge.browser_registry
            .snapshot(
                "whatsapp-test"
            )
        )

        assert (
            snapshot[
                "browser_profile_key"
            ]
            == "whatsapp-test"
        )

        assert (
            snapshot[
                "browser_session_mode"
            ]
            == "PERSISTENT"
        )

    finally:
        bridge.close()


def test_mode_registration_materializes_profile():
    registry = QccBrowserRegistry()

    registry.set_profile_mode(
        profile_key="profile-a",
        mode="PERSISTENT",
    )

    assert (
        registry.profile_keys()
        == (
            "profile-a",
        )
    )


def test_profile_reporter_is_fail_open_without_bridge():
    reporter = QccBrowserProfileReporter(
        browser_profile_key="profile-a",
        browser_session_mode="PERSISTENT",
        bridge_base_url=(
            "http://127.0.0.1:1"
        ),
        timeout=0.01,
    )

    assert reporter.register() is False


def test_whatsapp_reports_real_browser_session_identity():
    source = (
        ROOT
        / "backend"
        / "automation"
        / "connectors"
        / "whatsapp_connector.py"
    ).read_text(
        encoding="utf-8"
    )

    start = source.index(
        "    def start(self):"
    )

    block = source[
        start:
        start + 2600
    ]

    assert (
        "QCC_BROWSER_PROFILE_REGISTRATION_V1"
        in block
    )

    assert (
        "session.identity.profile_key"
        in block
    )

    assert (
        "session.identity.mode"
        in block
    )

    assert (
        '"PERSISTENT"'
        not in block
    )


def test_dehu_reports_real_browser_session_identity():
    source = (
        ROOT
        / "backend"
        / "automation"
        / "connectors"
        / "dehu_connector.py"
    ).read_text(
        encoding="utf-8"
    )

    start = source.index(
        "    def start("
    )

    block = source[
        start:
        start + 2600
    ]

    assert (
        "QCC_BROWSER_PROFILE_REGISTRATION_V1"
        in block
    )

    assert (
        "session.identity.profile_key"
        in block
    )

    assert (
        "session.identity.mode"
        in block
    )

    assert (
        '"PERSISTENT"'
        not in block
    )


def test_generic_profile_route_exists():
    source = (
        ROOT
        / "backend"
        / "qcc"
        / "bridge"
        / "server.py"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        'if path == "/qcc/browser-profile":'
        in source
    )
