from dataclasses import dataclass


CALL_UI_TERMINAL_STATUSES = frozenset(
    {
        "ENDED",
        "MISSED",
        "REJECTED",
        "BUSY",
        "FAILED",
        "CANCELLED",
    }
)


@dataclass(frozen=True)
class CallUIEvent:
    """
    Evento provider-neutral para presentación de llamadas.

    No conoce Flet.
    No conoce Selenium.
    No conoce SQLite.
    """

    event_key: str

    call_id: int | None = None

    channel: str | None = None
    direction: str | None = None
    status: str | None = None

    phone_number: str | None = None
    display_name: str | None = None
    client_id: int | None = None

    provider: str | None = None
    provider_call_id: str | None = None
    external_call_key: str | None = None

    can_accept: bool = False
    can_reject: bool = False
    can_hangup: bool = False

    incoming_ringing: bool = False
    terminal: bool = False

    source: str | None = None


class CallUIEventService:
    """
    Frontera application/realtime -> evento visual genérico.

    La resolución de identidad CRM permanece en backend.
    """

    def __init__(
        self,
        *,
        call_service=None,
    ):
        self.call_service = call_service


    @staticmethod
    def _text(
        value,
    ):
        normalized = str(
            value
            or ""
        ).strip()

        return normalized or None


    def _resolve_overview(
        self,
        *,
        call_id,
        phone_number,
    ):
        if (
            self.call_service is None
            or call_id is None
        ):
            return None

        try:
            items = (
                self.call_service
                .list_call_overviews(
                    search=(
                        phone_number
                        or None
                    ),
                    limit=200,
                )
            )
        except Exception:
            return None

        for item in items or []:
            if (
                getattr(
                    item,
                    "call_id",
                    None,
                )
                == call_id
            ):
                return item

        return None


    def project_whatsapp_realtime_result(
        self,
        result,
    ):
        if result is None:
            return None

        observation = getattr(
            result,
            "observation",
            None,
        )

        persisted_call = getattr(
            result,
            "persisted_call",
            None,
        )

        active = getattr(
            observation,
            "active",
            None,
        )

        previous = getattr(
            observation,
            "previous",
            None,
        )

        active_present = bool(
            active is not None
            and getattr(
                active,
                "present",
                False,
            )
        )

        snapshot = (
            active
            if active_present
            else previous
        )

        if (
            persisted_call is None
            and snapshot is None
        ):
            return None

        raw_call_id = getattr(
            persisted_call,
            "id",
            None,
        )

        try:
            call_id = (
                int(raw_call_id)
                if raw_call_id
                not in (None, "")
                else None
            )
        except Exception:
            call_id = None

        channel = (
            self._text(
                getattr(
                    persisted_call,
                    "channel",
                    None,
                )
            )
            or "WHATSAPP"
        )

        direction = (
            self._text(
                getattr(
                    persisted_call,
                    "direction",
                    None,
                )
            )
            or self._text(
                getattr(
                    snapshot,
                    "direction",
                    None,
                )
            )
        )

        status = self._text(
            getattr(
                persisted_call,
                "status",
                None,
            )
        )

        provider_phase = self._text(
            getattr(
                snapshot,
                "phase",
                None,
            )
        )

        if status is None:
            status = {
                "INCOMING_RINGING":
                    "RINGING",
                "OUTGOING_DIALING":
                    "DIALING",
                "ACTIVE":
                    "ANSWERED",
            }.get(
                provider_phase
            )

        phone_number = (
            self._text(
                getattr(
                    persisted_call,
                    "phone_number",
                    None,
                )
            )
            or self._text(
                getattr(
                    snapshot,
                    "participant_phone",
                    None,
                )
            )
        )

        provider_call_id = (
            self._text(
                getattr(
                    persisted_call,
                    "provider_call_id",
                    None,
                )
            )
            or self._text(
                getattr(
                    snapshot,
                    "provider_call_id",
                    None,
                )
            )
        )

        external_call_key = (
            self._text(
                getattr(
                    persisted_call,
                    "external_call_key",
                    None,
                )
            )
            or self._text(
                getattr(
                    snapshot,
                    "external_call_key",
                    None,
                )
            )
        )

        provider = (
            self._text(
                getattr(
                    persisted_call,
                    "provider",
                    None,
                )
            )
            or "WHATSAPP"
        )

        display_name = (
            self._text(
                getattr(
                    persisted_call,
                    "display_name_snapshot",
                    None,
                )
            )
            or self._text(
                getattr(
                    snapshot,
                    "participant_display_name",
                    None,
                )
            )
            or phone_number
            or "Contacto desconocido"
        )

        client_id = getattr(
            persisted_call,
            "client_id",
            None,
        )

        overview = (
            self._resolve_overview(
                call_id=call_id,
                phone_number=(
                    phone_number
                ),
            )
        )

        if overview is not None:
            crm_name = self._text(
                getattr(
                    overview,
                    "display_name",
                    None,
                )
            )

            if crm_name:
                display_name = crm_name

            overview_client_id = getattr(
                overview,
                "client_id",
                None,
            )

            if overview_client_id is not None:
                client_id = (
                    overview_client_id
                )

        normalized_direction = str(
            direction
            or ""
        ).upper()

        normalized_status = str(
            status
            or ""
        ).upper()

        incoming_ringing = bool(
            active_present
            and normalized_direction
            == "INBOUND"
            and (
                normalized_status
                == "RINGING"
                or provider_phase
                == "INCOMING_RINGING"
            )
        )

        terminal = (
            normalized_status
            in CALL_UI_TERMINAL_STATUSES
        )

        can_accept = bool(
            active_present
            and getattr(
                active,
                "can_accept",
                False,
            )
        )

        can_reject = bool(
            active_present
            and getattr(
                active,
                "can_reject",
                False,
            )
        )

        can_hangup = bool(
            active_present
            and getattr(
                active,
                "can_hangup",
                False,
            )
        )

        if call_id is not None:
            event_key = (
                f"CALL:{call_id}"
            )

        elif external_call_key:
            event_key = (
                "EXTERNAL:"
                f"{external_call_key}"
            )

        elif provider_call_id:
            event_key = (
                "PROVIDER:"
                f"{provider_call_id}"
            )

        else:
            return None

        return CallUIEvent(
            event_key=event_key,
            call_id=call_id,
            channel=channel,
            direction=direction,
            status=status,
            phone_number=phone_number,
            display_name=display_name,
            client_id=client_id,
            provider=provider,
            provider_call_id=(
                provider_call_id
            ),
            external_call_key=(
                external_call_key
            ),
            can_accept=can_accept,
            can_reject=can_reject,
            can_hangup=can_hangup,
            incoming_ringing=(
                incoming_ringing
            ),
            terminal=terminal,
            source=(
                "WHATSAPP_REALTIME"
            ),
        )
