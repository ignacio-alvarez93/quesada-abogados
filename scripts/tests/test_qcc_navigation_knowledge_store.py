import json

import pytest

from backend.automation.site_architecture.state_transition import (
    STATE_TRANSITION_CHANGED,
    STATE_TRANSITION_CONFIDENCE_HIGH,
    STATE_TRANSITION_SCHEMA_VERSION,
    STATE_TRANSITION_TYPE,
)
from backend.qcc.navigation_knowledge import (
    NavigationKnowledgeStore,
)


FP_A = "a" * 64
FP_B = "b" * 64
FP_C = "c" * 64


def _transition(
    before,
    after,
    *,
    selector="#continue",
    confidence=(
        STATE_TRANSITION_CONFIDENCE_HIGH
    ),
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
                "BUTTON",

            "policy":
                "REQUIRES_POLICY",

            "selector":
                selector,

            "frame_path":
                "main",

            # Deben ser descartados:
            "text":
                "PII TEXT",

            "value":
                "SECRET VALUE",

            "html":
                "<html>SECRET</html>",

            "payload": {
                "secret":
                    "SECRET"
            },
        },

        "confidence":
            confidence,

        "contract_changed":
            False,

        "inconclusive":
            False,

        # También debe descartarse.
        "raw_dom":
            "<body>SECRET</body>",
    }


def test_empty_site_has_empty_graph(
    tmp_path,
):
    store = NavigationKnowledgeStore(
        root=tmp_path
    )

    graph = store.build_graph(
        "TEST_SITE"
    )

    assert graph["node_count"] == 0
    assert graph["edge_count"] == 0


def test_transition_is_persisted_and_reloaded(
    tmp_path,
):
    store = NavigationKnowledgeStore(
        root=tmp_path
    )

    revision = store.record_transition(
        "TEST_SITE",
        _transition(
            FP_A,
            FP_B,
        ),
        before_state="STATE_A",
        after_state="STATE_B",
    )

    assert revision == 1

    reloaded = NavigationKnowledgeStore(
        root=tmp_path
    )

    snapshot = reloaded.snapshot(
        "TEST_SITE"
    )

    assert (
        snapshot[
            "transition_observation_count"
        ]
        == 1
    )

    assert (
        snapshot["revision"]
        == 1
    )


def test_repeated_observations_strengthen_same_edge(
    tmp_path,
):
    store = NavigationKnowledgeStore(
        root=tmp_path
    )

    for _ in range(3):
        store.record_transition(
            "TEST_SITE",
            _transition(
                FP_A,
                FP_B,
            ),
            before_state="STATE_A",
            after_state="STATE_B",
        )

    graph = store.build_graph(
        "TEST_SITE"
    )

    assert graph["node_count"] == 2
    assert graph["edge_count"] == 1

    edge = graph["edges"][0]

    assert (
        edge["observation_count"]
        == 3
    )


def test_multiple_presentations_expand_graph(
    tmp_path,
):
    store = NavigationKnowledgeStore(
        root=tmp_path
    )

    store.record_transition(
        "TEST_SITE",
        _transition(
            FP_A,
            FP_B,
            selector="#first",
        ),
        before_state="STATE_A",
        after_state="STATE_B",
    )

    store.record_transition(
        "TEST_SITE",
        _transition(
            FP_B,
            FP_C,
            selector="#second",
        ),
        before_state="STATE_B",
        after_state="STATE_C",
    )

    graph = store.build_graph(
        "TEST_SITE"
    )

    assert graph["node_count"] == 3
    assert graph["edge_count"] == 2


def test_semantic_state_aliases_are_accumulated(
    tmp_path,
):
    store = NavigationKnowledgeStore(
        root=tmp_path
    )

    for _ in range(4):
        store.record_transition(
            "TEST_SITE",
            _transition(
                FP_A,
                FP_B,
            ),
            before_state="STATE_A",
            after_state="STATE_B",
        )

    candidates = (
        store.resolve_state_fingerprints(
            "TEST_SITE",
            "STATE_B",
        )
    )

    assert candidates == (
        {
            "fingerprint":
                FP_B,
            "observation_count":
                4,
        },
    )


def test_same_semantic_state_can_have_multiple_fingerprints(
    tmp_path,
):
    store = NavigationKnowledgeStore(
        root=tmp_path
    )

    store.record_transition(
        "TEST_SITE",
        _transition(
            FP_A,
            FP_B,
        ),
        after_state="TARGET",
    )

    store.record_transition(
        "TEST_SITE",
        _transition(
            FP_A,
            FP_C,
        ),
        after_state="TARGET",
    )

    candidates = (
        store.resolve_state_fingerprints(
            "TEST_SITE",
            "TARGET",
        )
    )

    assert {
        item["fingerprint"]
        for item in candidates
    } == {
        FP_B,
        FP_C,
    }


def test_sites_are_strictly_isolated(
    tmp_path,
):
    store = NavigationKnowledgeStore(
        root=tmp_path
    )

    store.record_transition(
        "SITE_A",
        _transition(
            FP_A,
            FP_B,
        ),
    )

    store.record_transition(
        "SITE_B",
        _transition(
            FP_B,
            FP_C,
        ),
    )

    graph_a = store.build_graph(
        "SITE_A"
    )

    graph_b = store.build_graph(
        "SITE_B"
    )

    assert graph_a["edge_count"] == 1
    assert graph_b["edge_count"] == 1

    assert (
        graph_a["edges"][0][
            "source_fingerprint"
        ]
        == FP_A
    )

    assert (
        graph_b["edges"][0][
            "source_fingerprint"
        ]
        == FP_B
    )


def test_transition_persistence_is_pii_safe(
    tmp_path,
):
    store = NavigationKnowledgeStore(
        root=tmp_path
    )

    store.record_transition(
        "TEST_SITE",
        _transition(
            FP_A,
            FP_B,
        ),
    )

    path = (
        tmp_path
        / "TEST_SITE"
        / "navigation_knowledge.json"
    )

    payload = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    serialized = json.dumps(
        payload
    ).lower()

    forbidden = (
        "pii text",
        "secret value",
        "<html>",
        "<body>",
        '"raw_dom"',
        '"payload"',
    )

    for token in forbidden:
        assert token not in serialized

    action = (
        payload[
            "transitions"
        ][0][
            "action"
        ]
    )

    assert set(
        action
    ) == {
        "kind",
        "policy",
        "selector",
        "frame_path",
    }


@pytest.mark.parametrize(
    "site_code",
    (
        "../MERCURIO",
        "A/B",
        "A B",
        "",
    ),
)
def test_site_code_cannot_escape_storage_root(
    tmp_path,
    site_code,
):
    store = NavigationKnowledgeStore(
        root=tmp_path
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_NAVIGATION_KNOWLEDGE_SITE_CODE_INVALID"
        ),
    ):
        store.snapshot(
            site_code
        )


def test_store_is_provider_agnostic():
    from pathlib import Path

    source = Path(
        "backend/qcc/navigation_knowledge/"
        "store.py"
    ).read_text(
        encoding="utf-8"
    ).upper()

    forbidden = (
        "MERCURIO",
        "INSTAGRAM",
        "YOUTUBE",
        "DEHU",
        "ICP_PLUS",
    )

    for token in forbidden:
        assert token not in source
