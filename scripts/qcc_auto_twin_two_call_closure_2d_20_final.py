"""WO 2D-20 FINAL: fixed-point two-call materialization closure.

Project Direction has authorized the reconciler's documented
QCC_AUTO_TWIN_FIXED_POINT_CLOSURE_V1 two-call pattern (see
backend/qcc/auto_twin/automatic_materialization.py:1746-1759 and
backend/qcc/bridge/server.py:724-738) and clarified that "at most one
new revision" applies PER call, not to the whole closure.

CALL 1 (previous_revision_id=matrev-1586425db7664a40678bfa82, PINNED):
materializes the CURRENT capability-aware EX01_PERSONAL[TITULAR] and
EX01_PERSONAL[FAMILIAR] replacement states (already recorded by 2D-20K
observation + corroborated by 2D-20S provenance) into a new revision.
Their transitions cannot be materialized in this same call -- the
reconciler's own conservative rule requires both transition endpoints
to already exist in the PINNED base revision, and they do not yet.

Independent gate: CALL 1's revision is inspected from disk before
CALL 2 is even considered. Any invariant failure stops here.

CALL 2 (previous_revision_id=<CALL 1's new revision>, PINNED):
now that TITULAR/FAMILIAR physically exist in the (explicitly pinned)
latest revision, the AUTHORIZATION->TITULAR/FAMILIAR transitions
become materializable, resolved via the SAME candidates already
rebound by the 2D-20R/2D-20S contextual supersession corroboration
path inside reconcile_auto_twin_discovery_materialization().

Exactly two calls. No third call under any circumstance. Does not
modify source, tests, raw captures, navigation candidates/events,
observation/supersession data, or any prior revision.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from backend.qcc.auto_twin.automatic_materialization import (  # noqa: E402
    reconcile_auto_twin_discovery_materialization,
)
from backend.qcc.auto_twin.managed_site_store import (  # noqa: E402
    AutoTwinManagedSiteStore,
)
from backend.qcc.auto_twin.materialized_revision_store import (  # noqa: E402
    DEFAULT_AUTO_TWIN_MATERIALIZED_ROOT,
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

LEGACY_STATE_ID = "AUTO_DB042CDED188D6A7A948F28C"


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

    print("=== BEFORE ===")
    print("pinned base revision:", PINNED_BASE_REVISION_ID)
    print(
        "mercurio materialized revision-directory count:",
        len(before_revision_dirs),
    )

    observation_store = AutoTwinObservationStore()
    managed_site_store = AutoTwinManagedSiteStore()
    human_navigation_candidate_store = HumanNavigationCandidateStore()

    # -----------------------------------------------------------
    # CALL 1: materialize CURRENT replacement states, pinned to the
    # ORIGINAL authorized base.
    # -----------------------------------------------------------
    print("\n=== CALL 1 (PINNED to original base) ===")
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
        # It is fine for the legacy state_id to still be ABSENT --
        # required check is that it is not a CURRENT state. Its
        # presence here would mean the carry-forward path resurrected
        # the superseded legacy identity, which must never happen.
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

    for state_id in state_ids1:
        if state_id == AUTHORIZATION_STATE_ID:
            continue

        state_json = _state_fingerprint(call1_revision_id, state_id)
        fingerprint_to_state_id[state_json.get("fingerprint")] = state_id

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

    print("AUTHORIZATION state_id:", AUTHORIZATION_STATE_ID, "OK")
    print(
        "AUTHORIZATION fingerprint:",
        auth_state.get("fingerprint"),
        "OK",
    )
    print("TITULAR state_id:", titular_state_id, "fp OK")
    print("FAMILIAR state_id:", familiar_state_id, "fp OK")
    print("legacy fingerprint absent from CURRENT (CALL 1 revision): OK")

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

    print("\n=== SUMMARY ===")
    print("original pinned base:", PINNED_BASE_REVISION_ID)
    print("CALL 1 revision_id:", call1_revision_id)
    print("CALL 1 state_count:", call1.get("state_count"))
    print("CALL 2 revision_id:", call2_revision_id)
    print("CALL 2 state_count:", call2.get("state_count"))
    print("CALL 2 base_revision_id (must equal CALL 1):",
          call2.get("base_revision_id"))
    print(
        "mercurio materialized revision-directory count before/after:",
        len(before_revision_dirs),
        "/",
        len(after_call2_revision_dirs),
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
