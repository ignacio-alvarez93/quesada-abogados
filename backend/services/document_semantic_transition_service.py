"""
Construcción de snapshots y transiciones documentales semánticas.

Este servicio es puro:
- no abre SQLite;
- no toca Box;
- no crea notificaciones;
- no modifica expedientes;
- no modifica alertas.
"""

import hashlib
import json


EVENT_INITIAL_SNAPSHOT = "INITIAL_SNAPSHOT"
EVENT_DOCUMENT_COMPLETE = "DOCUMENT_COMPLETE"
EVENT_DOCUMENT_INCOMPLETE = "DOCUMENT_INCOMPLETE"
EVENT_DIAGNOSIS_AVAILABLE = "DIAGNOSIS_AVAILABLE"
EVENT_DIAGNOSIS_UNAVAILABLE = "DIAGNOSIS_UNAVAILABLE"
EVENT_ROLE_AMBIGUITY_CREATED = "ROLE_AMBIGUITY_CREATED"
EVENT_ROLE_AMBIGUITY_RESOLVED = "ROLE_AMBIGUITY_RESOLVED"
EVENT_DOCUMENT_DIAGNOSIS_CHANGED = (
    "DOCUMENT_DIAGNOSIS_CHANGED"
)


def _canonical_json(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _integer(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _semantic_group_summary(readiness):
    groups = []

    for group in (readiness or {}).get(
        "grupos",
        [],
    ):
        code = str(
            group.get("codigo") or ""
        ).strip().upper()

        if not code:
            continue

        if code.startswith("LEGACY_REQ_"):
            continue

        groups.append(
            {
                "codigo": code,
                "estado": group.get("estado"),
                "cumplido": bool(
                    group.get("cumplido")
                ),
                "bloquea_completitud": bool(
                    group.get(
                        "bloquea_completitud"
                    )
                ),
                "documentos_detectados": (
                    _integer(
                        group.get(
                            "documentos_detectados"
                        )
                    )
                ),
                "documentos_requeridos": (
                    _integer(
                        group.get(
                            "documentos_requeridos"
                        )
                    )
                ),
                "opciones_ambiguas_por_rol": (
                    _integer(
                        group.get(
                            "opciones_ambiguas_por_rol"
                        )
                    )
                ),
            }
        )

    return sorted(
        groups,
        key=lambda item: item["codigo"],
    )


def build_semantic_snapshot(diagnosis):
    """
    Convierte el diagnóstico completo en un snapshot estable.

    Se excluyen fechas de generación y mensajes circunstanciales
    para que la huella solo cambie cuando cambia el diagnóstico.
    """
    diagnosis = diagnosis or {}

    documentary = diagnosis.get(
        "estado_documental_semantico",
        {},
    )
    process = diagnosis.get(
        "estado_procesal_detectado",
        {},
    )
    combined = diagnosis.get(
        "decision_semantica",
        {},
    )
    readiness = diagnosis.get(
        "semantic_readiness",
        {},
    )
    role_summary = diagnosis.get(
        "resumen_inferencia_roles",
        {},
    )
    policy = diagnosis.get(
        "politica_motor_estado",
        {},
    )

    payload = {
        "expediente_id": _integer(
            diagnosis.get("expediente_id")
        ),
        "cliente_id": _integer(
            (
                diagnosis.get("expediente")
                or {}
            ).get("cliente_id")
        )
        or None,
        "estado_documental": (
            documentary.get(
                "estado_documental"
            )
            or "SIN_DIAGNOSTICO"
        ),
        "estado_procesal": (
            process.get("estado_procesal")
        ),
        "estado_combinado": (
            combined.get("estado_sugerido")
            or diagnosis.get("estado_sugerido")
        ),
        "semantico_aplicable": bool(
            documentary.get("aplicable")
        ),
        "motor_activo": (
            diagnosis.get(
                "motor_estado_activo"
            )
            or policy.get("motor_activo")
            or "LEGACY"
        ),
        "grupos_bloqueantes": _integer(
            readiness.get(
                "grupos_bloqueantes"
            )
        ),
        "ambiguedades_rol": (
            _integer(
                role_summary.get("ambiguos")
            )
            + len(
                readiness.get(
                    "opciones_ambiguas_por_rol",
                    [],
                )
            )
        ),
        "grupos": _semantic_group_summary(
            readiness
        ),
    }

    fingerprint = hashlib.sha256(
        _canonical_json(payload).encode(
            "utf-8"
        )
    ).hexdigest()

    return {
        **payload,
        "fingerprint": fingerprint,
        "diagnosis_json": _canonical_json(
            payload
        ),
    }


def _transition_type(previous, current):
    if previous is None:
        return EVENT_INITIAL_SNAPSHOT

    previous_applicable = bool(
        previous.get("semantico_aplicable")
    )
    current_applicable = bool(
        current.get("semantico_aplicable")
    )

    if (
        not previous_applicable
        and current_applicable
    ):
        return EVENT_DIAGNOSIS_AVAILABLE

    if (
        previous_applicable
        and not current_applicable
    ):
        return EVENT_DIAGNOSIS_UNAVAILABLE

    previous_state = previous.get(
        "estado_documental"
    )
    current_state = current.get(
        "estado_documental"
    )

    if (
        previous_state
        != "COMPLETO_SIN_PRESENTAR"
        and current_state
        == "COMPLETO_SIN_PRESENTAR"
    ):
        return EVENT_DOCUMENT_COMPLETE

    if (
        previous_state
        == "COMPLETO_SIN_PRESENTAR"
        and current_state
        == "PENDIENTE_DOCUMENTACION"
    ):
        return EVENT_DOCUMENT_INCOMPLETE

    previous_ambiguities = _integer(
        previous.get("ambiguedades_rol")
    )
    current_ambiguities = _integer(
        current.get("ambiguedades_rol")
    )

    if (
        previous_ambiguities == 0
        and current_ambiguities > 0
    ):
        return EVENT_ROLE_AMBIGUITY_CREATED

    if (
        previous_ambiguities > 0
        and current_ambiguities == 0
    ):
        return EVENT_ROLE_AMBIGUITY_RESOLVED

    return EVENT_DOCUMENT_DIAGNOSIS_CHANGED


def compare_semantic_snapshots(
    previous,
    current,
):
    """
    Devuelve una transición únicamente cuando cambia la huella.

    El snapshot inicial se registra, pero por defecto no debe
    convertirse todavía en una alerta visible.
    """
    if not current:
        raise ValueError(
            "El snapshot actual es obligatorio"
        )

    previous_fingerprint = (
        previous.get("fingerprint")
        if previous
        else None
    )
    current_fingerprint = current.get(
        "fingerprint"
    )

    if not current_fingerprint:
        raise ValueError(
            "El snapshot actual no tiene fingerprint"
        )

    if (
        previous_fingerprint
        == current_fingerprint
    ):
        return {
            "changed": False,
            "event": None,
        }

    event_type = _transition_type(
        previous,
        current,
    )

    expediente_id = _integer(
        current.get("expediente_id")
    )

    idempotency_payload = {
        "expediente_id": expediente_id,
        "event_type": event_type,
        "previous_fingerprint": (
            previous_fingerprint
        ),
        "new_fingerprint": (
            current_fingerprint
        ),
    }

    idempotency_key = hashlib.sha256(
        _canonical_json(
            idempotency_payload
        ).encode("utf-8")
    ).hexdigest()

    return {
        "changed": True,
        "event": {
            "expediente_id": expediente_id,
            "cliente_id": current.get(
                "cliente_id"
            ),
            "event_type": event_type,
            "previous_document_state": (
                previous.get(
                    "estado_documental"
                )
                if previous
                else None
            ),
            "new_document_state": (
                current.get(
                    "estado_documental"
                )
            ),
            "previous_process_state": (
                previous.get(
                    "estado_procesal"
                )
                if previous
                else None
            ),
            "new_process_state": current.get(
                "estado_procesal"
            ),
            "previous_fingerprint": (
                previous_fingerprint
            ),
            "new_fingerprint": (
                current_fingerprint
            ),
            "idempotency_key": (
                idempotency_key
            ),
        },
    }
