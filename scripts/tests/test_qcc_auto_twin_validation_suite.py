import pytest

from backend.qcc.auto_twin import (
    AUTO_TWIN_VALIDATION_DIMENSIONS,
    AUTO_TWIN_VALIDATION_SUITE_SECTION_EVALUATED,
    AUTO_TWIN_VALIDATION_SUITE_SECTION_FIDELITY,
    AUTO_TWIN_VALIDATION_SUITE_SECTION_NAVIGATION,
    AUTO_TWIN_VALIDATION_SUITE_SECTION_NETWORK_SAFETY,
    AUTO_TWIN_VALIDATION_SUITE_SECTION_SKIPPED,
    AUTO_TWIN_VALIDATION_SUITE_SECTION_UNRESOLVED,
    AUTO_TWIN_VALIDATION_SUITE_VERDICT_FAIL,
    AUTO_TWIN_VALIDATION_SUITE_VERDICT_INCONCLUSIVE,
    AUTO_TWIN_VALIDATION_SUITE_VERDICT_PASS,
    AutoTwinCandidateRevisionStore,
    AutoTwinManagedSite,
    AutoTwinValidationEvidenceStore,
    build_auto_twin_validation_evidence,
    run_auto_twin_validation_suite,
)

from backend.qcc.auto_twin.navigation_transition_validation_store import (
    AutoTwinNavigationTransitionValidationStore,
)


TWIN_KEY = "mercurio"
REVISION_ID = "matrev-test"


def _managed_twin():
    return AutoTwinManagedSite(
        twin_key=TWIN_KEY,
        site_code="MERCURIO",
        origins=(
            "https://mercurio.delegaciondelgobierno.gob.es",
        ),
        path_prefixes=(
            "/mercurio",
        ),
    )


def _candidate_store(
    tmp_path,
):
    store = AutoTwinCandidateRevisionStore(
        path=(
            tmp_path
            / "candidates.json"
        )
    )

    created = store.record_changed_observation(
        _managed_twin(),
        {
            "classification":
                "CHANGED",

            "capture_id":
                "capture-real",

            "observed_at":
                "2026-09-05T10:00:00+00:00",

            "browser_profile_key":
                "mercurio_assisted",

            "pathname":
                "/mercurio/page.html",

            "functional_state":
                "FORM",

            "state_key":
                "state-key",

            "fingerprint":
                "fp-new",

            "baseline_fingerprint":
                "fp-old",

            "baseline_capture_id":
                "capture-baseline",
        },
    )

    return (
        store,
        created["candidate"][
            "candidate_id"
        ],
    )


def _evidence_store(
    tmp_path,
):
    return AutoTwinValidationEvidenceStore(
        path=(
            tmp_path
            / "validation_evidence.json"
        )
    )


def _navigation_store(
    tmp_path,
):
    return AutoTwinNavigationTransitionValidationStore(
        path=(
            tmp_path
            / "navigation_transition_validation.json"
        )
    )


def _checks(
    status="PASS",
):
    return {
        dimension: {
            "status":
                status,
        }
        for dimension
        in AUTO_TWIN_VALIDATION_DIMENSIONS
    }


def _record_fidelity_evidence(
    evidence_store,
    *,
    candidate_id,
    candidate_revision,
    status="PASS",
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

    evidence_store.record_validation_evidence(
        evidence
    )


def _record_navigation_validated(
    navigation_store,
    *,
    candidate_id,
    revision_id=REVISION_ID,
):
    navigation_store.record_twin_validated({
        "status":
            "TWIN_VALIDATED",

        "reason":
            "EXACT_LOCAL_TARGET_REACHED",

        "twin_key":
            TWIN_KEY,

        "revision_id":
            revision_id,

        "candidate_id":
            candidate_id,

        "before_state_id":
            "AUTO_A",

        "after_state_id":
            "AUTO_B",

        "selector":
            'a[onclick="continuar()"]',

        "expected_runtime_entry":
            "states/01-AUTO_B/runtime/index.html",

        "location": {
            "href":
                (
                    "http://127.0.0.1:45678/"
                    "states/01-AUTO_B/runtime/index.html"
                ),

            "pathname":
                (
                    "/states/01-AUTO_B/"
                    "runtime/index.html"
                ),
        },
    })


def _write_runtime_html(
    materialized_root,
    *,
    revision_id=REVISION_ID,
    content="<html><body>sterile</body></html>",
):
    runtime_root = (
        materialized_root
        / TWIN_KEY
        / revision_id
        / "runtime"
    )

    runtime_root.mkdir(
        parents=True,
    )

    (
        runtime_root
        / "index.html"
    ).write_text(
        content,
        encoding="utf-8",
    )

    return runtime_root


def test_suite_skips_every_section_without_evidence(
    tmp_path,
):
    candidate_store, candidate_id = (
        _candidate_store(
            tmp_path
        )
    )

    evidence_store = _evidence_store(
        tmp_path
    )

    navigation_store = _navigation_store(
        tmp_path
    )

    result = run_auto_twin_validation_suite(
        twin_key=TWIN_KEY,
        candidate_id=candidate_id,
        candidate_store=candidate_store,
        evidence_store=evidence_store,
        navigation_validation_store=navigation_store,
        materialized_root=tmp_path,
    )

    assert result["verdict"] == (
        AUTO_TWIN_VALIDATION_SUITE_VERDICT_INCONCLUSIVE
    )

    assert result["certifiable"] is False

    assert set(
        result["skipped_sections"]
    ) == {
        AUTO_TWIN_VALIDATION_SUITE_SECTION_FIDELITY,
        AUTO_TWIN_VALIDATION_SUITE_SECTION_NAVIGATION,
        AUTO_TWIN_VALIDATION_SUITE_SECTION_NETWORK_SAFETY,
    }

    assert result["evaluated_sections"] == ()

    assert (
        result["sections"][
            AUTO_TWIN_VALIDATION_SUITE_SECTION_FIDELITY
        ]["status"]
        == AUTO_TWIN_VALIDATION_SUITE_SECTION_SKIPPED
    )


def test_suite_result_id_is_deterministic(
    tmp_path,
):
    candidate_store, candidate_id = (
        _candidate_store(
            tmp_path
        )
    )

    evidence_store = _evidence_store(
        tmp_path
    )

    navigation_store = _navigation_store(
        tmp_path
    )

    kwargs = dict(
        twin_key=TWIN_KEY,
        candidate_id=candidate_id,
        candidate_store=candidate_store,
        evidence_store=evidence_store,
        navigation_validation_store=navigation_store,
        materialized_root=tmp_path,
    )

    first = run_auto_twin_validation_suite(
        **kwargs
    )

    second = run_auto_twin_validation_suite(
        **kwargs
    )

    assert (
        first["suite_result_id"]
        == second["suite_result_id"]
    )

    assert len(
        first["suite_result_id"]
    ) == 64


def test_suite_passes_when_all_sections_evaluated_and_clean(
    tmp_path,
):
    candidate_store, candidate_id = (
        _candidate_store(
            tmp_path
        )
    )

    evidence_store = _evidence_store(
        tmp_path
    )

    navigation_store = _navigation_store(
        tmp_path
    )

    _record_fidelity_evidence(
        evidence_store,
        candidate_id=candidate_id,
        candidate_revision=1,
        status="PASS",
    )

    _record_navigation_validated(
        navigation_store,
        candidate_id=candidate_id,
    )

    _write_runtime_html(
        tmp_path,
    )

    result = run_auto_twin_validation_suite(
        twin_key=TWIN_KEY,
        candidate_id=candidate_id,
        candidate_store=candidate_store,
        evidence_store=evidence_store,
        navigation_validation_store=navigation_store,
        materialized_revision_id=REVISION_ID,
        materialized_root=tmp_path,
    )

    assert result["verdict"] == (
        AUTO_TWIN_VALIDATION_SUITE_VERDICT_PASS
    )

    assert result["certifiable"] is True

    assert set(
        result["evaluated_sections"]
    ) == {
        AUTO_TWIN_VALIDATION_SUITE_SECTION_FIDELITY,
        AUTO_TWIN_VALIDATION_SUITE_SECTION_NAVIGATION,
        AUTO_TWIN_VALIDATION_SUITE_SECTION_NETWORK_SAFETY,
    }

    network_section = result["sections"][
        AUTO_TWIN_VALIDATION_SUITE_SECTION_NETWORK_SAFETY
    ]

    assert network_section["metrics"][
        "html_files_scanned"
    ] == 1

    assert network_section["metrics"][
        "unsterilized_files"
    ] == []


def test_suite_fails_when_network_safety_detects_leak(
    tmp_path,
):
    candidate_store, candidate_id = (
        _candidate_store(
            tmp_path
        )
    )

    evidence_store = _evidence_store(
        tmp_path
    )

    navigation_store = _navigation_store(
        tmp_path
    )

    _record_fidelity_evidence(
        evidence_store,
        candidate_id=candidate_id,
        candidate_revision=1,
        status="PASS",
    )

    _record_navigation_validated(
        navigation_store,
        candidate_id=candidate_id,
    )

    _write_runtime_html(
        tmp_path,
        content=(
            '<html><body>'
            '<a href="https://real.example.com/leak">leak</a>'
            '</body></html>'
        ),
    )

    result = run_auto_twin_validation_suite(
        twin_key=TWIN_KEY,
        candidate_id=candidate_id,
        candidate_store=candidate_store,
        evidence_store=evidence_store,
        navigation_validation_store=navigation_store,
        materialized_revision_id=REVISION_ID,
        materialized_root=tmp_path,
    )

    assert result["verdict"] == (
        AUTO_TWIN_VALIDATION_SUITE_VERDICT_FAIL
    )

    assert result["certifiable"] is False

    network_section = result["sections"][
        AUTO_TWIN_VALIDATION_SUITE_SECTION_NETWORK_SAFETY
    ]

    assert network_section["verdict"] == "FAIL"

    assert network_section["metrics"][
        "unsterilized_files"
    ] == ["index.html"]


def test_suite_is_unresolved_when_fidelity_evidence_is_stale(
    tmp_path,
):
    candidate_store, candidate_id = (
        _candidate_store(
            tmp_path
        )
    )

    evidence_store = _evidence_store(
        tmp_path
    )

    navigation_store = _navigation_store(
        tmp_path
    )

    _record_fidelity_evidence(
        evidence_store,
        candidate_id=candidate_id,
        candidate_revision=999,
        status="PASS",
    )

    result = run_auto_twin_validation_suite(
        twin_key=TWIN_KEY,
        candidate_id=candidate_id,
        candidate_store=candidate_store,
        evidence_store=evidence_store,
        navigation_validation_store=navigation_store,
        materialized_root=tmp_path,
    )

    assert result["verdict"] == (
        AUTO_TWIN_VALIDATION_SUITE_VERDICT_INCONCLUSIVE
    )

    assert result["certifiable"] is False

    assert (
        result["sections"][
            AUTO_TWIN_VALIDATION_SUITE_SECTION_FIDELITY
        ]["status"]
        == AUTO_TWIN_VALIDATION_SUITE_SECTION_UNRESOLVED
    )


def test_suite_never_touches_candidate_lifecycle(
    tmp_path,
):
    candidate_store, candidate_id = (
        _candidate_store(
            tmp_path
        )
    )

    evidence_store = _evidence_store(
        tmp_path
    )

    navigation_store = _navigation_store(
        tmp_path
    )

    _record_fidelity_evidence(
        evidence_store,
        candidate_id=candidate_id,
        candidate_revision=1,
        status="PASS",
    )

    _record_navigation_validated(
        navigation_store,
        candidate_id=candidate_id,
    )

    _write_runtime_html(
        tmp_path,
    )

    before = candidate_store.get_candidate(
        TWIN_KEY,
        candidate_id,
    )

    result = run_auto_twin_validation_suite(
        twin_key=TWIN_KEY,
        candidate_id=candidate_id,
        candidate_store=candidate_store,
        evidence_store=evidence_store,
        navigation_validation_store=navigation_store,
        materialized_revision_id=REVISION_ID,
        materialized_root=tmp_path,
    )

    after = candidate_store.get_candidate(
        TWIN_KEY,
        candidate_id,
    )

    assert result["verdict"] == (
        AUTO_TWIN_VALIDATION_SUITE_VERDICT_PASS
    )

    assert before == after


def test_suite_raises_for_unknown_candidate(
    tmp_path,
):
    candidate_store, _ = _candidate_store(
        tmp_path
    )

    evidence_store = _evidence_store(
        tmp_path
    )

    navigation_store = _navigation_store(
        tmp_path
    )

    with pytest.raises(ValueError):
        run_auto_twin_validation_suite(
            twin_key=TWIN_KEY,
            candidate_id="does-not-exist",
            candidate_store=candidate_store,
            evidence_store=evidence_store,
            navigation_validation_store=navigation_store,
            materialized_root=tmp_path,
        )
