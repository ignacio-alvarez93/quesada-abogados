import pytest

from backend.automation.site_architecture.navigation_graph import (
    NAVIGATION_GRAPH_SCHEMA_VERSION,
    NAVIGATION_GRAPH_TYPE,
)
from backend.qcc.auto_twin.exploration_session import (
    AUTO_TWIN_EXPLORATION_SESSION_ACTIVE,
    AUTO_TWIN_EXPLORATION_SESSION_RESUME_EVIDENCE_AMBIGUOUS,
    AUTO_TWIN_EXPLORATION_SESSION_RESUME_REVISION_INCOMPATIBLE,
    AUTO_TWIN_EXPLORATION_SESSION_RESUME_REVISION_STALE,
    AUTO_TWIN_EXPLORATION_SESSION_RESUME_SCHEMA_INCOMPATIBLE,
    AUTO_TWIN_EXPLORATION_SESSION_RESUME_SITE_INCOMPATIBLE,
    AUTO_TWIN_EXPLORATION_SESSION_RESUME_SNAPSHOT_INVALID,
    AUTO_TWIN_EXPLORATION_SESSION_SNAPSHOT_SCHEMA_VERSION,
    AUTO_TWIN_EXPLORATION_SESSION_STOPPED,
    AUTO_TWIN_EXPLORATION_STEP_SELECTED,
    AUTO_TWIN_EXPLORATION_STOP_BUDGET_EXHAUSTED,
    AutoTwinExplorationSession,
    resume_exploration_session,
)
from backend.qcc.auto_twin.managed_site_registry import AutoTwinManagedSite
from backend.qcc.auto_twin.observation_store import AutoTwinObservationStore
from backend.qcc.auto_twin.profile_policy import build_auto_twin_profile_policy


ORIGIN = "http://127.0.0.1:8767"


def _store(tmp_path):
    return AutoTwinObservationStore(path=tmp_path / "observation_state.json")


def _site(twin_key="twin-a", site_code="SITE_A"):
    return AutoTwinManagedSite(
        twin_key=twin_key,
        site_code=site_code,
        origins=(ORIGIN,),
        discover_unknown_states=True,
    )


def _observe(store, site, *, capture_id, fingerprint, pathname="/case/step",
             state="STATE_A"):
    return store.observe(
        site,
        capture_id=capture_id,
        observed_at="2026-01-01T00:00:00.000000Z",
        browser_profile_key="twin_discovery",
        url=ORIGIN + pathname,
        site_code=site.site_code,
        state_observation={"state": state, "fingerprint": fingerprint},
    )


def _discovery_policy():
    return build_auto_twin_profile_policy("twin_discovery")


def _observer_policy():
    return build_auto_twin_profile_policy("some_other_profile")


def _empty_graph():
    return {
        "schema_version": NAVIGATION_GRAPH_SCHEMA_VERSION,
        "graph_type": NAVIGATION_GRAPH_TYPE,
        "observation_count": 0,
        "changed_observation_count": 0,
        "node_count": 0,
        "edge_count": 0,
        "nodes": (),
        "edges": (),
    }


def _action(*, kind="SELECT", policy="STATE_CHANGE_CANDIDATE",
            selector="#action"):
    return {
        "kind": kind,
        "policy": policy,
        "selector": selector,
        "frame_path": "main",
        "semantics": (),
        "interaction": {
            "visible": True,
            "disabled": False,
            "interactable": True,
        },
        "element": {
            "tag": "div",
            "id": selector.lstrip("#"),
            "name": "",
            "type": "",
            "role": "",
        },
        "navigation": {
            "href": None,
            "target": None,
        },
    }


def _session(store, site, *, source_fingerprint="fp-1", session_id="s-1",
             max_steps=5, exploration_budget=5, policy=None):
    return AutoTwinExplorationSession(
        session_id=session_id,
        observation_store=store,
        profile_policy=policy or _discovery_policy(),
        twin_key=site.twin_key,
        source_fingerprint=source_fingerprint,
        max_steps=max_steps,
        exploration_budget=exploration_budget,
    )


def _bootstrap(tmp_path):
    store = _store(tmp_path)
    site = _site()
    _observe(store, site, capture_id="c1", fingerprint="fp-1")
    return store, site


# -- round trip -----------------------------------------------------------


def test_snapshot_round_trip_preserves_identity_and_budget(tmp_path):
    store, site = _bootstrap(tmp_path)
    session = _session(store, site, max_steps=7, exploration_budget=3)

    snapshot = session.to_snapshot()

    assert snapshot["schema_version"] == (
        AUTO_TWIN_EXPLORATION_SESSION_SNAPSHOT_SCHEMA_VERSION
    )
    assert snapshot["session_id"] == "s-1"
    assert snapshot["twin_key"] == site.twin_key
    assert snapshot["site_code"] == site.site_code
    assert snapshot["status"] == AUTO_TWIN_EXPLORATION_SESSION_ACTIVE
    assert snapshot["current_fingerprint"] == "fp-1"
    assert snapshot["max_steps"] == 7
    assert snapshot["exploration_budget"] == 3

    resumed = resume_exploration_session(
        snapshot, observation_store=store, profile_policy=_discovery_policy()
    )

    assert resumed.session_id == session.session_id
    assert resumed.twin_key == session.twin_key
    assert resumed.site_code == session.site_code
    assert resumed.status == session.status
    assert resumed.current_fingerprint == session.current_fingerprint
    assert resumed.max_steps == session.max_steps
    assert resumed.exploration_budget == session.exploration_budget
    assert resumed.steps_taken == session.steps_taken
    assert resumed.step_index == session.step_index
    assert resumed.to_dict() == session.to_dict()


def test_snapshot_preserves_visited_states_transitions_and_branch_context(
    tmp_path,
):
    store, site = _bootstrap(tmp_path)
    _observe(store, site, capture_id="c2", fingerprint="fp-2", pathname="/case/2")

    inventory = {
        "fp-1": (_action(kind="LINK", policy="NAVIGATION_CANDIDATE", selector="#next"),),
        "fp-2": (_action(selector="#a"),),
    }

    session = _session(store, site, max_steps=5, exploration_budget=5)

    result = session.step(
        navigation_graph=_empty_graph(),
        action_inventory_by_fingerprint=inventory,
    )
    session.record_outcome(
        candidate_id=result["candidate"]["candidate_id"],
        executed=True,
        resulting_fingerprint="fp-2",
    )

    snapshot = session.to_snapshot()

    assert snapshot["visited_fingerprints"] == ["fp-1"]
    assert len(snapshot["visited_transition_keys"]) == 1
    assert snapshot["current_fingerprint"] == "fp-2"

    resumed = resume_exploration_session(
        snapshot, observation_store=store, profile_policy=_discovery_policy()
    )

    assert resumed.current_fingerprint == "fp-2"
    assert resumed.current_state_context()["pathname"] == "/case/2"
    assert resumed.to_dict()["visited_fingerprint_count"] == 1
    assert resumed.to_dict()["visited_transition_count"] == 1

    # The already-resolved transition out of fp-1 must never be
    # re-proposed after resume.
    second = resumed.step(
        navigation_graph=_empty_graph(),
        action_inventory_by_fingerprint=inventory,
    )
    assert second["candidate"]["action"]["selector"] == "#a"
    assert second["candidate"]["state_fingerprint"] == "fp-2"


def test_snapshot_preserves_stop_reason_and_evidence_history(tmp_path):
    store, site = _bootstrap(tmp_path)
    session = _session(store, site, max_steps=1, exploration_budget=5)

    inventory = {"fp-1": (_action(selector="#a"),)}
    first = session.step(
        navigation_graph=_empty_graph(),
        action_inventory_by_fingerprint=inventory,
    )
    session.record_outcome(
        candidate_id=first["candidate"]["candidate_id"], executed=False
    )

    stopped = session.step(
        navigation_graph=_empty_graph(),
        action_inventory_by_fingerprint=inventory,
    )
    assert stopped["stop_reason"] == AUTO_TWIN_EXPLORATION_STOP_BUDGET_EXHAUSTED

    snapshot = session.to_snapshot()
    assert snapshot["status"] == AUTO_TWIN_EXPLORATION_SESSION_STOPPED
    assert snapshot["stop_reason"] == AUTO_TWIN_EXPLORATION_STOP_BUDGET_EXHAUSTED
    assert len(snapshot["evidence"]) == len(session.evidence)

    resumed = resume_exploration_session(
        snapshot, observation_store=store, profile_policy=_discovery_policy()
    )

    assert resumed.status == AUTO_TWIN_EXPLORATION_SESSION_STOPPED
    assert resumed.stop_reason == AUTO_TWIN_EXPLORATION_STOP_BUDGET_EXHAUSTED
    assert [entry["status"] for entry in resumed.evidence] == [
        entry["status"] for entry in session.evidence
    ]

    # A terminal resumed session is still idempotent -- never re-plans.
    again = resumed.step(
        navigation_graph=_empty_graph(),
        action_inventory_by_fingerprint=inventory,
    )
    assert again["decision"] != AUTO_TWIN_EXPLORATION_STEP_SELECTED
    assert len(resumed.evidence) == len(session.evidence)


def test_snapshot_preserves_pending_candidate_without_resolving_it(tmp_path):
    store, site = _bootstrap(tmp_path)
    session = _session(store, site)

    inventory = {"fp-1": (_action(selector="#a"),)}
    result = session.step(
        navigation_graph=_empty_graph(),
        action_inventory_by_fingerprint=inventory,
    )
    candidate_id = result["candidate"]["candidate_id"]

    snapshot = session.to_snapshot()
    assert snapshot["pending_candidate"]["candidate_id"] == candidate_id

    resumed = resume_exploration_session(
        snapshot, observation_store=store, profile_policy=_discovery_policy()
    )

    # No automatic REAL action during resume: the pending candidate is
    # still pending, and a new step() is refused exactly like before
    # the snapshot was taken.
    with pytest.raises(RuntimeError):
        resumed.step(
            navigation_graph=_empty_graph(),
            action_inventory_by_fingerprint=inventory,
        )

    outcome = resumed.record_outcome(candidate_id=candidate_id, executed=False)
    assert outcome["status"] == "SKIPPED"


# -- idempotence / no duplicate execution ---------------------------------


def test_resume_is_idempotent_and_never_executes(tmp_path):
    store, site = _bootstrap(tmp_path)
    session = _session(store, site)

    inventory = {"fp-1": (_action(selector="#a"),)}
    result = session.step(
        navigation_graph=_empty_graph(),
        action_inventory_by_fingerprint=inventory,
    )
    session.record_outcome(
        candidate_id=result["candidate"]["candidate_id"],
        executed=True,
        resulting_fingerprint="fp-1",
    )

    snapshot = session.to_snapshot()
    revision_before = store.revision

    first_resume = resume_exploration_session(
        snapshot, observation_store=store, profile_policy=_discovery_policy()
    )
    second_resume = resume_exploration_session(
        snapshot, observation_store=store, profile_policy=_discovery_policy()
    )

    assert store.revision == revision_before
    assert first_resume.to_dict() == second_resume.to_dict()
    assert list(first_resume.evidence) == list(second_resume.evidence)
    assert first_resume.steps_taken == session.steps_taken
    assert second_resume.steps_taken == session.steps_taken


# -- rejections -------------------------------------------------------------


def test_resume_rejects_non_dict_snapshot(tmp_path):
    store, _site = _bootstrap(tmp_path)

    with pytest.raises(ValueError) as excinfo:
        resume_exploration_session(
            "not-a-snapshot",
            observation_store=store,
            profile_policy=_discovery_policy(),
        )

    assert str(excinfo.value) == (
        AUTO_TWIN_EXPLORATION_SESSION_RESUME_SNAPSHOT_INVALID
    )


def test_resume_rejects_incompatible_schema_version(tmp_path):
    store, site = _bootstrap(tmp_path)
    session = _session(store, site)
    snapshot = dict(session.to_snapshot())
    snapshot["schema_version"] = 999

    with pytest.raises(ValueError) as excinfo:
        resume_exploration_session(
            snapshot, observation_store=store, profile_policy=_discovery_policy()
        )

    assert str(excinfo.value) == (
        AUTO_TWIN_EXPLORATION_SESSION_RESUME_SCHEMA_INCOMPATIBLE
    )


def test_resume_rejects_tampered_resume_token_as_ambiguous(tmp_path):
    store, site = _bootstrap(tmp_path)
    session = _session(store, site)
    snapshot = dict(session.to_snapshot())
    snapshot["steps_taken"] = snapshot["steps_taken"] + 1

    with pytest.raises(ValueError) as excinfo:
        resume_exploration_session(
            snapshot, observation_store=store, profile_policy=_discovery_policy()
        )

    assert str(excinfo.value) == (
        AUTO_TWIN_EXPLORATION_SESSION_RESUME_EVIDENCE_AMBIGUOUS
    )


def test_resume_rejects_missing_resume_token_as_ambiguous(tmp_path):
    store, site = _bootstrap(tmp_path)
    session = _session(store, site)
    snapshot = dict(session.to_snapshot())
    del snapshot["resume_token"]

    with pytest.raises(ValueError) as excinfo:
        resume_exploration_session(
            snapshot, observation_store=store, profile_policy=_discovery_policy()
        )

    assert str(excinfo.value) == (
        AUTO_TWIN_EXPLORATION_SESSION_RESUME_EVIDENCE_AMBIGUOUS
    )


def test_resume_rejects_incompatible_site_code(tmp_path):
    store, site = _bootstrap(tmp_path)
    session = _session(store, site)

    # A second twin, registered under a different site_code, observed
    # into the SAME store so the twin_key the snapshot carries still
    # resolves -- but now to an incompatible site.
    other_store = _store(tmp_path.parent / "other-resume-site")
    other_site = _site(twin_key=site.twin_key, site_code="SITE_B")
    _observe(other_store, other_site, capture_id="c1", fingerprint="fp-1")

    snapshot = session.to_snapshot()

    with pytest.raises(ValueError) as excinfo:
        resume_exploration_session(
            snapshot,
            observation_store=other_store,
            profile_policy=_discovery_policy(),
        )

    assert str(excinfo.value) == (
        AUTO_TWIN_EXPLORATION_SESSION_RESUME_SITE_INCOMPATIBLE
    )


def test_resume_rejects_stale_revision_when_store_has_moved_on(tmp_path):
    store, site = _bootstrap(tmp_path)
    session = _session(store, site)
    snapshot = session.to_snapshot()

    # The store advances (e.g. a concurrent observation) after the
    # snapshot was taken.
    _observe(store, site, capture_id="c2", fingerprint="fp-2", pathname="/case/2")

    with pytest.raises(ValueError) as excinfo:
        resume_exploration_session(
            snapshot, observation_store=store, profile_policy=_discovery_policy()
        )

    assert str(excinfo.value) == (
        AUTO_TWIN_EXPLORATION_SESSION_RESUME_REVISION_STALE
    )


def test_resume_rejects_revision_ahead_of_store_as_incompatible(tmp_path):
    store, site = _bootstrap(tmp_path)
    session = _session(store, site)
    snapshot = dict(session.to_snapshot())

    tampered = dict(snapshot)
    tampered["revision"] = snapshot["revision"] + 1
    tampered["resume_token"] = None
    # Recompute a self-consistent (but store-incompatible) token so
    # this test isolates the revision check from the ambiguity check.
    from backend.qcc.auto_twin.exploration_session import _resume_token

    payload = {k: v for k, v in tampered.items() if k != "resume_token"}
    tampered["resume_token"] = _resume_token(payload)

    with pytest.raises(ValueError) as excinfo:
        resume_exploration_session(
            tampered, observation_store=store, profile_policy=_discovery_policy()
        )

    assert str(excinfo.value) == (
        AUTO_TWIN_EXPLORATION_SESSION_RESUME_REVISION_INCOMPATIBLE
    )


def test_resume_requires_discovery_profile(tmp_path):
    store, site = _bootstrap(tmp_path)
    session = _session(store, site)
    snapshot = session.to_snapshot()

    with pytest.raises(ValueError):
        resume_exploration_session(
            snapshot, observation_store=store, profile_policy=_observer_policy()
        )


def test_resume_never_mutates_observation_store(tmp_path):
    store, site = _bootstrap(tmp_path)
    session = _session(store, site)
    snapshot = session.to_snapshot()

    revision_before = store.revision
    resume_exploration_session(
        snapshot, observation_store=store, profile_policy=_discovery_policy()
    )
    assert store.revision == revision_before
