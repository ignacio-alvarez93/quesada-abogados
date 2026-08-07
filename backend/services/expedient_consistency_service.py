"""
Políticas transversales de coherencia de expedientes.

Este módulo no abre conexiones propias ni realiza commits. Centraliza reglas
de dominio que deben compartir la ficha general, los formularios dinámicos y
los flujos de trazabilidad.

Reglas iniciales protegidas:
- coherencia entre estado y fecha de presentación;
- bloqueo del cambio ordinario de subtipo tras la presentación;
- coherencia entre el subtipo de Reagrupación Familiar y el tipo de solicitud
  almacenado en el EX02.
"""

from __future__ import annotations

import unicodedata
from typing import Any


PRESENTATION_STATE_NOT_PRESENTED = "NO PRESENTADO"
PRESENTATION_STATE_PRESENTED = "PRESENTADO"

REAGRUPACION_TYPE_CODE = "REAGRUPACION_FAMILIAR"
REAGRUPACION_INITIAL_SUBTYPE = "INICIAL"
REAGRUPACION_RENEWAL_SUBTYPE = "RENOVACION"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalized_code(value: Any) -> str:
    raw = _text(value).upper()

    normalized = unicodedata.normalize(
        "NFKD",
        raw,
    )

    return "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    )


def normalize_presentation_state(value: Any) -> str:
    """
    Normaliza el estado simplificado de presentación.

    Actualmente el contrato de `expedientes.estado_presentacion` admite:
    - NO PRESENTADO
    - PRESENTADO
    """
    state = _normalized_code(value)

    if not state:
        return PRESENTATION_STATE_NOT_PRESENTED

    if state == PRESENTATION_STATE_NOT_PRESENTED:
        return PRESENTATION_STATE_NOT_PRESENTED

    if state == PRESENTATION_STATE_PRESENTED:
        return PRESENTATION_STATE_PRESENTED

    raise ValueError(
        "Estado de presentación no válido. "
        "Debe ser NO PRESENTADO o PRESENTADO."
    )


def normalize_presentation_fields(
    estado_presentacion: Any,
    fecha_presentacion: Any,
) -> tuple[str, str | None]:
    """
    Normaliza y valida el par estado/fecha.

    La fecha se conserva como texto para que el servicio llamante aplique su
    normalizador de fecha habitual.
    """
    state = normalize_presentation_state(
        estado_presentacion
    )

    date_value = _text(fecha_presentacion) or None

    if state == PRESENTATION_STATE_NOT_PRESENTED:
        return state, None

    if not date_value:
        raise ValueError(
            "Un expediente marcado como PRESENTADO "
            "debe tener fecha de presentación."
        )

    return state, date_value


def validate_subtype_change_after_presentation(
    current_subtype_id: Any,
    requested_subtype_id: Any,
    current_presentation_state: Any,
) -> None:
    """
    Impide modificar ordinariamente el subtipo una vez presentado.

    Las rectificaciones históricas deben realizarse mediante migración o flujo
    administrativo específico y auditado.
    """
    current_id = (
        int(current_subtype_id)
        if current_subtype_id not in (None, "")
        else None
    )

    requested_id = (
        int(requested_subtype_id)
        if requested_subtype_id not in (None, "")
        else None
    )

    if current_id == requested_id:
        return

    state = normalize_presentation_state(
        current_presentation_state
    )

    if state == PRESENTATION_STATE_PRESENTED:
        raise ValueError(
            "No se puede cambiar el subtipo de un expediente "
            "ya presentado. Utiliza una rectificación controlada."
        )


def classify_reagrupacion_request(
    request_value: Any,
) -> str:
    """
    Clasifica el texto guardado en `tipo_de_solicitud`.

    Devuelve:
    - INICIAL
    - RENOVACION
    - vacío cuando no puede clasificarse
    """
    value = _normalized_code(request_value)

    if not value:
        return ""

    if "RENOV" in value:
        return REAGRUPACION_RENEWAL_SUBTYPE

    if "INICIAL" in value:
        return REAGRUPACION_INITIAL_SUBTYPE

    return ""


def validate_reagrupacion_request_value(
    type_code: Any,
    subtype_code: Any,
    request_value: Any,
) -> None:
    """
    Comprueba la coherencia entre catálogo y EX02.

    Solo actúa sobre REAGRUPACION_FAMILIAR. El resto de procedimientos queda
    fuera del alcance de esta política.
    """
    if (
        _normalized_code(type_code)
        != REAGRUPACION_TYPE_CODE
    ):
        return

    subtype = _normalized_code(subtype_code)
    request_class = classify_reagrupacion_request(
        request_value
    )

    if subtype not in {
        REAGRUPACION_INITIAL_SUBTYPE,
        REAGRUPACION_RENEWAL_SUBTYPE,
    }:
        return

    if not request_class:
        raise ValueError(
            "El tipo de solicitud EX02 no permite determinar "
            "si se trata de una inicial o una renovación."
        )

    if subtype != request_class:
        subtype_label = (
            "RENOVACIÓN"
            if subtype == REAGRUPACION_RENEWAL_SUBTYPE
            else "INICIAL"
        )

        request_label = (
            "RENOVACIÓN"
            if request_class
            == REAGRUPACION_RENEWAL_SUBTYPE
            else "INICIAL"
        )

        raise ValueError(
            "El subtipo del expediente es "
            f"{subtype_label}, pero el EX02 indica "
            f"{request_label}."
        )


def validate_reagrupacion_request_for_expedient(
    conn,
    expediente_id: int,
    request_value: Any,
) -> None:
    """
    Resuelve tipo y subtipo desde la conexión existente y valida el EX02.

    No confirma ni revierte la transacción.
    """
    row = conn.execute(
        """
        SELECT
            t.codigo AS tipo_codigo,
            s.codigo AS subtipo_codigo
        FROM expedientes e
        JOIN config_tipos_expediente t
          ON t.id = e.tipo_expediente_id
        LEFT JOIN config_subtipos_expediente s
          ON s.id = e.subtipo_expediente_id
        WHERE e.id = ?
        """,
        (int(expediente_id),),
    ).fetchone()

    if not row:
        raise ValueError(
            "No se encuentra el expediente para validar el EX02."
        )

    validate_reagrupacion_request_value(
        row["tipo_codigo"],
        row["subtipo_codigo"],
        request_value,
    )
