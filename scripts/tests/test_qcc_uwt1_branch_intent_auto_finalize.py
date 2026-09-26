"""UWT-1: trusted CURRENT-based causal auto-finalization.

Covers:
    A changed trusted CURRENT closing X -> B without a later human
    action Y, while an unchanged CURRENT never fabricates causality
    and never consumes X. Provider-neutral: no site/provider names
    are hardcoded into runtime behavior under test.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.qcc.auto_twin.materialization_coordinator import (
    AutoTwinMaterializationCoordinator,
)
from backend.qcc.auto_twin.navigation_transition_materialization import (
    project_twin_eligible_navigation_candidates,
)
from backend.qcc.bridge.server import (
    _qcc_project_auto_twin_materialization_after_human_learning,
)
from backend.qcc.context.human_transition_correlator import (
    correlate_observed_human_transition,
    finalize_observed_human_transition_against_next_action,
    finalize_observed_human_transition_from_trusted_current,
)
from backend.qcc.context.observed_human_action import (
    QccObservedHumanAction,
)
from backend.qcc.context.observed_human_transition import (
    QccObservedHumanTransition,
)
from backend.qcc.context.store import QccContextStore
from backend.qcc.contracts.live_navigation import (
    QccLiveNavigationContext,
)
from backend.qcc.contracts.protocol import (
    QccPresentationSession,
    QccPresentationStatus,
)
from backend.qcc.navigation_knowledge.store import (
    NavigationKnowledgeStore,
)
from backend.qcc.navigation_learning import (
    HumanNavigationCandidateStore,
    process_observed_human_navigation_learning,
)


FP_A = "a" * 64
FP_B = "b" * 64
FP_C = "c" * 64

SITE = "TESTSITE"
ENV = "LAB"

SERVER_SOURCE = Path(
    "backend/qcc/bridge/server.py"
).read_text(
    encoding="utf-8"
)


def _action(
    *,
    event_id="event-1",
    session_id="session-1",
    environment=ENV,
    observed_at=None,
    navigation_context=(),
):
    return QccObservedHumanAction(
        event_id=event_id,
        session_id=session_id,
        site_code=SITE,
        environment=environment,
        before_state="STATE_A",
        before_fingerprint=FP_A,
        kind="LINK",
        policy="NAVIGATION_CANDIDATE",
        selector="#btncont",
        frame_path="main",
        observed_at=(
            observed_at
            or datetime.now(timezone.utc)
        ),
        navigation_context=navigation_context,
    )


# ---------------------------------------------------------
# Fake store: mirrors the pattern in
# test_qcc_human_transition_runtime.py.
# ---------------------------------------------------------


class _FakeStore:
    def __init__(
        self,
        action,
        *,
        after_fingerprint=FP_B,
        after_state="STATE_B",
    ):
        self.action = action
        self.consumed = False
        self.stored = None

        self.session = SimpleNamespace(
            session_id="session-1",
            provider=SITE,
        )

        self.current = SimpleNamespace(
            session_id="session-1",
            current_state=after_state,
            current_fingerprint=after_fingerprint,
        )

    def get_active_session(self):
        return self.session

    def get_live_navigation(self):
        return self.current

    def get_navigation_environment(self):
        return ENV

    def get_observed_human_action(self):
        return self.action

    def consume_observed_human_action(
        self,
        *,
        session_id,
        now=None,
        ttl_seconds=30.0,
    ):
        assert session_id == "session-1"
        self.consumed = True

        action = self.action
        self.action = None
        return action

    def get_observed_human_transition(self):
        return self.stored

    def set_observed_human_transition(
        self,
        transition,
    ):
        self.stored = transition
        return transition

    def clear_observed_human_transition(
        self,
        *,
        session_id=None,
    ):
        if self.stored is None:
            return False

        if (
            session_id is not None
            and self.stored.session_id != session_id
        ):
            return False

        self.stored = None
        return True


# ---------------------------------------------------------
# 1/4. Changed trusted CURRENT finalizes without a later
# human action. Same URL / same navigation route: only the
# functional fingerprint differs.
# ---------------------------------------------------------


def test_changed_current_finalizes_without_next_action():
    action = _action(
        navigation_context=(
            {
                "key": "MODEL",
                "selected_values": ["X"],
            },
        ),
    )

    store = _FakeStore(action)

    provisional = correlate_observed_human_transition(
        store,
        after_site_code=SITE,
        after_observed_at=(
            action.observed_at + timedelta(seconds=1)
        ),
    )

    assert provisional is not None
    assert provisional.changed is True

    finalized = finalize_observed_human_transition_from_trusted_current(
        store,
        transition=provisional,
    )

    assert finalized is provisional
    assert finalized.before_fingerprint == FP_A
    assert finalized.after_fingerprint == FP_B

    # X was consumed exactly once and the provisional
    # snapshot was cleared.
    assert store.consumed is True
    assert store.action is None
    assert store.stored is None


# ---------------------------------------------------------
# 2/3. Same-state CURRENT does not finalize and does not
# consume X, because a later CURRENT may still be the real
# destination.
# ---------------------------------------------------------


def test_same_state_current_does_not_finalize_or_consume():
    action = _action()
    store = _FakeStore(
        action,
        after_fingerprint=FP_A,
        after_state="STATE_A",
    )

    provisional = correlate_observed_human_transition(
        store,
        after_site_code=SITE,
        after_observed_at=(
            action.observed_at + timedelta(seconds=1)
        ),
    )

    assert provisional is not None
    assert provisional.changed is False

    finalized = finalize_observed_human_transition_from_trusted_current(
        store,
        transition=provisional,
    )

    assert finalized is None
    assert store.consumed is False
    assert store.action is action


# ---------------------------------------------------------
# 5. BEFORE navigation_context is preserved exactly: AFTER
# never redefines branch context.
# ---------------------------------------------------------


def test_before_navigation_context_preserved_exactly():
    context = (
        {
            "key": "MODEL",
            "selected_values": ["EX01"],
        },
    )

    action = _action(
        navigation_context=context,
    )

    store = _FakeStore(action)

    provisional = correlate_observed_human_transition(
        store,
        after_site_code=SITE,
        after_observed_at=(
            action.observed_at + timedelta(seconds=1)
        ),
    )

    finalized = finalize_observed_human_transition_from_trusted_current(
        store,
        transition=provisional,
    )

    assert finalized.navigation_context == action.navigation_context
    assert finalized.navigation_context[0]["key"] == "MODEL"
    assert (
        finalized.navigation_context[0]["selected_values"]
        == ["EX01"]
    )


# ---------------------------------------------------------
# No-op / defensive contracts.
# ---------------------------------------------------------


def test_none_transition_is_noop():
    store = _FakeStore(_action())

    assert (
        finalize_observed_human_transition_from_trusted_current(
            store,
            transition=None,
        )
        is None
    )

    assert store.consumed is False


def test_malformed_transition_type_raises_and_creates_no_knowledge():
    store = _FakeStore(_action())

    with pytest.raises(TypeError):
        finalize_observed_human_transition_from_trusted_current(
            store,
            transition={"not": "a transition"},
        )

    assert store.consumed is False


def test_mismatched_event_id_does_not_finalize():
    action = _action(event_id="event-1")
    store = _FakeStore(action)

    other_action = _action(event_id="event-OTHER")

    foreign_transition = (
        QccObservedHumanTransition.from_action(
            other_action,
            after_state="STATE_B",
            after_fingerprint=FP_B,
            after_observed_at=(
                other_action.observed_at + timedelta(seconds=1)
            ),
        )
    )

    finalized = finalize_observed_human_transition_from_trusted_current(
        store,
        transition=foreign_transition,
    )

    assert finalized is None
    assert store.consumed is False


# ---------------------------------------------------------
# Integration against the REAL QccContextStore: authority
# checks (site / environment / session) and replay/legacy
# interplay.
# ---------------------------------------------------------


def _session(session_id="human-session-1", provider=SITE):
    return QccPresentationSession(
        session_id=session_id,
        expedient_id=1,
        client_id=1,
        procedure="TEST",
        provider=provider,
        runtime="SELENIUMBASE_ASSISTED",
        started_at=datetime.now(timezone.utc),
        status=QccPresentationStatus.WAITING_USER,
        current_step="TEST",
        progress=50,
        requires_user_action=True,
    )


def _navigation(fingerprint=FP_A, state="STATE_A"):
    return QccLiveNavigationContext(
        session_id="human-session-1",
        updated_at=datetime.now(timezone.utc),
        current_state=state,
        current_fingerprint=fingerprint,
    )


def _real_store():
    store = QccContextStore()
    store.set_active_session(_session())
    store.set_live_navigation(_navigation())
    store.set_navigation_environment(
        ENV,
        session_id="human-session-1",
    )
    return store


def _set_pending_action(store, **overrides):
    action = QccObservedHumanAction(
        event_id=overrides.get("event_id", "event-1"),
        session_id="human-session-1",
        site_code=overrides.get("site_code", SITE),
        environment=overrides.get("environment", ENV),
        before_state="STATE_A",
        before_fingerprint=FP_A,
        kind="LINK",
        policy="NAVIGATION_CANDIDATE",
        selector="#btncont",
        frame_path="main",
        observed_at=(
            overrides.get("observed_at")
            or datetime.now(timezone.utc)
        ),
    )

    return store.set_observed_human_action(action)


def test_real_store_changed_current_closes_episode():
    store = _real_store()
    action = _set_pending_action(store)

    store.set_live_navigation(
        _navigation(
            fingerprint=FP_B,
            state="STATE_B",
        )
    )

    provisional = correlate_observed_human_transition(
        store,
        after_site_code=SITE,
        after_observed_at=(
            action.observed_at + timedelta(seconds=1)
        ),
    )

    finalized = finalize_observed_human_transition_from_trusted_current(
        store,
        transition=provisional,
    )

    assert finalized is not None
    assert finalized.after_fingerprint == FP_B

    assert store.get_observed_human_action() is None
    assert store.get_observed_human_transition() is None


def test_real_store_site_mismatch_fails_closed():
    store = _real_store()
    action = _set_pending_action(store)

    store.set_live_navigation(
        _navigation(
            fingerprint=FP_B,
            state="STATE_B",
        )
    )

    provisional = correlate_observed_human_transition(
        store,
        after_site_code="OTHER_SITE",
        after_observed_at=(
            action.observed_at + timedelta(seconds=1)
        ),
    )

    assert provisional is None
    assert store.get_observed_human_action() is action


def test_environment_mismatch_fails_closed():
    action = _action()
    store = _FakeStore(action)

    # The environment authority disagrees with the pending action's
    # own trusted environment: never correlate, never consume.
    store.get_navigation_environment = lambda: "REAL"

    provisional = correlate_observed_human_transition(
        store,
        after_site_code=SITE,
        after_observed_at=(
            action.observed_at + timedelta(seconds=1)
        ),
    )

    assert provisional is None
    assert store.consumed is False
    assert store.action is action


def test_session_mismatch_fails_closed():
    action = _action(session_id="session-1")
    store = _FakeStore(action)

    # CURRENT observed under a different session identity than the
    # pending action's trusted session.
    store.session = SimpleNamespace(
        session_id="session-OTHER",
        provider=SITE,
    )
    store.current.session_id = "session-OTHER"

    provisional = correlate_observed_human_transition(
        store,
        after_site_code=SITE,
        after_observed_at=(
            action.observed_at + timedelta(seconds=1)
        ),
    )

    assert provisional is None
    assert store.consumed is False
    assert store.action is action


def test_replayed_current_does_not_duplicate_causal_evidence():
    store = _real_store()
    action = _set_pending_action(store)

    store.set_live_navigation(
        _navigation(
            fingerprint=FP_B,
            state="STATE_B",
        )
    )

    after_time = action.observed_at + timedelta(seconds=1)

    first = correlate_observed_human_transition(
        store,
        after_site_code=SITE,
        after_observed_at=after_time,
    )

    finalized_first = finalize_observed_human_transition_from_trusted_current(
        store,
        transition=first,
    )

    assert finalized_first is not None

    # Replay of the exact same CURRENT observation: no pending action
    # remains, so no new provisional/finalized evidence is created.
    replay = correlate_observed_human_transition(
        store,
        after_site_code=SITE,
        after_observed_at=(
            after_time + timedelta(milliseconds=1)
        ),
    )

    assert replay is None


def test_case_a_later_y_does_not_duplicate_already_finalized_x():
    store = _real_store()
    action = _set_pending_action(store)

    store.set_live_navigation(
        _navigation(
            fingerprint=FP_B,
            state="STATE_B",
        )
    )

    provisional = correlate_observed_human_transition(
        store,
        after_site_code=SITE,
        after_observed_at=(
            action.observed_at + timedelta(seconds=1)
        ),
    )

    finalized = finalize_observed_human_transition_from_trusted_current(
        store,
        transition=provisional,
    )

    assert finalized is not None

    later_y = QccObservedHumanAction(
        event_id="event-y",
        session_id="human-session-1",
        site_code=SITE,
        environment=ENV,
        before_state="STATE_B",
        before_fingerprint=FP_B,
        kind="LINK",
        policy="NAVIGATION_CANDIDATE",
        selector="#next",
        frame_path="main",
        observed_at=(
            action.observed_at + timedelta(seconds=2)
        ),
    )

    boundary = finalize_observed_human_transition_against_next_action(
        store,
        next_action=later_y,
    )

    # No pending X remains: CASE A produces no duplicate.
    assert boundary is None


def test_case_b_legacy_next_action_boundary_still_works():
    store = _real_store()
    action = _set_pending_action(store)

    # CURRENT never functionally changes (still A): UWT-1 must not
    # finalize, leaving the legacy boundary in charge.
    provisional = correlate_observed_human_transition(
        store,
        after_site_code=SITE,
        after_observed_at=(
            action.observed_at + timedelta(seconds=1)
        ),
    )

    finalized = finalize_observed_human_transition_from_trusted_current(
        store,
        transition=provisional,
    )

    assert finalized is None
    assert store.get_observed_human_action() is action

    later_y = QccObservedHumanAction(
        event_id="event-y",
        session_id="human-session-1",
        site_code=SITE,
        environment=ENV,
        before_state="STATE_A",
        before_fingerprint=FP_A,
        kind="LINK",
        policy="NAVIGATION_CANDIDATE",
        selector="#next",
        frame_path="main",
        observed_at=(
            action.observed_at + timedelta(seconds=2)
        ),
    )

    boundary = finalize_observed_human_transition_against_next_action(
        store,
        next_action=later_y,
    )

    assert boundary is not None
    assert boundary.event_id == action.event_id
    assert store.get_observed_human_action() is None


# ---------------------------------------------------------
# 6/7. Candidate store + NavigationKnowledge threshold and
# TWIN_ELIGIBLE projection are unaffected: one trusted REAL
# observation is enough for TWIN_ELIGIBLE, but NOT enough for
# NavigationKnowledge promotion (still 3).
# ---------------------------------------------------------


def test_one_real_observation_records_candidate_and_is_twin_eligible(
    tmp_path,
):
    candidates = HumanNavigationCandidateStore(
        root=tmp_path / "candidates"
    )
    knowledge = NavigationKnowledgeStore(
        root=tmp_path / "knowledge"
    )

    action = _action(environment="REAL")

    transition = QccObservedHumanTransition.from_action(
        action,
        after_state="STATE_B",
        after_fingerprint=FP_B,
        after_observed_at=(
            action.observed_at + timedelta(seconds=1)
        ),
    )

    result = process_observed_human_navigation_learning(
        candidates,
        knowledge,
        transition=transition,
        site_code=SITE,
        environment="REAL",
    )

    assert result["candidate_recorded"] is True
    assert result["candidate_observation_count"] == 1
    assert result["candidate_status"] == "CANDIDATE"

    # One observation remains below the NavigationKnowledge
    # confirmation threshold (still 3, unchanged by UWT-1).
    assert result["promotion_count"] == 0
    assert (
        knowledge.snapshot(
            SITE,
            environment="REAL",
        )["transition_observation_count"]
        == 0
    )

    snapshot = candidates.snapshot(
        SITE,
        environment="REAL",
    )

    eligible = project_twin_eligible_navigation_candidates(
        snapshot
    )

    assert len(eligible) == 1
    assert eligible[0]["eligibility"] == "TWIN_ELIGIBLE"
    assert eligible[0]["real_observation_count"] == 1


# ---------------------------------------------------------
# 8. Exact AFTER capture_id triggers the post-learning AUTO
# TWIN enqueue via the generic trusted_trigger_site_code
# contract (shared by the legacy Y-path and UWT-1).
# ---------------------------------------------------------


class _Registry:
    def __init__(self, sites):
        self._sites = sites

    def get_by_site_code(self, site_code):
        twin_key = self._sites.get(site_code)

        return (
            SimpleNamespace(twin_key=twin_key, site_code=site_code)
            if twin_key
            else None
        )


def test_current_trusted_finalize_enqueues_with_exact_capture_id(
    tmp_path,
):
    calls = []

    def processor(*, twin_key, trigger_capture_id):
        calls.append(
            (twin_key, trigger_capture_id)
        )
        return {"status": "NO_CHANGE"}

    coordinator = AutoTwinMaterializationCoordinator(
        processor=processor
    )

    server = SimpleNamespace(
        qcc_auto_twin_store=_Registry({SITE: "twin-key"}),
        qcc_auto_twin_materialization_coordinator=coordinator,
    )

    result = _qcc_project_auto_twin_materialization_after_human_learning(
        server=server,
        site_code=SITE,
        # UWT-1: the trusted trigger is the CURRENT's own backend
        # resolved site_code, not a "next action" site_code.
        trusted_trigger_site_code=SITE,
        trigger_capture_id="cap-current-exact",
    )

    assert result["status"] == "QUEUED"
    assert result["trigger_capture_id"] == "cap-current-exact"

    assert coordinator.wait_until_idle(timeout=5.0)
    assert calls == [("twin-key", "cap-current-exact")]


def test_bridge_wires_exact_after_capture_id_for_current_finalize():
    join_start = SERVER_SOURCE.index(
        "# HUMAN CAUSAL JOIN"
    )

    learning_start = SERVER_SOURCE.index(
        "# TRUSTED HUMAN NAVIGATION LEARNING",
        join_start,
    )

    join_end = SERVER_SOURCE.index(
        "# CANONICAL LIVE ACTION EVIDENCE",
        learning_start,
    )

    block = SERVER_SOURCE[join_start:join_end]

    assert (
        "finalize_observed_human_transition_from_trusted_current"
        in block
    )

    assert "finalized_current_transition" in block

    assert (
        "_qcc_project_auto_twin_materialization_after_human_learning"
        in block
    )

    assert "trusted_trigger_site_code" in block

    enqueue_start = block.index(
        "_qcc_project_auto_twin_materialization_after_human_learning"
    )

    enqueue_call = block[
        enqueue_start:
        enqueue_start + 600
    ]

    assert "trigger_capture_id" in enqueue_call
    assert '"capture_id"' in enqueue_call


def test_legacy_next_action_boundary_still_present_in_bridge():
    assert (
        "finalize_observed_human_transition_against_next_action"
        in SERVER_SOURCE
    )

    assert (
        "def finalize_observed_human_transition_against_next_action"
        in Path(
            "backend/qcc/context/human_transition_correlator.py"
        ).read_text(encoding="utf-8")
    )
