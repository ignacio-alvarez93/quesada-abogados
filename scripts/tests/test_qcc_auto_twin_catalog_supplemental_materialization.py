from pathlib import Path
import json

import pytest

from backend.qcc.auto_twin.materialization_plan import (
    _load_supplemental_catalog_evidence,
)


PLAN_PATH = Path(
    "backend/qcc/auto_twin/materialization_plan.py"
)

BUILDER_PATH = Path(
    "backend/qcc/auto_twin/materialization_builder.py"
)


def _capture(
    *,
    pathname="/es/nuevo-registro",
    profile="twin_discovery",
):
    return {
        "browser_profile_key":
            profile,

        "frames": [
            {
                "frame_id":
                    0,

                "result": {
                    "pathname":
                        pathname,

                    "catalog_probe": {
                        "schema_version":
                            1,

                        "catalog_count":
                            1,

                        "native_catalog_count":
                            0,

                        "custom_catalog_count":
                            1,

                        "elements": [
                            {
                                "catalog_type":
                                    "custom_select",

                                "implementation":
                                    "dnt-select",

                                "selector":
                                    "#country",

                                "element": {
                                    "tag":
                                        "dnt-select",

                                    "id":
                                        "country",

                                    "name":
                                        "country",

                                    "label_text":
                                        "País",

                                    "attributes":
                                        {},
                                },

                                "state": {
                                    "selected_value":
                                        "724",

                                    "selected_label":
                                        "España",

                                    "selected_values":
                                        ["724"],

                                    "selected_index":
                                        1,

                                    "disabled":
                                        False,

                                    "required":
                                        True,

                                    "multiple":
                                        False,
                                },

                                "options_count":
                                    2,

                                "options": [
                                    {
                                        "value":
                                            "",

                                        "label":
                                            "Portugal",

                                        "selected":
                                            False,

                                        "disabled":
                                            False,
                                    },
                                    {
                                        "value":
                                            "",

                                        "label":
                                            "España",

                                        "selected":
                                            True,

                                        "disabled":
                                            False,
                                    },
                                ],

                                "dependency_hints":
                                    {},
                            },
                        ],
                    },
                },
            },
        ],
    }


def _write_capture(
    root,
    capture_id,
    payload,
):
    directory = (
        root
        / capture_id
    )

    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    (
        directory
        / "qcc_capture.json"
    ).write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_supplemental_catalog_evidence_has_explicit_provenance(
    tmp_path,
):
    capture_id = "catalog-cap-1"

    _write_capture(
        tmp_path,
        capture_id,
        _capture(),
    )

    evidence = (
        _load_supplemental_catalog_evidence(
            root=tmp_path,
            capture_id=capture_id,
            expected_pathname=(
                "/es/nuevo-registro"
            ),
            required_profile_key=(
                "twin_discovery"
            ),
        )
    )

    assert evidence[
        "catalog_source_capture_id"
    ] == capture_id

    assert evidence[
        "catalog_count"
    ] == 1

    assert evidence[
        "catalog_option_count"
    ] == 2

    assert len(
        evidence[
            "catalog_fingerprint"
        ]
    ) == 64


def test_supplemental_catalog_evidence_fails_open_when_capture_missing(
    tmp_path,
    capsys,
):
    # The referenced capture directory never existed under this root
    # (simulates a historical supplemental capture pruned/unavailable
    # while still referenced by carried-forward catalog provenance).
    missing_capture_id = "catalog-cap-does-not-exist"

    evidence = (
        _load_supplemental_catalog_evidence(
            root=tmp_path,
            capture_id=missing_capture_id,
            expected_pathname=(
                "/es/nuevo-registro"
            ),
            required_profile_key=(
                "twin_discovery"
            ),
        )
    )

    # Governed continuation: identical to the existing contract for a
    # state with no catalog_capture_id at all (optional supplemental
    # evidence, never fabricated, never treated as present/complete).
    assert evidence == {}

    logged = capsys.readouterr().out

    assert (
        "QCC_AUTO_TWIN_CATALOG_SUPPLEMENT_CAPTURE_MISSING:"
        + missing_capture_id
    ) in logged


def test_supplemental_catalog_evidence_rejects_wrong_path(
    tmp_path,
):
    _write_capture(
        tmp_path,
        "catalog-cap-1",
        _capture(),
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_CATALOG_PATHNAME_MISMATCH"
        ),
    ):
        _load_supplemental_catalog_evidence(
            root=tmp_path,
            capture_id=(
                "catalog-cap-1"
            ),
            expected_pathname="/otra",
            required_profile_key=(
                "twin_discovery"
            ),
        )


def test_supplemental_catalog_evidence_rejects_empty_catalog(
    tmp_path,
):
    payload = _capture()

    payload[
        "frames"
    ][0][
        "result"
    ][
        "catalog_probe"
    ] = {
        "schema_version":
            1,

        "catalog_count":
            0,

        "elements":
            [],
    }

    _write_capture(
        tmp_path,
        "catalog-empty",
        payload,
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_CATALOG_SUPPLEMENT_EMPTY"
        ),
    ):
        _load_supplemental_catalog_evidence(
            root=tmp_path,
            capture_id="catalog-empty",
            expected_pathname=(
                "/es/nuevo-registro"
            ),
            required_profile_key=(
                "twin_discovery"
            ),
        )


def test_materialization_plan_carries_catalog_supplement_in_state_identity():
    source = PLAN_PATH.read_text(
        encoding="utf-8"
    )

    required = (
        '"catalog_capture_id"',
        '"catalog_source_capture_id"',
        '"catalog_fingerprint"',
        '"catalog_count"',
        '"catalog_option_count"',
        "normalized_states[",
        "].update(",
        "_load_supplemental_catalog_evidence(",
    )

    for token in required:
        assert token in source


def test_materialization_builder_writes_catalog_runtime_artifact():
    source = BUILDER_PATH.read_text(
        encoding="utf-8"
    )

    required = (
        "materialize_catalog_runtime_artifact(",
        '"catalog_source_capture_id"',
        '"catalog_fingerprint"',
        '"catalog_count"',
        '"catalog_option_count"',
        '"qcc_capture.json"',
        "QCC_AUTO_TWIN_CATALOG_SUPPLEMENT_FINGERPRINT_MISMATCH",
        "QCC_AUTO_TWIN_CATALOG_SUPPLEMENT_COUNT_MISMATCH",
        "QCC_AUTO_TWIN_CATALOG_SUPPLEMENT_OPTION_COUNT_MISMATCH",
    )

    for token in required:
        assert token in source


def test_materialized_revision_core_state_manifest_remains_visual_source_only():
    source = BUILDER_PATH.read_text(
        encoding="utf-8"
    )

    start = source.index(
        "revision_state_manifest.append({"
    )

    end = source.index(
        "})",
        start,
    )

    block = source[
        start:end
    ]

    assert (
        '"source_capture_id"'
        in block
    )

    assert (
        '"catalog_source_capture_id"'
        not in block
    )
