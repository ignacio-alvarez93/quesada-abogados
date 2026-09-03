"""Composición de reconocedores instalados en QCC.

El core genérico no importa sitios concretos.
La composición ocurre exclusivamente aquí.
"""

from __future__ import annotations

from backend.automation.site_architecture.state_recognizer_registry import (
    SiteStateRecognizerRegistry,
)

from .mercurio import (
    build_mercurio_state_registration,
    resolve_mercurio_architecture_scope,
)


def build_default_site_state_recognizer_registry():
    registry = (
        SiteStateRecognizerRegistry()
    )

    registry.register(
        build_mercurio_state_registration()
    )

    registry.register_retention_scope_resolver(
        site_code="MERCURIO",
        resolver=(
            resolve_mercurio_architecture_scope
        ),
    )

    return registry
