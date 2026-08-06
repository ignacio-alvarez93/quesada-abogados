PRAGMA foreign_keys = ON;

-- Primera cadena funcional real:
-- Reagrupación familiar concedida
-- → propuesta de visado de reagrupación familiar.

INSERT INTO config_familias_expediente (
    codigo,
    nombre,
    descripcion,
    notification_workflow_code,
    orden,
    activo
)
SELECT
    'TRAMITES_CONSULARES',
    'TRÁMITES CONSULARES',
    (
        'Procedimientos tramitados ante consulados, '
        || 'oficinas consulares y proveedores externos '
        || 'de servicios consulares.'
    ),
    'RESOLUCION_DIRECTA',
    70,
    1
WHERE NOT EXISTS (
    SELECT 1
    FROM config_familias_expediente
    WHERE codigo = 'TRAMITES_CONSULARES'
);

UPDATE config_familias_expediente
SET
    nombre = 'TRÁMITES CONSULARES',
    descripcion = (
        'Procedimientos tramitados ante consulados, '
        || 'oficinas consulares y proveedores externos '
        || 'de servicios consulares.'
    ),
    notification_workflow_code = 'RESOLUCION_DIRECTA',
    activo = 1,
    updated_at = CURRENT_TIMESTAMP
WHERE codigo = 'TRAMITES_CONSULARES';


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
    'VISADO_REAGRUPACION_FAMILIAR',
    'VISADO DE REAGRUPACIÓN FAMILIAR',
    (
        'Solicitud y seguimiento del visado consular '
        || 'posterior a la concesión de una autorización '
        || 'de reagrupación familiar.'
    ),
    1,
    NULL,
    'TRAMITES_CONSULARES',
    f.id
FROM config_familias_expediente f
WHERE f.codigo = 'TRAMITES_CONSULARES'
  AND NOT EXISTS (
      SELECT 1
      FROM config_tipos_expediente t
      WHERE t.codigo = 'VISADO_REAGRUPACION_FAMILIAR'
  );

UPDATE config_tipos_expediente
SET
    nombre = 'VISADO DE REAGRUPACIÓN FAMILIAR',
    descripcion = (
        'Solicitud y seguimiento del visado consular '
        || 'posterior a la concesión de una autorización '
        || 'de reagrupación familiar.'
    ),
    activo = 1,
    workflow_code = 'TRAMITES_CONSULARES',
    familia_id = (
        SELECT id
        FROM config_familias_expediente
        WHERE codigo = 'TRAMITES_CONSULARES'
    ),
    updated_at = CURRENT_TIMESTAMP
WHERE codigo = 'VISADO_REAGRUPACION_FAMILIAR';


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
    'REAGRUPACION_CONCEDIDA_A_VISADO',
    (
        'Reagrupación familiar concedida '
        || 'a visado consular'
    ),
    fo.id,
    torigen.id,
    sorigen.id,
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
    10,
    1,
    (
        'Genera una propuesta revisable. '
        || 'No crea automáticamente el expediente de visado.'
    )
FROM config_familias_expediente fo
JOIN config_tipos_expediente torigen
  ON torigen.familia_id = fo.id
JOIN config_subtipos_expediente sorigen
  ON sorigen.tipo_expediente_id = torigen.id
JOIN config_familias_expediente fd
  ON fd.codigo = 'TRAMITES_CONSULARES'
JOIN config_tipos_expediente tdestino
  ON tdestino.familia_id = fd.id
WHERE fo.codigo = 'EXTRANJERIA'
  AND torigen.codigo = 'REAGRUPACION_FAMILIAR'
  AND sorigen.codigo = 'INICIAL'
  AND tdestino.codigo =
      'VISADO_REAGRUPACION_FAMILIAR'
  AND NOT EXISTS (
      SELECT 1
      FROM config_reglas_expediente_derivado r
      WHERE r.codigo =
          'REAGRUPACION_CONCEDIDA_A_VISADO'
  );

UPDATE config_reglas_expediente_derivado
SET
    nombre = (
        'Reagrupación familiar concedida '
        || 'a visado consular'
    ),
    familia_origen_id = (
        SELECT id
        FROM config_familias_expediente
        WHERE codigo = 'EXTRANJERIA'
    ),
    tipo_expediente_origen_id = (
        SELECT id
        FROM config_tipos_expediente
        WHERE codigo = 'REAGRUPACION_FAMILIAR'
    ),
    subtipo_expediente_origen_id = (
        SELECT s.id
        FROM config_subtipos_expediente s
        JOIN config_tipos_expediente t
          ON t.id = s.tipo_expediente_id
        WHERE t.codigo = 'REAGRUPACION_FAMILIAR'
          AND s.codigo = 'INICIAL'
    ),
    evento_disparador = 'RESOLUCION_FAVORABLE',
    resultado_requerido = 'CONCEDIDO',
    familia_destino_id = (
        SELECT id
        FROM config_familias_expediente
        WHERE codigo = 'TRAMITES_CONSULARES'
    ),
    tipo_expediente_destino_id = (
        SELECT id
        FROM config_tipos_expediente
        WHERE codigo =
            'VISADO_REAGRUPACION_FAMILIAR'
    ),
    subtipo_expediente_destino_id = NULL,
    tipo_relacion = 'ACTUACION_POSTERIOR',
    obligatorio = 0,
    creacion_automatica = 0,
    requiere_revision_humana = 1,
    orden = 10,
    activo = 1,
    observaciones = (
        'Genera una propuesta revisable. '
        || 'No crea automáticamente el expediente de visado.'
    ),
    updated_at = CURRENT_TIMESTAMP
WHERE codigo = 'REAGRUPACION_CONCEDIDA_A_VISADO';
