"""Gobierno JIT de la navegación viva QCC.

Consume exclusivamente datos de la captura actual:

- QCC_NAVIGATION_PLAN canónico runtime-only;
- acciones observadas en el DOM vivo;
- URL viva;
- site_code reconocido;
- Managed Site Governance Registry.

Produce únicamente una decisión descriptiva:

- decision;
- reason;
- automation_allowed.

No ejecuta acciones.
No controla navegador.
No modifica Navigation Knowledge.
"""

from __future__ import annotations

from datetime import (
    datetime,
    timezone,
)

from backend.automation.site_architecture.governed_navigation import (
    govern_navigation_plan,
)
from backend.automation.site_architecture.managed_governance_registry import (
    ManagedSiteGovernanceRegistry,
)
from backend.automation.site_architecture.site_interaction_policy import (
    SITE_INTERACTION_DENY,
)
from backend.qcc.context.store import (
    QccContextStore,
)
from backend.qcc.contracts.live_navigation import (
    QccLiveNavigationContext,
)


LIVE_GOVERNANCE_APPLIED = "APPLIED"

LIVE_GOVERNANCE_NO_ACTIVE_SESSION = (
    "NO_ACTIVE_SESSION"
)

LIVE_GOVERNANCE_NO_CURRENT = (
    "NO_CURRENT"
)

LIVE_GOVERNANCE_STALE_SESSION = (
    "STALE_SESSION"
)

LIVE_GOVERNANCE_SITE_REQUIRED = (
    "SITE_REQUIRED"
)

LIVE_GOVERNANCE_SITE_MISMATCH = (
    "SITE_MISMATCH"
)

LIVE_GOVERNANCE_PLANNING_UNAVAILABLE = (
    "PLANNING_UNAVAILABLE"
)

LIVE_GOVERNANCE_RUNTIME_PLAN_UNAVAILABLE = (
    "RUNTIME_PLAN_UNAVAILABLE"
)

LIVE_GOVERNANCE_MANAGED_SITE_UNRESOLVED = (
    "MANAGED_SITE_UNRESOLVED"
)

LIVE_GOVERNANCE_EVALUATION_ERROR = (
    "GOVERNANCE_EVALUATION_ERROR"
)


def _code(
    value,
):
    normalized = str(
        value
        or ""
    ).strip().upper()

    return normalized or None


def _result(
    *,
    applied,
    reason,
    decision=None,
    automation_allowed=None,
    revision=None,
):
    return {
        "applied":
            bool(
                applied
            ),

        "reason":
            str(
                reason
            ),

        "decision":
            (
                str(
                    decision
                )
                if decision is not None
                else None
            ),

        "automation_allowed":
            (
                bool(
                    automation_allowed
                )
                if automation_allowed
                is not None
                else None
            ),

        "revision":
            (
                int(
                    revision
                )
                if revision is not None
                else None
            ),
    }


def _project_decision(
    context_store,
    current,
    *,
    decision,
    reason,
    automation_allowed,
):
    """Copia la navegación y sustituye solo governance."""

    navigation = QccLiveNavigationContext(
        session_id=(
            current.session_id
        ),

        updated_at=datetime.now(
            timezone.utc
        ),

        current_state=(
            current.current_state
        ),

        current_fingerprint=(
            current.current_fingerprint
        ),

        target_state=(
            current.target_state
        ),

        target_fingerprint=(
            current.target_fingerprint
        ),

        route_reachable=(
            current.route_reachable
        ),

        remaining_steps=(
            current.remaining_steps
        ),

        next_step_kind=(
            current.next_step_kind
        ),

        next_step_policy=(
            current.next_step_policy
        ),

        next_step_selector=(
            current.next_step_selector
        ),

        next_step_frame_path=(
            current.next_step_frame_path
        ),

        next_step_confidence=(
            current.next_step_confidence
        ),

        governance_decision=(
            decision
        ),

        governance_reason=(
            reason
        ),

        automation_allowed=(
            bool(
                automation_allowed
            )
        ),

        display_title=(
            current.display_title
        ),

        display_instruction=(
            current.display_instruction
        ),
    )

    return (
        context_store
        .set_live_navigation(
            navigation
        )
    )


def _deny(
    context_store,
    current,
    *,
    reason,
):
    try:
        revision = (
            _project_decision(
                context_store,
                current,
                decision=(
                    SITE_INTERACTION_DENY
                ),
                reason=reason,
                automation_allowed=False,
            )
        )

    except ValueError:
        return _result(
            applied=False,
            reason=(
                LIVE_GOVERNANCE_STALE_SESSION
            ),
        )

    return _result(
        applied=True,
        reason=reason,
        decision=(
            SITE_INTERACTION_DENY
        ),
        automation_allowed=False,
        revision=revision,
    )


def apply_live_navigation_governance(
    context_store,
    governance_registry,
    *,
    planning_result,
    live_actions,
    page_url,
    site_code,
):
    """Gobierna JIT solo el siguiente paso vivo.

    `planning_result` debe ser el resultado de
    refresh_live_navigation_plan(...,
        include_runtime_plan=True).

    El plan NO se reconstruye desde /qcc/context.
    """

    if not isinstance(
        context_store,
        QccContextStore,
    ):
        raise TypeError(
            "QCC_LIVE_GOVERNANCE_CONTEXT_STORE_INVALID"
        )

    if not isinstance(
        governance_registry,
        ManagedSiteGovernanceRegistry,
    ):
        raise TypeError(
            "QCC_LIVE_GOVERNANCE_REGISTRY_INVALID"
        )

    session = (
        context_store
        .get_active_session()
    )

    if session is None:
        return _result(
            applied=False,
            reason=(
                LIVE_GOVERNANCE_NO_ACTIVE_SESSION
            ),
        )

    current = (
        context_store
        .get_live_navigation()
    )

    if current is None:
        return _result(
            applied=False,
            reason=(
                LIVE_GOVERNANCE_NO_CURRENT
            ),
        )

    if (
        current.session_id
        != session.session_id
    ):
        return _result(
            applied=False,
            reason=(
                LIVE_GOVERNANCE_STALE_SESSION
            ),
        )

    normalized_site = _code(
        site_code
    )

    if normalized_site is None:
        return _deny(
            context_store,
            current,
            reason=(
                LIVE_GOVERNANCE_SITE_REQUIRED
            ),
        )

    if (
        _code(
            session.provider
        )
        != normalized_site
    ):
        return _deny(
            context_store,
            current,
            reason=(
                LIVE_GOVERNANCE_SITE_MISMATCH
            ),
        )

    if not isinstance(
        planning_result,
        dict,
    ):
        return _result(
            applied=False,
            reason=(
                LIVE_GOVERNANCE_PLANNING_UNAVAILABLE
            ),
        )

    planning = planning_result.get(
        "planning"
    )

    if not isinstance(
        planning,
        dict,
    ):
        return _result(
            applied=False,
            reason=(
                LIVE_GOVERNANCE_PLANNING_UNAVAILABLE
            ),
        )

    runtime_plan = planning.get(
        "runtime_plan"
    )

    if not isinstance(
        runtime_plan,
        dict,
    ):
        return _result(
            applied=False,
            reason=(
                LIVE_GOVERNANCE_RUNTIME_PLAN_UNAVAILABLE
            ),
        )

    if not isinstance(
        live_actions,
        (tuple, list),
    ):
        return _deny(
            context_store,
            current,
            reason=(
                "LIVE_ACTION_EVIDENCE_INVALID"
            ),
        )

    try:
        resolved = (
            governance_registry
            .resolve(
                url=page_url,
                site_code=(
                    normalized_site
                ),
            )
        )

    except (
        TypeError,
        ValueError,
    ):
        resolved = None

    if resolved is None:
        return _deny(
            context_store,
            current,
            reason=(
                LIVE_GOVERNANCE_MANAGED_SITE_UNRESOLVED
            ),
        )

    try:
        governed = (
            govern_navigation_plan(
                runtime_plan,
                target=(
                    resolved.target
                ),
                profile=(
                    resolved.profile
                ),
                policy=(
                    resolved.policy
                ),
                current_actions=(
                    live_actions
                ),
            )
        )

    except (
        TypeError,
        ValueError,
    ):
        return _deny(
            context_store,
            current,
            reason=(
                LIVE_GOVERNANCE_EVALUATION_ERROR
            ),
        )

    decision = governed.get(
        "decision"
    )

    reason = governed.get(
        "reason"
    )

    automation_allowed = (
        governed.get(
            "automation_allowed"
        )
    )

    if (
        not decision
        or not reason
        or not isinstance(
            automation_allowed,
            bool,
        )
    ):
        return _deny(
            context_store,
            current,
            reason=(
                LIVE_GOVERNANCE_EVALUATION_ERROR
            ),
        )

    try:
        revision = (
            _project_decision(
                context_store,
                current,
                decision=decision,
                reason=reason,
                automation_allowed=(
                    automation_allowed
                ),
            )
        )

    except ValueError:
        return _result(
            applied=False,
            reason=(
                LIVE_GOVERNANCE_STALE_SESSION
            ),
        )

    return _result(
        applied=True,
        reason=(
            LIVE_GOVERNANCE_APPLIED
        ),
        decision=decision,
        automation_allowed=(
            automation_allowed
        ),
        revision=revision,
    )
