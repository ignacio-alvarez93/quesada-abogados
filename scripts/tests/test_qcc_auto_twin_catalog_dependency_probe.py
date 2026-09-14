import copy

import pytest

from backend.qcc.auto_twin.catalog_dependency_probe import (
    AUTO_TWIN_CATALOG_DEPENDENCY_OPTION_IDENTITY_MODE,
    analyze_auto_twin_governed_catalog_probe,
)
from backend.qcc.auto_twin.catalog_probe_decision import (
    AUTO_TWIN_CATALOG_PROBE_DECISION_SCHEMA_VERSION,
    AUTO_TWIN_CATALOG_PROBE_DECISION_TYPE,
)


def _artifact():
    return {
        "schema_version": 1,
        "artifact_type":
            "QCC_GENERIC_CATALOG_CAUSAL_PROBE",
        "safety_mode":
            "GOVERNED_REAL_PROBE",
        "source_selector":
            "#interested\\.province",
        "target_selector":
            "#interested\\.city",
        "requested_value":
            "",
        "requested_label":
            "Almería",
        "authority": {
            # No es autoridad backend.
            # Debe considerarse únicamente declarativa.
            "browser_profile_key":
                "FORGED_PROFILE",
            "twin_key":
                "FORGED_TWIN",
        },
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
                "catalog_type":
                    "custom_select",
                "selected_value":
                    "04",
                "selected_label":
                    "Almería",
            },
            "target": {
                "selector":
                    "#interested\\.city",
                "catalog_type":
                    "custom_select",
                "options_count":
                    3,
                "options": [
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
                    {
                        "value": "",
                        "label": "Adra",
                        "disabled": False,
                    },
                ],
            },
            "stabilization": {
                "stable": True,
                "attempts": 2,
            },
        },
        "restoration": {
            "method":
                "ARIA_CLEAR_CLICK",
            "hard_document_restore": {
                "attempted": True,
                "completed": True,
                "method": "DOCUMENT_RELOAD",
            },
        },
        "restoration_verification": {
            "exact": True,
            "compared_catalogs": 9,
            "differences": [],
        },
    }


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
            (
                "https://reg.redsara.es/"
                "es/nuevo-registro"
            ),
        "twin_key":
            "red_sara",
        "site_code":
            "RED_SARA",
        "profile_policy": {
            "policy":
                "DISCOVERY",
            "active_discovery":
                True,
            "active_catalog_probe":
                True,
        },
    }


def _analyze(
    artifact=None,
    decision=None,
):
    return (
        analyze_auto_twin_governed_catalog_probe(
            artifact
            if artifact is not None
            else _artifact(),
            authoritative_decision=(
                decision
                if decision is not None
                else _decision()
            ),
        )
    )


def test_governed_probe_builds_canonical_dependency():
    result = _analyze()

    assert (
        result["twin_key"]
        == "red_sara"
    )

    assert (
        result["pathname"]
        == "/es/nuevo-registro"
    )

    assert (
        result["source"]["catalog_key"]
        == "main::#interested\\.province"
    )

    assert (
        result["target"]["catalog_key"]
        == "main::#interested\\.city"
    )

    assert (
        result["trigger"]["before_value"]
        == ""
    )

    assert (
        result["trigger"]["value"]
        == "04"
    )

    assert (
        result["trigger"]["label"]
        == "Almería"
    )

    assert (
        result["target"]["before_options_count"]
        == 0
    )

    assert (
        result["target"]["options_count"]
        == 3
    )

    assert (
        result["causal_relation_count"]
        == 2
    )

    assert len(
        result["dependency_fingerprint"]
    ) == 64


def test_relations_are_canonical_influences_and_depends_on():
    result = _analyze()

    signatures = {
        (
            item["relation"],
            item["source"],
            item["target"],
        )
        for item
        in result["causal_relations"]
    }

    assert signatures == {
        (
            "INFLUENCES",
            "main::#interested\\.province",
            "main::#interested\\.city",
        ),
        (
            "DEPENDS_ON",
            "main::#interested\\.city",
            "main::#interested\\.province",
        ),
    }


def test_empty_raw_option_values_preserve_label_identity():
    result = _analyze()

    assert (
        result["option_identity_mode"]
        == AUTO_TWIN_CATALOG_DEPENDENCY_OPTION_IDENTITY_MODE
        == "VALUE_OR_LABEL"
    )

    assert [
        (
            option["value"],
            option["label"],
        )
        for option
        in result["target"]["options"]
    ] == [
        ("", "Abla"),
        ("", "Abrucena"),
        ("", "Adra"),
    ]


def test_worker_declared_authority_is_not_trusted():
    artifact = _artifact()

    artifact["authority"] = {
        "browser_profile_key":
            "attacker_profile",
        "twin_key":
            "attacker_twin",
        "site_code":
            "ATTACKER",
        "url":
            "https://attacker.invalid/",
    }

    result = _analyze(
        artifact=artifact,
    )

    assert (
        result["twin_key"]
        == "red_sara"
    )

    assert (
        result["site_code"]
        == "RED_SARA"
    )

    assert (
        result["provenance"][
            "browser_profile_key"
        ]
        == "twin_discovery"
    )


def test_denied_backend_authority_is_rejected():
    decision = _decision()
    decision["allowed"] = False

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_AUTHORITY_DENIED"
        ),
    ):
        _analyze(
            decision=decision,
        )


def test_backend_policy_requires_discovery_and_probe():
    decision = _decision()

    decision[
        "profile_policy"
    ][
        "active_discovery"
    ] = False

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_POLICY_DENIED"
        ),
    ):
        _analyze(
            decision=decision,
        )


def test_exact_restoration_is_required():
    artifact = _artifact()

    artifact[
        "restoration_verification"
    ][
        "exact"
    ] = False

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_RESTORATION_REQUIRED"
        ),
    ):
        _analyze(
            artifact=artifact,
        )


def test_stable_observation_is_required():
    artifact = _artifact()

    artifact[
        "observation"
    ][
        "stabilization"
    ][
        "stable"
    ] = False

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_NOT_STABLE"
        ),
    ):
        _analyze(
            artifact=artifact,
        )


def test_requested_identity_must_match_observed_identity():
    artifact = _artifact()

    artifact[
        "requested_label"
    ] = "Málaga"

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_REQUEST_LABEL_MISMATCH"
        ),
    ):
        _analyze(
            artifact=artifact,
        )


def test_target_must_actually_change():
    artifact = _artifact()

    artifact[
        "before"
    ][
        "target_options"
    ] = copy.deepcopy(
        artifact[
            "observation"
        ][
            "target"
        ][
            "options"
        ]
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_TARGET_UNCHANGED"
        ),
    ):
        _analyze(
            artifact=artifact,
        )


def test_dependency_fingerprint_is_deterministic():
    first = _analyze()

    artifact = copy.deepcopy(
        _artifact()
    )

    artifact[
        "restoration"
    ][
        "irrelevant_runtime_detail"
    ] = "ignored"

    second = _analyze(
        artifact=artifact,
    )

    assert (
        first[
            "dependency_fingerprint"
        ]
        == second[
            "dependency_fingerprint"
        ]
    )


def test_module_is_provider_neutral():
    from pathlib import Path

    source = Path(
        "backend/qcc/auto_twin/"
        "catalog_dependency_probe.py"
    ).read_text(
        encoding="utf-8"
    ).lower()

    assert "red_sara" not in source
    assert "mercurio" not in source
    assert "dnt-select" not in source
