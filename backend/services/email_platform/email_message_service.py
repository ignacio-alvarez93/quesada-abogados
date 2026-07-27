"""
Persistencia normalizada y deduplicada de mensajes.
"""

import json

from backend.services.email_platform import (
    email_normalization_service,
    schema_service,
)


def _dict(row):
    return dict(row) if row else None


def store_message(message, conn=None):
    normalized = (
        email_normalization_service
        .normalize_message(message)
    )

    schema_service.ensure_email_platform_schema(
        conn
    )

    with schema_service.connection(conn) as current:
        existing = current.execute(
            """
            SELECT *
            FROM email_messages
            WHERE dedupe_key = ?
            """,
            (normalized["dedupe_key"],),
        ).fetchone()

        if existing:
            return {
                "created": False,
                "message": dict(existing),
                "normalized": normalized,
            }

        cursor = current.execute(
            """
            INSERT INTO email_messages (
                account_id,
                provider,
                account_email,
                provider_message_id,
                provider_thread_id,
                internet_message_id,
                dedupe_key,
                direction,
                folder,
                sender_email,
                sender_name,
                recipients_json,
                cc_json,
                bcc_json,
                subject,
                received_at,
                sent_at,
                body_text,
                body_html,
                body_sha256,
                has_attachments,
                processing_status,
                raw_metadata_json
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?,
                'NEW', ?
            )
            """,
            (
                normalized.get("account_id"),
                normalized["provider"],
                normalized["account_email"],
                normalized["provider_message_id"],
                normalized["provider_thread_id"],
                normalized["internet_message_id"],
                normalized["dedupe_key"],
                normalized["direction"],
                normalized["folder"],
                normalized["sender_email"],
                normalized["sender_name"],
                json.dumps(
                    normalized["recipients"],
                    ensure_ascii=False,
                ),
                json.dumps(
                    normalized["cc"],
                    ensure_ascii=False,
                ),
                json.dumps(
                    normalized["bcc"],
                    ensure_ascii=False,
                ),
                normalized["subject"],
                normalized["received_at"] or None,
                normalized["sent_at"] or None,
                normalized["body_text"],
                normalized["body_html"],
                normalized["body_sha256"],
                normalized["has_attachments"],
                json.dumps(
                    normalized["raw_metadata"],
                    ensure_ascii=False,
                ),
            ),
        )

        stored = current.execute(
            """
            SELECT *
            FROM email_messages
            WHERE id = ?
            """,
            (cursor.lastrowid,),
        ).fetchone()

        return {
            "created": True,
            "message": dict(stored),
            "normalized": normalized,
        }


def get_message(message_id, conn=None):
    schema_service.ensure_email_platform_schema(
        conn
    )

    with schema_service.connection(conn) as current:
        return _dict(
            current.execute(
                """
                SELECT *
                FROM email_messages
                WHERE id = ?
                """,
                (int(message_id),),
            ).fetchone()
        )


def update_processing_status(
    message_id,
    status,
    *,
    error="",
    conn=None,
):
    with schema_service.connection(conn) as current:
        current.execute(
            """
            UPDATE email_messages
            SET
                processing_status = ?,
                processing_error = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                str(status or "").strip().upper(),
                str(error or "").strip(),
                int(message_id),
            ),
        )


def list_messages(
    *,
    processing_status=None,
    limit=100,
):
    schema_service.ensure_email_platform_schema()

    sql = """
        SELECT *
        FROM email_messages
        WHERE 1 = 1
    """
    params = []

    if processing_status:
        sql += " AND processing_status = ?"
        params.append(
            str(processing_status)
            .strip()
            .upper()
        )

    sql += """
        ORDER BY
            COALESCE(received_at, created_at) DESC,
            id DESC
        LIMIT ?
    """
    params.append(int(limit))

    with schema_service.connection() as conn:
        return [
            dict(row)
            for row in conn.execute(
                sql,
                params,
            ).fetchall()
        ]
