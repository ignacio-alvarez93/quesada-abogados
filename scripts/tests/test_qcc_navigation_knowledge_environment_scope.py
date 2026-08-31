from __future__ import annotations

from backend.automation.site_architecture.state_transition import (
    STATE_TRANSITION_CHANGED,
    STATE_TRANSITION_CONFIDENCE_HIGH,
    STATE_TRANSITION_SCHEMA_VERSION,
    STATE_TRANSITION_TYPE,
)
from backend.qcc.navigation_knowledge import (
    NAVIGATION_KNOWLEDGE_SCHEMA_VERSION,
    NavigationKnowledgeStore,
)


FP_A = "a" * 64
FP_B = "b" * 64
FP_C = "c" * 64


def _transition(
    before,
    after,
    selector,
):
    return {
        "schema_version":
            STATE_TRANSITION_SCHEMA_VERSION,

        "transition_type":
            STATE_TRANSITION_TYPE,

        "changed":
            True,

        "status":
            STATE_TRANSITION_CHANGED,

        "before_fingerprint":
            before,

        "after_fingerprint":
            after,

        "action": {
            "kind":
                "LINK",

            "policy":
                "NAVIGATION_CANDIDATE",

            "selector":
                selector,

            "frame_path":
                "main",
        },

        "confidence":
            STATE_TRANSITION_CONFIDENCE_HIGH,

        "contract_changed":
            True,

        "inconclusive":
            False,
    }


def test_same_site_lab_and_real_are_strictly_isolated(
    tmp_path,
):
    store = NavigationKnowledgeStore(
        root=tmp_path
    )

    store.record_transition(
        "MERCURIO",
        _transition(
            FP_A,
            FP_B,
            "#lab",
        ),
        environment="LAB",
        before_state="STATE_A",
        after_state="STATE_B",
    )

    store.record_transition(
        "MERCURIO",
        _transition(
            FP_A,
            FP_C,
            "#real",
        ),
        environment="REAL",
        before_state="STATE_A",
        after_state="STATE_C",
    )

    lab = store.snapshot(
        "MERCURIO",
        environment="LAB",
    )

    real = store.snapshot(
        "MERCURIO",
        environment="REAL",
    )

    assert lab["environment"] == "LAB"
    assert real["environment"] == "REAL"

    assert (
        lab["transitions"][0]["action"]["selector"]
        == "#lab"
    )

    assert (
        real["transitions"][0]["action"]["selector"]
        == "#real"
    )

    assert (
        lab["transitions"][0]["after_fingerprint"]
        == FP_B
    )

    assert (
        real["transitions"][0]["after_fingerprint"]
        == FP_C
    )


def test_environment_is_part_of_physical_storage_key(
    tmp_path,
):
    store = NavigationKnowledgeStore(
        root=tmp_path
    )

    store.record_transition(
        "MERCURIO",
        _transition(
            FP_A,
            FP_B,
            "#lab",
        ),
        environment="LAB",
    )

    path = (
        tmp_path
        / "MERCURIO"
        / "LAB"
        / "navigation_knowledge.json"
    )

    assert path.exists()

    assert not (
        tmp_path
        / "MERCURIO"
        / "navigation_knowledge.json"
    ).exists()


def test_real_never_falls_back_to_generic_knowledge(
    tmp_path,
):
    store = NavigationKnowledgeStore(
        root=tmp_path
    )

    store.record_transition(
        "MERCURIO",
        _transition(
            FP_A,
            FP_B,
            "#generic",
        ),
    )

    generic = store.snapshot(
        "MERCURIO"
    )

    real = store.snapshot(
        "MERCURIO",
        environment="REAL",
    )

    assert (
        generic["transition_observation_count"]
        == 1
    )

    assert (
        real["transition_observation_count"]
        == 0
    )

    assert real["transitions"] == []
    assert real["state_aliases"] == {}


def test_graph_is_built_only_from_requested_environment(
    tmp_path,
):
    store = NavigationKnowledgeStore(
        root=tmp_path
    )

    store.record_transition(
        "MERCURIO",
        _transition(
            FP_A,
            FP_B,
            "#lab",
        ),
        environment="LAB",
    )

    lab_graph = store.build_graph(
        "MERCURIO",
        environment="LAB",
    )

    real_graph = store.build_graph(
        "MERCURIO",
        environment="REAL",
    )

    assert lab_graph["node_count"] == 2
    assert lab_graph["edge_count"] == 1

    assert real_graph["node_count"] == 0
    assert real_graph["edge_count"] == 0


def test_semantic_alias_resolution_is_environment_scoped(
    tmp_path,
):
    store = NavigationKnowledgeStore(
        root=tmp_path
    )

    store.record_transition(
        "MERCURIO",
        _transition(
            FP_A,
            FP_B,
            "#lab",
        ),
        environment="LAB",
        after_state="TARGET",
    )

    lab = store.resolve_state_fingerprints(
        "MERCURIO",
        "TARGET",
        environment="LAB",
    )

    real = store.resolve_state_fingerprints(
        "MERCURIO",
        "TARGET",
        environment="REAL",
    )

    assert len(lab) == 1
    assert lab[0]["fingerprint"] == FP_B
    assert real == ()


def test_payload_schema_carries_environment_identity(
    tmp_path,
):
    store = NavigationKnowledgeStore(
        root=tmp_path
    )

    store.record_transition(
        "MERCURIO",
        _transition(
            FP_A,
            FP_B,
            "#lab",
        ),
        environment="LAB",
    )

    payload = store.snapshot(
        "MERCURIO",
        environment="LAB",
    )

    assert (
        payload["schema_version"]
        == NAVIGATION_KNOWLEDGE_SCHEMA_VERSION
        == 2
    )

    assert payload["site_code"] == "MERCURIO"
    assert payload["environment"] == "LAB"
