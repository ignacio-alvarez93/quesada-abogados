"""Unit tests for UWT-6B3-1C1 AutoTwinFormEffectEvidenceStore.

Covers both the durable persistence contract owned by this store and
the B3-1B pre-materialization normalization contract it depends on
(``form_effect_runtime.normalize_form_effect_evidence_record`` /
``bind_form_effect_runtime_payload``) -- the existing
``test_qcc_auto_twin_form_effect_runtime.py`` is out of this work
order's authorized MODIFY scope, so that coverage lives here instead.
"""

from __future__ import annotations

import json

import pytest

from backend.qcc.auto_twin.form_effect_evidence_store import (
    AutoTwinFormEffectEvidenceStore,
    AutoTwinFormEffectEvidenceStoreError,
)
from backend.qcc.auto_twin.form_effect_runtime import (
    FormEffectRuntimeError,
    bind_form_effect_runtime_payload,
    normalize_form_effect_evidence_record,
)


BEFORE_FINGERPRINT_A = "a" * 64
BEFORE_FINGERPRINT_B = "b" * 64

BRANCH_CONTEXT_ID = "c" * 64


def _target(
    *,
    control_key="main::INPUT::#x",
    frame_path="main",
    selector="#x",
    semantic_kind="TEXT_INPUT",
):
    return {
        "control_key": control_key,
        "frame_path": frame_path,
        "selector": selector,
        "semantic_kind": semantic_kind,
    }


def _disabled_effect(*, after=True, target=None):
    return {
        "kind": "DISABLED_CHANGED",
        "target": target or _target(),
        "before": not after,
        "after": after,
    }


def _selection_changed_effect():
    return {
        "kind": "SELECTION_CHANGED",
        "target": _target(
            control_key="main::SELECT::#city",
            selector="#city",
            semantic_kind="SELECT",
        ),
        "before": {
            "selected_values": ("madrid-centro",),
            "selected_indexes": (0,),
        },
        "after": {
            "selected_values": ("bcn-eixample",),
            "selected_indexes": (1,),
        },
    }


def _blocked_effect():
    return {
        "kind": "HAS_VALUE_CHANGED",
        "target": _target(control_key="main::INPUT::#y", selector="#y"),
        "before": False,
        "after": True,
    }


def _select_action():
    return {
        "kind": "SELECT",
        "selector": "#province",
        "frame_path": "main",
    }


def _select_mutation_identity(*, selected_index=1):
    return {
        "kind": "SELECT",
        "selected_index": selected_index,
    }


def _experiment_result(
    *,
    pathname="/foo",
    before_fingerprint=BEFORE_FINGERPRINT_A,
    action=None,
    mutation_identity=None,
    effects=None,
):
    return {
        "pathname": pathname,
        "before_fingerprint": before_fingerprint,
        "action": action or _select_action(),
        "mutation_identity": (
            mutation_identity or _select_mutation_identity()
        ),
        "effects": list(effects or (_disabled_effect(),)),
    }


def _store(tmp_path):
    return AutoTwinFormEffectEvidenceStore(
        root=tmp_path / "form_effect_evidence"
    )


# ---------------------------------------------------------------------------
# B3-1B normalization (via direct form_effect_runtime API)
# ---------------------------------------------------------------------------

def test_normalize_strips_selected_values_from_selection_changed():
    record = normalize_form_effect_evidence_record(
        action=_select_action(),
        mutation_identity=_select_mutation_identity(),
        effects=[_selection_changed_effect()],
    )

    serialized = json.dumps(record)

    assert "selected_value" not in serialized
    assert "selected_values" not in serialized
    assert "selected_indexes" not in serialized

    delegated = record["effects"][0]

    assert delegated["kind"] == "SELECTION_CHANGED"
    assert delegated["owner"] == "CATALOG_RUNTIME"
    assert set(delegated) == {"kind", "target", "owner"}


def test_normalize_blocked_effect_persists_kind_only():
    record = normalize_form_effect_evidence_record(
        action=_select_action(),
        mutation_identity=_select_mutation_identity(),
        effects=[_blocked_effect()],
    )

    assert record["effects"] == ({"kind": "HAS_VALUE_CHANGED"},)

    serialized = json.dumps(record)

    assert "before" not in serialized


def test_normalize_is_deterministic():
    effects = [
        _disabled_effect(),
        _selection_changed_effect(),
        _blocked_effect(),
    ]

    record_a = normalize_form_effect_evidence_record(
        action=_select_action(),
        mutation_identity=_select_mutation_identity(),
        effects=list(effects),
    )

    record_b = normalize_form_effect_evidence_record(
        action=_select_action(),
        mutation_identity=_select_mutation_identity(),
        effects=list(reversed(effects)),
    )

    assert record_a == record_b


def test_normalize_contextual_shape_fails_closed():
    with pytest.raises(FormEffectRuntimeError):
        normalize_form_effect_evidence_record(
            action={**_select_action(), "context": {"x": 1}},
            mutation_identity=_select_mutation_identity(),
            effects=[],
        )


def test_bind_conflicting_trigger_fails_closed():
    record_a = normalize_form_effect_evidence_record(
        action=_select_action(),
        mutation_identity=_select_mutation_identity(),
        effects=[_disabled_effect(after=True)],
    )

    record_b = normalize_form_effect_evidence_record(
        action=_select_action(),
        mutation_identity=_select_mutation_identity(),
        effects=[_disabled_effect(after=False)],
    )

    with pytest.raises(FormEffectRuntimeError):
        bind_form_effect_runtime_payload(
            state_id="STATE_1",
            normalized_records=[record_a, record_b],
        )


def test_bind_produces_canonical_runtime_payload_shape():
    record = normalize_form_effect_evidence_record(
        action=_select_action(),
        mutation_identity=_select_mutation_identity(),
        effects=[_disabled_effect()],
    )

    payload = bind_form_effect_runtime_payload(
        state_id="STATE_1",
        normalized_records=[record],
    )

    assert payload["route_count"] == 1
    assert payload["routes"][0]["trigger"]["state_id"] == "STATE_1"
    assert payload["routes"][0]["status"] == "EXECUTABLE"


# ---------------------------------------------------------------------------
# Evidence store — durable persistence contract
# ---------------------------------------------------------------------------

def test_record_returns_deterministic_evidence_id(tmp_path):
    store = _store(tmp_path)

    record = store.record(
        twin_key="twin-1",
        experiment_result=_experiment_result(),
        functional_state="FORM_MAIN",
    )

    assert record["evidence_id"]
    assert len(record["evidence_id"]) == 64


def test_record_is_idempotent_for_identical_evidence(tmp_path):
    store = _store(tmp_path)

    result = _experiment_result()

    record_a = store.record(
        twin_key="twin-1",
        experiment_result=result,
        functional_state="FORM_MAIN",
    )

    record_b = store.record(
        twin_key="twin-1",
        experiment_result=result,
        functional_state="FORM_MAIN",
    )

    assert record_a == record_b

    snapshot = store._load("twin-1")

    assert snapshot["evidence_count"] == 1
    assert snapshot["revision"] == 1


def test_record_no_raw_selected_values_persisted(tmp_path):
    store = _store(tmp_path)

    record = store.record(
        twin_key="twin-1",
        experiment_result=_experiment_result(
            effects=[_selection_changed_effect()],
        ),
        functional_state="FORM_MAIN",
    )

    serialized = json.dumps(record)

    for forbidden in (
        "selected_value",
        "selected_values",
        "selected_indexes",
        "madrid-centro",
        "bcn-eixample",
    ):
        assert forbidden not in serialized


def test_record_physical_identity_preserved(tmp_path):
    store = _store(tmp_path)

    record = store.record(
        twin_key="twin-1",
        experiment_result=_experiment_result(
            pathname="/expedientes",
            before_fingerprint=BEFORE_FINGERPRINT_A,
        ),
        functional_state="FORM_MAIN",
        branch_context_id=BRANCH_CONTEXT_ID,
    )

    assert record["pathname"] == "/expedientes"
    assert record["functional_state"] == "FORM_MAIN"
    assert record["branch_context_id"] == BRANCH_CONTEXT_ID
    assert record["before_fingerprint"] == BEFORE_FINGERPRINT_A


@pytest.mark.parametrize(
    "malformed_fingerprint",
    ["", "A" * 64, "g" * 64, "a" * 63],
)
def test_record_malformed_before_fingerprint_rejected(
    tmp_path, malformed_fingerprint
):
    store = _store(tmp_path)

    with pytest.raises(AutoTwinFormEffectEvidenceStoreError):
        store.record(
            twin_key="twin-1",
            experiment_result=_experiment_result(
                before_fingerprint=malformed_fingerprint,
            ),
            functional_state="FORM_MAIN",
        )


def test_record_malformed_branch_context_id_rejected(tmp_path):
    store = _store(tmp_path)

    with pytest.raises(AutoTwinFormEffectEvidenceStoreError):
        store.record(
            twin_key="twin-1",
            experiment_result=_experiment_result(),
            functional_state="FORM_MAIN",
            branch_context_id="not-a-sha256",
        )


def test_record_pathname_validation(tmp_path):
    store = _store(tmp_path)

    with pytest.raises(AutoTwinFormEffectEvidenceStoreError):
        store.record(
            twin_key="twin-1",
            experiment_result=_experiment_result(pathname="no-leading-slash"),
            functional_state="FORM_MAIN",
        )


def test_different_physical_state_yields_different_id(tmp_path):
    store = _store(tmp_path)

    record_a = store.record(
        twin_key="twin-1",
        experiment_result=_experiment_result(pathname="/foo"),
        functional_state="FORM_MAIN",
    )

    record_b = store.record(
        twin_key="twin-1",
        experiment_result=_experiment_result(pathname="/bar"),
        functional_state="FORM_MAIN",
    )

    assert record_a["evidence_id"] != record_b["evidence_id"]


def test_different_before_fingerprint_yields_different_id(tmp_path):
    store = _store(tmp_path)

    record_a = store.record(
        twin_key="twin-1",
        experiment_result=_experiment_result(
            before_fingerprint=BEFORE_FINGERPRINT_A,
        ),
        functional_state="FORM_MAIN",
    )

    record_b = store.record(
        twin_key="twin-1",
        experiment_result=_experiment_result(
            before_fingerprint=BEFORE_FINGERPRINT_B,
        ),
        functional_state="FORM_MAIN",
    )

    assert record_a["evidence_id"] != record_b["evidence_id"]


def test_conflicting_trigger_for_same_physical_identity_fails_closed(
    tmp_path,
):
    store = _store(tmp_path)

    store.record(
        twin_key="twin-1",
        experiment_result=_experiment_result(
            effects=[_disabled_effect(after=True)],
        ),
        functional_state="FORM_MAIN",
    )

    with pytest.raises(AutoTwinFormEffectEvidenceStoreError):
        store.record(
            twin_key="twin-1",
            experiment_result=_experiment_result(
                effects=[_disabled_effect(after=False)],
            ),
            functional_state="FORM_MAIN",
        )


def test_reload_round_trip(tmp_path):
    store = _store(tmp_path)

    recorded = store.record(
        twin_key="twin-1",
        experiment_result=_experiment_result(),
        functional_state="FORM_MAIN",
    )

    reloaded_store = _store(tmp_path)

    fetched = reloaded_store.get("twin-1", recorded["evidence_id"])

    assert fetched == recorded


def test_revision_only_increments_on_actual_mutation(tmp_path):
    store = _store(tmp_path)

    result = _experiment_result()

    store.record(
        twin_key="twin-1",
        experiment_result=result,
        functional_state="FORM_MAIN",
    )

    assert store._load("twin-1")["revision"] == 1

    store.record(
        twin_key="twin-1",
        experiment_result=result,
        functional_state="FORM_MAIN",
    )

    assert store._load("twin-1")["revision"] == 1

    store.record(
        twin_key="twin-1",
        experiment_result=_experiment_result(pathname="/other"),
        functional_state="FORM_MAIN",
    )

    assert store._load("twin-1")["revision"] == 2


def test_get_returns_none_for_unknown_evidence_id(tmp_path):
    store = _store(tmp_path)

    store.record(
        twin_key="twin-1",
        experiment_result=_experiment_result(),
        functional_state="FORM_MAIN",
    )

    assert store.get("twin-1", "f" * 64) is None


def test_list_for_state_deterministic_order(tmp_path):
    store = _store(tmp_path)

    store.record(
        twin_key="twin-1",
        experiment_result=_experiment_result(
            action={"kind": "SELECT", "selector": "#b", "frame_path": "main"},
        ),
        functional_state="FORM_MAIN",
    )

    store.record(
        twin_key="twin-1",
        experiment_result=_experiment_result(
            action={"kind": "SELECT", "selector": "#a", "frame_path": "main"},
        ),
        functional_state="FORM_MAIN",
    )

    listed_a = store.list_for_state(
        "twin-1",
        pathname="/foo",
        functional_state="FORM_MAIN",
    )

    listed_b = store.list_for_state(
        "twin-1",
        pathname="/foo",
        functional_state="FORM_MAIN",
    )

    assert listed_a == listed_b
    assert len(listed_a) == 2
    assert [item["evidence_id"] for item in listed_a] == sorted(
        item["evidence_id"] for item in listed_a
    )


def test_list_for_state_filters_by_functional_state_none_semantics(
    tmp_path,
):
    store = _store(tmp_path)

    store.record(
        twin_key="twin-1",
        experiment_result=_experiment_result(),
        functional_state=None,
    )

    store.record(
        twin_key="twin-1",
        experiment_result=_experiment_result(
            action={"kind": "SELECT", "selector": "#other", "frame_path": "main"},
        ),
        functional_state="FORM_MAIN",
    )

    listed_none = store.list_for_state(
        "twin-1",
        pathname="/foo",
        functional_state=None,
    )

    assert len(listed_none) == 1
    assert listed_none[0]["functional_state"] is None


def test_no_raw_experiment_result_persisted(tmp_path):
    store = _store(tmp_path)

    canary = "RAW_RUN_EXPERIMENT_RESULT_CANARY"

    result = _experiment_result()
    result["unexpected_raw_field"] = canary

    record = store.record(
        twin_key="twin-1",
        experiment_result=result,
        functional_state="FORM_MAIN",
    )

    serialized = json.dumps(record)

    assert canary not in serialized
    assert "unexpected_raw_field" not in record
