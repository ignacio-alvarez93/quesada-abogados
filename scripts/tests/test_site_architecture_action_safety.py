import pytest

from backend.automation.site_architecture.action_safety import (
    ACTION_SAFETY_DENY,
    ACTION_SAFETY_HUMAN_ONLY,
    ACTION_SAFETY_NAVIGATION_CANDIDATE,
    ACTION_SAFETY_REVERSIBLE_CANDIDATE,
    ACTION_SAFETY_REVIEW_REQUIRED,
    evaluate_action_safety,
)


def _action(
    *,
    kind="SELECT",
    policy="STATE_CHANGE_CANDIDATE",
    selector="#action",
    visible=True,
    disabled=False,
    interactable=True,
    role="",
    href=None,
):
    return {
        "kind":
            kind,

        "policy":
            policy,

        "selector":
            selector,

        "frame_path":
            "main",

        "interaction": {
            "visible":
                visible,

            "disabled":
                disabled,

            "interactable":
                interactable,
        },

        "element": {
            "tag": "div",
            "id": "action",
            "name": "",
            "type": "",
            "role": role,
        },

        "navigation": {
            "href": href,
            "target": None,
        },
    }


@pytest.mark.parametrize(
    "kind",
    (
        "SELECT",
        "RADIO",
        "CHECKBOX",
    ),
)
def test_reversible_state_controls_are_candidates(
    kind,
):
    result = evaluate_action_safety(
        _action(
            kind=kind,
        )
    )

    assert (
        result["decision"]
        == ACTION_SAFETY_REVERSIBLE_CANDIDATE
    )

    assert (
        result["requires_restore"]
        is True
    )



def test_submit_is_always_denied():
    result = evaluate_action_safety(
        _action(
            kind="SUBMIT",
            policy="REQUIRES_POLICY",
        )
    )

    assert (
        result["decision"]
        == ACTION_SAFETY_REVIEW_REQUIRED
    )

    assert (
        result["reason"]
        == "ACTIVE_ACTION_REQUIRES_SITE_POLICY"
    )


def test_file_upload_is_always_denied():
    result = evaluate_action_safety(
        _action(
            kind="FILE_UPLOAD",
            policy="REQUIRES_POLICY",
        )
    )

    assert (
        result["decision"]
        == ACTION_SAFETY_REVIEW_REQUIRED
    )

def test_input_value_probe_is_denied():
    result = evaluate_action_safety(
        _action(
            kind="INPUT_VALUE",
            policy="VALUE_CHANGE_CANDIDATE",
        )
    )

    assert (
        result["decision"]
        == ACTION_SAFETY_REVIEW_REQUIRED
    )



def test_generic_button_requires_review():
    result = evaluate_action_safety(
        _action(
            kind="BUTTON",
            policy="REQUIRES_POLICY",
        )
    )

    assert (
        result["decision"]
        == ACTION_SAFETY_REVIEW_REQUIRED
    )


def test_link_requires_review():
    result = evaluate_action_safety(
        _action(
            kind="LINK",
            policy="NAVIGATION_CANDIDATE",
            href="/next",
        )
    )

    assert (
        result["decision"]
        == ACTION_SAFETY_NAVIGATION_CANDIDATE
    )


def test_local_role_tab_can_be_navigation_candidate():
    result = evaluate_action_safety(
        _action(
            kind="TAB",
            policy="NAVIGATION_CANDIDATE",
            role="tab",
        )
    )

    assert (
        result["decision"]
        == ACTION_SAFETY_NAVIGATION_CANDIDATE
    )


def test_tab_with_href_requires_review():
    result = evaluate_action_safety(
        _action(
            kind="TAB",
            policy="NAVIGATION_CANDIDATE",
            role="tab",
            href="/next",
        )
    )

    assert (
        result["decision"]
        == ACTION_SAFETY_NAVIGATION_CANDIDATE
    )

def test_disabled_action_is_denied():
    result = evaluate_action_safety(
        _action(
            disabled=True,
        )
    )

    assert (
        result["decision"]
        == ACTION_SAFETY_DENY
    )


def test_missing_selector_is_denied():
    result = evaluate_action_safety(
        _action(
            selector=None,
        )
    )

    assert (
        result["decision"]
        == ACTION_SAFETY_DENY
    )


def test_policy_mismatch_is_denied():
    result = evaluate_action_safety(
        _action(
            kind="SELECT",
            policy="NAVIGATION_CANDIDATE",
        )
    )

    assert (
        result["decision"]
        == ACTION_SAFETY_DENY
    )


def test_unknown_action_is_denied():
    result = evaluate_action_safety(
        _action(
            kind="MAGIC_BUTTON",
            policy="UNKNOWN",
        )
    )

    assert (
        result["decision"]
        == ACTION_SAFETY_DENY
    )


def test_policy_output_does_not_copy_pii():
    action = _action()

    action["text"] = "Juan Pérez"
    action["value"] = "X1234567A"

    result = evaluate_action_safety(
        action
    )

    assert "text" not in result["action"]
    assert "value" not in result["action"]


def test_invalid_input_is_rejected():
    with pytest.raises(
        ValueError,
        match=(
            "SITE_ARCHITECTURE_ACTION_SAFETY_INPUT_INVALID"
        ),
    ):
        evaluate_action_safety(
            "click"
        )
