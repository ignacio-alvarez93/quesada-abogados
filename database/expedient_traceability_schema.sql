-- database/expedient_traceability_schema.sql
-- Módulo Expedientes - Fase 2: trazabilidad documental y económica inicial

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS expediente_eventos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    expediente_id INTEGER NOT NULL,
    cliente_id INTEGER NOT NULL,
    tipo_evento TEXT NOT NULL,
    titulo TEXT NOT NULL,
    descripcion TEXT,
    estado_anterior TEXT,
    estado_nuevo TEXT,
    entidad_relacionada TEXT,
    entidad_relacionada_id INTEGER,
    usuario TEXT,
    fecha_evento TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (expediente_id) REFERENCES expedientes(id) ON DELETE CASCADE,
    FOREIGN KEY (cliente_id) REFERENCES clientes(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS expediente_justificantes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    expediente_id INTEGER NOT NULL,
    cliente_id INTEGER NOT NULL,
    archivo_nombre TEXT,
    archivo_ruta TEXT,
    tipo_justificante TEXT DEFAULT 'PRESENTACION',
    fecha_presentacion TEXT,
    numero_registro TEXT,
    organo_presentacion TEXT,
    procedimiento_detectado TEXT,
    estado_conciliacion TEXT NOT NULL DEFAULT 'PENDIENTE',
    observaciones TEXT,
    activo INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (expediente_id) REFERENCES expedientes(id) ON DELETE CASCADE,
    FOREIGN KEY (cliente_id) REFERENCES clientes(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS hojas_encargo (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    expediente_id INTEGER NOT NULL,
    cliente_id INTEGER NOT NULL,
    numero_hoja TEXT,
    fecha_firma TEXT,
    procedimiento TEXT,
    importe_bruto REAL NOT NULL DEFAULT 0,
    descuento_manual REAL NOT NULL DEFAULT 0,
    descuento_consultas_previas REAL NOT NULL DEFAULT 0,
    importe_neto REAL NOT NULL DEFAULT 0,
    forma_pago_pactada TEXT,
    numero_plazos INTEGER DEFAULT 1,
    fecha_maxima_pago TEXT,
    documento_ruta TEXT,
    estado_firma TEXT NOT NULL DEFAULT 'PENDIENTE FIRMA',
    observaciones TEXT,
    activo INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (expediente_id) REFERENCES expedientes(id) ON DELETE CASCADE,
    FOREIGN KEY (cliente_id) REFERENCES clientes(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS consultas_previas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_id INTEGER NOT NULL,
    fecha_consulta TEXT NOT NULL,
    importe REAL NOT NULL DEFAULT 0,
    forma_pago TEXT,
    profesional_responsable TEXT,
    descontable INTEGER NOT NULL DEFAULT 1,
    estado TEXT NOT NULL DEFAULT 'DISPONIBLE',
    expediente_id_aplicado INTEGER,
    fecha_aplicacion TEXT,
    observaciones TEXT,
    activo INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (cliente_id) REFERENCES clientes(id) ON DELETE CASCADE,
    FOREIGN KEY (expediente_id_aplicado) REFERENCES expedientes(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS expediente_consultas_aplicadas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    expediente_id INTEGER NOT NULL,
    cliente_id INTEGER NOT NULL,
    consulta_previa_id INTEGER NOT NULL,
    hoja_encargo_id INTEGER,
    importe_aplicado REAL NOT NULL DEFAULT 0,
    fecha_aplicacion TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    observaciones TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (expediente_id) REFERENCES expedientes(id) ON DELETE CASCADE,
    FOREIGN KEY (cliente_id) REFERENCES clientes(id) ON DELETE CASCADE,
    FOREIGN KEY (consulta_previa_id) REFERENCES consultas_previas(id) ON DELETE CASCADE,
    FOREIGN KEY (hoja_encargo_id) REFERENCES hojas_encargo(id) ON DELETE SET NULL,
    UNIQUE(expediente_id, consulta_previa_id)
);

CREATE INDEX IF NOT EXISTS idx_eventos_expediente ON expediente_eventos(expediente_id);
CREATE INDEX IF NOT EXISTS idx_justificantes_expediente ON expediente_justificantes(expediente_id);
CREATE INDEX IF NOT EXISTS idx_hojas_expediente ON hojas_encargo(expediente_id);
CREATE INDEX IF NOT EXISTS idx_consultas_cliente ON consultas_previas(cliente_id);
CREATE INDEX IF NOT EXISTS idx_consultas_aplicadas_expediente ON expediente_consultas_aplicadas(expediente_id);
