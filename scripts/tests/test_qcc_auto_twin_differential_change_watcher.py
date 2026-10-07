import json

import pytest

from backend.qcc.auto_twin.contract_watcher import ContractWatchState
from backend.qcc.auto_twin.contract_watcher_confirmation import (
    ContractWatcherConfirmationPolicy,
)
from backend.qcc.auto_twin.contract_watcher_history_store import (
    ContractWatcherHistoryStore,
)
from backend.qcc.auto_twin.contract_watcher_observation_selector import (
    CONTRACT_WATCHER_SELECTOR_SKIP_NOTHING_TO_COMPARE,
    CONTRACT_WATCHER_SELECTOR_SKIP_STATE_NOT_BASELINED,
    contract_watcher_observation_contract_key,
)
from backend.qcc.auto_twin.contract_watcher_pipeline import (
    ContractWatcherCycleOutcome,
)
from backend.qcc.auto_twin.contract_watcher_store import ContractWatcherEvidenceStore
from backend.qcc.auto_twin.differential_change_watcher import (
    DIFFERENTIAL_CHANGE_CATEGORY_INTERACTION,
    DIFFERENTIAL_CHANGE_CATEGORY_RESOURCE,
    DIFFERENTIAL_CHANGE_CATEGORY_STATE_TRANSITION,
    DIFFERENTIAL_CHANGE_CATEGORY_STRUCTURAL,
    DIFFERENTIAL_CHANGE_RESULT_CLASSIFIED,
    DIFFERENTIAL_CHANGE_RESULT_NO_DRIFT,
    DIFFERENTIAL_CHANGE_RESULT_SKIPPED,
    DIFFERENTIAL_CHANGE_RESULT_UNKNOWN,
    build_differential_change_evidence_for_twin_state,
    classify_differential_change_categories,
)
from backend.qcc.auto_twin.managed_site_registry import AutoTwinManagedSite
from backend.qcc.auto_twin.observation_store import AutoTwinObservationStore


ORIGIN = "http://127.0.0.1:8767"


def _policy(threshold=2):
    return ContractWatcherConfirmationPolicy(required_consecutive_observations=threshold)


def _site(twin_key="twin-a", site_code="SITE_A"):
    return AutoTwinManagedSite(
        twin_key=twin_key,
        site_code=site_code,
        origins=(ORIGIN,),
        discover_unknown_states=True,
    )


def _observe(store, site, *, capture_id, fingerprint, pathname="/case/step",
             state="STATE_A", observed_at="2026-01-01T00:00:00.000000Z"):
    return store.observe(
        site,
        capture_id=capture_id,
        observed_at=observed_at,
        browser_profile_key="twin_discovery",
        url=ORIGIN + pathname,
        site_code=site.site_code,
        state_observation={"state": state, "fingerprint": fingerprint},
    )


def _element(selector, *, semantics=("BUTTON",), rect=None, disabled=False,
             class_token="tab-default", element_id=None):
    return {
        "frame_path": "main",
        "semantics": semantics,
        "class": class_token,
        "id": element_id or selector.lstrip("#"),
        "selectors": {
            "frame_path": "main",
            "primary": {
                "strategy": "ID",
                "selector": selector,
                "confidence": "HIGH",
                "unique": True,
            },
            "fallbacks": (),
            "candidates": ({
                "strategy": "ID",
                "selector": selector,
                "confidence": "HIGH",
                "unique": True,
            },),
            "confidence": "HIGH",
        },
        "interaction": {
            "state": "INTERACTABLE",
            "visible": True,
            "in_viewport": True,
            "disabled": disabled,
            "readonly": False,
            "pointer_events": "auto",
        },
        "geometry": {
            "coordinate_space": "TOP_LEVEL_VIEWPORT",
            "frame_path": "main",
            "viewport_rect": rect,
        },
    }


def _catalog(key, *, options):
    return {
        "frame_path": "main",
        "catalog_type": "native_select",
        "selector": "#" + key,
        "catalog_key": "main::#" + key,
        "options": list(options),
    }


def _write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def _write_capture(root, *, capture_id, elements=(), catalogs=(),
                    pathname="/case/step", functional_state="STATE_A",
                    site_code="SITE_A"):
    capture_dir = root / capture_id
    capture_dir.mkdir(parents=True)

    metadata = {
        "capture_id": capture_id,
        "site_code": site_code,
        "artifacts": {
            "raw_capture": "qcc_capture.json",
            "site_architecture": "site_architecture.json",
            "state_observation": "state_observation.json",
            "metadata": "metadata.json",
        },
        "retention": {"browser_profile_key": "twin_discovery"},
        "state_observation": {
            "state": functional_state,
            "fingerprint": "fingerprint-" + capture_id,
        },
    }

    _write_json(capture_dir / "metadata.json", metadata)

    _write_json(
        capture_dir / "qcc_capture.json",
        {
            "schema_version": 1,
            "browser_profile_key": "twin_discovery",
            "main_url": ORIGIN + pathname,
        },
    )

    _write_json(
        capture_dir / "site_architecture.json",
        {
            "schema_version": 1,
            "page": {"pathname": pathname, "url": ORIGIN + pathname},
            "viewport": {
                "inner_width": 1534,
                "inner_height": 911,
                "device_pixel_ratio": 1,
                "scroll_x": 0,
                "scroll_y": 0,
            },
            "elements": list(elements),
            "catalogs": list(catalogs),
        },
    )

    _write_json(
        capture_dir / "state_observation.json",
        {
            "schema_version": 1,
            "state": functional_state,
            "fingerprint": "fingerprint-" + capture_id,
        },
    )

    return capture_dir


def _setup(tmp_path, *, before_elements=(), after_elements=(),
           before_catalogs=(), after_catalogs=()):
    observation_store = AutoTwinObservationStore(path=tmp_path / "observation_state.json")
    site = _site()

    _observe(observation_store, site, capture_id="cap-A", fingerprint="fp-a")
    _observe(observation_store, site, capture_id="cap-B", fingerprint="fp-b")

    capture_root = tmp_path / "site_architecture"

    _write_capture(
        capture_root,
        capture_id="cap-A",
        elements=before_elements,
        catalogs=before_catalogs,
    )

    _write_capture(
        capture_root,
        capture_id="cap-B",
        elements=after_elements,
        catalogs=after_catalogs,
    )

    state_key = next(iter(observation_store.snapshot()["twins"]["twin-a"]["states"]))

    evidence_store = ContractWatcherEvidenceStore(root=tmp_path / "evidence")
    history_store = ContractWatcherHistoryStore(root=tmp_path / "evidence")

    return observation_store, capture_root, state_key, evidence_store, history_store


# ---------------------------------------------------------------------------
# Pure classifier.
# ---------------------------------------------------------------------------


def _base_evidence(**overrides):
    evidence = {
        "inconclusive": False,
        "elements": (),
        "catalog_diff": {
            "catalogs_added": [],
            "catalogs_removed": [],
            "option_changes": [],
        },
        "fingerprint_changed": False,
        "page_changed": False,
    }
    evidence.update(overrides)
    return evidence


def test_classify_reports_no_drift_when_nothing_changed():
    result = classify_differential_change_categories(_base_evidence())

    assert result["result"] == DIFFERENTIAL_CHANGE_RESULT_NO_DRIFT
    assert result["categories"] == ()
    assert result["category_evidence"] == {}


def test_classify_inconclusive_stays_explicit_unknown():
    result = classify_differential_change_categories(
        _base_evidence(inconclusive=True, page_changed=True)
    )

    assert result["result"] == DIFFERENTIAL_CHANGE_RESULT_UNKNOWN
    assert result["categories"] == ()
    assert result["category_evidence"] == {}


def test_classify_detects_structural_from_added_element():
    evidence = _base_evidence(
        elements=[{"change": "ADDED", "changes": [], "identity": ["main", "#a"]}],
    )

    result = classify_differential_change_categories(evidence)

    assert result["result"] == DIFFERENTIAL_CHANGE_RESULT_CLASSIFIED
    assert result["categories"] == (DIFFERENTIAL_CHANGE_CATEGORY_STRUCTURAL,)
    assert result["category_evidence"][DIFFERENTIAL_CHANGE_CATEGORY_STRUCTURAL][
        "elements_added"
    ] == 1


def test_classify_detects_interaction_from_changed_element():
    evidence = _base_evidence(
        elements=[{
            "change": "CHANGED",
            "changes": ["INTERACTION_CHANGED"],
            "identity": ["main", "#a"],
        }],
    )

    result = classify_differential_change_categories(evidence)

    assert result["categories"] == (DIFFERENTIAL_CHANGE_CATEGORY_INTERACTION,)


def test_classify_detects_resource_from_catalog_option_change():
    evidence = _base_evidence(
        catalog_diff={
            "catalogs_added": [],
            "catalogs_removed": [],
            "option_changes": [{
                "catalog_key": "main::#province",
                "options_added": [["2", "Two", False]],
                "options_removed": [],
                "options_reordered": False,
            }],
        },
    )

    result = classify_differential_change_categories(evidence)

    assert result["categories"] == (DIFFERENTIAL_CHANGE_CATEGORY_RESOURCE,)


def test_classify_detects_state_transition_from_fingerprint_change():
    evidence = _base_evidence(
        fingerprint_changed=True,
        before_functional_fingerprint="fp-before",
        after_functional_fingerprint="fp-after",
    )

    result = classify_differential_change_categories(evidence)

    assert result["categories"] == (DIFFERENTIAL_CHANGE_CATEGORY_STATE_TRANSITION,)
    assert result["category_evidence"][DIFFERENTIAL_CHANGE_CATEGORY_STATE_TRANSITION] == {
        "before_functional_fingerprint": "fp-before",
        "after_functional_fingerprint": "fp-after",
    }


def test_classify_combines_multiple_categories_in_canonical_order():
    evidence = _base_evidence(
        elements=[{
            "change": "CHANGED",
            "changes": ["INTERACTION_CHANGED"],
            "identity": ["main", "#a"],
        }],
        fingerprint_changed=True,
    )

    result = classify_differential_change_categories(evidence)

    assert result["categories"] == (
        DIFFERENTIAL_CHANGE_CATEGORY_INTERACTION,
        DIFFERENTIAL_CHANGE_CATEGORY_STATE_TRANSITION,
    )


def test_classify_fails_closed_on_malformed_input():
    with pytest.raises(TypeError):
        classify_differential_change_categories("not-a-dict")

    with pytest.raises(ValueError):
        classify_differential_change_categories({"inconclusive": False})


# ---------------------------------------------------------------------------
# AUTO-TWIN bridge: ACTIVE baseline vs latest REAL observation.
# ---------------------------------------------------------------------------


def test_skips_when_state_not_yet_baselined(tmp_path):
    observation_store = AutoTwinObservationStore(path=tmp_path / "observation_state.json")

    result = build_differential_change_evidence_for_twin_state(
        observation_store,
        twin_key="twin-a",
        state_key="never-observed",
        confirmation_policy=_policy(),
        capture_root=tmp_path / "site_architecture",
    )

    assert result["result"] == DIFFERENTIAL_CHANGE_RESULT_SKIPPED
    assert result["reason"] == CONTRACT_WATCHER_SELECTOR_SKIP_STATE_NOT_BASELINED
    assert result["contract_key"] == contract_watcher_observation_contract_key(
        "twin-a", "never-observed"
    )


def test_skips_when_nothing_new_since_baseline(tmp_path):
    observation_store = AutoTwinObservationStore(path=tmp_path / "observation_state.json")
    site = _site()

    _observe(observation_store, site, capture_id="cap-A", fingerprint="fp-a")

    state_key = next(iter(observation_store.snapshot()["twins"]["twin-a"]["states"]))

    result = build_differential_change_evidence_for_twin_state(
        observation_store,
        twin_key="twin-a",
        state_key=state_key,
        confirmation_policy=_policy(),
        capture_root=tmp_path / "site_architecture",
    )

    assert result["result"] == DIFFERENTIAL_CHANGE_RESULT_SKIPPED
    assert result["reason"] == CONTRACT_WATCHER_SELECTOR_SKIP_NOTHING_TO_COMPARE


def test_structural_drift_detected_against_active_baseline(tmp_path):
    before = [_element("#a")]
    after = [_element("#a"), _element("#b")]

    observation_store, capture_root, state_key, evidence_store, history_store = _setup(
        tmp_path, before_elements=before, after_elements=after,
    )

    result = build_differential_change_evidence_for_twin_state(
        observation_store,
        twin_key="twin-a",
        state_key=state_key,
        confirmation_policy=_policy(),
        capture_root=capture_root,
        evidence_store=evidence_store,
        history_store=history_store,
    )

    assert result["result"] == DIFFERENTIAL_CHANGE_RESULT_CLASSIFIED
    assert result["categories"] == (DIFFERENTIAL_CHANGE_CATEGORY_STRUCTURAL,)
    assert result["watch_state"] == ContractWatchState.CHANGE_SUSPECTED.value
    assert result["cycle_outcome"] == ContractWatcherCycleOutcome.OBSERVATION_REGISTERED.value
    assert result["baseline_capture_id"] == "cap-A"
    assert result["observation_capture_id"] == "cap-B"


def test_interaction_drift_detected_against_active_baseline(tmp_path):
    before = [_element("#a", disabled=False)]
    after = [_element("#a", disabled=True)]

    observation_store, capture_root, state_key, evidence_store, history_store = _setup(
        tmp_path, before_elements=before, after_elements=after,
    )

    result = build_differential_change_evidence_for_twin_state(
        observation_store,
        twin_key="twin-a",
        state_key=state_key,
        confirmation_policy=_policy(),
        capture_root=capture_root,
        evidence_store=evidence_store,
        history_store=history_store,
    )

    assert result["categories"] == (DIFFERENTIAL_CHANGE_CATEGORY_INTERACTION,)


def test_resource_drift_detected_from_catalog_option_change(tmp_path):
    elements = [_element("#a")]

    before_catalogs = [_catalog("province", options=[{"value": "1", "label": "One"}])]
    after_catalogs = [_catalog("province", options=[
        {"value": "1", "label": "One"},
        {"value": "2", "label": "Two"},
    ])]

    observation_store, capture_root, state_key, evidence_store, history_store = _setup(
        tmp_path,
        before_elements=elements,
        after_elements=elements,
        before_catalogs=before_catalogs,
        after_catalogs=after_catalogs,
    )

    result = build_differential_change_evidence_for_twin_state(
        observation_store,
        twin_key="twin-a",
        state_key=state_key,
        confirmation_policy=_policy(),
        capture_root=capture_root,
        evidence_store=evidence_store,
        history_store=history_store,
    )

    assert result["categories"] == (DIFFERENTIAL_CHANGE_CATEGORY_RESOURCE,)


def test_state_transition_drift_detected_from_active_ui_region(tmp_path):
    before = [_element("#tab", class_token="tab-default")]
    after = [_element("#tab", class_token="tab-active")]

    observation_store, capture_root, state_key, evidence_store, history_store = _setup(
        tmp_path, before_elements=before, after_elements=after,
    )

    result = build_differential_change_evidence_for_twin_state(
        observation_store,
        twin_key="twin-a",
        state_key=state_key,
        confirmation_policy=_policy(),
        capture_root=capture_root,
        evidence_store=evidence_store,
        history_store=history_store,
    )

    assert result["categories"] == (DIFFERENTIAL_CHANGE_CATEGORY_STATE_TRANSITION,)


def test_no_drift_when_captures_are_structurally_identical(tmp_path):
    elements = [_element("#a")]

    observation_store, capture_root, state_key, evidence_store, history_store = _setup(
        tmp_path, before_elements=elements, after_elements=elements,
    )

    result = build_differential_change_evidence_for_twin_state(
        observation_store,
        twin_key="twin-a",
        state_key=state_key,
        confirmation_policy=_policy(),
        capture_root=capture_root,
        evidence_store=evidence_store,
        history_store=history_store,
    )

    assert result["result"] == DIFFERENTIAL_CHANGE_RESULT_NO_DRIFT
    assert result["categories"] == ()
    assert result["watch_state"] == ContractWatchState.NO_CHANGE.value


def test_re_observation_is_idempotent(tmp_path):
    before = [_element("#a")]
    after = [_element("#a"), _element("#b")]

    observation_store, capture_root, state_key, evidence_store, history_store = _setup(
        tmp_path, before_elements=before, after_elements=after,
    )

    first = build_differential_change_evidence_for_twin_state(
        observation_store,
        twin_key="twin-a",
        state_key=state_key,
        confirmation_policy=_policy(),
        capture_root=capture_root,
        evidence_store=evidence_store,
        history_store=history_store,
    )

    second = build_differential_change_evidence_for_twin_state(
        observation_store,
        twin_key="twin-a",
        state_key=state_key,
        confirmation_policy=_policy(),
        capture_root=capture_root,
        evidence_store=evidence_store,
        history_store=history_store,
    )

    assert first["evidence_id"] == second["evidence_id"]
    assert first["categories"] == second["categories"]
    assert first["cycle_outcome"] == ContractWatcherCycleOutcome.OBSERVATION_REGISTERED.value
    assert second["cycle_outcome"] == ContractWatcherCycleOutcome.OBSERVATION_REPLAYED.value


def test_never_mutates_observation_store_or_promotes_active(tmp_path):
    before = [_element("#a")]
    after = [_element("#a"), _element("#b")]

    observation_store, capture_root, state_key, evidence_store, history_store = _setup(
        tmp_path, before_elements=before, after_elements=after,
    )

    before_snapshot = observation_store.snapshot()

    build_differential_change_evidence_for_twin_state(
        observation_store,
        twin_key="twin-a",
        state_key=state_key,
        confirmation_policy=_policy(),
        capture_root=capture_root,
        evidence_store=evidence_store,
        history_store=history_store,
    )

    after_snapshot = observation_store.snapshot()

    assert before_snapshot == after_snapshot

    state = after_snapshot["twins"]["twin-a"]["states"][state_key]

    # ACTIVE baseline is never advanced by this bridge.
    assert state["baseline_capture_id"] == "cap-A"


def test_stable_identity_linkage_matches_selector_convention(tmp_path):
    before = [_element("#a")]
    after = [_element("#a"), _element("#b")]

    observation_store, capture_root, state_key, evidence_store, history_store = _setup(
        tmp_path, before_elements=before, after_elements=after,
    )

    result = build_differential_change_evidence_for_twin_state(
        observation_store,
        twin_key="twin-a",
        state_key=state_key,
        confirmation_policy=_policy(),
        capture_root=capture_root,
        evidence_store=evidence_store,
        history_store=history_store,
    )

    assert result["contract_key"] == contract_watcher_observation_contract_key(
        "twin-a", state_key
    )
