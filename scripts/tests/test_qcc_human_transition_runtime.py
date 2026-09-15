from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from backend.qcc.context.human_transition_correlator import (
    correlate_observed_human_transition,
    finalize_observed_human_transition,
)
from backend.qcc.context.observed_human_action import (
    QccObservedHumanAction,
)
from backend.qcc.context.observed_human_transition import (
    QccObservedHumanTransition,
)


FP_A = "a" * 64
FP_B = "b" * 64
FP_C = "c" * 64


def _action(
    *,
    observed_at=None,
):
    return QccObservedHumanAction(
        event_id="event-1",
        session_id="session-1",
        site_code="MERCURIO",
        environment="LAB",
        before_state="STATE_A",
        before_fingerprint=FP_A,
        kind="LINK",
        policy="NAVIGATION_CANDIDATE",
        selector="#btncont",
        frame_path="main",
        observed_at=(
            observed_at
            or datetime.now(
                timezone.utc
            )
        ),
    )


def test_transition_from_human_action():
    action = _action()

    transition = (
        QccObservedHumanTransition
        .from_action(
            action,
            after_state="STATE_B",
            after_fingerprint=FP_B,
            after_observed_at=(
                action.observed_at
                + timedelta(
                    seconds=1
                )
            ),
        )
    )

    assert transition.event_id == "event-1"
    assert transition.before_state == "STATE_A"
    assert transition.after_state == "STATE_B"
    assert transition.changed is True

    assert transition.transition_action() == {
        "kind":
            "LINK",
        "policy":
            "NAVIGATION_CANDIDATE",
        "selector":
            "#btncont",
        "frame_path":
            "main",
    }


def test_transition_requires_b_after_action():
    action = _action()

    with pytest.raises(
        ValueError,
        match=(
            "QCC_HUMAN_TRANSITION_AFTER_NOT_AFTER_ACTION"
        ),
    ):
        QccObservedHumanTransition.from_action(
            action,
            after_state="STATE_B",
            after_fingerprint=FP_B,
            after_observed_at=(
                action.observed_at
            ),
        )


class _FakeStore:
    def __init__(
        self,
        action,
    ):
        self.action = action
        self.consumed = False
        self.stored = None

        self.session = SimpleNamespace(
            session_id="session-1",
            provider="MERCURIO",
        )

        self.current = SimpleNamespace(
            session_id="session-1",
            current_state="STATE_B",
            current_fingerprint=FP_B,
        )

    def get_active_session(self):
        return self.session

    def get_live_navigation(self):
        return self.current

    def get_navigation_environment(self):
        return "LAB"

    def get_observed_human_action(self):
        return self.action

    def consume_observed_human_action(
        self,
        *,
        session_id,
        now=None,
        ttl_seconds=30.0,
    ):
        assert session_id == "session-1"
        self.consumed = True

        action = self.action
        self.action = None
        return action

    def get_observed_human_transition(
        self,
    ):
        return self.stored

    def set_observed_human_transition(
        self,
        transition,
    ):
        self.stored = transition
        return transition

    def clear_observed_human_transition(
        self,
        *,
        session_id=None,
    ):
        if self.stored is None:
            return False

        if (
            session_id is not None
            and self.stored.session_id
            != session_id
        ):
            return False

        self.stored = None
        return True


def test_correlator_keeps_action_open_and_updates_latest_current():
    action = _action()
    store = _FakeStore(
        action
    )

    # --------------------------------------------------
    # B1 · first CURRENT after the physical action.
    # Must remain provisional.
    # --------------------------------------------------

    first = (
        correlate_observed_human_transition(
            store,
            after_site_code="MERCURIO",
            after_observed_at=(
                action.observed_at
                + timedelta(
                    seconds=1
                )
            ),
        )
    )

    assert first is not None
    assert first.before_state == "STATE_A"
    assert first.after_state == "STATE_B"
    assert first.after_fingerprint == FP_B

    # Critical new contract:
    # first CURRENT does NOT consume the human action.
    assert store.consumed is False
    assert store.action is action
    assert store.stored is first

    # --------------------------------------------------
    # B2 · later CURRENT from the SAME physical action.
    # This must replace B1 as provisional destination.
    # --------------------------------------------------

    store.current = SimpleNamespace(
        session_id="session-1",
        current_state="STATE_C",
        current_fingerprint=FP_C,
    )

    second = (
        correlate_observed_human_transition(
            store,
            after_site_code="MERCURIO",
            after_observed_at=(
                action.observed_at
                + timedelta(
                    seconds=2
                )
            ),
        )
    )

    assert second is not None
    assert second.event_id == first.event_id
    assert second.before_state == "STATE_A"
    assert second.before_fingerprint == FP_A
    assert second.after_state == "STATE_C"
    assert second.after_fingerprint == FP_C

    assert store.consumed is False
    assert store.action is action
    assert store.stored is second

    # --------------------------------------------------
    # Next physical action boundary.
    # Finalize X against the LAST observed CURRENT B2.
    # --------------------------------------------------

    finalized = (
        finalize_observed_human_transition(
            store,
            before_next_action_at=(
                action.observed_at
                + timedelta(
                    seconds=3
                )
            ),
        )
    )

    assert finalized is second
    assert finalized.after_state == "STATE_C"
    assert finalized.after_fingerprint == FP_C

    assert store.consumed is True
    assert store.action is None
    assert store.stored is None


def test_correlator_without_pending_action_is_noop():
    store = _FakeStore(
        None
    )

    result = (
        correlate_observed_human_transition(
            store,
            after_site_code="MERCURIO",
            after_observed_at=(
                datetime.now(
                    timezone.utc
                )
            ),
        )
    )

    assert result is None
    assert store.consumed is False


def test_wrong_site_does_not_consume_action():
    action = _action()
    store = _FakeStore(
        action
    )

    result = (
        correlate_observed_human_transition(
            store,
            after_site_code="OTHER",
            after_observed_at=(
                action.observed_at
                + timedelta(
                    seconds=1
                )
            ),
        )
    )

    assert result is None
    assert store.consumed is False


def test_runtime_projection_is_pii_safe():
    action = _action()

    transition = (
        QccObservedHumanTransition
        .from_action(
            action,
            after_state="STATE_B",
            after_fingerprint=FP_B,
            after_observed_at=(
                action.observed_at
                + timedelta(
                    seconds=1
                )
            ),
        )
    )

    payload = (
        transition
        .to_runtime_dict()
    )

    assert payload["changed"] is True
    assert payload["action"]["selector"] == "#btncont"

    serialized = str(
        payload
    ).lower()

    for forbidden in (
        "nie",
        "email",
        "phone",
        "value",
        "text",
        "payload",
    ):
        assert forbidden not in serialized
