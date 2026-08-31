from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from backend.qcc.context.human_transition_correlator import (
    correlate_observed_human_transition,
)
from backend.qcc.context.observed_human_action import (
    QccObservedHumanAction,
)
from backend.qcc.context.observed_human_transition import (
    QccObservedHumanTransition,
)


FP_A = "a" * 64
FP_B = "b" * 64


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

    def set_observed_human_transition(
        self,
        transition,
    ):
        self.stored = transition
        return transition


def test_correlator_consumes_once_and_stores_transition():
    action = _action()
    store = _FakeStore(
        action
    )

    transition = (
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

    assert transition is not None
    assert transition.before_state == "STATE_A"
    assert transition.after_state == "STATE_B"
    assert transition.changed is True
    assert store.consumed is True
    assert store.stored is transition


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
