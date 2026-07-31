"""
Coordinación de diagnósticos, snapshots y eventos semánticos.

Este servicio:
- recibe un diagnóstico ya calculado;
- construye el snapshot;
- compara con el snapshot almacenado;
- registra una transición idempotente;
- actualiza el snapshot.

No escanea Box.
No crea notificaciones visibles.
No modifica el estado del expediente.
"""

from backend.services import (
    document_semantic_event_repository
    as event_repository,
)
from backend.services import (
    document_semantic_transition_service
    as transition_service,
)


EVENT_PRESENTATION = {
    transition_service.EVENT_INITIAL_SNAPSHOT: {
        "severity": "INFO",
        "title": "Diagnóstico documental inicial",
    },
    transition_service.EVENT_DOCUMENT_COMPLETE: {
        "severity": "INFO",
        "title": "Documentación completa",
    },
    transition_service.EVENT_DOCUMENT_INCOMPLETE: {
        "severity": "HIGH",
        "title": "Documentación incompleta",
    },
    transition_service.EVENT_DIAGNOSIS_AVAILABLE: {
        "severity": "INFO",
        "title": "Diagnóstico documental disponible",
    },
    transition_service.EVENT_DIAGNOSIS_UNAVAILABLE: {
        "severity": "MEDIUM",
        "title": "Diagnóstico documental no disponible",
    },
    transition_service.EVENT_ROLE_AMBIGUITY_CREATED: {
        "severity": "MEDIUM",
        "title": "Ambigüedad documental detectada",
    },
    transition_service.EVENT_ROLE_AMBIGUITY_RESOLVED: {
        "severity": "INFO",
        "title": "Ambigüedad documental resuelta",
    },
    transition_service.EVENT_DOCUMENT_DIAGNOSIS_CHANGED: {
        "severity": "INFO",
        "title": "Diagnóstico documental actualizado",
    },
}


def _event_presentation(event):
    config = EVENT_PRESENTATION.get(
        event.get("event_type"),
        {
            "severity": "INFO",
            "title": "Cambio documental semántico",
        },
    )

    previous_state = (
        event.get("previous_document_state")
        or "SIN SNAPSHOT"
    )
    new_state = (
        event.get("new_document_state")
        or "SIN_DIAGNOSTICO"
    )

    description = (
        f"El estado documental pasó de "
        f"{previous_state} a {new_state}."
    )

    return {
        "severity": config["severity"],
        "title": config["title"],
        "description": description,
    }


def _process_diagnosis_in_connection(
    diagnosis,
    *,
    source_type="MANUAL_DIAGNOSIS",
    source_scan_run_id=None,
    source_scan_job_id=None,
    create_initial_event=False,
    conn,
):
    """
    Procesa atómicamente un diagnóstico.

    El primer diagnóstico siempre crea snapshot, pero el evento
    INITIAL_SNAPSHOT solo se persiste cuando se solicita de forma
    explícita. Así se evita inundar el sistema al inicializarlo.
    """
    current_snapshot = (
        transition_service
        .build_semantic_snapshot(
            diagnosis
        )
    )

    expediente_id = int(
        current_snapshot.get("expediente_id")
        or 0
    )

    if not expediente_id:
        raise ValueError(
            "El diagnóstico no contiene expediente_id"
        )

    previous_snapshot = (
        event_repository.get_snapshot(
            expediente_id,
            conn=conn,
        )
    )

    comparison = (
        transition_service
        .compare_semantic_snapshots(
            previous_snapshot,
            current_snapshot,
        )
    )

    event_result = None
    event_skipped = False

    if comparison["changed"]:
        event = comparison["event"]

        is_initial = (
            event.get("event_type")
            == transition_service
            .EVENT_INITIAL_SNAPSHOT
        )

        if is_initial and not create_initial_event:
            event_skipped = True
        else:
            presentation = _event_presentation(
                event
            )

            event_result = (
                event_repository.insert_event(
                    event,
                    source_type=source_type,
                    source_scan_run_id=(
                        source_scan_run_id
                    ),
                    source_scan_job_id=(
                        source_scan_job_id
                    ),
                    title=presentation["title"],
                    description=(
                        presentation["description"]
                    ),
                    severity=(
                        presentation["severity"]
                    ),
                    metadata={
                        "motor_activo": (
                            current_snapshot.get(
                                "motor_activo"
                            )
                        ),
                        "grupos_bloqueantes": (
                            current_snapshot.get(
                                "grupos_bloqueantes"
                            )
                        ),
                        "ambiguedades_rol": (
                            current_snapshot.get(
                                "ambiguedades_rol"
                            )
                        ),
                    },
                    conn=conn,
                )
            )

    stored_snapshot = (
        event_repository.upsert_snapshot(
            current_snapshot,
            source_type=source_type,
            source_scan_run_id=(
                source_scan_run_id
            ),
            source_scan_job_id=(
                source_scan_job_id
            ),
            conn=conn,
        )
    )

    return {
        "expediente_id": expediente_id,
        "changed": comparison["changed"],
        "event_skipped": event_skipped,
        "event_result": event_result,
        "previous_snapshot": previous_snapshot,
        "current_snapshot": stored_snapshot,
    }

def process_diagnosis(
    diagnosis,
    *,
    source_type="MANUAL_DIAGNOSIS",
    source_scan_run_id=None,
    source_scan_job_id=None,
    create_initial_event=False,
    conn=None,
    db_path=None,
):
    """
    Procesa un diagnóstico en una única transacción.

    Si se recibe una conexión externa:
    - no confirma;
    - no revierte;
    - no cierra la conexión.

    Si no se recibe conexión:
    - abre una conexión;
    - confirma todas las operaciones juntas;
    - revierte todo ante cualquier error.
    """
    if conn is not None:
        return _process_diagnosis_in_connection(
            diagnosis,
            source_type=source_type,
            source_scan_run_id=(
                source_scan_run_id
            ),
            source_scan_job_id=(
                source_scan_job_id
            ),
            create_initial_event=(
                create_initial_event
            ),
            conn=conn,
        )

    connection = (
        event_repository.open_connection(
            db_path
        )
    )

    try:
        result = (
            _process_diagnosis_in_connection(
                diagnosis,
                source_type=source_type,
                source_scan_run_id=(
                    source_scan_run_id
                ),
                source_scan_job_id=(
                    source_scan_job_id
                ),
                create_initial_event=(
                    create_initial_event
                ),
                conn=connection,
            )
        )
        connection.commit()
        return result
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

