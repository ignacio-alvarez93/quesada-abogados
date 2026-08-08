"""
Productor de TASK operativas derivadas de Trazabilidad.

Principio:
Trazabilidad es la fuente del hecho administrativo.
Calendar representa el trabajo derivado.

Reglas actuales:

    ADMISION_TRAMITE_TASA
        -> TASK "Aportar tasa"

    REQUERIMIENTO
        -> TASK "Atender requerimiento"

Los vencimientos automáticos son objetivos operativos
internos de gestión. No representan ni sustituyen el
cómputo de los plazos jurídicos del procedimiento.
"""

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

from backend.services import (
    calendar_task_application_service,
    task_service,
)


DEFAULT_DB_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "quesada.db"
)


ORIGEN_TIPO = "TRAZABILIDAD"

TAX_TASK_TYPE = "APORTACION_TASA"
TAX_TASK_TITLE = "Aportar tasa"

TAX_ADMISSION_EVENT = "ADMISION_TRAMITE_TASA"
TAX_SUBMISSION_EVENT = "JUSTIFICANTE_APORTACION_TASA"

TAX_SOURCE_PREFIX = (
    "TRACEABILITY:TASK:TAX:EXP:"
)


REQUIREMENT_TASK_TYPE = (
    "ATENCION_REQUERIMIENTO"
)

REQUIREMENT_TASK_TITLE = (
    "Atender requerimiento"
)

REQUIREMENT_EVENT = "REQUERIMIENTO"

DOCUMENT_SUBMISSION_EVENT = (
    "JUSTIFICANTE_APORTACION_DOCUMENTACION"
)

REQUIREMENT_SOURCE_PREFIX = (
    "TRACEABILITY:TASK:REQUIREMENT:EXP:"
)


def _text(value):
    return str(
        value or ""
    ).strip()


def _upper(value):
    return _text(value).upper()


def _connect(db_path=DEFAULT_DB_PATH):
    conn = sqlite3.connect(
        str(db_path),
        timeout=30,
    )

    conn.row_factory = sqlite3.Row

    conn.execute(
        "PRAGMA foreign_keys = ON"
    )

    conn.execute(
        "PRAGMA busy_timeout = 30000"
    )

    return conn


def build_tax_source_key(
    expediente_id,
):
    return (
        TAX_SOURCE_PREFIX
        + str(int(expediente_id))
    )


def build_requirement_source_key(
    expediente_id,
    requirement_document_id,
):
    return (
        REQUIREMENT_SOURCE_PREFIX
        + str(int(expediente_id))
        + ":REQ:"
        + str(int(requirement_document_id))
    )


def _load_expedient(
    expediente_id,
    *,
    db_path,
):
    with closing(
        _connect(db_path)
    ) as conn:
        row = conn.execute(
            """
            SELECT
                e.id,
                e.cliente_id,
                e.numero_expediente,
                e.responsable
            FROM expedientes e
            WHERE e.id = ?
            """,
            (
                int(expediente_id),
            ),
        ).fetchone()

        if not row:
            raise ValueError(
                "Expediente no encontrado."
            )

        return dict(row)


def _parse_metadata(row):
    raw = (
        row["metadata_documento_json"]
        if row
        else None
    )

    if not raw:
        return {}

    try:
        parsed = json.loads(raw)
    except (
        TypeError,
        ValueError,
    ):
        return {}

    return (
        parsed
        if isinstance(parsed, dict)
        else {}
    )


def _load_tax_documents(
    expediente_id,
    *,
    db_path,
):
    with closing(
        _connect(db_path)
    ) as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                tipo_justificante,
                metadata_documento_json,
                fecha_documento,
                fecha_presentacion,
                activo,
                created_at
            FROM expediente_justificantes
            WHERE expediente_id = ?
              AND activo = 1
              AND tipo_justificante IN (
                  'ADMISION_TRAMITE_TASA',
                  'JUSTIFICANTE_APORTACION_TASA'
              )
            ORDER BY
                created_at ASC,
                id ASC
            """,
            (
                int(expediente_id),
            ),
        ).fetchall()

    admission = None
    submission = None

    for row in rows:
        item = dict(row)

        if (
            item["tipo_justificante"]
            == TAX_ADMISSION_EVENT
        ):
            admission = item

        elif (
            item["tipo_justificante"]
            == TAX_SUBMISSION_EVENT
        ):
            submission = item

    return {
        "admission": admission,
        "submission": submission,
    }


def _find_task(
    expediente_id,
    *,
    db_path,
):
    source_key = build_tax_source_key(
        expediente_id
    )

    tasks = task_service.list_tasks(
        expediente_id=expediente_id,
        include_archived=True,
        db_path=db_path,
    )

    for task in tasks:
        if (
            _text(
                task.get("source_key")
            )
            == source_key
        ):
            return task

    return None


def _load_document(
    document_id,
    *,
    db_path,
):
    if document_id is None:
        return None

    with closing(
        _connect(db_path)
    ) as conn:
        row = conn.execute(
            """
            SELECT
                id,
                expediente_id,
                tipo_justificante,
                metadata_documento_json,
                fecha_documento,
                fecha_presentacion,
                activo,
                created_at
            FROM expediente_justificantes
            WHERE id = ?
            """,
            (
                int(document_id),
            ),
        ).fetchone()

    return (
        dict(row)
        if row
        else None
    )


def _find_requirement_task(
    expediente_id,
    requirement_document_id,
    *,
    db_path,
):
    source_key = (
        build_requirement_source_key(
            expediente_id,
            requirement_document_id,
        )
    )

    tasks = task_service.list_tasks(
        expediente_id=expediente_id,
        include_archived=True,
        db_path=db_path,
    )

    for task in tasks:
        if (
            _text(
                task.get("source_key")
            )
            == source_key
        ):
            return task

    return None


def _load_active_requirements(
    expediente_id,
    *,
    db_path,
):
    with closing(
        _connect(db_path)
    ) as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                expediente_id,
                tipo_justificante,
                metadata_documento_json,
                fecha_documento,
                fecha_presentacion,
                activo,
                created_at
            FROM expediente_justificantes
            WHERE expediente_id = ?
              AND activo = 1
              AND tipo_justificante = 'REQUERIMIENTO'
            ORDER BY
                created_at ASC,
                id ASC
            """,
            (
                int(expediente_id),
            ),
        ).fetchall()

    return [
        dict(row)
        for row in rows
    ]


def _persist_submission_requirement_link(
    submission_document_id,
    requirement_document_id,
    *,
    db_path,
):
    with closing(
        _connect(db_path)
    ) as conn:
        row = conn.execute(
            """
            SELECT metadata_documento_json
            FROM expediente_justificantes
            WHERE id = ?
            """,
            (
                int(submission_document_id),
            ),
        ).fetchone()

        if not row:
            raise ValueError(
                "Justificante de aportación "
                "no encontrado."
            )

        try:
            metadata = json.loads(
                row[
                    "metadata_documento_json"
                ]
                or "{}"
            )
        except (
            TypeError,
            ValueError,
        ):
            metadata = {}

        if not isinstance(
            metadata,
            dict,
        ):
            metadata = {}

        metadata[
            "requerimiento_documento_id"
        ] = int(
            requirement_document_id
        )

        conn.execute(
            """
            UPDATE expediente_justificantes
            SET
                metadata_documento_json = ?,
                updated_at =
                    CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                json.dumps(
                    metadata,
                    ensure_ascii=False,
                ),
                int(
                    submission_document_id
                ),
            ),
        )

        conn.commit()


def _open_requirement_candidates(
    expediente_id,
    *,
    db_path,
):
    candidates = []

    for requirement in (
        _load_active_requirements(
            expediente_id,
            db_path=db_path,
        )
    ):
        task = _find_requirement_task(
            expediente_id,
            requirement["id"],
            db_path=db_path,
        )

        if not task:
            continue

        if _upper(
            task.get("estado")
        ) in {
            "COMPLETADA",
            "CANCELADA",
        }:
            continue

        candidates.append(
            {
                "requirement":
                    requirement,
                "task":
                    task,
            }
        )

    return candidates


def _has_active_submission_for_requirement(
    expediente_id,
    requirement_document_id,
    *,
    db_path,
):
    with closing(
        _connect(db_path)
    ) as conn:
        rows = conn.execute(
            """
            SELECT
                metadata_documento_json
            FROM expediente_justificantes
            WHERE expediente_id = ?
              AND activo = 1
              AND tipo_justificante =
                  'JUSTIFICANTE_APORTACION_DOCUMENTACION'
            """,
            (
                int(expediente_id),
            ),
        ).fetchall()

    for row in rows:
        try:
            metadata = json.loads(
                row[
                    "metadata_documento_json"
                ]
                or "{}"
            )
        except (
            TypeError,
            ValueError,
        ):
            continue

        if not isinstance(
            metadata,
            dict,
        ):
            continue

        linked_id = metadata.get(
            "requerimiento_documento_id"
        )

        if linked_id is None:
            continue

        try:
            linked_id = int(
                linked_id
            )
        except (
            TypeError,
            ValueError,
        ):
            continue

        if (
            linked_id
            == int(
                requirement_document_id
            )
        ):
            return True

    return False


def _default_requirement_due_at(
    requirement,
):
    metadata = _parse_metadata(
        requirement
    )

    base_value = (
        metadata.get(
            "fecha_requerimiento"
        )
        or requirement.get(
            "fecha_documento"
        )
        or requirement.get(
            "fecha_presentacion"
        )
        or requirement.get(
            "created_at"
        )
        or ""
    )

    parsed = None

    if base_value:
        try:
            parsed = datetime.fromisoformat(
                str(base_value).replace(
                    "T",
                    " ",
                )
            )
        except ValueError:
            parsed = None

    if parsed is None:
        parsed = datetime.now()

    due_at = (
        parsed
        + timedelta(days=10)
    ).replace(
        hour=12,
        minute=0,
        second=0,
        microsecond=0,
    )

    return due_at.strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def _build_requirement_description(
    metadata,
):
    parts = [
        (
            "Atender requerimiento administrativo "
            "del expediente."
        )
    ]

    documents = _text(
        metadata.get(
            "documentacion_requerida_abogado"
        )
        or metadata.get(
            "documentacion_requerida_original"
        )
    )

    if documents:
        parts.append(
            "Documentación requerida: "
            + documents
        )

    plazo = metadata.get(
        "plazo_dias"
    )

    if plazo is not None:
        parts.append(
            "Plazo detectado en el documento: "
            + str(plazo)
            + " días."
        )

    csv_value = _text(
        metadata.get(
            "csv_requerimiento"
        )
    )

    if csv_value:
        parts.append(
            "CSV: "
            + csv_value
            + "."
        )

    parts.append(
        (
            "El vencimiento de Calendar es "
            "un objetivo operativo interno, "
            "no un cómputo jurídico."
        )
    )

    return " ".join(parts)


def sync_requirement_obligation(
    expediente_id,
    *,
    event_code,
    document_id,
    due_at=None,
    usuario="ERP",
    db_path=DEFAULT_DB_PATH,
):
    """
    Proyecta un requerimiento concreto sobre Calendar.

    Cada REQUERIMIENTO genera su propia TASK mediante
    una source_key que incorpora el justificante_id.
    """
    expediente_id = int(
        expediente_id
    )

    normalized_event = _upper(
        event_code
    )

    if normalized_event not in {
        REQUIREMENT_EVENT,
        DOCUMENT_SUBMISSION_EVENT,
    }:
        return {
            "ok": True,
            "action": "NO_APLICABLE",
            "task": None,
        }

    document = _load_document(
        document_id,
        db_path=db_path,
    )

    if not document:
        return {
            "ok": False,
            "action": "DOCUMENT_NOT_FOUND",
            "task": None,
        }

    if (
        int(document["expediente_id"])
        != expediente_id
    ):
        raise ValueError(
            "El documento no pertenece "
            "al expediente."
        )

    # -----------------------------------------------------
    # Primera fase:
    # REQUERIMIENTO -> TASK individual.
    # -----------------------------------------------------
    if normalized_event == REQUIREMENT_EVENT:
        existing = _find_requirement_task(
            expediente_id,
            document["id"],
            db_path=db_path,
        )

        # Al archivar el requerimiento, se cancela
        # únicamente su TASK.
        if not bool(document.get("activo")):
            if not existing:
                return {
                    "ok": True,
                    "action": "NO_TASK",
                    "task": None,
                }

            if _upper(
                existing.get("estado")
            ) == "CANCELADA":
                return {
                    "ok": True,
                    "action": "UNCHANGED",
                    "task": existing,
                }

            task = (
                calendar_task_application_service
                .cancel_calendar_task(
                    existing["id"],
                    db_path=db_path,
                )
            )

            return {
                "ok": True,
                "action": "CANCELLED",
                "task": task,
            }

        metadata = _parse_metadata(
            document
        )

        if existing:
            return {
                "ok": True,
                "action": "UNCHANGED",
                "task": existing,
            }

        confirmed_due_at = (
            _text(due_at)
            or _default_requirement_due_at(
                document
            )
        )

        expediente = _load_expedient(
            expediente_id,
            db_path=db_path,
        )

        result = (
            calendar_task_application_service
            .create_calendar_task(
                titulo=REQUIREMENT_TASK_TITLE,
                fecha_vencimiento=confirmed_due_at,
                descripcion=(
                    _build_requirement_description(
                        metadata
                    )
                ),
                cliente_id=(
                    expediente["cliente_id"]
                ),
                expediente_id=expediente_id,
                tipo=REQUIREMENT_TASK_TYPE,
                prioridad="ALTA",
                responsable=(
                    expediente.get(
                        "responsable"
                    )
                    or ""
                ),
                origen_tipo=ORIGEN_TIPO,
                origen_id=str(
                    document["id"]
                ),
                source_key=(
                    build_requirement_source_key(
                        expediente_id,
                        document["id"],
                    )
                ),
                created_by=usuario,
                db_path=db_path,
            )
        )

        return {
            "ok": True,
            "action": (
                "CREATED"
                if result["created"]
                else "UNCHANGED"
            ),
            "task": result["task"],
            "notifications":
                result["notifications"],
            "due_date_source":
                "OPERATIONAL_DEFAULT",
        }

    # -----------------------------------------------------
    # APORTACIÓN DE DOCUMENTACIÓN
    # -----------------------------------------------------

    submission_metadata = _parse_metadata(
        document
    )

    linked_requirement_id = (
        submission_metadata.get(
            "requerimiento_documento_id"
        )
    )

    # -----------------------------------------------------
    # Archivado de una aportación ya vinculada.
    # No reabrimos silenciosamente con la fecha anterior.
    # -----------------------------------------------------

    if not bool(
        document.get("activo")
    ):
        if not linked_requirement_id:
            return {
                "ok": True,
                "action":
                    "UNMATCHED_ARCHIVED_SUBMISSION",
                "task": None,
            }

        requirement = _load_document(
            linked_requirement_id,
            db_path=db_path,
        )

        if (
            not requirement
            or int(
                requirement[
                    "expediente_id"
                ]
            ) != expediente_id
        ):
            return {
                "ok": False,
                "action":
                    "REQUIREMENT_NOT_FOUND",
                "task": None,
            }

        task = _find_requirement_task(
            expediente_id,
            linked_requirement_id,
            db_path=db_path,
        )

        if not task:
            return {
                "ok": True,
                "action": "NO_TASK",
                "task": None,
                "requirement_document_id":
                    int(
                        linked_requirement_id
                    ),
            }

        if _upper(
            task.get("estado")
        ) == "COMPLETADA":
            return {
                "ok": True,
                "action":
                    "NEEDS_DUE_DATE_FOR_REOPEN",
                "task": task,
                "requires_due_date": True,
                "requirement_document_id":
                    int(
                        linked_requirement_id
                    ),
            }

        return {
            "ok": True,
            "action": "UNCHANGED",
            "task": task,
            "requires_due_date": False,
            "requirement_document_id":
                int(
                    linked_requirement_id
                ),
        }

    # -----------------------------------------------------
    # Vínculo explícito ya presente en metadata.
    # -----------------------------------------------------

    if linked_requirement_id:
        requirement = _load_document(
            linked_requirement_id,
            db_path=db_path,
        )

        if (
            not requirement
            or int(
                requirement[
                    "expediente_id"
                ]
            ) != expediente_id
            or _upper(
                requirement[
                    "tipo_justificante"
                ]
            ) != REQUIREMENT_EVENT
        ):
            return {
                "ok": False,
                "action":
                    "INVALID_REQUIREMENT_LINK",
                "task": None,
            }

        requirement_id = int(
            linked_requirement_id
        )

    else:
        # -------------------------------------------------
        # Sin vínculo explícito:
        # solo automatizamos si hay exactamente
        # un requerimiento pendiente.
        # -------------------------------------------------

        candidates = (
            _open_requirement_candidates(
                expediente_id,
                db_path=db_path,
            )
        )

        if not candidates:
            return {
                "ok": True,
                "action":
                    "NO_OPEN_REQUIREMENT",
                "task": None,
            }

        if len(candidates) > 1:
            return {
                "ok": True,
                "action":
                    "AMBIGUOUS_REQUIREMENT",
                "task": None,
                "candidate_requirement_ids": [
                    int(
                        candidate[
                            "requirement"
                        ]["id"]
                    )
                    for candidate
                    in candidates
                ],
            }

        requirement_id = int(
            candidates[0][
                "requirement"
            ]["id"]
        )

        _persist_submission_requirement_link(
            document["id"],
            requirement_id,
            db_path=db_path,
        )

    task = _find_requirement_task(
        expediente_id,
        requirement_id,
        db_path=db_path,
    )

    # Resiliencia:
    # si existe el requerimiento pero no su TASK,
    # intentamos proyectarla antes de completar.
    if not task:
        requirement_sync = (
            sync_requirement_obligation(
                expediente_id,
                event_code=REQUIREMENT_EVENT,
                document_id=requirement_id,
                usuario=usuario,
                db_path=db_path,
            )
        )

        task = requirement_sync.get(
            "task"
        )

    if not task:
        return {
            "ok": False,
            "action":
                "REQUIREMENT_TASK_NOT_FOUND",
            "task": None,
            "requirement_document_id":
                requirement_id,
        }

    if _upper(
        task.get("estado")
    ) == "COMPLETADA":
        return {
            "ok": True,
            "action": "UNCHANGED",
            "task": task,
            "requirement_document_id":
                requirement_id,
        }

    completed_task = (
        calendar_task_application_service
        .complete_calendar_task(
            task["id"],
            db_path=db_path,
        )
    )

    return {
        "ok": True,
        "action": "COMPLETED",
        "task": completed_task,
        "requirement_document_id":
            requirement_id,
    }


def get_requirement_obligation_status(
    expediente_id,
    requirement_document_id,
    *,
    db_path=DEFAULT_DB_PATH,
):
    """
    Consulta pura del estado Calendar asociado a
    un requerimiento administrativo concreto.

    No crea, completa, reabre ni cancela tareas.
    """
    expediente_id = int(
        expediente_id
    )
    requirement_document_id = int(
        requirement_document_id
    )

    requirement = _load_document(
        requirement_document_id,
        db_path=db_path,
    )

    if not requirement:
        return {
            "ok": False,
            "status": "REQUIREMENT_NOT_FOUND",
            "task": None,
            "requirement_document_id":
                requirement_document_id,
        }

    if (
        int(
            requirement["expediente_id"]
        )
        != expediente_id
    ):
        return {
            "ok": False,
            "status": "INVALID_REQUIREMENT",
            "task": None,
            "requirement_document_id":
                requirement_document_id,
        }

    if (
        _upper(
            requirement[
                "tipo_justificante"
            ]
        )
        != REQUIREMENT_EVENT
    ):
        return {
            "ok": False,
            "status": "INVALID_REQUIREMENT",
            "task": None,
            "requirement_document_id":
                requirement_document_id,
        }

    task = _find_requirement_task(
        expediente_id,
        requirement_document_id,
        db_path=db_path,
    )

    if not bool(
        requirement.get("activo")
    ):
        return {
            "ok": True,
            "status": "REQUIREMENT_ARCHIVED",
            "task": task,
            "requirement_document_id":
                requirement_document_id,
        }

    if not task:
        return {
            "ok": True,
            "status": "TASK_NOT_CREATED",
            "task": None,
            "requirement_document_id":
                requirement_document_id,
        }

    state = _upper(
        task.get("estado")
    )

    has_active_submission = (
        _has_active_submission_for_requirement(
            expediente_id,
            requirement_document_id,
            db_path=db_path,
        )
    )

    if has_active_submission:
        return {
            "ok": True,
            "status": "SATISFIED",
            "task": task,
            "requirement_document_id":
                requirement_document_id,
        }

    if state in {
        "COMPLETADA",
        "CANCELADA",
    }:
        return {
            "ok": True,
            "status":
                "NEEDS_DUE_DATE_FOR_REOPEN",
            "task": task,
            "requires_due_date": True,
            "requirement_document_id":
                requirement_document_id,
        }

    return {
        "ok": True,
        "status": "TASK_ACTIVE",
        "task": task,
        "requirement_document_id":
            requirement_document_id,
    }


def confirm_requirement_due_date(
    expediente_id,
    requirement_document_id,
    due_at,
    *,
    usuario="ERP",
    db_path=DEFAULT_DB_PATH,
):
    """
    Confirma un vencimiento operativo para un
    requerimiento concreto.

    Si su TASK está COMPLETADA o CANCELADA,
    actualiza la fecha y reabre la misma TASK.

    No calcula ni representa el plazo jurídico.
    """
    expediente_id = int(
        expediente_id
    )

    requirement_document_id = int(
        requirement_document_id
    )

    clean_due_at = _text(
        due_at
    )

    if not clean_due_at:
        raise ValueError(
            "La fecha límite es obligatoria."
        )

    try:
        parsed_due_at = datetime.fromisoformat(
            clean_due_at.replace(
                "T",
                " ",
            )
        )
    except ValueError as exc:
        raise ValueError(
            "La fecha límite no tiene "
            "un formato válido."
        ) from exc

    normalized_due_at = (
        parsed_due_at.strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    )

    requirement = _load_document(
        requirement_document_id,
        db_path=db_path,
    )

    if not requirement:
        raise ValueError(
            "Requerimiento no encontrado."
        )

    if (
        int(
            requirement["expediente_id"]
        )
        != expediente_id
    ):
        raise ValueError(
            "El requerimiento no pertenece "
            "al expediente."
        )

    if (
        _upper(
            requirement[
                "tipo_justificante"
            ]
        )
        != REQUIREMENT_EVENT
    ):
        raise ValueError(
            "El documento indicado "
            "no es un requerimiento."
        )

    if not bool(
        requirement.get("activo")
    ):
        raise ValueError(
            "El requerimiento está archivado."
        )

    if (
        _has_active_submission_for_requirement(
            expediente_id,
            requirement_document_id,
            db_path=db_path,
        )
    ):
        raise ValueError(
            "El requerimiento ya está atendido "
            "por una aportación activa."
        )

    existing = _find_requirement_task(
        expediente_id,
        requirement_document_id,
        db_path=db_path,
    )

    metadata = _parse_metadata(
        requirement
    )

    if not existing:
        result = (
            sync_requirement_obligation(
                expediente_id,
                event_code=REQUIREMENT_EVENT,
                document_id=(
                    requirement_document_id
                ),
                due_at=normalized_due_at,
                usuario=usuario,
                db_path=db_path,
            )
        )

        return {
            **result,
            "confirmed_due_at":
                normalized_due_at,
        }

    update = (
        calendar_task_application_service
        .update_calendar_task(
            existing["id"],
            fecha_vencimiento=(
                normalized_due_at
            ),
            descripcion=(
                _build_requirement_description(
                    metadata
                )
            ),
            db_path=db_path,
        )
    )

    state = _upper(
        existing.get("estado")
    )

    if state in {
        "COMPLETADA",
        "CANCELADA",
    }:
        reopened = (
            calendar_task_application_service
            .reopen_calendar_task(
                existing["id"],
                db_path=db_path,
            )
        )

        return {
            "ok": True,
            "action": "REOPENED",
            "task": reopened["task"],
            "notifications":
                reopened["notifications"],
            "requirement_document_id":
                requirement_document_id,
            "confirmed_due_at":
                normalized_due_at,
        }

    return {
        "ok": True,
        "action": "UPDATED",
        "task": update["task"],
        "requirement_document_id":
            requirement_document_id,
        "confirmed_due_at":
            normalized_due_at,
    }


def _default_tax_due_at(
    admission,
):
    """
    Vencimiento OPERATIVO interno para la tarea
    de aportar tasa.

    No representa ni calcula el plazo jurídico.
    Objetivo del despacho: completar la actuación
    cuanto antes, con referencia de 10 días naturales.
    """
    base_value = (
        admission.get("fecha_documento")
        or admission.get("fecha_presentacion")
        or admission.get("created_at")
        or ""
    )

    parsed = None

    if base_value:
        try:
            parsed = datetime.fromisoformat(
                str(base_value).replace(
                    "T",
                    " ",
                )
            )
        except ValueError:
            parsed = None

    if parsed is None:
        parsed = datetime.now()

    due_at = parsed + timedelta(
        days=10
    )

    # Hora operativa estándar.
    due_at = due_at.replace(
        hour=12,
        minute=0,
        second=0,
        microsecond=0,
    )

    return due_at.strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def _build_description(
    metadata,
):
    parts = [
        (
            "La admisión a trámite "
            "requiere aportación de tasa."
        )
    ]

    modelo = _text(
        metadata.get("tasa_modelo")
    )

    codigo = _text(
        metadata.get("tasa_codigo")
    )

    apartado = _text(
        metadata.get("tasa_apartado")
    )

    importe_centimos = (
        metadata.get(
            "tasa_importe_centimos"
        )
    )

    plazo_pago = (
        metadata.get(
            "plazo_pago_dias_habiles"
        )
    )

    plazo_aportacion = (
        metadata.get(
            "plazo_aportacion_dias"
        )
    )

    if modelo or codigo:
        tasa = "Tasa"

        if modelo:
            tasa += f" {modelo}"

        if codigo:
            tasa += f" código {codigo}"

        if apartado:
            tasa += f" apartado {apartado}"

        parts.append(
            tasa + "."
        )

    if (
        importe_centimos
        is not None
    ):
        try:
            importe = (
                int(importe_centimos)
                / 100
            )

            parts.append(
                "Importe detectado: "
                f"{importe:.2f} €."
            )

        except (
            TypeError,
            ValueError,
        ):
            pass

    if plazo_pago:
        parts.append(
            "Plazo textual detectado "
            "para pago: "
            f"{plazo_pago} días hábiles."
        )

    if plazo_aportacion:
        parts.append(
            "Plazo textual detectado "
            "para aportación: "
            f"{plazo_aportacion} días."
        )

    return " ".join(parts)


def get_tax_obligation_status(
    expediente_id,
    *,
    db_path=DEFAULT_DB_PATH,
):
    """
    Devuelve una proyección de SOLO LECTURA del estado
    operativo de la obligación de aportar tasa.

    No crea, actualiza, completa, cancela, reabre ni
    programa TASKS.
    """
    expediente_id = int(
        expediente_id
    )

    _load_expedient(
        expediente_id,
        db_path=db_path,
    )

    documents = _load_tax_documents(
        expediente_id,
        db_path=db_path,
    )

    admission = documents["admission"]
    submission = documents["submission"]

    existing = _find_task(
        expediente_id,
        db_path=db_path,
    )

    if not admission:
        return {
            "ok": True,
            "status": "NO_OBLIGATION",
            "obligation_exists": False,
            "satisfied": False,
            "requires_due_date": False,
            "task": existing,
            "metadata": {},
            "admission": None,
            "submission": submission,
        }

    metadata = _parse_metadata(
        admission
    )

    tasa_requerida = metadata.get(
        "tasa_requerida"
    )

    if tasa_requerida is False:
        return {
            "ok": True,
            "status": "NO_OBLIGATION",
            "obligation_exists": False,
            "satisfied": False,
            "requires_due_date": False,
            "task": existing,
            "metadata": metadata,
            "admission": admission,
            "submission": submission,
        }

    if submission:
        return {
            "ok": True,
            "status": "SATISFIED",
            "obligation_exists": True,
            "satisfied": True,
            "requires_due_date": False,
            "task": existing,
            "metadata": metadata,
            "admission": admission,
            "submission": submission,
        }

    if not existing:
        return {
            "ok": True,
            "status": "TASK_NOT_CREATED",
            "obligation_exists": True,
            "satisfied": False,
            "requires_due_date": False,
            "task": None,
            "metadata": metadata,
            "admission": admission,
            "submission": None,
        }

    state = _upper(
        existing.get("estado")
    )

    if state in {
        "COMPLETADA",
        "CANCELADA",
    }:
        return {
            "ok": True,
            "status": "NEEDS_DUE_DATE_FOR_REOPEN",
            "obligation_exists": True,
            "satisfied": False,
            "requires_due_date": True,
            "task": existing,
            "metadata": metadata,
            "admission": admission,
            "submission": None,
        }

    return {
        "ok": True,
        "status": "TASK_ACTIVE",
        "obligation_exists": True,
        "satisfied": False,
        "requires_due_date": False,
        "task": existing,
        "metadata": metadata,
        "admission": admission,
        "submission": None,
    }


def confirm_tax_due_date(
    expediente_id,
    due_at,
    *,
    usuario="ERP",
    db_path=DEFAULT_DB_PATH,
):
    """
    Confirma expresamente la fecha límite de la obligación
    de tasa y sincroniza su TASK de Calendar.

    No calcula plazos: due_at debe proceder de una
    confirmación explícita.
    """
    clean_due_at = _text(
        due_at
    )

    if not clean_due_at:
        raise ValueError(
            "La fecha límite es obligatoria."
        )

    try:
        parsed_due_at = datetime.fromisoformat(
            clean_due_at.replace(
                "T",
                " ",
            )
        )
    except ValueError as exc:
        raise ValueError(
            "La fecha límite no tiene un formato válido."
        ) from exc

    normalized_due_at = (
        parsed_due_at.strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    )

    snapshot = (
        get_tax_obligation_status(
            expediente_id,
            db_path=db_path,
        )
    )

    if not snapshot[
        "obligation_exists"
    ]:
        raise ValueError(
            "El expediente no tiene una obligación "
            "activa de aportar tasa."
        )

    if snapshot["satisfied"]:
        raise ValueError(
            "La obligación de tasa ya está satisfecha."
        )

    result = sync_tax_obligation(
        expediente_id,
        due_at=normalized_due_at,
        usuario=usuario,
        db_path=db_path,
    )

    return {
        **result,
        "confirmed_due_at":
            normalized_due_at,
    }


def sync_tax_obligation(
    expediente_id,
    *,
    due_at=None,
    usuario="ERP",
    db_path=DEFAULT_DB_PATH,
):
    """
    Sincroniza la obligación operativa de aportar tasa.

    due_at:
        Fecha límite CONFIRMADA por usuario o por una
        fuente futura suficientemente fiable.

        El productor nunca la calcula a partir de un
        plazo textual.
    """

    expediente_id = int(
        expediente_id
    )

    expediente = _load_expedient(
        expediente_id,
        db_path=db_path,
    )

    documents = _load_tax_documents(
        expediente_id,
        db_path=db_path,
    )

    admission = documents[
        "admission"
    ]

    submission = documents[
        "submission"
    ]

    existing = _find_task(
        expediente_id,
        db_path=db_path,
    )

    # -----------------------------------------------------
    # Ya no existe una admisión que genere la obligación.
    # -----------------------------------------------------

    if not admission:
        if not existing:
            return {
                "ok": True,
                "action": "NO_OBLIGATION",
                "task": None,
            }

        if _upper(
            existing.get("estado")
        ) == "CANCELADA":
            return {
                "ok": True,
                "action": "UNCHANGED",
                "task": existing,
            }

        task = (
            calendar_task_application_service
            .cancel_calendar_task(
                existing["id"],
                db_path=db_path,
            )
        )

        return {
            "ok": True,
            "action": "CANCELLED",
            "task": task,
        }

    metadata = _parse_metadata(
        admission
    )

    tasa_requerida = (
        metadata.get(
            "tasa_requerida"
        )
    )

    # ADMISION_TRAMITE_TASA ya constituye una señal
    # canónica de obligación. Si metadata incluye un
    # booleano explícito False, prevalece la evidencia.
    if tasa_requerida is False:
        if not existing:
            return {
                "ok": True,
                "action": "NO_OBLIGATION",
                "task": None,
            }

        if _upper(
            existing.get("estado")
        ) == "CANCELADA":
            return {
                "ok": True,
                "action": "UNCHANGED",
                "task": existing,
            }

        task = (
            calendar_task_application_service
            .cancel_calendar_task(
                existing["id"],
                db_path=db_path,
            )
        )

        return {
            "ok": True,
            "action": "CANCELLED",
            "task": task,
        }

    # -----------------------------------------------------
    # Existe justificante real de aportación.
    # -----------------------------------------------------

    if submission:
        if not existing:
            return {
                "ok": True,
                "action": "ALREADY_SATISFIED",
                "task": None,
            }

        if _upper(
            existing.get("estado")
        ) == "COMPLETADA":
            return {
                "ok": True,
                "action": "UNCHANGED",
                "task": existing,
            }

        task = (
            calendar_task_application_service
            .complete_calendar_task(
                existing["id"],
                db_path=db_path,
            )
        )

        return {
            "ok": True,
            "action": "COMPLETED",
            "task": task,
        }

    # -----------------------------------------------------
    # Existe obligación pendiente pero no hay vencimiento
    # confirmado. No se inventa.
    # -----------------------------------------------------

    if not _text(due_at):
        if existing:
            state = _upper(
                existing.get("estado")
            )

            if state in {
                "COMPLETADA",
                "CANCELADA",
            }:
                return {
                    "ok": True,
                    "action":
                        "NEEDS_DUE_DATE_FOR_REOPEN",
                    "task": existing,
                    "requires_due_date": True,
                    "metadata": metadata,
                }

            return {
                "ok": True,
                "action": "UNCHANGED",
                "task": existing,
                "requires_due_date": False,
                "metadata": metadata,
            }

        due_at = _default_tax_due_at(
            admission
        )

        result = (
            calendar_task_application_service
            .create_calendar_task(
                titulo=TAX_TASK_TITLE,
                fecha_vencimiento=due_at,
                descripcion=(
                    _build_description(
                        metadata
                    )
                ),
                cliente_id=(
                    expediente[
                        "cliente_id"
                    ]
                ),
                expediente_id=(
                    expediente_id
                ),
                tipo=TAX_TASK_TYPE,
                prioridad="ALTA",
                responsable=(
                    expediente.get(
                        "responsable"
                    )
                    or ""
                ),
                origen_tipo=ORIGEN_TIPO,
                origen_id=str(
                    admission["id"]
                ),
                source_key=(
                    build_tax_source_key(
                        expediente_id
                    )
                ),
                created_by=usuario,
                db_path=db_path,
            )
        )

        return {
            "ok": True,
            "action": (
                "CREATED"
                if result["created"]
                else "UNCHANGED"
            ),
            "task": result["task"],
            "notifications":
                result["notifications"],
            "requires_due_date": False,
            "metadata": metadata,
            "due_date_source":
                "OPERATIONAL_DEFAULT",
        }

    # -----------------------------------------------------
    # Crear o reabrir la obligación con fecha confirmada.
    # -----------------------------------------------------

    if existing:
        state = _upper(
            existing.get("estado")
        )

        if state in {
            "COMPLETADA",
            "CANCELADA",
        }:
            update = (
                calendar_task_application_service
                .update_calendar_task(
                    existing["id"],
                    fecha_vencimiento=due_at,
                    descripcion=(
                        _build_description(
                            metadata
                        )
                    ),
                    db_path=db_path,
                )
            )

            result = (
                calendar_task_application_service
                .reopen_calendar_task(
                    existing["id"],
                    db_path=db_path,
                )
            )

            return {
                "ok": True,
                "action": "REOPENED",
                "task": result["task"],
                "notifications":
                    result["notifications"],
            }

        update = (
            calendar_task_application_service
            .update_calendar_task(
                existing["id"],
                fecha_vencimiento=due_at,
                descripcion=(
                    _build_description(
                        metadata
                    )
                ),
                db_path=db_path,
            )
        )

        return {
            "ok": True,
            "action": "UPDATED",
            "task": update["task"],
        }

    result = (
        calendar_task_application_service
        .create_calendar_task(
            titulo=TAX_TASK_TITLE,
            fecha_vencimiento=due_at,
            descripcion=(
                _build_description(
                    metadata
                )
            ),
            cliente_id=(
                expediente[
                    "cliente_id"
                ]
            ),
            expediente_id=(
                expediente_id
            ),
            tipo=TAX_TASK_TYPE,
            prioridad="ALTA",
            responsable=(
                expediente.get(
                    "responsable"
                )
                or ""
            ),
            origen_tipo=ORIGEN_TIPO,
            origen_id=str(
                admission["id"]
            ),
            source_key=(
                build_tax_source_key(
                    expediente_id
                )
            ),
            created_by=usuario,
            db_path=db_path,
        )
    )

    return {
        "ok": True,
        "action": (
            "CREATED"
            if result["created"]
            else "UNCHANGED"
        ),
        "task": result["task"],
        "notifications":
            result["notifications"],
    }
