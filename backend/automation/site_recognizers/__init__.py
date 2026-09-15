"""Plugins de reconocimiento semántico de sitios."""

from .default_registry import (
    build_default_site_state_recognizer_registry,
)
from .mercurio import (
    MERCURIO_LAB_LOCALHOST_ORIGIN,
    MERCURIO_SEDE_ORIGIN,
    build_mercurio_state_registration,
    recognize_mercurio_state,
)

__all__ = [
    "MERCURIO_LAB_LOCALHOST_ORIGIN",
    "MERCURIO_SEDE_ORIGIN",
    "build_default_site_state_recognizer_registry",
    "build_mercurio_state_registration",
    "recognize_mercurio_state",
]
