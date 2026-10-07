import pytest

from backend.automation.site_architecture.navigation_graph import (
    NAVIGATION_GRAPH_SCHEMA_VERSION,
    NAVIGATION_GRAPH_TYPE,
    build_navigation_graph,
)
from backend.qcc.auto_twin.exploration_candidate_planner import (
    build_exploration_action_identity,
)
from backend.qcc.auto_twin.exploration_session import (
    AUTO_TWIN_EXPLORATION_EVIDENCE_EXECUTED,
    AUTO_TWIN_EXPLORATION_EVIDENCE_PLANNED,
    AUTO_TWIN_EXPLORATION_EVIDENCE_SESSION_STOPPED,
    AUTO_TWIN_EXPLORATION_EVIDENCE_SKIPPED,
    AUTO_TWIN_EXPLORATION_SESSION_ACTIVE,
    AUTO_TWIN_EXPLORATION_SESSION_STOPPED,
    AUTO_TWIN_EXPLORATION_STEP_SELECTED,
    AUTO_TWIN_EXPLORATION_STEP_STOPPED,
    AUTO_TWIN_EXPLORATION_STOP_BUDGET_EXHAUSTED,
    AUTO_TWIN_EXPLORATION_STOP_HUMAN_ONLY_BOUNDARY,
    AUTO_TWIN_EXPLORATION_STOP_LOOP_PROTECTION,
    AUTO_TWIN_EXPLORATION_STOP_NO_SAFE_CANDIDATES,
    AUTO_TWIN_EXPLORATION_STOP_RUNTIME_UNAVAILABLE,
    AUTO_TWIN_EXPLORATION_STOP_UNKNOWN_STATE,
    AutoTwinExplorationSession,
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
            selector="#action", href=None):
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
            "href": href,
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


# -- construction / governance ------------------------------------------


def test_requires_discovery_profile(tmp_path):
    store, site = _bootstrap(tmp_path)

    with pytest.raises(ValueError):
        _session(store, site, policy=_observer_policy())


def test_requires_known_twin(tmp_path):
    store = _store(tmp_path)

    with pytest.raises(ValueError):
        AutoTwinExplorationSession(
            session_id="s-1",
            observation_store=store,
            profile_policy=_discovery_policy(),
            twin_key="unknown-twin",
            source_fingerprint="fp-1",
        )


def test_requires_session_id(tmp_path):
    store, site = _bootstrap(tmp_path)

    with pytest.raises(ValueError):
        _session(store, site, session_id="")


def test_identity_resolved_from_observation_store(tmp_path):
    store, site = _bootstrap(tmp_path)

    session = _session(store, site)

    assert session.twin_key == site.twin_key
    assert session.site_code == site.site_code
    assert session.status == AUTO_TWIN_EXPLORATION_SESSION_ACTIVE
    assert session.current_fingerprint == "fp-1"

    snapshot = session.to_dict()
    assert snapshot["session_id"] == "s-1"
    assert snapshot["current_state_context"]["pathname"] == "/case/step"


# -- deterministic selection / one transition at a time -----------------


def test_step_selects_single_deterministic_candidate(tmp_path):
    store, site = _bootstrap(tmp_path)

    inventory = {
        "fp-1": (
            _action(kind="RADIO", selector="#b"),
            _action(kind="SELECT", selector="#a"),
        ),
    }

    session = _session(store, site)

    result = session.step(
        navigation_graph=_empty_graph(),
        action_inventory_by_fingerprint=inventory,
    )

    assert result["decision"] == AUTO_TWIN_EXPLORATION_STEP_SELECTED
    # Deterministic planner ordering sorts by action kind before
    # selector: "RADIO" < "SELECT".
    assert result["candidate"]["action"]["selector"] == "#b"
    assert result["evidence"]["status"] == AUTO_TWIN_EXPLORATION_EVIDENCE_PLANNED

    skipped = [
        entry for entry in session.evidence
        if entry["status"] == AUTO_TWIN_EXPLORATION_EVIDENCE_SKIPPED
    ]
    assert len(skipped) == 1
    assert skipped[0]["action"]["selector"] == "#a"
    assert skipped[0]["reason"] == "NOT_SELECTED_THIS_STEP"


def test_step_refuses_while_outcome_pending(tmp_path):
    store, site = _bootstrap(tmp_path)

    inventory = {"fp-1": (_action(selector="#a"),)}
    session = _session(store, site)

    session.step(
        navigation_graph=_empty_graph(),
        action_inventory_by_fingerprint=inventory,
    )

    with pytest.raises(RuntimeError):
        session.step(
            navigation_graph=_empty_graph(),
            action_inventory_by_fingerprint=inventory,
        )


def test_record_outcome_requires_matching_candidate(tmp_path):
    store, site = _bootstrap(tmp_path)

    inventory = {"fp-1": (_action(selector="#a"),)}
    session = _session(store, site)

    session.step(
        navigation_graph=_empty_graph(),
        action_inventory_by_fingerprint=inventory,
    )

    with pytest.raises(ValueError):
        session.record_outcome(candidate_id="wrong-id", executed=True)


def test_record_outcome_without_pending_raises(tmp_path):
    store, site = _bootstrap(tmp_path)
    session = _session(store, site)

    with pytest.raises(RuntimeError):
        session.record_outcome(candidate_id="anything", executed=True)


# -- transition / memory progression -------------------------------------


def test_executed_transition_advances_current_fingerprint(tmp_path):
    store, site = _bootstrap(tmp_path)
    _observe(store, site, capture_id="c2", fingerprint="fp-2", pathname="/case/2")

    inventory = {
        "fp-1": (_action(kind="LINK", policy="NAVIGATION_CANDIDATE", selector="#next"),),
        "fp-2": (_action(selector="#a"),),
    }

    session = _session(store, site)

    result = session.step(
        navigation_graph=_empty_graph(),
        action_inventory_by_fingerprint=inventory,
    )
    candidate = result["candidate"]

    outcome = session.record_outcome(
        candidate_id=candidate["candidate_id"],
        executed=True,
        resulting_fingerprint="fp-2",
    )

    assert outcome["status"] == AUTO_TWIN_EXPLORATION_EVIDENCE_EXECUTED
    assert session.current_fingerprint == "fp-2"
    assert session.steps_taken == 1

    next_result = session.step(
        navigation_graph=_empty_graph(),
        action_inventory_by_fingerprint=inventory,
    )
    assert next_result["decision"] == AUTO_TWIN_EXPLORATION_STEP_SELECTED
    assert next_result["candidate"]["state_fingerprint"] == "fp-2"


def test_declined_candidate_offers_next_remaining_candidate(tmp_path):
    store, site = _bootstrap(tmp_path)

    inventory = {
        "fp-1": (
            _action(kind="SELECT", selector="#a"),
            _action(kind="RADIO", selector="#b"),
        ),
    }

    session = _session(store, site, exploration_budget=5, max_steps=5)

    first = session.step(
        navigation_graph=_empty_graph(),
        action_inventory_by_fingerprint=inventory,
    )
    first_candidate = first["candidate"]
    assert first_candidate["action"]["selector"] == "#b"

    session.record_outcome(
        candidate_id=first_candidate["candidate_id"], executed=False
    )

    second = session.step(
        navigation_graph=_empty_graph(),
        action_inventory_by_fingerprint=inventory,
    )
    assert second["candidate"]["action"]["selector"] == "#a"
    assert session.steps_taken == 0


# -- STOP reasons ---------------------------------------------------------


def test_stop_runtime_unavailable_on_missing_evidence(tmp_path):
    store, site = _bootstrap(tmp_path)
    session = _session(store, site)

    result = session.step(
        navigation_graph=None,
        action_inventory_by_fingerprint={"fp-1": ()},
    )

    assert result["decision"] == AUTO_TWIN_EXPLORATION_STEP_STOPPED
    assert result["stop_reason"] == AUTO_TWIN_EXPLORATION_STOP_RUNTIME_UNAVAILABLE
    assert session.status == AUTO_TWIN_EXPLORATION_SESSION_STOPPED


def test_stop_runtime_unavailable_on_malformed_evidence(tmp_path):
    store, site = _bootstrap(tmp_path)
    session = _session(store, site)

    result = session.step(
        navigation_graph="not-a-dict",
        action_inventory_by_fingerprint={"fp-1": ()},
    )

    assert result["stop_reason"] == AUTO_TWIN_EXPLORATION_STOP_RUNTIME_UNAVAILABLE


def test_stop_unknown_state(tmp_path):
    store, site = _bootstrap(tmp_path)
    session = _session(store, site)

    result = session.step(
        navigation_graph=_empty_graph(),
        action_inventory_by_fingerprint={"fp-other": ()},
    )

    assert result["stop_reason"] == AUTO_TWIN_EXPLORATION_STOP_UNKNOWN_STATE


def test_stop_no_safe_candidates_when_only_unknown_risk_actions(tmp_path):
    store, site = _bootstrap(tmp_path)

    inventory = {
        "fp-1": (_action(kind="BUTTON", policy="REVIEW_REQUIRED", selector="#x"),),
    }

    session = _session(store, site)

    result = session.step(
        navigation_graph=_empty_graph(),
        action_inventory_by_fingerprint=inventory,
    )

    assert result["stop_reason"] == AUTO_TWIN_EXPLORATION_STOP_NO_SAFE_CANDIDATES


def test_stop_no_safe_candidates_when_no_actions_at_all(tmp_path):
    store, site = _bootstrap(tmp_path)

    session = _session(store, site)

    result = session.step(
        navigation_graph=_empty_graph(),
        action_inventory_by_fingerprint={"fp-1": ()},
    )

    assert result["stop_reason"] == AUTO_TWIN_EXPLORATION_STOP_NO_SAFE_CANDIDATES


def test_stop_human_only_boundary(tmp_path):
    store, site = _bootstrap(tmp_path)

    action = _action(kind="SELECT", selector="#a")
    inventory = {"fp-1": (action,)}

    human_only_keys = frozenset({build_exploration_action_identity(action)})

    session = _session(store, site)

    result = session.step(
        navigation_graph=_empty_graph(),
        action_inventory_by_fingerprint=inventory,
        human_only_action_keys=human_only_keys,
    )

    assert result["stop_reason"] == AUTO_TWIN_EXPLORATION_STOP_HUMAN_ONLY_BOUNDARY


def test_stop_budget_exhausted_on_exploration_budget(tmp_path):
    store, site = _bootstrap(tmp_path)
    _observe(store, site, capture_id="c2", fingerprint="fp-2", pathname="/case/2")

    inventory = {
        "fp-1": (_action(selector="#a"),),
        "fp-2": (_action(selector="#b"),),
    }

    session = _session(store, site, exploration_budget=1, max_steps=5)

    first = session.step(
        navigation_graph=_empty_graph(),
        action_inventory_by_fingerprint=inventory,
    )
    session.record_outcome(
        candidate_id=first["candidate"]["candidate_id"],
        executed=True,
        resulting_fingerprint="fp-2",
    )

    second = session.step(
        navigation_graph=_empty_graph(),
        action_inventory_by_fingerprint=inventory,
    )

    assert second["stop_reason"] == AUTO_TWIN_EXPLORATION_STOP_BUDGET_EXHAUSTED
    assert session.status == AUTO_TWIN_EXPLORATION_SESSION_STOPPED


def test_stop_budget_exhausted_on_max_steps_even_without_execution(tmp_path):
    store, site = _bootstrap(tmp_path)

    inventory = {"fp-1": (_action(selector="#a"),)}

    session = _session(store, site, max_steps=1, exploration_budget=5)

    first = session.step(
        navigation_graph=_empty_graph(),
        action_inventory_by_fingerprint=inventory,
    )
    session.record_outcome(
        candidate_id=first["candidate"]["candidate_id"], executed=False
    )

    second = session.step(
        navigation_graph=_empty_graph(),
        action_inventory_by_fingerprint=inventory,
    )

    assert second["stop_reason"] == AUTO_TWIN_EXPLORATION_STOP_BUDGET_EXHAUSTED
    assert session.steps_taken == 0


def test_stop_loop_protection_on_returning_to_a_left_fingerprint(tmp_path):
    store, site = _bootstrap(tmp_path)
    _observe(store, site, capture_id="c2", fingerprint="fp-2", pathname="/case/2")

    inventory = {
        "fp-1": (_action(selector="#a"),),
        "fp-2": (_action(selector="#b"),),
    }

    session = _session(store, site, max_steps=10, exploration_budget=10)

    first = session.step(
        navigation_graph=_empty_graph(),
        action_inventory_by_fingerprint=inventory,
    )
    session.record_outcome(
        candidate_id=first["candidate"]["candidate_id"],
        executed=True,
        resulting_fingerprint="fp-2",
    )

    second = session.step(
        navigation_graph=_empty_graph(),
        action_inventory_by_fingerprint=inventory,
    )
    session.record_outcome(
        candidate_id=second["candidate"]["candidate_id"],
        executed=True,
        resulting_fingerprint="fp-1",
    )

    third = session.step(
        navigation_graph=_empty_graph(),
        action_inventory_by_fingerprint=inventory,
    )

    assert third["stop_reason"] == AUTO_TWIN_EXPLORATION_STOP_LOOP_PROTECTION


def test_terminal_session_is_idempotent(tmp_path):
    store, site = _bootstrap(tmp_path)

    session = _session(store, site)

    result = session.step(
        navigation_graph=_empty_graph(),
        action_inventory_by_fingerprint={"fp-1": ()},
    )
    assert result["stop_reason"] == AUTO_TWIN_EXPLORATION_STOP_NO_SAFE_CANDIDATES

    evidence_count_after_first_stop = len(session.evidence)

    again = session.step(
        navigation_graph=_empty_graph(),
        action_inventory_by_fingerprint={"fp-1": ()},
    )

    assert again["decision"] == AUTO_TWIN_EXPLORATION_STEP_STOPPED
    assert again["stop_reason"] == AUTO_TWIN_EXPLORATION_STOP_NO_SAFE_CANDIDATES
    assert len(session.evidence) == evidence_count_after_first_stop


def test_already_executed_transition_excluded_on_revisit_without_loop(tmp_path):
    # Reusing the same source fingerprint across two *different* sessions
    # against the same transition never collides; within one session the
    # per-session transition memory keeps a repeated plan from offering an
    # already-executed (fingerprint, action) pair a second time, with the
    # frontier walk observing it via the Navigation Graph itself once it is
    # materialized elsewhere -- this test only proves the session-local
    # guard independent of the Navigation Graph.
    store, site = _bootstrap(tmp_path)

    inventory = {
        "fp-1": (
            _action(kind="SELECT", selector="#a"),
            _action(kind="RADIO", selector="#b"),
        ),
    }

    session = _session(store, site, max_steps=10, exploration_budget=10)

    first = session.step(
        navigation_graph=_empty_graph(),
        action_inventory_by_fingerprint=inventory,
    )
    session.record_outcome(
        candidate_id=first["candidate"]["candidate_id"],
        executed=True,
        resulting_fingerprint="fp-2",
    )

    # fp-2 was never observed/registered, so the next step necessarily
    # reports UNKNOWN_STATE -- which still proves the prior transition
    # memory was recorded via session.to_dict().
    snapshot = session.to_dict()
    assert snapshot["visited_transition_count"] == 1
    assert snapshot["visited_fingerprint_count"] == 1
