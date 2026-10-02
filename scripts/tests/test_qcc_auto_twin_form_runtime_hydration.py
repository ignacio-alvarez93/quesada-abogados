import pytest

from backend.qcc.auto_twin.form_runtime_hydration import (
    RUNTIME_POLICY_PRESERVE_EXISTING,
    RUNTIME_POLICY_REQUIRE_EXTERNAL_FILE,
    RUNTIME_POLICY_RESTORE_CAPTURED_STATE,
    RUNTIME_POLICY_SUPPLY_SYNTHETIC_VALUE,
    build_form_runtime_hydration_plan,
)


def _payload(elements):
    return {
        "schema_version": 1,
        "captured_at": "2026-10-02T10:00:00.000Z",
        "metadata": {
            "url": "https://example.test/form",
            "origin": "https://example.test",
            "pathname": "/form",
            "title": "Form test",
            "ready_state": "complete",
        },
        "documents": [],
        "frames": [],
        "shadows": [],
        "catalogs": [],
        "counts": {},
        "elements": elements,
    }


def _element(**overrides):
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


def _single_operation(plan):
    assert plan["operation_count"] == 1
    return plan["operations"][0]


# ---------------------------------------------------------------------------
# TEXT
# ---------------------------------------------------------------------------

def test_text_empty_does_not_require_runtime_value():
    element = _element(
        form_signals={"has_value": False},
    )

    plan = build_form_runtime_hydration_plan(
        _payload([element])
    )

    operation = _single_operation(plan)

    assert operation["kind"] == "TEXT"
    assert operation["requires_runtime_value"] is False
    assert operation["runtime_policy"] == "NONE"


def test_text_populated_requires_runtime_value():
    element = _element(
        attributes={
            "id": "field",
            "name": "field",
            "type": "text",
            "value": "Juan Perez",
        },
        form_signals={"has_value": True},
    )

    plan = build_form_runtime_hydration_plan(
        _payload([element])
    )

    operation = _single_operation(plan)

    assert operation["requires_runtime_value"] is True
    assert (
        operation["runtime_policy"]
        == RUNTIME_POLICY_SUPPLY_SYNTHETIC_VALUE
    )


# ---------------------------------------------------------------------------
# PASSWORD
# ---------------------------------------------------------------------------

def test_password_populated_without_literal_value():
    element = _element(
        type="password",
        attributes={
            "id": "field",
            "name": "field",
            "type": "password",
            "value": "super-secret",
        },
        form_signals={"has_value": True},
    )

    plan = build_form_runtime_hydration_plan(
        _payload([element])
    )

    operation = _single_operation(plan)

    assert operation["requires_runtime_value"] is True
    assert "super-secret" not in str(plan)


# ---------------------------------------------------------------------------
# HIDDEN
# ---------------------------------------------------------------------------

def test_hidden_preserve_existing_default():
    element = _element(
        tag="input",
        type="hidden",
        attributes={
            "id": "field",
            "name": "field",
            "type": "hidden",
            "value": "session-token-abc",
        },
        form_signals={"has_value": True},
    )

    plan = build_form_runtime_hydration_plan(
        _payload([element])
    )

    operation = _single_operation(plan)

    assert operation["kind"] == "HIDDEN"
    assert operation["requires_runtime_value"] is False
    assert (
        operation["runtime_policy"]
        == RUNTIME_POLICY_PRESERVE_EXISTING
    )
    assert "session-token-abc" not in str(plan)


# ---------------------------------------------------------------------------
# TEXTAREA
# ---------------------------------------------------------------------------

def test_textarea_populated_requires_runtime_value():
    element = _element(
        tag="textarea",
        type="",
        attributes={
            "id": "field",
            "name": "field",
        },
        form_signals={"has_value": True},
    )

    plan = build_form_runtime_hydration_plan(
        _payload([element])
    )

    operation = _single_operation(plan)

    assert operation["kind"] == "TEXTAREA"
    assert operation["requires_runtime_value"] is True


# ---------------------------------------------------------------------------
# CHECKBOX
# ---------------------------------------------------------------------------

def test_checkbox_false_and_true():
    unchecked = _element(
        type="checkbox",
        attributes={
            "id": "field",
            "name": "field",
            "type": "checkbox",
        },
        checked=False,
    )

    checked = _element(
        type="checkbox",
        attributes={
            "id": "field2",
            "name": "field2",
            "type": "checkbox",
        },
        id="field2",
        name="field2",
        checked=True,
    )

    plan_unchecked = build_form_runtime_hydration_plan(
        _payload([unchecked])
    )

    plan_checked = build_form_runtime_hydration_plan(
        _payload([checked])
    )

    op_unchecked = _single_operation(plan_unchecked)
    op_checked = _single_operation(plan_checked)

    assert op_unchecked["form_state"]["checked"] is False
    assert op_checked["form_state"]["checked"] is True

    assert (
        op_checked["runtime_policy"]
        == RUNTIME_POLICY_RESTORE_CAPTURED_STATE
    )


# ---------------------------------------------------------------------------
# RADIO
# ---------------------------------------------------------------------------

def test_radio_selected_option_identity():
    option_a = _element(
        tag="input",
        type="radio",
        id="",
        attributes={
            "name": "datosForAut",
            "type": "radio",
            "value": "130",
        },
        name="datosForAut",
        checked=True,
        index=0,
    )

    option_b = _element(
        tag="input",
        type="radio",
        id="",
        attributes={
            "name": "datosForAut",
            "type": "radio",
            "value": "140",
        },
        name="datosForAut",
        checked=False,
        index=1,
    )

    plan = build_form_runtime_hydration_plan(
        _payload([option_a, option_b])
    )

    assert plan["operation_count"] == 2

    by_value = {
        operation["option_value"]: operation
        for operation in plan["operations"]
    }

    assert by_value["130"]["form_state"]["checked"] is True
    assert by_value["140"]["form_state"]["checked"] is False

    # Group selector alone is non-unique; compound group+value
    # selector must still resolve addressability (Section 8).
    assert by_value["130"]["addressable"] is True
    assert by_value["140"]["addressable"] is True
    assert (
        by_value["130"]["selector"]
        != by_value["140"]["selector"]
    )


# ---------------------------------------------------------------------------
# SELECT
# ---------------------------------------------------------------------------

def test_select_single():
    element = _element(
        tag="select",
        type="",
        attributes={"id": "field", "name": "field"},
        options=[
            {"value": "33", "text": "Asturias", "selected": False},
            {"value": "28", "text": "Madrid", "selected": True},
        ],
    )

    plan = build_form_runtime_hydration_plan(
        _payload([element])
    )

    operation = _single_operation(plan)

    assert operation["kind"] == "SELECT"
    assert operation["form_state"]["selected_values"] == ("28",)
    assert (
        operation["runtime_policy"]
        == RUNTIME_POLICY_RESTORE_CAPTURED_STATE
    )


def test_select_multiple():
    element = _element(
        tag="select",
        type="",
        attributes={"id": "field", "name": "field", "multiple": ""},
        options=[
            {"value": "a", "text": "A", "selected": True},
            {"value": "b", "text": "B", "selected": False},
            {"value": "c", "text": "C", "selected": True},
        ],
    )

    plan = build_form_runtime_hydration_plan(
        _payload([element])
    )

    operation = _single_operation(plan)

    assert operation["form_state"]["selected_values"] == (
        "a",
        "c",
    )
    assert operation["form_constraints"]["multiple"] is True


# ---------------------------------------------------------------------------
# CONSTRAINTS
# ---------------------------------------------------------------------------

def test_constraints_carried_forward():
    element = _element(
        attributes={
            "id": "field",
            "name": "field",
            "type": "text",
            "required": "",
            "maxlength": "40",
            "pattern": "[A-Z]+",
        },
        form_signals={"has_value": False},
    )

    plan = build_form_runtime_hydration_plan(
        _payload([element])
    )

    operation = _single_operation(plan)

    constraints = operation["form_constraints"]

    assert constraints["required"] is True
    assert constraints["maxlength"] == "40"
    assert constraints["pattern"] == "[A-Z]+"


# ---------------------------------------------------------------------------
# FILE
# ---------------------------------------------------------------------------

def test_file_requires_external_file():
    element = _element(
        tag="input",
        type="file",
        attributes={"id": "field", "name": "field", "type": "file"},
        form_signals={"file_selected": True},
    )

    plan = build_form_runtime_hydration_plan(
        _payload([element])
    )

    operation = _single_operation(plan)

    assert operation["kind"] == "FILE"
    assert operation["requires_runtime_file"] is True
    assert (
        operation["runtime_policy"]
        == RUNTIME_POLICY_REQUIRE_EXTERNAL_FILE
    )


# ---------------------------------------------------------------------------
# CONTROL KEY DETERMINISM
# ---------------------------------------------------------------------------

def test_control_key_is_deterministic_across_calls():
    element = _element(
        attributes={
            "id": "field",
            "name": "field",
            "type": "text",
        },
        form_signals={"has_value": True},
    )

    plan_one = build_form_runtime_hydration_plan(
        _payload([element])
    )

    plan_two = build_form_runtime_hydration_plan(
        _payload([dict(element)])
    )

    assert (
        plan_one["operations"][0]["control_key"]
        == plan_two["operations"][0]["control_key"]
    )


def test_control_key_never_uses_document_index():
    element_low_index = _element(
        attributes={
            "id": "field",
            "name": "field",
            "type": "text",
        },
        form_signals={"has_value": True},
        index=0,
    )

    element_high_index = _element(
        attributes={
            "id": "field",
            "name": "field",
            "type": "text",
        },
        form_signals={"has_value": True},
        index=99,
    )

    plan_low = build_form_runtime_hydration_plan(
        _payload([element_low_index])
    )

    plan_high = build_form_runtime_hydration_plan(
        _payload([element_high_index])
    )

    assert (
        plan_low["operations"][0]["control_key"]
        == plan_high["operations"][0]["control_key"]
    )


# ---------------------------------------------------------------------------
# AMBIGUOUS SELECTOR FAILS CLOSED
# ---------------------------------------------------------------------------

def test_ambiguous_selector_fails_closed():
    duplicate_one = {
        "index": 0,
        "frame_path": "main",
        "tag": "input",
        "id": "",
        "name": "",
        "type": "text",
        "role": "",
        "attributes": {
            "type": "text",
            "aria-label": "Shared Label",
        },
        "form_signals": {"has_value": False},
    }

    duplicate_two = dict(
        duplicate_one,
        index=1,
    )

    plan = build_form_runtime_hydration_plan(
        _payload([duplicate_one, duplicate_two])
    )

    assert plan["operation_count"] == 2

    for operation in plan["operations"]:
        assert operation["addressable"] is False
        assert operation["selector"] is None


# ---------------------------------------------------------------------------
# RAW CUSTOMER TEXT ABSENT
# ---------------------------------------------------------------------------

def test_raw_customer_text_absent_from_plan():
    element = _element(
        attributes={
            "id": "field",
            "name": "field",
            "type": "text",
            "value": "Maria Lopez Garcia 12345678Z",
        },
        form_signals={"has_value": True},
    )

    plan = build_form_runtime_hydration_plan(
        _payload([element])
    )

    assert "Maria Lopez Garcia" not in str(plan)
    assert "12345678Z" not in str(plan)


# ---------------------------------------------------------------------------
# PROVIDER NEUTRALITY
# ---------------------------------------------------------------------------

def test_plan_is_provider_neutral():
    element = _element(
        attributes={
            "id": "field",
            "name": "field",
            "type": "text",
        },
        form_signals={"has_value": False},
    )

    plan = build_form_runtime_hydration_plan(
        _payload([element])
    )

    payload_text = str(plan).lower()

    for provider_token in (
        "mercurio",
        "red sara",
        "dehu",
        "icpplus",
    ):
        assert provider_token not in payload_text


# ---------------------------------------------------------------------------
# MAIN FRAME ONLY
# ---------------------------------------------------------------------------

def test_non_main_frame_controls_are_unsupported():
    main_element = _element(
        attributes={
            "id": "field",
            "name": "field",
            "type": "text",
        },
        form_signals={"has_value": False},
        frame_path="main",
        index=0,
    )

    iframe_element = _element(
        id="iframe-field",
        name="iframe-field",
        attributes={
            "id": "iframe-field",
            "name": "iframe-field",
            "type": "text",
        },
        form_signals={"has_value": False},
        frame_path="qcc-frame:1",
        index=1,
    )

    plan = build_form_runtime_hydration_plan(
        _payload([main_element, iframe_element])
    )

    assert plan["operation_count"] == 1
    assert plan["frame_scope"] == "MAIN"
    assert plan["unsupported_frame_control_count"] == 1
    assert (
        plan["unsupported_frame_controls"][0]["status"]
        == "UNSUPPORTED_FRAME"
    )


# ---------------------------------------------------------------------------
# RAW VALUE DOES NOT CREATE BRANCH IDENTITY
# ---------------------------------------------------------------------------

def test_plan_has_no_branch_or_functional_identity_keys():
    element = _element(
        attributes={
            "id": "field",
            "name": "field",
            "type": "text",
        },
        form_signals={"has_value": True},
    )

    plan = build_form_runtime_hydration_plan(
        _payload([element])
    )

    for forbidden_key in (
        "branch_context",
        "functional_state",
        "state_graph",
        "stable_state_fingerprint",
    ):
        assert forbidden_key not in plan
        assert forbidden_key not in plan["operations"][0]


# ---------------------------------------------------------------------------
# SCHEMA SHAPE
# ---------------------------------------------------------------------------

def test_plan_schema_shape():
    plan = build_form_runtime_hydration_plan(
        _payload([])
    )

    assert plan["schema_version"] == 1
    assert (
        plan["record_type"]
        == "QCC_AUTO_TWIN_FORM_RUNTIME_HYDRATION_PLAN"
    )
    assert plan["frame_scope"] == "MAIN"
    assert plan["operation_count"] == 0
    assert plan["operations"] == ()


def test_invalid_payload_fails_closed():
    with pytest.raises(ValueError):
        build_form_runtime_hydration_plan({"not": "valid"})
