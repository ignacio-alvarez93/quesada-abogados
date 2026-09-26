"""Validez documental provider-neutral: derogación y fin de vigencia.

El modelo temporal existente (``temporal.py``) resuelve qué versión de un
bloque estaba vigente en una fecha usando ``effective_from``. No representa
todavía el FIN de vigencia de una norma completa: ni supersesión (que ya
se expone como evidencia, no como derogación, en ``query.py``), ni
derogación, ni anulación.

Este módulo añade esa capa, estrictamente evidencial:

- ``IN_FORCE``: la fuente confirma explícitamente que la norma sigue
  vigente (banderas oficiales en negativo, no ausencia de dato).
- ``REPEALED``: la fuente declara explícitamente derogación o anulación.
- ``EXPLICIT_END_OF_VALIDITY``: la fuente declara fin de vigencia sin
  que medie derogación/anulación explícita.
- ``UNKNOWN``: no existe evidencia estructurada suficiente. Nunca se
  interpreta como "vigente" ni como "derogada".

Principios:

- nunca se infiere derogación por la mera existencia de una versión
  posterior: eso es supersesión, ya modelada en ``query.py`` mediante
  ``superseded_on``/``open_ended``;
- solo se afirma un estado a partir de evidencia estructurada explícita
  del provider, nunca de heurísticas de contenido ni de IA;
- cada afirmación conserva la evidencia cruda (campo/valor) que la
  sustenta, para auditoría;
- la ausencia/errores de evidencia fallan cerrados hacia ``UNKNOWN``,
  nunca hacia ``IN_FORCE`` ni ``REPEALED``.

No realiza persistencia, HTTP, UI ni IA.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Callable

from .items import KnowledgeItem
from .source_registry import normalize_source_key


class KnowledgeValidityStatus(
    str,
    Enum,
):
    IN_FORCE = "IN_FORCE"
    REPEALED = "REPEALED"

    EXPLICIT_END_OF_VALIDITY = (
        "EXPLICIT_END_OF_VALIDITY"
    )

    UNKNOWN = "UNKNOWN"


@dataclass(
    frozen=True,
    slots=True,
)
class KnowledgeValidityEvidence:
    """Campo/valor crudo del provider que sustenta la afirmación."""

    field: str
    value: str


@dataclass(
    frozen=True,
    slots=True,
)
class KnowledgeDocumentValidity:
    """Afirmación estructurada de validez de una norma completa."""

    source_key: str
    external_id: str

    status: KnowledgeValidityStatus

    end_date: date | None = None

    # external_id de la norma que deroga/anula, si la evidencia lo
    # identifica. Cadena vacía si no hay identificación explícita.
    repealed_by_external_id: str = ""

    evidence: tuple[
        KnowledgeValidityEvidence,
        ...,
    ] = ()

    reason: str = ""

    @property
    def in_force(
        self,
    ) -> bool:
        return (
            self.status
            is KnowledgeValidityStatus.IN_FORCE
        )

    @property
    def has_evidence(
        self,
    ) -> bool:
        return bool(
            self.evidence
        )


def unknown_validity(
    *,
    source_key: str,
    external_id: str,
    reason: str,
    evidence: tuple[
        KnowledgeValidityEvidence,
        ...,
    ] = (),
) -> KnowledgeDocumentValidity:
    """Construye una afirmación ``UNKNOWN`` explícita.

    Es la respuesta por defecto siempre que no exista evidencia
    estructurada suficiente. Nunca se fabrica un estado positivo.
    """

    return KnowledgeDocumentValidity(
        source_key=normalize_source_key(
            source_key
        ),
        external_id=str(
            external_id or ""
        ).strip(),
        status=(
            KnowledgeValidityStatus.UNKNOWN
        ),
        evidence=evidence,
        reason=reason,
    )


# Capacidad opcional por fuente: interpreta evidencia de validez.
#
# Cada provider con campos de derogación/vigencia propios implementa
# esta firma en su propio paquete (p. ej. ``boe_consolidated``). Este
# módulo desconoce deliberadamente esos nombres de campo.
KnowledgeValidityResolver = Callable[
    [KnowledgeItem],
    KnowledgeDocumentValidity,
]
