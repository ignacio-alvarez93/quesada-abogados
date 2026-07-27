PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS config_familias_expediente (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT NOT NULL UNIQUE,
    nombre TEXT NOT NULL,
    descripcion TEXT,
    notification_workflow_code TEXT NOT NULL DEFAULT 'RESOLUCION_DIRECTA',
    orden INTEGER NOT NULL DEFAULT 0,
    activo INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO config_familias_expediente
(codigo, nombre, descripcion, notification_workflow_code, orden, activo)
VALUES
(
    'EXTRANJERIA',
    'EXTRANJERÍA',
    'Procedimientos administrativos de extranjería tramitados principalmente ante Oficinas de Extranjería.',
    'EXTRANJERIA_STANDARD',
    10,
    1
),
(
    'NACIONALIDAD',
    'NACIONALIDAD',
    'Procedimientos de adquisición, conservación, recuperación y opción de nacionalidad española.',
    'RESOLUCION_DIRECTA',
    20,
    1
),
(
    'VISADOS',
    'VISADOS',
    'Procedimientos de visado tramitados ante consulados y oficinas consulares.',
    'RESOLUCION_DIRECTA',
    30,
    1
),
(
    'UGE',
    'UNIDAD DE GRANDES EMPRESAS',
    'Procedimientos tramitados ante la Unidad de Grandes Empresas y Colectivos Estratégicos.',
    'RESOLUCION_DIRECTA',
    40,
    1
),
(
    'CANCELACION_ANTECEDENTES',
    'CANCELACIÓN DE ANTECEDENTES',
    'Procedimientos de cancelación de antecedentes penales o policiales.',
    'RESOLUCION_DIRECTA',
    50,
    1
),
(
    'ASILO',
    'ASILO Y PROTECCIÓN INTERNACIONAL',
    'Procedimientos de asilo, protección subsidiaria y protección internacional.',
    'RESOLUCION_DIRECTA',
    60,
    1
),
(
    'OTROS',
    'OTROS',
    'Familia residual para procedimientos todavía no clasificados.',
    'RESOLUCION_DIRECTA',
    999,
    1
);

-- La columna se añade mediante migración defensiva Python porque SQLite
-- no soporta ADD COLUMN IF NOT EXISTS de forma portable en este proyecto.
--
-- La asignación histórica se realiza en expedient_family_service:
-- NACIONALIDAD  -> familia NACIONALIDAD
-- EXTRANJERIA   -> familia EXTRANJERIA
-- resto         -> familia OTROS
