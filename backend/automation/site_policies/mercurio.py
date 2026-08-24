"""Perfiles y política de interacción QCC para Mercurio."""

from __future__ import annotations

from backend.automation.site_architecture.managed_execution import (
    ManagedSiteProfile,
)
from backend.automation.site_architecture.site_interaction_policy import (
    SiteInteractionPolicy,
)
from backend.automation.site_architecture.site_target import (
    SiteEnvironment,
)


MERCURIO_SITE_CODE = "MERCURIO"

MERCURIO_INTERACTION_POLICY_CODE = (
    "MERCURIO_ASSISTED_V1"
)

MERCURIO_LAB_ORIGIN = (
    "http://127.0.0.1:8767"
)

MERCURIO_REAL_ORIGIN = (
    "https://mercurio.delegaciondelgobierno.gob.es"
)

MERCURIO_ALLOWED_PATH_PREFIXES = (
    "/mercurio",
)

MERCURIO_CAPABILITIES = (
    "FORM_FILL",
    "STATE_OBSERVATION",
    "FILE_PREPARATION",
)


def build_mercurio_interaction_policy():
    """
    Política común a Mercurio LAB y REAL.

    Automatización:
    - rellenar valores;
    - seleccionar controles;
    - preparar fichero en input file.

    Interacción humana:
    - navegación mediante click;
    - botones;
    - submit;
    - acciones sensibles.
    """

    return SiteInteractionPolicy(
        policy_code=(
            MERCURIO_INTERACTION_POLICY_CODE
        ),
        site_code=MERCURIO_SITE_CODE,
        action_kind_rules={
            "INPUT_VALUE":
                "AUTOMATION_ALLOWED",

            "SELECT":
                "AUTOMATION_ALLOWED",

            "RADIO":
                "AUTOMATION_ALLOWED",

            "CHECKBOX":
                "AUTOMATION_ALLOWED",

            "FILE_UPLOAD":
                "AUTOMATION_ALLOWED",

            "TAB":
                "HUMAN_ONLY",

            "LINK":
                "HUMAN_ONLY",

            "BUTTON":
                "HUMAN_ONLY",

            "SUBMIT":
                "HUMAN_ONLY",
        },
    )


def build_mercurio_profile(
    environment,
):
    """
    Construye el perfil Mercurio para LAB o REAL.

    La política funcional es idéntica.
    Solo cambia el entorno/origin.
    """

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
                "MERCURIO_ENVIRONMENT_INVALID"
            ) from exc

    if (
        environment
        == SiteEnvironment.LAB
    ):
        origin = (
            MERCURIO_LAB_ORIGIN
        )

    elif (
        environment
        == SiteEnvironment.REAL
    ):
        origin = (
            MERCURIO_REAL_ORIGIN
        )

    else:
        raise ValueError(
            "MERCURIO_ENVIRONMENT_INVALID"
        )

    return ManagedSiteProfile(
        site_code=MERCURIO_SITE_CODE,
        environment=environment,
        allowed_origins=(
            origin,
        ),
        allowed_path_prefixes=(
            MERCURIO_ALLOWED_PATH_PREFIXES
        ),
        interaction_policy=(
            MERCURIO_INTERACTION_POLICY_CODE
        ),
        capabilities=(
            MERCURIO_CAPABILITIES
        ),
    )
