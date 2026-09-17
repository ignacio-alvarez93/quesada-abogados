"""Durable historical confirmation log for QCC Contract Watcher (1B).

Subordinate to ``ContractWatcherEvidenceStore``: never duplicates a
contract, never duplicates raw evidence content and never persists raw
HTML/screenshots/cookies/tokens/PII. Each entry only references an
already-validated, already-persisted ``evidence_id`` plus the minimal
deterministic lifecycle metadata needed to reconstruct a governed
confirmation streak (severity, watch_state, semantic change signature,
the effective ``ContractWatcherConfirmationPolicy`` and the resulting
streak/lifecycle decision).

Layout (colocated with, but never mutating, the evidence store):

    data/qcc/auto_twin/contract_watcher/
        <contract_key>/
            <evidence_id>/evidence.json      (ContractWatcherEvidenceStore)
            history.json                      (this store)

One JSON document per watched logical contract, rewritten atomically on
every append (temp file + ``os.replace``), mirroring the existing
``AutoTwinNavigationTransitionValidationStore`` convention. Entries are
strictly ordered by ``created_at`` and are never mutated or removed once
appended; appending is idempotent for an already-seen ``evidence_id``
and rejects an observation that would be out of order relative to the
last persisted entry instead of silently reordering it.

Instance-local safety only: like ``ContractWatcherEvidenceStore``, this
store uses an in-process ``threading.RLock`` and atomic single-file
replacement. It has not been made safe for concurrent *processes*
writing the same ``history.json`` (no cross-process file lock), which
matches the actual single-worker contract of this Work Order; it must
not be assumed to be multi-process safe.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
import threading
import uuid

from .contract_watcher_confirmation import (
    ContractWatcherConfirmationPolicy,
    ContractWatcherConfirmationState,
    apply_confirmation_step,
    confirmation_policy_from_dict,
)
from .contract_watcher_store import (
    DEFAULT_CONTRACT_WATCHER_ROOT,
    _safe_segment,
)


CONTRACT_WATCHER_HISTORY_SCHEMA_VERSION = 1

CONTRACT_WATCHER_HISTORY_TYPE = "QCC_CONTRACT_WATCHER_HISTORY"

CONTRACT_WATCHER_HISTORY_FILENAME = "history.json"


class ContractWatcherHistoryOutOfOrderError(ValueError):
    """Raised when an observation's ``created_at`` does not strictly advance.

    A ``ValueError`` subclass (not a bare ``ValueError``) so that callers
    above this store (the 1C governed cycle/batch layer) can distinguish
    this specific, expected, restart-safe rejection — e.g. a batch retried
    with stale ordering, or two distinct observations sharing a coarse
    timestamp — from an unrelated structural/programming defect, and
    isolate it as a per-target failure instead of aborting an entire
    batch. Never raised for an exact replay of an already-persisted
    ``evidence_id``, which is always idempotent regardless of ordering.
    """


def _parse_timestamp(value, *, error):
    candidate = str(value or "").strip()

    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"

    try:
        return datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError(error) from exc


class ContractWatcherHistoryStore:
    """Filesystem-only durable log of confirmation decisions per contract."""

    def __init__(self, *, root=None):
        self._root = Path(
            root if root is not None else DEFAULT_CONTRACT_WATCHER_ROOT
        )

        self._lock = threading.RLock()

    @property
    def root(self):
        return self._root

    def history_path(self, *, contract_key):
        safe_contract_key = _safe_segment(
            contract_key,
            error="QCC_CONTRACT_WATCHER_HISTORY_CONTRACT_KEY_INVALID",
        )

        return (
            self._root / safe_contract_key / CONTRACT_WATCHER_HISTORY_FILENAME
        )

    def _read(self, path, *, contract_key):
        if not path.is_file():
            return []

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("QCC_CONTRACT_WATCHER_HISTORY_INVALID") from exc

        if not isinstance(payload, dict):
            raise ValueError("QCC_CONTRACT_WATCHER_HISTORY_INVALID")

        if (
            payload.get("schema_version")
            != CONTRACT_WATCHER_HISTORY_SCHEMA_VERSION
        ):
            raise ValueError(
                "QCC_CONTRACT_WATCHER_HISTORY_SCHEMA_VERSION_INVALID"
            )

        if payload.get("record_type") != CONTRACT_WATCHER_HISTORY_TYPE:
            raise ValueError("QCC_CONTRACT_WATCHER_HISTORY_TYPE_INVALID")

        if payload.get("contract_key") != contract_key:
            raise ValueError(
                "QCC_CONTRACT_WATCHER_HISTORY_CONTRACT_KEY_MISMATCH"
            )

        entries = payload.get("entries")

        if not isinstance(entries, list):
            raise ValueError("QCC_CONTRACT_WATCHER_HISTORY_ENTRIES_INVALID")

        return deepcopy(entries)

    def _write(self, path, *, contract_key, entries):
        directory = path.parent
        directory.mkdir(parents=True, exist_ok=True)

        payload = {
            "schema_version": CONTRACT_WATCHER_HISTORY_SCHEMA_VERSION,
            "record_type": CONTRACT_WATCHER_HISTORY_TYPE,
            "contract_key": contract_key,
            "entry_count": len(entries),
            "entries": entries,
        }

        body = (
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
            + "\n"
        )

        temp = directory / (".history." + uuid.uuid4().hex + ".tmp")

        try:
            with temp.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())

            os.replace(temp, path)
        finally:
            if temp.exists():
                temp.unlink()

    def list_entries(self, *, contract_key):
        """Returns the persisted, ordered entries exactly as stored."""

        safe_contract_key = _safe_segment(
            contract_key,
            error="QCC_CONTRACT_WATCHER_HISTORY_CONTRACT_KEY_INVALID",
        )

        path = self.history_path(contract_key=safe_contract_key)

        with self._lock:
            return self._read(path, contract_key=safe_contract_key)

    def register_observation(
        self,
        *,
        contract_key,
        evidence_id,
        watch_state,
        severity,
        created_at,
        semantic_signature,
        policy,
    ):
        """Appends one validated observation, or replays it idempotently.

        Ordering is trusted from ``created_at`` (already validated by
        ``build_contract_watcher_evidence``/``validate_contract_watcher_evidence``
        upstream): an observation whose ``created_at`` does not come
        strictly after the last persisted entry's ``created_at`` is
        rejected instead of silently reordered, unless it is an exact
        replay of an already-persisted ``evidence_id`` (idempotent,
        never double-counted).
        """

        if not isinstance(policy, ContractWatcherConfirmationPolicy):
            raise TypeError(
                "QCC_CONTRACT_WATCHER_HISTORY_POLICY_REQUIRED"
            )

        safe_contract_key = _safe_segment(
            contract_key,
            error="QCC_CONTRACT_WATCHER_HISTORY_CONTRACT_KEY_INVALID",
        )

        evidence_id = _safe_segment(
            evidence_id,
            error="QCC_CONTRACT_WATCHER_HISTORY_EVIDENCE_ID_INVALID",
        )

        path = self.history_path(contract_key=safe_contract_key)

        with self._lock:
            entries = self._read(path, contract_key=safe_contract_key)

            existing = next(
                (
                    entry
                    for entry in entries
                    if entry.get("evidence_id") == evidence_id
                ),
                None,
            )

            if existing is not None:
                return {
                    "created": False,
                    "contract_key": safe_contract_key,
                    "entry": deepcopy(existing),
                    "history_length": len(entries),
                }

            new_timestamp = _parse_timestamp(
                created_at,
                error="QCC_CONTRACT_WATCHER_HISTORY_CREATED_AT_INVALID",
            )

            if entries:
                last = entries[-1]

                last_timestamp = _parse_timestamp(
                    last["created_at"],
                    error="QCC_CONTRACT_WATCHER_HISTORY_CREATED_AT_INVALID",
                )

                if new_timestamp <= last_timestamp:
                    raise ContractWatcherHistoryOutOfOrderError(
                        "QCC_CONTRACT_WATCHER_HISTORY_OUT_OF_ORDER"
                    )

                state = ContractWatcherConfirmationState(
                    streak_signature=last["streak_signature"],
                    streak_count=last["streak_count"],
                )
            else:
                state = ContractWatcherConfirmationState()

            next_state, lifecycle_state = apply_confirmation_step(
                state=state,
                watch_state=watch_state,
                semantic_signature=semantic_signature,
                policy=policy,
            )

            entry = {
                "sequence_index": len(entries),
                "evidence_id": evidence_id,
                "created_at": created_at,
                "watch_state": watch_state,
                "severity": severity,
                "semantic_signature": semantic_signature,
                "policy": policy.to_dict(),
                "lifecycle_state": lifecycle_state,
                "streak_signature": next_state.streak_signature,
                "streak_count": next_state.streak_count,
            }

            entries.append(entry)

            self._write(path, contract_key=safe_contract_key, entries=entries)

            return {
                "created": True,
                "contract_key": safe_contract_key,
                "entry": deepcopy(entry),
                "history_length": len(entries),
            }

    def current_status(self, *, contract_key):
        """Cheap read of the last persisted decision (no replay)."""

        entries = self.list_entries(contract_key=contract_key)

        if not entries:
            return {
                "contract_key": contract_key,
                "lifecycle_state": None,
                "streak_signature": None,
                "streak_count": 0,
                "last_evidence_id": None,
                "history_length": 0,
                "entries": [],
            }

        last = entries[-1]

        return {
            "contract_key": contract_key,
            "lifecycle_state": last["lifecycle_state"],
            "streak_signature": last["streak_signature"],
            "streak_count": last["streak_count"],
            "last_evidence_id": last["evidence_id"],
            "history_length": len(entries),
            "entries": entries,
        }

    def reconstruct(self, *, contract_key):
        """Recomputes lifecycle state purely from durable entries.

        Replays ``apply_confirmation_step`` from scratch over the
        persisted entries (each using its own persisted policy) and
        fails closed if the replay disagrees with what was persisted at
        append time — this is what makes ``CHANGE_CONFIRMED`` reproducible
        after a process restart instead of depending on any in-memory
        counter.
        """

        entries = self.list_entries(contract_key=contract_key)

        state = ContractWatcherConfirmationState()
        timeline = []

        for entry in entries:
            policy = confirmation_policy_from_dict(entry.get("policy"))

            state, lifecycle_state = apply_confirmation_step(
                state=state,
                watch_state=entry["watch_state"],
                semantic_signature=entry["semantic_signature"],
                policy=policy,
            )

            if (
                lifecycle_state != entry["lifecycle_state"]
                or state.streak_signature != entry["streak_signature"]
                or state.streak_count != entry["streak_count"]
            ):
                raise ValueError(
                    "QCC_CONTRACT_WATCHER_HISTORY_RECONSTRUCTION_MISMATCH"
                )

            timeline.append(deepcopy(entry))

        return {
            "contract_key": contract_key,
            "timeline": timeline,
            "lifecycle_state": (
                timeline[-1]["lifecycle_state"] if timeline else None
            ),
            "streak_signature": state.streak_signature,
            "streak_count": state.streak_count,
        }
