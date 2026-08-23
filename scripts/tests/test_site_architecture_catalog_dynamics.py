import pytest

from backend.automation.site_architecture import (
    CATALOG_DYNAMIC_OPTIONS_CHANGED,
    CATALOG_DYNAMIC_SOURCE_SELECTION_CHANGED,
    build_catalog_dynamic_evidence,
)


def _catalog(
    key,
    *,
    value,
    label,
    options,
):
    return {
        "catalog_key":
            key,

        "state": {
            "selected_value":
                value,

            "selected_label":
                label,

            "selected_values":
                (
                    [value]
                    if value
                    else []
                ),

            "selected_index":
                0,
        },

        "options": [
            {
                "value":
                    option_value,

                "label":
                    option_label,

                "disabled":
                    False,
            }
            for (
                option_value,
                option_label,
            )
            in options
        ],
    }


def test_dynamic_evidence_detects_dependent_options_change():
    before = [
        _catalog(
            "main::#parent",
            value="A",
            label="A",
            options=[
                ("A", "A"),
                ("B", "B"),
            ],
        ),
        _catalog(
            "main::#child",
            value="1",
            label="Uno",
            options=[
                ("1", "Uno"),
                ("2", "Dos"),
            ],
        ),
    ]

    after = [
        _catalog(
            "main::#parent",
            value="B",
            label="B",
            options=[
                ("A", "A"),
                ("B", "B"),
            ],
        ),
        _catalog(
            "main::#child",
            value="",
            label="--",
            options=[
                ("", "--"),
                ("9", "Nueve"),
            ],
        ),
    ]

    evidence = (
        build_catalog_dynamic_evidence(
            before,
            after,
            source_catalog_key=(
                "main::#parent"
            ),
        )
    )

    assert len(evidence) == 2

    assert (
        evidence[0]["kind"]
        == CATALOG_DYNAMIC_SOURCE_SELECTION_CHANGED
    )

    assert (
        evidence[1]["kind"]
        == CATALOG_DYNAMIC_OPTIONS_CHANGED
    )

    assert (
        evidence[1]["source"]
        == "main::#parent"
    )

    assert (
        evidence[1]["target"]
        == "main::#child"
    )

    assert (
        evidence[1]["before_options_count"]
        == 2
    )

    assert (
        evidence[1]["after_options_count"]
        == 2
    )


def test_dynamic_evidence_ignores_unchanged_catalogs():
    before = [
        _catalog(
            "main::#source",
            value="1",
            label="Uno",
            options=[
                ("1", "Uno"),
                ("2", "Dos"),
            ],
        ),
        _catalog(
            "main::#stable",
            value="X",
            label="X",
            options=[
                ("X", "X"),
            ],
        ),
    ]

    after = [
        _catalog(
            "main::#source",
            value="2",
            label="Dos",
            options=[
                ("1", "Uno"),
                ("2", "Dos"),
            ],
        ),
        _catalog(
            "main::#stable",
            value="X",
            label="X",
            options=[
                ("X", "X"),
            ],
        ),
    ]

    evidence = (
        build_catalog_dynamic_evidence(
            before,
            after,
            source_catalog_key=(
                "main::#source"
            ),
        )
    )

    assert len(evidence) == 1

    assert (
        evidence[0]["kind"]
        == CATALOG_DYNAMIC_SOURCE_SELECTION_CHANGED
    )


def test_dynamic_evidence_requires_real_source_change():
    catalogs = [
        _catalog(
            "main::#source",
            value="1",
            label="Uno",
            options=[
                ("1", "Uno"),
            ],
        ),
    ]

    with pytest.raises(
        ValueError,
        match=(
            "CATALOG_DYNAMIC_SOURCE_UNCHANGED"
        ),
    ):
        build_catalog_dynamic_evidence(
            catalogs,
            catalogs,
            source_catalog_key=(
                "main::#source"
            ),
        )


def test_dynamic_evidence_requires_known_source():
    catalogs = []

    with pytest.raises(
        ValueError,
        match=(
            "CATALOG_DYNAMIC_SOURCE_NOT_FOUND"
        ),
    ):
        build_catalog_dynamic_evidence(
            catalogs,
            catalogs,
            source_catalog_key=(
                "main::#missing"
            ),
        )
