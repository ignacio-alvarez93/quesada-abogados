import copy
import json

import pytest

from backend.qcc.auto_twin.catalog_dependency_probe import (
    analyze_auto_twin_governed_catalog_probe,
)
from backend.qcc.auto_twin.catalog_dependency_store import (
    AutoTwinCatalogDependencyStore,
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
            "https://reg.redsara.es/es/nuevo-registro",

        "twin_key":
            "red_sara",

        "site_code":
            "RED_SARA",

        "profile_policy": {
            "active_discovery":
                True,

            "active_catalog_probe":
                True,
        },
    }


def _artifact(
    *,
    label="Almería",
    value="04",
    cities=None,
):
    if cities is None:
        cities = [
            "Abla",
            "Abrucena",
            "Adra",
        ]

    return {
        "schema_version":
            1,

        "artifact_type":
            "QCC_GENERIC_CATALOG_CAUSAL_PROBE",

        "safety_mode":
            "GOVERNED_REAL_PROBE",

        "source_selector":
            "#interested\\.province",

        "target_selector":
            "#interested\\.city",

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
                    "#interested\\.province",

                "selected_value":
                    value,

                "selected_label":
                    label,
            },

            "target": {
                "selector":
                    "#interested\\.city",

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


def _evidence(
    **kwargs,
):
    return (
        analyze_auto_twin_governed_catalog_probe(
            _artifact(
                **kwargs
            ),
            authoritative_decision=(
                _decision()
            ),
        )
    )


def test_first_dependency_is_persisted(
    tmp_path,
):
    path = (
        tmp_path
        / "catalog_dependencies.json"
    )

    store = (
        AutoTwinCatalogDependencyStore(
            path=path
        )
    )

    evidence = _evidence()

    result = (
        store.record_dependency(
            evidence
        )
    )

    assert (
        result["created"]
        is True
    )

    assert (
        store.revision
        == 1
    )

    assert path.is_file()

    loaded = (
        store.get_dependency(
            "red_sara",
            evidence[
                "dependency_fingerprint"
            ],
        )
    )

    assert (
        loaded
        == evidence
    )


def test_same_dependency_is_idempotent(
    tmp_path,
):
    store = (
        AutoTwinCatalogDependencyStore(
            path=(
                tmp_path
                / "catalog_dependencies.json"
            )
        )
    )

    evidence = _evidence()

    first = (
        store.record_dependency(
            evidence
        )
    )

    second = (
        store.record_dependency(
            copy.deepcopy(
                evidence
            )
        )
    )

    assert first[
        "created"
    ] is True

    assert second[
        "created"
    ] is False

    assert (
        store.revision
        == 1
    )

    assert len(
        store.list_dependencies(
            twin_key="red_sara"
        )
    ) == 1


def test_different_trigger_creates_new_dependency(
    tmp_path,
):
    store = (
        AutoTwinCatalogDependencyStore(
            path=(
                tmp_path
                / "catalog_dependencies.json"
            )
        )
    )

    almeria = _evidence()

    malaga = _evidence(
        label="Málaga",
        value="29",
        cities=[
            "Málaga",
            "Marbella",
        ],
    )

    store.record_dependency(
        almeria
    )

    store.record_dependency(
        malaga
    )

    assert (
        store.revision
        == 2
    )

    assert len(
        store.list_dependencies(
            twin_key="red_sara"
        )
    ) == 2


def test_store_survives_reload(
    tmp_path,
):
    path = (
        tmp_path
        / "catalog_dependencies.json"
    )

    evidence = _evidence()

    first = (
        AutoTwinCatalogDependencyStore(
            path=path
        )
    )

    first.record_dependency(
        evidence
    )

    second = (
        AutoTwinCatalogDependencyStore(
            path=path
        )
    )

    assert (
        second.revision
        == 1
    )

    assert (
        second.get_dependency(
            "red_sara",
            evidence[
                "dependency_fingerprint"
            ],
        )
        == evidence
    )


def test_store_returns_defensive_copies(
    tmp_path,
):
    store = (
        AutoTwinCatalogDependencyStore(
            path=(
                tmp_path
                / "catalog_dependencies.json"
            )
        )
    )

    evidence = _evidence()

    store.record_dependency(
        evidence
    )

    loaded = (
        store.get_dependency(
            "red_sara",
            evidence[
                "dependency_fingerprint"
            ],
        )
    )

    loaded[
        "target"
    ][
        "options"
    ].clear()

    again = (
        store.get_dependency(
            "red_sara",
            evidence[
                "dependency_fingerprint"
            ],
        )
    )

    assert (
        again[
            "target"
        ][
            "options_count"
        ]
        == 3
    )

    assert len(
        again[
            "target"
        ][
            "options"
        ]
    ) == 3


def test_forged_fingerprint_is_rejected(
    tmp_path,
):
    store = (
        AutoTwinCatalogDependencyStore(
            path=(
                tmp_path
                / "catalog_dependencies.json"
            )
        )
    )

    evidence = _evidence()

    evidence[
        "dependency_fingerprint"
    ] = (
        "0"
        * 64
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_STORE_FINGERPRINT_MISMATCH"
        ),
    ):
        store.record_dependency(
            evidence
        )


def test_corrupt_persisted_counts_are_rejected(
    tmp_path,
):
    path = (
        tmp_path
        / "catalog_dependencies.json"
    )

    store = (
        AutoTwinCatalogDependencyStore(
            path=path
        )
    )

    store.record_dependency(
        _evidence()
    )

    payload = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    payload[
        "dependency_count"
    ] = 999

    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_STORE_COUNTS_INVALID"
        ),
    ):
        AutoTwinCatalogDependencyStore(
            path=path
        )


def test_atomic_write_leaves_no_temp_file(
    tmp_path,
):
    path = (
        tmp_path
        / "catalog_dependencies.json"
    )

    store = (
        AutoTwinCatalogDependencyStore(
            path=path
        )
    )

    store.record_dependency(
        _evidence()
    )

    assert path.is_file()

    assert not (
        path.with_suffix(
            path.suffix
            + ".tmp"
        )
    ).exists()
