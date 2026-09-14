from copy import deepcopy
from pathlib import Path

from backend.automation.site_architecture.action_inventory import (
    build_action_inventory,
)
from backend.automation.site_architecture.selectors import (
    SelectorStrategy,
    build_selector_candidates,
    resolve_selector_profile,
)
from backend.automation.site_architecture.state_fingerprint import (
    build_functional_state_fingerprint,
)


def _host(idoption):
    return {
        "tag":
            "dnt-horizontal-menu-item",

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

        "attributes": {
            "active":
                "false",

            "class":
                "hydrated",

            "idoption":
                str(idoption),

            "tabindex":
                "0",
        },

        "semantics":
            (),

        "interaction": {
            "visible":
                True,

            "disabled":
                False,

            "interactable":
                False,
        },

        "state_signals":
            {},

        "composed_action_surface": {
            "locator_basis":
                "COMPOSED_PATH_HOST",

            "kind":
                "LINK",

            "leaf_tag":
                "a",

            "leaf_role":
                "menuitem",

            "shadow_depth":
                1,
        },
    }


def test_composed_host_gets_generic_structural_attribute_candidate():
    element = _host(2)

    candidates = (
        build_selector_candidates(
            element
        )
    )

    structural = [
        candidate
        for candidate in candidates
        if candidate.strategy
        == SelectorStrategy.STRUCTURAL_ATTRIBUTE
    ]

    assert any(
        candidate.selector
        == (
            'dnt-horizontal-menu-item'
            '[idoption="2"]'
        )
        for candidate in structural
    )


def test_composed_host_selector_is_unique_within_frame():
    elements = [
        _host(1),
        _host(2),
        _host(3),
    ]

    profile = (
        resolve_selector_profile(
            elements[1],
            elements,
        )
    )

    assert profile.primary is not None

    assert (
        profile.primary.selector
        == (
            'dnt-horizontal-menu-item'
            '[idoption="2"]'
        )
    )


def test_composed_surface_becomes_navigation_action():
    element = _host(2)

    profile = (
        resolve_selector_profile(
            element,
            [element],
        )
    )

    element["selectors"] = (
        profile.to_dict()
    )

    actions = (
        build_action_inventory(
            [element]
        )
    )

    assert len(actions) == 1

    action = actions[0]

    assert action["kind"] == "LINK"

    assert (
        action["policy"]
        == "NAVIGATION_CANDIDATE"
    )

    assert (
        action["selector"]
        == (
            'dnt-horizontal-menu-item'
            '[idoption="2"]'
        )
    )

    assert (
        action["locator_basis"]
        == "COMPOSED_PATH_HOST"
    )


def test_composed_addressability_does_not_change_v1_fingerprint():
    base = {
        "schema_version":
            1,

        "page": {
            "origin":
                "https://example.test",

            "pathname":
                "/",
        },

        "actions":
            [],

        "catalogs":
            [],

        "catalog_relations":
            [],
    }

    enriched = deepcopy(
        base
    )

    enriched["actions"] = [{
        "kind":
            "LINK",

        "policy":
            "NAVIGATION_CANDIDATE",

        "selector":
            (
                'x-menu-item'
                '[option="2"]'
            ),

        "frame_path":
            "main",

        "locator_basis":
            "COMPOSED_PATH_HOST",

        "semantics":
            (),

        "interaction": {
            "visible":
                True,

            "disabled":
                False,
        },

        "state_signals":
            {},

        "element": {
            "tag":
                "x-menu-item",
        },
    }]

    assert (
        build_functional_state_fingerprint(
            base
        )
        ==
        build_functional_state_fingerprint(
            enriched
        )
    )


def test_service_worker_captures_composed_surface_and_listener_uses_composed_path():
    text = Path(
        "chrome_extension/qcc/background/"
        "service_worker.js"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        "function composedActionSurfaceOf("
        in text
    )

    assert (
        '"COMPOSED_PATH_HOST"'
        in text
    )

    assert (
        "event.composedPath()"
        in text
    )
