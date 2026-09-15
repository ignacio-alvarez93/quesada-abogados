"""WO 2D-20 (authorized resume): PASS 2 materialization.

Consumes only the CURRENT/non-superseded observation view (2D-20K) and
runs the real production reconciliation
(reconcile_auto_twin_discovery_materialization), exactly as
backend/qcc/bridge/server.py invokes it in production, including its
two-call closure pattern (pass 1: materialize new state(s); pass 2:
materialize newly eligible transition(s)).

Does not modify: source, tests, observations, captures, supersession
history, or any prior materialized revision (the revision store is
strictly append-only and content-addressed; this script never deletes
or rewrites a manifest).

If any precondition or invariant fails, this script stops (raises/
prints) without attempting any repair.
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

EXPECTED_PREVIOUS_REVISION_ID = "matrev-1586425db7664a40678bfa82"

OLD_COLLIDED_STATE_KEY = (
    "db042cded188d6a7a948f28c9c52681c3eaef8efc02d3eac5a7f4467bb14eb87"
)

AUTHORIZATION_STATE_ID = "AUTO_46D7EFFD1132808AA1B6B5AF"
AUTHORIZATION_FINGERPRINT = (
    "0f048a41feded5af2ceae831e57bf6c1d79d3d8"
    "6ccfe991c698a5b21e3e7aca2"
)

TITULAR_FINGERPRINT = (
    "52efb715d5688ad10cb2945d862847868ce25b4"
    "208f6ca84dcf57aa8a4032311"
)

FAMILIAR_FINGERPRINT = (
    "88c730539a17c84d7c3ac6fb753c7ba40a748928"
    "9f7d0c950d815f3aa568ae38"
)

FAMILIAR_TRIGGER_CAPTURE_ID = "20260912_060635_832343_986fda4c"
TITULAR_TRIGGER_CAPTURE_ID = "20260912_060228_192874_aa602bac"


def _mercurio_revision_dirs():
    root = DEFAULT_AUTO_TWIN_MATERIALIZED_ROOT / "mercurio"
    return {p.name for p in root.iterdir() if p.is_dir()}


def main() -> int:
    before_revisions = _mercurio_revision_dirs()

    print("=== PRECONDITIONS ===")
    print(
        "expected previous revision present:",
        EXPECTED_PREVIOUS_REVISION_ID in before_revisions,
    )
    print("mercurio revision count before:", len(before_revisions))

    observation_store = AutoTwinObservationStore()
    managed_site_store = AutoTwinManagedSiteStore()
    human_navigation_candidate_store = HumanNavigationCandidateStore()

    current = observation_store.snapshot(
        "mercurio",
        current_only=True,
    )["twin"]["states"]

    historical = observation_store.snapshot("mercurio")["twin"]["states"]

    if OLD_COLLIDED_STATE_KEY in current:
        raise SystemExit(
            "PRECONDITION_FAILED: old collided state still CURRENT"
        )

    if OLD_COLLIDED_STATE_KEY not in historical:
        raise SystemExit(
            "PRECONDITION_FAILED: old collided state no longer "
            "historically readable"
        )

    ex01_personal_current = {
        key: value
        for key, value in current.items()
        if value.get("functional_state") == "EX01_PERSONAL"
    }

    if len(ex01_personal_current) != 2:
        raise SystemExit(
            "PRECONDITION_FAILED: expected exactly 2 current "
            f"EX01_PERSONAL states, found {len(ex01_personal_current)}"
        )

    fingerprints_current = {
        value.get("last_fingerprint")
        for value in ex01_personal_current.values()
    }

    if fingerprints_current != {
        TITULAR_FINGERPRINT,
        FAMILIAR_FINGERPRINT,
    }:
        raise SystemExit(
            "PRECONDITION_FAILED: current EX01_PERSONAL fingerprints "
            f"do not match expected set: {fingerprints_current!r}"
        )

    print("preconditions satisfied.\n")

    NON_CONFORMING_REVISION_IDS = {
        "matrev-0737ace5e5dc6fef1dbd982d",
        "matrev-e913839c49ad1ebf87f8b505",
        "matrev-ceafd8162d0e4eeb5f08cb62",
    }

    def _reconcile(trigger_capture_id):
        result = reconcile_auto_twin_discovery_materialization(
            managed_site_store=managed_site_store,
            observation_store=observation_store,
            capture_root=CAPTURE_ROOT,
            trigger_capture_id=trigger_capture_id,
            twin_key="mercurio",
            previous_revision_id=EXPECTED_PREVIOUS_REVISION_ID,
            human_navigation_candidate_store=(
                human_navigation_candidate_store
            ),
        )

        if result.get("previous_revision_selection_mode") != "PINNED":
            raise SystemExit(
                "INVARIANT_FAILED: selection_mode was not PINNED -- "
                f"got {result.get('previous_revision_selection_mode')!r}"
            )

        if result.get("base_revision_id") != EXPECTED_PREVIOUS_REVISION_ID:
            raise SystemExit(
                "INVARIANT_FAILED: base_revision_id mismatch -- "
                f"got {result.get('base_revision_id')!r}, expected "
                f"{EXPECTED_PREVIOUS_REVISION_ID!r}"
            )

        if result.get("base_revision_id") in NON_CONFORMING_REVISION_IDS:
            raise SystemExit(
                "INVARIANT_FAILED: base_revision_id is one of the "
                "known non-conforming revisions"
            )

        return result

    print("=== PASS 1 (pinned base, materialize new state(s)) ===")
    pass1 = _reconcile(FAMILIAR_TRIGGER_CAPTURE_ID)
    print(json.dumps(pass1, indent=2, ensure_ascii=False, default=str))

    after_pass1_revisions = _mercurio_revision_dirs()
    new_after_pass1 = after_pass1_revisions - before_revisions

    print("\n=== AFTER PASS 1 ===")
    print("new revision(s) created so far:", sorted(new_after_pass1))
    print(
        "previous (pinned) revision still present unchanged:",
        EXPECTED_PREVIOUS_REVISION_ID in after_pass1_revisions,
    )

    if len(new_after_pass1) > 1:
        raise SystemExit(
            "INVARIANT_FAILED: pass 1 alone already wrote more than "
            f"one new revision: {sorted(new_after_pass1)}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
