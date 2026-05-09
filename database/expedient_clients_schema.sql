-- database/expedient_clients_schema.sql
-- Relación muchos-a-muchos entre expedientes y clientes.
-- Permite casos como reagrupación:
-- - cliente principal / reagrupado
-- - cliente pagador / reagrupante
-- - titular, familiar, representante, etc.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS expediente_clientes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    expediente_id INTEGER NOT NULL,
    cliente_id INTEGER NOT NULL,
    rol TEXT NOT NULL DEFAULT 'RELACIONADO',
    es_principal INTEGER NOT NULL DEFAULT 0,
    activo INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (expediente_id) REFERENCES expedientes(id) ON DELETE CASCADE,
    FOREIGN KEY (cliente_id) REFERENCES clientes(id) ON DELETE CASCADE,
    UNIQUE(expediente_id, cliente_id, rol)
);

CREATE INDEX IF NOT EXISTS idx_expediente_clientes_expediente ON expediente_clientes(expediente_id);
CREATE INDEX IF NOT EXISTS idx_expediente_clientes_cliente ON expediente_clientes(cliente_id);
CREATE INDEX IF NOT EXISTS idx_expediente_clientes_rol ON expediente_clientes(rol);

-- Backfill: todo expediente actual queda asociado a su cliente principal.
INSERT OR IGNORE INTO expediente_clientes (
    expediente_id,
    cliente_id,
    rol,
    es_principal,
    activo
)
SELECT
    id,
    cliente_id,
    'CLIENTE_PRINCIPAL',
    1,
    1
FROM expedientes
WHERE cliente_id IS NOT NULL;
