"""Puerto de persistencia de revisión humana de promoción Knowledge.

Independiente de KnowledgeCatalogRepository: este puerto conserva el
ciclo de vida de la revisión, no la política de catálogo resultante.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .promotion_review import (
    KnowledgePromotionReviewOutcome,
    KnowledgePromotionReviewRecord,
)


@runtime_checkable
class KnowledgePromotionReviewRepository(Protocol):
    """Puerto intercambiable SQLite/PostgreSQL de revisión de promoción."""

    def initialize_schema(self) -> None:
        ...

    def create_pending_review(
        self,
        *,
        source_canonical_key: str,
        target_canonical_key: str,
        reason: str,
        recommended_priority: int | None,
    ) -> KnowledgePromotionReviewRecord:
        ...

    def get_review(
        self,
        review_id: str,
    ) -> KnowledgePromotionReviewRecord | None:
        ...

    def mark_approved(
        self,
        review_id: str,
        *,
        reviewer_ref: str,
        outcome: KnowledgePromotionReviewOutcome,
    ) -> KnowledgePromotionReviewRecord:
        ...

    def mark_rejected(
        self,
        review_id: str,
        *,
        reviewer_ref: str,
    ) -> KnowledgePromotionReviewRecord:
        ...

    def list_pending_reviews(
        self,
    ) -> tuple[
        KnowledgePromotionReviewRecord,
        ...,
    ]:
        ...
