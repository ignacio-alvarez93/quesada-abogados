from pathlib import Path
import json

import pytest

from backend.qcc.auto_twin.catalog_refresh import (
    AUTO_TWIN_CATALOG_REFRESH_NO_CHANGE,
    AUTO_TWIN_CATALOG_REFRESH_NO_EVIDENCE,
    AUTO_TWIN_CATALOG_REFRESH_REQUIRED,
    decide_catalog_refresh,
)


PATHNAME = "/es/nuevo-registro"
FUNCTIONAL_STATE = "STATE-REGISTRO"


def _catalog_capture(
    *,
    labels=("Portugal", "España"),
    selected_label="España",
    selected_value="724",
    profile="twin_discovery",
):
    options = [
        {
            "value":
                "",

            "label":
                label,

            "selected":
                (
                    label
                    == selected_label
                ),

            "disabled":
                False,
        }
        for label in labels
    ]

    return {
        "browser_profile_key":
            profile,

        "frames": [
            {
                "frame_id":
                    0,

                "result": {
                    "pathname":
                        PATHNAME,

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
                                        selected_value,

                                    "selected_label":
                                        selected_label,

                                    "selected_values":
                                        [
                                            selected_value
                                        ],

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
                                    len(
                                        options
                                    ),

                                "options":
                                    options,

                                "dependency_hints":
                                    {},
                            },
                        ],
                    },
                },
            },
        ],
    }


def _empty_capture():
    payload = (
        _catalog_capture()
    )

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

        "native_catalog_count":
            0,

        "custom_catalog_count":
            0,

        "elements":
            [],
    }

    return payload


def _revision(
    root,
    *,
    catalog_fingerprint=None,
):
    revision = (
        root
        / "matrev-test"
    )

    runtime = (
        revision
        / "states"
        / "01-STATE"
        / "runtime"
    )

    runtime.mkdir(
        parents=True
    )

    state = {
        "state_id":
            "STATE",

        "source_capture_id":
            "visual-cap",

        "pathname":
            PATHNAME,

        "functional_state":
            FUNCTIONAL_STATE,

        "runtime_renderer_version":
            3,
    }

    if catalog_fingerprint:
        state[
            "catalog_fingerprint"
        ] = (
            catalog_fingerprint
        )

    (
        runtime
        / "state.json"
    ).write_text(
        json.dumps(
            state
        ),
        encoding="utf-8",
    )

    registry_dir = (
        revision
        / "runtime"
    )

    registry_dir.mkdir(
        parents=True
    )

    (
        registry_dir
        / "registry.json"
    ).write_text(
        json.dumps({
            "states": [
                {
                    **state,

                    "runtime_entry":
                        (
                            "states/"
                            "01-STATE/"
                            "runtime/"
                            "index.html"
                        ),
                },
            ],
        }),
        encoding="utf-8",
    )

    return revision


def _candidate_fingerprint(
    tmp_path,
):
    revision = _revision(
        tmp_path
    )

    result = (
        decide_catalog_refresh(
            qcc_capture_payload=(
                _catalog_capture()
            ),
            trigger_capture_id=(
                "catalog-cap"
            ),
            revision_dir=revision,
            pathname=PATHNAME,
            functional_state=(
                FUNCTIONAL_STATE
            ),
            required_profile_key=(
                "twin_discovery"
            ),
        )
    )

    assert (
        result["status"]
        == AUTO_TWIN_CATALOG_REFRESH_REQUIRED
    )

    return (
        result[
            "candidate_catalog_fingerprint"
        ]
    )


def test_catalog_refresh_required_when_twin_has_no_catalog(
    tmp_path,
):
    revision = _revision(
        tmp_path
    )

    result = (
        decide_catalog_refresh(
            qcc_capture_payload=(
                _catalog_capture()
            ),
            trigger_capture_id=(
                "catalog-cap-1"
            ),
            revision_dir=revision,
            pathname=PATHNAME,
            functional_state=(
                FUNCTIONAL_STATE
            ),
            required_profile_key=(
                "twin_discovery"
            ),
        )
    )

    assert (
        result["status"]
        == AUTO_TWIN_CATALOG_REFRESH_REQUIRED
    )

    assert (
        result["reason"]
        == "CATALOG_NOT_MATERIALIZED"
    )

    assert result[
        "candidate_catalog_fingerprint"
    ]

    assert (
        result[
            "current_catalog_fingerprint"
        ]
        is None
    )


def test_catalog_refresh_no_change_for_same_fingerprint(
    tmp_path,
):
    fingerprint = (
        _candidate_fingerprint(
            tmp_path
            / "first"
        )
    )

    revision = _revision(
        tmp_path
        / "second",
        catalog_fingerprint=(
            fingerprint
        ),
    )

    result = (
        decide_catalog_refresh(
            qcc_capture_payload=(
                _catalog_capture()
            ),
            trigger_capture_id=(
                "catalog-cap-new"
            ),
            revision_dir=revision,
            pathname=PATHNAME,
            functional_state=(
                FUNCTIONAL_STATE
            ),
            required_profile_key=(
                "twin_discovery"
            ),
        )
    )

    assert (
        result["status"]
        == AUTO_TWIN_CATALOG_REFRESH_NO_CHANGE
    )

    assert (
        result["reason"]
        == "CATALOG_FINGERPRINT_UNCHANGED"
    )


def test_catalog_refresh_required_when_options_change(
    tmp_path,
):
    fingerprint = (
        _candidate_fingerprint(
            tmp_path
            / "first"
        )
    )

    revision = _revision(
        tmp_path
        / "second",
        catalog_fingerprint=(
            fingerprint
        ),
    )

    changed = _catalog_capture(
        labels=(
            "Portugal",
            "España",
            "Francia",
        )
    )

    result = (
        decide_catalog_refresh(
            qcc_capture_payload=changed,
            trigger_capture_id=(
                "catalog-cap-changed"
            ),
            revision_dir=revision,
            pathname=PATHNAME,
            functional_state=(
                FUNCTIONAL_STATE
            ),
            required_profile_key=(
                "twin_discovery"
            ),
        )
    )

    assert (
        result["status"]
        == AUTO_TWIN_CATALOG_REFRESH_REQUIRED
    )

    assert (
        result["reason"]
        == "CATALOG_FINGERPRINT_CHANGED"
    )

    assert (
        result[
            "candidate_catalog_fingerprint"
        ]
        != result[
            "current_catalog_fingerprint"
        ]
    )


def test_catalog_refresh_skips_empty_probe(
    tmp_path,
):
    revision = _revision(
        tmp_path
    )

    result = (
        decide_catalog_refresh(
            qcc_capture_payload=(
                _empty_capture()
            ),
            trigger_capture_id=(
                "catalog-empty"
            ),
            revision_dir=revision,
            pathname=PATHNAME,
            functional_state=(
                FUNCTIONAL_STATE
            ),
            required_profile_key=(
                "twin_discovery"
            ),
        )
    )

    assert (
        result["status"]
        == AUTO_TWIN_CATALOG_REFRESH_NO_EVIDENCE
    )

    assert (
        result["catalog_count"]
        == 0
    )


def test_catalog_refresh_rejects_wrong_profile(
    tmp_path,
):
    revision = _revision(
        tmp_path
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_CATALOG_PROFILE_NOT_AUTHORIZED"
        ),
    ):
        decide_catalog_refresh(
            qcc_capture_payload=(
                _catalog_capture(
                    profile="normal"
                )
            ),
            trigger_capture_id=(
                "catalog-cap"
            ),
            revision_dir=revision,
            pathname=PATHNAME,
            functional_state=(
                FUNCTIONAL_STATE
            ),
            required_profile_key=(
                "twin_discovery"
            ),
        )


def test_catalog_refresh_requires_exact_state_identity(
    tmp_path,
):
    revision = _revision(
        tmp_path
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_CATALOG_REFRESH_STATE_IDENTITY_AMBIGUOUS"
        ),
    ):
        decide_catalog_refresh(
            qcc_capture_payload=(
                _catalog_capture()
            ),
            trigger_capture_id=(
                "catalog-cap"
            ),
            revision_dir=revision,
            pathname=PATHNAME,
            functional_state=(
                "OTHER-STATE"
            ),
            required_profile_key=(
                "twin_discovery"
            ),
        )


def test_catalog_refresh_decision_does_not_mutate_revision(
    tmp_path,
):
    revision = _revision(
        tmp_path
    )

    before = {
        path.relative_to(
            revision
        ).as_posix():
            path.read_bytes()

        for path in revision.rglob("*")
        if path.is_file()
    }

    decide_catalog_refresh(
        qcc_capture_payload=(
            _catalog_capture()
        ),
        trigger_capture_id=(
            "catalog-cap"
        ),
        revision_dir=revision,
        pathname=PATHNAME,
        functional_state=(
            FUNCTIONAL_STATE
        ),
        required_profile_key=(
            "twin_discovery"
        ),
    )

    after = {
        path.relative_to(
            revision
        ).as_posix():
            path.read_bytes()

        for path in revision.rglob("*")
        if path.is_file()
    }

    assert before == after
