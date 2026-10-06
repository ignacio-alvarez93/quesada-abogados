"""Revisión humana explícita de promoción DISCOVERED -> FOLLOWED.

KnowledgePromotionPolicyService decide qué promoción se recomienda.
Este módulo gobierna el paso adicional obligatorio: ninguna promoción
DISCOVERED -> FOLLOWED cambia el catálogo sin una revisión humana
explícita, persistida y atribuible a un revisor.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class KnowledgePromotionReviewState(str, Enum):
    """Estado del ciclo de vida de una revisión humana."""

    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class KnowledgePromotionReviewOutcome(str, Enum):
    """Efecto real sobre el catálogo tras la revisión."""

    NOT_PROMOTED = "NOT_PROMOTED"
    PROMOTED_FOLLOWED = "PROMOTED_FOLLOWED"


@dataclass(frozen=True, slots=True)
class KnowledgePromotionReviewRecord:
    """Registro auditable de una recomendación de promoción."""

    review_id: str
    source_canonical_key: str
    target_canonical_key: str
    reason: str
    recommended_priority: int | None

    state: KnowledgePromotionReviewState
    reviewer_ref: str | None

    created_at: str
    reviewed_at: str | None

    outcome: KnowledgePromotionReviewOutcome

    def __post_init__(self) -> None:
        review_id = str(self.review_id or "").strip()

        if not review_id:
            raise ValueError(
                "review_id no puede estar vacío"
            )

        source_canonical_key = str(
            self.source_canonical_key or ""
        ).strip()

        if not source_canonical_key:
            raise ValueError(
                "source_canonical_key no puede estar vacío"
            )

        target_canonical_key = str(
            self.target_canonical_key or ""
        ).strip()

        if not target_canonical_key:
            raise ValueError(
                "target_canonical_key no puede estar vacío"
            )

        if not isinstance(
            self.state,
            KnowledgePromotionReviewState,
        ):
            raise TypeError(
                "state debe ser KnowledgePromotionReviewState"
            )

        if not isinstance(
            self.outcome,
            KnowledgePromotionReviewOutcome,
        ):
            raise TypeError(
                "outcome debe ser KnowledgePromotionReviewOutcome"
            )

        if not self.created_at:
            raise ValueError(
                "created_at no puede estar vacío"
            )

        if self.state is KnowledgePromotionReviewState.PENDING_REVIEW:
            if self.reviewer_ref is not None:
                raise ValueError(
                    "PENDING_REVIEW no puede tener reviewer_ref"
                )

            if self.reviewed_at is not None:
                raise ValueError(
                    "PENDING_REVIEW no puede tener reviewed_at"
                )

            if (
                self.outcome
                is not KnowledgePromotionReviewOutcome.NOT_PROMOTED
            ):
                raise ValueError(
                    "PENDING_REVIEW debe tener outcome NOT_PROMOTED"
                )
        else:
            if (
                not self.reviewer_ref
                or not str(self.reviewer_ref).strip()
            ):
                raise ValueError(
                    f"{self.state.value} requiere reviewer_ref"
                )

            if not self.reviewed_at:
                raise ValueError(
                    f"{self.state.value} requiere reviewed_at"
                )

        if (
            self.state is KnowledgePromotionReviewState.APPROVED
            and self.outcome
            is not KnowledgePromotionReviewOutcome.PROMOTED_FOLLOWED
        ):
            raise ValueError(
                "APPROVED debe resultar en outcome PROMOTED_FOLLOWED"
            )

        if (
            self.state is KnowledgePromotionReviewState.REJECTED
            and self.outcome
            is not KnowledgePromotionReviewOutcome.NOT_PROMOTED
        ):
            raise ValueError(
                "REJECTED debe resultar en outcome NOT_PROMOTED"
            )

        if (
            self.recommended_priority is not None
            and not 0 <= self.recommended_priority <= 100
        ):
            raise ValueError(
                "recommended_priority debe estar entre 0 y 100"
            )

        object.__setattr__(
            self,
            "review_id",
            review_id,
        )
        object.__setattr__(
            self,
            "source_canonical_key",
            source_canonical_key,
        )
        object.__setattr__(
            self,
            "target_canonical_key",
            target_canonical_key,
        )
        object.__setattr__(
            self,
            "reason",
            str(self.reason or "").strip(),
        )
