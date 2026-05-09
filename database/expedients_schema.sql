-- database/expedients_schema.sql
-- Módulo Expedientes - Fase 1
-- Ejecutar una vez contra database/quesada.db

PRAGMA foreign_keys = ON;

-- Estados documentales específicos del expediente.
CREATE TABLE IF NOT EXISTS config_estados_documentales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT NOT NULL UNIQUE,
    nombre TEXT NOT NULL,
    color TEXT DEFAULT '#0057B8',
    orden INTEGER NOT NULL DEFAULT 0,
    activo INTEGER NOT NULL DEFAULT 1
);

-- Estados administrativos específicos del expediente.
CREATE TABLE IF NOT EXISTS config_estados_administrativos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT NOT NULL UNIQUE,
    nombre TEXT NOT NULL,
    color TEXT DEFAULT '#0057B8',
    orden INTEGER NOT NULL DEFAULT 0,
    activo INTEGER NOT NULL DEFAULT 1
);

-- Expedientes operativos.
-- tipo_expediente_id usa config_tipos_expediente ya creado por Configuración Operativa.
-- prioridad_id usa config_prioridades ya creado por Configuración Operativa.
CREATE TABLE IF NOT EXISTS expedientes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    cliente_id INTEGER NOT NULL,

    numero_expediente TEXT NOT NULL UNIQUE,
    tipo_expediente_id INTEGER,
    subtipo_expediente TEXT,

    estado_documental_id INTEGER,
    estado_administrativo_id INTEGER,
    estado_presentacion TEXT DEFAULT 'NO PRESENTADO',

    prioridad_id INTEGER,

    responsable TEXT,

    fecha_apertura TEXT,
    fecha_presentacion TEXT,
    fecha_resolucion TEXT,

    numero_registro TEXT,
    organo_presentacion TEXT,
    provincia TEXT,

    observaciones TEXT,
    observaciones_internas TEXT,

    -- Preparado para futura integración Box.
    -- En fase 1 no se observa ni manipula Box.
    box_folder_path TEXT,

    activo INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (cliente_id) REFERENCES clientes(id) ON DELETE CASCADE,
    FOREIGN KEY (tipo_expediente_id) REFERENCES config_tipos_expediente(id),
    FOREIGN KEY (estado_documental_id) REFERENCES config_estados_documentales(id),
    FOREIGN KEY (estado_administrativo_id) REFERENCES config_estados_administrativos(id),
    FOREIGN KEY (prioridad_id) REFERENCES config_prioridades(id)
);

CREATE INDEX IF NOT EXISTS idx_expedientes_cliente ON expedientes(cliente_id);
CREATE INDEX IF NOT EXISTS idx_expedientes_tipo ON expedientes(tipo_expediente_id);
CREATE INDEX IF NOT EXISTS idx_expedientes_documental ON expedientes(estado_documental_id);
CREATE INDEX IF NOT EXISTS idx_expedientes_administrativo ON expedientes(estado_administrativo_id);
CREATE INDEX IF NOT EXISTS idx_expedientes_prioridad ON expedientes(prioridad_id);
CREATE INDEX IF NOT EXISTS idx_expedientes_activo ON expedientes(activo);
