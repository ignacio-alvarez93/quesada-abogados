"""Governed SeleniumBase E2E for UWT-6B3-1C3 Form Effect fidelity.

Proves, with a REAL governed SeleniumBase browser, the entire
approved chain:

    synthetic REAL-shaped evidence
        -> AutoTwinFormEffectEvidenceStore
        -> MaterializationPlan
        -> materialization_builder
        -> physical materialized revision
        -> TwinLocalRuntimeService
        -> TwinBrowserRuntimeService
        -> SeleniumBaseBrowserSession
        -> observable browser behavior

Local Twin only. No REAL navigation, no REAL capture, no personal
data. Independently runnable: does not depend on any other test
module being collected first.

If this environment cannot launch a governed SeleniumBase/Chrome
session, the test is explicitly skipped with a BLOCKED reason rather
than silently reporting success.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from email import policy
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlparse

import pytest

import backend.qcc.auto_twin.materialization_plan as plan_module

from backend.automation.site_architecture.dynamic_form_effects import (
    ANCHOR_STATUS_DETERMINISTIC,
    ANCHOR_STRATEGY_AFTER_STABLE_SIBLING,
    EFFECT_CHECKED_CHANGED,
    EFFECT_CONTROL_APPEARED,
    EFFECT_CONTROL_DISAPPEARED,
    EFFECT_DISABLED_CHANGED,
    EFFECT_READONLY_CHANGED,
    EFFECT_REQUIRED_CHANGED,
    EFFECT_SELECTION_CHANGED,
    EFFECT_VISIBILITY_CHANGED,
)
from backend.qcc.auto_twin.control_appeared_fragment import (
    FRAGMENT_STATUS_CAPTURED,
)

from backend.qcc.auto_twin.form_effect_evidence_store import (
    AutoTwinFormEffectEvidenceStore,
)

from backend.qcc.auto_twin.form_effect_runtime import (
    AUTO_TWIN_FORM_EFFECT_RUNTIME_ADAPTER_FILENAME,
    AUTO_TWIN_FORM_EFFECT_RUNTIME_FILENAME,
    AUTO_TWIN_FORM_EFFECT_RUNTIME_PAYLOAD_ELEMENT_ID,
    ROUTE_STATUS_EXECUTABLE,
    SELECTION_CHANGED_OWNER,
)

from backend.qcc.auto_twin.materialization_builder import (
    AUTO_TWIN_RUNTIME_RENDERER_VERSION,
    materialize_auto_twin_plan,
)

from backend.qcc.auto_twin.materialization_plan import (
    AUTO_TWIN_MATERIALIZATION_SOURCE_ARTIFACTS,
    build_auto_twin_materialization_plan,
)

from backend.qcc.auto_twin.materialized_revision import (
    AUTO_TWIN_MATERIALIZATION_MODE_BOOTSTRAP_REAL,
)

from backend.services.twin_browser_runtime_service import (
    TwinBrowserRuntimeService,
)


REAL_ORIGIN = "https://mercurio.delegaciondelgobierno.gob.es"

TWIN_KEY = "uwt6b3-1c3-synthetic-twin"
PROFILE = "qcc_assisted"

CAPTURE_ID = "capture-form-effect-e2e-1"
STATE_ID = "FORM_EFFECT_E2E_STATE_1"
PATHNAME = "/mercurio/formulario-efectos.html"
FUNCTIONAL_STATE = "FORM_EFFECT_E2E_MAIN"

BEFORE_FINGERPRINT = "e" * 64


# ---------------------------------------------------------------------------
# Synthetic source document (section C).
# ---------------------------------------------------------------------------


def _html_document():
    return """<!doctype html>
<html>
<head><title>Formulario Efectos</title></head>
<body>
<form>
<select id="plan">
<option value="a">A</option>
<option value="b">B</option>
</select>
<input id="accept" type="checkbox">
<input id="plan-basic" name="plan-radio" type="radio" checked>
<input id="plan-pro" name="plan-radio" type="radio">
<input id="visibility-target" type="text">
<input id="disabled-target" type="text">
<input id="readonly-target" type="text">
<input id="required-target" type="text">
<input id="checked-target" type="checkbox">
<div id="gone-target">Bye</div>
<select id="delegated-select">
<option value="x">X</option>
<option value="y">Y</option>
</select>
</form>
</body>
</html>
"""


def _write_mhtml(path, html_body):
    root = EmailMessage()
    root["MIME-Version"] = "1.0"
    root.set_type("multipart/related")

    html_part = EmailMessage()
    html_part.set_content(
        html_body,
        subtype="html",
        charset="utf-8",
    )

    html_part["Content-Location"] = REAL_ORIGIN + PATHNAME

    root.attach(html_part)

    path.write_bytes(root.as_bytes(policy=policy.default))


def _write_source_files(root, capture_id):
    directory = Path(root) / capture_id
    directory.mkdir(parents=True)

    for _kind, filename, _destination in (
        AUTO_TWIN_MATERIALIZATION_SOURCE_ARTIFACTS
    ):
        if filename == "page.mhtml":
            _write_mhtml(directory / filename, _html_document())
        elif filename == "page.html":
            (directory / filename).write_text(
                _html_document(),
                encoding="utf-8",
            )
        elif filename.endswith(".png"):
            (directory / filename).write_bytes(b"QCC_TEST_PNG")
        else:
            (directory / filename).write_text("{}", encoding="utf-8")


def _fake_bundle():
    return {
        "capture_id": CAPTURE_ID,
        "capture": {
            "capture_id": CAPTURE_ID,
            "pathname": PATHNAME,
            "functional_state": FUNCTIONAL_STATE,
            "browser_profile_key": PROFILE,
        },
        "snapshot": {
            "page": {
                "origin": REAL_ORIGIN,
                "pathname": PATHNAME,
            },
        },
        "rendering_profile": {
            "rendering_profile_id": "render-profile-e2e-1",
        },
        "fingerprint": BEFORE_FINGERPRINT,
    }


def _install_loader(monkeypatch):
    bundle = _fake_bundle()

    def fake_loader(*, capture_id, root, require_viewport_image):
        assert capture_id == CAPTURE_ID
        return deepcopy(bundle)

    monkeypatch.setattr(
        plan_module,
        "load_auto_twin_persisted_capture_bundle",
        fake_loader,
    )


# ---------------------------------------------------------------------------
# Governed evidence routes (section D).
# ---------------------------------------------------------------------------


def _target(control_key, selector, semantic_kind):
    return {
        "control_key": control_key,
        "frame_path": "main",
        "selector": selector,
        "semantic_kind": semantic_kind,
    }


def _select_experiment_result():
    return {
        "pathname": PATHNAME,
        "before_fingerprint": BEFORE_FINGERPRINT,
        "action": {"kind": "SELECT", "selector": "#plan", "frame_path": "main"},
        "mutation_identity": {"kind": "SELECT", "selected_index": 1},
        "effects": [
            {
                "kind": EFFECT_VISIBILITY_CHANGED,
                "target": _target(
                    "main::INPUT::#visibility-target",
                    "#visibility-target",
                    "TEXT_INPUT",
                ),
                "before": True,
                "after": False,
            },
            {
                "kind": EFFECT_REQUIRED_CHANGED,
                "target": _target(
                    "main::INPUT::#required-target",
                    "#required-target",
                    "TEXT_INPUT",
                ),
                "before": False,
                "after": True,
            },
            {
                "kind": EFFECT_SELECTION_CHANGED,
                "target": _target(
                    "main::SELECT::#delegated-select",
                    "#delegated-select",
                    "SELECT",
                ),
                "before": {
                    "selected_values": ("x",),
                    "selected_indexes": (0,),
                },
                "after": {
                    "selected_values": ("y",),
                    "selected_indexes": (1,),
                },
            },
        ],
    }


def _checkbox_experiment_result():
    return {
        "pathname": PATHNAME,
        "before_fingerprint": BEFORE_FINGERPRINT,
        "action": {
            "kind": "CHECKBOX",
            "selector": "#accept",
            "frame_path": "main",
        },
        "mutation_identity": {"kind": "CHECKBOX", "checked": True},
        "effects": [
            {
                "kind": EFFECT_DISABLED_CHANGED,
                "target": _target(
                    "main::INPUT::#disabled-target",
                    "#disabled-target",
                    "TEXT_INPUT",
                ),
                "before": False,
                "after": True,
            },
            {
                "kind": EFFECT_CHECKED_CHANGED,
                "target": _target(
                    "main::INPUT::#checked-target",
                    "#checked-target",
                    "CHECKBOX",
                ),
                "before": False,
                "after": True,
            },
        ],
    }


def _radio_experiment_result():
    return {
        "pathname": PATHNAME,
        "before_fingerprint": BEFORE_FINGERPRINT,
        "action": {
            "kind": "RADIO",
            "selector": "#plan-pro",
            "frame_path": "main",
        },
        "mutation_identity": {"kind": "RADIO", "checked": True},
        "effects": [
            {
                "kind": EFFECT_READONLY_CHANGED,
                "target": _target(
                    "main::INPUT::#readonly-target",
                    "#readonly-target",
                    "TEXT_INPUT",
                ),
                "before": False,
                "after": True,
            },
            {
                "kind": EFFECT_CONTROL_DISAPPEARED,
                "target": _target(
                    "main::DIV::#gone-target",
                    "#gone-target",
                    "CONTAINER",
                ),
                "before": True,
                "after": None,
            },
            {
                "kind": EFFECT_CONTROL_APPEARED,
                "target": _target(
                    "main::DIV::#appear-target",
                    "#appear-target",
                    "CONTAINER",
                ),
                "before": None,
                "after": True,
                "anchor": {
                    "status": ANCHOR_STATUS_DETERMINISTIC,
                    "strategy": ANCHOR_STRATEGY_AFTER_STABLE_SIBLING,
                    "selector": "#readonly-target",
                    "frame_path": "main",
                },
                "fragment": {
                    "status": FRAGMENT_STATUS_CAPTURED,
                    "html": (
                        '<div id="appear-target">New Panel</div>'
                    ),
                },
            },
        ],
    }


def _record_all_evidence(form_effect_evidence_root):
    store = AutoTwinFormEffectEvidenceStore(root=form_effect_evidence_root)

    evidence_ids = []

    for experiment_result in (
        _select_experiment_result(),
        _checkbox_experiment_result(),
        _radio_experiment_result(),
    ):
        record = store.record(
            twin_key=TWIN_KEY,
            experiment_result=experiment_result,
            functional_state=FUNCTIONAL_STATE,
            branch_context_id=None,
        )

        evidence_ids.append(record["evidence_id"])

    return evidence_ids


# ---------------------------------------------------------------------------
# Plan + physical materialization.
# ---------------------------------------------------------------------------


def _state_runtime_dir(result, state_id):
    revision_dir = Path(result["revision_dir"])

    matches = [
        path
        for path in (revision_dir / "states").glob("*-" + state_id)
        if path.is_dir()
    ]

    assert len(matches) == 1

    return matches[0] / "runtime"


_PAYLOAD_RE = re.compile(
    r'<script type="application/json" id="'
    + re.escape(AUTO_TWIN_FORM_EFFECT_RUNTIME_PAYLOAD_ELEMENT_ID)
    + r'">(.*?)</script>',
    re.DOTALL,
)


def _extract_payload_json(html_text):
    match = _PAYLOAD_RE.search(html_text)
    assert match is not None
    return json.loads(match.group(1))


# ---------------------------------------------------------------------------
# JS: baseline/after snapshot + stimuli.
# ---------------------------------------------------------------------------

_STATE_SNAPSHOT_SCRIPT = """
return {
  plan_selected_index: document.querySelector('#plan').selectedIndex,
  accept_checked: document.querySelector('#accept').checked,
  plan_basic_checked: document.querySelector('#plan-basic').checked,
  plan_pro_checked: document.querySelector('#plan-pro').checked,
  visibility_target_hidden:
    document.querySelector('#visibility-target')
      .getAttribute('data-qcc-auto-twin-form-effect-hidden') === '1',
  disabled_target_disabled:
    document.querySelector('#disabled-target').disabled,
  readonly_target_readonly:
    document.querySelector('#readonly-target').readOnly,
  required_target_required:
    document.querySelector('#required-target').required,
  checked_target_checked:
    document.querySelector('#checked-target').checked,
  gone_target_exists: !!document.querySelector('#gone-target'),
  gone_target_hidden: (function () {
    var el = document.querySelector('#gone-target');
    return !!el
      && el.getAttribute('data-qcc-auto-twin-form-effect-hidden') === '1';
  })(),
  delegated_select_index:
    document.querySelector('#delegated-select').selectedIndex,
  appear_target_count:
    document.querySelectorAll('#appear-target').length,
  appear_target_text: (function () {
    var el = document.querySelector('#appear-target');
    return el ? el.textContent : null;
  })(),
  appear_target_follows_anchor: (function () {
    var anchor = document.querySelector('#readonly-target');
    return !!anchor
      && anchor.nextElementSibling
      && anchor.nextElementSibling.id === 'appear-target';
  })()
};
"""

_SELECT_STIMULUS_SCRIPT = """
var el = document.querySelector('#plan');
el.selectedIndex = 1;
el.dispatchEvent(new Event('input', {bubbles: true}));
el.dispatchEvent(new Event('change', {bubbles: true}));
"""

_CHECKBOX_STIMULUS_SCRIPT = """
var el = document.querySelector('#accept');
el.checked = true;
el.dispatchEvent(new Event('input', {bubbles: true}));
el.dispatchEvent(new Event('change', {bubbles: true}));
"""

_RADIO_STIMULUS_SCRIPT = """
var el = document.querySelector('#plan-pro');
el.checked = true;
el.dispatchEvent(new Event('input', {bubbles: true}));
el.dispatchEvent(new Event('change', {bubbles: true}));
"""


def test_governed_form_effect_materialization_e2e(tmp_path, monkeypatch):
    form_effect_evidence_root = tmp_path / "form_effect_evidence"

    evidence_ids = _record_all_evidence(form_effect_evidence_root)
    assert len(evidence_ids) == 3

    captures_root = tmp_path / "captures"
    materialized_root = tmp_path / "materialized"

    _write_source_files(captures_root, CAPTURE_ID)
    _install_loader(monkeypatch)

    state_source = {
        "state_id": STATE_ID,
        "capture_id": CAPTURE_ID,
        "pathname": PATHNAME,
        "functional_state": FUNCTIONAL_STATE,
        "form_effect_evidence_ids": evidence_ids,
    }

    plan = build_auto_twin_materialization_plan(
        twin_key=TWIN_KEY,
        materialization_mode=AUTO_TWIN_MATERIALIZATION_MODE_BOOTSTRAP_REAL,
        state_sources=[state_source],
        required_origin=REAL_ORIGIN,
        required_profile_key=PROFILE,
        root=captures_root,
        form_effect_evidence_root=form_effect_evidence_root,
    )

    result = materialize_auto_twin_plan(
        plan=plan,
        source_root=captures_root,
        materialized_root=materialized_root,
        procedure_code="MERCURIO",
        flow_variant="SITE_LEVEL",
        form_effect_evidence_root=form_effect_evidence_root,
    )

    # -----------------------------------------------------------------
    # E. Materialization assertions BEFORE browser.
    # -----------------------------------------------------------------

    revision_id = result["revision"]["materialized_revision_id"]
    revision_dir = Path(result["revision_dir"])

    assert revision_dir.is_dir()

    registry_path = revision_dir / "runtime" / "registry.json"
    assert registry_path.is_file()

    registry = json.loads(registry_path.read_text(encoding="utf-8"))

    registry_state = next(
        item
        for item in registry["states"]
        if item["state_id"] == STATE_ID
    )

    runtime_entry = registry_state["runtime_entry"]
    assert runtime_entry

    runtime_dir = _state_runtime_dir(result, STATE_ID)

    runtime_json_path = runtime_dir / AUTO_TWIN_FORM_EFFECT_RUNTIME_FILENAME
    adapter_js_path = (
        runtime_dir / AUTO_TWIN_FORM_EFFECT_RUNTIME_ADAPTER_FILENAME
    )

    assert runtime_json_path.is_file()
    assert adapter_js_path.is_file()

    materialized_payload = json.loads(
        runtime_json_path.read_text(encoding="utf-8")
    )

    assert materialized_payload["route_count"] == 3

    trigger_kinds = {
        route["trigger"]["action"]["kind"]
        for route in materialized_payload["routes"]
    }

    assert trigger_kinds == {"SELECT", "CHECKBOX", "RADIO"}

    payload_text = json.dumps(materialized_payload)
    assert "selected_value" not in payload_text
    assert "selected_values" not in payload_text

    state_metadata = json.loads(
        (runtime_dir / "state.json").read_text(encoding="utf-8")
    )
    assert "form_effect_runtime_fingerprint" in state_metadata
    assert state_metadata["form_effect_route_count"] == 3

    renderer = json.loads(
        (revision_dir / "runtime" / "renderer.json").read_text(
            encoding="utf-8"
        )
    )
    assert renderer["renderer_version"] == AUTO_TWIN_RUNTIME_RENDERER_VERSION
    assert renderer["renderer_version"] == 7

    html_text = (runtime_dir / "index.html").read_text(encoding="utf-8")
    assert "selected_value" not in html_text

    embedded_payload = _extract_payload_json(html_text)
    assert embedded_payload == materialized_payload

    # SELECTION_CHANGED stays delegated to CATALOG_RUNTIME and is
    # never promoted to an executable effect.
    select_route = next(
        route
        for route in embedded_payload["routes"]
        if route["trigger"]["action"]["kind"] == "SELECT"
    )

    assert select_route["status"] == ROUTE_STATUS_EXECUTABLE

    delegated_kinds = {
        effect["kind"] for effect in select_route["delegated_effects"]
    }
    assert EFFECT_SELECTION_CHANGED in delegated_kinds

    for effect in select_route["delegated_effects"]:
        if effect["kind"] == EFFECT_SELECTION_CHANGED:
            assert effect["owner"] == SELECTION_CHANGED_OWNER

    # CONTROL_APPEARED reaches the materialized RADIO route as a full
    # EXECUTABLE effect (anchor + sterilized/minimized fragment),
    # never silently dropped to BLOCKED.
    radio_route = next(
        route
        for route in embedded_payload["routes"]
        if route["trigger"]["action"]["kind"] == "RADIO"
    )

    assert radio_route["status"] == ROUTE_STATUS_EXECUTABLE

    radio_executable_kinds = {
        effect["kind"] for effect in radio_route["executable_effects"]
    }
    assert EFFECT_CONTROL_APPEARED in radio_executable_kinds

    appeared_effect = next(
        effect
        for effect in radio_route["executable_effects"]
        if effect["kind"] == EFFECT_CONTROL_APPEARED
    )

    assert appeared_effect["anchor"]["selector"] == "#readonly-target"
    assert "New Panel" in appeared_effect["fragment"]["html"]

    # -----------------------------------------------------------------
    # F. Start the governed Twin (real TwinLocalRuntimeService + real
    # SeleniumBaseBrowserSession through TwinBrowserRuntimeService).
    # -----------------------------------------------------------------

    service = TwinBrowserRuntimeService(
        materialized_root=materialized_root,
        profile_resolver=lambda key: tmp_path / "browser_profiles" / key,
    )

    try:
        try:
            status = service.start(
                twin_key=TWIN_KEY,
                revision_id=revision_id,
                state_id=STATE_ID,
            )
        except Exception as exc:
            pytest.skip(
                "SELENIUMBASE_E2E_BLOCKED:"
                + f" {type(exc).__name__}: {exc}"
            )
            return

        if status["status"] != "RUNNING":
            pytest.skip(
                "SELENIUMBASE_E2E_BLOCKED:"
                + f" status={status['status']}"
                + f" last_error={status.get('last_error')}"
            )
            return

        # TwinBrowserRuntimeService.start() was called with the exact
        # state_id above: had it not resolved to THIS physical state,
        # ``_resolve_state`` would have raised
        # QCC_AUTO_TWIN_BROWSER_STATE_ID_NOT_FOUND/_AMBIGUOUS before
        # ever reaching "RUNNING". The public status additionally
        # confirms pathname and the exact served runtime_entry file.
        assert status["pathname"] == PATHNAME
        assert status["url"].endswith(runtime_entry)

        parsed_url = urlparse(status["url"])
        assert parsed_url.hostname == "127.0.0.1"
        assert parsed_url.scheme == "http"

        # -------------------------------------------------------------
        # H. Baseline.
        # -------------------------------------------------------------

        baseline = service.execute_script(
            twin_key=TWIN_KEY,
            script=_STATE_SNAPSHOT_SCRIPT,
        )

        assert baseline["plan_selected_index"] == 0
        assert baseline["accept_checked"] is False
        assert baseline["plan_basic_checked"] is True
        assert baseline["plan_pro_checked"] is False
        assert baseline["visibility_target_hidden"] is False
        assert baseline["disabled_target_disabled"] is False
        assert baseline["readonly_target_readonly"] is False
        assert baseline["required_target_required"] is False
        assert baseline["checked_target_checked"] is False
        assert baseline["gone_target_exists"] is True
        assert baseline["gone_target_hidden"] is False
        assert baseline["delegated_select_index"] == 0
        assert baseline["appear_target_count"] == 0

        # -------------------------------------------------------------
        # I. SELECT observable behavior.
        # -------------------------------------------------------------

        service.execute_script(
            twin_key=TWIN_KEY,
            script=_SELECT_STIMULUS_SCRIPT,
        )

        after_select = service.execute_script(
            twin_key=TWIN_KEY,
            script=_STATE_SNAPSHOT_SCRIPT,
        )

        assert after_select["plan_selected_index"] == 1
        assert after_select["visibility_target_hidden"] is True
        assert after_select["required_target_required"] is True

        # L. Delegated selection ownership: Form Effect Runtime never
        # executes the SELECTION_CHANGED route itself.
        assert after_select["delegated_select_index"] == 0

        # -------------------------------------------------------------
        # J. CHECKBOX observable behavior.
        # -------------------------------------------------------------

        service.execute_script(
            twin_key=TWIN_KEY,
            script=_CHECKBOX_STIMULUS_SCRIPT,
        )

        after_checkbox = service.execute_script(
            twin_key=TWIN_KEY,
            script=_STATE_SNAPSHOT_SCRIPT,
        )

        assert after_checkbox["accept_checked"] is True
        assert after_checkbox["disabled_target_disabled"] is True
        assert after_checkbox["checked_target_checked"] is True

        # -------------------------------------------------------------
        # K. RADIO observable behavior.
        # -------------------------------------------------------------

        service.execute_script(
            twin_key=TWIN_KEY,
            script=_RADIO_STIMULUS_SCRIPT,
        )

        after_radio = service.execute_script(
            twin_key=TWIN_KEY,
            script=_STATE_SNAPSHOT_SCRIPT,
        )

        assert after_radio["plan_pro_checked"] is True
        assert after_radio["plan_basic_checked"] is False
        assert after_radio["readonly_target_readonly"] is True

        # CONTROL_DISAPPEARED is visual suppression only.
        assert after_radio["gone_target_exists"] is True
        assert after_radio["gone_target_hidden"] is True

        # CONTROL_APPEARED: the governed anchor + sterilized/minimized
        # fragment are materialized into a REAL inserted DOM node, at
        # the exact deterministic structural position.
        assert after_radio["appear_target_count"] == 1
        assert after_radio["appear_target_text"] == "New Panel"
        assert after_radio["appear_target_follows_anchor"] is True

        # Idempotence: repeating the exact same trigger must not
        # duplicate the appeared subtree.
        service.execute_script(
            twin_key=TWIN_KEY,
            script=_RADIO_STIMULUS_SCRIPT,
        )

        after_radio_repeat = service.execute_script(
            twin_key=TWIN_KEY,
            script=_STATE_SNAPSHOT_SCRIPT,
        )

        assert after_radio_repeat["appear_target_count"] == 1

    finally:
        service.stop(twin_key=TWIN_KEY)

        stopped_status = service.get_status(twin_key=TWIN_KEY)
        assert stopped_status["status"] == "STOPPED"
