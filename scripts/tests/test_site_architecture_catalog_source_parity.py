from backend.automation.site_architecture.catalogs import (
    merge_catalogs_with_select_actions,
    normalize_catalogs,
)


def _select_action():
    return {
        "kind":
            "SELECT",

        "policy":
            "STATE_CHANGE_CANDIDATE",

        "selector":
            "#province",

        "frame_path":
            "main",

        "element": {
            "tag":
                "select",

            "id":
                "province",

            "name":
                "province",

            "type":
                "",

            "role":
                "",
        },
    }


def test_select_action_creates_minimal_native_catalog():
    catalogs = normalize_catalogs(
        merge_catalogs_with_select_actions(
            (),
            (
                _select_action(),
            ),
        )
    )

    assert len(catalogs) == 1

    catalog = catalogs[0]

    assert (
        catalog["catalog_type"]
        == "native_select"
    )

    assert (
        catalog["selector"]
        == "#province"
    )

    assert (
        catalog["frame_path"]
        == "main"
    )

    assert (
        catalog["catalog_key"]
        == "main::#province"
    )


def test_explicit_qcc_catalog_prevents_duplicate():
    explicit = {
        "catalog_type":
            "native_select",

        "selector":
            "#province",

        "frame_path":
            "main",

        "element": {
            "tag":
                "select",

            "id":
                "province",

            "name":
                "province",
        },

        "state": {
            "selected_value":
                "33",

            "selected_label":
                "ASTURIAS",
        },

        "options_count":
            2,

        "options": [
            {
                "value":
                    "",

                "label":
                    "--",
            },
            {
                "value":
                    "33",

                "label":
                    "ASTURIAS",
            },
        ],

        "dependency_hints":
            {},
    }

    catalogs = normalize_catalogs(
        merge_catalogs_with_select_actions(
            (
                explicit,
            ),
            (
                _select_action(),
            ),
        )
    )

    assert len(catalogs) == 1

    catalog = catalogs[0]

    assert (
        catalog["state"][
            "selected_value"
        ]
        == "33"
    )

    assert (
        catalog["options_count"]
        == 2
    )


def test_non_select_action_does_not_create_catalog():
    catalogs = normalize_catalogs(
        merge_catalogs_with_select_actions(
            (),
            ({
                "kind":
                    "LINK",

                "selector":
                    "#continue",

                "frame_path":
                    "main",

                "element": {
                    "tag":
                        "a",
                },
            },),
        )
    )

    assert catalogs == ()
