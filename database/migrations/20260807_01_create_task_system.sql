PRAGMA foreign_keys = ON;

-- Núcleo universal de tareas del ERP.
--
-- Una tarea representa trabajo pendiente con una fecha de vencimiento.
-- El calendario será una proyección visual de esta tabla.
--
-- Los avisos Telegram se implementarán mediante una outbox independiente
-- en la siguiente fase.

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    cliente_id INTEGER,
    expediente_id INTEGER,

    titulo TEXT NOT NULL,
    descripcion TEXT,

    tipo TEXT NOT NULL DEFAULT 'GENERAL',

    prioridad TEXT NOT NULL DEFAULT 'NORMAL'
        CHECK (
            prioridad IN (
                'BAJA',
                'NORMAL',
                'ALTA',
                'URGENTE'
            )
        ),

    estado TEXT NOT NULL DEFAULT 'PENDIENTE'
        CHECK (
            estado IN (
                'PENDIENTE',
                'EN_CURSO',
                'COMPLETADA',
                'CANCELADA'
            )
        ),

    responsable TEXT,

    fecha_inicio TEXT,
    fecha_vencimiento TEXT NOT NULL,

    origen_tipo TEXT NOT NULL DEFAULT 'MANUAL',
    origen_id TEXT,

    -- Clave estable para impedir que automatismos creen
    -- varias veces la misma tarea.
    source_key TEXT,

    created_by TEXT,

    completada_at TEXT,
    cancelada_at TEXT,

    activo INTEGER NOT NULL DEFAULT 1,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (cliente_id)
        REFERENCES clientes(id),

    FOREIGN KEY (expediente_id)
        REFERENCES expedientes(id)
);

CREATE INDEX IF NOT EXISTS
    idx_tasks_estado_vencimiento
ON tasks(
    activo,
    estado,
    fecha_vencimiento
);

CREATE INDEX IF NOT EXISTS
    idx_tasks_cliente
ON tasks(cliente_id);

CREATE INDEX IF NOT EXISTS
    idx_tasks_expediente
ON tasks(expediente_id);

CREATE INDEX IF NOT EXISTS
    idx_tasks_responsable
ON tasks(responsable);

CREATE INDEX IF NOT EXISTS
    idx_tasks_origen
ON tasks(
    origen_tipo,
    origen_id
);

CREATE UNIQUE INDEX IF NOT EXISTS
    ux_tasks_source_key
ON tasks(source_key)
WHERE
    source_key IS NOT NULL
    AND TRIM(source_key) <> '';
