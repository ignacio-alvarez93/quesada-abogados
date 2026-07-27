"""
Orquestación del primer caso de uso de correo:

- registrar el mensaje;
- detectar comunicación oficial de Extranjería;
- localizar el expediente por ID Mercurio;
- asignar el número oficial de forma segura;
- registrar trazabilidad;
- reconciliar el seguimiento de Notificaciones.
"""

import json

from backend.services import (
    notification_tracking_service,
)
from backend.services.email_platform import (
    email_message_service,
    schema_service,
)
from backend.services.email_platform.processors import (
    extranjeria_expedient_number_processor
    as processor,
)


def _text(value):
    return str(value or "").strip()


def _upper(value):
    return _text(value).upper()


def _upsert_processing_result(
    conn,
    *,
    email_message_id,
    status,
    confidence,
    extracted_data,
    matched_entity_id=None,
    action_code="",
    action_status="",
    review_reason="",
    error_message="",
):
    conn.execute(
        """
        INSERT INTO email_processing_results (
            email_message_id,
            processor_code,
            status,
            confidence,
            extracted_data_json,
            matched_entity_type,
            matched_entity_id,
            action_code,
            action_status,
            review_reason,
            error_message
        )
        VALUES (
            ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?
        )

        ON CONFLICT(
            email_message_id,
            processor_code
        )
        DO UPDATE SET
            status = excluded.status,
            confidence = excluded.confidence,
            extracted_data_json =
                excluded.extracted_data_json,
            matched_entity_type =
                excluded.matched_entity_type,
            matched_entity_id =
                excluded.matched_entity_id,
            action_code =
                excluded.action_code,
            action_status =
                excluded.action_status,
            review_reason =
                excluded.review_reason,
            error_message =
                excluded.error_message,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            int(email_message_id),
            processor.PROCESSOR_CODE,
            _upper(status),
            int(confidence or 0),
            json.dumps(
                extracted_data or {},
                ensure_ascii=False,
            ),
            (
                "expedientes"
                if matched_entity_id
                else ""
            ),
            matched_entity_id,
            _upper(action_code),
            _upper(action_status),
            _upper(review_reason),
            _text(error_message),
        ),
    )


def _find_expedient_candidates(
    conn,
    numero_presentacion_registro,
):
    identifier = _upper(
        numero_presentacion_registro
    )

    return [
        dict(row)
        for row in conn.execute(
            """
            SELECT
                e.id,
                e.cliente_id,
                e.numero_expediente,
                e.numero_expediente_mercurio,
                e.numero_presentacion_registro,
                e.numero_expediente_extranjeria,
                e.activo,

                c.nombre,
                c.primer_apellido,
                c.segundo_apellido

            FROM expedientes e

            JOIN clientes c
              ON c.id = e.cliente_id

            WHERE e.activo = 1
              AND (
                    UPPER(
                        TRIM(
                            COALESCE(
                                e.numero_presentacion_registro,
                                ''
                            )
                        )
                    ) = ?
                    OR
                    UPPER(
                        TRIM(
                            COALESCE(
                                e.numero_expediente_mercurio,
                                ''
                            )
                        )
                    ) = ?
              )

            ORDER BY e.id ASC
            """,
            (identifier, identifier),
        ).fetchall()
    ]


def _find_official_number_conflicts(
    conn,
    official_number,
    expediente_id,
):
    return [
        dict(row)
        for row in conn.execute(
            """
            SELECT
                id,
                numero_expediente,
                cliente_id
            FROM expedientes
            WHERE id != ?
              AND TRIM(
                    COALESCE(
                        numero_expediente_extranjeria,
                        ''
                    )
                  ) = ?
            ORDER BY id ASC
            """,
            (
                int(expediente_id),
                _text(official_number),
            ),
        ).fetchall()
    ]


def _client_full_name(expediente):
    return " ".join(
        [
            expediente.get("nombre") or "",
            expediente.get(
                "primer_apellido"
            )
            or "",
            expediente.get(
                "segundo_apellido"
            )
            or "",
        ]
    ).strip().upper()


def _assign_official_number(
    conn,
    *,
    expediente,
    email_message_id,
    extracted,
):
    expediente_id = int(expediente["id"])
    cliente_id = int(expediente["cliente_id"])

    official_number = _text(
        extracted.get(
            "numero_expediente_extranjeria"
        )
    )

    existing_number = _text(
        expediente.get(
            "numero_expediente_extranjeria"
        )
    )

    if (
        existing_number
        and existing_number != official_number
    ):
        return {
            "ok": False,
            "status": "REVIEW_REQUIRED",
            "reason":
                "EXPEDIENTE_CON_NUMERO_DIFERENTE",
        }

    conflicts = _find_official_number_conflicts(
        conn,
        official_number,
        expediente_id,
    )

    if conflicts:
        return {
            "ok": False,
            "status": "REVIEW_REQUIRED",
            "reason":
                "NUMERO_OFICIAL_ASIGNADO_A_OTRO_EXPEDIENTE",
            "conflicts": conflicts,
        }

    changed = not bool(existing_number)

    if changed:
        conn.execute(
            """
            UPDATE expedientes
            SET
                numero_expediente_extranjeria = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                official_number,
                expediente_id,
            ),
        )

        conn.execute(
            """
            INSERT INTO expediente_eventos (
                expediente_id,
                cliente_id,
                tipo_evento,
                titulo,
                descripcion,
                estado_anterior,
                estado_nuevo,
                entidad_relacionada,
                entidad_relacionada_id,
                usuario
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                expediente_id,
                cliente_id,
                "NUMERO_EXPEDIENTE_RECIBIDO_EMAIL",
                (
                    "NÚMERO DE EXPEDIENTE "
                    "RECIBIDO POR EMAIL"
                ),
                (
                    "Se ha recibido y vinculado el "
                    "número oficial de Extranjería.\n"
                    "ID Mercurio: "
                    + _text(
                        extracted.get(
                            "numero_presentacion_registro"
                        )
                    )
                    + ".\nNúmero oficial: "
                    + official_number
                    + ".\nInteresado comunicado: "
                    + _text(
                        extracted.get(
                            "nombre_interesado"
                        )
                    )
                    + "."
                ),
                existing_number,
                official_number,
                "email_messages",
                int(email_message_id),
                "EMAIL_WATCH",
            ),
        )

    return {
        "ok": True,
        "status": "APPLIED",
        "changed": changed,
        "expediente_id": expediente_id,
        "cliente_id": cliente_id,
        "numero_expediente_extranjeria":
            official_number,
    }


def process_message(message):
    """
    Registra y procesa un mensaje normalizado.

    Esta función es independiente del proveedor. IONOS IMAP y Gmail
    deberán transformarlo al mismo diccionario antes de invocarla.
    """
    schema_service.ensure_email_platform_schema()

    stored_result = (
        email_message_service.store_message(
            message
        )
    )

    stored = stored_result["message"]
    normalized = stored_result["normalized"]
    email_message_id = int(stored["id"])

    extraction_result = processor.extract(
        normalized
    )

    if (
        extraction_result["status"]
        != "EXTRACTED"
    ):
        with schema_service.connection() as conn:
            _upsert_processing_result(
                conn,
                email_message_id=email_message_id,
                status="IGNORED",
                confidence=0,
                extracted_data=(
                    extraction_result[
                        "extracted_data"
                    ]
                ),
                action_code="NO_ACTION",
                action_status="IGNORED",
                review_reason="|".join(
                    extraction_result.get(
                        "missing"
                    )
                    or []
                ),
            )

            email_message_service.update_processing_status(
                email_message_id,
                "IGNORED",
                conn=conn,
            )

        return {
            "ok": True,
            "created":
                stored_result["created"],
            "email_message_id":
                email_message_id,
            "processor_code":
                processor.PROCESSOR_CODE,
            "status": "IGNORED",
            "extraction":
                extraction_result,
        }

    extracted = extraction_result[
        "extracted_data"
    ]

    expediente_id = None
    assignment = None

    with schema_service.connection() as conn:
        candidates = _find_expedient_candidates(
            conn,
            extracted[
                "numero_presentacion_registro"
            ],
        )

        if len(candidates) == 0:
            _upsert_processing_result(
                conn,
                email_message_id=email_message_id,
                status="REVIEW_REQUIRED",
                confidence=(
                    extraction_result[
                        "confidence"
                    ]
                ),
                extracted_data=extracted,
                action_code=(
                    "ASSIGN_OFFICIAL_NUMBER"
                ),
                action_status="NOT_APPLIED",
                review_reason=(
                    "EXPEDIENTE_NO_ENCONTRADO"
                ),
            )

            email_message_service.update_processing_status(
                email_message_id,
                "REVIEW_REQUIRED",
                conn=conn,
            )

            return {
                "ok": True,
                "created":
                    stored_result["created"],
                "email_message_id":
                    email_message_id,
                "processor_code":
                    processor.PROCESSOR_CODE,
                "status":
                    "REVIEW_REQUIRED",
                "reason":
                    "EXPEDIENTE_NO_ENCONTRADO",
                "extracted_data": extracted,
                "candidates": [],
            }

        if len(candidates) > 1:
            _upsert_processing_result(
                conn,
                email_message_id=email_message_id,
                status="REVIEW_REQUIRED",
                confidence=(
                    extraction_result[
                        "confidence"
                    ]
                ),
                extracted_data=extracted,
                action_code=(
                    "ASSIGN_OFFICIAL_NUMBER"
                ),
                action_status="NOT_APPLIED",
                review_reason=(
                    "MULTIPLES_EXPEDIENTES_COINCIDENTES"
                ),
            )

            email_message_service.update_processing_status(
                email_message_id,
                "REVIEW_REQUIRED",
                conn=conn,
            )

            return {
                "ok": True,
                "created":
                    stored_result["created"],
                "email_message_id":
                    email_message_id,
                "processor_code":
                    processor.PROCESSOR_CODE,
                "status":
                    "REVIEW_REQUIRED",
                "reason":
                    "MULTIPLES_EXPEDIENTES_COINCIDENTES",
                "extracted_data": extracted,
                "candidates": candidates,
            }

        expediente = candidates[0]
        expediente_id = int(
            expediente["id"]
        )

        assignment = _assign_official_number(
            conn,
            expediente=expediente,
            email_message_id=email_message_id,
            extracted=extracted,
        )

        if not assignment["ok"]:
            _upsert_processing_result(
                conn,
                email_message_id=email_message_id,
                status="REVIEW_REQUIRED",
                confidence=(
                    extraction_result[
                        "confidence"
                    ]
                ),
                extracted_data=extracted,
                matched_entity_id=expediente_id,
                action_code=(
                    "ASSIGN_OFFICIAL_NUMBER"
                ),
                action_status="NOT_APPLIED",
                review_reason=(
                    assignment["reason"]
                ),
            )

            email_message_service.update_processing_status(
                email_message_id,
                "REVIEW_REQUIRED",
                conn=conn,
            )

            return {
                "ok": True,
                "created":
                    stored_result["created"],
                "email_message_id":
                    email_message_id,
                "processor_code":
                    processor.PROCESSOR_CODE,
                "status":
                    "REVIEW_REQUIRED",
                "reason":
                    assignment["reason"],
                "extracted_data": extracted,
                "expediente": expediente,
                "assignment": assignment,
            }

        _upsert_processing_result(
            conn,
            email_message_id=email_message_id,
            status="MATCHED",
            confidence=(
                extraction_result[
                    "confidence"
                ]
            ),
            extracted_data=extracted,
            matched_entity_id=expediente_id,
            action_code=(
                "ASSIGN_OFFICIAL_NUMBER"
            ),
            action_status=(
                "APPLIED"
                if assignment["changed"]
                else "ALREADY_APPLIED"
            ),
        )

        email_message_service.update_processing_status(
            email_message_id,
            "PROCESSED",
            conn=conn,
        )

    notification_result = (
        notification_tracking_service
        .reconcile_expedient(
            expediente_id,
            source=(
                "EMAIL:"
                + processor.PROCESSOR_CODE
            ),
            usuario="EMAIL_WATCH",
        )
    )

    return {
        "ok": True,
        "created":
            stored_result["created"],
        "email_message_id":
            email_message_id,
        "processor_code":
            processor.PROCESSOR_CODE,
        "status": "PROCESSED",
        "extracted_data": extracted,
        "expediente_id":
            expediente_id,
        "cliente_id":
            assignment["cliente_id"],
        "assignment": assignment,
        "notification_tracking":
            notification_result,
    }


def list_review_required(limit=100):
    schema_service.ensure_email_platform_schema()

    with schema_service.connection() as conn:
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT
                    r.*,
                    m.sender_email,
                    m.subject,
                    m.received_at,
                    m.body_text
                FROM email_processing_results r

                JOIN email_messages m
                  ON m.id = r.email_message_id

                WHERE r.status =
                    'REVIEW_REQUIRED'

                ORDER BY
                    COALESCE(
                        m.received_at,
                        m.created_at
                    ) DESC,
                    r.id DESC

                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        ]
