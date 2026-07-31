"""
Política de selección del motor de estado documental.

La política permite un despliegue gradual:

- LEGACY:
    conserva siempre el estado legacy.

- SEMANTIC_ELIGIBLE:
    utiliza el estado semántico únicamente en ámbitos
    expresamente autorizados y con cobertura válida.

En cualquier duda o error se aplica fallback legacy.
"""

import os


MODE_LEGACY = "LEGACY"
MODE_SEMANTIC_ELIGIBLE = "SEMANTIC_ELIGIBLE"

VALID_MODES = {
    MODE_LEGACY,
    MODE_SEMANTIC_ELIGIBLE,
}


SEMANTIC_ELIGIBLE_SCOPES = {
    (
        "NACIONALIDAD",
        "CASO_GENERAL",
    ),
    (
        "REAGRUPACION_FAMILIAR",
        "INICIAL",
    ),
    (
        "REGULARIZACION_MASIVA_TRANS_21",
        "INDIVIDUALES",
    ),
    (
        "RESIDENCIA_TEMPORAL_NO_LUCRATIVA",
        "RENOVACION_TITULAR",
    ),
}


def _norm(value):
    return str(value or "").strip().upper()


def normalize_mode(mode):
    normalized = _norm(mode) or MODE_LEGACY

    if normalized not in VALID_MODES:
        return MODE_LEGACY

    return normalized


def get_configured_mode(environ=None):
    """
    Obtiene el modo de despliegue desde el entorno.

    Ante ausencia o valor inválido siempre devuelve LEGACY.
    """
    source = (
        environ
        if environ is not None
        else os.environ
    )

    return normalize_mode(
        source.get(
            "DOCUMENT_STATE_ENGINE_MODE"
        )
    )


def normalize_scope(
    tipo_codigo,
    subtipo_codigo=None,
):
    return (
        _norm(tipo_codigo),
        _norm(subtipo_codigo) or "GENERAL",
    )


def _semantic_groups(readiness):
    return [
        group
        for group in (
            readiness.get("grupos", [])
            if readiness
            else []
        )
        if group.get("activo", True)
        and not _norm(
            group.get("codigo")
        ).startswith("LEGACY_REQ_")
    ]


def evaluate_semantic_eligibility(
    *,
    tipo_codigo,
    subtipo_codigo,
    semantic_readiness,
    semantic_decision,
    eligible_scopes=None,
):
    """
    Determina si el motor semántico puede ser vinculante.

    No selecciona todavía el estado; únicamente evalúa
    las condiciones de elegibilidad.
    """
    scopes = (
        set(eligible_scopes)
        if eligible_scopes is not None
        else SEMANTIC_ELIGIBLE_SCOPES
    )

    scope = normalize_scope(
        tipo_codigo,
        subtipo_codigo,
    )
    readiness = semantic_readiness or {}
    decision = semantic_decision or {}
    reasons = []

    scope_authorized = scope in scopes

    if not scope_authorized:
        reasons.append(
            "El tipo/subtipo no está autorizado "
            "para activación semántica"
        )

    readiness_available = bool(
        readiness.get("disponible")
    )

    if not readiness_available:
        reasons.append(
            "El evaluador semántico no está disponible"
        )

    if readiness.get("error"):
        reasons.append(
            "La evaluación semántica contiene un error"
        )

    groups = _semantic_groups(readiness)

    if not groups:
        reasons.append(
            "No existen grupos semánticos activos"
        )

    blocking_groups = [
        group
        for group in groups
        if _norm(
            group.get("regla_cumplimiento")
        ) != "OPTIONAL"
    ]

    if groups and not blocking_groups:
        reasons.append(
            "No existen grupos semánticos bloqueantes"
        )

    documentary_applicable = bool(
        decision.get(
            "aplicable_documental",
            decision.get("aplicable"),
        )
    )

    if not documentary_applicable:
        reasons.append(
            "La decisión documental semántica "
            "no es aplicable"
        )

    semantic_state = decision.get(
        "estado_sugerido"
    )

    if not semantic_state:
        reasons.append(
            "La decisión semántica no contiene estado"
        )

    eligible = all(
        [
            scope_authorized,
            readiness_available,
            not readiness.get("error"),
            bool(groups),
            bool(blocking_groups),
            documentary_applicable,
            bool(semantic_state),
        ]
    )

    return {
        "elegible": eligible,
        "scope": {
            "tipo_codigo": scope[0],
            "subtipo_codigo": scope[1],
        },
        "scope_autorizado": scope_authorized,
        "readiness_disponible": (
            readiness_available
        ),
        "grupos_semanticos": len(groups),
        "grupos_bloqueantes_configurados": len(
            blocking_groups
        ),
        "decision_documental_aplicable": (
            documentary_applicable
        ),
        "estado_semantico": semantic_state,
        "motivos_no_elegible": reasons,
    }


def select_document_state_engine(
    *,
    mode,
    legacy_state,
    tipo_codigo,
    subtipo_codigo,
    semantic_readiness,
    semantic_decision,
    eligible_scopes=None,
):
    """
    Selecciona el estado vinculante con fallback legacy.

    Nunca devuelve un estado vacío. Si la política no puede
    utilizar el motor semántico, conserva el estado legacy.
    """
    normalized_mode = normalize_mode(mode)

    eligibility = evaluate_semantic_eligibility(
        tipo_codigo=tipo_codigo,
        subtipo_codigo=subtipo_codigo,
        semantic_readiness=semantic_readiness,
        semantic_decision=semantic_decision,
        eligible_scopes=eligible_scopes,
    )

    use_semantic = (
        normalized_mode
        == MODE_SEMANTIC_ELIGIBLE
        and eligibility["elegible"]
    )

    if use_semantic:
        selected_engine = "SEMANTIC"
        selected_state = semantic_decision.get(
            "estado_sugerido"
        )
        fallback_applied = False
        reason = (
            "Motor semántico activado para un ámbito "
            "elegible y con cobertura válida"
        )
    else:
        selected_engine = "LEGACY"
        selected_state = legacy_state
        fallback_applied = (
            normalized_mode
            == MODE_SEMANTIC_ELIGIBLE
        )

        if normalized_mode == MODE_LEGACY:
            reason = (
                "La configuración mantiene activo "
                "el motor legacy"
            )
        else:
            reason = (
                "Se aplicó fallback legacy porque el "
                "ámbito no superó la política semántica"
            )

    return {
        "modo_configurado": normalized_mode,
        "motor_activo": selected_engine,
        "estado_seleccionado": selected_state,
        "estado_legacy": legacy_state,
        "estado_semantico": (
            semantic_decision.get(
                "estado_sugerido"
            )
            if semantic_decision
            else None
        ),
        "fallback_legacy_aplicado": (
            fallback_applied
        ),
        "motivo_seleccion": reason,
        "elegibilidad_semantica": eligibility,
    }
