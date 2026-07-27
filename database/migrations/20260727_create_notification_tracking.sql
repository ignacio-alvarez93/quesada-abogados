PRAGMA foreign_keys = ON;

-- Proyección operativa de la trazabilidad administrativa.
-- La creación efectiva también se garantiza mediante migración
-- defensiva en notification_tracking_service.py.

CREATE TABLE IF NOT EXISTS notification_tracking (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    expediente_id INTEGER NOT NULL UNIQUE,
    cliente_id INTEGER NOT NULL,

    familia_codigo TEXT,
    notification_workflow_code TEXT NOT NULL,

    estado TEXT NOT NULL,
    activo INTEGER NOT NULL DEFAULT 1,

    numero_expediente_interno TEXT,
    numero_presentacion_registro TEXT,
    numero_expediente_extranjeria TEXT,
    numero_registro_regage TEXT,
    registro_csv_geiser TEXT,

    justificante_presentacion_id INTEGER,
    justificante_admision_id INTEGER,
    justificante_resolucion_id INTEGER,

    tipo_admision TEXT,
    resultado_resolucion TEXT,

    fecha_inicio_espera_numero TEXT,
    fecha_inicio_espera_admision TEXT,
    fecha_inicio_espera_resolucion TEXT,
    closed_at TEXT,

    origen_ultima_sincronizacion TEXT,
    usuario_ultima_sincronizacion TEXT,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (expediente_id) REFERENCES expedientes(id),
    FOREIGN KEY (cliente_id) REFERENCES clientes(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS
    ux_notification_tracking_expediente
ON notification_tracking(expediente_id);

CREATE INDEX IF NOT EXISTS
    idx_notification_tracking_activo_estado
ON notification_tracking(activo, estado);

CREATE INDEX IF NOT EXISTS
    idx_notification_tracking_cliente
ON notification_tracking(cliente_id);
