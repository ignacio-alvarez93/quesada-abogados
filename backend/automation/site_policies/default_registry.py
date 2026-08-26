"""Composición de sitios con ejecución gestionada QCC.

El registro genérico no conoce proveedores.
La composición concreta ocurre aquí.
"""

from __future__ import annotations

from backend.automation.site_architecture.managed_governance_registry import (
    ManagedSiteGovernanceRegistry,
)
from backend.automation.site_policies.mercurio import (
    build_mercurio_governance_registration,
)


def build_default_managed_site_governance_registry():
    registry = (
        ManagedSiteGovernanceRegistry()
    )

    registry.register(
        build_mercurio_governance_registration()
    )

    return registry
