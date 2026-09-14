from backend.qcc.auto_twin.navigation_transition_validation_store import (
    AutoTwinNavigationTransitionValidationStore,
)


def _validation():
    return {
        "status":
            "TWIN_VALIDATED",

        "reason":
            "EXACT_LOCAL_TARGET_REACHED",

        "twin_key":
            "mercurio",

        "revision_id":
            "matrev-test",

        "candidate_id":
            "candidate-1",

        "before_state_id":
            "AUTO_A",

        "after_state_id":
            "AUTO_B",

        "selector":
            'a[onclick="continuar()"]',

        "expected_runtime_entry":
            "states/01-AUTO_B/runtime/index.html",

        "location": {
            "href":
                (
                    "http://127.0.0.1:45678/"
                    "states/01-AUTO_B/runtime/index.html"
                ),

            "pathname":
                (
                    "/states/01-AUTO_B/"
                    "runtime/index.html"
                ),
        },
    }


def test_navigation_transition_validation_store_persists_twin_validated(
    tmp_path,
):
    path = (
        tmp_path
        / "validation.json"
    )

    store = (
        AutoTwinNavigationTransitionValidationStore(
            path=path
        )
    )

    result = store.record_twin_validated(
        _validation()
    )

    assert result[
        "created"
    ] is True

    assert result[
        "record"
    ][
        "status"
    ] == "TWIN_VALIDATED"

    assert path.is_file()

    reloaded = (
        AutoTwinNavigationTransitionValidationStore(
            path=path
        )
    )

    snapshot = reloaded.snapshot()

    assert snapshot[
        "record_count"
    ] == 1

    assert snapshot[
        "records"
    ][0][
        "candidate_id"
    ] == "candidate-1"


def test_navigation_transition_validation_store_is_idempotent(
    tmp_path,
):
    store = (
        AutoTwinNavigationTransitionValidationStore(
            path=(
                tmp_path
                / "validation.json"
            )
        )
    )

    first = store.record_twin_validated(
        _validation()
    )

    second = store.record_twin_validated(
        _validation()
    )

    assert first[
        "created"
    ] is True

    assert second[
        "created"
    ] is False

    assert (
        first[
            "evidence_id"
        ]
        == second[
            "evidence_id"
        ]
    )

    assert store.snapshot()[
        "record_count"
    ] == 1

    assert store.revision == 1


def test_navigation_transition_validation_store_scopes_revision_identity(
    tmp_path,
):
    store = (
        AutoTwinNavigationTransitionValidationStore(
            path=(
                tmp_path
                / "validation.json"
            )
        )
    )

    first = _validation()

    second = _validation()
    second[
        "revision_id"
    ] = "matrev-test-v2"

    result_a = (
        store.record_twin_validated(
            first
        )
    )

    result_b = (
        store.record_twin_validated(
            second
        )
    )

    assert (
        result_a[
            "evidence_id"
        ]
        != result_b[
            "evidence_id"
        ]
    )

    assert store.snapshot()[
        "record_count"
    ] == 2
