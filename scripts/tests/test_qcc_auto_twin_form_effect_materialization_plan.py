"""Unit tests for UWT-6B3-1C1 MaterializationPlan form-effect refs.

Covers ``build_auto_twin_materialization_plan``'s optional
``form_effect_evidence_ids`` state-source field: physical identity
binding, before_fingerprint binding and fail-closed behavior. Absent
refs must keep historical plan semantics exactly unchanged (see
``test_qcc_auto_twin_materialization_plan.py``, out of this work
order's authorized MODIFY scope).
"""

from __future__ import annotations

from pathlib import Path

import pytest

import backend.qcc.auto_twin.materialization_plan as plan_module

from backend.qcc.auto_twin.form_effect_evidence_store import (
    AutoTwinFormEffectEvidenceStore,
)
from backend.qcc.auto_twin.materialized_revision import (
    AUTO_TWIN_MATERIALIZATION_MODE_BOOTSTRAP_REAL,
)
from backend.qcc.auto_twin.materialization_plan import (
    AUTO_TWIN_MATERIALIZATION_SOURCE_ARTIFACTS,
    build_auto_twin_materialization_plan,
)


REAL_ORIGIN = "https://mercurio.delegaciondelgobierno.gob.es"

TWIN_KEY = "mercurio-form-plan"
CAPTURE_ID = "capture-form-1"
STATE_ID = "FORM_STATE_1"
PATHNAME = "/mercurio/formulario.html"
FUNCTIONAL_STATE = "FORM_MAIN"

BEFORE_FINGERPRINT = "a" * 64
OTHER_FINGERPRINT = "b" * 64
BRANCH_CONTEXT_ID = "c" * 64


def _write_source_files(root, capture_id):
    directory = Path(root) / capture_id
    directory.mkdir(parents=True)

    for index, (_kind, filename, _destination) in enumerate(
        AUTO_TWIN_MATERIALIZATION_SOURCE_ARTIFACTS,
        start=1,
    ):
        (directory / filename).write_bytes(
            f"{capture_id}:{filename}:{index}".encode("utf-8")
        )


def _fake_bundle(
    *,
    capture_id,
    pathname,
    functional_state,
    fingerprint,
    profile="qcc_assisted",
    origin=REAL_ORIGIN,
):
    return {
        "capture_id": capture_id,
        "capture": {
            "capture_id": capture_id,
            "pathname": pathname,
            "functional_state": functional_state,
            "browser_profile_key": profile,
        },
        "snapshot": {
            "page": {
                "origin": origin,
                "pathname": pathname,
            },
        },
        "rendering_profile": {
            "rendering_profile_id": "render-profile-1",
        },
        "fingerprint": fingerprint,
    }


def _install_loader(monkeypatch, bundle):
    def fake_loader(*, capture_id, root, require_viewport_image):
        assert capture_id == CAPTURE_ID
        return bundle

    monkeypatch.setattr(
        plan_module,
        "load_auto_twin_persisted_capture_bundle",
        fake_loader,
    )


def _state_source(**overrides):
    base = {
        "state_id": STATE_ID,
        "capture_id": CAPTURE_ID,
        "pathname": PATHNAME,
        "functional_state": FUNCTIONAL_STATE,
    }

    base.update(overrides)

    return base


def _select_action():
    return {"kind": "SELECT", "selector": "#province", "frame_path": "main"}


def _target():
    return {
        "control_key": "main::INPUT::#x",
        "frame_path": "main",
        "selector": "#x",
        "semantic_kind": "TEXT_INPUT",
    }


def _experiment_result(*, after=True, pathname=PATHNAME, before_fingerprint=BEFORE_FINGERPRINT):
    return {
        "pathname": pathname,
        "before_fingerprint": before_fingerprint,
        "action": _select_action(),
        "mutation_identity": {"kind": "SELECT", "selected_index": 1},
        "effects": [
            {
                "kind": "DISABLED_CHANGED",
                "target": _target(),
                "before": not after,
                "after": after,
            },
        ],
    }


def _record_evidence(
    *,
    form_effect_evidence_root,
    functional_state=FUNCTIONAL_STATE,
    branch_context_id=None,
    **experiment_result_overrides,
):
    store = AutoTwinFormEffectEvidenceStore(
        root=form_effect_evidence_root
    )

    record = store.record(
        twin_key=TWIN_KEY,
        experiment_result=_experiment_result(
            **experiment_result_overrides
        ),
        functional_state=functional_state,
        branch_context_id=branch_context_id,
    )

    return record["evidence_id"]


def _build_plan(
    *,
    tmp_path,
    monkeypatch,
    state_source,
    fingerprint=BEFORE_FINGERPRINT,
    pathname=PATHNAME,
    functional_state=FUNCTIONAL_STATE,
):
    _write_source_files(tmp_path, CAPTURE_ID)

    bundle = _fake_bundle(
        capture_id=CAPTURE_ID,
        pathname=pathname,
        functional_state=functional_state,
        fingerprint=fingerprint,
    )

    _install_loader(monkeypatch, bundle)

    form_effect_evidence_root = tmp_path / "form_effect_evidence"

    return build_auto_twin_materialization_plan(
        twin_key=TWIN_KEY,
        materialization_mode=AUTO_TWIN_MATERIALIZATION_MODE_BOOTSTRAP_REAL,
        state_sources=[state_source],
        required_origin=REAL_ORIGIN,
        required_profile_key="qcc_assisted",
        root=tmp_path,
        form_effect_evidence_root=form_effect_evidence_root,
    ), form_effect_evidence_root


# ---------------------------------------------------------------------------
# 1. Absent refs => historical path unaffected.
# ---------------------------------------------------------------------------

def test_absent_refs_unaffected(tmp_path, monkeypatch):
    plan, _root = _build_plan(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        state_source=_state_source(),
    )

    state = plan["state_manifest"][0]

    assert "form_effect_evidence_ids" not in state
    assert "form_effect_runtime_fingerprint" not in state
    assert "form_effect_route_count" not in state


def test_empty_refs_treated_as_absent(tmp_path, monkeypatch):
    plan, _root = _build_plan(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        state_source=_state_source(form_effect_evidence_ids=[]),
    )

    state = plan["state_manifest"][0]

    assert "form_effect_evidence_ids" not in state


# ---------------------------------------------------------------------------
# 2. Valid reference binds to correct state.
# ---------------------------------------------------------------------------

def test_valid_reference_binds_to_state(tmp_path, monkeypatch):
    _write_source_files(tmp_path, CAPTURE_ID)

    bundle = _fake_bundle(
        capture_id=CAPTURE_ID,
        pathname=PATHNAME,
        functional_state=FUNCTIONAL_STATE,
        fingerprint=BEFORE_FINGERPRINT,
    )

    monkeypatch.setattr(
        plan_module,
        "load_auto_twin_persisted_capture_bundle",
        lambda **kwargs: bundle,
    )

    form_effect_evidence_root = tmp_path / "form_effect_evidence"

    evidence_id = _record_evidence(
        form_effect_evidence_root=form_effect_evidence_root,
    )

    plan = build_auto_twin_materialization_plan(
        twin_key=TWIN_KEY,
        materialization_mode=AUTO_TWIN_MATERIALIZATION_MODE_BOOTSTRAP_REAL,
        state_sources=[
            _state_source(
                form_effect_evidence_ids=[evidence_id],
            )
        ],
        required_origin=REAL_ORIGIN,
        required_profile_key="qcc_assisted",
        root=tmp_path,
        form_effect_evidence_root=form_effect_evidence_root,
    )

    state = plan["state_manifest"][0]

    assert state["form_effect_evidence_ids"] == [evidence_id]
    assert state["form_effect_route_count"] == 1
    assert isinstance(state["form_effect_runtime_fingerprint"], str)
    assert len(state["form_effect_runtime_fingerprint"]) == 64

    # No raw evidence/payload blobs in the plan.
    assert "effects" not in state
    assert "action" not in state


# ---------------------------------------------------------------------------
# 3. Unknown ID fails closed.
# ---------------------------------------------------------------------------

def test_unknown_evidence_id_fails_closed(tmp_path, monkeypatch):
    with pytest.raises(ValueError):
        _build_plan(
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
            state_source=_state_source(
                form_effect_evidence_ids=["f" * 64],
            ),
        )


# ---------------------------------------------------------------------------
# 4. Pathname mismatch fails closed.
# ---------------------------------------------------------------------------

def test_pathname_mismatch_fails_closed(tmp_path, monkeypatch):
    form_effect_evidence_root = tmp_path / "form_effect_evidence"

    evidence_id = _record_evidence(
        form_effect_evidence_root=form_effect_evidence_root,
        pathname="/mercurio/otra-pagina.html",
    )

    _write_source_files(tmp_path, CAPTURE_ID)

    bundle = _fake_bundle(
        capture_id=CAPTURE_ID,
        pathname=PATHNAME,
        functional_state=FUNCTIONAL_STATE,
        fingerprint=BEFORE_FINGERPRINT,
    )

    monkeypatch.setattr(
        plan_module,
        "load_auto_twin_persisted_capture_bundle",
        lambda **kwargs: bundle,
    )

    with pytest.raises(ValueError):
        build_auto_twin_materialization_plan(
            twin_key=TWIN_KEY,
            materialization_mode=AUTO_TWIN_MATERIALIZATION_MODE_BOOTSTRAP_REAL,
            state_sources=[
                _state_source(
                    form_effect_evidence_ids=[evidence_id],
                )
            ],
            required_origin=REAL_ORIGIN,
            required_profile_key="qcc_assisted",
            root=tmp_path,
            form_effect_evidence_root=form_effect_evidence_root,
        )


# ---------------------------------------------------------------------------
# 5. functional_state mismatch fails closed.
# ---------------------------------------------------------------------------

def test_functional_state_mismatch_fails_closed(tmp_path, monkeypatch):
    form_effect_evidence_root = tmp_path / "form_effect_evidence"

    evidence_id = _record_evidence(
        form_effect_evidence_root=form_effect_evidence_root,
        functional_state="SOME_OTHER_STATE",
    )

    with pytest.raises(ValueError):
        _build_plan(
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
            state_source=_state_source(
                form_effect_evidence_ids=[evidence_id],
            ),
        )


# ---------------------------------------------------------------------------
# 6. branch_context mismatch fails closed.
# ---------------------------------------------------------------------------

def test_branch_context_mismatch_fails_closed(tmp_path, monkeypatch):
    form_effect_evidence_root = tmp_path / "form_effect_evidence"

    evidence_id = _record_evidence(
        form_effect_evidence_root=form_effect_evidence_root,
        branch_context_id=BRANCH_CONTEXT_ID,
    )

    with pytest.raises(ValueError):
        _build_plan(
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
            state_source=_state_source(
                form_effect_evidence_ids=[evidence_id],
            ),
        )


# ---------------------------------------------------------------------------
# 7. before_fingerprint mismatch fails closed.
# ---------------------------------------------------------------------------

def test_before_fingerprint_mismatch_fails_closed(tmp_path, monkeypatch):
    form_effect_evidence_root = tmp_path / "form_effect_evidence"

    evidence_id = _record_evidence(
        form_effect_evidence_root=form_effect_evidence_root,
        before_fingerprint=OTHER_FINGERPRINT,
    )

    with pytest.raises(ValueError):
        _build_plan(
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
            state_source=_state_source(
                form_effect_evidence_ids=[evidence_id],
            ),
            fingerprint=BEFORE_FINGERPRINT,
        )


# ---------------------------------------------------------------------------
# 8. Duplicate reference deduped deterministically.
# ---------------------------------------------------------------------------

def test_duplicate_reference_deduped(tmp_path, monkeypatch):
    form_effect_evidence_root = tmp_path / "form_effect_evidence"

    evidence_id = _record_evidence(
        form_effect_evidence_root=form_effect_evidence_root,
    )

    _write_source_files(tmp_path, CAPTURE_ID)

    bundle = _fake_bundle(
        capture_id=CAPTURE_ID,
        pathname=PATHNAME,
        functional_state=FUNCTIONAL_STATE,
        fingerprint=BEFORE_FINGERPRINT,
    )

    monkeypatch.setattr(
        plan_module,
        "load_auto_twin_persisted_capture_bundle",
        lambda **kwargs: bundle,
    )

    plan = build_auto_twin_materialization_plan(
        twin_key=TWIN_KEY,
        materialization_mode=AUTO_TWIN_MATERIALIZATION_MODE_BOOTSTRAP_REAL,
        state_sources=[
            _state_source(
                form_effect_evidence_ids=[evidence_id, evidence_id],
            )
        ],
        required_origin=REAL_ORIGIN,
        required_profile_key="qcc_assisted",
        root=tmp_path,
        form_effect_evidence_root=form_effect_evidence_root,
    )

    state = plan["state_manifest"][0]

    assert state["form_effect_evidence_ids"] == [evidence_id]
    assert state["form_effect_route_count"] == 1


# ---------------------------------------------------------------------------
# 9. Conflicting route fails closed.
# ---------------------------------------------------------------------------

def test_conflicting_route_fails_closed(tmp_path, monkeypatch):
    form_effect_evidence_root = tmp_path / "form_effect_evidence"

    store = AutoTwinFormEffectEvidenceStore(
        root=form_effect_evidence_root
    )

    # Simulate two independently-persisted evidence records that
    # happen to share the exact same physical identity + structural
    # trigger but disagree on the observed result -- store.record()
    # itself would reject this at write time (see
    # test_qcc_auto_twin_form_effect_evidence_store.py); this directly
    # crafts the tampered/corrupted-data scenario to prove the PLAN's
    # binding step still fails closed rather than silently picking
    # one side.
    base_record = {
        "twin_key": TWIN_KEY,
        "pathname": PATHNAME,
        "functional_state": FUNCTIONAL_STATE,
        "branch_context_id": None,
        "before_fingerprint": BEFORE_FINGERPRINT,
        "action": _select_action(),
        "mutation_identity": {"kind": "SELECT", "selected_index": 1},
    }

    record_a = {
        **base_record,
        "evidence_id": "1" * 64,
        "effects": [
            {"kind": "DISABLED_CHANGED", "target": _target(), "after": True}
        ],
    }

    record_b = {
        **base_record,
        "evidence_id": "2" * 64,
        "effects": [
            {"kind": "DISABLED_CHANGED", "target": _target(), "after": False}
        ],
    }

    payload = store._empty(TWIN_KEY)
    payload["evidence"] = [record_a, record_b]
    payload["evidence_count"] = 2
    payload["revision"] = 1
    store._write(TWIN_KEY, payload)

    with pytest.raises(ValueError):
        _build_plan(
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
            state_source=_state_source(
                form_effect_evidence_ids=[
                    record_a["evidence_id"],
                    record_b["evidence_id"],
                ],
            ),
        )


# ---------------------------------------------------------------------------
# 10. Carry-forward never attempts evidence loading/rebinding.
# ---------------------------------------------------------------------------

def test_carry_forward_never_loads_form_effect_evidence(tmp_path, monkeypatch):
    base_revision_dir = tmp_path / "base-revision"
    base_revision_dir.mkdir(parents=True)

    form_effect_evidence_root = tmp_path / "form_effect_evidence"

    def fail_if_called(*args, **kwargs):
        raise AssertionError(
            "MATERIALIZED_CARRY_FORWARD must never load form-effect "
            "evidence"
        )

    monkeypatch.setattr(
        AutoTwinFormEffectEvidenceStore,
        "get",
        fail_if_called,
    )

    plan = build_auto_twin_materialization_plan(
        twin_key=TWIN_KEY,
        materialization_mode=AUTO_TWIN_MATERIALIZATION_MODE_BOOTSTRAP_REAL,
        state_sources=[
            {
                "state_id": "CARRY_STATE",
                "capture_id": "unused-capture",
                "pathname": PATHNAME,
                "functional_state": FUNCTIONAL_STATE,
                "source_mode": "MATERIALIZED_CARRY_FORWARD",
                "form_effect_evidence_ids": ["f" * 64],
            }
        ],
        required_origin=REAL_ORIGIN,
        required_profile_key="qcc_assisted",
        base_materialized_revision_id="matrev-base-001",
        root=tmp_path,
        form_effect_evidence_root=form_effect_evidence_root,
    )

    state = plan["state_manifest"][0]

    assert "form_effect_evidence_ids" not in state
