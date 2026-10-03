from __future__ import annotations

import json

import pytest

from backend.automation.site_architecture.dynamic_form_effects import (
    EFFECT_CHECKED_CHANGED,
    EFFECT_CONTROL_APPEARED,
    EFFECT_CONTROL_DISAPPEARED,
    EFFECT_DISABLED_CHANGED,
    EFFECT_HAS_VALUE_CHANGED,
    EFFECT_INTERACTABLE_CHANGED,
    EFFECT_READONLY_CHANGED,
    EFFECT_REQUIRED_CHANGED,
    EFFECT_SELECTION_CHANGED,
    EFFECT_VISIBILITY_CHANGED,
)
from backend.qcc.auto_twin.form_effect_runtime import (
    AUTO_TWIN_FORM_EFFECT_RUNTIME_ADAPTER_FILENAME,
    AUTO_TWIN_FORM_EFFECT_RUNTIME_ADAPTER_VERSION,
    AUTO_TWIN_FORM_EFFECT_RUNTIME_FILENAME,
    AUTO_TWIN_FORM_EFFECT_RUNTIME_PAYLOAD_ELEMENT_ID,
    AUTO_TWIN_FORM_EFFECT_RUNTIME_SCRIPT_MARKER,
    BLOCKED_EFFECT_KINDS,
    DELEGATED_EFFECT_KINDS,
    EXECUTABLE_EFFECT_KINDS,
    FormEffectRuntimeError,
    ROUTE_STATUS_BLOCKED,
    ROUTE_STATUS_EXECUTABLE,
    SELECTION_CHANGED_OWNER,
    build_form_effect_runtime_payload,
    form_effect_runtime_adapter_source,
    inject_form_effect_runtime_adapter,
)


def _target(
    *,
    control_key="main::INPUT::#alpha",
    frame_path="main",
    selector="#alpha",
    semantic_kind="TEXT_INPUT",
):
    return {
        "control_key": control_key,
        "frame_path": frame_path,
        "selector": selector,
        "semantic_kind": semantic_kind,
    }


def _bool_effect(kind, *, after, before=None, target=None):
    return {
        "kind": kind,
        "target": target or _target(),
        "before": before,
        "after": after,
    }


def _select_entry(
    *,
    state_id="STATE_1",
    selector="#plan",
    selected_index=1,
    effects=None,
):
    return {
        "state_id": state_id,
        "action": {
            "kind": "SELECT",
            "selector": selector,
            "frame_path": "main",
        },
        "mutation_identity": {
            "kind": "SELECT",
            "selected_index": selected_index,
        },
        "effects": effects or (),
    }


def _checkbox_entry(
    *,
    state_id="STATE_1",
    selector="#terms",
    checked=True,
    effects=None,
):
    return {
        "state_id": state_id,
        "action": {
            "kind": "CHECKBOX",
            "selector": selector,
            "frame_path": "main",
        },
        "mutation_identity": {
            "kind": "CHECKBOX",
            "checked": checked,
        },
        "effects": effects or (),
    }


def _radio_entry(
    *,
    state_id="STATE_1",
    selector="#yes",
    checked=True,
    effects=None,
):
    return {
        "state_id": state_id,
        "action": {
            "kind": "RADIO",
            "selector": selector,
            "frame_path": "main",
        },
        "mutation_identity": {
            "kind": "RADIO",
            "checked": checked,
        },
        "effects": effects or (),
    }


# 1. SELECT selected_index trigger.
def test_select_trigger_uses_selected_index():
    payload = build_form_effect_runtime_payload([
        _select_entry(selected_index=2),
    ])

    route = payload["routes"][0]

    assert route["trigger"]["mutation_identity"] == {
        "kind": "SELECT",
        "selected_index": 2,
    }


# 2. selected_value absent.
def test_select_selected_value_absent_from_trigger_and_rejected_as_input():
    payload = build_form_effect_runtime_payload([
        _select_entry(selected_index=0),
    ])

    serialized = json.dumps(payload)

    assert "selected_value" not in serialized

    entry = _select_entry(selected_index=0)
    entry["mutation_identity"] = {
        "kind": "SELECT",
        "selected_index": 0,
        "selected_value": "1",
    }

    with pytest.raises(FormEffectRuntimeError):
        build_form_effect_runtime_payload([entry])


# 3. checkbox true/false.
def test_checkbox_true_and_false_accepted():
    for checked in (True, False):
        payload = build_form_effect_runtime_payload([
            _checkbox_entry(checked=checked),
        ])

        assert payload["routes"][0]["trigger"][
            "mutation_identity"
        ] == {
            "kind": "CHECKBOX",
            "checked": checked,
        }


# 4. radio true.
def test_radio_checked_true_accepted():
    payload = build_form_effect_runtime_payload([
        _radio_entry(checked=True),
    ])

    assert payload["routes"][0]["trigger"][
        "mutation_identity"
    ] == {
        "kind": "RADIO",
        "checked": True,
    }


# 5. radio false rejected.
def test_radio_checked_false_rejected():
    with pytest.raises(FormEffectRuntimeError):
        build_form_effect_runtime_payload([
            _radio_entry(checked=False),
        ])


# 6. invalid selected_index rejected.
@pytest.mark.parametrize(
    "selected_index",
    [-1, True, "1", 1.5, None],
)
def test_invalid_selected_index_rejected(selected_index):
    entry = _select_entry(selected_index=0)
    entry["mutation_identity"] = {
        "kind": "SELECT",
        "selected_index": selected_index,
    }

    with pytest.raises(FormEffectRuntimeError):
        build_form_effect_runtime_payload([entry])


# 7. state_id participates in identity.
def test_state_id_participates_in_identity():
    payload = build_form_effect_runtime_payload([
        _select_entry(state_id="STATE_A", selected_index=0),
        _select_entry(state_id="STATE_B", selected_index=0),
    ])

    assert payload["route_count"] == 2

    state_ids = {
        route["trigger"]["state_id"]
        for route in payload["routes"]
    }

    assert state_ids == {"STATE_A", "STATE_B"}


# 8. frame_path participates in identity.
def test_frame_path_participates_in_identity():
    payload = build_form_effect_runtime_payload([
        _select_entry(selected_index=0),
    ])

    route = payload["routes"][0]

    assert route["trigger"]["action"]["frame_path"] == "main"


# 9. non-main frame fails closed.
def test_non_main_frame_fails_closed():
    entry = _select_entry(selected_index=0)
    entry["action"]["frame_path"] = "iframe[0]"

    with pytest.raises(FormEffectRuntimeError):
        build_form_effect_runtime_payload([entry])


def test_non_main_target_frame_fails_closed():
    effect = _bool_effect(
        EFFECT_DISABLED_CHANGED,
        after=True,
        target=_target(frame_path="iframe[0]"),
    )

    entry = _select_entry(selected_index=0, effects=[effect])

    with pytest.raises(FormEffectRuntimeError):
        build_form_effect_runtime_payload([entry])


# 10. identical evidence deduplicates.
def test_identical_evidence_deduplicates():
    effect = _bool_effect(EFFECT_DISABLED_CHANGED, after=True)

    payload = build_form_effect_runtime_payload([
        _select_entry(selected_index=0, effects=[effect]),
        _select_entry(selected_index=0, effects=[dict(effect)]),
    ])

    assert payload["route_count"] == 1


# 11. conflicting identical trigger fails closed.
def test_conflicting_identical_trigger_fails_closed():
    effect_a = _bool_effect(EFFECT_DISABLED_CHANGED, after=True)
    effect_b = _bool_effect(EFFECT_DISABLED_CHANGED, after=False)

    with pytest.raises(FormEffectRuntimeError):
        build_form_effect_runtime_payload([
            _select_entry(selected_index=0, effects=[effect_a]),
            _select_entry(selected_index=0, effects=[effect_b]),
        ])


# 12. deterministic ordering.
def test_deterministic_ordering():
    entries = [
        _select_entry(state_id="STATE_B", selected_index=0),
        _select_entry(state_id="STATE_A", selected_index=1),
        _checkbox_entry(state_id="STATE_A", checked=True),
    ]

    payload_one = build_form_effect_runtime_payload(list(entries))
    payload_two = build_form_effect_runtime_payload(
        list(reversed(entries))
    )

    assert payload_one["routes"] == payload_two["routes"]


# 13. visibility true/false.
def test_visibility_changed_true_and_false_executable():
    for after in (True, False):
        effect = _bool_effect(EFFECT_VISIBILITY_CHANGED, after=after)

        payload = build_form_effect_runtime_payload([
            _select_entry(selected_index=0, effects=[effect]),
        ])

        route = payload["routes"][0]

        assert route["status"] == ROUTE_STATUS_EXECUTABLE
        assert route["executable_effects"][0]["after"] == after


# 14. disabled true/false.
def test_disabled_changed_true_and_false_executable():
    for after in (True, False):
        effect = _bool_effect(EFFECT_DISABLED_CHANGED, after=after)

        payload = build_form_effect_runtime_payload([
            _select_entry(selected_index=0, effects=[effect]),
        ])

        assert (
            payload["routes"][0]["executable_effects"][0]["after"]
            == after
        )


# 15. readonly true/false + semantic guard.
def test_readonly_changed_true_and_false_executable_for_text_input():
    for after in (True, False):
        effect = _bool_effect(
            EFFECT_READONLY_CHANGED,
            after=after,
            target=_target(semantic_kind="TEXT_INPUT"),
        )

        payload = build_form_effect_runtime_payload([
            _select_entry(selected_index=0, effects=[effect]),
        ])

        assert (
            payload["routes"][0]["executable_effects"][0]["after"]
            == after
        )


def test_readonly_changed_rejected_for_non_text_semantic():
    effect = _bool_effect(
        EFFECT_READONLY_CHANGED,
        after=True,
        target=_target(semantic_kind="SELECT"),
    )

    with pytest.raises(FormEffectRuntimeError):
        build_form_effect_runtime_payload([
            _select_entry(selected_index=0, effects=[effect]),
        ])


# 16. required true/false.
def test_required_changed_true_and_false_executable():
    for after in (True, False):
        effect = _bool_effect(EFFECT_REQUIRED_CHANGED, after=after)

        payload = build_form_effect_runtime_payload([
            _select_entry(selected_index=0, effects=[effect]),
        ])

        assert (
            payload["routes"][0]["executable_effects"][0]["after"]
            == after
        )


# 17. checked true/false.
def test_checked_changed_true_and_false_executable():
    for after in (True, False):
        effect = _bool_effect(EFFECT_CHECKED_CHANGED, after=after)

        payload = build_form_effect_runtime_payload([
            _select_entry(selected_index=0, effects=[effect]),
        ])

        assert (
            payload["routes"][0]["executable_effects"][0]["after"]
            == after
        )


# 18. checked live property semantics.
def test_checked_changed_dispatches_only_on_actual_change():
    source = form_effect_runtime_adapter_source()

    assert "targetElement.checked === after" in source
    assert "dispatchEvent" in source


# 19. CONTROL_DISAPPEARED never remove().
def test_control_disappeared_never_uses_remove():
    effect = {
        "kind": EFFECT_CONTROL_DISAPPEARED,
        "target": _target(),
        "before": True,
        "after": None,
    }

    payload = build_form_effect_runtime_payload([
        _select_entry(selected_index=0, effects=[effect]),
    ])

    route = payload["routes"][0]

    assert route["status"] == ROUTE_STATUS_EXECUTABLE
    assert route["executable_effects"][0]["kind"] == (
        EFFECT_CONTROL_DISAPPEARED
    )

    source = form_effect_runtime_adapter_source()

    assert ".remove()" not in source
    assert "applyControlDisappeared" in source


# 20. CONTROL_APPEARED blocked.
def test_control_appeared_blocked():
    effect = {
        "kind": EFFECT_CONTROL_APPEARED,
        "target": _target(),
        "before": None,
        "after": True,
    }

    payload = build_form_effect_runtime_payload([
        _select_entry(selected_index=0, effects=[effect]),
    ])

    route = payload["routes"][0]

    assert route["status"] == ROUTE_STATUS_BLOCKED
    assert route["executable_effects"] == ()
    assert EFFECT_CONTROL_APPEARED in route["blocked_effect_kinds"]


# 21. INTERACTABLE blocked.
def test_interactable_changed_blocked():
    effect = _bool_effect(EFFECT_INTERACTABLE_CHANGED, after=True)

    payload = build_form_effect_runtime_payload([
        _select_entry(selected_index=0, effects=[effect]),
    ])

    route = payload["routes"][0]

    assert route["status"] == ROUTE_STATUS_BLOCKED
    assert (
        EFFECT_INTERACTABLE_CHANGED
        in route["blocked_effect_kinds"]
    )


# 22. HAS_VALUE blocked.
def test_has_value_changed_blocked():
    effect = _bool_effect(EFFECT_HAS_VALUE_CHANGED, after=True)

    payload = build_form_effect_runtime_payload([
        _select_entry(selected_index=0, effects=[effect]),
    ])

    route = payload["routes"][0]

    assert route["status"] == ROUTE_STATUS_BLOCKED
    assert EFFECT_HAS_VALUE_CHANGED in route["blocked_effect_kinds"]


def test_blocked_effect_prevents_partial_executable_fidelity():
    blocked = _bool_effect(EFFECT_HAS_VALUE_CHANGED, after=True)
    executable = _bool_effect(
        EFFECT_DISABLED_CHANGED,
        after=True,
        target=_target(
            control_key="main::INPUT::#beta",
            selector="#beta",
        ),
    )

    payload = build_form_effect_runtime_payload([
        _select_entry(
            selected_index=0,
            effects=[blocked, executable],
        ),
    ])

    route = payload["routes"][0]

    assert route["status"] == ROUTE_STATUS_BLOCKED
    assert route["executable_effects"] == ()


# 23. SELECTION_CHANGED delegated to CATALOG_RUNTIME.
def test_selection_changed_delegated_to_catalog_runtime():
    effect = {
        "kind": EFFECT_SELECTION_CHANGED,
        "target": _target(semantic_kind="SELECT"),
        "before": {
            "selected_values": ("1",),
            "selected_indexes": (0,),
        },
        "after": {
            "selected_values": ("2",),
            "selected_indexes": (1,),
        },
    }

    payload = build_form_effect_runtime_payload([
        _select_entry(selected_index=1, effects=[effect]),
    ])

    route = payload["routes"][0]

    assert route["status"] == ROUTE_STATUS_EXECUTABLE
    assert route["executable_effects"] == ()
    assert len(route["delegated_effects"]) == 1

    delegated = route["delegated_effects"][0]

    assert delegated["kind"] == EFFECT_SELECTION_CHANGED
    assert delegated["owner"] == SELECTION_CHANGED_OWNER
    assert "before" not in delegated
    assert "after" not in delegated


# 24. no second selection engine.
def test_no_second_selection_engine():
    assert EFFECT_SELECTION_CHANGED not in EXECUTABLE_EFFECT_KINDS

    source = form_effect_runtime_adapter_source()

    assert "selectByIndex" not in source
    assert ".selected = " not in source
    assert "applySelectionChanged" not in source


# 25. no second context engine.
def test_no_second_context_engine():
    source = form_effect_runtime_adapter_source()

    assert "navigation_context" not in source
    assert "context_signature" not in source


# 26. contextual-shaped routing rejected/fail-closed.
@pytest.mark.parametrize(
    "shape_key",
    ["context", "navigation_context", "context_signature"],
)
def test_contextual_shaped_evidence_rejected(shape_key):
    entry = _select_entry(selected_index=0)
    entry[shape_key] = {"anything": True}

    with pytest.raises(FormEffectRuntimeError):
        build_form_effect_runtime_payload([entry])

    entry2 = _select_entry(selected_index=0)
    entry2["action"][shape_key] = "x"

    with pytest.raises(FormEffectRuntimeError):
        build_form_effect_runtime_payload([entry2])


# 27. malformed action rejected.
@pytest.mark.parametrize(
    "action",
    [
        None,
        {},
        {"kind": "SELECT", "selector": "", "frame_path": "main"},
        {"kind": "TEXT", "selector": "#a", "frame_path": "main"},
    ],
)
def test_malformed_action_rejected(action):
    entry = _select_entry(selected_index=0)
    entry["action"] = action

    with pytest.raises(FormEffectRuntimeError):
        build_form_effect_runtime_payload([entry])


# 28. malformed target rejected.
@pytest.mark.parametrize(
    "target",
    [
        None,
        {},
        {
            "control_key": "k",
            "frame_path": "main",
            "selector": "",
            "semantic_kind": "TEXT_INPUT",
        },
    ],
)
def test_malformed_target_rejected(target):
    effect = {
        "kind": EFFECT_DISABLED_CHANGED,
        "target": target,
        "before": False,
        "after": True,
    }

    with pytest.raises(FormEffectRuntimeError):
        build_form_effect_runtime_payload([
            _select_entry(selected_index=0, effects=[effect]),
        ])


# 29. privacy/no literal values.
_FORBIDDEN_PRIVACY_KEYS = (
    "selected_value",
    "free_text",
    "textarea_content",
    "password",
    "file_path",
    "cookies",
    "tokens",
    "raw_dom",
    "raw_capture",
)


def test_privacy_no_literal_values_in_payload():
    effect = _bool_effect(EFFECT_CHECKED_CHANGED, after=True)

    payload = build_form_effect_runtime_payload([
        _checkbox_entry(checked=True, effects=[effect]),
        _radio_entry(checked=True),
    ])

    serialized = json.dumps(payload)

    for forbidden in _FORBIDDEN_PRIVACY_KEYS:
        assert forbidden not in serialized


# 30. deterministic adapter source.
def test_adapter_source_is_deterministic_and_payload_agnostic():
    first = form_effect_runtime_adapter_source()
    second = form_effect_runtime_adapter_source()

    assert first == second
    assert "#alpha" not in first
    assert "STATE_1" not in first


# 31. unresolved/ambiguous runtime controls fail closed.
def test_adapter_resolves_unique_nodes_only():
    source = form_effect_runtime_adapter_source()

    assert "nodes.length !== 1" in source
    assert "return null" in source


def test_adapter_performs_no_navigation_or_network():
    source = form_effect_runtime_adapter_source()

    assert "fetch(" not in source
    assert "XMLHttpRequest" not in source
    assert "location.href" not in source
    assert "location.assign" not in source
    assert "location.replace" not in source


# 32. existing effect constants reused.
def test_existing_effect_constants_reused():
    assert EXECUTABLE_EFFECT_KINDS == {
        EFFECT_VISIBILITY_CHANGED,
        EFFECT_DISABLED_CHANGED,
        EFFECT_READONLY_CHANGED,
        EFFECT_REQUIRED_CHANGED,
        EFFECT_CHECKED_CHANGED,
        EFFECT_CONTROL_DISAPPEARED,
    }

    assert DELEGATED_EFFECT_KINDS == {EFFECT_SELECTION_CHANGED}

    assert BLOCKED_EFFECT_KINDS == {
        EFFECT_INTERACTABLE_CHANGED,
        EFFECT_HAS_VALUE_CHANGED,
        EFFECT_CONTROL_APPEARED,
    }


def test_malformed_evidence_records_container_rejected():
    with pytest.raises(FormEffectRuntimeError):
        build_form_effect_runtime_payload("not-a-list")

    with pytest.raises(FormEffectRuntimeError):
        build_form_effect_runtime_payload(["not-a-dict"])


def test_empty_evidence_records_yields_empty_payload():
    payload = build_form_effect_runtime_payload([])

    assert payload["route_count"] == 0
    assert payload["routes"] == ()
    assert payload["contextual_effects"] == "NO"


# ---------------------------------------------------------------------------
# inject_form_effect_runtime_adapter() (UWT-6B3-1C2 HTML wiring).
# ---------------------------------------------------------------------------


def _html_shell(body=""):
    return (
        "<!doctype html><html><head></head><body>"
        + body
        + "</body></html>"
    )


def _runtime_payload():
    return build_form_effect_runtime_payload([
        _select_entry(selected_index=0),
    ])


def test_inject_adapter_is_deterministic():
    payload = _runtime_payload()

    first = inject_form_effect_runtime_adapter(_html_shell(), payload)
    second = inject_form_effect_runtime_adapter(_html_shell(), payload)

    assert first == second


def test_inject_adapter_adds_payload_element_and_local_script_reference():
    payload = _runtime_payload()

    html = inject_form_effect_runtime_adapter(_html_shell(), payload)

    assert html.count(
        'id="' + AUTO_TWIN_FORM_EFFECT_RUNTIME_PAYLOAD_ELEMENT_ID + '"'
    ) == 1

    assert html.count(
        AUTO_TWIN_FORM_EFFECT_RUNTIME_SCRIPT_MARKER + '="'
    ) == 1

    assert (
        'src="' + AUTO_TWIN_FORM_EFFECT_RUNTIME_ADAPTER_FILENAME + '"'
    ) in html

    assert (
        str(AUTO_TWIN_FORM_EFFECT_RUNTIME_ADAPTER_VERSION)
        in html
    )


def test_inject_adapter_payload_is_embedded_and_parseable():
    payload = _runtime_payload()

    html = inject_form_effect_runtime_adapter(_html_shell(), payload)

    start = html.index(
        'id="' + AUTO_TWIN_FORM_EFFECT_RUNTIME_PAYLOAD_ELEMENT_ID + '"'
    )
    start = html.index(">", start) + 1
    end = html.index("</script>", start)

    embedded = json.loads(html[start:end])

    assert embedded == json.loads(json.dumps(payload))


def test_inject_adapter_escapes_script_breakout():
    payload = build_form_effect_runtime_payload([
        _select_entry(
            selector="#a</script><script>alert(1)</script>",
            selected_index=0,
        ),
    ])

    html = inject_form_effect_runtime_adapter(_html_shell(), payload)

    assert "</script><script>alert(1)" not in html


def test_inject_adapter_idempotent_on_already_wired_html():
    payload = _runtime_payload()

    once = inject_form_effect_runtime_adapter(_html_shell(), payload)
    twice = inject_form_effect_runtime_adapter(once, payload)

    assert once == twice

    assert once.count(
        AUTO_TWIN_FORM_EFFECT_RUNTIME_SCRIPT_MARKER + '="'
    ) == 1


def test_inject_adapter_noop_for_empty_routes():
    empty_payload = build_form_effect_runtime_payload([])

    html = _html_shell()

    assert (
        inject_form_effect_runtime_adapter(html, empty_payload)
        == html
    )


def test_inject_adapter_rejects_malformed_payload_authority():
    with pytest.raises(FormEffectRuntimeError):
        inject_form_effect_runtime_adapter(_html_shell(), {})

    with pytest.raises(FormEffectRuntimeError):
        inject_form_effect_runtime_adapter(
            _html_shell(),
            {
                "schema_version": 1,
                "record_type": "QCC_AUTO_TWIN_FORM_EFFECT_RUNTIME_PLAN",
                "routes": "not-a-list",
            },
        )

    with pytest.raises(TypeError):
        inject_form_effect_runtime_adapter(None, _runtime_payload())


def test_inject_adapter_never_navigates_or_fetches():
    payload = _runtime_payload()

    html = inject_form_effect_runtime_adapter(_html_shell(), payload)

    assert "fetch(" not in html
    assert "XMLHttpRequest" not in html
    assert "location.href" not in html
    assert "location.assign" not in html


def test_runtime_artifact_filenames_are_stable():
    assert (
        AUTO_TWIN_FORM_EFFECT_RUNTIME_FILENAME
        == "form_effect_runtime.json"
    )

    assert (
        AUTO_TWIN_FORM_EFFECT_RUNTIME_ADAPTER_FILENAME
        == "form_effect_runtime_adapter.js"
    )
