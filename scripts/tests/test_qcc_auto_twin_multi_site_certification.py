import pytest

from backend.qcc.auto_twin import (
    AUTO_TWIN_CAPABILITY_GOVERNED_EXPLORATION_READINESS,
    AUTO_TWIN_CAPABILITY_NETWORK_LOCAL_SAFETY,
    AUTO_TWIN_CAPABILITY_STRUCTURAL_FIDELITY,
    AUTO_TWIN_CAPABILITY_TRANSITION_BEHAVIOR_FIDELITY,
    AUTO_TWIN_CERTIFICATION_BATCH_MEMBER_REASON_RECORD_MISSING,
    AUTO_TWIN_CERTIFICATION_CAPABILITIES,
    AUTO_TWIN_CERTIFICATION_STATUS_FAIL,
    AUTO_TWIN_CERTIFICATION_STATUS_NOT_SUPPORTED,
    AUTO_TWIN_CERTIFICATION_STATUS_PASS,
    AUTO_TWIN_CERTIFICATION_STATUS_UNRESOLVED,
    AUTO_TWIN_VALIDATION_DIMENSIONS,
    AutoTwinCandidateRevisionStore,
    AutoTwinManagedSite,
    AutoTwinValidationEvidenceStore,
    build_auto_twin_profile_policy,
    build_auto_twin_validation_evidence,
    build_multi_site_certification,
    build_multi_site_certification_batch,
)

from backend.qcc.auto_twin.exploration_candidate_planner import (
    plan_exploration_candidates,
)
from backend.qcc.auto_twin.navigation_transition_validation_store import (
    AutoTwinNavigationTransitionValidationStore,
)
from backend.qcc.auto_twin.observation_store import AutoTwinObservationStore


TWIN_KEY = "mercurio"
SITE_CODE = "MERCURIO"
REVISION_ID = "matrev-test"
ORIGIN = "https://mercurio.delegaciondelgobierno.gob.es"

SITE_B_TWIN_KEY = "red_sara"
SITE_B_SITE_CODE = "RED_SARA"
SITE_B_ORIGIN = "https://sede.redsara.gob.es"


def _managed_site(twin_key=TWIN_KEY, site_code=SITE_CODE):
    return AutoTwinManagedSite(
        twin_key=twin_key,
        site_code=site_code,
        origins=(ORIGIN,),
        path_prefixes=("/mercurio",),
    )


def _candidate_store(tmp_path):
    store = AutoTwinCandidateRevisionStore(path=tmp_path / "candidates.json")

    created = store.record_changed_observation(
        _managed_site(),
        {
            "classification": "CHANGED",
            "capture_id": "capture-real",
            "observed_at": "2026-09-05T10:00:00+00:00",
            "browser_profile_key": "mercurio_assisted",
            "pathname": "/mercurio/page.html",
            "functional_state": "FORM",
            "state_key": "state-key",
            "fingerprint": "fp-new",
            "baseline_fingerprint": "fp-old",
            "baseline_capture_id": "capture-baseline",
        },
    )

    return store, created["candidate"]["candidate_id"]


def _evidence_store(tmp_path):
    return AutoTwinValidationEvidenceStore(
        path=tmp_path / "validation_evidence.json"
    )


def _navigation_store(tmp_path):
    return AutoTwinNavigationTransitionValidationStore(
        path=tmp_path / "navigation_transition_validation.json"
    )


def _checks(status="PASS"):
    return {
        dimension: {"status": status}
        for dimension in AUTO_TWIN_VALIDATION_DIMENSIONS
    }


def _record_fidelity_evidence(
    evidence_store, *, candidate_id, candidate_revision, status="PASS"
):
    evidence = build_auto_twin_validation_evidence(
        twin_key=TWIN_KEY,
        candidate_id=candidate_id,
        candidate_revision=candidate_revision,
        real_capture_id="capture-real",
        twin_capture_id="capture-twin",
        pathname="/mercurio/page.html",
        functional_state="FORM",
        rendering_profile_id="profile-1",
        checks=_checks(status),
    )

    evidence_store.record_validation_evidence(evidence)


def _record_navigation_validated(
    navigation_store, *, candidate_id, revision_id=REVISION_ID
):
    navigation_store.record_twin_validated(
        {
            "status": "TWIN_VALIDATED",
            "reason": "EXACT_LOCAL_TARGET_REACHED",
            "twin_key": TWIN_KEY,
            "revision_id": revision_id,
            "candidate_id": candidate_id,
            "before_state_id": "AUTO_A",
            "after_state_id": "AUTO_B",
            "selector": 'a[onclick="continuar()"]',
            "expected_runtime_entry": "states/01-AUTO_B/runtime/index.html",
            "location": {
                "href": (
                    "http://127.0.0.1:45678/states/01-AUTO_B/runtime/"
                    "index.html"
                ),
                "pathname": "/states/01-AUTO_B/runtime/index.html",
            },
        }
    )


def _write_runtime_html(
    materialized_root,
    *,
    revision_id=REVISION_ID,
    content="<html><body>sterile</body></html>",
):
    runtime_root = materialized_root / TWIN_KEY / revision_id / "runtime"
    runtime_root.mkdir(parents=True)
    (runtime_root / "index.html").write_text(content, encoding="utf-8")
    return runtime_root


def _record_all_clean_evidence(
    *, candidate_id, evidence_store, navigation_store, materialized_root
):
    _record_fidelity_evidence(
        evidence_store, candidate_id=candidate_id, candidate_revision=1
    )
    _record_navigation_validated(navigation_store, candidate_id=candidate_id)
    _write_runtime_html(materialized_root)


def _discovery_policy():
    return build_auto_twin_profile_policy("twin_discovery")


def _observer_policy():
    return build_auto_twin_profile_policy("mercurio_assisted")


def _exploration_plan_with_candidates(tmp_path, *, count=1):
    observation_store = AutoTwinObservationStore(
        path=tmp_path / "observation_state.json"
    )

    site = _managed_site()

    observation_store.observe(
        site,
        capture_id="capture-explore",
        observed_at="2026-01-01T00:00:00.000000Z",
        browser_profile_key="mercurio_discovery",
        url=ORIGIN + "/mercurio/page.html",
        site_code=site.site_code,
        state_observation={"state": "FORM", "fingerprint": "fp-explore"},
    )

    inventory = {
        "fp-explore": tuple(
            {
                "kind": "SELECT",
                "policy": "STATE_CHANGE_CANDIDATE",
                "selector": f"#field-{index}",
                "frame_path": "main",
                "semantics": (),
                "interaction": {
                    "visible": True,
                    "disabled": False,
                    "interactable": True,
                },
                "element": {
                    "tag": "select",
                    "id": f"field-{index}",
                    "name": "",
                    "type": "",
                    "role": "",
                },
                "navigation": {"href": None, "target": None},
            }
            for index in range(count)
        )
    }

    empty_graph = {
        "schema_version": 1,
        "graph_type": "QCC_NAVIGATION_GRAPH",
        "observation_count": 0,
        "changed_observation_count": 0,
        "node_count": 0,
        "edge_count": 0,
        "nodes": (),
        "edges": (),
    }

    return plan_exploration_candidates(
        observation_store=observation_store,
        twin_key=TWIN_KEY,
        profile_policy=_discovery_policy(),
        navigation_graph=empty_graph,
        action_inventory_by_fingerprint=inventory,
        source_fingerprint="fp-explore",
    )


def _build_passing_certification_record(
    tmp_path, *, twin_key, site_code, origin, revision_id=REVISION_ID
):
    """Builds a full, independently-governed UWT-12A PASS record for an
    arbitrary managed site -- used only to exercise UWT-12B's
    composition over several already-built per-site records."""

    site = AutoTwinManagedSite(
        twin_key=twin_key,
        site_code=site_code,
        origins=(origin,),
        path_prefixes=(f"/{twin_key}",),
    )

    candidate_store = AutoTwinCandidateRevisionStore(
        path=tmp_path / "candidates.json"
    )
    created = candidate_store.record_changed_observation(
        site,
        {
            "classification": "CHANGED",
            "capture_id": "capture-real",
            "observed_at": "2026-09-05T10:00:00+00:00",
            "browser_profile_key": f"{twin_key}_assisted",
            "pathname": f"/{twin_key}/page.html",
            "functional_state": "FORM",
            "state_key": "state-key",
            "fingerprint": "fp-new",
            "baseline_fingerprint": "fp-old",
            "baseline_capture_id": "capture-baseline",
        },
    )
    candidate_id = created["candidate"]["candidate_id"]

    evidence_store = AutoTwinValidationEvidenceStore(
        path=tmp_path / "validation_evidence.json"
    )
    evidence_store.record_validation_evidence(
        build_auto_twin_validation_evidence(
            twin_key=twin_key,
            candidate_id=candidate_id,
            candidate_revision=1,
            real_capture_id="capture-real",
            twin_capture_id="capture-twin",
            pathname=f"/{twin_key}/page.html",
            functional_state="FORM",
            rendering_profile_id="profile-1",
            checks=_checks("PASS"),
        )
    )

    navigation_store = AutoTwinNavigationTransitionValidationStore(
        path=tmp_path / "navigation_transition_validation.json"
    )
    navigation_store.record_twin_validated(
        {
            "status": "TWIN_VALIDATED",
            "reason": "EXACT_LOCAL_TARGET_REACHED",
            "twin_key": twin_key,
            "revision_id": revision_id,
            "candidate_id": candidate_id,
            "before_state_id": "AUTO_A",
            "after_state_id": "AUTO_B",
            "selector": 'a[onclick="continuar()"]',
            "expected_runtime_entry": "states/01-AUTO_B/runtime/index.html",
            "location": {
                "href": (
                    "http://127.0.0.1:45678/states/01-AUTO_B/runtime/"
                    "index.html"
                ),
                "pathname": "/states/01-AUTO_B/runtime/index.html",
            },
        }
    )

    runtime_root = tmp_path / twin_key / revision_id / "runtime"
    runtime_root.mkdir(parents=True)
    (runtime_root / "index.html").write_text(
        "<html><body>sterile</body></html>", encoding="utf-8"
    )

    observation_store = AutoTwinObservationStore(
        path=tmp_path / "observation_state.json"
    )
    observation_store.observe(
        site,
        capture_id="capture-explore",
        observed_at="2026-01-01T00:00:00.000000Z",
        browser_profile_key=f"{twin_key}_discovery",
        url=origin + f"/{twin_key}/page.html",
        site_code=site.site_code,
        state_observation={"state": "FORM", "fingerprint": "fp-explore"},
    )

    inventory = {
        "fp-explore": (
            {
                "kind": "SELECT",
                "policy": "STATE_CHANGE_CANDIDATE",
                "selector": "#field-0",
                "frame_path": "main",
                "semantics": (),
                "interaction": {
                    "visible": True,
                    "disabled": False,
                    "interactable": True,
                },
                "element": {
                    "tag": "select",
                    "id": "field-0",
                    "name": "",
                    "type": "",
                    "role": "",
                },
                "navigation": {"href": None, "target": None},
            },
        )
    }

    empty_graph = {
        "schema_version": 1,
        "graph_type": "QCC_NAVIGATION_GRAPH",
        "observation_count": 0,
        "changed_observation_count": 0,
        "node_count": 0,
        "edge_count": 0,
        "nodes": (),
        "edges": (),
    }

    plan = plan_exploration_candidates(
        observation_store=observation_store,
        twin_key=twin_key,
        profile_policy=_discovery_policy(),
        navigation_graph=empty_graph,
        action_inventory_by_fingerprint=inventory,
        source_fingerprint="fp-explore",
    )

    return build_multi_site_certification(
        managed_site=site,
        twin_key=twin_key,
        candidate_id=candidate_id,
        candidate_store=candidate_store,
        evidence_store=evidence_store,
        profile_policy=_discovery_policy(),
        navigation_validation_store=navigation_store,
        materialized_revision_id=revision_id,
        materialized_root=tmp_path,
        exploration_plan=plan,
    )


def test_certification_unresolved_without_any_evidence(tmp_path):
    candidate_store, candidate_id = _candidate_store(tmp_path)
    evidence_store = _evidence_store(tmp_path)
    navigation_store = _navigation_store(tmp_path)

    record = build_multi_site_certification(
        managed_site=_managed_site(),
        twin_key=TWIN_KEY,
        candidate_id=candidate_id,
        candidate_store=candidate_store,
        evidence_store=evidence_store,
        profile_policy=_discovery_policy(),
        navigation_validation_store=navigation_store,
        materialized_root=tmp_path,
    )

    assert record["certification_verdict"] == (
        AUTO_TWIN_CERTIFICATION_STATUS_UNRESOLVED
    )
    assert record["certifiable"] is False

    for capability in AUTO_TWIN_CERTIFICATION_CAPABILITIES:
        assert record["capability_matrix"][capability]["status"] == (
            AUTO_TWIN_CERTIFICATION_STATUS_UNRESOLVED
        )


def test_certification_passes_when_all_capabilities_pass(tmp_path):
    candidate_store, candidate_id = _candidate_store(tmp_path)
    evidence_store = _evidence_store(tmp_path)
    navigation_store = _navigation_store(tmp_path)

    _record_all_clean_evidence(
        candidate_id=candidate_id,
        evidence_store=evidence_store,
        navigation_store=navigation_store,
        materialized_root=tmp_path,
    )

    plan = _exploration_plan_with_candidates(tmp_path, count=1)

    record = build_multi_site_certification(
        managed_site=_managed_site(),
        twin_key=TWIN_KEY,
        candidate_id=candidate_id,
        candidate_store=candidate_store,
        evidence_store=evidence_store,
        profile_policy=_discovery_policy(),
        navigation_validation_store=navigation_store,
        materialized_revision_id=REVISION_ID,
        materialized_root=tmp_path,
        exploration_plan=plan,
    )

    assert record["certification_verdict"] == (
        AUTO_TWIN_CERTIFICATION_STATUS_PASS
    )
    assert record["certifiable"] is True

    assert record["structural_fidelity_status"] == (
        AUTO_TWIN_CERTIFICATION_STATUS_PASS
    )
    assert record["transition_behavior_fidelity_status"] == (
        AUTO_TWIN_CERTIFICATION_STATUS_PASS
    )
    assert record["network_local_safety_status"] == (
        AUTO_TWIN_CERTIFICATION_STATUS_PASS
    )
    assert record["governed_exploration_readiness_status"] == (
        AUTO_TWIN_CERTIFICATION_STATUS_PASS
    )

    assert record["evidence"]["exploration_plan_id"] == plan["plan_id"]


def test_certification_fails_when_network_safety_leaks(tmp_path):
    candidate_store, candidate_id = _candidate_store(tmp_path)
    evidence_store = _evidence_store(tmp_path)
    navigation_store = _navigation_store(tmp_path)

    _record_fidelity_evidence(
        evidence_store, candidate_id=candidate_id, candidate_revision=1
    )
    _record_navigation_validated(navigation_store, candidate_id=candidate_id)
    _write_runtime_html(
        tmp_path,
        content=(
            '<html><body><a href="https://real.example.com/leak">leak'
            "</a></body></html>"
        ),
    )

    plan = _exploration_plan_with_candidates(tmp_path, count=1)

    record = build_multi_site_certification(
        managed_site=_managed_site(),
        twin_key=TWIN_KEY,
        candidate_id=candidate_id,
        candidate_store=candidate_store,
        evidence_store=evidence_store,
        profile_policy=_discovery_policy(),
        navigation_validation_store=navigation_store,
        materialized_revision_id=REVISION_ID,
        materialized_root=tmp_path,
        exploration_plan=plan,
    )

    assert record["certification_verdict"] == (
        AUTO_TWIN_CERTIFICATION_STATUS_FAIL
    )
    assert record["certifiable"] is False
    assert record["network_local_safety_status"] == (
        AUTO_TWIN_CERTIFICATION_STATUS_FAIL
    )


def test_certification_not_supported_when_discovery_profile_inactive(
    tmp_path,
):
    candidate_store, candidate_id = _candidate_store(tmp_path)
    evidence_store = _evidence_store(tmp_path)
    navigation_store = _navigation_store(tmp_path)

    _record_all_clean_evidence(
        candidate_id=candidate_id,
        evidence_store=evidence_store,
        navigation_store=navigation_store,
        materialized_root=tmp_path,
    )

    record = build_multi_site_certification(
        managed_site=_managed_site(),
        twin_key=TWIN_KEY,
        candidate_id=candidate_id,
        candidate_store=candidate_store,
        evidence_store=evidence_store,
        profile_policy=_observer_policy(),
        navigation_validation_store=navigation_store,
        materialized_revision_id=REVISION_ID,
        materialized_root=tmp_path,
    )

    assert record["governed_exploration_readiness_status"] == (
        AUTO_TWIN_CERTIFICATION_STATUS_NOT_SUPPORTED
    )
    assert record["certification_verdict"] == (
        AUTO_TWIN_CERTIFICATION_STATUS_NOT_SUPPORTED
    )
    assert record["certifiable"] is False


def test_exploration_readiness_fails_when_plan_has_no_candidates(tmp_path):
    candidate_store, candidate_id = _candidate_store(tmp_path)
    evidence_store = _evidence_store(tmp_path)
    navigation_store = _navigation_store(tmp_path)

    _record_all_clean_evidence(
        candidate_id=candidate_id,
        evidence_store=evidence_store,
        navigation_store=navigation_store,
        materialized_root=tmp_path,
    )

    plan = _exploration_plan_with_candidates(tmp_path, count=0)

    record = build_multi_site_certification(
        managed_site=_managed_site(),
        twin_key=TWIN_KEY,
        candidate_id=candidate_id,
        candidate_store=candidate_store,
        evidence_store=evidence_store,
        profile_policy=_discovery_policy(),
        navigation_validation_store=navigation_store,
        materialized_revision_id=REVISION_ID,
        materialized_root=tmp_path,
        exploration_plan=plan,
    )

    assert record["governed_exploration_readiness_status"] == (
        AUTO_TWIN_CERTIFICATION_STATUS_FAIL
    )
    assert record["certification_verdict"] == (
        AUTO_TWIN_CERTIFICATION_STATUS_FAIL
    )


def test_certification_id_is_deterministic(tmp_path):
    candidate_store, candidate_id = _candidate_store(tmp_path)
    evidence_store = _evidence_store(tmp_path)
    navigation_store = _navigation_store(tmp_path)

    _record_all_clean_evidence(
        candidate_id=candidate_id,
        evidence_store=evidence_store,
        navigation_store=navigation_store,
        materialized_root=tmp_path,
    )

    plan = _exploration_plan_with_candidates(tmp_path, count=1)

    kwargs = dict(
        managed_site=_managed_site(),
        twin_key=TWIN_KEY,
        candidate_id=candidate_id,
        candidate_store=candidate_store,
        evidence_store=evidence_store,
        profile_policy=_discovery_policy(),
        navigation_validation_store=navigation_store,
        materialized_revision_id=REVISION_ID,
        materialized_root=tmp_path,
        exploration_plan=plan,
    )

    first = build_multi_site_certification(**kwargs)
    second = build_multi_site_certification(**kwargs)

    assert first["certification_id"] == second["certification_id"]
    assert len(first["certification_id"]) == 64


def test_certification_never_mutates_candidate_lifecycle(tmp_path):
    candidate_store, candidate_id = _candidate_store(tmp_path)
    evidence_store = _evidence_store(tmp_path)
    navigation_store = _navigation_store(tmp_path)

    _record_all_clean_evidence(
        candidate_id=candidate_id,
        evidence_store=evidence_store,
        navigation_store=navigation_store,
        materialized_root=tmp_path,
    )

    plan = _exploration_plan_with_candidates(tmp_path, count=1)

    before = candidate_store.get_candidate(TWIN_KEY, candidate_id)

    record = build_multi_site_certification(
        managed_site=_managed_site(),
        twin_key=TWIN_KEY,
        candidate_id=candidate_id,
        candidate_store=candidate_store,
        evidence_store=evidence_store,
        profile_policy=_discovery_policy(),
        navigation_validation_store=navigation_store,
        materialized_revision_id=REVISION_ID,
        materialized_root=tmp_path,
        exploration_plan=plan,
    )

    after = candidate_store.get_candidate(TWIN_KEY, candidate_id)

    assert record["certification_verdict"] == (
        AUTO_TWIN_CERTIFICATION_STATUS_PASS
    )
    assert before == after


def test_certification_raises_on_site_twin_mismatch(tmp_path):
    candidate_store, candidate_id = _candidate_store(tmp_path)
    evidence_store = _evidence_store(tmp_path)
    navigation_store = _navigation_store(tmp_path)

    other_site = _managed_site(twin_key="other-twin", site_code="OTHER")

    with pytest.raises(ValueError):
        build_multi_site_certification(
            managed_site=other_site,
            twin_key=TWIN_KEY,
            candidate_id=candidate_id,
            candidate_store=candidate_store,
            evidence_store=evidence_store,
            profile_policy=_discovery_policy(),
            navigation_validation_store=navigation_store,
            materialized_root=tmp_path,
        )


def test_certification_raises_for_unknown_candidate(tmp_path):
    candidate_store, _ = _candidate_store(tmp_path)
    evidence_store = _evidence_store(tmp_path)
    navigation_store = _navigation_store(tmp_path)

    with pytest.raises(ValueError):
        build_multi_site_certification(
            managed_site=_managed_site(),
            twin_key=TWIN_KEY,
            candidate_id="does-not-exist",
            candidate_store=candidate_store,
            evidence_store=evidence_store,
            profile_policy=_discovery_policy(),
            navigation_validation_store=navigation_store,
            materialized_root=tmp_path,
        )


def test_capability_matrix_keys_are_fixed(tmp_path):
    candidate_store, candidate_id = _candidate_store(tmp_path)
    evidence_store = _evidence_store(tmp_path)
    navigation_store = _navigation_store(tmp_path)

    record = build_multi_site_certification(
        managed_site=_managed_site(),
        twin_key=TWIN_KEY,
        candidate_id=candidate_id,
        candidate_store=candidate_store,
        evidence_store=evidence_store,
        profile_policy=_discovery_policy(),
        navigation_validation_store=navigation_store,
        materialized_root=tmp_path,
    )

    assert set(record["capability_matrix"]) == {
        AUTO_TWIN_CAPABILITY_STRUCTURAL_FIDELITY,
        AUTO_TWIN_CAPABILITY_TRANSITION_BEHAVIOR_FIDELITY,
        AUTO_TWIN_CAPABILITY_NETWORK_LOCAL_SAFETY,
        AUTO_TWIN_CAPABILITY_GOVERNED_EXPLORATION_READINESS,
    }

    assert record["site_identity"]["twin_key"] == TWIN_KEY
    assert record["site_identity"]["site_code"] == SITE_CODE

    assert record["twin_revision_identity"]["candidate_id"] == candidate_id
    assert record["twin_revision_identity"]["candidate_revision"] == 1


# ---------------------------------------------------------------------------
# UWT-12B: multi-site certification batch
# ---------------------------------------------------------------------------


def test_batch_passes_when_every_required_member_passes(tmp_path):
    record_a = _build_passing_certification_record(
        tmp_path / "site-a",
        twin_key=TWIN_KEY,
        site_code=SITE_CODE,
        origin=ORIGIN,
    )
    record_b = _build_passing_certification_record(
        tmp_path / "site-b",
        twin_key=SITE_B_TWIN_KEY,
        site_code=SITE_B_SITE_CODE,
        origin=SITE_B_ORIGIN,
    )

    batch = build_multi_site_certification_batch(
        members=[
            {"site_code": SITE_B_SITE_CODE, "certification_record": record_b},
            {"site_code": SITE_CODE, "certification_record": record_a},
        ]
    )

    assert batch["batch_verdict"] == AUTO_TWIN_CERTIFICATION_STATUS_PASS
    assert batch["certifiable"] is True
    assert batch["member_count"] == 2
    assert batch["required_member_count"] == 2
    assert batch["unresolved_members"] == ()

    # Deterministic ordering: always by site_code, regardless of input order.
    assert [member["site_code"] for member in batch["members"]] == [
        SITE_CODE,
        SITE_B_SITE_CODE,
    ]
    assert batch["evidence"]["member_certification_ids"] == (
        record_a["certification_id"],
        record_b["certification_id"],
    )


def test_batch_unresolved_when_required_member_record_missing(tmp_path):
    record_a = _build_passing_certification_record(
        tmp_path / "site-a",
        twin_key=TWIN_KEY,
        site_code=SITE_CODE,
        origin=ORIGIN,
    )

    batch = build_multi_site_certification_batch(
        members=[
            {"site_code": SITE_CODE, "certification_record": record_a},
            {"site_code": SITE_B_SITE_CODE, "certification_record": None},
        ]
    )

    assert batch["batch_verdict"] == (
        AUTO_TWIN_CERTIFICATION_STATUS_UNRESOLVED
    )
    assert batch["certifiable"] is False

    missing_member = next(
        member
        for member in batch["members"]
        if member["site_code"] == SITE_B_SITE_CODE
    )
    assert missing_member["status"] == (
        AUTO_TWIN_CERTIFICATION_STATUS_UNRESOLVED
    )
    assert missing_member["reason"] == (
        AUTO_TWIN_CERTIFICATION_BATCH_MEMBER_REASON_RECORD_MISSING
    )
    assert missing_member["certification_id"] is None

    assert len(batch["unresolved_members"]) == 1
    assert batch["unresolved_members"][0]["site_code"] == SITE_B_SITE_CODE


def test_batch_optional_member_failure_does_not_gate_overall(tmp_path):
    record_a = _build_passing_certification_record(
        tmp_path / "site-a",
        twin_key=TWIN_KEY,
        site_code=SITE_CODE,
        origin=ORIGIN,
    )

    batch = build_multi_site_certification_batch(
        members=[
            {"site_code": SITE_CODE, "certification_record": record_a},
            {
                "site_code": SITE_B_SITE_CODE,
                "certification_record": None,
                "required": False,
            },
        ]
    )

    assert batch["batch_verdict"] == AUTO_TWIN_CERTIFICATION_STATUS_PASS
    assert batch["certifiable"] is True
    assert len(batch["unresolved_members"]) == 1
    assert batch["unresolved_members"][0]["required"] is False


def test_batch_rejects_duplicate_site_code(tmp_path):
    record_a = _build_passing_certification_record(
        tmp_path / "site-a",
        twin_key=TWIN_KEY,
        site_code=SITE_CODE,
        origin=ORIGIN,
    )

    with pytest.raises(ValueError):
        build_multi_site_certification_batch(
            members=[
                {"site_code": SITE_CODE, "certification_record": record_a},
                {"site_code": SITE_CODE, "certification_record": None},
            ]
        )


def test_batch_rejects_duplicate_revision_identity(tmp_path):
    record_a = _build_passing_certification_record(
        tmp_path / "site-a",
        twin_key=TWIN_KEY,
        site_code=SITE_CODE,
        origin=ORIGIN,
    )
    relabeled = dict(record_a)
    relabeled["site_identity"] = dict(record_a["site_identity"])
    relabeled["site_identity"]["site_code"] = SITE_B_SITE_CODE

    with pytest.raises(ValueError):
        build_multi_site_certification_batch(
            members=[
                {"site_code": SITE_CODE, "certification_record": record_a},
                {
                    "site_code": SITE_B_SITE_CODE,
                    "certification_record": relabeled,
                },
            ]
        )


def test_batch_rejects_malformed_record(tmp_path):
    with pytest.raises(ValueError):
        build_multi_site_certification_batch(
            members=[
                {
                    "site_code": SITE_CODE,
                    "certification_record": {"not": "a certification"},
                },
            ]
        )


def test_batch_rejects_site_code_mismatch(tmp_path):
    record_a = _build_passing_certification_record(
        tmp_path / "site-a",
        twin_key=TWIN_KEY,
        site_code=SITE_CODE,
        origin=ORIGIN,
    )

    with pytest.raises(ValueError):
        build_multi_site_certification_batch(
            members=[
                {
                    "site_code": SITE_B_SITE_CODE,
                    "certification_record": record_a,
                },
            ]
        )


def test_batch_requires_at_least_one_required_member(tmp_path):
    record_a = _build_passing_certification_record(
        tmp_path / "site-a",
        twin_key=TWIN_KEY,
        site_code=SITE_CODE,
        origin=ORIGIN,
    )

    with pytest.raises(ValueError):
        build_multi_site_certification_batch(
            members=[
                {
                    "site_code": SITE_CODE,
                    "certification_record": record_a,
                    "required": False,
                },
            ]
        )


def test_batch_rejects_empty_members(tmp_path):
    with pytest.raises(ValueError):
        build_multi_site_certification_batch(members=[])


def test_batch_id_is_deterministic_and_order_independent(tmp_path):
    record_a = _build_passing_certification_record(
        tmp_path / "site-a",
        twin_key=TWIN_KEY,
        site_code=SITE_CODE,
        origin=ORIGIN,
    )
    record_b = _build_passing_certification_record(
        tmp_path / "site-b",
        twin_key=SITE_B_TWIN_KEY,
        site_code=SITE_B_SITE_CODE,
        origin=SITE_B_ORIGIN,
    )

    forward = build_multi_site_certification_batch(
        members=[
            {"site_code": SITE_CODE, "certification_record": record_a},
            {"site_code": SITE_B_SITE_CODE, "certification_record": record_b},
        ]
    )
    reversed_order = build_multi_site_certification_batch(
        members=[
            {"site_code": SITE_B_SITE_CODE, "certification_record": record_b},
            {"site_code": SITE_CODE, "certification_record": record_a},
        ]
    )

    assert forward["certification_batch_id"] == (
        reversed_order["certification_batch_id"]
    )
    assert len(forward["certification_batch_id"]) == 64
