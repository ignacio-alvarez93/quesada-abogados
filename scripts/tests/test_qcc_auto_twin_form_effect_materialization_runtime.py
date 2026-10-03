"""Integration tests for UWT-6B3-1C2 Form Effect Materialization Runtime.

Covers the physical wiring between:

    MaterializationPlan
        -> persisted governed Form Effect Evidence
        -> canonical B3-1B runtime payload
        -> materialized runtime artifacts
        -> local Twin HTML adapter

No browser fidelity assertion here (owned by UWT-6B3-1C3).
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from email import policy
from email.message import EmailMessage
from pathlib import Path

import pytest

import backend.qcc.auto_twin.materialization_plan as plan_module

from backend.automation.site_architecture.dynamic_form_effects import (
    EFFECT_CHECKED_CHANGED,
    EFFECT_CONTROL_DISAPPEARED,
    EFFECT_DISABLED_CHANGED,
    EFFECT_READONLY_CHANGED,
    EFFECT_REQUIRED_CHANGED,
    EFFECT_SELECTION_CHANGED,
    EFFECT_VISIBILITY_CHANGED,
)

from backend.qcc.auto_twin.form_effect_evidence_store import (
    AutoTwinFormEffectEvidenceStore,
)

from backend.qcc.auto_twin.form_effect_runtime import (
    AUTO_TWIN_FORM_EFFECT_RUNTIME_ADAPTER_FILENAME,
    AUTO_TWIN_FORM_EFFECT_RUNTIME_ADAPTER_VERSION,
    AUTO_TWIN_FORM_EFFECT_RUNTIME_FILENAME,
    AUTO_TWIN_FORM_EFFECT_RUNTIME_PAYLOAD_ELEMENT_ID,
    AUTO_TWIN_FORM_EFFECT_RUNTIME_SCRIPT_MARKER,
    ROUTE_STATUS_EXECUTABLE,
    SELECTION_CHANGED_OWNER,
    bind_form_effect_runtime_payload,
    form_effect_runtime_adapter_source,
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


REAL_ORIGIN = "https://mercurio.delegaciondelgobierno.gob.es"

TWIN_KEY = "mercurio-form-runtime"
PROFILE = "qcc_assisted"

CAPTURE_ID = "capture-form-runtime-1"
STATE_ID = "FORM_RUNTIME_STATE_1"
PATHNAME = "/mercurio/formulario.html"
FUNCTIONAL_STATE = "FORM_MAIN"

CAPTURE_ID_NO_REF = "capture-form-runtime-2"
STATE_ID_NO_REF = "FORM_RUNTIME_STATE_2"
PATHNAME_NO_REF = "/mercurio/otra-pagina.html"

BEFORE_FINGERPRINT = "a" * 64


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _html_document():
    return """<!doctype html>
<html>
<head><title>Formulario</title></head>
<body>
<form>
<select id="plan">
<option value="a">A</option>
<option value="b">B</option>
</select>
<input id="visibility-target" type="text">
<input id="disabled-target" type="text">
<input id="readonly-target" type="text">
<input id="required-target" type="text">
<input id="checked-target" type="checkbox">
<div id="gone-target">Bye</div>
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

    html_part["Content-Location"] = (
        REAL_ORIGIN + PATHNAME
    )

    root.attach(html_part)

    path.write_bytes(
        root.as_bytes(policy=policy.default)
    )


def _write_source_files(root, capture_id):
    directory = Path(root) / capture_id
    directory.mkdir(parents=True)

    for _kind, filename, _destination in (
        AUTO_TWIN_MATERIALIZATION_SOURCE_ARTIFACTS
    ):
        if filename == "page.mhtml":
            _write_mhtml(
                directory / filename,
                _html_document(),
            )
        elif filename == "page.html":
            (directory / filename).write_text(
                _html_document(),
                encoding="utf-8",
            )
        elif filename.endswith(".png"):
            (directory / filename).write_bytes(b"QCC_TEST_PNG")
        else:
            (directory / filename).write_text(
                "{}",
                encoding="utf-8",
            )


def _fake_bundle(*, capture_id, pathname, functional_state):
    return {
        "capture_id": capture_id,
        "capture": {
            "capture_id": capture_id,
            "pathname": pathname,
            "functional_state": functional_state,
            "browser_profile_key": PROFILE,
        },
        "snapshot": {
            "page": {
                "origin": REAL_ORIGIN,
                "pathname": pathname,
            },
        },
        "rendering_profile": {
            "rendering_profile_id": "render-profile-1",
        },
        "fingerprint": BEFORE_FINGERPRINT,
    }


def _install_loader(monkeypatch, bundles):
    def fake_loader(*, capture_id, root, require_viewport_image):
        return deepcopy(bundles[capture_id])

    monkeypatch.setattr(
        plan_module,
        "load_auto_twin_persisted_capture_bundle",
        fake_loader,
    )


def _target(control_key, selector, semantic_kind):
    return {
        "control_key": control_key,
        "frame_path": "main",
        "selector": selector,
        "semantic_kind": semantic_kind,
    }


def _select_action():
    return {"kind": "SELECT", "selector": "#plan", "frame_path": "main"}


def _effects():
    return [
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
            "kind": EFFECT_CHECKED_CHANGED,
            "target": _target(
                "main::INPUT::#checked-target",
                "#checked-target",
                "CHECKBOX",
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
            "kind": EFFECT_SELECTION_CHANGED,
            "target": _target(
                "main::SELECT::#plan",
                "#plan",
                "SELECT",
            ),
            "before": {
                "selected_values": ("a",),
                "selected_indexes": (0,),
            },
            "after": {
                "selected_values": ("b",),
                "selected_indexes": (1,),
            },
        },
    ]


def _experiment_result(*, pathname=PATHNAME, before_fingerprint=BEFORE_FINGERPRINT):
    return {
        "pathname": pathname,
        "before_fingerprint": before_fingerprint,
        "action": _select_action(),
        "mutation_identity": {"kind": "SELECT", "selected_index": 1},
        "effects": _effects(),
    }


def _record_evidence(
    *,
    form_effect_evidence_root,
    functional_state=FUNCTIONAL_STATE,
    branch_context_id=None,
    **overrides,
):
    store = AutoTwinFormEffectEvidenceStore(root=form_effect_evidence_root)

    record = store.record(
        twin_key=TWIN_KEY,
        experiment_result=_experiment_result(**overrides),
        functional_state=functional_state,
        branch_context_id=branch_context_id,
    )

    return record, store


def _state_source(**overrides):
    base = {
        "state_id": STATE_ID,
        "capture_id": CAPTURE_ID,
        "pathname": PATHNAME,
        "functional_state": FUNCTIONAL_STATE,
    }

    base.update(overrides)

    return base


def _build_plan_and_materialize(
    tmp_path,
    monkeypatch,
    *,
    state_sources,
    form_effect_evidence_root,
):
    captures_root = tmp_path / "captures"
    materialized_root = tmp_path / "materialized"

    for source in state_sources:
        _write_source_files(captures_root, source["capture_id"])

    bundles = {
        source["capture_id"]: _fake_bundle(
            capture_id=source["capture_id"],
            pathname=source["pathname"],
            functional_state=source["functional_state"],
        )
        for source in state_sources
    }

    _install_loader(monkeypatch, bundles)

    plan = build_auto_twin_materialization_plan(
        twin_key=TWIN_KEY,
        materialization_mode=AUTO_TWIN_MATERIALIZATION_MODE_BOOTSTRAP_REAL,
        state_sources=state_sources,
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

    return plan, result


def _state_runtime_dir(result, state_id):
    revision_dir = Path(result["revision_dir"])

    matches = [
        path
        for path in (revision_dir / "states").glob("*-" + state_id)
        if path.is_dir()
    ]

    assert len(matches) == 1

    return matches[0] / "runtime"


_PAYLOAD_RE_TEMPLATE = (
    r'<script type="application/json" id="{}">(.*?)</script>'
)


def _extract_payload_json(html_text):
    pattern = re.compile(
        _PAYLOAD_RE_TEMPLATE.format(
            re.escape(AUTO_TWIN_FORM_EFFECT_RUNTIME_PAYLOAD_ELEMENT_ID)
        ),
        re.DOTALL,
    )

    match = pattern.search(html_text)

    assert match is not None

    return json.loads(match.group(1))


# ---------------------------------------------------------------------------
# Happy path: fresh REAL_CAPTURE state with one evidence record.
# ---------------------------------------------------------------------------


def test_happy_path_materializes_form_effect_runtime(tmp_path, monkeypatch):
    form_effect_evidence_root = tmp_path / "form_effect_evidence"

    record, _store = _record_evidence(
        form_effect_evidence_root=form_effect_evidence_root,
    )

    evidence_id = record["evidence_id"]

    plan, result = _build_plan_and_materialize(
        tmp_path,
        monkeypatch,
        state_sources=[
            _state_source(form_effect_evidence_ids=[evidence_id]),
        ],
        form_effect_evidence_root=form_effect_evidence_root,
    )

    plan_state = plan["state_manifest"][0]

    runtime_dir = _state_runtime_dir(result, STATE_ID)

    # 1 + 5. Physical artifacts exist.
    runtime_json_path = runtime_dir / AUTO_TWIN_FORM_EFFECT_RUNTIME_FILENAME
    adapter_js_path = (
        runtime_dir / AUTO_TWIN_FORM_EFFECT_RUNTIME_ADAPTER_FILENAME
    )

    assert runtime_json_path.is_file()
    assert adapter_js_path.is_file()

    materialized_payload = json.loads(
        runtime_json_path.read_text(encoding="utf-8")
    )

    # 2. Exact canonical payload equals bind_form_effect_runtime_payload.
    expected_payload = bind_form_effect_runtime_payload(
        state_id=STATE_ID,
        normalized_records=[
            {
                "action": record["action"],
                "mutation_identity": record["mutation_identity"],
                "effects": record["effects"],
            }
        ],
    )

    assert materialized_payload == json.loads(json.dumps(expected_payload))

    # 3. Fingerprint equals plan fingerprint.
    from backend.qcc.auto_twin.materialization_builder import (
        _canonical_bytes,
        _sha256_bytes,
    )

    actual_fingerprint = _sha256_bytes(
        _canonical_bytes(materialized_payload)
    )

    assert actual_fingerprint == plan_state["form_effect_runtime_fingerprint"]

    # 4. Route count equals plan route count.
    assert (
        materialized_payload["route_count"]
        == plan_state["form_effect_route_count"]
        == 1
    )

    # 6. Adapter JS content equals form_effect_runtime_adapter_source().
    assert (
        adapter_js_path.read_text(encoding="utf-8")
        == form_effect_runtime_adapter_source()
    )

    html_text = (runtime_dir / "index.html").read_text(encoding="utf-8")

    # 7 + 8. Payload element and adapter script marker appear exactly once.
    assert html_text.count(
        'id="' + AUTO_TWIN_FORM_EFFECT_RUNTIME_PAYLOAD_ELEMENT_ID + '"'
    ) == 1

    assert html_text.count(
        AUTO_TWIN_FORM_EFFECT_RUNTIME_SCRIPT_MARKER + '="'
    ) == 1

    assert (
        'src="' + AUTO_TWIN_FORM_EFFECT_RUNTIME_ADAPTER_FILENAME + '"'
    ) in html_text

    # 9. Payload is parseable from HTML and matches materialized payload.
    embedded_payload = _extract_payload_json(html_text)
    assert embedded_payload == materialized_payload

    route = embedded_payload["routes"][0]

    # 10. SELECT trigger uses selected_index, never selected_value.
    assert route["trigger"]["mutation_identity"] == {
        "kind": "SELECT",
        "selected_index": 1,
    }

    assert "selected_value" not in html_text

    # 11. SELECTION_CHANGED remains delegated to CATALOG_RUNTIME.
    assert route["status"] == ROUTE_STATUS_EXECUTABLE

    delegated_kinds = {
        effect["kind"] for effect in route["delegated_effects"]
    }

    assert EFFECT_SELECTION_CHANGED in delegated_kinds

    for effect in route["delegated_effects"]:
        if effect["kind"] == EFFECT_SELECTION_CHANGED:
            assert effect["owner"] == SELECTION_CHANGED_OWNER

    executable_kinds = {
        effect["kind"] for effect in route["executable_effects"]
    }

    # 12-16. Structural effects materialize.
    assert EFFECT_VISIBILITY_CHANGED in executable_kinds
    assert EFFECT_DISABLED_CHANGED in executable_kinds
    assert EFFECT_READONLY_CHANGED in executable_kinds
    assert EFFECT_REQUIRED_CHANGED in executable_kinds
    assert EFFECT_CHECKED_CHANGED in executable_kinds

    # 17. CONTROL_DISAPPEARED is visual suppression only; no DOM removal.
    assert EFFECT_CONTROL_DISAPPEARED in executable_kinds
    assert ".remove()" not in form_effect_runtime_adapter_source()

    # 18. state.json metadata.
    state_metadata = json.loads(
        (runtime_dir / "state.json").read_text(encoding="utf-8")
    )

    assert (
        state_metadata["form_effect_runtime_adapter_version"]
        == AUTO_TWIN_FORM_EFFECT_RUNTIME_ADAPTER_VERSION
    )
    assert (
        state_metadata["form_effect_runtime_fingerprint"]
        == actual_fingerprint
    )
    assert state_metadata["form_effect_route_count"] == 1
    assert state_metadata["form_effect_evidence_ids"] == [evidence_id]

    # 19. registry.json carries the same metadata.
    registry = json.loads(
        (
            Path(result["revision_dir"]) / "runtime" / "registry.json"
        ).read_text(encoding="utf-8")
    )

    registry_state = next(
        item
        for item in registry["states"]
        if item["state_id"] == STATE_ID
    )

    assert (
        registry_state["form_effect_runtime_fingerprint"]
        == actual_fingerprint
    )
    assert registry_state["form_effect_evidence_ids"] == [evidence_id]

    # 20 + 21. renderer.json metadata.
    renderer = json.loads(
        (
            Path(result["revision_dir"]) / "runtime" / "renderer.json"
        ).read_text(encoding="utf-8")
    )

    assert renderer["renderer_version"] == AUTO_TWIN_RUNTIME_RENDERER_VERSION
    assert renderer["renderer_version"] == 7
    assert (
        renderer["form_effect_runtime_adapter_version"]
        == AUTO_TWIN_FORM_EFFECT_RUNTIME_ADAPTER_VERSION
    )

    # 32. No runtime literal values leak into artifacts/HTML.
    for forbidden in (
        "selected_value",
        "password",
        "file_path",
        "cookies",
        "tokens",
        "raw_capture",
    ):
        assert forbidden not in html_text
        assert forbidden not in json.dumps(materialized_payload)


# ---------------------------------------------------------------------------
# 22. State without refs creates no form-effect artifacts.
# ---------------------------------------------------------------------------


def test_state_without_refs_creates_no_form_effect_artifacts(
    tmp_path, monkeypatch
):
    form_effect_evidence_root = tmp_path / "form_effect_evidence"

    plan, result = _build_plan_and_materialize(
        tmp_path,
        monkeypatch,
        state_sources=[_state_source()],
        form_effect_evidence_root=form_effect_evidence_root,
    )

    plan_state = plan["state_manifest"][0]
    assert "form_effect_evidence_ids" not in plan_state

    runtime_dir = _state_runtime_dir(result, STATE_ID)

    assert not (
        runtime_dir / AUTO_TWIN_FORM_EFFECT_RUNTIME_FILENAME
    ).is_file()
    assert not (
        runtime_dir / AUTO_TWIN_FORM_EFFECT_RUNTIME_ADAPTER_FILENAME
    ).is_file()

    html_text = (runtime_dir / "index.html").read_text(encoding="utf-8")

    assert AUTO_TWIN_FORM_EFFECT_RUNTIME_PAYLOAD_ELEMENT_ID not in html_text
    assert AUTO_TWIN_FORM_EFFECT_RUNTIME_SCRIPT_MARKER not in html_text

    state_metadata = json.loads(
        (runtime_dir / "state.json").read_text(encoding="utf-8")
    )

    assert "form_effect_runtime_fingerprint" not in state_metadata
    assert "form_effect_evidence_ids" not in state_metadata

    # Renderer version/backward compatibility preserved.
    renderer = json.loads(
        (
            Path(result["revision_dir"]) / "runtime" / "renderer.json"
        ).read_text(encoding="utf-8")
    )

    assert renderer["renderer_version"] == 7


def test_two_states_only_referencing_state_gets_artifacts(
    tmp_path, monkeypatch
):
    form_effect_evidence_root = tmp_path / "form_effect_evidence"

    record, _store = _record_evidence(
        form_effect_evidence_root=form_effect_evidence_root,
    )

    evidence_id = record["evidence_id"]

    _plan, result = _build_plan_and_materialize(
        tmp_path,
        monkeypatch,
        state_sources=[
            _state_source(form_effect_evidence_ids=[evidence_id]),
            _state_source(
                state_id=STATE_ID_NO_REF,
                capture_id=CAPTURE_ID_NO_REF,
                pathname=PATHNAME_NO_REF,
                functional_state=None,
            ),
        ],
        form_effect_evidence_root=form_effect_evidence_root,
    )

    with_refs_runtime = _state_runtime_dir(result, STATE_ID)
    without_refs_runtime = _state_runtime_dir(result, STATE_ID_NO_REF)

    assert (
        with_refs_runtime / AUTO_TWIN_FORM_EFFECT_RUNTIME_FILENAME
    ).is_file()

    assert not (
        without_refs_runtime / AUTO_TWIN_FORM_EFFECT_RUNTIME_FILENAME
    ).is_file()


# ---------------------------------------------------------------------------
# 31. Duplicate IDs do not duplicate routes.
# ---------------------------------------------------------------------------


def test_duplicate_ids_do_not_duplicate_routes(tmp_path, monkeypatch):
    form_effect_evidence_root = tmp_path / "form_effect_evidence"

    record, _store = _record_evidence(
        form_effect_evidence_root=form_effect_evidence_root,
    )

    evidence_id = record["evidence_id"]

    plan, result = _build_plan_and_materialize(
        tmp_path,
        monkeypatch,
        state_sources=[
            _state_source(
                form_effect_evidence_ids=[evidence_id, evidence_id],
            ),
        ],
        form_effect_evidence_root=form_effect_evidence_root,
    )

    runtime_dir = _state_runtime_dir(result, STATE_ID)

    materialized_payload = json.loads(
        (runtime_dir / AUTO_TWIN_FORM_EFFECT_RUNTIME_FILENAME).read_text(
            encoding="utf-8"
        )
    )

    assert materialized_payload["route_count"] == 1
    assert plan["state_manifest"][0]["form_effect_route_count"] == 1


# ---------------------------------------------------------------------------
# Fail-closed scenarios: built via tampering an otherwise-valid plan,
# since build_auto_twin_materialization_plan() already independently
# validates evidence references at plan-build time (see
# test_qcc_auto_twin_form_effect_materialization_plan.py). These tests
# prove the BUILDER also revalidates rather than trusting the plan
# blindly.
# ---------------------------------------------------------------------------


def _valid_plan(tmp_path, monkeypatch, form_effect_evidence_root, evidence_id):
    captures_root = tmp_path / "captures"

    _write_source_files(captures_root, CAPTURE_ID)

    bundles = {
        CAPTURE_ID: _fake_bundle(
            capture_id=CAPTURE_ID,
            pathname=PATHNAME,
            functional_state=FUNCTIONAL_STATE,
        ),
    }

    _install_loader(monkeypatch, bundles)

    plan = build_auto_twin_materialization_plan(
        twin_key=TWIN_KEY,
        materialization_mode=AUTO_TWIN_MATERIALIZATION_MODE_BOOTSTRAP_REAL,
        state_sources=[
            _state_source(form_effect_evidence_ids=[evidence_id]),
        ],
        required_origin=REAL_ORIGIN,
        required_profile_key=PROFILE,
        root=captures_root,
        form_effect_evidence_root=form_effect_evidence_root,
    )

    return plan, captures_root


def test_unknown_evidence_id_fails_closed_at_materializer(
    tmp_path, monkeypatch
):
    form_effect_evidence_root = tmp_path / "form_effect_evidence"

    record, _store = _record_evidence(
        form_effect_evidence_root=form_effect_evidence_root,
    )

    plan, captures_root = _valid_plan(
        tmp_path,
        monkeypatch,
        form_effect_evidence_root,
        record["evidence_id"],
    )

    # Evidence vanished from the store between plan-build and
    # materialize (e.g. store was pruned/relocated).
    (
        form_effect_evidence_root / (TWIN_KEY + ".json")
    ).unlink()

    with pytest.raises(ValueError, match="FORM_EFFECT_RUNTIME_EVIDENCE_UNKNOWN"):
        materialize_auto_twin_plan(
            plan=plan,
            source_root=captures_root,
            materialized_root=tmp_path / "materialized",
            procedure_code="MERCURIO",
            flow_variant="SITE_LEVEL",
            form_effect_evidence_root=form_effect_evidence_root,
        )


def test_fingerprint_mismatch_fails_closed_at_materializer(
    tmp_path, monkeypatch
):
    form_effect_evidence_root = tmp_path / "form_effect_evidence"

    record, _store = _record_evidence(
        form_effect_evidence_root=form_effect_evidence_root,
    )

    plan, captures_root = _valid_plan(
        tmp_path,
        monkeypatch,
        form_effect_evidence_root,
        record["evidence_id"],
    )

    tampered = deepcopy(plan)
    tampered["state_manifest"][0]["form_effect_runtime_fingerprint"] = (
        "0" * 64
    )

    with pytest.raises(
        ValueError, match="FORM_EFFECT_RUNTIME_FINGERPRINT_MISMATCH"
    ):
        materialize_auto_twin_plan(
            plan=tampered,
            source_root=captures_root,
            materialized_root=tmp_path / "materialized",
            procedure_code="MERCURIO",
            flow_variant="SITE_LEVEL",
            form_effect_evidence_root=form_effect_evidence_root,
        )


def test_route_count_mismatch_fails_closed_at_materializer(
    tmp_path, monkeypatch
):
    form_effect_evidence_root = tmp_path / "form_effect_evidence"

    record, _store = _record_evidence(
        form_effect_evidence_root=form_effect_evidence_root,
    )

    plan, captures_root = _valid_plan(
        tmp_path,
        monkeypatch,
        form_effect_evidence_root,
        record["evidence_id"],
    )

    tampered = deepcopy(plan)
    tampered["state_manifest"][0]["form_effect_route_count"] = 99

    with pytest.raises(
        ValueError, match="FORM_EFFECT_RUNTIME_ROUTE_COUNT_MISMATCH"
    ):
        materialize_auto_twin_plan(
            plan=tampered,
            source_root=captures_root,
            materialized_root=tmp_path / "materialized",
            procedure_code="MERCURIO",
            flow_variant="SITE_LEVEL",
            form_effect_evidence_root=form_effect_evidence_root,
        )


def test_physical_pathname_mismatch_fails_closed_at_materializer(
    tmp_path, monkeypatch
):
    form_effect_evidence_root = tmp_path / "form_effect_evidence"

    record, _store = _record_evidence(
        form_effect_evidence_root=form_effect_evidence_root,
    )

    plan, captures_root = _valid_plan(
        tmp_path,
        monkeypatch,
        form_effect_evidence_root,
        record["evidence_id"],
    )

    tampered = deepcopy(plan)
    tampered["state_manifest"][0]["pathname"] = "/mercurio/otra-ruta.html"

    with pytest.raises(
        ValueError, match="FORM_EFFECT_RUNTIME_PATHNAME_MISMATCH"
    ):
        materialize_auto_twin_plan(
            plan=tampered,
            source_root=captures_root,
            materialized_root=tmp_path / "materialized",
            procedure_code="MERCURIO",
            flow_variant="SITE_LEVEL",
            form_effect_evidence_root=form_effect_evidence_root,
        )


def test_functional_state_mismatch_fails_closed_at_materializer(
    tmp_path, monkeypatch
):
    form_effect_evidence_root = tmp_path / "form_effect_evidence"

    record, _store = _record_evidence(
        form_effect_evidence_root=form_effect_evidence_root,
    )

    plan, captures_root = _valid_plan(
        tmp_path,
        monkeypatch,
        form_effect_evidence_root,
        record["evidence_id"],
    )

    tampered = deepcopy(plan)
    tampered["state_manifest"][0]["functional_state"] = "SOME_OTHER_STATE"

    with pytest.raises(
        ValueError, match="FORM_EFFECT_RUNTIME_FUNCTIONAL_STATE_MISMATCH"
    ):
        materialize_auto_twin_plan(
            plan=tampered,
            source_root=captures_root,
            materialized_root=tmp_path / "materialized",
            procedure_code="MERCURIO",
            flow_variant="SITE_LEVEL",
            form_effect_evidence_root=form_effect_evidence_root,
        )


def test_branch_context_mismatch_fails_closed_at_materializer(
    tmp_path, monkeypatch
):
    form_effect_evidence_root = tmp_path / "form_effect_evidence"

    record, _store = _record_evidence(
        form_effect_evidence_root=form_effect_evidence_root,
    )

    plan, captures_root = _valid_plan(
        tmp_path,
        monkeypatch,
        form_effect_evidence_root,
        record["evidence_id"],
    )

    tampered = deepcopy(plan)
    tampered["state_manifest"][0]["branch_context_id"] = "b" * 64

    with pytest.raises(
        ValueError, match="FORM_EFFECT_RUNTIME_BRANCH_CONTEXT_MISMATCH"
    ):
        materialize_auto_twin_plan(
            plan=tampered,
            source_root=captures_root,
            materialized_root=tmp_path / "materialized",
            procedure_code="MERCURIO",
            flow_variant="SITE_LEVEL",
            form_effect_evidence_root=form_effect_evidence_root,
        )


def test_before_fingerprint_mismatch_fails_closed_at_materializer(
    tmp_path, monkeypatch
):
    form_effect_evidence_root = tmp_path / "form_effect_evidence"

    record, _store = _record_evidence(
        form_effect_evidence_root=form_effect_evidence_root,
    )

    plan, captures_root = _valid_plan(
        tmp_path,
        monkeypatch,
        form_effect_evidence_root,
        record["evidence_id"],
    )

    tampered = deepcopy(plan)
    tampered["state_manifest"][0]["fingerprint"] = "c" * 64

    with pytest.raises(
        ValueError, match="FORM_EFFECT_RUNTIME_BEFORE_FINGERPRINT_MISMATCH"
    ):
        materialize_auto_twin_plan(
            plan=tampered,
            source_root=captures_root,
            materialized_root=tmp_path / "materialized",
            procedure_code="MERCURIO",
            flow_variant="SITE_LEVEL",
            form_effect_evidence_root=form_effect_evidence_root,
        )


def test_same_trigger_conflicting_evidence_fails_closed_at_materializer(
    tmp_path, monkeypatch
):
    form_effect_evidence_root = tmp_path / "form_effect_evidence"

    record, store = _record_evidence(
        form_effect_evidence_root=form_effect_evidence_root,
    )

    plan, captures_root = _valid_plan(
        tmp_path,
        monkeypatch,
        form_effect_evidence_root,
        record["evidence_id"],
    )

    # Directly craft a tampered/corrupted second evidence record
    # sharing the exact same physical identity + structural trigger
    # but disagreeing on the observed result -- store.record() itself
    # would reject this at write time; this proves the BUILDER still
    # fails closed rather than silently picking one side.
    conflicting_record = deepcopy(record)
    conflicting_record["evidence_id"] = "9" * 64
    conflicting_record["effects"][1]["after"] = False

    payload = store._load(TWIN_KEY)
    payload["evidence"].append(conflicting_record)
    payload["evidence_count"] = len(payload["evidence"])
    store._write(TWIN_KEY, payload)

    tampered = deepcopy(plan)
    tampered["state_manifest"][0]["form_effect_evidence_ids"] = sorted(
        [record["evidence_id"], conflicting_record["evidence_id"]]
    )

    with pytest.raises(
        ValueError, match="FORM_EFFECT_RUNTIME_BINDING_CONFLICT"
    ):
        materialize_auto_twin_plan(
            plan=tampered,
            source_root=captures_root,
            materialized_root=tmp_path / "materialized",
            procedure_code="MERCURIO",
            flow_variant="SITE_LEVEL",
            form_effect_evidence_root=form_effect_evidence_root,
        )


# ---------------------------------------------------------------------------
# Backward compatibility: historical plan with no form_effect_evidence_ids
# at all behaves exactly as before.
# ---------------------------------------------------------------------------


def test_historical_plan_without_refs_materializes_unaffected(
    tmp_path, monkeypatch
):
    form_effect_evidence_root = tmp_path / "form_effect_evidence"

    plan, result = _build_plan_and_materialize(
        tmp_path,
        monkeypatch,
        state_sources=[_state_source()],
        form_effect_evidence_root=form_effect_evidence_root,
    )

    assert result["state_count"] == 1

    runtime_dir = _state_runtime_dir(result, STATE_ID)
    assert (runtime_dir / "index.html").is_file()
    assert (runtime_dir / "network_sterilization.json").is_file()


# ---------------------------------------------------------------------------
# Default parameter backward compatibility: materialize_auto_twin_plan()
# called with no form_effect_evidence_root argument must not raise, for
# a plan carrying no form-effect references.
# ---------------------------------------------------------------------------


def test_materializer_default_form_effect_root_backward_compatible(
    tmp_path, monkeypatch
):
    captures_root = tmp_path / "captures"
    materialized_root = tmp_path / "materialized"

    _write_source_files(captures_root, CAPTURE_ID)

    bundles = {
        CAPTURE_ID: _fake_bundle(
            capture_id=CAPTURE_ID,
            pathname=PATHNAME,
            functional_state=FUNCTIONAL_STATE,
        ),
    }

    _install_loader(monkeypatch, bundles)

    plan = build_auto_twin_materialization_plan(
        twin_key=TWIN_KEY,
        materialization_mode=AUTO_TWIN_MATERIALIZATION_MODE_BOOTSTRAP_REAL,
        state_sources=[_state_source()],
        required_origin=REAL_ORIGIN,
        required_profile_key=PROFILE,
        root=captures_root,
    )

    result = materialize_auto_twin_plan(
        plan=plan,
        source_root=captures_root,
        materialized_root=materialized_root,
        procedure_code="MERCURIO",
        flow_variant="SITE_LEVEL",
    )

    assert result["state_count"] == 1
