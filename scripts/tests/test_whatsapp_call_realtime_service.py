from types import SimpleNamespace
import unittest

from backend.automation.connectors.whatsapp_connector import (
    WHATSAPP_CALL_DIRECTION_INBOUND,
    WHATSAPP_CALL_DIRECTION_OUTBOUND,
    WHATSAPP_CALL_PHASE_ACTIVE,
    WHATSAPP_CALL_PHASE_CONNECTING,
    WHATSAPP_CALL_PHASE_ENDED_TRANSIENT,
    WHATSAPP_CALL_PHASE_INCOMING_RINGING,
    WhatsAppCallSnapshot,
)
from backend.communications.calls import (
    CALL_STATUS_ANSWERED,
    CALL_STATUS_RINGING,
)
from backend.services.whatsapp_call_observation import (
    CALL_OBSERVATION_SURFACE_APPEARED,
    CALL_OBSERVATION_UPDATED,
    WhatsAppCallObservation,
)
from backend.services.whatsapp_call_realtime_service import (
    WHATSAPP_CALL_REALTIME_DISABLED,
    WHATSAPP_CALL_REALTIME_NOT_ACTIONABLE,
    WHATSAPP_CALL_REALTIME_RECONCILED,
    WhatsAppCallRealtimeService,
)


OBSERVED_AT = (
    "2026-08-15T09:30:00+00:00"
)


class FakeCallService:
    def __init__(
        self,
    ):
        self.snapshots = []
        self.error = None

    def reconcile_provider_call(
        self,
        snapshot,
    ):
        self.snapshots.append(
            snapshot
        )

        if self.error is not None:
            raise self.error

        return SimpleNamespace(
            id=len(
                self.snapshots
            ),
            provider=(
                snapshot.provider
            ),
            external_call_key=(
                snapshot.external_call_key
            ),
            status=(
                snapshot.status
            ),
        )


def snapshot(
    *,
    phase,
    direction,
):
    return WhatsAppCallSnapshot(
        present=True,
        phase=phase,
        direction=direction,
        provider_call_id="raw-call-001",
        external_call_key="opaque-call-001",
        participant_lid="remote@lid",
        participant_phone_id=(
            "34600111222@c.us"
        ),
        participant_phone="+34600111222",
        participant_display_name="Contacto",
        is_video=False,
        identity_complete=True,
    )


def observation(
    provider_snapshot,
):
    return WhatsAppCallObservation(
        changed=True,
        change_type=(
            CALL_OBSERVATION_SURFACE_APPEARED
        ),
        previous=None,
        current=provider_snapshot,
        active=provider_snapshot,
        disappeared=None,
    )


class WhatsAppCallRealtimeServiceTest(
    unittest.TestCase
):
    def test_disabled_service_never_requires_clock_or_persists(
        self,
    ):
        service = WhatsAppCallRealtimeService(
            call_service=None
        )

        result = service.process_observation(
            observation(
                snapshot(
                    phase=(
                        WHATSAPP_CALL_PHASE_INCOMING_RINGING
                    ),
                    direction=(
                        WHATSAPP_CALL_DIRECTION_INBOUND
                    ),
                )
            ),
            observed_at=None,
        )

        self.assertEqual(
            result.action,
            WHATSAPP_CALL_REALTIME_DISABLED,
        )

        self.assertIsNone(
            result.persisted_call
        )

        self.assertIsNone(
            result.provider_snapshot
        )


    def test_non_actionable_surface_never_reaches_call_service(
        self,
    ):
        call_service = FakeCallService()

        service = WhatsAppCallRealtimeService(
            call_service=call_service
        )

        result = service.process_observation(
            observation(
                snapshot(
                    phase=(
                        WHATSAPP_CALL_PHASE_CONNECTING
                    ),
                    direction=(
                        WHATSAPP_CALL_DIRECTION_OUTBOUND
                    ),
                )
            ),
            observed_at=OBSERVED_AT,
        )

        self.assertEqual(
            result.action,
            WHATSAPP_CALL_REALTIME_NOT_ACTIONABLE,
        )

        self.assertEqual(
            call_service.snapshots,
            [],
        )


    def test_ringing_observation_reconciles_provider_snapshot(
        self,
    ):
        call_service = FakeCallService()

        service = WhatsAppCallRealtimeService(
            call_service=call_service
        )

        result = service.process_observation(
            observation(
                snapshot(
                    phase=(
                        WHATSAPP_CALL_PHASE_INCOMING_RINGING
                    ),
                    direction=(
                        WHATSAPP_CALL_DIRECTION_INBOUND
                    ),
                )
            ),
            observed_at=OBSERVED_AT,
        )

        self.assertEqual(
            result.action,
            WHATSAPP_CALL_REALTIME_RECONCILED,
        )

        self.assertEqual(
            len(
                call_service.snapshots
            ),
            1,
        )

        projected = (
            call_service.snapshots[0]
        )

        self.assertEqual(
            projected.status,
            CALL_STATUS_RINGING,
        )

        self.assertIsNone(
            projected.ringing_at
        )

        self.assertEqual(
            projected.metadata[
                "crm_observed_ringing_at"
            ],
            OBSERVED_AT,
        )

        self.assertEqual(
            result.persisted_call.status,
            CALL_STATUS_RINGING,
        )


    def test_late_active_reconciles_without_fake_lifecycle_timestamp(
        self,
    ):
        call_service = FakeCallService()

        service = WhatsAppCallRealtimeService(
            call_service=call_service
        )

        result = service.process_observation(
            observation(
                snapshot(
                    phase=(
                        WHATSAPP_CALL_PHASE_ACTIVE
                    ),
                    direction=(
                        WHATSAPP_CALL_DIRECTION_OUTBOUND
                    ),
                )
            ),
            observed_at=OBSERVED_AT,
        )

        self.assertEqual(
            result.action,
            WHATSAPP_CALL_REALTIME_RECONCILED,
        )

        projected = (
            result.provider_snapshot
        )

        self.assertEqual(
            projected.status,
            CALL_STATUS_ANSWERED,
        )

        self.assertIsNone(
            projected.dialed_at
        )

        self.assertIsNone(
            projected.ringing_at
        )

        self.assertIsNone(
            projected.answered_at
        )

        self.assertIsNone(
            projected.ended_at
        )

        self.assertEqual(
            projected.metadata[
                "crm_observed_answered_at"
            ],
            OBSERVED_AT,
        )

        self.assertEqual(
            projected.metadata[
                "crm_observed_answered_provider_phase"
            ],
            WHATSAPP_CALL_PHASE_ACTIVE,
        )

        self.assertNotIn(
            "provider_phase",
            projected.metadata,
        )


    def test_incoming_ringing_to_ended_transient_reconciles_missed(
        self,
    ):
        call_service = FakeCallService()

        service = WhatsAppCallRealtimeService(
            call_service=call_service
        )

        ringing = snapshot(
            phase=(
                WHATSAPP_CALL_PHASE_INCOMING_RINGING
            ),
            direction=(
                WHATSAPP_CALL_DIRECTION_INBOUND
            ),
        )

        ended = snapshot(
            phase=(
                WHATSAPP_CALL_PHASE_ENDED_TRANSIENT
            ),
            direction=(
                WHATSAPP_CALL_DIRECTION_INBOUND
            ),
        )

        changed = WhatsAppCallObservation(
            changed=True,
            change_type=(
                CALL_OBSERVATION_UPDATED
            ),
            previous=ringing,
            current=ended,
            active=ended,
            disappeared=None,
        )

        result = service.process_observation(
            changed,
            observed_at=OBSERVED_AT,
        )

        self.assertEqual(
            result.action,
            WHATSAPP_CALL_REALTIME_RECONCILED,
        )

        self.assertEqual(
            len(
                call_service.snapshots
            ),
            1,
        )

        projected = (
            call_service.snapshots[0]
        )

        self.assertEqual(
            projected.status,
            "MISSED",
        )

        self.assertEqual(
            projected.external_call_key,
            ringing.external_call_key,
        )

        self.assertEqual(
            projected.provider_call_id,
            ringing.provider_call_id,
        )

        self.assertEqual(
            projected.metadata[
                "crm_terminal_inference"
            ],
            "INCOMING_RINGING_TO_ENDED_TRANSIENT",
        )

        self.assertEqual(
            projected.metadata[
                "crm_observed_missed_provider_phase"
            ],
            WHATSAPP_CALL_PHASE_ENDED_TRANSIENT,
        )


    def test_incoming_ringing_disappearance_reconciles_missed(
        self,
    ):
        call_service = FakeCallService()

        service = WhatsAppCallRealtimeService(
            call_service=call_service
        )

        ringing = snapshot(
            phase=(
                WHATSAPP_CALL_PHASE_INCOMING_RINGING
            ),
            direction=(
                WHATSAPP_CALL_DIRECTION_INBOUND
            ),
        )

        provider_absent = WhatsAppCallSnapshot(
            present=False,
            phase="ABSENT",
            direction="UNKNOWN",
        )

        disappeared = WhatsAppCallObservation(
            changed=True,
            change_type=(
                "CALL_SURFACE_DISAPPEARED"
            ),
            previous=ringing,
            current=provider_absent,
            active=None,
            disappeared=ringing,
        )

        result = service.process_observation(
            disappeared,
            observed_at=OBSERVED_AT,
        )

        self.assertEqual(
            result.action,
            WHATSAPP_CALL_REALTIME_RECONCILED,
        )

        self.assertEqual(
            len(
                call_service.snapshots
            ),
            1,
        )

        projected = (
            call_service.snapshots[0]
        )

        self.assertEqual(
            projected.status,
            "MISSED",
        )

        self.assertEqual(
            projected.external_call_key,
            ringing.external_call_key,
        )

        self.assertEqual(
            projected.metadata[
                "crm_observed_missed_at"
            ],
            OBSERVED_AT,
        )

        self.assertEqual(
            projected.metadata[
                "crm_terminal_inference"
            ],
            "INCOMING_RINGING_SURFACE_DISAPPEARED",
        )


    def test_call_service_error_is_not_hidden(
        self,
    ):
        call_service = FakeCallService()
        call_service.error = RuntimeError(
            "provider persistence failed"
        )

        service = WhatsAppCallRealtimeService(
            call_service=call_service
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "provider persistence failed",
        ):
            service.process_observation(
                observation(
                    snapshot(
                        phase=(
                            WHATSAPP_CALL_PHASE_ACTIVE
                        ),
                        direction=(
                            WHATSAPP_CALL_DIRECTION_INBOUND
                        ),
                    )
                ),
                observed_at=OBSERVED_AT,
            )


if __name__ == "__main__":
    unittest.main()
