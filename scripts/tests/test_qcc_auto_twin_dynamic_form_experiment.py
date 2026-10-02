"""Unit tests for UWT-6B2 governed dynamic-form Twin experiments.

Pure/fake-driven coverage of ``TwinDynamicFormExperimentService``. No
real browser, no REAL site, no REAL client data. Capture payloads are
hand-built fixtures in the exact ``capture_dom_payload`` / Site
Architecture DOM_CAPTURE schema so that the real, unchanged
normalization/effect/restoration authorities are exercised end to
end through fakes only at the browser/capture/form-runtime boundary.
"""

from __future__ import annotations

import copy
import json

import pytest

from backend.automation.dom_inspector import (
    DOM_CAPTURE_SCHEMA_VERSION,
)
from backend.qcc.auto_twin.form_runtime_hydration import (
    build_form_runtime_hydration_plan,
)
from backend.services.twin_dynamic_form_experiment_service import (
    ACTION_CHECKBOX,
    ACTION_RADIO,
    ACTION_SELECT,
    TwinDynamicFormExperimentError,
    TwinDynamicFormExperimentService,
)


# ---------------------------------------------------------------------------
# Fixture helpers — raw DOM_CAPTURE payload shape (capture_dom_payload)
# ---------------------------------------------------------------------------

DEFAULT_URL = "http://127.0.0.1:54137/runtime/index.html"
EXTERNAL_URL = "https://mercurio.real.test/expedientes"


def _interaction_signals(**overrides):
    base = {
        "hidden": False,
        "aria_hidden": False,
        "aria_disabled": False,
        "readonly": False,
        "in_viewport": True,
        "opacity": "1",
        "pointer_events": "auto",
    }

    base.update(overrides)

    return base


def _metadata(url):
    from urllib.parse import urlsplit

    parsed = urlsplit(url)

    return {
        "url": url,
        "origin": f"{parsed.scheme}://{parsed.netloc}",
        "pathname": parsed.path,
        "title": "Synthetic Twin",
        "ready_state": "complete",
        "content_type": "text/html",
        "character_set": "UTF-8",
    }


def _payload(elements, *, url=DEFAULT_URL, catalogs=()):
    return {
        "schema_version": DOM_CAPTURE_SCHEMA_VERSION,
        "captured_at": "2026-10-02T10:00:00.000Z",
        "metadata": _metadata(url),
        "viewport": {
            "inner_width": 1280,
            "inner_height": 800,
        },
        "html": "",
        "documents": [],
        "elements": list(elements),
        "frames": [],
        "shadows": [],
        "catalogs": list(catalogs),
        "counts": {},
    }


def _select(*, index, id_, name, options, disabled=False):
    return {
        "index": index,
        "frame_path": "main",
        "tag": "select",
        "id": id_,
        "name": name,
        "type": "",
        "role": "",
        "classes": [],
        "attributes": {"id": id_, "name": name},
        "text": "",
        "visible": True,
        "disabled": disabled,
        "interaction_signals": _interaction_signals(),
        "options": list(options),
    }


def _checkbox(*, index, id_, name, checked, value="yes", required=False):
    attributes = {"id": id_, "name": name, "type": "checkbox", "value": value}

    if required:
        attributes["required"] = ""

    return {
        "index": index,
        "frame_path": "main",
        "tag": "input",
        "id": id_,
        "name": name,
        "type": "checkbox",
        "role": "",
        "classes": [],
        "attributes": attributes,
        "text": "",
        "visible": True,
        "disabled": False,
        "interaction_signals": _interaction_signals(),
        "form_signals": {"checked": checked},
    }


def _radio(*, index, id_, name, value, checked):
    return {
        "index": index,
        "frame_path": "main",
        "tag": "input",
        "id": id_,
        "name": name,
        "type": "radio",
        "role": "",
        "classes": [],
        "attributes": {
            "id": id_,
            "name": name,
            "type": "radio",
            "value": value,
        },
        "text": "",
        "visible": True,
        "disabled": False,
        "interaction_signals": _interaction_signals(),
        "form_signals": {"checked": checked},
    }


def _target_input(*, index, id_, name, disabled, visible=True):
    return {
        "index": index,
        "frame_path": "main",
        "tag": "input",
        "id": id_,
        "name": name,
        "type": "text",
        "role": "",
        "classes": [],
        "attributes": {"id": id_, "name": name, "type": "text"},
        "text": "",
        "visible": visible,
        "disabled": disabled,
        "interaction_signals": _interaction_signals(),
        "form_signals": {"has_value": False},
    }


def _text_input(*, index, id_, name, required=False):
    attributes = {"id": id_, "name": name, "type": "text"}

    if required:
        attributes["required"] = ""

    return {
        "index": index,
        "frame_path": "main",
        "tag": "input",
        "id": id_,
        "name": name,
        "type": "text",
        "role": "",
        "classes": [],
        "attributes": attributes,
        "text": "",
        "visible": True,
        "disabled": False,
        "interaction_signals": _interaction_signals(),
        "form_signals": {"has_value": False},
    }


def _button(*, index, id_):
    return {
        "index": index,
        "frame_path": "main",
        "tag": "button",
        "id": id_,
        "name": "",
        "type": "button",
        "role": "",
        "classes": [],
        "attributes": {"id": id_, "type": "button"},
        "text": "Continue",
        "visible": True,
        "disabled": False,
        "interaction_signals": _interaction_signals(),
    }


def _link(*, index, id_, href="/next"):
    return {
        "index": index,
        "frame_path": "main",
        "tag": "a",
        "id": id_,
        "name": "",
        "type": "",
        "role": "",
        "classes": [],
        "attributes": {"id": id_, "href": href},
        "text": "Next",
        "visible": True,
        "disabled": False,
        "interaction_signals": _interaction_signals(),
    }


class FakeBrowser:
    def __init__(self, *, initial_checked=False):
        self.calls = []
        self._checked_state = initial_checked

    def select_option_by_value(self, selector, value):
        self.calls.append(("select_option_by_value", selector, value))

    def check_if_unchecked(self, selector):
        self.calls.append(("check_if_unchecked", selector))
        self._checked_state = True

    def uncheck_if_checked(self, selector):
        self.calls.append(("uncheck_if_checked", selector))
        self._checked_state = False

    def is_checked(self, selector):
        self.calls.append(("is_checked", selector))
        return self._checked_state

    def click(self, selector):
        self.calls.append(("click", selector))
        self._checked_state = True


class FakeFormRuntimeService:
    def __init__(self):
        self.applied = []

    def apply_hydration_plan(self, *, browser, plan, runtime_values):
        self.applied.append(
            {
                "browser": browser,
                "plan": plan,
                "runtime_values": dict(runtime_values or {}),
            }
        )

        return {"schema_version": 1}


class QueueCaptureProvider:
    """Returns canned payloads in order; records call count/args."""

    def __init__(self, payloads):
        self._queue = list(payloads)
        self.calls = []

    def __call__(self, browser):
        self.calls.append(browser)

        if not self._queue:
            raise AssertionError(
                "QueueCaptureProvider exhausted"
            )

        return self._queue.pop(0)


class RecordingSettleHook:
    def __init__(self):
        self.calls = []

    def __call__(self, browser, phase):
        self.calls.append((browser, phase))


# ---------------------------------------------------------------------------
# Scenario builders
# ---------------------------------------------------------------------------

def _select_scenario(*, url=DEFAULT_URL):
    before_elements = [
        _select(
            index=0,
            id_="province",
            name="province",
            options=[
                {"value": "28", "text": "Madrid", "selected": True},
                {"value": "08", "text": "Barcelona", "selected": False},
            ],
        ),
        _select(
            index=1,
            id_="city",
            name="city",
            options=[
                {"value": "madrid-centro", "text": "Centro", "selected": True},
            ],
        ),
    ]

    after_elements = [
        _select(
            index=0,
            id_="province",
            name="province",
            options=[
                {"value": "28", "text": "Madrid", "selected": False},
                {"value": "08", "text": "Barcelona", "selected": True},
            ],
        ),
        _select(
            index=1,
            id_="city",
            name="city",
            options=[
                {"value": "bcn-eixample", "text": "Eixample", "selected": True},
            ],
        ),
    ]

    before_payload = _payload(before_elements, url=url)
    after_payload = _payload(after_elements, url=url)
    restored_payload = copy.deepcopy(before_payload)

    action = {
        "kind": ACTION_SELECT,
        "selector": "#province",
        "frame_path": "main",
    }

    mutation = {"selected_value": "08"}

    return (
        action,
        mutation,
        before_payload,
        after_payload,
        restored_payload,
    )


def _checkbox_scenario():
    before_elements = [
        _checkbox(index=0, id_="accept", name="accept", checked=False),
        _target_input(
            index=1,
            id_="details",
            name="details",
            disabled=True,
        ),
    ]

    after_elements = [
        _checkbox(index=0, id_="accept", name="accept", checked=True),
        _target_input(
            index=1,
            id_="details",
            name="details",
            disabled=False,
        ),
    ]

    before_payload = _payload(before_elements)
    after_payload = _payload(after_elements)
    restored_payload = copy.deepcopy(before_payload)

    action = {
        "kind": ACTION_CHECKBOX,
        "selector": "#accept",
        "frame_path": "main",
    }

    mutation = {"checked": True}

    return (
        action,
        mutation,
        before_payload,
        after_payload,
        restored_payload,
    )


def _radio_scenario():
    before_elements = [
        _radio(index=0, id_="plan-basic", name="plan", value="basic", checked=True),
        _radio(index=1, id_="plan-pro", name="plan", value="pro", checked=False),
        _target_input(
            index=2,
            id_="pro-options",
            name="pro-options",
            disabled=True,
        ),
    ]

    after_elements = [
        _radio(index=0, id_="plan-basic", name="plan", value="basic", checked=False),
        _radio(index=1, id_="plan-pro", name="plan", value="pro", checked=True),
        _target_input(
            index=2,
            id_="pro-options",
            name="pro-options",
            disabled=False,
        ),
    ]

    before_payload = _payload(before_elements)
    after_payload = _payload(after_elements)
    restored_payload = copy.deepcopy(before_payload)

    action = {
        "kind": ACTION_RADIO,
        "selector": "#plan-pro",
        "frame_path": "main",
    }

    mutation = {"checked": True}

    return (
        action,
        mutation,
        before_payload,
        after_payload,
        restored_payload,
    )


def _run(
    *,
    action,
    mutation,
    before_payload,
    after_payload,
    restored_payload,
    source_catalog_key=None,
    settle_hook=None,
    initial_checked=False,
):
    capture_provider = QueueCaptureProvider(
        [before_payload, after_payload, restored_payload]
    )

    form_runtime_service = FakeFormRuntimeService()

    service = TwinDynamicFormExperimentService(
        capture_provider=capture_provider,
        form_runtime_service=form_runtime_service,
    )

    browser = FakeBrowser(initial_checked=initial_checked)

    result = service.run_experiment(
        browser=browser,
        action=action,
        mutation=mutation,
        source_catalog_key=source_catalog_key,
        settle_hook=settle_hook,
    )

    return result, browser, form_runtime_service, capture_provider


# ---------------------------------------------------------------------------
# 1. External host rejected
# ---------------------------------------------------------------------------

def test_external_host_rejected():
    (
        action,
        mutation,
        before_payload,
        after_payload,
        restored_payload,
    ) = _select_scenario(url=EXTERNAL_URL)

    capture_provider = QueueCaptureProvider(
        [before_payload, after_payload, restored_payload]
    )

    service = TwinDynamicFormExperimentService(
        capture_provider=capture_provider,
        form_runtime_service=FakeFormRuntimeService(),
    )

    with pytest.raises(TwinDynamicFormExperimentError) as excinfo:
        service.run_experiment(
            browser=FakeBrowser(),
            action=action,
            mutation=mutation,
        )

    assert "TWIN_ONLY_GATE_REJECTED_HOST" in str(excinfo.value)
    assert capture_provider.calls.__len__() == 1


# ---------------------------------------------------------------------------
# 2. Loopback ephemeral port accepted (no hardcoded 8767)
# ---------------------------------------------------------------------------

def test_loopback_ephemeral_port_accepted():
    ephemeral_url = "http://127.0.0.1:61234/runtime/index.html"

    (
        action,
        mutation,
        before_payload,
        after_payload,
        restored_payload,
    ) = _select_scenario(url=ephemeral_url)

    result, _browser, _form_runtime, _capture = _run(
        action=action,
        mutation=mutation,
        before_payload=before_payload,
        after_payload=after_payload,
        restored_payload=restored_payload,
    )

    assert result["status"] == "SUCCESS"


# ---------------------------------------------------------------------------
# 3-5. Allowed actions
# ---------------------------------------------------------------------------

def test_select_allowed():
    (
        action,
        mutation,
        before_payload,
        after_payload,
        restored_payload,
    ) = _select_scenario()

    result, browser, form_runtime, _capture = _run(
        action=action,
        mutation=mutation,
        before_payload=before_payload,
        after_payload=after_payload,
        restored_payload=restored_payload,
    )

    assert result["status"] == "SUCCESS"
    assert result["action"]["kind"] == ACTION_SELECT
    assert result["effect_count"] >= 1

    assert (
        "select_option_by_value",
        "#province",
        "08",
    ) in browser.calls

    assert len(form_runtime.applied) == 1


def test_checkbox_allowed():
    (
        action,
        mutation,
        before_payload,
        after_payload,
        restored_payload,
    ) = _checkbox_scenario()

    result, browser, form_runtime, _capture = _run(
        action=action,
        mutation=mutation,
        before_payload=before_payload,
        after_payload=after_payload,
        restored_payload=restored_payload,
        initial_checked=False,
    )

    assert result["status"] == "SUCCESS"
    assert result["action"]["kind"] == ACTION_CHECKBOX
    assert ("check_if_unchecked", "#accept") in browser.calls
    assert len(form_runtime.applied) == 1


def test_radio_checked_true_allowed():
    (
        action,
        mutation,
        before_payload,
        after_payload,
        restored_payload,
    ) = _radio_scenario()

    result, browser, form_runtime, _capture = _run(
        action=action,
        mutation=mutation,
        before_payload=before_payload,
        after_payload=after_payload,
        restored_payload=restored_payload,
        initial_checked=False,
    )

    assert result["status"] == "SUCCESS"
    assert result["action"]["kind"] == ACTION_RADIO
    assert ("click", "#plan-pro") in browser.calls
    assert len(form_runtime.applied) == 1


# ---------------------------------------------------------------------------
# 6-10. Rejected actions/mutations (fail closed before browser interaction)
# ---------------------------------------------------------------------------

def test_radio_checked_false_rejected():
    (
        action,
        _mutation,
        before_payload,
        after_payload,
        restored_payload,
    ) = _radio_scenario()

    capture_provider = QueueCaptureProvider(
        [before_payload, after_payload, restored_payload]
    )

    service = TwinDynamicFormExperimentService(
        capture_provider=capture_provider,
        form_runtime_service=FakeFormRuntimeService(),
    )

    with pytest.raises(TwinDynamicFormExperimentError) as excinfo:
        service.run_experiment(
            browser=FakeBrowser(),
            action=action,
            mutation={"checked": False},
        )

    assert "MUTATION_RADIO_CHECKED_MUST_BE_TRUE" in str(excinfo.value)
    assert capture_provider.calls == []


def test_input_value_rejected():
    capture_provider = QueueCaptureProvider([])

    service = TwinDynamicFormExperimentService(
        capture_provider=capture_provider,
        form_runtime_service=FakeFormRuntimeService(),
    )

    with pytest.raises(TwinDynamicFormExperimentError) as excinfo:
        service.run_experiment(
            browser=FakeBrowser(),
            action={
                "kind": "INPUT_VALUE",
                "selector": "#full_name",
                "frame_path": "main",
            },
            mutation={"value": "Maria"},
        )

    assert "ACTION_KIND_NOT_ALLOWED" in str(excinfo.value)
    assert capture_provider.calls == []


def test_button_rejected():
    capture_provider = QueueCaptureProvider([])

    service = TwinDynamicFormExperimentService(
        capture_provider=capture_provider,
        form_runtime_service=FakeFormRuntimeService(),
    )

    with pytest.raises(TwinDynamicFormExperimentError) as excinfo:
        service.run_experiment(
            browser=FakeBrowser(),
            action={
                "kind": "BUTTON",
                "selector": "#continue_button",
                "frame_path": "main",
            },
            mutation={},
        )

    assert "ACTION_KIND_NOT_ALLOWED" in str(excinfo.value)
    assert capture_provider.calls == []


def test_navigation_action_rejected():
    capture_provider = QueueCaptureProvider([])

    service = TwinDynamicFormExperimentService(
        capture_provider=capture_provider,
        form_runtime_service=FakeFormRuntimeService(),
    )

    with pytest.raises(TwinDynamicFormExperimentError) as excinfo:
        service.run_experiment(
            browser=FakeBrowser(),
            action={
                "kind": "LINK",
                "selector": "#next",
                "frame_path": "main",
            },
            mutation={},
        )

    assert "ACTION_KIND_NOT_ALLOWED" in str(excinfo.value)
    assert capture_provider.calls == []


def test_non_main_frame_rejected():
    capture_provider = QueueCaptureProvider([])

    service = TwinDynamicFormExperimentService(
        capture_provider=capture_provider,
        form_runtime_service=FakeFormRuntimeService(),
    )

    with pytest.raises(TwinDynamicFormExperimentError) as excinfo:
        service.run_experiment(
            browser=FakeBrowser(),
            action={
                "kind": ACTION_SELECT,
                "selector": "#province",
                "frame_path": "1",
            },
            mutation={"selected_value": "08"},
        )

    assert "ACTION_FRAME_NOT_MAIN" in str(excinfo.value)
    assert capture_provider.calls == []


# ---------------------------------------------------------------------------
# 11. Unknown selector rejected
# ---------------------------------------------------------------------------

def test_unknown_selector_rejected():
    (
        _action,
        _mutation,
        before_payload,
        after_payload,
        restored_payload,
    ) = _select_scenario()

    capture_provider = QueueCaptureProvider(
        [before_payload, after_payload, restored_payload]
    )

    service = TwinDynamicFormExperimentService(
        capture_provider=capture_provider,
        form_runtime_service=FakeFormRuntimeService(),
    )

    with pytest.raises(TwinDynamicFormExperimentError) as excinfo:
        service.run_experiment(
            browser=FakeBrowser(),
            action={
                "kind": ACTION_SELECT,
                "selector": "#does-not-exist",
                "frame_path": "main",
            },
            mutation={"selected_value": "08"},
        )

    assert "ACTION_NOT_FOUND_IN_INVENTORY" in str(excinfo.value)
    assert capture_provider.calls.__len__() == 1


# ---------------------------------------------------------------------------
# 12. Ambiguous action rejected (white-box test of our own lookup)
# ---------------------------------------------------------------------------

class _FakeSnapshot:
    def __init__(self, actions):
        self.actions = tuple(actions)


def test_ambiguous_action_rejected():
    service = TwinDynamicFormExperimentService(
        capture_provider=QueueCaptureProvider([]),
        form_runtime_service=FakeFormRuntimeService(),
    )

    duplicated_action = {
        "kind": ACTION_SELECT,
        "selector": "#province",
        "frame_path": "main",
        "policy": "STATE_CHANGE_CANDIDATE",
    }

    snapshot = _FakeSnapshot(
        [dict(duplicated_action), dict(duplicated_action)]
    )

    with pytest.raises(TwinDynamicFormExperimentError) as excinfo:
        service._locate_action(
            snapshot,
            kind=ACTION_SELECT,
            selector="#province",
            frame_path="main",
        )

    assert "ACTION_AMBIGUOUS_IN_INVENTORY" in str(excinfo.value)


# ---------------------------------------------------------------------------
# 13 / 14. Structural projection only / mutation never copied wholesale
# ---------------------------------------------------------------------------

def test_source_action_projected_structurally_only():
    (
        action,
        mutation,
        before_payload,
        after_payload,
        restored_payload,
    ) = _select_scenario()

    result, *_ = _run(
        action=action,
        mutation=mutation,
        before_payload=before_payload,
        after_payload=after_payload,
        restored_payload=restored_payload,
    )

    assert result["action"] == {
        "kind": ACTION_SELECT,
        "selector": "#province",
        "frame_path": "main",
        "policy": "STATE_CHANGE_CANDIDATE",
        "resolved": True,
    }


def test_mutation_not_copied_wholesale_to_result():
    (
        action,
        _mutation,
        before_payload,
        after_payload,
        restored_payload,
    ) = _select_scenario()

    sentinel_value = "SENTINEL_MUTATION_LITERAL_ZZTOP"

    after_payload = copy.deepcopy(after_payload)
    after_payload["elements"][0]["options"] = [
        {"value": "28", "text": "Madrid", "selected": False},
        {"value": "08", "text": "Barcelona", "selected": True},
    ]

    result, *_ = _run(
        action=action,
        mutation={"selected_value": "08"},
        before_payload=before_payload,
        after_payload=after_payload,
        restored_payload=restored_payload,
    )

    serialized = json.dumps(result, default=str)

    assert sentinel_value not in serialized
    assert "mutation" not in result


# ---------------------------------------------------------------------------
# 15. Capture provider called BEFORE/AFTER/RESTORED
# ---------------------------------------------------------------------------

def test_capture_provider_called_before_after_restored():
    (
        action,
        mutation,
        before_payload,
        after_payload,
        restored_payload,
    ) = _checkbox_scenario()

    _result, _browser, _form_runtime, capture_provider = _run(
        action=action,
        mutation=mutation,
        before_payload=before_payload,
        after_payload=after_payload,
        restored_payload=restored_payload,
    )

    assert len(capture_provider.calls) == 3


# ---------------------------------------------------------------------------
# 16. B1 effect model invoked
# ---------------------------------------------------------------------------

def test_dynamic_effect_model_invoked():
    (
        action,
        mutation,
        before_payload,
        after_payload,
        restored_payload,
    ) = _checkbox_scenario()

    result, *_ = _run(
        action=action,
        mutation=mutation,
        before_payload=before_payload,
        after_payload=after_payload,
        restored_payload=restored_payload,
    )

    effect_kinds = {effect["kind"] for effect in result["effects"]}

    assert "CHECKED_CHANGED" in effect_kinds
    assert "DISABLED_CHANGED" in effect_kinds
    assert result["restoration"]["effect_count"] == 0


# ---------------------------------------------------------------------------
# 17. A2 restoration plan used
# ---------------------------------------------------------------------------

def test_form_runtime_restoration_plan_reused():
    (
        action,
        mutation,
        before_payload,
        after_payload,
        restored_payload,
    ) = _checkbox_scenario()

    _result, _browser, form_runtime, _capture = _run(
        action=action,
        mutation=mutation,
        before_payload=before_payload,
        after_payload=after_payload,
        restored_payload=restored_payload,
    )

    assert len(form_runtime.applied) == 1

    expected_plan = build_form_runtime_hydration_plan(
        before_payload
    )

    assert form_runtime.applied[0]["plan"] == expected_plan
    assert form_runtime.applied[0]["runtime_values"] == {}


# ---------------------------------------------------------------------------
# 18. Restoration effect_count must be zero (fail closed otherwise)
# ---------------------------------------------------------------------------

def test_restoration_not_exact_fails_closed():
    (
        action,
        mutation,
        before_payload,
        after_payload,
        _restored_payload,
    ) = _checkbox_scenario()

    broken_restored_payload = copy.deepcopy(before_payload)
    broken_restored_payload["elements"][0]["form_signals"]["checked"] = True

    capture_provider = QueueCaptureProvider(
        [before_payload, after_payload, broken_restored_payload]
    )

    service = TwinDynamicFormExperimentService(
        capture_provider=capture_provider,
        form_runtime_service=FakeFormRuntimeService(),
    )

    with pytest.raises(TwinDynamicFormExperimentError) as excinfo:
        service.run_experiment(
            browser=FakeBrowser(),
            action=action,
            mutation=mutation,
        )

    assert "RESTORATION_FAILED" in str(excinfo.value)


# ---------------------------------------------------------------------------
# 19. Catalog mismatch fails closed (even with zero control-level effects)
# ---------------------------------------------------------------------------

def test_restoration_catalog_mismatch_fails_closed():
    (
        action,
        mutation,
        before_payload,
        after_payload,
        _restored_payload,
    ) = _checkbox_scenario()

    before_payload = copy.deepcopy(before_payload)
    before_payload["catalogs"] = [
        {
            "frame_path": "main",
            "selector": "#extra-catalog",
            "element": {"id": "extra-catalog"},
            "dependency_hints": {"aria-controls": "x"},
        }
    ]

    restored_payload = copy.deepcopy(before_payload)
    restored_payload["catalogs"] = [
        {
            "frame_path": "main",
            "selector": "#extra-catalog",
            "element": {"id": "extra-catalog"},
            "dependency_hints": {"aria-controls": "y"},
        }
    ]

    capture_provider = QueueCaptureProvider(
        [before_payload, after_payload, restored_payload]
    )

    service = TwinDynamicFormExperimentService(
        capture_provider=capture_provider,
        form_runtime_service=FakeFormRuntimeService(),
    )

    with pytest.raises(TwinDynamicFormExperimentError) as excinfo:
        service.run_experiment(
            browser=FakeBrowser(),
            action=action,
            mutation=mutation,
        )

    assert "RESTORATION_FAILED" in str(excinfo.value)


# ---------------------------------------------------------------------------
# 20. Navigation/path change fails closed
# ---------------------------------------------------------------------------

def test_navigation_side_effect_fails_closed():
    (
        action,
        mutation,
        before_payload,
        after_payload,
        restored_payload,
    ) = _checkbox_scenario()

    navigated_after_payload = copy.deepcopy(after_payload)
    navigated_after_payload["metadata"]["url"] = (
        "http://127.0.0.1:54137/runtime/other-page.html"
    )
    navigated_after_payload["metadata"]["pathname"] = (
        "/runtime/other-page.html"
    )

    capture_provider = QueueCaptureProvider(
        [before_payload, navigated_after_payload, restored_payload]
    )

    service = TwinDynamicFormExperimentService(
        capture_provider=capture_provider,
        form_runtime_service=FakeFormRuntimeService(),
    )

    with pytest.raises(TwinDynamicFormExperimentError) as excinfo:
        service.run_experiment(
            browser=FakeBrowser(),
            action=action,
            mutation=mutation,
        )

    assert "NAVIGATION_SIDE_EFFECT_DETECTED" in str(excinfo.value)


# ---------------------------------------------------------------------------
# 21 / 22. Settle hook called after mutation and after restoration
# ---------------------------------------------------------------------------

def test_settle_hook_called_after_mutation_and_restoration():
    (
        action,
        mutation,
        before_payload,
        after_payload,
        restored_payload,
    ) = _select_scenario()

    settle_hook = RecordingSettleHook()

    _result, _browser, _form_runtime, _capture = _run(
        action=action,
        mutation=mutation,
        before_payload=before_payload,
        after_payload=after_payload,
        restored_payload=restored_payload,
        settle_hook=settle_hook,
    )

    phases = [phase for (_browser, phase) in settle_hook.calls]

    assert phases == ["AFTER_MUTATION", "AFTER_RESTORE"]


# ---------------------------------------------------------------------------
# 23. Privacy canaries absent
# ---------------------------------------------------------------------------

def test_privacy_canaries_absent():
    (
        action,
        mutation,
        before_payload,
        after_payload,
        restored_payload,
    ) = _checkbox_scenario()

    canary = "SECRET_PASSWORD_CANARY_7X"

    before_payload = copy.deepcopy(before_payload)
    before_payload["elements"].append(
        _text_input(index=9, id_="csrf_literal", name="csrf_literal")
    )
    before_payload["elements"][-1]["attributes"]["value"] = canary

    restored_payload = copy.deepcopy(restored_payload)
    restored_payload["elements"] = copy.deepcopy(
        before_payload["elements"]
    )

    result, *_ = _run(
        action=action,
        mutation=mutation,
        before_payload=before_payload,
        after_payload=after_payload,
        restored_payload=restored_payload,
    )

    serialized = json.dumps(result, default=str)

    assert canary not in serialized


# ---------------------------------------------------------------------------
# 24. Deterministic result
# ---------------------------------------------------------------------------

def test_result_is_deterministic():
    (
        action,
        mutation,
        before_payload,
        after_payload,
        restored_payload,
    ) = _select_scenario()

    result_a, *_ = _run(
        action=action,
        mutation=mutation,
        before_payload=copy.deepcopy(before_payload),
        after_payload=copy.deepcopy(after_payload),
        restored_payload=copy.deepcopy(restored_payload),
    )

    result_b, *_ = _run(
        action=action,
        mutation=mutation,
        before_payload=copy.deepcopy(before_payload),
        after_payload=copy.deepcopy(after_payload),
        restored_payload=copy.deepcopy(restored_payload),
    )

    assert result_a == result_b


# ---------------------------------------------------------------------------
# 25. No persistence side effect
# ---------------------------------------------------------------------------

def test_no_runtime_values_persisted():
    (
        action,
        mutation,
        before_payload,
        after_payload,
        restored_payload,
    ) = _select_scenario()

    result, _browser, form_runtime, _capture = _run(
        action=action,
        mutation=mutation,
        before_payload=before_payload,
        after_payload=after_payload,
        restored_payload=restored_payload,
    )

    assert result["runtime_values_persisted"] == "NO"
    assert form_runtime.applied[0]["runtime_values"] == {}
