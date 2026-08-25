"""Grafo funcional de navegación de QCC Site Architecture."""

from __future__ import annotations

import json

from .state_transition import (
    STATE_TRANSITION_CHANGED,
    STATE_TRANSITION_CONFIDENCE_HIGH,
    STATE_TRANSITION_CONFIDENCE_LOW,
    STATE_TRANSITION_CONFIDENCE_MEDIUM,
    STATE_TRANSITION_SCHEMA_VERSION,
    STATE_TRANSITION_TYPE,
    STATE_TRANSITION_UNCHANGED,
)


NAVIGATION_GRAPH_SCHEMA_VERSION = 1
NAVIGATION_GRAPH_TYPE = "QCC_NAVIGATION_GRAPH"

_CONFIDENCE_RANK = {
    STATE_TRANSITION_CONFIDENCE_LOW: 1,
    STATE_TRANSITION_CONFIDENCE_MEDIUM: 2,
    STATE_TRANSITION_CONFIDENCE_HIGH: 3,
}


def _text(value):
    value = str(
        value
        or ""
    ).strip()

    return value or None


def _normalize_action(action):
    """
    Mantiene únicamente identidad funcional PII-safe.

    El Navigation Graph no transporta text, value,
    payload ni otros datos de la acción.
    """

    if action is None:
        return None

    if not isinstance(
        action,
        dict,
    ):
        raise ValueError(
            "SITE_ARCHITECTURE_NAVIGATION_GRAPH_ACTION_INVALID"
        )

    return {
        "kind":
            _text(
                action.get("kind")
            ),

        "policy":
            _text(
                action.get("policy")
            ),

        "selector":
            _text(
                action.get("selector")
            ),

        "frame_path":
            str(
                action.get("frame_path")
                or "main"
            ),
    }


def _normalize_transition(
    transition,
):
    if not isinstance(
        transition,
        dict,
    ):
        raise ValueError(
            "SITE_ARCHITECTURE_NAVIGATION_GRAPH_TRANSITION_INVALID"
        )

    if (
        transition.get("schema_version")
        != STATE_TRANSITION_SCHEMA_VERSION
    ):
        raise ValueError(
            "SITE_ARCHITECTURE_NAVIGATION_GRAPH_TRANSITION_SCHEMA_INVALID"
        )

    if (
        transition.get("transition_type")
        != STATE_TRANSITION_TYPE
    ):
        raise ValueError(
            "SITE_ARCHITECTURE_NAVIGATION_GRAPH_TRANSITION_TYPE_INVALID"
        )

    changed = transition.get(
        "changed"
    )

    if not isinstance(
        changed,
        bool,
    ):
        raise ValueError(
            "SITE_ARCHITECTURE_NAVIGATION_GRAPH_CHANGED_INVALID"
        )

    status = _text(
        transition.get("status")
    )

    expected_status = (
        STATE_TRANSITION_CHANGED
        if changed
        else STATE_TRANSITION_UNCHANGED
    )

    if status != expected_status:
        raise ValueError(
            "SITE_ARCHITECTURE_NAVIGATION_GRAPH_STATUS_INVALID"
        )

    before = _text(
        transition.get(
            "before_fingerprint"
        )
    )

    after = _text(
        transition.get(
            "after_fingerprint"
        )
    )

    if not before or not after:
        raise ValueError(
            "SITE_ARCHITECTURE_NAVIGATION_GRAPH_FINGERPRINT_INVALID"
        )

    confidence = _text(
        transition.get(
            "confidence"
        )
    )

    if confidence not in _CONFIDENCE_RANK:
        raise ValueError(
            "SITE_ARCHITECTURE_NAVIGATION_GRAPH_CONFIDENCE_INVALID"
        )

    return {
        "changed":
            changed,

        "before_fingerprint":
            before,

        "after_fingerprint":
            after,

        "action":
            _normalize_action(
                transition.get(
                    "action"
                )
            ),

        "confidence":
            confidence,

        "contract_changed":
            bool(
                transition.get(
                    "contract_changed"
                )
            ),

        "inconclusive":
            bool(
                transition.get(
                    "inconclusive"
                )
            ),
    }


def _action_key(
    action,
):
    return json.dumps(
        action,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _edge_key(
    source,
    target,
    action,
):
    return (
        source,
        target,
        _action_key(
            action
        ),
    )


def _node(
    fingerprint,
):
    return {
        "fingerprint":
            fingerprint,

        "appearance_count":
            0,

        "incoming_edge_count":
            0,

        "outgoing_edge_count":
            0,
    }


def _edge(
    *,
    source,
    target,
    action,
    confidence,
):
    return {
        "source_fingerprint":
            source,

        "target_fingerprint":
            target,

        "action":
            action,

        "observation_count":
            0,

        # Confianza máxima realmente observada.
        # Repetir LOW no convierte evidencia en HIGH.
        "confidence":
            confidence,

        "confidence_counts": {
            STATE_TRANSITION_CONFIDENCE_HIGH:
                0,

            STATE_TRANSITION_CONFIDENCE_MEDIUM:
                0,

            STATE_TRANSITION_CONFIDENCE_LOW:
                0,
        },

        "contract_changed_count":
            0,

        "inconclusive_count":
            0,
    }


def build_navigation_graph(
    transitions,
):
    """
    Agrega observaciones QCC_STATE_TRANSITION.

    Reglas V1:
    - cualquier estado observado genera nodo;
    - FUNCTIONAL_STATE_UNCHANGED nunca genera arista;
    - aristas idénticas se deduplican;
    - observaciones repetidas aumentan evidencia;
    - el grafo describe navegación, no la autoriza.
    """

    nodes = {}
    edges = {}

    observation_count = 0
    changed_observation_count = 0

    for raw_transition in (
        transitions
        or ()
    ):
        transition = (
            _normalize_transition(
                raw_transition
            )
        )

        observation_count += 1

        source = transition[
            "before_fingerprint"
        ]

        target = transition[
            "after_fingerprint"
        ]

        for fingerprint in (
            source,
            target,
        ):
            node = nodes.setdefault(
                fingerprint,
                _node(
                    fingerprint
                ),
            )

            node[
                "appearance_count"
            ] += 1

        if not transition["changed"]:
            continue

        changed_observation_count += 1

        action = transition[
            "action"
        ]

        key = _edge_key(
            source,
            target,
            action,
        )

        edge = edges.get(
            key
        )

        if edge is None:
            edge = _edge(
                source=source,
                target=target,
                action=action,
                confidence=transition[
                    "confidence"
                ],
            )

            edges[key] = edge

        edge[
            "observation_count"
        ] += 1

        confidence = transition[
            "confidence"
        ]

        edge[
            "confidence_counts"
        ][confidence] += 1

        if (
            _CONFIDENCE_RANK[
                confidence
            ]
            > _CONFIDENCE_RANK[
                edge["confidence"]
            ]
        ):
            edge[
                "confidence"
            ] = confidence

        if transition[
            "contract_changed"
        ]:
            edge[
                "contract_changed_count"
            ] += 1

        if transition[
            "inconclusive"
        ]:
            edge[
                "inconclusive_count"
            ] += 1

    for edge in edges.values():
        nodes[
            edge["source_fingerprint"]
        ][
            "outgoing_edge_count"
        ] += 1

        nodes[
            edge["target_fingerprint"]
        ][
            "incoming_edge_count"
        ] += 1

    node_records = tuple(
        sorted(
            nodes.values(),
            key=lambda item: (
                item["fingerprint"]
            ),
        )
    )

    edge_records = tuple(
        sorted(
            edges.values(),
            key=lambda item: (
                item[
                    "source_fingerprint"
                ],
                item[
                    "target_fingerprint"
                ],
                _action_key(
                    item["action"]
                ),
            ),
        )
    )

    return {
        "schema_version":
            NAVIGATION_GRAPH_SCHEMA_VERSION,

        "graph_type":
            NAVIGATION_GRAPH_TYPE,

        "observation_count":
            observation_count,

        "changed_observation_count":
            changed_observation_count,

        "node_count":
            len(
                node_records
            ),

        "edge_count":
            len(
                edge_records
            ),

        "nodes":
            node_records,

        "edges":
            edge_records,
    }
