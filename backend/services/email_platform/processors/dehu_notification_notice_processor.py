"""
Procesador determinista de avisos de nueva notificación DEHú.

Este procesador:
- identifica exclusivamente al remitente oficial de avisos DEHú;
- extrae los datos del correo;
- obtiene el número oficial desde el concepto not_<numero>_...;
- no accede al portal;
- no acepta ni rechaza notificaciones.
"""

import re
from datetime import datetime

from backend.services.email_platform import (
    email_normalization_service,
)


PROCESSOR_CODE = "DEHU_NOTIFICATION_NOTICE"

AUTHORIZED_SENDERS = {
    "no-reply-notifica@correo.gob.es",
    "noreply.dehu@correo.gob.es",
}


IDENTIFIER_PATTERN = re.compile(
    r"""
    identificador
    \s*:\s*
    ([0-9a-zA-Z_-]{12,100})
    \b
    """,
    re.IGNORECASE | re.VERBOSE,
)

CONCEPT_FIELD_PATTERN = re.compile(
    r"""
    concepto
    \s*:\s*
    ([^\r\n<]+)
    """,
    re.IGNORECASE | re.VERBOSE,
)

EXTRANJERIA_CONCEPT_PATTERN = re.compile(
    r"""
    \b
    (
        (?:
            not
            (?:-[a-z0-9-]+)?
            |
            com
        )
        _
        (\d{12,18})
        _
        (\d+)
        _
        (\d+)
    )
    \b
    """,
    re.IGNORECASE | re.VERBOSE,
)

NACIONALIDAD_REFERENCE_PATTERN = re.compile(
    r"""
    \b
    (R\d{4,12}/\d{4})
    \b
    """,
    re.IGNORECASE | re.VERBOSE,
)


RECIPIENT_PATTERN = re.compile(
    r"""
    titular
    \s*:\s*
    (.+?)
    \s+con
    \s+NIF/NIE
    \s*:?
    \s*
    ([^\r\n]+)
    """,
    re.IGNORECASE | re.VERBOSE,
)

MODERN_RECIPIENT_PATTERN = re.compile(
    r"""
    (.+?)
    \s+con
    \s+NIF/NIE
    \s*:\s*
    ([^\s]+)
    \s+en
    \s+calidad
    \s+de
    \s+Titular
    """,
    re.IGNORECASE | re.VERBOSE,
)

ISSUER_PATTERN = re.compile(
    r"""
    organismo
    \s+emisor
    \s*:\s*
    (.+?)
    (?:
        ,\s*con\s+DIR3
        |
        \r?\n
    )
    """,
    re.IGNORECASE | re.DOTALL | re.VERBOSE,
)

DIR3_PATTERN = re.compile(
    r"""
    DIR3
    \s*:?
    \s*
    ([A-Z]{2}\d{7,12})
    \b
    """,
    re.IGNORECASE | re.VERBOSE,
)

RELATIONSHIP_PATTERN = re.compile(
    r"""
    v[ií]nculo
    \s*:\s*
    ([^\r\n]+)
    """,
    re.IGNORECASE | re.VERBOSE,
)

DEADLINE_WITH_TIME_PATTERN = re.compile(
    r"""
    antes
    \s+de
    \s+las
    \s+
    (\d{2}:\d{2}:\d{2})
    \s+del
    \s+d[ií]a
    \s+
    (\d{2}/\d{2}/\d{2,4})
    """,
    re.IGNORECASE | re.VERBOSE,
)

DEADLINE_DATE_ONLY_PATTERN = re.compile(
    r"""
    con
    \s+vencimiento
    \s+el
    \s+d[ií]a
    \s*:\s*
    (\d{2}/\d{2}/\d{2,4})
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _clean(value):
    return " ".join(
        str(value or "").split()
    ).strip()


def _upper(value):
    return _clean(value).upper()


def _deadline_iso(date_value, time_value):
    date_value = _clean(date_value)
    time_value = _clean(time_value)

    if not date_value:
        return ""

    formats = (
        "%d/%m/%y %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
    )

    candidate = (
        date_value
        + " "
        + (time_value or "23:59:59")
    )

    for date_format in formats:
        try:
            return datetime.strptime(
                candidate,
                date_format,
            ).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue

    return ""


def can_process(message):
    sender = (
        email_normalization_service
        .normalize_email_address(
            message.get("sender_email")
        )
    )

    return sender in AUTHORIZED_SENDERS


def extract(message):
    body = (
        email_normalization_service
        .normalize_body_text(
            message.get("body_text")
            or ""
        )
    )

    sender = (
        email_normalization_service
        .normalize_email_address(
            message.get("sender_email")
        )
    )

    identifier_match = (
        IDENTIFIER_PATTERN.search(body)
    )
    concept_field_match = (
        CONCEPT_FIELD_PATTERN.search(body)
    )

    concept_value = (
        _clean(concept_field_match.group(1))
        if concept_field_match
        else ""
    )

    extranjeria_concept_match = (
        EXTRANJERIA_CONCEPT_PATTERN.search(
            concept_value
        )
    )

    nacionalidad_reference_match = (
        NACIONALIDAD_REFERENCE_PATTERN.search(
            concept_value
            or body
        )
    )
    recipient_match = (
        RECIPIENT_PATTERN.search(body)
        or MODERN_RECIPIENT_PATTERN.search(body)
    )
    issuer_match = (
        ISSUER_PATTERN.search(body)
    )
    dir3_match = (
        DIR3_PATTERN.search(body)
    )
    relationship_match = (
        RELATIONSHIP_PATTERN.search(body)
    )
    deadline_with_time_match = (
        DEADLINE_WITH_TIME_PATTERN.search(body)
    )

    deadline_date_only_match = (
        DEADLINE_DATE_ONLY_PATTERN.search(body)
    )

    deadline_at = ""

    if deadline_with_time_match:
        deadline_at = _deadline_iso(
            deadline_with_time_match.group(2),
            deadline_with_time_match.group(1),
        )

    elif deadline_date_only_match:
        deadline_at = _deadline_iso(
            deadline_date_only_match.group(1),
            "23:59:59",
        )

    extracted = {
        "sender_authorized":
            sender in AUTHORIZED_SENDERS,
        "sender_email":
            sender,

        "dehu_identifier":
            (
                _clean(identifier_match.group(1))
                if identifier_match
                else ""
            ),

        "concept":
            concept_value,

        "concept_type":
            (
                _upper(
                    extranjeria_concept_match
                    .group(1)
                    .split("_", 1)[0]
                )
                if extranjeria_concept_match
                else (
                    "NACIONALIDAD"
                    if nacionalidad_reference_match
                    else "UNKNOWN"
                )
            ),

        "expedient_reference":
            (
                _clean(
                    extranjeria_concept_match
                    .group(2)
                )
                if extranjeria_concept_match
                else (
                    _upper(
                        nacionalidad_reference_match
                        .group(1)
                    )
                    if nacionalidad_reference_match
                    else ""
                )
            ),

        "expedient_reference_type":
            (
                "EXTRANJERIA_NUMERIC"
                if extranjeria_concept_match
                else (
                    "NACIONALIDAD"
                    if nacionalidad_reference_match
                    else "UNKNOWN"
                )
            ),

        # Compatibilidad con el servicio actual.
        "numero_expediente_extranjeria":
            (
                _clean(
                    extranjeria_concept_match
                    .group(2)
                )
                if extranjeria_concept_match
                else ""
            ),

        "concept_reference_1":
            (
                _clean(
                    extranjeria_concept_match
                    .group(3)
                )
                if extranjeria_concept_match
                else ""
            ),

        "concept_reference_2":
            (
                _clean(
                    extranjeria_concept_match
                    .group(4)
                )
                if extranjeria_concept_match
                else ""
            ),

        "recipient_name":
            (
                _upper(recipient_match.group(1))
                if recipient_match
                else ""
            ),

        "recipient_document_masked":
            (
                _clean(recipient_match.group(2))
                if recipient_match
                else ""
            ),

        "issuer_name":
            (
                _clean(issuer_match.group(1))
                if issuer_match
                else ""
            ),

        "issuer_dir3":
            (
                _upper(dir3_match.group(1))
                if dir3_match
                else ""
            ),

        "relationship_type":
            (
                _upper(
                    relationship_match.group(1)
                )
                if relationship_match
                else ""
            ),

        "deadline_at":
            deadline_at,
    }

    missing = []

    if not extracted["sender_authorized"]:
        missing.append(
            "REMITENTE_NO_AUTORIZADO"
        )

    if not extracted["dehu_identifier"]:
        missing.append(
            "IDENTIFICADOR_DEHU_NO_DETECTADO"
        )

    if not extracted["concept"]:
        missing.append(
            "CONCEPTO_DEHU_NO_DETECTADO"
        )

    if not extracted[
        "expedient_reference"
    ]:
        missing.append(
            "REFERENCIA_EXPEDIENTE_NO_DETECTADA"
        )

    if not extracted["deadline_at"]:
        missing.append(
            "FECHA_LIMITE_NO_DETECTADA"
        )

    if missing:
        return {
            "processor_code": PROCESSOR_CODE,
            "status": "NOT_MATCHED",
            "confidence": 0,
            "extracted_data": extracted,
            "missing": missing,
        }

    confidence = 100

    optional_values = (
        "recipient_name",
        "recipient_document_masked",
        "issuer_name",
        "issuer_dir3",
        "relationship_type",
    )

    missing_optional = [
        key
        for key in optional_values
        if not extracted.get(key)
    ]

    if missing_optional:
        confidence = 95

    return {
        "processor_code": PROCESSOR_CODE,
        "status": "EXTRACTED",
        "confidence": confidence,
        "extracted_data": extracted,
        "missing": [],
        "missing_optional": missing_optional,
    }
