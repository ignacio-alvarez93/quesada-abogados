"""
Procesador determinista del correo mediante el que Mercurio comunica
el número oficial asignado por la Oficina de Extranjería.
"""

import re

from backend.services.email_platform import (
    email_normalization_service,
)


PROCESSOR_CODE = (
    "EXTRANJERIA_EXPEDIENT_NUMBER"
)

AUTHORIZED_SENDERS = {
    "notificaciones.extranjeria@correo.gob.es",
}

MERCURIO_PATTERN = re.compile(
    r"\bID\s+(I\d{12,20})\b",
    re.IGNORECASE,
)

OFFICIAL_NUMBER_PATTERN = re.compile(
    r"""
    n[uú]mero
    \s+de
    \s+expediente
    \s*[:\-]?
    \s*(\d{12,18})
    \b
    """,
    re.IGNORECASE | re.VERBOSE,
)

INTERESTED_NAME_PATTERN = re.compile(
    r"""
    interesado/a
    \s+con
    \s+nombre
    \s+(.+?)
    \s*,\s*
    ha\s+sido
    """,
    re.IGNORECASE
    | re.DOTALL
    | re.VERBOSE,
)


def _clean_name(value):
    return " ".join(
        str(value or "").split()
    ).strip().upper()


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

    mercurio_match = (
        MERCURIO_PATTERN.search(body)
    )
    official_match = (
        OFFICIAL_NUMBER_PATTERN.search(body)
    )
    name_match = (
        INTERESTED_NAME_PATTERN.search(body)
    )

    extracted = {
        "sender_authorized":
            sender in AUTHORIZED_SENDERS,
        "sender_email":
            sender,
        "numero_presentacion_registro":
            (
                mercurio_match.group(1).upper()
                if mercurio_match
                else ""
            ),
        "numero_expediente_extranjeria":
            (
                official_match.group(1)
                if official_match
                else ""
            ),
        "nombre_interesado":
            (
                _clean_name(
                    name_match.group(1)
                )
                if name_match
                else ""
            ),
    }

    missing = []

    if not extracted["sender_authorized"]:
        missing.append(
            "REMITENTE_NO_AUTORIZADO"
        )

    if not extracted[
        "numero_presentacion_registro"
    ]:
        missing.append(
            "ID_MERCURIO_NO_DETECTADO"
        )

    if not extracted[
        "numero_expediente_extranjeria"
    ]:
        missing.append(
            "NUMERO_OFICIAL_NO_DETECTADO"
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

    if not extracted["nombre_interesado"]:
        confidence = 95

    return {
        "processor_code": PROCESSOR_CODE,
        "status": "EXTRACTED",
        "confidence": confidence,
        "extracted_data": extracted,
        "missing": [],
    }
