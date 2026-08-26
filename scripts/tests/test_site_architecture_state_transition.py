from copy import deepcopy

import pytest

from backend.automation.site_architecture.state_transition import (
    STATE_TRANSITION_CHANGED,
    STATE_TRANSITION_CONFIDENCE_HIGH,
    STATE_TRANSITION_UNCHANGED,
    detect_state_transition,
)


def _snapshot():
    return {
        "schema_version": 1,

        "page": {
            "url":
                "https://example.test/form",

            "origin":
                "https://example.test",

            "pathname":
                "/form",

            "query":
                "",

            "title":
                "Formulario",

            "signature":
                None,
        },

        "elements": (),

        "actions": (
            {
                "frame_path":
                    "main",

                "kind":
                    "TAB",

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
            },
        ),

        "catalogs": (),
        "catalog_relations": (),
    }


def test_same_functional_state_is_not_transition():
    before = _snapshot()
    after = deepcopy(before)

    result = detect_state_transition(
        before,
        after,
    )

    assert result["changed"] is False

    assert (
        result["status"]
        == STATE_TRANSITION_UNCHANGED
    )

    assert (
        result["before_fingerprint"]
        == result["after_fingerprint"]
    )

    assert (
        result["confidence"]
        == STATE_TRANSITION_CONFIDENCE_HIGH
    )


def test_active_tab_change_is_transition():
    before = _snapshot()
    after = deepcopy(before)

    after["actions"][0][
        "state_signals"
    ]["aria_selected"] = True

    result = detect_state_transition(
        before,
        after,
    )

    assert result["changed"] is True

    assert (
        result["status"]
        == STATE_TRANSITION_CHANGED
    )

    assert (
        result["before_fingerprint"]
        != result["after_fingerprint"]
    )


def test_path_change_is_transition():
    before = _snapshot()
    after = deepcopy(before)

    after["page"]["pathname"] = (
        "/next"
    )

    after["page"]["url"] = (
        "https://example.test/next"
    )

    result = detect_state_transition(
        before,
        after,
    )

    assert result["changed"] is True
    assert result["contract_changed"] is True


def test_query_only_change_is_not_functional_transition():
    before = _snapshot()
    after = deepcopy(before)

    after["page"]["query"] = (
        "session=999"
    )

    after["page"]["url"] = (
        "https://example.test/form?session=999"
    )

    result = detect_state_transition(
        before,
        after,
    )

    # Contract diff ve cambio de página,
    # pero la identidad funcional permanece.
    assert result["contract_changed"] is True
    assert result["changed"] is False


def test_transition_records_safe_action_identity():
    before = _snapshot()
    after = deepcopy(before)

    after["actions"][0][
        "state_signals"
    ]["aria_selected"] = True

    action = {
        "kind": "TAB",
        "policy":
            "NAVIGATION_CANDIDATE",

        "selector":
            "#tab-presenter",

        "frame_path":
            "main",

        "text":
            "Juan Pérez",

        "value":
            "X1234567A",

        "payload": {
            "secret":
                "MUST-NOT-LEAK"
        },
    }

    result = detect_state_transition(
        before,
        after,
        action=action,
    )

    assert result["action"] == {
        "kind":
            "TAB",

        "policy":
            "NAVIGATION_CANDIDATE",

        "selector":
            "#tab-presenter",

        "frame_path":
            "main",
    }

    assert "text" not in result["action"]
    assert "value" not in result["action"]
    assert "payload" not in result["action"]


def test_transition_allows_no_action_context():
    result = detect_state_transition(
        _snapshot(),
        _snapshot(),
    )

    assert result["action"] is None


def test_transition_rejects_invalid_action():
    with pytest.raises(
        ValueError,
        match=(
            "SITE_ARCHITECTURE_TRANSITION_ACTION_INVALID"
        ),
    ):
        detect_state_transition(
            _snapshot(),
            _snapshot(),
            action="click",
        )
