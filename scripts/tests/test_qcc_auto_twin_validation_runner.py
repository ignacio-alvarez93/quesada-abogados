import json

from PIL import Image

import pytest

from backend.qcc.auto_twin import (
    AUTO_TWIN_BEHAVIOR_KIND_NAVIGATION,
    AUTO_TWIN_BEHAVIOR_SOURCE_REAL_OBSERVED,
    AUTO_TWIN_BEHAVIOR_SOURCE_TWIN_CONTROLLED,
    AUTO_TWIN_VALIDATION_RUNNER_AMBIGUOUS,
    AUTO_TWIN_VALIDATION_RUNNER_EVALUATED,
    AUTO_TWIN_VALIDATION_RUNNER_SKIPPED,
    AutoTwinCandidateRevisionStore,
    AutoTwinManagedSite,
    AutoTwinValidationEvidenceStore,
    build_auto_twin_behavior_trace,
    build_auto_twin_profile_policy,
    run_auto_twin_validation_evaluation,
)


WIDTH = 40
HEIGHT = 30

REAL_ID = "capture-real"
TWIN_ID = "capture-twin"

PATHNAME = (
    "/mercurio/page.html"
)

STATE = "FORM"


def _write_json(
    path,
    value,
):
    path.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _element():
    return {
        "semantics":
            [
                "INPUT",
            ],

        "selectors": {
            "frame_path":
                "main",

            "candidates": [
                {
                    "selector":
                        "#field",

                    "unique":
                        True,
                },
            ],

            "primary": {
                "strategy":
                    "CSS",

                "selector":
                    "#field",

                "confidence":
                    1.0,

                "unique":
                    True,
            },

            "fallbacks":
                [],
        },

        "interaction": {
            "visible":
                True,

            "disabled":
                False,

            "aria_disabled":
                False,

            "readonly":
                False,

            "hidden":
                False,

            "aria_hidden":
                False,

            "pointer_events":
                "auto",
        },

        "geometry": {
            "viewport_rect": {
                "x":
                    5,

                "y":
                    5,

                "width":
                    20,

                "height":
                    10,
            },
        },
    }


def _write_capture(
    root,
    *,
    capture_id,
    profile_key,
    origin,
    fingerprint,
    width=WIDTH,
):
    capture_dir = (
        root
        / capture_id
    )

    capture_dir.mkdir(
        parents=True,
    )

    screenshot = (
        capture_dir
        / "screenshot_viewport.png"
    )

    Image.new(
        "RGB",
        (
            width,
            HEIGHT,
        ),
        (
            255,
            255,
            255,
        ),
    ).save(
        screenshot
    )

    metadata = {
        "capture_id":
            capture_id,

        "site_code":
            "MERCURIO",

        "state_observation": {
            "state":
                STATE,

            "fingerprint":
                fingerprint,
        },

        "retention": {
            "browser_profile_key":
                profile_key,
        },

        "artifacts": {
            "raw_capture":
                "qcc_capture.json",

            "site_architecture":
                "site_architecture.json",

            "state_observation":
                "state_observation.json",

            "metadata":
                "metadata.json",

            "screenshot_viewport":
                "screenshot_viewport.png",
        },

        "visual_evidence": {
            "viewport": {
                "artifact":
                    "screenshot_viewport.png",

                "content_type":
                    "image/png",
            },
        },
    }

    _write_json(
        capture_dir
        / "metadata.json",
        metadata,
    )

    _write_json(
        capture_dir
        / "qcc_capture.json",
        {
            "schema_version":
                1,

            "browser_profile_key":
                profile_key,

            "main_url":
                (
                    origin
                    + PATHNAME
                ),
        },
    )

    _write_json(
        capture_dir
        / "state_observation.json",
        {
            "schema_version":
                1,

            "state":
                STATE,

            "fingerprint":
                fingerprint,
        },
    )

    _write_json(
        capture_dir
        / "site_architecture.json",
        {
            "schema_version":
                1,

            "page": {
                "url":
                    (
                        origin
                        + PATHNAME
                    ),

                "origin":
                    origin,

                "pathname":
                    PATHNAME,

                "query":
                    "",

                "title":
                    "Mercurio",

                "signature":
                    "same-signature",
            },

            "viewport": {
                "inner_width":
                    width,

                "inner_height":
                    HEIGHT,

                "device_pixel_ratio":
                    1,

                "scroll_x":
                    0,

                "scroll_y":
                    0,
            },

            "elements": [
                _element()
            ],

            "catalogs":
                [],
        },
    )


def _managed():
    return AutoTwinManagedSite(
        twin_key="mercurio",
        site_code="MERCURIO",
        origins=(
            "https://real.example",
        ),
        path_prefixes=(
            "/mercurio",
        ),
    )


def _candidate_store(
    tmp_path,
    *,
    count=1,
):
    store = (
        AutoTwinCandidateRevisionStore(
            path=(
                tmp_path
                / "candidates.json"
            )
        )
    )

    candidates = []

    for index in range(
        count
    ):
        real_id = (
            REAL_ID
            if index == 0
            else (
                f"capture-real-"
                f"{index + 1}"
            )
        )

        created = (
            store.record_changed_observation(
                _managed(),
                {
                    "classification":
                        "CHANGED",

                    "capture_id":
                        real_id,

                    "observed_at":
                        (
                            "2026-09-05T"
                            f"10:0{index}:00+00:00"
                        ),

                    "browser_profile_key":
                        "mercurio_assisted",

                    "pathname":
                        PATHNAME,

                    "functional_state":
                        STATE,

                    "state_key":
                        (
                            "state-key-"
                            + str(index)
                        ),

                    "fingerprint":
                        (
                            "fp-new-"
                            + str(index)
                        ),

                    "baseline_fingerprint":
                        (
                            "fp-old-"
                            + str(index)
                        ),

                    "baseline_capture_id":
                        (
                            "capture-baseline-"
                            + str(index)
                        ),
                },
            )
        )

        candidates.append(
            created[
                "candidate"
            ]
        )

    return (
        store,
        candidates,
    )


def _evidence_store(
    tmp_path,
):
    return (
        AutoTwinValidationEvidenceStore(
            path=(
                tmp_path
                / "evidence.json"
            )
        )
    )


def _root(
    tmp_path,
):
    root = (
        tmp_path
        / "site_architecture"
    )

    _write_capture(
        root,
        capture_id=REAL_ID,
        profile_key=(
            "mercurio_assisted"
        ),
        origin=(
            "https://real.example"
        ),
        fingerprint="real-fp",
    )

    _write_capture(
        root,
        capture_id=TWIN_ID,
        profile_key=(
            "twin_discovery"
        ),
        origin=(
            "http://127.0.0.1:8767"
        ),
        fingerprint="twin-fp",
    )

    return root


def _behavior_pair(
    candidate_id,
):
    real = (
        build_auto_twin_behavior_trace(
            twin_key="mercurio",
            candidate_id=(
                candidate_id
            ),
            source=(
                AUTO_TWIN_BEHAVIOR_SOURCE_REAL_OBSERVED
            ),
            behavior_kind=(
                AUTO_TWIN_BEHAVIOR_KIND_NAVIGATION
            ),
            action={
                "kind":
                    "NAVIGATION",

                "action_code":
                    "CONTINUE",
            },
            transition={
                "before_state":
                    "FORM",

                "after_state":
                    "NEXT",

                "changed":
                    True,
            },
            policy="HUMAN_ONLY",
        )
    )

    twin = (
        build_auto_twin_behavior_trace(
            twin_key="mercurio",
            candidate_id=(
                candidate_id
            ),
            source=(
                AUTO_TWIN_BEHAVIOR_SOURCE_TWIN_CONTROLLED
            ),
            behavior_kind=(
                AUTO_TWIN_BEHAVIOR_KIND_NAVIGATION
            ),
            action={
                "kind":
                    "NAVIGATION",

                "action_code":
                    "CONTINUE",
            },
            transition={
                "before_state":
                    "FORM",

                "after_state":
                    "NEXT",

                "changed":
                    True,
            },
            policy="AUTOMATION_ALLOWED",
        )
    )

    return (
        real,
        twin,
    )


def test_runner_connects_trigger_loader_and_evaluator(
    tmp_path,
):
    root = _root(
        tmp_path
    )

    candidate_store, candidates = (
        _candidate_store(
            tmp_path
        )
    )

    evidence_store = (
        _evidence_store(
            tmp_path
        )
    )

    (
        real_behavior,
        twin_behavior,
    ) = _behavior_pair(
        candidates[0][
            "candidate_id"
        ]
    )

    result = (
        run_auto_twin_validation_evaluation(
            managed_twin=(
                _managed()
            ),
            profile_policy=(
                build_auto_twin_profile_policy(
                    "twin_discovery"
                )
            ),
            candidate_store=(
                candidate_store
            ),
            evidence_store=(
                evidence_store
            ),
            twin_capture_id=(
                TWIN_ID
            ),
            capture_root=(
                root
            ),
            real_behavior_trace=(
                real_behavior
            ),
            twin_behavior_trace=(
                twin_behavior
            ),
        )
    )

    assert (
        result[
            "status"
        ]
        == AUTO_TWIN_VALIDATION_RUNNER_EVALUATED
    )

    assert (
        result[
            "evaluated"
        ]
        is True
    )

    assert (
        result[
            "decision"
        ][
            "real_capture_id"
        ]
        == REAL_ID
    )

    assert (
        result[
            "evaluation"
        ][
            "verdict"
        ]
        == "PASS"
    )

    assert (
        result[
            "evaluation"
        ][
            "ready_for_validation"
        ]
        is True
    )

    assert (
        evidence_store.revision
        == 1
    )


def test_missing_behavior_persists_inconclusive(
    tmp_path,
):
    root = _root(
        tmp_path
    )

    candidate_store, _ = (
        _candidate_store(
            tmp_path
        )
    )

    evidence_store = (
        _evidence_store(
            tmp_path
        )
    )

    result = (
        run_auto_twin_validation_evaluation(
            managed_twin=(
                _managed()
            ),
            profile_policy=(
                build_auto_twin_profile_policy(
                    "twin_discovery"
                )
            ),
            candidate_store=(
                candidate_store
            ),
            evidence_store=(
                evidence_store
            ),
            twin_capture_id=(
                TWIN_ID
            ),
            capture_root=(
                root
            ),
        )
    )

    assert (
        result[
            "status"
        ]
        == AUTO_TWIN_VALIDATION_RUNNER_EVALUATED
    )

    assert (
        result[
            "evaluation"
        ][
            "verdict"
        ]
        == "INCONCLUSIVE"
    )

    assert (
        result[
            "evaluation"
        ][
            "ready_for_validation"
        ]
        is False
    )

    assert (
        evidence_store.revision
        == 1
    )


def test_observer_profile_skips_before_real_bundle_load(
    tmp_path,
):
    root = _root(
        tmp_path
    )

    # Remove REAL intentionally. If runner tried to load it,
    # this test would fail.
    import shutil

    shutil.rmtree(
        root
        / REAL_ID
    )

    candidate_store, _ = (
        _candidate_store(
            tmp_path
        )
    )

    evidence_store = (
        _evidence_store(
            tmp_path
        )
    )

    result = (
        run_auto_twin_validation_evaluation(
            managed_twin=(
                _managed()
            ),
            profile_policy=(
                build_auto_twin_profile_policy(
                    "ordinary-profile"
                )
            ),
            candidate_store=(
                candidate_store
            ),
            evidence_store=(
                evidence_store
            ),
            twin_capture_id=(
                TWIN_ID
            ),
            capture_root=(
                root
            ),
        )
    )

    assert (
        result[
            "status"
        ]
        == AUTO_TWIN_VALIDATION_RUNNER_SKIPPED
    )

    assert (
        result[
            "evaluated"
        ]
        is False
    )

    assert (
        result[
            "decision"
        ][
            "reason"
        ]
        == "PROFILE_NOT_VALIDATION"
    )

    assert (
        evidence_store.revision
        == 0
    )


def test_ambiguous_candidate_skips_before_real_bundle_load(
    tmp_path,
):
    root = _root(
        tmp_path
    )

    candidate_store, _ = (
        _candidate_store(
            tmp_path,
            count=2,
        )
    )

    # No second REAL capture exists.
    # Ambiguity must be resolved before loading either.
    evidence_store = (
        _evidence_store(
            tmp_path
        )
    )

    result = (
        run_auto_twin_validation_evaluation(
            managed_twin=(
                _managed()
            ),
            profile_policy=(
                build_auto_twin_profile_policy(
                    "twin_discovery"
                )
            ),
            candidate_store=(
                candidate_store
            ),
            evidence_store=(
                evidence_store
            ),
            twin_capture_id=(
                TWIN_ID
            ),
            capture_root=(
                root
            ),
        )
    )

    assert (
        result[
            "status"
        ]
        == AUTO_TWIN_VALIDATION_RUNNER_AMBIGUOUS
    )

    assert (
        result[
            "evaluated"
        ]
        is False
    )

    assert (
        result[
            "decision"
        ][
            "reason"
        ]
        == "AMBIGUOUS_CANDIDATE"
    )

    assert (
        evidence_store.revision
        == 0
    )


def test_missing_exact_real_capture_fails_closed(
    tmp_path,
):
    root = _root(
        tmp_path
    )

    candidate_store, _ = (
        _candidate_store(
            tmp_path
        )
    )

    evidence_store = (
        _evidence_store(
            tmp_path
        )
    )

    import shutil

    shutil.rmtree(
        root
        / REAL_ID
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_PERSISTED_CAPTURE_NOT_FOUND"
        ),
    ):
        run_auto_twin_validation_evaluation(
            managed_twin=(
                _managed()
            ),
            profile_policy=(
                build_auto_twin_profile_policy(
                    "twin_discovery"
                )
            ),
            candidate_store=(
                candidate_store
            ),
            evidence_store=(
                evidence_store
            ),
            twin_capture_id=(
                TWIN_ID
            ),
            capture_root=(
                root
            ),
        )

    assert (
        evidence_store.revision
        == 0
    )


def test_incompatible_rendering_profile_fails_before_persistence(
    tmp_path,
):
    root = _root(
        tmp_path
    )

    # Rewrite REAL with different physical width.
    import shutil

    shutil.rmtree(
        root
        / REAL_ID
    )

    _write_capture(
        root,
        capture_id=REAL_ID,
        profile_key=(
            "mercurio_assisted"
        ),
        origin=(
            "https://real.example"
        ),
        fingerprint="real-fp",
        width=41,
    )

    candidate_store, _ = (
        _candidate_store(
            tmp_path
        )
    )

    evidence_store = (
        _evidence_store(
            tmp_path
        )
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_VALIDATION_EVALUATOR_"
            "CAPTURE_PAIR_NOT_READY"
        ),
    ):
        run_auto_twin_validation_evaluation(
            managed_twin=(
                _managed()
            ),
            profile_policy=(
                build_auto_twin_profile_policy(
                    "twin_discovery"
                )
            ),
            candidate_store=(
                candidate_store
            ),
            evidence_store=(
                evidence_store
            ),
            twin_capture_id=(
                TWIN_ID
            ),
            capture_root=(
                root
            ),
        )

    assert (
        evidence_store.revision
        == 0
    )


def test_same_runtime_evaluation_is_idempotent(
    tmp_path,
):
    root = _root(
        tmp_path
    )

    candidate_store, candidates = (
        _candidate_store(
            tmp_path
        )
    )

    evidence_store = (
        _evidence_store(
            tmp_path
        )
    )

    (
        real_behavior,
        twin_behavior,
    ) = _behavior_pair(
        candidates[0][
            "candidate_id"
        ]
    )

    kwargs = {
        "managed_twin":
            _managed(),

        "profile_policy":
            build_auto_twin_profile_policy(
                "twin_discovery"
            ),

        "candidate_store":
            candidate_store,

        "evidence_store":
            evidence_store,

        "twin_capture_id":
            TWIN_ID,

        "capture_root":
            root,

        "real_behavior_trace":
            real_behavior,

        "twin_behavior_trace":
            twin_behavior,
    }

    first = (
        run_auto_twin_validation_evaluation(
            **kwargs
        )
    )

    second = (
        run_auto_twin_validation_evaluation(
            **kwargs
        )
    )

    assert (
        first[
            "evaluation"
        ][
            "evidence_id"
        ]
        == second[
            "evaluation"
        ][
            "evidence_id"
        ]
    )

    assert (
        first[
            "evaluation"
        ][
            "evidence_created"
        ]
        is True
    )

    assert (
        second[
            "evaluation"
        ][
            "evidence_created"
        ]
        is False
    )

    assert (
        evidence_store.revision
        == 1
    )


def test_runner_never_changes_candidate_status(
    tmp_path,
):
    root = _root(
        tmp_path
    )

    candidate_store, candidates = (
        _candidate_store(
            tmp_path
        )
    )

    evidence_store = (
        _evidence_store(
            tmp_path
        )
    )

    candidate_id = (
        candidates[0][
            "candidate_id"
        ]
    )

    run_auto_twin_validation_evaluation(
        managed_twin=_managed(),
        profile_policy=(
            build_auto_twin_profile_policy(
                "twin_discovery"
            )
        ),
        candidate_store=(
            candidate_store
        ),
        evidence_store=(
            evidence_store
        ),
        twin_capture_id=TWIN_ID,
        capture_root=root,
    )

    after = (
        candidate_store.get_candidate(
            "mercurio",
            candidate_id,
        )
    )

    assert (
        after[
            "status"
        ]
        == "PENDING_VALIDATION"
    )
