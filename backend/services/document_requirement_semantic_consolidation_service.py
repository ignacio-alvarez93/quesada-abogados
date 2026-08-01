"""
Consolidación de requisitos documentales migrados en grupos semánticos.

No toca:
- config_documentos_requeridos;
- Box Watch;
- rutas o identificadores de Box;
- inventarios o escaneados;
- archivos físicos.

Crea grupos semánticos, copia sus opciones, registra su procedencia
y desactiva los grupos LEGACY_REQ_* sustituidos.
"""

import sqlite3
from pathlib import Path


DB_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "quesada.db"
)

PROVENANCE_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "migrations"
    / "20260731_create_semantic_requirement_provenance.sql"
)

NOMENCLATURE_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "migrations"
    / "20260731_create_canonical_document_nomenclatures.sql"
)


SEMANTIC_PLAN = [
    # --------------------------------------------------------
    # NACIONALIDAD POR RESIDENCIA / CASO GENERAL
    # --------------------------------------------------------
    {
        "tipo_codigo": "NACIONALIDAD",
        "subtipo_codigo": "CASO_GENERAL",
        "codigo": "ANTECEDENTES",
        "nombre": "ANTECEDENTES PENALES",
        "regla": "ALL",
        "legacy_ids": [1],
        "orden": 10,
    },
    {
        "tipo_codigo": "NACIONALIDAD",
        "subtipo_codigo": "CASO_GENERAL",
        "codigo": "NACIMIENTO_SOLICITANTE",
        "nombre": "NACIMIENTO DEL SOLICITANTE",
        "regla": "ALL",
        "legacy_ids": [2],
        "orden": 20,
    },
    {
        "tipo_codigo": "NACIONALIDAD",
        "subtipo_codigo": "CASO_GENERAL",
        "codigo": "IDENTIDAD_TITULAR",
        "nombre": "IDENTIDAD DEL TITULAR",
        "regla": "ALL",
        "legacy_ids": [3, 4],
        "orden": 30,
    },
    {
        "tipo_codigo": "NACIONALIDAD",
        "subtipo_codigo": "CASO_GENERAL",
        "codigo": "INTEGRACION_CCSE",
        "nombre": "PRUEBA CCSE",
        "regla": "ALL",
        "legacy_ids": [5],
        "orden": 40,
    },
    {
        "tipo_codigo": "NACIONALIDAD",
        "subtipo_codigo": "CASO_GENERAL",
        "codigo": "INTEGRACION_DELE",
        "nombre": "PRUEBA DELE",
        "regla": "OPTIONAL",
        "legacy_ids": [6],
        "orden": 50,
    },
    {
        "tipo_codigo": "NACIONALIDAD",
        "subtipo_codigo": "CASO_GENERAL",
        "codigo": "TASA",
        "nombre": "TASA DE NACIONALIDAD",
        "regla": "ALL",
        "legacy_ids": [7],
        "orden": 60,
    },
    {
        "tipo_codigo": "NACIONALIDAD",
        "subtipo_codigo": "CASO_GENERAL",
        "codigo": "DOMICILIO",
        "nombre": "ACREDITACIÓN DEL DOMICILIO",
        "regla": "ALL",
        "legacy_ids": [8],
        "orden": 70,
    },
    {
        "tipo_codigo": "NACIONALIDAD",
        "subtipo_codigo": "CASO_GENERAL",
        "codigo": "NACIMIENTO_HIJOS_MENORES",
        "nombre": "NACIMIENTO DE HIJOS MENORES",
        "regla": "OPTIONAL",
        "legacy_ids": [9],
        "orden": 80,
    },
    {
        "tipo_codigo": "NACIONALIDAD",
        "subtipo_codigo": "CASO_GENERAL",
        "codigo": "REPRESENTACION",
        "nombre": "ACREDITACIÓN DE LA REPRESENTACIÓN",
        "regla": "ALL",
        "legacy_ids": [10],
        "orden": 90,
    },
    {
        "tipo_codigo": "NACIONALIDAD",
        "subtipo_codigo": "CASO_GENERAL",
        "codigo": "IDENTIDAD_REPRESENTANTE",
        "nombre": "IDENTIDAD DEL REPRESENTANTE",
        "regla": "OPTIONAL",
        "legacy_ids": [11],
        "orden": 100,
    },

    # --------------------------------------------------------
    # REGULARIZACIÓN MASIVA / INDIVIDUALES
    # --------------------------------------------------------
    {
        "tipo_codigo": "REGULARIZACION_MASIVA_TRANS_21",
        "subtipo_codigo": "INDIVIDUALES",
        "codigo": "ANTECEDENTES",
        "nombre": "ANTECEDENTES PENALES",
        "regla": "ALL",
        "legacy_ids": [12],
        "orden": 10,
    },
    {
        "tipo_codigo": "REGULARIZACION_MASIVA_TRANS_21",
        "subtipo_codigo": "INDIVIDUALES",
        "codigo": "DOMICILIO",
        "nombre": "ACREDITACIÓN DEL DOMICILIO",
        "regla": "ALL",
        "legacy_ids": [13],
        "orden": 20,
    },
    {
        "tipo_codigo": "REGULARIZACION_MASIVA_TRANS_21",
        "subtipo_codigo": "INDIVIDUALES",
        "codigo": "IDENTIDAD",
        "nombre": "IDENTIDAD DEL SOLICITANTE",
        "regla": "ALL",
        "legacy_ids": [14],
        "orden": 30,
    },
    {
        "tipo_codigo": "REGULARIZACION_MASIVA_TRANS_21",
        "subtipo_codigo": "INDIVIDUALES",
        "codigo": "PERMANENCIA",
        "nombre": "ACREDITACIÓN DE LA PERMANENCIA",
        "regla": "ALL",
        "legacy_ids": [15],
        "orden": 40,
    },
    {
        "tipo_codigo": "REGULARIZACION_MASIVA_TRANS_21",
        "subtipo_codigo": "INDIVIDUALES",
        "codigo": "REPRESENTACION",
        "nombre": "ACREDITACIÓN DE LA REPRESENTACIÓN",
        "regla": "ALL",
        "legacy_ids": [16],
        "orden": 50,
    },
    {
        "tipo_codigo": "REGULARIZACION_MASIVA_TRANS_21",
        "subtipo_codigo": "INDIVIDUALES",
        "codigo": "RELACION_LABORAL",
        "nombre": "RELACIÓN LABORAL",
        "regla": "OPTIONAL",
        "legacy_ids": [17],
        "orden": 60,
    },
    {
        "tipo_codigo": "REGULARIZACION_MASIVA_TRANS_21",
        "subtipo_codigo": None,
        "codigo": "VULNERABILIDAD",
        "nombre": "ACREDITACIÓN DE VULNERABILIDAD",
        "regla": "OPTIONAL",
        "legacy_ids": [18],
        "orden": 70,
    },
    {
        "tipo_codigo": "REGULARIZACION_MASIVA_TRANS_21",
        "subtipo_codigo": "INDIVIDUALES",
        "codigo": "NACIMIENTO_SOLICITANTE",
        "nombre": "NACIMIENTO DEL SOLICITANTE",
        "regla": "ALL",
        "legacy_ids": [19],
        "orden": 80,
    },

    # --------------------------------------------------------
    # RESIDENCIA NO LUCRATIVA / RENOVACIÓN TITULAR
    # --------------------------------------------------------
    {
        "tipo_codigo": "RESIDENCIA_TEMPORAL_NO_LUCRATIVA",
        "subtipo_codigo": "RENOVACION_TITULAR",
        "codigo": "IDENTIDAD_TITULAR",
        "nombre": "IDENTIDAD DEL TITULAR",
        "regla": "ALL",
        "legacy_ids": [20, 21],
        "orden": 10,
    },
    {
        "tipo_codigo": "RESIDENCIA_TEMPORAL_NO_LUCRATIVA",
        "subtipo_codigo": "RENOVACION_TITULAR",
        "codigo": "DOMICILIO",
        "nombre": "ACREDITACIÓN DEL DOMICILIO",
        "regla": "ALL",
        "legacy_ids": [22],
        "orden": 20,
    },
    {
        "tipo_codigo": "RESIDENCIA_TEMPORAL_NO_LUCRATIVA",
        "subtipo_codigo": "RENOVACION_TITULAR",
        "codigo": "SEGURO_SALUD",
        "nombre": "SEGURO DE SALUD",
        "regla": "ALL",
        "legacy_ids": [23],
        "orden": 30,
    },
    {
        "tipo_codigo": "RESIDENCIA_TEMPORAL_NO_LUCRATIVA",
        "subtipo_codigo": "RENOVACION_TITULAR",
        "codigo": "MEDIOS_ECONOMICOS",
        "nombre": "ACREDITACIÓN DE MEDIOS ECONÓMICOS",
        "regla": "ALL",
        "legacy_ids": [24],
        "orden": 40,
    },

    # --------------------------------------------------------
    # REAGRUPACIÓN FAMILIAR / INICIAL
    # --------------------------------------------------------
    {
        "tipo_codigo": "REAGRUPACION_FAMILIAR",
        "subtipo_codigo": "INICIAL",
        "codigo": "IDENTIDAD_PARTES",
        "nombre": "IDENTIDAD DE LAS PARTES",
        "regla": "ALL",
        "legacy_ids": [25, 26, 27],
        "orden": 10,
        "option_nomenclatures": [
            {
                "codigo": "PASAPORTE",
                "rol_documental": "REAGRUPANTE",
                "nomenclatures": [
                    {
                        "patron_nombre": (
                            "PASAPORTE REAGRUPANTE"
                        ),
                        "extension_permitida": (
                            "pdf,jpg,jpeg,png"
                        ),
                        "prioridad": 10,
                    },
                ],
            },
            {
                "codigo": "PASAPORTE",
                "rol_documental": "REAGRUPADO",
                "nomenclatures": [
                    {
                        "patron_nombre": (
                            "PASAPORTE REAGRUPADO"
                        ),
                        "extension_permitida": (
                            "pdf,jpg,jpeg,png"
                        ),
                        "prioridad": 10,
                    },
                    {
                        "patron_nombre": (
                            "PASAPORTE REAGRUPADA"
                        ),
                        "extension_permitida": (
                            "pdf,jpg,jpeg,png"
                        ),
                        "prioridad": 20,
                    },
                ],
            },
            {
                "codigo": "NIE",
                "rol_documental": "REAGRUPANTE",
                "nomenclatures": [
                    {
                        "patron_nombre": "NIE REAGRUPANTE",
                        "extension_permitida": (
                            "pdf,jpg,jpeg,png"
                        ),
                        "prioridad": 10,
                    },
                    {
                        "patron_nombre": "TIE REAGRUPANTE",
                        "extension_permitida": (
                            "pdf,jpg,jpeg,png"
                        ),
                        "prioridad": 20,
                    },
                ],
            },
        ],
    },
    {
        "tipo_codigo": "REAGRUPACION_FAMILIAR",
        "subtipo_codigo": "INICIAL",
        "codigo": "DOMICILIO_CONVIVENCIA",
        "nombre": "DOMICILIO Y CONVIVENCIA",
        "regla": "ALL",
        "legacy_ids": [28],
        "orden": 20,
        "option_nomenclatures": [
            {
                "codigo": "EMPADRONAMIENTO_CONJUNTO",
                "rol_documental": None,
                "nomenclatures": [
                    {
                        "patron_nombre": (
                            "EMPADRONAMIENTO CONJUNTO"
                        ),
                        "extension_permitida": (
                            "pdf,jpg,jpeg,png"
                        ),
                        "prioridad": 10,
                    },
                    {
                        "patron_nombre": (
                            "EMPADRONAMIENTO COLECTIVO"
                        ),
                        "extension_permitida": (
                            "pdf,jpg,jpeg,png"
                        ),
                        "prioridad": 10,
                    },
                    {
                        "patron_nombre": "PADRON CONJUNTO",
                        "extension_permitida": (
                            "pdf,jpg,jpeg,png"
                        ),
                        "prioridad": 20,
                    },
                    {
                        "patron_nombre": "PADRON COLECTIVO",
                        "extension_permitida": (
                            "pdf,jpg,jpeg,png"
                        ),
                        "prioridad": 20,
                    },
                    {
                        "patron_nombre": (
                            "CERTIFICADO CONVIVENCIA"
                        ),
                        "extension_permitida": (
                            "pdf,jpg,jpeg,png"
                        ),
                        "prioridad": 30,
                    },
                ],
            },
        ],
    },
    {
        "tipo_codigo": "REAGRUPACION_FAMILIAR",
        "subtipo_codigo": "INICIAL",
        "codigo": "VIVIENDA",
        "nombre": "ADECUACIÓN DE LA VIVIENDA",
        "regla": "ANY",
        "legacy_ids": [29],
        "orden": 30,
        "extra_options": [
            {
                "codigo": (
                    "JUSTIFICANTE_SOLICITUD_"
                    "INFORME_VIVIENDA"
                ),
                "nombre": (
                    "JUSTIFICANTE DE SOLICITUD "
                    "DEL INFORME DE VIVIENDA"
                ),
                "descripcion": (
                    "Resguardo o justificante que acredita "
                    "la solicitud del informe de adecuación "
                    "de vivienda."
                ),
                "categoria": "VIVIENDA",
                "rol_documental": None,
                "etiqueta_requisito": (
                    "Justificante de solicitud del "
                    "informe de vivienda"
                ),
                "descripcion_requisito": (
                    "Alternativa válida mientras el informe "
                    "de adecuación de vivienda está pendiente."
                ),
                "orden": 20,
                "nomenclatures": [
                    {
                        "patron_nombre": (
                            "JUSTIFICANTE SOLICITUD "
                            "INFORME VIVIENDA"
                        ),
                        "extension_permitida": (
                            "pdf,jpg,jpeg,png"
                        ),
                        "prioridad": 10,
                    },
                    {
                        "patron_nombre": (
                            "RESGUARDO SOLICITUD "
                            "INFORME VIVIENDA"
                        ),
                        "extension_permitida": (
                            "pdf,jpg,jpeg,png"
                        ),
                        "prioridad": 10,
                    },
                    {
                        "patron_nombre": (
                            "SOLICITUD INFORME "
                            "ADECUACION VIVIENDA"
                        ),
                        "extension_permitida": (
                            "pdf,jpg,jpeg,png"
                        ),
                        "prioridad": 20,
                    },
                    {
                        "patron_nombre": (
                            "JUSTIFICANTE SOLICITUD "
                            "ADECUACION VIVIENDA"
                        ),
                        "extension_permitida": (
                            "pdf,jpg,jpeg,png"
                        ),
                        "prioridad": 20,
                    },
                ],
            },
        ],
    },
    {
        "tipo_codigo": "REAGRUPACION_FAMILIAR",
        "subtipo_codigo": "INICIAL",
        "codigo": "VINCULO_FAMILIAR",
        "nombre": "ACREDITACIÓN DEL VÍNCULO FAMILIAR",
        "regla": "ALL",
        "legacy_ids": [30],
        "orden": 40,
        "option_nomenclatures": [
            {
                "codigo": "CERTIFICADO_MATRIMONIO",
                "rol_documental": None,
                "nomenclatures": [
                    {
                        "patron_nombre": (
                            "CERTIFICADO MATRIMONIO"
                        ),
                        "extension_permitida": (
                            "pdf,jpg,jpeg,png"
                        ),
                        "prioridad": 10,
                    },
                    {
                        "patron_nombre": "CERT MATRIMONIO",
                        "extension_permitida": (
                            "pdf,jpg,jpeg,png"
                        ),
                        "prioridad": 20,
                    },
                    {
                        "patron_nombre": (
                            "ACTA DE MATRIMONIO"
                        ),
                        "extension_permitida": (
                            "pdf,jpg,jpeg,png"
                        ),
                        "prioridad": 20,
                    },
                    {
                        "patron_nombre": "ACTA MATRIMONIO",
                        "extension_permitida": (
                            "pdf,jpg,jpeg,png"
                        ),
                        "prioridad": 30,
                    },
                ],
            },
        ],
    },
    {
        "tipo_codigo": "REAGRUPACION_FAMILIAR",
        "subtipo_codigo": "INICIAL",
        "codigo": "MEDIOS_ECONOMICOS",
        "nombre": "ACREDITACIÓN DE MEDIOS ECONÓMICOS",
        "regla": "ALL",
        "legacy_ids": [31],
        "orden": 50,
    },
]


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _legacy_group_code(legacy_id):
    return f"LEGACY_REQ_{int(legacy_id)}_%"


def _resolve_procedure(conn, definition):
    tipo = conn.execute(
        """
        SELECT id
        FROM config_tipos_expediente
        WHERE codigo = ?
        """,
        (definition["tipo_codigo"],),
    ).fetchone()

    if not tipo:
        raise ValueError(
            f"No existe el tipo {definition['tipo_codigo']}"
        )

    tipo_id = int(tipo["id"])
    subtipo_code = definition["subtipo_codigo"]

    if subtipo_code is None:
        return tipo_id, None

    subtipo = conn.execute(
        """
        SELECT id
        FROM config_subtipos_expediente
        WHERE tipo_expediente_id = ?
          AND codigo = ?
        """,
        (tipo_id, subtipo_code),
    ).fetchone()

    if not subtipo:
        raise ValueError(
            "No existe el subtipo "
            f"{subtipo_code} para {definition['tipo_codigo']}"
        )

    return tipo_id, int(subtipo["id"])


def _find_legacy_group(conn, legacy_id):
    row = conn.execute(
        """
        SELECT *
        FROM config_grupos_requisitos_documentales
        WHERE codigo LIKE ?
        """,
        (_legacy_group_code(legacy_id),),
    ).fetchone()

    if not row:
        raise ValueError(
            f"No existe el grupo legacy #{legacy_id}"
        )

    return row


def preview_semantic_consolidation():
    conn = _connect()
    try:
        result = []

        for definition in SEMANTIC_PLAN:
            tipo_id, subtipo_id = _resolve_procedure(
                conn,
                definition,
            )

            legacy_groups = [
                _find_legacy_group(conn, legacy_id)
                for legacy_id in definition["legacy_ids"]
            ]

            result.append(
                {
                    "tipo_expediente_id": tipo_id,
                    "subtipo_expediente_id": subtipo_id,
                    "codigo": definition["codigo"],
                    "nombre": definition["nombre"],
                    "regla": definition["regla"],
                    "legacy_group_ids": [
                        int(group["id"])
                        for group in legacy_groups
                    ],
                    "legacy_document_ids": list(
                        definition["legacy_ids"]
                    ),
                }
            )

        return result
    finally:
        conn.close()


def _get_or_create_semantic_group(
    conn,
    tipo_id,
    subtipo_id,
    definition,
):
    row = conn.execute(
        """
        SELECT id
        FROM config_grupos_requisitos_documentales
        WHERE tipo_expediente_id = ?
          AND codigo = ?
          AND (
                subtipo_expediente_id = ?
                OR (
                    subtipo_expediente_id IS NULL
                    AND ? IS NULL
                )
          )
        """,
        (
            tipo_id,
            definition["codigo"],
            subtipo_id,
            subtipo_id,
        ),
    ).fetchone()

    minimum = (
        0
        if definition["regla"] == "OPTIONAL"
        else 1
    )

    values = (
        definition["nombre"],
        "Grupo semántico consolidado desde requisitos legacy",
        definition["regla"],
        minimum,
        int(definition["orden"]),
        1,
    )

    if row:
        conn.execute(
            """
            UPDATE config_grupos_requisitos_documentales
            SET
                nombre = ?,
                descripcion = ?,
                regla_cumplimiento = ?,
                minimo_documentos = ?,
                orden = ?,
                activo = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            values + (int(row["id"]),),
        )
        return int(row["id"]), False

    cursor = conn.execute(
        """
        INSERT INTO config_grupos_requisitos_documentales (
            tipo_expediente_id,
            subtipo_expediente_id,
            codigo,
            nombre,
            descripcion,
            regla_cumplimiento,
            minimo_documentos,
            orden,
            activo
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            tipo_id,
            subtipo_id,
            definition["codigo"],
        )
        + values,
    )

    return int(cursor.lastrowid), True


def _copy_legacy_options(
    conn,
    semantic_group_id,
    legacy_group_id,
):
    rows = conn.execute(
        """
        SELECT
            documento_catalogo_id,
            rol_documental,
            etiqueta_requisito,
            descripcion_requisito,
            orden,
            activo
        FROM config_grupo_requisito_documentos
        WHERE grupo_id = ?
        ORDER BY orden, id
        """,
        (legacy_group_id,),
    ).fetchall()

    created = 0
    reused = 0

    for row in rows:
        existing = conn.execute(
            """
            SELECT id
            FROM config_grupo_requisito_documentos
            WHERE grupo_id = ?
              AND documento_catalogo_id = ?
              AND COALESCE(rol_documental, '') =
                  COALESCE(?, '')
            """,
            (
                semantic_group_id,
                int(row["documento_catalogo_id"]),
                row["rol_documental"],
            ),
        ).fetchone()

        values = (
            row["etiqueta_requisito"],
            row["descripcion_requisito"],
            int(row["orden"] or 0),
            int(row["activo"] or 0),
        )

        if existing:
            conn.execute(
                """
                UPDATE config_grupo_requisito_documentos
                SET
                    etiqueta_requisito = ?,
                    descripcion_requisito = ?,
                    orden = ?,
                    activo = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                values + (int(existing["id"]),),
            )
            reused += 1
            continue

        conn.execute(
            """
            INSERT INTO config_grupo_requisito_documentos (
                grupo_id,
                documento_catalogo_id,
                rol_documental,
                etiqueta_requisito,
                descripcion_requisito,
                orden,
                activo
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                semantic_group_id,
                int(row["documento_catalogo_id"]),
                row["rol_documental"],
            )
            + values,
        )
        created += 1

    return created, reused


def _get_or_create_catalog_document(
    conn,
    option_definition,
):
    code = str(
        option_definition.get("codigo") or ""
    ).strip().upper()

    name = str(
        option_definition.get("nombre") or ""
    ).strip().upper()

    if not code:
        raise ValueError(
            "La opción documental adicional no tiene código"
        )

    if not name:
        raise ValueError(
            f"La opción documental {code} no tiene nombre"
        )

    row = conn.execute(
        """
        SELECT id
        FROM config_documentos_catalogo
        WHERE codigo = ?
        """,
        (code,),
    ).fetchone()

    values = (
        name,
        str(
            option_definition.get("descripcion") or ""
        ).strip() or None,
        str(
            option_definition.get("categoria") or ""
        ).strip().upper() or None,
        1,
    )

    if row:
        conn.execute(
            """
            UPDATE config_documentos_catalogo
            SET
                nombre = ?,
                descripcion = ?,
                categoria = ?,
                activo = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            values + (int(row["id"]),),
        )
        return int(row["id"]), False

    cursor = conn.execute(
        """
        INSERT INTO config_documentos_catalogo (
            codigo,
            nombre,
            descripcion,
            categoria,
            activo
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (code,) + values,
    )

    return int(cursor.lastrowid), True


def _normalize_extensions(value):
    raw = str(
        value or "pdf,jpg,jpeg,png"
    ).lower().replace(";", ",")

    extensions = []

    for item in raw.split(","):
        extension = item.strip().lstrip(".")

        if extension and extension not in extensions:
            extensions.append(extension)

    return ",".join(extensions) or "pdf,jpg,jpeg,png"


def _add_extra_nomenclatures(
    conn,
    *,
    document_id,
    tipo_id,
    subtipo_id,
    role,
    option_definition,
):
    created = 0
    reused = 0
    updated = 0

    for nomenclature in (
        option_definition.get("nomenclatures") or []
    ):
        pattern = str(
            nomenclature.get("patron_nombre") or ""
        ).strip().upper()

        if not pattern:
            raise ValueError(
                "La nomenclatura adicional no tiene patrón"
            )

        extensions = _normalize_extensions(
            nomenclature.get("extension_permitida")
        )
        priority = int(
            nomenclature.get("prioridad") or 100
        )
        active = int(
            nomenclature.get("activo", 1) or 0
        )

        existing = conn.execute(
            """
            SELECT *
            FROM config_nomenclaturas_catalogo
            WHERE documento_catalogo_id = ?
              AND tipo_expediente_id = ?
              AND COALESCE(subtipo_expediente_id, -1) =
                  COALESCE(?, -1)
              AND COALESCE(rol_documental, '') =
                  COALESCE(?, '')
              AND UPPER(TRIM(patron_nombre)) = ?
              AND LOWER(TRIM(extension_permitida)) = ?
            """,
            (
                int(document_id),
                int(tipo_id),
                subtipo_id,
                role,
                pattern,
                extensions,
            ),
        ).fetchone()

        values = (
            priority,
            active,
        )

        if existing:
            changed = any(
                [
                    int(existing["prioridad"] or 100)
                    != priority,
                    int(existing["activo"] or 0)
                    != active,
                ]
            )

            conn.execute(
                """
                UPDATE config_nomenclaturas_catalogo
                SET
                    prioridad = ?,
                    activo = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                values + (int(existing["id"]),),
            )

            if changed:
                updated += 1
            else:
                reused += 1

            continue

        conn.execute(
            """
            INSERT INTO config_nomenclaturas_catalogo (
                documento_catalogo_id,
                tipo_expediente_id,
                subtipo_expediente_id,
                rol_documental,
                patron_nombre,
                extension_permitida,
                prioridad,
                activo,
                origen_legacy_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                int(document_id),
                int(tipo_id),
                subtipo_id,
                role,
                pattern,
                extensions,
                priority,
                active,
            ),
        )

        created += 1

    return {
        "created": created,
        "reused": reused,
        "updated": updated,
    }


def _add_option_nomenclatures(
    conn,
    semantic_group_id,
    tipo_id,
    subtipo_id,
    definition,
):
    created = 0
    reused = 0
    updated = 0

    for option in (
        definition.get("option_nomenclatures") or []
    ):
        code = str(
            option.get("codigo") or ""
        ).strip().upper()

        role = str(
            option.get("rol_documental") or ""
        ).strip().upper() or None

        if not code:
            raise ValueError(
                "La nomenclatura de opción no tiene código"
            )

        row = conn.execute(
            """
            SELECT
                d.id AS documento_catalogo_id
            FROM config_grupo_requisito_documentos o
            JOIN config_documentos_catalogo d
              ON d.id = o.documento_catalogo_id
            WHERE o.grupo_id = ?
              AND d.codigo = ?
              AND COALESCE(o.rol_documental, '') =
                  COALESCE(?, '')
              AND o.activo = 1
            """,
            (
                int(semantic_group_id),
                code,
                role,
            ),
        ).fetchone()

        if not row:
            raise ValueError(
                "No existe la opción heredada "
                f"{code} / {role or 'SIN_ROL'} "
                f"en el grupo #{semantic_group_id}"
            )

        nomenclature_summary = (
            _add_extra_nomenclatures(
                conn,
                document_id=int(
                    row["documento_catalogo_id"]
                ),
                tipo_id=tipo_id,
                subtipo_id=subtipo_id,
                role=role,
                option_definition=option,
            )
        )

        created += nomenclature_summary["created"]
        reused += nomenclature_summary["reused"]
        updated += nomenclature_summary["updated"]

    return {
        "nomenclatures_created": created,
        "nomenclatures_reused": reused,
        "nomenclatures_updated": updated,
    }


def _add_extra_options(
    conn,
    semantic_group_id,
    tipo_id,
    subtipo_id,
    definition,
):
    created = 0
    reused = 0
    catalog_created = 0
    catalog_reused = 0
    nomenclatures_created = 0
    nomenclatures_reused = 0
    nomenclatures_updated = 0

    for option in definition.get("extra_options") or []:
        document_id, document_created = (
            _get_or_create_catalog_document(
                conn,
                option,
            )
        )

        if document_created:
            catalog_created += 1
        else:
            catalog_reused += 1

        role = str(
            option.get("rol_documental") or ""
        ).strip().upper() or None

        nomenclature_summary = _add_extra_nomenclatures(
            conn,
            document_id=document_id,
            tipo_id=tipo_id,
            subtipo_id=subtipo_id,
            role=role,
            option_definition=option,
        )

        nomenclatures_created += (
            nomenclature_summary["created"]
        )
        nomenclatures_reused += (
            nomenclature_summary["reused"]
        )
        nomenclatures_updated += (
            nomenclature_summary["updated"]
        )

        row = conn.execute(
            """
            SELECT id
            FROM config_grupo_requisito_documentos
            WHERE grupo_id = ?
              AND documento_catalogo_id = ?
              AND COALESCE(rol_documental, '') =
                  COALESCE(?, '')
            """,
            (
                int(semantic_group_id),
                int(document_id),
                role,
            ),
        ).fetchone()

        values = (
            str(
                option.get("etiqueta_requisito") or ""
            ).strip() or None,
            str(
                option.get("descripcion_requisito") or ""
            ).strip() or None,
            int(option.get("orden") or 0),
            1,
        )

        if row:
            conn.execute(
                """
                UPDATE config_grupo_requisito_documentos
                SET
                    etiqueta_requisito = ?,
                    descripcion_requisito = ?,
                    orden = ?,
                    activo = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                values + (int(row["id"]),),
            )
            reused += 1
            continue

        conn.execute(
            """
            INSERT INTO config_grupo_requisito_documentos (
                grupo_id,
                documento_catalogo_id,
                rol_documental,
                etiqueta_requisito,
                descripcion_requisito,
                orden,
                activo
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(semantic_group_id),
                int(document_id),
                role,
            )
            + values,
        )
        created += 1

    return {
        "options_created": created,
        "options_reused": reused,
        "catalog_created": catalog_created,
        "catalog_reused": catalog_reused,
        "nomenclatures_created": nomenclatures_created,
        "nomenclatures_reused": nomenclatures_reused,
        "nomenclatures_updated": nomenclatures_updated,
    }


def consolidate_semantic_groups(
    *,
    deactivate_legacy=True,
):
    if not PROVENANCE_SCHEMA_PATH.exists():
        raise FileNotFoundError(
            "No existe el esquema de trazabilidad semántica"
        )

    if not NOMENCLATURE_SCHEMA_PATH.exists():
        raise FileNotFoundError(
            "No existe el esquema de nomenclaturas canónicas"
        )

    conn = _connect()

    try:
        conn.executescript(
            PROVENANCE_SCHEMA_PATH.read_text(
                encoding="utf-8"
            )
        )

        conn.executescript(
            NOMENCLATURE_SCHEMA_PATH.read_text(
                encoding="utf-8"
            )
        )

        summary = {
            "semantic_groups_planned": len(SEMANTIC_PLAN),
            "semantic_groups_created": 0,
            "semantic_groups_reused": 0,
            "options_created": 0,
            "options_reused": 0,
            "catalog_documents_created": 0,
            "catalog_documents_reused": 0,
            "nomenclatures_created": 0,
            "nomenclatures_reused": 0,
            "nomenclatures_updated": 0,
            "provenance_created": 0,
            "provenance_reused": 0,
            "legacy_groups_deactivated": 0,
        }

        for definition in SEMANTIC_PLAN:
            tipo_id, subtipo_id = _resolve_procedure(
                conn,
                definition,
            )

            semantic_group_id, created = (
                _get_or_create_semantic_group(
                    conn,
                    tipo_id,
                    subtipo_id,
                    definition,
                )
            )

            summary[
                "semantic_groups_created"
                if created
                else "semantic_groups_reused"
            ] += 1

            for legacy_id in definition["legacy_ids"]:
                legacy_group = _find_legacy_group(
                    conn,
                    legacy_id,
                )
                legacy_group_id = int(legacy_group["id"])

                option_created, option_reused = (
                    _copy_legacy_options(
                        conn,
                        semantic_group_id,
                        legacy_group_id,
                    )
                )

                summary["options_created"] += option_created
                summary["options_reused"] += option_reused

                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO
                    config_grupos_requisitos_origen_legacy (
                        grupo_semantico_id,
                        grupo_legacy_id
                    )
                    VALUES (?, ?)
                    """,
                    (
                        semantic_group_id,
                        legacy_group_id,
                    ),
                )

                if cursor.rowcount == 1:
                    summary["provenance_created"] += 1
                else:
                    summary["provenance_reused"] += 1

                if (
                    deactivate_legacy
                    and int(legacy_group["activo"] or 0) == 1
                ):
                    conn.execute(
                        """
                        UPDATE config_grupos_requisitos_documentales
                        SET
                            activo = 0,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (legacy_group_id,),
                    )
                    summary[
                        "legacy_groups_deactivated"
                    ] += 1

            option_nomenclature_summary = (
                _add_option_nomenclatures(
                    conn,
                    semantic_group_id,
                    tipo_id,
                    subtipo_id,
                    definition,
                )
            )

            summary["nomenclatures_created"] += (
                option_nomenclature_summary[
                    "nomenclatures_created"
                ]
            )
            summary["nomenclatures_reused"] += (
                option_nomenclature_summary[
                    "nomenclatures_reused"
                ]
            )
            summary["nomenclatures_updated"] += (
                option_nomenclature_summary[
                    "nomenclatures_updated"
                ]
            )

            extra_summary = _add_extra_options(
                conn,
                semantic_group_id,
                tipo_id,
                subtipo_id,
                definition,
            )

            summary["options_created"] += (
                extra_summary["options_created"]
            )
            summary["options_reused"] += (
                extra_summary["options_reused"]
            )
            summary["catalog_documents_created"] += (
                extra_summary["catalog_created"]
            )
            summary["catalog_documents_reused"] += (
                extra_summary["catalog_reused"]
            )
            summary["nomenclatures_created"] += (
                extra_summary["nomenclatures_created"]
            )
            summary["nomenclatures_reused"] += (
                extra_summary["nomenclatures_reused"]
            )
            summary["nomenclatures_updated"] += (
                extra_summary["nomenclatures_updated"]
            )

        conn.commit()
        return summary

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
