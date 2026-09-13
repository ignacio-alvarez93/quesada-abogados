"""WO 2D-20S: governed corroboration enrichment of the EX01_PERSONAL
supersession.

2D-20K recorded the append-safe supersession of the pre-2D-20J
collided EX01_PERSONAL observation by its two capability-aware
replacements, but its provenance never carried the per-replacement
``replacement_navigation_context_signatures`` corroboration required
by the 2D-20R contextual 1->N navigation-target resolver
(backend/qcc/auto_twin/navigation_transition_materialization.py). As
long as that key is absent, PASS 2 materialization stays fail-closed
for any stale navigation candidate still targeting the old collided
fingerprint.

This script does NOT re-supersede, re-derive fingerprints, or touch
raw captures/candidates/materialized revisions. It only:

1. reads the ALREADY-recorded EX01_PERSONAL supersession
   (data/qcc/auto_twin/observation_state.json, written by 2D-20K) and
   the ALREADY-recorded, immutable human navigation-candidate evidence
   (data/qcc/navigation_learning/MERCURIO/REAL/
   human_navigation_candidates.json);
2. derives corroboration entries by correlating that evidence via
   correlate_supersession_replacement_navigation_context_signatures()
   -- timestamps, fingerprints and opaque context_signature hashes
   only, never raw branch/navigation_context literal values such as
   130/131;
3. if, and only if, that correlation uniquely and unambiguously
   corroborates every declared replacement, appends the corroboration
   to the EXISTING supersession record's provenance via
   AutoTwinObservationStore.enrich_supersession_provenance() (2D-20S)
   -- an append-safe, idempotent merge that never touches
   old_state_key, replacement_state_keys, reason, recorded_at, or any
   pre-existing provenance field.

Any ambiguity, missing evidence, or conflict stops this script before
any write -- BLOCKED_BY_EVIDENCE.

Does NOT run PASS 2 materialization.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from backend.qcc.auto_twin.managed_site_store import (  # noqa: E402
    AutoTwinManagedSiteStore,
)
from backend.qcc.auto_twin.navigation_transition_materialization import (  # noqa: E402
    PROVENANCE_CORROBORATION_KEY,
    correlate_supersession_replacement_navigation_context_signatures,
)
from backend.qcc.auto_twin.observation_store import (  # noqa: E402
    AutoTwinObservationStore,
)
from backend.qcc.navigation_learning.human_candidate_store import (  # noqa: E402
    HumanNavigationCandidateStore,
)


OLD_COLLIDED_STATE_KEY = (
    "db042cded188d6a7a948f28c9c52681c3eaef8efc02d3eac5a7f4467bb14eb87"
)

SITE_CODE = "MERCURIO"
ENVIRONMENT = "REAL"

WORK_ORDER = "2D-20S"


def _candidates_for_correlation(store):
    payload = store.snapshot(
        SITE_CODE,
        environment=ENVIRONMENT,
    )

    return tuple(
        {
            "after_fingerprint": item.get("after_fingerprint"),
            "context_signature": item.get("context_signature"),
            "observed_at": item.get("last_observed_at"),
        }
        for item in payload.get("candidates", ())
    )


def main() -> int:
    observation_store = AutoTwinObservationStore()
    managed_site_store = AutoTwinManagedSiteStore()
    human_navigation_candidate_store = HumanNavigationCandidateStore()

    managed_twin = managed_site_store.get("mercurio")

    if managed_twin is None:
        raise SystemExit(
            "BLOCKED: managed twin 'mercurio' not found"
        )

    before_historical = observation_store.snapshot("mercurio")
    before_current = observation_store.snapshot(
        "mercurio",
        current_only=True,
    )

    before_states = before_historical["twin"]["states"]
    before_supersessions = before_historical["twin"]["supersessions"]

    print("=== BEFORE ===")
    print("observation state count:", len(before_states))
    print("supersession count:", len(before_supersessions))

    old_state = before_states.get(OLD_COLLIDED_STATE_KEY)

    if old_state is None:
        raise SystemExit(
            "BLOCKED_BY_EVIDENCE: old collided state_key "
            f"{OLD_COLLIDED_STATE_KEY} not found"
        )

    record = before_supersessions.get(OLD_COLLIDED_STATE_KEY)

    if record is None:
        raise SystemExit(
            "BLOCKED_BY_EVIDENCE: no recorded supersession for "
            f"old_state_key {OLD_COLLIDED_STATE_KEY} -- run 2D-20K "
            "reprojection first"
        )

    replacement_state_keys = tuple(
        record.get("replacement_state_keys") or ()
    )

    print("superseded old state_key:", OLD_COLLIDED_STATE_KEY)
    print("replacement state_keys:", replacement_state_keys)

    if (
        PROVENANCE_CORROBORATION_KEY
        in (record.get("provenance") or {})
    ):
        print(
            "\ncorroboration already present -- enrichment is "
            "idempotent, proceeding to confirm no drift.\n"
        )

    current_states = before_current["twin"]["states"]

    missing_current = [
        key
        for key in replacement_state_keys
        if key not in current_states
    ]

    if missing_current:
        raise SystemExit(
            "BLOCKED_BY_EVIDENCE: replacement state_key(s) not in "
            f"CURRENT view: {missing_current!r}"
        )

    replacement_anchors = {
        key: current_states[key].get("last_seen_at")
        for key in replacement_state_keys
    }

    print("\nreplacement CURRENT fingerprints (evidence, unchanged):")
    for key in replacement_state_keys:
        print(
            f"  {key} -> "
            f"{current_states[key].get('last_fingerprint')} "
            f"(anchor last_seen_at={replacement_anchors[key]!r})"
        )

    candidates = _candidates_for_correlation(
        human_navigation_candidate_store
    )

    print(
        f"\nrecorded human navigation candidates evaluated: "
        f"{len(candidates)}"
    )

    corroboration = (
        correlate_supersession_replacement_navigation_context_signatures(
            stale_fingerprint=old_state.get("last_fingerprint"),
            replacement_anchors=replacement_anchors,
            candidates=candidates,
            current_states=current_states,
        )
    )

    if not corroboration or set(corroboration) != set(
        replacement_state_keys
    ):
        raise SystemExit(
            "BLOCKED_BY_EVIDENCE: recorded navigation-candidate and "
            "capture evidence does not uniquely and unambiguously "
            "corroborate every declared replacement -- refusing to "
            "write partial or absent corroboration"
        )

    print("\n=== DERIVED CORROBORATION (from recorded evidence) ===")
    print(json.dumps(corroboration, indent=2, ensure_ascii=False))

    updated_record = observation_store.enrich_supersession_provenance(
        managed_twin,
        old_state_key=OLD_COLLIDED_STATE_KEY,
        replacement_navigation_context_signatures=corroboration,
    )

    after_historical = observation_store.snapshot("mercurio")
    after_current = observation_store.snapshot(
        "mercurio",
        current_only=True,
    )

    after_states = after_historical["twin"]["states"]
    after_supersessions = after_historical["twin"]["supersessions"]

    print("\n=== AFTER ===")
    print("observation state count:", len(after_states))
    print("supersession count:", len(after_supersessions))
    print(
        "\nupdated supersession record:\n",
        json.dumps(updated_record, indent=2, ensure_ascii=False),
    )

    # Auditability: nothing about identity/count/history moved.
    assert len(after_states) == len(before_states)
    assert len(after_supersessions) == len(before_supersessions)
    assert (
        after_states[OLD_COLLIDED_STATE_KEY]
        == before_states[OLD_COLLIDED_STATE_KEY]
    )
    for key in replacement_state_keys:
        assert after_states[key] == before_states[key]
    assert (
        updated_record["old_state_key"]
        == record["old_state_key"]
    )
    assert (
        updated_record["replacement_state_keys"]
        == record["replacement_state_keys"]
    )
    assert updated_record["reason"] == record["reason"]
    assert updated_record["recorded_at"] == record["recorded_at"]
    assert (
        OLD_COLLIDED_STATE_KEY
        in after_current["twin"]["states"]
    ) is False
    for key in replacement_state_keys:
        assert key in after_current["twin"]["states"]

    print(
        "\ninvariant check passed: no raw capture/candidate/"
        "materialized revision or historical state/supersession "
        "field was modified; only provenance."
        f"{PROVENANCE_CORROBORATION_KEY} was added.\n"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
