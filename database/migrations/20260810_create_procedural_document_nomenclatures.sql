PRAGMA foreign_keys = ON;

-- ============================================================
-- NOMENCLATURAS PROCEDIMENTALES TRANSVERSALES
-- ============================================================
--
-- Complementan las nomenclaturas específicas por tipo/subtipo.
--
-- No representan requisitos documentales del ciudadano.
-- Representan documentos producidos o recibidos durante
-- la tramitación administrativa de un expediente.
-- ============================================================

CREATE TABLE IF NOT EXISTS
config_nomenclaturas_procedimentales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    documento_catalogo_id INTEGER NOT NULL,

    patron_nombre TEXT NOT NULL,

    extension_permitida TEXT
        NOT NULL DEFAULT 'pdf,jpg,jpeg,png',

    prioridad INTEGER NOT NULL DEFAULT 100,
    activo INTEGER NOT NULL DEFAULT 1,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (documento_catalogo_id)
        REFERENCES config_documentos_catalogo(id),

    CHECK (TRIM(patron_nombre) <> ''),
    CHECK (prioridad >= 0),
    CHECK (activo IN (0, 1))
);


CREATE UNIQUE INDEX IF NOT EXISTS
idx_nomenclaturas_procedimentales_unique
ON config_nomenclaturas_procedimentales (
    documento_catalogo_id,
    UPPER(TRIM(patron_nombre)),
    LOWER(TRIM(extension_permitida))
);


CREATE INDEX IF NOT EXISTS
idx_nomenclaturas_procedimentales_documento
ON config_nomenclaturas_procedimentales (
    documento_catalogo_id,
    activo,
    prioridad
);


-- ============================================================
-- DOCUMENTOS CANÓNICOS PROCEDIMENTALES
-- ============================================================

INSERT OR IGNORE INTO config_documentos_catalogo (
    codigo,
    nombre,
    descripcion,
    categoria,
    activo
)
VALUES
(
    'ADMISION_TRAMITE',
    'ADMISIÓN A TRÁMITE',
    'Comunicación administrativa de admisión a trámite.',
    'TRAMITACION',
    1
);

INSERT OR IGNORE INTO config_documentos_catalogo (
    codigo,
    nombre,
    descripcion,
    categoria,
    activo
)
VALUES
(
    'ADMISION_TRAMITE_TASA',
    'ADMISIÓN A TRÁMITE Y TASA',
    'Comunicación de admisión a trámite que incorpora información o requerimiento relativo a tasa.',
    'TRAMITACION',
    1
);

INSERT OR IGNORE INTO config_documentos_catalogo (
    codigo,
    nombre,
    descripcion,
    categoria,
    activo
)
VALUES
(
    'TRAMITE_AUDIENCIA',
    'TRÁMITE DE AUDIENCIA',
    'Comunicación administrativa de apertura de trámite de audiencia.',
    'TRAMITACION',
    1
);

INSERT OR IGNORE INTO config_documentos_catalogo (
    codigo,
    nombre,
    descripcion,
    categoria,
    activo
)
VALUES
(
    'RESOLUCION_CONCESION',
    'RESOLUCIÓN DE CONCESIÓN',
    'Resolución administrativa favorable o de concesión.',
    'RESOLUCION',
    1
);

INSERT OR IGNORE INTO config_documentos_catalogo (
    codigo,
    nombre,
    descripcion,
    categoria,
    activo
)
VALUES
(
    'RESOLUCION_DENEGACION',
    'RESOLUCIÓN DE DENEGACIÓN',
    'Resolución administrativa desfavorable o denegatoria.',
    'RESOLUCION',
    1
);

INSERT OR IGNORE INTO config_documentos_catalogo (
    codigo,
    nombre,
    descripcion,
    categoria,
    activo
)
VALUES
(
    'INADMISION',
    'INADMISIÓN',
    'Resolución o comunicación administrativa de inadmisión.',
    'RESOLUCION',
    1
);

INSERT OR IGNORE INTO config_documentos_catalogo (
    codigo,
    nombre,
    descripcion,
    categoria,
    activo
)
VALUES
(
    'ARCHIVO',
    'ARCHIVO',
    'Resolución o comunicación administrativa de archivo del procedimiento.',
    'RESOLUCION',
    1
);


-- ============================================================
-- PATRONES PROCEDIMENTALES PRINCIPALES
-- ============================================================

INSERT OR IGNORE INTO config_nomenclaturas_procedimentales (
    documento_catalogo_id,
    patron_nombre,
    prioridad,
    activo
)
SELECT
    id,
    'ADMISION A TRAMITE',
    10,
    1
FROM config_documentos_catalogo
WHERE codigo = 'ADMISION_TRAMITE';


INSERT OR IGNORE INTO config_nomenclaturas_procedimentales (
    documento_catalogo_id,
    patron_nombre,
    prioridad,
    activo
)
SELECT
    id,
    'ADMISION A TRAMITE Y TASA',
    10,
    1
FROM config_documentos_catalogo
WHERE codigo = 'ADMISION_TRAMITE_TASA';


INSERT OR IGNORE INTO config_nomenclaturas_procedimentales (
    documento_catalogo_id,
    patron_nombre,
    prioridad,
    activo
)
SELECT
    id,
    'TRAMITE DE AUDIENCIA',
    10,
    1
FROM config_documentos_catalogo
WHERE codigo = 'TRAMITE_AUDIENCIA';


INSERT OR IGNORE INTO config_nomenclaturas_procedimentales (
    documento_catalogo_id,
    patron_nombre,
    prioridad,
    activo
)
SELECT
    id,
    'RESOLUCION DE CONCESION',
    10,
    1
FROM config_documentos_catalogo
WHERE codigo = 'RESOLUCION_CONCESION';


INSERT OR IGNORE INTO config_nomenclaturas_procedimentales (
    documento_catalogo_id,
    patron_nombre,
    prioridad,
    activo
)
SELECT
    id,
    'RESOLUCION DE DENEGACION',
    10,
    1
FROM config_documentos_catalogo
WHERE codigo = 'RESOLUCION_DENEGACION';


INSERT OR IGNORE INTO config_nomenclaturas_procedimentales (
    documento_catalogo_id,
    patron_nombre,
    prioridad,
    activo
)
SELECT
    id,
    'INADMISION',
    10,
    1
FROM config_documentos_catalogo
WHERE codigo = 'INADMISION';


INSERT OR IGNORE INTO config_nomenclaturas_procedimentales (
    documento_catalogo_id,
    patron_nombre,
    prioridad,
    activo
)
SELECT
    id,
    'ARCHIVO',
    10,
    1
FROM config_documentos_catalogo
WHERE codigo = 'ARCHIVO';
