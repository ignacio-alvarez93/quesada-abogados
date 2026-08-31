from datetime import (
    datetime,
    timedelta,
    timezone,
)

import pytest

from backend.qcc.context.live_action_evidence import (
    QccCanonicalLiveAction,
    QccLiveActionEvidence,
)
from backend.qcc.context.store import (
    QccContextStore,
)
from backend.qcc.contracts.live_navigation import (
    QccLiveNavigationContext,
)
from backend.qcc.contracts.protocol import (
    QccPresentationSession,
    QccPresentationStatus,
)


NOW = datetime(
    2026,
    8,
    31,
    10,
    30,
    tzinfo=timezone.utc,
)

FP_A = "a" * 64
FP_B = "b" * 64


def _session(
    session_id="session-1",
):
    return QccPresentationSession(
        session_id=session_id,
        expedient_id=1,
        client_id=1,
        procedure="TEST",
        provider="MERCURIO",
        runtime="SELENIUMBASE_ASSISTED",
        started_at=NOW,
        status=(
            QccPresentationStatus
            .WAITING_USER
        ),
        current_step="TEST",
        progress=50,
        requires_user_action=True,
    )


def _navigation(
    *,
    session_id="session-1",
    fingerprint=FP_A,
    state="STATE_A",
):
    return QccLiveNavigationContext(
        session_id=session_id,
        updated_at=NOW,
        current_state=state,
        current_fingerprint=fingerprint,
    )


def _action(
    selector="#continuar",
):
    return {
        "kind":
            "BUTTON",

        "policy":
            "REQUIRES_POLICY",

        "selector":
            selector,

        "frame_path":
            "main",

        "visible":
            True,

        "disabled":
            False,

        "in_viewport":
            True,

        "opacity":
            1.0,

        "pointer_events":
            "auto",
    }


def _evidence(
    *,
    environment="REAL",
    fingerprint=FP_A,
    state="STATE_A",
    captured_at=NOW,
    actions=None,
):
    return QccLiveActionEvidence(
        session_id="session-1",
        site_code="MERCURIO",
        environment=environment,
        before_state=state,
        before_fingerprint=fingerprint,
        actions=tuple(
            actions
            if actions is not None
            else (
                _action(),
            )
        ),
        captured_at=captured_at,
    )


def _ready_store():
    store = QccContextStore()

    store.set_active_session(
        _session()
    )

    store.set_live_navigation(
        _navigation()
    )

    store.set_navigation_environment(
        "REAL",
        session_id="session-1",
    )

    return store


def test_action_is_normalized_from_backend_mapping():
    action = (
        QccCanonicalLiveAction
        .from_action(
            {
                "kind":
                    " button ",

                "policy":
                    " requires_policy ",

                "selector":
                    " #continuar ",

                "frame_path":
                    " main ",

                "visible":
                    True,

                "disabled":
                    False,
            }
        )
    )

    assert action.kind == "BUTTON"
    assert (
        action.policy
        == "REQUIRES_POLICY"
    )
    assert (
        action.selector
        == "#continuar"
    )
    assert (
        action.frame_path
        == "main"
    )


def test_evidence_finds_by_selector_and_frame_not_policy():
    evidence = _evidence(
        actions=(
            _action(
                "#continuar"
            ),
            {
                **_action(
                    "#otra"
                ),
                "policy":
                    "STATE_CHANGE_CANDIDATE",
            },
        )
    )

    matches = (
        evidence.candidates_for(
            selector="#continuar",
            frame_path="main",
        )
    )

    assert len(matches) == 1

    assert (
        matches[0].policy
        == "REQUIRES_POLICY"
    )


def test_store_requires_active_session():
    store = QccContextStore()

    with pytest.raises(
        ValueError,
        match=(
            "QCC_LIVE_ACTION_EVIDENCE_SESSION_NOT_ACTIVE"
        ),
    ):
        store.set_live_action_evidence(
            _evidence()
        )


def test_store_requires_current():
    store = QccContextStore()

    store.set_active_session(
        _session()
    )

    store.set_navigation_environment(
        "REAL",
        session_id="session-1",
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_LIVE_ACTION_EVIDENCE_CURRENT_REQUIRED"
        ),
    ):
        store.set_live_action_evidence(
            _evidence()
        )


def test_store_rejects_environment_mismatch():
    store = _ready_store()

    with pytest.raises(
        ValueError,
        match=(
            "QCC_LIVE_ACTION_EVIDENCE_ENVIRONMENT_MISMATCH"
        ),
    ):
        store.set_live_action_evidence(
            _evidence(
                environment="LAB"
            )
        )


def test_store_rejects_wrong_current_fingerprint():
    store = _ready_store()

    with pytest.raises(
        ValueError,
        match=(
            "QCC_LIVE_ACTION_EVIDENCE_FINGERPRINT_MISMATCH"
        ),
    ):
        store.set_live_action_evidence(
            _evidence(
                fingerprint=FP_B
            )
        )


def test_runtime_evidence_does_not_change_public_revision():
    store = _ready_store()

    revision = store.revision
    snapshot = store.snapshot()

    store.set_live_action_evidence(
        _evidence()
    )

    assert store.revision == revision
    assert store.snapshot() == snapshot

    serialized = str(
        store.snapshot()
    )

    assert (
        "live_action_evidence"
        not in serialized
    )

    assert (
        "#continuar"
        not in serialized
    )


def test_evidence_expires():
    store = _ready_store()

    store.set_live_action_evidence(
        _evidence(
            captured_at=NOW
        )
    )

    result = (
        store.get_live_action_evidence(
            now=(
                NOW
                + timedelta(
                    seconds=31
                )
            )
        )
    )

    assert result is None


def test_new_current_invalidates_previous_action_inventory():
    store = _ready_store()

    store.set_live_action_evidence(
        _evidence()
    )

    store.set_live_navigation(
        _navigation(
            fingerprint=FP_B,
            state="STATE_B",
        )
    )

    assert (
        store.get_live_action_evidence(
            now=NOW
        )
        is None
    )


def test_session_replacement_clears_action_inventory():
    store = _ready_store()

    store.set_live_action_evidence(
        _evidence()
    )

    store.set_active_session(
        _session(
            "session-2"
        )
    )

    assert (
        store.get_live_action_evidence(
            now=NOW
        )
        is None
    )


def test_clear_live_navigation_clears_action_inventory():
    store = _ready_store()

    store.set_live_action_evidence(
        _evidence()
    )

    assert (
        store.clear_live_navigation(
            session_id="session-1",
        )
        is True
    )

    assert (
        store.get_live_action_evidence(
            now=NOW
        )
        is None
    )


def test_clear_environment_clears_action_inventory():
    store = _ready_store()

    store.set_live_action_evidence(
        _evidence()
    )

    assert (
        store.clear_navigation_environment(
            session_id="session-1",
        )
        is True
    )

    assert (
        store.get_live_action_evidence(
            now=NOW
        )
        is None
    )
