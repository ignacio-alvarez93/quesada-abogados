from copy import deepcopy

from backend.automation.site_architecture.state_fingerprint import (
    FUNCTIONAL_STATE_SCHEMA_VERSION,
    build_functional_state_fingerprint,
    build_functional_state_payload,
)


def _snapshot():
    return {
        "schema_version": 1,

        "page": {
            "origin":
                "https://example.test",

            "pathname":
                "/form",
        },

        "actions": (
            {
                "frame_path":
                    "main",

                "kind":
                    "BUTTON",

                "policy":
                    "NAVIGATION_CANDIDATE",

                "selector":
                    "#continue",

                "semantics":
                    ("BUTTON",),

                "interaction": {
                    "disabled":
                        False,

                    "visible":
                        True,

                    "interactable":
                        True,
                },

                "state_signals": {
                    "checked":
                        False,

                    "selected":
                        False,

                    "aria_selected":
                        None,

                    "aria_expanded":
                        None,

                    "aria_pressed":
                        None,

                    "aria_current":
                        None,
                },

                "element": {
                    "tag":
                        "button",

                    "id":
                        "continue",

                    "name":
                        "",

                    "type":
                        "button",

                    "role":
                        None,
                },
            },
        ),

        "elements": (
            {
                "tag":
                    "div",

                "id":
                    "panel-a",

                "class":
                    (
                        "tabs-panel "
                        "r-tabs-state-active"
                    ),

                "visible":
                    True,

                "attributes": {
                    "id":
                        "panel-a",

                    "class":
                        (
                            "tabs-panel "
                            "r-tabs-state-active"
                        ),
                },
            },

            {
                "tag":
                    "div",

                "id":
                    "panel-b",

                "class":
                    (
                        "tabs-panel "
                        "r-tabs-state-default"
                    ),

                "visible":
                    False,

                "attributes": {
                    "id":
                        "panel-b",

                    "class":
                        (
                            "tabs-panel "
                            "r-tabs-state-default"
                        ),
                },
            },

            {
                "tag":
                    "input",

                "id":
                    "branch-130",

                "name":
                    "datosForAut",

                "type":
                    "radio",

                "class":
                    "form-radio",

                "value":
                    "130",

                "checked":
                    False,

                "state_signals": {
                    "checked":
                        False,
                },

                "attributes": {
                    "id":
                        "branch-130",

                    "name":
                        "datosForAut",

                    "type":
                        "radio",

                    "class":
                        "form-radio",

                    "value":
                        "130",
                },
            },
        ),

        "catalogs": (),

        "catalog_relations": (),
    }


def test_functional_state_contract_is_v3():
    assert (
        FUNCTIONAL_STATE_SCHEMA_VERSION
        == 3
    )


def test_active_panel_changes_functional_fingerprint():
    before = _snapshot()
    after = deepcopy(
        before
    )

    after[
        "elements"
    ][0][
        "class"
    ] = (
        "tabs-panel "
        "r-tabs-state-default"
    )

    after[
        "elements"
    ][0][
        "attributes"
    ][
        "class"
    ] = (
        "tabs-panel "
        "r-tabs-state-default"
    )

    after[
        "elements"
    ][1][
        "class"
    ] = (
        "tabs-panel "
        "r-tabs-state-active"
    )

    after[
        "elements"
    ][1][
        "attributes"
    ][
        "class"
    ] = (
        "tabs-panel "
        "r-tabs-state-active"
    )

    assert (
        build_functional_state_fingerprint(
            before
        )
        !=
        build_functional_state_fingerprint(
            after
        )
    )


def test_visibility_alone_still_does_not_define_state():
    before = _snapshot()
    after = deepcopy(
        before
    )

    after[
        "elements"
    ][0][
        "visible"
    ] = False

    after[
        "elements"
    ][1][
        "visible"
    ] = True

    assert (
        build_functional_state_fingerprint(
            before
        )
        ==
        build_functional_state_fingerprint(
            after
        )
    )


def test_radio_selection_stays_out_of_fingerprint():
    before = _snapshot()
    after = deepcopy(
        before
    )

    after[
        "elements"
    ][2][
        "checked"
    ] = True

    after[
        "elements"
    ][2][
        "state_signals"
    ][
        "checked"
    ] = True

    after[
        "elements"
    ][2][
        "value"
    ] = "131"

    after[
        "elements"
    ][2][
        "attributes"
    ][
        "value"
    ] = "131"

    assert (
        build_functional_state_fingerprint(
            before
        )
        ==
        build_functional_state_fingerprint(
            after
        )
    )


def test_non_state_css_class_change_is_ignored():
    before = _snapshot()
    after = deepcopy(
        before
    )

    after[
        "elements"
    ][2][
        "class"
    ] = (
        "form-radio cosmetic-large"
    )

    after[
        "elements"
    ][2][
        "attributes"
    ][
        "class"
    ] = (
        "form-radio cosmetic-large"
    )

    assert (
        build_functional_state_fingerprint(
            before
        )
        ==
        build_functional_state_fingerprint(
            after
        )
    )


def test_payload_contains_only_active_structural_region():
    payload = (
        build_functional_state_payload(
            _snapshot()
        )
    )

    regions = payload[
        "active_ui_regions"
    ]

    assert len(
        regions
    ) == 1

    assert (
        regions[0][
            "element"
        ][
            "id"
        ]
        == "panel-a"
    )

    assert (
        regions[0][
            "active_class_tokens"
        ]
        == (
            "r-tabs-state-active",
        )
    )
