import unittest

from backend.communications.call_snapshots import (
    InvalidProviderCallSnapshot,
    ProviderCallReconciliationConflict,
    ProviderCallSnapshot,
    materialize_provider_call_snapshot,
    merge_provider_call_snapshot,
)
from backend.communications.calls import (
    CALL_STATUS_ANSWERED,
    CALL_STATUS_DIALING,
    CALL_STATUS_ENDED,
    CALL_STATUS_MISSED,
    CALL_STATUS_RINGING,
    CommunicationCall,
    InvalidCallTimestamp,
)
from backend.communications.models import (
    CHANNEL_PHONE,
    DIRECTION_INBOUND,
    DIRECTION_OUTBOUND,
)


class CommunicationCallSnapshotDomainTest(
    unittest.TestCase
):
    def test_historical_inbound_missed_call_materializes_timing(
        self,
    ):
        call = (
            materialize_provider_call_snapshot(
                ProviderCallSnapshot(
                    provider=" mobile_link ",
                    external_call_key=" missed-001 ",
                    channel=CHANNEL_PHONE,
                    direction=DIRECTION_INBOUND,
                    phone_number="+34600800001",
                    status=CALL_STATUS_MISSED,
                    ringing_at=(
                        "2026-08-14T10:00:00+02:00"
                    ),
                    ended_at=(
                        "2026-08-14T10:00:12+02:00"
                    ),
                )
            )
        )

        self.assertEqual(
            call.provider,
            "MOBILE_LINK",
        )

        self.assertEqual(
            call.external_call_key,
            "missed-001",
        )

        self.assertEqual(
            call.status,
            CALL_STATUS_MISSED,
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

    def test_historical_answered_call_materializes_full_timing(
        self,
    ):
        call = (
            materialize_provider_call_snapshot(
                ProviderCallSnapshot(
                    provider="MOBILE_LINK",
                    external_call_key="ended-001",
                    channel=CHANNEL_PHONE,
                    direction=DIRECTION_INBOUND,
                    phone_number="+34600800002",
                    status=CALL_STATUS_ENDED,
                    ringing_at=(
                        "2026-08-14T11:00:00+02:00"
                    ),
                    answered_at=(
                        "2026-08-14T11:00:05+02:00"
                    ),
                    ended_at=(
                        "2026-08-14T11:02:05+02:00"
                    ),
                )
            )
        )

        self.assertEqual(
            call.ring_duration_seconds,
            5,
        )

        self.assertEqual(
            call.talk_duration_seconds,
            120,
        )

        self.assertEqual(
            call.total_duration_seconds,
            125,
        )

    def test_historical_outbound_direct_answer_without_ring(
        self,
    ):
        call = (
            materialize_provider_call_snapshot(
                ProviderCallSnapshot(
                    provider="MOBILE_LINK",
                    external_call_key="ended-002",
                    channel=CHANNEL_PHONE,
                    direction=DIRECTION_OUTBOUND,
                    phone_number="+34600800003",
                    status=CALL_STATUS_ENDED,
                    dialed_at=(
                        "2026-08-14T12:00:00+02:00"
                    ),
                    answered_at=(
                        "2026-08-14T12:00:04+02:00"
                    ),
                    ended_at=(
                        "2026-08-14T12:01:04+02:00"
                    ),
                )
            )
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

    def test_provider_durations_fill_missing_timestamps_without_invention(
        self,
    ):
        call = (
            materialize_provider_call_snapshot(
                ProviderCallSnapshot(
                    provider="MOBILE_LINK",
                    external_call_key="ended-003",
                    channel=CHANNEL_PHONE,
                    direction=DIRECTION_INBOUND,
                    phone_number="+34600800004",
                    status=CALL_STATUS_ENDED,
                    talk_duration_seconds=90,
                    total_duration_seconds=95,
                )
            )
        )

        self.assertIsNone(
            call.ringing_at
        )

        self.assertIsNone(
            call.answered_at
        )

        self.assertIsNone(
            call.ended_at
        )

        self.assertIsNone(
            call.ring_duration_seconds
        )

        self.assertEqual(
            call.talk_duration_seconds,
            90,
        )

        self.assertEqual(
            call.total_duration_seconds,
            95,
        )

    def test_ended_without_answer_timestamp_is_not_zero_talk(
        self,
    ):
        call = (
            materialize_provider_call_snapshot(
                ProviderCallSnapshot(
                    provider="MOBILE_LINK",
                    external_call_key="ended-004",
                    channel=CHANNEL_PHONE,
                    direction=DIRECTION_INBOUND,
                    phone_number="+34600800005",
                    status=CALL_STATUS_ENDED,
                    ringing_at=(
                        "2026-08-14T13:00:00+02:00"
                    ),
                    ended_at=(
                        "2026-08-14T13:02:00+02:00"
                    ),
                )
            )
        )

        self.assertEqual(
            call.total_duration_seconds,
            120,
        )

        self.assertIsNone(
            call.talk_duration_seconds
        )

    def test_non_answered_terminal_without_timestamps_has_known_zero_talk(
        self,
    ):
        call = (
            materialize_provider_call_snapshot(
                ProviderCallSnapshot(
                    provider="MOBILE_LINK",
                    external_call_key="missed-002",
                    channel=CHANNEL_PHONE,
                    direction=DIRECTION_INBOUND,
                    phone_number="+34600800006",
                    status=CALL_STATUS_MISSED,
                )
            )
        )

        self.assertIsNone(
            call.ringing_at
        )

        self.assertIsNone(
            call.ended_at
        )

        self.assertIsNone(
            call.ring_duration_seconds
        )

        self.assertEqual(
            call.talk_duration_seconds,
            0,
        )

        self.assertIsNone(
            call.total_duration_seconds
        )

    def test_derived_and_provider_duration_conflict_is_rejected(
        self,
    ):
        with self.assertRaisesRegex(
            InvalidProviderCallSnapshot,
            "no coincide",
        ):
            materialize_provider_call_snapshot(
                ProviderCallSnapshot(
                    provider="MOBILE_LINK",
                    external_call_key="conflict-001",
                    channel=CHANNEL_PHONE,
                    direction=DIRECTION_INBOUND,
                    phone_number="+34600800007",
                    status=CALL_STATUS_MISSED,
                    ringing_at=(
                        "2026-08-14T14:00:00+02:00"
                    ),
                    ended_at=(
                        "2026-08-14T14:00:10+02:00"
                    ),
                    ring_duration_seconds=9,
                )
            )

    def test_non_answered_terminal_cannot_have_talk_duration(
        self,
    ):
        with self.assertRaisesRegex(
            InvalidProviderCallSnapshot,
            "duración hablada cero",
        ):
            materialize_provider_call_snapshot(
                ProviderCallSnapshot(
                    provider="MOBILE_LINK",
                    external_call_key="invalid-talk",
                    channel=CHANNEL_PHONE,
                    direction=DIRECTION_INBOUND,
                    phone_number="+34600800008",
                    status=CALL_STATUS_MISSED,
                    talk_duration_seconds=5,
                )
            )

    def test_active_snapshot_cannot_contain_ended_at(
        self,
    ):
        with self.assertRaisesRegex(
            InvalidProviderCallSnapshot,
            "RINGING",
        ):
            materialize_provider_call_snapshot(
                ProviderCallSnapshot(
                    provider="MOBILE_LINK",
                    external_call_key="invalid-active",
                    channel=CHANNEL_PHONE,
                    direction=DIRECTION_INBOUND,
                    phone_number="+34600800009",
                    status=CALL_STATUS_RINGING,
                    ended_at=(
                        "2026-08-14T15:00:00+02:00"
                    ),
                )
            )

    def test_inbound_snapshot_cannot_be_dialing(
        self,
    ):
        with self.assertRaisesRegex(
            InvalidProviderCallSnapshot,
            "DIALING",
        ):
            materialize_provider_call_snapshot(
                ProviderCallSnapshot(
                    provider="MOBILE_LINK",
                    external_call_key="invalid-direction",
                    channel=CHANNEL_PHONE,
                    direction=DIRECTION_INBOUND,
                    phone_number="+34600800010",
                    status=CALL_STATUS_DIALING,
                )
            )

    def test_out_of_order_snapshot_is_rejected(
        self,
    ):
        with self.assertRaises(
            InvalidCallTimestamp
        ):
            materialize_provider_call_snapshot(
                ProviderCallSnapshot(
                    provider="MOBILE_LINK",
                    external_call_key="invalid-time",
                    channel=CHANNEL_PHONE,
                    direction=DIRECTION_INBOUND,
                    phone_number="+34600800011",
                    status=CALL_STATUS_ENDED,
                    ringing_at=(
                        "2026-08-14T16:00:10+02:00"
                    ),
                    answered_at=(
                        "2026-08-14T16:00:05+02:00"
                    ),
                    ended_at=(
                        "2026-08-14T16:01:00+02:00"
                    ),
                )
            )

    def test_snapshot_does_not_invent_crm_links(
        self,
    ):
        call = (
            materialize_provider_call_snapshot(
                ProviderCallSnapshot(
                    provider="WHATSAPP_WEB",
                    external_call_key="wa-call-001",
                    provider_call_id="raw-wa-1",
                    channel="WHATSAPP",
                    direction=DIRECTION_INBOUND,
                    phone_number="+34600800012",
                    status=CALL_STATUS_ANSWERED,
                    display_name_snapshot="CONTACTO",
                    ringing_at=(
                        "2026-08-14T17:00:00+02:00"
                    ),
                    answered_at=(
                        "2026-08-14T17:00:03+02:00"
                    ),
                    metadata={
                        "source":
                            "provider_history",
                    },
                )
            )
        )

        self.assertIsNone(
            call.client_id
        )

        self.assertIsNone(
            call.expedient_id
        )

        self.assertIsNone(
            call.thread_id
        )

        self.assertEqual(
            call.provider_call_id,
            "raw-wa-1",
        )

        self.assertEqual(
            call.display_name_snapshot,
            "CONTACTO",
        )


    def test_reconciliation_enriches_without_losing_crm_context(
        self,
    ):
        existing = CommunicationCall(
            id=100,
            channel=CHANNEL_PHONE,
            direction=DIRECTION_INBOUND,
            phone_number="+34600810001",
            client_id=10,
            expedient_id=20,
            thread_id=30,
            reason_code="EXPEDIENT_STATUS",
            status=CALL_STATUS_RINGING,
            provider="MOBILE_LINK",
            external_call_key="merge-001",
            ringing_at=(
                "2026-08-14T18:00:00+02:00"
            ),
            metadata={
                "crm_key": "crm_value",
                "shared": "crm",
            },
        )

        merged = merge_provider_call_snapshot(
            existing,
            ProviderCallSnapshot(
                provider="MOBILE_LINK",
                external_call_key="merge-001",
                provider_call_id="raw-merge-001",
                channel=CHANNEL_PHONE,
                direction=DIRECTION_INBOUND,
                phone_number="600810001",
                display_name_snapshot="PROVIDER NAME",
                status=CALL_STATUS_MISSED,
                ringing_at=(
                    "2026-08-14T18:00:00+02:00"
                ),
                ended_at=(
                    "2026-08-14T18:00:12+02:00"
                ),
                metadata={
                    "history_key": "history_value",
                    "shared": "provider",
                },
            ),
        )

        self.assertEqual(
            merged.id,
            100,
        )

        self.assertEqual(
            merged.phone_number,
            "+34600810001",
        )

        self.assertEqual(
            merged.client_id,
            10,
        )

        self.assertEqual(
            merged.expedient_id,
            20,
        )

        self.assertEqual(
            merged.thread_id,
            30,
        )

        self.assertEqual(
            merged.reason_code,
            "EXPEDIENT_STATUS",
        )

        self.assertEqual(
            merged.provider_call_id,
            "raw-merge-001",
        )

        self.assertEqual(
            merged.display_name_snapshot,
            "PROVIDER NAME",
        )

        self.assertEqual(
            merged.status,
            CALL_STATUS_MISSED,
        )

        self.assertEqual(
            merged.total_duration_seconds,
            12,
        )

        self.assertEqual(
            merged.metadata["crm_key"],
            "crm_value",
        )

        self.assertEqual(
            merged.metadata["history_key"],
            "history_value",
        )

        self.assertEqual(
            merged.metadata["shared"],
            "crm",
        )

    def test_reconciliation_keeps_existing_display_name(
        self,
    ):
        existing = CommunicationCall(
            id=101,
            channel=CHANNEL_PHONE,
            direction=DIRECTION_INBOUND,
            phone_number="+34600810002",
            display_name_snapshot="CRM NAME",
            status=CALL_STATUS_RINGING,
            provider="MOBILE_LINK",
            external_call_key="merge-002",
        )

        merged = merge_provider_call_snapshot(
            existing,
            ProviderCallSnapshot(
                provider="MOBILE_LINK",
                external_call_key="merge-002",
                channel=CHANNEL_PHONE,
                direction=DIRECTION_INBOUND,
                phone_number="+34600810002",
                display_name_snapshot="PROVIDER NAME",
                status=CALL_STATUS_RINGING,
            ),
        )

        self.assertEqual(
            merged.display_name_snapshot,
            "CRM NAME",
        )

    def test_reconciliation_rejects_channel_conflict(
        self,
    ):
        existing = CommunicationCall(
            id=102,
            channel=CHANNEL_PHONE,
            direction=DIRECTION_INBOUND,
            phone_number="+34600810003",
            status=CALL_STATUS_RINGING,
            provider="MOBILE_LINK",
            external_call_key="merge-003",
        )

        with self.assertRaisesRegex(
            ProviderCallReconciliationConflict,
            "channel",
        ):
            merge_provider_call_snapshot(
                existing,
                ProviderCallSnapshot(
                    provider="MOBILE_LINK",
                    external_call_key="merge-003",
                    channel="WHATSAPP",
                    direction=DIRECTION_INBOUND,
                    phone_number="+34600810003",
                    status=CALL_STATUS_RINGING,
                ),
            )

    def test_reconciliation_rejects_provider_call_id_conflict(
        self,
    ):
        existing = CommunicationCall(
            id=103,
            channel=CHANNEL_PHONE,
            direction=DIRECTION_INBOUND,
            phone_number="+34600810004",
            status=CALL_STATUS_RINGING,
            provider="MOBILE_LINK",
            provider_call_id="raw-A",
            external_call_key="merge-004",
        )

        with self.assertRaisesRegex(
            ProviderCallReconciliationConflict,
            "provider_call_id",
        ):
            merge_provider_call_snapshot(
                existing,
                ProviderCallSnapshot(
                    provider="MOBILE_LINK",
                    external_call_key="merge-004",
                    provider_call_id="raw-B",
                    channel=CHANNEL_PHONE,
                    direction=DIRECTION_INBOUND,
                    phone_number="+34600810004",
                    status=CALL_STATUS_RINGING,
                ),
            )

    def test_reconciliation_rejects_terminal_conflict(
        self,
    ):
        existing = CommunicationCall(
            id=104,
            channel=CHANNEL_PHONE,
            direction=DIRECTION_INBOUND,
            phone_number="+34600810005",
            status=CALL_STATUS_MISSED,
            provider="MOBILE_LINK",
            external_call_key="merge-005",
            talk_duration_seconds=0,
        )

        with self.assertRaisesRegex(
            ProviderCallReconciliationConflict,
            "status",
        ):
            merge_provider_call_snapshot(
                existing,
                ProviderCallSnapshot(
                    provider="MOBILE_LINK",
                    external_call_key="merge-005",
                    channel=CHANNEL_PHONE,
                    direction=DIRECTION_INBOUND,
                    phone_number="+34600810005",
                    status=CALL_STATUS_ENDED,
                ),
            )

    def test_reconciliation_rejects_lifecycle_regression(
        self,
    ):
        existing = CommunicationCall(
            id=105,
            channel=CHANNEL_PHONE,
            direction=DIRECTION_INBOUND,
            phone_number="+34600810006",
            status=CALL_STATUS_ANSWERED,
            provider="MOBILE_LINK",
            external_call_key="merge-006",
        )

        with self.assertRaisesRegex(
            ProviderCallReconciliationConflict,
            "status",
        ):
            merge_provider_call_snapshot(
                existing,
                ProviderCallSnapshot(
                    provider="MOBILE_LINK",
                    external_call_key="merge-006",
                    channel=CHANNEL_PHONE,
                    direction=DIRECTION_INBOUND,
                    phone_number="+34600810006",
                    status=CALL_STATUS_RINGING,
                ),
            )

    def test_reconciliation_accepts_equivalent_timestamp_representation(
        self,
    ):
        existing = CommunicationCall(
            id=106,
            channel=CHANNEL_PHONE,
            direction=DIRECTION_INBOUND,
            phone_number="+34600810007",
            status=CALL_STATUS_RINGING,
            provider="MOBILE_LINK",
            external_call_key="merge-007",
            ringing_at=(
                "2026-08-14T16:00:00Z"
            ),
        )

        merged = merge_provider_call_snapshot(
            existing,
            ProviderCallSnapshot(
                provider="MOBILE_LINK",
                external_call_key="merge-007",
                channel=CHANNEL_PHONE,
                direction=DIRECTION_INBOUND,
                phone_number="+34600810007",
                status=CALL_STATUS_RINGING,
                ringing_at=(
                    "2026-08-14T18:00:00+02:00"
                ),
            ),
        )

        self.assertEqual(
            merged.ringing_at,
            "2026-08-14T16:00:00Z",
        )


if __name__ == "__main__":
    unittest.main()
