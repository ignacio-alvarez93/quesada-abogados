"""UWT-3 Universal State / Transition Graph — provider-neutral regression suite.

Covers QCC_UWT_3_UNIVERSAL_STATE_GRAPH_V1 acceptance scenarios.

Two structurally unrelated site-neutral fixtures are used on purpose
(``_ecommerce_state`` / ``_spa_form_state``): genericity must not be proven
using a single shape, and neither fixture references any real provider.
"""

from copy import deepcopy
from types import MappingProxyType

import pytest

from backend.qcc.universal_web import (
    GraphInvariantError,
    StateGraph,
    build_action_identity,
    build_external_ui_boundary,
    build_functional_state,
)
from backend.qcc.universal_web.functional_state import FunctionalState


# ---------------------------------------------------------------------------
# Fixture A: generic e-commerce/search flow.
# ---------------------------------------------------------------------------

def _ecommerce_snapshot(node_label, *, pathname):
    return {
        "schema_version": 1,

        "captured_at":
            "2026-09-01T10:00:00.000Z",

        "page": {
            "url":
                "https://shop.example" + pathname,
            "origin":
                "https://shop.example",
            "pathname":
                pathname,
            "query":
                "",
            "title":
                node_label,
            "signature":
                None,
        },

        "elements": (
            {
                "id": None,
                "tag": "div",
                "class": "surface",
            },
        ),

        "actions": (
            {
                "frame_path": "main",
                "kind": "BUTTON",
                "policy": "STATE_CHANGE",
                "selector": "#" + node_label.lower(),
                "semantics": ("BUTTON",),
                "interaction": {
                    "state": "INTERACTABLE",
                    "visible": True,
                    "interactable": True,
                    "disabled": False,
                },
                "state_signals": {
                    "checked": None,
                    "selected": None,
                    "aria_selected": None,
                    "aria_expanded": None,
                    "aria_pressed": None,
                    "aria_current": None,
                },
                "element": {
                    "tag": "button",
                    "id": node_label.lower(),
                    "name": "",
                    "type": "button",
                    "role": "button",
                },
            },
        ),

        "catalogs": (),
        "catalog_relations": (),
    }


def _ecommerce_state(node_label, *, pathname="/shop", site_identity="ECOM_SITE"):
    return build_functional_state(
        snapshot=_ecommerce_snapshot(node_label, pathname=pathname),
        site_identity=site_identity,
    )


# ---------------------------------------------------------------------------
# Fixture B: structurally different pattern (multi-step SPA/form, with a
# catalog control present, unlike fixture A).
# ---------------------------------------------------------------------------

def _spa_form_snapshot(node_label, *, pathname):
    return {
        "schema_version": 1,

        "captured_at":
            "2026-09-01T12:00:00.000Z",

        "page": {
            "url":
                "https://app.example" + pathname,
            "origin":
                "https://app.example",
            "pathname":
                pathname,
            "query":
                "",
            "title":
                node_label,
            "signature":
                None,
        },

        "elements": (
            {
                "id": "step-indicator",
                "selector": "#step-indicator",
                "tag": "div",
                "class": "active",
            },
        ),

        "actions": (
            {
                "frame_path": "main",
                "kind": "INPUT",
                "policy": "STATE_CHANGE",
                "selector": "#field-" + node_label.lower(),
                "semantics": ("INPUT",),
                "interaction": {
                    "state": "INTERACTABLE",
                    "visible": True,
                    "interactable": True,
                    "disabled": False,
                },
                "state_signals": {
                    "checked": None,
                    "selected": None,
                    "aria_selected": None,
                    "aria_expanded": None,
                    "aria_pressed": None,
                    "aria_current": None,
                },
                "element": {
                    "tag": "input",
                    "id": "field-" + node_label.lower(),
                    "name": "",
                    "type": "text",
                    "role": "textbox",
                },
            },
        ),

        "catalogs": (
            {
                "frame_path": "main",
                "catalog_type": "native_select",
                "selector": "#" + node_label.lower() + "-options",
            },
        ),

        "catalog_relations": (),
    }


def _spa_form_state(node_label, *, pathname="/form", site_identity="SPA_FORM_SITE"):
    return build_functional_state(
        snapshot=_spa_form_snapshot(node_label, pathname=pathname),
        site_identity=site_identity,
    )


# ---------------------------------------------------------------------------
# 1. empty graph
# ---------------------------------------------------------------------------

def test_empty_graph():
    graph = StateGraph()

    assert graph.node_count == 0
    assert graph.transition_count == 0

    serialized = graph.to_dict()

    assert serialized["nodes"] == ()
    assert serialized["transitions"] == ()


# ---------------------------------------------------------------------------
# 2. add one state
# ---------------------------------------------------------------------------

def test_add_one_state():
    graph = StateGraph()
    node = graph.add_state(_ecommerce_state("SEARCH"))

    assert graph.node_count == 1
    assert graph.get_state(node.node_id) is node


# ---------------------------------------------------------------------------
# 3. repeated same state is idempotent
# ---------------------------------------------------------------------------

def test_repeated_same_state_is_idempotent():
    graph = StateGraph()

    first = graph.add_state(_ecommerce_state("SEARCH"))
    second = graph.add_state(_ecommerce_state("SEARCH"))

    assert first.node_id == second.node_id
    assert graph.node_count == 1


def test_dom_noise_does_not_create_new_node():
    base_snapshot = _ecommerce_snapshot("SEARCH", pathname="/search")
    noisy_snapshot = deepcopy(base_snapshot)
    noisy_snapshot["captured_at"] = "2026-09-02T00:00:00.000Z"

    graph = StateGraph()

    first = graph.add_state(
        build_functional_state(snapshot=base_snapshot, site_identity="ECOM_SITE")
    )
    second = graph.add_state(
        build_functional_state(snapshot=noisy_snapshot, site_identity="ECOM_SITE")
    )

    assert first.node_id == second.node_id
    assert graph.node_count == 1


def test_different_url_same_operative_state_is_one_node():
    graph = StateGraph()

    first = graph.add_state(_ecommerce_state("SEARCH", pathname="/search"))
    second = graph.add_state(_ecommerce_state("SEARCH", pathname="/search-alt-url"))

    assert first.node_id == second.node_id
    assert graph.node_count == 1


def test_same_url_can_map_to_multiple_functional_nodes():
    graph = StateGraph()
    pathname = "/dashboard"

    first = graph.add_state(_ecommerce_state("STATE_ONE", pathname=pathname))
    second = graph.add_state(_ecommerce_state("STATE_TWO", pathname=pathname))

    assert first.node_id != second.node_id
    assert graph.node_count == 2


# ---------------------------------------------------------------------------
# 4. linear: A -> B -> C
# ---------------------------------------------------------------------------

def test_linear_a_b_c():
    graph = StateGraph()

    a = graph.add_state(_ecommerce_state("SEARCH", pathname="/search"))
    b = graph.add_state(_ecommerce_state("PRODUCT", pathname="/product"))
    c = graph.add_state(_ecommerce_state("CART", pathname="/cart"))

    graph.add_transition(
        source_node_id=a.node_id,
        action=build_action_identity(kind="button", selector="#view"),
        target_node_id=b.node_id,
    )
    graph.add_transition(
        source_node_id=b.node_id,
        action=build_action_identity(kind="button", selector="#add"),
        target_node_id=c.node_id,
    )

    assert graph.node_count == 3
    assert graph.transition_count == 2
    assert graph.find_path(a.node_id, c.node_id) == (a.node_id, b.node_id, c.node_id)


# ---------------------------------------------------------------------------
# 5. bifurcation: A -> B, A -> C
# ---------------------------------------------------------------------------

def test_bifurcation_two_targets_from_same_source():
    graph = StateGraph()

    a = graph.add_state(_ecommerce_state("SEARCH", pathname="/search"))
    b = graph.add_state(_ecommerce_state("PRODUCT", pathname="/product"))
    c = graph.add_state(_ecommerce_state("CART", pathname="/cart"))

    graph.add_transition(
        source_node_id=a.node_id,
        action=build_action_identity(kind="button", selector="#view"),
        target_node_id=b.node_id,
    )
    graph.add_transition(
        source_node_id=a.node_id,
        action=build_action_identity(kind="button", selector="#add"),
        target_node_id=c.node_id,
    )

    assert graph.successors(a.node_id) == tuple(sorted({b.node_id, c.node_id}))


# ---------------------------------------------------------------------------
# 6. convergence: A -> B -> D, A -> C -> D, D exists once
# ---------------------------------------------------------------------------

def test_convergence_single_target_node():
    graph = StateGraph()

    a = graph.add_state(_ecommerce_state("SEARCH", pathname="/search"))
    b = graph.add_state(_ecommerce_state("PRODUCT", pathname="/product"))
    c = graph.add_state(_ecommerce_state("CART", pathname="/cart"))

    graph.add_transition(
        source_node_id=a.node_id,
        action=build_action_identity(kind="button", selector="#view-product"),
        target_node_id=b.node_id,
    )
    graph.add_transition(
        source_node_id=a.node_id,
        action=build_action_identity(kind="button", selector="#quick-add"),
        target_node_id=c.node_id,
    )

    d_via_b = graph.add_observed_transition(
        source_state=_ecommerce_state("PRODUCT", pathname="/product"),
        action=build_action_identity(kind="button", selector="#checkout-from-product"),
        target_state=_ecommerce_state("CHECKOUT", pathname="/checkout/from-product"),
    )
    d_via_c = graph.add_observed_transition(
        source_state=_ecommerce_state("CART", pathname="/cart"),
        action=build_action_identity(kind="button", selector="#checkout-from-cart"),
        target_state=_ecommerce_state("CHECKOUT", pathname="/checkout/from-cart"),
    )

    assert d_via_b.target_node_id == d_via_c.target_node_id
    assert graph.node_count == 4


# ---------------------------------------------------------------------------
# 7. simple loop: A -> B -> A
# ---------------------------------------------------------------------------

def test_simple_loop_a_b_a():
    graph = StateGraph()

    a = graph.add_state(_ecommerce_state("SEARCH", pathname="/search"))
    b = graph.add_state(_ecommerce_state("PRODUCT", pathname="/product"))

    graph.add_transition(
        source_node_id=a.node_id,
        action=build_action_identity(kind="button", selector="#forward"),
        target_node_id=b.node_id,
    )
    graph.add_transition(
        source_node_id=b.node_id,
        action=build_action_identity(kind="button", selector="#back"),
        target_node_id=a.node_id,
    )

    assert graph.node_count == 2
    assert graph.transition_count == 2
    assert graph.is_reachable(a.node_id, a.node_id) is True
    assert graph.find_path(a.node_id, b.node_id) == (a.node_id, b.node_id)


# ---------------------------------------------------------------------------
# 8. self-loop: A -> A
# ---------------------------------------------------------------------------

def test_self_loop_same_state():
    graph = StateGraph()

    transition = graph.add_observed_transition(
        source_state=_ecommerce_state("SEARCH", pathname="/search"),
        action=build_action_identity(kind="button", selector="#refresh"),
        target_state=_ecommerce_state("SEARCH", pathname="/search"),
    )

    assert transition.source_node_id == transition.target_node_id
    assert graph.node_count == 1
    assert graph.transition_count == 1
    assert graph.successors(transition.source_node_id) == (transition.source_node_id,)


# ---------------------------------------------------------------------------
# 9. complex loop: A -> B -> C -> B
# ---------------------------------------------------------------------------

def test_complex_loop_a_b_c_b():
    graph = StateGraph()

    a = graph.add_state(_ecommerce_state("SEARCH", pathname="/search"))
    b = graph.add_state(_ecommerce_state("PRODUCT", pathname="/product"))
    c = graph.add_state(_ecommerce_state("RELATED_PRODUCT", pathname="/related"))

    graph.add_transition(
        source_node_id=a.node_id,
        action=build_action_identity(kind="button", selector="#forward"),
        target_node_id=b.node_id,
    )
    graph.add_transition(
        source_node_id=b.node_id,
        action=build_action_identity(kind="button", selector="#forward"),
        target_node_id=c.node_id,
    )
    graph.add_transition(
        source_node_id=c.node_id,
        action=build_action_identity(kind="button", selector="#return"),
        target_node_id=b.node_id,
    )

    assert graph.successors(b.node_id) == (c.node_id,)
    assert graph.predecessors(b.node_id) == tuple(sorted({a.node_id, c.node_id}))
    assert graph.is_reachable(a.node_id, c.node_id) is True
    assert graph.find_path(a.node_id, c.node_id) == (a.node_id, b.node_id, c.node_id)


# ---------------------------------------------------------------------------
# 10. multiple actions from same source / 11. same action, different sources
# ---------------------------------------------------------------------------

def test_multiple_actions_from_same_source():
    graph = StateGraph()

    a = graph.add_state(_ecommerce_state("SEARCH", pathname="/search"))
    b = graph.add_state(_ecommerce_state("PRODUCT", pathname="/product"))
    c = graph.add_state(_ecommerce_state("CART", pathname="/cart"))

    graph.add_transition(
        source_node_id=a.node_id,
        action=build_action_identity(kind="button", selector="#view"),
        target_node_id=b.node_id,
    )
    graph.add_transition(
        source_node_id=a.node_id,
        action=build_action_identity(kind="button", selector="#add"),
        target_node_id=c.node_id,
    )

    assert len(graph.outgoing(a.node_id)) == 2


def test_same_action_identity_on_different_source_states():
    graph = StateGraph()

    a = graph.add_state(_ecommerce_state("SEARCH", pathname="/search"))
    b = graph.add_state(_ecommerce_state("PRODUCT", pathname="/product"))
    c = graph.add_state(_ecommerce_state("CART", pathname="/cart"))
    d = graph.add_state(_ecommerce_state("CHECKOUT", pathname="/checkout"))

    shared_action = build_action_identity(kind="button", selector="#continue")

    t1 = graph.add_transition(
        source_node_id=a.node_id,
        action=shared_action,
        target_node_id=b.node_id,
    )
    t2 = graph.add_transition(
        source_node_id=c.node_id,
        action=shared_action,
        target_node_id=d.node_id,
    )

    assert t1.transition_id != t2.transition_id
    assert graph.transition_count == 2


# ---------------------------------------------------------------------------
# 12. repeated transition idempotency
# ---------------------------------------------------------------------------

def test_repeated_transition_is_idempotent():
    graph = StateGraph()

    a = graph.add_state(_ecommerce_state("SEARCH", pathname="/search"))
    b = graph.add_state(_ecommerce_state("PRODUCT", pathname="/product"))
    action = build_action_identity(kind="button", selector="#view")

    first = graph.add_transition(
        source_node_id=a.node_id,
        action=action,
        target_node_id=b.node_id,
        provenance="obs-1",
    )
    second = graph.add_transition(
        source_node_id=a.node_id,
        action=action,
        target_node_id=b.node_id,
        provenance="obs-2",
    )

    assert first.transition_id == second.transition_id
    assert graph.transition_count == 1
    assert set(second.provenance) == {"obs-1", "obs-2"}


# ---------------------------------------------------------------------------
# 13. missing source fail-closed / 14. missing target fail-closed
# ---------------------------------------------------------------------------

def test_missing_source_fails_closed():
    graph = StateGraph()
    b = graph.add_state(_ecommerce_state("PRODUCT", pathname="/product"))

    with pytest.raises(GraphInvariantError):
        graph.add_transition(
            source_node_id="unknown-node",
            action=build_action_identity(kind="button", selector="#view"),
            target_node_id=b.node_id,
        )


def test_missing_target_fails_closed():
    graph = StateGraph()
    a = graph.add_state(_ecommerce_state("SEARCH", pathname="/search"))

    with pytest.raises(GraphInvariantError):
        graph.add_transition(
            source_node_id=a.node_id,
            action=build_action_identity(kind="button", selector="#view"),
            target_node_id="unknown-node",
        )


# ---------------------------------------------------------------------------
# 15. incompatible node collision fail-closed
# ---------------------------------------------------------------------------

def test_incompatible_node_collision_fails_closed():
    state_a = _ecommerce_state("SEARCH", pathname="/search")

    colliding_payload = dict(state_a.operative_payload)
    colliding_payload["actions"] = "DIFFERENT_OPERATIVE_EVIDENCE"

    colliding_state = FunctionalState(
        schema_version=state_a.schema_version,
        state_type=state_a.state_type,
        site_identity=state_a.site_identity,
        page_identity=state_a.page_identity,
        operative_payload=MappingProxyType(colliding_payload),
        fingerprint=state_a.fingerprint,
        external_ui_boundary=None,
        evidence_available=True,
    )

    graph = StateGraph()
    graph.add_state(state_a)

    with pytest.raises(GraphInvariantError):
        graph.add_state(colliding_state)


# ---------------------------------------------------------------------------
# 16. incompatible transition collision fail-closed
# ---------------------------------------------------------------------------

def test_incompatible_transition_collision_fails_closed():
    graph = StateGraph()

    a = graph.add_state(_ecommerce_state("SEARCH", pathname="/search"))
    b = graph.add_state(_ecommerce_state("PRODUCT", pathname="/product"))
    c = graph.add_state(_ecommerce_state("CART", pathname="/cart"))

    action = build_action_identity(kind="button", selector="#go")

    graph.add_transition(source_node_id=a.node_id, action=action, target_node_id=b.node_id)

    with pytest.raises(GraphInvariantError):
        graph.add_transition(source_node_id=a.node_id, action=action, target_node_id=c.node_id)


def test_malformed_action_identity_fails_closed():
    with pytest.raises(GraphInvariantError):
        build_action_identity(kind="", selector="#x")

    with pytest.raises(GraphInvariantError):
        build_action_identity(kind="button", selector="")


def test_external_ui_boundary_state_cannot_become_graph_node():
    boundary_state = build_functional_state(
        external_ui_boundary=build_external_ui_boundary(kind="FILE_DIALOG"),
    )

    graph = StateGraph()

    with pytest.raises(GraphInvariantError):
        graph.add_state(boundary_state)


def test_evidence_unavailable_state_cannot_become_graph_node():
    malformed_state = build_functional_state(snapshot={"schema_version": 999})

    graph = StateGraph()

    with pytest.raises(GraphInvariantError):
        graph.add_state(malformed_state)


# ---------------------------------------------------------------------------
# 17. outgoing / 18. incoming queries
# ---------------------------------------------------------------------------

def test_outgoing_query_returns_deterministic_order():
    graph = StateGraph()

    a = graph.add_state(_ecommerce_state("SEARCH", pathname="/search"))
    b = graph.add_state(_ecommerce_state("PRODUCT", pathname="/product"))
    c = graph.add_state(_ecommerce_state("CART", pathname="/cart"))

    graph.add_transition(
        source_node_id=a.node_id,
        action=build_action_identity(kind="button", selector="#z-last"),
        target_node_id=c.node_id,
    )
    graph.add_transition(
        source_node_id=a.node_id,
        action=build_action_identity(kind="button", selector="#a-first"),
        target_node_id=b.node_id,
    )

    outgoing = graph.outgoing(a.node_id)

    assert [transition.action.selector for transition in outgoing] == [
        "#a-first",
        "#z-last",
    ]


def test_incoming_query_returns_all_predecessors():
    graph = StateGraph()

    a = graph.add_state(_ecommerce_state("SEARCH", pathname="/search"))
    b = graph.add_state(_ecommerce_state("PRODUCT", pathname="/product"))
    c = graph.add_state(_ecommerce_state("CART", pathname="/cart"))

    graph.add_transition(
        source_node_id=a.node_id,
        action=build_action_identity(kind="button", selector="#view"),
        target_node_id=c.node_id,
    )
    graph.add_transition(
        source_node_id=b.node_id,
        action=build_action_identity(kind="button", selector="#add"),
        target_node_id=c.node_id,
    )

    incoming = graph.incoming(c.node_id)

    assert {transition.source_node_id for transition in incoming} == {
        a.node_id,
        b.node_id,
    }


# ---------------------------------------------------------------------------
# 19. successors / 20. predecessors
# ---------------------------------------------------------------------------

def test_successors_query_deduplicates_multi_edge_to_same_target():
    graph = StateGraph()

    a = graph.add_state(_ecommerce_state("SEARCH", pathname="/search"))
    b = graph.add_state(_ecommerce_state("PRODUCT", pathname="/product"))

    graph.add_transition(
        source_node_id=a.node_id,
        action=build_action_identity(kind="button", selector="#view-1"),
        target_node_id=b.node_id,
    )
    graph.add_transition(
        source_node_id=a.node_id,
        action=build_action_identity(kind="button", selector="#view-2"),
        target_node_id=b.node_id,
    )

    assert graph.successors(a.node_id) == (b.node_id,)


def test_predecessors_query_converging_sources():
    graph = StateGraph()

    a = graph.add_state(_ecommerce_state("SEARCH", pathname="/search"))
    b = graph.add_state(_ecommerce_state("PRODUCT", pathname="/product"))
    c = graph.add_state(_ecommerce_state("CART", pathname="/cart"))

    graph.add_transition(
        source_node_id=a.node_id,
        action=build_action_identity(kind="button", selector="#view"),
        target_node_id=c.node_id,
    )
    graph.add_transition(
        source_node_id=b.node_id,
        action=build_action_identity(kind="button", selector="#add"),
        target_node_id=c.node_id,
    )

    assert graph.predecessors(c.node_id) == tuple(sorted({a.node_id, b.node_id}))


def test_has_transition_query():
    graph = StateGraph()

    a = graph.add_state(_ecommerce_state("SEARCH", pathname="/search"))
    b = graph.add_state(_ecommerce_state("PRODUCT", pathname="/product"))
    action = build_action_identity(kind="button", selector="#view")

    graph.add_transition(source_node_id=a.node_id, action=action, target_node_id=b.node_id)

    assert graph.has_transition(
        source_node_id=a.node_id, action=action, target_node_id=b.node_id
    ) is True
    assert graph.has_transition(
        source_node_id=a.node_id, action=action, target_node_id=a.node_id
    ) is False


# ---------------------------------------------------------------------------
# 21. reachability true / 22. reachability false
# ---------------------------------------------------------------------------

def test_reachability_true():
    graph = StateGraph()

    a = graph.add_state(_ecommerce_state("SEARCH", pathname="/search"))
    b = graph.add_state(_ecommerce_state("PRODUCT", pathname="/product"))

    graph.add_transition(
        source_node_id=a.node_id,
        action=build_action_identity(kind="button", selector="#view"),
        target_node_id=b.node_id,
    )

    assert graph.is_reachable(a.node_id, b.node_id) is True


def test_reachability_false():
    graph = StateGraph()

    a = graph.add_state(_ecommerce_state("SEARCH", pathname="/search"))
    b = graph.add_state(_ecommerce_state("PRODUCT", pathname="/product"))

    assert graph.is_reachable(a.node_id, b.node_id) is False


# ---------------------------------------------------------------------------
# 23. deterministic path / 24. termination with cycles
# ---------------------------------------------------------------------------

def test_deterministic_path_choice_among_equal_length_routes():
    graph = StateGraph()

    a = graph.add_state(_ecommerce_state("SEARCH", pathname="/search"))
    b = graph.add_state(_ecommerce_state("PRODUCT", pathname="/product"))
    c = graph.add_state(_ecommerce_state("CART", pathname="/cart"))
    d = graph.add_state(_ecommerce_state("CHECKOUT", pathname="/checkout"))

    graph.add_transition(
        source_node_id=a.node_id,
        action=build_action_identity(kind="button", selector="#to-b"),
        target_node_id=b.node_id,
    )
    graph.add_transition(
        source_node_id=a.node_id,
        action=build_action_identity(kind="button", selector="#to-c"),
        target_node_id=c.node_id,
    )
    graph.add_transition(
        source_node_id=b.node_id,
        action=build_action_identity(kind="button", selector="#to-d"),
        target_node_id=d.node_id,
    )
    graph.add_transition(
        source_node_id=c.node_id,
        action=build_action_identity(kind="button", selector="#to-d"),
        target_node_id=d.node_id,
    )

    expected_first_hop = sorted((b.node_id, c.node_id))[0]

    path_1 = graph.find_path(a.node_id, d.node_id)
    path_2 = graph.find_path(a.node_id, d.node_id)

    assert path_1 == path_2
    assert path_1[0] == a.node_id
    assert path_1[1] == expected_first_hop
    assert path_1[-1] == d.node_id
    assert len(path_1) == 3


def test_path_algorithm_terminates_with_cycles():
    graph = StateGraph()

    a = graph.add_state(_ecommerce_state("SEARCH", pathname="/search"))
    b = graph.add_state(_ecommerce_state("PRODUCT", pathname="/product"))
    c = graph.add_state(_ecommerce_state("CART", pathname="/cart"))

    action_next = build_action_identity(kind="button", selector="#next")
    action_back = build_action_identity(kind="button", selector="#back")

    graph.add_transition(source_node_id=a.node_id, action=action_next, target_node_id=b.node_id)
    graph.add_transition(source_node_id=b.node_id, action=action_next, target_node_id=c.node_id)
    graph.add_transition(source_node_id=c.node_id, action=action_back, target_node_id=b.node_id)
    graph.add_transition(source_node_id=b.node_id, action=action_back, target_node_id=a.node_id)

    path = graph.find_path(a.node_id, c.node_id)

    assert path == (a.node_id, b.node_id, c.node_id)
    assert graph.is_reachable(c.node_id, a.node_id) is True
    assert graph.is_reachable(a.node_id, a.node_id) is True


# ---------------------------------------------------------------------------
# 25. deterministic serialization / 26. serialization round trip
# ---------------------------------------------------------------------------

def test_deterministic_serialization_independent_of_insertion_order():
    def build_forward():
        graph = StateGraph()

        a = graph.add_state(_ecommerce_state("SEARCH", pathname="/search"))
        b = graph.add_state(_ecommerce_state("PRODUCT", pathname="/product"))
        c = graph.add_state(_ecommerce_state("CART", pathname="/cart"))

        graph.add_transition(
            source_node_id=a.node_id,
            action=build_action_identity(kind="button", selector="#view"),
            target_node_id=b.node_id,
        )
        graph.add_transition(
            source_node_id=b.node_id,
            action=build_action_identity(kind="button", selector="#add"),
            target_node_id=c.node_id,
        )

        return graph

    def build_reverse():
        graph = StateGraph()

        c = graph.add_state(_ecommerce_state("CART", pathname="/cart"))
        b = graph.add_state(_ecommerce_state("PRODUCT", pathname="/product"))
        a = graph.add_state(_ecommerce_state("SEARCH", pathname="/search"))

        graph.add_transition(
            source_node_id=b.node_id,
            action=build_action_identity(kind="button", selector="#add"),
            target_node_id=c.node_id,
        )
        graph.add_transition(
            source_node_id=a.node_id,
            action=build_action_identity(kind="button", selector="#view"),
            target_node_id=b.node_id,
        )

        return graph

    assert build_forward().to_dict() == build_reverse().to_dict()


def test_serialization_round_trip_preserves_topology():
    graph = StateGraph()

    a = graph.add_state(_ecommerce_state("SEARCH", pathname="/search"))
    b = graph.add_state(_ecommerce_state("PRODUCT", pathname="/product"))
    c = graph.add_state(_ecommerce_state("CART", pathname="/cart"))

    graph.add_transition(
        source_node_id=a.node_id,
        action=build_action_identity(kind="button", selector="#view"),
        target_node_id=b.node_id,
        provenance="evidence-1",
    )
    graph.add_transition(
        source_node_id=b.node_id,
        action=build_action_identity(kind="button", selector="#add"),
        target_node_id=c.node_id,
    )

    payload = graph.to_dict()
    restored = StateGraph.from_dict(payload)

    assert restored.to_dict() == payload
    assert restored.node_count == graph.node_count
    assert restored.transition_count == graph.transition_count
    assert restored.find_path(a.node_id, c.node_id) == (
        a.node_id,
        b.node_id,
        c.node_id,
    )


def test_from_dict_rejects_malformed_schema_version():
    with pytest.raises(GraphInvariantError):
        StateGraph.from_dict({"schema_version": 999, "graph_type": "X"})


# ---------------------------------------------------------------------------
# 27. dangling edge validation / 28. disconnected components / 29. partial
# ---------------------------------------------------------------------------

def test_dangling_edge_validation_detects_corruption():
    graph = StateGraph()

    a = graph.add_state(_ecommerce_state("SEARCH", pathname="/search"))
    b = graph.add_state(_ecommerce_state("PRODUCT", pathname="/product"))

    graph.add_transition(
        source_node_id=a.node_id,
        action=build_action_identity(kind="button", selector="#view"),
        target_node_id=b.node_id,
    )

    # Simulate external corruption unreachable through the public API
    # (add_transition always enforces both endpoints exist): remove the
    # target node directly to exercise validate()'s dangling-edge check.
    del graph._nodes[b.node_id]

    result = graph.validate()

    assert result.ok is False
    assert any("DANGLING_TARGET" in error for error in result.errors)


def test_disconnected_components_are_accepted():
    graph = StateGraph()

    a = graph.add_state(_ecommerce_state("SEARCH", pathname="/search"))
    b = graph.add_state(_ecommerce_state("PRODUCT", pathname="/product"))

    graph.add_transition(
        source_node_id=a.node_id,
        action=build_action_identity(kind="button", selector="#view"),
        target_node_id=b.node_id,
    )

    isolated = graph.add_state(_spa_form_state("ENTRY", pathname="/entry"))

    result = graph.validate()

    assert result.ok is True
    assert graph.is_reachable(a.node_id, isolated.node_id) is False


def test_partial_terminal_state_without_outgoing_is_accepted():
    graph = StateGraph()
    node = graph.add_state(_ecommerce_state("CONFIRMATION", pathname="/confirmation"))

    assert graph.outgoing(node.node_id) == ()
    assert graph.validate().ok is True


# ---------------------------------------------------------------------------
# 30 / 31. site-neutral fixtures (fixture B: generic SPA/form flow)
# ---------------------------------------------------------------------------

def test_fixture_b_spa_form_linear_and_loop():
    graph = StateGraph()

    step1 = graph.add_state(_spa_form_state("STEP_ONE", pathname="/form/step-1"))
    step2 = graph.add_state(_spa_form_state("STEP_TWO", pathname="/form/step-2"))

    action_next = build_action_identity(kind="input", selector="#continue")
    action_edit = build_action_identity(kind="button", selector="#edit")

    graph.add_transition(
        source_node_id=step1.node_id, action=action_next, target_node_id=step2.node_id
    )
    graph.add_transition(
        source_node_id=step2.node_id, action=action_edit, target_node_id=step1.node_id
    )

    assert graph.node_count == 2
    assert graph.is_reachable(step1.node_id, step2.node_id) is True
    assert graph.is_reachable(step2.node_id, step1.node_id) is True
    assert graph.find_path(step1.node_id, step2.node_id) == (
        step1.node_id,
        step2.node_id,
    )


def test_fixture_b_repeated_state_is_idempotent():
    graph = StateGraph()

    first = graph.add_state(_spa_form_state("STEP_ONE", pathname="/form/step-1"))
    second = graph.add_state(_spa_form_state("STEP_ONE", pathname="/form/step-1"))

    assert first.node_id == second.node_id
    assert graph.node_count == 1


# ---------------------------------------------------------------------------
# Property / invariant tests (work order section 20).
# ---------------------------------------------------------------------------

def test_graph_traversal_never_infinite_loops_on_dense_cycle():
    graph = StateGraph()

    nodes = [
        graph.add_state(_ecommerce_state(f"NODE_{index}", pathname=f"/n{index}"))
        for index in range(5)
    ]

    for index in range(len(nodes)):
        current = nodes[index]
        following = nodes[(index + 1) % len(nodes)]

        graph.add_transition(
            source_node_id=current.node_id,
            action=build_action_identity(kind="button", selector="#next"),
            target_node_id=following.node_id,
        )

    for source in nodes:
        for target in nodes:
            # Must terminate for every pair, including source == target.
            graph.is_reachable(source.node_id, target.node_id)
            graph.find_path(source.node_id, target.node_id)

    assert graph.is_reachable(nodes[0].node_id, nodes[-1].node_id) is True
