import unittest

from backend.automation.connectors.whatsapp_connector import (
    WHATSAPP_CALL_DIRECTION_INBOUND,
    WHATSAPP_CALL_DIRECTION_OUTBOUND,
    WHATSAPP_CALL_DIRECTION_UNKNOWN,
    WHATSAPP_CALL_PHASE_ABSENT,
    WHATSAPP_CALL_PHASE_ACTIVE,
    WHATSAPP_CALL_PHASE_CONNECTING,
    WHATSAPP_CALL_PHASE_ENDED_TRANSIENT,
    WHATSAPP_CALL_PHASE_INCOMING_RINGING,
    WHATSAPP_CALL_PHASE_OUTGOING_DIALING,
    WhatsAppCallSnapshot,
)
from backend.services.whatsapp_call_observation import (
    CALL_OBSERVATION_ABSENT,
    CALL_OBSERVATION_REPLACED,
    CALL_OBSERVATION_SURFACE_APPEARED,
    CALL_OBSERVATION_SURFACE_DISAPPEARED,
    CALL_OBSERVATION_UNCHANGED,
    CALL_OBSERVATION_UPDATED,
    WhatsAppCallObservationTracker,
)


def absent_snapshot():
    return WhatsAppCallSnapshot(
        present=False,
        phase=(
            WHATSAPP_CALL_PHASE_ABSENT
        ),
        direction=(
            WHATSAPP_CALL_DIRECTION_UNKNOWN
        ),
    )


def connecting_snapshot():
    return WhatsAppCallSnapshot(
        present=True,
        phase=(
            WHATSAPP_CALL_PHASE_CONNECTING
        ),
        direction=(
            WHATSAPP_CALL_DIRECTION_UNKNOWN
        ),
        can_hangup=True,
        identity_complete=False,
    )


def dialing_snapshot(
    call_id="CALL-001",
):
    return WhatsAppCallSnapshot(
        present=True,
        phase=(
            WHATSAPP_CALL_PHASE_OUTGOING_DIALING
        ),
        direction=(
            WHATSAPP_CALL_DIRECTION_OUTBOUND
        ),
        provider_call_id=call_id,
        external_call_key=(
            f"opaque-{call_id}"
        ),
        participant_lid="remote@lid",
        participant_phone_id=(
            "34600111222@c.us"
        ),
        participant_phone="+34600111222",
        participant_display_name="Contacto",
        is_video=False,
        visible_state="Llamando...",
        can_hangup=True,
        identity_complete=True,
    )


class WhatsAppCallObservationTrackerTest(
    unittest.TestCase
):
    def test_absent_without_active_call_is_not_change(
        self,
    ):
        tracker = (
            WhatsAppCallObservationTracker()
        )

        result = tracker.observe(
            absent_snapshot()
        )

        self.assertFalse(
            result.changed
        )

        self.assertEqual(
            result.change_type,
            CALL_OBSERVATION_ABSENT,
        )

        self.assertIsNone(
            result.active
        )

        self.assertIsNone(
            result.disappeared
        )


    def test_partial_connecting_can_be_promoted_to_identified_dialing(
        self,
    ):
        tracker = (
            WhatsAppCallObservationTracker()
        )

        first = tracker.observe(
            connecting_snapshot()
        )

        second = tracker.observe(
            dialing_snapshot()
        )

        self.assertEqual(
            first.change_type,
            CALL_OBSERVATION_SURFACE_APPEARED,
        )

        self.assertEqual(
            second.change_type,
            CALL_OBSERVATION_UPDATED,
        )

        self.assertTrue(
            second.active.identity_complete
        )

        self.assertEqual(
            second.active.provider_call_id,
            "CALL-001",
        )

        self.assertEqual(
            second.active.direction,
            WHATSAPP_CALL_DIRECTION_OUTBOUND,
        )


    def test_ended_transient_retains_known_call_identity(
        self,
    ):
        tracker = (
            WhatsAppCallObservationTracker()
        )

        dialing = dialing_snapshot()

        tracker.observe(
            dialing
        )

        active = WhatsAppCallSnapshot(
            present=True,
            phase=(
                WHATSAPP_CALL_PHASE_ACTIVE
            ),
            direction=(
                WHATSAPP_CALL_DIRECTION_UNKNOWN
            ),
            provider_call_id="CALL-001",
            external_call_key=(
                "opaque-CALL-001"
            ),
            visible_state="0:03",
            can_hangup=True,
            identity_complete=False,
        )

        active_result = (
            tracker.observe(
                active
            )
        )

        self.assertEqual(
            active_result.active.direction,
            WHATSAPP_CALL_DIRECTION_OUTBOUND,
        )

        self.assertEqual(
            active_result.active.participant_phone,
            "+34600111222",
        )

        ended = WhatsAppCallSnapshot(
            present=True,
            phase=(
                WHATSAPP_CALL_PHASE_ENDED_TRANSIENT
            ),
            direction=(
                WHATSAPP_CALL_DIRECTION_OUTBOUND
            ),
            provider_call_id="CALL-001",
            external_call_key=(
                "opaque-CALL-001"
            ),
            identity_complete=False,
        )

        ended_result = (
            tracker.observe(
                ended
            )
        )

        self.assertEqual(
            ended_result.change_type,
            CALL_OBSERVATION_UPDATED,
        )

        self.assertEqual(
            ended_result.active.participant_phone,
            "+34600111222",
        )

        self.assertEqual(
            ended_result.active.participant_lid,
            "remote@lid",
        )

        self.assertTrue(
            ended_result.active.identity_complete
        )

        # Los campos visuales NO se heredan.
        self.assertIsNone(
            ended_result.active.visible_state
        )

        self.assertFalse(
            ended_result.active.can_hangup
        )


    def test_absent_after_known_call_returns_disappeared_snapshot(
        self,
    ):
        tracker = (
            WhatsAppCallObservationTracker()
        )

        tracker.observe(
            dialing_snapshot()
        )

        result = tracker.observe(
            absent_snapshot()
        )

        self.assertEqual(
            result.change_type,
            CALL_OBSERVATION_SURFACE_DISAPPEARED,
        )

        self.assertTrue(
            result.changed
        )

        self.assertIsNone(
            result.active
        )

        self.assertEqual(
            result.disappeared.provider_call_id,
            "CALL-001",
        )

        self.assertIsNone(
            tracker.active
        )


    def test_ringing_disappearance_does_not_invent_missed_status(
        self,
    ):
        tracker = (
            WhatsAppCallObservationTracker()
        )

        ringing = WhatsAppCallSnapshot(
            present=True,
            phase=(
                WHATSAPP_CALL_PHASE_INCOMING_RINGING
            ),
            direction=(
                WHATSAPP_CALL_DIRECTION_INBOUND
            ),
            provider_call_id="CALL-IN-001",
            external_call_key=(
                "opaque-CALL-IN-001"
            ),
            participant_lid="remote@lid",
            participant_phone_id=(
                "34600111222@c.us"
            ),
            participant_phone="+34600111222",
            can_accept=True,
            can_reject=True,
            identity_complete=True,
        )

        tracker.observe(
            ringing
        )

        result = tracker.observe(
            absent_snapshot()
        )

        self.assertEqual(
            result.change_type,
            CALL_OBSERVATION_SURFACE_DISAPPEARED,
        )

        self.assertEqual(
            result.disappeared.phase,
            WHATSAPP_CALL_PHASE_INCOMING_RINGING,
        )

        self.assertFalse(
            hasattr(
                result,
                "status",
            )
        )

        self.assertFalse(
            hasattr(
                result,
                "outcome",
            )
        )


    def test_identical_snapshot_is_unchanged(
        self,
    ):
        tracker = (
            WhatsAppCallObservationTracker()
        )

        snapshot = dialing_snapshot()

        first = tracker.observe(
            snapshot
        )

        second = tracker.observe(
            snapshot
        )

        self.assertEqual(
            first.change_type,
            CALL_OBSERVATION_SURFACE_APPEARED,
        )

        self.assertTrue(
            first.changed
        )

        self.assertEqual(
            second.change_type,
            CALL_OBSERVATION_UNCHANGED,
        )

        self.assertFalse(
            second.changed
        )

        self.assertEqual(
            second.active,
            snapshot,
        )

        self.assertIsNone(
            second.disappeared
        )


    def test_different_provider_identity_replaces_active_surface(
        self,
    ):
        tracker = (
            WhatsAppCallObservationTracker()
        )

        first = dialing_snapshot(
            call_id="CALL-001",
        )

        second = dialing_snapshot(
            call_id="CALL-002",
        )

        tracker.observe(
            first
        )

        result = tracker.observe(
            second
        )

        self.assertEqual(
            result.change_type,
            CALL_OBSERVATION_REPLACED,
        )

        self.assertEqual(
            result.previous.provider_call_id,
            "CALL-001",
        )

        self.assertEqual(
            result.active.provider_call_id,
            "CALL-002",
        )


if __name__ == "__main__":
    unittest.main()
