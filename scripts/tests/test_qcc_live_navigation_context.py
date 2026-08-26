from datetime import (
    datetime,
    timezone,
)

import pytest

from backend.qcc.context.store import (
    QccContextStore,
)
from backend.qcc.contracts.live_navigation import (
    QCC_LIVE_NAVIGATION_SCHEMA_VERSION,
    QCC_LIVE_NAVIGATION_TYPE,
    QccLiveNavigationContext,
)
from backend.qcc.contracts.protocol import (
    QccPresentationSession,
    QccPresentationStatus,
)


def _session(
    session_id="live-nav-001",
):
    return QccPresentationSession(
        session_id=session_id,
        expedient_id=1,
        client_id=1,
        procedure="TEST",
        provider="TEST_PROVIDER",
        runtime="TEST_RUNTIME",
        started_at=datetime(
            2026,
            8,
            26,
            8,
            0,
            tzinfo=timezone.utc,
        ),
        status=(
            QccPresentationStatus
            .AUTOMATING
        ),
        current_step="TEST",
        progress=10,
        requires_user_action=False,
    )


def _navigation(
    session_id="live-nav-001",
):
    return QccLiveNavigationContext(
        session_id=session_id,
        updated_at=datetime(
            2026,
            8,
            26,
            8,
            1,
            tzinfo=timezone.utc,
        ),

        current_state="STATE_A",
        current_fingerprint="fp-a",

        target_state="STATE_B",
        target_fingerprint="fp-b",

        route_reachable=True,
        remaining_steps=1,

        next_step_kind="BUTTON",
        next_step_policy="NAVIGATION",
        next_step_selector="#continue",
        next_step_frame_path=("main",),
        next_step_confidence=0.98,

        governance_decision="HUMAN_ONLY",
        governance_reason="SITE_POLICY",
        automation_allowed=False,

        display_title="Acción manual requerida",
        display_instruction=(
            "Continúa manualmente para avanzar."
        ),
    )


def test_live_navigation_contract_payload():
    payload = _navigation().to_payload()

    assert payload[
        "schema_version"
    ] == QCC_LIVE_NAVIGATION_SCHEMA_VERSION

    assert payload[
        "context_type"
    ] == QCC_LIVE_NAVIGATION_TYPE

    assert payload[
        "session_id"
    ] == "live-nav-001"

    assert payload["current"] == {
        "state": "STATE_A",
        "fingerprint": "fp-a",
    }

    assert payload["target"] == {
        "state": "STATE_B",
        "fingerprint": "fp-b",
    }

    assert payload["route"] == {
        "reachable": True,
        "remaining_steps": 1,
    }

    assert payload[
        "next_step"
    ]["selector"] == "#continue"

    assert payload[
        "governance"
    ]["decision"] == "HUMAN_ONLY"

    assert payload[
        "governance"
    ]["automation_allowed"] is False


def test_live_navigation_round_trip():
    original = _navigation()

    restored = (
        QccLiveNavigationContext
        .from_payload(
            original.to_payload()
        )
    )

    assert restored == original


def test_live_navigation_rejects_unknown_top_level_data():
    payload = _navigation().to_payload()

    payload["dom"] = "<html>secret</html>"

    with pytest.raises(
        ValueError,
        match=(
            "QCC_LIVE_NAVIGATION_FIELD_NOT_ALLOWED"
        ),
    ):
        QccLiveNavigationContext.from_payload(
            payload
        )


def test_live_navigation_rejects_unknown_nested_data():
    payload = _navigation().to_payload()

    payload["next_step"]["text"] = (
        "sensitive DOM text"
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_LIVE_NAVIGATION_FIELD_NOT_ALLOWED"
        ),
    ):
        QccLiveNavigationContext.from_payload(
            payload
        )


def test_store_requires_matching_active_session():
    store = QccContextStore()

    store.set_active_session(
        _session(
            "session-a"
        )
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_LIVE_NAVIGATION_SESSION_NOT_ACTIVE"
        ),
    ):
        store.set_live_navigation(
            _navigation(
                "session-b"
            )
        )


def test_store_projects_live_navigation():
    store = QccContextStore()

    store.set_active_session(
        _session()
    )

    revision = (
        store.set_live_navigation(
            _navigation()
        )
    )

    assert revision == 2

    snapshot = store.snapshot()

    assert (
        snapshot[
            "live_navigation"
        ][
            "current"
        ][
            "state"
        ]
        == "STATE_A"
    )

    assert (
        snapshot[
            "live_navigation"
        ][
            "governance"
        ][
            "decision"
        ]
        == "HUMAN_ONLY"
    )


def test_same_session_update_preserves_navigation():
    store = QccContextStore()

    store.set_active_session(
        _session()
    )

    store.set_live_navigation(
        _navigation()
    )

    store.set_active_session(
        _session()
    )

    assert (
        store.get_live_navigation()
        is not None
    )

    assert (
        store.snapshot()[
            "live_navigation"
        ][
            "session_id"
        ]
        == "live-nav-001"
    )


def test_new_session_clears_previous_navigation():
    store = QccContextStore()

    store.set_active_session(
        _session(
            "session-a"
        )
    )

    store.set_live_navigation(
        _navigation(
            "session-a"
        )
    )

    store.set_active_session(
        _session(
            "session-b"
        )
    )

    assert (
        store.get_live_navigation()
        is None
    )

    assert (
        store.snapshot()[
            "live_navigation"
        ]
        is None
    )


def test_clearing_session_clears_navigation_atomically():
    store = QccContextStore()

    store.set_active_session(
        _session()
    )

    store.set_live_navigation(
        _navigation()
    )

    assert (
        store.clear_active_session(
            session_id="live-nav-001"
        )
        is True
    )

    snapshot = store.snapshot()

    assert snapshot["active"] is False

    assert (
        snapshot["active_session"]
        is None
    )

    assert (
        snapshot["live_navigation"]
        is None
    )


def test_old_session_cannot_clear_new_navigation():
    store = QccContextStore()

    store.set_active_session(
        _session(
            "new-session"
        )
    )

    store.set_live_navigation(
        _navigation(
            "new-session"
        )
    )

    assert (
        store.clear_live_navigation(
            session_id="old-session"
        )
        is False
    )

    assert (
        store.get_live_navigation()
        is not None
    )


def test_contract_has_no_provider_coupling():
    from pathlib import Path

    source = Path(
        "backend/qcc/contracts/"
        "live_navigation.py"
    ).read_text(
        encoding="utf-8"
    )

    assert "MERCURIO" not in source
    assert "ICP_PLUS" not in source
    assert "SELENIUMBASE" not in source
    assert "DESKTOP_GUI" not in source
