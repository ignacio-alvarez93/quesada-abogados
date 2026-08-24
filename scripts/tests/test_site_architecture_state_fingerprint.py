from copy import deepcopy

from backend.automation.site_architecture.state_fingerprint import (
    build_functional_state_fingerprint,
    build_functional_state_payload,
    canonicalize_functional_state,
)


def _snapshot():
    return {
        "schema_version": 1,

        "captured_at":
            "2026-08-24T10:00:00.000Z",

        "page": {
            "url":
                "https://example.test/form?session=123",

            "origin":
                "https://example.test",

            "pathname":
                "/form",

            "query":
                "session=123",

            "title":
                "Caso de Juan",

            "signature":
                None,
        },

        "actions": (
            {
                "frame_path": "main",
                "kind": "TAB",
                "policy":
                    "NAVIGATION_CANDIDATE",

                "selector":
                    "#tab-presenter",

                "semantics":
                    ("BUTTON",),

                "interaction": {
                    "state":
                        "INTERACTABLE",

                    "visible":
                        True,

                    "interactable":
                        True,

                    "disabled":
                        False,
                },

                "state_signals": {
                    "checked": False,
                    "selected": False,

                    "aria_selected":
                        False,

                    "aria_expanded":
                        None,

                    "aria_pressed":
                        None,

                    "aria_current":
                        None,
                },

                "element": {
                    "tag": "button",
                    "id": "tab-presenter",
                    "name": "",
                    "type": "button",
                    "role": "tab",
                },

                "value":
                    "PII-MUST-BE-IGNORED",

                "text":
                    "Juan Pérez",
            },
        ),

        "catalogs": (
            {
                "frame_path": "main",
                "catalog_type":
                    "native_select",
                "selector":
                    "#municipality",

                "options_count":
                    180,

                "state": {
                    "selected_value":
                        "079",

                    "selected_label":
                        "MADRID",
                },
            },
        ),

        "catalog_relations": (
            {
                "relation":
                    "DOM_REFERENCE",

                "source":
                    "main::#province",

                "target":
                    "main::#municipality",
            },
        ),
    }


def test_functional_state_is_deterministic():
    snapshot = _snapshot()

    assert (
        build_functional_state_fingerprint(
            snapshot
        )
        == build_functional_state_fingerprint(
            deepcopy(snapshot)
        )
    )


def test_functional_state_is_sha256():
    fingerprint = (
        build_functional_state_fingerprint(
            _snapshot()
        )
    )

    assert len(fingerprint) == 64

    int(
        fingerprint,
        16,
    )


def test_personal_or_session_data_do_not_change_state():
    before = _snapshot()
    after = deepcopy(before)

    after["captured_at"] = (
        "2026-08-24T11:00:00.000Z"
    )

    after["page"]["url"] = (
        "https://example.test/form?session=999"
    )

    after["page"]["query"] = (
        "session=999"
    )

    after["page"]["title"] = (
        "Caso de María"
    )

    after["actions"][0]["value"] = (
        "OTHER-CLIENT"
    )

    after["actions"][0]["text"] = (
        "María García"
    )

    assert (
        build_functional_state_fingerprint(
            before
        )
        == build_functional_state_fingerprint(
            after
        )
    )


def test_form_radio_value_does_not_define_screen_identity():
    before = _snapshot()
    after = deepcopy(before)

    after["actions"][0][
        "state_signals"
    ]["checked"] = True

    after["actions"][0][
        "state_signals"
    ]["selected"] = True

    assert (
        build_functional_state_fingerprint(
            before
        )
        == build_functional_state_fingerprint(
            after
        )
    )


def test_active_ui_state_changes_fingerprint():
    before = _snapshot()
    after = deepcopy(before)

    after["actions"][0][
        "state_signals"
    ]["aria_selected"] = True

    assert (
        build_functional_state_fingerprint(
            before
        )
        != build_functional_state_fingerprint(
            after
        )
    )


def test_visibility_change_changes_fingerprint():
    before = _snapshot()
    after = deepcopy(before)

    after["actions"][0][
        "interaction"
    ]["visible"] = False

    assert (
        build_functional_state_fingerprint(
            before
        )
        != build_functional_state_fingerprint(
            after
        )
    )


def test_viewport_interaction_change_does_not_change_fingerprint():
    before = _snapshot()
    after = deepcopy(before)

    after["actions"][0][
        "interaction"
    ]["state"] = "OFF_VIEWPORT"

    after["actions"][0][
        "interaction"
    ]["interactable"] = False

    assert (
        build_functional_state_fingerprint(
            before
        )
        == build_functional_state_fingerprint(
            after
        )
    )


def test_catalog_selected_value_does_not_change_fingerprint():
    before = _snapshot()
    after = deepcopy(before)

    after["catalogs"][0][
        "state"
    ]["selected_value"] = "001"

    after["catalogs"][0][
        "state"
    ]["selected_label"] = "OTHER"

    assert (
        build_functional_state_fingerprint(
            before
        )
        == build_functional_state_fingerprint(
            after
        )
    )


def test_pathname_change_changes_fingerprint():
    before = _snapshot()
    after = deepcopy(before)

    after["page"]["pathname"] = (
        "/next-step"
    )

    assert (
        build_functional_state_fingerprint(
            before
        )
        != build_functional_state_fingerprint(
            after
        )
    )


def test_action_order_does_not_change_fingerprint():
    before = _snapshot()

    second = deepcopy(
        before["actions"][0]
    )

    second["selector"] = "#other"
    second["element"]["id"] = "other"

    before["actions"] = (
        before["actions"][0],
        second,
    )

    after = deepcopy(before)

    after["actions"] = tuple(
        reversed(
            after["actions"]
        )
    )

    assert (
        build_functional_state_fingerprint(
            before
        )
        == build_functional_state_fingerprint(
            after
        )
    )


def test_payload_contains_no_form_values():
    payload = (
        build_functional_state_payload(
            _snapshot()
        )
    )

    canonical = (
        canonicalize_functional_state(
            _snapshot()
        )
    )

    assert "Juan Pérez" not in canonical
    assert "PII-MUST-BE-IGNORED" not in canonical
    assert "MADRID" not in canonical
    assert "079" not in canonical

    assert (
        payload["state_type"]
        == "QCC_FUNCTIONAL_STATE"
    )
