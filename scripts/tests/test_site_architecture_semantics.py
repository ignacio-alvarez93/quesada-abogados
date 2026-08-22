from backend.automation.site_architecture.semantics import (
    classify_element_semantics,
)


def test_classifies_basic_form_controls():
    cases = (
        (
            {"tag": "input", "type": "text"},
            ("TEXT_INPUT",),
        ),
        (
            {"tag": "input", "type": "file"},
            ("FILE_INPUT",),
        ),
        (
            {"tag": "input", "type": "checkbox"},
            ("CHECKBOX",),
        ),
        (
            {"tag": "input", "type": "radio"},
            ("RADIO",),
        ),
        (
            {"tag": "select"},
            ("SELECT",),
        ),
        (
            {"tag": "textarea"},
            ("TEXTAREA",),
        ),
    )

    for element, expected in cases:
        assert (
            classify_element_semantics(element)
            == expected
        )


def test_submit_is_button_and_submit():
    assert (
        classify_element_semantics({
            "tag": "input",
            "type": "submit",
        })
        == (
            "BUTTON",
            "SUBMIT",
        )
    )


def test_aria_role_can_define_semantics():
    assert (
        classify_element_semantics({
            "tag": "div",
            "role": "button",
        })
        == ("BUTTON",)
    )


def test_role_does_not_duplicate_native_semantic():
    assert (
        classify_element_semantics({
            "tag": "a",
            "role": "link",
        })
        == ("LINK",)
    )


def test_unknown_element_has_no_invented_semantics():
    assert (
        classify_element_semantics({
            "tag": "div",
        })
        == ()
    )
