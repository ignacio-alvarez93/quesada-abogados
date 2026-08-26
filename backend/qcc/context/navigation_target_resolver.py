"""Resolución de objetivos semánticos sobre Navigation Knowledge.

Un estado semántico puede corresponder a varios
fingerprints funcionales históricos.

La resolución prioriza:
1. target_fingerprint explícito;
2. candidato alcanzable con menos pasos;
3. mayor evidencia semántica;
4. desempate determinista por fingerprint.

No gobierna ni ejecuta acciones.
"""

from __future__ import annotations

from backend.automation.site_architecture.navigation_planner import (
    plan_navigation_route,
)
from backend.qcc.context.navigation_intent import (
    QccNavigationIntent,
)
from backend.qcc.navigation_knowledge import (
    NavigationKnowledgeStore,
)


TARGET_RESOLUTION_EXPLICIT = (
    "EXPLICIT_FINGERPRINT"
)

TARGET_RESOLUTION_SEMANTIC = (
    "SEMANTIC_STATE"
)

TARGET_RESOLUTION_UNRESOLVED = (
    "UNRESOLVED"
)


def _text(
    value,
):
    normalized = str(
        value
        or ""
    ).strip()

    return normalized or None


def _result(
    *,
    resolved,
    reason,
    target_state=None,
    target_fingerprint=None,
    reachable=None,
    remaining_steps=None,
    candidate_count=0,
):
    return {
        "resolved":
            bool(
                resolved
            ),

        "reason":
            str(
                reason
            ),

        "target_state":
            _text(
                target_state
            ),

        "target_fingerprint":
            _text(
                target_fingerprint
            ),

        "reachable":
            (
                bool(
                    reachable
                )
                if reachable
                is not None
                else None
            ),

        "remaining_steps":
            (
                int(
                    remaining_steps
                )
                if remaining_steps
                is not None
                else None
            ),

        "candidate_count":
            int(
                candidate_count
            ),
    }


def resolve_navigation_target(
    knowledge_store,
    intent,
    *,
    current_fingerprint,
):
    """Resuelve el objetivo funcional de una sesión."""

    if not isinstance(
        knowledge_store,
        NavigationKnowledgeStore,
    ):
        raise TypeError(
            "QCC_NAVIGATION_TARGET_KNOWLEDGE_STORE_INVALID"
        )

    if not isinstance(
        intent,
        QccNavigationIntent,
    ):
        raise TypeError(
            "QCC_NAVIGATION_TARGET_INTENT_INVALID"
        )

    current = _text(
        current_fingerprint
    )

    if current is None:
        return _result(
            resolved=False,
            reason=(
                TARGET_RESOLUTION_UNRESOLVED
            ),
            target_state=(
                intent.target_state
            ),
        )

    graph = knowledge_store.build_graph(
        intent.site_code
    )

    explicit = _text(
        intent.target_fingerprint
    )

    if explicit is not None:
        try:
            plan = plan_navigation_route(
                graph,
                current,
                explicit,
            )

        except ValueError:
            return _result(
                resolved=True,
                reason=(
                    TARGET_RESOLUTION_EXPLICIT
                ),
                target_state=(
                    intent.target_state
                ),
                target_fingerprint=(
                    explicit
                ),
                reachable=False,
                remaining_steps=None,
                candidate_count=1,
            )

        return _result(
            resolved=True,
            reason=(
                TARGET_RESOLUTION_EXPLICIT
            ),
            target_state=(
                intent.target_state
            ),
            target_fingerprint=(
                explicit
            ),
            reachable=(
                plan.get(
                    "reachable"
                )
            ),
            remaining_steps=(
                plan.get(
                    "remaining_steps"
                )
                if plan.get(
                    "reachable"
                )
                else None
            ),
            candidate_count=1,
        )

    state = _text(
        intent.target_state
    )

    if state is None:
        return _result(
            resolved=False,
            reason=(
                TARGET_RESOLUTION_UNRESOLVED
            ),
        )

    candidates = (
        knowledge_store
        .resolve_state_fingerprints(
            intent.site_code,
            state,
        )
    )

    if not candidates:
        return _result(
            resolved=False,
            reason=(
                TARGET_RESOLUTION_UNRESOLVED
            ),
            target_state=state,
            candidate_count=0,
        )

    ranked = []

    for candidate in candidates:
        fingerprint = (
            candidate[
                "fingerprint"
            ]
        )

        observation_count = int(
            candidate.get(
                "observation_count",
                0,
            )
            or 0
        )

        try:
            plan = plan_navigation_route(
                graph,
                current,
                fingerprint,
            )

        except ValueError:
            continue

        if not plan.get(
            "reachable"
        ):
            continue

        ranked.append(
            (
                int(
                    plan.get(
                        "remaining_steps",
                        0,
                    )
                    or 0
                ),
                -observation_count,
                fingerprint,
            )
        )

    if not ranked:
        # Sabemos que el estado existe históricamente,
        # pero ninguno de sus fingerprints es
        # alcanzable desde CURRENT usando el grafo
        # conocido.
        return _result(
            resolved=False,
            reason=(
                TARGET_RESOLUTION_UNRESOLVED
            ),
            target_state=state,
            reachable=False,
            candidate_count=len(
                candidates
            ),
        )

    (
        remaining_steps,
        _negative_evidence,
        fingerprint,
    ) = min(
        ranked
    )

    return _result(
        resolved=True,
        reason=(
            TARGET_RESOLUTION_SEMANTIC
        ),
        target_state=state,
        target_fingerprint=(
            fingerprint
        ),
        reachable=True,
        remaining_steps=(
            remaining_steps
        ),
        candidate_count=len(
            candidates
        ),
    )
