"""Adaptador de reconocimiento funcional de estados Mercurio.

Este módulo conecta el detector específico de Mercurio
con la infraestructura genérica Site Architecture.

No ejecuta acciones y no concede permisos.
"""

from __future__ import annotations

from backend.automation.site_architecture.snapshot import (
    build_normalized_snapshot_payload,
)
from backend.automation.site_architecture.state_recognizer_registry import (
    SiteStateRecognizerRegistration,
)
from backend.automation.site_policies.mercurio import (
    MERCURIO_LAB_ORIGIN,
    MERCURIO_REAL_ORIGIN,
    MERCURIO_SITE_CODE,
)
from tools.mercurio_lab.core.state_detector import (
    detect_mercurio_general_state,
)


MERCURIO_SEDE_ORIGIN = (
    "https://sede.administracionespublicas.gob.es"
)

MERCURIO_LAB_LOCALHOST_ORIGIN = (
    "http://localhost:8767"
)


def _snapshot_payload(
    snapshot,
):
    if isinstance(
        snapshot,
        dict,
    ):
        return snapshot

    return (
        build_normalized_snapshot_payload(
            snapshot
        )
    )


def recognize_mercurio_state(
    snapshot,
):
    """Traduce Site Architecture a estado semántico Mercurio.

    Devuelve únicamente una identidad funcional estable
    o None cuando el estado todavía no se reconoce.
    """

    payload = _snapshot_payload(
        snapshot
    )

    state = (
        detect_mercurio_general_state(
            payload
        )
    )

    if state is None:
        return None

    return state.value


def build_mercurio_state_registration():
    """Registro común para navegación Mercurio LAB/REAL."""

    return SiteStateRecognizerRegistration(
        site_code=MERCURIO_SITE_CODE,
        origins=(
            MERCURIO_REAL_ORIGIN,
            MERCURIO_SEDE_ORIGIN,
            MERCURIO_LAB_ORIGIN,
            MERCURIO_LAB_LOCALHOST_ORIGIN,
        ),
        recognizer=(
            recognize_mercurio_state
        ),
    )
