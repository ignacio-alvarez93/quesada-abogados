from backend.automation.site_architecture.visibility import (
    normalize_interaction_state,
)


def _button(**overrides):
    element = {
        "tag": "button",
        "visible": True,
        "disabled": False,
        "semantics": ("BUTTON",),
        "interaction_signals": {
            "hidden": False,
            "aria_hidden": False,
            "aria_disabled": False,
            "readonly": False,
            "in_viewport": True,
            "opacity": "1",
            "pointer_events": "auto",
        },
    }

    element.update(overrides)
    return element


def test_visible_button_is_interactable():
    state = normalize_interaction_state(
        _button()
    )

    assert state["visible"] is True
    assert state["interactable"] is True
    assert state["state"] == "INTERACTABLE"


def test_disabled_element_is_not_interactable():
    state = normalize_interaction_state(
        _button(disabled=True)
    )

    assert state["disabled"] is True
    assert state["state"] == "DISABLED"
    assert state["interactable"] is False


def test_off_viewport_element_is_not_immediately_interactable():
    element = _button()
    element["interaction_signals"] = dict(
        element["interaction_signals"],
        in_viewport=False,
    )

    state = normalize_interaction_state(
        element
    )

    assert state["visible"] is True
    assert state["in_viewport"] is False
    assert state["state"] == "OFF_VIEWPORT"


def test_aria_hidden_element_is_hidden():
    element = _button()
    element["interaction_signals"] = dict(
        element["interaction_signals"],
        aria_hidden=True,
    )

    state = normalize_interaction_state(
        element
    )

    assert state["visible"] is False
    assert state["state"] == "HIDDEN"


def test_readonly_text_input_is_readonly():
    element = _button(
        tag="input",
        semantics=("TEXT_INPUT",),
    )
    element["interaction_signals"] = dict(
        element["interaction_signals"],
        readonly=True,
    )

    state = normalize_interaction_state(
        element
    )

    assert state["state"] == "READONLY"
    assert state["interactable"] is False


def test_visible_non_actionable_element_is_not_interactable():
    state = normalize_interaction_state({
        **_button(),
        "tag": "div",
        "semantics": (),
    })

    assert (
        state["state"]
        == "NOT_INTERACTABLE"
    )
