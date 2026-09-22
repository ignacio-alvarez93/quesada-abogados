from datetime import datetime, timedelta, timezone

import pytest

from backend.qcc.context.human_action_canonicalizer import (
    QccHumanDomSignal,
)
from backend.qcc.context.human_policy_teaching import (
    QCC_HUMAN_POLICY_TEACHING_RESTRICTION_HUMAN_ONLY,
    QccHumanPolicyTeachingRecord,
    resolve_effective_policy_with_teaching,
    teach_human_only_from_signal,
)
from backend.qcc.context.live_action_evidence import (
    QccLiveActionEvidence,
)
from backend.qcc.context.store import QccContextStore
from backend.qcc.contracts.live_navigation import QccLiveNavigationContext
from backend.qcc.contracts.protocol import (
    QccPresentationSession,
    QccPresentationStatus,
)


NOW = datetime.now(timezone.utc)
FP_A = "a" * 64


def _canonical_action():
    return {
        "kind": "LINK",
        "policy": "NAVIGATION_CANDIDATE",
        "selector": "#enviar",
        "frame_path": "main",
        "visible": True,
        "disabled": False,
        "in_viewport": True,
        "opacity": 1.0,
        "pointer_events": "auto",
    }


def _ready_store(*, capture_id="cap-1"):
    store = QccContextStore()

    store.set_active_session(
        QccPresentationSession(
            session_id="s1",
            expedient_id=1,
            client_id=1,
            procedure="TEST",
            provider="MERCURIO",
            runtime="SELENIUMBASE_ASSISTED",
            started_at=NOW,
            status=QccPresentationStatus.WAITING_USER,
            current_step="TEST",
            progress=50,
            requires_user_action=True,
        )
    )

    store.set_navigation_environment("REAL", session_id="s1")

    store.set_live_navigation(
        QccLiveNavigationContext(
            session_id="s1",
            updated_at=NOW,
            current_state="STATE_A",
            current_fingerprint=FP_A,
        )
    )

    evidence = QccLiveActionEvidence(
        session_id="s1",
        site_code="MERCURIO",
        environment="REAL",
        before_state="STATE_A",
        before_fingerprint=FP_A,
        actions=(_canonical_action(),),
        captured_at=NOW,
        capture_id=capture_id,
    )

    store.set_live_action_evidence(evidence)

    return store


def _signal(*, observed_at=None, selector="#enviar", event_id="evt-1"):
    return QccHumanDomSignal(
        event_id=event_id,
        session_id="s1",
        selector=selector,
        frame_path="main",
        observed_at=observed_at or (NOW + timedelta(seconds=1)),
    )


def test_teaching_binds_exact_evidence_identity():
    store = _ready_store(capture_id="cap-exact")

    record = teach_human_only_from_signal(
        store,
        _signal(),
        taught_by="SIDE_PANEL",
        now=NOW + timedelta(seconds=1),
    )

    assert isinstance(record, QccHumanPolicyTeachingRecord)
    assert record.site_code == "MERCURIO"
    assert record.environment == "REAL"
    assert record.action_kind == "LINK"
    assert record.action_selector == "#enviar"
    assert record.action_frame_path == "main"
    assert record.before_state == "STATE_A"
    assert record.before_fingerprint == FP_A
    assert record.evidence_capture_id == "cap-exact"
    assert record.previous_effective_policy == "NAVIGATION_CANDIDATE"
    assert (
        record.resulting_restriction
        == QCC_HUMAN_POLICY_TEACHING_RESTRICTION_HUMAN_ONLY
    )
    assert record.taught_by == "SIDE_PANEL"
    assert record.session_id == "s1"


def test_teaching_never_produces_automation_allowed():
    # There is no parameter, kwarg or code path that can request
    # anything other than HUMAN_ONLY: constructing the record directly
    # with an unsupported restriction must fail closed.
    with pytest.raises(ValueError):
        QccHumanPolicyTeachingRecord(
            teaching_id="t1",
            site_code="MERCURIO",
            environment="REAL",
            action_kind="LINK",
            action_selector="#enviar",
            action_frame_path="main",
            before_state="STATE_A",
            before_fingerprint=FP_A,
            evidence_capture_id="cap-1",
            previous_effective_policy="HUMAN_ONLY",
            resulting_restriction="AUTOMATION_ALLOWED",
            taught_by="SIDE_PANEL",
            session_id="s1",
            taught_at=NOW,
        )


def test_teaching_rejects_stale_evidence():
    store = _ready_store()

    with pytest.raises(ValueError) as excinfo:
        teach_human_only_from_signal(
            store,
            _signal(),
            taught_by="SIDE_PANEL",
            now=NOW + timedelta(minutes=45),
        )

    assert "STALE" in str(excinfo.value)


def test_teaching_rejects_ambiguous_action():
    store = QccContextStore()

    store.set_active_session(
        QccPresentationSession(
            session_id="s1",
            expedient_id=1,
            client_id=1,
            procedure="TEST",
            provider="MERCURIO",
            runtime="SELENIUMBASE_ASSISTED",
            started_at=NOW,
            status=QccPresentationStatus.WAITING_USER,
            current_step="TEST",
            progress=50,
            requires_user_action=True,
        )
    )

    store.set_navigation_environment("REAL", session_id="s1")

    store.set_live_navigation(
        QccLiveNavigationContext(
            session_id="s1",
            updated_at=NOW,
            current_state="STATE_A",
            current_fingerprint=FP_A,
        )
    )

    duplicate_action = _canonical_action()

    store.set_live_action_evidence(
        QccLiveActionEvidence(
            session_id="s1",
            site_code="MERCURIO",
            environment="REAL",
            before_state="STATE_A",
            before_fingerprint=FP_A,
            actions=(
                {**duplicate_action, "kind": "LINK"},
                {**duplicate_action, "kind": "BUTTON"},
            ),
            captured_at=NOW,
        )
    )

    with pytest.raises(ValueError) as excinfo:
        teach_human_only_from_signal(
            store,
            _signal(),
            taught_by="SIDE_PANEL",
            now=NOW + timedelta(seconds=1),
        )

    assert "AMBIGUOUS" in str(excinfo.value)


def test_teaching_rejects_wrong_session_scope():
    store = _ready_store()

    wrong_session_signal = QccHumanDomSignal(
        event_id="evt-x",
        session_id="other-session",
        selector="#enviar",
        frame_path="main",
        observed_at=NOW + timedelta(seconds=1),
    )

    with pytest.raises(ValueError) as excinfo:
        teach_human_only_from_signal(
            store,
            wrong_session_signal,
            taught_by="SIDE_PANEL",
            now=NOW + timedelta(seconds=1),
        )

    assert "SESSION_NOT_ACTIVE" in str(excinfo.value)


def test_resolve_effective_policy_with_teaching_is_monotonic():
    assert (
        resolve_effective_policy_with_teaching(
            canonical_policy="AUTOMATION_ALLOWED",
            taught_restriction=None,
        )
        == "AUTOMATION_ALLOWED"
    )

    assert (
        resolve_effective_policy_with_teaching(
            canonical_policy="AUTOMATION_ALLOWED",
            taught_restriction="HUMAN_ONLY",
        )
        == "HUMAN_ONLY"
    )

    assert (
        resolve_effective_policy_with_teaching(
            canonical_policy="HUMAN_ONLY",
            taught_restriction="HUMAN_ONLY",
        )
        == "HUMAN_ONLY"
    )

    # A teaching override never relaxes an absolute DENY.
    assert (
        resolve_effective_policy_with_teaching(
            canonical_policy="DENY",
            taught_restriction="HUMAN_ONLY",
        )
        == "DENY"
    )

    with pytest.raises(ValueError):
        resolve_effective_policy_with_teaching(
            canonical_policy="AUTOMATION_ALLOWED",
            taught_restriction="AUTOMATION_ALLOWED",
        )
