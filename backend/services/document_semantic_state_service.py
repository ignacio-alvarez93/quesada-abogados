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


def semantic_document_state(
    semantic_readiness,
    *,
    has_presentacion=False,
    has_requerimiento=False,
    has_concesion=False,
    has_denegacion=False,
):
    """
    Convierte readiness en una decisión documental paralela.

    Las señales procesales fuertes mantienen prioridad:
    denegación, concesión, requerimiento y presentación.
    """

    readiness = semantic_readiness or {}

    if not readiness.get("disponible"):
        return {
            "aplicable": False,
            "estado_sugerido": (
                ESTADO_SIN_DIAGNOSTICO
            ),
            "motivo": (
                "El evaluador semántico no está "
                "disponible"
            ),
            "fuente": "SEMANTIC_READINESS",
        }

    groups = readiness.get("grupos") or []

    active_groups = [
        group
        for group in groups
        if group.get("activo", True)
        and not str(
            group.get("codigo") or ""
        ).startswith("LEGACY_REQ_")
    ]

    if not active_groups:
        return {
            "aplicable": False,
            "estado_sugerido": (
                ESTADO_SIN_DIAGNOSTICO
            ),
            "motivo": (
                "No existen grupos semánticos activos "
                "aplicables"
            ),
            "fuente": "SEMANTIC_READINESS",
        }

    if has_denegacion:
        return {
            "aplicable": True,
            "estado_sugerido": "DENEGADO",
            "motivo": (
                "Se detectó una señal documental "
                "de denegación"
            ),
            "fuente": "SEMANTIC_PLUS_SIGNALS",
        }

    if has_concesion:
        return {
            "aplicable": True,
            "estado_sugerido": "CONCEDIDO",
            "motivo": (
                "Se detectó una señal documental "
                "de concesión"
            ),
            "fuente": "SEMANTIC_PLUS_SIGNALS",
        }

    if has_requerimiento:
        return {
            "aplicable": True,
            "estado_sugerido": "REQUERIDO",
            "motivo": (
                "Se detectó una señal documental "
                "de requerimiento"
            ),
            "fuente": "SEMANTIC_PLUS_SIGNALS",
        }

    if has_presentacion:
        return {
            "aplicable": True,
            "estado_sugerido": "PRESENTADO",
            "motivo": (
                "Se detectó una señal documental "
                "de presentación"
            ),
            "fuente": "SEMANTIC_PLUS_SIGNALS",
        }

    if readiness.get("completo") is True:
        return {
            "aplicable": True,
            "estado_sugerido": (
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
            for group in active_groups
            if group.get(
                "bloquea_completitud"
            )
            and not group.get("cumplido")
        )

    return {
        "aplicable": True,
        "estado_sugerido": (
            ESTADO_PENDIENTE_DOCUMENTACION
        ),
        "motivo": (
            f"Existen {int(blocking or 0)} "
            "grupo(s) semántico(s) bloqueante(s)"
        ),
        "fuente": "SEMANTIC_READINESS",
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
