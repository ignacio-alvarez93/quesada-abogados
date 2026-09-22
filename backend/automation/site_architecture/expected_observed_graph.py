"""Expected Graph vs Observed Graph comparator (V1).

QCC_GRAPH_INTELLIGENCE_V1

Read model only. This module NEVER grants execution authority and NEVER
mutates anything: it takes an ``ExpectedGraph`` (contract / approved
architecture / materialized known graph, fingerprint-addressed) and an
Observed Graph (the output of
``backend.automation.site_architecture.navigation_graph.
build_navigation_graph``, i.e. what QCC has actually learned from
evidence) and produces a deterministic, explainable diff.

Provider-neutral: nothing here references any specific site/provider.

Classifications:

    MATCH
    NEW_STATE
    NEW_TRANSITION
    MISSING_EXPECTED_STATE
    MISSING_EXPECTED_TRANSITION
    DIVERGENT_TARGET
    INSUFFICIENT_EVIDENCE

HUMAN_ONLY transitions are valid graph knowledge like any other: this
module carries action kind/selector/frame_path only, never policy, and
never treats confidence/evidence counts as an authorization signal.
"""

from __future__ import annotations

from dataclasses import (
    dataclass,
)


GRAPH_COMPARISON_SCHEMA_VERSION = 1

GRAPH_CLASSIFICATION_MATCH = "MATCH"
GRAPH_CLASSIFICATION_NEW_STATE = "NEW_STATE"
GRAPH_CLASSIFICATION_NEW_TRANSITION = "NEW_TRANSITION"
GRAPH_CLASSIFICATION_MISSING_EXPECTED_STATE = "MISSING_EXPECTED_STATE"
GRAPH_CLASSIFICATION_MISSING_EXPECTED_TRANSITION = (
    "MISSING_EXPECTED_TRANSITION"
)
GRAPH_CLASSIFICATION_DIVERGENT_TARGET = "DIVERGENT_TARGET"
GRAPH_CLASSIFICATION_INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


def _text(value):
    return str(value or "").strip()


def _required_text(value, error):
    text = _text(value)

    if not text:
        raise ValueError(error)

    return text


@dataclass(
    frozen=True,
    slots=True,
)
class ExpectedGraphState:
    """One contract-approved state, addressed by its materialized
    fingerprint. ``state_id`` is a human-readable label only, carried
    for explainability, never used for matching."""

    state_id: str
    fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "state_id",
            _required_text(
                self.state_id,
                "QCC_EXPECTED_GRAPH_STATE_ID_REQUIRED",
            ),
        )

        object.__setattr__(
            self,
            "fingerprint",
            _required_text(
                self.fingerprint,
                "QCC_EXPECTED_GRAPH_STATE_FINGERPRINT_REQUIRED",
            ).lower(),
        )


@dataclass(
    frozen=True,
    slots=True,
)
class ExpectedGraphTransition:
    """One contract-approved transition between two expected states,
    identified by ``state_id`` (resolved to fingerprints against the
    owning ``ExpectedGraph`` at construction time)."""

    from_state_id: str
    to_state_id: str

    action_kind: str
    action_selector: str
    action_frame_path: str = "main"

    # Route identity respected: two contextually distinct transitions
    # sharing the same physical action are different expected edges.
    contextual: bool = False
    context_signature: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "from_state_id",
            _required_text(
                self.from_state_id,
                "QCC_EXPECTED_GRAPH_TRANSITION_FROM_STATE_REQUIRED",
            ),
        )

        object.__setattr__(
            self,
            "to_state_id",
            _required_text(
                self.to_state_id,
                "QCC_EXPECTED_GRAPH_TRANSITION_TO_STATE_REQUIRED",
            ),
        )

        object.__setattr__(
            self,
            "action_kind",
            _required_text(
                self.action_kind,
                "QCC_EXPECTED_GRAPH_TRANSITION_KIND_REQUIRED",
            ).upper(),
        )

        object.__setattr__(
            self,
            "action_selector",
            _required_text(
                self.action_selector,
                "QCC_EXPECTED_GRAPH_TRANSITION_SELECTOR_REQUIRED",
            ),
        )

        object.__setattr__(
            self,
            "action_frame_path",
            _text(self.action_frame_path) or "main",
        )

        object.__setattr__(
            self,
            "context_signature",
            _text(self.context_signature) or None,
        )

    def action_identity(self) -> tuple[str, str, str]:
        return (
            self.action_kind,
            self.action_selector,
            self.action_frame_path,
        )

    def route_identity(self) -> tuple:
        """Full route identity, including contextual scoping.

        Two transitions with the same physical action but different
        context (e.g. a different selected radio option) are distinct
        routes and must never be collapsed into one comparison entry.
        """

        return (
            self.action_identity(),
            bool(self.contextual),
            self.context_signature,
        )


@dataclass(
    frozen=True,
    slots=True,
)
class ExpectedGraph:
    states: tuple[ExpectedGraphState, ...]
    transitions: tuple[ExpectedGraphTransition, ...]

    def __post_init__(self) -> None:
        states = tuple(self.states or ())

        for state in states:
            if not isinstance(state, ExpectedGraphState):
                raise TypeError(
                    "QCC_EXPECTED_GRAPH_STATE_INVALID"
                )

        state_ids = [state.state_id for state in states]

        if len(state_ids) != len(set(state_ids)):
            raise ValueError(
                "QCC_EXPECTED_GRAPH_STATE_ID_DUPLICATE"
            )

        transitions = tuple(self.transitions or ())

        for transition in transitions:
            if not isinstance(transition, ExpectedGraphTransition):
                raise TypeError(
                    "QCC_EXPECTED_GRAPH_TRANSITION_INVALID"
                )

            if transition.from_state_id not in state_ids:
                raise ValueError(
                    "QCC_EXPECTED_GRAPH_TRANSITION_FROM_STATE_UNKNOWN"
                )

            if transition.to_state_id not in state_ids:
                raise ValueError(
                    "QCC_EXPECTED_GRAPH_TRANSITION_TO_STATE_UNKNOWN"
                )

        object.__setattr__(self, "states", states)
        object.__setattr__(self, "transitions", transitions)

    def fingerprint_by_state_id(self) -> dict:
        return {
            state.state_id: state.fingerprint
            for state in self.states
        }

    def state_id_by_fingerprint(self) -> dict:
        return {
            state.fingerprint: state.state_id
            for state in self.states
        }


@dataclass(
    frozen=True,
    slots=True,
)
class GraphComparisonEntry:
    classification: str
    explanation: str
    expected: dict | None
    observed: dict | None
    evidence: dict | None


def _observed_nodes_by_fingerprint(observed_graph) -> dict:
    return {
        node["fingerprint"]: node
        for node in observed_graph.get("nodes") or ()
    }


def _observed_edges_by_source_and_action(observed_graph) -> dict:
    index = {}

    for edge in observed_graph.get("edges") or ():
        action = edge.get("action") or {}

        key = (
            edge["source_fingerprint"],
            _text(action.get("kind")).upper(),
            _text(action.get("selector")),
            _text(action.get("frame_path")) or "main",
        )

        index.setdefault(key, []).append(edge)

    return index


def compare_expected_to_observed_graph(
    *,
    expected: ExpectedGraph,
    observed_graph: dict,
) -> dict:
    """Deterministically diff ``expected`` against ``observed_graph``.

    ``observed_graph`` must be the exact dict shape produced by
    ``build_navigation_graph`` (fingerprint-addressed nodes/edges).

    This function carries no execution authority and never reports a
    confidence/evidence signal as if it were a policy decision: callers
    consuming ``evidence`` for anything beyond explainability are out of
    contract.
    """

    if not isinstance(expected, ExpectedGraph):
        raise TypeError(
            "QCC_EXPECTED_GRAPH_INVALID"
        )

    if not isinstance(observed_graph, dict):
        raise TypeError(
            "QCC_OBSERVED_GRAPH_INVALID"
        )

    observed_nodes = _observed_nodes_by_fingerprint(observed_graph)
    observed_edge_index = _observed_edges_by_source_and_action(
        observed_graph
    )

    state_entries = []

    expected_fingerprints = {
        state.fingerprint
        for state in expected.states
    }

    for state in expected.states:
        node = observed_nodes.get(state.fingerprint)

        if node is not None:
            state_entries.append(
                GraphComparisonEntry(
                    classification=GRAPH_CLASSIFICATION_MATCH,
                    explanation=(
                        "Expected state "
                        + state.state_id
                        + " has been observed."
                    ),
                    expected={
                        "state_id": state.state_id,
                        "fingerprint": state.fingerprint,
                    },
                    observed=dict(node),
                    evidence={
                        "appearance_count":
                            node.get("appearance_count"),
                    },
                )
            )
        else:
            state_entries.append(
                GraphComparisonEntry(
                    classification=(
                        GRAPH_CLASSIFICATION_MISSING_EXPECTED_STATE
                    ),
                    explanation=(
                        "Expected state "
                        + state.state_id
                        + " has never been observed."
                    ),
                    expected={
                        "state_id": state.state_id,
                        "fingerprint": state.fingerprint,
                    },
                    observed=None,
                    evidence=None,
                )
            )

    for fingerprint, node in observed_nodes.items():
        if fingerprint in expected_fingerprints:
            continue

        state_entries.append(
            GraphComparisonEntry(
                classification=GRAPH_CLASSIFICATION_NEW_STATE,
                explanation=(
                    "Observed state "
                    + fingerprint
                    + " is not part of the expected graph."
                ),
                expected=None,
                observed=dict(node),
                evidence={
                    "appearance_count":
                        node.get("appearance_count"),
                },
            )
        )

    transition_entries = []
    matched_observed_edge_keys = set()

    fingerprint_by_state_id = expected.fingerprint_by_state_id()

    for transition in expected.transitions:
        from_fingerprint = fingerprint_by_state_id[
            transition.from_state_id
        ]
        to_fingerprint = fingerprint_by_state_id[
            transition.to_state_id
        ]

        key = (
            from_fingerprint,
            *transition.action_identity(),
        )

        candidate_edges = observed_edge_index.get(key) or []

        matching_edge = next(
            (
                edge
                for edge in candidate_edges
                if edge["target_fingerprint"] == to_fingerprint
            ),
            None,
        )

        expected_payload = {
            "from_state_id": transition.from_state_id,
            "to_state_id": transition.to_state_id,
            "action": {
                "kind": transition.action_kind,
                "selector": transition.action_selector,
                "frame_path": transition.action_frame_path,
            },
            "contextual": transition.contextual,
            "context_signature": transition.context_signature,
        }

        if matching_edge is not None:
            matched_observed_edge_keys.add(
                (
                    matching_edge["source_fingerprint"],
                    matching_edge["target_fingerprint"],
                    _text(
                        (matching_edge.get("action") or {}).get("kind")
                    ).upper(),
                    _text(
                        (matching_edge.get("action") or {}).get(
                            "selector"
                        )
                    ),
                )
            )

            transition_entries.append(
                GraphComparisonEntry(
                    classification=GRAPH_CLASSIFICATION_MATCH,
                    explanation=(
                        "Expected transition "
                        + transition.from_state_id
                        + " -> "
                        + transition.to_state_id
                        + " has been observed with the expected"
                        " target."
                    ),
                    expected=expected_payload,
                    observed=dict(matching_edge),
                    evidence={
                        "observation_count":
                            matching_edge.get("observation_count"),

                        "confidence":
                            matching_edge.get("confidence"),
                    },
                )
            )
            continue

        if candidate_edges:
            # The exact action was observed from the expected source
            # state, but it led somewhere other than the contract.
            divergent = candidate_edges[0]

            matched_observed_edge_keys.add(
                (
                    divergent["source_fingerprint"],
                    divergent["target_fingerprint"],
                    _text(
                        (divergent.get("action") or {}).get("kind")
                    ).upper(),
                    _text(
                        (divergent.get("action") or {}).get(
                            "selector"
                        )
                    ),
                )
            )

            transition_entries.append(
                GraphComparisonEntry(
                    classification=(
                        GRAPH_CLASSIFICATION_DIVERGENT_TARGET
                    ),
                    explanation=(
                        "Expected transition "
                        + transition.from_state_id
                        + " -> "
                        + transition.to_state_id
                        + " was observed to reach a different"
                        " target state."
                    ),
                    expected=expected_payload,
                    observed=dict(divergent),
                    evidence={
                        "observation_count":
                            divergent.get("observation_count"),

                        "confidence":
                            divergent.get("confidence"),
                    },
                )
            )
            continue

        source_node = observed_nodes.get(from_fingerprint)

        if source_node is None or not source_node.get(
            "appearance_count"
        ):
            transition_entries.append(
                GraphComparisonEntry(
                    classification=(
                        GRAPH_CLASSIFICATION_INSUFFICIENT_EVIDENCE
                    ),
                    explanation=(
                        "Expected transition "
                        + transition.from_state_id
                        + " -> "
                        + transition.to_state_id
                        + " could not be evaluated: its source state"
                        " has not been observed yet."
                    ),
                    expected=expected_payload,
                    observed=None,
                    evidence=None,
                )
            )
            continue

        transition_entries.append(
            GraphComparisonEntry(
                classification=(
                    GRAPH_CLASSIFICATION_MISSING_EXPECTED_TRANSITION
                ),
                explanation=(
                    "Expected transition "
                    + transition.from_state_id
                    + " -> "
                    + transition.to_state_id
                    + " has not been observed even though its source"
                    " state has."
                ),
                expected=expected_payload,
                observed=None,
                evidence={
                    "source_appearance_count":
                        source_node.get("appearance_count"),
                },
            )
        )

    for edge in observed_graph.get("edges") or ():
        action = edge.get("action") or {}

        key = (
            edge["source_fingerprint"],
            edge["target_fingerprint"],
            _text(action.get("kind")).upper(),
            _text(action.get("selector")),
        )

        if key in matched_observed_edge_keys:
            continue

        transition_entries.append(
            GraphComparisonEntry(
                classification=GRAPH_CLASSIFICATION_NEW_TRANSITION,
                explanation=(
                    "Observed transition from "
                    + edge["source_fingerprint"]
                    + " is not part of the expected graph."
                ),
                expected=None,
                observed=dict(edge),
                evidence={
                    "observation_count":
                        edge.get("observation_count"),

                    "confidence":
                        edge.get("confidence"),
                },
            )
        )

    return {
        "schema_version": GRAPH_COMPARISON_SCHEMA_VERSION,
        "state_entries": tuple(state_entries),
        "transition_entries": tuple(transition_entries),
    }
