"""QCC Contract Watcher — AUTO TWIN observation-driven selector (1E).

Bridges ``AutoTwinObservationStore`` (AUTO TWIN's own, already-accepted
per-``(twin_key, state_key)`` identity/classification bookkeeping) into
governed ``ContractWatcherPersistedWatchRequest`` batches
(``contract_watcher_persisted_adapter``, 1D), so an external caller (a
future coordinator, a CLI, a test) can deterministically decide *which*
persisted captures to compare without inventing a second baseline-
selection policy.

This module is READ-ONLY with respect to ``AutoTwinObservationStore``:
it only calls ``snapshot()`` and never writes back to it. AUTO TWIN
remains the sole writer of TWIN identity/classification state; Contract
Watcher never becomes a second writer of that trust boundary.

Selection policy (deliberately minimal, invents nothing new):

- ``baseline_capture_id`` and ``last_capture_id`` are read verbatim from
  each observed state — both are already-governed, already-explicit
  identifiers (``baseline_capture_id`` is set once, only on first
  discovery, by AUTO TWIN's own promotion policy; this module never
  re-derives or overrides it).
- ``contract_key`` is derived by one explicit, documented, deterministic
  convention: ``f"{twin_key}::{state_key}"``. It is never inferred from
  incidental metadata, keeping "a trusted baseline is always an explicit
  governance decision" intact.
- A state with no ``baseline_capture_id``/``last_capture_id`` yet (never
  promoted, i.e. still UNKNOWN) is skipped and reported, never raised.
- A state whose ``baseline_capture_id`` equals its ``last_capture_id``
  (nothing new to compare) is skipped and reported, never raised.
- Every skip is returned to the caller as a per-target, reported
  omission — never a silent drop.

This function does not itself call 1D/1C, does not schedule, does not
loop. It performs a single, pure, restart-safe read-and-derive pass
over whatever ``observation_store`` currently holds.
"""

from __future__ import annotations

from .contract_watcher_confirmation import ContractWatcherConfirmationPolicy
from .contract_watcher_persisted_adapter import (
    ContractWatcherPersistedCaptureRef,
    ContractWatcherPersistedWatchRequest,
)
from .contract_watcher_pipeline import DEFAULT_GEOMETRY_TOLERANCE_PX
from .observation_store import AutoTwinObservationStore

from backend.qcc.site_architecture.ingestor import (
    DEFAULT_QCC_SITE_ARCHITECTURE_ROOT,
)


CONTRACT_WATCHER_SELECTOR_SKIP_STATE_NOT_BASELINED = (
    "QCC_CONTRACT_WATCHER_SELECTOR_SKIP_STATE_NOT_BASELINED"
)

CONTRACT_WATCHER_SELECTOR_SKIP_NOTHING_TO_COMPARE = (
    "QCC_CONTRACT_WATCHER_SELECTOR_SKIP_NOTHING_TO_COMPARE"
)


def _text(value) -> str:
    return str(value or "").strip()


def contract_watcher_observation_contract_key(twin_key, state_key) -> str:
    """The one deterministic ``contract_key`` convention this slice uses.

    Exposed (not just inlined) so any future caller that needs to look
    up the same governed contract identity independently — for example
    to read ``ContractWatcherHistoryStore`` status for one specific
    ``(twin_key, state_key)`` — reconstructs the exact same key instead
    of duplicating this convention.
    """

    twin_key = _text(twin_key)
    state_key = _text(state_key)

    if not twin_key or not state_key:
        raise ValueError(
            "QCC_CONTRACT_WATCHER_SELECTOR_CONTRACT_KEY_COMPONENTS_REQUIRED"
        )

    return f"{twin_key}::{state_key}"


def select_contract_watcher_persisted_watch_requests(
    observation_store,
    *,
    confirmation_policy,
    capture_root=DEFAULT_QCC_SITE_ARCHITECTURE_ROOT,
    geometry_tolerance_px=DEFAULT_GEOMETRY_TOLERANCE_PX,
):
    """Derives governed persisted watch requests from AUTO TWIN observations.

    Reads ``observation_store.snapshot()`` exactly once and never writes
    to it. Fails closed (raises) on a structurally invalid snapshot —
    that is a corrupted read, not a legitimate business state, so it is
    never silently skipped. A per-state omission that IS a legitimate,
    expected business state (not yet baselined, or nothing new since the
    baseline) is instead reported in ``skipped`` and processing
    continues with the remaining states.

    ``confirmation_policy`` and ``geometry_tolerance_px`` are applied
    uniformly to every derived request: this selector introduces no
    per-contract governance policy of its own, only reads one that
    already exists (AUTO TWIN's baseline/observation bookkeeping).

    Returns ``{"selected": [...], "skipped": [...]}``. Never invokes
    1C/1D itself, never schedules, never loops.
    """

    if not isinstance(observation_store, AutoTwinObservationStore):
        raise TypeError(
            "QCC_CONTRACT_WATCHER_SELECTOR_OBSERVATION_STORE_INVALID"
        )

    if not isinstance(confirmation_policy, ContractWatcherConfirmationPolicy):
        raise TypeError(
            "QCC_CONTRACT_WATCHER_SELECTOR_CONFIRMATION_POLICY_REQUIRED"
        )

    snapshot = observation_store.snapshot()

    twins = snapshot.get("twins")

    if not isinstance(twins, dict):
        raise ValueError("QCC_CONTRACT_WATCHER_SELECTOR_SNAPSHOT_TWINS_INVALID")

    selected = []
    skipped = []

    for twin_key in sorted(twins):
        twin = twins[twin_key]

        if not isinstance(twin, dict):
            raise ValueError(
                "QCC_CONTRACT_WATCHER_SELECTOR_SNAPSHOT_TWIN_INVALID"
            )

        states = twin.get("states")

        if not isinstance(states, dict):
            raise ValueError(
                "QCC_CONTRACT_WATCHER_SELECTOR_SNAPSHOT_STATES_INVALID"
            )

        for state_key in sorted(states):
            state = states[state_key]

            if not isinstance(state, dict):
                raise ValueError(
                    "QCC_CONTRACT_WATCHER_SELECTOR_SNAPSHOT_STATE_INVALID"
                )

            contract_key = contract_watcher_observation_contract_key(
                twin_key, state_key
            )

            baseline_capture_id = _text(state.get("baseline_capture_id"))
            last_capture_id = _text(state.get("last_capture_id"))

            if not baseline_capture_id or not last_capture_id:
                skipped.append({
                    "twin_key": twin_key,
                    "state_key": state_key,
                    "contract_key": contract_key,
                    "reason": (
                        CONTRACT_WATCHER_SELECTOR_SKIP_STATE_NOT_BASELINED
                    ),
                })
                continue

            if baseline_capture_id == last_capture_id:
                skipped.append({
                    "twin_key": twin_key,
                    "state_key": state_key,
                    "contract_key": contract_key,
                    "reason": (
                        CONTRACT_WATCHER_SELECTOR_SKIP_NOTHING_TO_COMPARE
                    ),
                })
                continue

            selected.append(
                ContractWatcherPersistedWatchRequest(
                    contract_key=contract_key,
                    baseline_capture=ContractWatcherPersistedCaptureRef(
                        capture_id=baseline_capture_id,
                        root=capture_root,
                    ),
                    observation_capture=ContractWatcherPersistedCaptureRef(
                        capture_id=last_capture_id,
                        root=capture_root,
                    ),
                    confirmation_policy=confirmation_policy,
                    geometry_tolerance_px=geometry_tolerance_px,
                    observed_at=_text(state.get("last_seen_at")) or None,
                    request_id=contract_key,
                )
            )

    return {
        "selected": selected,
        "skipped": skipped,
    }
