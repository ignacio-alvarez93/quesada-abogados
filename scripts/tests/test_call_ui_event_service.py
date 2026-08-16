import unittest
from types import SimpleNamespace

from backend.services.call_ui_event_service import (
    CallUIEventService,
)


class FakeCallService:
    def __init__(
        self,
        overviews=None,
    ):
        self.overviews = list(
            overviews
            or []
        )

    def list_call_overviews(
        self,
        **kwargs,
    ):
        return list(
            self.overviews
        )


def snapshot(
    *,
    phase="INCOMING_RINGING",
    present=True,
):
    return SimpleNamespace(
        present=present,
        phase=phase,
        direction="INBOUND",
        participant_phone=(
            "+34639156371"
        ),
        participant_display_name=(
            "Mama"
        ),
        provider_call_id=(
            "provider-real-1"
        ),
        external_call_key=(
            "false_provider-real-1"
        ),
        can_accept=True,
        can_reject=True,
        can_hangup=False,
    )


def persisted(
    *,
    status="RINGING",
):
    return SimpleNamespace(
        id=50,
        channel="WHATSAPP",
        direction="INBOUND",
        status=status,
        phone_number=(
            "+34639156371"
        ),
        display_name_snapshot=(
            "Mama"
        ),
        client_id=30,
        provider="WHATSAPP",
        provider_call_id=(
            "provider-real-1"
        ),
        external_call_key=(
            "false_provider-real-1"
        ),
    )


class CallUIEventServiceTest(
    unittest.TestCase
):
    def test_crm_identity_has_priority(
        self,
    ):
        service = CallUIEventService(
            call_service=(
                FakeCallService(
                    [
                        SimpleNamespace(
                            call_id=50,
                            display_name=(
                                "JEAN PIERRY MUÑOZ VALDEZ"
                            ),
                            client_id=30,
                        )
                    ]
                )
            )
        )

        result = SimpleNamespace(
            observation=(
                SimpleNamespace(
                    active=snapshot(),
                    previous=None,
                )
            ),
            persisted_call=(
                persisted()
            ),
        )

        event = (
            service
            .project_whatsapp_realtime_result(
                result
            )
        )

        self.assertEqual(
            event.event_key,
            "CALL:50",
        )

        self.assertTrue(
            event.incoming_ringing
        )

        self.assertEqual(
            event.display_name,
            "JEAN PIERRY MUÑOZ VALDEZ",
        )

        self.assertTrue(
            event.can_accept
        )

        self.assertTrue(
            event.can_reject
        )


    def test_terminal_preserves_same_key(
        self,
    ):
        service = CallUIEventService()

        result = SimpleNamespace(
            observation=(
                SimpleNamespace(
                    active=(
                        SimpleNamespace(
                            present=False
                        )
                    ),
                    previous=(
                        snapshot()
                    ),
                )
            ),
            persisted_call=(
                persisted(
                    status="MISSED"
                )
            ),
        )

        event = (
            service
            .project_whatsapp_realtime_result(
                result
            )
        )

        self.assertEqual(
            event.event_key,
            "CALL:50",
        )

        self.assertFalse(
            event.incoming_ringing
        )

        self.assertTrue(
            event.terminal
        )


if __name__ == "__main__":
    unittest.main()
