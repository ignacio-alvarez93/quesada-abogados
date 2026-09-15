from copy import deepcopy

from PIL import Image

import pytest

from backend.qcc.auto_twin import (
    AUTO_TWIN_BEHAVIOR_KIND_NAVIGATION,
    AUTO_TWIN_BEHAVIOR_SOURCE_REAL_OBSERVED,
    AUTO_TWIN_BEHAVIOR_SOURCE_TWIN_CONTROLLED,
    AUTO_TWIN_VALIDATION_VERDICT_INCONCLUSIVE,
    AUTO_TWIN_VALIDATION_VERDICT_PASS,
    AutoTwinCandidateRevisionStore,
    AutoTwinManagedSite,
    AutoTwinValidationEvidenceStore,
    build_auto_twin_behavior_trace,
    build_auto_twin_rendering_profile,
    evaluate_auto_twin_candidate_fidelity,
)


WIDTH = 40
HEIGHT = 30


def _managed_twin():
    return AutoTwinManagedSite(
        twin_key="mercurio",
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
    store = (
        AutoTwinCandidateRevisionStore(
            path=(
                tmp_path
                / "candidates.json"
            )
        )
    )

    created = (
        store.record_changed_observation(
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
    )

    return (
        store,
        created[
            "candidate"
        ],
    )


def _evidence_store(
    tmp_path,
):
    return (
        AutoTwinValidationEvidenceStore(
            path=(
                tmp_path
                / "validation_evidence.json"
            )
        )
    )


def _profile():
    return (
        build_auto_twin_rendering_profile(
            inner_width=WIDTH,
            inner_height=HEIGHT,
            device_pixel_ratio=1,
        )
    )


def _capture(
    capture_id,
    *,
    profile,
):
    return {
        "capture_id":
            capture_id,

        "pathname":
            "/mercurio/page.html",

        "functional_state":
            "FORM",

        "browser_profile_key":
            profile,

        "viewport": {
            "inner_width":
                WIDTH,

            "inner_height":
                HEIGHT,

            "device_pixel_ratio":
                1,

            "scroll_x":
                0,

            "scroll_y":
                0,
        },
    }


def _element():
    return {
        "semantics":
            ("INPUT",),

        "selectors": {
            "frame_path":
                "main",

            "candidates": (
                {
                    "selector":
                        "#field",

                    "unique":
                        True,
                },
            ),

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
                (),
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
                    10,

                "y":
                    20,

                "width":
                    100,

                "height":
                    30,
            },
        },
    }


def _snapshot(
    *,
    real,
):
    origin = (
        "https://real.example"
        if real
        else "http://127.0.0.1:8767"
    )

    return {
        "schema_version":
            1,

        "page": {
            "url":
                (
                    origin
                    + "/mercurio/page.html"
                ),

            "origin":
                origin,

            "pathname":
                "/mercurio/page.html",

            "query":
                "",

            "title":
                "Mercurio",

            "signature":
                "same-signature",
        },

        "elements": (
            _element(),
        ),

        # Presencia explícita significa inventario
        # disponible y vacío, no NOT_AVAILABLE.
        "catalogs":
            [],
    }


def _png(
    path,
):
    Image.new(
        "RGB",
        (
            WIDTH,
            HEIGHT,
        ),
        (
            255,
            255,
            255,
        ),
    ).save(
        path
    )

    return path


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


def _evaluate(
    tmp_path,
    *,
    real_capture_id="capture-real",
    with_behavior=True,
):
    candidate_store, candidate = (
        _candidate_store(
            tmp_path
        )
    )

    evidence_store = (
        _evidence_store(
            tmp_path
        )
    )

    real_image = (
        tmp_path
        / "real.png"
    )

    twin_image = (
        tmp_path
        / "twin.png"
    )

    _png(
        real_image
    )

    _png(
        twin_image
    )

    real_behavior = None
    twin_behavior = None

    if with_behavior:
        (
            real_behavior,
            twin_behavior,
        ) = _behavior_pair(
            candidate[
                "candidate_id"
            ]
        )

    result = (
        evaluate_auto_twin_candidate_fidelity(
            candidate_store=(
                candidate_store
            ),
            evidence_store=(
                evidence_store
            ),
            twin_key="mercurio",
            candidate_id=(
                candidate[
                    "candidate_id"
                ]
            ),
            rendering_profile=(
                _profile()
            ),
            real_capture=(
                _capture(
                    real_capture_id,
                    profile=(
                        "mercurio_assisted"
                    ),
                )
            ),
            twin_capture=(
                _capture(
                    "capture-twin",
                    profile=(
                        "twin_discovery"
                    ),
                )
            ),
            real_snapshot=(
                _snapshot(
                    real=True
                )
            ),
            twin_snapshot=(
                _snapshot(
                    real=False
                )
            ),
            real_image_path=(
                real_image
            ),
            twin_image_path=(
                twin_image
            ),
            real_behavior_trace=(
                real_behavior
            ),
            twin_behavior_trace=(
                twin_behavior
            ),
        )
    )

    return (
        result,
        candidate_store,
        evidence_store,
        candidate,
    )


def test_evaluator_connects_complete_production_chain(
    tmp_path,
):
    (
        result,
        _candidate_store_value,
        evidence_store,
        candidate,
    ) = _evaluate(
        tmp_path
    )

    assert (
        result[
            "evaluated"
        ]
        is True
    )

    assert (
        result[
            "candidate_id"
        ]
        == candidate[
            "candidate_id"
        ]
    )

    assert (
        result[
            "verdict"
        ]
        == AUTO_TWIN_VALIDATION_VERDICT_PASS
    )

    assert (
        result[
            "ready_for_validation"
        ]
        is True
    )

    assert (
        result[
            "evidence_created"
        ]
        is True
    )

    persisted = (
        evidence_store.get_evidence(
            "mercurio",
            candidate[
                "candidate_id"
            ],
            result[
                "evidence_id"
            ],
        )
    )

    assert persisted is not None

    assert (
        persisted[
            "validation_evidence"
        ][
            "verdict"
        ]
        == AUTO_TWIN_VALIDATION_VERDICT_PASS
    )


def test_missing_behavior_is_persisted_as_inconclusive(
    tmp_path,
):
    result, _, _, _ = (
        _evaluate(
            tmp_path,
            with_behavior=False,
        )
    )

    assert (
        result[
            "verdict"
        ]
        == AUTO_TWIN_VALIDATION_VERDICT_INCONCLUSIVE
    )

    assert (
        result[
            "ready_for_validation"
        ]
        is False
    )

    assert (
        result[
            "validation_evidence"
        ][
            "checks"
        ][
            "BEHAVIOR"
        ][
            "status"
        ]
        == "NOT_AVAILABLE"
    )


def test_real_capture_must_belong_to_candidate(
    tmp_path,
):
    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_VALIDATION_EVALUATOR_"
            "REAL_CAPTURE_NOT_CANDIDATE_EVIDENCE"
        ),
    ):
        _evaluate(
            tmp_path,
            real_capture_id=(
                "capture-from-another-candidate"
            ),
        )


def test_unknown_candidate_is_rejected(
    tmp_path,
):
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
            "QCC_AUTO_TWIN_CANDIDATE_NOT_FOUND"
        ),
    ):
        evaluate_auto_twin_candidate_fidelity(
            candidate_store=(
                candidate_store
            ),
            evidence_store=(
                evidence_store
            ),
            twin_key="mercurio",
            candidate_id="missing",
            rendering_profile=(
                _profile()
            ),
            real_capture=(
                _capture(
                    "capture-real",
                    profile="real",
                )
            ),
            twin_capture=(
                _capture(
                    "capture-twin",
                    profile="twin",
                )
            ),
            real_snapshot={},
            twin_snapshot={},
            real_image_path=(
                tmp_path
                / "real.png"
            ),
            twin_image_path=(
                tmp_path
                / "twin.png"
            ),
        )


def test_same_evaluation_is_idempotent_in_evidence_store(
    tmp_path,
):
    candidate_store, candidate = (
        _candidate_store(
            tmp_path
        )
    )

    evidence_store = (
        _evidence_store(
            tmp_path
        )
    )

    real_image = (
        _png(
            tmp_path
            / "real.png"
        )
    )

    twin_image = (
        _png(
            tmp_path
            / "twin.png"
        )
    )

    (
        real_behavior,
        twin_behavior,
    ) = _behavior_pair(
        candidate[
            "candidate_id"
        ]
    )

    kwargs = {
        "candidate_store":
            candidate_store,

        "evidence_store":
            evidence_store,

        "twin_key":
            "mercurio",

        "candidate_id":
            candidate[
                "candidate_id"
            ],

        "rendering_profile":
            _profile(),

        "real_capture":
            _capture(
                "capture-real",
                profile=(
                    "mercurio_assisted"
                ),
            ),

        "twin_capture":
            _capture(
                "capture-twin",
                profile=(
                    "twin_discovery"
                ),
            ),

        "real_snapshot":
            _snapshot(
                real=True
            ),

        "twin_snapshot":
            _snapshot(
                real=False
            ),

        "real_image_path":
            real_image,

        "twin_image_path":
            twin_image,

        "real_behavior_trace":
            real_behavior,

        "twin_behavior_trace":
            twin_behavior,
    }

    first = (
        evaluate_auto_twin_candidate_fidelity(
            **kwargs
        )
    )

    second = (
        evaluate_auto_twin_candidate_fidelity(
            **kwargs
        )
    )

    assert (
        first[
            "evidence_id"
        ]
        == second[
            "evidence_id"
        ]
    )

    assert (
        first[
            "evidence_created"
        ]
        is True
    )

    assert (
        second[
            "evidence_created"
        ]
        is False
    )

    assert (
        evidence_store.revision
        == 1
    )


def test_evaluator_does_not_mutate_candidate_lifecycle(
    tmp_path,
):
    (
        _result,
        candidate_store,
        _evidence_store_value,
        candidate,
    ) = _evaluate(
        tmp_path
    )

    after = (
        candidate_store.get_candidate(
            "mercurio",
            candidate[
                "candidate_id"
            ],
        )
    )

    assert (
        after[
            "status"
        ]
        == candidate[
            "status"
        ]
        == "PENDING_VALIDATION"
    )

    assert (
        after[
            "baseline_capture_id"
        ]
        == candidate[
            "baseline_capture_id"
        ]
    )

    assert (
        after[
            "baseline_fingerprint"
        ]
        == candidate[
            "baseline_fingerprint"
        ]
    )


def test_capture_pair_uses_candidate_state_identity(
    tmp_path,
):
    result, _, _, candidate = (
        _evaluate(
            tmp_path
        )
    )

    evidence = (
        result[
            "validation_evidence"
        ]
    )

    assert (
        evidence[
            "state_identity"
        ][
            "pathname"
        ]
        == candidate[
            "pathname"
        ]
    )

    assert (
        evidence[
            "state_identity"
        ][
            "functional_state"
        ]
        == candidate[
            "functional_state"
        ]
    )


def test_real_and_twin_capture_ids_cannot_collide(
    tmp_path,
):
    candidate_store, candidate = (
        _candidate_store(
            tmp_path
        )
    )

    evidence_store = (
        _evidence_store(
            tmp_path
        )
    )

    capture = (
        _capture(
            "capture-real",
            profile="profile",
        )
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_VALIDATION_EVALUATOR_"
            "CAPTURE_ID_COLLISION"
        ),
    ):
        evaluate_auto_twin_candidate_fidelity(
            candidate_store=(
                candidate_store
            ),
            evidence_store=(
                evidence_store
            ),
            twin_key="mercurio",
            candidate_id=(
                candidate[
                    "candidate_id"
                ]
            ),
            rendering_profile=(
                _profile()
            ),
            real_capture=(
                capture
            ),
            twin_capture=(
                deepcopy(
                    capture
                )
            ),
            real_snapshot={},
            twin_snapshot={},
            real_image_path="real.png",
            twin_image_path="twin.png",
        )


def test_result_remains_lightweight(
    tmp_path,
):
    result, _, _, _ = (
        _evaluate(
            tmp_path
        )
    )

    serialized = str(
        result
    ).lower()

    for forbidden in (
        "outerhtml",
        "mhtml",
        "image_bytes",
        "screenshot_viewport",
        "qcc_capture",
    ):
        assert (
            forbidden
            not in serialized
        )
