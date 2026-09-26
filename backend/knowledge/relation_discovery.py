"""Descubrimiento de identidades Knowledge mediante relaciones jurídicas.

Esta capa NO ingiere contenido.

Su única responsabilidad es observar las relaciones normalizadas de un
KnowledgeItem materializado y registrar identidades relacionadas en el
catálogo como DISCOVERED cuando todavía no existen.

Reglas V1:

- una entrada existente nunca se degrada;
- CORE/FOLLOWED permanecen intactas;
- descubrir una relación no implica FOLLOWED;
- únicamente se resuelven prefijos cuya fuente Knowledge existe;
- relaciones a proveedores todavía no implementados se contabilizan
  como unsupported y no se inventa una fuente.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Mapping

from .catalog import (
    KnowledgeCatalogTier,
    build_knowledge_catalog_entry,
)
from .catalog_repository import (
    KnowledgeCatalogRepository,
)
from .repository import (
    KnowledgeRepository,
)
from .relation_identity import (
    resolve_relation_identity,
)


@dataclass(frozen=True, slots=True)
class KnowledgeRelationDiscoveryResult:
    """Resumen de una expansión de catálogo por relaciones."""

    canonical_key: str

    relation_count: int

    discovered_count: int
    existing_count: int
    unsupported_count: int

    discovered_keys: tuple[str, ...]
    unsupported_external_ids: tuple[str, ...]


def resolve_relation_source_key(
    external_id: str,
) -> str | None:
    """Compatibilidad V1: devuelve solo la fuente resuelta.

    La identidad completa/canónica se obtiene mediante
    ``resolve_relation_identity``.
    """

    identity = resolve_relation_identity(
        external_id
    )

    if identity is None:
        return None

    return identity.source_key


def parse_knowledge_legal_relations(
    metadata: Mapping[str, str],
) -> tuple[
    Mapping[str, object],
    ...,
]:
    raw = str(
        metadata.get(
            "legal_relations_json"
        )
        or ""
    ).strip()

    if not raw:
        return ()

    try:
        payload = json.loads(
            raw
        )
    except json.JSONDecodeError as exc:
        raise ValueError(
            "legal_relations_json no contiene JSON válido"
        ) from exc

    if not isinstance(
        payload,
        list,
    ):
        raise ValueError(
            "legal_relations_json debe contener una lista"
        )

    result = []

    for relation in payload:
        if not isinstance(
            relation,
            Mapping,
        ):
            raise ValueError(
                "Cada relación jurídica debe ser un objeto"
            )

        result.append(
            relation
        )

    return tuple(
        result
    )


class KnowledgeRelationDiscoveryService:
    """Expande el catálogo desde relaciones jurídicas conocidas."""

    def __init__(
        self,
        *,
        knowledge_repository: KnowledgeRepository,
        catalog_repository: KnowledgeCatalogRepository,
    ) -> None:
        if not isinstance(
            knowledge_repository,
            KnowledgeRepository,
        ):
            raise TypeError(
                "knowledge_repository debe implementar "
                "KnowledgeRepository"
            )

        if not isinstance(
            catalog_repository,
            KnowledgeCatalogRepository,
        ):
            raise TypeError(
                "catalog_repository debe implementar "
                "KnowledgeCatalogRepository"
            )

        self._knowledge_repository = (
            knowledge_repository
        )

        self._catalog_repository = (
            catalog_repository
        )

    def discover_from_item(
        self,
        source_key: str,
        external_id: str,
    ) -> KnowledgeRelationDiscoveryResult:
        """Registra como DISCOVERED las relaciones aún desconocidas."""

        item = (
            self._knowledge_repository.get_current(
                source_key,
                external_id,
            )
        )

        if item is None:
            raise LookupError(
                "No existe KnowledgeItem materializado: "
                f"{source_key}:{external_id}"
            )

        relations = parse_knowledge_legal_relations(
            dict(
                item.metadata
            )
        )

        discovered_keys: list[str] = []
        unsupported_ids: list[str] = []

        existing_count = 0

        # Una misma norma puede aparecer más de una vez en el
        # análisis jurídico. El catálogo trabaja por identidad.
        seen_targets: set[
            tuple[str, str]
        ] = set()

        for relation in relations:
            observed_target_external_id = str(
                relation.get(
                    "target_id"
                )
                or ""
            ).strip()

            if not observed_target_external_id:
                continue

            resolved_identity = (
                resolve_relation_identity(
                    observed_target_external_id
                )
            )

            if resolved_identity is None:
                if (
                    observed_target_external_id
                    not in unsupported_ids
                ):
                    unsupported_ids.append(
                        observed_target_external_id
                    )
                continue

            target_source_key = (
                resolved_identity.source_key
            )

            target_external_id = (
                resolved_identity.external_id
            )

            identity = (
                target_source_key,
                target_external_id,
            )

            if identity in seen_targets:
                continue

            seen_targets.add(
                identity
            )

            existing = (
                self._catalog_repository.get_entry(
                    target_source_key,
                    target_external_id,
                )
            )

            if existing is not None:
                # Regla fundamental:
                # discovery nunca degrada ni altera una política
                # previamente establecida por el despacho.
                existing_count += 1
                continue

            relation_text = str(
                relation.get(
                    "relation_text"
                )
                or ""
            ).strip()

            direction = str(
                relation.get(
                    "direction"
                )
                or ""
            ).strip()

            reason_parts = [
                (
                    "Descubierta mediante relación jurídica "
                    f"desde {item.canonical_key}."
                )
            ]

            if resolved_identity.used_alias:
                reason_parts.append(
                    "Alias externo verificado: "
                    f"{resolved_identity.observed_external_id} "
                    "-> "
                    f"{resolved_identity.canonical_key}."
                )

            if relation_text:
                reason_parts.append(
                    f"Relación: {relation_text}."
                )

            if direction:
                reason_parts.append(
                    f"Dirección BOE: {direction}."
                )

            entry = (
                build_knowledge_catalog_entry(
                    source_key=(
                        target_source_key
                    ),
                    external_id=(
                        target_external_id
                    ),
                    tier=(
                        KnowledgeCatalogTier.DISCOVERED
                    ),
                    watch_updates=False,
                    priority=20,
                    added_reason=" ".join(
                        reason_parts
                    ),
                )
            )

            self._catalog_repository.upsert(
                entry
            )

            discovered_keys.append(
                entry.canonical_key
            )

        return KnowledgeRelationDiscoveryResult(
            canonical_key=item.canonical_key,
            relation_count=len(
                relations
            ),
            discovered_count=len(
                discovered_keys
            ),
            existing_count=existing_count,
            unsupported_count=len(
                unsupported_ids
            ),
            discovered_keys=tuple(
                discovered_keys
            ),
            unsupported_external_ids=tuple(
                unsupported_ids
            ),
        )
