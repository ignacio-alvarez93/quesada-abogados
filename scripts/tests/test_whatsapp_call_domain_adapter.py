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
    project_whatsapp_call_intent_to_provider_snapshot,
)
from backend.services.whatsapp_call_observation import (
    CALL_OBSERVATION_SURFACE_APPEARED,
    CALL_OBSERVATION_UPDATED,
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


    def test_incoming_ringing_to_ended_transient_maps_to_missed(
        self,
    ):
        ringing = call_snapshot(
            phase=(
                WHATSAPP_CALL_PHASE_INCOMING_RINGING
            ),
            direction=(
                WHATSAPP_CALL_DIRECTION_INBOUND
            ),
        )

        ended = call_snapshot(
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

        result = adapt_whatsapp_call_observation(
            changed,
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
            "MISSED",
        )

        self.assertEqual(
            result.intent.external_call_key,
            ringing.external_call_key,
        )

        self.assertEqual(
            result.intent.provider_call_id,
            ringing.provider_call_id,
        )

        self.assertEqual(
            result.intent.metadata[
                "crm_terminal_inference"
            ],
            "INCOMING_RINGING_TO_ENDED_TRANSIENT",
        )

        projected = (
            project_whatsapp_call_intent_to_provider_snapshot(
                result.intent
            )
        )

        self.assertEqual(
            projected.status,
            "MISSED",
        )

        self.assertIsNone(
            projected.ended_at
        )

        self.assertEqual(
            projected.metadata[
                "crm_observed_missed_at"
            ],
            OBSERVED_AT,
        )

        self.assertEqual(
            projected.metadata[
                "crm_observed_missed_provider_phase"
            ],
            WHATSAPP_CALL_PHASE_ENDED_TRANSIENT,
        )


    def test_answered_to_ended_transient_does_not_become_missed(
        self,
    ):
        active = call_snapshot(
            phase=(
                WHATSAPP_CALL_PHASE_ACTIVE
            ),
            direction=(
                WHATSAPP_CALL_DIRECTION_INBOUND
            ),
        )

        ended = call_snapshot(
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
            previous=active,
            current=ended,
            active=ended,
            disappeared=None,
        )

        result = adapt_whatsapp_call_observation(
            changed,
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


    def test_incoming_ringing_disappearance_maps_to_missed(
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

        self.assertTrue(
            result.ready
        )

        self.assertEqual(
            result.reason,
            "READY",
        )

        self.assertEqual(
            result.intent.status,
            "MISSED",
        )

        self.assertEqual(
            result.intent.external_call_key,
            snapshot.external_call_key,
        )

        self.assertEqual(
            result.intent.metadata[
                "crm_terminal_inference"
            ],
            "INCOMING_RINGING_SURFACE_DISAPPEARED",
        )

        projected = (
            project_whatsapp_call_intent_to_provider_snapshot(
                result.intent
            )
        )

        self.assertEqual(
            projected.status,
            "MISSED",
        )

        self.assertIsNone(
            projected.ended_at
        )

        self.assertEqual(
            projected.metadata[
                "crm_observed_missed_at"
            ],
            OBSERVED_AT,
        )

        self.assertEqual(
            projected.metadata[
                "crm_observed_missed_provider_phase"
            ],
            WHATSAPP_CALL_PHASE_INCOMING_RINGING,
        )


    def test_answered_disappearance_does_not_become_missed(
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

        self.assertIsNone(
            result.intent
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


    def test_realtime_projection_keeps_observed_at_out_of_provider_timestamps(
        self,
    ):
        adaptation = adapt_whatsapp_call_observation(
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

        snapshot = (
            project_whatsapp_call_intent_to_provider_snapshot(
                adaptation.intent
            )
        )

        self.assertEqual(
            snapshot.status,
            CALL_STATUS_ANSWERED,
        )

        self.assertIsNone(
            snapshot.dialed_at
        )

        self.assertIsNone(
            snapshot.ringing_at
        )

        self.assertIsNone(
            snapshot.answered_at
        )

        self.assertIsNone(
            snapshot.ended_at
        )

        self.assertEqual(
            snapshot.metadata[
                "crm_observed_answered_at"
            ],
            OBSERVED_AT,
        )


    def test_realtime_projection_uses_status_specific_observation_metadata(
        self,
    ):
        cases = (
            (
                WHATSAPP_CALL_PHASE_INCOMING_RINGING,
                WHATSAPP_CALL_DIRECTION_INBOUND,
                "crm_observed_ringing_at",
            ),
            (
                WHATSAPP_CALL_PHASE_OUTGOING_DIALING,
                WHATSAPP_CALL_DIRECTION_OUTBOUND,
                "crm_observed_dialing_at",
            ),
            (
                WHATSAPP_CALL_PHASE_ACTIVE,
                WHATSAPP_CALL_DIRECTION_OUTBOUND,
                "crm_observed_answered_at",
            ),
        )

        for (
            phase,
            direction,
            metadata_key,
        ) in cases:
            with self.subTest(
                phase=phase
            ):
                adaptation = (
                    adapt_whatsapp_call_observation(
                        observation(
                            call_snapshot(
                                phase=phase,
                                direction=direction,
                            )
                        ),
                        observed_at=OBSERVED_AT,
                    )
                )

                snapshot = (
                    project_whatsapp_call_intent_to_provider_snapshot(
                        adaptation.intent
                    )
                )

                self.assertEqual(
                    snapshot.metadata[
                        metadata_key
                    ],
                    OBSERVED_AT,
                )


    def test_projection_preserves_canonical_provider_identity(
        self,
    ):
        adaptation = adapt_whatsapp_call_observation(
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

        snapshot = (
            project_whatsapp_call_intent_to_provider_snapshot(
                adaptation.intent
            )
        )

        self.assertEqual(
            snapshot.provider,
            "WHATSAPP_WEB",
        )

        self.assertEqual(
            snapshot.external_call_key,
            "Opaque_Key_TRUE_false_001",
        )

        self.assertEqual(
            snapshot.provider_call_id,
            "raw-call-001",
        )

        self.assertEqual(
            snapshot.phone_number,
            "+34600111222",
        )


    def test_projection_uses_status_specific_provider_phase_metadata(
        self,
    ):
        adaptation = adapt_whatsapp_call_observation(
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

        snapshot = (
            project_whatsapp_call_intent_to_provider_snapshot(
                adaptation.intent
            )
        )

        self.assertNotIn(
            "provider_phase",
            snapshot.metadata,
        )

        self.assertEqual(
            snapshot.metadata[
                "crm_observed_answered_provider_phase"
            ],
            WHATSAPP_CALL_PHASE_ACTIVE,
        )

        self.assertEqual(
            snapshot.metadata[
                "crm_observed_answered_at"
            ],
            OBSERVED_AT,
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
