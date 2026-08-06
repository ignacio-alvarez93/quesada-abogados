PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS config_situaciones_administrativas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT NOT NULL UNIQUE,
    nombre TEXT NOT NULL,
    descripcion TEXT,
    orden INTEGER NOT NULL DEFAULT 0,
    activo INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS config_tipos_autorizacion (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT NOT NULL UNIQUE,
    nombre TEXT NOT NULL,
    familia_codigo TEXT NOT NULL,
    regimen_juridico TEXT,
    categoria TEXT,
    modalidad TEXT,
    norma_principal TEXT,
    articulo_normativo TEXT,
    organismo_tramitador TEXT,
    habilita_trabajo INTEGER NOT NULL DEFAULT 0,
    tipo_habilitacion_laboral TEXT,
    duracion_ordinaria_meses INTEGER,
    caracter_indefinido INTEGER NOT NULL DEFAULT 0,
    admite_inicial INTEGER NOT NULL DEFAULT 1,
    admite_renovacion INTEGER NOT NULL DEFAULT 0,
    admite_modificacion INTEGER NOT NULL DEFAULT 0,
    admite_familiares INTEGER NOT NULL DEFAULT 0,
    admite_nuevas_solicitudes INTEGER NOT NULL DEFAULT 1,
    fecha_vigencia_desde TEXT,
    fecha_vigencia_hasta TEXT,
    estado_catalogo TEXT NOT NULL DEFAULT 'VIGENTE',
    orden INTEGER NOT NULL DEFAULT 0,
    activo INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cliente_autorizaciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_id INTEGER NOT NULL,
    situacion_administrativa_id INTEGER,
    tipo_autorizacion_id INTEGER,
    estado_autorizacion TEXT NOT NULL DEFAULT 'VIGENTE',
    fecha_solicitud TEXT,
    fecha_presentacion TEXT,
    fecha_concesion TEXT,
    fecha_notificacion TEXT,
    fecha_vigencia_desde TEXT,
    fecha_vigencia_hasta TEXT,
    numero_expediente_administrativo TEXT,
    organismo_concedente TEXT,
    provincia TEXT,
    expediente_origen_id INTEGER,
    documento_origen_id INTEGER,
    motivo_inicio TEXT,
    motivo_fin TEXT,
    es_actual INTEGER NOT NULL DEFAULT 0,
    activo INTEGER NOT NULL DEFAULT 1,
    observaciones TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (cliente_id)
        REFERENCES clientes(id)
        ON DELETE CASCADE,
    FOREIGN KEY (situacion_administrativa_id)
        REFERENCES config_situaciones_administrativas(id),
    FOREIGN KEY (tipo_autorizacion_id)
        REFERENCES config_tipos_autorizacion(id),
    FOREIGN KEY (expediente_origen_id)
        REFERENCES expedientes(id)
);

CREATE INDEX IF NOT EXISTS idx_cliente_autorizaciones_cliente
ON cliente_autorizaciones(cliente_id, activo);

CREATE INDEX IF NOT EXISTS idx_cliente_autorizaciones_tipo
ON cliente_autorizaciones(tipo_autorizacion_id, activo);

CREATE INDEX IF NOT EXISTS idx_cliente_autorizaciones_expediente
ON cliente_autorizaciones(expediente_origen_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_cliente_autorizacion_actual
ON cliente_autorizaciones(cliente_id)
WHERE es_actual = 1 AND activo = 1;

INSERT OR IGNORE INTO config_situaciones_administrativas
(codigo, nombre, descripcion, orden, activo)
VALUES
('NO_APLICA', 'NO APLICA', 'La situación administrativa en España no resulta aplicable.', 10, 1),
('EN_ORIGEN', 'EN PAÍS DE ORIGEN', 'La persona se encuentra en su país de origen.', 20, 1),
('NO_HA_ENTRADO_EN_ESPANA', 'NO HA ENTRADO EN ESPAÑA', 'No consta entrada previa en España.', 30, 1),
('ESTANCIA_REGULAR', 'ESTANCIA REGULAR', 'La persona se encuentra en situación de estancia regular.', 40, 1),
('RESIDENCIA_TEMPORAL', 'RESIDENCIA TEMPORAL', 'La persona es titular de residencia temporal.', 50, 1),
('RESIDENCIA_LARGA_DURACION', 'RESIDENCIA DE LARGA DURACIÓN', 'La persona es titular de residencia de larga duración.', 60, 1),
('REGIMEN_COMUNITARIO', 'RÉGIMEN COMUNITARIO', 'La persona está sometida al régimen de ciudadanos de la Unión o sus familiares.', 70, 1),
('CIUDADANO_UE', 'CIUDADANO DE LA UNIÓN', 'Ciudadano de la Unión Europea, EEE o Suiza.', 80, 1),
('SOLICITANTE_PROTECCION_INTERNACIONAL', 'SOLICITANTE DE PROTECCIÓN INTERNACIONAL', 'Solicitud de protección internacional en tramitación.', 90, 1),
('PROTECCION_TEMPORAL', 'PROTECCIÓN TEMPORAL', 'Persona beneficiaria de protección temporal.', 100, 1),
('SITUACION_IRREGULAR', 'SITUACIÓN IRREGULAR', 'No dispone de autorización vigente conocida.', 110, 1),
('AUTORIZACION_EN_RENOVACION', 'AUTORIZACIÓN EN RENOVACIÓN', 'La autorización anterior se encuentra en proceso de renovación.', 120, 1),
('AUTORIZACION_CADUCADA', 'AUTORIZACIÓN CADUCADA', 'La autorización ha perdido vigencia.', 130, 1),
('CIUDADANO_ESPANOL', 'CIUDADANO ESPAÑOL', 'Persona de nacionalidad española.', 140, 1),
('NACIONALIZADO_ESPANOL', 'NACIONALIZADO ESPAÑOL', 'Persona que ha adquirido la nacionalidad española.', 150, 1),
('DESCONOCIDA', 'SITUACIÓN DESCONOCIDA', 'No existe información suficiente para determinar la situación.', 999, 1);
