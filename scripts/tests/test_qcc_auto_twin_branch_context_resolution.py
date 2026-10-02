"""QCC_BRANCH_CONTEXT_CAPTURE_V1 AUTO TWIN BranchContext resolver suite.

Covers backend.qcc.auto_twin.branch_context_resolution
.resolve_auto_twin_branch_context_for_candidate(): it must reuse,
never duplicate, the existing governed navigation evidence pipeline
(HumanNavigationCandidateStore -> project_twin_eligible_navigation_
candidates -> classify_twin_navigation_transition_outcomes), and must
fail closed whenever the candidate's own action group is not uniquely
and unambiguously CONTEXTUAL_RESOLVED.
"""

import backend.qcc.auto_twin.branch_context_resolution as resolution_module

from backend.qcc.auto_twin.branch_context_resolution import (
    resolve_auto_twin_branch_context_for_candidate,
)
from backend.qcc.navigation_learning.human_candidate_store import (
    HumanNavigationCandidateStore,
)


SITE = "TESTSITE"
ENV = "LAB"

FP_A = "a" * 64
FP_B = "b" * 64
FP_C = "c" * 64


def _store(tmp_path):
    return HumanNavigationCandidateStore(
        root=tmp_path / "human-navigation-learning"
    )


def _record(
    store,
    *,
    event_id,
    after_fingerprint,
    selected_value,
    before_fingerprint=FP_A,
):
    result = store.record_observed_transition({
        "changed": True,
        "event_id": event_id,
        "after_observed_at": "2026-09-05T15:00:00+00:00",
        "site_code": SITE,
        "environment": ENV,
        "before_state": "STATE_A",
        "before_fingerprint": before_fingerprint,
        "navigation_context": [
            {
                "key": "ROUTE",
                "selector": "select#route",
                "frame_path": "main",
                "kind": "SELECT",
                "selected_values": [selected_value],
            },
        ],
        "kind": "LINK",
        "policy": "NAVIGATION_CANDIDATE",
        "selector": "#continue",
        "frame_path": "main",
        "after_state": "STATE_B",
        "after_fingerprint": after_fingerprint,
    })

    return result["candidate"]["candidate_id"]


def _record_no_navigation_context(
    store,
    *,
    event_id,
    after_fingerprint,
    before_fingerprint=FP_A,
):
    result = store.record_observed_transition({
        "changed": True,
        "event_id": event_id,
        "after_observed_at": "2026-09-05T15:00:00+00:00",
        "site_code": SITE,
        "environment": ENV,
        "before_state": "STATE_A",
        "before_fingerprint": before_fingerprint,
        "kind": "LINK",
        "policy": "NAVIGATION_CANDIDATE",
        "selector": "#continue",
        "frame_path": "main",
        "after_state": "STATE_B",
        "after_fingerprint": after_fingerprint,
    })

    return result["candidate"]["candidate_id"]


# ---------------------------------------------------------------------------
# 4. DETERMINISTIC -> None.
# ---------------------------------------------------------------------------


def test_deterministic_outcome_resolves_to_none(tmp_path):
    store = _store(tmp_path)

    candidate_id = _record(
        store,
        event_id="evt-1",
        after_fingerprint=FP_B,
        selected_value="130",
    )

    resolved = resolve_auto_twin_branch_context_for_candidate(
        store,
        site_code=SITE,
        environment=ENV,
        candidate_id=candidate_id,
    )

    assert resolved is None


# ---------------------------------------------------------------------------
# 5. CONTEXTUAL_OPAQUE -> None.
# ---------------------------------------------------------------------------


def test_contextual_opaque_outcome_resolves_to_none(tmp_path):
    store = _store(tmp_path)

    candidate_id = _record_no_navigation_context(
        store,
        event_id="evt-1",
        after_fingerprint=FP_B,
    )

    _record_no_navigation_context(
        store,
        event_id="evt-2",
        after_fingerprint=FP_C,
    )

    resolved = resolve_auto_twin_branch_context_for_candidate(
        store,
        site_code=SITE,
        environment=ENV,
        candidate_id=candidate_id,
    )

    assert resolved is None


# ---------------------------------------------------------------------------
# 6. CONTEXTUAL_RESOLVED + candidate match -> BranchContext.
# 9. same governed evidence -> same context_id.
# 10. different governed branch -> different context_id.
# ---------------------------------------------------------------------------


def test_contextual_resolved_candidate_match_returns_branch_context(
    tmp_path,
):
    store = _store(tmp_path)

    candidate_130 = _record(
        store,
        event_id="evt-130",
        after_fingerprint=FP_B,
        selected_value="130",
    )

    candidate_131 = _record(
        store,
        event_id="evt-131",
        after_fingerprint=FP_C,
        selected_value="131",
    )

    context_130 = resolve_auto_twin_branch_context_for_candidate(
        store,
        site_code=SITE,
        environment=ENV,
        candidate_id=candidate_130,
    )

    context_131 = resolve_auto_twin_branch_context_for_candidate(
        store,
        site_code=SITE,
        environment=ENV,
        candidate_id=candidate_131,
    )

    assert context_130 is not None
    assert context_131 is not None

    # 10. different governed branch -> different context_id.
    assert context_130.context_id != context_131.context_id

    # 9. same governed evidence -> same context_id (determinism).
    replay = resolve_auto_twin_branch_context_for_candidate(
        store,
        site_code=SITE,
        environment=ENV,
        candidate_id=candidate_130,
    )

    assert replay is not None
    assert replay.context_id == context_130.context_id


# ---------------------------------------------------------------------------
# 7. candidate absent -> None.
# ---------------------------------------------------------------------------


def test_absent_candidate_resolves_to_none(tmp_path):
    store = _store(tmp_path)

    _record(
        store,
        event_id="evt-130",
        after_fingerprint=FP_B,
        selected_value="130",
    )

    resolved = resolve_auto_twin_branch_context_for_candidate(
        store,
        site_code=SITE,
        environment=ENV,
        candidate_id="0" * 64,
    )

    assert resolved is None


def test_malformed_inputs_resolve_to_none(tmp_path):
    store = _store(tmp_path)

    assert (
        resolve_auto_twin_branch_context_for_candidate(
            store,
            site_code="",
            environment=ENV,
            candidate_id="anything",
        )
        is None
    )

    assert (
        resolve_auto_twin_branch_context_for_candidate(
            store,
            site_code=SITE,
            environment=ENV,
            candidate_id="",
        )
        is None
    )

    assert (
        resolve_auto_twin_branch_context_for_candidate(
            object(),
            site_code=SITE,
            environment=ENV,
            candidate_id="anything",
        )
        is None
    )


# ---------------------------------------------------------------------------
# 8. ambiguous candidate match -> fail closed.
# ---------------------------------------------------------------------------


def test_ambiguous_candidate_match_fails_closed(tmp_path, monkeypatch):
    store = _store(tmp_path)

    candidate_id = _record(
        store,
        event_id="evt-130",
        after_fingerprint=FP_B,
        selected_value="130",
    )

    fabricated_groups = (
        {
            "outcome_mode": "CONTEXTUAL_RESOLVED",
            "branches": [
                {
                    "navigation_context": [],
                    "candidate_ids": [candidate_id],
                },
                {
                    "navigation_context": [],
                    "candidate_ids": [candidate_id],
                },
            ],
        },
    )

    monkeypatch.setattr(
        resolution_module,
        "classify_twin_navigation_transition_outcomes",
        lambda projected: fabricated_groups,
    )

    resolved = resolve_auto_twin_branch_context_for_candidate(
        store,
        site_code=SITE,
        environment=ENV,
        candidate_id=candidate_id,
    )

    assert resolved is None


# ---------------------------------------------------------------------------
# 1-3. candidate store snapshot / project_twin_eligible_navigation_
# candidates / classify_twin_navigation_transition_outcomes are reused,
# never reimplemented.
# ---------------------------------------------------------------------------


def test_resolver_reuses_snapshot_projection_and_classification(
    tmp_path, monkeypatch,
):
    store = _store(tmp_path)

    candidate_130 = _record(
        store,
        event_id="evt-130",
        after_fingerprint=FP_B,
        selected_value="130",
    )

    _record(
        store,
        event_id="evt-131",
        after_fingerprint=FP_C,
        selected_value="131",
    )

    calls = []

    original_snapshot = store.snapshot

    def spy_snapshot(*args, **kwargs):
        calls.append("snapshot")
        return original_snapshot(*args, **kwargs)

    monkeypatch.setattr(store, "snapshot", spy_snapshot)

    original_project = (
        resolution_module.project_twin_eligible_navigation_candidates
    )

    def spy_project(*args, **kwargs):
        calls.append("project")
        return original_project(*args, **kwargs)

    monkeypatch.setattr(
        resolution_module,
        "project_twin_eligible_navigation_candidates",
        spy_project,
    )

    original_classify = (
        resolution_module.classify_twin_navigation_transition_outcomes
    )

    def spy_classify(*args, **kwargs):
        calls.append("classify")
        return original_classify(*args, **kwargs)

    monkeypatch.setattr(
        resolution_module,
        "classify_twin_navigation_transition_outcomes",
        spy_classify,
    )

    resolved = resolve_auto_twin_branch_context_for_candidate(
        store,
        site_code=SITE,
        environment=ENV,
        candidate_id=candidate_130,
    )

    assert resolved is not None
    assert calls == ["snapshot", "project", "classify"]
