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
building new evidence, ``run_contract_watcher_cycle`` fails closed with
``ContractWatcherBaselineIdentityError`` if either:

- the caller-supplied ``baseline_reference`` no longer matches the
  ``before_reference`` recorded on the *already-persisted* 1A evidence
  behind the contract's last history entry (identity changed; read from
  durable storage, never an in-memory cache), or
- the caller-supplied ``baseline_reference`` matches but
  ``baseline_contract`` is no longer canonically identical to the
  baseline content this module itself durably pinned the first time
  that reference was used for this ``contract_key`` (the same reference
  was reused for different content).

The second check is deliberately *not* based on
``before_functional_fingerprint`` (1A's functional-state identity):
that fingerprint exists to answer "is this the same functional UI
state" (tabs/dialogs/active regions) and, by design, ignores plain
structural additions/removals that never touch functional state — so
two baselines with different elements can legitimately share the same
functional fingerprint. Reusing it here would silently let a
same-reference baseline drift in content. Instead, this module derives
its own pipeline-level, deterministic ``build_baseline_content_signature``
over the already-normalized Site Contract (the same canonical payload
1A itself normalizes via ``build_normalized_snapshot_payload`` /
schema-version validation), excludes only the genuinely incidental
``captured_at`` capture instant, and durably pins
``(contract_key, baseline_reference) -> signature`` the first time a
reference is used, colocated with (but never mutating) the 1B history
store.

Neither drift check ever reaches 1B, so a changed baseline can never
silently inherit or extend an existing confirmation streak. This module
never advances/replaces a baseline itself: recovering from a rejected
cycle (starting a new confirmation sequence with a new baseline) is an
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
from pathlib import Path
import hashlib
import json
import os
import threading
import uuid

from backend.automation.site_architecture.models import SiteArchitectureSnapshot
from backend.automation.site_architecture.schema import (
    require_supported_schema_version,
)
from backend.automation.site_architecture.snapshot import (
    build_normalized_snapshot_payload,
)

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
from .contract_watcher_store import _safe_segment


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


# ---------------------------------------------------------------------------
# Pipeline-level baseline content identity.
#
# 1A/1B never persist the raw ``before``/``after`` Site Contract, only the
# comparison result plus 1A's functional-state fingerprint (a deliberately
# narrow, purpose-built identity — see module docstring). Detecting whether
# a caller-supplied ``baseline_reference`` was reused for genuinely
# different baseline content therefore needs its own, pipeline-owned,
# canonical content identity and its own minimal durable pin — never a new
# Site Architecture schema, never a broad revision store.
# ---------------------------------------------------------------------------

_BASELINE_IDENTITY_FILENAME = "baseline_identity.json"

_BASELINE_IDENTITY_SCHEMA_VERSION = 1

_BASELINE_IDENTITY_RECORD_TYPE = "QCC_CONTRACT_WATCHER_BASELINE_IDENTITY"

_BASELINE_CONTENT_SIGNATURE_NAMESPACE = "QCC_CONTRACT_WATCHER_BASELINE_CONTENT_V1\0"

# The DOM capture instant is genuinely incidental capture metadata: it
# necessarily differs between two captures of byte-identical content and
# is already excluded from every other content-addressed identity in this
# evidence family (``contract_watcher._evidence_id`` excludes ``created_at``
# the same way). No other Site Contract field is excluded: a baseline
# content signature must be a full, conservative identity of the
# already-normalized contract, not a redefinition of 1A's narrower
# functional-state fingerprint.
_INCIDENTAL_BASELINE_CONTRACT_KEYS = frozenset({"captured_at"})

_baseline_identity_lock = threading.RLock()


def _canonical_baseline_contract_payload(contract):
    if isinstance(contract, SiteArchitectureSnapshot):
        payload = build_normalized_snapshot_payload(contract)
    elif isinstance(contract, dict):
        require_supported_schema_version(contract.get("schema_version"))
        payload = contract
    else:
        raise ValueError(
            "QCC_CONTRACT_WATCHER_TARGET_BASELINE_CONTRACT_INVALID"
        )

    return {
        key: value
        for key, value in payload.items()
        if key not in _INCIDENTAL_BASELINE_CONTRACT_KEYS
    }


def build_baseline_content_signature(contract):
    """Deterministic, PII-safe canonical identity of a baseline contract.

    Accepts a ``SiteArchitectureSnapshot`` or an already-normalized dict
    (same acceptance rule as ``build_contract_watcher_evidence``). Two
    calls with canonically identical normalized content (ignoring only
    ``captured_at``) always return the same signature, regardless of
    Python object identity; any other structural difference — including
    differences the narrower functional-state fingerprint does not
    track, such as a purely additive element — always changes it.
    """

    canonical_payload = _canonical_baseline_contract_payload(contract)

    canonical = json.dumps(
        canonical_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(
        (_BASELINE_CONTENT_SIGNATURE_NAMESPACE + canonical).encode("utf-8")
    ).hexdigest()


def _baseline_identity_path(*, root, contract_key):
    safe_contract_key = _safe_segment(
        contract_key,
        error="QCC_CONTRACT_WATCHER_CYCLE_CONTRACT_KEY_INVALID",
    )

    return Path(root) / safe_contract_key / _BASELINE_IDENTITY_FILENAME


def _read_baseline_identity(path):
    if not path.is_file():
        return None

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractWatcherCycleError(
            "QCC_CONTRACT_WATCHER_CYCLE_BASELINE_IDENTITY_STORE_INVALID"
        ) from exc

    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != _BASELINE_IDENTITY_SCHEMA_VERSION
        or payload.get("record_type") != _BASELINE_IDENTITY_RECORD_TYPE
        or not payload.get("baseline_reference")
        or not payload.get("baseline_content_signature")
    ):
        raise ContractWatcherCycleError(
            "QCC_CONTRACT_WATCHER_CYCLE_BASELINE_IDENTITY_STORE_INVALID"
        )

    return payload


def _write_baseline_identity(
    path, *, contract_key, baseline_reference, baseline_content_signature
):
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)

    payload = {
        "schema_version": _BASELINE_IDENTITY_SCHEMA_VERSION,
        "record_type": _BASELINE_IDENTITY_RECORD_TYPE,
        "contract_key": contract_key,
        "baseline_reference": baseline_reference,
        "baseline_content_signature": baseline_content_signature,
    }

    body = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
        + "\n"
    )

    temp = directory / (".baseline_identity." + uuid.uuid4().hex + ".tmp")

    try:
        with temp.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def _enforce_pinned_baseline_content(*, target, history_store):
    """Fails closed if ``baseline_reference`` is reused for different content.

    Restart-safe: persisted at
    ``<history_store.root>/<contract_key>/baseline_identity.json``,
    colocated with (but never mutated by) the 1B history store, and
    independent of the 1A evidence schema. The pin is established the
    first time a ``(contract_key, baseline_reference)`` pair is seen and
    never silently replaced afterwards while that reference is reused.
    """

    baseline_content_signature = build_baseline_content_signature(
        target.baseline_contract
    )

    path = _baseline_identity_path(
        root=history_store.root, contract_key=target.contract_key
    )

    with _baseline_identity_lock:
        pinned = _read_baseline_identity(path)

        if (
            pinned is not None
            and pinned["baseline_reference"] == target.baseline_reference
        ):
            if pinned["baseline_content_signature"] != baseline_content_signature:
                raise ContractWatcherBaselineIdentityError(
                    "QCC_CONTRACT_WATCHER_CYCLE_BASELINE_CONTENT_DRIFT"
                )

            return

        _write_baseline_identity(
            path,
            contract_key=target.contract_key,
            baseline_reference=target.baseline_reference,
            baseline_content_signature=baseline_content_signature,
        )


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


def _pinned_baseline_reference(*, target, evidence_store, history_store):
    """Reads the baseline reference behind the contract's last evidence.

    Returns ``None`` when this is the first observation of a new
    confirmation sequence (nothing to pin against yet).
    """

    status = history_store.current_status(contract_key=target.contract_key)

    if not status["history_length"]:
        return None

    last_evidence = evidence_store.get(
        contract_key=target.contract_key,
        evidence_id=status["last_evidence_id"],
    )

    if last_evidence is None:
        raise ContractWatcherCycleError(
            "QCC_CONTRACT_WATCHER_CYCLE_HISTORY_EVIDENCE_MISSING"
        )

    return last_evidence["before_reference"]


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

    pinned_reference = _pinned_baseline_reference(
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

    _enforce_pinned_baseline_content(
        target=target,
        history_store=resolved_history_store,
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
