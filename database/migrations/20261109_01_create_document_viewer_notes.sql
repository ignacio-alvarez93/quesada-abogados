-- DV24-P2: notas persistentes por documento del visor documental.
--
-- Aditiva e idempotente: solo crea document_viewer_notes y su índice.
-- No modifica document_inbox_items.notes, expedientes, usuarios, Box ni
-- ninguna otra tabla. Las notas pertenecen al CRM, nunca al PDF.
--
-- Identidad documental (document_ref):
--   inbox:<item_id>                          ítem inmutable de Bandeja
--   expedient:<expediente_id>:<ruta relativa> archivo bajo la raíz del expediente
-- content_sha256 fija la revisión del archivo anotado: un archivo
-- reemplazado no hereda las notas de la versión anterior.

CREATE TABLE IF NOT EXISTS document_viewer_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_kind TEXT NOT NULL
        CHECK (document_kind IN ('inbox', 'expedient')),
    document_ref TEXT NOT NULL
        CHECK (length(document_ref) BETWEEN 1 AND 2048),
    inbox_item_id INTEGER,
    expediente_id INTEGER,
    relative_path TEXT,
    content_sha256 TEXT NOT NULL
        CHECK (length(content_sha256) = 64),
    size_bytes INTEGER NOT NULL
        CHECK (size_bytes >= 0),
    body TEXT NOT NULL
        CHECK (length(trim(body)) > 0 AND length(body) <= 4000),
    author_user_id INTEGER NOT NULL,
    author_username TEXT NOT NULL
        CHECK (length(author_username) > 0),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'archived')),
    request_id TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    CHECK (
        (document_kind = 'inbox' AND inbox_item_id IS NOT NULL)
        OR (
            document_kind = 'expedient'
            AND expediente_id IS NOT NULL
            AND relative_path IS NOT NULL
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_document_viewer_notes_document
    ON document_viewer_notes(document_ref, content_sha256, id);
