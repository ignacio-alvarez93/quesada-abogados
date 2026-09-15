"""WO 2D-20 FINAL: CALL 2 only, pinned to the 2D-20W-audited CALL-1
revision matrev-d1205abd0e4e762b2c3a297e.

2D-20W independently proved this revision REUSABLE_CALL1_BASE. This
script does NOT create or recreate CALL 1. It executes exactly one
further reconciliation/materialization call, pinned to that exact
revision, to close the AUTHORIZATION->TITULAR/FAMILIAR transitions via
2D-20R/2D-20S contextual 1->N supersession evidence, now that 2D-20W
has made catalog refresh variant-aware so it no longer crashes on the
governed EX01_PERSONAL 1->N family.

Exactly one reconciliation call. Does not modify source, tests, raw
captures, navigation candidates/events, observation/supersession data,
or any prior revision.
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

CALL1_REVISION_ID = "matrev-d1205abd0e4e762b2c3a297e"
EXPECTED_CALL1_CONTENT_SHA256 = (
    "ca0a0c97a0dfcb624a1c610eb24a75005ed59ad7fda6ed46e3810a92d208a176"
)

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

TITULAR_STATE_ID = "AUTO_D70C0C4AF299B13FCE228BDF"
TITULAR_FINGERPRINT = (
    "52efb715d5688ad10cb2945d862847868ce25b4208f6ca84dcf57aa8a4032311"
)
FAMILIAR_STATE_ID = "AUTO_16010CB127944DEE64B99B89"
FAMILIAR_FINGERPRINT = (
    "88c730539a17c84d7c3ac6fb753c7ba40a7489289f7d0c950d815f3aa568ae38"
)

LEGACY_STATE_ID = "AUTO_DB042CDED188D6A7A948F28C"

NON_CONFORMING_REVISION_IDS = {
    "matrev-0737ace5e5dc6fef1dbd982d",
    "matrev-e913839c49ad1ebf87f8b505",
    "matrev-ceafd8162d0e4eeb5f08cb62",
    "matrev-684fc2abc9bbea4402bd0261",
}

EXPECTED_INITIAL_REVISION_DIR_COUNT = 193
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

    return json.loads(
        (matches[0] / "runtime" / "state.json").read_text(
            encoding="utf-8"
        )
    )


def _navigation_transitions(revision_id):
    path = (
        _revision_dir(revision_id)
        / "runtime"
        / "navigation_transitions.json"
    )

    if not path.exists():
        return None

    return json.loads(path.read_text(encoding="utf-8"))


def _registry(revision_id):
    path = (
        _revision_dir(revision_id) / "runtime" / "registry.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    before_revision_dirs = _mercurio_revision_dirs()

    print("=== INITIAL INVARIANT CHECK ===")
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

    if CALL1_REVISION_ID not in before_revision_dirs:
        raise SystemExit(
            "PASS2_BLOCKED_CALL1_REVISION_MISSING: "
            f"{CALL1_REVISION_ID}"
        )

    for rid in NON_CONFORMING_REVISION_IDS:
        if rid not in before_revision_dirs:
            raise SystemExit(
                "PASS2_BLOCKED_EXPECTED_NON_CONFORMING_REVISION_"
                f"MISSING: {rid}"
            )

    call1_manifest_before = _manifest(CALL1_REVISION_ID)

    if (
        call1_manifest_before.get("content_sha256")
        != EXPECTED_CALL1_CONTENT_SHA256
    ):
        raise SystemExit(
            "PASS2_BLOCKED_CALL1_REVISION_CONTENT_CHANGED: "
            f"got {call1_manifest_before.get('content_sha256')!r}, "
            f"expected {EXPECTED_CALL1_CONTENT_SHA256!r}"
        )

    print(
        "matrev-d1205abd0e4e762b2c3a297e content_sha256 unchanged "
        "since 2D-20W audit: OK"
    )

    observation_store = AutoTwinObservationStore()
    managed_site_store = AutoTwinManagedSiteStore()
    human_navigation_candidate_store = HumanNavigationCandidateStore()

    before_snapshot = observation_store.snapshot("mercurio")
    before_states = before_snapshot["twin"]["states"]
    before_supersessions = before_snapshot["twin"]["supersessions"]

    print("observation store revision:", observation_store.revision)

    if observation_store.revision != EXPECTED_INITIAL_OBSERVATION_REVISION:
        raise SystemExit(
            "PASS2_BLOCKED_INITIAL_OBSERVATION_REVISION_DRIFTED: "
            f"got {observation_store.revision}"
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

    print("initial invariants OK.\n")

    # -----------------------------------------------------------
    # Re-verify CALL-1 revision's audited invariants still hold,
    # directly from disk, before pinning it as CALL 2's base.
    # -----------------------------------------------------------
    print("=== RE-VERIFY CALL-1 (matrev-d1205abd0e4e762b2c3a297e) ===")

    state_manifest1 = call1_manifest_before.get("state_manifest") or []
    state_ids1 = {e.get("state_id") for e in state_manifest1}

    if LEGACY_STATE_ID in state_ids1:
        raise SystemExit(
            "PASS2_BLOCKED_CALL1_LEGACY_STATE_ID_PRESENT"
        )

    for state_id, expected_fp in (
        (AUTHORIZATION_STATE_ID, AUTHORIZATION_FINGERPRINT),
        (TITULAR_STATE_ID, TITULAR_FINGERPRINT),
        (FAMILIAR_STATE_ID, FAMILIAR_FINGERPRINT),
    ):
        if state_id not in state_ids1:
            raise SystemExit(
                "PASS2_BLOCKED_CALL1_STATE_MISSING: "
                f"{state_id}"
            )

        actual_fp = _state_fingerprint(
            CALL1_REVISION_ID, state_id
        ).get("fingerprint")

        if actual_fp != expected_fp:
            raise SystemExit(
                "PASS2_BLOCKED_CALL1_FINGERPRINT_DRIFTED: "
                f"{state_id} got {actual_fp!r}, expected {expected_fp!r}"
            )

    print("CALL-1 re-verification OK -- proceeding to CALL 2.\n")

    # -----------------------------------------------------------
    # CALL 2: pinned exactly to the audited CALL-1 revision.
    # -----------------------------------------------------------
    print("=== CALL 2 (PINNED to matrev-d1205abd0e4e762b2c3a297e) ===")
    call2 = reconcile_auto_twin_discovery_materialization(
        managed_site_store=managed_site_store,
        observation_store=observation_store,
        capture_root=CAPTURE_ROOT,
        trigger_capture_id=TRIGGER_CAPTURE_ID,
        twin_key="mercurio",
        previous_revision_id=CALL1_REVISION_ID,
        human_navigation_candidate_store=human_navigation_candidate_store,
    )
    print(json.dumps(call2, indent=2, ensure_ascii=False, default=str))

    if call2.get("previous_revision_selection_mode") != "PINNED":
        raise SystemExit(
            "PASS2_BLOCKED_CALL2_SELECTION_MODE_NOT_PINNED"
        )

    if call2.get("base_revision_id") != CALL1_REVISION_ID:
        raise SystemExit(
            "PASS2_BLOCKED_CALL2_BASE_REVISION_NOT_CALL1: "
            f"got {call2.get('base_revision_id')!r}"
        )

    if call2.get("status") != "MATERIALIZED":
        raise SystemExit(
            "PASS2_BLOCKED_CALL2_NOT_MATERIALIZED: "
            f"status={call2.get('status')!r} "
            f"reason={call2.get('reason')!r}"
        )

    call2_revision_id = call2.get("materialized_revision_id")

    if not call2_revision_id or call2_revision_id == CALL1_REVISION_ID:
        raise SystemExit(
            "PASS2_BLOCKED_CALL2_REVISION_ID_INVALID"
        )

    if call2_revision_id in NON_CONFORMING_REVISION_IDS:
        raise SystemExit(
            "PASS2_BLOCKED_CALL2_FELL_BACK_TO_NON_CONFORMING_REVISION: "
            f"{call2_revision_id}"
        )

    after_revision_dirs = _mercurio_revision_dirs()
    new_revisions = after_revision_dirs - before_revision_dirs

    if new_revisions != {call2_revision_id}:
        raise SystemExit(
            "PASS2_BLOCKED_CALL2_UNEXPECTED_REVISION_SET: "
            f"{sorted(new_revisions)!r}"
        )

    if len(after_revision_dirs) != EXPECTED_FINAL_REVISION_DIR_COUNT:
        raise SystemExit(
            "PASS2_BLOCKED_FINAL_REVISION_COUNT_UNEXPECTED: "
            f"got {len(after_revision_dirs)}, expected "
            f"{EXPECTED_FINAL_REVISION_DIR_COUNT}"
        )

    # Prior CALL-1 revision untouched.
    call1_manifest_after = _manifest(CALL1_REVISION_ID)

    if (
        call1_manifest_after.get("content_sha256")
        != EXPECTED_CALL1_CONTENT_SHA256
    ):
        raise SystemExit(
            "PASS2_BLOCKED_CALL1_REVISION_MUTATED_DURING_CALL2"
        )

    # -----------------------------------------------------------
    # Independent verification of CALL 2 from disk.
    # -----------------------------------------------------------
    print(f"\n=== CALL 2 INDEPENDENT VERIFICATION ({call2_revision_id}) ===")

    manifest2 = _manifest(call2_revision_id)
    state_manifest2 = manifest2.get("state_manifest") or []
    state_ids2 = {e.get("state_id") for e in state_manifest2}

    print("CALL 2 final state count:", len(state_manifest2))
    print("CALL 2 state_ids:", sorted(state_ids2))

    if LEGACY_STATE_ID in state_ids2:
        raise SystemExit(
            "PASS2_BLOCKED_CALL2_LEGACY_STATE_ID_PRESENT"
        )

    for state_id, expected_fp in (
        (AUTHORIZATION_STATE_ID, AUTHORIZATION_FINGERPRINT),
        (TITULAR_STATE_ID, TITULAR_FINGERPRINT),
        (FAMILIAR_STATE_ID, FAMILIAR_FINGERPRINT),
    ):
        if state_id not in state_ids2:
            raise SystemExit(
                "PASS2_BLOCKED_CALL2_STATE_MISSING: "
                f"{state_id}"
            )

        actual_fp = _state_fingerprint(
            call2_revision_id, state_id
        ).get("fingerprint")

        if actual_fp != expected_fp:
            raise SystemExit(
                "PASS2_BLOCKED_CALL2_FINGERPRINT_MISMATCH: "
                f"{state_id} got {actual_fp!r}"
            )

    print("AUTHORIZATION/TITULAR/FAMILIAR state_ids+fingerprints: OK")

    # Catalog refresh / registry sanity: both EX01_PERSONAL variants
    # still coexist in the registry with distinct identities (2D-20W).
    registry2 = _registry(call2_revision_id)
    ex01_personal_entries = [
        s
        for s in (registry2.get("states") or [])
        if s.get("functional_state") == "EX01_PERSONAL"
    ]

    print(
        "EX01_PERSONAL registry entries:",
        len(ex01_personal_entries),
    )

    if len(ex01_personal_entries) != 2:
        raise SystemExit(
            "PASS2_BLOCKED_CALL2_EX01_PERSONAL_REGISTRY_COUNT_"
            f"UNEXPECTED: {len(ex01_personal_entries)}"
        )

    registry_state_ids = {
        e.get("state_id") for e in ex01_personal_entries
    }

    if registry_state_ids != {TITULAR_STATE_ID, FAMILIAR_STATE_ID}:
        raise SystemExit(
            "PASS2_BLOCKED_CALL2_EX01_PERSONAL_REGISTRY_STATE_IDS_"
            f"UNEXPECTED: {sorted(registry_state_ids)!r}"
        )

    print(
        "both EX01_PERSONAL variants coexist in registry with "
        "distinct state_ids (2D-20W variant-aware catalog refresh): OK"
    )

    # Navigation transitions / outcome_mode.
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

    for t in authorization_group_transitions:
        print(
            "transition:",
            "after_fingerprint=" + t.get("after_fingerprint", "")[:12],
            "candidate_ids=" + str(t.get("candidate_ids")),
            "discriminator_keys=" + str(t.get("discriminator_keys")),
            "navigation_context=" + str(t.get("navigation_context")),
            "context_signature="
            + str(t.get("context_signature"))[:16],
        )

    # -----------------------------------------------------------
    # Final CURRENT-view proof (observation store).
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

    # observation_state.json must be completely untouched by
    # materialization (it is read-only from this call's perspective).
    after_observation_revision = observation_store.revision

    if after_observation_revision != EXPECTED_INITIAL_OBSERVATION_REVISION:
        raise SystemExit(
            "PASS2_BLOCKED_OBSERVATION_STATE_MUTATED_DURING_CALL2: "
            f"revision now {after_observation_revision}"
        )

    print(
        "observation_state.json unchanged by CALL 2 (revision still "
        f"{after_observation_revision}): OK"
    )

    print("\n=== SUMMARY ===")
    print("CALL 2 previous_revision_id (pinned base):", CALL1_REVISION_ID)
    print(
        "CALL 2 previous_revision_selection_mode:",
        call2.get("previous_revision_selection_mode"),
    )
    print("CALL 2 revision_id:", call2_revision_id)
    print(
        "revision-directory count before/after:",
        len(before_revision_dirs),
        "/",
        len(after_revision_dirs),
    )
    print("final state count:", len(state_manifest2))
    print("AUTHORIZATION state_id/fingerprint:", AUTHORIZATION_STATE_ID,
          AUTHORIZATION_FINGERPRINT)
    print("TITULAR state_id/fingerprint:", TITULAR_STATE_ID,
          TITULAR_FINGERPRINT)
    print("FAMILIAR state_id/fingerprint:", FAMILIAR_STATE_ID,
          FAMILIAR_FINGERPRINT)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
