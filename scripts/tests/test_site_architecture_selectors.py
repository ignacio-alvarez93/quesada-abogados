from backend.automation.site_architecture.selectors import (
    build_selector_candidates,
)


def test_id_is_first_selector_candidate():
    candidates = build_selector_candidates({
        "tag": "input",
        "id": "nie",
        "name": "nie",
        "type": "text",
        "attributes": {},
    })

    assert candidates[0].strategy.value == "ID"
    assert candidates[0].selector == "#nie"
    assert candidates[0].confidence.value == "HIGH"
    assert candidates[0].unique is None


def test_generates_stable_attribute_candidates():
    candidates = build_selector_candidates({
        "tag": "button",
        "id": "",
        "name": "",
        "type": "",
        "role": "button",
        "attributes": {
            "data-testid": "continue-button",
            "aria-label": "Continuar",
        },
    })

    selectors = tuple(
        candidate.selector
        for candidate in candidates
    )

    assert (
        '[data-testid="continue-button"]'
        in selectors
    )
    assert (
        '[aria-label="Continuar"]'
        in selectors
    )
    assert '[role="button"]' in selectors


def test_unsafe_id_uses_attribute_selector():
    candidates = build_selector_candidates({
        "tag": "div",
        "id": "field:1",
        "attributes": {},
    })

    assert (
        candidates[0].selector
        == '[id="field:1"]'
    )


def test_unknown_element_has_no_selector_candidate():
    assert (
        build_selector_candidates({
            "tag": "div",
            "attributes": {},
        })
        == ()
    )


def test_unique_id_becomes_primary_selector():
    from backend.automation.site_architecture.selectors import (
        resolve_selector_profile,
    )

    element = {
        "frame_path": "main",
        "tag": "input",
        "id": "nie",
        "name": "nie",
        "type": "text",
        "attributes": {},
    }

    profile = resolve_selector_profile(
        element,
        [element],
    )

    assert profile.frame_path == "main"
    assert profile.primary.selector == "#nie"
    assert profile.primary.unique is True
    assert profile.confidence.value == "HIGH"
    assert profile.fallbacks[0].selector == '[name="nie"]'


def test_non_unique_candidate_is_not_selected_as_primary():
    from backend.automation.site_architecture.selectors import (
        resolve_selector_profile,
    )

    target = {
        "frame_path": "main",
        "tag": "button",
        "name": "action",
        "attributes": {
            "data-testid": "continue",
        },
    }

    other = {
        "frame_path": "main",
        "tag": "button",
        "name": "action",
        "attributes": {},
    }

    profile = resolve_selector_profile(
        target,
        [target, other],
    )

    assert profile.candidates[0].unique is False
    assert (
        profile.primary.selector
        == '[data-testid="continue"]'
    )


def test_selector_uniqueness_is_scoped_to_frame():
    from backend.automation.site_architecture.selectors import (
        resolve_selector_profile,
    )

    main = {
        "frame_path": "main",
        "tag": "button",
        "id": "continuar",
        "attributes": {},
    }

    child = {
        "frame_path": "1",
        "tag": "button",
        "id": "continuar",
        "attributes": {},
    }

    profile = resolve_selector_profile(
        main,
        [main, child],
    )

    assert profile.primary.selector == "#continuar"
    assert profile.primary.unique is True


def test_ambiguous_selectors_do_not_create_primary():
    from backend.automation.site_architecture.selectors import (
        resolve_selector_profile,
    )

    first = {
        "frame_path": "main",
        "tag": "button",
        "role": "button",
        "attributes": {},
    }

    second = dict(first)

    profile = resolve_selector_profile(
        first,
        [first, second],
    )

    assert profile.primary is None
    assert profile.fallbacks == ()
    assert profile.confidence is None
    assert profile.candidates[0].unique is False
