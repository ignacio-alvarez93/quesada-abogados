from backend.automation.site_architecture.selectors import (
    SelectorStrategy,
    build_selector_candidates,
    resolve_selector_profile,
)


def _button(
    *,
    onclick,
    element_id="",
    aria_label="",
):
    return {
        "tag":
            "button",

        "id":
            element_id,

        "name":
            "",

        "type":
            "button",

        "role":
            "",

        "frame_path":
            "main",

        "attributes": {
            "onclick":
                onclick,

            "aria-label":
                aria_label,
        },
    }


def test_simple_onclick_function_is_safe_selector_candidate():
    element = _button(
        onclick="irOpcion()"
    )

    candidates = (
        build_selector_candidates(
            element
        )
    )

    onclick = [
        item
        for item in candidates
        if (
            item.strategy
            == SelectorStrategy.ONCLICK
        )
    ]

    assert len(onclick) == 1

    assert (
        onclick[0].selector
        == (
            'button['
            'onclick="irOpcion()"]'
        )
    )


def test_return_simple_function_is_supported():
    element = _button(
        onclick="return irOpcion();"
    )

    selectors = {
        item.selector
        for item
        in build_selector_candidates(
            element
        )
    }

    assert (
        'button['
        'onclick="return irOpcion();"]'
        in selectors
    )


def test_window_function_is_supported():
    element = _button(
        onclick="window.irOpcion()"
    )

    selectors = {
        item.selector
        for item
        in build_selector_candidates(
            element
        )
    }

    assert (
        'button['
        'onclick="window.irOpcion()"]'
        in selectors
    )


def test_arbitrary_object_method_is_rejected():
    values = (
        "this.form.submit()",
        "foo.bar()",
        "document.forms.submit()",
        "obj.method()",
    )

    for value in values:
        candidates = (
            build_selector_candidates(
                _button(
                    onclick=value
                )
            )
        )

        assert all(
            item.strategy
            != SelectorStrategy.ONCLICK
            for item in candidates
        )


def test_onclick_with_arguments_is_not_selector_candidate():
    element = _button(
        onclick=(
            'enviar("NIE-X1234567")'
        )
    )

    candidates = (
        build_selector_candidates(
            element
        )
    )

    assert all(
        item.strategy
        != SelectorStrategy.ONCLICK
        for item in candidates
    )

    serialized = repr(
        candidates
    )

    assert (
        "X1234567"
        not in serialized
    )


def test_arbitrary_javascript_is_not_selector_candidate():
    dangerous_values = (
        "foo(); bar();",
        "location.href='/secret'",
        "this.form.submit()",
        "func(value)",
        "alert('hello')",
        "x = 1",
    )

    for value in dangerous_values:
        candidates = (
            build_selector_candidates(
                _button(
                    onclick=value
                )
            )
        )

        assert all(
            item.strategy
            != SelectorStrategy.ONCLICK
            for item in candidates
        )


def test_unique_onclick_can_be_primary():
    button = _button(
        onclick="irOpcion()"
    )

    other = _button(
        onclick="cerrarOpcion()"
    )

    profile = (
        resolve_selector_profile(
            button,
            (
                button,
                other,
            ),
        )
    )

    assert (
        profile.primary
        is not None
    )

    assert (
        profile.primary.strategy
        == SelectorStrategy.ONCLICK
    )

    assert (
        profile.primary.selector
        == (
            'button['
            'onclick="irOpcion()"]'
        )
    )

    assert (
        profile.primary.unique
        is True
    )


def test_duplicate_onclick_is_not_primary():
    first = _button(
        onclick="irOpcion()"
    )

    second = _button(
        onclick="irOpcion()"
    )

    profile = (
        resolve_selector_profile(
            first,
            (
                first,
                second,
            ),
        )
    )

    assert all(
        not (
            item.strategy
            == SelectorStrategy.ONCLICK
            and item.unique
        )
        for item in profile.candidates
    )


def test_existing_id_keeps_priority_over_onclick():
    element = _button(
        onclick="irOpcion()",
        element_id="continueButton",
    )

    profile = (
        resolve_selector_profile(
            element,
            (element,),
        )
    )

    assert (
        profile.primary.strategy
        == SelectorStrategy.ID
    )

    assert (
        profile.primary.selector
        == "#continueButton"
    )


def test_existing_aria_keeps_priority_over_onclick():
    element = _button(
        onclick="irOpcion()",
        aria_label="Continuar",
    )

    profile = (
        resolve_selector_profile(
            element,
            (element,),
        )
    )

    assert (
        profile.primary.strategy
        == SelectorStrategy.ARIA_LABEL
    )
