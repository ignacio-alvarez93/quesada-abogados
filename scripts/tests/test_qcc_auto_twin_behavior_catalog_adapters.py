from copy import deepcopy

import pytest

from backend.automation.site_architecture.catalog_dynamics import (
    catalog_option_identity_signature,
)

from backend.qcc.auto_twin import (
    AUTO_TWIN_BEHAVIOR_KIND_CATALOG_MUTATION,
    AUTO_TWIN_BEHAVIOR_SOURCE_REAL_CONTROLLED_HARVEST,
    AUTO_TWIN_BEHAVIOR_SOURCE_TWIN_CONTROLLED,
    behavior_trace_from_real_catalog_harvest,
    behavior_trace_from_twin_catalog_analysis,
    compare_auto_twin_behavior,
)


def _options(*values):
    return [
        {
            "value":
                value,

            "label":
                value.upper(),

            "disabled":
                False,
        }
        for value in values
    ]


def _real_artifact():
    return {
        "schema_version":
            1,

        "artifact_type":
            "QCC_SITE_CATALOG_HARVEST",

        "source_system":
            "MERCURIO",

        "origin":
            "https://mercurio.delegaciondelgobierno.gob.es",

        "pathname":
            "/mercurio/form.html",

        "harvested_at":
            "2026-09-05T10:00:00Z",

        "source": {
            "selector":
                "#province",

            "options": [
                {
                    "value":
                        "33",

                    "label":
                        "ASTURIAS",

                    "disabled":
                        False,
                },
                {
                    "value":
                        "28",

                    "label":
                        "MADRID",

                    "disabled":
                        False,
                },
            ],
        },

        "target": {
            "selector":
                "#municipality",
        },

        "observations": [
            {
                "source_value":
                    "33",

                "source_label":
                    "ASTURIAS",

                "target_options":
                    _options(
                        "33001",
                        "33002",
                    ),
            },
            {
                "source_value":
                    "28",

                "source_label":
                    "MADRID",

                "target_options":
                    _options(
                        "28001",
                        "28002",
                        "28003",
                    ),
            },
        ],

        "completion": {
            "source_options":
                2,

            "observations":
                2,

            "complete":
                True,
        },

        "restoration": {
            "attempted":
                True,

            "exact":
                True,
        },
    }


def _twin_analysis():
    return {
        "source_catalog_key":
            "main::#province",

        "selector":
            "#province",

        "evidence": (
            {
                "kind":
                    "SOURCE_SELECTION_CHANGED",

                "source":
                    "main::#province",

                "target":
                    "main::#province",

                "before": {
                    "selected_value":
                        "33",

                    "selected_label":
                        "ASTURIAS",
                },

                "after": {
                    "selected_value":
                        "28",

                    "selected_label":
                        "MADRID",
                },
            },
            {
                "kind":
                    "CATALOG_OPTIONS_CHANGED",

                "source":
                    "main::#province",

                "target":
                    "main::#municipality",

                "before_options_count":
                    2,

                "after_options_count":
                    3,

                "before_options_signature":
                    catalog_option_identity_signature(
                        _options(
                            "33001",
                            "33002",
                        )
                    ),

                "after_options_signature":
                    catalog_option_identity_signature(
                        _options(
                            "28001",
                            "28002",
                            "28003",
                        )
                    ),

                "before_selected_value":
                    "33001",

                "after_selected_value":
                    "28001",
            },

            # Another affected target must not contaminate
            # the municipality comparison.
            {
                "kind":
                    "CATALOG_OPTIONS_CHANGED",

                "source":
                    "main::#province",

                "target":
                    "main::#locality",

                "before_options_count":
                    10,

                "after_options_count":
                    20,
            },
        ),

        "evidence_count":
            3,

        "causal_relations": (
            {
                "relation":
                    "INFLUENCES",

                "source":
                    "main::#province",

                "target":
                    "main::#municipality",
            },
        ),

        "causal_relation_count":
            4,

        "restoration_exact":
            True,

        "compared_catalogs":
            3,
    }


def _real():
    return (
        behavior_trace_from_real_catalog_harvest(
            _real_artifact(),
            twin_key="mercurio",
            candidate_id="candidate-1",
            before_source_value="33",
            after_source_value="28",
        )
    )


def _twin():
    return (
        behavior_trace_from_twin_catalog_analysis(
            _twin_analysis(),
            twin_key="mercurio",
            candidate_id="candidate-1",
            target_selector="#municipality",
        )
    )


def test_real_adapter_uses_controlled_harvest_provenance():
    trace = _real()

    assert (
        trace[
            "source"
        ]
        == AUTO_TWIN_BEHAVIOR_SOURCE_REAL_CONTROLLED_HARVEST
    )

    assert (
        trace[
            "behavior_kind"
        ]
        == AUTO_TWIN_BEHAVIOR_KIND_CATALOG_MUTATION
    )


def test_twin_adapter_uses_twin_controlled_provenance():
    trace = _twin()

    assert (
        trace[
            "source"
        ]
        == AUTO_TWIN_BEHAVIOR_SOURCE_TWIN_CONTROLLED
    )

    assert (
        trace[
            "behavior_kind"
        ]
        == AUTO_TWIN_BEHAVIOR_KIND_CATALOG_MUTATION
    )


def test_real_pair_derives_source_and_target_effects():
    trace = _real()

    kinds = {
        effect[
            "kind"
        ]
        for effect
        in trace[
            "effects"
        ]
    }

    assert kinds == {
        "SOURCE_SELECTION_CHANGED",
        "CATALOG_OPTIONS_CHANGED",
    }


def test_real_pair_derives_canonical_causal_relations():
    trace = _real()

    signatures = {
        (
            relation[
                "relation"
            ],
            relation[
                "source"
            ],
            relation[
                "target"
            ],
        )
        for relation
        in trace[
            "causal_relations"
        ]
    }

    assert signatures == {
        (
            "INFLUENCES",
            "main::#province",
            "main::#municipality",
        ),
        (
            "DEPENDS_ON",
            "main::#municipality",
            "main::#province",
        ),
    }


def test_real_and_twin_catalog_pair_are_functionally_equivalent():
    real = _real()
    twin = _twin()

    assert (
        real[
            "functional_signature"
        ]
        == twin[
            "functional_signature"
        ]
    )

    result = compare_auto_twin_behavior(
        real_trace=real,
        twin_trace=twin,
    )

    assert (
        result[
            "behavior_fidelity_pass"
        ]
        is True
    )


def test_real_and_twin_policy_difference_is_irrelevant():
    real = _real()
    twin = _twin()

    assert (
        real[
            "policy"
        ]
        == "REAL_GOVERNED_HARVEST"
    )

    assert (
        twin[
            "policy"
        ]
        == "TWIN_ONLY"
    )

    assert (
        real[
            "functional_signature"
        ]
        == twin[
            "functional_signature"
        ]
    )


def test_twin_unrelated_target_evidence_is_filtered():
    trace = _twin()

    serialized = repr(
        trace[
            "effects"
        ]
        + trace[
            "causal_relations"
        ]
    )

    assert (
        "main::#locality"
        not in serialized
    )


def test_twin_selected_target_value_is_not_common_functional_identity():
    first = _twin()

    analysis = (
        _twin_analysis()
    )

    analysis[
        "evidence"
    ][1][
        "before_selected_value"
    ] = "OTHER"

    analysis[
        "evidence"
    ][1][
        "after_selected_value"
    ] = "OTHER2"

    second = (
        behavior_trace_from_twin_catalog_analysis(
            analysis,
            twin_key="mercurio",
            candidate_id="candidate-1",
            target_selector="#municipality",
        )
    )

    assert (
        first[
            "functional_signature"
        ]
        == second[
            "functional_signature"
        ]
    )


def test_real_requires_complete_harvest():
    artifact = _real_artifact()

    artifact[
        "completion"
    ][
        "complete"
    ] = False

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_REAL_CATALOG_HARVEST_INCOMPLETE"
        ),
    ):
        behavior_trace_from_real_catalog_harvest(
            artifact,
            twin_key="mercurio",
            candidate_id="candidate-1",
            before_source_value="33",
            after_source_value="28",
        )


def test_real_requires_exact_restoration():
    artifact = _real_artifact()

    artifact[
        "restoration"
    ][
        "exact"
    ] = False

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_REAL_CATALOG_RESTORATION_REQUIRED"
        ),
    ):
        behavior_trace_from_real_catalog_harvest(
            artifact,
            twin_key="mercurio",
            candidate_id="candidate-1",
            before_source_value="33",
            after_source_value="28",
        )


def test_real_multi_observation_requires_restore_attempt():
    artifact = _real_artifact()

    artifact[
        "restoration"
    ][
        "attempted"
    ] = False

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_REAL_CATALOG_RESTORATION_ATTEMPT_REQUIRED"
        ),
    ):
        behavior_trace_from_real_catalog_harvest(
            artifact,
            twin_key="mercurio",
            candidate_id="candidate-1",
            before_source_value="33",
            after_source_value="28",
        )


def test_real_requires_full_source_value_coverage():
    artifact = _real_artifact()

    artifact[
        "observations"
    ][1][
        "source_value"
    ] = "99"

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_REAL_CATALOG_COVERAGE_MISMATCH"
        ),
    ):
        behavior_trace_from_real_catalog_harvest(
            artifact,
            twin_key="mercurio",
            candidate_id="candidate-1",
            before_source_value="33",
            after_source_value="28",
        )


def test_real_pair_must_exist_in_harvest():
    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_REAL_CATALOG_PAIR_NOT_OBSERVED"
        ),
    ):
        behavior_trace_from_real_catalog_harvest(
            _real_artifact(),
            twin_key="mercurio",
            candidate_id="candidate-1",
            before_source_value="33",
            after_source_value="99",
        )


def test_twin_requires_exact_restoration():
    analysis = _twin_analysis()

    analysis[
        "restoration_exact"
    ] = False

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_TWIN_CATALOG_RESTORATION_REQUIRED"
        ),
    ):
        behavior_trace_from_twin_catalog_analysis(
            analysis,
            twin_key="mercurio",
            candidate_id="candidate-1",
            target_selector="#municipality",
        )


def test_twin_requires_canonical_source_change():
    analysis = _twin_analysis()

    analysis[
        "evidence"
    ] = tuple(
        evidence
        for evidence
        in analysis[
            "evidence"
        ]
        if (
            evidence[
                "kind"
            ]
            != "SOURCE_SELECTION_CHANGED"
        )
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_TWIN_CATALOG_SOURCE_CHANGE_REQUIRED"
        ),
    ):
        behavior_trace_from_twin_catalog_analysis(
            analysis,
            twin_key="mercurio",
            candidate_id="candidate-1",
            target_selector="#municipality",
        )


def test_target_option_order_is_functional_evidence():
    artifact = _real_artifact()

    artifact[
        "observations"
    ][1][
        "target_options"
    ] = list(
        reversed(
            artifact[
                "observations"
            ][1][
                "target_options"
            ]
        )
    )

    trace = (
        behavior_trace_from_real_catalog_harvest(
            artifact,
            twin_key="mercurio",
            candidate_id="candidate-1",
            before_source_value="33",
            after_source_value="28",
        )
    )

    assert any(
        effect[
            "kind"
        ]
        == "CATALOG_OPTIONS_CHANGED"
        for effect
        in trace[
            "effects"
        ]
    )


def test_trace_does_not_embed_raw_catalog_options():
    trace = _real()

    serialized = repr(
        trace
    )

    assert (
        "target_options"
        not in serialized
    )

    assert (
        "source_label"
        not in serialized
    )


def test_catalog_behavior_does_not_claim_navigation_transition():
    for trace in (
        _real(),
        _twin(),
    ):
        assert trace[
            "transition"
        ] == {
            "before_state":
                None,

            "after_state":
                None,

            "changed":
                False,
        }


def _catalog_mutation_effect(
    trace,
):
    return next(
        effect
        for effect
        in trace[
            "effects"
        ]
        if (
            effect[
                "kind"
            ]
            == "CATALOG_OPTIONS_CHANGED"
        )
    )


def test_option_signature_is_order_sensitive_and_lightweight():
    original = (
        catalog_option_identity_signature(
            _options(
                "A",
                "B",
                "C",
            )
        )
    )

    reordered = (
        catalog_option_identity_signature(
            _options(
                "A",
                "C",
                "B",
            )
        )
    )

    assert original != reordered

    assert len(original) == 64
    assert len(reordered) == 64


def test_same_counts_different_option_composition_fails_fidelity():
    artifact = _real_artifact()

    artifact[
        "observations"
    ][1][
        "target_options"
    ] = _options(
        "28001",
        "28002",
        "28999",
    )

    real = (
        behavior_trace_from_real_catalog_harvest(
            artifact,
            twin_key="mercurio",
            candidate_id="candidate-1",
            before_source_value="33",
            after_source_value="28",
        )
    )

    twin = _twin()

    real_effect = (
        _catalog_mutation_effect(
            real
        )
    )

    twin_effect = (
        _catalog_mutation_effect(
            twin
        )
    )

    assert (
        real_effect[
            "before_options_count"
        ]
        == twin_effect[
            "before_options_count"
        ]
        == 2
    )

    assert (
        real_effect[
            "after_options_count"
        ]
        == twin_effect[
            "after_options_count"
        ]
        == 3
    )

    assert (
        real_effect[
            "after_options_signature"
        ]
        != twin_effect[
            "after_options_signature"
        ]
    )

    result = compare_auto_twin_behavior(
        real_trace=real,
        twin_trace=twin,
    )

    assert (
        result[
            "behavior_fidelity_pass"
        ]
        is False
    )

    assert (
        result[
            "checks"
        ][
            "BEHAVIOR"
        ][
            "status"
        ]
        == "FAIL"
    )


def test_same_counts_different_option_order_fails_fidelity():
    artifact = _real_artifact()

    artifact[
        "observations"
    ][1][
        "target_options"
    ] = list(
        reversed(
            artifact[
                "observations"
            ][1][
                "target_options"
            ]
        )
    )

    real = (
        behavior_trace_from_real_catalog_harvest(
            artifact,
            twin_key="mercurio",
            candidate_id="candidate-1",
            before_source_value="33",
            after_source_value="28",
        )
    )

    twin = _twin()

    real_effect = (
        _catalog_mutation_effect(
            real
        )
    )

    twin_effect = (
        _catalog_mutation_effect(
            twin
        )
    )

    assert (
        real_effect[
            "after_options_count"
        ]
        == twin_effect[
            "after_options_count"
        ]
        == 3
    )

    assert (
        real_effect[
            "after_options_signature"
        ]
        != twin_effect[
            "after_options_signature"
        ]
    )

    result = compare_auto_twin_behavior(
        real_trace=real,
        twin_trace=twin,
    )

    assert (
        result[
            "checks"
        ][
            "BEHAVIOR"
        ][
            "status"
        ]
        == "FAIL"
    )


def test_missing_option_identity_is_inconclusive_not_false_pass():
    analysis = _twin_analysis()

    for evidence in analysis[
        "evidence"
    ]:
        if (
            evidence.get(
                "kind"
            )
            == "CATALOG_OPTIONS_CHANGED"
            and evidence.get(
                "target"
            )
            == "main::#municipality"
        ):
            evidence.pop(
                "before_options_signature",
                None,
            )

            evidence.pop(
                "after_options_signature",
                None,
            )

    legacy_twin = (
        behavior_trace_from_twin_catalog_analysis(
            analysis,
            twin_key="mercurio",
            candidate_id="candidate-1",
            target_selector="#municipality",
        )
    )

    result = compare_auto_twin_behavior(
        real_trace=_real(),
        twin_trace=legacy_twin,
    )

    assert (
        result[
            "behavior_fidelity_pass"
        ]
        is False
    )

    assert (
        result[
            "checks"
        ][
            "BEHAVIOR"
        ][
            "status"
        ]
        == "INCONCLUSIVE"
    )

    metrics = (
        result[
            "checks"
        ][
            "BEHAVIOR"
        ][
            "metrics"
        ]
    )

    assert (
        metrics[
            "real_catalog_option_identity_complete"
        ]
        is True
    )

    assert (
        metrics[
            "twin_catalog_option_identity_complete"
        ]
        is False
    )


def test_behavior_trace_contains_hashes_not_raw_option_payload():
    trace = _real()

    effect = (
        _catalog_mutation_effect(
            trace
        )
    )

    assert len(
        effect[
            "before_options_signature"
        ]
    ) == 64

    assert len(
        effect[
            "after_options_signature"
        ]
    ) == 64

    serialized = repr(
        trace
    )

    assert "target_options" not in serialized

    assert "33001" not in serialized
    assert "33002" not in serialized
    assert "28001" not in serialized
    assert "28002" not in serialized
    assert "28003" not in serialized
