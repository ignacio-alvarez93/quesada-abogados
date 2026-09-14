"""Contratos canónicos del dominio Knowledge.

Este módulo no realiza persistencia, acceso a red ni procesamiento IA.

Knowledge es consumidor de información estructurada y no autoridad
sobre los dominios jurídicos u operativos del ERP.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class KnowledgeSourceKind(str, Enum):
    """Naturaleza funcional de una fuente de conocimiento."""

    OFFICIAL_GAZETTE = "OFFICIAL_GAZETTE"
    OFFICIAL_LEGISLATION = "OFFICIAL_LEGISLATION"
    JURISPRUDENCE = "JURISPRUDENCE"
    ADMINISTRATIVE_RESOLUTION = "ADMINISTRATIVE_RESOLUTION"
    ADMINISTRATIVE_REQUIREMENT = "ADMINISTRATIVE_REQUIREMENT"
    INTERNAL_CASE = "INTERNAL_CASE"
    INTERNAL_NOTE = "INTERNAL_NOTE"
    EXTERNAL_GUIDANCE = "EXTERNAL_GUIDANCE"
    TRANSCRIPT = "TRANSCRIPT"


class KnowledgeAuthority(str, Enum):
    """Nivel de autoridad de la fuente.

    El nivel describe procedencia y fiabilidad institucional.
    No convierte a Knowledge en autoridad jurídica del ERP.
    """

    OFFICIAL_PRIMARY = "OFFICIAL_PRIMARY"
    OFFICIAL_SECONDARY = "OFFICIAL_SECONDARY"
    INTERNAL_VALIDATED = "INTERNAL_VALIDATED"
    EXTERNAL_REFERENCE = "EXTERNAL_REFERENCE"


@dataclass(frozen=True, slots=True)
class KnowledgeSourceDefinition:
    """Definición estable de una fuente disponible para Knowledge."""

    key: str
    provider: str
    display_name: str
    source_kind: KnowledgeSourceKind
    authority: KnowledgeAuthority
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.key:
            raise ValueError("Knowledge source key no puede estar vacío")

        if self.key != self.key.strip().upper():
            raise ValueError(
                "Knowledge source key debe estar normalizado en mayúsculas"
            )

        if not self.provider.strip():
            raise ValueError("Knowledge source provider no puede estar vacío")

        if not self.display_name.strip():
            raise ValueError(
                "Knowledge source display_name no puede estar vacío"
            )


class KnowledgeItemKind(str, Enum):
    """Naturaleza de una pieza concreta de conocimiento."""

    OFFICIAL_PUBLICATION = "OFFICIAL_PUBLICATION"
    LEGISLATION = "LEGISLATION"
    JURISPRUDENCE = "JURISPRUDENCE"
    ADMINISTRATIVE_RESOLUTION = "ADMINISTRATIVE_RESOLUTION"
    ADMINISTRATIVE_REQUIREMENT = "ADMINISTRATIVE_REQUIREMENT"
    INTERNAL_CASE = "INTERNAL_CASE"
    INTERNAL_NOTE = "INTERNAL_NOTE"
    GUIDANCE = "GUIDANCE"
    TRANSCRIPT = "TRANSCRIPT"
    OTHER = "OTHER"
