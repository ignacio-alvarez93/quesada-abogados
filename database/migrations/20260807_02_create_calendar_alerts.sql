PRAGMA foreign_keys = ON;

-- Avisos temporales del calendario.
--
-- Un aviso no representa necesariamente trabajo.
-- Representa información relevante asociada a una fecha:
--
-- - caducidad de antecedentes;
-- - caducidad de pasaporte;
-- - fecha límite documental;
-- - vencimiento administrativo;
-- - recordatorio operativo.
--
-- Las tareas siguen siendo acciones ejecutables.

CREATE TABLE IF NOT EXISTS calendar_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    cliente_id INTEGER,
    expediente_id INTEGER,

    -- Referencia documental opcional.
    -- No se fuerza FK porque el ecosistema documental
    -- actual utiliza varias tablas/orígenes.
    documento_id INTEGER,

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

    estado TEXT NOT NULL DEFAULT 'ACTIVO'
        CHECK (
            estado IN (
                'ACTIVO',
                'RESUELTO',
                'CANCELADO'
            )
        ),

    -- Fecha del hecho que se está vigilando.
    -- Ej.: caducidad de penales.
    fecha_evento TEXT NOT NULL,

    -- Fecha desde la que queremos empezar
    -- a mostrar/avisar sobre ese hecho.
    fecha_inicio_aviso TEXT,

    origen_tipo TEXT NOT NULL DEFAULT 'MANUAL',
    origen_id TEXT,

    -- Idempotencia para avisos automáticos.
    -- Ej:
    -- CADUCIDAD_PENALES:EXP51:DOC120
    source_key TEXT,

    created_by TEXT,

    resolved_at TEXT,
    cancelled_at TEXT,

    activo INTEGER NOT NULL DEFAULT 1,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (cliente_id)
        REFERENCES clientes(id),

    FOREIGN KEY (expediente_id)
        REFERENCES expedientes(id)
);

CREATE INDEX IF NOT EXISTS
    idx_calendar_alerts_event
ON calendar_alerts(
    activo,
    estado,
    fecha_evento
);

CREATE INDEX IF NOT EXISTS
    idx_calendar_alerts_cliente
ON calendar_alerts(cliente_id);

CREATE INDEX IF NOT EXISTS
    idx_calendar_alerts_expediente
ON calendar_alerts(expediente_id);

CREATE INDEX IF NOT EXISTS
    idx_calendar_alerts_origen
ON calendar_alerts(
    origen_tipo,
    origen_id
);

CREATE UNIQUE INDEX IF NOT EXISTS
    ux_calendar_alerts_source_key
ON calendar_alerts(source_key)
WHERE
    source_key IS NOT NULL
    AND TRIM(source_key) <> '';
