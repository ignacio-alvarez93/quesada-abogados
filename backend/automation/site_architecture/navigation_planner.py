"""Planificación descriptiva de rutas sobre QCC Navigation Graph."""

from __future__ import annotations

from collections import (
    defaultdict,
    deque,
)
from copy import deepcopy
import json

from .navigation_graph import (
    NAVIGATION_GRAPH_SCHEMA_VERSION,
    NAVIGATION_GRAPH_TYPE,
)


NAVIGATION_PLAN_SCHEMA_VERSION = 1
NAVIGATION_PLAN_TYPE = "QCC_NAVIGATION_PLAN"

NAVIGATION_PLAN_ROUTE_FOUND = "ROUTE_FOUND"
NAVIGATION_PLAN_ALREADY_AT_TARGET = (
    "ALREADY_AT_TARGET"
)
NAVIGATION_PLAN_UNREACHABLE = "UNREACHABLE"


_CONFIDENCE_RANK = {
    "LOW": 1,
    "MEDIUM": 2,
    "HIGH": 3,
}


def _text(value):
    value = str(
        value
        or ""
    ).strip()

    return value or None


def _fingerprint(
    value,
    *,
    error,
):
    result = _text(
        value
    )

    if not result:
        raise ValueError(
            error
        )

    return result


def _action_key(
    action,
):
    return json.dumps(
        action,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _edge_order_key(
    edge,
):
    """
    El planner sigue siendo descriptivo.

    Entre rutas de igual longitud prioriza
    evidencia observacional más fuerte, nunca
    permisos de ejecución.
    """

    confidence = _text(
        edge.get(
            "confidence"
        )
    )

    confidence_rank = (
        _CONFIDENCE_RANK.get(
            confidence,
            0,
        )
    )

    return (
        -confidence_rank,
        int(
            edge.get(
                "contract_changed_count",
                0,
            )
            or 0
        ),
        int(
            edge.get(
                "inconclusive_count",
                0,
            )
            or 0
        ),
        -int(
            edge.get(
                "observation_count",
                0,
            )
            or 0
        ),
        str(
            edge.get(
                "target_fingerprint"
            )
            or ""
        ),
        _action_key(
            edge.get(
                "action"
            )
        ),
    )


def _normalize_graph(
    graph,
):
    if not isinstance(
        graph,
        dict,
    ):
        raise ValueError(
            "SITE_ARCHITECTURE_NAVIGATION_PLAN_GRAPH_INVALID"
        )

    if (
        graph.get(
            "schema_version"
        )
        != NAVIGATION_GRAPH_SCHEMA_VERSION
    ):
        raise ValueError(
            "SITE_ARCHITECTURE_NAVIGATION_PLAN_GRAPH_SCHEMA_INVALID"
        )

    if (
        graph.get(
            "graph_type"
        )
        != NAVIGATION_GRAPH_TYPE
    ):
        raise ValueError(
            "SITE_ARCHITECTURE_NAVIGATION_PLAN_GRAPH_TYPE_INVALID"
        )

    raw_nodes = graph.get(
        "nodes"
    )

    raw_edges = graph.get(
        "edges"
    )

    if not isinstance(
        raw_nodes,
        (tuple, list),
    ):
        raise ValueError(
            "SITE_ARCHITECTURE_NAVIGATION_PLAN_NODES_INVALID"
        )

    if not isinstance(
        raw_edges,
        (tuple, list),
    ):
        raise ValueError(
            "SITE_ARCHITECTURE_NAVIGATION_PLAN_EDGES_INVALID"
        )

    nodes = set()

    for node in raw_nodes:
        if not isinstance(
            node,
            dict,
        ):
            raise ValueError(
                "SITE_ARCHITECTURE_NAVIGATION_PLAN_NODE_INVALID"
            )

        fingerprint = _fingerprint(
            node.get(
                "fingerprint"
            ),
            error=(
                "SITE_ARCHITECTURE_NAVIGATION_PLAN_NODE_FINGERPRINT_INVALID"
            ),
        )

        nodes.add(
            fingerprint
        )

    edges = []

    for edge in raw_edges:
        if not isinstance(
            edge,
            dict,
        ):
            raise ValueError(
                "SITE_ARCHITECTURE_NAVIGATION_PLAN_EDGE_INVALID"
            )

        source = _fingerprint(
            edge.get(
                "source_fingerprint"
            ),
            error=(
                "SITE_ARCHITECTURE_NAVIGATION_PLAN_EDGE_SOURCE_INVALID"
            ),
        )

        target = _fingerprint(
            edge.get(
                "target_fingerprint"
            ),
            error=(
                "SITE_ARCHITECTURE_NAVIGATION_PLAN_EDGE_TARGET_INVALID"
            ),
        )

        if (
            source not in nodes
            or target not in nodes
        ):
            raise ValueError(
                "SITE_ARCHITECTURE_NAVIGATION_PLAN_EDGE_NODE_UNKNOWN"
            )

        edges.append(
            edge
        )

    return (
        frozenset(
            nodes
        ),
        tuple(
            edges
        ),
    )


def _result(
    *,
    source,
    target,
    reachable,
    status,
    reason,
    route,
    steps,
    visited_node_count,
):
    steps = tuple(
        steps
    )

    return {
        "schema_version":
            NAVIGATION_PLAN_SCHEMA_VERSION,

        "plan_type":
            NAVIGATION_PLAN_TYPE,

        "source_fingerprint":
            source,

        "target_fingerprint":
            target,

        "reachable":
            bool(
                reachable
            ),

        "status":
            status,

        "reason":
            reason,

        "route_fingerprints":
            tuple(
                route
            ),

        "step_count":
            len(
                steps
            ),

        "remaining_steps":
            len(
                steps
            ),

        "next_step":
            (
                steps[0]
                if steps
                else None
            ),

        "steps":
            steps,

        "visited_node_count":
            int(
                visited_node_count
            ),
    }


def _step(
    index,
    edge,
):
    """
    Copia únicamente datos ya presentes
    en el grafo PII-safe.

    No resuelve ni inventa autorización.
    """

    return {
        "index":
            int(
                index
            ),

        "source_fingerprint":
            edge[
                "source_fingerprint"
            ],

        "target_fingerprint":
            edge[
                "target_fingerprint"
            ],

        "action":
            deepcopy(
                edge.get(
                    "action"
                )
            ),

        "confidence":
            _text(
                edge.get(
                    "confidence"
                )
            ),

        "observation_count":
            int(
                edge.get(
                    "observation_count",
                    0,
                )
                or 0
            ),

        "contract_changed_count":
            int(
                edge.get(
                    "contract_changed_count",
                    0,
                )
                or 0
            ),

        "inconclusive_count":
            int(
                edge.get(
                    "inconclusive_count",
                    0,
                )
                or 0
            ),
    }


def plan_navigation_route(
    graph,
    source_fingerprint,
    target_fingerprint,
):
    """
    Busca una ruta dirigida mínima entre dos
    fingerprints observados.

    Contrato V1:
    - solo describe rutas ya observadas;
    - no navega;
    - no ejecuta acciones;
    - no concede permisos de automatización;
    - no conoce ningún proveedor específico;
    - minimiza número de transiciones;
    - entre alternativas equivalentes prioriza
      evidencia observacional más fuerte.
    """

    source = _fingerprint(
        source_fingerprint,
        error=(
            "SITE_ARCHITECTURE_NAVIGATION_PLAN_SOURCE_REQUIRED"
        ),
    )

    target = _fingerprint(
        target_fingerprint,
        error=(
            "SITE_ARCHITECTURE_NAVIGATION_PLAN_TARGET_REQUIRED"
        ),
    )

    nodes, edges = _normalize_graph(
        graph
    )

    if source not in nodes:
        return _result(
            source=source,
            target=target,
            reachable=False,
            status=(
                NAVIGATION_PLAN_UNREACHABLE
            ),
            reason="SOURCE_NOT_OBSERVED",
            route=(),
            steps=(),
            visited_node_count=0,
        )

    if target not in nodes:
        return _result(
            source=source,
            target=target,
            reachable=False,
            status=(
                NAVIGATION_PLAN_UNREACHABLE
            ),
            reason="TARGET_NOT_OBSERVED",
            route=(),
            steps=(),
            visited_node_count=0,
        )

    if source == target:
        return _result(
            source=source,
            target=target,
            reachable=True,
            status=(
                NAVIGATION_PLAN_ALREADY_AT_TARGET
            ),
            reason="ALREADY_AT_TARGET",
            route=(
                source,
            ),
            steps=(),
            visited_node_count=1,
        )

    adjacency = defaultdict(
        list
    )

    for edge in edges:
        adjacency[
            edge[
                "source_fingerprint"
            ]
        ].append(
            edge
        )

    for outgoing in adjacency.values():
        outgoing.sort(
            key=_edge_order_key
        )

    queue = deque(
        [source]
    )

    discovered = {
        source
    }

    parent_edge = {}

    visited_node_count = 0
    found = False

    while queue:
        current = queue.popleft()

        visited_node_count += 1

        for edge in adjacency.get(
            current,
            (),
        ):
            neighbor = edge[
                "target_fingerprint"
            ]

            if neighbor in discovered:
                continue

            discovered.add(
                neighbor
            )

            parent_edge[
                neighbor
            ] = edge

            if neighbor == target:
                found = True
                queue.clear()
                break

            queue.append(
                neighbor
            )

    if not found:
        return _result(
            source=source,
            target=target,
            reachable=False,
            status=(
                NAVIGATION_PLAN_UNREACHABLE
            ),
            reason="NO_ROUTE",
            route=(),
            steps=(),
            visited_node_count=(
                visited_node_count
            ),
        )

    route_edges = []

    cursor = target

    while cursor != source:
        edge = parent_edge[
            cursor
        ]

        route_edges.append(
            edge
        )

        cursor = edge[
            "source_fingerprint"
        ]

    route_edges.reverse()

    steps = tuple(
        _step(
            index,
            edge,
        )
        for index, edge
        in enumerate(
            route_edges,
            start=1,
        )
    )

    route = [
        source
    ]

    route.extend(
        step[
            "target_fingerprint"
        ]
        for step in steps
    )

    return _result(
        source=source,
        target=target,
        reachable=True,
        status=(
            NAVIGATION_PLAN_ROUTE_FOUND
        ),
        reason="ROUTE_FOUND",
        route=route,
        steps=steps,
        visited_node_count=(
            visited_node_count
        ),
    )
