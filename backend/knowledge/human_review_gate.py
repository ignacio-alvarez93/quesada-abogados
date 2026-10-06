"""Puerta de revisión humana para promoción DISCOVERED -> FOLLOWED.

No sustituye KnowledgePromotionPolicyService: reutiliza sus
decisiones para saber qué promoción se recomienda, pero nunca
cambia el tier del catálogo sin una aprobación humana explícita,
persistida y atribuible a un revisor (fail-closed).
"""

from __future__ import annotations

from .catalog import (
    KnowledgeCatalogTier,
    build_knowledge_catalog_entry,
)
from .catalog_repository import (
    KnowledgeCatalogRepository,
)
from .promotion_policy import (
    KnowledgePromotionAction,
    KnowledgePromotionDecision,
)
from .promotion_review import (
    KnowledgePromotionReviewOutcome,
    KnowledgePromotionReviewRecord,
    KnowledgePromotionReviewState,
)
from .promotion_review_repository import (
    KnowledgePromotionReviewRepository,
)


def _split_canonical_key(
    canonical_key: str,
) -> tuple[str, str]:
    source_key, _, external_id = (
        canonical_key.partition(":")
    )

    if not source_key or not external_id:
        raise ValueError(
            f"canonical_key inválido: {canonical_key}"
        )

    return source_key, external_id


def _require_reviewer_ref(
    reviewer_ref: object,
) -> str:
    if not isinstance(
        reviewer_ref,
        str,
    ):
        raise TypeError(
            "reviewer_ref debe ser str"
        )

    reviewer_ref = reviewer_ref.strip()

    if not reviewer_ref:
        raise ValueError(
            "reviewer_ref es obligatorio: ninguna promoción "
            "sin revisor identificado"
        )

    return reviewer_ref


class KnowledgeHumanReviewGateService:
    """Gobierna la promoción DISCOVERED -> FOLLOWED mediante revisión humana."""

    def __init__(
        self,
        *,
        catalog_repository: KnowledgeCatalogRepository,
        review_repository: KnowledgePromotionReviewRepository,
    ) -> None:
        if not isinstance(
            catalog_repository,
            KnowledgeCatalogRepository,
        ):
            raise TypeError(
                "catalog_repository debe implementar "
                "KnowledgeCatalogRepository"
            )

        if not isinstance(
            review_repository,
            KnowledgePromotionReviewRepository,
        ):
            raise TypeError(
                "review_repository debe implementar "
                "KnowledgePromotionReviewRepository"
            )

        self._catalog_repository = (
            catalog_repository
        )

        self._review_repository = (
            review_repository
        )

    def submit_for_review(
        self,
        decision: KnowledgePromotionDecision,
    ) -> KnowledgePromotionReviewRecord:
        """Persiste una recomendación PENDING_REVIEW sin mutar el catálogo."""

        if not isinstance(
            decision,
            KnowledgePromotionDecision,
        ):
            raise TypeError(
                "decision debe ser KnowledgePromotionDecision"
            )

        if (
            decision.action
            is not KnowledgePromotionAction.PROMOTE_FOLLOWED
        ):
            raise ValueError(
                "Solo decisiones PROMOTE_FOLLOWED requieren "
                "revisión humana"
            )

        if (
            decision.previous_tier
            is not KnowledgeCatalogTier.DISCOVERED
        ):
            raise ValueError(
                "La puerta de revisión humana solo gobierna "
                "promociones DISCOVERED -> FOLLOWED"
            )

        target_entry = self._get_target_entry(
            decision.target_canonical_key
        )

        if target_entry.tier is not KnowledgeCatalogTier.DISCOVERED:
            raise ValueError(
                "La identidad objetivo ya no está en DISCOVERED: "
                f"{decision.target_canonical_key}"
            )

        return self._review_repository.create_pending_review(
            source_canonical_key=(
                decision.source_canonical_key
            ),
            target_canonical_key=(
                decision.target_canonical_key
            ),
            reason=decision.reason.value,
            recommended_priority=(
                decision.recommended_priority
            ),
        )

    def approve(
        self,
        review_id: str,
        *,
        reviewer_ref: str,
    ) -> KnowledgePromotionReviewRecord:
        """Aprueba la revisión y promociona DISCOVERED -> FOLLOWED."""

        reviewer_ref = _require_reviewer_ref(
            reviewer_ref
        )

        review = self._get_review(
            review_id
        )

        if review.state is KnowledgePromotionReviewState.APPROVED:
            # Idempotente: una aprobación ya aplicada no se repite.
            return review

        if review.state is not KnowledgePromotionReviewState.PENDING_REVIEW:
            raise ValueError(
                f"La revisión {review_id} está en estado "
                f"{review.state.value} y no puede aprobarse"
            )

        target_entry = self._get_target_entry(
            review.target_canonical_key
        )

        if target_entry.tier is not KnowledgeCatalogTier.DISCOVERED:
            raise ValueError(
                "La identidad objetivo ya no está en DISCOVERED: "
                f"{review.target_canonical_key}"
            )

        previous_reason = target_entry.added_reason

        approval_reason = (
            "Promoción a FOLLOWED aprobada por revisión "
            f"humana ({reviewer_ref})."
        )

        added_reason = (
            f"{previous_reason} {approval_reason}"
            if previous_reason
            else approval_reason
        )

        promoted_entry = build_knowledge_catalog_entry(
            source_key=target_entry.source_key,
            external_id=target_entry.external_id,
            tier=KnowledgeCatalogTier.FOLLOWED,
            watch_updates=True,
            priority=max(
                target_entry.priority,
                review.recommended_priority or 0,
            ),
            added_reason=added_reason,
        )

        self._catalog_repository.upsert(
            promoted_entry
        )

        return self._review_repository.mark_approved(
            review_id,
            reviewer_ref=reviewer_ref,
            outcome=(
                KnowledgePromotionReviewOutcome.PROMOTED_FOLLOWED
            ),
        )

    def reject(
        self,
        review_id: str,
        *,
        reviewer_ref: str,
    ) -> KnowledgePromotionReviewRecord:
        """Rechaza la revisión. El catálogo permanece sin cambios."""

        reviewer_ref = _require_reviewer_ref(
            reviewer_ref
        )

        review = self._get_review(
            review_id
        )

        if review.state is KnowledgePromotionReviewState.REJECTED:
            return review

        if review.state is not KnowledgePromotionReviewState.PENDING_REVIEW:
            raise ValueError(
                f"La revisión {review_id} está en estado "
                f"{review.state.value} y no puede rechazarse"
            )

        return self._review_repository.mark_rejected(
            review_id,
            reviewer_ref=reviewer_ref,
        )

    def _get_review(
        self,
        review_id: str,
    ) -> KnowledgePromotionReviewRecord:
        review = self._review_repository.get_review(
            review_id
        )

        if review is None:
            raise LookupError(
                f"No existe revisión: {review_id}"
            )

        return review

    def _get_target_entry(
        self,
        target_canonical_key: str,
    ):
        source_key, external_id = _split_canonical_key(
            target_canonical_key
        )

        target_entry = self._catalog_repository.get_entry(
            source_key,
            external_id,
        )

        if target_entry is None:
            raise LookupError(
                "La identidad objetivo no existe en "
                f"KnowledgeCatalog: {target_canonical_key}"
            )

        return target_entry
