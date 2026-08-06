PRAGMA foreign_keys = ON;

-- ESTANCIA_REGULAR era demasiado genérica.
-- Se conserva inactiva para no romper referencias históricas.
UPDATE config_situaciones_administrativas
SET
    activo = 0,
    updated_at = CURRENT_TIMESTAMP
WHERE codigo = 'ESTANCIA_REGULAR';

-- El régimen comunitario es un régimen jurídico de la autorización,
-- no una situación administrativa autónoma del cliente.
UPDATE config_situaciones_administrativas
SET
    activo = 0,
    updated_at = CURRENT_TIMESTAMP
WHERE codigo = 'REGIMEN_COMUNITARIO';

INSERT OR IGNORE INTO config_situaciones_administrativas (
    codigo,
    nombre,
    descripcion,
    orden,
    activo
)
VALUES
(
    'ESTANCIA_CORTA_DURACION',
    'ESTANCIA DE CORTA DURACIÓN',
    'La persona se encuentra en España por un periodo de estancia de corta duración.',
    35,
    1
),
(
    'ESTANCIA_LARGA_DURACION',
    'ESTANCIA DE LARGA DURACIÓN',
    'La persona se encuentra en España bajo una autorización de estancia superior a noventa días.',
    40,
    1
);
