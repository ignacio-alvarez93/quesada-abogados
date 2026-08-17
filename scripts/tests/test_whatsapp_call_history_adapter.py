import unittest

from backend.communications.calls import (
    CALL_DIRECTION_INBOUND,
    CALL_DIRECTION_OUTBOUND,
    CALL_STATUS_CANCELLED,
    CALL_STATUS_ENDED,
    CALL_STATUS_MISSED,
)
from backend.services.whatsapp_call_history_adapter import (
    WhatsAppHistoricalCallSnapshot,
    project_whatsapp_history_snapshot,
)


class WhatsAppCallHistoryAdapterTest(
    unittest.TestCase
):
    def test_inbound_completed(self):
        result = project_whatsapp_history_snapshot(
            WhatsAppHistoricalCallSnapshot(
                provider_call_id="CALL-1",
                external_call_key=(
                    "false_23244480487535@lid_CALL-1"
                ),
                peer_lid="23244480487535@lid",
                peer_phone_id="34639156371@c.us",
                peer_display_name="Mama",
                provider_timestamp=1786892997,
                call_duration_seconds=18,
                raw_outcome="Completed",
                raw_final_outcome="Completed",
                row_state="Entrante",
            )
        )

        self.assertEqual(
            result.direction,
            CALL_DIRECTION_INBOUND,
        )
        self.assertEqual(
            result.status,
            CALL_STATUS_ENDED,
        )
        self.assertEqual(
            result.phone_number,
            "+34639156371",
        )
        self.assertEqual(
            result.talk_duration_seconds,
            18,
        )

    def test_inbound_missed_group_overrides_raw_canceled(self):
        result = project_whatsapp_history_snapshot(
            WhatsAppHistoricalCallSnapshot(
                provider_call_id="CALL-2",
                external_call_key=(
                    "false_23244480487535@lid_CALL-2"
                ),
                peer_lid="23244480487535@lid",
                peer_phone_id="34639156371@c.us",
                peer_display_name="Mama",
                provider_timestamp=1786868431,
                call_duration_seconds=0,
                raw_outcome="Canceled",
                raw_final_outcome="Canceled",
                row_state="Perdida (5)",
            )
        )

        self.assertEqual(
            result.status,
            CALL_STATUS_MISSED,
        )

    def test_outbound_canceled(self):
        result = project_whatsapp_history_snapshot(
            WhatsAppHistoricalCallSnapshot(
                provider_call_id="CALL-3",
                external_call_key=(
                    "true_23244480487535@lid_CALL-3"
                ),
                peer_lid="23244480487535@lid",
                peer_phone_id="34639156371@c.us",
                peer_display_name="Mama",
                provider_timestamp=1786892960,
                call_duration_seconds=0,
                raw_outcome="Missed",
                raw_final_outcome="Canceled",
                row_state="Saliente (11)",
            )
        )

        self.assertEqual(
            result.direction,
            CALL_DIRECTION_OUTBOUND,
        )
        self.assertEqual(
            result.status,
            CALL_STATUS_CANCELLED,
        )

    def test_unknown_semantics_fail_closed(self):
        with self.assertRaises(ValueError):
            project_whatsapp_history_snapshot(
                WhatsAppHistoricalCallSnapshot(
                    provider_call_id="CALL-4",
                    external_call_key=(
                        "false_23244480487535@lid_CALL-4"
                    ),
                    peer_lid="23244480487535@lid",
                    peer_phone_id="34639156371@c.us",
                    peer_display_name="Mama",
                    provider_timestamp=1786892997,
                    call_duration_seconds=None,
                    raw_outcome="UnknownProviderOutcome",
                    raw_final_outcome=None,
                    row_state="Entrante",
                )
            )


    def test_accepted_elsewhere_is_historical_ended(self):
        result = project_whatsapp_history_snapshot(
            WhatsAppHistoricalCallSnapshot(
                provider_call_id="CALL-AE",
                external_call_key=(
                    "false_21565165068295@lid_CALL-AE"
                ),
                peer_lid="21565165068295@lid",
                peer_phone_id="34631003414@c.us",
                peer_display_name="Mi Amor",
                provider_timestamp=1786741476,
                call_duration_seconds=None,
                raw_outcome="AcceptedElsewhere",
                raw_final_outcome=None,
                row_state="Entrante",
            )
        )

        self.assertEqual(
            result.status,
            CALL_STATUS_ENDED,
        )
        self.assertIsNone(
            result.talk_duration_seconds,
        )

    def test_ongoing_with_final_completed_is_ended(self):
        result = project_whatsapp_history_snapshot(
            WhatsAppHistoricalCallSnapshot(
                provider_call_id="CALL-ONGOING",
                external_call_key=(
                    "true_23244480487535@lid_CALL-ONGOING"
                ),
                peer_lid="23244480487535@lid",
                peer_phone_id="34639156371@c.us",
                peer_display_name="Mama",
                provider_timestamp=1786893232,
                call_duration_seconds=0,
                raw_outcome="Ongoing",
                raw_final_outcome="Completed",
                row_state="Saliente",
            )
        )

        self.assertEqual(
            result.status,
            CALL_STATUS_ENDED,
        )

    def test_rejected_inside_missed_row_is_missed(self):
        result = project_whatsapp_history_snapshot(
            WhatsAppHistoricalCallSnapshot(
                provider_call_id="CALL-REJECTED",
                external_call_key=(
                    "false_29403463581864@lid_CALL-REJECTED"
                ),
                peer_lid="29403463581864@lid",
                peer_phone_id="447425929197@c.us",
                peer_display_name="Jorge",
                provider_timestamp=1786807987,
                call_duration_seconds=0,
                raw_outcome="Rejected",
                raw_final_outcome="Missed",
                row_state="Perdida (3)",
            )
        )

        self.assertEqual(
            result.status,
            CALL_STATUS_MISSED,
        )


if __name__ == "__main__":
    unittest.main()
