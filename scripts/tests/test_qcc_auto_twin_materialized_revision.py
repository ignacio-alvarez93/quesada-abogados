from copy import deepcopy

import pytest

from backend.qcc.auto_twin.materialized_revision import (
    AUTO_TWIN_MATERIALIZATION_MODE_BOOTSTRAP_REAL,
    AUTO_TWIN_MATERIALIZATION_MODE_CANDIDATE_UPDATE,
    AUTO_TWIN_MATERIALIZATION_SOURCE_REAL_EVIDENCE,
    AUTO_TWIN_MATERIALIZED_REVISION_TYPE,
    build_auto_twin_materialized_revision,
    validate_auto_twin_materialized_revision,
)


HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def _build(
    **overrides,
):
    payload = {
        "twin_key":
            "mercurio",

        "materialization_mode":
            AUTO_TWIN_MATERIALIZATION_MODE_BOOTSTRAP_REAL,

        "source_capture_ids": [
            "capture-model",
            "capture-personal",
        ],

        "candidate_refs": [],

        "state_manifest": [
            {
                "state_id":
                    "MERCURIO_MODEL_SELECTION",

                "source_capture_id":
                    "capture-model",

                "pathname":
                    "/mercurio/seleccionModelo-33.html",

                "functional_state":
                    "MERCURIO_MODEL_SELECTION",
            },
            {
                "state_id":
                    "EX01_PERSONAL",

                "source_capture_id":
                    "capture-personal",

                "pathname":
                    "/mercurio/nuevaSolicitud-EX01.html",

                "functional_state":
                    "EX01_PERSONAL",
            },
        ],

        "artifact_manifest": [
            {
                "path":
                    "states/model/page.html",

                "kind":
                    "HTML",

                "sha256":
                    HASH_A,

                "size_bytes":
                    123,
            },
            {
                "path":
                    "states/personal/page.html",

                "kind":
                    "HTML",

                "sha256":
                    HASH_B,

                "size_bytes":
                    456,
            },
        ],

        "content_sha256":
            HASH_C,

        "created_at":
            "2026-09-05T13:30:00Z",
    }

    payload.update(
        overrides
    )

    return (
        build_auto_twin_materialized_revision(
            **payload
        )
    )


def test_bootstrap_materialized_revision_requires_no_candidate():
    record = _build()

    assert (
        record[
            "record_type"
        ]
        == AUTO_TWIN_MATERIALIZED_REVISION_TYPE
    )

    assert (
        record[
            "materialization_mode"
        ]
        == AUTO_TWIN_MATERIALIZATION_MODE_BOOTSTRAP_REAL
    )

    assert (
        record[
            "candidate_refs"
        ]
        == []
    )

    assert (
        record[
            "generation_source"
        ]
        == AUTO_TWIN_MATERIALIZATION_SOURCE_REAL_EVIDENCE
    )

    assert (
        record[
            "immutable"
        ]
        is True
    )


def test_bootstrap_forbids_candidate_refs():
    with pytest.raises(
        ValueError,
        match=(
            "BOOTSTRAP_CANDIDATE_REFS_FORBIDDEN"
        ),
    ):
        _build(
            candidate_refs=[
                {
                    "candidate_id":
                        "candidate-1",

                    "candidate_revision":
                        1,

                    "state_ids": [
                        "EX01_PERSONAL",
                    ],
                }
            ]
        )


def test_candidate_update_requires_candidate_refs():
    with pytest.raises(
        ValueError,
        match=(
            "CANDIDATE_UPDATE_REFS_REQUIRED"
        ),
    ):
        _build(
            materialization_mode=(
                AUTO_TWIN_MATERIALIZATION_MODE_CANDIDATE_UPDATE
            ),
            candidate_refs=[],
        )


def test_candidate_update_can_aggregate_multiple_state_scoped_candidates():
    record = _build(
        materialization_mode=(
            AUTO_TWIN_MATERIALIZATION_MODE_CANDIDATE_UPDATE
        ),
        candidate_refs=[
            {
                "candidate_id":
                    "candidate-model",

                "candidate_revision":
                    8,

                "state_ids": [
                    "MERCURIO_MODEL_SELECTION",
                ],
            },
            {
                "candidate_id":
                    "candidate-personal",

                "candidate_revision":
                    11,

                "state_ids": [
                    "EX01_PERSONAL",
                ],
            },
        ],
    )

    assert len(
        record[
            "candidate_refs"
        ]
    ) == 2


def test_candidate_ref_cannot_reference_unknown_state():
    with pytest.raises(
        ValueError,
        match=(
            "CANDIDATE_STATE_OUT_OF_SCOPE"
        ),
    ):
        _build(
            materialization_mode=(
                AUTO_TWIN_MATERIALIZATION_MODE_CANDIDATE_UPDATE
            ),
            candidate_refs=[
                {
                    "candidate_id":
                        "candidate-1",

                    "candidate_revision":
                        1,

                    "state_ids": [
                        "UNKNOWN_STATE",
                    ],
                }
            ],
        )


def test_materialized_revision_id_is_deterministic():
    first = _build(
        created_at=(
            "2026-09-05T13:30:00Z"
        )
    )

    second = _build(
        created_at=(
            "2026-09-05T18:00:00Z"
        )
    )

    assert (
        first[
            "materialized_revision_id"
        ]
        == second[
            "materialized_revision_id"
        ]
    )


def test_source_capture_ids_must_be_unique():
    with pytest.raises(
        ValueError
    ):
        _build(
            source_capture_ids=[
                "capture-model",
                "capture-model",
            ]
        )


def test_every_source_capture_must_be_represented_by_a_state():
    with pytest.raises(
        ValueError,
        match=(
            "SOURCE_CAPTURE_COVERAGE_INVALID"
        ),
    ):
        _build(
            source_capture_ids=[
                "capture-model",
                "capture-personal",
                "capture-unused",
            ]
        )


def test_state_capture_cannot_escape_source_set():
    states = deepcopy(
        _build()[
            "state_manifest"
        ]
    )

    states[0][
        "source_capture_id"
    ] = "foreign-capture"

    with pytest.raises(
        ValueError,
        match=(
            "STATE_CAPTURE_OUT_OF_SCOPE"
        ),
    ):
        _build(
            state_manifest=states
        )


@pytest.mark.parametrize(
    "path",
    (
        "../golden/page.html",
        "/absolute/page.html",
        "states/../../golden.html",
    ),
)
def test_artifact_paths_cannot_escape_revision_root(
    path,
):
    artifacts = deepcopy(
        _build()[
            "artifact_manifest"
        ]
    )

    artifacts[0][
        "path"
    ] = path

    with pytest.raises(
        ValueError,
        match=(
            "ARTIFACT_PATH_UNSAFE"
        ),
    ):
        _build(
            artifact_manifest=artifacts
        )


def test_validation_detects_identity_tampering():
    record = _build()

    record[
        "source_capture_ids"
    ][0] = "tampered"

    with pytest.raises(
        ValueError
    ):
        validate_auto_twin_materialized_revision(
            record
        )


def test_validation_detects_noncanonical_extra_fields():
    record = _build()

    record[
        "validation_evidence_ids"
    ] = [
        "forbidden-pre-build-evidence"
    ]

    with pytest.raises(
        ValueError,
        match=(
            "NON_CANONICAL"
        ),
    ):
        validate_auto_twin_materialized_revision(
            record
        )


def test_materialized_revision_contains_no_validation_or_promotion_status():
    record = _build()

    assert (
        "candidate_status_at_materialization"
        not in record
    )

    assert (
        "validation_evidence_ids"
        not in record
    )

    assert (
        "validation_status"
        not in record
    )

    serialized = repr(
        record
    )

    assert (
        "ACTIVE"
        not in serialized
    )

    assert (
        "promotion"
        not in serialized.lower()
    )

    assert (
        "golden"
        not in serialized.lower()
    )


def test_canonical_record_round_trips():
    record = _build()

    validated = (
        validate_auto_twin_materialized_revision(
            record
        )
    )

    assert validated == record

    assert validated is not record
