from backend.automation.site_architecture.action_inventory import (
    ACTION_POLICY_NAVIGATION,
    ACTION_POLICY_REQUIRES_POLICY,
    ACTION_POLICY_STATE_CHANGE,
    ACTION_POLICY_VALUE_CHANGE,
    build_action_inventory,
)


def _element(
    *,
    semantics=(),
    tag="div",
    element_id="",
    role="",
    element_type="",
    attributes=None,
):
    return {
        "index": 1,
        "frame_path": "main",
        "tag": tag,
        "id": element_id,
        "name": "",
        "type": element_type,
        "role": role,
        "attributes": attributes or {},
        "semantics": semantics,
        "selectors": {
            "primary": {
                "selector":
                    (
                        f"#{element_id}"
                        if element_id
                        else tag
                    ),
            },
            "confidence": "HIGH",
        },
        "interaction": {
            "state": "INTERACTABLE",
            "visible": True,
            "interactable": True,
            "disabled": False,
        },
    }


def test_inventory_ignores_non_actionable_element():
    actions = build_action_inventory([
        _element(
            tag="div",
            semantics=(),
        )
    ])

    assert actions == ()


def test_inventory_classifies_select_as_state_change():
    actions = build_action_inventory([
        _element(
            tag="select",
            element_id="province",
            semantics=("SELECT",),
        )
    ])

    assert len(actions) == 1
    assert actions[0]["kind"] == "SELECT"

    assert (
        actions[0]["policy"]
        == ACTION_POLICY_STATE_CHANGE
    )

    assert (
        actions[0]["selector"]
        == "#province"
    )


def test_inventory_classifies_link_as_navigation():
    actions = build_action_inventory([
        _element(
            tag="a",
            element_id="next",
            semantics=("LINK",),
            attributes={
                "href": "/next"
            },
        )
    ])

    assert actions[0]["kind"] == "LINK"

    assert (
        actions[0]["policy"]
        == ACTION_POLICY_NAVIGATION
    )

    assert (
        actions[0]["navigation"]["href"]
        == "/next"
    )


def test_inventory_classifies_tab_as_navigation():
    actions = build_action_inventory([
        _element(
            tag="div",
            element_id="tab-presenter",
            role="tab",
        )
    ])

    assert actions[0]["kind"] == "TAB"

    assert (
        actions[0]["policy"]
        == ACTION_POLICY_NAVIGATION
    )


def test_inventory_classifies_text_input_as_value_change():
    actions = build_action_inventory([
        _element(
            tag="input",
            element_id="nie",
            element_type="text",
            semantics=("TEXT_INPUT",),
        )
    ])

    assert actions[0]["kind"] == "INPUT_VALUE"

    assert (
        actions[0]["policy"]
        == ACTION_POLICY_VALUE_CHANGE
    )


def test_inventory_never_auto_authorizes_submit():
    actions = build_action_inventory([
        _element(
            tag="button",
            element_id="submit",
            element_type="submit",
            semantics=(
                "BUTTON",
                "SUBMIT",
            ),
        )
    ])

    assert actions[0]["kind"] == "SUBMIT"

    assert (
        actions[0]["policy"]
        == ACTION_POLICY_REQUIRES_POLICY
    )


def test_inventory_never_auto_authorizes_generic_button():
    actions = build_action_inventory([
        _element(
            tag="button",
            element_id="action",
            semantics=("BUTTON",),
        )
    ])

    assert actions[0]["kind"] == "BUTTON"

    assert (
        actions[0]["policy"]
        == ACTION_POLICY_REQUIRES_POLICY
    )


def test_inventory_does_not_copy_text_or_value():
    element = _element(
        tag="button",
        element_id="client-action",
        semantics=("BUTTON",),
    )

    element["text"] = "Dato sensible"
    element["value"] = "ABC123"

    action = build_action_inventory(
        [element]
    )[0]

    assert "text" not in action
    assert "value" not in action
