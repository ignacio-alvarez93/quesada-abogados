"""Política gobernada de promoción del catálogo Knowledge.

V1.3D introduce reglas deterministas para decidir cuándo una
identidad DISCOVERED debe pasar a FOLLOWED.

Principios:

- discovery y promotion son responsabilidades distintas;
- ninguna regla puede degradar CORE/FOLLOWED;
- una relación histórica anterior no provoca promoción;
- solo relaciones posteriores explícitamente relevantes pueden
  promocionar una norma;
- la política es auditable y no depende de IA;
- evaluar y aplicar son operaciones distintas.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from .catalog import (
    KnowledgeCatalogEntry,
    KnowledgeCatalogTier,
    build_knowledge_catalog_entry,
)
from .catalog_repository import (
    KnowledgeCatalogRepository,
)
from .relation_discovery import (
    parse_knowledge_legal_relations,
)
from .relation_identity import (
    resolve_relation_identity,
)
from .repository import (
    KnowledgeRepository,
)


class KnowledgePromotionAction(
    str,
    Enum,
):
    KEEP = "KEEP"
    PROMOTE_FOLLOWED = "PROMOTE_FOLLOWED"
    UNSUPPORTED = "UNSUPPORTED"
    NOT_CATALOGED = "NOT_CATALOGED"


class KnowledgePromotionReason(
    str,
    Enum,
):
    FORWARD_MATERIAL_CHANGE = (
        "FORWARD_MATERIAL_CHANGE"
    )
    FORWARD_IMPLEMENTATION = (
        "FORWARD_IMPLEMENTATION"
    )
    ALREADY_GOVERNED = (
        "ALREADY_GOVERNED"
    )
    SOURCE_NOT_GOVERNED = (
        "SOURCE_NOT_GOVERNED"
    )
    HISTORICAL_RELATION = (
        "HISTORICAL_RELATION"
    )
    NON_PROMOTING_RELATION = (
        "NON_PROMOTING_RELATION"
    )
    UNSUPPORTED_SOURCE = (
        "UNSUPPORTED_SOURCE"
    )
    TARGET_NOT_CATALOGED = (
        "TARGET_NOT_CATALOGED"
    )


_MATERIAL_CHANGE_RELATIONS = frozenset(
    {
        "SE MODIFICA",
        "SE DEROGA",
        "SE AÑADE",
        "SE SUSTITUYE",
    }
)

_IMPLEMENTATION_RELATIONS = frozenset(
    {
        "SE DICTA DE CONFORMIDAD",
        "SE DESARROLLA",
        "SE COMPLETA",
    }
)


@dataclass(
    frozen=True,
    slots=True,
)
class KnowledgePromotionDecision:
    source_canonical_key: str
    target_canonical_key: str

    action: KnowledgePromotionAction
    reason: KnowledgePromotionReason

    relation_direction: str
    relation_text: str

    previous_tier: (
        KnowledgeCatalogTier
        | None
    )

    resulting_tier: (
        KnowledgeCatalogTier
        | None
    )

    recommended_priority: int | None


@dataclass(
    frozen=True,
    slots=True,
)
class KnowledgePromotionBatchResult:
    canonical_key: str

    relation_count: int
    evaluated_count: int

    recommended_count: int
    promoted_count: int
    kept_count: int

    unsupported_count: int
    not_cataloged_count: int

    decisions: tuple[
        KnowledgePromotionDecision,
        ...,
    ]


def normalize_relation_text(
    value: object,
) -> str:
    return " ".join(
        str(
            value or ""
        )
        .strip()
        .upper()
        .split()
    )


def evaluate_catalog_promotion(
    *,
    source_entry: KnowledgeCatalogEntry,
    target_entry: KnowledgeCatalogEntry,
    relation: Mapping[str, object],
) -> KnowledgePromotionDecision:
    """Evalúa una relación sin modificar persistencia."""

    if not isinstance(
        source_entry,
        KnowledgeCatalogEntry,
    ):
        raise TypeError(
            "source_entry debe ser "
            "KnowledgeCatalogEntry"
        )

    if not isinstance(
        target_entry,
        KnowledgeCatalogEntry,
    ):
        raise TypeError(
            "target_entry debe ser "
            "KnowledgeCatalogEntry"
        )

    direction = str(
        relation.get(
            "direction"
        )
        or ""
    ).strip().lower()

    relation_text = (
        normalize_relation_text(
            relation.get(
                "relation_text"
            )
        )
    )

    if (
        target_entry.tier
        in {
            KnowledgeCatalogTier.CORE,
            KnowledgeCatalogTier.FOLLOWED,
        }
    ):
        return KnowledgePromotionDecision(
            source_canonical_key=(
                source_entry.canonical_key
            ),
            target_canonical_key=(
                target_entry.canonical_key
            ),
            action=(
                KnowledgePromotionAction.KEEP
            ),
            reason=(
                KnowledgePromotionReason.ALREADY_GOVERNED
            ),
            relation_direction=direction,
            relation_text=relation_text,
            previous_tier=target_entry.tier,
            resulting_tier=target_entry.tier,
            recommended_priority=None,
        )

    if (
        source_entry.tier
        not in {
            KnowledgeCatalogTier.CORE,
            KnowledgeCatalogTier.FOLLOWED,
        }
    ):
        return KnowledgePromotionDecision(
            source_canonical_key=(
                source_entry.canonical_key
            ),
            target_canonical_key=(
                target_entry.canonical_key
            ),
            action=(
                KnowledgePromotionAction.KEEP
            ),
            reason=(
                KnowledgePromotionReason.SOURCE_NOT_GOVERNED
            ),
            relation_direction=direction,
            relation_text=relation_text,
            previous_tier=target_entry.tier,
            resulting_tier=target_entry.tier,
            recommended_priority=None,
        )

    # BOE "anteriores" representa normas que la
    # disposición fuente desarrolla, deroga, transpone, etc.
    # No significa que debamos seguirlas activamente.
    if direction != "posteriores":
        return KnowledgePromotionDecision(
            source_canonical_key=(
                source_entry.canonical_key
            ),
            target_canonical_key=(
                target_entry.canonical_key
            ),
            action=(
                KnowledgePromotionAction.KEEP
            ),
            reason=(
                KnowledgePromotionReason.HISTORICAL_RELATION
            ),
            relation_direction=direction,
            relation_text=relation_text,
            previous_tier=target_entry.tier,
            resulting_tier=target_entry.tier,
            recommended_priority=None,
        )

    if (
        relation_text
        in _MATERIAL_CHANGE_RELATIONS
    ):
        priority = (
            90
            if source_entry.tier
            is KnowledgeCatalogTier.CORE
            else 80
        )

        return KnowledgePromotionDecision(
            source_canonical_key=(
                source_entry.canonical_key
            ),
            target_canonical_key=(
                target_entry.canonical_key
            ),
            action=(
                KnowledgePromotionAction.PROMOTE_FOLLOWED
            ),
            reason=(
                KnowledgePromotionReason.FORWARD_MATERIAL_CHANGE
            ),
            relation_direction=direction,
            relation_text=relation_text,
            previous_tier=target_entry.tier,
            resulting_tier=(
                KnowledgeCatalogTier.FOLLOWED
            ),
            recommended_priority=priority,
        )

    if (
        relation_text
        in _IMPLEMENTATION_RELATIONS
    ):
        priority = (
            80
            if source_entry.tier
            is KnowledgeCatalogTier.CORE
            else 70
        )

        return KnowledgePromotionDecision(
            source_canonical_key=(
                source_entry.canonical_key
            ),
            target_canonical_key=(
                target_entry.canonical_key
            ),
            action=(
                KnowledgePromotionAction.PROMOTE_FOLLOWED
            ),
            reason=(
                KnowledgePromotionReason.FORWARD_IMPLEMENTATION
            ),
            relation_direction=direction,
            relation_text=relation_text,
            previous_tier=target_entry.tier,
            resulting_tier=(
                KnowledgeCatalogTier.FOLLOWED
            ),
            recommended_priority=priority,
        )

    return KnowledgePromotionDecision(
        source_canonical_key=(
            source_entry.canonical_key
        ),
        target_canonical_key=(
            target_entry.canonical_key
        ),
        action=KnowledgePromotionAction.KEEP,
        reason=(
            KnowledgePromotionReason.NON_PROMOTING_RELATION
        ),
        relation_direction=direction,
        relation_text=relation_text,
        previous_tier=target_entry.tier,
        resulting_tier=target_entry.tier,
        recommended_priority=None,
    )


class KnowledgePromotionPolicyService:
    """Evalúa/aplica promociones desde relaciones jurídicas."""

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

    def evaluate_from_item(
        self,
        source_key: str,
        external_id: str,
        *,
        apply: bool = False,
    ) -> KnowledgePromotionBatchResult:
        if not isinstance(
            apply,
            bool,
        ):
            raise TypeError(
                "apply debe ser bool"
            )

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

        source_entry = (
            self._catalog_repository.get_entry(
                source_key,
                external_id,
            )
        )

        if source_entry is None:
            raise LookupError(
                "La identidad fuente no existe "
                "en KnowledgeCatalog: "
                f"{source_key}:{external_id}"
            )

        relations = (
            parse_knowledge_legal_relations(
                dict(
                    item.metadata
                )
            )
        )

        decisions: list[
            KnowledgePromotionDecision
        ] = []

        seen_targets: set[
            tuple[str, str]
        ] = set()

        promoted_count = 0
        recommended_count = 0
        kept_count = 0
        unsupported_count = 0
        not_cataloged_count = 0

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
                unsupported_count += 1

                decisions.append(
                    KnowledgePromotionDecision(
                        source_canonical_key=(
                            source_entry.canonical_key
                        ),
                        target_canonical_key=(
                            observed_target_external_id
                        ),
                        action=(
                            KnowledgePromotionAction.UNSUPPORTED
                        ),
                        reason=(
                            KnowledgePromotionReason.UNSUPPORTED_SOURCE
                        ),
                        relation_direction=str(
                            relation.get(
                                "direction"
                            )
                            or ""
                        ).strip().lower(),
                        relation_text=(
                            normalize_relation_text(
                                relation.get(
                                    "relation_text"
                                )
                            )
                        ),
                        previous_tier=None,
                        resulting_tier=None,
                        recommended_priority=None,
                    )
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

            target_entry = (
                self._catalog_repository.get_entry(
                    target_source_key,
                    target_external_id,
                )
            )

            if target_entry is None:
                not_cataloged_count += 1

                decisions.append(
                    KnowledgePromotionDecision(
                        source_canonical_key=(
                            source_entry.canonical_key
                        ),
                        target_canonical_key=(
                            f"{target_source_key}:"
                            f"{target_external_id}"
                        ),
                        action=(
                            KnowledgePromotionAction.NOT_CATALOGED
                        ),
                        reason=(
                            KnowledgePromotionReason.TARGET_NOT_CATALOGED
                        ),
                        relation_direction=str(
                            relation.get(
                                "direction"
                            )
                            or ""
                        ).strip().lower(),
                        relation_text=(
                            normalize_relation_text(
                                relation.get(
                                    "relation_text"
                                )
                            )
                        ),
                        previous_tier=None,
                        resulting_tier=None,
                        recommended_priority=None,
                    )
                )

                continue

            decision = (
                evaluate_catalog_promotion(
                    source_entry=source_entry,
                    target_entry=target_entry,
                    relation=relation,
                )
            )

            if (
                decision.action
                is KnowledgePromotionAction.PROMOTE_FOLLOWED
            ):
                recommended_count += 1

                if apply:
                    reason = (
                        target_entry.added_reason
                    )

                    promotion_reason = (
                        "Promocionada automáticamente "
                        "a FOLLOWED por relación "
                        f"{decision.relation_text} "
                        f"desde {source_entry.canonical_key}."
                    )

                    if reason:
                        added_reason = (
                            f"{reason} "
                            f"{promotion_reason}"
                        )
                    else:
                        added_reason = (
                            promotion_reason
                        )

                    promoted_entry = (
                        build_knowledge_catalog_entry(
                            source_key=(
                                target_entry.source_key
                            ),
                            external_id=(
                                target_entry.external_id
                            ),
                            tier=(
                                KnowledgeCatalogTier.FOLLOWED
                            ),
                            watch_updates=True,
                            priority=max(
                                target_entry.priority,
                                (
                                    decision.recommended_priority
                                    or 0
                                ),
                            ),
                            added_reason=(
                                added_reason
                            ),
                        )
                    )

                    self._catalog_repository.upsert(
                        promoted_entry
                    )

                    promoted_count += 1

            else:
                kept_count += 1

            decisions.append(
                decision
            )

        return KnowledgePromotionBatchResult(
            canonical_key=(
                item.canonical_key
            ),
            relation_count=len(
                relations
            ),
            evaluated_count=len(
                seen_targets
            ),
            recommended_count=(
                recommended_count
            ),
            promoted_count=(
                promoted_count
            ),
            kept_count=kept_count,
            unsupported_count=(
                unsupported_count
            ),
            not_cataloged_count=(
                not_cataloged_count
            ),
            decisions=tuple(
                decisions
            ),
        )
