from copy import deepcopy
from pathlib import Path

import pytest

from backend.automation.site_architecture.navigation_graph import (
    NAVIGATION_GRAPH_SCHEMA_VERSION,
    NAVIGATION_GRAPH_TYPE,
)
from backend.automation.site_architecture.navigation_planner import (
    NAVIGATION_PLAN_ALREADY_AT_TARGET,
    NAVIGATION_PLAN_ROUTE_FOUND,
    NAVIGATION_PLAN_TYPE,
    NAVIGATION_PLAN_UNREACHABLE,
    plan_navigation_route,
)


def _edge(
    source,
    target,
    *,
    action=None,
    confidence="HIGH",
    observations=1,
    contract_changed=0,
    inconclusive=0,
):
    return {
        "source_fingerprint":
            source,

        "target_fingerprint":
            target,

        "action":
            action,

        "observation_count":
            observations,

        "confidence":
            confidence,

        "confidence_counts": {
            "HIGH":
                (
                    observations
                    if confidence == "HIGH"
                    else 0
                ),

            "MEDIUM":
                (
                    observations
                    if confidence == "MEDIUM"
                    else 0
                ),

            "LOW":
                (
                    observations
                    if confidence == "LOW"
                    else 0
                ),
        },

        "contract_changed_count":
            contract_changed,

        "inconclusive_count":
            inconclusive,
    }


def _graph(
    *edges,
    extra_nodes=(),
):
    fingerprints = set(
        extra_nodes
    )

    for edge in edges:
        fingerprints.add(
            edge[
                "source_fingerprint"
            ]
        )

        fingerprints.add(
            edge[
                "target_fingerprint"
            ]
        )

    nodes = tuple(
        {
            "fingerprint":
                fingerprint,

            "appearance_count":
                1,

            "incoming_edge_count":
                0,

            "outgoing_edge_count":
                0,
        }
        for fingerprint
        in sorted(
            fingerprints
        )
    )

    return {
        "schema_version":
            NAVIGATION_GRAPH_SCHEMA_VERSION,

        "graph_type":
            NAVIGATION_GRAPH_TYPE,

        "observation_count":
            len(
                edges
            ),

        "changed_observation_count":
            len(
                edges
            ),

        "node_count":
            len(
                nodes
            ),

        "edge_count":
            len(
                edges
            ),

        "nodes":
            nodes,

        "edges":
            tuple(
                edges
            ),
    }


def test_same_state_is_already_at_target():
    graph = _graph(
        extra_nodes=("A",)
    )

    plan = plan_navigation_route(
        graph,
        "A",
        "A",
    )

    assert plan["reachable"] is True

    assert (
        plan["status"]
        == NAVIGATION_PLAN_ALREADY_AT_TARGET
    )

    assert plan["step_count"] == 0

    assert (
        plan["route_fingerprints"]
        == ("A",)
    )

    assert plan["next_step"] is None


def test_direct_route_is_planned():
    graph = _graph(
        _edge(
            "A",
            "B",
            action={
                "kind":
                    "BUTTON",

                "policy":
                    "REQUIRES_POLICY",

                "selector":
                    "#continue",

                "frame_path":
                    "main",
            },
        )
    )

    plan = plan_navigation_route(
        graph,
        "A",
        "B",
    )

    assert plan["reachable"] is True

    assert (
        plan["status"]
        == NAVIGATION_PLAN_ROUTE_FOUND
    )

    assert plan["step_count"] == 1

    assert (
        plan["route_fingerprints"]
        == (
            "A",
            "B",
        )
    )

    assert (
        plan["next_step"][
            "action"
        ][
            "selector"
        ]
        == "#continue"
    )


def test_shortest_route_wins():
    graph = _graph(
        _edge(
            "A",
            "B",
        ),
        _edge(
            "B",
            "D",
        ),
        _edge(
            "A",
            "D",
        ),
    )

    plan = plan_navigation_route(
        graph,
        "A",
        "D",
    )

    assert plan["step_count"] == 1

    assert (
        plan["route_fingerprints"]
        == (
            "A",
            "D",
        )
    )


def test_equal_length_route_prefers_stronger_evidence():
    graph = _graph(
        _edge(
            "A",
            "B",
            confidence="LOW",
        ),
        _edge(
            "B",
            "D",
            confidence="HIGH",
        ),
        _edge(
            "A",
            "C",
            confidence="HIGH",
        ),
        _edge(
            "C",
            "D",
            confidence="HIGH",
        ),
    )

    plan = plan_navigation_route(
        graph,
        "A",
        "D",
    )

    assert plan["step_count"] == 2

    assert (
        plan["route_fingerprints"]
        == (
            "A",
            "C",
            "D",
        )
    )


def test_automatic_transition_is_valid_route_step():
    graph = _graph(
        _edge(
            "A",
            "B",
            action=None,
        )
    )

    plan = plan_navigation_route(
        graph,
        "A",
        "B",
    )

    assert plan["reachable"] is True

    assert (
        plan["next_step"][
            "action"
        ]
        is None
    )


def test_unreachable_target_is_reported():
    graph = _graph(
        _edge(
            "A",
            "B",
        ),
        extra_nodes=(
            "C",
        ),
    )

    plan = plan_navigation_route(
        graph,
        "A",
        "C",
    )

    assert plan["reachable"] is False

    assert (
        plan["status"]
        == NAVIGATION_PLAN_UNREACHABLE
    )

    assert plan["reason"] == "NO_ROUTE"
    assert plan["steps"] == ()
    assert plan["next_step"] is None


def test_unobserved_source_and_target_are_fail_closed():
    graph = _graph(
        extra_nodes=("A",)
    )

    source = plan_navigation_route(
        graph,
        "UNKNOWN",
        "A",
    )

    target = plan_navigation_route(
        graph,
        "A",
        "UNKNOWN",
    )

    assert source["reachable"] is False

    assert (
        source["reason"]
        == "SOURCE_NOT_OBSERVED"
    )

    assert target["reachable"] is False

    assert (
        target["reason"]
        == "TARGET_NOT_OBSERVED"
    )


def test_planner_does_not_mutate_graph():
    graph = _graph(
        _edge(
            "A",
            "B",
            action={
                "kind":
                    "BUTTON",

                "policy":
                    "REQUIRES_POLICY",

                "selector":
                    "#next",

                "frame_path":
                    "main",
            },
        )
    )

    before = deepcopy(
        graph
    )

    plan_navigation_route(
        graph,
        "A",
        "B",
    )

    assert graph == before


def test_invalid_graph_is_rejected():
    with pytest.raises(
        ValueError,
        match=(
            "NAVIGATION_PLAN_GRAPH_TYPE_INVALID"
        ),
    ):
        plan_navigation_route(
            {
                "schema_version":
                    1,

                "graph_type":
                    "WRONG",

                "nodes":
                    (),

                "edges":
                    (),
            },
            "A",
            "B",
        )


def test_generic_planner_contains_no_provider_coupling():
    source = Path(
        "backend/automation/"
        "site_architecture/"
        "navigation_planner.py"
    ).read_text(
        encoding="utf-8"
    )

    assert "MERCURIO" not in source.upper()
    assert "ICP_PLUS" not in source.upper()


def test_navigation_planner_is_public_api():
    from backend.automation import (
        site_architecture,
    )

    assert (
        site_architecture
        .NAVIGATION_PLAN_TYPE
        == "QCC_NAVIGATION_PLAN"
    )

    assert (
        site_architecture
        .plan_navigation_route
        is plan_navigation_route
    )

    assert (
        NAVIGATION_PLAN_TYPE
        == "QCC_NAVIGATION_PLAN"
    )
