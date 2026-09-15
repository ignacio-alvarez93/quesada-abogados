import json

import pytest

from backend.qcc.navigation_knowledge.store import (
    NavigationKnowledgeStore,
)

from backend.qcc.navigation_learning import (
    HumanNavigationCandidateStore,
    build_human_candidate_state_transition,
    promote_confirmed_human_candidate,
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

        "session_id":
            "runtime-session",

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


def _confirmed(
    candidate_store,
    *,
    environment="LAB",
):
    result = None

    for index in range(
        1,
        4,
    ):
        result = (
            candidate_store
            .record_observed_transition(
                _transition(
                    f"{environment.lower()}-event-{index}",
                    environment=environment,
                )
            )
        )

    return result[
        "candidate"
    ]


def test_unconfirmed_candidate_cannot_reach_knowledge(
    tmp_path,
):
    candidates, knowledge = (
        _stores(
            tmp_path
        )
    )

    result = (
        candidates
        .record_observed_transition(
            _transition(
                "event-1"
            )
        )
    )

    candidate = result[
        "candidate"
    ]

    with pytest.raises(
        ValueError,
        match=(
            "QCC_HUMAN_NAVIGATION_PROMOTION_REQUIRES_CONFIRMED"
        ),
    ):
        promote_confirmed_human_candidate(
            candidates,
            knowledge,
            site_code="MERCURIO",
            environment="LAB",
            candidate_id=(
                candidate[
                    "candidate_id"
                ]
            ),
        )

    snapshot = knowledge.snapshot(
        "MERCURIO",
        environment="LAB",
    )

    assert (
        snapshot[
            "transition_observation_count"
        ]
        == 0
    )


def test_confirmed_candidate_preserves_three_observations(
    tmp_path,
):
    candidates, knowledge = (
        _stores(
            tmp_path
        )
    )

    candidate = _confirmed(
        candidates
    )

    result = (
        promote_confirmed_human_candidate(
            candidates,
            knowledge,
            site_code="MERCURIO",
            environment="LAB",
            candidate_id=(
                candidate[
                    "candidate_id"
                ]
            ),
        )
    )

    assert (
        result[
            "recorded_count"
        ]
        == 3
    )

    assert (
        result[
            "already_recorded_count"
        ]
        == 0
    )

    snapshot = knowledge.snapshot(
        "MERCURIO",
        environment="LAB",
    )

    assert (
        snapshot[
            "transition_observation_count"
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

    edge = graph[
        "edges"
    ][0]

    assert (
        edge[
            "observation_count"
        ]
        == 3
    )

    assert (
        edge[
            "action"
        ][
            "selector"
        ]
        == "#btncont"
    )

    assert (
        edge[
            "action"
        ][
            "policy"
        ]
        == "NAVIGATION_CANDIDATE"
    )


def test_repeating_promotion_never_duplicates_evidence(
    tmp_path,
):
    candidates, knowledge = (
        _stores(
            tmp_path
        )
    )

    candidate = _confirmed(
        candidates
    )

    kwargs = {
        "site_code":
            "MERCURIO",

        "environment":
            "LAB",

        "candidate_id":
            candidate[
                "candidate_id"
            ],
    }

    first = (
        promote_confirmed_human_candidate(
            candidates,
            knowledge,
            **kwargs,
        )
    )

    second = (
        promote_confirmed_human_candidate(
            candidates,
            knowledge,
            **kwargs,
        )
    )

    assert (
        first[
            "recorded_count"
        ]
        == 3
    )

    assert (
        second[
            "recorded_count"
        ]
        == 0
    )

    assert (
        second[
            "already_recorded_count"
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

    assert (
        graph[
            "edges"
        ][0][
            "observation_count"
        ]
        == 3
    )


def test_partial_promotion_can_resume_without_inflation(
    tmp_path,
):
    candidates, knowledge = (
        _stores(
            tmp_path
        )
    )

    candidate = _confirmed(
        candidates
    )

    transition = (
        build_human_candidate_state_transition(
            candidate
        )
    )

    first_event = candidate[
        "event_ids"
    ][0]

    observation_id = (
        "QCC_HUMAN_CAUSAL:"
        + candidate[
            "candidate_id"
        ]
        + ":"
        + first_event
    )

    first = (
        knowledge
        .record_transition_once(
            "MERCURIO",
            transition,
            observation_id=(
                observation_id
            ),
            environment="LAB",
            before_state=(
                candidate[
                    "before_state"
                ]
            ),
            after_state=(
                candidate[
                    "after_state"
                ]
            ),
        )
    )

    assert (
        first[
            "recorded"
        ]
        is True
    )

    result = (
        promote_confirmed_human_candidate(
            candidates,
            knowledge,
            site_code="MERCURIO",
            environment="LAB",
            candidate_id=(
                candidate[
                    "candidate_id"
                ]
            ),
        )
    )

    assert (
        result[
            "recorded_count"
        ]
        == 2
    )

    assert (
        result[
            "already_recorded_count"
        ]
        == 1
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

    assert (
        graph[
            "edges"
        ][0][
            "observation_count"
        ]
        == 3
    )


def test_lab_and_real_knowledge_are_not_cross_promoted(
    tmp_path,
):
    candidates, knowledge = (
        _stores(
            tmp_path
        )
    )

    lab_candidate = _confirmed(
        candidates,
        environment="LAB",
    )

    _confirmed(
        candidates,
        environment="REAL",
    )

    promote_confirmed_human_candidate(
        candidates,
        knowledge,
        site_code="MERCURIO",
        environment="LAB",
        candidate_id=(
            lab_candidate[
                "candidate_id"
            ]
        ),
    )

    lab = knowledge.snapshot(
        "MERCURIO",
        environment="LAB",
    )

    real = knowledge.snapshot(
        "MERCURIO",
        environment="REAL",
    )

    assert (
        lab[
            "transition_observation_count"
        ]
        == 3
    )

    assert (
        real[
            "transition_observation_count"
        ]
        == 0
    )


def test_knowledge_store_loads_legacy_payload_without_ids(
    tmp_path,
):
    _, knowledge = _stores(
        tmp_path
    )

    legacy_transition = {
        "schema_version":
            1,

        "transition_type":
            "QCC_STATE_TRANSITION",

        "changed":
            True,

        "status":
            "FUNCTIONAL_STATE_CHANGED",

        "before_fingerprint":
            FP_A,

        "after_fingerprint":
            FP_B,

        "action": {
            "kind":
                "LINK",

            "policy":
                "NAVIGATION_CANDIDATE",

            "selector":
                "#btncont",

            "frame_path":
                "main",
        },

        "confidence":
            "HIGH",

        "contract_changed":
            False,

        "inconclusive":
            False,
    }

    knowledge.record_transition(
        "MERCURIO",
        legacy_transition,
        environment="LAB",
        before_state="STATE_A",
        after_state="STATE_B",
    )

    path = (
        tmp_path
        / "knowledge"
        / "MERCURIO"
        / "LAB"
        / "navigation_knowledge.json"
    )

    payload = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    payload.pop(
        "transition_observation_ids",
        None,
    )

    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    loaded = knowledge.snapshot(
        "MERCURIO",
        environment="LAB",
    )

    assert (
        "transition_observation_ids"
        not in loaded
    )

    assert (
        loaded[
            "transition_observation_count"
        ]
        == 1
    )


def test_promotion_does_not_upgrade_execution_policy(
    tmp_path,
):
    candidates, _ = _stores(
        tmp_path
    )

    candidate = _confirmed(
        candidates
    )

    transition = (
        build_human_candidate_state_transition(
            candidate
        )
    )

    assert (
        transition[
            "action"
        ][
            "policy"
        ]
        == "NAVIGATION_CANDIDATE"
    )

    serialized = str(
        transition
    )

    assert (
        "AUTOMATION_ALLOWED"
        not in serialized
    )



def test_observation_ids_are_private_knowledge_metadata(
    tmp_path,
):
    candidates, knowledge = (
        _stores(
            tmp_path
        )
    )

    candidate = _confirmed(
        candidates
    )

    promote_confirmed_human_candidate(
        candidates,
        knowledge,
        site_code="MERCURIO",
        environment="LAB",
        candidate_id=(
            candidate[
                "candidate_id"
            ]
        ),
    )

    public = knowledge.snapshot(
        "MERCURIO",
        environment="LAB",
    )

    assert (
        "transition_observation_ids"
        not in public
    )

    path = (
        tmp_path
        / "knowledge"
        / "MERCURIO"
        / "LAB"
        / "navigation_knowledge.json"
    )

    persisted = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    assert (
        len(
            persisted[
                "transition_observation_ids"
            ]
        )
        == 3
    )


def test_promoted_candidate_is_frozen(
    tmp_path,
):
    candidates, knowledge = (
        _stores(
            tmp_path
        )
    )

    candidate = _confirmed(
        candidates
    )

    promote_confirmed_human_candidate(
        candidates,
        knowledge,
        site_code="MERCURIO",
        environment="LAB",
        candidate_id=(
            candidate[
                "candidate_id"
            ]
        ),
    )

    fourth = (
        candidates
        .record_observed_transition(
            _transition(
                "lab-event-4"
            )
        )
    )

    assert (
        fourth[
            "recorded"
        ]
        is False
    )

    assert (
        fourth[
            "promoted_candidate"
        ]
        is True
    )

    assert (
        fourth[
            "candidate"
        ][
            "observation_count"
        ]
        == 3
    )

    again = (
        promote_confirmed_human_candidate(
            candidates,
            knowledge,
            site_code="MERCURIO",
            environment="LAB",
            candidate_id=(
                candidate[
                    "candidate_id"
                ]
            ),
        )
    )

    assert (
        again[
            "recorded_count"
        ]
        == 0
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

    assert (
        graph[
            "edges"
        ][0][
            "observation_count"
        ]
        == 3
    )
