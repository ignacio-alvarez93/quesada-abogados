-- ============================================================
-- KNOWLEDGE · ESTRUCTURA JURÍDICA CANÓNICA
-- Migration: 20260915_create_knowledge_structure
--
-- KnowledgeItem
--      -> KnowledgeBlock
--          -> KnowledgeBlockVersion
--
-- Debe permanecer idempotente.
-- ============================================================

PRAGMA foreign_keys = ON;


CREATE TABLE IF NOT EXISTS knowledge_blocks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    source_key TEXT NOT NULL,
    external_id TEXT NOT NULL,

    block_id TEXT NOT NULL,
    canonical_key TEXT NOT NULL,

    position INTEGER NOT NULL,

    title TEXT NOT NULL DEFAULT '',
    canonical_uri TEXT NOT NULL DEFAULT '',

    current_version_key TEXT NOT NULL,

    metadata_json TEXT NOT NULL,

    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    FOREIGN KEY (
        source_key,
        external_id
    )
    REFERENCES knowledge_items (
        source_key,
        external_id
    )
    ON DELETE CASCADE,

    UNIQUE (
        source_key,
        external_id,
        block_id
    ),

    UNIQUE (
        canonical_key
    ),

    CHECK (
        position >= 1
    )
);


CREATE INDEX IF NOT EXISTS idx_knowledge_blocks_item
    ON knowledge_blocks(
        source_key,
        external_id,
        position
    );


CREATE TABLE IF NOT EXISTS knowledge_block_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    knowledge_block_id INTEGER NOT NULL,

    source_key TEXT NOT NULL,
    external_id TEXT NOT NULL,
    block_id TEXT NOT NULL,

    version_key TEXT NOT NULL,
    canonical_key TEXT NOT NULL,

    version_position INTEGER NOT NULL,

    modifier_external_id TEXT NOT NULL DEFAULT '',

    published_on TEXT,
    effective_from TEXT,

    is_current INTEGER NOT NULL,

    content_text TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,

    metadata_json TEXT NOT NULL,

    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    FOREIGN KEY (
        knowledge_block_id
    )
    REFERENCES knowledge_blocks (
        id
    )
    ON DELETE CASCADE,

    FOREIGN KEY (
        source_key,
        external_id,
        block_id
    )
    REFERENCES knowledge_blocks (
        source_key,
        external_id,
        block_id
    )
    ON DELETE CASCADE,

    UNIQUE (
        source_key,
        external_id,
        block_id,
        version_position
    ),

    UNIQUE (
        version_key
    ),

    UNIQUE (
        canonical_key
    ),

    CHECK (
        version_position >= 1
    ),

    CHECK (
        is_current IN (0, 1)
    )
);


CREATE INDEX IF NOT EXISTS idx_knowledge_block_versions_block
    ON knowledge_block_versions(
        source_key,
        external_id,
        block_id,
        version_position
    );


CREATE INDEX IF NOT EXISTS idx_knowledge_block_versions_effective
    ON knowledge_block_versions(
        effective_from
    );


CREATE INDEX IF NOT EXISTS idx_knowledge_block_versions_modifier
    ON knowledge_block_versions(
        modifier_external_id
    );


CREATE UNIQUE INDEX IF NOT EXISTS uq_knowledge_block_current_version
    ON knowledge_block_versions(
        source_key,
        external_id,
        block_id
    )
    WHERE is_current = 1;
