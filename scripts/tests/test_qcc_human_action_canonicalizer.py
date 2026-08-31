from datetime import (
    datetime,
    timedelta,
    timezone,
)

import pytest

from backend.qcc.context.human_action_canonicalizer import (
    QccHumanDomSignal,
    canonicalize_human_dom_signal,
)
from backend.qcc.context.live_action_evidence import (
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
    12,
    0,
    tzinfo=timezone.utc,
)

FP_A = "a" * 64


def _session():
    return QccPresentationSession(
        session_id="session-1",
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


def _navigation():
    return QccLiveNavigationContext(
        session_id="session-1",
        updated_at=NOW,
        current_state="STATE_A",
        current_fingerprint=FP_A,
    )


def _canonical_action(
    *,
    selector="#continuar",
    kind="BUTTON",
    policy="HUMAN_ONLY",
    frame_path="main",
):
    return {
        "kind":
            kind,

        "policy":
            policy,

        "selector":
            selector,

        "frame_path":
            frame_path,

        "visible":
            True,

        "disabled":
            False,
    }


def _evidence(
    *,
    captured_at=NOW,
    actions=None,
):
    return QccLiveActionEvidence(
        session_id="session-1",
        site_code="MERCURIO",
        environment="REAL",
        before_state="STATE_A",
        before_fingerprint=FP_A,
        actions=tuple(
            actions
            if actions is not None
            else (
                _canonical_action(),
            )
        ),
        captured_at=captured_at,
    )


def _signal(
    *,
    event_id="event-1",
    session_id="session-1",
    selector="#continuar",
    frame_path="main",
    observed_at=None,
):
    return QccHumanDomSignal(
        event_id=event_id,
        session_id=session_id,
        selector=selector,
        frame_path=frame_path,
        observed_at=(
            observed_at
            if observed_at is not None
            else (
                NOW
                + timedelta(
                    seconds=1
                )
            )
        ),
    )


def _ready_store(
    *,
    evidence=None,
):
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

    store.set_live_action_evidence(
        evidence
        if evidence is not None
        else _evidence()
    )

    return store


def test_signal_contract_has_no_policy_or_kind_authority():
    signal = _signal()

    assert not hasattr(
        signal,
        "policy",
    )

    assert not hasattr(
        signal,
        "kind",
    )

    assert not hasattr(
        signal,
        "site_code",
    )

    assert not hasattr(
        signal,
        "environment",
    )

    assert not hasattr(
        signal,
        "before_fingerprint",
    )


def test_signal_normalizes_selector_frame_and_ids():
    signal = QccHumanDomSignal(
        event_id=" event-1 ",
        session_id=" session-1 ",
        selector=" #continuar ",
        frame_path=" main ",
        observed_at=NOW,
    )

    assert (
        signal.event_id
        == "event-1"
    )

    assert (
        signal.session_id
        == "session-1"
    )

    assert (
        signal.selector
        == "#continuar"
    )

    assert (
        signal.frame_path
        == "main"
    )


def test_signal_requires_timezone_aware_time():
    with pytest.raises(
        ValueError,
        match=(
            "QCC_HUMAN_DOM_SIGNAL_TIME_TZ_REQUIRED"
        ),
    ):
        QccHumanDomSignal(
            event_id="event-1",
            session_id="session-1",
            selector="#continuar",
            frame_path="main",
            observed_at=datetime(
                2026,
                8,
                31,
                12,
                0,
            ),
        )


def test_resolver_requires_active_session():
    store = QccContextStore()

    with pytest.raises(
        ValueError,
        match=(
            "QCC_HUMAN_DOM_SIGNAL_SESSION_NOT_ACTIVE"
        ),
    ):
        canonicalize_human_dom_signal(
            store,
            _signal(),
            now=(
                NOW
                + timedelta(
                    seconds=1
                )
            ),
        )


def test_resolver_requires_live_action_evidence():
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

    with pytest.raises(
        ValueError,
        match=(
            "QCC_HUMAN_DOM_SIGNAL_EVIDENCE_REQUIRED"
        ),
    ):
        canonicalize_human_dom_signal(
            store,
            _signal(),
            now=(
                NOW
                + timedelta(
                    seconds=1
                )
            ),
        )


def test_signal_must_occur_after_capture_a():
    store = _ready_store(
        evidence=_evidence(
            captured_at=NOW
        )
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_HUMAN_DOM_SIGNAL_BEFORE_EVIDENCE"
        ),
    ):
        canonicalize_human_dom_signal(
            store,
            _signal(
                observed_at=(
                    NOW
                    - timedelta(
                        milliseconds=1
                    )
                )
            ),
            now=NOW,
        )


def test_stale_signal_is_rejected():
    store = _ready_store(
        evidence=_evidence(
            captured_at=(
                NOW
                - timedelta(
                    seconds=40
                )
            )
        )
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_HUMAN_DOM_SIGNAL_STALE"
        ),
    ):
        canonicalize_human_dom_signal(
            store,
            _signal(
                observed_at=(
                    NOW
                    - timedelta(
                        seconds=31
                    )
                )
            ),
            now=NOW,
        )


def test_zero_candidate_is_rejected():
    store = _ready_store()

    with pytest.raises(
        ValueError,
        match=(
            "QCC_HUMAN_DOM_SIGNAL_ACTION_NOT_FOUND"
        ),
    ):
        canonicalize_human_dom_signal(
            store,
            _signal(
                selector="#desconocido"
            ),
            now=(
                NOW
                + timedelta(
                    seconds=1
                )
            ),
        )


def test_multiple_candidates_are_rejected():
    store = _ready_store(
        evidence=_evidence(
            actions=(
                _canonical_action(
                    selector="#continuar",
                    policy="HUMAN_ONLY",
                ),
                _canonical_action(
                    selector="#continuar",
                    policy="REQUIRES_POLICY",
                ),
            )
        )
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_HUMAN_DOM_SIGNAL_ACTION_AMBIGUOUS"
        ),
    ):
        canonicalize_human_dom_signal(
            store,
            _signal(),
            now=(
                NOW
                + timedelta(
                    seconds=1
                )
            ),
        )


def test_exact_candidate_supplies_backend_kind_and_policy():
    store = _ready_store(
        evidence=_evidence(
            actions=(
                _canonical_action(
                    kind="BUTTON",
                    policy="HUMAN_ONLY",
                ),
            )
        )
    )

    result = (
        canonicalize_human_dom_signal(
            store,
            _signal(),
            now=(
                NOW
                + timedelta(
                    seconds=1
                )
            ),
        )
    )

    assert (
        result.kind
        == "BUTTON"
    )

    assert (
        result.policy
        == "HUMAN_ONLY"
    )

    assert (
        result.selector
        == "#continuar"
    )

    assert (
        result.frame_path
        == "main"
    )


def test_observed_action_inherits_context_not_browser_authority():
    store = _ready_store()

    result = (
        canonicalize_human_dom_signal(
            store,
            _signal(),
            now=(
                NOW
                + timedelta(
                    seconds=1
                )
            ),
        )
    )

    assert (
        result.site_code
        == "MERCURIO"
    )

    assert (
        result.environment
        == "REAL"
    )

    assert (
        result.before_state
        == "STATE_A"
    )

    assert (
        result.before_fingerprint
        == FP_A
    )


def test_canonicalized_action_is_registered_runtime_only():
    store = _ready_store()

    revision = (
        store.revision
    )

    snapshot = (
        store.snapshot()
    )

    result = (
        canonicalize_human_dom_signal(
            store,
            _signal(),
            now=(
                NOW
                + timedelta(
                    seconds=1
                )
            ),
        )
    )

    pending = (
        store
        .get_observed_human_action(
            now=(
                NOW
                + timedelta(
                    seconds=1
                )
            )
        )
    )

    assert (
        pending
        == result
    )

    assert (
        store.revision
        == revision
    )

    assert (
        store.snapshot()
        == snapshot
    )


def test_same_event_retry_remains_idempotent():
    store = _ready_store()

    first = (
        canonicalize_human_dom_signal(
            store,
            _signal(
                event_id="event-1"
            ),
            now=(
                NOW
                + timedelta(
                    seconds=1
                )
            ),
        )
    )

    second = (
        canonicalize_human_dom_signal(
            store,
            _signal(
                event_id="event-1"
            ),
            now=(
                NOW
                + timedelta(
                    seconds=1
                )
            ),
        )
    )

    assert (
        first.event_id
        == second.event_id
        == "event-1"
    )


def test_second_distinct_signal_becomes_ambiguous():
    store = _ready_store()

    canonicalize_human_dom_signal(
        store,
        _signal(
            event_id="event-1"
        ),
        now=(
            NOW
            + timedelta(
                seconds=1
            )
        ),
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_OBSERVED_HUMAN_ACTION_AMBIGUOUS"
        ),
    ):
        canonicalize_human_dom_signal(
            store,
            _signal(
                event_id="event-2"
            ),
            now=(
                NOW
                + timedelta(
                    seconds=2
                )
            ),
        )

    assert (
        store.get_observed_human_action(
            now=(
                NOW
                + timedelta(
                    seconds=2
                )
            )
        )
        is None
    )


def test_resolver_does_not_change_canonical_evidence():
    store = _ready_store()

    before = (
        store
        .get_live_action_evidence(
            now=NOW
        )
    )

    canonicalize_human_dom_signal(
        store,
        _signal(),
        now=(
            NOW
            + timedelta(
                seconds=1
            )
        ),
    )

    after = (
        store
        .get_live_action_evidence(
            now=(
                NOW
                + timedelta(
                    seconds=1
                )
            )
        )
    )

    assert (
        before
        == after
    )
