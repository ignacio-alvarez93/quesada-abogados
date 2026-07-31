"""
Procesamiento semántico posterior a un escaneo documental.

Este servicio recibe los expedientes afectados por un escaneo,
calcula su diagnóstico y persiste snapshots y transiciones.

No escanea archivos.
No modifica documentos.
No modifica rutas Box.
No crea notificaciones visibles.
"""

from backend.services import (
    document_semantic_event_repository
    as event_repository,
)
from backend.services import (
    document_semantic_event_service
    as event_service,
)
from backend.services import (
    expedient_document_state_service
    as document_state_service,
)


def _normalize_expedient_ids(values):
    result = []

    for value in values or []:
        try:
            expediente_id = int(value or 0)
        except (TypeError, ValueError):
            continue

        if expediente_id <= 0:
            continue

        if expediente_id not in result:
            result.append(expediente_id)

    return result


def process_scanned_expedients(
    expedient_ids,
    *,
    source_scan_run_id=None,
    source_scan_job_id=None,
    diagnosis_provider=None,
    create_initial_events=False,
    conn=None,
    db_path=None,
):
    """
    Procesa una lista deduplicada de expedientes.

    Los fallos de un expediente se registran en el resultado,
    pero no impiden procesar los demás.
    """
    requested_values = list(
        expedient_ids or []
    )
    ids = _normalize_expedient_ids(
        requested_values
    )

    provider = (
        diagnosis_provider
        or document_state_service
        .diagnose_expediente_document_state
    )

    summary = {
        "requested": len(
            requested_values
        ),
        "unique_expedients": len(ids),
        "processed": 0,
        "changed": 0,
        "unchanged": 0,
        "events_created": 0,
        "events_skipped": 0,
        "errors": 0,
        "results": [],
    }

    owns_connection = conn is None
    connection = (
        conn
        or event_repository.open_connection(
            db_path
        )
    )

    try:
        for expediente_id in ids:
            savepoint = (
                f"semantic_exp_{expediente_id}"
            )

            connection.execute(
                f"SAVEPOINT {savepoint}"
            )

            try:
                diagnosis = provider(
                    expediente_id
                )

                result = (
                    event_service
                    .process_diagnosis(
                        diagnosis,
                        source_type=(
                            "BOX_WATCH_SCAN"
                        ),
                        source_scan_run_id=(
                            source_scan_run_id
                        ),
                        source_scan_job_id=(
                            source_scan_job_id
                        ),
                        create_initial_event=(
                            create_initial_events
                        ),
                        conn=connection,
                    )
                )

                connection.execute(
                    f"RELEASE SAVEPOINT {savepoint}"
                )

                summary["processed"] += 1

                if result["changed"]:
                    summary["changed"] += 1
                else:
                    summary["unchanged"] += 1

                event_result = result.get(
                    "event_result"
                )

                if (
                    event_result
                    and event_result.get(
                        "created"
                    )
                ):
                    summary[
                        "events_created"
                    ] += 1

                if result.get(
                    "event_skipped"
                ):
                    summary[
                        "events_skipped"
                    ] += 1

                summary["results"].append(
                    {
                        "expediente_id": (
                            expediente_id
                        ),
                        "ok": True,
                        "changed": result[
                            "changed"
                        ],
                        "event_created": bool(
                            event_result
                            and event_result.get(
                                "created"
                            )
                        ),
                        "event_type": (
                            event_result[
                                "event"
                            ].get("event_type")
                            if event_result
                            else None
                        ),
                    }
                )
            except Exception as exc:
                connection.execute(
                    f"ROLLBACK TO SAVEPOINT {savepoint}"
                )
                connection.execute(
                    f"RELEASE SAVEPOINT {savepoint}"
                )

                summary["errors"] += 1
                summary["results"].append(
                    {
                        "expediente_id": (
                            expediente_id
                        ),
                        "ok": False,
                        "error": str(exc),
                    }
                )

        if owns_connection:
            connection.commit()

        return summary
    except Exception:
        if owns_connection:
            connection.rollback()
        raise
    finally:
        if owns_connection:
            connection.close()
