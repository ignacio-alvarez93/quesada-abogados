"""Persistencia SQLite de revisión humana de promoción Knowledge."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import uuid

from .promotion_review import (
    KnowledgePromotionReviewOutcome,
    KnowledgePromotionReviewRecord,
    KnowledgePromotionReviewState,
)


DEFAULT_DB_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "quesada.db"
)

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "migrations"
    / "20261006_create_knowledge_promotion_review.sql"
)


def _utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


class SQLiteKnowledgePromotionReviewRepository:
    """Adaptador SQLite de la puerta de revisión humana de promoción."""

    def __init__(
        self,
        db_path: str | Path = DEFAULT_DB_PATH,
    ) -> None:
        self._db_path = Path(
            db_path
        )

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _connect(
        self,
    ) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self._db_path
        )

        connection.row_factory = (
            sqlite3.Row
        )

        connection.execute(
            "PRAGMA foreign_keys = ON"
        )

        return connection

    @contextmanager
    def _managed_connection(self):
        connection = self._connect()

        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize_schema(
        self,
    ) -> None:
        if not _MIGRATION_PATH.exists():
            raise FileNotFoundError(
                "No existe migración de revisión de promoción: "
                f"{_MIGRATION_PATH}"
            )

        schema = (
            _MIGRATION_PATH.read_text(
                encoding="utf-8"
            )
        )

        self._db_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with self._managed_connection() as connection:
            connection.executescript(
                schema
            )

    @staticmethod
    def _record_from_row(
        row: sqlite3.Row,
    ) -> KnowledgePromotionReviewRecord:
        return KnowledgePromotionReviewRecord(
            review_id=row[
                "review_id"
            ],
            source_canonical_key=row[
                "source_canonical_key"
            ],
            target_canonical_key=row[
                "target_canonical_key"
            ],
            reason=row[
                "reason"
            ],
            recommended_priority=(
                int(
                    row["recommended_priority"]
                )
                if row["recommended_priority"]
                is not None
                else None
            ),
            state=KnowledgePromotionReviewState(
                row["state"]
            ),
            reviewer_ref=row[
                "reviewer_ref"
            ],
            created_at=row[
                "created_at"
            ],
            reviewed_at=row[
                "reviewed_at"
            ],
            outcome=KnowledgePromotionReviewOutcome(
                row["outcome"]
            ),
        )

    def create_pending_review(
        self,
        *,
        source_canonical_key: str,
        target_canonical_key: str,
        reason: str,
        recommended_priority: int | None,
    ) -> KnowledgePromotionReviewRecord:
        source_canonical_key = str(
            source_canonical_key or ""
        ).strip()

        target_canonical_key = str(
            target_canonical_key or ""
        ).strip()

        if not source_canonical_key:
            raise ValueError(
                "source_canonical_key no puede estar vacío"
            )

        if not target_canonical_key:
            raise ValueError(
                "target_canonical_key no puede estar vacío"
            )

        review_id = uuid.uuid4().hex
        now = _utc_now()

        with self._managed_connection() as connection:
            connection.execute(
                """
                INSERT INTO knowledge_promotion_reviews (
                    review_id,
                    source_canonical_key,
                    target_canonical_key,
                    reason,
                    recommended_priority,
                    state,
                    reviewer_ref,
                    created_at,
                    reviewed_at,
                    outcome
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review_id,
                    source_canonical_key,
                    target_canonical_key,
                    str(
                        reason or ""
                    ).strip(),
                    recommended_priority,
                    KnowledgePromotionReviewState.PENDING_REVIEW.value,
                    None,
                    now,
                    None,
                    KnowledgePromotionReviewOutcome.NOT_PROMOTED.value,
                ),
            )

        return self.get_review(
            review_id
        )

    def get_review(
        self,
        review_id: str,
    ) -> KnowledgePromotionReviewRecord | None:
        review_id = str(
            review_id or ""
        ).strip()

        if not review_id:
            raise ValueError(
                "review_id no puede estar vacío"
            )

        with self._managed_connection() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM knowledge_promotion_reviews
                WHERE review_id = ?
                """,
                (
                    review_id,
                ),
            ).fetchone()

        if row is None:
            return None

        return self._record_from_row(
            row
        )

    def mark_approved(
        self,
        review_id: str,
        *,
        reviewer_ref: str,
        outcome: KnowledgePromotionReviewOutcome,
    ) -> KnowledgePromotionReviewRecord:
        if not isinstance(
            outcome,
            KnowledgePromotionReviewOutcome,
        ):
            raise TypeError(
                "outcome debe ser "
                "KnowledgePromotionReviewOutcome"
            )

        return self._mark_decided(
            review_id,
            state=(
                KnowledgePromotionReviewState.APPROVED
            ),
            reviewer_ref=reviewer_ref,
            outcome=outcome,
        )

    def mark_rejected(
        self,
        review_id: str,
        *,
        reviewer_ref: str,
    ) -> KnowledgePromotionReviewRecord:
        return self._mark_decided(
            review_id,
            state=(
                KnowledgePromotionReviewState.REJECTED
            ),
            reviewer_ref=reviewer_ref,
            outcome=(
                KnowledgePromotionReviewOutcome.NOT_PROMOTED
            ),
        )

    def _mark_decided(
        self,
        review_id: str,
        *,
        state: KnowledgePromotionReviewState,
        reviewer_ref: str,
        outcome: KnowledgePromotionReviewOutcome,
    ) -> KnowledgePromotionReviewRecord:
        review_id = str(
            review_id or ""
        ).strip()

        reviewer_ref = str(
            reviewer_ref or ""
        ).strip()

        if not review_id:
            raise ValueError(
                "review_id no puede estar vacío"
            )

        if not reviewer_ref:
            raise ValueError(
                "reviewer_ref no puede estar vacío"
            )

        now = _utc_now()

        with self._managed_connection() as connection:
            current = connection.execute(
                """
                SELECT *
                FROM knowledge_promotion_reviews
                WHERE review_id = ?
                """,
                (
                    review_id,
                ),
            ).fetchone()

            if current is None:
                raise LookupError(
                    f"No existe revisión: {review_id}"
                )

            connection.execute(
                """
                UPDATE knowledge_promotion_reviews
                SET
                    state = ?,
                    reviewer_ref = ?,
                    reviewed_at = ?,
                    outcome = ?
                WHERE review_id = ?
                """,
                (
                    state.value,
                    reviewer_ref,
                    now,
                    outcome.value,
                    review_id,
                ),
            )

        return self.get_review(
            review_id
        )

    def list_pending_reviews(
        self,
    ) -> tuple[
        KnowledgePromotionReviewRecord,
        ...,
    ]:
        with self._managed_connection() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM knowledge_promotion_reviews
                WHERE state = ?
                ORDER BY created_at ASC
                """,
                (
                    KnowledgePromotionReviewState.PENDING_REVIEW.value,
                ),
            ).fetchall()

        return tuple(
            self._record_from_row(
                row
            )
            for row in rows
        )
