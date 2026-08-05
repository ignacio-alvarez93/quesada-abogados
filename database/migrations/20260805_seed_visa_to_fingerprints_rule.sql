PRAGMA foreign_keys = ON;

-- Segunda cadena funcional real:
-- Visado de reagrupación familiar concedido
-- → propuesta de expediente de toma de huellas.
--
-- La toma de huellas pertenece funcionalmente a la familia
-- DOCUMENTACION_EXTRANJEROS, no a POLICIA_NACIONAL.

INSERT INTO config_familias_expediente (
    codigo,
    nombre,
    descripcion,
    notification_workflow_code,
    orden,
    activo
)
SELECT
    'DOCUMENTACION_EXTRANJEROS',
    'DOCUMENTACIÓN DE EXTRANJEROS',
    (
        'Actuaciones relativas a la documentación física '
        || 'y administrativa de personas extranjeras, '
        || 'incluidas toma de huellas, expedición, '
        || 'renovación y recogida de TIE.'
    ),
    'DOCUMENTACION_EXTRANJEROS',
    75,
    1
WHERE NOT EXISTS (
    SELECT 1
    FROM config_familias_expediente
    WHERE codigo = 'DOCUMENTACION_EXTRANJEROS'
);

UPDATE config_familias_expediente
SET
    nombre = 'DOCUMENTACIÓN DE EXTRANJEROS',
    descripcion = (
        'Actuaciones relativas a la documentación física '
        || 'y administrativa de personas extranjeras, '
        || 'incluidas toma de huellas, expedición, '
        || 'renovación y recogida de TIE.'
    ),
    notification_workflow_code =
        'DOCUMENTACION_EXTRANJEROS',
    orden = 75,
    activo = 1,
    updated_at = CURRENT_TIMESTAMP
WHERE codigo = 'DOCUMENTACION_EXTRANJEROS';


-- Si POLICIA_NACIONAL fue creada por una versión anterior de esta
-- migración, se conserva porque será una familia válida para otras
-- actuaciones, pero se elimina la atribución incorrecta de huellas/TIE.

UPDATE config_familias_expediente
SET
    descripcion = (
        'Actuaciones policiales específicas, incluidas '
        || 'solicitudes de acceso, rectificación o '
        || 'cancelación de antecedentes policiales.'
    ),
    notification_workflow_code = 'RESOLUCION_DIRECTA',
    orden = 80,
    updated_at = CURRENT_TIMESTAMP
WHERE codigo = 'POLICIA_NACIONAL';


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
    'TOMA_HUELLAS',
    'TOMA DE HUELLAS',
    (
        'Solicitud o búsqueda de cita, preparación '
        || 'documental, formularios, tasas y seguimiento '
        || 'de la toma de huellas para expedir la TIE.'
    ),
    1,
    NULL,
    'DOCUMENTACION_EXTRANJEROS',
    f.id
FROM config_familias_expediente f
WHERE f.codigo = 'DOCUMENTACION_EXTRANJEROS'
  AND NOT EXISTS (
      SELECT 1
      FROM config_tipos_expediente t
      WHERE t.codigo = 'TOMA_HUELLAS'
  );

UPDATE config_tipos_expediente
SET
    nombre = 'TOMA DE HUELLAS',
    descripcion = (
        'Solicitud o búsqueda de cita, preparación '
        || 'documental, formularios, tasas y seguimiento '
        || 'de la toma de huellas para expedir la TIE.'
    ),
    activo = 1,
    workflow_code = 'DOCUMENTACION_EXTRANJEROS',
    familia_id = (
        SELECT id
        FROM config_familias_expediente
        WHERE codigo = 'DOCUMENTACION_EXTRANJEROS'
    ),
    updated_at = CURRENT_TIMESTAMP
WHERE codigo = 'TOMA_HUELLAS';


INSERT INTO config_reglas_expediente_derivado (
    codigo,
    nombre,
    familia_origen_id,
    tipo_expediente_origen_id,
    subtipo_expediente_origen_id,
    evento_disparador,
    resultado_requerido,
    familia_destino_id,
    tipo_expediente_destino_id,
    subtipo_expediente_destino_id,
    tipo_relacion,
    obligatorio,
    creacion_automatica,
    requiere_revision_humana,
    plazo_dias,
    orden,
    activo,
    observaciones
)
SELECT
    'VISADO_REAGRUPACION_CONCEDIDO_A_HUELLAS',
    (
        'Visado de reagrupación concedido '
        || 'a toma de huellas'
    ),
    fo.id,
    torigen.id,
    NULL,
    'RESOLUCION_FAVORABLE',
    'CONCEDIDO',
    fd.id,
    tdestino.id,
    NULL,
    'ACTUACION_POSTERIOR',
    0,
    0,
    1,
    NULL,
    20,
    1,
    (
        'Genera una propuesta revisable de toma de huellas '
        || 'dentro de Documentación de Extranjeros. '
        || 'No crea automáticamente el expediente.'
    )
FROM config_familias_expediente fo
JOIN config_tipos_expediente torigen
  ON torigen.familia_id = fo.id
JOIN config_familias_expediente fd
  ON fd.codigo = 'DOCUMENTACION_EXTRANJEROS'
JOIN config_tipos_expediente tdestino
  ON tdestino.familia_id = fd.id
WHERE fo.codigo = 'TRAMITES_CONSULARES'
  AND torigen.codigo =
      'VISADO_REAGRUPACION_FAMILIAR'
  AND tdestino.codigo = 'TOMA_HUELLAS'
  AND NOT EXISTS (
      SELECT 1
      FROM config_reglas_expediente_derivado r
      WHERE r.codigo =
          'VISADO_REAGRUPACION_CONCEDIDO_A_HUELLAS'
  );

UPDATE config_reglas_expediente_derivado
SET
    nombre = (
        'Visado de reagrupación concedido '
        || 'a toma de huellas'
    ),
    familia_origen_id = (
        SELECT id
        FROM config_familias_expediente
        WHERE codigo = 'TRAMITES_CONSULARES'
    ),
    tipo_expediente_origen_id = (
        SELECT id
        FROM config_tipos_expediente
        WHERE codigo =
            'VISADO_REAGRUPACION_FAMILIAR'
    ),
    subtipo_expediente_origen_id = NULL,
    evento_disparador = 'RESOLUCION_FAVORABLE',
    resultado_requerido = 'CONCEDIDO',
    familia_destino_id = (
        SELECT id
        FROM config_familias_expediente
        WHERE codigo = 'DOCUMENTACION_EXTRANJEROS'
    ),
    tipo_expediente_destino_id = (
        SELECT id
        FROM config_tipos_expediente
        WHERE codigo = 'TOMA_HUELLAS'
    ),
    subtipo_expediente_destino_id = NULL,
    tipo_relacion = 'ACTUACION_POSTERIOR',
    obligatorio = 0,
    creacion_automatica = 0,
    requiere_revision_humana = 1,
    plazo_dias = NULL,
    orden = 20,
    activo = 1,
    observaciones = (
        'Genera una propuesta revisable de toma de huellas '
        || 'dentro de Documentación de Extranjeros. '
        || 'No crea automáticamente el expediente.'
    ),
    updated_at = CURRENT_TIMESTAMP
WHERE codigo =
    'VISADO_REAGRUPACION_CONCEDIDO_A_HUELLAS';
