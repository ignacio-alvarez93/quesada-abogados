from copy import deepcopy
import json

import pytest

from backend.qcc.auto_twin import (
    AUTO_TWIN_VALIDATION_DIMENSIONS,
    AUTO_TWIN_VALIDATION_EVIDENCE_STORE_TYPE,
    AUTO_TWIN_VALIDATION_VERDICT_FAIL,
    AUTO_TWIN_VALIDATION_VERDICT_INCONCLUSIVE,
    AUTO_TWIN_VALIDATION_VERDICT_PASS,
    AutoTwinValidationEvidenceStore,
    build_auto_twin_validation_evidence,
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


def _evidence(
    *,
    candidate_revision=1,
    real_capture_id="real-1",
    twin_capture_id="twin-1",
    status="PASS",
):
    return (
        build_auto_twin_validation_evidence(
            twin_key="mercurio",
            candidate_id="candidate-1",
            candidate_revision=(
                candidate_revision
            ),
            real_capture_id=(
                real_capture_id
            ),
            twin_capture_id=(
                twin_capture_id
            ),
            pathname=(
                "/mercurio/page.html"
            ),
            functional_state="FORM",
            rendering_profile_id=(
                "profile-1"
            ),
            checks=(
                _checks(
                    status
                )
            ),
        )
    )


def _store(
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


def test_record_persists_complete_validation_evidence(
    tmp_path,
):
    store = _store(
        tmp_path
    )

    result = (
        store.record_validation_evidence(
            _evidence()
        )
    )

    assert (
        result[
            "created"
        ]
        is True
    )

    assert (
        result[
            "store_revision"
        ]
        == 1
    )

    record = result[
        "record"
    ]

    assert (
        len(
            record[
                "evidence_id"
            ]
        )
        == 64
    )

    assert (
        record[
            "validation_evidence"
        ][
            "verdict"
        ]
        == AUTO_TWIN_VALIDATION_VERDICT_PASS
    )

    assert (
        record[
            "validation_evidence"
        ][
            "ready_for_validation"
        ]
        is True
    )


def test_same_evidence_is_idempotent(
    tmp_path,
):
    store = _store(
        tmp_path
    )

    first = (
        store.record_validation_evidence(
            _evidence()
        )
    )

    second = (
        store.record_validation_evidence(
            _evidence()
        )
    )

    assert (
        first[
            "record"
        ][
            "evidence_id"
        ]
        == second[
            "record"
        ][
            "evidence_id"
        ]
    )

    assert (
        second[
            "created"
        ]
        is False
    )

    assert (
        second[
            "store_revision"
        ]
        == 1
    )


def test_different_capture_pair_creates_new_audit_record(
    tmp_path,
):
    store = _store(
        tmp_path
    )

    first = (
        store.record_validation_evidence(
            _evidence()
        )
    )

    second = (
        store.record_validation_evidence(
            _evidence(
                twin_capture_id="twin-2"
            )
        )
    )

    assert (
        first[
            "record"
        ][
            "evidence_id"
        ]
        != second[
            "record"
        ][
            "evidence_id"
        ]
    )

    assert (
        store.revision
        == 2
    )

    snapshot = (
        store.candidate_snapshot(
            "mercurio",
            "candidate-1",
        )
    )

    assert (
        snapshot[
            "candidate"
        ][
            "evidence_count"
        ]
        == 2
    )


def test_store_survives_reload(
    tmp_path,
):
    path = (
        tmp_path
        / "validation_evidence.json"
    )

    first = (
        AutoTwinValidationEvidenceStore(
            path=path
        )
    )

    saved = (
        first.record_validation_evidence(
            _evidence()
        )
    )

    second = (
        AutoTwinValidationEvidenceStore(
            path=path
        )
    )

    loaded = (
        second.get_evidence(
            "mercurio",
            "candidate-1",
            saved[
                "record"
            ][
                "evidence_id"
            ],
        )
    )

    assert (
        loaded
        == saved[
            "record"
        ]
    )

    assert (
        second.revision
        == 1
    )


def test_candidate_revision_conflict_is_rejected(
    tmp_path,
):
    store = _store(
        tmp_path
    )

    store.record_validation_evidence(
        _evidence(
            candidate_revision=1
        )
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_VALIDATION_EVIDENCE_"
            "CANDIDATE_REVISION_CONFLICT"
        ),
    ):
        store.record_validation_evidence(
            _evidence(
                candidate_revision=2
            )
        )


def test_tampered_verdict_is_rejected(
    tmp_path,
):
    store = _store(
        tmp_path
    )

    evidence = _evidence()

    evidence[
        "verdict"
    ] = (
        AUTO_TWIN_VALIDATION_VERDICT_FAIL
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_VALIDATION_EVIDENCE_TAMPERED"
        ),
    ):
        store.record_validation_evidence(
            evidence
        )


def test_wrong_schema_is_rejected(
    tmp_path,
):
    store = _store(
        tmp_path
    )

    evidence = _evidence()

    evidence[
        "schema_version"
    ] = 999

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_VALIDATION_EVIDENCE_SCHEMA_INVALID"
        ),
    ):
        store.record_validation_evidence(
            evidence
        )


def test_wrong_type_is_rejected(
    tmp_path,
):
    store = _store(
        tmp_path
    )

    evidence = _evidence()

    evidence[
        "evidence_type"
    ] = "OTHER"

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_VALIDATION_EVIDENCE_TYPE_INVALID"
        ),
    ):
        store.record_validation_evidence(
            evidence
        )


@pytest.mark.parametrize(
    (
        "status",
        "expected_verdict",
        "expected_ready",
    ),
    [
        (
            "PASS",
            AUTO_TWIN_VALIDATION_VERDICT_PASS,
            True,
        ),
        (
            "FAIL",
            AUTO_TWIN_VALIDATION_VERDICT_FAIL,
            False,
        ),
        (
            "INCONCLUSIVE",
            AUTO_TWIN_VALIDATION_VERDICT_INCONCLUSIVE,
            False,
        ),
    ],
)
def test_store_audits_all_verdicts(
    tmp_path,
    status,
    expected_verdict,
    expected_ready,
):
    store = _store(
        tmp_path
    )

    result = (
        store.record_validation_evidence(
            _evidence(
                status=status
            )
        )
    )

    evidence = (
        result[
            "record"
        ][
            "validation_evidence"
        ]
    )

    assert (
        evidence[
            "verdict"
        ]
        == expected_verdict
    )

    assert (
        evidence[
            "ready_for_validation"
        ]
        is expected_ready
    )


def test_latest_for_candidate_returns_latest_audit_record(
    tmp_path,
):
    store = _store(
        tmp_path
    )

    store.record_validation_evidence(
        _evidence(
            twin_capture_id="twin-1"
        )
    )

    second = (
        store.record_validation_evidence(
            _evidence(
                twin_capture_id="twin-2"
            )
        )
    )

    latest = (
        store.latest_for_candidate(
            "mercurio",
            "candidate-1",
        )
    )

    assert (
        latest[
            "evidence_id"
        ]
        == second[
            "record"
        ][
            "evidence_id"
        ]
    )


def test_twin_snapshot_is_lightweight_audit_history(
    tmp_path,
):
    store = _store(
        tmp_path
    )

    store.record_validation_evidence(
        _evidence()
    )

    snapshot = (
        store.snapshot(
            "mercurio"
        )
    )

    assert (
        snapshot[
            "store_type"
        ]
        == AUTO_TWIN_VALIDATION_EVIDENCE_STORE_TYPE
    )

    assert (
        snapshot[
            "candidate_count"
        ]
        == 1
    )

    assert (
        snapshot[
            "evidence_count"
        ]
        == 1
    )

    assert (
        snapshot[
            "candidates"
        ][0][
            "candidate_id"
        ]
        == "candidate-1"
    )


def test_persisted_file_contains_only_lightweight_evidence(
    tmp_path,
):
    store = _store(
        tmp_path
    )

    store.record_validation_evidence(
        _evidence()
    )

    payload = json.loads(
        store.path.read_text(
            encoding="utf-8"
        )
    )

    serialized = json.dumps(
        payload
    ).lower()

    assert (
        "outerhtml"
        not in serialized
    )

    assert (
        "mhtml"
        not in serialized
    )

    assert (
        "screenshot_viewport"
        not in serialized
    )

    assert (
        "image_bytes"
        not in serialized
    )


def test_loaded_tampered_evidence_id_is_rejected(
    tmp_path,
):
    store = _store(
        tmp_path
    )

    result = (
        store.record_validation_evidence(
            _evidence()
        )
    )

    payload = json.loads(
        store.path.read_text(
            encoding="utf-8"
        )
    )

    evidence = (
        payload[
            "twins"
        ][
            "mercurio"
        ][
            "candidates"
        ][
            "candidate-1"
        ][
            "evidence"
        ]
    )

    record = evidence.pop(
        result[
            "record"
        ][
            "evidence_id"
        ]
    )

    evidence[
        "0" * 64
    ] = record

    store.path.write_text(
        json.dumps(
            payload
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_VALIDATION_EVIDENCE_ID_MISMATCH"
        ),
    ):
        AutoTwinValidationEvidenceStore(
            path=store.path
        )
