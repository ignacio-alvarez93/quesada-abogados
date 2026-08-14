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
    CALL_OUTCOME_OPTIONS,
    CALL_REASON_OPTIONS,
    CALL_STATUS_RINGING,
    CALL_TERMINAL_STATUSES,
    CommunicationCall,
    InvalidCallTimestamp,
    InvalidCallTransition,
    can_transition_call_status,
    get_call_outcome_label,
    get_call_outcome_options,
    get_call_reason_label,
    get_call_reason_options,
    is_valid_call_outcome_code,
    is_valid_call_reason_code,
    normalize_call_outcome_code,
    normalize_call_reason_code,
    transition_call_status,
    transition_call_status_at,
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

    def test_inbound_call_starts_ringing(
        self,
    ):
        call = CommunicationCall(
            id=1,
            channel=CHANNEL_PHONE,
            direction=DIRECTION_INBOUND,
            phone_number="+34600123456",
        )

        ringing = transition_call_status(
            call,
            CALL_STATUS_RINGING,
        )

        self.assertEqual(
            call.status,
            CALL_STATUS_CREATED,
        )

        self.assertEqual(
            ringing.status,
            CALL_STATUS_RINGING,
        )

    def test_outbound_call_starts_dialing(
        self,
    ):
        call = CommunicationCall(
            id=1,
            channel=CHANNEL_WHATSAPP,
            direction=DIRECTION_OUTBOUND,
            phone_number="+34600123456",
        )

        dialing = transition_call_status(
            call,
            "DIALING",
        )

        self.assertEqual(
            dialing.status,
            "DIALING",
        )

    def test_inbound_cannot_start_dialing(
        self,
    ):
        call = CommunicationCall(
            id=1,
            channel=CHANNEL_PHONE,
            direction=DIRECTION_INBOUND,
            phone_number="+34600123456",
        )

        with self.assertRaises(
            InvalidCallTransition
        ):
            transition_call_status(
                call,
                "DIALING",
            )

    def test_outbound_cannot_start_ringing(
        self,
    ):
        call = CommunicationCall(
            id=1,
            channel=CHANNEL_PHONE,
            direction=DIRECTION_OUTBOUND,
            phone_number="+34600123456",
        )

        with self.assertRaises(
            InvalidCallTransition
        ):
            transition_call_status(
                call,
                CALL_STATUS_RINGING,
            )

    def test_answered_call_can_end(
        self,
    ):
        call = CommunicationCall(
            id=1,
            channel=CHANNEL_PHONE,
            direction=DIRECTION_INBOUND,
            phone_number="+34600123456",
            status=CALL_STATUS_ANSWERED,
        )

        ended = transition_call_status(
            call,
            CALL_STATUS_ENDED,
        )

        self.assertEqual(
            ended.status,
            CALL_STATUS_ENDED,
        )

    def test_terminal_call_cannot_restart(
        self,
    ):
        call = CommunicationCall(
            id=1,
            channel=CHANNEL_PHONE,
            direction=DIRECTION_INBOUND,
            phone_number="+34600123456",
            status=CALL_STATUS_MISSED,
        )

        with self.assertRaises(
            InvalidCallTransition
        ):
            transition_call_status(
                call,
                CALL_STATUS_ANSWERED,
            )

    def test_duplicate_provider_state_is_noop(
        self,
    ):
        call = CommunicationCall(
            id=1,
            channel=CHANNEL_PHONE,
            direction=DIRECTION_INBOUND,
            phone_number="+34600123456",
            status=CALL_STATUS_RINGING,
        )

        repeated = transition_call_status(
            call,
            CALL_STATUS_RINGING,
        )

        self.assertIs(
            repeated,
            call,
        )

    def test_transition_predicate_is_pure(
        self,
    ):
        self.assertTrue(
            can_transition_call_status(
                CALL_STATUS_RINGING,
                CALL_STATUS_ANSWERED,
            )
        )

        self.assertFalse(
            can_transition_call_status(
                CALL_STATUS_ENDED,
                CALL_STATUS_RINGING,
            )
        )

    def test_inbound_call_timing(
        self,
    ):
        call = CommunicationCall(
            id=1,
            channel=CHANNEL_PHONE,
            direction=DIRECTION_INBOUND,
            phone_number="+34600123456",
        )

        call = transition_call_status_at(
            call,
            CALL_STATUS_RINGING,
            "2026-08-14T15:00:00+02:00",
        )

        call = transition_call_status_at(
            call,
            CALL_STATUS_ANSWERED,
            "2026-08-14T15:00:07+02:00",
        )

        self.assertEqual(
            call.ring_duration_seconds,
            7,
        )

        self.assertIsNone(
            call.talk_duration_seconds
        )

        self.assertIsNone(
            call.total_duration_seconds
        )

        call = transition_call_status_at(
            call,
            CALL_STATUS_ENDED,
            "2026-08-14T15:03:07+02:00",
        )

        self.assertEqual(
            call.ring_duration_seconds,
            7,
        )

        self.assertEqual(
            call.talk_duration_seconds,
            180,
        )

        self.assertEqual(
            call.total_duration_seconds,
            187,
        )

    def test_outbound_call_timing(
        self,
    ):
        call = CommunicationCall(
            id=1,
            channel=CHANNEL_PHONE,
            direction=DIRECTION_OUTBOUND,
            phone_number="+34600123456",
        )

        call = transition_call_status_at(
            call,
            "DIALING",
            "2026-08-14T15:00:00+02:00",
        )

        call = transition_call_status_at(
            call,
            CALL_STATUS_RINGING,
            "2026-08-14T15:00:03+02:00",
        )

        call = transition_call_status_at(
            call,
            CALL_STATUS_ANSWERED,
            "2026-08-14T15:00:08+02:00",
        )

        call = transition_call_status_at(
            call,
            CALL_STATUS_ENDED,
            "2026-08-14T15:05:08+02:00",
        )

        self.assertEqual(
            call.ring_duration_seconds,
            5,
        )

        self.assertEqual(
            call.talk_duration_seconds,
            300,
        )

        self.assertEqual(
            call.total_duration_seconds,
            308,
        )

    def test_missed_call_has_zero_talk_duration(
        self,
    ):
        call = CommunicationCall(
            id=1,
            channel=CHANNEL_PHONE,
            direction=DIRECTION_INBOUND,
            phone_number="+34600123456",
        )

        call = transition_call_status_at(
            call,
            CALL_STATUS_RINGING,
            "2026-08-14T15:00:00+02:00",
        )

        call = transition_call_status_at(
            call,
            CALL_STATUS_MISSED,
            "2026-08-14T15:00:12+02:00",
        )

        self.assertEqual(
            call.ring_duration_seconds,
            12,
        )

        self.assertEqual(
            call.talk_duration_seconds,
            0,
        )

        self.assertEqual(
            call.total_duration_seconds,
            12,
        )

    def test_active_answered_call_has_no_final_duration(
        self,
    ):
        call = CommunicationCall(
            id=1,
            channel=CHANNEL_PHONE,
            direction=DIRECTION_INBOUND,
            phone_number="+34600123456",
        )

        call = transition_call_status_at(
            call,
            CALL_STATUS_RINGING,
            "2026-08-14T15:00:00+02:00",
        )

        call = transition_call_status_at(
            call,
            CALL_STATUS_ANSWERED,
            "2026-08-14T15:00:04+02:00",
        )

        self.assertEqual(
            call.ring_duration_seconds,
            4,
        )

        self.assertIsNone(
            call.talk_duration_seconds
        )

        self.assertIsNone(
            call.total_duration_seconds
        )

    def test_duplicate_timed_event_is_noop(
        self,
    ):
        call = CommunicationCall(
            id=1,
            channel=CHANNEL_PHONE,
            direction=DIRECTION_INBOUND,
            phone_number="+34600123456",
        )

        ringing = transition_call_status_at(
            call,
            CALL_STATUS_RINGING,
            "2026-08-14T15:00:00+02:00",
        )

        duplicate = (
            transition_call_status_at(
                ringing,
                CALL_STATUS_RINGING,
                "2026-08-14T15:00:05+02:00",
            )
        )

        self.assertIs(
            duplicate,
            ringing,
        )

        self.assertEqual(
            duplicate.ringing_at,
            "2026-08-14T15:00:00+02:00",
        )

    def test_out_of_order_timestamp_is_rejected(
        self,
    ):
        call = CommunicationCall(
            id=1,
            channel=CHANNEL_PHONE,
            direction=DIRECTION_INBOUND,
            phone_number="+34600123456",
        )

        call = transition_call_status_at(
            call,
            CALL_STATUS_RINGING,
            "2026-08-14T15:00:10+02:00",
        )

        with self.assertRaises(
            InvalidCallTimestamp
        ):
            transition_call_status_at(
                call,
                CALL_STATUS_ANSWERED,
                "2026-08-14T15:00:09+02:00",
            )

    def test_mixed_timezone_awareness_is_rejected(
        self,
    ):
        call = CommunicationCall(
            id=1,
            channel=CHANNEL_PHONE,
            direction=DIRECTION_INBOUND,
            phone_number="+34600123456",
        )

        call = transition_call_status_at(
            call,
            CALL_STATUS_RINGING,
            "2026-08-14T15:00:00+02:00",
        )

        with self.assertRaises(
            InvalidCallTimestamp
        ):
            transition_call_status_at(
                call,
                CALL_STATUS_ANSWERED,
                "2026-08-14T15:00:05",
            )

    def test_direct_outbound_answer_without_ring_is_supported(
        self,
    ):
        call = CommunicationCall(
            id=1,
            channel=CHANNEL_PHONE,
            direction=DIRECTION_OUTBOUND,
            phone_number="+34600123456",
        )

        call = transition_call_status_at(
            call,
            "DIALING",
            "2026-08-14T15:00:00+02:00",
        )

        call = transition_call_status_at(
            call,
            CALL_STATUS_ANSWERED,
            "2026-08-14T15:00:04+02:00",
        )

        call = transition_call_status_at(
            call,
            CALL_STATUS_ENDED,
            "2026-08-14T15:01:04+02:00",
        )

        self.assertIsNone(
            call.ring_duration_seconds
        )

        self.assertEqual(
            call.talk_duration_seconds,
            60,
        )

        self.assertEqual(
            call.total_duration_seconds,
            64,
        )

    def test_reason_catalog_is_stable_and_unique(
        self,
    ):
        options = (
            get_call_reason_options()
        )

        self.assertIs(
            options,
            CALL_REASON_OPTIONS,
        )

        codes = [
            option.code
            for option in options
        ]

        self.assertEqual(
            len(codes),
            14,
        )

        self.assertEqual(
            len(codes),
            len(set(codes)),
        )

        self.assertIn(
            "EXPEDIENT_STATUS",
            codes,
        )

        self.assertIn(
            "PAYMENT",
            codes,
        )

        self.assertIn(
            "OTHER",
            codes,
        )

    def test_outcome_catalog_is_stable_and_unique(
        self,
    ):
        options = (
            get_call_outcome_options()
        )

        self.assertIs(
            options,
            CALL_OUTCOME_OPTIONS,
        )

        codes = [
            option.code
            for option in options
        ]

        self.assertEqual(
            len(codes),
            11,
        )

        self.assertEqual(
            len(codes),
            len(set(codes)),
        )

        self.assertIn(
            "CLIENT_INFORMED",
            codes,
        )

        self.assertIn(
            "NO_ANSWER",
            codes,
        )

        self.assertIn(
            "OTHER",
            codes,
        )

    def test_reason_catalog_returns_label(
        self,
    ):
        self.assertEqual(
            get_call_reason_label(
                "EXPEDIENT_STATUS"
            ),
            "Estado del expediente",
        )

        self.assertEqual(
            get_call_reason_label(
                "MISSING_DOCUMENTATION"
            ),
            "Documentación pendiente",
        )

    def test_outcome_catalog_returns_label(
        self,
    ):
        self.assertEqual(
            get_call_outcome_label(
                "CLIENT_INFORMED"
            ),
            "Cliente informado",
        )

        self.assertEqual(
            get_call_outcome_label(
                "CALL_BACK_LATER"
            ),
            "Volver a llamar",
        )

    def test_catalog_codes_are_normalized(
        self,
    ):
        self.assertEqual(
            normalize_call_reason_code(
                "  expedient_status  "
            ),
            "EXPEDIENT_STATUS",
        )

        self.assertEqual(
            normalize_call_outcome_code(
                " client_informed "
            ),
            "CLIENT_INFORMED",
        )

        self.assertTrue(
            is_valid_call_reason_code(
                "payment"
            )
        )

        self.assertTrue(
            is_valid_call_outcome_code(
                "resolved"
            )
        )

    def test_unknown_catalog_codes_are_not_valid(
        self,
    ):
        self.assertFalse(
            is_valid_call_reason_code(
                "UNKNOWN_REASON"
            )
        )

        self.assertFalse(
            is_valid_call_outcome_code(
                "UNKNOWN_OUTCOME"
            )
        )

        self.assertFalse(
            is_valid_call_reason_code(
                None
            )
        )

        self.assertFalse(
            is_valid_call_outcome_code(
                None
            )
        )

        self.assertIsNone(
            get_call_reason_label(
                "UNKNOWN_REASON"
            )
        )

        self.assertIsNone(
            get_call_outcome_label(
                "UNKNOWN_OUTCOME"
            )
        )


if __name__ == "__main__":
    unittest.main()
