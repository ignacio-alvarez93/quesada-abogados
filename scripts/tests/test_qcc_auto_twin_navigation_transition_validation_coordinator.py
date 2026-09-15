import json

from backend.qcc.auto_twin.navigation_transition_validation_store import (
    AutoTwinNavigationTransitionValidationStore,
)
from backend.qcc.auto_twin.navigation_transition_validation_coordinator import (
    AutoTwinNavigationTransitionValidationCoordinator,
)


def _runtime(
    root,
):
    runtime = (
        root
        / "mercurio"
        / "matrev-test"
        / "runtime"
    )

    runtime.mkdir(
        parents=True
    )

    (
        runtime
        / "navigation_transitions.json"
    ).write_text(
        json.dumps({
            "transitions": [
                {
                    "candidate_id":
                        "candidate-1",
                },
                {
                    "candidate_id":
                        "candidate-2",
                },
            ],
        }),
        encoding="utf-8",
    )


def _fake_validator(
    *,
    twin_key,
    revision_id,
    candidate_id,
    validation_store,
    materialized_root,
):
    validation = {
        "status":
            "TWIN_VALIDATED",

        "reason":
            "EXACT_LOCAL_TARGET_REACHED",

        "twin_key":
            twin_key,

        "revision_id":
            revision_id,

        "candidate_id":
            candidate_id,

        "before_state_id":
            "AUTO_A",

        "after_state_id":
            "AUTO_B",

        "selector":
            "#continue",

        "expected_runtime_entry":
            "states/AUTO_B/runtime/index.html",

        "location": {
            "href":
                (
                    "http://127.0.0.1:12345/"
                    "states/AUTO_B/runtime/index.html"
                ),

            "pathname":
                (
                    "/states/AUTO_B/runtime/index.html"
                ),
        },
    }

    persistence = (
        validation_store
        .record_twin_validated(
            validation
        )
    )

    return {
        "status":
            "TWIN_VALIDATED",

        "recorded":
            True,

        "validation":
            validation,

        "persistence":
            persistence,
    }


def test_navigation_validation_coordinator_processes_and_skips_exact_revision(
    tmp_path,
):
    _runtime(
        tmp_path
    )

    store = (
        AutoTwinNavigationTransitionValidationStore(
            path=(
                tmp_path
                / "validated.json"
            )
        )
    )

    coordinator = (
        AutoTwinNavigationTransitionValidationCoordinator(
            materialized_root=tmp_path,
            validation_store=store,
            validator=_fake_validator,
        )
    )

    first = coordinator.process_revision(
        twin_key="mercurio",
        revision_id="matrev-test",
    )

    assert first[
        "status"
    ] == "COMPLETE"

    assert first[
        "validated_count"
    ] == 2

    assert first[
        "skipped_count"
    ] == 0

    assert store.snapshot()[
        "record_count"
    ] == 2

    second = coordinator.process_revision(
        twin_key="mercurio",
        revision_id="matrev-test",
    )

    assert second[
        "validated_count"
    ] == 0

    assert second[
        "skipped_count"
    ] == 2

    assert store.snapshot()[
        "record_count"
    ] == 2


def test_navigation_validation_coordinator_background_queue_completes(
    tmp_path,
):
    _runtime(
        tmp_path
    )

    store = (
        AutoTwinNavigationTransitionValidationStore(
            path=(
                tmp_path
                / "validated.json"
            )
        )
    )

    coordinator = (
        AutoTwinNavigationTransitionValidationCoordinator(
            materialized_root=tmp_path,
            validation_store=store,
            validator=_fake_validator,
        )
    )

    queued = coordinator.enqueue(
        twin_key="mercurio",
        revision_id="matrev-test",
    )

    assert queued[
        "status"
    ] == "QUEUED"

    assert coordinator.wait_until_idle(
        timeout=2
    ) is True

    snapshot = coordinator.snapshot()

    assert snapshot[
        "pending_count"
    ] == 0

    assert snapshot[
        "last_result"
    ][
        "validated_count"
    ] == 2

    assert store.snapshot()[
        "record_count"
    ] == 2


def test_navigation_validation_coordinator_ignores_contextual_opaque_actions(
    tmp_path,
):
    runtime = (
        tmp_path
        / "mercurio"
        / "matrev-contextual"
        / "runtime"
    )

    runtime.mkdir(
        parents=True
    )

    (
        runtime
        / "navigation_transitions.json"
    ).write_text(
        json.dumps({
            "transitions": [],
            "contextual_action_count": 1,
            "contextual_actions": [
                {
                    "action_group_id":
                        "group-1",

                    "outcome_mode":
                        "CONTEXTUAL_OPAQUE",

                    "before_fingerprint":
                        "a" * 64,

                    "action": {
                        "kind":
                            "LINK",

                        "policy":
                            "NAVIGATION_CANDIDATE",

                        "selector":
                            'a[onclick="continuar(\'INI\');"]',

                        "frame_path":
                            "main",
                    },

                    "outcome_count":
                        2,

                    "outcomes": [
                        {
                            "after_fingerprint":
                                "b" * 64,

                            "candidate_ids":
                                ["candidate-b"],

                            "real_observation_count":
                                4,
                        },
                        {
                            "after_fingerprint":
                                "c" * 64,

                            "candidate_ids":
                                ["candidate-c"],

                            "real_observation_count":
                                1,
                        },
                    ],
                },
            ],
        }),
        encoding="utf-8",
    )

    store = (
        AutoTwinNavigationTransitionValidationStore(
            path=(
                tmp_path
                / "validated.json"
            )
        )
    )

    calls = []

    def validator_must_not_run(**kwargs):
        calls.append(
            kwargs
        )

        raise AssertionError(
            "CONTEXTUAL_OPAQUE_VALIDATOR_MUST_NOT_RUN"
        )

    coordinator = (
        AutoTwinNavigationTransitionValidationCoordinator(
            materialized_root=tmp_path,
            validation_store=store,
            validator=validator_must_not_run,
        )
    )

    result = coordinator.process_revision(
        twin_key="mercurio",
        revision_id="matrev-contextual",
    )

    assert result["status"] == "COMPLETE"
    assert result["transition_count"] == 0
    assert result["validated_count"] == 0
    assert result["skipped_count"] == 0
    assert result["failed_count"] == 0

    assert calls == []

    assert store.snapshot()[
        "record_count"
    ] == 0
