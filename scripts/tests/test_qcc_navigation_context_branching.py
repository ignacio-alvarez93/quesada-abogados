from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from backend.qcc.context.navigation_context import (
    derive_navigation_discriminator_keys,
    navigation_context_signature,
    normalize_navigation_context,
    project_navigation_context,
)
from backend.qcc.context.observed_human_action import (
    QccObservedHumanAction,
)
from backend.qcc.context.observed_human_transition import (
    QccObservedHumanTransition,
)
from backend.qcc.navigation_learning.human_candidate_store import (
    _candidate_id,
    _safe_identity,
)


FP_A = "a" * 64
FP_B = "b" * 64
FP_C = "c" * 64


def _context(ex_value, province="ASTURIAS"):
    return [
        {
            "key": "EX_MODEL",
            "selector": "#modelo-ex",
            "kind": "RADIO",
            "selected_values": [ex_value],
        },
        {
            "key": "PROVINCIA",
            "selector": "#provincia",
            "kind": "SELECT",
            "selected_values": [province],
        },
    ]


def test_context_signature_is_order_independent():
    one = _context("EX01")
    two = list(reversed(one))

    assert (
        navigation_context_signature(one)
        == navigation_context_signature(two)
    )


def test_action_to_transition_preserves_pre_action_context():
    now = datetime.now(timezone.utc)

    action = QccObservedHumanAction(
        event_id="evt-1",
        session_id="session-1",
        site_code="MERCURIO",
        environment="REAL",
        before_state="SELECT_EX",
        before_fingerprint=FP_A,
        kind="BUTTON",
        policy="HUMAN_ONLY",
        selector="#continuar",
        frame_path="main",
        observed_at=now,
        navigation_context=_context("EX01"),
    )

    transition = QccObservedHumanTransition.from_action(
        action,
        after_state="EX01",
        after_fingerprint=FP_B,
        after_observed_at=(
            now
            + timedelta(
                milliseconds=100,
            )
        ),
    )

    assert (
        transition.navigation_context
        == normalize_navigation_context(
            _context("EX01")
        )
    )

    payload = transition.to_runtime_dict()

    assert "navigation_context" not in payload

    assert (
        transition.navigation_context[0]["key"]
        == "EX_MODEL"
    )


def test_candidate_identity_is_branch_specific():
    base = dict(
        changed=True,
        site_code="MERCURIO",
        environment="REAL",
        before_state="SELECT_EX",
        before_fingerprint=FP_A,
        kind="BUTTON",
        policy="HUMAN_ONLY",
        selector="#continuar",
        frame_path="main",
        after_state="EX",
        after_fingerprint=FP_B,
    )

    ex01 = SimpleNamespace(
        **base,
        navigation_context=_context("EX01"),
    )

    ex02 = SimpleNamespace(
        **base,
        navigation_context=_context("EX02"),
    )

    one = _safe_identity(ex01)
    two = _safe_identity(ex02)

    assert one["context_signature"]
    assert two["context_signature"]

    assert (
        one["context_signature"]
        != two["context_signature"]
    )

    assert (
        _candidate_id(one)
        != _candidate_id(two)
    )


def test_discriminator_ignores_constant_province():
    transitions = [
        {
            "after_fingerprint": FP_B,
            "navigation_context":
                _context(
                    "EX01",
                    province="ASTURIAS",
                ),
        },
        {
            "after_fingerprint": FP_C,
            "navigation_context":
                _context(
                    "EX02",
                    province="ASTURIAS",
                ),
        },
    ]

    keys = (
        derive_navigation_discriminator_keys(
            transitions
        )
    )

    assert keys == ("EX_MODEL",)

    projected = (
        project_navigation_context(
            transitions[0][
                "navigation_context"
            ],
            keys,
        )
    )

    assert len(projected) == 1
    assert projected[0]["key"] == "EX_MODEL"
