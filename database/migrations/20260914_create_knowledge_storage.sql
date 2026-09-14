-- ============================================================
-- KNOWLEDGE · PERSISTENCIA CANÓNICA SQLITE
-- Migration: 20260914_create_knowledge_storage
--
-- Autoridad de schema SQLite para Knowledge.
-- Debe permanecer idempotente.
-- ============================================================

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS knowledge_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    source_key TEXT NOT NULL,
    external_id TEXT NOT NULL,
    canonical_key TEXT NOT NULL,

    title TEXT NOT NULL,
    item_kind TEXT NOT NULL,
    canonical_uri TEXT NOT NULL DEFAULT '',
    source_revision TEXT NOT NULL DEFAULT '',
    published_on TEXT,
    language TEXT NOT NULL,

    content_text TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    record_sha256 TEXT NOT NULL,

    metadata_json TEXT NOT NULL,

    revision_number INTEGER NOT NULL,

    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    UNIQUE(source_key, external_id),
    UNIQUE(canonical_key)
);

CREATE INDEX IF NOT EXISTS idx_knowledge_items_source
    ON knowledge_items(source_key);

CREATE INDEX IF NOT EXISTS idx_knowledge_items_published_on
    ON knowledge_items(published_on);

CREATE INDEX IF NOT EXISTS idx_knowledge_items_kind
    ON knowledge_items(item_kind);


CREATE TABLE IF NOT EXISTS knowledge_item_revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    knowledge_item_id INTEGER NOT NULL,

    revision_number INTEGER NOT NULL,
    revision_status TEXT NOT NULL,

    source_key TEXT NOT NULL,
    external_id TEXT NOT NULL,
    canonical_key TEXT NOT NULL,

    title TEXT NOT NULL,
    item_kind TEXT NOT NULL,
    canonical_uri TEXT NOT NULL DEFAULT '',
    source_revision TEXT NOT NULL DEFAULT '',
    published_on TEXT,
    language TEXT NOT NULL,

    content_text TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    record_sha256 TEXT NOT NULL,

    metadata_json TEXT NOT NULL,

    observed_at TEXT NOT NULL,

    FOREIGN KEY(knowledge_item_id)
        REFERENCES knowledge_items(id)
        ON DELETE CASCADE,

    UNIQUE(
        knowledge_item_id,
        revision_number
    )
);

CREATE INDEX IF NOT EXISTS idx_knowledge_revisions_identity
    ON knowledge_item_revisions(
        source_key,
        external_id,
        revision_number
    );

CREATE INDEX IF NOT EXISTS idx_knowledge_revisions_status
    ON knowledge_item_revisions(revision_status);
