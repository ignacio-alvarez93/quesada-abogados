"""Catálogo gobernado de Knowledge.

El catálogo expresa la política interna del despacho sobre una
identidad Knowledge.

No describe el contenido jurídico de la fuente y no forma parte
del fingerprint de KnowledgeItem.

Una identidad puede formar parte del catálogo incluso antes de que
su contenido haya sido ingerido/materializado.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .source_registry import (
    get_knowledge_source,
    normalize_source_key,
)


class KnowledgeCatalogTier(str, Enum):
    """Nivel de relevancia operativa dentro de Knowledge."""

    CORE = "CORE"
    FOLLOWED = "FOLLOWED"
    DISCOVERED = "DISCOVERED"


@dataclass(frozen=True, slots=True)
class KnowledgeCatalogEntry:
    """Política interna aplicada a una identidad Knowledge."""

    source_key: str
    external_id: str
    tier: KnowledgeCatalogTier

    watch_updates: bool
    priority: int = 50
    added_reason: str = ""

    def __post_init__(self) -> None:
        source_key = normalize_source_key(
            self.source_key
        )

        # Fail-closed: solo fuentes canónicas registradas.
        get_knowledge_source(
            source_key
        )

        external_id = str(
            self.external_id or ""
        ).strip()

        if not external_id:
            raise ValueError(
                "Knowledge catalog external_id "
                "no puede estar vacío"
            )

        if not isinstance(
            self.tier,
            KnowledgeCatalogTier,
        ):
            raise TypeError(
                "Knowledge catalog tier debe ser "
                "KnowledgeCatalogTier"
            )

        if not isinstance(
            self.watch_updates,
            bool,
        ):
            raise TypeError(
                "Knowledge catalog watch_updates "
                "debe ser bool"
            )

        if (
            not isinstance(self.priority, int)
            or isinstance(self.priority, bool)
        ):
            raise TypeError(
                "Knowledge catalog priority "
                "debe ser entero"
            )

        if not 0 <= self.priority <= 100:
            raise ValueError(
                "Knowledge catalog priority "
                "debe estar entre 0 y 100"
            )

        # CORE y FOLLOWED significan vigilancia activa.
        if (
            self.tier
            in {
                KnowledgeCatalogTier.CORE,
                KnowledgeCatalogTier.FOLLOWED,
            }
            and not self.watch_updates
        ):
            raise ValueError(
                f"{self.tier.value} requiere "
                "watch_updates=True"
            )

        added_reason = str(
            self.added_reason or ""
        ).strip()

        object.__setattr__(
            self,
            "source_key",
            source_key,
        )
        object.__setattr__(
            self,
            "external_id",
            external_id,
        )
        object.__setattr__(
            self,
            "added_reason",
            added_reason,
        )

    @property
    def canonical_key(self) -> str:
        return (
            f"{self.source_key}:"
            f"{self.external_id}"
        )


def build_knowledge_catalog_entry(
    *,
    source_key: str,
    external_id: str,
    tier: KnowledgeCatalogTier,
    watch_updates: bool,
    priority: int = 50,
    added_reason: str = "",
) -> KnowledgeCatalogEntry:
    """Factory pública del contrato de catálogo."""

    return KnowledgeCatalogEntry(
        source_key=source_key,
        external_id=external_id,
        tier=tier,
        watch_updates=watch_updates,
        priority=priority,
        added_reason=added_reason,
    )
