PRAGMA foreign_keys = ON;

-- ============================================================
-- ORIGEN DE CREACIÓN DEL EXPEDIENTE
-- ============================================================
--
-- Tabla complementaria uno-a-uno para no reconstruir todavía
-- la tabla central expedientes.
--
-- Un expediente sin registro explícito se interpreta como
-- APERTURA_MANUAL por compatibilidad con datos históricos.

CREATE TABLE IF NOT EXISTS expediente_origenes_creacion (
    expediente_id INTEGER PRIMARY KEY,

    origen_creacion TEXT NOT NULL
        DEFAULT 'APERTURA_MANUAL',

    descripcion TEXT,

    created_by TEXT,
    created_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    updated_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (expediente_id)
        REFERENCES expedientes(id)
        ON DELETE CASCADE,

    CHECK (
        origen_creacion IN (
            'APERTURA_MANUAL',
            'DERIVACION_INTERNA',
            'CONTINUIDAD_MANUAL',
            'CONTINUIDAD_CON_HITO_EXTERNO',
            'MIGRACION_LEGACY',
            'IMPORTACION'
        )
    )
);

CREATE INDEX IF NOT EXISTS
idx_expediente_origenes_creacion_codigo
ON expediente_origenes_creacion (
    origen_creacion,
    expediente_id
);


-- ============================================================
-- ORIGEN DE UNA RELACIÓN ENTRE EXPEDIENTES
-- ============================================================
--
-- expediente_relaciones define qué expedientes están vinculados.
-- Esta tabla complementaria explica cómo se creó la relación.

CREATE TABLE IF NOT EXISTS expediente_relacion_origenes (
    relacion_id INTEGER PRIMARY KEY,

    origen_relacion TEXT NOT NULL
        DEFAULT 'VINCULACION_MANUAL',

    descripcion TEXT,

    created_by TEXT,
    created_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    updated_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (relacion_id)
        REFERENCES expediente_relaciones(id)
        ON DELETE CASCADE,

    CHECK (
        origen_relacion IN (
            'DERIVACION_AUTOMATICA',
            'VINCULACION_MANUAL',
            'MIGRACION_LEGACY',
            'IMPORTACION'
        )
    )
);

CREATE INDEX IF NOT EXISTS
idx_expediente_relacion_origenes_codigo
ON expediente_relacion_origenes (
    origen_relacion,
    relacion_id
);


-- ============================================================
-- HITOS EXTERNOS
-- ============================================================
--
-- Representan trámites o acontecimientos de la trayectoria del
-- cliente que no fueron gestionados como expedientes del despacho.
--
-- Ejemplo:
--
-- Reagrupación CRM
-- → Visado gestionado externamente
-- → Toma de huellas CRM

CREATE TABLE IF NOT EXISTS expediente_hitos_externos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    cliente_id INTEGER NOT NULL,

    codigo TEXT NOT NULL,
    nombre TEXT NOT NULL,

    familia_referencia_codigo TEXT,
    tipo_referencia_codigo TEXT,
    subtipo_referencia_codigo TEXT,

    fecha_inicio TEXT,
    fecha_fin TEXT,

    estado TEXT NOT NULL
        DEFAULT 'REGISTRADO',

    resultado TEXT,

    observaciones TEXT,
    documento_referencia TEXT,

    expediente_anterior_id INTEGER,
    expediente_posterior_id INTEGER,

    orden INTEGER NOT NULL
        DEFAULT 0,

    created_by TEXT,
    activo INTEGER NOT NULL
        DEFAULT 1,

    created_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    updated_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (cliente_id)
        REFERENCES clientes(id)
        ON DELETE CASCADE,

    FOREIGN KEY (expediente_anterior_id)
        REFERENCES expedientes(id)
        ON DELETE SET NULL,

    FOREIGN KEY (expediente_posterior_id)
        REFERENCES expedientes(id)
        ON DELETE SET NULL,

    CHECK (
        expediente_anterior_id IS NOT NULL
        OR expediente_posterior_id IS NOT NULL
    ),

    CHECK (
        expediente_anterior_id IS NULL
        OR expediente_posterior_id IS NULL
        OR expediente_anterior_id
            <> expediente_posterior_id
    ),

    CHECK (
        estado IN (
            'REGISTRADO',
            'EN_TRAMITE',
            'FINALIZADO',
            'CANCELADO'
        )
    ),

    CHECK (
        activo IN (0, 1)
    )
);

CREATE INDEX IF NOT EXISTS
idx_hitos_externos_cliente
ON expediente_hitos_externos (
    cliente_id,
    activo,
    created_at
);

CREATE INDEX IF NOT EXISTS
idx_hitos_externos_anterior
ON expediente_hitos_externos (
    expediente_anterior_id,
    activo,
    orden
);

CREATE INDEX IF NOT EXISTS
idx_hitos_externos_posterior
ON expediente_hitos_externos (
    expediente_posterior_id,
    activo,
    orden
);

CREATE INDEX IF NOT EXISTS
idx_hitos_externos_codigo
ON expediente_hitos_externos (
    codigo,
    resultado,
    activo
);

CREATE UNIQUE INDEX IF NOT EXISTS
uq_hito_externo_activo_trayectoria
ON expediente_hitos_externos (
    cliente_id,
    codigo,
    IFNULL(expediente_anterior_id, 0),
    IFNULL(expediente_posterior_id, 0)
)
WHERE activo = 1;
