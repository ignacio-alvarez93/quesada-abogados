"""Política de capacidades AUTO TWIN por perfil QCC.

La política AUTO TWIN es deliberadamente ortogonal a
BrowserSessionMode.

BrowserSessionMode describe el lifecycle técnico:
- EPHEMERAL
- PERSISTENT
- ASSISTED

AutoTwinProfilePolicy describe qué puede hacer ese
navegador respecto de un TWIN gestionado por QCC.

La decisión de si una URL pertenece a un TWIN gestionado
NO pertenece a este módulo.
"""

from __future__ import annotations

from dataclasses import dataclass


AUTO_TWIN_PROFILE_POLICY_SCHEMA_VERSION = 1

AUTO_TWIN_DISCOVERY_PROFILE_KEY = (
    "twin_discovery"
)

AUTO_TWIN_POLICY_OBSERVER = "OBSERVER"
AUTO_TWIN_POLICY_DISCOVERY = "DISCOVERY"


def normalize_auto_twin_profile_key(
    profile_key,
) -> str:
    value = str(
        profile_key
        or ""
    ).strip()

    if not value:
        raise ValueError(
            "QCC_AUTO_TWIN_PROFILE_KEY_REQUIRED"
        )

    return value


@dataclass(
    frozen=True,
)
class AutoTwinProfilePolicy:
    """Capacidades AUTO TWIN de un navegador QCC."""

    profile_key: str

    # Todo navegador QCC que visite un sitio con TWIN
    # gestionado puede contribuir observación pasiva.
    observe_managed_twins: bool = True

    # Puede publicar evidencia para detectar que REAL
    # ha cambiado frente al baseline conocido.
    detect_changes: bool = True

    # Puede capturar de forma pasiva catálogos ya
    # presentes en el estado observado.
    capture_catalogs: bool = True

    # Puede explorar activamente estados seguros.
    active_discovery: bool = False

    # Puede alterar controles catalogales de forma
    # gobernada para descubrir relaciones causales.
    active_catalog_probe: bool = False

    # Puede solicitar adquisiciones profundas destinadas
    # a construcción/reconstrucción del TWIN.
    deep_capture: bool = False

    # Puede actuar como perfil de validación REAL ↔ TWIN.
    validate_twin: bool = False

    policy_code: str = AUTO_TWIN_POLICY_OBSERVER

    schema_version: int = (
        AUTO_TWIN_PROFILE_POLICY_SCHEMA_VERSION
    )

    def __post_init__(
        self,
    ) -> None:
        profile_key = (
            normalize_auto_twin_profile_key(
                self.profile_key
            )
        )

        if self.policy_code not in {
            AUTO_TWIN_POLICY_OBSERVER,
            AUTO_TWIN_POLICY_DISCOVERY,
        }:
            raise ValueError(
                "QCC_AUTO_TWIN_POLICY_CODE_INVALID"
            )

        object.__setattr__(
            self,
            "profile_key",
            profile_key,
        )

    def to_dict(
        self,
    ) -> dict:
        return {
            "schema_version":
                self.schema_version,

            "profile_key":
                self.profile_key,

            "policy_code":
                self.policy_code,

            "observe_managed_twins":
                self.observe_managed_twins,

            "detect_changes":
                self.detect_changes,

            "capture_catalogs":
                self.capture_catalogs,

            "active_discovery":
                self.active_discovery,

            "active_catalog_probe":
                self.active_catalog_probe,

            "deep_capture":
                self.deep_capture,

            "validate_twin":
                self.validate_twin,
        }


def build_auto_twin_profile_policy(
    profile_key,
) -> AutoTwinProfilePolicy:
    """Resuelve capacidades AUTO TWIN por identidad de perfil.

    Todos los perfiles QCC pueden observar pasivamente
    sitios cuyo TWIN esté gestionado.

    Únicamente ``twin_discovery`` recibe capacidades
    activas de descubrimiento profundo.
    """

    key = normalize_auto_twin_profile_key(
        profile_key
    )

    if key == AUTO_TWIN_DISCOVERY_PROFILE_KEY:
        return AutoTwinProfilePolicy(
            profile_key=key,
            observe_managed_twins=True,
            detect_changes=True,
            capture_catalogs=True,
            active_discovery=True,
            active_catalog_probe=True,
            deep_capture=True,
            validate_twin=True,
            policy_code=(
                AUTO_TWIN_POLICY_DISCOVERY
            ),
        )

    return AutoTwinProfilePolicy(
        profile_key=key,
        observe_managed_twins=True,
        detect_changes=True,
        capture_catalogs=True,
        active_discovery=False,
        active_catalog_probe=False,
        deep_capture=False,
        validate_twin=False,
        policy_code=(
            AUTO_TWIN_POLICY_OBSERVER
        ),
    )
