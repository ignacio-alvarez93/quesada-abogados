"""Política de interacción específica de sitio para QCC."""

from __future__ import annotations

from dataclasses import dataclass

from .action_safety import (
    ACTION_SAFETY_DENY,
    evaluate_action_safety,
)
from .managed_execution import (
    ManagedSiteProfile,
)
from .site_target import (
    SiteTarget,
)


SITE_INTERACTION_SCHEMA_VERSION = 1

SITE_INTERACTION_AUTOMATION_ALLOWED = (
    "AUTOMATION_ALLOWED"
)

SITE_INTERACTION_HUMAN_ONLY = (
    "HUMAN_ONLY"
)

SITE_INTERACTION_DENY = "DENY"


_ALLOWED_FINAL_DECISIONS = {
    SITE_INTERACTION_AUTOMATION_ALLOWED,
    SITE_INTERACTION_HUMAN_ONLY,
    SITE_INTERACTION_DENY,
}


class SiteInteractionPolicyConfigurationError(
    ValueError,
):
    """Configuración inválida de política de interacción."""


def _text(value):
    return str(
        value
        or ""
    ).strip()


def _normalized_code(
    value,
    *,
    error,
):
    result = _text(
        value
    ).upper()

    if not result:
        raise SiteInteractionPolicyConfigurationError(
            error
        )

    return result


def _normalize_rules(
    rules,
):
    if not isinstance(
        rules,
        dict,
    ):
        raise SiteInteractionPolicyConfigurationError(
            "SITE_INTERACTION_RULES_INVALID"
        )

    normalized = {}

    for raw_kind, raw_decision in rules.items():
        kind = _normalized_code(
            raw_kind,
            error=(
                "SITE_INTERACTION_ACTION_KIND_INVALID"
            ),
        )

        decision = _normalized_code(
            raw_decision,
            error=(
                "SITE_INTERACTION_DECISION_INVALID"
            ),
        )

        if (
            decision
            not in _ALLOWED_FINAL_DECISIONS
        ):
            raise SiteInteractionPolicyConfigurationError(
                "SITE_INTERACTION_DECISION_INVALID"
            )

        normalized[
            kind
        ] = decision

    return normalized


@dataclass(
    frozen=True,
    slots=True,
)
class SiteInteractionPolicy:
    """
    Política específica de un sitio.

    Es fail-closed:
    una acción sin regla explícita queda DENY.

    No ejecuta acciones.
    """

    policy_code: str

    site_code: str

    action_kind_rules: dict

    def __post_init__(
        self,
    ):
        object.__setattr__(
            self,
            "policy_code",
            _normalized_code(
                self.policy_code,
                error=(
                    "SITE_INTERACTION_POLICY_CODE_REQUIRED"
                ),
            ),
        )

        object.__setattr__(
            self,
            "site_code",
            _normalized_code(
                self.site_code,
                error=(
                    "SITE_INTERACTION_SITE_CODE_REQUIRED"
                ),
            ),
        )

        object.__setattr__(
            self,
            "action_kind_rules",
            _normalize_rules(
                self.action_kind_rules
            ),
        )


def _decision(
    *,
    decision,
    reason,
    safety,
):
    return {
        "schema_version":
            SITE_INTERACTION_SCHEMA_VERSION,

        "decision":
            decision,

        "automation_allowed":
            (
                decision
                == SITE_INTERACTION_AUTOMATION_ALLOWED
            ),

        "reason":
            reason,

        "safety":
            safety,
    }


def evaluate_site_interaction(
    *,
    target,
    profile,
    policy,
    action,
):
    """
    Resuelve la decisión final de una acción.

    Esta función no sustituye al Site Gate.
    El caller debe haber autorizado antes target/profile.

    Generic DENY es absoluto.
    """

    if not isinstance(
        target,
        SiteTarget,
    ):
        raise ValueError(
            "SITE_INTERACTION_TARGET_INVALID"
        )

    if not isinstance(
        profile,
        ManagedSiteProfile,
    ):
        raise ValueError(
            "SITE_INTERACTION_PROFILE_INVALID"
        )

    if not isinstance(
        policy,
        SiteInteractionPolicy,
    ):
        raise ValueError(
            "SITE_INTERACTION_POLICY_INVALID"
        )

    if (
        target.site_code
        != profile.site_code
        or profile.site_code
        != policy.site_code
    ):
        return _decision(
            decision=SITE_INTERACTION_DENY,
            reason="SITE_INTERACTION_SITE_MISMATCH",
            safety=None,
        )

    if (
        profile.interaction_policy
        != policy.policy_code
    ):
        return _decision(
            decision=SITE_INTERACTION_DENY,
            reason="SITE_INTERACTION_POLICY_MISMATCH",
            safety=None,
        )

    safety = evaluate_action_safety(
        action
    )

    if (
        safety["decision"]
        == ACTION_SAFETY_DENY
    ):
        return _decision(
            decision=SITE_INTERACTION_DENY,
            reason="GENERIC_SAFETY_DENY",
            safety=safety,
        )

    kind = _text(
        action.get("kind")
    ).upper()

    site_decision = (
        policy.action_kind_rules.get(
            kind
        )
    )

    if site_decision is None:
        return _decision(
            decision=SITE_INTERACTION_DENY,
            reason="SITE_INTERACTION_RULE_MISSING",
            safety=safety,
        )

    if (
        site_decision
        == SITE_INTERACTION_HUMAN_ONLY
    ):
        return _decision(
            decision=SITE_INTERACTION_HUMAN_ONLY,
            reason="SITE_POLICY_HUMAN_ONLY",
            safety=safety,
        )

    if (
        site_decision
        == SITE_INTERACTION_AUTOMATION_ALLOWED
    ):
        return _decision(
            decision=SITE_INTERACTION_AUTOMATION_ALLOWED,
            reason="SITE_POLICY_AUTOMATION_ALLOWED",
            safety=safety,
        )

    return _decision(
        decision=SITE_INTERACTION_DENY,
        reason="SITE_POLICY_DENY",
        safety=safety,
    )
