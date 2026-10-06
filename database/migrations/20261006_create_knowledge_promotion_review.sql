-- ============================================================
-- KNOWLEDGE · REVISIÓN HUMANA DE PROMOCIÓN
-- Migration: 20261006_create_knowledge_promotion_review
--
-- Puerta de revisión humana explícita para promoción
-- DISCOVERED -> FOLLOWED del catálogo gobernado.
--
-- Aditiva: no modifica knowledge_catalog_entries.
-- Una recomendación PENDING_REVIEW no muta el catálogo.
-- Solo APPROVED produce tier=FOLLOWED.
--
-- Debe permanecer idempotente.
-- ============================================================

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS knowledge_promotion_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    review_id TEXT NOT NULL,

    source_canonical_key TEXT NOT NULL,
    target_canonical_key TEXT NOT NULL,

    reason TEXT NOT NULL DEFAULT '',
    recommended_priority INTEGER,

    state TEXT NOT NULL,
    reviewer_ref TEXT,

    created_at TEXT NOT NULL,
    reviewed_at TEXT,

    outcome TEXT NOT NULL,

    UNIQUE(review_id),

    CHECK (
        state IN (
            'PENDING_REVIEW',
            'APPROVED',
            'REJECTED'
        )
    ),

    CHECK (
        outcome IN (
            'NOT_PROMOTED',
            'PROMOTED_FOLLOWED'
        )
    ),

    CHECK (
        recommended_priority IS NULL
        OR (
            recommended_priority >= 0
            AND recommended_priority <= 100
        )
    ),

    CHECK (
        state != 'PENDING_REVIEW'
        OR (
            reviewer_ref IS NULL
            AND reviewed_at IS NULL
        )
    ),

    CHECK (
        state = 'PENDING_REVIEW'
        OR (
            reviewer_ref IS NOT NULL
            AND reviewed_at IS NOT NULL
        )
    ),

    CHECK (
        state != 'APPROVED'
        OR outcome = 'PROMOTED_FOLLOWED'
    ),

    CHECK (
        state != 'REJECTED'
        OR outcome = 'NOT_PROMOTED'
    )
);

CREATE INDEX IF NOT EXISTS idx_knowledge_promotion_reviews_state
    ON knowledge_promotion_reviews(state);

CREATE INDEX IF NOT EXISTS idx_knowledge_promotion_reviews_target
    ON knowledge_promotion_reviews(target_canonical_key);
