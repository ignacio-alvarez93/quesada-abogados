import json

import pytest

from backend.qcc.auto_twin.catalog_materialization import (
    AUTO_TWIN_CATALOG_OPTION_IDENTITY_MODE,
    AUTO_TWIN_CATALOG_RUNTIME_TYPE,
    build_catalog_runtime_payload,
    materialize_catalog_runtime_artifact,
)


def _capture(
    catalogs,
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
                            len(
                                catalogs
                            ),

                        "elements":
                            catalogs,
                    },
                },
            },
        ],
    }


def _custom_catalog(
    *,
    element_id="country",
    label="País",
    selected_value="724",
    selected_label="España",
    options=None,
):
    if options is None:
        options = [
            {
                "value": "",
                "label": "Portugal",
                "selected": False,
                "disabled": False,
            },
            {
                "value": "",
                "label": "España",
                "selected": True,
                "disabled": False,
            },
        ]

    return {
        "catalog_type":
            "custom_select",

        "implementation":
            "dnt-select",

        "selector":
            "#"
            + element_id,

        "element": {
            "tag":
                "dnt-select",

            "id":
                element_id,

            "name":
                element_id,

            "classes": [
                "hydrated",
            ],

            "label_text":
                label,

            "attributes": {
                "select-label":
                    label,
            },
        },

        "state": {
            "selected_value":
                selected_value,

            "selected_label":
                selected_label,

            "selected_values": [
                selected_value,
            ]
            if selected_value
            else [],

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

        # Deben desaparecer del runtime.
        "property_surface": {
            "diagnostic":
                True,
        },

        "value_evidence": {
            "diagnostic":
                True,
        },
    }


def test_catalog_runtime_preserves_custom_catalog_contract():
    payload = (
        build_catalog_runtime_payload(
            qcc_capture_payload=(
                _capture([
                    _custom_catalog()
                ])
            ),
            source_capture_id="cap-1",
            expected_pathname=(
                "/es/nuevo-registro"
            ),
            required_profile_key=(
                "twin_discovery"
            ),
        )
    )

    assert (
        payload["record_type"]
        == AUTO_TWIN_CATALOG_RUNTIME_TYPE
    )

    assert (
        payload["source_capture_id"]
        == "cap-1"
    )

    assert (
        payload["source_profile_key"]
        == "twin_discovery"
    )

    assert (
        payload["catalog_count"]
        == 1
    )

    assert (
        payload["option_count"]
        == 2
    )

    catalog = payload[
        "catalogs"
    ][0]

    assert (
        catalog["catalog_type"]
        == "custom_select"
    )

    assert (
        catalog["implementation"]
        == "dnt-select"
    )

    assert (
        catalog["catalog_key"]
        == "main::#country"
    )

    assert (
        catalog["state"][
            "selected_value"
        ]
        == "724"
    )

    assert (
        catalog["state"][
            "selected_label"
        ]
        == "España"
    )


def test_catalog_runtime_accepts_label_identity_without_raw_value():
    payload = (
        build_catalog_runtime_payload(
            qcc_capture_payload=(
                _capture([
                    _custom_catalog()
                ])
            ),
            source_capture_id="cap-1",
        )
    )

    options = (
        payload[
            "catalogs"
        ][0]["options"]
    )

    assert options == [
        {
            "value": "",
            "label": "Portugal",
            "selected": False,
            "disabled": False,
        },
        {
            "value": "",
            "label": "España",
            "selected": True,
            "disabled": False,
        },
    ]

    assert (
        payload[
            "option_identity_mode"
        ]
        == AUTO_TWIN_CATALOG_OPTION_IDENTITY_MODE
    )


def test_catalog_runtime_preserves_empty_dynamic_target():
    payload = (
        build_catalog_runtime_payload(
            qcc_capture_payload=(
                _capture([
                    _custom_catalog(
                        element_id=(
                            "interested.city"
                        ),
                        label="Población",
                        selected_value="",
                        selected_label="",
                        options=[],
                    )
                ])
            ),
            source_capture_id="cap-city",
        )
    )

    catalog = payload[
        "catalogs"
    ][0]

    assert (
        catalog["options_count"]
        == 0
    )

    assert (
        catalog["options"]
        == []
    )


def test_catalog_runtime_strips_diagnostic_probe_payload():
    payload = (
        build_catalog_runtime_payload(
            qcc_capture_payload=(
                _capture([
                    _custom_catalog()
                ])
            ),
            source_capture_id="cap-clean",
        )
    )

    serialized = json.dumps(
        payload,
        ensure_ascii=False,
    )

    assert (
        "property_surface"
        not in serialized
    )

    assert (
        "value_evidence"
        not in serialized
    )

    assert (
        "diagnostic"
        not in serialized
    )


def test_catalog_runtime_validates_pathname():
    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_CATALOG_PATHNAME_MISMATCH"
        ),
    ):
        build_catalog_runtime_payload(
            qcc_capture_payload=(
                _capture([
                    _custom_catalog()
                ])
            ),
            source_capture_id="cap-1",
            expected_pathname="/otra",
        )


def test_catalog_runtime_validates_discovery_profile():
    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_CATALOG_PROFILE_NOT_AUTHORIZED"
        ),
    ):
        build_catalog_runtime_payload(
            qcc_capture_payload=(
                _capture(
                    [
                        _custom_catalog()
                    ],
                    profile="browser-normal",
                )
            ),
            source_capture_id="cap-1",
            required_profile_key=(
                "twin_discovery"
            ),
        )


def test_catalog_runtime_fingerprint_is_deterministic():
    capture = _capture([
        _custom_catalog()
    ])

    first = (
        build_catalog_runtime_payload(
            qcc_capture_payload=capture,
            source_capture_id="cap-a",
        )
    )

    second = (
        build_catalog_runtime_payload(
            qcc_capture_payload=capture,
            source_capture_id="cap-b",
        )
    )

    # La procedencia puede variar sin alterar
    # el contenido funcional del catálogo.
    assert (
        first[
            "catalog_fingerprint"
        ]
        == second[
            "catalog_fingerprint"
        ]
    )


def test_materialize_catalog_runtime_artifact_writes_catalogs_json(
    tmp_path,
):
    capture = _capture([
        _custom_catalog()
    ])

    capture_path = (
        tmp_path
        / "qcc_capture.json"
    )

    capture_path.write_text(
        json.dumps(
            capture,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = (
        materialize_catalog_runtime_artifact(
            qcc_capture_path=(
                capture_path
            ),
            runtime_dir=(
                tmp_path
                / "runtime"
            ),
            source_capture_id="cap-physical",
            expected_pathname=(
                "/es/nuevo-registro"
            ),
            required_profile_key=(
                "twin_discovery"
            ),
        )
    )

    target = result[
        "path"
    ]

    assert target.is_file()

    persisted = json.loads(
        target.read_text(
            encoding="utf-8"
        )
    )

    assert (
        persisted[
            "source_capture_id"
        ]
        == "cap-physical"
    )

    assert (
        persisted[
            "catalog_count"
        ]
        == 1
    )
