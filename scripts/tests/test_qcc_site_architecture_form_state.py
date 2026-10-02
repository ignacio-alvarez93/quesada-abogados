from backend.automation.site_architecture import (
    build_functional_state_fingerprint,
    normalize_dom_capture,
)
from backend.automation.site_architecture.form_state import (
    normalize_form_constraints,
    normalize_form_state,
)


def _payload(elements):
    return {
        "schema_version": 1,
        "captured_at":
            "2026-10-02T10:00:00.000Z",

        "metadata": {
            "url":
                "https://example.test/form",

            "origin":
                "https://example.test",

            "pathname":
                "/form",

            "title":
                "Form test",

            "ready_state":
                "complete",
        },

        "documents": [],
        "frames": [],
        "shadows": [],
        "catalogs": [],
        "counts": {},

        "elements": elements,
    }


def _text_element(**overrides):
    element = {
        "index": 0,
        "frame_path": "main",
        "tag": "input",
        "id": "field",
        "name": "field",
        "type": "text",
        "role": "",
        "attributes": {
            "id": "field",
            "name": "field",
            "type": "text",
        },
        "visible": True,
        "disabled": False,
    }

    element.update(overrides)

    return element


# ---------------------------------------------------------------------------
# TEXT
# ---------------------------------------------------------------------------

def test_text_input_empty_has_value_false():
    element = _text_element(
        form_signals={
            "has_value": False,
        },
    )

    snapshot = normalize_dom_capture(
        _payload([element])
    )

    form_state = (
        snapshot.elements[0]["form_state"]
    )

    assert form_state["has_value"] is False


def test_text_input_populated_has_value_true():
    element = _text_element(
        attributes={
            "id": "field",
            "name": "field",
            "type": "text",
            "value": "Juan Perez",
        },
        form_signals={
            "has_value": True,
        },
    )

    snapshot = normalize_dom_capture(
        _payload([element])
    )

    form_state = (
        snapshot.elements[0]["form_state"]
    )

    assert form_state["has_value"] is True


def test_text_input_literal_text_absent_from_normalized_form_state():
    element = _text_element(
        attributes={
            "id": "field",
            "name": "field",
            "type": "text",
            "value": "Juan Perez",
        },
        form_signals={
            "has_value": True,
        },
    )

    snapshot = normalize_dom_capture(
        _payload([element])
    )

    form_state = (
        snapshot.elements[0]["form_state"]
    )

    assert "value" not in form_state
    assert "Juan Perez" not in str(form_state)


# ---------------------------------------------------------------------------
# PASSWORD
# ---------------------------------------------------------------------------

def test_password_populated_has_value_true():
    element = _text_element(
        type="password",
        attributes={
            "id": "field",
            "name": "field",
            "type": "password",
            "value": "super-secret",
        },
        form_signals={
            "has_value": True,
        },
    )

    snapshot = normalize_dom_capture(
        _payload([element])
    )

    form_state = (
        snapshot.elements[0]["form_state"]
    )

    assert form_state["has_value"] is True
    assert "value" not in form_state
    assert "super-secret" not in str(form_state)


# ---------------------------------------------------------------------------
# HIDDEN
# ---------------------------------------------------------------------------

def test_hidden_populated_has_value_true():
    element = _text_element(
        tag="input",
        type="hidden",
        attributes={
            "id": "field",
            "name": "field",
            "type": "hidden",
            "value": "session-token-abc",
        },
        form_signals={
            "has_value": True,
        },
    )

    snapshot = normalize_dom_capture(
        _payload([element])
    )

    form_state = (
        snapshot.elements[0]["form_state"]
    )

    assert form_state["has_value"] is True
    assert "value" not in form_state
    assert "session-token-abc" not in str(form_state)


# ---------------------------------------------------------------------------
# TEXTAREA
# ---------------------------------------------------------------------------

def test_textarea_empty_and_non_empty():
    empty = normalize_form_state({
        "tag": "textarea",
        "semantics": ("TEXTAREA",),
        "form_signals": {
            "has_value": False,
        },
    })

    non_empty = normalize_form_state({
        "tag": "textarea",
        "semantics": ("TEXTAREA",),
        "form_signals": {
            "has_value": True,
        },
    })

    assert empty["has_value"] is False
    assert non_empty["has_value"] is True


# ---------------------------------------------------------------------------
# CHECKBOX
# ---------------------------------------------------------------------------

def test_checkbox_checked_true_and_false():
    checked_true = normalize_form_state({
        "tag": "input",
        "type": "checkbox",
        "semantics": ("CHECKBOX",),
        "checked": True,
    })

    checked_false = normalize_form_state({
        "tag": "input",
        "type": "checkbox",
        "semantics": ("CHECKBOX",),
        "checked": False,
    })

    assert checked_true["checked"] is True
    assert checked_false["checked"] is False


def test_checkbox_option_value_remains_available_in_element_evidence():
    element = {
        "index": 0,
        "frame_path": "main",
        "tag": "input",
        "id": "accepts-terms",
        "name": "accepts-terms",
        "type": "checkbox",
        "role": "",
        "attributes": {
            "id": "accepts-terms",
            "name": "accepts-terms",
            "type": "checkbox",
            "value": "yes",
        },
        "checked": True,
        "visible": True,
        "disabled": False,
    }

    snapshot = normalize_dom_capture(
        _payload([element])
    )

    normalized = snapshot.elements[0]

    assert (
        normalized["attributes"]["value"]
        == "yes"
    )

    assert normalized["form_state"]["checked"] is True


# ---------------------------------------------------------------------------
# RADIO
# ---------------------------------------------------------------------------

def test_radio_checked_true_and_false():
    checked_true = normalize_form_state({
        "tag": "input",
        "type": "radio",
        "semantics": ("RADIO",),
        "checked": True,
    })

    checked_false = normalize_form_state({
        "tag": "input",
        "type": "radio",
        "semantics": ("RADIO",),
        "checked": False,
    })

    assert checked_true["checked"] is True
    assert checked_false["checked"] is False


# ---------------------------------------------------------------------------
# SELECT
# ---------------------------------------------------------------------------

def test_select_single_selected_values_and_indexes():
    form_state = normalize_form_state({
        "tag": "select",
        "semantics": ("SELECT",),
        "options": [
            {"value": "33", "text": "Asturias", "selected": False},
            {"value": "28", "text": "Madrid", "selected": True},
            {"value": "08", "text": "Barcelona", "selected": False},
        ],
    })

    assert form_state["selected_values"] == ("28",)
    assert form_state["selected_indexes"] == (1,)


def test_select_multiple_selected_values_document_order():
    form_state = normalize_form_state({
        "tag": "select",
        "semantics": ("SELECT",),
        "options": [
            {"value": "a", "text": "A", "selected": True},
            {"value": "b", "text": "B", "selected": False},
            {"value": "c", "text": "C", "selected": True},
        ],
    })

    assert form_state["selected_values"] == ("a", "c")
    assert form_state["selected_indexes"] == (0, 2)


def test_select_deterministic_document_order_across_calls():
    element = {
        "tag": "select",
        "semantics": ("SELECT",),
        "options": [
            {"value": "x", "text": "X", "selected": True},
            {"value": "y", "text": "Y", "selected": True},
        ],
    }

    first = normalize_form_state(element)
    second = normalize_form_state(element)

    assert (
        first["selected_values"]
        == second["selected_values"]
        == ("x", "y")
    )


# ---------------------------------------------------------------------------
# FILE
# ---------------------------------------------------------------------------

def test_file_input_exposes_only_file_selected():
    element = {
        "index": 0,
        "frame_path": "main",
        "tag": "input",
        "id": "upload",
        "name": "upload",
        "type": "file",
        "role": "",
        "attributes": {
            "id": "upload",
            "name": "upload",
            "type": "file",
        },
        "form_signals": {
            "file_selected": True,
            "file_count": 1,
        },
        "visible": True,
        "disabled": False,
    }

    snapshot = normalize_dom_capture(
        _payload([element])
    )

    form_state = (
        snapshot.elements[0]["form_state"]
    )

    assert form_state["file_selected"] is True
    assert "path" not in form_state
    assert "filename" not in form_state
    assert "fakepath" not in str(form_state).lower()


# ---------------------------------------------------------------------------
# CONSTRAINTS
# ---------------------------------------------------------------------------

def test_form_constraints_projects_generic_fields():
    constraints = normalize_form_constraints({
        "tag": "input",
        "type": "text",
        "semantics": ("TEXT_INPUT",),
        "disabled": False,
        "attributes": {
            "required": "",
            "pattern": "[0-9]+",
            "min": "1",
            "max": "10",
            "step": "1",
            "minlength": "2",
            "maxlength": "20",
            "placeholder": "Introduce un valor",
            "autocomplete": "off",
        },
        "form_signals": {
            "required": True,
            "readonly": False,
            "multiple": False,
        },
    })

    assert constraints["required"] is True
    assert constraints["readonly"] is False
    assert constraints["disabled"] is False
    assert constraints["multiple"] is False
    assert constraints["pattern"] == "[0-9]+"
    assert constraints["min"] == "1"
    assert constraints["max"] == "10"
    assert constraints["step"] == "1"
    assert constraints["minlength"] == "2"
    assert constraints["maxlength"] == "20"
    assert constraints["placeholder"] == "Introduce un valor"
    assert constraints["autocomplete"] == "off"


def test_form_constraints_absent_optional_fields_are_null():
    constraints = normalize_form_constraints({
        "tag": "input",
        "type": "text",
        "semantics": ("TEXT_INPUT",),
        "disabled": False,
        "attributes": {},
        "form_signals": {
            "required": False,
            "readonly": False,
            "multiple": False,
        },
    })

    assert constraints["pattern"] is None
    assert constraints["min"] is None
    assert constraints["max"] is None
    assert constraints["step"] is None
    assert constraints["minlength"] is None
    assert constraints["maxlength"] is None
    assert constraints["placeholder"] is None
    assert constraints["autocomplete"] is None


def test_form_constraints_select_multiple():
    constraints = normalize_form_constraints({
        "tag": "select",
        "semantics": ("SELECT",),
        "disabled": False,
        "attributes": {
            "multiple": "",
        },
        "form_signals": {
            "required": False,
            "readonly": False,
            "multiple": True,
        },
    })

    assert constraints["multiple"] is True


def test_form_constraints_disabled_and_readonly():
    constraints = normalize_form_constraints({
        "tag": "input",
        "type": "text",
        "semantics": ("TEXT_INPUT",),
        "disabled": True,
        "attributes": {
            "readonly": "",
        },
        "form_signals": {
            "required": False,
            "readonly": True,
            "multiple": False,
        },
    })

    assert constraints["disabled"] is True
    assert constraints["readonly"] is True


# ---------------------------------------------------------------------------
# NORMALIZER
# ---------------------------------------------------------------------------

def test_normalizer_only_attaches_form_fields_for_relevant_controls():
    elements = [
        {
            "index": 0,
            "frame_path": "main",
            "tag": "div",
            "id": "wrapper",
            "attributes": {},
            "visible": True,
            "disabled": False,
        },
        _text_element(
            form_signals={
                "has_value": True,
            },
        ),
    ]

    snapshot = normalize_dom_capture(
        _payload(elements)
    )

    assert "form_state" not in snapshot.elements[0]
    assert "form_constraints" not in snapshot.elements[0]

    assert "form_state" in snapshot.elements[1]
    assert "form_constraints" in snapshot.elements[1]


# ---------------------------------------------------------------------------
# ACTION INVENTORY
# ---------------------------------------------------------------------------

def test_action_inventory_propagates_exact_normalized_form_fields():
    element = _text_element(
        form_signals={
            "has_value": True,
            "required": True,
            "readonly": False,
            "multiple": False,
        },
        attributes={
            "id": "field",
            "name": "field",
            "type": "text",
            "placeholder": "Nombre",
        },
    )

    snapshot = normalize_dom_capture(
        _payload([element])
    )

    assert len(snapshot.actions) == 1

    action = snapshot.actions[0]

    assert (
        action["form_state"]
        == snapshot.elements[0]["form_state"]
    )

    assert (
        action["form_constraints"]
        == snapshot.elements[0]["form_constraints"]
    )

    assert action["form_state"]["has_value"] is True
    assert action["form_constraints"]["required"] is True
    assert (
        action["form_constraints"]["placeholder"]
        == "Nombre"
    )


def test_action_inventory_form_fields_null_for_non_form_actions():
    element = {
        "index": 0,
        "frame_path": "main",
        "tag": "button",
        "id": "continue-action",
        "name": "",
        "type": "button",
        "role": "button",
        "attributes": {
            "id": "continue-action",
            "type": "button",
            "role": "button",
        },
        "visible": True,
        "disabled": False,
    }

    snapshot = normalize_dom_capture(
        _payload([element])
    )

    assert len(snapshot.actions) == 1

    action = snapshot.actions[0]

    assert action["form_state"] is None
    assert action["form_constraints"] is None


# ---------------------------------------------------------------------------
# LEGACY
# ---------------------------------------------------------------------------

def test_legacy_capture_without_form_signals_normalizes_safely():
    element = _text_element()
    element.pop("form_signals", None)

    snapshot = normalize_dom_capture(
        _payload([element])
    )

    form_state = (
        snapshot.elements[0]["form_state"]
    )

    form_constraints = (
        snapshot.elements[0]["form_constraints"]
    )

    assert form_state["has_value"] is None
    assert form_constraints["required"] is False
    assert form_constraints["disabled"] is False


def test_legacy_capture_without_semantics_relevant_fields_skips_cleanly():
    element = {
        "index": 0,
        "frame_path": "main",
        "tag": "div",
        "attributes": {},
    }

    snapshot = normalize_dom_capture(
        _payload([element])
    )

    assert "form_state" not in snapshot.elements[0]
    assert "form_constraints" not in snapshot.elements[0]


# ---------------------------------------------------------------------------
# UWT — functional fingerprint must stay unchanged
# ---------------------------------------------------------------------------

def test_functional_fingerprint_unchanged_by_new_form_evidence():
    base_element = _text_element()

    with_value_signals = _text_element(
        form_signals={
            "has_value": True,
            "required": True,
        },
        attributes={
            "id": "field",
            "name": "field",
            "type": "text",
            "value": "Juan Perez",
        },
    )

    snapshot_without = normalize_dom_capture(
        _payload([base_element])
    )

    snapshot_with = normalize_dom_capture(
        _payload([with_value_signals])
    )

    fingerprint_without = (
        build_functional_state_fingerprint(
            snapshot_without
        )
    )

    fingerprint_with = (
        build_functional_state_fingerprint(
            snapshot_with
        )
    )

    assert fingerprint_without == fingerprint_with


# ---------------------------------------------------------------------------
# SITE NEUTRALITY
# ---------------------------------------------------------------------------

def test_form_state_module_has_no_site_specific_logic():
    source = (
        "backend/automation/site_architecture/form_state.py"
    )

    with open(source, encoding="utf-8") as handle:
        content = handle.read().lower()

    forbidden = (
        "mercurio",
        "ex01",
        "datosforaut",
        "gsup",
        "province",
        "nationality",
    )

    for token in forbidden:
        assert token not in content
