import json

from backend.qcc.auto_twin.automatic_materialization import (
    _carry_forward_navigation_candidates,
    _navigation_refresh_for_latest_revision,
)

from backend.qcc.auto_twin.navigation_transition_materialization import (
    AUTO_TWIN_NAVIGATION_EVIDENCE_SOURCE,
    AUTO_TWIN_NAVIGATION_EVIDENCE_TWIN_ELIGIBLE,
    AUTO_TWIN_NAVIGATION_TRANSITION_SCHEMA_VERSION,
    AUTO_TWIN_NAVIGATION_TRANSITION_TYPE,
)


FP_A = "a" * 64
FP_B = "b" * 64


def _candidate(
    *,
    observation_count=1,
    status="CANDIDATE",
):
    return {
        "schema_version":
            AUTO_TWIN_NAVIGATION_TRANSITION_SCHEMA_VERSION,

        "transition_type":
            AUTO_TWIN_NAVIGATION_TRANSITION_TYPE,

        "candidate_id":
            "candidate-1",

        "eligibility":
            AUTO_TWIN_NAVIGATION_EVIDENCE_TWIN_ELIGIBLE,

        "evidence_source":
            AUTO_TWIN_NAVIGATION_EVIDENCE_SOURCE,

        "real_observation_count":
            observation_count,

        "candidate_status":
            status,

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
                'a[onclick="continuar(\'INI\');"]',

            "frame_path":
                "main",
        },
    }


def _write_revision(
    root,
    *,
    transitions=(),
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
            "states": [
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
        }),
        encoding="utf-8",
    )

    (
        runtime
        / "navigation_transitions.json"
    ).write_text(
        json.dumps({
            "transitions":
                list(
                    transitions
                )
        }),
        encoding="utf-8",
    )


def test_existing_physical_states_make_candidate_materializable(
    tmp_path,
):
    _write_revision(
        tmp_path
    )

    selected, refresh = (
        _navigation_refresh_for_latest_revision(
            revision_dir=tmp_path,
            candidates=(
                _candidate(),
            ),
        )
    )

    assert len(
        selected
    ) == 1

    assert refresh is True


def test_missing_physical_target_defers_transition(
    tmp_path,
):
    runtime = tmp_path / "runtime"
    runtime.mkdir()

    (
        runtime
        / "registry.json"
    ).write_text(
        json.dumps({
            "states": [
                {
                    "state_id":
                        "STATE_A",

                    "fingerprint":
                        FP_A,

                    "runtime_entry":
                        "states/01-STATE_A/runtime/index.html",
                }
            ]
        }),
        encoding="utf-8",
    )

    selected, refresh = (
        _navigation_refresh_for_latest_revision(
            revision_dir=tmp_path,
            candidates=(
                _candidate(),
            ),
        )
    )

    assert selected == ()
    assert refresh is False


def test_same_materialized_evidence_is_idempotent(
    tmp_path,
):
    candidate = _candidate()

    # Runtime artifact contains extra resolved fields.
    runtime_transition = {
        **candidate,

        "before_state_id":
            "STATE_A",

        "after_state_id":
            "STATE_B",

        "target_runtime_entry":
            "states/02-STATE_B/runtime/index.html",
    }

    _write_revision(
        tmp_path,
        transitions=(
            runtime_transition,
        ),
    )

    selected, refresh = (
        _navigation_refresh_for_latest_revision(
            revision_dir=tmp_path,
            candidates=(
                candidate,
            ),
        )
    )

    assert len(
        selected
    ) == 1

    assert refresh is False


def test_stronger_real_evidence_creates_navigation_refresh(
    tmp_path,
):
    old = _candidate(
        observation_count=1,
        status="CANDIDATE",
    )

    runtime_transition = {
        **old,

        "before_state_id":
            "STATE_A",

        "after_state_id":
            "STATE_B",

        "target_runtime_entry":
            "states/02-STATE_B/runtime/index.html",
    }

    _write_revision(
        tmp_path,
        transitions=(
            runtime_transition,
        ),
    )

    stronger = _candidate(
        observation_count=2,
        status="CORROBORATED",
    )

    selected, refresh = (
        _navigation_refresh_for_latest_revision(
            revision_dir=tmp_path,
            candidates=(
                stronger,
            ),
        )
    )

    assert len(
        selected
    ) == 1

    assert refresh is True


def test_new_state_uses_last_capture_when_causal_fingerprint_matches():
    from backend.qcc.auto_twin.automatic_materialization import (
        _new_state_navigation_source,
    )

    state = {
        "baseline_capture_id":
            "baseline-a",

        "baseline_fingerprint":
            "1" * 64,

        "last_capture_id":
            "causal-a",

        "last_fingerprint":
            FP_A,
    }

    capture_id, source_kind = (
        _new_state_navigation_source(
            state,
            (
                _candidate(),
            ),
        )
    )

    assert capture_id == "causal-a"
    assert source_kind == "CAUSAL_LAST"


def test_new_state_keeps_baseline_when_not_part_of_causal_evidence():
    from backend.qcc.auto_twin.automatic_materialization import (
        _new_state_navigation_source,
    )

    state = {
        "baseline_capture_id":
            "baseline-other",

        "baseline_fingerprint":
            "1" * 64,

        "last_capture_id":
            "last-other",

        "last_fingerprint":
            "c" * 64,
    }

    capture_id, source_kind = (
        _new_state_navigation_source(
            state,
            (
                _candidate(),
            ),
        )
    )

    assert capture_id == "baseline-other"
    assert source_kind == "BASELINE"


def _materialized_runtime_transition(
    *,
    candidate_id="old-candidate",
    observation_count=1,
    before_fingerprint=FP_A,
    after_fingerprint=FP_B,
    selector='a[onclick="continuar();"]',
):
    return {
        **_candidate(
            observation_count=observation_count,
        ),

        "candidate_id":
            candidate_id,

        "before_fingerprint":
            before_fingerprint,

        "after_fingerprint":
            after_fingerprint,

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

        "before_state_id":
            "STATE_A",

        "after_state_id":
            "STATE_B",

        "target_runtime_entry":
            "states/02-STATE_B/runtime/index.html",
    }


def test_carry_forward_reintroduces_candidate_missing_from_partial_live_snapshot(
    tmp_path,
):
    """A newer materialization pass whose live candidate-store
    snapshot is empty/partial must not silently drop navigation that
    was already validated and materialized in the immediately
    preceding revision."""

    _write_revision(
        tmp_path,
        transitions=(
            _materialized_runtime_transition(),
        ),
    )

    carried = _carry_forward_navigation_candidates(
        tmp_path,
        (),
    )

    assert len(carried) == 1
    assert carried[0]["candidate_id"] == "old-candidate"
    assert carried[0]["before_fingerprint"] == FP_A
    assert carried[0]["after_fingerprint"] == FP_B

    selected, refresh = (
        _navigation_refresh_for_latest_revision(
            revision_dir=tmp_path,
            candidates=carried,
        )
    )

    assert len(selected) == 1


def test_carry_forward_never_overrides_a_live_candidate_with_the_same_id(
    tmp_path,
):
    _write_revision(
        tmp_path,
        transitions=(
            _materialized_runtime_transition(
                observation_count=1,
            ),
        ),
    )

    live = _candidate(
        observation_count=5,
        status="CORROBORATED",
    )

    live = {
        **live,

        "candidate_id":
            "old-candidate",
    }

    carried = _carry_forward_navigation_candidates(
        tmp_path,
        (live,),
    )

    assert len(carried) == 1
    assert carried[0] is live
    assert carried[0]["real_observation_count"] == 5


def test_carry_forward_drops_transition_whose_endpoint_state_disappeared(
    tmp_path,
):
    """A carried-forward candidate is never exempt from the ordinary
    fingerprint-existence gate: an endpoint that genuinely no longer
    exists must still be dropped, not force-materialized."""

    runtime = tmp_path / "runtime"
    runtime.mkdir(
        parents=True
    )

    (
        runtime
        / "registry.json"
    ).write_text(
        json.dumps({
            "states": [
                {
                    "state_id":
                        "STATE_A",

                    "fingerprint":
                        FP_A,

                    "runtime_entry":
                        "states/01-STATE_A/runtime/index.html",
                },
            ]
        }),
        encoding="utf-8",
    )

    stale_after_fingerprint = "c" * 64

    (
        runtime
        / "navigation_transitions.json"
    ).write_text(
        json.dumps({
            "transitions": [
                _materialized_runtime_transition(
                    after_fingerprint=(
                        stale_after_fingerprint
                    ),
                ),
            ]
        }),
        encoding="utf-8",
    )

    carried = _carry_forward_navigation_candidates(
        tmp_path,
        (),
    )

    assert len(carried) == 1

    selected, refresh = (
        _navigation_refresh_for_latest_revision(
            revision_dir=tmp_path,
            candidates=carried,
        )
    )

    assert selected == ()
