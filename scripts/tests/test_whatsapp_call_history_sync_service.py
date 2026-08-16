import unittest

from backend.communications.calls import (
    CALL_STATUS_CANCELLED,
    CALL_STATUS_ENDED,
    CALL_STATUS_MISSED,
)
from backend.services.whatsapp_call_history_sync_service import (
    build_whatsapp_history_reconciliation_plan,
)


def item(
    *,
    key,
    peer_lid="23244480487535@lid",
    outcome="Completed",
    final="Completed",
    row_state="Entrante",
    duration=18,
):
    return {
        "provider_call_id":
            key.rsplit("_", 1)[-1],

        "external_call_key":
            key,

        "peer_lid":
            peer_lid,

        "peer_phone_id":
            "34639156371@c.us",

        "peer_display_name":
            "Mama",

        "provider_timestamp":
            1786892997,

        "call_duration_seconds":
            duration,

        "raw_outcome":
            outcome,

        "raw_final_outcome":
            final,

        "row_state":
            row_state,

        "is_video":
            False,
    }


class WhatsAppCallHistorySyncServiceTest(
    unittest.TestCase
):
    def test_completed_inbound_is_planned_as_ended(
        self,
    ):
        result = (
            build_whatsapp_history_reconciliation_plan({
                "items": [
                    item(
                        key=(
                            "false_23244480487535@lid_CALL1"
                        ),
                    ),
                ],
            })
        )

        self.assertEqual(
            result["planned"],
            1,
        )
        self.assertEqual(
            result["errors"],
            [],
        )
        self.assertEqual(
            result["status_counts"],
            {
                CALL_STATUS_ENDED: 1,
            },
        )

    def test_missed_group_is_planned_as_missed(
        self,
    ):
        result = (
            build_whatsapp_history_reconciliation_plan({
                "items": [
                    item(
                        key=(
                            "false_23244480487535@lid_CALL2"
                        ),
                        outcome="Canceled",
                        final="Canceled",
                        row_state="Perdida (5)",
                        duration=0,
                    ),
                ],
            })
        )

        self.assertEqual(
            result["status_counts"],
            {
                CALL_STATUS_MISSED: 1,
            },
        )

    def test_outbound_unanswered_is_cancelled(
        self,
    ):
        result = (
            build_whatsapp_history_reconciliation_plan({
                "items": [
                    item(
                        key=(
                            "true_23244480487535@lid_CALL3"
                        ),
                        outcome="Missed",
                        final="Canceled",
                        row_state="Saliente",
                        duration=0,
                    ),
                ],
            })
        )

        self.assertEqual(
            result["status_counts"],
            {
                CALL_STATUS_CANCELLED: 1,
            },
        )

    def test_peer_identity_mismatch_fails_closed(
        self,
    ):
        result = (
            build_whatsapp_history_reconciliation_plan({
                "items": [
                    item(
                        key=(
                            "false_23244480487535@lid_CALL4"
                        ),
                        peer_lid=(
                            "99999999999999@lid"
                        ),
                    ),
                ],
            })
        )

        self.assertEqual(
            result["planned"],
            0,
        )
        self.assertEqual(
            len(
                result["errors"]
            ),
            1,
        )

    def test_unknown_semantics_fail_closed(
        self,
    ):
        result = (
            build_whatsapp_history_reconciliation_plan({
                "items": [
                    item(
                        key=(
                            "false_23244480487535@lid_CALL5"
                        ),
                        outcome="UnknownOutcome",
                        final=None,
                        row_state="Entrante",
                        duration=None,
                    ),
                ],
            })
        )

        self.assertEqual(
            result["planned"],
            0,
        )
        self.assertEqual(
            len(
                result["errors"]
            ),
            1,
        )


if __name__ == "__main__":
    unittest.main()
