import pytest

from backend.automation.site_architecture.navigation_graph import (
    NAVIGATION_GRAPH_SCHEMA_VERSION,
    NAVIGATION_GRAPH_TYPE,
    build_navigation_graph,
)
from backend.qcc.auto_twin.exploration_candidate_planner import (
    AUTO_TWIN_EXPLORATION_RISK_ALREADY_VISITED,
    AUTO_TWIN_EXPLORATION_RISK_HUMAN_ONLY,
    AUTO_TWIN_EXPLORATION_RISK_IRREVERSIBLE,
    AUTO_TWIN_EXPLORATION_RISK_READ_ONLY_NAVIGATION,
    AUTO_TWIN_EXPLORATION_RISK_REVERSIBLE,
    AUTO_TWIN_EXPLORATION_RISK_SENSITIVE_RESTRICTED,
    AUTO_TWIN_EXPLORATION_RISK_UNKNOWN,
    build_exploration_action_identity,
    plan_exploration_candidates,
)
from backend.qcc.auto_twin.managed_site_registry import AutoTwinManagedSite
from backend.qcc.auto_twin.observation_store import AutoTwinObservationStore
from backend.qcc.auto_twin.profile_policy import (
    build_auto_twin_profile_policy,
)


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
             state="STATE_A", branch_context=None):
    return store.observe(
        site,
        capture_id=capture_id,
        observed_at="2026-01-01T00:00:00.000000Z",
        browser_profile_key="twin_discovery",
        url=ORIGIN + pathname,
        site_code=site.site_code,
        state_observation={"state": state, "fingerprint": fingerprint},
        branch_context=branch_context,
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


def _transition(*, before, after, kind="LINK", policy="NAVIGATION_CANDIDATE",
                 selector="#link"):
    return {
        "schema_version": 1,
        "transition_type": "QCC_STATE_TRANSITION",
        "changed": True,
        "status": "FUNCTIONAL_STATE_CHANGED",
        "before_fingerprint": before,
        "after_fingerprint": after,
        "action": {
            "kind": kind,
            "policy": policy,
            "selector": selector,
            "frame_path": "main",
        },
        "confidence": "HIGH",
        "contract_changed": False,
        "inconclusive": False,
    }


def _action(*, kind="SELECT", policy="STATE_CHANGE_CANDIDATE",
            selector="#action", visible=True, disabled=False,
            interactable=True, href=None, element_id=None, semantics=()):
    return {
        "kind": kind,
        "policy": policy,
        "selector": selector,
        "frame_path": "main",
        "semantics": semantics,
        "interaction": {
            "visible": visible,
            "disabled": disabled,
            "interactable": interactable,
        },
        "element": {
            "tag": "div",
            "id": element_id or selector.lstrip("#"),
            "name": "",
            "type": "",
            "role": "",
        },
        "navigation": {
            "href": href,
            "target": None,
        },
    }


def test_requires_discovery_profile(tmp_path):
    store = _store(tmp_path)

    with pytest.raises(ValueError):
        plan_exploration_candidates(
            observation_store=store,
            twin_key="twin-a",
            profile_policy=_observer_policy(),
            navigation_graph=_empty_graph(),
            action_inventory_by_fingerprint={},
            source_fingerprint="fp-1",
        )


def test_bootstrap_state_proposes_reversible_and_navigation_candidates(
    tmp_path,
):
    store = _store(tmp_path)
    site = _site()
    _observe(store, site, capture_id="capture-1", fingerprint="fp-1")

    inventory = {
        "fp-1": (
            _action(kind="SELECT", selector="#plan"),
            _action(kind="LINK", policy="NAVIGATION_CANDIDATE",
                    selector="#next"),
        ),
    }

    result = plan_exploration_candidates(
        observation_store=store,
        twin_key=site.twin_key,
        profile_policy=_discovery_policy(),
        navigation_graph=_empty_graph(),
        action_inventory_by_fingerprint=inventory,
        source_fingerprint="fp-1",
    )

    assert result["candidate_count"] == 2
    assert result["rejected_count"] == 0

    risk_tiers = [c["risk_tier"] for c in result["candidates"]]
    assert risk_tiers == [
        AUTO_TWIN_EXPLORATION_RISK_REVERSIBLE,
        AUTO_TWIN_EXPLORATION_RISK_READ_ONLY_NAVIGATION,
    ]

    first = result["candidates"][0]
    assert first["twin_key"] == site.twin_key
    assert first["site_code"] == site.site_code
    assert first["state_fingerprint"] == "fp-1"
    assert first["step_depth"] == 0
    assert first["pathname"] == "/case/step"
    assert first["functional_state"] == "STATE_A"


def test_candidate_id_is_deterministic_and_order_independent(tmp_path):
    store = _store(tmp_path)
    site = _site()
    _observe(store, site, capture_id="capture-1", fingerprint="fp-1")

    inventory_a = {
        "fp-1": (
            _action(kind="SELECT", selector="#a"),
            _action(kind="RADIO", selector="#b"),
        ),
    }

    inventory_b = {
        "fp-1": (
            _action(kind="RADIO", selector="#b"),
            _action(kind="SELECT", selector="#a"),
        ),
    }

    result_a = plan_exploration_candidates(
        observation_store=store,
        twin_key=site.twin_key,
        profile_policy=_discovery_policy(),
        navigation_graph=_empty_graph(),
        action_inventory_by_fingerprint=inventory_a,
        source_fingerprint="fp-1",
    )

    result_b = plan_exploration_candidates(
        observation_store=store,
        twin_key=site.twin_key,
        profile_policy=_discovery_policy(),
        navigation_graph=_empty_graph(),
        action_inventory_by_fingerprint=inventory_b,
        source_fingerprint="fp-1",
    )

    assert result_a["plan_id"] == result_b["plan_id"]

    ids_a = [c["candidate_id"] for c in result_a["candidates"]]
    ids_b = [c["candidate_id"] for c in result_b["candidates"]]
    assert ids_a == ids_b


def test_already_visited_transition_is_excluded(tmp_path):
    store = _store(tmp_path)
    site = _site()
    _observe(store, site, capture_id="capture-1", fingerprint="fp-1")
    _observe(store, site, capture_id="capture-2", fingerprint="fp-2",
              pathname="/case/next")

    graph = build_navigation_graph(
        [_transition(before="fp-1", after="fp-2")]
    )

    inventory = {
        "fp-1": (
            _action(kind="LINK", policy="NAVIGATION_CANDIDATE",
                    selector="#link"),
        ),
    }

    result = plan_exploration_candidates(
        observation_store=store,
        twin_key=site.twin_key,
        profile_policy=_discovery_policy(),
        navigation_graph=graph,
        action_inventory_by_fingerprint=inventory,
        source_fingerprint="fp-1",
    )

    assert result["candidate_count"] == 0
    assert result["rejected_count"] == 1

    rejected = result["rejected_candidates"][0]
    assert rejected["rejection_reason"] == "TRANSITION_ALREADY_VISITED"
    assert rejected["risk_tier"] == AUTO_TWIN_EXPLORATION_RISK_ALREADY_VISITED


def test_step_budget_bounds_the_frontier_walk(tmp_path):
    store = _store(tmp_path)
    site = _site()
    _observe(store, site, capture_id="c1", fingerprint="fp-1")
    _observe(store, site, capture_id="c2", fingerprint="fp-2",
              pathname="/case/2")
    _observe(store, site, capture_id="c3", fingerprint="fp-3",
              pathname="/case/3")

    graph = build_navigation_graph([
        _transition(before="fp-1", after="fp-2", selector="#step1"),
        _transition(before="fp-2", after="fp-3", selector="#step2"),
    ])

    inventory = {
        "fp-1": (_action(kind="SELECT", selector="#a"),),
        "fp-2": (_action(kind="SELECT", selector="#b"),),
        "fp-3": (_action(kind="SELECT", selector="#c"),),
    }

    result = plan_exploration_candidates(
        observation_store=store,
        twin_key=site.twin_key,
        profile_policy=_discovery_policy(),
        navigation_graph=graph,
        action_inventory_by_fingerprint=inventory,
        source_fingerprint="fp-1",
        max_steps=1,
    )

    visited_fingerprint_states = {
        candidate["state_fingerprint"]
        for candidate in result["candidates"] + result["rejected_candidates"]
    }

    assert visited_fingerprint_states == {"fp-1", "fp-2"}
    assert "fp-3" not in result["visited_fingerprints"]


def test_max_candidates_budget_is_deterministic_and_explicit(tmp_path):
    store = _store(tmp_path)
    site = _site()
    _observe(store, site, capture_id="c1", fingerprint="fp-1")

    inventory = {
        "fp-1": tuple(
            _action(kind="SELECT", selector=f"#select-{index}")
            for index in range(5)
        ),
    }

    result = plan_exploration_candidates(
        observation_store=store,
        twin_key=site.twin_key,
        profile_policy=_discovery_policy(),
        navigation_graph=_empty_graph(),
        action_inventory_by_fingerprint=inventory,
        source_fingerprint="fp-1",
        max_candidates=2,
    )

    assert result["candidate_count"] == 2
    assert result["rejected_count"] == 3

    overflow_reasons = {
        candidate["rejection_reason"]
        for candidate in result["rejected_candidates"]
    }
    assert overflow_reasons == {"CANDIDATE_COUNT_BUDGET_EXCEEDED"}

    selectors = [c["action"]["selector"] for c in result["candidates"]]
    assert selectors == ["#select-0", "#select-1"]


@pytest.mark.parametrize(
    "kind, policy, selector, href, expected_reason",
    (
        ("SUBMIT", "REQUIRES_POLICY", "#submit", None,
         "SUBMIT_ACTION_EXCLUDED"),
        ("BUTTON", "REQUIRES_POLICY", "#captcha-solve", None,
         "CAPTCHA_ACTION_EXCLUDED"),
        ("LINK", "NAVIGATION_CANDIDATE", "#pay-now", "/checkout",
         "PAYMENT_ACTION_EXCLUDED"),
        ("BUTTON", "REQUIRES_POLICY", "#signature-pad", None,
         "SIGNATURE_ACTION_EXCLUDED"),
        ("LINK", "NAVIGATION_CANDIDATE", "#expediente-link",
         "/expediente/filing", "ADMINISTRATIVE_FILING_ACTION_EXCLUDED"),
        ("FILE_UPLOAD", "REQUIRES_POLICY", "#upload", None,
         "IRREVERSIBLE_ACTION_EXCLUDED"),
        ("BUTTON", "REQUIRES_POLICY", "#generic-button", None,
         "UNKNOWN_RISK_ACTION_EXCLUDED_BY_DEFAULT"),
    ),
)
def test_sensitive_and_unknown_actions_are_excluded_with_explicit_reason(
    tmp_path, kind, policy, selector, href, expected_reason,
):
    store = _store(tmp_path)
    site = _site()
    _observe(store, site, capture_id="c1", fingerprint="fp-1")

    inventory = {
        "fp-1": (
            _action(kind=kind, policy=policy, selector=selector, href=href),
        ),
    }

    result = plan_exploration_candidates(
        observation_store=store,
        twin_key=site.twin_key,
        profile_policy=_discovery_policy(),
        navigation_graph=_empty_graph(),
        action_inventory_by_fingerprint=inventory,
        source_fingerprint="fp-1",
    )

    assert result["candidate_count"] == 0
    assert result["rejected_count"] == 1
    assert (
        result["rejected_candidates"][0]["rejection_reason"]
        == expected_reason
    )


def test_not_visible_action_is_denied_by_underlying_safety(tmp_path):
    store = _store(tmp_path)
    site = _site()
    _observe(store, site, capture_id="c1", fingerprint="fp-1")

    inventory = {
        "fp-1": (_action(kind="SELECT", selector="#hidden", visible=False),),
    }

    result = plan_exploration_candidates(
        observation_store=store,
        twin_key=site.twin_key,
        profile_policy=_discovery_policy(),
        navigation_graph=_empty_graph(),
        action_inventory_by_fingerprint=inventory,
        source_fingerprint="fp-1",
    )

    assert result["candidate_count"] == 0
    rejected = result["rejected_candidates"][0]
    assert rejected["risk_tier"] == AUTO_TWIN_EXPLORATION_RISK_UNKNOWN
    assert rejected["rejection_reason"] == (
        "ACTION_SAFETY_DENY_ACTION_NOT_VISIBLE"
    )


def test_human_only_action_keys_are_excluded(tmp_path):
    store = _store(tmp_path)
    site = _site()
    _observe(store, site, capture_id="c1", fingerprint="fp-1")

    action = _action(kind="SELECT", selector="#human-only")

    inventory = {"fp-1": (action,)}

    human_only_keys = frozenset(
        {build_exploration_action_identity(action)}
    )

    result = plan_exploration_candidates(
        observation_store=store,
        twin_key=site.twin_key,
        profile_policy=_discovery_policy(),
        navigation_graph=_empty_graph(),
        action_inventory_by_fingerprint=inventory,
        source_fingerprint="fp-1",
        human_only_action_keys=human_only_keys,
    )

    assert result["candidate_count"] == 0
    rejected = result["rejected_candidates"][0]
    assert rejected["risk_tier"] == AUTO_TWIN_EXPLORATION_RISK_HUMAN_ONLY
    assert rejected["rejection_reason"] == "HUMAN_ONLY_EXCLUDED"


def test_invalid_navigation_graph_fails_closed(tmp_path):
    store = _store(tmp_path)

    with pytest.raises(ValueError):
        plan_exploration_candidates(
            observation_store=store,
            twin_key="twin-a",
            profile_policy=_discovery_policy(),
            navigation_graph={"not": "a graph"},
            action_inventory_by_fingerprint={},
            source_fingerprint="fp-1",
        )


def test_invalid_max_steps_and_max_candidates_fail_closed(tmp_path):
    store = _store(tmp_path)

    with pytest.raises(ValueError):
        plan_exploration_candidates(
            observation_store=store,
            twin_key="twin-a",
            profile_policy=_discovery_policy(),
            navigation_graph=_empty_graph(),
            action_inventory_by_fingerprint={},
            source_fingerprint="fp-1",
            max_steps=-1,
        )

    with pytest.raises(ValueError):
        plan_exploration_candidates(
            observation_store=store,
            twin_key="twin-a",
            profile_policy=_discovery_policy(),
            navigation_graph=_empty_graph(),
            action_inventory_by_fingerprint={},
            source_fingerprint="fp-1",
            max_candidates=0,
        )
