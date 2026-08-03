"""
Evaluación pura de requisitos documentales semánticos.

Este servicio:
- solo lee la configuración documental agrupada;
- no accede al disco ni a Box;
- no modifica expedientes;
- no genera alertas;
- no sustituye todavía el motor legacy;
- exige coincidencia de rol cuando el requisito tiene rol.
"""

import sqlite3
from pathlib import Path


DB_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "quesada.db"
)


VALID_RULES = {
    "ALL",
    "ANY",
    "AT_LEAST",
    "OPTIONAL",
}


DOCUMENT_CODE_ALIASES = {
    "ANTECEDENTES_PENALES": {
        "AAPP",
        "ANTECEDENTES",
        "ANTECEDENTES_ESPANA",
        "REGISTRO_CENTRAL_PENADOS",
    },
    "PASAPORTE": {
        "PASAP",
        "PASAPORTE_ACTUAL",
        "PASAPORTE_COMPLETO",
    },
    "NIE": {
        "TIE",
        "TARJETA_RESIDENCIA",
    },
    "PODER_REPRESENTACION": {
        "PODER",
        "DESIGNACION",
        "DESIGNACION_REPRESENTANTE",
        "MANDATO_REPRESENTACION",
    },
    "EMPADRONAMIENTO": {
        "PADRON",
        "EMPADRONAMIENTO_HISTORICO",
    },
    "ACTA_NACIMIENTO": {
        "ACTA_NAC",
        "CERTIFICADO_NACIMIENTO",
    },
    "CERTIFICADO_MATRIMONIO": {
        "ACTA_MATRIMONIO",
        "ACTA_MAT",
    },
    "CCSE": {
        "CCSE_CERTIFICADO",
    },
    "DELE": {
        "DELE_CERTIFICADO",
    },
    "TASA_790016": {
        "TASA",
        "TASA_PAGADA",
        "FORMULARIO_TASA",
        "FORMULARIO_PAGO_TASAS",
        "790",
        "790016",
    },
}


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _norm(value):
    return str(value or "").strip().upper()


def _int_or_none(value):
    if value in (None, "", "None"):
        return None
    return int(value)


def _expanded_codes(code):
    normalized = _norm(code)

    if not normalized:
        return set()

    graph = {}

    for canonical, aliases in DOCUMENT_CODE_ALIASES.items():
        canonical = _norm(canonical)
        graph.setdefault(canonical, set())

        for alias in aliases:
            alias = _norm(alias)
            graph.setdefault(canonical, set()).add(alias)
            graph.setdefault(alias, set()).add(canonical)

    expanded = {normalized}
    pending = [normalized]

    while pending:
        current = pending.pop()

        for related in graph.get(current, set()):
            if related not in expanded:
                expanded.add(related)
                pending.append(related)

    return expanded


def _codes_match(required_code, detected_code):
    return bool(
        _expanded_codes(required_code)
        .intersection(_expanded_codes(detected_code))
    )


def normalize_detection(detection):
    if isinstance(detection, str):
        detection = {
            "codigo": detection,
        }

    if not isinstance(detection, dict):
        raise ValueError(
            "Cada detección debe ser un código o un diccionario"
        )

    code = _norm(detection.get("codigo"))

    if not code:
        raise ValueError(
            "La detección documental necesita un código"
        )

    normalized = dict(detection)
    normalized["codigo"] = code
    normalized["rol_documental"] = (
        _norm(detection.get("rol_documental"))
        or None
    )

    return normalized


def _load_active_groups(
    conn,
    tipo_expediente_id,
    subtipo_expediente_id=None,
):
    tipo_id = int(tipo_expediente_id)
    subtipo_id = _int_or_none(subtipo_expediente_id)

    sql = """
        SELECT
            g.id AS grupo_id,
            g.tipo_expediente_id,
            g.subtipo_expediente_id,
            g.codigo AS grupo_codigo,
            g.nombre AS grupo_nombre,
            g.descripcion AS grupo_descripcion,
            g.regla_cumplimiento,
            g.minimo_documentos,
            g.orden AS grupo_orden,
            o.id AS opcion_id,
            o.documento_catalogo_id,
            o.rol_documental,
            o.etiqueta_requisito,
            o.descripcion_requisito,
            o.orden AS opcion_orden,
            d.codigo AS documento_codigo,
            d.nombre AS documento_nombre,
            d.categoria AS documento_categoria
        FROM config_grupos_requisitos_documentales g
        LEFT JOIN config_grupo_requisito_documentos o
          ON o.grupo_id = g.id
         AND o.activo = 1
        LEFT JOIN config_documentos_catalogo d
          ON d.id = o.documento_catalogo_id
         AND d.activo = 1
        WHERE g.tipo_expediente_id = ?
          AND g.activo = 1
          AND g.codigo NOT LIKE 'LEGACY_REQ_%'
          AND (
                g.subtipo_expediente_id IS NULL
                OR g.subtipo_expediente_id = ?
          )
        ORDER BY
            g.orden,
            g.id,
            o.orden,
            o.id
    """

    rows = conn.execute(
        sql,
        (
            tipo_id,
            subtipo_id if subtipo_id is not None else -1,
        ),
    ).fetchall()

    groups = {}

    for row in rows:
        group_id = int(row["grupo_id"])

        if group_id not in groups:
            groups[group_id] = {
                "grupo_id": group_id,
                "tipo_expediente_id": int(
                    row["tipo_expediente_id"]
                ),
                "subtipo_expediente_id": (
                    int(row["subtipo_expediente_id"])
                    if row["subtipo_expediente_id"] is not None
                    else None
                ),
                "codigo": row["grupo_codigo"],
                "nombre": row["grupo_nombre"],
                "descripcion": row["grupo_descripcion"],
                "regla_cumplimiento": _norm(
                    row["regla_cumplimiento"]
                ),
                "minimo_documentos": int(
                    row["minimo_documentos"] or 0
                ),
                "orden": int(row["grupo_orden"] or 0),
                "opciones": [],
            }

        if row["opcion_id"] is not None:
            groups[group_id]["opciones"].append(
                {
                    "opcion_id": int(row["opcion_id"]),
                    "documento_catalogo_id": int(
                        row["documento_catalogo_id"]
                    ),
                    "documento_codigo": row[
                        "documento_codigo"
                    ],
                    "documento_nombre": row[
                        "documento_nombre"
                    ],
                    "documento_categoria": row[
                        "documento_categoria"
                    ],
                    "rol_documental": (
                        _norm(row["rol_documental"])
                        or None
                    ),
                    "etiqueta_requisito": row[
                        "etiqueta_requisito"
                    ],
                    "descripcion_requisito": row[
                        "descripcion_requisito"
                    ],
                    "orden": int(row["opcion_orden"] or 0),
                }
            )

    return list(groups.values())


FAMILY_LINK_CONTEXT_KEY = (
    "vinculo_reagrupado_reagrupante"
)


def _normalize_context_text(value):
    text = _norm(value)

    replacements = {
        "Á": "A",
        "É": "E",
        "Í": "I",
        "Ó": "O",
        "Ú": "U",
        "Ü": "U",
        "Ñ": "N",
    }

    for source, target in replacements.items():
        text = text.replace(source, target)

    return " ".join(text.split())


def _family_link_profile(context):
    context = context or {}

    raw_value = context.get(
        FAMILY_LINK_CONTEXT_KEY
    )

    normalized = _normalize_context_text(
        raw_value
    )

    if not normalized:
        return {
            "valor_original": raw_value,
            "valor_normalizado": "",
            "estado": "SIN_CONTEXTO",
            "documentos_aplicables": None,
            "advertencia": (
                "No consta el vínculo entre la persona "
                "reagrupada y la persona reagrupante"
            ),
        }

    if normalized == "CONYUGE":
        return {
            "valor_original": raw_value,
            "valor_normalizado": normalized,
            "estado": "CONFIGURADO",
            "documentos_aplicables": {
                "CERTIFICADO_MATRIMONIO",
            },
            "advertencia": None,
        }

    if normalized.startswith("HIJO/A"):
        return {
            "valor_original": raw_value,
            "valor_normalizado": normalized,
            "estado": "CONFIGURADO_PARCIAL",
            "documentos_aplicables": {
                "ACTA_NACIMIENTO",
            },
            "advertencia": (
                "El vínculo exige acta de nacimiento; "
                "pueden existir requisitos adicionales "
                "según edad, discapacidad o supuesto."
            ),
        }

    return {
        "valor_original": raw_value,
        "valor_normalizado": normalized,
        "estado": "NO_CONFIGURADO",
        "documentos_aplicables": set(),
        "advertencia": (
            "El vínculo consta en el expediente, pero "
            "todavía no tiene reglas documentales "
            "específicas configuradas"
        ),
    }


def _apply_group_context(group, context):
    if _norm(group.get("codigo")) not in {
        "VINCULO",
        "VINCULO_FAMILIAR",
    }:
        return {
            **group,
            "filtro_contextual_aplicado": False,
            "contexto_incompleto": False,
            "contexto_documental": None,
        }

    profile = _family_link_profile(context)
    applicable = profile.get(
        "documentos_aplicables"
    )

    contextual_group = {
        **group,
        "contexto_documental": profile,
        "filtro_contextual_aplicado": (
            applicable is not None
        ),
        "contexto_incompleto": (
            profile["estado"]
            in {
                "SIN_CONTEXTO",
                "NO_CONFIGURADO",
            }
        ),
    }

    if applicable is None:
        return contextual_group

    contextual_group["opciones"] = [
        option
        for option in group["opciones"]
        if _norm(
            option.get("documento_codigo")
        ) in applicable
    ]

    return contextual_group


def _evaluate_option(option, detections):
    required_code = option["documento_codigo"]
    required_role = option["rol_documental"]

    code_matches = [
        detection
        for detection in detections
        if _codes_match(
            required_code,
            detection["codigo"],
        )
    ]

    if not code_matches:
        return {
            **option,
            "estado": "FALTANTE",
            "detectado": False,
            "ambiguo_por_rol": False,
            "detecciones_coincidentes": [],
        }

    if required_role is None:
        return {
            **option,
            "estado": "DETECTADO",
            "detectado": True,
            "ambiguo_por_rol": False,
            "detecciones_coincidentes": code_matches,
        }

    role_matches = [
        detection
        for detection in code_matches
        if detection.get("rol_documental")
        == required_role
    ]

    if role_matches:
        return {
            **option,
            "estado": "DETECTADO",
            "detectado": True,
            "ambiguo_por_rol": False,
            "detecciones_coincidentes": role_matches,
        }

    return {
        **option,
        "estado": "ROL_NO_ACREDITADO",
        "detectado": False,
        "ambiguo_por_rol": True,
        "detecciones_coincidentes": code_matches,
    }


def _evaluate_group(group, detections):
    rule = _norm(group["regla_cumplimiento"])

    if rule not in VALID_RULES:
        raise ValueError(
            f"Regla documental no válida: {rule}"
        )

    evaluated_options = [
        _evaluate_option(option, detections)
        for option in group["opciones"]
    ]

    detected_count = sum(
        1
        for option in evaluated_options
        if option["detectado"]
    )
    total_options = len(evaluated_options)
    ambiguous_count = sum(
        1
        for option in evaluated_options
        if option["ambiguo_por_rol"]
    )

    if rule == "ALL":
        required_count = total_options
        fulfilled = (
            total_options > 0
            and detected_count == total_options
        )

    elif rule == "ANY":
        required_count = 1
        fulfilled = detected_count >= 1

    elif rule == "AT_LEAST":
        required_count = int(
            group["minimo_documentos"] or 0
        )
        fulfilled = (
            required_count > 0
            and detected_count >= required_count
        )

    else:
        required_count = 0
        fulfilled = True

    if rule == "OPTIONAL":
        if detected_count == total_options and total_options:
            status = "OPCIONAL_COMPLETO"
        elif detected_count:
            status = "OPCIONAL_PARCIAL"
        elif ambiguous_count:
            status = "OPCIONAL_AMBIGUO"
        else:
            status = "OPCIONAL_NO_APORTADO"

    elif fulfilled:
        status = "CUMPLIDO"

    elif detected_count or ambiguous_count:
        status = "PARCIAL"

    else:
        status = "PENDIENTE"

    return {
        **group,
        "opciones": evaluated_options,
        "documentos_detectados": detected_count,
        "documentos_requeridos": required_count,
        "total_opciones": total_options,
        "opciones_ambiguas_por_rol": ambiguous_count,
        "cumplido": fulfilled,
        "bloquea_completitud": (
            rule != "OPTIONAL"
            and not fulfilled
        ),
        "estado": status,
    }


def evaluate_semantic_requirement_readiness(
    tipo_expediente_id,
    subtipo_expediente_id=None,
    detections=None,
    context=None,
):
    """
    Evalúa los grupos semánticos activos de un tipo/subtipo.

    `detections` admite:
        "PASAPORTE"

    o:
        {
            "codigo": "PASAPORTE",
            "rol_documental": "REAGRUPANTE",
            "archivo": "pasaporte_reagrupante.pdf",
        }
    """
    normalized_detections = [
        normalize_detection(detection)
        for detection in (detections or [])
    ]

    conn = _connect()

    try:
        groups = _load_active_groups(
            conn,
            tipo_expediente_id,
            subtipo_expediente_id,
        )
    finally:
        conn.close()

    context = dict(context or {})

    contextual_groups = [
        _apply_group_context(
            group,
            context,
        )
        for group in groups
    ]

    evaluated_groups = [
        _evaluate_group(
            group,
            normalized_detections,
        )
        for group in contextual_groups
    ]

    blocking_groups = [
        group
        for group in evaluated_groups
        if group["bloquea_completitud"]
    ]

    ambiguous_options = [
        option
        for group in evaluated_groups
        for option in group["opciones"]
        if option["ambiguo_por_rol"]
    ]

    return {
        "tipo_expediente_id": int(tipo_expediente_id),
        "subtipo_expediente_id": _int_or_none(
            subtipo_expediente_id
        ),
        "grupos": evaluated_groups,
        "total_grupos": len(evaluated_groups),
        "grupos_obligatorios": sum(
            1
            for group in evaluated_groups
            if group["regla_cumplimiento"] != "OPTIONAL"
        ),
        "grupos_cumplidos": sum(
            1
            for group in evaluated_groups
            if (
                group["regla_cumplimiento"] != "OPTIONAL"
                and group["cumplido"]
            )
        ),
        "grupos_bloqueantes": len(blocking_groups),
        "completo": (
            bool(evaluated_groups)
            and not blocking_groups
        ),
        "detecciones": normalized_detections,
        "contexto": context,
        "advertencias_contexto": [
            group["contexto_documental"]["advertencia"]
            for group in evaluated_groups
            if (
                group.get("contexto_documental")
                and group["contexto_documental"].get(
                    "advertencia"
                )
            )
        ],
        "opciones_ambiguas_por_rol": ambiguous_options,
    }
