PRAGMA foreign_keys = ON;

-- Familia:
-- Administración Local
--
-- Subfamilias visuales:
-- 1. Informes de vivienda
-- 2. Informes de integración
--
-- Trámites:
-- - Informe de vivienda adecuada
-- - Informe de integración social
-- - Informe de esfuerzo de integración


INSERT INTO config_familias_expediente (
    codigo,
    nombre,
    descripcion,
    notification_workflow_code,
    orden,
    activo
)
SELECT
    'ADMINISTRACION_LOCAL',
    'ADMINISTRACIÓN LOCAL',
    (
        'Solicitudes de informes emitidos por '
        || 'administraciones locales o autonómicas '
        || 'vinculados a procedimientos de extranjería.'
    ),
    'RESOLUCION_DIRECTA',
    90,
    1
WHERE NOT EXISTS (
    SELECT 1
    FROM config_familias_expediente
    WHERE codigo = 'ADMINISTRACION_LOCAL'
);

UPDATE config_familias_expediente
SET
    nombre = 'ADMINISTRACIÓN LOCAL',
    descripcion = (
        'Solicitudes de informes emitidos por '
        || 'administraciones locales o autonómicas '
        || 'vinculados a procedimientos de extranjería.'
    ),
    notification_workflow_code = 'RESOLUCION_DIRECTA',
    orden = 90,
    activo = 1,
    updated_at = CURRENT_TIMESTAMP
WHERE codigo = 'ADMINISTRACION_LOCAL';


INSERT INTO config_tipos_expediente (
    codigo,
    nombre,
    descripcion,
    activo,
    url_presentacion,
    workflow_code,
    familia_id
)
SELECT
    'INFORME_VIVIENDA_ADECUADA',
    'INFORME DE VIVIENDA ADECUADA',
    (
        'Solicitud y seguimiento del informe '
        || 'de adecuación de vivienda vinculado '
        || 'a procedimientos de extranjería.'
    ),
    1,
    NULL,
    'ADMINISTRACION_LOCAL',
    f.id
FROM config_familias_expediente f
WHERE f.codigo = 'ADMINISTRACION_LOCAL'
  AND NOT EXISTS (
      SELECT 1
      FROM config_tipos_expediente t
      WHERE t.codigo =
          'INFORME_VIVIENDA_ADECUADA'
  );

UPDATE config_tipos_expediente
SET
    nombre = 'INFORME DE VIVIENDA ADECUADA',
    descripcion = (
        'Solicitud y seguimiento del informe '
        || 'de adecuación de vivienda vinculado '
        || 'a procedimientos de extranjería.'
    ),
    activo = 1,
    url_presentacion = NULL,
    workflow_code = 'ADMINISTRACION_LOCAL',
    familia_id = (
        SELECT id
        FROM config_familias_expediente
        WHERE codigo = 'ADMINISTRACION_LOCAL'
    ),
    updated_at = CURRENT_TIMESTAMP
WHERE codigo = 'INFORME_VIVIENDA_ADECUADA';


INSERT INTO config_tipos_expediente (
    codigo,
    nombre,
    descripcion,
    activo,
    url_presentacion,
    workflow_code,
    familia_id
)
SELECT
    'INFORME_INTEGRACION_SOCIAL',
    'INFORME DE INTEGRACIÓN SOCIAL',
    (
        'Solicitud y seguimiento del informe '
        || 'de integración social vinculado '
        || 'a procedimientos de extranjería.'
    ),
    1,
    NULL,
    'ADMINISTRACION_LOCAL',
    f.id
FROM config_familias_expediente f
WHERE f.codigo = 'ADMINISTRACION_LOCAL'
  AND NOT EXISTS (
      SELECT 1
      FROM config_tipos_expediente t
      WHERE t.codigo =
          'INFORME_INTEGRACION_SOCIAL'
  );

UPDATE config_tipos_expediente
SET
    nombre = 'INFORME DE INTEGRACIÓN SOCIAL',
    descripcion = (
        'Solicitud y seguimiento del informe '
        || 'de integración social vinculado '
        || 'a procedimientos de extranjería.'
    ),
    activo = 1,
    url_presentacion = NULL,
    workflow_code = 'ADMINISTRACION_LOCAL',
    familia_id = (
        SELECT id
        FROM config_familias_expediente
        WHERE codigo = 'ADMINISTRACION_LOCAL'
    ),
    updated_at = CURRENT_TIMESTAMP
WHERE codigo = 'INFORME_INTEGRACION_SOCIAL';


INSERT INTO config_tipos_expediente (
    codigo,
    nombre,
    descripcion,
    activo,
    url_presentacion,
    workflow_code,
    familia_id
)
SELECT
    'INFORME_ESFUERZO_INTEGRACION',
    'INFORME DE ESFUERZO DE INTEGRACIÓN',
    (
        'Solicitud y seguimiento del informe '
        || 'de esfuerzo de integración vinculado '
        || 'a procedimientos de extranjería.'
    ),
    1,
    NULL,
    'ADMINISTRACION_LOCAL',
    f.id
FROM config_familias_expediente f
WHERE f.codigo = 'ADMINISTRACION_LOCAL'
  AND NOT EXISTS (
      SELECT 1
      FROM config_tipos_expediente t
      WHERE t.codigo =
          'INFORME_ESFUERZO_INTEGRACION'
  );

UPDATE config_tipos_expediente
SET
    nombre = 'INFORME DE ESFUERZO DE INTEGRACIÓN',
    descripcion = (
        'Solicitud y seguimiento del informe '
        || 'de esfuerzo de integración vinculado '
        || 'a procedimientos de extranjería.'
    ),
    activo = 1,
    url_presentacion = NULL,
    workflow_code = 'ADMINISTRACION_LOCAL',
    familia_id = (
        SELECT id
        FROM config_familias_expediente
        WHERE codigo = 'ADMINISTRACION_LOCAL'
    ),
    updated_at = CURRENT_TIMESTAMP
WHERE codigo = 'INFORME_ESFUERZO_INTEGRACION';
