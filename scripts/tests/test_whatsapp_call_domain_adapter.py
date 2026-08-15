import unittest
from dataclasses import replace

from backend.automation.connectors.whatsapp_connector import (
    WHATSAPP_CALL_DIRECTION_INBOUND,
    WHATSAPP_CALL_DIRECTION_OUTBOUND,
    WHATSAPP_CALL_DIRECTION_UNKNOWN,
    WHATSAPP_CALL_PHASE_ACTIVE,
    WHATSAPP_CALL_PHASE_CONNECTING,
    WHATSAPP_CALL_PHASE_ENDED_TRANSIENT,
    WHATSAPP_CALL_PHASE_INCOMING_RINGING,
    WHATSAPP_CALL_PHASE_OUTGOING_DIALING,
    WhatsAppCallSnapshot,
)
from backend.communications.calls import (
    CALL_DIRECTION_INBOUND,
    CALL_DIRECTION_OUTBOUND,
    CALL_STATUS_ANSWERED,
    CALL_STATUS_DIALING,
    CALL_STATUS_RINGING,
)
from backend.communications.models import (
    CHANNEL_WHATSAPP,
)
from backend.services.whatsapp_call_domain_adapter import (
    WHATSAPP_CALL_ADAPT_DIRECTION_PHASE_CONFLICT,
    WHATSAPP_CALL_ADAPT_DIRECTION_UNKNOWN,
    WHATSAPP_CALL_ADAPT_EXTERNAL_KEY_MISSING,
    WHATSAPP_CALL_ADAPT_NO_ACTIVE_SURFACE,
    WHATSAPP_CALL_ADAPT_PHASE_NOT_ACTIONABLE,
    WHATSAPP_CALL_ADAPT_PHONE_MISSING,
    WHATSAPP_CALL_ADAPT_READY,
    WHATSAPP_CALL_ADAPT_UNCHANGED,
    WHATSAPP_CALL_ADAPT_VIDEO_UNSUPPORTED,
    WHATSAPP_CALL_PROVIDER,
    adapt_whatsapp_call_observation,
)
from backend.services.whatsapp_call_observation import (
    CALL_OBSERVATION_SURFACE_APPEARED,
    WhatsAppCallObservation,
)


OBSERVED_AT = (
    "2026-08-15T10:30:00+02:00"
)


def call_snapshot(
    *,
    phase,
    direction,
):
    return WhatsAppCallSnapshot(
        present=True,
        phase=phase,
        direction=direction,
        provider_call_id="raw-call-001",
        external_call_key="Opaque_Key_TRUE_false_001",
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
    snapshot,
    *,
    changed=True,
):
    return WhatsAppCallObservation(
        changed=changed,
        change_type=(
            CALL_OBSERVATION_SURFACE_APPEARED
        ),
        previous=None,
        current=snapshot,
        active=snapshot,
        disappeared=None,
    )


class WhatsAppCallDomainAdapterTest(
    unittest.TestCase
):
    def test_incoming_ringing_maps_to_domain_ringing(
        self,
    ):
        result = adapt_whatsapp_call_observation(
            observation(
                call_snapshot(
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

        self.assertTrue(
            result.ready
        )

        self.assertEqual(
            result.reason,
            WHATSAPP_CALL_ADAPT_READY,
        )

        self.assertEqual(
            result.intent.status,
            CALL_STATUS_RINGING,
        )

        self.assertEqual(
            result.intent.direction,
            CALL_DIRECTION_INBOUND,
        )


    def test_outgoing_dialing_maps_to_domain_dialing(
        self,
    ):
        result = adapt_whatsapp_call_observation(
            observation(
                call_snapshot(
                    phase=(
                        WHATSAPP_CALL_PHASE_OUTGOING_DIALING
                    ),
                    direction=(
                        WHATSAPP_CALL_DIRECTION_OUTBOUND
                    ),
                )
            ),
            observed_at=OBSERVED_AT,
        )

        self.assertTrue(
            result.ready
        )

        self.assertEqual(
            result.intent.status,
            CALL_STATUS_DIALING,
        )

        self.assertEqual(
            result.intent.direction,
            CALL_DIRECTION_OUTBOUND,
        )


    def test_active_inbound_maps_to_answered(
        self,
    ):
        result = adapt_whatsapp_call_observation(
            observation(
                call_snapshot(
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

        self.assertTrue(
            result.ready
        )

        self.assertEqual(
            result.intent.status,
            CALL_STATUS_ANSWERED,
        )

        self.assertEqual(
            result.intent.direction,
            CALL_DIRECTION_INBOUND,
        )


    def test_active_outbound_maps_to_answered(
        self,
    ):
        result = adapt_whatsapp_call_observation(
            observation(
                call_snapshot(
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

        self.assertTrue(
            result.ready
        )

        self.assertEqual(
            result.intent.status,
            CALL_STATUS_ANSWERED,
        )

        self.assertEqual(
            result.intent.direction,
            CALL_DIRECTION_OUTBOUND,
        )


    def test_provider_identity_and_key_are_preserved_opaque(
        self,
    ):
        snapshot = call_snapshot(
            phase=(
                WHATSAPP_CALL_PHASE_OUTGOING_DIALING
            ),
            direction=(
                WHATSAPP_CALL_DIRECTION_OUTBOUND
            ),
        )

        result = adapt_whatsapp_call_observation(
            observation(
                snapshot
            ),
            observed_at=OBSERVED_AT,
        )

        self.assertEqual(
            result.intent.provider,
            WHATSAPP_CALL_PROVIDER,
        )

        self.assertEqual(
            result.intent.provider,
            "WHATSAPP_WEB",
        )

        self.assertEqual(
            result.intent.channel,
            CHANNEL_WHATSAPP,
        )

        self.assertEqual(
            result.intent.external_call_key,
            "Opaque_Key_TRUE_false_001",
        )

        self.assertEqual(
            result.intent.provider_call_id,
            "raw-call-001",
        )

        self.assertEqual(
            result.intent.phone_number,
            "+34600111222",
        )


    def test_connecting_is_not_actionable(
        self,
    ):
        result = adapt_whatsapp_call_observation(
            observation(
                call_snapshot(
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

        self.assertFalse(
            result.ready
        )

        self.assertEqual(
            result.reason,
            WHATSAPP_CALL_ADAPT_PHASE_NOT_ACTIONABLE,
        )


    def test_ended_transient_does_not_invent_terminal_status(
        self,
    ):
        result = adapt_whatsapp_call_observation(
            observation(
                call_snapshot(
                    phase=(
                        WHATSAPP_CALL_PHASE_ENDED_TRANSIENT
                    ),
                    direction=(
                        WHATSAPP_CALL_DIRECTION_INBOUND
                    ),
                )
            ),
            observed_at=OBSERVED_AT,
        )

        self.assertFalse(
            result.ready
        )

        self.assertEqual(
            result.reason,
            WHATSAPP_CALL_ADAPT_PHASE_NOT_ACTIONABLE,
        )

        self.assertIsNone(
            result.intent
        )


    def test_disappeared_surface_does_not_emit_domain_event(
        self,
    ):
        snapshot = call_snapshot(
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
            direction=(
                WHATSAPP_CALL_DIRECTION_UNKNOWN
            ),
        )

        disappeared = WhatsAppCallObservation(
            changed=True,
            change_type=(
                "CALL_SURFACE_DISAPPEARED"
            ),
            previous=snapshot,
            current=provider_absent,
            active=None,
            disappeared=snapshot,
        )

        result = adapt_whatsapp_call_observation(
            disappeared,
            observed_at=OBSERVED_AT,
        )

        self.assertFalse(
            result.ready
        )

        self.assertEqual(
            result.reason,
            WHATSAPP_CALL_ADAPT_NO_ACTIVE_SURFACE,
        )


    def test_unknown_direction_is_not_ready(
        self,
    ):
        result = adapt_whatsapp_call_observation(
            observation(
                call_snapshot(
                    phase=(
                        WHATSAPP_CALL_PHASE_ACTIVE
                    ),
                    direction=(
                        WHATSAPP_CALL_DIRECTION_UNKNOWN
                    ),
                )
            ),
            observed_at=OBSERVED_AT,
        )

        self.assertFalse(
            result.ready
        )

        self.assertEqual(
            result.reason,
            WHATSAPP_CALL_ADAPT_DIRECTION_UNKNOWN,
        )


    def test_phase_direction_conflict_is_rejected(
        self,
    ):
        result = adapt_whatsapp_call_observation(
            observation(
                call_snapshot(
                    phase=(
                        WHATSAPP_CALL_PHASE_INCOMING_RINGING
                    ),
                    direction=(
                        WHATSAPP_CALL_DIRECTION_OUTBOUND
                    ),
                )
            ),
            observed_at=OBSERVED_AT,
        )

        self.assertFalse(
            result.ready
        )

        self.assertEqual(
            result.reason,
            WHATSAPP_CALL_ADAPT_DIRECTION_PHASE_CONFLICT,
        )


    def test_external_key_is_required_for_domain_intent(
        self,
    ):
        snapshot = replace(
            call_snapshot(
                phase=(
                    WHATSAPP_CALL_PHASE_OUTGOING_DIALING
                ),
                direction=(
                    WHATSAPP_CALL_DIRECTION_OUTBOUND
                ),
            ),
            external_call_key=None,
            identity_complete=False,
        )

        result = adapt_whatsapp_call_observation(
            observation(
                snapshot
            ),
            observed_at=OBSERVED_AT,
        )

        self.assertFalse(
            result.ready
        )

        self.assertEqual(
            result.reason,
            WHATSAPP_CALL_ADAPT_EXTERNAL_KEY_MISSING,
        )


    def test_phone_is_required_for_domain_intent(
        self,
    ):
        snapshot = replace(
            call_snapshot(
                phase=(
                    WHATSAPP_CALL_PHASE_OUTGOING_DIALING
                ),
                direction=(
                    WHATSAPP_CALL_DIRECTION_OUTBOUND
                ),
            ),
            participant_phone=None,
        )

        result = adapt_whatsapp_call_observation(
            observation(
                snapshot
            ),
            observed_at=OBSERVED_AT,
        )

        self.assertFalse(
            result.ready
        )

        self.assertEqual(
            result.reason,
            WHATSAPP_CALL_ADAPT_PHONE_MISSING,
        )


    def test_video_is_explicitly_deferred(
        self,
    ):
        snapshot = replace(
            call_snapshot(
                phase=(
                    WHATSAPP_CALL_PHASE_ACTIVE
                ),
                direction=(
                    WHATSAPP_CALL_DIRECTION_INBOUND
                ),
            ),
            is_video=True,
        )

        result = adapt_whatsapp_call_observation(
            observation(
                snapshot
            ),
            observed_at=OBSERVED_AT,
        )

        self.assertFalse(
            result.ready
        )

        self.assertEqual(
            result.reason,
            WHATSAPP_CALL_ADAPT_VIDEO_UNSUPPORTED,
        )


    def test_unchanged_observation_does_not_emit_duplicate_intent(
        self,
    ):
        snapshot = call_snapshot(
            phase=(
                WHATSAPP_CALL_PHASE_ACTIVE
            ),
            direction=(
                WHATSAPP_CALL_DIRECTION_INBOUND
            ),
        )

        result = adapt_whatsapp_call_observation(
            observation(
                snapshot,
                changed=False,
            ),
            observed_at=OBSERVED_AT,
        )

        self.assertFalse(
            result.ready
        )

        self.assertEqual(
            result.reason,
            WHATSAPP_CALL_ADAPT_UNCHANGED,
        )


    def test_observed_at_is_crm_observation_time_not_generated_here(
        self,
    ):
        result = adapt_whatsapp_call_observation(
            observation(
                call_snapshot(
                    phase=(
                        WHATSAPP_CALL_PHASE_ACTIVE
                    ),
                    direction=(
                        WHATSAPP_CALL_DIRECTION_INBOUND
                    ),
                )
            ),
            observed_at=(
                "2026-08-15T08:45:12Z"
            ),
        )

        self.assertEqual(
            result.observed_at,
            "2026-08-15T08:45:12Z",
        )

        self.assertEqual(
            result.intent.observed_at,
            "2026-08-15T08:45:12Z",
        )


    def test_observed_at_requires_timezone(
        self,
    ):
        with self.assertRaisesRegex(
            ValueError,
            "zona horaria",
        ):
            adapt_whatsapp_call_observation(
                observation(
                    call_snapshot(
                        phase=(
                            WHATSAPP_CALL_PHASE_ACTIVE
                        ),
                        direction=(
                            WHATSAPP_CALL_DIRECTION_INBOUND
                        ),
                    )
                ),
                observed_at=(
                    "2026-08-15T10:30:00"
                ),
            )


if __name__ == "__main__":
    unittest.main()
