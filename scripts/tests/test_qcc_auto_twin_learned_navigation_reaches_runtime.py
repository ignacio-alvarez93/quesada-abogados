import json

from backend.qcc.auto_twin.automatic_materialization import (
    _carry_forward_navigation_candidates,
    _navigation_refresh_for_latest_revision,
)

from backend.qcc.auto_twin.navigation_transition_materialization import (
    AUTO_TWIN_NAVIGATION_EVIDENCE_SOURCE,
    project_twin_eligible_navigation_candidates,
)

import pytest

from backend.qcc.auto_twin.navigation_transition_runtime import (
    AUTO_TWIN_NAVIGATION_RUNTIME_SEMANTIC_SOURCE_MIRROR_MODE,
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


def _persist_revision_runtime(
    root,
    *,
    transitions=(),
    states=None,
):
    """Overwrite the runtime JSON files of an ALREADY-CREATED revision
    to simulate persisting a freshly materialized payload, without
    recreating (or re-mkdir'ing) the revision directory itself."""

    runtime = root / "runtime"

    assert runtime.is_dir()

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


# QCC_AUTO_TWIN_SEMANTIC_EQUIVALENT_TARGET_V1 regression tests.

SEM_SELECTOR = (
    'a[onclick="continuar();"]'
)

FP_SEM_SRC = "1" * 64
FP_SEM_T1 = "2" * 64
FP_SEM_T2 = "3" * 64


def _semantic_runtime_state(
    state_id,
    fingerprint,
    *,
    pathname="/mercurio/modoAcceso.html",
    functional_state=None,
    branch_context_id=None,
    state_variant_key=None,
):
    state = {
        "state_id":
            state_id,

        "fingerprint":
            fingerprint,

        "runtime_entry":
            f"states/{state_id}/runtime/index.html",

        "pathname":
            pathname,

        "functional_state":
            functional_state,
    }

    if branch_context_id is not None:
        state["branch_context_id"] = branch_context_id

    if state_variant_key is not None:
        state["state_variant_key"] = state_variant_key

    return state


def _semantic_opaque_candidates(
    *,
    after_one=FP_SEM_T1,
    after_two=FP_SEM_T2,
):
    return (
        _store_candidate(
            candidate_id="cand-one",
            before=FP_SEM_SRC,
            after=after_one,
            selector=SEM_SELECTOR,
        ),
        _store_candidate(
            candidate_id="cand-two",
            before=FP_SEM_SRC,
            after=after_two,
            selector=SEM_SELECTOR,
        ),
    )


def _semantic_transitions(
    *candidates,
):
    return (
        project_twin_eligible_navigation_candidates(
            _snapshot(
                *candidates
            )
        )
    )


def test_opaque_group_collapses_when_outcomes_share_semantic_identity():
    """A. Same logical target: two historical fingerprints resolving to
    the same pathname/functional_state collapse to one runtime route."""

    transitions = _semantic_transitions(
        *_semantic_opaque_candidates()
    )

    runtime_states = [
        _semantic_runtime_state(
            "STATE_SRC",
            FP_SEM_SRC,
            pathname="/mercurio/entrada.html",
        ),
        _semantic_runtime_state(
            "STATE_T1",
            FP_SEM_T1,
        ),
        _semantic_runtime_state(
            "STATE_T2",
            FP_SEM_T2,
        ),
    ]

    payload = build_navigation_runtime_payload(
        transitions,
        runtime_states,
    )

    assert payload["transition_count"] == 1
    assert payload["interactive_transition_count"] == 1
    assert payload["contextual_unresolved_count"] == 0

    transition = payload["transitions"][0]

    assert transition["semantic_target_collapsed"] is True
    assert transition["evidence_outcome_mode"] == "CONTEXTUAL_OPAQUE"
    assert (
        transition["after_state_id"]
        in {"STATE_T1", "STATE_T2"}
    )

    outgoing = outgoing_navigation_transitions(
        payload,
        "STATE_SRC",
    )

    assert len(outgoing) == 1


def test_opaque_group_remains_unresolved_when_pathname_differs():
    """B. Different pathname: must remain fail-closed."""

    transitions = _semantic_transitions(
        *_semantic_opaque_candidates()
    )

    runtime_states = [
        _semantic_runtime_state(
            "STATE_SRC",
            FP_SEM_SRC,
            pathname="/mercurio/entrada.html",
        ),
        _semantic_runtime_state(
            "STATE_T1",
            FP_SEM_T1,
            pathname="/mercurio/modoAcceso.html",
        ),
        _semantic_runtime_state(
            "STATE_T2",
            FP_SEM_T2,
            pathname="/mercurio/otraRuta.html",
        ),
    ]

    payload = build_navigation_runtime_payload(
        transitions,
        runtime_states,
    )

    assert payload["contextual_unresolved_count"] == 1
    assert payload["interactive_transition_count"] == 0

    assert (
        outgoing_navigation_transitions(
            payload,
            "STATE_SRC",
        )
        == ()
    )


def test_opaque_group_remains_unresolved_when_functional_state_differs():
    """C. Same pathname, different functional_state: fail-closed."""

    transitions = _semantic_transitions(
        *_semantic_opaque_candidates()
    )

    runtime_states = [
        _semantic_runtime_state(
            "STATE_SRC",
            FP_SEM_SRC,
            pathname="/mercurio/entrada.html",
        ),
        _semantic_runtime_state(
            "STATE_T1",
            FP_SEM_T1,
            functional_state="ACTIVE",
        ),
        _semantic_runtime_state(
            "STATE_T2",
            FP_SEM_T2,
            functional_state="INACTIVE",
        ),
    ]

    payload = build_navigation_runtime_payload(
        transitions,
        runtime_states,
    )

    assert payload["contextual_unresolved_count"] == 1
    assert payload["interactive_transition_count"] == 0


def test_opaque_group_remains_unresolved_when_branch_context_differs():
    """D. Same pathname/state, different non-empty branch_context_id."""

    transitions = _semantic_transitions(
        *_semantic_opaque_candidates()
    )

    runtime_states = [
        _semantic_runtime_state(
            "STATE_SRC",
            FP_SEM_SRC,
            pathname="/mercurio/entrada.html",
        ),
        _semantic_runtime_state(
            "STATE_T1",
            FP_SEM_T1,
            branch_context_id="BR1",
        ),
        _semantic_runtime_state(
            "STATE_T2",
            FP_SEM_T2,
            branch_context_id="BR2",
        ),
    ]

    payload = build_navigation_runtime_payload(
        transitions,
        runtime_states,
    )

    assert payload["contextual_unresolved_count"] == 1
    assert payload["interactive_transition_count"] == 0


def test_opaque_group_remains_unresolved_when_state_variant_differs():
    """E. state_variant_key present and differing: fail-closed."""

    transitions = _semantic_transitions(
        *_semantic_opaque_candidates()
    )

    runtime_states = [
        _semantic_runtime_state(
            "STATE_SRC",
            FP_SEM_SRC,
            pathname="/mercurio/entrada.html",
        ),
        _semantic_runtime_state(
            "STATE_T1",
            FP_SEM_T1,
            state_variant_key="V1",
        ),
        _semantic_runtime_state(
            "STATE_T2",
            FP_SEM_T2,
            state_variant_key="V2",
        ),
    ]

    payload = build_navigation_runtime_payload(
        transitions,
        runtime_states,
    )

    assert payload["contextual_unresolved_count"] == 1
    assert payload["interactive_transition_count"] == 0


def test_opaque_group_remains_unresolved_when_outcome_fingerprint_is_ambiguous():
    """F. One outcome fingerprint resolves to more than one physical
    runtime state: never guess, remain fail-closed."""

    transitions = _semantic_transitions(
        *_semantic_opaque_candidates()
    )

    runtime_states = [
        _semantic_runtime_state(
            "STATE_SRC",
            FP_SEM_SRC,
            pathname="/mercurio/entrada.html",
        ),
        _semantic_runtime_state(
            "STATE_T1_DUP_A",
            FP_SEM_T1,
        ),
        _semantic_runtime_state(
            "STATE_T1_DUP_B",
            FP_SEM_T1,
        ),
        _semantic_runtime_state(
            "STATE_T2",
            FP_SEM_T2,
        ),
    ]

    payload = build_navigation_runtime_payload(
        transitions,
        runtime_states,
    )

    assert payload["contextual_unresolved_count"] == 1
    assert payload["interactive_transition_count"] == 0


def test_opaque_collapse_preserves_multi_candidate_provenance():
    """G. The collapsed route preserves evidence that more than one
    REAL candidate/outcome supported the single semantic target."""

    transitions = _semantic_transitions(
        *_semantic_opaque_candidates()
    )

    runtime_states = [
        _semantic_runtime_state(
            "STATE_SRC",
            FP_SEM_SRC,
            pathname="/mercurio/entrada.html",
        ),
        _semantic_runtime_state(
            "STATE_T1",
            FP_SEM_T1,
        ),
        _semantic_runtime_state(
            "STATE_T2",
            FP_SEM_T2,
        ),
    ]

    payload = build_navigation_runtime_payload(
        transitions,
        runtime_states,
    )

    transition = payload["transitions"][0]

    assert sorted(
        transition["candidate_ids"]
    ) == ["cand-one", "cand-two"]

    assert transition["real_observation_count"] == 6


def test_existing_contextual_resolved_branching_is_unaffected():
    """H. Context-discriminated branching must remain unchanged."""

    context_bi = [
        {
            "key":
                "opcion",

            "selected_values":
                ["BI"],
        }
    ]

    context_pe = [
        {
            "key":
                "opcion",

            "selected_values":
                ["PE"],
        }
    ]

    candidates = (
        _store_candidate(
            candidate_id="cand-bi",
            before=FP_SEM_SRC,
            after=FP_SEM_T1,
            selector=SEM_SELECTOR,
            navigation_context=context_bi,
        ),
        _store_candidate(
            candidate_id="cand-pe",
            before=FP_SEM_SRC,
            after=FP_SEM_T2,
            selector=SEM_SELECTOR,
            navigation_context=context_pe,
        ),
    )

    transitions = _semantic_transitions(
        *candidates
    )

    runtime_states = [
        _semantic_runtime_state(
            "STATE_SRC",
            FP_SEM_SRC,
            pathname="/mercurio/entrada.html",
        ),
        _semantic_runtime_state(
            "STATE_T1",
            FP_SEM_T1,
        ),
        _semantic_runtime_state(
            "STATE_T2",
            FP_SEM_T2,
        ),
    ]

    payload = build_navigation_runtime_payload(
        transitions,
        runtime_states,
    )

    assert payload["contextual_unresolved_count"] == 0
    assert payload["contextual_resolved_count"] == 2
    assert payload["interactive_transition_count"] == 2

    for transition in payload["transitions"]:
        assert transition.get(
            "semantic_target_collapsed"
        ) is None

        assert (
            transition["outcome_mode"]
            == "CONTEXTUAL_RESOLVED"
        )


# QCC_AUTO_TWIN_SEMANTIC_TARGET_IDEMPOTENCY_R2 regression tests.
#
# _navigation_refresh_for_latest_revision() must compare LIKE WITH
# LIKE: the desired EXECUTABLE runtime capability (projected through
# build_navigation_runtime_payload using the SAME runtime_states
# authority actual materialization uses) against the currently
# materialized executable runtime capability -- never raw evidence
# cardinality against runtime cardinality.


def _semantic_revision_runtime_states():
    return [
        _semantic_runtime_state(
            "STATE_SRC",
            FP_SEM_SRC,
            pathname="/mercurio/entrada.html",
        ),
        _semantic_runtime_state(
            "STATE_T1",
            FP_SEM_T1,
        ),
        _semantic_runtime_state(
            "STATE_T2",
            FP_SEM_T2,
        ),
    ]


def test_semantic_collapse_navigation_refresh_settles(
    tmp_path,
):
    """A + B. Two raw evidence signatures (A->B1, A->B2) collapse to
    ONE executable runtime route. Once that projected runtime is
    persisted, reconciling against the IDENTICAL raw evidence must
    settle (refresh == False) -- never loop just because the raw
    cardinality (2) permanently differs from the runtime cardinality
    (1)."""

    runtime_states = (
        _semantic_revision_runtime_states()
    )

    revision = tmp_path / "revision"

    _write_revision(
        revision,
        states=runtime_states,
    )

    snapshot = _snapshot(
        *_semantic_opaque_candidates()
    )

    selected, refresh = _refresh(
        revision,
        snapshot,
    )

    # Raw evidence: both candidates physically qualify.
    assert len(selected) == 2
    assert refresh is True

    payload = build_navigation_runtime_payload(
        selected,
        runtime_states,
    )

    # Runtime: collapsed to ONE executable route.
    assert payload["transition_count"] == 1
    assert (
        payload["transitions"][0][
            "semantic_target_collapsed"
        ]
        is True
    )

    _persist_revision_runtime(
        revision,
        transitions=payload["transitions"],
        states=runtime_states,
    )

    for _ in range(2):
        again_selected, again_refresh = _refresh(
            revision,
            snapshot,
        )

        # Raw cardinality (2) permanently differs from runtime
        # cardinality (1) -- comparing them directly would loop
        # forever. The gate must settle.
        assert len(again_selected) == 2
        assert again_refresh is False


def test_semantic_collapse_detects_genuine_capability_change(
    tmp_path,
):
    """C. After an idempotent collapsed runtime exists, evidence that
    genuinely changes desired executable capability must still
    refresh."""

    runtime_states = (
        _semantic_revision_runtime_states()
    )

    revision = tmp_path / "revision"

    _write_revision(
        revision,
        states=runtime_states,
    )

    base_candidates = (
        _semantic_opaque_candidates()
    )

    selected, _ = _refresh(
        revision,
        _snapshot(
            *base_candidates
        ),
    )

    payload = build_navigation_runtime_payload(
        selected,
        runtime_states,
    )

    _persist_revision_runtime(
        revision,
        transitions=payload["transitions"],
        states=runtime_states,
    )

    _, fixed_point_refresh = _refresh(
        revision,
        _snapshot(
            *base_candidates
        ),
    )

    assert fixed_point_refresh is False

    # New REAL evidence for the SAME semantic target changes the
    # desired executable capability's provenance/observation count.
    extended_candidates = (
        base_candidates
        + (
            _store_candidate(
                candidate_id="cand-three",
                before=FP_SEM_SRC,
                after=FP_SEM_T1,
                selector=SEM_SELECTOR,
            ),
        )
    )

    _, changed_refresh = _refresh(
        revision,
        _snapshot(
            *extended_candidates
        ),
    )

    assert changed_refresh is True


def test_genuine_opaque_branch_reconcile_remains_stable(
    tmp_path,
):
    """D. Two outcomes with genuinely different semantic identities
    stay CONTEXTUAL_OPAQUE/non-executable, and once materialized in
    that unresolved state, repeated reconciliation must not force a
    refresh merely because raw candidates still exist."""

    runtime_states = [
        _semantic_runtime_state(
            "STATE_SRC",
            FP_SEM_SRC,
            pathname="/mercurio/entrada.html",
        ),
        _semantic_runtime_state(
            "STATE_T1",
            FP_SEM_T1,
            pathname="/mercurio/modoAcceso.html",
        ),
        _semantic_runtime_state(
            "STATE_T2",
            FP_SEM_T2,
            pathname="/mercurio/otraRuta.html",
        ),
    ]

    revision = tmp_path / "revision"

    _write_revision(
        revision,
        states=runtime_states,
    )

    candidates = (
        _semantic_opaque_candidates()
    )

    selected, refresh = _refresh(
        revision,
        _snapshot(
            *candidates
        ),
    )

    assert len(selected) == 2
    assert refresh is False

    payload = build_navigation_runtime_payload(
        selected,
        runtime_states,
    )

    assert payload["transition_count"] == 0
    assert payload["contextual_unresolved_count"] == 1

    _persist_revision_runtime(
        revision,
        transitions=payload["transitions"],
        states=runtime_states,
    )

    for _ in range(2):
        _, refresh_again = _refresh(
            revision,
            _snapshot(
                *candidates
            ),
        )

        assert refresh_again is False


def test_contextual_resolved_reconcile_remains_idempotent(
    tmp_path,
):
    """E. Context-discriminated branches must continue comparing
    equal after materialization."""

    runtime_states = (
        _semantic_revision_runtime_states()
    )

    context_bi = [
        {
            "key":
                "opcion",

            "selected_values":
                ["BI"],
        }
    ]

    context_pe = [
        {
            "key":
                "opcion",

            "selected_values":
                ["PE"],
        }
    ]

    candidates = (
        _store_candidate(
            candidate_id="cand-bi",
            before=FP_SEM_SRC,
            after=FP_SEM_T1,
            selector=SEM_SELECTOR,
            navigation_context=context_bi,
        ),
        _store_candidate(
            candidate_id="cand-pe",
            before=FP_SEM_SRC,
            after=FP_SEM_T2,
            selector=SEM_SELECTOR,
            navigation_context=context_pe,
        ),
    )

    revision = tmp_path / "revision"

    _write_revision(
        revision,
        states=runtime_states,
    )

    selected, refresh = _refresh(
        revision,
        _snapshot(
            *candidates
        ),
    )

    assert refresh is True

    payload = build_navigation_runtime_payload(
        selected,
        runtime_states,
    )

    assert payload["contextual_resolved_count"] == 2

    _persist_revision_runtime(
        revision,
        transitions=payload["transitions"],
        states=runtime_states,
    )

    for _ in range(2):
        _, refresh_again = _refresh(
            revision,
            _snapshot(
                *candidates
            ),
        )

        assert refresh_again is False


def test_deterministic_dedupe_reconcile_remains_idempotent(
    tmp_path,
):
    """F. Multiple evidence records for the SAME deterministic
    physical route stay one executable route and settle after
    materialization."""

    revision = tmp_path / "revision"

    _write_revision(
        revision
    )

    candidates = (
        _store_candidate(
            candidate_id="cand-one"
        ),
        _store_candidate(
            candidate_id="cand-two"
        ),
    )

    selected, refresh = _refresh(
        revision,
        _snapshot(
            *candidates
        ),
    )

    assert refresh is True
    assert len(selected) == 2

    payload = build_navigation_runtime_payload(
        selected,
        _runtime_states(),
    )

    assert payload["transition_count"] == 1

    _persist_revision_runtime(
        revision,
        transitions=payload["transitions"],
    )

    for _ in range(2):
        _, refresh_again = _refresh(
            revision,
            _snapshot(
                *candidates
            ),
        )

        assert refresh_again is False


# QCC_AUTO_TWIN_SEMANTIC_SOURCE_MIRROR_V1 regression tests.
#
# Reproduces the Mercurio entry-state defect generically: a learned
# route whose before_fingerprint belongs to ONE physical capture is
# mirrored onto a SIBLING physical capture that shares the exact same
# governed Twin identity (pathname/functional_state/branch_context_id/
# state_variant_key) but was never itself the before-state of any
# directly-observed REAL click.

MIRROR_SELECTOR = (
    'a[onclick="continuar();"]'
)

FP_MIRROR_ENTRY = "4" * 64
FP_MIRROR_REVISIT = "5" * 64
FP_MIRROR_TARGET = "6" * 64
FP_MIRROR_TARGET_2 = "7" * 64
FP_MIRROR_REVISIT_2 = "8" * 64


def test_entry_state_inherits_sibling_outgoing_transition():
    """A. A physically distinct sibling capture of the SAME governed
    Twin identity (e.g. the TWIN entry state) inherits the governed
    outgoing route observed only on another capture of that identity."""

    transitions = _semantic_transitions(
        _store_candidate(
            candidate_id="cand-revisit-continuar",
            before=FP_MIRROR_REVISIT,
            after=FP_MIRROR_TARGET,
            selector=MIRROR_SELECTOR,
        ),
    )

    runtime_states = [
        _semantic_runtime_state(
            "STATE_ENTRY",
            FP_MIRROR_ENTRY,
            pathname="/mercurio/inicioMercurio.html",
            functional_state="MERCURIO_INICIO",
        ),
        _semantic_runtime_state(
            "STATE_REVISIT",
            FP_MIRROR_REVISIT,
            pathname="/mercurio/inicioMercurio.html",
            functional_state="MERCURIO_INICIO",
        ),
        _semantic_runtime_state(
            "STATE_TARGET",
            FP_MIRROR_TARGET,
            pathname="/mercurio/modoAcceso.html",
        ),
    ]

    payload = build_navigation_runtime_payload(
        transitions,
        runtime_states,
    )

    assert payload["transition_count"] == 2

    own = outgoing_navigation_transitions(
        payload,
        "STATE_REVISIT",
    )

    assert len(own) == 1
    assert own[0]["interactive_execution_mode"] == "DETERMINISTIC"
    assert own[0]["after_state_id"] == "STATE_TARGET"

    mirrored = outgoing_navigation_transitions(
        payload,
        "STATE_ENTRY",
    )

    assert len(mirrored) == 1
    assert (
        mirrored[0]["interactive_execution_mode"]
        == AUTO_TWIN_NAVIGATION_RUNTIME_SEMANTIC_SOURCE_MIRROR_MODE
    )
    assert mirrored[0]["after_state_id"] == "STATE_TARGET"
    assert (
        mirrored[0]["target_runtime_entry"]
        == "states/STATE_TARGET/runtime/index.html"
    )
    assert mirrored[0]["semantic_source_state_id"] == "STATE_REVISIT"
    assert mirrored[0]["before_fingerprint"] == FP_MIRROR_ENTRY


def test_sibling_own_evidence_is_never_overridden_by_a_mirror():
    """B. A sibling that carries its OWN directly-observed route for the
    exact same action keeps that route untouched -- a mirror is never
    written over real evidence."""

    transitions = _semantic_transitions(
        _store_candidate(
            candidate_id="cand-revisit-continuar",
            before=FP_MIRROR_REVISIT,
            after=FP_MIRROR_TARGET,
            selector=MIRROR_SELECTOR,
        ),
        _store_candidate(
            candidate_id="cand-entry-own-continuar",
            before=FP_MIRROR_ENTRY,
            after=FP_MIRROR_TARGET_2,
            selector=MIRROR_SELECTOR,
        ),
    )

    runtime_states = [
        _semantic_runtime_state(
            "STATE_ENTRY",
            FP_MIRROR_ENTRY,
            pathname="/mercurio/inicioMercurio.html",
            functional_state="MERCURIO_INICIO",
        ),
        _semantic_runtime_state(
            "STATE_REVISIT",
            FP_MIRROR_REVISIT,
            pathname="/mercurio/inicioMercurio.html",
            functional_state="MERCURIO_INICIO",
        ),
        _semantic_runtime_state(
            "STATE_TARGET",
            FP_MIRROR_TARGET,
            pathname="/mercurio/modoAcceso.html",
        ),
        _semantic_runtime_state(
            "STATE_TARGET_2",
            FP_MIRROR_TARGET_2,
            pathname="/mercurio/otraRuta.html",
        ),
    ]

    payload = build_navigation_runtime_payload(
        transitions,
        runtime_states,
    )

    assert payload["transition_count"] == 2

    entry_outgoing = outgoing_navigation_transitions(
        payload,
        "STATE_ENTRY",
    )

    assert len(entry_outgoing) == 1
    assert entry_outgoing[0]["interactive_execution_mode"] == "DETERMINISTIC"
    assert entry_outgoing[0]["after_state_id"] == "STATE_TARGET_2"


def test_entry_state_without_sibling_evidence_invents_nothing():
    """E. No sibling capture carries any outgoing evidence: the entry
    state's own click remains without a route, and nothing is
    invented."""

    runtime_states = [
        _semantic_runtime_state(
            "STATE_ENTRY",
            FP_MIRROR_ENTRY,
            pathname="/mercurio/inicioMercurio.html",
            functional_state="MERCURIO_INICIO",
        ),
        _semantic_runtime_state(
            "STATE_UNRELATED",
            FP_MIRROR_TARGET,
            pathname="/mercurio/modoAcceso.html",
        ),
    ]

    payload = build_navigation_runtime_payload(
        (),
        runtime_states,
    )

    assert payload["transition_count"] == 0
    assert (
        outgoing_navigation_transitions(
            payload,
            "STATE_ENTRY",
        )
        == ()
    )


def test_conflicting_sibling_mirrors_fail_closed():
    """Two siblings with their OWN evidence disagreeing on the target of
    the SAME action must never let a third, evidence-less sibling
    silently pick one: mirroring fails closed exactly like any other
    directly-observed ambiguity."""

    transitions = _semantic_transitions(
        _store_candidate(
            candidate_id="cand-revisit-one",
            before=FP_MIRROR_REVISIT,
            after=FP_MIRROR_TARGET,
            selector=MIRROR_SELECTOR,
        ),
        _store_candidate(
            candidate_id="cand-revisit-two",
            before=FP_MIRROR_REVISIT_2,
            after=FP_MIRROR_TARGET_2,
            selector=MIRROR_SELECTOR,
        ),
    )

    runtime_states = [
        _semantic_runtime_state(
            "STATE_ENTRY",
            FP_MIRROR_ENTRY,
            pathname="/mercurio/inicioMercurio.html",
            functional_state="MERCURIO_INICIO",
        ),
        _semantic_runtime_state(
            "STATE_REVISIT",
            FP_MIRROR_REVISIT,
            pathname="/mercurio/inicioMercurio.html",
            functional_state="MERCURIO_INICIO",
        ),
        _semantic_runtime_state(
            "STATE_REVISIT_2",
            FP_MIRROR_REVISIT_2,
            pathname="/mercurio/inicioMercurio.html",
            functional_state="MERCURIO_INICIO",
        ),
        _semantic_runtime_state(
            "STATE_TARGET",
            FP_MIRROR_TARGET,
            pathname="/mercurio/modoAcceso.html",
        ),
        _semantic_runtime_state(
            "STATE_TARGET_2",
            FP_MIRROR_TARGET_2,
            pathname="/mercurio/otraRuta.html",
        ),
    ]

    with pytest.raises(ValueError):
        build_navigation_runtime_payload(
            transitions,
            runtime_states,
        )


def test_pathname_only_match_without_a_positive_classifier_never_mirrors():
    """Sharing a bare pathname, with every other identity field absent
    (unclassified), is NOT proof of governed identity: a single URL
    commonly carries several genuinely distinct physical steps (e.g. a
    progressively-revealed multi-step form). Mirroring must stay
    fail-closed here, including never mirroring a route back onto its
    own after_state as a bogus self-loop."""

    transitions = _semantic_transitions(
        _store_candidate(
            candidate_id="cand-step-a-to-b",
            before=FP_MIRROR_REVISIT,
            after=FP_MIRROR_TARGET,
            selector=MIRROR_SELECTOR,
        ),
    )

    runtime_states = [
        _semantic_runtime_state(
            "STATE_STEP_UNRELATED",
            FP_MIRROR_ENTRY,
            pathname="/mercurio/nuevaSolicitud-EX00.html",
            functional_state=None,
        ),
        _semantic_runtime_state(
            "STATE_STEP_SOURCE",
            FP_MIRROR_REVISIT,
            pathname="/mercurio/nuevaSolicitud-EX00.html",
            functional_state=None,
        ),
        _semantic_runtime_state(
            "STATE_STEP_TARGET",
            FP_MIRROR_TARGET,
            pathname="/mercurio/nuevaSolicitud-EX00.html",
            functional_state=None,
        ),
    ]

    payload = build_navigation_runtime_payload(
        transitions,
        runtime_states,
    )

    assert payload["transition_count"] == 1

    own = outgoing_navigation_transitions(
        payload,
        "STATE_STEP_SOURCE",
    )

    assert len(own) == 1
    assert own[0]["after_state_id"] == "STATE_STEP_TARGET"

    assert (
        outgoing_navigation_transitions(
            payload,
            "STATE_STEP_UNRELATED",
        )
        == ()
    )

    # No bogus self-loop mirrored onto the route's own target either.
    assert (
        outgoing_navigation_transitions(
            payload,
            "STATE_STEP_TARGET",
        )
        == ()
    )
