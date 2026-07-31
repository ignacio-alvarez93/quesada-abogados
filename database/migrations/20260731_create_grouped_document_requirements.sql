PRAGMA foreign_keys = ON;

-- ============================================================
-- CATÁLOGO DOCUMENTAL CANÓNICO
-- ============================================================
--
-- Define documentos reutilizables con independencia del
-- procedimiento en el que posteriormente sean exigidos.
--
-- Ejemplos:
--   PASAPORTE
--   CERTIFICADO_MATRIMONIO
--   CERTIFICADO_NACIMIENTO
--   INFORME_VIVIENDA

CREATE TABLE IF NOT EXISTS config_documentos_catalogo (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT NOT NULL UNIQUE,
    nombre TEXT NOT NULL,
    descripcion TEXT,
    categoria TEXT,
    activo INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CHECK (TRIM(codigo) <> ''),
    CHECK (TRIM(nombre) <> ''),
    CHECK (activo IN (0, 1))
);


-- ============================================================
-- GRUPOS DE REQUISITOS DOCUMENTALES
-- ============================================================
--
-- Representan qué debe acreditarse en un tipo/subtipo.
--
-- Reglas:
--   ALL       -> deben aportarse todas las opciones.
--   ANY       -> basta cualquiera de las opciones.
--   AT_LEAST  -> deben aportarse al menos N opciones.
--   OPTIONAL  -> el grupo no impide completar documentación.

CREATE TABLE IF NOT EXISTS config_grupos_requisitos_documentales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo_expediente_id INTEGER NOT NULL,
    subtipo_expediente_id INTEGER,
    codigo TEXT NOT NULL,
    nombre TEXT NOT NULL,
    descripcion TEXT,
    regla_cumplimiento TEXT NOT NULL DEFAULT 'ALL',
    minimo_documentos INTEGER NOT NULL DEFAULT 1,
    orden INTEGER NOT NULL DEFAULT 0,
    activo INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (tipo_expediente_id)
        REFERENCES config_tipos_expediente(id),

    FOREIGN KEY (subtipo_expediente_id)
        REFERENCES config_subtipos_expediente(id),

    CHECK (
        regla_cumplimiento IN (
            'ALL',
            'ANY',
            'AT_LEAST',
            'OPTIONAL'
        )
    ),

    CHECK (minimo_documentos >= 0),
    CHECK (TRIM(codigo) <> ''),
    CHECK (TRIM(nombre) <> ''),
    CHECK (activo IN (0, 1))
);


-- Un código de grupo no puede repetirse dentro del mismo tipo
-- cuando se trata de una configuración general sin subtipo.
CREATE UNIQUE INDEX IF NOT EXISTS
idx_grupo_requisito_codigo_general
ON config_grupos_requisitos_documentales (
    tipo_expediente_id,
    codigo
)
WHERE subtipo_expediente_id IS NULL;


-- Un código de grupo no puede repetirse dentro del mismo subtipo.
CREATE UNIQUE INDEX IF NOT EXISTS
idx_grupo_requisito_codigo_subtipo
ON config_grupos_requisitos_documentales (
    tipo_expediente_id,
    subtipo_expediente_id,
    codigo
)
WHERE subtipo_expediente_id IS NOT NULL;


CREATE INDEX IF NOT EXISTS
idx_grupos_requisitos_tipo_subtipo
ON config_grupos_requisitos_documentales (
    tipo_expediente_id,
    subtipo_expediente_id,
    activo,
    orden
);


-- ============================================================
-- DOCUMENTOS ADMITIDOS POR GRUPO
-- ============================================================
--
-- Relaciona cada grupo con los documentos canónicos que pueden
-- satisfacerlo.

CREATE TABLE IF NOT EXISTS config_grupo_requisito_documentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    grupo_id INTEGER NOT NULL,
    documento_catalogo_id INTEGER NOT NULL,
    orden INTEGER NOT NULL DEFAULT 0,
    activo INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (grupo_id)
        REFERENCES config_grupos_requisitos_documentales(id)
        ON DELETE CASCADE,

    FOREIGN KEY (documento_catalogo_id)
        REFERENCES config_documentos_catalogo(id),

    UNIQUE (grupo_id, documento_catalogo_id),
    CHECK (activo IN (0, 1))
);


CREATE INDEX IF NOT EXISTS
idx_grupo_requisito_documentos_grupo
ON config_grupo_requisito_documentos (
    grupo_id,
    activo,
    orden
);


CREATE INDEX IF NOT EXISTS
idx_grupo_requisito_documentos_catalogo
ON config_grupo_requisito_documentos (
    documento_catalogo_id
);
