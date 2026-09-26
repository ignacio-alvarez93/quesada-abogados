-- ============================================================
-- KNOWLEDGE · CATÁLOGO GOBERNADO
-- Migration: 20260915_create_knowledge_catalog
--
-- CORE / FOLLOWED / DISCOVERED expresa política interna.
--
-- Deliberadamente NO existe FK obligatoria a knowledge_items:
-- una identidad puede ser catalogada antes de ser materializada.
--
-- Debe permanecer idempotente.
-- ============================================================

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS knowledge_catalog_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    source_key TEXT NOT NULL,
    external_id TEXT NOT NULL,
    canonical_key TEXT NOT NULL,

    tier TEXT NOT NULL,
    watch_updates INTEGER NOT NULL,
    priority INTEGER NOT NULL,
    added_reason TEXT NOT NULL DEFAULT '',

    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    UNIQUE(source_key, external_id),
    UNIQUE(canonical_key),

    CHECK (
        tier IN (
            'CORE',
            'FOLLOWED',
            'DISCOVERED'
        )
    ),

    CHECK (
        watch_updates IN (0, 1)
    ),

    CHECK (
        priority >= 0
        AND priority <= 100
    ),

    CHECK (
        tier = 'DISCOVERED'
        OR watch_updates = 1
    )
);

CREATE INDEX IF NOT EXISTS idx_knowledge_catalog_tier
    ON knowledge_catalog_entries(tier);

CREATE INDEX IF NOT EXISTS idx_knowledge_catalog_watch
    ON knowledge_catalog_entries(watch_updates);

CREATE INDEX IF NOT EXISTS idx_knowledge_catalog_priority
    ON knowledge_catalog_entries(priority);
