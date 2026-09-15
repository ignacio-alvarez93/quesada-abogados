import json

import pytest

from backend.qcc.auto_twin.navigation_transition_validation import (
    validate_materialized_navigation_transition,
)


def _revision(
    root,
):
    revision = (
        root
        / "mercurio"
        / "matrev-validation"
    )

    runtime = (
        revision
        / "runtime"
    )

    runtime.mkdir(
        parents=True
    )

    payload = {
        "schema_version": 1,
        "record_type":
            "QCC_AUTO_TWIN_NAVIGATION_RUNTIME",
        "transition_count": 1,
        "transitions": [
            {
                "candidate_id":
                    "candidate-1",

                "eligibility":
                    "TWIN_ELIGIBLE",

                "before_state_id":
                    "AUTO_A",

                "after_state_id":
                    "AUTO_B",

                "target_runtime_entry":
                    "states/01-AUTO_B/runtime/index.html",

                "action": {
                    "kind":
                        "BUTTON",

                    "selector":
                        'button[onclick="go()"]',

                    "frame_path":
                        "main",
                },
            },
        ],
    }

    (
        runtime
        / "navigation_transitions.json"
    ).write_text(
        json.dumps(
            payload
        ),
        encoding="utf-8",
    )

    return revision


class FakeBrowserRuntime:
    def __init__(
        self,
        *,
        escaped=False,
    ):
        self.started = []
        self.stopped = []
        self.clicked = []
        self.escaped = escaped
        self.did_click = False

    def start(
        self,
        *,
        twin_key,
        revision_id,
        state_id=None,
        pathname=None,
    ):
        self.started.append({
            "twin_key":
                twin_key,

            "revision_id":
                revision_id,

            "state_id":
                state_id,

            "pathname":
                pathname,
        })

        return {
            "status":
                "RUNNING",

            "url":
                (
                    "http://127.0.0.1:45678/"
                    "states/00-AUTO_A/runtime/index.html"
                ),
        }

    def execute_script(
        self,
        *,
        twin_key,
        script,
        args=None,
        timeout=None,
    ):
        if (
            "QCC_AUTO_TWIN_NAVIGATION_VALIDATION_CLICK_V1"
            in script
        ):
            self.clicked.append(
                args[0]
            )

            self.did_click = True

            return {
                "found":
                    True,

                "href":
                    (
                        "http://127.0.0.1:45678/"
                        "states/00-AUTO_A/runtime/index.html"
                    ),
            }

        assert (
            "QCC_AUTO_TWIN_NAVIGATION_VALIDATION_LOCATION_V1"
            in script
        )

        if self.escaped:
            return {
                "href":
                    "https://example.com/escaped",

                "origin":
                    "https://example.com",

                "pathname":
                    "/escaped",
            }

        if self.did_click:
            return {
                "href":
                    (
                        "http://127.0.0.1:45678/"
                        "states/01-AUTO_B/runtime/index.html"
                    ),

                "origin":
                    "http://127.0.0.1:45678",

                "pathname":
                    "/states/01-AUTO_B/runtime/index.html",
            }

        raise AssertionError(
            "LOCATION_BEFORE_CLICK"
        )

    def stop(
        self,
        *,
        twin_key,
    ):
        self.stopped.append(
            twin_key
        )

        return {
            "status":
                "STOPPED",
        }


def test_navigation_transition_validation_replays_exact_local_edge(
    tmp_path,
):
    _revision(
        tmp_path
    )

    browser = (
        FakeBrowserRuntime()
    )

    result = (
        validate_materialized_navigation_transition(
            twin_key="mercurio",
            revision_id="matrev-validation",
            candidate_id="candidate-1",
            browser_runtime_service=browser,
            materialized_root=tmp_path,
            timeout_seconds=1,
            poll_interval_seconds=0.01,
        )
    )

    assert result[
        "status"
    ] == "TWIN_VALIDATED"

    assert result[
        "reason"
    ] == "EXACT_LOCAL_TARGET_REACHED"

    assert browser.started == [
        {
            "twin_key":
                "mercurio",

            "revision_id":
                "matrev-validation",

            "state_id":
                "AUTO_A",

            "pathname":
                None,
        },
    ]

    assert browser.clicked == [
        'button[onclick="go()"]',
    ]

    assert browser.stopped == [
        "mercurio",
    ]


def test_navigation_transition_validation_fails_closed_on_origin_escape(
    tmp_path,
):
    _revision(
        tmp_path
    )

    browser = FakeBrowserRuntime(
        escaped=True
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "QCC_AUTO_TWIN_NAVIGATION_VALIDATION_"
            "NON_LOCAL_RUNTIME"
        ),
    ):
        validate_materialized_navigation_transition(
            twin_key="mercurio",
            revision_id="matrev-validation",
            candidate_id="candidate-1",
            browser_runtime_service=browser,
            materialized_root=tmp_path,
            timeout_seconds=1,
            poll_interval_seconds=0.01,
        )

    assert browser.stopped == [
        "mercurio",
    ]


def test_navigation_transition_validation_records_success(
    tmp_path,
):
    from backend.qcc.auto_twin.navigation_transition_validation import (
        validate_and_record_materialized_navigation_transition,
    )
    from backend.qcc.auto_twin.navigation_transition_validation_store import (
        AutoTwinNavigationTransitionValidationStore,
    )

    _revision(
        tmp_path
    )

    browser = (
        FakeBrowserRuntime()
    )

    store = (
        AutoTwinNavigationTransitionValidationStore(
            path=(
                tmp_path
                / "validation-store.json"
            )
        )
    )

    result = (
        validate_and_record_materialized_navigation_transition(
            twin_key="mercurio",
            revision_id="matrev-validation",
            candidate_id="candidate-1",
            browser_runtime_service=browser,
            validation_store=store,
            materialized_root=tmp_path,
            timeout_seconds=1,
            poll_interval_seconds=0.01,
        )
    )

    assert result[
        "status"
    ] == "TWIN_VALIDATED"

    assert result[
        "recorded"
    ] is True

    assert result[
        "persistence"
    ][
        "created"
    ] is True

    assert store.snapshot()[
        "record_count"
    ] == 1


def test_navigation_transition_validation_recording_is_idempotent(
    tmp_path,
):
    from backend.qcc.auto_twin.navigation_transition_validation import (
        validate_and_record_materialized_navigation_transition,
    )
    from backend.qcc.auto_twin.navigation_transition_validation_store import (
        AutoTwinNavigationTransitionValidationStore,
    )

    _revision(
        tmp_path
    )

    store = (
        AutoTwinNavigationTransitionValidationStore(
            path=(
                tmp_path
                / "validation-store.json"
            )
        )
    )

    first = (
        validate_and_record_materialized_navigation_transition(
            twin_key="mercurio",
            revision_id="matrev-validation",
            candidate_id="candidate-1",
            browser_runtime_service=FakeBrowserRuntime(),
            validation_store=store,
            materialized_root=tmp_path,
            timeout_seconds=1,
            poll_interval_seconds=0.01,
        )
    )

    second = (
        validate_and_record_materialized_navigation_transition(
            twin_key="mercurio",
            revision_id="matrev-validation",
            candidate_id="candidate-1",
            browser_runtime_service=FakeBrowserRuntime(),
            validation_store=store,
            materialized_root=tmp_path,
            timeout_seconds=1,
            poll_interval_seconds=0.01,
        )
    )

    assert first[
        "persistence"
    ][
        "created"
    ] is True

    assert second[
        "persistence"
    ][
        "created"
    ] is False

    assert (
        first[
            "persistence"
        ][
            "evidence_id"
        ]
        == second[
            "persistence"
        ][
            "evidence_id"
        ]
    )

    assert store.snapshot()[
        "record_count"
    ] == 1
