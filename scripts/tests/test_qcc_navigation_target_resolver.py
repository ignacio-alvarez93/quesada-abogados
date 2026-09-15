from datetime import (
    datetime,
    timezone,
)

from backend.automation.site_architecture.state_transition import (
    STATE_TRANSITION_CHANGED,
    STATE_TRANSITION_CONFIDENCE_HIGH,
    STATE_TRANSITION_SCHEMA_VERSION,
    STATE_TRANSITION_TYPE,
)
from backend.qcc.context.navigation_intent import (
    QccNavigationIntent,
)
from backend.qcc.context.navigation_target_resolver import (
    TARGET_RESOLUTION_EXPLICIT,
    TARGET_RESOLUTION_SEMANTIC,
    TARGET_RESOLUTION_UNRESOLVED,
    resolve_navigation_target,
)
from backend.qcc.navigation_knowledge import (
    NavigationKnowledgeStore,
)


FP_A = "a" * 64
FP_B = "b" * 64
FP_C = "c" * 64
FP_D = "d" * 64


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
                "BUTTON",

            "policy":
                "REQUIRES_POLICY",

            "selector":
                selector,

            "frame_path":
                "main",
        },

        "confidence":
            STATE_TRANSITION_CONFIDENCE_HIGH,

        "contract_changed":
            False,

        "inconclusive":
            False,
    }


def _intent(
    *,
    target_state=None,
    target_fingerprint=None,
):
    return QccNavigationIntent(
        session_id="session-1",
        site_code="TEST_SITE",
        target_state=target_state,
        target_fingerprint=(
            target_fingerprint
        ),
        requested_at=datetime.now(
            timezone.utc
        ),
    )


def test_explicit_fingerprint_has_priority(
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
            "#go",
        ),
        before_state="A",
        after_state="B",
    )

    result = resolve_navigation_target(
        store,
        _intent(
            target_state="B",
            target_fingerprint=FP_B,
        ),
        current_fingerprint=FP_A,
    )

    assert result["resolved"] is True

    assert (
        result["reason"]
        == TARGET_RESOLUTION_EXPLICIT
    )

    assert (
        result["target_fingerprint"]
        == FP_B
    )

    assert result["reachable"] is True
    assert result["remaining_steps"] == 1


def test_semantic_state_resolves_to_known_fingerprint(
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
            "#go",
        ),
        before_state="A",
        after_state="TARGET",
    )

    result = resolve_navigation_target(
        store,
        _intent(
            target_state="TARGET",
        ),
        current_fingerprint=FP_A,
    )

    assert result["resolved"] is True

    assert (
        result["reason"]
        == TARGET_RESOLUTION_SEMANTIC
    )

    assert (
        result["target_fingerprint"]
        == FP_B
    )


def test_reachable_candidate_beats_more_frequent_unreachable_candidate(
    tmp_path,
):
    store = NavigationKnowledgeStore(
        root=tmp_path
    )

    # FP_D recibe mucha evidencia como TARGET,
    # pero pertenece a otra región desconectada.
    for _ in range(5):
        store.record_transition(
            "TEST_SITE",
            _transition(
                FP_C,
                FP_D,
                "#isolated",
            ),
            before_state="OTHER",
            after_state="TARGET",
        )

    # FP_B tiene menos evidencia, pero es
    # alcanzable desde CURRENT=FP_A.
    store.record_transition(
        "TEST_SITE",
        _transition(
            FP_A,
            FP_B,
            "#reachable",
        ),
        before_state="CURRENT",
        after_state="TARGET",
    )

    result = resolve_navigation_target(
        store,
        _intent(
            target_state="TARGET",
        ),
        current_fingerprint=FP_A,
    )

    assert result["resolved"] is True

    assert (
        result["target_fingerprint"]
        == FP_B
    )

    assert result["candidate_count"] == 2


def test_shortest_reachable_variant_wins(
    tmp_path,
):
    store = NavigationKnowledgeStore(
        root=tmp_path
    )

    # Ruta corta A -> B
    store.record_transition(
        "TEST_SITE",
        _transition(
            FP_A,
            FP_B,
            "#short",
        ),
        after_state="TARGET",
    )

    # Ruta larga A -> C -> D
    store.record_transition(
        "TEST_SITE",
        _transition(
            FP_A,
            FP_C,
            "#long1",
        ),
    )

    store.record_transition(
        "TEST_SITE",
        _transition(
            FP_C,
            FP_D,
            "#long2",
        ),
        after_state="TARGET",
    )

    result = resolve_navigation_target(
        store,
        _intent(
            target_state="TARGET",
        ),
        current_fingerprint=FP_A,
    )

    assert (
        result["target_fingerprint"]
        == FP_B
    )

    assert (
        result["remaining_steps"]
        == 1
    )


def test_evidence_breaks_equal_length_tie(
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
            "#b",
        ),
        after_state="TARGET",
    )

    for _ in range(3):
        store.record_transition(
            "TEST_SITE",
            _transition(
                FP_A,
                FP_C,
                "#c",
            ),
            after_state="TARGET",
        )

    result = resolve_navigation_target(
        store,
        _intent(
            target_state="TARGET",
        ),
        current_fingerprint=FP_A,
    )

    assert (
        result["target_fingerprint"]
        == FP_C
    )


def test_current_variant_can_already_be_target(
    tmp_path,
):
    store = NavigationKnowledgeStore(
        root=tmp_path
    )

    # Registramos FP_A como alias TARGET.
    store.record_transition(
        "TEST_SITE",
        _transition(
            FP_A,
            FP_B,
            "#leave-target",
        ),
        before_state="TARGET",
        after_state="OTHER",
    )

    result = resolve_navigation_target(
        store,
        _intent(
            target_state="TARGET",
        ),
        current_fingerprint=FP_A,
    )

    assert result["resolved"] is True

    assert (
        result["target_fingerprint"]
        == FP_A
    )

    assert result["remaining_steps"] == 0


def test_unknown_semantic_target_is_unresolved(
    tmp_path,
):
    store = NavigationKnowledgeStore(
        root=tmp_path
    )

    result = resolve_navigation_target(
        store,
        _intent(
            target_state="UNKNOWN",
        ),
        current_fingerprint=FP_A,
    )

    assert result["resolved"] is False

    assert (
        result["reason"]
        == TARGET_RESOLUTION_UNRESOLVED
    )


def test_known_but_unreachable_state_fails_closed(
    tmp_path,
):
    store = NavigationKnowledgeStore(
        root=tmp_path
    )

    store.record_transition(
        "TEST_SITE",
        _transition(
            FP_C,
            FP_D,
            "#isolated",
        ),
        after_state="TARGET",
    )

    result = resolve_navigation_target(
        store,
        _intent(
            target_state="TARGET",
        ),
        current_fingerprint=FP_A,
    )

    assert result["resolved"] is False
    assert result["reachable"] is False


def test_resolver_is_provider_agnostic():
    from pathlib import Path

    source = Path(
        "backend/qcc/context/"
        "navigation_target_resolver.py"
    ).read_text(
        encoding="utf-8"
    ).upper()

    for token in (
        "MERCURIO",
        "INSTAGRAM",
        "YOUTUBE",
        "DEHU",
        "ICP_PLUS",
    ):
        assert token not in source
