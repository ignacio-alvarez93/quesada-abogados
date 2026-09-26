"""Horizonte de evidencia provider-neutral.

Distingue explícitamente tres situaciones que el modelo temporal por
sí solo no puede separar:

- no se ha observado un cambio autoritativo posterior DENTRO del
  horizonte de evidencia conocido (``CHECKED``);
- la identidad nunca ha sido ingerida por Knowledge, así que no existe
  horizonte alguno (``NEVER_INGESTED``);
- Knowledge no puede determinar el horizonte porque no dispone de
  historial de ingestión para esa identidad (``HORIZON_UNKNOWN``).

Principio rector: la ausencia de una revisión más reciente NUNCA se
interpreta como "no existe una revisión más reciente en la fuente".
Solo se afirma que Knowledge no ha observado ninguna dentro de lo que
ha comprobado, y se expone explícitamente hasta qué punto se comprobó.

No realiza persistencia, HTTP, UI ni IA. Opera sobre
``KnowledgeRevisionSnapshot`` ya cargado por el repositorio.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .repository import KnowledgeRevisionSnapshot
from .source_registry import normalize_source_key


class KnowledgeEvidenceHorizonStatus(
    str,
    Enum,
):
    CHECKED = "CHECKED"

    NEVER_INGESTED = (
        "NEVER_INGESTED"
    )

    HORIZON_UNKNOWN = (
        "HORIZON_UNKNOWN"
    )


@dataclass(
    frozen=True,
    slots=True,
)
class KnowledgeEvidenceHorizon:
    """Metadata estructurada de completitud de evidencia."""

    source_key: str
    external_id: str

    status: KnowledgeEvidenceHorizonStatus

    # Timestamp UTC ISO-8601 de la última observación de ingestión
    # conocida. Cadena vacía si no existe ninguna.
    checked_as_of: str = ""

    # Marcador de frescura propio de la fuente (p. ej. la
    # ``fecha_actualizacion`` que BOE reporta para ese registro) tal
    # como se observó en la última ingestión. Cadena vacía si no se
    # dispone de uno.
    source_revision: str = ""

    observation_count: int = 0

    reason: str = ""

    @property
    def checked(
        self,
    ) -> bool:
        return (
            self.status
            is KnowledgeEvidenceHorizonStatus.CHECKED
        )


def resolve_evidence_horizon(
    *,
    source_key: str,
    external_id: str,
    revisions: tuple[
        KnowledgeRevisionSnapshot,
        ...,
    ],
) -> KnowledgeEvidenceHorizon:
    """Deriva el horizonte de evidencia a partir del historial observado.

    ``revisions`` debe proceder de
    ``KnowledgeRepository.list_revisions``. Una tupla vacía significa
    que Knowledge nunca ha ingerido la identidad, no que la fuente
    carezca de contenido.
    """

    normalized_source = (
        normalize_source_key(
            source_key
        )
    )

    clean_external = str(
        external_id or ""
    ).strip()

    if not clean_external:
        raise ValueError(
            "external_id no puede estar vacío"
        )

    if not isinstance(
        revisions,
        tuple,
    ):
        raise TypeError(
            "revisions debe ser tupla de "
            "KnowledgeRevisionSnapshot"
        )

    for snapshot in revisions:
        if not isinstance(
            snapshot,
            KnowledgeRevisionSnapshot,
        ):
            raise TypeError(
                "revisions debe contener "
                "KnowledgeRevisionSnapshot"
            )

    if not revisions:
        return KnowledgeEvidenceHorizon(
            source_key=normalized_source,
            external_id=clean_external,
            status=(
                KnowledgeEvidenceHorizonStatus.NEVER_INGESTED
            ),
            observation_count=0,
            reason=(
                "Knowledge nunca ha ingerido "
                "esta identidad; el horizonte "
                "de evidencia es desconocido."
            ),
        )

    latest = max(
        revisions,
        key=lambda snapshot: (
            snapshot.observed_at,
            snapshot.revision_number,
        ),
    )

    return KnowledgeEvidenceHorizon(
        source_key=normalized_source,
        external_id=clean_external,
        status=(
            KnowledgeEvidenceHorizonStatus.CHECKED
        ),
        checked_as_of=(
            latest.observed_at
        ),
        source_revision=(
            latest.item.source_revision
        ),
        observation_count=len(
            revisions
        ),
        reason=(
            "No se ha observado un cambio "
            "autoritativo posterior dentro "
            "del horizonte de evidencia "
            "conocido (fuente no comprobada "
            f"más allá de {latest.observed_at})."
        ),
    )
