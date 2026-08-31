import pytest

from backend.qcc.navigation_knowledge.store import (
    NavigationKnowledgeStore,
)

from backend.qcc.navigation_learning import (
    HumanNavigationCandidateStore,
    process_observed_human_navigation_learning,
)


FP_A = "a" * 64
FP_B = "b" * 64


def _transition(
    event_id,
    *,
    environment="LAB",
):
    return {
        "event_id":
            event_id,

        "site_code":
            "MERCURIO",

        "environment":
            environment,

        "before_state":
            "MERCURIO_MODEL_SELECTION",

        "before_fingerprint":
            FP_A,

        "kind":
            "LINK",

        "policy":
            "NAVIGATION_CANDIDATE",

        "selector":
            "#btncont",

        "frame_path":
            "main",

        "after_state":
            "EX01_AUTHORIZATION",

        "after_fingerprint":
            FP_B,

        "action_observed_at":
            "2026-08-31T09:00:00+00:00",

        "after_observed_at":
            "2026-08-31T09:00:01+00:00",

        "changed":
            True,
    }


def _stores(
    tmp_path,
):
    candidates = (
        HumanNavigationCandidateStore(
            root=(
                tmp_path
                / "candidates"
            )
        )
    )

    knowledge = (
        NavigationKnowledgeStore(
            root=(
                tmp_path
                / "knowledge"
            )
        )
    )

    return (
        candidates,
        knowledge,
    )


def test_runtime_learns_only_after_third_distinct_event(
    tmp_path,
):
    candidates, knowledge = (
        _stores(
            tmp_path
        )
    )

    first = (
        process_observed_human_navigation_learning(
            candidates,
            knowledge,
            transition=_transition(
                "event-1"
            ),
            site_code="MERCURIO",
            environment="LAB",
        )
    )

    assert (
        first[
            "candidate_status"
        ]
        == "CANDIDATE"
    )

    assert (
        knowledge.snapshot(
            "MERCURIO",
            environment="LAB",
        )[
            "transition_observation_count"
        ]
        == 0
    )

    second = (
        process_observed_human_navigation_learning(
            candidates,
            knowledge,
            transition=_transition(
                "event-2"
            ),
            site_code="MERCURIO",
            environment="LAB",
        )
    )

    assert (
        second[
            "candidate_status"
        ]
        == "CORROBORATED"
    )

    assert (
        knowledge.snapshot(
            "MERCURIO",
            environment="LAB",
        )[
            "transition_observation_count"
        ]
        == 0
    )

    third = (
        process_observed_human_navigation_learning(
            candidates,
            knowledge,
            transition=_transition(
                "event-3"
            ),
            site_code="MERCURIO",
            environment="LAB",
        )
    )

    assert (
        third[
            "candidate_status"
        ]
        == "CONFIRMED"
    )

    assert (
        third[
            "promotion_count"
        ]
        == 1
    )

    assert (
        third[
            "knowledge_recorded_count"
        ]
        == 3
    )

    graph = knowledge.build_graph(
        "MERCURIO",
        environment="LAB",
    )

    assert (
        graph[
            "edge_count"
        ]
        == 1
    )

    assert (
        graph[
            "edges"
        ][0][
            "observation_count"
        ]
        == 3
    )

    assert (
        graph[
            "edges"
        ][0][
            "action"
        ][
            "policy"
        ]
        == "NAVIGATION_CANDIDATE"
    )


def test_confirmed_batch_is_sealed_at_three(
    tmp_path,
):
    candidates, knowledge = (
        _stores(
            tmp_path
        )
    )

    for index in range(
        1,
        4,
    ):
        process_observed_human_navigation_learning(
            candidates,
            knowledge,
            transition=_transition(
                f"event-{index}"
            ),
            site_code="MERCURIO",
            environment="LAB",
        )

    fourth = (
        process_observed_human_navigation_learning(
            candidates,
            knowledge,
            transition=_transition(
                "event-4"
            ),
            site_code="MERCURIO",
            environment="LAB",
        )
    )

    assert (
        fourth[
            "candidate_recorded"
        ]
        is False
    )

    snapshot = candidates.snapshot(
        "MERCURIO",
        environment="LAB",
    )

    assert (
        snapshot[
            "candidates"
        ][0][
            "observation_count"
        ]
        == 3
    )

    graph = knowledge.build_graph(
        "MERCURIO",
        environment="LAB",
    )

    assert (
        graph[
            "observation_count"
        ]
        == 3
    )


class _FailOnceKnowledgeStore(
    NavigationKnowledgeStore
):
    def __init__(
        self,
        *,
        root,
    ):
        super().__init__(
            root=root
        )

        self.fail_once = True

    def record_transition_once(
        self,
        *args,
        **kwargs,
    ):
        if self.fail_once:
            self.fail_once = False
            raise OSError(
                "SIMULATED_TRANSIENT_WRITE_FAILURE"
            )

        return super().record_transition_once(
            *args,
            **kwargs,
        )


def test_confirmed_unpromoted_candidate_is_retryable(
    tmp_path,
):
    candidates = (
        HumanNavigationCandidateStore(
            root=(
                tmp_path
                / "candidates"
            )
        )
    )

    knowledge = (
        _FailOnceKnowledgeStore(
            root=(
                tmp_path
                / "knowledge"
            )
        )
    )

    for index in (
        1,
        2,
    ):
        process_observed_human_navigation_learning(
            candidates,
            knowledge,
            transition=_transition(
                f"event-{index}"
            ),
            site_code="MERCURIO",
            environment="LAB",
        )

    with pytest.raises(
        OSError,
        match=(
            "SIMULATED_TRANSIENT_WRITE_FAILURE"
        ),
    ):
        process_observed_human_navigation_learning(
            candidates,
            knowledge,
            transition=_transition(
                "event-3"
            ),
            site_code="MERCURIO",
            environment="LAB",
        )

    pending = (
        candidates.confirmed_unpromoted(
            "MERCURIO",
            environment="LAB",
        )
    )

    assert len(
        pending
    ) == 1

    retry = (
        process_observed_human_navigation_learning(
            candidates,
            knowledge,
            transition=None,
            site_code="MERCURIO",
            environment="LAB",
        )
    )

    assert (
        retry[
            "promotion_count"
        ]
        == 1
    )

    assert (
        retry[
            "knowledge_recorded_count"
        ]
        == 3
    )

    assert (
        candidates.confirmed_unpromoted(
            "MERCURIO",
            environment="LAB",
        )
        == ()
    )

    graph = knowledge.build_graph(
        "MERCURIO",
        environment="LAB",
    )

    assert (
        graph[
            "observation_count"
        ]
        == 3
    )


def test_runtime_learning_keeps_lab_and_real_separate(
    tmp_path,
):
    candidates, knowledge = (
        _stores(
            tmp_path
        )
    )

    for environment in (
        "LAB",
        "REAL",
    ):
        for index in range(
            1,
            4,
        ):
            process_observed_human_navigation_learning(
                candidates,
                knowledge,
                transition=_transition(
                    f"{environment}-{index}",
                    environment=environment,
                ),
                site_code="MERCURIO",
                environment=environment,
            )

    lab = knowledge.build_graph(
        "MERCURIO",
        environment="LAB",
    )

    real = knowledge.build_graph(
        "MERCURIO",
        environment="REAL",
    )

    assert (
        lab[
            "observation_count"
        ]
        == 3
    )

    assert (
        real[
            "observation_count"
        ]
        == 3
    )
