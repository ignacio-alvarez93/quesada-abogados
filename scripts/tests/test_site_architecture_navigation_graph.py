from copy import deepcopy
import json

import pytest

from backend.automation.site_architecture.navigation_graph import (
    NAVIGATION_GRAPH_TYPE,
    build_navigation_graph,
)
from backend.automation.site_architecture.state_transition import (
    detect_state_transition,
)


def _snapshot(
    pathname="/form",
    selected=False,
):
    return {
        "schema_version": 1,

        "page": {
            "url":
                f"https://example.test{pathname}",

            "origin":
                "https://example.test",

            "pathname":
                pathname,

            "query":
                "",

            "title":
                "Test",

            "signature":
                None,
        },

        "elements":
            (),

        "actions": (
            {
                "frame_path":
                    "main",

                "kind":
                    "TAB",

                "policy":
                    "NAVIGATION_CANDIDATE",

                "selector":
                    "#tab",

                "semantics":
                    ("BUTTON",),

                "interaction": {
                    "state":
                        "INTERACTABLE",

                    "visible":
                        True,

                    "interactable":
                        True,

                    "disabled":
                        False,
                },

                "state_signals": {
                    "aria_selected":
                        selected,

                    "aria_expanded":
                        None,

                    "aria_pressed":
                        None,

                    "aria_current":
                        None,
                },

                "element": {
                    "tag":
                        "button",

                    "id":
                        "tab",

                    "name":
                        "",

                    "type":
                        "button",

                    "role":
                        "tab",
                },
            },
        ),

        "catalogs":
            (),

        "catalog_relations":
            (),
    }


def _changed_transition(
    *,
    action=None,
):
    before = _snapshot(
        selected=False
    )

    after = _snapshot(
        selected=True
    )

    return detect_state_transition(
        before,
        after,
        action=action,
    )


def test_graph_records_observed_state_without_false_edge():
    snapshot = _snapshot()

    transition = detect_state_transition(
        snapshot,
        deepcopy(snapshot),
    )

    graph = build_navigation_graph(
        [transition]
    )

    assert (
        graph["graph_type"]
        == NAVIGATION_GRAPH_TYPE
    )

    assert graph["node_count"] == 1
    assert graph["edge_count"] == 0

    assert (
        graph[
            "changed_observation_count"
        ]
        == 0
    )


def test_changed_transition_creates_edge():
    transition = _changed_transition(
        action={
            "kind":
                "TAB",

            "policy":
                "NAVIGATION_CANDIDATE",

            "selector":
                "#tab",

            "frame_path":
                "main",
        }
    )

    graph = build_navigation_graph(
        [transition]
    )

    assert graph["node_count"] == 2
    assert graph["edge_count"] == 1

    edge = graph["edges"][0]

    assert (
        edge["source_fingerprint"]
        == transition[
            "before_fingerprint"
        ]
    )

    assert (
        edge["target_fingerprint"]
        == transition[
            "after_fingerprint"
        ]
    )

    assert edge["action"] == {
        "kind":
            "TAB",

        "policy":
            "NAVIGATION_CANDIDATE",

        "selector":
            "#tab",

        "frame_path":
            "main",
    }


def test_repeated_transition_increases_evidence_not_edges():
    transition = _changed_transition(
        action={
            "kind":
                "TAB",

            "policy":
                "NAVIGATION_CANDIDATE",

            "selector":
                "#tab",

            "frame_path":
                "main",
        }
    )

    graph = build_navigation_graph(
        [
            transition,
            deepcopy(
                transition
            ),
        ]
    )

    assert graph["edge_count"] == 1

    assert (
        graph["edges"][0][
            "observation_count"
        ]
        == 2
    )


def test_different_action_identity_creates_different_edge():
    first = _changed_transition(
        action={
            "kind": "BUTTON",
            "policy":
                "REQUIRES_POLICY",
            "selector": "#one",
        }
    )

    second = deepcopy(first)

    second["action"] = {
        "kind": "BUTTON",
        "policy":
            "REQUIRES_POLICY",
        "selector": "#two",
        "frame_path": "main",
    }

    graph = build_navigation_graph(
        [
            first,
            second,
        ]
    )

    assert graph["edge_count"] == 2


def test_graph_does_not_transport_contract_diff_or_action_payload():
    transition = _changed_transition(
        action={
            "kind": "BUTTON",
            "policy":
                "REQUIRES_POLICY",
            "selector": "#continue",
            "frame_path": "main",

            "text":
                "PERSONAL DATA",

            "value":
                "SECRET",
        }
    )

    transition[
        "contract_diff"
    ] = {
        "secret":
            "MUST-NOT-LEAK"
    }

    graph = build_navigation_graph(
        [transition]
    )

    serialized = json.dumps(
        graph,
        ensure_ascii=False,
    )

    assert "MUST-NOT-LEAK" not in serialized
    assert "PERSONAL DATA" not in serialized
    assert "SECRET" not in serialized


def test_graph_is_deterministic_for_transition_order():
    first = _changed_transition(
        action={
            "kind": "BUTTON",
            "policy":
                "REQUIRES_POLICY",
            "selector": "#one",
        }
    )

    before = _snapshot(
        pathname="/form"
    )

    after = _snapshot(
        pathname="/next"
    )

    second = detect_state_transition(
        before,
        after,
        action={
            "kind":
                "LINK",

            "policy":
                "NAVIGATION_CANDIDATE",

            "selector":
                "#next",
        },
    )

    a = build_navigation_graph(
        [
            first,
            second,
        ]
    )

    b = build_navigation_graph(
        [
            second,
            first,
        ]
    )

    assert a == b


def test_graph_rejects_non_transition_input():
    with pytest.raises(
        ValueError,
        match=(
            "NAVIGATION_GRAPH_TRANSITION_INVALID"
        ),
    ):
        build_navigation_graph(
            ["click"]
        )



def test_navigation_graph_is_public_api():
    from backend.automation import (
        site_architecture,
    )

    assert (
        site_architecture
        .NAVIGATION_GRAPH_SCHEMA_VERSION
        == 1
    )

    assert (
        site_architecture
        .NAVIGATION_GRAPH_TYPE
        == "QCC_NAVIGATION_GRAPH"
    )

    assert (
        site_architecture
        .build_navigation_graph
        is build_navigation_graph
    )
