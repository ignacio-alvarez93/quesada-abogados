import pytest

from backend.qcc.auto_twin import (
    AUTO_TWIN_VALIDATION_CHECK_FAIL,
    AUTO_TWIN_VALIDATION_CHECK_INCONCLUSIVE,
    AUTO_TWIN_VALIDATION_CHECK_NOT_AVAILABLE,
    AUTO_TWIN_VALIDATION_CHECK_PASS,
    AUTO_TWIN_VALIDATION_DIMENSIONS,
    AUTO_TWIN_VALIDATION_VERDICT_FAIL,
    AUTO_TWIN_VALIDATION_VERDICT_INCONCLUSIVE,
    AUTO_TWIN_VALIDATION_VERDICT_PASS,
    build_auto_twin_validation_evidence,
)


def _base(
    **overrides,
):
    payload = {
        "twin_key":
            "mercurio",

        "candidate_id":
            "candidate-1",

        "candidate_revision":
            1,

        "real_capture_id":
            "capture-real",

        "twin_capture_id":
            "capture-twin",

        "pathname":
            "/mercurio/page.html",

        "functional_state":
            "FORM",

        "rendering_profile_id":
            "chrome_desktop_1280x720_dpr1",
    }

    payload.update(
        overrides
    )

    return payload


def _all_pass():
    return {
        dimension: {
            "status":
                AUTO_TWIN_VALIDATION_CHECK_PASS,
        }
        for dimension
        in AUTO_TWIN_VALIDATION_DIMENSIONS
    }


def test_missing_checks_are_not_available_and_inconclusive():
    result = (
        build_auto_twin_validation_evidence(
            **_base(
                checks={}
            )
        )
    )

    assert (
        result["verdict"]
        == AUTO_TWIN_VALIDATION_VERDICT_INCONCLUSIVE
    )

    assert (
        result["ready_for_validation"]
        is False
    )

    assert set(
        result[
            "summary"
        ][
            "incomplete_dimensions"
        ]
    ) == set(
        AUTO_TWIN_VALIDATION_DIMENSIONS
    )

    assert all(
        check["status"]
        == AUTO_TWIN_VALIDATION_CHECK_NOT_AVAILABLE
        for check
        in result[
            "checks"
        ].values()
    )


def test_all_required_checks_pass():
    result = (
        build_auto_twin_validation_evidence(
            **_base(
                checks=_all_pass()
            )
        )
    )

    assert (
        result["verdict"]
        == AUTO_TWIN_VALIDATION_VERDICT_PASS
    )

    assert (
        result["ready_for_validation"]
        is True
    )

    assert (
        result[
            "summary"
        ][
            "failed_dimensions"
        ]
        == ()
    )

    assert (
        result[
            "summary"
        ][
            "incomplete_dimensions"
        ]
        == ()
    )


def test_any_required_failure_fails_verdict():
    checks = _all_pass()

    checks[
        "GEOMETRY"
    ] = {
        "status":
            AUTO_TWIN_VALIDATION_CHECK_FAIL,

        "summary":
            "Geometry exceeds tolerance.",

        "metrics": {
            "max_delta_px":
                14.0,
        },
    }

    result = (
        build_auto_twin_validation_evidence(
            **_base(
                checks=checks
            )
        )
    )

    assert (
        result["verdict"]
        == AUTO_TWIN_VALIDATION_VERDICT_FAIL
    )

    assert (
        result["ready_for_validation"]
        is False
    )

    assert (
        result[
            "summary"
        ][
            "failed_dimensions"
        ]
        == (
            "GEOMETRY",
        )
    )


def test_inconclusive_required_dimension_blocks_pass():
    checks = _all_pass()

    checks[
        "VISUAL"
    ] = {
        "status":
            AUTO_TWIN_VALIDATION_CHECK_INCONCLUSIVE,
    }

    result = (
        build_auto_twin_validation_evidence(
            **_base(
                checks=checks
            )
        )
    )

    assert (
        result["verdict"]
        == AUTO_TWIN_VALIDATION_VERDICT_INCONCLUSIVE
    )

    assert (
        result[
            "summary"
        ][
            "incomplete_dimensions"
        ]
        == (
            "VISUAL",
        )
    )


def test_optional_dimension_does_not_block_verdict():
    checks = {
        "STRUCTURE": {
            "status":
                "PASS",
        },
        "GEOMETRY": {
            "status":
                "PASS",
        },
        "VISUAL": {
            "status":
                "FAIL",
        },
    }

    result = (
        build_auto_twin_validation_evidence(
            **_base(
                checks=checks,

                required_dimensions=(
                    "STRUCTURE",
                    "GEOMETRY",
                ),
            )
        )
    )

    assert (
        result["verdict"]
        == AUTO_TWIN_VALIDATION_VERDICT_PASS
    )

    assert (
        result["ready_for_validation"]
        is True
    )


def test_state_identity_deliberately_has_no_origin():
    result = (
        build_auto_twin_validation_evidence(
            **_base(
                checks=_all_pass()
            )
        )
    )

    identity = result[
        "state_identity"
    ]

    assert (
        identity
        == {
            "pathname":
                "/mercurio/page.html",

            "functional_state":
                "FORM",
        }
    )

    assert "origin" not in identity
    assert "url" not in identity


def test_capture_pair_can_be_incomplete():
    result = (
        build_auto_twin_validation_evidence(
            **_base(
                twin_capture_id=None,
                checks={},
            )
        )
    )

    assert (
        result[
            "capture_pair"
        ][
            "real_capture_id"
        ]
        == "capture-real"
    )

    assert (
        result[
            "capture_pair"
        ][
            "twin_capture_id"
        ]
        is None
    )

    assert (
        result["ready_for_validation"]
        is False
    )


def test_check_payload_is_lightweight():
    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_VALIDATION_CHECK_FIELDS_INVALID"
        ),
    ):
        build_auto_twin_validation_evidence(
            **_base(
                checks={
                    "VISUAL": {
                        "status":
                            "PASS",

                        "screenshot":
                            b"forbidden",
                    },
                }
            )
        )


@pytest.mark.parametrize(
    "status",
    [
        "",
        "UNKNOWN",
        "ACTIVE",
    ],
)
def test_invalid_check_status_is_rejected(
    status,
):
    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_VALIDATION_CHECK_STATUS_INVALID"
        ),
    ):
        build_auto_twin_validation_evidence(
            **_base(
                checks={
                    "STRUCTURE": {
                        "status":
                            status,
                    },
                }
            )
        )


def test_nested_heavy_metrics_are_rejected():
    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_VALIDATION_METRICS_INVALID"
        ),
    ):
        build_auto_twin_validation_evidence(
            **_base(
                checks={
                    "VISUAL": {
                        "status":
                            "PASS",

                        "metrics": {
                            "pixels": [
                                1,
                                2,
                                3,
                            ],
                        },
                    },
                }
            )
        )


def test_references_are_lightweight_scalars():
    result = (
        build_auto_twin_validation_evidence(
            **_base(
                checks={
                    "STRUCTURE": {
                        "status":
                            "PASS",

                        "references": {
                            "real_capture_id":
                                "capture-real",

                            "twin_capture_id":
                                "capture-twin",
                        },
                    },
                },

                required_dimensions=(
                    "STRUCTURE",
                ),
            )
        )
    )

    assert (
        result[
            "checks"
        ][
            "STRUCTURE"
        ][
            "references"
        ][
            "real_capture_id"
        ]
        == "capture-real"
    )


def test_duplicate_required_dimensions_are_normalized():
    result = (
        build_auto_twin_validation_evidence(
            **_base(
                checks=_all_pass(),

                required_dimensions=(
                    "STRUCTURE",
                    "structure",
                    "GEOMETRY",
                ),
            )
        )
    )

    assert (
        result[
            "required_dimensions"
        ]
        == (
            "STRUCTURE",
            "GEOMETRY",
        )
    )


def test_empty_required_dimensions_are_rejected():
    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_VALIDATION_REQUIRED_DIMENSIONS_EMPTY"
        ),
    ):
        build_auto_twin_validation_evidence(
            **_base(
                checks={},
                required_dimensions=(),
            )
        )
