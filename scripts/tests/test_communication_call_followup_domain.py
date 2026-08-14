import unittest

from backend.communications.call_followups import (
    CALL_FOLLOW_UP_IN_PROGRESS,
    CALL_FOLLOW_UP_PENDING,
    CALL_FOLLOW_UP_RESOLVED,
    CommunicationCallCallback,
    CommunicationCallFollowUp,
    InvalidCallFollowUpTransition,
    transition_call_follow_up,
)


class CommunicationCallFollowUpDomainTest(
    unittest.TestCase
):
    def test_follow_up_starts_pending(
        self,
    ):
        follow_up = (
            CommunicationCallFollowUp(
                id=None,
                source_call_id=100,
            )
        )

        self.assertEqual(
            follow_up.status,
            CALL_FOLLOW_UP_PENDING,
        )

        self.assertIsNone(
            follow_up.resolved_at
        )

    def test_pending_can_move_to_in_progress(
        self,
    ):
        follow_up = (
            CommunicationCallFollowUp(
                id=1,
                source_call_id=100,
            )
        )

        active = (
            transition_call_follow_up(
                follow_up,
                CALL_FOLLOW_UP_IN_PROGRESS,
            )
        )

        self.assertEqual(
            active.status,
            CALL_FOLLOW_UP_IN_PROGRESS,
        )

        self.assertEqual(
            follow_up.status,
            CALL_FOLLOW_UP_PENDING,
        )

    def test_in_progress_can_return_to_pending(
        self,
    ):
        follow_up = (
            CommunicationCallFollowUp(
                id=1,
                source_call_id=100,
                status=(
                    CALL_FOLLOW_UP_IN_PROGRESS
                ),
            )
        )

        pending = (
            transition_call_follow_up(
                follow_up,
                CALL_FOLLOW_UP_PENDING,
            )
        )

        self.assertEqual(
            pending.status,
            CALL_FOLLOW_UP_PENDING,
        )

    def test_resolve_requires_timestamp(
        self,
    ):
        follow_up = (
            CommunicationCallFollowUp(
                id=1,
                source_call_id=100,
            )
        )

        with self.assertRaises(
            ValueError
        ):
            transition_call_follow_up(
                follow_up,
                CALL_FOLLOW_UP_RESOLVED,
            )

        resolved = (
            transition_call_follow_up(
                follow_up,
                CALL_FOLLOW_UP_RESOLVED,
                resolved_at=(
                    "2026-08-14T15:30:00+02:00"
                ),
            )
        )

        self.assertEqual(
            resolved.status,
            CALL_FOLLOW_UP_RESOLVED,
        )

        self.assertEqual(
            resolved.resolved_at,
            "2026-08-14T15:30:00+02:00",
        )

    def test_resolved_follow_up_is_terminal(
        self,
    ):
        follow_up = (
            CommunicationCallFollowUp(
                id=1,
                source_call_id=100,
                status=(
                    CALL_FOLLOW_UP_RESOLVED
                ),
                resolved_at=(
                    "2026-08-14T15:30:00+02:00"
                ),
            )
        )

        with self.assertRaises(
            InvalidCallFollowUpTransition
        ):
            transition_call_follow_up(
                follow_up,
                CALL_FOLLOW_UP_PENDING,
            )

    def test_duplicate_state_is_noop(
        self,
    ):
        follow_up = (
            CommunicationCallFollowUp(
                id=1,
                source_call_id=100,
            )
        )

        repeated = (
            transition_call_follow_up(
                follow_up,
                CALL_FOLLOW_UP_PENDING,
            )
        )

        self.assertIs(
            repeated,
            follow_up,
        )

    def test_multiple_callbacks_can_reference_source(
        self,
    ):
        first = CommunicationCallCallback(
            id=1,
            source_call_id=100,
            callback_call_id=101,
        )

        second = CommunicationCallCallback(
            id=2,
            source_call_id=100,
            callback_call_id=102,
        )

        self.assertEqual(
            first.source_call_id,
            second.source_call_id,
        )

        self.assertNotEqual(
            first.callback_call_id,
            second.callback_call_id,
        )


if __name__ == "__main__":
    unittest.main()
