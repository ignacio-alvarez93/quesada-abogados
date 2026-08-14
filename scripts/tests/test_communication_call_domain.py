import unittest

from backend.communications.calls import (
    CALL_STATUS_ANSWERED,
    CALL_STATUS_BUSY,
    CALL_STATUS_CANCELLED,
    CALL_STATUS_CREATED,
    CALL_STATUS_ENDED,
    CALL_STATUS_FAILED,
    CALL_STATUS_MISSED,
    CALL_STATUS_REJECTED,
    CALL_STATUS_RINGING,
    CALL_TERMINAL_STATUSES,
    CommunicationCall,
)
from backend.communications.models import (
    CHANNEL_PHONE,
    CHANNEL_WHATSAPP,
    DIRECTION_INBOUND,
    DIRECTION_OUTBOUND,
)


class CommunicationCallDomainTest(
    unittest.TestCase
):
    def test_call_can_exist_without_client_or_expedient(
        self,
    ):
        call = CommunicationCall(
            id=None,
            channel=CHANNEL_PHONE,
            direction=DIRECTION_INBOUND,
            phone_number="+34600123456",
            display_name_snapshot="Número no identificado",
        )

        self.assertIsNone(call.thread_id)
        self.assertIsNone(call.client_id)
        self.assertIsNone(call.expedient_id)

        self.assertEqual(
            call.status,
            CALL_STATUS_CREATED,
        )

        self.assertIsNone(
            call.talk_duration_seconds
        )

    def test_call_supports_client_and_expedient_context(
        self,
    ):
        call = CommunicationCall(
            id=10,
            channel=CHANNEL_WHATSAPP,
            direction=DIRECTION_OUTBOUND,
            phone_number="+34600123456",
            thread_id=20,
            client_id=30,
            expedient_id=40,
            reason_code="EXPEDIENT_STATUS",
        )

        self.assertEqual(call.thread_id, 20)
        self.assertEqual(call.client_id, 30)
        self.assertEqual(call.expedient_id, 40)

        self.assertEqual(
            call.reason_code,
            "EXPEDIENT_STATUS",
        )

    def test_terminal_call_statuses_are_explicit(
        self,
    ):
        expected = {
            CALL_STATUS_ENDED,
            CALL_STATUS_MISSED,
            CALL_STATUS_REJECTED,
            CALL_STATUS_BUSY,
            CALL_STATUS_FAILED,
            CALL_STATUS_CANCELLED,
        }

        self.assertEqual(
            CALL_TERMINAL_STATUSES,
            expected,
        )

        self.assertNotIn(
            CALL_STATUS_RINGING,
            CALL_TERMINAL_STATUSES,
        )

        self.assertNotIn(
            CALL_STATUS_ANSWERED,
            CALL_TERMINAL_STATUSES,
        )

    def test_zero_talk_duration_is_distinct_from_unknown(
        self,
    ):
        active = CommunicationCall(
            id=1,
            channel=CHANNEL_PHONE,
            direction=DIRECTION_OUTBOUND,
            phone_number="+34600123456",
            status=CALL_STATUS_RINGING,
        )

        missed = CommunicationCall(
            id=2,
            channel=CHANNEL_PHONE,
            direction=DIRECTION_OUTBOUND,
            phone_number="+34600123456",
            status=CALL_STATUS_MISSED,
            talk_duration_seconds=0,
        )

        self.assertIsNone(
            active.talk_duration_seconds
        )

        self.assertEqual(
            missed.talk_duration_seconds,
            0,
        )


if __name__ == "__main__":
    unittest.main()
