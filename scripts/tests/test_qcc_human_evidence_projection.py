import pytest

from backend.qcc.bridge.server import (
    _human_addressable_live_actions,
)
from backend.qcc.context.live_action_evidence import (
    QccCanonicalLiveAction,
)


def _action(
    *,
    kind="BUTTON",
    policy="HUMAN_ONLY",
    selector="#continuar",
    frame_path="main",
):
    return {
        "kind":
            kind,

        "policy":
            policy,

        "selector":
            selector,

        "frame_path":
            frame_path,

        "visible":
            True,

        "disabled":
            False,

        "in_viewport":
            True,

        "opacity":
            1.0,

        "pointer_events":
            "auto",
    }


def test_human_projection_omits_selectorless_action():
    selectorless = _action(
        selector=None,
    )

    addressable = _action(
        selector="#btncont",
    )

    projected = (
        _human_addressable_live_actions(
            (
                selectorless,
                addressable,
            )
        )
    )

    assert projected == (
        addressable,
    )


def test_human_projection_does_not_reclassify_policy():
    raw = _action(
        policy="REQUIRES_POLICY",
        selector="#btncont",
    )

    projected = (
        _human_addressable_live_actions(
            (
                raw,
            )
        )
    )

    assert projected == (
        raw,
    )

    assert (
        projected[0]["policy"]
        == "REQUIRES_POLICY"
    )


def test_human_projection_requires_complete_identity():
    valid = _action()

    actions = (
        _action(
            kind=None,
        ),
        _action(
            policy=None,
        ),
        _action(
            selector=None,
        ),
        valid,
    )

    assert (
        _human_addressable_live_actions(
            actions
        )
        == (
            valid,
        )
    )


def test_human_projection_does_not_mutate_source():
    raw = [
        _action(
            selector=None,
        ),
        _action(
            selector="#btncont",
        ),
    ]

    before = [
        dict(
            action
        )
        for action
        in raw
    ]

    _human_addressable_live_actions(
        raw
    )

    assert raw == before


def test_strict_canonical_action_still_rejects_missing_selector():
    with pytest.raises(
        ValueError,
        match=(
            "QCC_LIVE_ACTION_EVIDENCE_SELECTOR_REQUIRED"
        ),
    ):
        QccCanonicalLiveAction(
            kind="BUTTON",
            policy="HUMAN_ONLY",
            selector=None,
        )
