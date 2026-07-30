"""
Consultas de lectura para la bandeja mínima DEHú.

Este servicio no acepta, rechaza ni descarga notificaciones.
Únicamente expone:

- métricas;
- listado filtrado y paginado;
- detalle de un elemento;
- fuentes de correo asociadas.
"""

from datetime import datetime, timedelta

from backend.services.email_platform import (
    dehu_notification_service,
    schema_service,
)


DEFAULT_PAGE_SIZE = 10
MAX_PAGE_SIZE = 100


def _text(value):
    return str(value or "").strip()


def _upper(value):
    return _text(value).upper()


def _safe_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def _normalize_page(value):
    return max(1, _safe_int(value, 1))


def _normalize_page_size(value):
    page_size = _safe_int(
        value,
        DEFAULT_PAGE_SIZE,
    )

    return max(
        1,
        min(page_size, MAX_PAGE_SIZE),
    )


def _origin_expression(alias="dn"):
    """
    Clasifica el origen disponible del registro.

    EMAIL_ONLY:
        existen fuentes de correo y todavía no hay
        evidencia de consulta en el portal.

    PORTAL_ONLY:
        existe información procedente del portal,
        pero no hay correo asociado.

    EMAIL_AND_PORTAL:
        existen ambas fuentes.

    UNKNOWN:
        todavía no existe evidencia suficiente de
        ninguno de los dos canales.
    """

    return f"""
        CASE
            WHEN EXISTS (
                SELECT 1
                FROM dehu_notification_email_sources
                    des_origin
                WHERE
                    des_origin.dehu_notification_id
                    = {alias}.id
            )
            AND (
                NULLIF(
                    TRIM(
                        COALESCE(
                            {alias}.raw_dehu_data_json,
                            ''
                        )
                    ),
                    ''
                ) IS NOT NULL
                OR COALESCE(
                    {alias}.portal_status,
                    'UNKNOWN'
                ) NOT IN (
                    '',
                    'UNKNOWN',
                    'PENDING_VERIFICATION'
                )
            )
            THEN 'EMAIL_AND_PORTAL'

            WHEN EXISTS (
                SELECT 1
                FROM dehu_notification_email_sources
                    des_origin
                WHERE
                    des_origin.dehu_notification_id
                    = {alias}.id
            )
            THEN 'EMAIL_ONLY'

            WHEN (
                NULLIF(
                    TRIM(
                        COALESCE(
                            {alias}.raw_dehu_data_json,
                            ''
                        )
                    ),
                    ''
                ) IS NOT NULL
                OR COALESCE(
                    {alias}.portal_status,
                    'UNKNOWN'
                ) NOT IN (
                    '',
                    'UNKNOWN',
                    'PENDING_VERIFICATION'
                )
            )
            THEN 'PORTAL_ONLY'

            ELSE 'UNKNOWN'
        END
    """



def _now_text():
    return datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def _next_days_text(days):
    return (
        datetime.now()
        + timedelta(days=int(days))
    ).strftime("%Y-%m-%d %H:%M:%S")


def _build_where(
    *,
    search="",
    item_type="",
    family_hint="",
    verification_status="",
    portal_status="",
    deadline_filter="",
):
    clauses = ["1 = 1"]
    params = []

    search = _text(search)

    if search:
        pattern = f"%{search}%"

        clauses.append(
            """
            (
                dn.reference_value LIKE ?
                OR dn.dehu_identifier LIKE ?
                OR dn.recipient_name LIKE ?
                OR dn.issuer_name LIKE ?
                OR dn.concept LIKE ?
                OR e.numero_expediente LIKE ?
                OR e.numero_expediente_extranjeria LIKE ?
                OR c.nombre LIKE ?
                OR c.primer_apellido LIKE ?
                OR c.segundo_apellido LIKE ?
            )
            """
        )

        params.extend(
            [pattern] * 10
        )

    item_type = _upper(item_type)

    if item_type:
        clauses.append(
            "dn.item_type = ?"
        )
        params.append(item_type)

    family_hint = _upper(family_hint)

    if family_hint:
        clauses.append(
            "dn.family_hint = ?"
        )
        params.append(family_hint)

    verification_status = _upper(
        verification_status
    )

    if verification_status:
        clauses.append(
            "dn.verification_status = ?"
        )
        params.append(
            verification_status
        )

    portal_status = _upper(
        portal_status
    )

    if portal_status == "PENDING":
        clauses.append(
            """
            COALESCE(
                NULLIF(
                    TRIM(dn.portal_status),
                    ''
                ),
                'UNKNOWN'
            ) IN (
                'UNKNOWN',
                'PENDING_VERIFICATION'
            )
            """
        )

    elif portal_status:
        clauses.append(
            "dn.portal_status = ?"
        )
        params.append(portal_status)

    deadline_filter = _upper(
        deadline_filter
    )

    if deadline_filter == "UPCOMING_7_DAYS":
        clauses.append(
            """
            NULLIF(
                TRIM(dn.deadline_at),
                ''
            ) IS NOT NULL
            AND datetime(dn.deadline_at)
                >= datetime(?)
            AND datetime(dn.deadline_at)
                <= datetime(?)
            """
        )

        params.extend(
            [
                _now_text(),
                _next_days_text(7),
            ]
        )

    elif deadline_filter == "EXPIRED":
        clauses.append(
            """
            NULLIF(
                TRIM(dn.deadline_at),
                ''
            ) IS NOT NULL
            AND datetime(dn.deadline_at)
                < datetime(?)
            """
        )

        params.append(_now_text())

    elif deadline_filter == "NO_DEADLINE":
        clauses.append(
            """
            NULLIF(
                TRIM(dn.deadline_at),
                ''
            ) IS NULL
            """
        )

    return clauses, params



def get_summary(conn=None):
    with schema_service.connection(conn) as current:
        dehu_notification_service.ensure_dehu_schema(
            current
        )

        origin_sql = _origin_expression("dn")

        row = current.execute(
            f"""
            SELECT
                COUNT(*) AS total,

                SUM(
                    CASE
                        WHEN dn.item_type =
                            'NOTIFICATION'
                        THEN 1
                        ELSE 0
                    END
                ) AS notifications,

                SUM(
                    CASE
                        WHEN dn.item_type =
                            'COMMUNICATION'
                        THEN 1
                        ELSE 0
                    END
                ) AS communications,

                SUM(
                    CASE
                        WHEN dn.expediente_id
                            IS NOT NULL
                        THEN 1
                        ELSE 0
                    END
                ) AS linked,

                SUM(
                    CASE
                        WHEN dn.expediente_id
                            IS NULL
                        THEN 1
                        ELSE 0
                    END
                ) AS unlinked,

                SUM(
                    CASE
                        WHEN dn.verification_status =
                            'REFERENCE_DETECTED_'
                            || 'FAMILY_NOT_AVAILABLE'
                        THEN 1
                        ELSE 0
                    END
                ) AS family_unavailable,

                SUM(
                    CASE
                        WHEN
                            NULLIF(
                                TRIM(dn.deadline_at),
                                ''
                            ) IS NOT NULL
                        AND datetime(dn.deadline_at)
                            < datetime(?)
                        THEN 1
                        ELSE 0
                    END
                ) AS expired,

                SUM(
                    CASE
                        WHEN
                            NULLIF(
                                TRIM(dn.deadline_at),
                                ''
                            ) IS NOT NULL
                        AND datetime(dn.deadline_at)
                            >= datetime(?)
                        AND datetime(dn.deadline_at)
                            <= datetime(?)
                        THEN 1
                        ELSE 0
                    END
                ) AS upcoming_7_days,

                SUM(
                    CASE
                        WHEN ({origin_sql}) =
                            'EMAIL_ONLY'
                        THEN 1
                        ELSE 0
                    END
                ) AS email_only,

                SUM(
                    CASE
                        WHEN ({origin_sql}) =
                            'PORTAL_ONLY'
                        THEN 1
                        ELSE 0
                    END
                ) AS portal_only,

                SUM(
                    CASE
                        WHEN ({origin_sql}) =
                            'EMAIL_AND_PORTAL'
                        THEN 1
                        ELSE 0
                    END
                ) AS email_and_portal,

                SUM(
                    CASE
                        WHEN ({origin_sql}) =
                            'UNKNOWN'
                        THEN 1
                        ELSE 0
                    END
                ) AS origin_unknown

            FROM dehu_notifications dn
            """,
            (
                _now_text(),
                _now_text(),
                _next_days_text(7),
            ),
        ).fetchone()

        keys = (
            "total",
            "notifications",
            "communications",
            "linked",
            "unlinked",
            "family_unavailable",
            "expired",
            "upcoming_7_days",
            "email_only",
            "portal_only",
            "email_and_portal",
            "origin_unknown",
        )

        result = {
            key: _safe_int(
                row[key],
                0,
            )
            for key in keys
        }

        result["email_detected"] = (
            result["email_only"]
            + result["email_and_portal"]
        )

        result["portal_detected"] = (
            result["portal_only"]
            + result["email_and_portal"]
        )

        return result


def list_items(
    *,
    search="",
    item_type="",
    family_hint="",
    verification_status="",
    portal_status="",
    deadline_filter="",
    page=1,
    page_size=DEFAULT_PAGE_SIZE,
    conn=None,
):
    page = _normalize_page(page)
    page_size = _normalize_page_size(
        page_size
    )

    clauses, params = _build_where(
        search=search,
        item_type=item_type,
        family_hint=family_hint,
        verification_status=(
            verification_status
        ),
        portal_status=portal_status,
        deadline_filter=deadline_filter,
    )

    where_sql = "\nAND ".join(clauses)
    origin_sql = _origin_expression("dn")

    with schema_service.connection(conn) as current:
        dehu_notification_service.ensure_dehu_schema(
            current
        )

        total = current.execute(
            f"""
            SELECT COUNT(*)

            FROM dehu_notifications dn

            LEFT JOIN expedientes e
              ON e.id = dn.expediente_id

            LEFT JOIN clientes c
              ON c.id = dn.cliente_id

            WHERE {where_sql}
            """,
            params,
        ).fetchone()[0]

        total = _safe_int(total, 0)

        total_pages = max(
            1,
            (
                total
                + page_size
                - 1
            )
            // page_size,
        )

        page = min(
            page,
            total_pages,
        )

        offset = (
            page - 1
        ) * page_size

        rows = current.execute(
            f"""
            SELECT
                dn.id,
                dn.dehu_identifier,
                dn.concept,
                dn.item_type,
                dn.concept_type,
                dn.reference_value,
                dn.reference_type,
                dn.family_hint,
                dn.direct_access_url,

                dn.recipient_name,
                dn.recipient_document_masked,

                dn.issuer_name,
                dn.issuer_dir3,
                dn.relationship_type,

                dn.deadline_at,
                dn.portal_status,
                dn.verification_status,
                dn.download_status,

                dn.expediente_id,
                dn.cliente_id,

                dn.first_seen_at,
                dn.last_seen_at,
                dn.updated_at,

                ({origin_sql})
                    AS detection_origin,

                e.numero_expediente,
                e.numero_expediente_extranjeria,

                c.nombre AS cliente_nombre,
                c.primer_apellido
                    AS cliente_primer_apellido,
                c.segundo_apellido
                    AS cliente_segundo_apellido,

                (
                    SELECT COUNT(*)
                    FROM
                        dehu_notification_email_sources
                        des_count
                    WHERE
                        des_count.dehu_notification_id
                        = dn.id
                ) AS source_count,

                (
                    SELECT des.provider
                    FROM
                        dehu_notification_email_sources
                        des
                    WHERE
                        des.dehu_notification_id
                        = dn.id
                    ORDER BY
                        des.detected_at DESC,
                        des.id DESC
                    LIMIT 1
                ) AS source_provider,

                (
                    SELECT des.source_folder
                    FROM
                        dehu_notification_email_sources
                        des
                    WHERE
                        des.dehu_notification_id
                        = dn.id
                    ORDER BY
                        des.detected_at DESC,
                        des.id DESC
                    LIMIT 1
                ) AS source_folder,

                (
                    SELECT des.account_id
                    FROM
                        dehu_notification_email_sources
                        des
                    WHERE
                        des.dehu_notification_id
                        = dn.id
                    ORDER BY
                        des.detected_at DESC,
                        des.id DESC
                    LIMIT 1
                ) AS source_account_id

            FROM dehu_notifications dn

            LEFT JOIN expedientes e
              ON e.id = dn.expediente_id

            LEFT JOIN clientes c
              ON c.id = dn.cliente_id

            WHERE {where_sql}

            ORDER BY
                CASE
                    WHEN
                        NULLIF(
                            TRIM(dn.deadline_at),
                            ''
                        ) IS NULL
                    THEN 1
                    ELSE 0
                END ASC,

                datetime(dn.deadline_at) ASC,
                datetime(dn.last_seen_at) DESC,
                dn.id DESC

            LIMIT ?
            OFFSET ?
            """,
            [
                *params,
                page_size,
                offset,
            ],
        ).fetchall()

        return {
            "items": [
                dict(row)
                for row in rows
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }


def get_item_detail(
    notification_id,
    conn=None,
):
    notification_id = _safe_int(
        notification_id,
        0,
    )

    if notification_id <= 0:
        return None

    with schema_service.connection(conn) as current:
        dehu_notification_service.ensure_dehu_schema(
            current
        )

        row = current.execute(
            """
            SELECT
                dn.*,

                e.numero_expediente,
                e.numero_expediente_extranjeria,

                c.nombre AS cliente_nombre,
                c.primer_apellido
                    AS cliente_primer_apellido,
                c.segundo_apellido
                    AS cliente_segundo_apellido

            FROM dehu_notifications dn

            LEFT JOIN expedientes e
              ON e.id = dn.expediente_id

            LEFT JOIN clientes c
              ON c.id = dn.cliente_id

            WHERE dn.id = ?
            """,
            (notification_id,),
        ).fetchone()

        if row is None:
            return None

        sources = current.execute(
            """
            SELECT
                des.id,
                des.email_message_id,
                des.provider,
                des.account_id,
                des.source_folder,
                des.detected_at,

                em.account_email,
                em.provider_message_id,
                em.subject,
                em.sender_email,
                em.received_at

            FROM dehu_notification_email_sources
                des

            LEFT JOIN email_messages em
              ON em.id = des.email_message_id

            WHERE des.dehu_notification_id = ?

            ORDER BY
                des.detected_at DESC,
                des.id DESC
            """,
            (notification_id,),
        ).fetchall()

        result = dict(row)
        result["sources"] = [
            dict(source)
            for source in sources
        ]

        return result
