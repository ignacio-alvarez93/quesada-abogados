"""
Traducción del resultado de readiness a un estado documental.

Esta capa:
- no consulta ni modifica la base de datos;
- no toca Box;
- no crea alertas;
- no sustituye directamente el estado legacy;
- explica si el diagnóstico semántico es aplicable.
"""


ESTADO_SIN_DIAGNOSTICO = "SIN_DIAGNOSTICO"
ESTADO_PENDIENTE_DOCUMENTACION = (
    "PENDIENTE_DOCUMENTACION"
)
ESTADO_COMPLETO_SIN_PRESENTAR = (
    "COMPLETO_SIN_PRESENTAR"
)


def semantic_document_completeness(
    semantic_readiness,
):
    """
    Traduce readiness exclusivamente a estado documental.

    No toma en consideración presentación, requerimiento,
    concesión ni denegación.
    """
    readiness = semantic_readiness or {}

    if not readiness.get("disponible"):
        return {
            "aplicable": False,
            "estado_documental": (
                ESTADO_SIN_DIAGNOSTICO
            ),
            "motivo": (
                "El evaluador semántico no está disponible"
            ),
            "fuente": "SEMANTIC_READINESS",
        }

    groups = [
        group
        for group in readiness.get("grupos", [])
        if group.get("activo", True)
        and not str(
            group.get("codigo") or ""
        ).startswith("LEGACY_REQ_")
    ]

    if not groups:
        return {
            "aplicable": False,
            "estado_documental": (
                ESTADO_SIN_DIAGNOSTICO
            ),
            "motivo": (
                "No existen grupos semánticos activos "
                "aplicables"
            ),
            "fuente": "SEMANTIC_READINESS",
        }

    if readiness.get("completo") is True:
        return {
            "aplicable": True,
            "estado_documental": (
                ESTADO_COMPLETO_SIN_PRESENTAR
            ),
            "motivo": (
                "Todos los grupos semánticos "
                "bloqueantes están satisfechos"
            ),
            "fuente": "SEMANTIC_READINESS",
        }

    blocking = readiness.get(
        "grupos_bloqueantes"
    )

    if blocking is None:
        blocking = sum(
            1
            for group in groups
            if group.get(
                "bloquea_completitud"
            )
            and not group.get("cumplido")
        )

    return {
        "aplicable": True,
        "estado_documental": (
            ESTADO_PENDIENTE_DOCUMENTACION
        ),
        "motivo": (
            f"Existen {int(blocking or 0)} "
            "grupo(s) semántico(s) bloqueante(s)"
        ),
        "fuente": "SEMANTIC_READINESS",
    }


def process_state_from_signals(
    *,
    has_presentacion=False,
    has_requerimiento=False,
    has_concesion=False,
    has_denegacion=False,
):
    """
    Determina exclusivamente el estado procesal detectado.
    """
    if has_denegacion:
        return {
            "estado_procesal": "DENEGADO",
            "detectado": True,
            "motivo": (
                "Se detectó una señal documental "
                "de denegación"
            ),
        }

    if has_concesion:
        return {
            "estado_procesal": "CONCEDIDO",
            "detectado": True,
            "motivo": (
                "Se detectó una señal documental "
                "de concesión"
            ),
        }

    if has_requerimiento:
        return {
            "estado_procesal": "REQUERIDO",
            "detectado": True,
            "motivo": (
                "Se detectó una señal documental "
                "de requerimiento"
            ),
        }

    if has_presentacion:
        return {
            "estado_procesal": "PRESENTADO",
            "detectado": True,
            "motivo": (
                "Se detectó una señal documental "
                "de presentación"
            ),
        }

    return {
        "estado_procesal": None,
        "detectado": False,
        "motivo": (
            "No se detectaron señales procesales fuertes"
        ),
    }


def semantic_document_state(
    semantic_readiness,
    *,
    has_presentacion=False,
    has_requerimiento=False,
    has_concesion=False,
    has_denegacion=False,
):
    """
    Compone el estado procesal y el documental.

    Prioridades:
    1. señal procesal fuerte;
    2. resultado de completitud documental;
    3. ausencia controlada de diagnóstico.

    La falta de grupos semánticos no puede ocultar una
    presentación, un requerimiento, una concesión o una
    denegación detectada.
    """
    process = process_state_from_signals(
        has_presentacion=has_presentacion,
        has_requerimiento=has_requerimiento,
        has_concesion=has_concesion,
        has_denegacion=has_denegacion,
    )

    documentary = semantic_document_completeness(
        semantic_readiness
    )

    if process["detectado"]:
        return {
            "aplicable": True,
            "aplicable_documental": bool(
                documentary.get("aplicable")
            ),
            "estado_sugerido": process[
                "estado_procesal"
            ],
            "estado_procesal": process[
                "estado_procesal"
            ],
            "estado_documental": documentary.get(
                "estado_documental"
            ),
            "motivo": process.get("motivo"),
            "motivo_documental": documentary.get(
                "motivo"
            ),
            "fuente": "SEMANTIC_PLUS_SIGNALS",
        }

    return {
        "aplicable": bool(
            documentary.get("aplicable")
        ),
        "aplicable_documental": bool(
            documentary.get("aplicable")
        ),
        "estado_sugerido": documentary.get(
            "estado_documental",
            ESTADO_SIN_DIAGNOSTICO,
        ),
        "estado_procesal": None,
        "estado_documental": documentary.get(
            "estado_documental"
        ),
        "motivo": documentary.get("motivo"),
        "motivo_documental": documentary.get(
            "motivo"
        ),
        "fuente": documentary.get(
            "fuente",
            "SEMANTIC_READINESS",
        ),
    }



def compare_document_states(
    legacy_state,
    semantic_decision,
):
    """
    Compara ambos motores sin decidir cuál debe prevalecer.
    """
    semantic = semantic_decision or {}
    semantic_state = semantic.get(
        "estado_sugerido"
    )
    applicable = bool(
        semantic.get("aplicable")
    )

    return {
        "motor_activo": "LEGACY",
        "legacy_estado": legacy_state,
        "semantic_estado": semantic_state,
        "semantic_aplicable": applicable,
        "coincide": (
            applicable
            and legacy_state == semantic_state
        ),
        "divergencia": (
            applicable
            and legacy_state != semantic_state
        ),
        "motivo_semantico": semantic.get(
            "motivo"
        ),
    }
