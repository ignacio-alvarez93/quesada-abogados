"""
Reprocesamiento controlado de avisos oficiales almacenados.

Permite volver a ejecutar el procesamiento de mensajes ya registrados
cuando cambian:

- los resolvedores de referencias;
- los modelos de expedientes disponibles;
- las reglas de clasificación;
- los estados de vinculación.

El servicio reutiliza email_expedient_sync_service y conserva la
idempotencia de mensajes, avisos, fuentes y eventos.
"""

import sqlite3

from backend.services.email_platform import (
    email_expedient_sync_service,
    schema_service,
)


DEFAULT_PROCESSOR_CODE = (
    "DEHU_NOTIFICATION_NOTICE"
)


def _text(value):
    return str(value or "").strip()


def _upper(value):
    return _text(value).upper()


def _normalize_limit(value):
    if value in (None, ""):
        return None

    limit = int(value)

    if limit <= 0:
        raise ValueError(
            "limit debe ser mayor que cero"
        )

    return limit


def _build_filters(
    *,
    family_hint="",
    reference_type="",
    verification_status="",
    provider="",
    account_id=None,
    folder="",
    received_from="",
    received_to="",
):
    clauses = [
        "epr.processor_code = ?",
    ]

    params = [
        DEFAULT_PROCESSOR_CODE,
    ]

    family_hint = _upper(family_hint)

    if family_hint:
        clauses.append(
            """
            UPPER(
                COALESCE(
                    json_extract(
                        epr.extracted_data_json,
                        '$.family_hint'
                    ),
                    ''
                )
            ) = ?
            """
        )
        params.append(family_hint)

    reference_type = _upper(reference_type)

    if reference_type:
        clauses.append(
            """
            UPPER(
                COALESCE(
                    json_extract(
                        epr.extracted_data_json,
                        '$.expedient_reference_type'
                    ),
                    ''
                )
            ) = ?
            """
        )
        params.append(reference_type)

    verification_status = _upper(
        verification_status
    )

    if verification_status:
        clauses.append(
            """
            EXISTS (
                SELECT 1
                FROM dehu_notification_email_sources des
                JOIN dehu_notifications dn
                  ON dn.id =
                     des.dehu_notification_id
                WHERE des.email_message_id = em.id
                  AND UPPER(
                        COALESCE(
                            dn.verification_status,
                            ''
                        )
                      ) = ?
            )
            """
        )
        params.append(verification_status)

    provider = _upper(provider)

    if provider:
        clauses.append(
            """
            UPPER(
                COALESCE(
                    em.provider,
                    ''
                )
            ) = ?
            """
        )
        params.append(provider)

    if account_id not in (None, ""):
        clauses.append(
            "em.account_id = ?"
        )
        params.append(int(account_id))

    folder = _upper(folder)

    if folder:
        clauses.append(
            """
            UPPER(
                COALESCE(
                    em.folder,
                    ''
                )
            ) = ?
            """
        )
        params.append(folder)

    received_from = _text(received_from)

    if received_from:
        clauses.append(
            "em.received_at >= ?"
        )
        params.append(received_from)

    received_to = _text(received_to)

    if received_to:
        clauses.append(
            "em.received_at <= ?"
        )
        params.append(received_to)

    return clauses, params


def find_messages(
    *,
    family_hint="",
    reference_type="",
    verification_status="",
    provider="",
    account_id=None,
    folder="",
    received_from="",
    received_to="",
    limit=None,
    conn=None,
):
    limit = _normalize_limit(limit)

    clauses, params = _build_filters(
        family_hint=family_hint,
        reference_type=reference_type,
        verification_status=verification_status,
        provider=provider,
        account_id=account_id,
        folder=folder,
        received_from=received_from,
        received_to=received_to,
    )

    sql = """
        SELECT DISTINCT
            em.*
        FROM email_messages em

        JOIN email_processing_results epr
          ON epr.email_message_id = em.id

        WHERE
    """ + "\n AND ".join(clauses) + """

        ORDER BY
            em.received_at ASC,
            em.id ASC
    """

    if limit is not None:
        sql += "\nLIMIT ?"
        params.append(limit)

    owns_connection = conn is None

    if owns_connection:
        conn = sqlite3.connect(
            schema_service.DB_PATH
        )
        conn.row_factory = sqlite3.Row

    try:
        return [
            dict(row)
            for row in conn.execute(
                sql,
                params,
            ).fetchall()
        ]
    finally:
        if owns_connection:
            conn.close()


def reprocess_messages(
    *,
    family_hint="",
    reference_type="",
    verification_status="",
    provider="",
    account_id=None,
    folder="",
    received_from="",
    received_to="",
    limit=None,
    dry_run=False,
):
    messages = find_messages(
        family_hint=family_hint,
        reference_type=reference_type,
        verification_status=verification_status,
        provider=provider,
        account_id=account_id,
        folder=folder,
        received_from=received_from,
        received_to=received_to,
        limit=limit,
    )

    summary = {
        "ok": True,
        "dry_run": bool(dry_run),
        "selected": len(messages),
        "processed": 0,
        "statuses": {},
        "results": [],
        "errors": [],
    }

    if dry_run:
        summary["results"] = [
            {
                "email_message_id":
                    int(message["id"]),
                "provider":
                    _upper(
                        message.get("provider")
                    ),
                "provider_message_id":
                    _text(
                        message.get(
                            "provider_message_id"
                        )
                    ),
            }
            for message in messages
        ]

        return summary

    for message in messages:
        email_message_id = int(
            message["id"]
        )

        try:
            result = (
                email_expedient_sync_service
                .process_message(message)
            )

            status = _upper(
                result.get("status")
                or "UNKNOWN"
            )

            summary["processed"] += 1

            summary["statuses"][status] = (
                summary["statuses"].get(
                    status,
                    0,
                )
                + 1
            )

            summary["results"].append(
                {
                    "email_message_id":
                        email_message_id,
                    "status":
                        status,
                    "verification_status":
                        _upper(
                            result.get(
                                "verification_status"
                            )
                        ),
                    "reason":
                        _upper(
                            result.get("reason")
                        ),
                }
            )

        except Exception as exc:
            summary["ok"] = False

            summary["errors"].append(
                {
                    "email_message_id":
                        email_message_id,
                    "error":
                        str(exc),
                }
            )

    return summary
