"""QCC Contract Watcher — governed observation pipeline (1C).

This module is the provider-neutral, scheduler-ready orchestration layer
requested by Work Order QCC-CONTRACT-WATCHER-1C. It does not run a
browser, does not observe REAL sites, does not build a second Site
Architecture model and does not schedule anything itself. It only wires
together the already-accepted 1A evidence layer
(``contract_watcher.build_contract_watcher_evidence`` /
``contract_watcher_store.ContractWatcherEvidenceStore``) and the
already-accepted 1B lifecycle layer
(``contract_watcher_lifecycle.evaluate_and_register_contract_watcher_observation``
/ ``contract_watcher_history_store.ContractWatcherHistoryStore``) into one
governed single-cycle entry point plus a deterministic batch runner.

Baseline pinning
-----------------

1A/1B are pairwise-comparison-agnostic: they never require ``before`` to
be a stable "trusted baseline" across a confirmation sequence — the
caller of ``build_contract_watcher_evidence`` may legitimately compare
any two observations. Left ungoverned, a caller could accidentally drift
into a *rolling* previous-observation-to-current-observation comparison
(baseline A -> changed B -> unchanged B), which would report NO_CHANGE
for the third step and destroy the persistence evidence 1B exists to
capture.

This module closes that gap without touching 1A/1B: every
``ContractWatcherWatchTarget`` carries an explicit, caller-supplied
``baseline_reference`` (an opaque, durable observation/capture/revision
identifier — never a timestamp) and a ``baseline_contract`` that is
compared against on every cycle for that logical contract. Before
building new evidence, ``run_contract_watcher_cycle`` reads the
*already-persisted* evidence behind the contract's last history entry
(never an in-memory cache) and fails closed with
``ContractWatcherBaselineIdentityError`` if either:

- the caller-supplied ``baseline_reference`` no longer matches the
  ``before_reference`` recorded on that last persisted evidence
  (identity changed), or
- the caller-supplied ``baseline_reference`` matches but the freshly
  computed ``before_functional_fingerprint`` for ``baseline_contract``
  no longer matches the one recorded on that last persisted evidence
  (the same reference was reused for different content).

Neither case ever reaches 1B, so a changed baseline can never silently
inherit or extend an existing confirmation streak. This module never
advances/replaces a baseline itself: recovering from a rejected cycle
(starting a new confirmation sequence with a new baseline) is an
explicit, deliberately deferred governed decision outside this Work
Order's scope.

Deferred (explicitly out of scope for this Work Order): periodic
scheduling/timers, browser/SeleniumBase/CDP capture, Mercurio-specific
logic, Selector Self-Healing, alerts/notifications, Expected-vs-Observed
Graph, automatic Twin rebuild, REBUILD_REQUIRED policy, Flet UI, network
interception, JavaScript analysis and schema-requiredness extensions.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .contract_watcher import (
    DEFAULT_GEOMETRY_TOLERANCE_PX,
    build_contract_watcher_evidence,
)
from .contract_watcher_confirmation import ContractWatcherConfirmationPolicy
from .contract_watcher_lifecycle import (
    evaluate_and_register_contract_watcher_observation,
    get_default_contract_watcher_evidence_store,
    get_default_contract_watcher_history_store,
)


def _required_text(value, *, error):
    result = str(value or "").strip()

    if not result:
        raise ValueError(error)

    return result


class ContractWatcherCycleOutcome(str, Enum):
    """Explicit, scheduler/UI-facing outcome of one governed cycle."""

    OBSERVATION_REGISTERED = "OBSERVATION_REGISTERED"
    OBSERVATION_REPLAYED = "OBSERVATION_REPLAYED"


class ContractWatcherCycleError(ValueError):
    """Base class for governed, expected 1C cycle validation failures.

    Deliberately a ``ValueError`` subclass (not a bare ``Exception``) so
    that it is caught only by code that explicitly opts in
    (``run_contract_watcher_cycle_batch``), never by accident, and never
    masks unrelated bugs.
    """


class ContractWatcherBaselineIdentityError(ContractWatcherCycleError):
    """Raised when a cycle would silently change a pinned baseline identity."""


@dataclass(frozen=True)
class ContractWatcherWatchTarget:
    """Immutable, provider-neutral description of what to watch and how.

    ``baseline_reference`` must be a durable opaque observation/capture/
    revision identifier for the trusted baseline contract — never a
    timestamp. ``baseline_contract`` is the corresponding normalized Site
    Contract (a ``SiteArchitectureSnapshot`` or an already-normalized
    dict, exactly as accepted by ``build_contract_watcher_evidence``).
    """

    contract_key: str
    baseline_reference: str
    baseline_contract: object
    confirmation_policy: ContractWatcherConfirmationPolicy
    geometry_tolerance_px: float = DEFAULT_GEOMETRY_TOLERANCE_PX

    def __post_init__(self):
        object.__setattr__(
            self,
            "contract_key",
            _required_text(
                self.contract_key,
                error="QCC_CONTRACT_WATCHER_TARGET_CONTRACT_KEY_REQUIRED",
            ),
        )

        object.__setattr__(
            self,
            "baseline_reference",
            _required_text(
                self.baseline_reference,
                error="QCC_CONTRACT_WATCHER_TARGET_BASELINE_REFERENCE_REQUIRED",
            ),
        )

        if self.baseline_contract is None:
            raise ValueError(
                "QCC_CONTRACT_WATCHER_TARGET_BASELINE_CONTRACT_REQUIRED"
            )

        if not isinstance(
            self.confirmation_policy, ContractWatcherConfirmationPolicy
        ):
            raise TypeError(
                "QCC_CONTRACT_WATCHER_TARGET_CONFIRMATION_POLICY_REQUIRED"
            )


@dataclass(frozen=True)
class ContractWatcherObservationInput:
    """Immutable, provider-neutral description of one current observation.

    ``observation_reference`` must be a durable opaque observation/
    capture/revision identifier for the current, physically distinct
    observation — never a timestamp. Two calls with the same
    ``observation_reference`` and content are treated as the exact same
    physical observation (idempotent replay); a new
    ``observation_reference`` for the same semantic divergence is a
    separate, confirmation-eligible observation.
    """

    observation_reference: str
    observation_contract: object
    observed_at: str | None = None

    def __post_init__(self):
        object.__setattr__(
            self,
            "observation_reference",
            _required_text(
                self.observation_reference,
                error="QCC_CONTRACT_WATCHER_OBSERVATION_REFERENCE_REQUIRED",
            ),
        )

        if self.observation_contract is None:
            raise ValueError(
                "QCC_CONTRACT_WATCHER_OBSERVATION_CONTRACT_REQUIRED"
            )


@dataclass(frozen=True)
class ContractWatcherCycleRequest:
    """One independent unit of work for ``run_contract_watcher_cycle_batch``."""

    target: ContractWatcherWatchTarget
    observation: ContractWatcherObservationInput
    request_id: str | None = None

    def __post_init__(self):
        if not isinstance(self.target, ContractWatcherWatchTarget):
            raise TypeError("QCC_CONTRACT_WATCHER_CYCLE_REQUEST_TARGET_INVALID")

        if not isinstance(self.observation, ContractWatcherObservationInput):
            raise TypeError(
                "QCC_CONTRACT_WATCHER_CYCLE_REQUEST_OBSERVATION_INVALID"
            )


def _pinned_baseline(*, target, evidence_store, history_store):
    """Reads the baseline identity behind the contract's last evidence.

    Returns ``(pinned_reference, pinned_fingerprint)``, both ``None`` when
    this is the first observation of a new confirmation sequence (nothing
    to pin against yet).
    """

    status = history_store.current_status(contract_key=target.contract_key)

    if not status["history_length"]:
        return None, None

    last_evidence = evidence_store.get(
        contract_key=target.contract_key,
        evidence_id=status["last_evidence_id"],
    )

    if last_evidence is None:
        raise ContractWatcherCycleError(
            "QCC_CONTRACT_WATCHER_CYCLE_HISTORY_EVIDENCE_MISSING"
        )

    return (
        last_evidence["before_reference"],
        last_evidence["before_functional_fingerprint"],
    )


def run_contract_watcher_cycle(
    target,
    observation,
    *,
    evidence_store=None,
    history_store=None,
):
    """Runs exactly one governed observation cycle for one watch target.

    Validates ``target``/``observation``, enforces baseline-identity
    continuity against durable history, builds 1A evidence pinned to
    ``target.baseline_reference``, persists it, applies 1B lifecycle
    history and returns a deterministic structured cycle receipt.

    Performs no browser automation, no scheduling, no network access and
    no sleeping/polling/retrying. Raises ``TypeError``/``ValueError`` (or
    the more specific ``ContractWatcherBaselineIdentityError``) instead of
    ever returning a false ``NO_CHANGE``/success receipt for malformed or
    ungoverned input.
    """

    if not isinstance(target, ContractWatcherWatchTarget):
        raise TypeError("QCC_CONTRACT_WATCHER_CYCLE_TARGET_INVALID")

    if not isinstance(observation, ContractWatcherObservationInput):
        raise TypeError("QCC_CONTRACT_WATCHER_CYCLE_OBSERVATION_INVALID")

    resolved_evidence_store = (
        evidence_store or get_default_contract_watcher_evidence_store()
    )

    resolved_history_store = (
        history_store or get_default_contract_watcher_history_store()
    )

    pinned_reference, pinned_fingerprint = _pinned_baseline(
        target=target,
        evidence_store=resolved_evidence_store,
        history_store=resolved_history_store,
    )

    if (
        pinned_reference is not None
        and pinned_reference != target.baseline_reference
    ):
        raise ContractWatcherBaselineIdentityError(
            "QCC_CONTRACT_WATCHER_CYCLE_BASELINE_IDENTITY_CHANGED"
        )

    evidence = build_contract_watcher_evidence(
        contract_key=target.contract_key,
        before=target.baseline_contract,
        after=observation.observation_contract,
        before_reference=target.baseline_reference,
        after_reference=observation.observation_reference,
        geometry_tolerance_px=target.geometry_tolerance_px,
        created_at=observation.observed_at,
    )

    if (
        pinned_fingerprint is not None
        and evidence["before_functional_fingerprint"] != pinned_fingerprint
    ):
        raise ContractWatcherBaselineIdentityError(
            "QCC_CONTRACT_WATCHER_CYCLE_BASELINE_CONTENT_DRIFT"
        )

    registration = evaluate_and_register_contract_watcher_observation(
        evidence,
        policy=target.confirmation_policy,
        evidence_store=resolved_evidence_store,
        history_store=resolved_history_store,
    )

    entry = registration["entry"]

    outcome = (
        ContractWatcherCycleOutcome.OBSERVATION_REGISTERED
        if registration["created"]
        else ContractWatcherCycleOutcome.OBSERVATION_REPLAYED
    )

    return {
        "contract_key": target.contract_key,
        "baseline_reference": target.baseline_reference,
        "observation_reference": observation.observation_reference,
        "evidence_id": entry["evidence_id"],
        "semantic_signature": entry["semantic_signature"],
        "watch_state": entry["watch_state"],
        "severity": entry["severity"],
        "lifecycle_state": entry["lifecycle_state"],
        "streak_signature": entry["streak_signature"],
        "streak_count": entry["streak_count"],
        "policy": entry["policy"],
        "history_length": registration["history_length"],
        "outcome": outcome.value,
    }


def run_contract_watcher_cycle_batch(
    requests,
    *,
    evidence_store=None,
    history_store=None,
):
    """Runs a finite, caller-supplied collection of independent cycles.

    Processes ``requests`` sequentially in stable input order. Never
    sleeps, polls, retries, spawns threads/processes, launches browsers
    or accesses the network — it is scheduler-ready plumbing, not a
    scheduler.

    Failure policy (documented, not incidental): a governed, expected
    per-target rejection (``ContractWatcherCycleError`` and subclasses,
    e.g. malformed evidence input or a rejected baseline-identity change)
    is recorded as an explicit per-target failure and processing
    continues with the remaining independent requests. Anything else
    (a structurally invalid ``requests`` collection/item, or any
    unexpected exception) is never caught here and aborts the whole batch
    immediately — it is a caller/programming defect, not a business-rule
    rejection, and must never be hidden or silently downgraded to a false
    ``NO_CHANGE``.
    """

    if not isinstance(requests, (list, tuple)):
        raise TypeError("QCC_CONTRACT_WATCHER_BATCH_REQUESTS_INVALID")

    resolved_evidence_store = (
        evidence_store or get_default_contract_watcher_evidence_store()
    )

    resolved_history_store = (
        history_store or get_default_contract_watcher_history_store()
    )

    results = []
    failures = []
    lifecycle_counts = {}

    for index, request in enumerate(requests):
        if not isinstance(request, ContractWatcherCycleRequest):
            raise TypeError("QCC_CONTRACT_WATCHER_BATCH_REQUEST_INVALID")

        request_id = request.request_id or request.target.contract_key

        try:
            receipt = run_contract_watcher_cycle(
                request.target,
                request.observation,
                evidence_store=resolved_evidence_store,
                history_store=resolved_history_store,
            )
        except ContractWatcherCycleError as exc:
            failures.append({
                "index": index,
                "request_id": request_id,
                "contract_key": request.target.contract_key,
                "error": str(exc),
            })
            continue

        lifecycle_counts[receipt["lifecycle_state"]] = (
            lifecycle_counts.get(receipt["lifecycle_state"], 0) + 1
        )

        results.append(receipt)

    return {
        "requested": len(requests),
        "processed": len(results),
        "failed": len(failures),
        "results": results,
        "failures": failures,
        "lifecycle_counts": lifecycle_counts,
    }
