"""QCC Contract Watcher — durable no-skip persisted-capture backlog (1G).

Closes the one boundary Work Order 1F explicitly documented and left open
(see ``test_boundary_intermediate_capture_superseded_before_processing_is_skipped``
in ``scripts/tests/test_qcc_auto_twin_contract_watcher_observation_selector.py``):
the 1E selector (``contract_watcher_observation_selector``) only ever
derives a single ``(baseline_capture_id, last_capture_id)`` pair per
governed contract, so an intermediate persisted capture that becomes
"current" and is then superseded by a newer one *before* any select+batch
pass ever observes it is silently never independently evidenced.

Canonical source audit (Work Order QCC-CONTRACT-WATCHER-1G)
-------------------------------------------------------------

Three candidate sources of "every capture that ever existed for a
governed contract" were inspected:

- ``AutoTwinObservationStore`` — only ever remembers the CURRENT
  ``baseline_capture_id``/``last_capture_id`` pointers per state. It is
  explicitly documented (module docstring) as not duplicating heavy
  evidence, so it cannot answer "what captures existed between them".
- ``backend.qcc.site_architecture.light_history.QccArchitectureLightHistory``
  — an auxiliary, best-effort JSONL append log keyed by
  ``(browser_profile_key, origin, architecture_scope, functional_state)``.
  Its own call site documents it as non-authoritative: "Un fallo del
  histórico auxiliar nunca invalida una captura ya persistida" (a failure
  of this auxiliary history never invalidates an already-persisted
  capture) — i.e. an append can legitimately fail silently. It is
  therefore unsuitable as the authoritative enumeration source this Work
  Order requires.
- The persisted capture store itself
  (``data/qcc/site_architecture/<capture_id>/metadata.json``, the same
  root ``load_auto_twin_persisted_capture_bundle`` and 1D already treat
  as the sole source of truth for a normalized Site Contract) — durable,
  one directory per capture, and already relied upon for exactly this
  kind of full-inventory scan by
  ``QccSiteArchitectureIngestor._prune_retention_scope`` (iterates
  ``output_root``, reads only each capture's ``metadata.json``). This is
  therefore the existing, authoritative, enumerable persisted-capture
  store this Work Order asks to prefer over inventing a second one.

No new durable store, index or schema is introduced. This module only
adds a read-only enumeration + filtering pass over the exact same
on-disk captures 1D/1E already read individually.

Governed contract identity (what capture belongs to what contract)
--------------------------------------------------------------------

A capture is derived to belong to one governed ``(twin_key, state_key)``
contract by recomputing AUTO TWIN's own authoritative ``state_key``
identity function (``observation_store._state_identity`` /
``observation_store._state_key``) from that capture's own persisted
``pathname``/``functional_state``/``state_variant_key`` and comparing the
result, byte for byte, to the ``state_key`` already used as the
observation snapshot's own dictionary key. This is deliberately not a
new identity convention: it recomputes the exact same hash AUTO TWIN
itself would have produced had it called ``observe()`` on that capture,
so a capture is only ever considered part of a contract if AUTO TWIN's
own canonical identity function agrees.

Deterministic ordering
-----------------------

Captures on disk carry no explicit sequence number. Ordering is derived
from each capture's own ``metadata.json["received_at"]`` — the
backend-authoritative UTC instant ``QccSiteArchitectureIngestor.ingest``
itself records at ingestion time (never the browser-supplied
``captured_at``, and never filesystem mtime/inode order, which this
module never reads). Two captures cannot be reliably distinguished
below ``received_at``'s own resolution without inventing chronology, so
ties (and, defensively, any equal-timestamp pair) are broken by
``capture_id`` string order — a stable, canonical tie-breaker, not a
timestamp proxy: ``QccSiteArchitectureIngestor.ingest`` derives
``capture_id`` from the exact same instant plus a random per-capture
suffix, so this ordering is already consistent with — never contradicts
— the primary ``received_at`` ordering in the overwhelming common case,
and only the tie-breaker itself is filesystem/random-suffix dependent.
Known, accepted limitation: two captures that legitimately share the
exact same ``received_at`` value are ordered by this arbitrary but
stable tie-breaker, not by true wall-clock arrival order.

No-skip backlog policy
------------------------

For each governed ``(twin_key, state_key)`` contract that already has an
explicit, AUTO-TWIN-assigned ``baseline_capture_id`` (never auto-promoted
or invented here — exactly the same trust boundary 1E already enforces):

1. Every persisted capture whose recomputed ``state_key`` matches this
   contract's ``state_key`` and whose deterministic order is strictly
   after the baseline's own order is a *candidate*.
2. A candidate already durably represented by this contract's own
   accepted watcher evidence — read from ``ContractWatcherHistoryStore``
   entries, cross-referenced against ``ContractWatcherEvidenceStore`` for
   each entry's ``after_reference`` (never from an in-memory cursor, and
   never from evidence alone: an evidence record can legitimately exist
   without its history entry after a crash between the two durable
   writes inside ``evaluate_and_register_contract_watcher_observation``,
   and such a capture must remain pending, not be mistaken for done) —
   is excluded.
3. Every remaining candidate becomes its own independent
   ``ContractWatcherPersistedWatchRequest``, always paired with the same
   pinned ``baseline_capture_id`` (the baseline itself is never advanced
   by this module), in ascending deterministic order.

Processing every selected request through the existing, unmodified 1C/1D
governed cycle (``run_contract_watcher_persisted_cycle_batch``) is what
actually makes a capture durably "done": that layer's own baseline-
identity pinning, append-only ordering enforcement and per-target
failure isolation are reused completely unchanged. A capture whose
resolution fails (missing/malformed artifact, cross-contract mismatch)
never becomes durably evidenced, so it is never added to the "already
represented" set above and is therefore automatically rediscovered and
retried by the next call to this function — no separate retry/terminal
bookkeeping exists here, because Contract Watcher evidence has no
existing terminal-failure classification to defer to.

Retention interaction (accepted, pre-existing, out of scope)
----------------------------------------------------------------

``QccSiteArchitectureIngestor``'s retention ring can prune an old
capture of a functional_state once a newer capture of that same
functional_state exists and the ring exceeds its configured limit; only
the single latest capture per functional_state (plus whatever capture
was just ingested) is protected. If a capture is pruned before any
backlog pass ever observes it, its evidence is genuinely, permanently
unavailable — this module operates only on whatever the persisted
capture store currently holds and never invents evidence for content
that no longer exists on disk. This mirrors the exact same accepted
limitation 1D/1E already carry for ``baseline_capture_id`` itself.
"""

from __future__ import annotations

from pathlib import Path
import json

from .contract_watcher_confirmation import ContractWatcherConfirmationPolicy
from .contract_watcher_history_store import _parse_timestamp
from .contract_watcher_lifecycle import (
    get_default_contract_watcher_evidence_store,
    get_default_contract_watcher_history_store,
)
from .contract_watcher_observation_selector import (
    contract_watcher_observation_contract_key,
)
from .contract_watcher_persisted_adapter import (
    ContractWatcherPersistedCaptureRef,
    ContractWatcherPersistedWatchRequest,
)
from .contract_watcher_pipeline import DEFAULT_GEOMETRY_TOLERANCE_PX
from .observation_store import (
    AutoTwinObservationStore,
    _state_identity,
    _state_key,
    _url_identity,
)

from backend.qcc.site_architecture.ingestor import (
    DEFAULT_QCC_SITE_ARCHITECTURE_ROOT,
)


CONTRACT_WATCHER_BACKLOG_SKIP_STATE_NOT_BASELINED = (
    "QCC_CONTRACT_WATCHER_BACKLOG_SKIP_STATE_NOT_BASELINED"
)

CONTRACT_WATCHER_BACKLOG_SKIP_BASELINE_CAPTURE_UNREADABLE = (
    "QCC_CONTRACT_WATCHER_BACKLOG_SKIP_BASELINE_CAPTURE_UNREADABLE"
)

CONTRACT_WATCHER_BACKLOG_SKIP_NOTHING_PENDING = (
    "QCC_CONTRACT_WATCHER_BACKLOG_SKIP_NOTHING_PENDING"
)

_METADATA_FILENAME = "metadata.json"


def _text(value) -> str:
    return str(value or "").strip()


def _read_capture_backlog_entry(capture_dir):
    """Lightweight, read-only, fail-closed-per-capture metadata read.

    Mirrors the existing enumeration pattern already used by
    ``QccSiteArchitectureIngestor._prune_retention_scope`` (iterate the
    capture root, read only each ``metadata.json``) instead of loading
    every full persisted-capture bundle just to enumerate/order
    candidates. A malformed/unreadable/incomplete ``metadata.json``
    returns ``None`` -- never raises -- so one corrupted capture
    directory can never abort enumeration for its siblings, and remains
    retryable on a later pass exactly like any other unresolved
    candidate.
    """

    metadata_path = capture_dir / _METADATA_FILENAME

    if not metadata_path.is_file():
        return None

    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict):
        return None

    capture_id = _text(payload.get("capture_id"))

    if not capture_id or capture_id != capture_dir.name:
        return None

    state_observation = payload.get("state_observation")

    if not isinstance(state_observation, dict):
        return None

    page = payload.get("page")

    if not isinstance(page, dict):
        return None

    try:
        _origin, pathname = _url_identity(page.get("url"))
    except ValueError:
        return None

    received_at = _text(payload.get("received_at"))

    if not received_at:
        return None

    try:
        parsed_received_at = _parse_timestamp(
            received_at,
            error="QCC_CONTRACT_WATCHER_BACKLOG_RECEIVED_AT_INVALID",
        )
    except ValueError:
        return None

    if parsed_received_at.tzinfo is None:
        return None

    functional_state_raw = state_observation.get("state")
    functional_state = _text(functional_state_raw).upper() or None

    state_variant_key = _text(state_observation.get("state_variant_key")) or None

    identity = _state_identity(
        pathname=pathname,
        functional_state=functional_state,
        state_variant_key=state_variant_key,
    )

    return {
        "capture_id": capture_id,
        "state_key": _state_key(identity),
        "received_at": received_at,
        "order_key": (parsed_received_at, capture_id),
    }


def _enumerate_persisted_captures(capture_root):
    root_path = Path(capture_root)

    if not root_path.is_dir():
        return []

    entries = []

    for capture_dir in sorted(root_path.iterdir()):
        if not capture_dir.is_dir():
            continue

        entry = _read_capture_backlog_entry(capture_dir)

        if entry is not None:
            entries.append(entry)

    return entries


def _twin_state_entries(snapshot):
    twins = snapshot.get("twins")

    if not isinstance(twins, dict):
        raise ValueError("QCC_CONTRACT_WATCHER_BACKLOG_SNAPSHOT_TWINS_INVALID")

    for twin_key in sorted(twins):
        twin = twins[twin_key]

        if not isinstance(twin, dict):
            raise ValueError("QCC_CONTRACT_WATCHER_BACKLOG_SNAPSHOT_TWIN_INVALID")

        states = twin.get("states")

        if not isinstance(states, dict):
            raise ValueError("QCC_CONTRACT_WATCHER_BACKLOG_SNAPSHOT_STATES_INVALID")

        for state_key in sorted(states):
            state = states[state_key]

            if not isinstance(state, dict):
                raise ValueError(
                    "QCC_CONTRACT_WATCHER_BACKLOG_SNAPSHOT_STATE_INVALID"
                )

            yield twin_key, state_key, state


def _processed_observation_capture_ids(*, contract_key, evidence_store, history_store):
    """Durable "already independently evidenced" set for one contract.

    Deliberately derived from ``ContractWatcherHistoryStore`` entries
    (the durable ledger a downstream lifecycle decision actually
    replays), never from ``ContractWatcherEvidenceStore`` alone: the two
    stores are written in sequence by
    ``evaluate_and_register_contract_watcher_observation`` and a crash
    between the two durable writes can legitimately leave evidence
    persisted without its history entry. Treating such a capture as
    "already processed" would durably lose it. A history entry whose
    referenced evidence cannot be found is a genuine store-consistency
    violation (not a legitimate business state) and fails closed.
    """

    processed = set()

    for entry in history_store.list_entries(contract_key=contract_key):
        evidence_id = _text(entry.get("evidence_id"))

        if not evidence_id:
            continue

        evidence = evidence_store.get(
            contract_key=contract_key,
            evidence_id=evidence_id,
        )

        if evidence is None:
            raise ValueError(
                "QCC_CONTRACT_WATCHER_BACKLOG_HISTORY_EVIDENCE_MISSING"
            )

        after_reference = _text(evidence.get("after_reference"))

        if after_reference:
            processed.add(after_reference)

    return processed


def select_contract_watcher_persisted_backlog(
    observation_store,
    *,
    confirmation_policy,
    capture_root=DEFAULT_QCC_SITE_ARCHITECTURE_ROOT,
    geometry_tolerance_px=DEFAULT_GEOMETRY_TOLERANCE_PX,
    evidence_store=None,
    history_store=None,
):
    """Derives every durably pending persisted-capture watch request.

    Unlike ``select_contract_watcher_persisted_watch_requests`` (1E),
    this may return *more than one* selected request per governed
    contract -- one per eligible persisted capture strictly after the
    pinned baseline that has not yet been independently evidenced --
    always ordered ascending by the capture's own deterministic order so
    a caller that hands the full ``selected`` list to
    ``run_contract_watcher_persisted_cycle_batch`` in one call preserves
    the append-only chronological ordering
    ``ContractWatcherHistoryStore.register_observation`` requires.

    Read-only with respect to every store it touches
    (``observation_store``, ``evidence_store``, ``history_store``) and
    the persisted capture filesystem: this function never writes
    anything and never itself invokes 1C/1D.

    Fails closed (raises) on a structurally invalid observation snapshot
    or a durable evidence/history inconsistency -- never on a merely
    unresolved/unreadable individual capture, which is instead reported
    per-target in ``skipped`` and left for a later pass to rediscover.
    """

    if not isinstance(observation_store, AutoTwinObservationStore):
        raise TypeError(
            "QCC_CONTRACT_WATCHER_BACKLOG_OBSERVATION_STORE_INVALID"
        )

    if not isinstance(confirmation_policy, ContractWatcherConfirmationPolicy):
        raise TypeError(
            "QCC_CONTRACT_WATCHER_BACKLOG_CONFIRMATION_POLICY_REQUIRED"
        )

    resolved_evidence_store = (
        evidence_store or get_default_contract_watcher_evidence_store()
    )

    resolved_history_store = (
        history_store or get_default_contract_watcher_history_store()
    )

    snapshot = observation_store.snapshot()

    capture_entries = _enumerate_persisted_captures(capture_root)
    entries_by_capture_id = {entry["capture_id"]: entry for entry in capture_entries}

    selected = []
    skipped = []

    for twin_key, state_key, state in _twin_state_entries(snapshot):
        contract_key = contract_watcher_observation_contract_key(
            twin_key, state_key
        )

        baseline_capture_id = _text(state.get("baseline_capture_id"))

        if not baseline_capture_id:
            skipped.append({
                "twin_key": twin_key,
                "state_key": state_key,
                "contract_key": contract_key,
                "reason": CONTRACT_WATCHER_BACKLOG_SKIP_STATE_NOT_BASELINED,
            })
            continue

        baseline_entry = entries_by_capture_id.get(baseline_capture_id)

        if baseline_entry is None or baseline_entry["state_key"] != state_key:
            skipped.append({
                "twin_key": twin_key,
                "state_key": state_key,
                "contract_key": contract_key,
                "reason": (
                    CONTRACT_WATCHER_BACKLOG_SKIP_BASELINE_CAPTURE_UNREADABLE
                ),
            })
            continue

        processed_capture_ids = _processed_observation_capture_ids(
            contract_key=contract_key,
            evidence_store=resolved_evidence_store,
            history_store=resolved_history_store,
        )

        baseline_order_key = baseline_entry["order_key"]

        candidates = sorted(
            (
                entry
                for entry in capture_entries
                if (
                    entry["state_key"] == state_key
                    and entry["capture_id"] != baseline_capture_id
                    and entry["capture_id"] not in processed_capture_ids
                    and entry["order_key"] > baseline_order_key
                )
            ),
            key=lambda entry: entry["order_key"],
        )

        if not candidates:
            skipped.append({
                "twin_key": twin_key,
                "state_key": state_key,
                "contract_key": contract_key,
                "reason": CONTRACT_WATCHER_BACKLOG_SKIP_NOTHING_PENDING,
            })
            continue

        for entry in candidates:
            selected.append(
                ContractWatcherPersistedWatchRequest(
                    contract_key=contract_key,
                    baseline_capture=ContractWatcherPersistedCaptureRef(
                        capture_id=baseline_capture_id,
                        root=capture_root,
                    ),
                    observation_capture=ContractWatcherPersistedCaptureRef(
                        capture_id=entry["capture_id"],
                        root=capture_root,
                    ),
                    confirmation_policy=confirmation_policy,
                    geometry_tolerance_px=geometry_tolerance_px,
                    observed_at=entry["received_at"],
                    request_id=contract_key + ":" + entry["capture_id"],
                )
            )

    return {
        "selected": selected,
        "skipped": skipped,
    }
