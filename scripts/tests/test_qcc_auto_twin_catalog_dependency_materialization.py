import copy
import json

import pytest

from backend.qcc.auto_twin.catalog_dependency_materialization import (
    AUTO_TWIN_CATALOG_DEPENDENCY_RUNTIME_FILENAME,
    build_catalog_dependency_runtime_payload,
    materialize_catalog_dependency_runtime_artifact,
)
from backend.qcc.auto_twin.catalog_dependency_probe import (
    analyze_auto_twin_governed_catalog_probe,
)
from backend.qcc.auto_twin.catalog_probe_decision import (
    AUTO_TWIN_CATALOG_PROBE_DECISION_SCHEMA_VERSION,
    AUTO_TWIN_CATALOG_PROBE_DECISION_TYPE,
)


def _decision():
    return {
        "schema_version":
            AUTO_TWIN_CATALOG_PROBE_DECISION_SCHEMA_VERSION,

        "decision_type":
            AUTO_TWIN_CATALOG_PROBE_DECISION_TYPE,

        "allowed":
            True,

        "reason":
            "ACTIVE_CATALOG_PROBE_ALLOWED",

        "browser_profile_key":
            "twin_discovery",

        "url":
            "https://example.test/es/nuevo-registro",

        "twin_key":
            "example",

        "site_code":
            "EXAMPLE",

        "profile_policy": {
            "active_discovery":
                True,

            "active_catalog_probe":
                True,
        },
    }


def _dependency(
    *,
    value,
    label,
    cities,
):
    artifact = {
        "schema_version":
            1,

        "artifact_type":
            "QCC_GENERIC_CATALOG_CAUSAL_PROBE",

        "safety_mode":
            "GOVERNED_REAL_PROBE",

        "source_selector":
            "#province",

        "target_selector":
            "#city",

        "requested_value":
            value,

        "requested_label":
            label,

        "authority":
            {},

        "before": {
            "source_value":
                "",

            "source_label":
                "",

            "target_options":
                [],
        },

        "observation": {
            "source": {
                "selector":
                    "#province",

                "selected_value":
                    value,

                "selected_label":
                    label,
            },

            "target": {
                "selector":
                    "#city",

                "options_count":
                    len(
                        cities
                    ),

                "options": [
                    {
                        "value":
                            "",

                        "label":
                            city,

                        "disabled":
                            False,
                    }
                    for city
                    in cities
                ],
            },

            "stabilization": {
                "stable":
                    True,
            },
        },

        "restoration": {
            "hard_document_restore": {
                "completed":
                    True,
            },
        },

        "restoration_verification": {
            "exact":
                True,
        },
    }

    return (
        analyze_auto_twin_governed_catalog_probe(
            artifact,
            authoritative_decision=(
                _decision()
            ),
        )
    )


def test_runtime_payload_is_deterministic_and_sorted():
    first = _dependency(
        value="04",
        label="Almería",
        cities=[
            "Abla",
            "Abrucena",
        ],
    )

    second = _dependency(
        value="29",
        label="Málaga",
        cities=[
            "Málaga",
            "Marbella",
        ],
    )

    a = build_catalog_dependency_runtime_payload(
        twin_key="example",
        pathname="/es/nuevo-registro",
        dependencies=[
            second,
            first,
        ],
    )

    b = build_catalog_dependency_runtime_payload(
        twin_key="example",
        pathname="/es/nuevo-registro",
        dependencies=[
            first,
            second,
        ],
    )

    assert a == b

    assert (
        a["dependency_count"]
        == 2
    )

    assert (
        a["dependency_fingerprints"]
        == sorted(
            a[
                "dependency_fingerprints"
            ]
        )
    )

    assert len(
        a[
            "catalog_dependency_fingerprint"
        ]
    ) == 64


def test_runtime_preserves_value_or_label_options():
    dependency = _dependency(
        value="04",
        label="Almería",
        cities=[
            "Abla",
            "Abrucena",
        ],
    )

    result = (
        build_catalog_dependency_runtime_payload(
            twin_key="example",
            pathname="/es/nuevo-registro",
            dependencies=[
                dependency
            ],
        )
    )

    options = (
        result[
            "dependencies"
        ][0][
            "target"
        ][
            "options"
        ]
    )

    assert options == [
        {
            "value": "",
            "label": "Abla",
            "disabled": False,
        },
        {
            "value": "",
            "label": "Abrucena",
            "disabled": False,
        },
    ]


def test_runtime_rejects_forged_dependency_fingerprint():
    dependency = _dependency(
        value="04",
        label="Almería",
        cities=[
            "Abla",
        ],
    )

    dependency[
        "dependency_fingerprint"
    ] = (
        "0"
        * 64
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_RUNTIME_FINGERPRINT_MISMATCH"
        ),
    ):
        build_catalog_dependency_runtime_payload(
            twin_key="example",
            pathname="/es/nuevo-registro",
            dependencies=[
                dependency
            ],
        )


def test_runtime_rejects_wrong_twin_or_path():
    dependency = _dependency(
        value="04",
        label="Almería",
        cities=[
            "Abla",
        ],
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_RUNTIME_TWIN_MISMATCH"
        ),
    ):
        build_catalog_dependency_runtime_payload(
            twin_key="other",
            pathname="/es/nuevo-registro",
            dependencies=[
                dependency
            ],
        )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_RUNTIME_PATHNAME_MISMATCH"
        ),
    ):
        build_catalog_dependency_runtime_payload(
            twin_key="example",
            pathname="/otra",
            dependencies=[
                dependency
            ],
        )


def test_writer_creates_runtime_catalog_dependencies_json(
    tmp_path,
):
    dependency = _dependency(
        value="04",
        label="Almería",
        cities=[
            "Abla",
            "Abrucena",
        ],
    )

    result = (
        materialize_catalog_dependency_runtime_artifact(
            runtime_dir=tmp_path,
            twin_key="example",
            pathname="/es/nuevo-registro",
            dependencies=[
                dependency
            ],
        )
    )

    expected = (
        tmp_path
        / AUTO_TWIN_CATALOG_DEPENDENCY_RUNTIME_FILENAME
    )

    assert (
        result["path"]
        == expected
    )

    assert expected.is_file()

    persisted = json.loads(
        expected.read_text(
            encoding="utf-8"
        )
    )

    assert (
        persisted[
            "dependency_count"
        ]
        == 1
    )

    assert (
        persisted[
            "dependencies"
        ][0][
            "trigger"
        ][
            "value"
        ]
        == "04"
    )


def test_materializer_is_provider_neutral():
    from pathlib import Path

    source = Path(
        "backend/qcc/auto_twin/"
        "catalog_dependency_materialization.py"
    ).read_text(
        encoding="utf-8"
    ).lower()

    assert "red_sara" not in source
    assert "mercurio" not in source
    assert "dnt-select" not in source
