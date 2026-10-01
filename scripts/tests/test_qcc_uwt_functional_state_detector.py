"""UWT-2 Functional State Detector — provider-neutral regression suite.

Covers QCC_UWT_2_FUNCTIONAL_STATE_DETECTOR_V1 acceptance scenarios.

Two structurally unrelated site-neutral fixtures are used on purpose
(``_checkout_snapshot`` / ``_support_dashboard_snapshot``): genericity
must not be proven using a single Mercurio-shaped fixture.
"""

from copy import deepcopy

import pytest

from backend.qcc.universal_web import (
    FUNCTIONAL_STATE_CHANGED,
    SAME_FUNCTIONAL_STATE,
    UNKNOWN,
    UNKNOWN_REASON_EVIDENCE_UNAVAILABLE,
    UNKNOWN_REASON_EXTERNAL_UI_BOUNDARY,
    UNKNOWN_REASON_MISSING_OBSERVATION,
    build_external_ui_boundary,
    build_functional_state,
    build_stable_state_fingerprint,
    compare_functional_state,
)
from backend.qcc.universal_web.functional_state import FunctionalState


# ---------------------------------------------------------------------------
# Fixture A: generic e-commerce checkout. Deliberately unrelated to Mercurio.
# ---------------------------------------------------------------------------

def _checkout_snapshot():
    return {
        "schema_version": 1,

        "captured_at":
            "2026-09-01T10:00:00.000Z",

        "page": {
            "url":
                "https://shop.example/checkout?session=abc123",
            "origin":
                "https://shop.example",
            "pathname":
                "/checkout",
            "query":
                "session=abc123",
            "title":
                "Checkout",
            "signature":
                None,
        },

        "elements": (
            {
                "id": None,
                "tag": "div",
                "class": "card",
            },
            {
                "id": "tab-shipping",
                "selector": "#tab-shipping",
                "tag": "button",
                "class": "active",
            },
            {
                "id": "tab-billing",
                "selector": "#tab-billing",
                "tag": "button",
                "class": "",
            },
        ),

        "actions": (
            {
                "frame_path": "main",
                "kind": "BUTTON",
                "policy": "STATE_CHANGE",
                "selector": "#submit",
                "semantics": ("BUTTON",),
                "interaction": {
                    "state": "INTERACTABLE",
                    "visible": True,
                    "interactable": True,
                    "disabled": False,
                },
                "state_signals": {
                    "checked": None,
                    "selected": None,
                    "aria_selected": None,
                    "aria_expanded": None,
                    "aria_pressed": None,
                    "aria_current": None,
                },
                "element": {
                    "tag": "button",
                    "id": "submit",
                    "name": "",
                    "type": "submit",
                    "role": "button",
                },
            },
            {
                "frame_path": "main",
                "kind": "OPTION",
                "policy": "STATE_CHANGE",
                "selector": "#shipping-standard",
                "semantics": ("OPTION",),
                "interaction": {
                    "state": "INTERACTABLE",
                    "visible": True,
                    "interactable": True,
                    "disabled": False,
                },
                "state_signals": {
                    "checked": None,
                    "selected": None,
                    "aria_selected": False,
                    "aria_expanded": None,
                    "aria_pressed": None,
                    "aria_current": None,
                },
                "element": {
                    "tag": "li",
                    "id": "shipping-standard",
                    "name": "",
                    "type": "",
                    "role": "option",
                },
            },
        ),

        "catalogs": (
            {
                "frame_path": "main",
                "catalog_type": "native_select",
                "selector": "#country",
            },
        ),

        "catalog_relations": (
            {
                "relation": "DOM_REFERENCE",
                "source": "main::#country",
                "target": "main::#state",
            },
        ),
    }


# ---------------------------------------------------------------------------
# Fixture B: structurally different pattern (sidebar/dashboard, no catalogs).
# ---------------------------------------------------------------------------

def _support_dashboard_snapshot():
    return {
        "schema_version": 1,

        "captured_at":
            "2026-09-01T12:00:00.000Z",

        "page": {
            "url":
                "https://support.example/tickets?trace=xyz789",
            "origin":
                "https://support.example",
            "pathname":
                "/tickets",
            "query":
                "trace=xyz789",
            "title":
                "Tickets",
            "signature":
                None,
        },

        "elements": (
            {
                "id": "nav-open",
                "selector": "#nav-open",
                "tag": "li",
                "class": "active",
            },
            {
                "id": "nav-closed",
                "selector": "#nav-closed",
                "tag": "li",
                "class": "",
            },
            {
                "id": None,
                "tag": "div",
                "class": "surface",
            },
        ),

        "actions": (
            {
                "frame_path": "main",
                "kind": "DIALOG_TOGGLE",
                "policy": "STATE_CHANGE",
                "selector": "#open-ticket-modal",
                "semantics": ("BUTTON",),
                "interaction": {
                    "state": "INTERACTABLE",
                    "visible": True,
                    "interactable": True,
                    "disabled": False,
                },
                "state_signals": {
                    "checked": None,
                    "selected": None,
                    "aria_selected": None,
                    "aria_expanded": False,
                    "aria_pressed": None,
                    "aria_current": None,
                },
                "element": {
                    "tag": "button",
                    "id": "open-ticket-modal",
                    "name": "",
                    "type": "button",
                    "role": "button",
                },
            },
        ),

        "catalogs": (),
        "catalog_relations": (),
    }


def _snapshot(fixture):
    return deepcopy(fixture())


def _state(snapshot, *, site_identity="SITE_A"):
    return build_functional_state(
        snapshot=snapshot,
        site_identity=site_identity,
    )


# 1. identical observations -> SAME_FUNCTIONAL_STATE
def test_identical_observations_are_same_state():
    snapshot = _snapshot(_checkout_snapshot)

    delta = compare_functional_state(
        _state(snapshot),
        _state(deepcopy(snapshot)),
    )

    assert delta.classification == SAME_FUNCTIONAL_STATE


# 2. dictionary ordering changed -> SAME_FUNCTIONAL_STATE
def test_dictionary_key_ordering_does_not_change_classification():
    before = _snapshot(_checkout_snapshot)

    reordered_page = {
        "signature": before["page"]["signature"],
        "title": before["page"]["title"],
        "query": before["page"]["query"],
        "pathname": before["page"]["pathname"],
        "origin": before["page"]["origin"],
        "url": before["page"]["url"],
    }

    after = deepcopy(before)
    after["page"] = reordered_page

    delta = compare_functional_state(
        _state(before),
        _state(after),
    )

    assert delta.classification == SAME_FUNCTIONAL_STATE


# 3. timestamp changed -> SAME_FUNCTIONAL_STATE
def test_timestamp_change_does_not_change_classification():
    before = _snapshot(_checkout_snapshot)
    after = deepcopy(before)

    after["captured_at"] = "2026-09-02T09:30:00.000Z"

    delta = compare_functional_state(
        _state(before),
        _state(after),
    )

    assert delta.classification == SAME_FUNCTIONAL_STATE


# 4. session-like volatile value changed -> SAME_FUNCTIONAL_STATE
def test_session_like_pathname_parameter_does_not_change_classification():
    before = _snapshot(_checkout_snapshot)
    after = deepcopy(before)

    after["page"]["pathname"] = (
        "/checkout;jsessionid=AC3089C7FAFC69459B370BFB2AC5277D.node01"
    )

    delta = compare_functional_state(
        _state(before),
        _state(after),
    )

    assert delta.classification == SAME_FUNCTIONAL_STATE


# 5. cosmetic-only class/style change -> SAME_FUNCTIONAL_STATE
def test_cosmetic_only_class_change_does_not_change_classification():
    before = _snapshot(_checkout_snapshot)
    after = deepcopy(before)

    decorative = list(after["elements"])
    decorative[0] = dict(decorative[0])
    decorative[0]["class"] = "card shadow-sm"
    after["elements"] = tuple(decorative)

    delta = compare_functional_state(
        _state(before),
        _state(after),
    )

    assert delta.classification == SAME_FUNCTIONAL_STATE


# 6. same URL + relevant field appeared -> FUNCTIONAL_STATE_CHANGED
def test_relevant_control_appearing_changes_classification():
    before = _snapshot(_checkout_snapshot)
    after = deepcopy(before)

    new_action = deepcopy(after["actions"][0])
    new_action["selector"] = "#promo-code-input"
    new_action["element"]["id"] = "promo-code-input"

    after["actions"] = after["actions"] + (new_action,)

    delta = compare_functional_state(
        _state(before),
        _state(after),
    )

    assert delta.classification == FUNCTIONAL_STATE_CHANGED

    decisive_names = {
        signal.name
        for signal in delta.signals
        if signal.decisive and signal.changed
    }

    assert "actions" in decisive_names


# 7. same URL + relevant field disappeared -> FUNCTIONAL_STATE_CHANGED
def test_relevant_control_disappearing_changes_classification():
    before = _snapshot(_checkout_snapshot)
    after = deepcopy(before)

    after["actions"] = (after["actions"][0],)

    delta = compare_functional_state(
        _state(before),
        _state(after),
    )

    assert delta.classification == FUNCTIONAL_STATE_CHANGED


# 8. same URL + button enabled state changed -> FUNCTIONAL_STATE_CHANGED
def test_button_enabled_state_change_changes_classification():
    before = _snapshot(_checkout_snapshot)
    after = deepcopy(before)

    actions = list(after["actions"])
    actions[0] = deepcopy(actions[0])
    actions[0]["interaction"]["disabled"] = True
    after["actions"] = tuple(actions)

    delta = compare_functional_state(
        _state(before),
        _state(after),
    )

    assert delta.classification == FUNCTIONAL_STATE_CHANGED


# 9. same URL + required state changed -> FUNCTIONAL_STATE_CHANGED
def test_required_semantics_change_changes_classification():
    before = _snapshot(_checkout_snapshot)
    after = deepcopy(before)

    actions = list(after["actions"])
    actions[0] = deepcopy(actions[0])
    actions[0]["semantics"] = ("BUTTON", "REQUIRED_FIELD")
    after["actions"] = tuple(actions)

    delta = compare_functional_state(
        _state(before),
        _state(after),
    )

    assert delta.classification == FUNCTIONAL_STATE_CHANGED


# 10. same URL + operative selected option changed -> FUNCTIONAL_STATE_CHANGED
def test_aria_selected_option_change_changes_classification():
    before = _snapshot(_checkout_snapshot)
    after = deepcopy(before)

    actions = list(after["actions"])
    actions[1] = deepcopy(actions[1])
    actions[1]["state_signals"]["aria_selected"] = True
    after["actions"] = tuple(actions)

    delta = compare_functional_state(
        _state(before),
        _state(after),
    )

    assert delta.classification == FUNCTIONAL_STATE_CHANGED


# 11. same URL + visible functional section appeared -> FUNCTIONAL_STATE_CHANGED
def test_new_active_ui_region_appearing_changes_classification():
    before = _snapshot(_checkout_snapshot)
    after = deepcopy(before)

    after["elements"] = after["elements"] + (
        {
            "id": "promo-panel",
            "selector": "#promo-panel",
            "tag": "section",
            "class": "active",
        },
    )

    delta = compare_functional_state(
        _state(before),
        _state(after),
    )

    assert delta.classification == FUNCTIONAL_STATE_CHANGED

    decisive_names = {
        signal.name
        for signal in delta.signals
        if signal.decisive and signal.changed
    }

    assert "active_ui_regions" in decisive_names


# 12. same URL + active operative tab changed -> FUNCTIONAL_STATE_CHANGED
def test_active_tab_swap_changes_classification():
    before = _snapshot(_checkout_snapshot)
    after = deepcopy(before)

    elements = list(after["elements"])

    for index, element in enumerate(elements):
        if element.get("id") == "tab-shipping":
            elements[index] = dict(element)
            elements[index]["class"] = ""
        elif element.get("id") == "tab-billing":
            elements[index] = dict(element)
            elements[index]["class"] = "active"

    after["elements"] = tuple(elements)

    delta = compare_functional_state(
        _state(before),
        _state(after),
    )

    assert delta.classification == FUNCTIONAL_STATE_CHANGED


# 13. different URL + equivalent functional evidence.
#
# Explicit policy (work order section 9): URL is a signal, not state
# authority. Operative evidence is unchanged, so this is
# SAME_FUNCTIONAL_STATE even though pathname differs.
def test_different_url_with_equivalent_operative_evidence_is_same_state():
    before = _snapshot(_checkout_snapshot)
    after = deepcopy(before)

    after["page"]["pathname"] = "/checkout/step-2"
    after["page"]["url"] = "https://shop.example/checkout/step-2"

    delta = compare_functional_state(
        _state(before),
        _state(after),
    )

    assert delta.classification == SAME_FUNCTIONAL_STATE

    page_signal = next(
        signal
        for signal in delta.signals
        if signal.name == "page_identity"
    )

    assert page_signal.changed is True
    assert page_signal.decisive is False


# 14. insufficient/contradictory evidence -> UNKNOWN
def test_missing_observation_is_unknown():
    state = _state(_snapshot(_checkout_snapshot))

    delta = compare_functional_state(None, state)

    assert delta.classification == UNKNOWN
    assert delta.reason == UNKNOWN_REASON_MISSING_OBSERVATION


def test_malformed_snapshot_fails_closed_to_unknown():
    valid_state = _state(_snapshot(_checkout_snapshot))

    malformed_state = build_functional_state(
        snapshot={"schema_version": 999},
        site_identity="SITE_A",
    )

    assert malformed_state.evidence_available is False

    delta = compare_functional_state(
        valid_state,
        malformed_state,
    )

    assert delta.classification == UNKNOWN
    assert delta.reason == UNKNOWN_REASON_EVIDENCE_UNAVAILABLE


def test_external_ui_boundary_is_unknown_even_when_both_sides_match():
    boundary = build_external_ui_boundary(
        kind="FILE_DIALOG",
        detail="os_open_file_picker",
    )

    boundary_state_1 = build_functional_state(
        external_ui_boundary=boundary,
    )
    boundary_state_2 = build_functional_state(
        external_ui_boundary=boundary,
    )

    delta = compare_functional_state(
        boundary_state_1,
        boundary_state_2,
    )

    assert delta.classification == UNKNOWN
    assert delta.reason == UNKNOWN_REASON_EXTERNAL_UI_BOUNDARY


# 15. stable fingerprint deterministic across key ordering
def test_stable_fingerprint_is_deterministic_across_key_ordering():
    before = _snapshot(_checkout_snapshot)

    reordered = {
        "catalog_relations": before["catalog_relations"],
        "catalogs": before["catalogs"],
        "actions": tuple(reversed(before["actions"])),
        "elements": before["elements"],
        "page": before["page"],
        "captured_at": before["captured_at"],
        "schema_version": before["schema_version"],
    }

    fingerprint_a = build_stable_state_fingerprint(before)
    fingerprint_b = build_stable_state_fingerprint(reordered)

    assert fingerprint_a.value == fingerprint_b.value
    assert fingerprint_a.operative_value == fingerprint_b.operative_value


# 16. stable fingerprint changes for functional difference
def test_stable_fingerprint_changes_for_functional_difference():
    before = _snapshot(_checkout_snapshot)
    after = deepcopy(before)

    actions = list(after["actions"])
    actions[0] = deepcopy(actions[0])
    actions[0]["interaction"]["disabled"] = True
    after["actions"] = tuple(actions)

    fingerprint_before = build_stable_state_fingerprint(before)
    fingerprint_after = build_stable_state_fingerprint(after)

    assert (
        fingerprint_before.operative_value
        != fingerprint_after.operative_value
    )
    assert fingerprint_before.value != fingerprint_after.value


# 17. site-neutral fixture A (checkout form)
def test_fixture_a_same_state_roundtrip():
    snapshot = _snapshot(_checkout_snapshot)

    delta = compare_functional_state(
        _state(snapshot),
        _state(deepcopy(snapshot)),
    )

    assert delta.classification == SAME_FUNCTIONAL_STATE


# 18. site-neutral fixture B, structurally different web pattern
def test_fixture_b_dialog_toggle_changes_classification():
    before = _snapshot(_support_dashboard_snapshot)
    after = deepcopy(before)

    actions = list(after["actions"])
    actions[0] = deepcopy(actions[0])
    actions[0]["state_signals"]["aria_expanded"] = True
    after["actions"] = tuple(actions)

    delta = compare_functional_state(
        _state(before, site_identity="SITE_B"),
        _state(after, site_identity="SITE_B"),
    )

    assert delta.classification == FUNCTIONAL_STATE_CHANGED


def test_fixture_b_identical_observations_are_same_state():
    snapshot = _snapshot(_support_dashboard_snapshot)

    delta = compare_functional_state(
        _state(snapshot, site_identity="SITE_B"),
        _state(deepcopy(snapshot), site_identity="SITE_B"),
    )

    assert delta.classification == SAME_FUNCTIONAL_STATE


# ---------------------------------------------------------------------------
# Property / invariant tests (work order section 13).
# ---------------------------------------------------------------------------

def test_equal_snapshots_imply_equal_fingerprints():
    snapshot = _snapshot(_checkout_snapshot)

    assert (
        build_stable_state_fingerprint(snapshot).value
        == build_stable_state_fingerprint(deepcopy(snapshot)).value
    )


def test_fingerprint_equality_does_not_override_external_ui_boundary():
    snapshot = _snapshot(_checkout_snapshot)

    plain_state = _state(snapshot)

    boundary_state = FunctionalState(
        schema_version=plain_state.schema_version,
        state_type=plain_state.state_type,
        site_identity=plain_state.site_identity,
        page_identity=plain_state.page_identity,
        operative_payload=plain_state.operative_payload,
        fingerprint=plain_state.fingerprint,
        external_ui_boundary=build_external_ui_boundary(
            kind="NATIVE_DIALOG",
        ),
        evidence_available=True,
    )

    assert (
        plain_state.fingerprint.value
        == boundary_state.fingerprint.value
    )

    delta = compare_functional_state(
        plain_state,
        boundary_state,
    )

    assert delta.classification == UNKNOWN


def test_comparison_of_identical_state_with_itself_is_same():
    state = _state(_snapshot(_checkout_snapshot))

    delta = compare_functional_state(state, state)

    assert delta.classification == SAME_FUNCTIONAL_STATE


@pytest.mark.parametrize(
    "mutate",
    [
        False,
        True,
    ],
)
def test_classification_is_symmetric(mutate):
    before = _snapshot(_checkout_snapshot)
    after = deepcopy(before)

    if mutate:
        actions = list(after["actions"])
        actions[0] = deepcopy(actions[0])
        actions[0]["interaction"]["disabled"] = True
        after["actions"] = tuple(actions)

    state_before = _state(before)
    state_after = _state(after)

    forward = compare_functional_state(
        state_before,
        state_after,
    )

    backward = compare_functional_state(
        state_after,
        state_before,
    )

    assert forward.classification == backward.classification
