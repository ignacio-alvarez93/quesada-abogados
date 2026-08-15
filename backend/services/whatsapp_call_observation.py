"""
Memoria pura de observación realtime de llamadas WhatsApp.

Responsabilidad:
- comparar snapshots consecutivos;
- conservar identidad mientras una superficie de llamada exista;
- distinguir aparición, actualización, reemplazo y desaparición.

No:
- toca SeleniumBase/CDP;
- persiste;
- conoce CommunicationCall;
- clasifica MISSED / REJECTED / CANCELLED;
- inventa timestamps.
"""

from dataclasses import dataclass
from dataclasses import replace

from backend.automation.connectors.whatsapp_call_observer import (
    WHATSAPP_CALL_DIRECTION_UNKNOWN,
    WhatsAppCallSnapshot,
)


CALL_OBSERVATION_ABSENT = (
    "CALL_ABSENT"
)

CALL_OBSERVATION_SURFACE_APPEARED = (
    "CALL_SURFACE_APPEARED"
)

CALL_OBSERVATION_UPDATED = (
    "CALL_UPDATED"
)

CALL_OBSERVATION_REPLACED = (
    "CALL_REPLACED"
)

CALL_OBSERVATION_SURFACE_DISAPPEARED = (
    "CALL_SURFACE_DISAPPEARED"
)

CALL_OBSERVATION_UNCHANGED = (
    "CALL_UNCHANGED"
)


@dataclass(frozen=True)
class WhatsAppCallObservation:
    """Resultado de comparar una lectura con memoria runtime."""

    changed: bool
    change_type: str

    previous: WhatsAppCallSnapshot | None
    current: WhatsAppCallSnapshot

    active: WhatsAppCallSnapshot | None = None
    disappeared: WhatsAppCallSnapshot | None = None


def _clean_optional_text(
    value,
):
    normalized = str(
        value
        or ""
    ).strip()

    return (
        normalized
        or None
    )


def whatsapp_call_snapshots_conflict(
    previous,
    current,
):
    """
    Detecta que dos superficies identificadas pertenecen
    inequívocamente a llamadas distintas.

    external_call_key se trata como valor opaco.
    Nunca se reconstruye ni se interpreta su prefijo.
    """
    if (
        not isinstance(
            previous,
            WhatsAppCallSnapshot,
        )
        or not isinstance(
            current,
            WhatsAppCallSnapshot,
        )
    ):
        raise TypeError(
            "Se requieren WhatsAppCallSnapshot"
        )

    previous_external_key = (
        _clean_optional_text(
            previous.external_call_key
        )
    )

    current_external_key = (
        _clean_optional_text(
            current.external_call_key
        )
    )

    if (
        previous_external_key
        and current_external_key
        and previous_external_key
        != current_external_key
    ):
        return True

    previous_provider_id = (
        _clean_optional_text(
            previous.provider_call_id
        )
    )

    current_provider_id = (
        _clean_optional_text(
            current.provider_call_id
        )
    )

    if (
        previous_provider_id
        and current_provider_id
        and previous_provider_id
        != current_provider_id
    ):
        return True

    return False


def merge_whatsapp_call_observation(
    previous,
    current,
):
    """
    Enriquece una superficie parcial con identidad ya observada.

    Solo conserva campos de identidad/contexto.

    No conserva:
    - phase;
    - visible_state;
    - botones/controles.

    Esos campos describen exclusivamente la lectura actual.
    """
    if not isinstance(
        current,
        WhatsAppCallSnapshot,
    ):
        raise TypeError(
            "current debe ser WhatsAppCallSnapshot"
        )

    if (
        previous is None
        or not isinstance(
            previous,
            WhatsAppCallSnapshot,
        )
        or not previous.present
        or not current.present
        or whatsapp_call_snapshots_conflict(
            previous,
            current,
        )
    ):
        return current

    direction = (
        current.direction
    )

    if (
        direction
        == WHATSAPP_CALL_DIRECTION_UNKNOWN
        and previous.direction
        != WHATSAPP_CALL_DIRECTION_UNKNOWN
    ):
        direction = (
            previous.direction
        )

    provider_call_id = (
        _clean_optional_text(
            current.provider_call_id
        )
        or _clean_optional_text(
            previous.provider_call_id
        )
    )

    external_call_key = (
        _clean_optional_text(
            current.external_call_key
        )
        or _clean_optional_text(
            previous.external_call_key
        )
    )

    participant_lid = (
        _clean_optional_text(
            current.participant_lid
        )
        or _clean_optional_text(
            previous.participant_lid
        )
    )

    participant_phone_id = (
        _clean_optional_text(
            current.participant_phone_id
        )
        or _clean_optional_text(
            previous.participant_phone_id
        )
    )

    participant_phone = (
        _clean_optional_text(
            current.participant_phone
        )
        or _clean_optional_text(
            previous.participant_phone
        )
    )

    participant_display_name = (
        _clean_optional_text(
            current.participant_display_name
        )
        or _clean_optional_text(
            previous.participant_display_name
        )
    )

    is_video = (
        current.is_video
        if current.is_video is not None
        else previous.is_video
    )

    identity_complete = all(
        (
            provider_call_id,
            external_call_key,
            participant_lid,
            participant_phone_id,
        )
    )

    return replace(
        current,
        direction=direction,
        provider_call_id=(
            provider_call_id
        ),
        external_call_key=(
            external_call_key
        ),
        participant_lid=(
            participant_lid
        ),
        participant_phone_id=(
            participant_phone_id
        ),
        participant_phone=(
            participant_phone
        ),
        participant_display_name=(
            participant_display_name
        ),
        is_video=is_video,
        identity_complete=(
            identity_complete
        ),
    )


class WhatsAppCallObservationTracker:
    """
    Máquina mínima de memoria realtime.

    La memoria representa únicamente la superficie activa
    observada por este proceso.
    """

    def __init__(
        self,
    ):
        self._active = None

    @property
    def active(
        self,
    ):
        return self._active

    def reset(
        self,
    ):
        self._active = None

    def observe(
        self,
        current,
    ):
        if not isinstance(
            current,
            WhatsAppCallSnapshot,
        ):
            raise TypeError(
                "current debe ser WhatsAppCallSnapshot"
            )

        previous = (
            self._active
        )

        if not current.present:
            if previous is None:
                return WhatsAppCallObservation(
                    changed=False,
                    change_type=(
                        CALL_OBSERVATION_ABSENT
                    ),
                    previous=None,
                    current=current,
                    active=None,
                    disappeared=None,
                )

            self._active = None

            return WhatsAppCallObservation(
                changed=True,
                change_type=(
                    CALL_OBSERVATION_SURFACE_DISAPPEARED
                ),
                previous=previous,
                current=current,
                active=None,
                disappeared=previous,
            )

        effective = (
            merge_whatsapp_call_observation(
                previous,
                current,
            )
        )

        if previous is None:
            change_type = (
                CALL_OBSERVATION_SURFACE_APPEARED
            )

            changed = True

        elif whatsapp_call_snapshots_conflict(
            previous,
            current,
        ):
            change_type = (
                CALL_OBSERVATION_REPLACED
            )

            changed = True

        elif effective != previous:
            change_type = (
                CALL_OBSERVATION_UPDATED
            )

            changed = True

        else:
            change_type = (
                CALL_OBSERVATION_UNCHANGED
            )

            changed = False

        self._active = (
            effective
        )

        return WhatsAppCallObservation(
            changed=changed,
            change_type=change_type,
            previous=previous,
            current=current,
            active=effective,
            disappeared=None,
        )
