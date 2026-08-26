"""Observación genérica y PII-safe del estado funcional de un sitio."""

from __future__ import annotations

from enum import Enum
import re

from .state_fingerprint import (
    build_functional_state_fingerprint,
)


SITE_STATE_OBSERVATION_SCHEMA_VERSION = 1

SITE_STATE_OBSERVATION_TYPE = (
    "QCC_SITE_STATE_OBSERVATION"
)

STATE_RECOGNITION_RECOGNIZED = (
    "RECOGNIZED"
)

STATE_RECOGNITION_UNRECOGNIZED = (
    "UNRECOGNIZED"
)

STATE_RECOGNITION_ERROR = (
    "RECOGNIZER_ERROR"
)


_STATE_CODE_PATTERN = re.compile(
    r"^[A-Z][A-Z0-9_.:/-]{0,127}$"
)


def _normalize_state_code(
    value,
):
    """Normaliza identidad semántica, nunca contenido DOM."""

    if value is None:
        return None

    if isinstance(
        value,
        Enum,
    ):
        value = value.value

    normalized = str(
        value
    ).strip().upper()

    if not normalized:
        return None

    if not _STATE_CODE_PATTERN.fullmatch(
        normalized
    ):
        raise ValueError(
            "QCC_SITE_STATE_CODE_INVALID"
        )

    return normalized


def observe_site_state(
    snapshot,
    *,
    recognizer=None,
):
    """Observa un snapshot sin ejecutar ninguna interacción.

    Siempre calcula fingerprint funcional.

    El recognizer es opcional y específico del sitio.
    Su única responsabilidad es traducir el snapshot
    a una identidad semántica estable.

    Un fallo del recognizer no invalida la observación:
    el fingerprint continúa siendo utilizable.
    """

    fingerprint = (
        build_functional_state_fingerprint(
            snapshot
        )
    )

    state = None

    recognition_status = (
        STATE_RECOGNITION_UNRECOGNIZED
    )

    if recognizer is not None:
        if not callable(
            recognizer
        ):
            raise TypeError(
                "QCC_SITE_STATE_RECOGNIZER_INVALID"
            )

        try:
            raw_state = recognizer(
                snapshot
            )

            state = (
                _normalize_state_code(
                    raw_state
                )
            )

        except Exception:
            # El conocimiento semántico es auxiliar.
            # Un recognizer roto no debe impedir
            # capturar ni identificar estructuralmente
            # la página mediante fingerprint.
            state = None

            recognition_status = (
                STATE_RECOGNITION_ERROR
            )

        else:
            recognition_status = (
                STATE_RECOGNITION_RECOGNIZED
                if state is not None
                else STATE_RECOGNITION_UNRECOGNIZED
            )

    return {
        "schema_version":
            SITE_STATE_OBSERVATION_SCHEMA_VERSION,

        "observation_type":
            SITE_STATE_OBSERVATION_TYPE,

        "recognition_status":
            recognition_status,

        "recognized":
            state is not None,

        "state":
            state,

        "fingerprint":
            fingerprint,
    }
