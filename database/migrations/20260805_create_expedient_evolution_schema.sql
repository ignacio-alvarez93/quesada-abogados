PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS expediente_relaciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    expediente_origen_id INTEGER NOT NULL,
    expediente_destino_id INTEGER NOT NULL,
    tipo_relacion TEXT NOT NULL,
    regla_origen_id INTEGER,
    creado_automaticamente INTEGER NOT NULL DEFAULT 0,
    estado TEXT NOT NULL DEFAULT 'ACTIVA',
    motivo TEXT,
    created_by TEXT,
    activo INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (expediente_origen_id)
        REFERENCES expedientes(id)
        ON DELETE CASCADE,
    FOREIGN KEY (expediente_destino_id)
        REFERENCES expedientes(id)
        ON DELETE CASCADE,
    CHECK (expediente_origen_id <> expediente_destino_id),
    UNIQUE (
        expediente_origen_id,
        expediente_destino_id,
        tipo_relacion
    )
);

CREATE INDEX IF NOT EXISTS idx_expediente_relaciones_origen
ON expediente_relaciones(
    expediente_origen_id,
    activo,
    tipo_relacion
);

CREATE INDEX IF NOT EXISTS idx_expediente_relaciones_destino
ON expediente_relaciones(
    expediente_destino_id,
    activo,
    tipo_relacion
);

CREATE TABLE IF NOT EXISTS config_transiciones_autorizacion (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT NOT NULL UNIQUE,
    nombre TEXT NOT NULL,
    autorizacion_origen_id INTEGER,
    familia_destino_id INTEGER NOT NULL,
    tipo_expediente_destino_id INTEGER NOT NULL,
    subtipo_expediente_destino_id INTEGER,
    autorizacion_resultado_id INTEGER,
    tipo_transicion TEXT NOT NULL,
    requiere_resolucion_favorable INTEGER NOT NULL DEFAULT 1,
    requiere_autorizacion_vigente INTEGER NOT NULL DEFAULT 0,
    requiere_cliente_en_espana INTEGER NOT NULL DEFAULT 0,
    requiere_cliente_en_origen INTEGER NOT NULL DEFAULT 0,
    ventana_inicio_dias INTEGER,
    ventana_fin_dias INTEGER,
    base_normativa TEXT,
    articulo_normativo TEXT,
    fecha_vigencia_desde TEXT,
    fecha_vigencia_hasta TEXT,
    orden INTEGER NOT NULL DEFAULT 0,
    activo INTEGER NOT NULL DEFAULT 1,
    observaciones TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (autorizacion_origen_id)
        REFERENCES config_tipos_autorizacion(id),
    FOREIGN KEY (familia_destino_id)
        REFERENCES config_familias_expediente(id),
    FOREIGN KEY (tipo_expediente_destino_id)
        REFERENCES config_tipos_expediente(id),
    FOREIGN KEY (subtipo_expediente_destino_id)
        REFERENCES config_subtipos_expediente(id),
    FOREIGN KEY (autorizacion_resultado_id)
        REFERENCES config_tipos_autorizacion(id)
);

CREATE INDEX IF NOT EXISTS idx_transiciones_autorizacion_origen
ON config_transiciones_autorizacion(
    autorizacion_origen_id,
    activo
);

CREATE INDEX IF NOT EXISTS idx_transiciones_tipo_destino
ON config_transiciones_autorizacion(
    tipo_expediente_destino_id,
    subtipo_expediente_destino_id,
    activo
);

CREATE TABLE IF NOT EXISTS config_reglas_expediente_derivado (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT NOT NULL UNIQUE,
    nombre TEXT NOT NULL,
    familia_origen_id INTEGER,
    tipo_expediente_origen_id INTEGER,
    subtipo_expediente_origen_id INTEGER,
    evento_disparador TEXT NOT NULL,
    resultado_requerido TEXT,
    familia_destino_id INTEGER NOT NULL,
    tipo_expediente_destino_id INTEGER NOT NULL,
    subtipo_expediente_destino_id INTEGER,
    tipo_relacion TEXT NOT NULL DEFAULT 'ACTUACION_POSTERIOR',
    obligatorio INTEGER NOT NULL DEFAULT 0,
    creacion_automatica INTEGER NOT NULL DEFAULT 0,
    requiere_revision_humana INTEGER NOT NULL DEFAULT 1,
    plazo_dias INTEGER,
    orden INTEGER NOT NULL DEFAULT 0,
    activo INTEGER NOT NULL DEFAULT 1,
    observaciones TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (familia_origen_id)
        REFERENCES config_familias_expediente(id),
    FOREIGN KEY (tipo_expediente_origen_id)
        REFERENCES config_tipos_expediente(id),
    FOREIGN KEY (subtipo_expediente_origen_id)
        REFERENCES config_subtipos_expediente(id),
    FOREIGN KEY (familia_destino_id)
        REFERENCES config_familias_expediente(id),
    FOREIGN KEY (tipo_expediente_destino_id)
        REFERENCES config_tipos_expediente(id),
    FOREIGN KEY (subtipo_expediente_destino_id)
        REFERENCES config_subtipos_expediente(id)
);

CREATE INDEX IF NOT EXISTS idx_reglas_derivacion_origen
ON config_reglas_expediente_derivado(
    tipo_expediente_origen_id,
    subtipo_expediente_origen_id,
    evento_disparador,
    activo
);

CREATE INDEX IF NOT EXISTS idx_reglas_derivacion_destino
ON config_reglas_expediente_derivado(
    tipo_expediente_destino_id,
    subtipo_expediente_destino_id,
    activo
);

CREATE TABLE IF NOT EXISTS expediente_derivacion_propuestas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    expediente_origen_id INTEGER NOT NULL,
    regla_derivacion_id INTEGER NOT NULL,
    cliente_id INTEGER NOT NULL,
    familia_destino_id INTEGER NOT NULL,
    tipo_expediente_destino_id INTEGER NOT NULL,
    subtipo_expediente_destino_id INTEGER,
    estado TEXT NOT NULL DEFAULT 'PENDIENTE',
    expediente_destino_id INTEGER,
    motivo TEXT,
    datos_propuestos_json TEXT,
    detectada_por_evento TEXT,
    detectada_automaticamente INTEGER NOT NULL DEFAULT 1,
    revisada_por TEXT,
    revisada_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (expediente_origen_id)
        REFERENCES expedientes(id)
        ON DELETE CASCADE,
    FOREIGN KEY (regla_derivacion_id)
        REFERENCES config_reglas_expediente_derivado(id),
    FOREIGN KEY (cliente_id)
        REFERENCES clientes(id)
        ON DELETE CASCADE,
    FOREIGN KEY (familia_destino_id)
        REFERENCES config_familias_expediente(id),
    FOREIGN KEY (tipo_expediente_destino_id)
        REFERENCES config_tipos_expediente(id),
    FOREIGN KEY (subtipo_expediente_destino_id)
        REFERENCES config_subtipos_expediente(id),
    FOREIGN KEY (expediente_destino_id)
        REFERENCES expedientes(id),
    UNIQUE (
        expediente_origen_id,
        regla_derivacion_id
    )
);

CREATE INDEX IF NOT EXISTS idx_derivacion_propuestas_estado
ON expediente_derivacion_propuestas(
    estado,
    created_at
);

CREATE INDEX IF NOT EXISTS idx_derivacion_propuestas_cliente
ON expediente_derivacion_propuestas(
    cliente_id,
    estado
);
