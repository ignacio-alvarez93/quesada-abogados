"""WO 2D-20K: governed reprojection of the collided EX01_PERSONAL state.

Reprocesses the already-recorded, immutable REAL captures for the 130
(TITULAR) and 131 (FAMILIAR) branches through the 2D-20J
capability-aware identity, then -- only if both replacements validate
against the expected fingerprints -- supersedes the pre-2D-20J
collided EX01_PERSONAL observation via the append-safe
AutoTwinObservationStore.supersede() mechanism (2D-20K).

Reads only already-recorded evidence under data/qcc/site_architecture/.
Never writes to raw captures, historical candidates, materialized
revisions, or branch/navigation-context evidence. The only file this
script may modify is the derived, gitignored
data/qcc/auto_twin/observation_state.json.

Safe to re-run: supersede() is idempotent, and observe() replay of the
same immutable captures is deterministic.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from backend.automation.site_architecture import (  # noqa: E402
    adapt_qcc_extension_capture,
    normalize_dom_capture,
)
from backend.qcc.auto_twin.managed_site_store import (  # noqa: E402
    AutoTwinManagedSiteStore,
)
from backend.qcc.auto_twin.observation_store import (  # noqa: E402
    AutoTwinObservationStore,
)
from backend.qcc.site_architecture.ingestor import (  # noqa: E402
    QccSiteArchitectureIngestor,
)


SITE_ARCHITECTURE_ROOT = (
    REPO_ROOT / "data" / "qcc" / "site_architecture"
)

OLD_COLLIDED_STATE_KEY = (
    "db042cded188d6a7a948f28c9c52681c3eaef8efc02d3eac5a7f4467bb14eb87"
)

# capture_id -> expected branch label, in real chronological order.
TITULAR_CAPTURE_IDS = (
    "20260912_060218_754542_25a0d363",
    "20260912_060228_192874_aa602bac",
)

FAMILIAR_CAPTURE_IDS = (
    "20260912_060631_109928_94d6a6ca",
    "20260912_060635_832343_986fda4c",
)

EXPECTED_TITULAR_FINGERPRINT = (
    "52efb715d5688ad10cb2945d862847868ce25b4"
    "208f6ca84dcf57aa8a4032311"
)

EXPECTED_FAMILIAR_FINGERPRINT = (
    "88c730539a17c84d7c3ac6fb753c7ba40a748928"
    "9f7d0c950d815f3aa568ae38"
)

WORK_ORDER = "2D-20K"


def _read_json(path: Path) -> dict:
    return json.loads(
        path.read_text(encoding="utf-8")
    )


def _reprocess_capture(
    ingestor: QccSiteArchitectureIngestor,
    capture_id: str,
) -> dict:
    capture_dir = SITE_ARCHITECTURE_ROOT / capture_id

    raw_capture = _read_json(
        capture_dir / "qcc_capture.json"
    )

    metadata = _read_json(
        capture_dir / "metadata.json"
    )

    adapted_capture = adapt_qcc_extension_capture(raw_capture)

    snapshot = normalize_dom_capture(adapted_capture)

    state_result = ingestor._observe_state(snapshot)

    return {
        "capture_id": capture_id,
        "metadata": metadata,
        "state_result": state_result,
    }


def _observe_replay(
    observation_store: AutoTwinObservationStore,
    managed_twin,
    reprocessed: dict,
) -> dict:
    metadata = reprocessed["metadata"]
    state_result = reprocessed["state_result"]

    return observation_store.observe(
        managed_twin,
        capture_id=reprocessed["capture_id"],
        observed_at=metadata.get("received_at"),
        browser_profile_key=(
            metadata.get("retention", {}).get(
                "browser_profile_key"
            )
            or "twin_discovery"
        ),
        url=metadata.get("page", {}).get("url"),
        site_code=metadata.get("site_code"),
        state_observation=state_result["observation"],
    )


def _replay_branch(
    observation_store,
    managed_twin,
    ingestor,
    capture_ids,
    expected_fingerprint,
    label,
):
    print(f"--- Replaying {label} branch ---")

    last_result = None

    for capture_id in capture_ids:
        reprocessed = _reprocess_capture(
            ingestor,
            capture_id,
        )

        result = _observe_replay(
            observation_store,
            managed_twin,
            reprocessed,
        )

        print(
            f"  capture={capture_id} "
            f"state_variant_key="
            f"{result.get('state_variant_key')!r} "
            f"fingerprint={result['fingerprint']} "
            f"state_key={result['state_key']} "
            f"classification={result['classification']}"
        )

        last_result = result

    if last_result["fingerprint"] != expected_fingerprint:
        raise SystemExit(
            f"BLOCKED: {label} fingerprint mismatch -- "
            f"got {last_result['fingerprint']!r}, "
            f"expected {expected_fingerprint!r}"
        )

    return last_result


def main() -> int:
    observation_store = AutoTwinObservationStore()
    managed_site_store = AutoTwinManagedSiteStore()
    ingestor = QccSiteArchitectureIngestor()

    managed_twin = managed_site_store.get("mercurio")

    if managed_twin is None:
        raise SystemExit(
            "BLOCKED: managed twin 'mercurio' not found"
        )

    before = observation_store.snapshot("mercurio")

    old_state_before = before["twin"]["states"].get(
        OLD_COLLIDED_STATE_KEY
    )

    print("=== BEFORE ===")
    print(
        "old collided state present:",
        old_state_before is not None,
    )

    if old_state_before is None:
        raise SystemExit(
            "BLOCKED: old collided state_key "
            f"{OLD_COLLIDED_STATE_KEY} not found -- "
            "nothing to supersede"
        )

    # Step 1+2: reprocess immutable captures, validate both replacements.
    titular_result = _replay_branch(
        observation_store,
        managed_twin,
        ingestor,
        TITULAR_CAPTURE_IDS,
        EXPECTED_TITULAR_FINGERPRINT,
        "TITULAR (130)",
    )

    familiar_result = _replay_branch(
        observation_store,
        managed_twin,
        ingestor,
        FAMILIAR_CAPTURE_IDS,
        EXPECTED_FAMILIAR_FINGERPRINT,
        "FAMILIAR (131)",
    )

    titular_key = titular_result["state_key"]
    familiar_key = familiar_result["state_key"]

    if titular_key == familiar_key:
        raise SystemExit(
            "BLOCKED: TITULAR and FAMILIAR replay collapsed onto the "
            "same state_key -- refusing to supersede"
        )

    if OLD_COLLIDED_STATE_KEY in (titular_key, familiar_key):
        raise SystemExit(
            "BLOCKED: a replacement state_key still matches the old "
            "collided identity -- refusing to supersede"
        )

    # Step 3: only now, append the supersession record.
    record = observation_store.supersede(
        managed_twin,
        old_state_key=OLD_COLLIDED_STATE_KEY,
        replacement_state_keys=(
            titular_key,
            familiar_key,
        ),
        reason=(
            "2D-20K: capability-aware EX01_PERSONAL identity "
            "(pestFamiliar visibility) supersedes the pre-2D-20J "
            "collided generic-fingerprint identity"
        ),
        recorded_at=(
            datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        ),
        provenance={
            "work_order": WORK_ORDER,
            "titular_capture_ids": list(TITULAR_CAPTURE_IDS),
            "familiar_capture_ids": list(FAMILIAR_CAPTURE_IDS),
            "titular_state_key": titular_key,
            "familiar_state_key": familiar_key,
            "titular_fingerprint": EXPECTED_TITULAR_FINGERPRINT,
            "familiar_fingerprint": EXPECTED_FAMILIAR_FINGERPRINT,
        },
    )

    print("\n=== SUPERSESSION RECORD ===")
    print(json.dumps(record, indent=2, ensure_ascii=False))

    after_current = observation_store.snapshot(
        "mercurio",
        current_only=True,
    )

    after_historical = observation_store.snapshot("mercurio")

    print("\n=== AFTER (current_only) ===")
    print(
        "old collided key present in CURRENT view:",
        OLD_COLLIDED_STATE_KEY
        in after_current["twin"]["states"],
    )
    print(
        "titular key present in CURRENT view:",
        titular_key in after_current["twin"]["states"],
    )
    print(
        "familiar key present in CURRENT view:",
        familiar_key in after_current["twin"]["states"],
    )

    print("\n=== AFTER (historical) ===")
    print(
        "old collided key still readable historically:",
        OLD_COLLIDED_STATE_KEY
        in after_historical["twin"]["states"],
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
