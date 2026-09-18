"""QCC Contract Watcher — historical confirmation lifecycle API (1B).

Small, provider-neutral, deterministic entry points that turn repeated
validated ``contract_watcher`` evidence into a governed lifecycle
decision (NO_CHANGE / CHANGE_SUSPECTED / CHANGE_CONFIRMED /
VALIDATION_REQUIRED) for one watched logical contract (``contract_key``).

This module does not open a browser, does not schedule anything and
does not decide REBUILD_REQUIRED: it only evaluates and durably records
one observation at a time and lets a caller read the resulting
lifecycle status. Rebuild policy is an explicit, deliberately deferred
downstream extension point (see ``evaluate_and_register_contract_watcher_observation``).
"""

from __future__ import annotations

from .contract_watcher import validate_contract_watcher_evidence
from .contract_watcher_confirmation import (
    RAW_OBSERVATION_WATCH_STATES,
    ContractWatcherConfirmationPolicy,
    compute_semantic_change_signature,
)
from .contract_watcher_history_store import ContractWatcherHistoryStore
from .contract_watcher_store import ContractWatcherEvidenceStore


_DEFAULT_EVIDENCE_STORE = ContractWatcherEvidenceStore()

_DEFAULT_HISTORY_STORE = ContractWatcherHistoryStore()


def get_default_contract_watcher_evidence_store():
    return _DEFAULT_EVIDENCE_STORE


def get_default_contract_watcher_history_store():
    return _DEFAULT_HISTORY_STORE


def evaluate_and_register_contract_watcher_observation(
    evidence,
    *,
    policy,
    evidence_store=None,
    history_store=None,
):
    """Registers one validated observation and returns its lifecycle decision.

    ``evidence`` must be a record produced by
    ``build_contract_watcher_evidence`` (or an equivalent already
    validated/persisted evidence dict) — never raw HTML, screenshots or
    browser state. ``policy`` is mandatory and explicit: there is no
    hidden default confirmation threshold.

    The evidence is first persisted through the existing
    ``ContractWatcherEvidenceStore`` (idempotent by evidence identity,
    exactly as in 1A), then a deterministic semantic change signature is
    computed and one confirmation step is durably appended to this
    contract's history. Replaying the exact same evidence again is a
    no-op: the previously recorded decision is returned unchanged and
    the confirmation streak is never double-counted.

    Only NO_CHANGE, CHANGE_SUSPECTED and VALIDATION_REQUIRED are valid
    raw inputs (the vocabulary a single pairwise comparison may
    produce); CHANGE_CONFIRMED/REBUILD_REQUIRED evidence fails closed
    here because those are lifecycle-only outcomes, never comparison
    input.

    Structural severity (COSMETIC/NON_BREAKING/CONTRACT_CHANGE/BREAKING)
    is recorded for inspection but never consulted by the confirmation
    algorithm itself, so it can never shorten or bypass the configured
    threshold, and a resulting CHANGE_CONFIRMED — however severe — never
    automatically becomes REBUILD_REQUIRED; that remains an explicit,
    separate, deliberately deferred governed policy decision.
    """

    if not isinstance(policy, ContractWatcherConfirmationPolicy):
        raise TypeError(
            "QCC_CONTRACT_WATCHER_LIFECYCLE_POLICY_REQUIRED"
        )

    canonical = validate_contract_watcher_evidence(evidence)

    if canonical["watch_state"] not in RAW_OBSERVATION_WATCH_STATES:
        raise ValueError(
            "QCC_CONTRACT_WATCHER_LIFECYCLE_WATCH_STATE_UNSUPPORTED"
        )

    store = evidence_store or get_default_contract_watcher_evidence_store()
    history = history_store or get_default_contract_watcher_history_store()

    persisted_evidence = store.save(canonical)

    semantic_signature = compute_semantic_change_signature(persisted_evidence)

    return history.register_observation(
        contract_key=persisted_evidence["contract_key"],
        evidence_id=persisted_evidence["evidence_id"],
        watch_state=persisted_evidence["watch_state"],
        severity=persisted_evidence["severity"],
        created_at=persisted_evidence["created_at"],
        semantic_signature=semantic_signature,
        policy=policy,
    )


def get_contract_watcher_lifecycle_status(contract_key, *, history_store=None):
    """Cheap read of the current lifecycle status for a watched contract."""

    history = history_store or get_default_contract_watcher_history_store()

    return history.current_status(contract_key=contract_key)


def reconstruct_contract_watcher_lifecycle(contract_key, *, history_store=None):
    """Recomputes the lifecycle status purely from durable history.

    Independent of any in-memory counter and independent of the calling
    process's lifetime: after a restart, calling this against the same
    ``history_store`` root reproduces the exact same
    ``CHANGE_CONFIRMED``/streak state, or raises if the persisted history
    has been tampered with in a way that no longer replays consistently.
    """

    history = history_store or get_default_contract_watcher_history_store()

    return history.reconstruct(contract_key=contract_key)
