import json

from backend.qcc.auto_twin.automatic_materialization import (
    _carry_forward_navigation_candidates,
    _navigation_refresh_for_latest_revision,
)

from backend.qcc.auto_twin.navigation_transition_materialization import (
    AUTO_TWIN_NAVIGATION_EVIDENCE_SOURCE,
    project_twin_eligible_navigation_candidates,
)

from backend.qcc.auto_twin.navigation_transition_runtime import (
    build_navigation_runtime_payload,
    outgoing_navigation_transitions,
)


FP_A = "a" * 64
FP_B = "b" * 64
FP_MISSING = "c" * 64

NTH_SELECTOR = (
    'a[onclick="validarYEnviar()"]:qcc-nth-onclick(5)'
)


def _store_candidate(
    *,
    candidate_id="cand-a-b",
    before=FP_A,
    after=FP_B,
    selector=NTH_SELECTOR,
    status="CONFIRMED",
    observation_count=3,
    evidence_source=AUTO_TWIN_NAVIGATION_EVIDENCE_SOURCE,
    navigation_context=(),
):
    return {
        "candidate_id":
            candidate_id,

        "evidence_source":
            evidence_source,

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

        "navigation_context":
            list(navigation_context),

        "observation_count":
            observation_count,

        "status":
            status,

        "promoted_at":
            "2026-09-19T07:36:45.143407+00:00",
    }


def _snapshot(*candidates):
    return {
        "candidates":
            list(candidates),
    }


def _runtime_states():
    return [
        {
            "state_id":
                "STATE_A",

            "fingerprint":
                FP_A,

            "runtime_entry":
                "states/01-STATE_A/runtime/index.html",
        },
        {
            "state_id":
                "STATE_B",

            "fingerprint":
                FP_B,

            "runtime_entry":
                "states/02-STATE_B/runtime/index.html",
        },
    ]


def _write_revision(
    root,
    *,
    transitions=(),
    states=None,
):
    runtime = root / "runtime"
    runtime.mkdir(
        parents=True
    )

    (
        runtime
        / "registry.json"
    ).write_text(
        json.dumps({
            "states":
                (
                    _runtime_states()
                    if states is None
                    else states
                )
        }),
        encoding="utf-8",
    )

    (
        runtime
        / "navigation_transitions.json"
    ).write_text(
        json.dumps({
            "transition_count":
                len(transitions),

            "transitions":
                list(transitions),
        }),
        encoding="utf-8",
    )


def _refresh(
    root,
    snapshot,
):
    projected = (
        project_twin_eligible_navigation_candidates(
            snapshot
        )
    )

    carried = _carry_forward_navigation_candidates(
        root,
        projected,
    )

    return _navigation_refresh_for_latest_revision(
        revision_dir=root,
        candidates=carried,
    )


def test_confirmed_promoted_candidate_survives_projection():
    projected = (
        project_twin_eligible_navigation_candidates(
            _snapshot(
                _store_candidate()
            )
        )
    )

    assert len(projected) == 1
    assert projected[0]["before_fingerprint"] == FP_A
    assert projected[0]["after_fingerprint"] == FP_B
    assert projected[0]["candidate_status"] == "CONFIRMED"
    assert projected[0]["action"]["selector"] == NTH_SELECTOR


def test_non_eligible_candidates_are_excluded():
    projected = (
        project_twin_eligible_navigation_candidates(
            _snapshot(
                _store_candidate(
                    candidate_id="no-observations",
                    observation_count=0,
                ),
                _store_candidate(
                    candidate_id="foreign-source",
                    evidence_source="SOMETHING_ELSE",
                ),
            )
        )
    )

    assert projected == ()


def test_zero_transition_revision_refreshes_to_include_a_to_b(
    tmp_path,
):
    _write_revision(
        tmp_path
    )

    selected, refresh = _refresh(
        tmp_path,
        _snapshot(
            _store_candidate()
        ),
    )

    assert refresh is True
    assert len(selected) == 1

    payload = build_navigation_runtime_payload(
        selected,
        _runtime_states(),
    )

    assert payload["transition_count"] >= 1

    outgoing = outgoing_navigation_transitions(
        payload,
        "STATE_A",
    )

    assert len(outgoing) == 1
    assert outgoing[0]["action"]["selector"] == NTH_SELECTOR
    assert outgoing[0]["after_state_id"] == "STATE_B"

    assert (
        outgoing[0]["target_runtime_entry"]
        == "states/02-STATE_B/runtime/index.html"
    )


def test_missing_before_endpoint_is_excluded(
    tmp_path,
):
    _write_revision(
        tmp_path
    )

    selected, refresh = _refresh(
        tmp_path,
        _snapshot(
            _store_candidate(
                before=FP_MISSING,
            )
        ),
    )

    assert selected == ()
    assert refresh is False


def test_missing_after_endpoint_is_excluded(
    tmp_path,
):
    _write_revision(
        tmp_path
    )

    selected, refresh = _refresh(
        tmp_path,
        _snapshot(
            _store_candidate(
                after=FP_MISSING,
            )
        ),
    )

    assert selected == ()
    assert refresh is False


def test_repeated_reconciliation_is_idempotent_and_never_duplicates(
    tmp_path,
):
    snapshot = _snapshot(
        _store_candidate()
    )

    _write_revision(
        tmp_path
    )

    selected, _ = _refresh(
        tmp_path,
        snapshot,
    )

    payload = build_navigation_runtime_payload(
        selected,
        _runtime_states(),
    )

    # Same inputs -> byte-identical runtime payload.
    assert payload == build_navigation_runtime_payload(
        selected,
        _runtime_states(),
    )

    # Simulate the materialized result and reconcile again.
    (
        tmp_path
        / "runtime"
        / "navigation_transitions.json"
    ).write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    for _ in range(2):
        again, refresh = _refresh(
            tmp_path,
            snapshot,
        )

        assert refresh is False
        assert len(again) == 1


def test_previous_valid_navigation_is_carried_forward(
    tmp_path,
):
    first, _ = _refresh(
        _prepared(
            tmp_path / "first"
        ),
        _snapshot(
            _store_candidate()
        ),
    )

    payload = build_navigation_runtime_payload(
        first,
        _runtime_states(),
    )

    revision = tmp_path / "second"

    _write_revision(
        revision,
        transitions=payload["transitions"],
    )

    # The live candidate store is empty/partial in this pass.
    selected, refresh = _refresh(
        revision,
        _snapshot(),
    )

    assert refresh is False
    assert len(selected) == 1

    assert (
        selected[0]["action"]["selector"]
        == NTH_SELECTOR
    )


def _prepared(
    root,
):
    _write_revision(
        root
    )

    return root


def test_contextual_transition_carried_forward_is_idempotent(
    tmp_path,
):
    """Regression: a carried-forward contextual transition lost its
    context_signature, so its signature never matched the
    materialized one and every reconcile forced a refresh."""

    context = [
        {
            "key":
                "opcion",

            "selected_values":
                ["BI"],
        }
    ]

    snapshot = _snapshot(
        _store_candidate(
            selector='button[onclick="irOpcion()"]',
            navigation_context=context,
        )
    )

    first, _ = _refresh(
        _prepared(
            tmp_path / "first"
        ),
        snapshot,
    )

    assert len(first) == 1
    assert first[0]["context_signature"]

    payload = build_navigation_runtime_payload(
        first,
        _runtime_states(),
    )

    revision = tmp_path / "second"

    _write_revision(
        revision,
        transitions=payload["transitions"],
    )

    selected, refresh = _refresh(
        revision,
        _snapshot(),
    )

    assert len(selected) == 1
    assert refresh is False

    assert (
        selected[0]["context_signature"]
        == first[0]["context_signature"]
    )
