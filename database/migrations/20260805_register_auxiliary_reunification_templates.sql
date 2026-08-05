-- Registra las plantillas PDF auxiliares de Reagrupación.
-- Son documentos generables, pero no compiten con EX02
-- como mapper PDF principal del tipo de expediente 14.

BEGIN;

INSERT INTO form_mapper_templates (
    codigo,
    nombre,
    tipo_destino,
    activo,
    tipo_expediente_id,
    subtipo_expediente_id,
    mapper_json,
    required_fields_json,
    version,
    created_at,
    updated_at
)
SELECT
    'DEC_CONYUGE',
    'DECLARACION CONYUGE',
    'PDF',
    1,
    NULL,
    NULL,
    '{

  "Texto1": "datos_especificos.reagrupante_nombre",

  "Texto3": "datos_especificos.reagrupante_primer_apellido",

  "Texto2": "datos_especificos.reagrupante_segundo_apellido",



  "Texto5": "datos_especificos.reagrupante_nie",

  "Texto6": "datos_especificos.reagrupante_pasaporte",



  "Texto7": "__slice__:datos_especificos.reagrupante_fecha_nacimiento:8:10",

  "Texto8": "__slice__:datos_especificos.reagrupante_fecha_nacimiento:5:7",

  "Texto9": "__slice__:datos_especificos.reagrupante_fecha_nacimiento:0:4",



  "Texto10": "datos_especificos.reagrupante_localidad_nacimiento",

  "Texto11": "datos_especificos.reagrupante_pais_nacimiento",

  "Texto4": "datos_especificos.reagrupante_nacionalidad",



  "Casilla de verificación27": "__equals__:datos_especificos.reagrupante_estado_civil:SOLTERO/A",

  "Casilla de verificación28": "__equals__:datos_especificos.reagrupante_estado_civil:CASADO/A",

  "Casilla de verificación29": "__equals__:datos_especificos.reagrupante_estado_civil:VIUDO/A",

  "Casilla de verificación30": "__equals__:datos_especificos.reagrupante_estado_civil:DIVORCIADO/A",

  "Casilla de verificación31": "__equals__:datos_especificos.reagrupante_estado_civil:SEPARADO/A",



  "Texto12": "datos_especificos.reagrupante_nombre_padre",

  "Texto13": "datos_especificos.reagrupante_nombre_madre",



  "Texto14": "__join__: :datos_especificos.reagrupante_tipo_via:datos_especificos.reagrupante_nombre_via",

  "Texto15": "datos_especificos.reagrupante_numero",

  "Texto16": "datos_especificos.reagrupante_piso",

  "Texto17": "datos_especificos.reagrupante_localidad",

  "Texto18": "datos_especificos.reagrupante_codigo_postal",

  "Texto19": "datos_especificos.reagrupante_provincia",



  "Texto20": "datos_especificos.reagrupante_telefono",

  "Texto21": "datos_especificos.reagrupante_email",



  "Texto22": "__static__:EN OVIEDO",

  "Texto23": "__today__:%d",

  "Texto24": "__today__:%m",

  "Texto25": "__today__:%Y"

}',
    '[]',
    1,
    CURRENT_TIMESTAMP,
    CURRENT_TIMESTAMP
WHERE NOT EXISTS (
    SELECT 1
    FROM form_mapper_templates
    WHERE codigo = 'DEC_CONYUGE'
);

UPDATE form_mapper_templates
SET
    nombre = 'DECLARACION CONYUGE',
    tipo_destino = 'PDF',
    activo = 1,
    tipo_expediente_id = NULL,
    subtipo_expediente_id = NULL,
    mapper_json = '{

  "Texto1": "datos_especificos.reagrupante_nombre",

  "Texto3": "datos_especificos.reagrupante_primer_apellido",

  "Texto2": "datos_especificos.reagrupante_segundo_apellido",



  "Texto5": "datos_especificos.reagrupante_nie",

  "Texto6": "datos_especificos.reagrupante_pasaporte",



  "Texto7": "__slice__:datos_especificos.reagrupante_fecha_nacimiento:8:10",

  "Texto8": "__slice__:datos_especificos.reagrupante_fecha_nacimiento:5:7",

  "Texto9": "__slice__:datos_especificos.reagrupante_fecha_nacimiento:0:4",



  "Texto10": "datos_especificos.reagrupante_localidad_nacimiento",

  "Texto11": "datos_especificos.reagrupante_pais_nacimiento",

  "Texto4": "datos_especificos.reagrupante_nacionalidad",



  "Casilla de verificación27": "__equals__:datos_especificos.reagrupante_estado_civil:SOLTERO/A",

  "Casilla de verificación28": "__equals__:datos_especificos.reagrupante_estado_civil:CASADO/A",

  "Casilla de verificación29": "__equals__:datos_especificos.reagrupante_estado_civil:VIUDO/A",

  "Casilla de verificación30": "__equals__:datos_especificos.reagrupante_estado_civil:DIVORCIADO/A",

  "Casilla de verificación31": "__equals__:datos_especificos.reagrupante_estado_civil:SEPARADO/A",



  "Texto12": "datos_especificos.reagrupante_nombre_padre",

  "Texto13": "datos_especificos.reagrupante_nombre_madre",



  "Texto14": "__join__: :datos_especificos.reagrupante_tipo_via:datos_especificos.reagrupante_nombre_via",

  "Texto15": "datos_especificos.reagrupante_numero",

  "Texto16": "datos_especificos.reagrupante_piso",

  "Texto17": "datos_especificos.reagrupante_localidad",

  "Texto18": "datos_especificos.reagrupante_codigo_postal",

  "Texto19": "datos_especificos.reagrupante_provincia",



  "Texto20": "datos_especificos.reagrupante_telefono",

  "Texto21": "datos_especificos.reagrupante_email",



  "Texto22": "__static__:EN OVIEDO",

  "Texto23": "__today__:%d",

  "Texto24": "__today__:%m",

  "Texto25": "__today__:%Y"

}',
    required_fields_json = '[]',
    version = 1,
    updated_at = CURRENT_TIMESTAMP
WHERE codigo = 'DEC_CONYUGE';

INSERT INTO form_mapper_templates (
    codigo,
    nombre,
    tipo_destino,
    activo,
    tipo_expediente_id,
    subtipo_expediente_id,
    mapper_json,
    required_fields_json,
    version,
    created_at,
    updated_at
)
SELECT
    'DESIG_REAGRUPANTE',
    'DESIGNACION REPRESENTANTE REAGRUPANTE',
    'PDF',
    1,
    NULL,
    NULL,
    '{

  "Texto1": "datos_especificos.reagrupante_nombre",

  "Texto2": "datos_especificos.reagrupante_primer_apellido",

  "Texto3": "datos_especificos.reagrupante_segundo_apellido",

  "Texto4": "datos_especificos.reagrupante_nacionalidad",

  "Texto5": "datos_especificos.reagrupante_nie",

  "Texto6": "datos_especificos.reagrupante_pasaporte",



  "Texto7": "__slice__:datos_especificos.reagrupante_fecha_nacimiento:8:10",

  "Texto8": "__slice__:datos_especificos.reagrupante_fecha_nacimiento:5:7",

  "Texto9": "__slice__:datos_especificos.reagrupante_fecha_nacimiento:0:4",



  "Texto10": "datos_especificos.reagrupante_localidad_nacimiento",

  "Texto11": "datos_especificos.reagrupante_pais_nacimiento",



  "Casilla de verificación1": "__equals__:datos_especificos.reagrupante_estado_civil:SOLTERO/A",

  "Casilla de verificación2": "__equals__:datos_especificos.reagrupante_estado_civil:CASADO/A",

  "Casilla de verificación3": "__equals__:datos_especificos.reagrupante_estado_civil:VIUDO/A",

  "Casilla de verificación4": "__equals__:datos_especificos.reagrupante_estado_civil:SEPARADO/A",



  "Texto12": "datos_especificos.reagrupante_nombre_padre",

  "Texto13": "datos_especificos.reagrupante_nombre_madre",



  "Texto14": "__join__: :datos_especificos.reagrupante_tipo_via:datos_especificos.reagrupante_nombre_via",

  "Texto15": "datos_especificos.reagrupante_numero",

  "Texto16": "datos_especificos.reagrupante_piso",

  "Texto17": "datos_especificos.reagrupante_localidad",

  "Texto18": "datos_especificos.reagrupante_codigo_postal",

  "Texto19": "datos_especificos.reagrupante_provincia",

  "Texto20": "datos_especificos.reagrupante_telefono",

  "Texto21": "datos_especificos.reagrupante_email",



  "Texto22": "__static__:RESIDENCIA Y OTROS TRAMITES",



  "Texto23": "representante.representante_documento",

  "Texto25": "representante.representante_nombre",

  "Texto26": "representante.representante_apellido1",

  "Texto27": "representante.representante_apellido2",

  "Texto28": "__join__: :representante.representante_tipo_via:representante.representante_domicilio",

  "Texto29": "representante.representante_numero",

  "Texto30": "representante.representante_piso",

  "Texto31": "representante.representante_localidad",

  "Texto32": "representante.representante_codigo_postal",

  "Texto33": "representante.representante_provincia",

  "Texto34": "representante.representante_telefono_movil",

  "Texto35": "representante.representante_email",



  "Texto36": "representante.representante_localidad",

  "Texto37": "__today__:%d",

  "Texto38": "__today__:%m",

  "Texto39": "__today__:%Y"

}',
    '[]',
    1,
    CURRENT_TIMESTAMP,
    CURRENT_TIMESTAMP
WHERE NOT EXISTS (
    SELECT 1
    FROM form_mapper_templates
    WHERE codigo = 'DESIG_REAGRUPANTE'
);

UPDATE form_mapper_templates
SET
    nombre = 'DESIGNACION REPRESENTANTE REAGRUPANTE',
    tipo_destino = 'PDF',
    activo = 1,
    tipo_expediente_id = NULL,
    subtipo_expediente_id = NULL,
    mapper_json = '{

  "Texto1": "datos_especificos.reagrupante_nombre",

  "Texto2": "datos_especificos.reagrupante_primer_apellido",

  "Texto3": "datos_especificos.reagrupante_segundo_apellido",

  "Texto4": "datos_especificos.reagrupante_nacionalidad",

  "Texto5": "datos_especificos.reagrupante_nie",

  "Texto6": "datos_especificos.reagrupante_pasaporte",



  "Texto7": "__slice__:datos_especificos.reagrupante_fecha_nacimiento:8:10",

  "Texto8": "__slice__:datos_especificos.reagrupante_fecha_nacimiento:5:7",

  "Texto9": "__slice__:datos_especificos.reagrupante_fecha_nacimiento:0:4",



  "Texto10": "datos_especificos.reagrupante_localidad_nacimiento",

  "Texto11": "datos_especificos.reagrupante_pais_nacimiento",



  "Casilla de verificación1": "__equals__:datos_especificos.reagrupante_estado_civil:SOLTERO/A",

  "Casilla de verificación2": "__equals__:datos_especificos.reagrupante_estado_civil:CASADO/A",

  "Casilla de verificación3": "__equals__:datos_especificos.reagrupante_estado_civil:VIUDO/A",

  "Casilla de verificación4": "__equals__:datos_especificos.reagrupante_estado_civil:SEPARADO/A",



  "Texto12": "datos_especificos.reagrupante_nombre_padre",

  "Texto13": "datos_especificos.reagrupante_nombre_madre",



  "Texto14": "__join__: :datos_especificos.reagrupante_tipo_via:datos_especificos.reagrupante_nombre_via",

  "Texto15": "datos_especificos.reagrupante_numero",

  "Texto16": "datos_especificos.reagrupante_piso",

  "Texto17": "datos_especificos.reagrupante_localidad",

  "Texto18": "datos_especificos.reagrupante_codigo_postal",

  "Texto19": "datos_especificos.reagrupante_provincia",

  "Texto20": "datos_especificos.reagrupante_telefono",

  "Texto21": "datos_especificos.reagrupante_email",



  "Texto22": "__static__:RESIDENCIA Y OTROS TRAMITES",



  "Texto23": "representante.representante_documento",

  "Texto25": "representante.representante_nombre",

  "Texto26": "representante.representante_apellido1",

  "Texto27": "representante.representante_apellido2",

  "Texto28": "__join__: :representante.representante_tipo_via:representante.representante_domicilio",

  "Texto29": "representante.representante_numero",

  "Texto30": "representante.representante_piso",

  "Texto31": "representante.representante_localidad",

  "Texto32": "representante.representante_codigo_postal",

  "Texto33": "representante.representante_provincia",

  "Texto34": "representante.representante_telefono_movil",

  "Texto35": "representante.representante_email",



  "Texto36": "representante.representante_localidad",

  "Texto37": "__today__:%d",

  "Texto38": "__today__:%m",

  "Texto39": "__today__:%Y"

}',
    required_fields_json = '[]',
    version = 1,
    updated_at = CURRENT_TIMESTAMP
WHERE codigo = 'DESIG_REAGRUPANTE';

INSERT INTO document_templates (
    codigo,
    nombre,
    nombre_oficial,
    descripcion,
    categoria,
    tipo_destino,
    template_type,
    template_path,
    fields_json_path,
    metadata_json_path,
    mapper_destino,
    requiere_expediente,
    activo,
    orden,
    created_at,
    updated_at
)
SELECT
    'DEC_CONYUGE',
    'DECLARACION CONYUGE',
    'DECLARACION CONYUGE',
    '',
    'GENERAL',
    'PDF',
    'pdf',
    'templates/documents/DECLARACION_CONYUGE/template.pdf',
    NULL,
    NULL,
    'DEC_CONYUGE',
    1,
    1,
    0,
    CURRENT_TIMESTAMP,
    CURRENT_TIMESTAMP
WHERE NOT EXISTS (
    SELECT 1
    FROM document_templates
    WHERE codigo = 'DEC_CONYUGE'
);

UPDATE document_templates
SET
    nombre = 'DECLARACION CONYUGE',
    nombre_oficial = 'DECLARACION CONYUGE',
    descripcion = '',
    categoria = 'GENERAL',
    tipo_destino = 'PDF',
    template_type = 'pdf',
    template_path = 'templates/documents/DECLARACION_CONYUGE/template.pdf',
    fields_json_path = NULL,
    metadata_json_path = NULL,
    mapper_destino = 'DEC_CONYUGE',
    requiere_expediente = 1,
    activo = 1,
    orden = 0,
    updated_at = CURRENT_TIMESTAMP
WHERE codigo = 'DEC_CONYUGE';

INSERT INTO document_templates (
    codigo,
    nombre,
    nombre_oficial,
    descripcion,
    categoria,
    tipo_destino,
    template_type,
    template_path,
    fields_json_path,
    metadata_json_path,
    mapper_destino,
    requiere_expediente,
    activo,
    orden,
    created_at,
    updated_at
)
SELECT
    'DESIG_REAGRUPANTE',
    'DESIGNACION_REPRESENTANTE_REAGRUPANTE',
    'DESIGNACION REPRESENTANTE REAGRUPANTE',
    '',
    'REPRESENTACION',
    'PDF',
    'pdf',
    'templates/documents/DESIG_REAGRUPANTE/template.pdf',
    NULL,
    NULL,
    'DESIG_REAGRUPANTE',
    1,
    1,
    0,
    CURRENT_TIMESTAMP,
    CURRENT_TIMESTAMP
WHERE NOT EXISTS (
    SELECT 1
    FROM document_templates
    WHERE codigo = 'DESIG_REAGRUPANTE'
);

UPDATE document_templates
SET
    nombre = 'DESIGNACION_REPRESENTANTE_REAGRUPANTE',
    nombre_oficial = 'DESIGNACION REPRESENTANTE REAGRUPANTE',
    descripcion = '',
    categoria = 'REPRESENTACION',
    tipo_destino = 'PDF',
    template_type = 'pdf',
    template_path = 'templates/documents/DESIG_REAGRUPANTE/template.pdf',
    fields_json_path = NULL,
    metadata_json_path = NULL,
    mapper_destino = 'DESIG_REAGRUPANTE',
    requiere_expediente = 1,
    activo = 1,
    orden = 0,
    updated_at = CURRENT_TIMESTAMP
WHERE codigo = 'DESIG_REAGRUPANTE';

COMMIT;
