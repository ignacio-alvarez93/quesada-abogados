import pytest

from backend.qcc.auto_twin import (
    AUTO_TWIN_CANDIDATE_STATUS_REJECTED,
    AUTO_TWIN_CANDIDATE_STATUS_VALIDATED,
    AUTO_TWIN_CERTIFICATION_STATUS_FAIL,
    AUTO_TWIN_PROMOTION_READINESS_CHECK_CANDIDATE_CURRENT,
    AUTO_TWIN_PROMOTION_READINESS_CHECK_CAPABILITY_MATRIX,
    AUTO_TWIN_PROMOTION_READINESS_CHECK_IDENTITY_BINDING,
    AUTO_TWIN_PROMOTION_READINESS_CHECK_OVERALL_VERDICT,
    AUTO_TWIN_PROMOTION_READINESS_CHECKS,
    AUTO_TWIN_PROMOTION_READINESS_STATUS_BLOCKED,
    AUTO_TWIN_PROMOTION_READINESS_STATUS_READY,
    AUTO_TWIN_PROMOTION_READINESS_STATUS_UNRESOLVED,
    AUTO_TWIN_VALIDATION_DIMENSIONS,
    AutoTwinCandidateRevisionStore,
    AutoTwinManagedSite,
    AutoTwinValidationEvidenceStore,
    build_auto_twin_profile_policy,
    build_auto_twin_validation_evidence,
    build_multi_site_certification,
    evaluate_multi_site_promotion_readiness,
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


def _managed_site():
    return AutoTwinManagedSite(
        twin_key=TWIN_KEY,
        site_code=SITE_CODE,
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
    evidence_store, *, candidate_id, candidate_revision=1, status="PASS"
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


def _record_navigation_validated(navigation_store, *, candidate_id):
    navigation_store.record_twin_validated(
        {
            "status": "TWIN_VALIDATED",
            "reason": "EXACT_LOCAL_TARGET_REACHED",
            "twin_key": TWIN_KEY,
            "revision_id": REVISION_ID,
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


def _write_runtime_html(materialized_root):
    runtime_root = materialized_root / TWIN_KEY / REVISION_ID / "runtime"
    runtime_root.mkdir(parents=True)
    (runtime_root / "index.html").write_text(
        "<html><body>sterile</body></html>", encoding="utf-8"
    )


def _discovery_policy():
    return build_auto_twin_profile_policy("twin_discovery")


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


def _build_ready_environment(tmp_path):
    candidate_store, candidate_id = _candidate_store(tmp_path)
    evidence_store = _evidence_store(tmp_path)
    navigation_store = _navigation_store(tmp_path)

    _record_fidelity_evidence(evidence_store, candidate_id=candidate_id)
    _record_navigation_validated(navigation_store, candidate_id=candidate_id)
    _write_runtime_html(tmp_path)

    plan = _exploration_plan_with_candidates(tmp_path, count=1)

    certification_record = build_multi_site_certification(
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

    return candidate_store, evidence_store, candidate_id, certification_record


def _evaluate(
    *,
    candidate_store,
    evidence_store,
    candidate_id,
    certification_record,
    candidate_revision=1,
):
    return evaluate_multi_site_promotion_readiness(
        managed_site=_managed_site(),
        twin_key=TWIN_KEY,
        candidate_id=candidate_id,
        candidate_revision=candidate_revision,
        candidate_store=candidate_store,
        evidence_store=evidence_store,
        certification_record=certification_record,
    )


def test_ready_for_human_promotion_when_everything_resolves(tmp_path):
    (
        candidate_store,
        evidence_store,
        candidate_id,
        certification_record,
    ) = _build_ready_environment(tmp_path)

    result = _evaluate(
        candidate_store=candidate_store,
        evidence_store=evidence_store,
        candidate_id=candidate_id,
        certification_record=certification_record,
    )

    assert result["readiness_status"] == (
        AUTO_TWIN_PROMOTION_READINESS_STATUS_READY
    )
    assert result["ready_for_human_promotion"] is True
    assert result["blocking_reasons"] == ()
    assert result["unresolved_reasons"] == ()
    assert result["human_only"] is True

    for check_name in AUTO_TWIN_PROMOTION_READINESS_CHECKS:
        assert result["checks"][check_name]["status"] == "PASS"


def test_unresolved_when_certification_record_missing(tmp_path):
    candidate_store, candidate_id = _candidate_store(tmp_path)
    evidence_store = _evidence_store(tmp_path)

    result = _evaluate(
        candidate_store=candidate_store,
        evidence_store=evidence_store,
        candidate_id=candidate_id,
        certification_record=None,
    )

    assert result["readiness_status"] == (
        AUTO_TWIN_PROMOTION_READINESS_STATUS_UNRESOLVED
    )
    assert result["ready_for_human_promotion"] is False

    for check_name in AUTO_TWIN_PROMOTION_READINESS_CHECKS:
        assert result["checks"][check_name]["status"] == "UNRESOLVED"

    assert len(result["unresolved_reasons"]) == len(
        AUTO_TWIN_PROMOTION_READINESS_CHECKS
    )


def test_blocked_when_certification_verdict_fails(tmp_path):
    candidate_store, candidate_id = _candidate_store(tmp_path)
    evidence_store = _evidence_store(tmp_path)
    navigation_store = _navigation_store(tmp_path)

    _record_fidelity_evidence(evidence_store, candidate_id=candidate_id)
    _record_navigation_validated(navigation_store, candidate_id=candidate_id)

    # No runtime HTML written -> network/local safety section is
    # UNRESOLVED, but we additionally force a FAIL leak scenario to
    # exercise the BLOCKED path explicitly.
    runtime_root = tmp_path / TWIN_KEY / REVISION_ID / "runtime"
    runtime_root.mkdir(parents=True)
    (runtime_root / "index.html").write_text(
        '<html><body><a href="https://real.example.com/leak">leak</a>'
        "</body></html>",
        encoding="utf-8",
    )

    plan = _exploration_plan_with_candidates(tmp_path, count=1)

    certification_record = build_multi_site_certification(
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

    assert certification_record["certification_verdict"] == (
        AUTO_TWIN_CERTIFICATION_STATUS_FAIL
    )

    result = _evaluate(
        candidate_store=candidate_store,
        evidence_store=evidence_store,
        candidate_id=candidate_id,
        certification_record=certification_record,
    )

    assert result["readiness_status"] == (
        AUTO_TWIN_PROMOTION_READINESS_STATUS_BLOCKED
    )
    assert result["ready_for_human_promotion"] is False
    assert (
        result["checks"][
            AUTO_TWIN_PROMOTION_READINESS_CHECK_OVERALL_VERDICT
        ]["status"]
        == "BLOCKED"
    )
    assert "CERTIFICATION_VERDICT_FAIL" in result["blocking_reasons"]
    assert (
        result["checks"][
            AUTO_TWIN_PROMOTION_READINESS_CHECK_CAPABILITY_MATRIX
        ]["status"]
        == "BLOCKED"
    )


def test_blocked_when_candidate_revision_is_stale(tmp_path):
    (
        candidate_store,
        evidence_store,
        candidate_id,
        certification_record,
    ) = _build_ready_environment(tmp_path)

    # A newer observation on the same (state_key, fingerprint pair
    # changed) creates a brand-new candidate -- but to simulate the
    # exact candidate advancing past its certified revision we instead
    # directly bump the stored candidate_revision.
    stored = candidate_store.get_candidate(TWIN_KEY, candidate_id)
    assert stored["candidate_revision"] == 1

    twins = candidate_store._twins  # noqa: SLF001 - test-only inspection
    twins[TWIN_KEY]["candidates"][candidate_id]["candidate_revision"] = 2
    candidate_store._persist(twins=twins, revision=candidate_store.revision + 1)  # noqa: SLF001
    candidate_store._twins = twins  # noqa: SLF001
    candidate_store._revision += 1  # noqa: SLF001

    result = _evaluate(
        candidate_store=candidate_store,
        evidence_store=evidence_store,
        candidate_id=candidate_id,
        certification_record=certification_record,
    )

    assert result["readiness_status"] == (
        AUTO_TWIN_PROMOTION_READINESS_STATUS_BLOCKED
    )
    assert (
        result["checks"][
            AUTO_TWIN_PROMOTION_READINESS_CHECK_CANDIDATE_CURRENT
        ]["status"]
        == "BLOCKED"
    )
    assert "CANDIDATE_REVISION_STALE" in result["blocking_reasons"]


def test_blocked_when_candidate_has_been_rejected(tmp_path):
    (
        candidate_store,
        evidence_store,
        candidate_id,
        certification_record,
    ) = _build_ready_environment(tmp_path)

    candidate_store.transition_candidate_status(
        TWIN_KEY, candidate_id, target_status=AUTO_TWIN_CANDIDATE_STATUS_REJECTED
    )

    result = _evaluate(
        candidate_store=candidate_store,
        evidence_store=evidence_store,
        candidate_id=candidate_id,
        certification_record=certification_record,
    )

    assert result["readiness_status"] == (
        AUTO_TWIN_PROMOTION_READINESS_STATUS_BLOCKED
    )
    assert "CANDIDATE_STATUS_REJECTED" in result["blocking_reasons"]


def test_ready_when_candidate_has_been_validated(tmp_path):
    (
        candidate_store,
        evidence_store,
        candidate_id,
        certification_record,
    ) = _build_ready_environment(tmp_path)

    candidate_store.transition_candidate_status(
        TWIN_KEY, candidate_id, target_status=AUTO_TWIN_CANDIDATE_STATUS_VALIDATED
    )

    result = _evaluate(
        candidate_store=candidate_store,
        evidence_store=evidence_store,
        candidate_id=candidate_id,
        certification_record=certification_record,
    )

    assert result["readiness_status"] == (
        AUTO_TWIN_PROMOTION_READINESS_STATUS_READY
    )


def test_unresolved_when_candidate_not_found_in_store(tmp_path):
    (
        candidate_store,
        evidence_store,
        candidate_id,
        certification_record,
    ) = _build_ready_environment(tmp_path)

    other_store = AutoTwinCandidateRevisionStore(
        path=tmp_path / "other-candidates.json"
    )

    result = _evaluate(
        candidate_store=other_store,
        evidence_store=evidence_store,
        candidate_id=candidate_id,
        certification_record=certification_record,
    )

    assert result["readiness_status"] == (
        AUTO_TWIN_PROMOTION_READINESS_STATUS_UNRESOLVED
    )
    assert "CANDIDATE_NOT_FOUND_IN_STORE" in result["unresolved_reasons"]


def test_unresolved_when_validation_evidence_not_resolvable(tmp_path):
    (
        candidate_store,
        _evidence_store_unused,
        candidate_id,
        certification_record,
    ) = _build_ready_environment(tmp_path)

    empty_evidence_store = AutoTwinValidationEvidenceStore(
        path=tmp_path / "empty_validation_evidence.json"
    )

    result = _evaluate(
        candidate_store=candidate_store,
        evidence_store=empty_evidence_store,
        candidate_id=candidate_id,
        certification_record=certification_record,
    )

    assert result["readiness_status"] == (
        AUTO_TWIN_PROMOTION_READINESS_STATUS_UNRESOLVED
    )
    assert "VALIDATION_EVIDENCE_NOT_FOUND" in result["unresolved_reasons"]


def test_blocked_when_target_identity_does_not_match_certification(tmp_path):
    (
        candidate_store,
        evidence_store,
        candidate_id,
        certification_record,
    ) = _build_ready_environment(tmp_path)

    result = evaluate_multi_site_promotion_readiness(
        managed_site=_managed_site(),
        twin_key=TWIN_KEY,
        candidate_id="does-not-match",
        candidate_revision=1,
        candidate_store=candidate_store,
        evidence_store=evidence_store,
        certification_record=certification_record,
    )

    assert result["readiness_status"] == (
        AUTO_TWIN_PROMOTION_READINESS_STATUS_BLOCKED
    )
    assert (
        result["checks"][
            AUTO_TWIN_PROMOTION_READINESS_CHECK_IDENTITY_BINDING
        ]["status"]
        == "BLOCKED"
    )
    assert "CANDIDATE_ID_MISMATCH" in result["blocking_reasons"]


def test_blocked_when_candidate_revision_target_does_not_match(tmp_path):
    (
        candidate_store,
        evidence_store,
        candidate_id,
        certification_record,
    ) = _build_ready_environment(tmp_path)

    result = _evaluate(
        candidate_store=candidate_store,
        evidence_store=evidence_store,
        candidate_id=candidate_id,
        certification_record=certification_record,
        candidate_revision=2,
    )

    assert result["readiness_status"] == (
        AUTO_TWIN_PROMOTION_READINESS_STATUS_BLOCKED
    )
    assert "CANDIDATE_REVISION_MISMATCH" in result["blocking_reasons"]


def test_readiness_id_is_deterministic(tmp_path):
    (
        candidate_store,
        evidence_store,
        candidate_id,
        certification_record,
    ) = _build_ready_environment(tmp_path)

    kwargs = dict(
        candidate_store=candidate_store,
        evidence_store=evidence_store,
        candidate_id=candidate_id,
        certification_record=certification_record,
    )

    first = _evaluate(**kwargs)
    second = _evaluate(**kwargs)

    assert first["readiness_id"] == second["readiness_id"]
    assert len(first["readiness_id"]) == 64


def test_never_mutates_candidate_store_or_evidence_store(tmp_path):
    (
        candidate_store,
        evidence_store,
        candidate_id,
        certification_record,
    ) = _build_ready_environment(tmp_path)

    candidate_before = candidate_store.get_candidate(TWIN_KEY, candidate_id)
    evidence_before = evidence_store.candidate_snapshot(TWIN_KEY, candidate_id)
    candidate_store_revision_before = candidate_store.revision
    evidence_store_revision_before = evidence_store.revision

    _evaluate(
        candidate_store=candidate_store,
        evidence_store=evidence_store,
        candidate_id=candidate_id,
        certification_record=certification_record,
    )

    assert candidate_store.get_candidate(TWIN_KEY, candidate_id) == (
        candidate_before
    )
    assert evidence_store.candidate_snapshot(TWIN_KEY, candidate_id) == (
        evidence_before
    )
    assert candidate_store.revision == candidate_store_revision_before
    assert evidence_store.revision == evidence_store_revision_before


def test_raises_on_malformed_certification_record(tmp_path):
    candidate_store, candidate_id = _candidate_store(tmp_path)
    evidence_store = _evidence_store(tmp_path)

    with pytest.raises(ValueError):
        _evaluate(
            candidate_store=candidate_store,
            evidence_store=evidence_store,
            candidate_id=candidate_id,
            certification_record={"not": "a certification record"},
        )


def test_raises_on_site_twin_mismatch(tmp_path):
    candidate_store, candidate_id = _candidate_store(tmp_path)
    evidence_store = _evidence_store(tmp_path)

    with pytest.raises(ValueError):
        evaluate_multi_site_promotion_readiness(
            managed_site=_managed_site(),
            twin_key="other-twin",
            candidate_id=candidate_id,
            candidate_revision=1,
            candidate_store=candidate_store,
            evidence_store=evidence_store,
            certification_record=None,
        )


def test_raises_on_invalid_candidate_revision(tmp_path):
    candidate_store, candidate_id = _candidate_store(tmp_path)
    evidence_store = _evidence_store(tmp_path)

    with pytest.raises(ValueError):
        evaluate_multi_site_promotion_readiness(
            managed_site=_managed_site(),
            twin_key=TWIN_KEY,
            candidate_id=candidate_id,
            candidate_revision=0,
            candidate_store=candidate_store,
            evidence_store=evidence_store,
            certification_record=None,
        )
