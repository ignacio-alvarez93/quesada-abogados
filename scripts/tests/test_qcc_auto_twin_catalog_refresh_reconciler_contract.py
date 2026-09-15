from copy import deepcopy
import inspect


from backend.qcc.auto_twin.catalog_materialization import (
    _catalog_knowledge_projection,
)

from backend.qcc.auto_twin.catalog_refresh import (
    decide_catalog_refresh,
    materialized_catalog_provenance,
)

from backend.qcc.auto_twin.materialized_revision import (
    AUTO_TWIN_MATERIALIZATION_MODE_CATALOG_REFRESH,
    AUTO_TWIN_MATERIALIZATION_MODES,
)


def _catalogs():
    return [
        {
            "catalog_key":
                "main::#country",

            "catalog_type":
                "custom_select",

            "selector":
                "#country",

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
    ]


def test_catalog_knowledge_projection_ignores_current_selection():
    left = _catalogs()

    right = deepcopy(
        left
    )

    right[
        0
    ][
        "state"
    ][
        "selected_value"
    ] = "620"

    right[
        0
    ][
        "state"
    ][
        "selected_label"
    ] = "Portugal"

    right[
        0
    ][
        "state"
    ][
        "selected_values"
    ] = ["620"]

    right[
        0
    ][
        "state"
    ][
        "selected_index"
    ] = 0

    right[
        0
    ][
        "options"
    ][0][
        "selected"
    ] = True

    right[
        0
    ][
        "options"
    ][1][
        "selected"
    ] = False

    assert (
        _catalog_knowledge_projection(
            pathname="/es/nuevo-registro",
            catalogs=left,
        )
        ==
        _catalog_knowledge_projection(
            pathname="/es/nuevo-registro",
            catalogs=right,
        )
    )


def test_catalog_knowledge_projection_detects_new_option():
    left = _catalogs()

    right = deepcopy(
        left
    )

    right[
        0
    ][
        "options"
    ].append({
        "value":
            "",

        "label":
            "Francia",

        "selected":
            False,

        "disabled":
            False,
    })

    assert (
        _catalog_knowledge_projection(
            pathname="/es/nuevo-registro",
            catalogs=left,
        )
        !=
        _catalog_knowledge_projection(
            pathname="/es/nuevo-registro",
            catalogs=right,
        )
    )


def test_catalog_refresh_mode_is_explicit_materialization_mode():
    assert (
        AUTO_TWIN_MATERIALIZATION_MODE_CATALOG_REFRESH
        == "CATALOG_REFRESH"
    )

    assert (
        AUTO_TWIN_MATERIALIZATION_MODE_CATALOG_REFRESH
        in AUTO_TWIN_MATERIALIZATION_MODES
    )


def test_catalog_refresh_accepts_none_functional_state_contract():
    source = inspect.getsource(
        decide_catalog_refresh
    )

    assert (
        "QCC_AUTO_TWIN_CATALOG_REFRESH_FUNCTIONAL_STATE_REQUIRED"
        not in source
    )


def test_catalog_provenance_reader_is_backward_compatible(
    tmp_path,
):
    result = (
        materialized_catalog_provenance(
            revision_dir=(
                tmp_path
                / "old-revision"
            ),
            pathname=(
                "/es/nuevo-registro"
            ),
            functional_state=None,
        )
    )

    assert result == {}


# F3C2-A4.4B · visual CHANGED and catalog knowledge are orthogonal.

from backend.qcc.auto_twin.automatic_materialization import (
    _catalog_refresh_identity_for_trigger,
)


def test_catalog_refresh_known_identity_is_not_blocked_by_changed_classification():
    identity = (
        "/es/nuevo-registro",
        None,
    )

    observed_states = {
        "state-key": {
            "pathname":
                "/es/nuevo-registro",

            "functional_state":
                None,

            "last_capture_id":
                "cap-catalog",

            "last_classification":
                "CHANGED",
        }
    }

    result, discriminator = (
        _catalog_refresh_identity_for_trigger(
            observed_states=(
                observed_states
            ),
            known_identities={
                identity
            },
            trigger_capture_id=(
                "cap-catalog"
            ),
        )
    )

    assert result == identity
    assert isinstance(discriminator, dict)


def test_catalog_refresh_changed_unknown_identity_still_does_not_enter_refresh():
    observed_states = {
        "state-key": {
            "pathname":
                "/es/new-unknown-state",

            "functional_state":
                None,

            "last_capture_id":
                "cap-catalog",

            "last_classification":
                "CHANGED",
        }
    }

    result, discriminator = (
        _catalog_refresh_identity_for_trigger(
            observed_states=(
                observed_states
            ),
            known_identities={
                (
                    "/es/nuevo-registro",
                    None,
                )
            },
            trigger_capture_id=(
                "cap-catalog"
            ),
        )
    )

    assert result is None
    assert discriminator is None
