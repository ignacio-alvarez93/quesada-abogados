"""WO 2D-20 FINAL (post-2D-20V): fixed-point two-call materialization
closure.

Re-attempt of the authorized two-call closure now that 2D-20V has
fixed persisted_capture_bundle.py to project a canonical, provider/
capability-aware CURRENT fingerprint (delegating to the exact same
apply_mercurio_functional_fingerprint_capability() observation
ingestion already uses) instead of the raw, pre-2D-20H generic value
that collapsed TITULAR and FAMILIAR onto the same fingerprint in
matrev-684fc2abc9bbea4402bd0261.

This script:

1. Verifies no invariant has drifted since the end of 2D-20V (revision
   count, observation state) before writing anything, and confirms all
   FOUR known non-conforming revisions are present and will never be
   selected as a base.
2. Independently reproduces (read-only, using the exact same public
   functions the reconciler itself calls) which evidence source
   _new_state_navigation_source() will select for the real TITULAR
   state, to prove CAUSAL_BASELINE_FALLBACK ahead of CALL 1.
3. Executes CALL 1 (PINNED to matrev-1586425db7664a40678bfa82),
   independently inspects the resulting revision from disk -- including
   cross-checking the materialized fingerprints against the
   observation store's own CURRENT fingerprints -- and stops before any
   further write if any invariant fails.
4. Executes CALL 2 (PINNED to CALL 1's own new revision) only if CALL
   1 passed every gate, and independently verifies the resulting
   CONTEXTUAL_RESOLVED transition closure from disk.

Exactly two reconciliation calls, never three. Never falls back to any
of the four known non-conforming revisions. Does not modify source,
tests, raw captures, navigation candidates/events, observation/
supersession data, or any prior revision.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from backend.qcc.auto_twin.automatic_materialization import (  # noqa: E402
    _new_state_navigation_source,
    reconcile_auto_twin_discovery_materialization,
)
from backend.qcc.auto_twin.managed_site_store import (  # noqa: E402
    AutoTwinManagedSiteStore,
)
from backend.qcc.auto_twin.materialized_revision_store import (  # noqa: E402
    DEFAULT_AUTO_TWIN_MATERIALIZED_ROOT,
)
from backend.qcc.auto_twin.navigation_transition_materialization import (  # noqa: E402
    project_twin_eligible_navigation_candidates,
    rebind_contextual_supersession_navigation_targets,
)
from backend.qcc.auto_twin.observation_store import (  # noqa: E402
    AutoTwinObservationStore,
)
from backend.qcc.navigation_learning.human_candidate_store import (  # noqa: E402
    HumanNavigationCandidateStore,
)


CAPTURE_ROOT = REPO_ROOT / "data" / "qcc" / "site_architecture"
MATERIALIZED_ROOT = DEFAULT_AUTO_TWIN_MATERIALIZED_ROOT

PINNED_BASE_REVISION_ID = "matrev-1586425db7664a40678bfa82"

TRIGGER_CAPTURE_ID = "20260912_060635_832343_986fda4c"

OLD_COLLIDED_STATE_KEY = (
    "db042cded188d6a7a948f28c9c52681c3eaef8efc02d3eac5a7f4467bb14eb87"
)
OLD_COLLIDED_FINGERPRINT = (
    "d0af84caa02f93f585f9df7f3e2ef82b487348a64550e07c54f481e58e84e2f4"
)

AUTHORIZATION_STATE_ID = "AUTO_46D7EFFD1132808AA1B6B5AF"
AUTHORIZATION_FINGERPRINT = (
    "0f048a41feded5af2ceae831e57bf6c1d79d3d86ccfe991c698a5b21e3e7aca2"
)

TITULAR_FINGERPRINT = (
    "52efb715d5688ad10cb2945d862847868ce25b4208f6ca84dcf57aa8a4032311"
)
FAMILIAR_FINGERPRINT = (
    "88c730539a17c84d7c3ac6fb753c7ba40a7489289f7d0c950d815f3aa568ae38"
)

TITULAR_INCOMPLETE_LAST_CAPTURE_ID = "20260912_060228_192874_aa602bac"
TITULAR_BASELINE_CAPTURE_ID = "20260912_060218_754542_25a0d363"

LEGACY_STATE_ID = "AUTO_DB042CDED188D6A7A948F28C"

NON_CONFORMING_REVISION_IDS = {
    "matrev-0737ace5e5dc6fef1dbd982d",
    "matrev-e913839c49ad1ebf87f8b505",
    "matrev-ceafd8162d0e4eeb5f08cb62",
    "matrev-684fc2abc9bbea4402bd0261",
}

# Initial invariants asserted at the end of 2D-20V.
EXPECTED_INITIAL_REVISION_DIR_COUNT = 192
EXPECTED_FINAL_REVISION_DIR_COUNT = 194
EXPECTED_INITIAL_OBSERVATION_REVISION = 402
EXPECTED_INITIAL_STATE_COUNT = 23
EXPECTED_INITIAL_SUPERSESSION_COUNT = 1


def _mercurio_revision_dirs():
    root = MATERIALIZED_ROOT / "mercurio"
    return {p.name for p in root.iterdir() if p.is_dir()}


def _revision_dir(revision_id):
    return MATERIALIZED_ROOT / "mercurio" / revision_id


def _manifest(revision_id):
    path = _revision_dir(revision_id) / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _state_fingerprint(revision_id, state_id):
    revision_dir = _revision_dir(revision_id)

    matches = list(revision_dir.glob(f"states/*-{state_id}"))

    if len(matches) != 1:
        raise SystemExit(
            f"BLOCKED: expected exactly one states/ dir for "
            f"{state_id} in {revision_id}, found {len(matches)}"
        )

    state_json = json.loads(
        (matches[0] / "runtime" / "state.json").read_text(
            encoding="utf-8"
        )
    )

    return state_json


def _navigation_transitions(revision_id):
    path = (
        _revision_dir(revision_id)
        / "runtime"
        / "navigation_transitions.json"
    )

    if not path.exists():
        return None

    return json.loads(path.read_text(encoding="utf-8"))


def _reconcile(observation_store, managed_site_store, human_store, *,
               previous_revision_id):
    return reconcile_auto_twin_discovery_materialization(
        managed_site_store=managed_site_store,
        observation_store=observation_store,
        capture_root=CAPTURE_ROOT,
        trigger_capture_id=TRIGGER_CAPTURE_ID,
        twin_key="mercurio",
        previous_revision_id=previous_revision_id,
        human_navigation_candidate_store=human_store,
    )


def main() -> int:
    before_revision_dirs = _mercurio_revision_dirs()

    print("=== INITIAL INVARIANT CHECK (must match end of 2D-20V) ===")
    print(
        "mercurio materialized revision-directory count:",
        len(before_revision_dirs),
        "expected:",
        EXPECTED_INITIAL_REVISION_DIR_COUNT,
    )

    if len(before_revision_dirs) != EXPECTED_INITIAL_REVISION_DIR_COUNT:
        raise SystemExit(
            "PASS2_BLOCKED_INITIAL_REVISION_COUNT_DRIFTED: "
            f"got {len(before_revision_dirs)}, expected "
            f"{EXPECTED_INITIAL_REVISION_DIR_COUNT}"
        )

    missing_non_conforming = [
        rid
        for rid in NON_CONFORMING_REVISION_IDS
        if rid not in before_revision_dirs
    ]

    if missing_non_conforming:
        raise SystemExit(
            "PASS2_BLOCKED_EXPECTED_NON_CONFORMING_REVISION_MISSING: "
            f"{sorted(missing_non_conforming)!r}"
        )

    print(
        "all 4 known non-conforming revisions present (never to be "
        "used as base):",
        sorted(NON_CONFORMING_REVISION_IDS),
    )

    observation_store = AutoTwinObservationStore()
    managed_site_store = AutoTwinManagedSiteStore()
    human_navigation_candidate_store = HumanNavigationCandidateStore()

    before_snapshot = observation_store.snapshot("mercurio")
    before_states = before_snapshot["twin"]["states"]
    before_supersessions = before_snapshot["twin"]["supersessions"]

    print("observation store revision:", observation_store.revision)
    print("observation state count:", len(before_states))
    print("observation supersession count:", len(before_supersessions))

    if observation_store.revision != EXPECTED_INITIAL_OBSERVATION_REVISION:
        raise SystemExit(
            "PASS2_BLOCKED_INITIAL_OBSERVATION_REVISION_DRIFTED: "
            f"got {observation_store.revision}, expected "
            f"{EXPECTED_INITIAL_OBSERVATION_REVISION}"
        )

    if len(before_states) != EXPECTED_INITIAL_STATE_COUNT:
        raise SystemExit(
            "PASS2_BLOCKED_INITIAL_STATE_COUNT_DRIFTED: "
            f"got {len(before_states)}"
        )

    if len(before_supersessions) != EXPECTED_INITIAL_SUPERSESSION_COUNT:
        raise SystemExit(
            "PASS2_BLOCKED_INITIAL_SUPERSESSION_COUNT_DRIFTED: "
            f"got {len(before_supersessions)}"
        )

    print("initial invariants OK -- unchanged since end of 2D-20V.\n")

    # -----------------------------------------------------------
    # Independent pre-flight proof: reproduce, read-only, exactly
    # which evidence source _new_state_navigation_source() will pick
    # for the real TITULAR state, using the exact same public
    # functions the reconciler itself calls internally.
    # -----------------------------------------------------------
    print("=== PRE-FLIGHT: independent CAUSAL_BASELINE_FALLBACK proof ===")

    current_states = observation_store.snapshot(
        "mercurio", current_only=True
    )["twin"]["states"]

    titular_state_key = None
    titular_state = None
    familiar_state_key = None
    authorization_state_key = None

    for key, state in current_states.items():
        if (
            state.get("functional_state") == "EX01_PERSONAL"
            and state.get("state_variant_key") == "NO_FAMILIAR_TAB"
        ):
            titular_state_key = key
            titular_state = state

        if (
            state.get("functional_state") == "EX01_PERSONAL"
            and state.get("state_variant_key")
            == "FAMILIAR_TAB_AVAILABLE"
        ):
            familiar_state_key = key

        if state.get("functional_state") == "EX01_AUTHORIZATION":
            authorization_state_key = key

    if titular_state is None:
        raise SystemExit(
            "PASS2_BLOCKED_PREFLIGHT_TITULAR_STATE_NOT_FOUND"
        )

    if familiar_state_key is None:
        raise SystemExit(
            "PASS2_BLOCKED_PREFLIGHT_FAMILIAR_STATE_NOT_FOUND"
        )

    if authorization_state_key is None:
        raise SystemExit(
            "PASS2_BLOCKED_PREFLIGHT_AUTHORIZATION_STATE_NOT_FOUND"
        )

    print("TITULAR state_key:", titular_state_key)
    print(
        "TITULAR last_capture_id (recorded, incomplete):",
        titular_state.get("last_capture_id"),
    )
    print(
        "TITULAR baseline_capture_id (recorded):",
        titular_state.get("baseline_capture_id"),
    )
    print("FAMILIAR state_key:", familiar_state_key)
    print("AUTHORIZATION state_key:", authorization_state_key)

    observation_current_fingerprints = {
        "AUTHORIZATION": current_states[authorization_state_key].get(
            "last_fingerprint"
        ),
        "TITULAR": current_states[titular_state_key].get(
            "last_fingerprint"
        ),
        "FAMILIAR": current_states[familiar_state_key].get(
            "last_fingerprint"
        ),
    }

    print(
        "observation CURRENT fingerprints:",
        observation_current_fingerprints,
    )

    incomplete = [
        name
        for name in ("page.mhtml", "screenshot_viewport.png")
        if not (
            CAPTURE_ROOT
            / TITULAR_INCOMPLETE_LAST_CAPTURE_ID
            / name
        ).is_file()
    ]

    print(
        "confirmed missing artifacts on recorded last_capture_id:",
        incomplete,
    )

    candidate_snapshot = human_navigation_candidate_store.snapshot(
        "MERCURIO", environment="REAL"
    )

    projected = project_twin_eligible_navigation_candidates(
        candidate_snapshot
    )

    historical_states = observation_store.snapshot("mercurio")[
        "twin"
    ]["states"]

    twin_supersessions = observation_store.snapshot("mercurio")[
        "twin"
    ]["supersessions"]

    rebound = rebind_contextual_supersession_navigation_targets(
        projected,
        twin_supersessions=twin_supersessions,
        historical_states=historical_states,
        current_states=current_states,
    )

    preflight_capture_id, preflight_evidence_kind = (
        _new_state_navigation_source(
            titular_state,
            rebound,
            capture_root=CAPTURE_ROOT,
            expected_site_code="MERCURIO",
        )
    )

    print(
        "independently reproduced selection for TITULAR: "
        f"capture_id={preflight_capture_id!r} "
        f"source_reason={preflight_evidence_kind!r}"
    )

    if preflight_evidence_kind != "CAUSAL_BASELINE_FALLBACK":
        raise SystemExit(
            "PASS2_BLOCKED_PREFLIGHT_SOURCE_REASON_NOT_"
            f"CAUSAL_BASELINE_FALLBACK: got {preflight_evidence_kind!r}"
        )

    if preflight_capture_id != TITULAR_BASELINE_CAPTURE_ID:
        raise SystemExit(
            "PASS2_BLOCKED_PREFLIGHT_UNEXPECTED_CAPTURE_ID: "
            f"got {preflight_capture_id!r}"
        )

    print(
        "pre-flight proof OK: TITULAR will be sourced from "
        f"{preflight_capture_id!r} via CAUSAL_BASELINE_FALLBACK.\n"
    )

    # -----------------------------------------------------------
    # CALL 1: materialize CURRENT replacement states, pinned to the
    # ORIGINAL authorized base.
    # -----------------------------------------------------------
    print("=== CALL 1 (PINNED to original base) ===")
    call1 = _reconcile(
        observation_store,
        managed_site_store,
        human_navigation_candidate_store,
        previous_revision_id=PINNED_BASE_REVISION_ID,
    )
    print(json.dumps(call1, indent=2, ensure_ascii=False, default=str))

    if call1.get("previous_revision_selection_mode") != "PINNED":
        raise SystemExit(
            "PASS2_BLOCKED_CALL1_SELECTION_MODE_NOT_PINNED"
        )

    if call1.get("base_revision_id") != PINNED_BASE_REVISION_ID:
        raise SystemExit(
            "PASS2_BLOCKED_CALL1_BASE_REVISION_MISMATCH: "
            f"got {call1.get('base_revision_id')!r}"
        )

    if call1.get("status") != "MATERIALIZED":
        raise SystemExit(
            "PASS2_BLOCKED_CALL1_NOT_MATERIALIZED: "
            f"status={call1.get('status')!r} "
            f"reason={call1.get('reason')!r}"
        )

    call1_revision_id = call1.get("materialized_revision_id")

    if not call1_revision_id:
        raise SystemExit(
            "PASS2_BLOCKED_CALL1_REVISION_ID_MISSING"
        )

    if call1_revision_id in NON_CONFORMING_REVISION_IDS:
        raise SystemExit(
            "PASS2_BLOCKED_CALL1_FELL_BACK_TO_NON_CONFORMING_REVISION: "
            f"{call1_revision_id}"
        )

    after_call1_revision_dirs = _mercurio_revision_dirs()
    new_after_call1 = after_call1_revision_dirs - before_revision_dirs

    if new_after_call1 != {call1_revision_id}:
        raise SystemExit(
            "PASS2_BLOCKED_CALL1_UNEXPECTED_REVISION_SET: "
            f"{sorted(new_after_call1)!r}"
        )

    # -----------------------------------------------------------
    # Independent gate: verify CALL 1 from disk BEFORE considering
    # CALL 2 at all.
    # -----------------------------------------------------------
    print(f"\n=== CALL 1 INDEPENDENT VERIFICATION ({call1_revision_id}) ===")

    manifest1 = _manifest(call1_revision_id)
    state_manifest1 = manifest1.get("state_manifest") or []

    state_ids1 = {entry.get("state_id") for entry in state_manifest1}

    print("CALL 1 state count:", len(state_manifest1))
    print("CALL 1 state_ids:", sorted(state_ids1))

    if LEGACY_STATE_ID in state_ids1:
        raise SystemExit(
            "PASS2_BLOCKED_CALL1_LEGACY_STATE_ID_PRESENT"
        )

    if AUTHORIZATION_STATE_ID not in state_ids1:
        raise SystemExit(
            "PASS2_BLOCKED_CALL1_AUTHORIZATION_STATE_MISSING"
        )

    auth_state = _state_fingerprint(
        call1_revision_id, AUTHORIZATION_STATE_ID
    )

    if auth_state.get("fingerprint") != AUTHORIZATION_FINGERPRINT:
        raise SystemExit(
            "PASS2_BLOCKED_CALL1_AUTHORIZATION_FINGERPRINT_MISMATCH: "
            f"got {auth_state.get('fingerprint')!r}"
        )

    fingerprint_to_state_id = {}
    source_capture_by_state_id = {}

    for state_id in state_ids1:
        if state_id == AUTHORIZATION_STATE_ID:
            continue

        state_json = _state_fingerprint(call1_revision_id, state_id)
        fingerprint_to_state_id[state_json.get("fingerprint")] = state_id
        source_capture_by_state_id[state_id] = state_json.get(
            "source_capture_id"
        )

    if OLD_COLLIDED_FINGERPRINT in fingerprint_to_state_id:
        raise SystemExit(
            "PASS2_BLOCKED_CALL1_LEGACY_FINGERPRINT_PRESENT_AS_CURRENT"
        )

    titular_state_id = fingerprint_to_state_id.get(TITULAR_FINGERPRINT)
    familiar_state_id = fingerprint_to_state_id.get(FAMILIAR_FINGERPRINT)

    if not titular_state_id:
        raise SystemExit(
            "PASS2_BLOCKED_CALL1_TITULAR_FINGERPRINT_MISSING"
        )

    if not familiar_state_id:
        raise SystemExit(
            "PASS2_BLOCKED_CALL1_FAMILIAR_FINGERPRINT_MISSING"
        )

    if titular_state_id == familiar_state_id:
        raise SystemExit(
            "PASS2_BLOCKED_CALL1_TITULAR_FAMILIAR_STATE_ID_COLLISION"
        )

    if titular_state_id == LEGACY_STATE_ID or (
        familiar_state_id == LEGACY_STATE_ID
    ):
        raise SystemExit(
            "PASS2_BLOCKED_CALL1_REPLACEMENT_INHERITS_LEGACY_STATE_ID"
        )

    titular_source_capture_id = source_capture_by_state_id.get(
        titular_state_id
    )

    print("AUTHORIZATION state_id:", AUTHORIZATION_STATE_ID, "OK")
    print(
        "AUTHORIZATION fingerprint:",
        auth_state.get("fingerprint"),
        "OK",
    )
    print(
        "TITULAR state_id:",
        titular_state_id,
        "fp OK, source_capture_id=",
        titular_source_capture_id,
    )
    print(
        "FAMILIAR state_id:",
        familiar_state_id,
        "fp OK, source_capture_id=",
        source_capture_by_state_id.get(familiar_state_id),
    )
    print("legacy fingerprint absent from CURRENT (CALL 1 revision): OK")

    if titular_source_capture_id != TITULAR_BASELINE_CAPTURE_ID:
        raise SystemExit(
            "PASS2_BLOCKED_CALL1_TITULAR_SOURCE_CAPTURE_UNEXPECTED: "
            f"got {titular_source_capture_id!r}, expected "
            f"{TITULAR_BASELINE_CAPTURE_ID!r} (CAUSAL_BASELINE_FALLBACK)"
        )

    print(
        "TITULAR materialized from",
        titular_source_capture_id,
        "-- matches the pre-flight-proven CAUSAL_BASELINE_FALLBACK "
        "selection: OK",
    )

    # -----------------------------------------------------------
    # 2D-20V cross-check: materialized/CURRENT fingerprints must agree
    # with the observation store's own CURRENT fingerprints for the
    # SAME state_key/state_id triad.
    # -----------------------------------------------------------
    materialized_fingerprints = {
        "AUTHORIZATION": auth_state.get("fingerprint"),
        "TITULAR": TITULAR_FINGERPRINT,
        "FAMILIAR": FAMILIAR_FINGERPRINT,
    }

    if materialized_fingerprints != observation_current_fingerprints:
        raise SystemExit(
            "PASS2_BLOCKED_CALL1_MATERIALIZED_OBSERVATION_FINGERPRINT_"
            f"MISMATCH: materialized={materialized_fingerprints!r} "
            f"observation={observation_current_fingerprints!r}"
        )

    print(
        "materialized CURRENT fingerprints agree with observation "
        "CURRENT fingerprints (2D-20V canonical path): OK"
    )

    print("\nCALL 1 invariants satisfied -- proceeding to CALL 2.\n")

    # -----------------------------------------------------------
    # CALL 2: materialize newly eligible transitions, pinned to
    # CALL 1's own new revision (never the original base, never
    # default/auto-latest selection).
    # -----------------------------------------------------------
    print("=== CALL 2 (PINNED to CALL 1's new revision) ===")
    call2 = _reconcile(
        observation_store,
        managed_site_store,
        human_navigation_candidate_store,
        previous_revision_id=call1_revision_id,
    )
    print(json.dumps(call2, indent=2, ensure_ascii=False, default=str))

    if call2.get("previous_revision_selection_mode") != "PINNED":
        raise SystemExit(
            "PASS2_BLOCKED_CALL2_SELECTION_MODE_NOT_PINNED"
        )

    if call2.get("base_revision_id") != call1_revision_id:
        raise SystemExit(
            "PASS2_BLOCKED_CALL2_BASE_REVISION_NOT_CALL1: "
            f"got {call2.get('base_revision_id')!r}, "
            f"expected {call1_revision_id!r}"
        )

    if call2.get("status") != "MATERIALIZED":
        raise SystemExit(
            "PASS2_BLOCKED_CALL2_NOT_MATERIALIZED: "
            f"status={call2.get('status')!r} "
            f"reason={call2.get('reason')!r}"
        )

    call2_revision_id = call2.get("materialized_revision_id")

    if not call2_revision_id or call2_revision_id == call1_revision_id:
        raise SystemExit(
            "PASS2_BLOCKED_CALL2_REVISION_ID_INVALID"
        )

    if call2_revision_id in NON_CONFORMING_REVISION_IDS:
        raise SystemExit(
            "PASS2_BLOCKED_CALL2_FELL_BACK_TO_NON_CONFORMING_REVISION: "
            f"{call2_revision_id}"
        )

    after_call2_revision_dirs = _mercurio_revision_dirs()
    new_after_call2 = after_call2_revision_dirs - after_call1_revision_dirs

    if new_after_call2 != {call2_revision_id}:
        raise SystemExit(
            "PASS2_BLOCKED_CALL2_UNEXPECTED_REVISION_SET: "
            f"{sorted(new_after_call2)!r}"
        )

    # -----------------------------------------------------------
    # Independent verification of CALL 2 from disk.
    # -----------------------------------------------------------
    print(f"\n=== CALL 2 INDEPENDENT VERIFICATION ({call2_revision_id}) ===")

    manifest2 = _manifest(call2_revision_id)
    state_manifest2 = manifest2.get("state_manifest") or []
    state_ids2 = {entry.get("state_id") for entry in state_manifest2}

    print("CALL 2 state count:", len(state_manifest2))

    if LEGACY_STATE_ID in state_ids2:
        raise SystemExit(
            "PASS2_BLOCKED_CALL2_LEGACY_STATE_ID_PRESENT"
        )

    for state_id in (titular_state_id, familiar_state_id):
        if state_id not in state_ids2:
            raise SystemExit(
                "PASS2_BLOCKED_CALL2_REPLACEMENT_STATE_MISSING: "
                f"{state_id}"
            )

    nav = _navigation_transitions(call2_revision_id)

    if nav is None:
        raise SystemExit(
            "PASS2_BLOCKED_CALL2_NAVIGATION_TRANSITIONS_FILE_MISSING"
        )

    transitions = nav.get("transitions") or []

    authorization_group_transitions = [
        t
        for t in transitions
        if t.get("before_fingerprint") == AUTHORIZATION_FINGERPRINT
        and t.get("after_fingerprint")
        in (TITULAR_FINGERPRINT, FAMILIAR_FINGERPRINT)
    ]

    print(
        "AUTHORIZATION-sourced transitions targeting "
        "TITULAR/FAMILIAR:",
        len(authorization_group_transitions),
    )
    print(
        json.dumps(
            authorization_group_transitions,
            indent=2,
            ensure_ascii=False,
        )
    )

    if len(authorization_group_transitions) != 2:
        raise SystemExit(
            "PASS2_BLOCKED_CALL2_TRANSITION_COUNT_UNEXPECTED: "
            f"{len(authorization_group_transitions)}"
        )

    outcome_modes = {
        t.get("outcome_mode") for t in authorization_group_transitions
    }

    if outcome_modes != {"CONTEXTUAL_RESOLVED"}:
        raise SystemExit(
            "PASS2_BLOCKED_CALL2_OUTCOME_MODE_NOT_CONTEXTUAL_RESOLVED: "
            f"{outcome_modes!r}"
        )

    targeted_fingerprints = {
        t.get("after_fingerprint")
        for t in authorization_group_transitions
    }

    if targeted_fingerprints != {TITULAR_FINGERPRINT, FAMILIAR_FINGERPRINT}:
        raise SystemExit(
            "PASS2_BLOCKED_CALL2_TARGET_FINGERPRINTS_UNEXPECTED: "
            f"{targeted_fingerprints!r}"
        )

    legacy_still_targeted = any(
        t.get("after_fingerprint") == OLD_COLLIDED_FINGERPRINT
        for t in transitions
    )

    if legacy_still_targeted:
        raise SystemExit(
            "PASS2_BLOCKED_CALL2_LEGACY_FINGERPRINT_STILL_TARGETED"
        )

    print("outcome_mode CONTEXTUAL_RESOLVED for both branches: OK")
    print("legacy fingerprint absent from CALL 2 transitions: OK")

    # -----------------------------------------------------------
    # Final CURRENT-view proof (observation store, independent of
    # the materialized-revision files above).
    # -----------------------------------------------------------
    final_current = observation_store.snapshot(
        "mercurio",
        current_only=True,
    )["twin"]["states"]

    if OLD_COLLIDED_STATE_KEY in final_current:
        raise SystemExit(
            "PASS2_BLOCKED_LEGACY_STATE_KEY_STILL_CURRENT_IN_OBSERVATION"
        )

    final_historical = observation_store.snapshot("mercurio")[
        "twin"
    ]["states"]

    if OLD_COLLIDED_STATE_KEY not in final_historical:
        raise SystemExit(
            "PASS2_BLOCKED_LEGACY_STATE_KEY_NO_LONGER_HISTORICALLY_"
            "READABLE"
        )

    print(
        "\nlegacy state_key absent from CURRENT observation view, "
        "still historically readable: OK"
    )

    final_revision_dirs = after_call2_revision_dirs

    if len(final_revision_dirs) != EXPECTED_FINAL_REVISION_DIR_COUNT:
        raise SystemExit(
            "PASS2_BLOCKED_FINAL_REVISION_COUNT_UNEXPECTED: "
            f"got {len(final_revision_dirs)}, expected "
            f"{EXPECTED_FINAL_REVISION_DIR_COUNT}"
        )

    print("\n=== SUMMARY ===")
    print("starting revision-directory count:", len(before_revision_dirs))
    print("original pinned base:", PINNED_BASE_REVISION_ID)
    print("CALL 1 revision_id:", call1_revision_id)
    print("CALL 1 base_revision_id:", call1.get("base_revision_id"))
    print(
        "CALL 1 previous_revision_selection_mode:",
        call1.get("previous_revision_selection_mode"),
    )
    print("CALL 1 state_count:", call1.get("state_count"))
    print("AUTHORIZATION state_id/fingerprint:", AUTHORIZATION_STATE_ID,
          auth_state.get("fingerprint"))
    print("TITULAR state_id/fingerprint/source_reason:", titular_state_id,
          TITULAR_FINGERPRINT, "CAUSAL_BASELINE_FALLBACK")
    print("FAMILIAR state_id/fingerprint:", familiar_state_id,
          FAMILIAR_FINGERPRINT)
    print("TITULAR source_capture_id:", titular_source_capture_id)
    print("CALL 2 revision_id:", call2_revision_id)
    print("CALL 2 base_revision_id (must equal CALL 1):",
          call2.get("base_revision_id"))
    print(
        "CALL 2 previous_revision_selection_mode:",
        call2.get("previous_revision_selection_mode"),
    )
    print("CALL 2 state_count:", call2.get("state_count"))
    print(
        "mercurio materialized revision-directory count before/after:",
        len(before_revision_dirs),
        "/",
        len(final_revision_dirs),
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
