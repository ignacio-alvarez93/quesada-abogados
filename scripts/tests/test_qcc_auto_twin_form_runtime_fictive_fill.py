"""Regression: TwinFormRuntimeService auto-fills with fictive data — UWT-8.

Proves the governed hydration runtime now closes the previously-open
gap for ``RUNTIME_POLICY_SUPPLY_SYNTHETIC_VALUE`` controls: when the
caller supplies no explicit ``runtime_values`` override, a required
TEXT/TEXTAREA control is still filled -- deterministically, and with
an unmistakably fictive value -- rather than being silently skipped.

No browser, no network: a minimal fake browser double stands in for
SeleniumBase so this stays a fast, pure-Python regression.
"""

import json

from backend.qcc.auto_twin.fictive_data_projection import (
    project_fictive_text_value,
)
from backend.services.twin_form_runtime_service import (
    TwinFormRuntimeService,
)


class _FakeBrowser:
    def __init__(self):
        self.typed = {}

    def type(self, selector, value):
        self.typed[selector] = value

    def execute_script(self, script):
        return []


def _text_operation(
    *,
    control_key,
    selector,
    form_constraints=None,
):
    return {
        "control_key": control_key,
        "kind": "TEXT",
        "frame_path": "main",
        "addressable": True,
        "selector": selector,
        "selector_confidence": "HIGH",
        "option_value": None,
        "form_state": {
            "schema_version": 1,
            "has_value": True,
            "checked": None,
            "selected_values": (),
            "selected_indexes": (),
            "file_selected": None,
        },
        "form_constraints": form_constraints or {},
        "requires_runtime_value": True,
        "requires_runtime_file": False,
        "runtime_policy": "SUPPLY_SYNTHETIC_VALUE",
    }


def _plan(operations):
    return {
        "schema_version": 1,
        "record_type": "QCC_AUTO_TWIN_FORM_RUNTIME_HYDRATION_PLAN",
        "frame_scope": "MAIN",
        "operation_count": len(operations),
        "operations": tuple(operations),
        "unsupported_frame_control_count": 0,
        "unsupported_frame_controls": (),
    }


def test_required_text_without_override_is_fictively_filled():
    operation = _text_operation(
        control_key="ctrl-required-no-override",
        selector="#full_name",
        form_constraints={"autocomplete": "given-name"},
    )

    plan = _plan([operation])
    browser = _FakeBrowser()

    service = TwinFormRuntimeService()

    result = service.apply_hydration_plan(
        browser=browser,
        plan=plan,
        runtime_values={},
        state_id="STATE_TEST",
    )

    expected_value = project_fictive_text_value(
        control_key="ctrl-required-no-override",
        form_constraints={"autocomplete": "given-name"},
    )

    assert browser.typed["#full_name"] == expected_value
    assert result["operations_applied"] == 1
    assert result["runtime_values_applied"] == 1
    assert result["fictive_values_projected"] == 1
    assert result["errors"] == ()
    assert result["unresolved"] == ()


def test_explicit_override_takes_precedence_over_fictive_projection():
    operation = _text_operation(
        control_key="ctrl-explicit-override",
        selector="#full_name",
    )

    plan = _plan([operation])
    browser = _FakeBrowser()

    service = TwinFormRuntimeService()

    result = service.apply_hydration_plan(
        browser=browser,
        plan=plan,
        runtime_values={
            "ctrl-explicit-override": "Caller Supplied Value",
        },
        state_id="STATE_TEST",
    )

    assert browser.typed["#full_name"] == "Caller Supplied Value"
    assert result["runtime_values_applied"] == 1
    assert result["fictive_values_projected"] == 0


def test_fictive_fill_is_deterministic_across_runs():
    operation = _text_operation(
        control_key="ctrl-deterministic",
        selector="#field",
        form_constraints={"autocomplete": "email"},
    )

    plan = _plan([operation])
    service = TwinFormRuntimeService()

    first_browser = _FakeBrowser()
    service.apply_hydration_plan(
        browser=first_browser,
        plan=plan,
        runtime_values={},
    )

    second_browser = _FakeBrowser()
    service.apply_hydration_plan(
        browser=second_browser,
        plan=plan,
        runtime_values={},
    )

    assert (
        first_browser.typed["#field"]
        == second_browser.typed["#field"]
    )

    assert first_browser.typed["#field"].endswith("@twin.invalid")


def test_fictive_value_never_leaks_into_structured_evidence():
    operation = _text_operation(
        control_key="ctrl-no-leak",
        selector="#field",
    )

    plan = _plan([operation])
    browser = _FakeBrowser()

    service = TwinFormRuntimeService()

    result = service.apply_hydration_plan(
        browser=browser,
        plan=plan,
        runtime_values={},
    )

    serialized_result = json.dumps(result, default=str)

    assert browser.typed["#field"] not in serialized_result
