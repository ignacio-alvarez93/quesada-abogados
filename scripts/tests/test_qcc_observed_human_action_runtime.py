from datetime import (
    datetime,
    timedelta,
    timezone,
)

import pytest

from backend.qcc.context.observed_human_action import (
    QCC_OBSERVED_HUMAN_ACTION_SOURCE,
    QccObservedHumanAction,
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


FP_A = "a" * 64
FP_B = "b" * 64

NOW = datetime(
    2026,
    8,
    31,
    10,
    0,
    tzinfo=timezone.utc,
)


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
    session_id="session-1",
):
    return QccLiveNavigationContext(
        session_id=session_id,
        updated_at=NOW,
        current_state="STATE_A",
        current_fingerprint=FP_A,
    )


def _action(
    *,
    event_id="event-1",
    session_id="session-1",
    environment="REAL",
    before_state="STATE_A",
    before_fingerprint=FP_A,
    observed_at=NOW,
    selector="#continuar",
):
    return QccObservedHumanAction(
        event_id=event_id,
        session_id=session_id,
        site_code="MERCURIO",
        environment=environment,
        before_state=before_state,
        before_fingerprint=(
            before_fingerprint
        ),
        kind="BUTTON",
        policy="HUMAN_ONLY",
        selector=selector,
        frame_path="main",
        observed_at=observed_at,
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


def test_contract_is_pii_safe_functional_identity():
    action = _action()

    assert action.source == (
        QCC_OBSERVED_HUMAN_ACTION_SOURCE
    )

    assert (
        action.transition_action()
        == {
            "kind":
                "BUTTON",
            "policy":
                "HUMAN_ONLY",
            "selector":
                "#continuar",
            "frame_path":
                "main",
        }
    )

    assert not hasattr(
        action,
        "payload",
    )

    assert not hasattr(
        action,
        "text",
    )

    assert not hasattr(
        action,
        "value",
    )


def test_contract_normalizes_identity():
    action = QccObservedHumanAction(
        event_id=" event-1 ",
        session_id=" session-1 ",
        site_code=" mercurio ",
        environment=" real ",
        before_state=" state_a ",
        before_fingerprint=FP_A.upper(),
        kind=" button ",
        policy=" human_only ",
        selector=" #continuar ",
        frame_path=" main ",
        observed_at=NOW,
    )

    assert action.event_id == "event-1"
    assert action.session_id == "session-1"
    assert action.site_code == "MERCURIO"
    assert action.environment == "REAL"
    assert action.before_state == "STATE_A"
    assert action.before_fingerprint == FP_A
    assert action.kind == "BUTTON"
    assert action.policy == "HUMAN_ONLY"
    assert action.selector == "#continuar"
    assert action.frame_path == "main"


def test_contract_requires_valid_fingerprint():
    with pytest.raises(
        ValueError,
        match=(
            "QCC_OBSERVED_HUMAN_ACTION_FINGERPRINT_INVALID"
        ),
    ):
        _action(
            before_fingerprint="bad"
        )


def test_contract_requires_timezone_aware_time():
    with pytest.raises(
        ValueError,
        match=(
            "QCC_OBSERVED_HUMAN_ACTION_TIME_TZ_REQUIRED"
        ),
    ):
        _action(
            observed_at=datetime(
                2026,
                8,
                31,
                10,
                0,
            )
        )


def test_store_requires_active_session():
    store = QccContextStore()

    with pytest.raises(
        ValueError,
        match=(
            "QCC_OBSERVED_HUMAN_ACTION_SESSION_NOT_ACTIVE"
        ),
    ):
        store.set_observed_human_action(
            _action()
        )


def test_store_requires_current_navigation():
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
            "QCC_OBSERVED_HUMAN_ACTION_CURRENT_REQUIRED"
        ),
    ):
        store.set_observed_human_action(
            _action()
        )


def test_store_requires_bound_environment():
    store = QccContextStore()

    store.set_active_session(
        _session()
    )

    store.set_live_navigation(
        _navigation()
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_OBSERVED_HUMAN_ACTION_ENVIRONMENT_UNAVAILABLE"
        ),
    ):
        store.set_observed_human_action(
            _action()
        )


def test_store_rejects_environment_mismatch():
    store = _ready_store()

    with pytest.raises(
        ValueError,
        match=(
            "QCC_OBSERVED_HUMAN_ACTION_ENVIRONMENT_MISMATCH"
        ),
    ):
        store.set_observed_human_action(
            _action(
                environment="LAB"
            )
        )


def test_store_rejects_wrong_before_fingerprint():
    store = _ready_store()

    with pytest.raises(
        ValueError,
        match=(
            "QCC_OBSERVED_HUMAN_ACTION_FINGERPRINT_MISMATCH"
        ),
    ):
        store.set_observed_human_action(
            _action(
                before_fingerprint=FP_B
            )
        )


def test_runtime_action_does_not_change_public_snapshot_or_revision():
    store = _ready_store()

    revision = store.revision
    snapshot = store.snapshot()

    store.set_observed_human_action(
        _action()
    )

    assert store.revision == revision
    assert store.snapshot() == snapshot

    serialized = str(
        store.snapshot()
    )

    assert (
        "observed_human_action"
        not in serialized
    )

    assert (
        "#continuar"
        not in serialized
    )


def test_transport_retry_is_idempotent():
    store = _ready_store()

    first = _action()

    assert (
        store.set_observed_human_action(
            first
        )
        is first
    )

    retry = _action()

    stored = (
        store.set_observed_human_action(
            retry
        )
    )

    assert (
        stored.event_id
        == "event-1"
    )


def test_second_distinct_action_invalidates_ambiguity():
    store = _ready_store()

    store.set_observed_human_action(
        _action(
            event_id="event-1",
            selector="#continuar",
        )
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_OBSERVED_HUMAN_ACTION_AMBIGUOUS"
        ),
    ):
        store.set_observed_human_action(
            _action(
                event_id="event-2",
                selector="#otra",
            )
        )

    assert (
        store.get_observed_human_action(
            now=NOW
        )
        is None
    )


def test_stale_action_expires_without_public_revision():
    store = _ready_store()

    revision = store.revision

    store.set_observed_human_action(
        _action(
            observed_at=NOW
        )
    )

    result = (
        store.get_observed_human_action(
            now=(
                NOW
                + timedelta(
                    seconds=31
                )
            )
        )
    )

    assert result is None
    assert store.revision == revision


def test_action_is_single_use():
    store = _ready_store()

    store.set_observed_human_action(
        _action()
    )

    consumed = (
        store.consume_observed_human_action(
            session_id="session-1",
            now=NOW,
        )
    )

    assert consumed is not None

    assert (
        consumed.transition_action()[
            "policy"
        ]
        == "HUMAN_ONLY"
    )

    assert (
        store.consume_observed_human_action(
            session_id="session-1",
            now=NOW,
        )
        is None
    )


def test_new_session_clears_pending_action():
    store = _ready_store()

    store.set_observed_human_action(
        _action()
    )

    store.set_active_session(
        _session(
            "session-2"
        )
    )

    assert (
        store.get_observed_human_action(
            now=NOW
        )
        is None
    )


def test_clear_live_navigation_invalidates_pending_action():
    store = _ready_store()

    store.set_observed_human_action(
        _action()
    )

    assert (
        store.clear_live_navigation(
            session_id="session-1",
        )
        is True
    )

    assert (
        store.get_observed_human_action(
            now=NOW
        )
        is None
    )


def test_clear_active_session_clears_pending_action():
    store = _ready_store()

    store.set_observed_human_action(
        _action()
    )

    assert (
        store.clear_active_session(
            session_id="session-1",
        )
        is True
    )

    assert (
        store.get_observed_human_action(
            now=NOW
        )
        is None
    )
