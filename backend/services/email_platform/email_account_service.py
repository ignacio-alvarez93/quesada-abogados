"""
Gestión de cuentas de correo sin almacenar secretos.

credential_key es una referencia lógica. En esta primera fase las
credenciales se resuelven mediante variables de entorno.
"""

import json

from backend.services.email_platform import (
    schema_service,
)


def _dict(row):
    return dict(row) if row else None


def ensure_account(
    *,
    nombre,
    email_address,
    provider,
    credential_key="",
    config=None,
    incoming_enabled=True,
    outgoing_enabled=False,
    conn=None,
):
    schema_service.ensure_email_platform_schema(
        conn
    )

    normalized_provider = str(
        provider or ""
    ).strip().upper()

    normalized_email = str(
        email_address or ""
    ).strip().lower()

    if not normalized_provider:
        raise ValueError(
            "El proveedor de correo es obligatorio"
        )

    if not normalized_email:
        raise ValueError(
            "La dirección de correo es obligatoria"
        )

    with schema_service.connection(conn) as current:
        current.execute(
            """
            INSERT INTO email_accounts (
                nombre,
                email_address,
                provider,
                incoming_enabled,
                outgoing_enabled,
                credential_key,
                config_json,
                activo
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)

            ON CONFLICT(provider, email_address)
            DO UPDATE SET
                nombre = excluded.nombre,
                incoming_enabled =
                    excluded.incoming_enabled,
                outgoing_enabled =
                    excluded.outgoing_enabled,
                credential_key =
                    excluded.credential_key,
                config_json =
                    excluded.config_json,
                activo = 1,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                str(nombre or "").strip(),
                normalized_email,
                normalized_provider,
                int(bool(incoming_enabled)),
                int(bool(outgoing_enabled)),
                str(
                    credential_key or ""
                ).strip(),
                json.dumps(
                    config or {},
                    ensure_ascii=False,
                ),
            ),
        )

        return _dict(
            current.execute(
                """
                SELECT *
                FROM email_accounts
                WHERE provider = ?
                  AND email_address = ?
                """,
                (
                    normalized_provider,
                    normalized_email,
                ),
            ).fetchone()
        )


def get_account(account_id, conn=None):
    schema_service.ensure_email_platform_schema(
        conn
    )

    with schema_service.connection(conn) as current:
        return _dict(
            current.execute(
                """
                SELECT *
                FROM email_accounts
                WHERE id = ?
                """,
                (int(account_id),),
            ).fetchone()
        )


def get_active_incoming_accounts(
    provider=None,
):
    schema_service.ensure_email_platform_schema()

    sql = """
        SELECT *
        FROM email_accounts
        WHERE activo = 1
          AND incoming_enabled = 1
    """
    params = []

    if provider:
        sql += " AND provider = ?"
        params.append(
            str(provider).strip().upper()
        )

    sql += " ORDER BY id ASC"

    with schema_service.connection() as conn:
        return [
            dict(row)
            for row in conn.execute(
                sql,
                params,
            ).fetchall()
        ]


def update_sync_success(
    account_id,
    *,
    cursor=None,
    conn=None,
):
    with schema_service.connection(conn) as current:
        current.execute(
            """
            UPDATE email_accounts
            SET
                last_sync_cursor =
                    COALESCE(?, last_sync_cursor),
                last_sync_at =
                    CURRENT_TIMESTAMP,
                last_sync_status = 'OK',
                last_sync_error = '',
                updated_at =
                    CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                (
                    str(cursor)
                    if cursor is not None
                    else None
                ),
                int(account_id),
            ),
        )


def update_sync_error(
    account_id,
    error,
    *,
    conn=None,
):
    with schema_service.connection(conn) as current:
        current.execute(
            """
            UPDATE email_accounts
            SET
                last_sync_at =
                    CURRENT_TIMESTAMP,
                last_sync_status = 'ERROR',
                last_sync_error = ?,
                updated_at =
                    CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                str(error or "").strip(),
                int(account_id),
            ),
        )
