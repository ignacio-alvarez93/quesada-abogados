import copy

import pytest

from backend.automation.site_architecture import (
    CATALOG_DYNAMIC_OPTIONS_CHANGED,
    CATALOG_DYNAMIC_SOURCE_SELECTION_CHANGED,
    analyze_qcc_catalog_experiment,
)


TWIN_ORIGIN = (
    "http://127.0.0.1:8767"
)


def _catalog(
    element_id,
    *,
    value,
    label,
    options,
):
    return {
        "catalog_type":
            "native_select",

        "selector":
            f"#{element_id}",

        "element": {
            "tag":
                "select",
            "id":
                element_id,
            "name":
                element_id,
            "classes":
                [],
            "attributes":
                {},
        },

        "state": {
            "selected_value":
                value,
            "selected_label":
                label,
            "selected_values":
                [value] if value else [],
            "selected_index":
                0,
            "disabled":
                False,
            "required":
                False,
            "multiple":
                False,
        },

        "options_count":
            len(options),

        "options": [
            {
                "value":
                    option_value,
                "label":
                    option_label,
                "selected":
                    option_value == value,
                "disabled":
                    False,
            }
            for (
                option_value,
                option_label,
            )
            in options
        ],

        "dependency_hints":
            {},
    }


def _capture(catalogs):
    frame = {
        "schema_version":
            1,

        "captured_at":
            "2026-08-23T21:00:00Z",

        "url":
            (
                TWIN_ORIGIN
                + "/mercurio/"
                + "nuevaSolicitud-EX01.html"
            ),

        "origin":
            TWIN_ORIGIN,

        "pathname":
            "/mercurio/nuevaSolicitud-EX01.html",

        "title":
            "Mercurio Twin",

        "ready_state":
            "complete",

        "content_type":
            "text/html",

        "character_set":
            "UTF-8",

        "html":
            "<html></html>",

        "counts": {
            "elements":
                0,
        },

        "elements":
            [],

        "shadow_roots":
            [],

        "catalog_probe": {
            "schema_version":
                1,

            "catalog_count":
                len(catalogs),

            "elements":
                catalogs,
        },
    }

    return {
        "ok":
            True,

        "capture_type":
            "QCC_EXTENSION_DOM_CAPTURE",

        "schema_version":
            1,

        "captured_at":
            "2026-08-23T21:00:00Z",

        "tab_id":
            10,

        "captured_frames":
            1,

        "main_url":
            frame["url"],

        "frames": [{
            "frame_id":
                0,

            "document_id":
                "main-doc",

            "result":
                frame,
        }],
    }


def _experiment():
    before_catalogs = [
        _catalog(
            "province",
            value="33",
            label="ASTURIAS",
            options=[
                ("15", "A CORUÑA"),
                ("33", "ASTURIAS"),
            ],
        ),
        _catalog(
            "municipality",
            value="24",
            label="GIJON",
            options=[
                ("24", "GIJON"),
                ("44", "OVIEDO"),
            ],
        ),
        _catalog(
            "locality",
            value="",
            label="--",
            options=[
                ("", "--"),
                ("030000", "CABUEÑES"),
            ],
        ),
    ]

    after_catalogs = [
        _catalog(
            "province",
            value="15",
            label="A CORUÑA",
            options=[
                ("15", "A CORUÑA"),
                ("33", "ASTURIAS"),
            ],
        ),
        _catalog(
            "municipality",
            value="",
            label="--",
            options=[
                ("", "--"),
                ("001", "A CORUÑA"),
            ],
        ),
        _catalog(
            "locality",
            value="",
            label="--",
            options=[
                ("", "--"),
            ],
        ),
    ]

    before = _capture(
        before_catalogs
    )

    after = _capture(
        after_catalogs
    )

    restored = copy.deepcopy(
        before
    )

    return {
        "ok":
            True,

        "experiment_type":
            "QCC_CATALOG_EXPERIMENT",

        "schema_version":
            1,

        "safety_mode":
            "TWIN_ONLY",

        "origin":
            TWIN_ORIGIN,

        "selector":
            "#province",

        "restoration_verification": {
            "exact":
                True,
            "compared_catalogs":
                3,
        },

        "before":
            before,

        "after":
            after,

        "restored":
            restored,
    }


def test_analyzer_builds_dynamic_evidence():
    result = (
        analyze_qcc_catalog_experiment(
            _experiment()
        )
    )

    assert (
        result["source_catalog_key"]
        == "main::#province"
    )

    assert result[
        "restoration_exact"
    ] is True

    assert result[
        "compared_catalogs"
    ] == 3

    evidence = result[
        "evidence"
    ]

    assert len(evidence) == 3

    assert (
        evidence[0]["kind"]
        == CATALOG_DYNAMIC_SOURCE_SELECTION_CHANGED
    )

    changed = {
        item["target"]
        for item in evidence
        if (
            item["kind"]
            == CATALOG_DYNAMIC_OPTIONS_CHANGED
        )
    }

    assert changed == {
        "main::#municipality",
        "main::#locality",
    }


def test_analyzer_rejects_non_twin_origin():
    experiment = _experiment()

    experiment["origin"] = (
        "https://example.test"
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_CATALOG_EXPERIMENT_ORIGIN_INVALID"
        ),
    ):
        analyze_qcc_catalog_experiment(
            experiment
        )


def test_analyzer_rejects_forged_restore_flag():
    experiment = _experiment()

    restored = experiment[
        "restored"
    ]

    catalog = (
        restored["frames"][0]
        ["result"]["catalog_probe"]
        ["elements"][1]
    )

    catalog["state"][
        "selected_value"
    ] = ""

    catalog["state"][
        "selected_values"
    ] = []

    with pytest.raises(
        ValueError,
        match=(
            "QCC_CATALOG_EXPERIMENT_RESTORE_STATE_MISMATCH"
        ),
    ):
        analyze_qcc_catalog_experiment(
            experiment
        )


def test_analyzer_requires_declared_restoration_success():
    experiment = _experiment()

    experiment[
        "restoration_verification"
    ]["exact"] = False

    with pytest.raises(
        ValueError,
        match=(
            "QCC_CATALOG_EXPERIMENT_NOT_RESTORED"
        ),
    ):
        analyze_qcc_catalog_experiment(
            experiment
        )
