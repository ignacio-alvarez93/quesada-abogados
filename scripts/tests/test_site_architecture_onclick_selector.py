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


def test_onclick_with_safe_literal_argument_is_structural_selector_candidate():
    element = _button(
        onclick="continuar('INI');"
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
        == 'button[onclick="continuar();"]'
    )

    assert "INI" not in onclick[0].selector


def test_onclick_literal_argument_never_exposes_pii_like_value():
    element = _button(
        onclick="verDetalle('NIE-X1234567');"
    )

    candidates = (
        build_selector_candidates(
            element
        )
    )

    serialized = repr(candidates)

    assert "X1234567" not in serialized

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
        == 'button[onclick="verDetalle();"]'
    )


def test_onclick_with_expression_argument_is_rejected():
    unsafe_values = (
        "continuar(window.tipo)",
        "continuar(getTipo())",
        "continuar('INI' + suffix)",
        "continuar(document.cookie)",
    )

    for value in unsafe_values:
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


def _anchor(
    *,
    onclick,
    index,
):
    return {
        "tag":
            "a",

        "id":
            "",

        "name":
            "",

        "type":
            "",

        "role":
            "",

        "frame_path":
            "main",

        "index":
            index,

        "attributes": {
            "onclick":
                onclick,
        },
    }


def test_colliding_onclick_literals_get_positional_disambiguation():
    """CONTINUAR ABOGACÍA and siblings collapse to one structural
    signature but must remain individually listener-addressable
    without ever persisting the literal branch code."""

    abogacia = _anchor(
        onclick="validarYEnviar('AB')",
        index=10,
    )

    interno = _anchor(
        onclick="validarYEnviar('IN')",
        index=11,
    )

    recurso = _anchor(
        onclick="validarYEnviar('RC')",
        index=12,
    )

    elements = (
        abogacia,
        interno,
        recurso,
    )

    profile_abogacia = (
        resolve_selector_profile(
            abogacia,
            elements,
        )
    )

    profile_interno = (
        resolve_selector_profile(
            interno,
            elements,
        )
    )

    profile_recurso = (
        resolve_selector_profile(
            recurso,
            elements,
        )
    )

    for profile in (
        profile_abogacia,
        profile_interno,
        profile_recurso,
    ):
        assert profile.primary is not None

        assert (
            profile.primary.strategy
            == (
                SelectorStrategy
                .ONCLICK_STRUCTURAL_POSITION
            )
        )

        assert (
            profile.primary.selector.startswith(
                'a[onclick="validarYEnviar()"]'
            )
        )

    selectors = {
        profile_abogacia.primary.selector,
        profile_interno.primary.selector,
        profile_recurso.primary.selector,
    }

    # Each physical control resolves to its own deterministic,
    # individually addressable selector.
    assert len(selectors) == 3

    assert (
        profile_abogacia.primary.selector
        == (
            'a[onclick="validarYEnviar()"]'
            ":qcc-nth-onclick(1)"
        )
    )

    assert (
        profile_interno.primary.selector
        == (
            'a[onclick="validarYEnviar()"]'
            ":qcc-nth-onclick(2)"
        )
    )

    assert (
        profile_recurso.primary.selector
        == (
            'a[onclick="validarYEnviar()"]'
            ":qcc-nth-onclick(3)"
        )
    )

    for value in ("AB", "IN", "RC"):
        assert all(
            value
            not in candidate.selector
            for profile in (
                profile_abogacia,
                profile_interno,
                profile_recurso,
            )
            for candidate in profile.candidates
        )


def test_positional_disambiguation_requires_stable_capture_index():
    """Without a stable capture-order index, ambiguity fails closed
    exactly as before -- no selector is invented."""

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

    assert profile.primary is None

    assert all(
        candidate.strategy
        != (
            SelectorStrategy
            .ONCLICK_STRUCTURAL_POSITION
        )
        for candidate in profile.candidates
    )


def test_positional_disambiguation_fails_closed_on_duplicate_index():
    """A malformed capture with duplicate stable indexes must never
    silently pick a colliding physical target."""

    first = _anchor(
        onclick="validarYEnviar('AB');",
        index=5,
    )

    second = _anchor(
        onclick="validarYEnviar('IN');",
        index=5,
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

    assert profile.primary is None

    assert all(
        candidate.strategy
        != (
            SelectorStrategy
            .ONCLICK_STRUCTURAL_POSITION
        )
        for candidate in profile.candidates
    )
