-- DV25-P3B3 (H2): solicitud canónica persistente de archivado en Box desde el visor.
--
-- Aditiva e idempotente: solo crea document_viewer_archive_intents y su índice.
-- No modifica document_inbox_items, document_inbox_events, expedientes, usuarios
-- ni Box. NO se aplica al abrir pantallas ni al arrancar: solo por el proceso de
-- migración aprobado (en P3B3, exclusivamente sobre bases temporales de test).
--
-- idempotency_key: SHA-256 de (ítem, cliente, expediente, subcarpeta,
--   nomenclatura, SHA-256 del origen). La misma petición repetida desde otro
--   proceso o puesto choca con UNIQUE: nunca se archiva dos veces.
-- Índice parcial: un ítem solo puede tener una solicitud activa (en curso o
--   pendiente de revisión humana) aunque llegue con otra clave.
-- fence + owner_token: cada adquisición incrementa fence; solo el titular
--   vigente puede cerrar la solicitud (UPDATE condicionado).
--
-- Dialecto: SQLite. El contrato (UNIQUE, índice parcial, UPDATE condicionado)
-- es el mismo en PostgreSQL; allí id sería GENERATED ALWAYS AS IDENTITY.

CREATE TABLE IF NOT EXISTS document_viewer_archive_intents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    idempotency_key TEXT NOT NULL UNIQUE
        CHECK (length(idempotency_key) = 64),
    inbox_item_id INTEGER NOT NULL
        CHECK (inbox_item_id > 0),
    client_id INTEGER NOT NULL
        CHECK (client_id > 0),
    expedient_id INTEGER NOT NULL
        CHECK (expedient_id > 0),
    subfolder TEXT NOT NULL,
    nomenclature_key TEXT NOT NULL,
    source_sha256 TEXT NOT NULL
        CHECK (length(source_sha256) = 64),
    requested_by_user_id INTEGER NOT NULL
        CHECK (requested_by_user_id > 0),
    state TEXT NOT NULL
        CHECK (state IN ('claimed', 'registered', 'rejected', 'needs_review')),
    fence INTEGER NOT NULL DEFAULT 1
        CHECK (fence >= 1),
    owner_token TEXT NOT NULL
        CHECK (length(owner_token) BETWEEN 16 AND 64),
    claimed_at TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL,
    finished_at TEXT,
    destination_path TEXT,
    result_json TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_document_viewer_archive_intents_active_item
    ON document_viewer_archive_intents(inbox_item_id)
    WHERE state IN ('claimed', 'needs_review');
