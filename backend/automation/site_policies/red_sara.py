"""Perfiles y gobierno QCC para Red SARA.

Registro inicial conservador:

- reconoce el origin REAL gestionado;
- permite observación de estado;
- no concede automatización a ninguna acción.

El aprendizaje de comportamiento no modifica esta política.
"""

from __future__ import annotations

from backend.automation.site_architecture.managed_execution import (
    ManagedSiteProfile,
)
from backend.automation.site_architecture.managed_governance_registry import (
    ManagedSiteGovernanceOrigin,
    ManagedSiteGovernanceRegistration,
)
from backend.automation.site_architecture.site_interaction_policy import (
    SiteInteractionPolicy,
)
from backend.automation.site_architecture.site_target import (
    SiteEnvironment,
)


RED_SARA_SITE_CODE = "RED_SARA"

RED_SARA_INTERACTION_POLICY_CODE = (
    "RED_SARA_OBSERVATION_ONLY_V1"
)

RED_SARA_REAL_ORIGIN = (
    "https://reg.redsara.es"
)

RED_SARA_ALLOWED_PATH_PREFIXES = (
    "/",
)

RED_SARA_CAPABILITIES = (
    "STATE_OBSERVATION",
)


def build_red_sara_interaction_policy():
    """Fail-closed: ninguna acción REAL está autorizada."""

    return SiteInteractionPolicy(
        policy_code=(
            RED_SARA_INTERACTION_POLICY_CODE
        ),
        site_code=(
            RED_SARA_SITE_CODE
        ),
        action_kind_rules={},
    )


def build_red_sara_profile(
    environment,
):
    """Construye el perfil Red SARA REAL gestionado."""

    if not isinstance(
        environment,
        SiteEnvironment,
    ):
        try:
            environment = SiteEnvironment(
                str(
                    environment
                    or ""
                ).strip().upper()
            )

        except ValueError as exc:
            raise ValueError(
                "RED_SARA_ENVIRONMENT_INVALID"
            ) from exc

    if (
        environment
        != SiteEnvironment.REAL
    ):
        raise ValueError(
            "RED_SARA_ENVIRONMENT_INVALID"
        )

    return ManagedSiteProfile(
        site_code=(
            RED_SARA_SITE_CODE
        ),
        environment=(
            SiteEnvironment.REAL
        ),
        allowed_origins=(
            RED_SARA_REAL_ORIGIN,
        ),
        allowed_path_prefixes=(
            RED_SARA_ALLOWED_PATH_PREFIXES
        ),
        interaction_policy=(
            RED_SARA_INTERACTION_POLICY_CODE
        ),
        capabilities=(
            RED_SARA_CAPABILITIES
        ),
    )


def build_red_sara_governance_registration():
    """Registro gestionado REAL de Red SARA."""

    return ManagedSiteGovernanceRegistration(
        site_code=(
            RED_SARA_SITE_CODE
        ),
        origins=(
            ManagedSiteGovernanceOrigin(
                environment=(
                    SiteEnvironment.REAL
                ),
                origin=(
                    RED_SARA_REAL_ORIGIN
                ),
            ),
        ),
        profile_builder=(
            build_red_sara_profile
        ),
        policy_builder=(
            build_red_sara_interaction_policy
        ),
    )
