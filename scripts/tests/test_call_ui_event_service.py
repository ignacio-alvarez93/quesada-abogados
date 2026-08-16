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


class CallUIPostCallSemanticsTest(
    unittest.TestCase
):
    @staticmethod
    def _result(
        status,
        *,
        reason_code=None,
        reason_detail=None,
        notes=None,
    ):
        call = persisted(
            status=status
        )

        call.reason_code = (
            reason_code
        )

        call.reason_detail = (
            reason_detail
        )

        call.notes = notes

        return SimpleNamespace(
            observation=(
                SimpleNamespace(
                    active=(
                        SimpleNamespace(
                            present=False
                        )
                    ),
                    previous=(
                        snapshot(
                            phase="ACTIVE"
                        )
                    ),
                )
            ),
            persisted_call=call,
        )


    def test_ended_requires_post_call_form(
        self,
    ):
        service = CallUIEventService()

        event = (
            service
            .project_whatsapp_realtime_result(
                self._result(
                    "ENDED"
                )
            )
        )

        self.assertTrue(
            event.terminal
        )

        self.assertTrue(
            event.post_call_required
        )

        self.assertEqual(
            event.event_key,
            "CALL:50",
        )


    def test_missed_never_requires_post_call_form(
        self,
    ):
        service = CallUIEventService()

        event = (
            service
            .project_whatsapp_realtime_result(
                self._result(
                    "MISSED"
                )
            )
        )

        self.assertTrue(
            event.terminal
        )

        self.assertFalse(
            event.post_call_required
        )


    def test_rejected_never_requires_post_call_form(
        self,
    ):
        service = CallUIEventService()

        event = (
            service
            .project_whatsapp_realtime_result(
                self._result(
                    "REJECTED"
                )
            )
        )

        self.assertTrue(
            event.terminal
        )

        self.assertFalse(
            event.post_call_required
        )


    def test_existing_editorial_data_is_projected(
        self,
    ):
        service = CallUIEventService()

        event = (
            service
            .project_whatsapp_realtime_result(
                self._result(
                    "ENDED",
                    reason_code=(
                        "LEGAL_CONSULTATION"
                    ),
                    reason_detail=(
                        "Renovación"
                    ),
                    notes=(
                        "Cliente informado"
                    ),
                )
            )
        )

        self.assertEqual(
            event.reason_code,
            "LEGAL_CONSULTATION",
        )

        self.assertEqual(
            event.reason_detail,
            "Renovación",
        )

        self.assertEqual(
            event.notes,
            "Cliente informado",
        )


    def test_answered_is_not_terminal_or_post_call(
        self,
    ):
        service = CallUIEventService()

        event = (
            service
            .project_whatsapp_realtime_result(
                self._result(
                    "ANSWERED"
                )
            )
        )

        self.assertFalse(
            event.terminal
        )

        self.assertFalse(
            event.post_call_required
        )
