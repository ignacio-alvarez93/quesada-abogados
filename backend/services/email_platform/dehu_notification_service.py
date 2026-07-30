"""
Persistencia y vinculación provisional de avisos DEHú recibidos por email.

La coincidencia inicial se realiza exclusivamente contra
expedientes.numero_expediente_extranjeria.

La verificación definitiva exigirá contrastar posteriormente el número
observado en el portal DEHú.
"""

import json

from backend.services.email_platform import (
    email_message_service,
    official_reference_resolver,
    schema_service,
)
from backend.services.email_platform.processors import (
    dehu_notification_notice_processor
    as processor,
)


PORTAL_STATUS_UNKNOWN = "UNKNOWN"

VERIFICATION_EMAIL_ONLY = "EMAIL_ONLY"
VERIFICATION_MATCHED_PROVISIONAL = (
    "MATCHED_PROVISIONAL"
)
VERIFICATION_EXPEDIENT_NOT_FOUND = (
    "EXPEDIENT_NOT_FOUND"
)
VERIFICATION_MULTIPLE_EXPEDIENTS = (
    "MULTIPLE_EXPEDIENTS"
)

VERIFICATION_REFERENCE_DETECTED_FAMILY_NOT_AVAILABLE = (
    "REFERENCE_DETECTED_FAMILY_NOT_AVAILABLE"
)

DOWNLOAD_NOT_REQUESTED = "NOT_REQUESTED"


def _text(value):
    return str(value or "").strip()


def _upper(value):
    return _text(value).upper()


def _table_columns(conn, table_name):
    return {
        str(row["name"])
        for row in conn.execute(
            f"PRAGMA table_info({table_name})"
        ).fetchall()
    }


def _ensure_column(
    conn,
    *,
    table_name,
    column_name,
    definition,
):
    columns = _table_columns(
        conn,
        table_name,
    )

    if column_name in columns:
        return False

    conn.execute(
        f"""
        ALTER TABLE {table_name}
        ADD COLUMN {column_name} {definition}
        """
    )

    return True


def ensure_dehu_schema(conn=None):
    with schema_service.connection(conn) as current:
        current.execute(
            """
            CREATE TABLE IF NOT EXISTS
                dehu_notifications (
                    id INTEGER PRIMARY KEY
                        AUTOINCREMENT,

                    dehu_identifier TEXT NOT NULL
                        UNIQUE,
                    concept TEXT,

                    item_type TEXT NOT NULL
                        DEFAULT 'UNKNOWN',
                    concept_type TEXT NOT NULL
                        DEFAULT 'UNKNOWN',

                    reference_value TEXT,
                    reference_type TEXT NOT NULL
                        DEFAULT 'UNKNOWN',
                    family_hint TEXT NOT NULL
                        DEFAULT 'UNKNOWN',

                    direct_access_url TEXT,

                    email_expedient_number TEXT,
                    dehu_expedient_number TEXT,

                    expediente_id INTEGER,
                    cliente_id INTEGER,

                    primary_email_message_id INTEGER,

                    recipient_name TEXT,
                    recipient_document_masked TEXT,

                    issuer_name TEXT,
                    issuer_dir3 TEXT,
                    relationship_type TEXT,

                    deadline_at TEXT,

                    portal_status TEXT NOT NULL
                        DEFAULT 'UNKNOWN',
                    verification_status TEXT NOT NULL
                        DEFAULT 'EMAIL_ONLY',
                    download_status TEXT NOT NULL
                        DEFAULT 'NOT_REQUESTED',

                    document_inbox_batch_id INTEGER,

                    first_seen_at TEXT NOT NULL
                        DEFAULT CURRENT_TIMESTAMP,
                    last_seen_at TEXT NOT NULL
                        DEFAULT CURRENT_TIMESTAMP,

                    accepted_at TEXT,
                    rejected_at TEXT,
                    downloaded_at TEXT,

                    last_error TEXT,

                    raw_email_data_json TEXT,
                    raw_dehu_data_json TEXT,

                    created_at TEXT NOT NULL
                        DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL
                        DEFAULT CURRENT_TIMESTAMP,

                    FOREIGN KEY (expediente_id)
                        REFERENCES expedientes(id),
                    FOREIGN KEY (cliente_id)
                        REFERENCES clientes(id),
                    FOREIGN KEY (
                        primary_email_message_id
                    )
                        REFERENCES email_messages(id)
                )
            """
        )

        current.execute(
            """
            CREATE TABLE IF NOT EXISTS
                dehu_notification_email_sources (
                    id INTEGER PRIMARY KEY
                        AUTOINCREMENT,

                    dehu_notification_id INTEGER
                        NOT NULL,
                    email_message_id INTEGER
                        NOT NULL,
                    provider TEXT,
                    account_id INTEGER,
                    source_folder TEXT,

                    detected_at TEXT NOT NULL
                        DEFAULT CURRENT_TIMESTAMP,

                    FOREIGN KEY (
                        dehu_notification_id
                    )
                        REFERENCES
                            dehu_notifications(id),

                    FOREIGN KEY (email_message_id)
                        REFERENCES email_messages(id),

                    UNIQUE(
                        dehu_notification_id,
                        email_message_id
                    )
                )
            """
        )

        _ensure_column(
            current,
            table_name="dehu_notifications",
            column_name="item_type",
            definition=(
                "TEXT NOT NULL DEFAULT 'UNKNOWN'"
            ),
        )

        _ensure_column(
            current,
            table_name="dehu_notifications",
            column_name="concept_type",
            definition=(
                "TEXT NOT NULL DEFAULT 'UNKNOWN'"
            ),
        )

        _ensure_column(
            current,
            table_name="dehu_notifications",
            column_name="reference_value",
            definition="TEXT",
        )

        _ensure_column(
            current,
            table_name="dehu_notifications",
            column_name="reference_type",
            definition=(
                "TEXT NOT NULL DEFAULT 'UNKNOWN'"
            ),
        )

        _ensure_column(
            current,
            table_name="dehu_notifications",
            column_name="family_hint",
            definition=(
                "TEXT NOT NULL DEFAULT 'UNKNOWN'"
            ),
        )

        _ensure_column(
            current,
            table_name="dehu_notifications",
            column_name="direct_access_url",
            definition="TEXT",
        )


        _ensure_column(
            current,
            table_name="dehu_notifications",
            column_name="procedural_event_code",
            definition="TEXT",
        )

        _ensure_column(
            current,
            table_name="dehu_notifications",
            column_name="procedural_event_label",
            definition="TEXT",
        )

        _ensure_column(
            current,
            table_name="dehu_notifications",
            column_name="classification_status",
            definition=(
                "TEXT NOT NULL DEFAULT 'UNCLASSIFIED'"
            ),
        )

        _ensure_column(
            current,
            table_name="dehu_notifications",
            column_name="classification_source",
            definition="TEXT",
        )

        _ensure_column(
            current,
            table_name="dehu_notifications",
            column_name="confirmed_event_id",
            definition="INTEGER",
        )

        _ensure_column(
            current,
            table_name="dehu_notifications",
            column_name="confirmed_justificante_id",
            definition="INTEGER",
        )

        _ensure_column(
            current,
            table_name="dehu_notifications",
            column_name="classification_confirmed_at",
            definition="TEXT",
        )

        _ensure_column(
            current,
            table_name="dehu_notifications",
            column_name="classification_confirmed_by",
            definition="TEXT",
        )

        _ensure_column(
            current,
            table_name="dehu_notifications",
            column_name="dehu_receipt_path",
            definition="TEXT",
        )

        _ensure_column(
            current,
            table_name="dehu_notifications",
            column_name="dehu_receipt_name",
            definition="TEXT",
        )

        _ensure_column(
            current,
            table_name="dehu_notifications",
            column_name="dehu_receipt_metadata_json",
            definition="TEXT",
        )

        _ensure_column(
            current,
            table_name=(
                "dehu_notification_email_sources"
            ),
            column_name="source_folder",
            definition="TEXT",
        )

        current.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_dehu_notification_item_type
            ON dehu_notifications(item_type)
            """
        )

        current.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_dehu_notification_reference
            ON dehu_notifications(
                reference_type,
                reference_value
            )
            """
        )

        current.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_dehu_notification_family
            ON dehu_notifications(
                family_hint,
                verification_status
            )
            """
        )

        current.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_dehu_source_origin
            ON dehu_notification_email_sources(
                provider,
                account_id,
                source_folder
            )
            """
        )

        current.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_dehu_notification_expedient
            ON dehu_notifications(expediente_id)
            """
        )

        current.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_dehu_notification_number
            ON dehu_notifications(
                email_expedient_number
            )
            """
        )

        current.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_dehu_notification_status
            ON dehu_notifications(
                portal_status,
                verification_status,
                download_status
            )
            """
        )

        current.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_dehu_notification_deadline
            ON dehu_notifications(deadline_at)
            """
        )


def _upsert_processing_result(
    conn,
    *,
    email_message_id,
    status,
    confidence,
    extracted_data,
    matched_entity_id=None,
    action_status="",
    review_reason="",
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
            ?, ?, ?, ?, ?, ''
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
            error_message = '',
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
            (
                "REGISTER_DEHU_COMMUNICATION"
                if _upper(
                    (extracted_data or {}).get(
                        "item_type"
                    )
                ) == "COMMUNICATION"
                else "REGISTER_DEHU_NOTIFICATION"
            ),
            _upper(action_status),
            _upper(review_reason),
        ),
    )


def _register_expedient_event(
    conn,
    *,
    notification_id,
    email_message_id,
    expediente,
    extracted,
):
    item_type = _upper(
        extracted.get("item_type")
        or "UNKNOWN"
    )

    is_communication = (
        item_type == "COMMUNICATION"
    )

    event_type = (
        "DEHU_COMMUNICATION_NOTICE_RECEIVED"
        if is_communication
        else "DEHU_NOTIFICATION_NOTICE_RECEIVED"
    )

    event_title = (
        "AVISO DE COMUNICACIÓN DEHÚ RECIBIDO"
        if is_communication
        else "AVISO DE NOTIFICACIÓN DEHÚ RECIBIDO"
    )

    item_label = (
        "comunicación"
        if is_communication
        else "notificación"
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
            int(expediente["id"]),
            int(expediente["cliente_id"]),
            event_type,
            event_title,
            (
                "Se ha recibido un aviso de "
                + item_label
                + " DEHú.\n"
                "Identificador: "
                + _text(
                    extracted.get(
                        "dehu_identifier"
                    )
                )
                + ".\nConcepto: "
                + _text(
                    extracted.get("concept")
                )
                + ".\nNúmero de expediente: "
                + _text(
                    extracted.get(
                        "numero_expediente_extranjeria"
                    )
                )
                + ".\nFecha límite: "
                + _text(
                    extracted.get("deadline_at")
                )
                + ".\n"
                "Vinculación provisional pendiente "
                "de contraste en el portal DEHú."
            ),
            "",
            VERIFICATION_MATCHED_PROVISIONAL,
            "dehu_notifications",
            int(notification_id),
            "EMAIL_WATCH",
        ),
    )


def process_stored_message(
    *,
    stored_result,
):
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
            ensure_dehu_schema(conn)

            _upsert_processing_result(
                conn,
                email_message_id=email_message_id,
                status="REVIEW_REQUIRED",
                confidence=0,
                extracted_data=(
                    extraction_result[
                        "extracted_data"
                    ]
                ),
                action_status="NOT_APPLIED",
                review_reason="|".join(
                    extraction_result.get(
                        "missing"
                    )
                    or []
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
            "status": "REVIEW_REQUIRED",
            "reason": "|".join(
                extraction_result.get("missing")
                or []
            ),
            "extraction": extraction_result,
        }

    extracted = extraction_result[
        "extracted_data"
    ]

    official_number = _text(
        extracted.get(
            "numero_expediente_extranjeria"
        )
    )

    with schema_service.connection() as conn:
        ensure_dehu_schema(conn)

        resolution = (
            official_reference_resolver.resolve(
                conn,
                reference_value=_text(
                    extracted.get(
                        "expedient_reference"
                    )
                ),
                reference_type=_upper(
                    extracted.get(
                        "expedient_reference_type"
                    )
                ),
                family_hint=_upper(
                    extracted.get("family_hint")
                ),
            )
        )

        candidates = (
            resolution.get("candidates")
            or []
        )

        expediente = None
        verification_status = (
            VERIFICATION_EMAIL_ONLY
        )
        processing_status = "REVIEW_REQUIRED"
        action_status = "NOT_APPLIED"
        review_reason = ""

        resolution_status = (
            resolution.get("status")
        )

        if (
            resolution_status
            == official_reference_resolver
            .STATUS_FAMILY_NOT_AVAILABLE
        ):
            verification_status = (
                VERIFICATION_REFERENCE_DETECTED_FAMILY_NOT_AVAILABLE
            )
            review_reason = (
                "REFERENCIA_DETECTADA_FAMILIA_NO_DISPONIBLE"
            )

        elif (
            resolution_status
            == official_reference_resolver
            .STATUS_REFERENCE_NOT_DETECTED
        ):
            verification_status = (
                VERIFICATION_EMAIL_ONLY
            )
            review_reason = (
                "REFERENCIA_EXPEDIENTE_NO_DETECTADA"
            )

        elif (
            resolution_status
            == official_reference_resolver
            .STATUS_NOT_FOUND
        ):
            verification_status = (
                VERIFICATION_EXPEDIENT_NOT_FOUND
            )
            review_reason = (
                "EXPEDIENTE_NO_ENCONTRADO"
            )

        elif (
            resolution_status
            == official_reference_resolver
            .STATUS_MULTIPLE
        ):
            verification_status = (
                VERIFICATION_MULTIPLE_EXPEDIENTS
            )
            review_reason = (
                "MULTIPLES_EXPEDIENTES_COINCIDENTES"
            )

        elif (
            resolution_status
            == official_reference_resolver
            .STATUS_MATCHED
        ):
            expediente = candidates[0]
            verification_status = (
                VERIFICATION_MATCHED_PROVISIONAL
            )
            processing_status = "MATCHED"
            action_status = "APPLIED"

        existing = conn.execute(
            """
            SELECT *
            FROM dehu_notifications
            WHERE dehu_identifier = ?
            """,
            (
                _text(
                    extracted["dehu_identifier"]
                ),
            ),
        ).fetchone()

        previous_expediente_id = (
            int(existing["expediente_id"])
            if (
                existing
                and existing["expediente_id"]
            )
            else None
        )

        conn.execute(
            """
            INSERT INTO dehu_notifications (
                dehu_identifier,
                concept,

                item_type,
                concept_type,
                reference_value,
                reference_type,
                family_hint,
                direct_access_url,

                email_expedient_number,

                expediente_id,
                cliente_id,
                primary_email_message_id,

                recipient_name,
                recipient_document_masked,

                issuer_name,
                issuer_dir3,
                relationship_type,

                deadline_at,

                portal_status,
                verification_status,
                download_status,

                raw_email_data_json
            )
            VALUES (
                ?, ?,
                ?, ?, ?, ?, ?, ?,
                ?,
                ?, ?, ?,
                ?, ?,
                ?, ?, ?,
                ?,
                ?, ?, ?,
                ?
            )

            ON CONFLICT(dehu_identifier)
            DO UPDATE SET
                concept =
                    excluded.concept,

                item_type =
                    excluded.item_type,

                concept_type =
                    excluded.concept_type,

                reference_value =
                    excluded.reference_value,

                reference_type =
                    excluded.reference_type,

                family_hint =
                    excluded.family_hint,

                direct_access_url =
                    COALESCE(
                        NULLIF(
                            excluded.direct_access_url,
                            ''
                        ),
                        dehu_notifications
                        .direct_access_url
                    ),

                email_expedient_number =
                    excluded.email_expedient_number,

                expediente_id =
                    COALESCE(
                        excluded.expediente_id,
                        dehu_notifications.expediente_id
                    ),

                cliente_id =
                    COALESCE(
                        excluded.cliente_id,
                        dehu_notifications.cliente_id
                    ),

                recipient_name =
                    excluded.recipient_name,

                recipient_document_masked =
                    excluded.recipient_document_masked,

                issuer_name =
                    excluded.issuer_name,

                issuer_dir3 =
                    excluded.issuer_dir3,

                relationship_type =
                    excluded.relationship_type,

                deadline_at =
                    excluded.deadline_at,

                verification_status =
                    excluded.verification_status,

                raw_email_data_json =
                    excluded.raw_email_data_json,

                last_seen_at =
                    CURRENT_TIMESTAMP,

                updated_at =
                    CURRENT_TIMESTAMP
            """,
            (
                _text(
                    extracted["dehu_identifier"]
                ),
                _text(
                    extracted["concept"]
                ),

                _upper(
                    extracted.get("item_type")
                    or "UNKNOWN"
                ),
                _upper(
                    extracted.get("concept_type")
                    or "UNKNOWN"
                ),
                _text(
                    extracted.get(
                        "expedient_reference"
                    )
                ),
                _upper(
                    extracted.get(
                        "expedient_reference_type"
                    )
                    or "UNKNOWN"
                ),
                _upper(
                    extracted.get("family_hint")
                    or "UNKNOWN"
                ),
                _text(
                    extracted.get(
                        "direct_access_url"
                    )
                ),

                official_number,

                (
                    int(expediente["id"])
                    if expediente
                    else None
                ),
                (
                    int(expediente["cliente_id"])
                    if expediente
                    else None
                ),
                email_message_id,

                _text(
                    extracted["recipient_name"]
                ),
                _text(
                    extracted[
                        "recipient_document_masked"
                    ]
                ),

                _text(
                    extracted["issuer_name"]
                ),
                _text(
                    extracted["issuer_dir3"]
                ),
                _text(
                    extracted["relationship_type"]
                ),

                _text(
                    extracted["deadline_at"]
                ),

                PORTAL_STATUS_UNKNOWN,
                verification_status,
                DOWNLOAD_NOT_REQUESTED,

                json.dumps(
                    extracted,
                    ensure_ascii=False,
                ),
            ),
        )

        notification = conn.execute(
            """
            SELECT *
            FROM dehu_notifications
            WHERE dehu_identifier = ?
            """,
            (
                _text(
                    extracted["dehu_identifier"]
                ),
            ),
        ).fetchone()

        notification_id = int(
            notification["id"]
        )

        conn.execute(
            """
            INSERT OR IGNORE INTO
                dehu_notification_email_sources (
                    dehu_notification_id,
                    email_message_id,
                    provider,
                    account_id,
                    source_folder
                )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                notification_id,
                email_message_id,
                _upper(
                    stored.get("provider")
                ),
                stored.get("account_id"),
                _text(
                    stored.get("folder")
                ),
            ),
        )

        matched_entity_id = (
            int(expediente["id"])
            if expediente
            else None
        )

        _upsert_processing_result(
            conn,
            email_message_id=email_message_id,
            status=processing_status,
            confidence=(
                extraction_result["confidence"]
            ),
            extracted_data=extracted,
            matched_entity_id=matched_entity_id,
            action_status=action_status,
            review_reason=review_reason,
        )

        email_message_service.update_processing_status(
            email_message_id,
            (
                "PROCESSED"
                if expediente
                else "REVIEW_REQUIRED"
            ),
            conn=conn,
        )

        if (
            expediente
            and previous_expediente_id is None
        ):
            _register_expedient_event(
                conn,
                notification_id=notification_id,
                email_message_id=email_message_id,
                expediente=expediente,
                extracted=extracted,
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
            (
                "PROCESSED"
                if expediente
                else "REVIEW_REQUIRED"
            ),
        "reason": review_reason,
        "verification_status":
            verification_status,
        "dehu_notification_id":
            notification_id,
        "dehu_identifier":
            extracted["dehu_identifier"],
        "numero_expediente_extranjeria":
            official_number,
        "expediente_id":
            (
                int(expediente["id"])
                if expediente
                else None
            ),
        "cliente_id":
            (
                int(expediente["cliente_id"])
                if expediente
                else None
            ),
        "extracted_data": extracted,
        "candidates": candidates,
    }


PROCEDURAL_EVENT_LABELS = {
    "ADMISION_TRAMITE":
        "Admisión a trámite",
    "ADMISION_TRAMITE_TASA":
        "Admisión a trámite y tasa",
    "INADMISION_TRAMITE":
        "Inadmisión a trámite",
    "REQUERIMIENTO":
        "Requerimiento",
    "RESOLUCION_FAVORABLE":
        "Resolución favorable",
    "RESOLUCION_DENEGATORIA":
        "Resolución denegatoria",
    "OTRO":
        "Otro documento administrativo",
}


def confirm_notification_from_traceability(
    *,
    dehu_identifier,
    expediente_id,
    cliente_id,
    event_code,
    event_id,
    justificante_id,
    receipt_file=None,
    receipt_extraction=None,
    usuario="ERP",
    conn=None,
):
    """
    Confirma jurídicamente una notificación DEHú desde Trazabilidad.

    La clave de enlace es dehu_identifier. El número oficial del
    expediente solo se utiliza como comprobación complementaria.
    """
    import json

    identifier = _text(
        dehu_identifier
    ).lower()

    if not identifier:
        raise ValueError(
            "No se indicó el identificador DEHú"
        )

    expediente_id = int(expediente_id)
    cliente_id = int(cliente_id)
    event_id = int(event_id)
    justificante_id = int(justificante_id)
    event_code = _upper(event_code)

    event_label = (
        PROCEDURAL_EVENT_LABELS.get(
            event_code
        )
        or event_code.replace("_", " ").title()
    )

    receipt_file = receipt_file or {}
    receipt_extraction = (
        receipt_extraction or {}
    )

    extracted_identifier = _text(
        receipt_extraction.get(
            "dehu_identifier"
        )
    ).lower()

    if (
        extracted_identifier
        and extracted_identifier != identifier
    ):
        raise ValueError(
            "El identificador del resguardo no coincide "
            "con la notificación DEHú"
        )

    with schema_service.connection(conn) as current:
        ensure_dehu_schema(current)

        notification = current.execute(
            """
            SELECT *
            FROM dehu_notifications
            WHERE LOWER(
                TRIM(dehu_identifier)
            ) = ?
            """,
            (identifier,),
        ).fetchone()

        if notification is None:
            receipt_concept = _text(
                receipt_extraction.get(
                    "concept"
                )
            )

            receipt_reference = _text(
                receipt_extraction.get(
                    "reference_value"
                )
            )

            receipt_issuer = _text(
                receipt_extraction.get(
                    "issuer"
                )
            )

            receipt_recipient = _text(
                receipt_extraction.get(
                    "interested_party_name"
                )
            )

            receipt_document = _text(
                receipt_extraction.get(
                    "interested_party_document"
                )
            )

            receipt_accessed_at = _text(
                receipt_extraction.get(
                    "accessed_at"
                )
            )

            current.execute(
                """
                INSERT INTO dehu_notifications (
                    dehu_identifier,
                    concept,

                    item_type,
                    concept_type,

                    reference_value,
                    reference_type,
                    family_hint,

                    dehu_expedient_number,

                    expediente_id,
                    cliente_id,

                    recipient_name,
                    recipient_document_masked,

                    issuer_name,
                    relationship_type,

                    portal_status,
                    verification_status,
                    download_status,

                    accepted_at,
                    raw_dehu_data_json,

                    first_seen_at,
                    last_seen_at,
                    created_at,
                    updated_at
                )
                VALUES (
                    ?, ?,

                    'NOTIFICATION',
                    'UNKNOWN',

                    ?,
                    'EXPEDIENT_NUMBER',
                    'EXTRANJERIA',

                    ?,

                    ?,
                    ?,

                    ?,
                    ?,

                    ?,
                    ?,

                    'ACCEPTED',
                    'MATCHED_PROVISIONAL',
                    'DOWNLOADED',

                    ?,
                    ?,

                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                )
                """,
                (
                    identifier,
                    receipt_concept,

                    receipt_reference,
                    receipt_reference,

                    expediente_id,
                    cliente_id,

                    receipt_recipient,
                    receipt_document,

                    receipt_issuer,
                    _text(
                        receipt_extraction.get(
                            "relationship_role"
                        )
                    ),

                    receipt_accessed_at or None,
                    json.dumps(
                        receipt_extraction,
                        ensure_ascii=False,
                        default=str,
                    ),
                ),
            )

            notification = current.execute(
                """
                SELECT *
                FROM dehu_notifications
                WHERE LOWER(
                    TRIM(dehu_identifier)
                ) = ?
                """,
                (identifier,),
            ).fetchone()

        current_expediente_id = (
            int(notification["expediente_id"])
            if notification["expediente_id"]
            else None
        )

        if (
            current_expediente_id is not None
            and current_expediente_id
            != expediente_id
        ):
            raise ValueError(
                "La notificación DEHú está vinculada "
                f"al expediente CRM #{current_expediente_id}, "
                f"no al expediente #{expediente_id}"
            )

        existing_event_id = (
            int(notification["confirmed_event_id"])
            if notification["confirmed_event_id"]
            else None
        )

        existing_justificante_id = (
            int(
                notification[
                    "confirmed_justificante_id"
                ]
            )
            if notification[
                "confirmed_justificante_id"
            ]
            else None
        )

        # Reintento idempotente de la misma confirmación.
        if (
            existing_event_id == event_id
            and existing_justificante_id
            == justificante_id
            and _upper(
                notification[
                    "procedural_event_code"
                ]
            ) == event_code
        ):
            return {
                "ok": True,
                "changed": False,
                "idempotent": True,
                "notification_id":
                    int(notification["id"]),
                "dehu_identifier":
                    notification[
                        "dehu_identifier"
                    ],
                "procedural_event_code":
                    event_code,
                "procedural_event_label":
                    event_label,
                "verification_status":
                    notification[
                        "verification_status"
                    ],
            }

        # Una clasificación definitiva previa distinta
        # no se sobrescribe silenciosamente.
        if (
            _upper(
                notification[
                    "classification_status"
                ]
            ) == "CONFIRMED"
            and (
                existing_event_id != event_id
                or existing_justificante_id
                != justificante_id
            )
        ):
            raise ValueError(
                "La notificación DEHú ya tiene una "
                "clasificación definitiva diferente"
            )

        current.execute(
            """
            UPDATE dehu_notifications
            SET
                expediente_id = ?,
                cliente_id = ?,

                procedural_event_code = ?,
                procedural_event_label = ?,

                classification_status =
                    'CONFIRMED',
                classification_source =
                    'TRACEABILITY',

                confirmed_event_id = ?,
                confirmed_justificante_id = ?,
                classification_confirmed_at =
                    CURRENT_TIMESTAMP,
                classification_confirmed_by = ?,

                verification_status =
                    'CONFIRMED_BY_TRACEABILITY',

                dehu_receipt_path = ?,
                dehu_receipt_name = ?,
                dehu_receipt_metadata_json = ?,

                updated_at = CURRENT_TIMESTAMP

            WHERE id = ?
            """,
            (
                expediente_id,
                cliente_id,
                event_code,
                event_label,
                event_id,
                justificante_id,
                _text(usuario) or "ERP",
                _text(receipt_file.get("path")),
                _text(receipt_file.get("name")),
                json.dumps(
                    receipt_extraction,
                    ensure_ascii=False,
                    default=str,
                ),
                int(notification["id"]),
            ),
        )

        current.commit()

        return {
            "ok": True,
            "changed": True,
            "idempotent": False,
            "notification_id":
                int(notification["id"]),
            "dehu_identifier":
                notification["dehu_identifier"],
            "procedural_event_code":
                event_code,
            "procedural_event_label":
                event_label,
            "verification_status":
                "CONFIRMED_BY_TRACEABILITY",
        }
