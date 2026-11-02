"""FCP-10C-01: Advisory allocation and effective limits with FCP-9 - pure,
deterministic, fail-closed, provider-neutral, NON-AUTHORITATIVE.

Answers ONE question: given the FCP-9C-01 capacity question the caller
already asks (`CapacityRequest`) and the FCP-10 A/B evidence over the same
instant (A02 quota observation, B01 host resources, optional B02 budgets,
optional A01 concurrency policy), how far must `max_workers` and each
provider limit be NARROWED, which pending workers would then fill the
remaining slots in the Runner's own order, and - when quotas are exhausted -
which workers stay replannable on the provider they ALREADY have? It never
answers "may I dispatch now?".

Why this is a consultative composition, not a second dispatcher
----------------------------------------------------------------
* Director and Runner stay the ONLY execution and Git authorities. The
  Runner's own `PipelineRunner._start_ready` (`max_workers`,
  `provider_limits`, `_provider_start_held`, `_same_worktree_conflict`,
  write leases) decides at execution time. Nothing here starts, queues,
  leases, reserves, retries, runs a blueprint, switches or reassigns a
  provider, proposes a fallback, buys, subscribes, calls a remote API, runs a
  process or touches Git, the filesystem, the clock, the environment or the
  network: no pool, lease, ledger, gateway or store of its own exists.
* Composition, not duplication: every input goes through its own pure
  evaluator exactly as is - FCP-9C-01 `evaluate_capacity`, FCP-10A-02
  `adapt_observations`, FCP-10B-01 `evaluate_resources`, FCP-10B-02
  `evaluate_budget` - and the A01 policy through the contract's own
  validation. The B01 request must be bound to the very base `CapacityPlan`
  evaluated here and every evidence request to the same instant.
* Only narrowing: the base is the FCP-9 plan's `effective_max_workers` /
  `effective_provider_limits`. Each FCP-10 source yields a headroom (new
  starts that still fit) and every effective limit is
  `min(base, occupied + headroom)`. The narrowed limits are handed back to
  `evaluate_capacity` as its own `max_workers` / `provider_limits` (which it
  only ever lowers), so priority, dependency, provider hold, resource group
  and worktree exclusivity decisions remain FCP-9's. A limit of 0 is not
  representable to FCP-9 / the Runner (`runner_*` None): the FCP-10 hold
  then withdraws the worker's slot; a withdrawn slot is never handed to
  another worker in the same evaluation.
* Order and tie-break are FCP-9's (`TIE_BREAK`): highest `priority` first,
  then declared worker order; slots are 0..n-1 in that order.
* Fail closed: AUTH_BLOCKED, QUOTA_WAIT, uncertain quota evidence, unknown
  resources, unknown or missing budgets never enable a slot, and their
  evidence ids / eligibility instant are echoed. Budgets are sized only
  through a reservation of the provider itself (one `BudgetRequest` per
  provider once any budget is declared); a shared (non-provider) budget is
  divided by the LARGEST reservation of the providers it serves.
* Quota exhaustion: workers stay on the provider they already have
  (`active_provider`, else the declared one). `replannable` lists pending
  workers whose own provider is apt; `quota_held` those whose own provider
  is quota-waiting or auth-blocked. No alternative is ever proposed.

Verdicts (contract `VERDICTS`, none is a permit) per provider and global:
REFUSE > UNKNOWN > WAIT > READY. Worker decisions reuse FCP-9C-01's:
INACTIVE > REFUSED > UNKNOWN > WAITING > SCHEDULABLE. Output
(`AllocationPlan`, schema `fcp10c01-resource-quota-allocation-plan-v1`)
holds only validated ids, enumerated codes, integers and fingerprints, and
fixes every FCP-10A-01 zero-authority flag plus `provider_reassigned`,
`fallback_proposed`, `limits_relaxed` and `blueprint_run` to False as
read-only properties.
"""

from __future__ import annotations

import dataclasses
import hashlib
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

try:
    from scripts.ai import fabric_resource_quota_budget as bg
    from scripts.ai import fabric_resource_quota_contract as qc
    from scripts.ai import fabric_resource_quota_observation as qo
    from scripts.ai import fabric_resource_quota_resource as rr
    from scripts.ai import fabric_scheduler_capacity as cap
    from scripts.ai import fabric_scheduler_contract as sc
    from scripts.ai import fabric_scheduler_window as sw
except ImportError:  # pragma: no cover - direct script execution
    import fabric_resource_quota_budget as bg  # type: ignore[no-redef]
    import fabric_resource_quota_contract as qc  # type: ignore[no-redef]
    import fabric_resource_quota_observation as qo  # type: ignore[no-redef]
    import fabric_resource_quota_resource as rr  # type: ignore[no-redef]
    import fabric_scheduler_capacity as cap  # type: ignore[no-redef]
    import fabric_scheduler_contract as sc  # type: ignore[no-redef]
    import fabric_scheduler_window as sw  # type: ignore[no-redef]

REQUEST_SCHEMA = "fcp10c01-resource-quota-allocation-request-v1"
REQUEST_SCHEMA_VERSION = 1
SCHEMA = "fcp10c01-resource-quota-allocation-plan-v1"
SCHEMA_VERSION = 1
ALLOCATION_MARKER = "FCP10C01_ALLOCATION_ADVISORY_ONLY_NOT_CERTIFIED_NOT_AUTHORIZED"
TIE_BREAK = "PRIORITY_DESC_THEN_DECLARED_ORDER"

MAX_WORKERS = cap.MAX_WORKERS
MAX_BUDGET_REQUESTS = qc.MAX_PROVIDERS
MAX_CANONICAL_JSON_BYTES = cap.MAX_CANONICAL_JSON_BYTES

READY = qc.READY
WAIT = qc.WAIT
REFUSE = qc.REFUSE
UNKNOWN = qc.UNKNOWN
VERDICTS = qc.VERDICTS

# Worker decisions and plan outcomes (FCP-9C-01's own).
SCHEDULABLE = cap.SCHEDULABLE
WAITING = cap.WAITING
REFUSED = cap.REFUSED
INACTIVE = cap.INACTIVE
IDLE = cap.IDLE
DECISIONS = cap.DECISIONS
OUTCOMES = cap.OUTCOMES
_DECISION_OF_VERDICT = {READY: SCHEDULABLE, WAIT: WAITING, UNKNOWN: cap.UNKNOWN, REFUSE: REFUSED}
_SEVERITY = (SCHEDULABLE, WAITING, cap.UNKNOWN, REFUSED)

# Request-level refusal codes, in their fixed canonical order.
REQUEST_NOT_TYPED = qc.REQUEST_NOT_TYPED
SCHEMA_VERSION_UNSUPPORTED = qc.SCHEMA_VERSION_UNSUPPORTED
REQUEST_ID_INVALID = qc.REQUEST_ID_INVALID
ID_SECRET_SHAPED = qc.ID_SECRET_SHAPED
CAPACITY_REQUEST_REFUSED = "CAPACITY_REQUEST_REFUSED"
QUOTA_REQUEST_REFUSED = "QUOTA_REQUEST_REFUSED"
QUOTA_INSTANT_MISMATCH = "QUOTA_INSTANT_MISMATCH"
RESOURCE_REQUEST_NOT_TYPED = "RESOURCE_REQUEST_NOT_TYPED"
RESOURCE_PLAN_MISMATCH = "RESOURCE_PLAN_MISMATCH"
RESOURCE_INSTANT_MISMATCH = "RESOURCE_INSTANT_MISMATCH"
RESOURCE_REQUEST_REFUSED = "RESOURCE_REQUEST_REFUSED"
BUDGET_REQUESTS_MALFORMED = "BUDGET_REQUESTS_MALFORMED"
BUDGET_RESERVATION_MISSING = "BUDGET_RESERVATION_MISSING"
BUDGET_PROVIDER_UNKNOWN = "BUDGET_PROVIDER_UNKNOWN"
BUDGET_PROVIDER_DUPLICATE = "BUDGET_PROVIDER_DUPLICATE"
BUDGET_EVIDENCE_MISMATCH = "BUDGET_EVIDENCE_MISMATCH"
BUDGET_INSTANT_MISMATCH = "BUDGET_INSTANT_MISMATCH"
BUDGET_REQUEST_REFUSED = "BUDGET_REQUEST_REFUSED"
POLICY_REFUSED = "POLICY_REFUSED"
POLICY_LIMIT_NOT_CONCURRENT = "POLICY_LIMIT_NOT_CONCURRENT"
POLICY_PROVIDER_UNKNOWN = "POLICY_PROVIDER_UNKNOWN"
REQUEST_TOO_LARGE = qc.REQUEST_TOO_LARGE
REQUEST_REASONS = (
    REQUEST_NOT_TYPED, SCHEMA_VERSION_UNSUPPORTED, REQUEST_ID_INVALID, ID_SECRET_SHAPED, CAPACITY_REQUEST_REFUSED,
    QUOTA_REQUEST_REFUSED, QUOTA_INSTANT_MISMATCH, RESOURCE_REQUEST_NOT_TYPED, RESOURCE_PLAN_MISMATCH,
    RESOURCE_INSTANT_MISMATCH, RESOURCE_REQUEST_REFUSED, BUDGET_REQUESTS_MALFORMED, BUDGET_RESERVATION_MISSING,
    BUDGET_PROVIDER_UNKNOWN, BUDGET_PROVIDER_DUPLICATE, BUDGET_EVIDENCE_MISMATCH, BUDGET_INSTANT_MISMATCH,
    BUDGET_REQUEST_REFUSED, POLICY_REFUSED, POLICY_LIMIT_NOT_CONCURRENT, POLICY_PROVIDER_UNKNOWN, REQUEST_TOO_LARGE,
)

# Constraint reason codes (the contract's, FCP-9C-01's and FCP-10B-01's own
# where they exist), grouped by the verdict they force, in their fixed
# canonical order.
PROVIDER_AUTH_BLOCKED = qc.PROVIDER_AUTH_BLOCKED
RESERVATION_EXCEEDS_LIMIT = qc.RESERVATION_EXCEEDS_LIMIT
DEMAND_EXCEEDS_CAPACITY = rr.DEMAND_EXCEEDS_CAPACITY
QUOTA_EVIDENCE_UNCERTAIN = "QUOTA_EVIDENCE_UNCERTAIN"
RESOURCE_UNKNOWN = "RESOURCE_UNKNOWN"
BUDGET_UNKNOWN = "BUDGET_UNKNOWN"
BUDGET_EVIDENCE_MISSING = "BUDGET_EVIDENCE_MISSING"
PROVIDER_QUOTA_WAIT = qc.PROVIDER_QUOTA_WAIT
CAPACITY_FULL = cap.CAPACITY_FULL
PROVEN_SLOTS_SATURATED = "PROVEN_SLOTS_SATURATED"
RESOURCE_SATURATED = rr.RESOURCE_SATURATED
BUDGET_SATURATED = "BUDGET_SATURATED"
CONCURRENCY_LIMIT_SATURATED = "CONCURRENCY_LIMIT_SATURATED"
REFUSING_REASONS = (PROVIDER_AUTH_BLOCKED, RESERVATION_EXCEEDS_LIMIT, DEMAND_EXCEEDS_CAPACITY)
UNKNOWN_REASONS = (QUOTA_EVIDENCE_UNCERTAIN, RESOURCE_UNKNOWN, BUDGET_UNKNOWN, BUDGET_EVIDENCE_MISSING)
WAITING_REASONS = (PROVIDER_QUOTA_WAIT, CAPACITY_FULL, PROVEN_SLOTS_SATURATED, RESOURCE_SATURATED, BUDGET_SATURATED,
                   CONCURRENCY_LIMIT_SATURATED)
RESULT_REASONS = REFUSING_REASONS + UNKNOWN_REASONS + WAITING_REASONS
QUOTA_HOLD_REASONS = (PROVIDER_AUTH_BLOCKED, PROVIDER_QUOTA_WAIT)


def _ordered(codes, vocabulary) -> tuple:
    return sc._ordered(codes, vocabulary)


def _codes_ok(codes, vocabulary) -> bool:
    return (type(codes) is tuple and all(qc._in(c, vocabulary) for c in codes)
            and codes == _ordered(codes, vocabulary))


def _sorted_ids(values) -> bool:
    return (type(values) is tuple and all(qc._valid_id(v) for v in values)
            and list(values) == sorted(set(values)))


def _fingerprint_ok(value) -> bool:
    return type(value) is str and sc._FINGERPRINT_RE.fullmatch(value) is not None


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def verdict_for(reasons: tuple) -> str:
    """REFUSE > UNKNOWN > WAIT > READY."""
    if any(r in REFUSING_REASONS for r in reasons):
        return REFUSE
    if any(r in UNKNOWN_REASONS for r in reasons):
        return UNKNOWN
    return WAIT if reasons else READY


def decision_for(capacity_decision: str, reasons: tuple) -> str:
    """The FCP-9 decision, never improved: INACTIVE stays INACTIVE, else the
    more severe of it and the FCP-10 verdict of `reasons`."""
    if capacity_decision == INACTIVE:
        return INACTIVE
    overlay = _DECISION_OF_VERDICT[verdict_for(reasons)]
    return max(capacity_decision, overlay, key=_SEVERITY.index)


def _headroom_ok(reasons: tuple, headroom) -> bool:
    """No reason: at least one more start fits. Any reason: none does."""
    if not qc._bounded_int(headroom, 0, MAX_WORKERS):
        return False
    return headroom >= 1 if not reasons else headroom == 0


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AllocationRequest:
    """Explicit, immutable allocation question. `capacity_request` is the
    FCP-9C-01 question as is; `quota_request` (A02) and `resource_request`
    (B01, over the base plan) are required; `budget_requests` (B02, one per
    provider, each with that provider's reservation) and `quota_policy`
    (A01, CONCURRENT_EXECUTIONS limits) are optional. Validated by
    `allocate` (fail closed), not here."""
    request_id: str
    capacity_request: object
    quota_request: object
    resource_request: object
    budget_requests: tuple = ()
    quota_policy: Optional[object] = None
    schema_version: int = REQUEST_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProviderAllocation:
    """Effective limit of one provider. Construction re-derives the verdict
    and the limit, which never exceeds `base_limit`."""
    provider_id: str
    verdict: str
    reasons: tuple
    evidence_ids: tuple
    base_limit: int
    occupied: int
    headroom: int
    limit: int
    runner_limit: Optional[int]
    assigned: int
    quota_availability: Optional[str] = None
    next_eligible_utc: Optional[str] = None

    def __post_init__(self):
        if not sc._valid_provider_id(self.provider_id):
            raise ValueError("provider_id must be a valid provider id")
        if not _codes_ok(self.reasons, RESULT_REASONS):
            raise ValueError("reasons must be ordered result reason codes")
        if self.verdict != verdict_for(self.reasons):
            raise ValueError("verdict must be exactly the one derived from reasons")
        if not _sorted_ids(self.evidence_ids):
            raise ValueError("evidence_ids must be sorted unique ids")
        if not (qc._bounded_int(self.base_limit, 1, MAX_WORKERS) and qc._bounded_int(self.occupied, 0, cap.MAX_ITEMS)):
            raise ValueError("base_limit / occupied out of bounds")
        if not _headroom_ok(self.reasons, self.headroom):
            raise ValueError("headroom must match the reasons")
        if self.limit != min(self.base_limit, self.occupied + self.headroom):
            raise ValueError("limit must be min(base_limit, occupied + headroom)")
        if self.runner_limit != (self.limit if self.limit >= 1 else None):
            raise ValueError("runner_limit is the limit when the Runner can hold it")
        if not qc._bounded_int(self.assigned, 0, max(0, self.limit - self.occupied)):
            raise ValueError("assigned slots exceed the effective limit")
        if self.quota_availability is not None and not qc._in(self.quota_availability, qc.AVAILABILITY_STATES):
            raise ValueError("quota_availability must use the Router vocabulary")
        if self.next_eligible_utc is not None and (
                self.quota_availability != "QUOTA_WAIT" or not bg._normalized_utc(self.next_eligible_utc)):
            raise ValueError("only a quota wait echoes a normalized eligibility instant")

    def to_dict(self) -> dict:
        return {
            "provider_id": self.provider_id, "verdict": self.verdict, "reasons": list(self.reasons),
            "evidence_ids": list(self.evidence_ids), "base_limit": self.base_limit, "occupied": self.occupied,
            "headroom": self.headroom, "limit": self.limit, "runner_limit": self.runner_limit,
            "assigned": self.assigned, "quota_availability": self.quota_availability,
            "next_eligible_utc": self.next_eligible_utc,
        }


@dataclass(frozen=True)
class WorkerAllocation:
    """Per-worker advisory decision: FCP-9's own decision under the narrowed
    limits plus the FCP-10 reasons of its provider and of the whole batch.
    Construction re-derives `decision`, which can never be better than
    FCP-9's."""
    item_id: str
    state: str
    provider: str
    priority: int
    capacity_decision: str
    capacity_reasons: tuple
    reasons: tuple
    decision: str
    slot: Optional[int]
    replannable: bool

    def __post_init__(self):
        if not sc._safe_id(self.item_id):
            raise ValueError("item_id must be a safe id")
        if not qc._in(self.state, cap.NODE_STATES):
            raise ValueError("state must be an observed worker state")
        if not sc._valid_provider_id(self.provider) or not sc._is_int(self.priority):
            raise ValueError("provider / priority must be valid")
        if not (qc._in(self.capacity_decision, DECISIONS) and _codes_ok(self.capacity_reasons, cap.ITEM_REASONS)
                and self.capacity_decision == cap._classify(self.capacity_reasons)):
            raise ValueError("capacity decision must be FCP-9's own")
        if not _codes_ok(self.reasons, RESULT_REASONS):
            raise ValueError("reasons must be ordered result reason codes")
        if self.capacity_decision == INACTIVE and self.reasons:
            raise ValueError("an inactive worker carries no allocation reason")
        if self.decision != decision_for(self.capacity_decision, self.reasons):
            raise ValueError("decision must be exactly the one derived from FCP-9 and the reasons")
        if self.decision == SCHEDULABLE:
            if not qc._bounded_int(self.slot, 0, MAX_WORKERS - 1):
                raise ValueError("a SCHEDULABLE worker carries a slot")
        elif self.slot is not None:
            raise ValueError("only a SCHEDULABLE worker carries a slot")
        if type(self.replannable) is not bool:
            raise ValueError("replannable must be a bool")
        if self.replannable and (self.state not in cap._PENDING_STATES or self.decision in (INACTIVE, REFUSED)):
            raise ValueError("only a pending, non-refused worker is replannable")

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id, "state": self.state, "provider": self.provider, "priority": self.priority,
            "capacity_decision": self.capacity_decision, "capacity_reasons": list(self.capacity_reasons),
            "reasons": list(self.reasons), "decision": self.decision, "slot": self.slot,
            "replannable": self.replannable,
        }


class _AllocationGuarantees(qc._QuotaGuarantees):
    """FCP-10A-01 zero-authority flags plus: no provider reassignment, no
    fallback, no relaxed limit, no blueprint run."""

    @property
    def provider_reassigned(self) -> bool:
        return False

    @property
    def fallback_proposed(self) -> bool:
        return False

    @property
    def limits_relaxed(self) -> bool:
        return False

    @property
    def blueprint_run(self) -> bool:
        return False

    @staticmethod
    def _guarantees() -> dict:
        guarantees = qc._QuotaGuarantees._guarantees()
        guarantees.update(marker=ALLOCATION_MARKER, provider_reassigned=False, fallback_proposed=False,
                          limits_relaxed=False, blueprint_run=False)
        return guarantees


def outcome_for(workers: tuple) -> str:
    """FCP-9C-01's: UNKNOWN > SCHEDULABLE > WAITING > REFUSED > IDLE."""
    present = {w.decision for w in workers}
    for outcome in (cap.UNKNOWN, SCHEDULABLE, WAITING, REFUSED):
        if outcome in present:
            return outcome
    return IDLE


def _replannable(state: str, provider_ok: bool, capacity_decision: str, capacity_reasons: tuple) -> bool:
    return (state in cap._PENDING_STATES and provider_ok and capacity_decision != REFUSED
            and cap.ACTIVE_PROVIDER_UNOBSERVED not in capacity_reasons)


@dataclass(frozen=True)
class AllocationPlan(_AllocationGuarantees):
    """Advisory allocation. Echo fields hold only validated values (None and
    () when refused). Construction re-checks every invariant, so a hand-made
    plan cannot raise a limit, exceed a headroom or claim a slot an FCP-10
    hold withdraws."""
    outcome: str
    request_id: Optional[str]
    request_fingerprint: Optional[str]
    request_reasons: tuple
    verdict: str
    reasons: tuple
    evidence_ids: tuple
    dag_id: Optional[str]
    base_plan_fingerprint: Optional[str]
    narrowed_plan_fingerprint: Optional[str]
    base_max_workers: Optional[int]
    occupied_slots: Optional[int]
    headroom: Optional[int]
    max_workers: Optional[int]
    runner_max_workers: Optional[int]
    providers: tuple
    workers: tuple
    planning_order: tuple

    def __post_init__(self):
        if not qc._in(self.outcome, OUTCOMES):
            raise ValueError("unknown outcome")
        if not _codes_ok(self.request_reasons, REQUEST_REASONS):
            raise ValueError("request_reasons must be ordered request reason codes")
        if self.request_reasons:
            echo = (self.request_id, self.request_fingerprint, self.dag_id, self.base_plan_fingerprint,
                    self.narrowed_plan_fingerprint, self.base_max_workers, self.occupied_slots, self.headroom,
                    self.max_workers, self.runner_max_workers)
            if (self.outcome != REFUSED or self.verdict != REFUSE or self.reasons or self.evidence_ids
                    or self.providers or self.workers or self.planning_order or echo != (None,) * len(echo)):
                raise ValueError("a refused request echoes nothing and decides nothing")
            return
        if not qc._valid_id(self.request_id) or not sc._safe_id(self.dag_id):
            raise ValueError("request_id / dag_id must be validated")
        if not all(_fingerprint_ok(f) for f in (self.request_fingerprint, self.base_plan_fingerprint,
                                                self.narrowed_plan_fingerprint)):
            raise ValueError("fingerprints must be sha256 hex digests")
        if not _codes_ok(self.reasons, RESULT_REASONS) or self.verdict != verdict_for(self.reasons):
            raise ValueError("verdict must be exactly the one derived from ordered reasons")
        if not _sorted_ids(self.evidence_ids):
            raise ValueError("evidence_ids must be sorted unique ids")
        if self.verdict == READY and not self.evidence_ids:
            raise ValueError("READY must cite evidence; success is never inferred")
        if not (qc._bounded_int(self.base_max_workers, 1, MAX_WORKERS)
                and qc._bounded_int(self.occupied_slots, 0, cap.MAX_ITEMS)):
            raise ValueError("base_max_workers / occupied_slots out of bounds")
        if not _headroom_ok(self.reasons, self.headroom):
            raise ValueError("headroom must match the reasons")
        if self.max_workers != min(self.base_max_workers, self.occupied_slots + self.headroom):
            raise ValueError("max_workers must be min(base, occupied + headroom)")
        if self.runner_max_workers != (self.max_workers if self.max_workers >= 1 else None):
            raise ValueError("runner_max_workers is max_workers when the Runner can hold it")
        if not (type(self.providers) is tuple and 1 <= len(self.providers) <= qc.MAX_PROVIDERS
                and all(type(p) is ProviderAllocation for p in self.providers)):
            raise ValueError("providers must be 1..MAX_PROVIDERS ProviderAllocations")
        by_provider = {p.provider_id: p for p in self.providers}
        if list(by_provider) != sorted(by_provider) or len(by_provider) != len(self.providers):
            raise ValueError("providers must be sorted and unique")
        if any(p.base_limit > self.base_max_workers for p in self.providers):
            raise ValueError("a provider never exceeds the global base")
        if not (type(self.workers) is tuple and 1 <= len(self.workers) <= cap.MAX_ITEMS
                and all(type(w) is WorkerAllocation for w in self.workers)):
            raise ValueError("workers must be 1..MAX_ITEMS WorkerAllocations")
        by_id = {w.item_id: w for w in self.workers}
        if len(by_id) != len(self.workers):
            raise ValueError("workers must name each worker once")
        if not (type(self.planning_order) is tuple and sorted(self.planning_order) == sorted(by_id)):
            raise ValueError("planning_order must be a permutation of the workers")
        for worker in self.workers:
            provider = by_provider.get(worker.provider)
            if provider is None:
                raise ValueError("every worker needs its provider allocation")
            expected = () if worker.capacity_decision == INACTIVE else _ordered(
                set(provider.reasons) | set(self.reasons), RESULT_REASONS)
            if worker.reasons != expected:
                raise ValueError("worker reasons must be its provider's and the global ones")
            if worker.replannable != _replannable(worker.state, provider.verdict == READY, worker.capacity_decision,
                                                  worker.capacity_reasons):
                raise ValueError("replannable must be derived from the worker's own provider")
        admitted = [by_id[i] for i in self.planning_order if by_id[i].decision == SCHEDULABLE]
        if [w.slot for w in admitted] != list(range(len(admitted))):
            raise ValueError("slots must be 0..n-1 in planning order")
        if len(admitted) > min(self.headroom, max(0, self.max_workers - self.occupied_slots)):
            raise ValueError("allocated workers exceed the global headroom")
        for provider in self.providers:
            if provider.assigned != sum(1 for w in admitted if w.provider == provider.provider_id):
                raise ValueError("provider assignments must match the allocated workers")
        if self.outcome != outcome_for(self.workers):
            raise ValueError("outcome must be exactly the one derived from the workers")

    @property
    def allocated(self) -> tuple:
        """Informational only, never a permit: SCHEDULABLE ids by slot."""
        chosen = [w for w in self.workers if w.decision == SCHEDULABLE]
        return tuple(w.item_id for w in sorted(chosen, key=lambda w: w.slot))

    @property
    def replannable(self) -> tuple:
        """Pending workers whose ALREADY assigned provider is apt, in
        planning order. Never a reassignment."""
        by_id = {w.item_id: w for w in self.workers}
        return tuple(i for i in self.planning_order if by_id[i].replannable)

    @property
    def quota_held(self) -> tuple:
        """Pending workers whose own provider is quota-waiting or
        auth-blocked, in planning order. No alternative is proposed."""
        held = {p.provider_id for p in self.providers if set(p.reasons) & set(QUOTA_HOLD_REASONS)}
        by_id = {w.item_id: w for w in self.workers}
        return tuple(i for i in self.planning_order
                     if by_id[i].state in cap._PENDING_STATES and by_id[i].provider in held)

    @property
    def exhausted_providers(self) -> tuple:
        return tuple(p.provider_id for p in self.providers if PROVIDER_QUOTA_WAIT in p.reasons)

    @property
    def runner_provider_limits(self) -> tuple:
        """Narrowed `(provider_id, limit)` pairs the Runner can hold.
        Informational only."""
        return tuple((p.provider_id, p.runner_limit) for p in self.providers if p.runner_limit is not None)

    def provider_allocation(self, provider_id: str) -> Optional[ProviderAllocation]:
        for provider in self.providers:
            if provider.provider_id == provider_id:
                return provider
        return None

    def worker(self, item_id: str) -> Optional[WorkerAllocation]:
        for worker in self.workers:
            if worker.item_id == item_id:
                return worker
        return None

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA, "schema_version": SCHEMA_VERSION, "outcome": self.outcome,
            "request_id": self.request_id, "request_fingerprint": self.request_fingerprint,
            "request_reasons": list(self.request_reasons), "verdict": self.verdict, "reasons": list(self.reasons),
            "evidence_ids": list(self.evidence_ids), "dag_id": self.dag_id,
            "base_plan_fingerprint": self.base_plan_fingerprint,
            "narrowed_plan_fingerprint": self.narrowed_plan_fingerprint, "base_max_workers": self.base_max_workers,
            "occupied_slots": self.occupied_slots, "headroom": self.headroom, "max_workers": self.max_workers,
            "runner_max_workers": self.runner_max_workers, "tie_break": TIE_BREAK,
            "providers": [p.to_dict() for p in self.providers], "workers": [w.to_dict() for w in self.workers],
            "planning_order": list(self.planning_order), "allocated": list(self.allocated),
            "replannable": list(self.replannable), "quota_held": list(self.quota_held),
            "execution_time_guards_not_evaluated": list(cap.EXECUTION_TIME_GUARDS_NOT_EVALUATED),
            **_AllocationGuarantees._guarantees(),
        }


def canonical_json(plan: AllocationPlan) -> str:
    """Stable, sorted, compact, size-bounded serialization of the exact plan
    type (a subclass cannot substitute `to_dict`)."""
    if type(plan) is not AllocationPlan:
        raise TypeError("canonical_json accepts only an AllocationPlan")
    text = sc._canonical(AllocationPlan.to_dict(plan))
    if len(text) > MAX_CANONICAL_JSON_BYTES:
        raise ValueError("canonical plan exceeds MAX_CANONICAL_JSON_BYTES")
    return text


def _refused(reasons) -> AllocationPlan:
    return AllocationPlan(
        outcome=REFUSED, request_id=None, request_fingerprint=None, request_reasons=_ordered(reasons, REQUEST_REASONS),
        verdict=REFUSE, reasons=(), evidence_ids=(), dag_id=None, base_plan_fingerprint=None,
        narrowed_plan_fingerprint=None, base_max_workers=None, occupied_slots=None, headroom=None, max_workers=None,
        runner_max_workers=None, providers=(), workers=(), planning_order=(),
    )


# ---------------------------------------------------------------------------
# Validation (every evidence request goes through its own evaluator)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _Evidence:
    base: object
    snapshot: object
    resources: object
    budgets: dict


def _budget_reasons(requests, providers: set, as_of) -> tuple:
    """Returns (reasons, {provider: BudgetEvaluation})."""
    if not (type(requests) is tuple and len(requests) <= MAX_BUDGET_REQUESTS
            and all(type(r) is bg.BudgetRequest for r in requests)):
        return {BUDGET_REQUESTS_MALFORMED}, {}
    reasons, evaluations, seen = set(), {}, []
    for budget in requests:
        reservation = budget.reservation
        if type(reservation) is not qc.AdvisoryReservation:
            reasons.add(BUDGET_RESERVATION_MISSING)
        elif type(reservation.provider_id) is not str or reservation.provider_id not in providers:
            reasons.add(BUDGET_PROVIDER_UNKNOWN)
        else:
            seen.append(reservation.provider_id)
        if qc.parse_utc(budget.as_of_utc) != as_of:
            reasons.add(BUDGET_INSTANT_MISMATCH)
        evaluation = bg.evaluate_budget(budget)
        if evaluation.request_reasons:
            reasons.add(BUDGET_REQUEST_REFUSED)
        elif type(reservation) is qc.AdvisoryReservation:
            evaluations[reservation.provider_id] = evaluation
    if len(seen) != len(set(seen)):
        reasons.add(BUDGET_PROVIDER_DUPLICATE)
    # Only the reservation may differ: the same policy, executions, receipts
    # and tariffs, so a shared budget has one accounted amount.
    if any((r.policy, r.executions, r.receipts, r.tariffs) != (requests[0].policy, requests[0].executions,
                                                                requests[0].receipts, requests[0].tariffs)
           for r in requests):
        reasons.add(BUDGET_EVIDENCE_MISMATCH)
    return reasons, evaluations


def _policy_reasons(policy, providers: set) -> set:
    if policy is None:
        return set()
    if qc._policy_reasons(policy):
        return {POLICY_REFUSED}
    reasons = set()
    for limit in policy.limits:
        if limit.unit != qc.UNIT_CONCURRENT_EXECUTIONS:
            reasons.add(POLICY_LIMIT_NOT_CONCURRENT)
        if limit.provider_id is not None and limit.provider_id not in providers:
            reasons.add(POLICY_PROVIDER_UNKNOWN)
    if any(qc._secret_shaped(i) for i in [policy.policy_id] + [lim.limit_id for lim in policy.limits]):
        reasons.add(ID_SECRET_SHAPED)
    return reasons


def _validate(request) -> tuple:
    """Returns (reasons, evidence). Never raises and never echoes raw input."""
    if type(request) is not AllocationRequest:
        return (REQUEST_NOT_TYPED,), None
    reasons = set()
    if not (sc._is_int(request.schema_version) and request.schema_version == REQUEST_SCHEMA_VERSION):
        reasons.add(SCHEMA_VERSION_UNSUPPORTED)
    if not qc._valid_id(request.request_id):
        reasons.add(REQUEST_ID_INVALID)
    elif qc._secret_shaped(request.request_id):
        reasons.add(ID_SECRET_SHAPED)
    base = cap.evaluate_capacity(request.capacity_request)
    if base.request_reasons:
        return _ordered(reasons | {CAPACITY_REQUEST_REFUSED}, REQUEST_REASONS), None
    capacity_request = request.capacity_request
    as_of = sw.parse_utc(capacity_request.as_of_utc)
    providers = {b.provider_id for b in base.provider_budgets}

    snapshot = qo.adapt_observations(request.quota_request)
    if snapshot.request_reasons:
        reasons.add(QUOTA_REQUEST_REFUSED)
    elif qc.parse_utc(snapshot.as_of_utc) != as_of:
        reasons.add(QUOTA_INSTANT_MISMATCH)

    resources = None
    resource_request = request.resource_request
    if type(resource_request) is not rr.ResourceRequest:
        reasons.add(RESOURCE_REQUEST_NOT_TYPED)
    else:
        if not (resource_request.manifest == capacity_request.manifest
                and type(resource_request.capacity_plan) is cap.CapacityPlan
                and cap.canonical_json(resource_request.capacity_plan) == cap.canonical_json(base)):
            reasons.add(RESOURCE_PLAN_MISMATCH)
        if qc.parse_utc(resource_request.as_of_utc) != as_of:
            reasons.add(RESOURCE_INSTANT_MISMATCH)
        resources = rr.evaluate_resources(resource_request)
        if resources.request_reasons:
            reasons.add(RESOURCE_REQUEST_REFUSED)

    budget_reasons, budgets = _budget_reasons(request.budget_requests, providers, as_of)
    reasons |= budget_reasons
    reasons |= _policy_reasons(request.quota_policy, providers)
    return _ordered(reasons, REQUEST_REASONS), _Evidence(base, snapshot, resources, budgets)


# ---------------------------------------------------------------------------
# Constraints (each returns reasons and, when it constrains, a headroom)
# ---------------------------------------------------------------------------

def _quota_constraint(view, occupied: int) -> tuple:
    """A02 provider view, never upgraded: holds and doubts as they are."""
    if view is None:
        return {QUOTA_EVIDENCE_UNCERTAIN}, None
    reasons = set()
    if view.availability == "AUTH_BLOCKED":
        reasons.add(PROVIDER_AUTH_BLOCKED)
    elif view.availability == "QUOTA_WAIT":
        reasons.add(PROVIDER_QUOTA_WAIT)
    if view.certainty != qo.CERTAIN:
        reasons.add(QUOTA_EVIDENCE_UNCERTAIN)
    if view.capacity == "FULL":
        reasons.add(CAPACITY_FULL)
    headroom = None
    if view.proven_slots is not None:
        headroom = max(0, view.proven_slots - occupied)
        if headroom == 0:
            reasons.add(PROVEN_SLOTS_SATURATED)
    return reasons, headroom


def _resource_constraint(reasons_in: tuple, verdict: str, headroom: int) -> tuple:
    """B01 verdict and headroom (provider or global), mapped as is."""
    reasons = set()
    if rr.DEMAND_EXCEEDS_CAPACITY in reasons_in:
        reasons.add(DEMAND_EXCEEDS_CAPACITY)
    if any(r in rr.UNKNOWN_REASONS for r in reasons_in):
        reasons.add(RESOURCE_UNKNOWN)
    if rr.RESOURCE_SATURATED in reasons_in:
        reasons.add(RESOURCE_SATURATED)
    return reasons, headroom if verdict == READY else None


def _fits(remaining, reserved) -> int:
    """Whole further executions of `reserved` that `remaining` absorbs."""
    if not reserved:
        return MAX_WORKERS
    if type(remaining) is Decimal:
        return min(int(bg._EXACT.divide_int(remaining, reserved)), MAX_WORKERS)
    return min(remaining // reserved, MAX_WORKERS)


def _budget_constraints(evaluations: dict, providers: list) -> tuple:
    """Per provider: (reasons, headroom) from the accounts its own
    reservation is in scope of. Shared accounts (no provider) are sized
    jointly by the largest reservation they serve: (reasons, headroom)."""
    per_provider, shared = {}, {}
    if not evaluations:
        return {p: (set(), None) for p in providers}, (set(), None)
    for provider in providers:
        evaluation = evaluations.get(provider)
        if evaluation is None:
            per_provider[provider] = ({BUDGET_EVIDENCE_MISSING}, None)
            continue
        in_scope = [a for a in evaluation.accounts if a.reservation_in_scope]
        codes = {r for a in in_scope for r in a.reasons}
        if in_scope and bg.NO_EVIDENCE in evaluation.reasons:
            codes.add(bg.NO_EVIDENCE)
        reasons = set()
        if any(r in bg.REFUSING_REASONS for r in codes):
            reasons.add(RESERVATION_EXCEEDS_LIMIT)
        if any(r in bg.UNKNOWN_REASONS for r in codes):
            reasons.add(BUDGET_UNKNOWN)
        if any(r in bg.WAITING_REASONS for r in codes):
            reasons.add(BUDGET_SATURATED)
        headroom = None
        if not reasons:
            own = [_fits(a.remaining, a.reserved) for a in in_scope if a.provider_id is not None]
            headroom = min(own) if own else None
            for account in in_scope:
                if account.provider_id is None:
                    shared.setdefault(account.limit_id, []).append((account.remaining, account.reserved))
        per_provider[provider] = (reasons, headroom)
    joint = [_fits(min(r for r, _ in pairs), max(s for _, s in pairs)) for pairs in shared.values()]
    return per_provider, (set(), min(joint) if joint else None)


def _policy_constraints(policy, providers: list, occupied: dict, occupied_total: int) -> tuple:
    """A01 CONCURRENT_EXECUTIONS maxima are absolute caps (occupied
    included). A limit without a provider caps the whole batch."""
    per_provider = {p: (set(), None) for p in providers}
    if policy is None:
        return per_provider, (set(), None)
    caps = {}
    for limit in policy.limits:
        caps[limit.provider_id] = min(caps.get(limit.provider_id, limit.maximum), limit.maximum)
    for provider in providers:
        if provider in caps:
            headroom = max(0, caps[provider] - occupied[provider])
            per_provider[provider] = ({CONCURRENCY_LIMIT_SATURATED} if headroom == 0 else set(), headroom)
    if None not in caps:
        return per_provider, (set(), None)
    headroom = max(0, caps[None] - occupied_total)
    return per_provider, ({CONCURRENCY_LIMIT_SATURATED} if headroom == 0 else set(), headroom)


def _combine(parts) -> tuple:
    reasons = set().union(*(r for r, _ in parts))
    if reasons:
        return _ordered(reasons, RESULT_REASONS), 0
    return (), min([h for _, h in parts if h is not None] + [MAX_WORKERS])


# ---------------------------------------------------------------------------
# Allocation
# ---------------------------------------------------------------------------

def _policy_dict(policy) -> Optional[dict]:
    if policy is None:
        return None
    return {"policy_id": policy.policy_id, "limits": sorted(
        ([lim.limit_id, lim.scope, lim.unit, lim.maximum, lim.provider_id, lim.resource_id] for lim in policy.limits),
        key=lambda row: row[0])}


def allocate(request: AllocationRequest) -> AllocationPlan:
    """Pure, deterministic advisory allocation. Never raises on bad input
    and never mutates it: an invalid request is an explained refusal. The
    result never authorizes dispatch, raises a limit, reassigns a provider,
    proposes a fallback, holds a reservation or buys anything."""
    reasons, evidence = _validate(request)
    if reasons:
        return _refused(reasons)
    base, snapshot, resources = evidence.base, evidence.snapshot, evidence.resources
    capacity_request = request.capacity_request
    providers = [b.provider_id for b in base.provider_budgets]
    occupied = {b.provider_id: b.occupied for b in base.provider_budgets}
    base_cap = base.effective_max_workers
    limit_of = dict(base.effective_provider_limits)

    budget_of, budget_shared = _budget_constraints(evidence.budgets, providers)
    policy_of, policy_shared = _policy_constraints(request.quota_policy, providers, occupied, base.occupied_slots)
    global_parts = [
        ({QUOTA_EVIDENCE_UNCERTAIN} if snapshot.snapshot_reasons else set(), None),
        _resource_constraint(resources.reasons, resources.verdict, resources.headroom),
        budget_shared, policy_shared,
    ]
    global_reasons, headroom = _combine(global_parts)
    max_workers = min(base_cap, base.occupied_slots + headroom)
    runner_max = max_workers if max_workers >= 1 else None

    constraints = {}
    for provider in providers:
        view = snapshot.provider_view(provider)
        resource = resources.provider_budget(provider)
        parts = [_quota_constraint(view, occupied[provider]),
                 _resource_constraint(resource.reasons, resource.verdict, resource.headroom),
                 budget_of[provider], policy_of[provider]]
        provider_reasons, provider_headroom = _combine(parts)
        base_limit = min(limit_of.get(provider, base_cap), base_cap)
        limit = min(base_limit, occupied[provider] + provider_headroom)
        evidence_ids = set(view.evidence_ids if view is not None else ())
        evidence_ids |= {e for rid in resource.resource_ids for e in resources.resource_view(rid).evidence_ids}
        budget = evidence.budgets.get(provider)
        if budget is not None:
            evidence_ids |= set(budget.evidence_ids)
        constraints[provider] = dict(
            provider_id=provider, verdict=verdict_for(provider_reasons), reasons=provider_reasons,
            evidence_ids=tuple(sorted(evidence_ids)), base_limit=base_limit, occupied=occupied[provider],
            headroom=provider_headroom, limit=limit, runner_limit=limit if limit >= 1 else None,
            assigned=0, quota_availability=None if view is None else view.availability,
            next_eligible_utc=None if view is None else view.next_eligible_utc,
        )

    narrowed_limits = dict(capacity_request.provider_limits)
    for provider, constraint in constraints.items():
        if constraint["runner_limit"] is not None:
            narrowed_limits[provider] = min(narrowed_limits.get(provider, MAX_WORKERS), constraint["runner_limit"])
    narrowed = cap.evaluate_capacity(dataclasses.replace(
        capacity_request, max_workers=capacity_request.max_workers if runner_max is None else runner_max,
        provider_limits=tuple(sorted(narrowed_limits.items()))))
    if narrowed.request_reasons:  # pragma: no cover - only valid limits are ever narrowed
        return _refused((CAPACITY_REQUEST_REFUSED,))

    by_id = {d.item_id: d for d in narrowed.decisions}
    workers, slot = {}, 0
    for item_id in narrowed.planning_order:
        decision = by_id[item_id]
        constraint = constraints[decision.provider]
        applied = () if decision.decision == INACTIVE else _ordered(
            set(constraint["reasons"]) | set(global_reasons), RESULT_REASONS)
        final = decision_for(decision.decision, applied)
        workers[item_id] = WorkerAllocation(
            item_id=item_id, state=decision.state, provider=decision.provider, priority=decision.priority,
            capacity_decision=decision.decision, capacity_reasons=decision.reasons, reasons=applied, decision=final,
            slot=slot if final == SCHEDULABLE else None,
            replannable=_replannable(decision.state, constraint["verdict"] == READY, decision.decision,
                                     decision.reasons),
        )
        if final == SCHEDULABLE:
            slot += 1
            constraint["assigned"] += 1
    provider_allocations = tuple(ProviderAllocation(**constraints[p]) for p in sorted(constraints))
    worker_allocations = tuple(workers[d.item_id] for d in narrowed.decisions)

    cited = {e for p in provider_allocations for e in p.evidence_ids} | set(resources.evidence_ids)
    base_fingerprint = _sha(cap.canonical_json(base))
    request_body = {
        "schema": REQUEST_SCHEMA, "schema_version": REQUEST_SCHEMA_VERSION, "request_id": request.request_id,
        "base_plan_fingerprint": base_fingerprint, "quota_snapshot_fingerprint": snapshot.snapshot_fingerprint,
        "resource_request_fingerprint": resources.request_fingerprint,
        "budget_request_fingerprints": sorted([p, e.request_fingerprint] for p, e in evidence.budgets.items()),
        "quota_policy": _policy_dict(request.quota_policy),
    }
    plan = AllocationPlan(
        outcome=outcome_for(worker_allocations), request_id=request.request_id,
        request_fingerprint=_sha(sc._canonical(request_body)), request_reasons=(),
        verdict=verdict_for(global_reasons), reasons=global_reasons, evidence_ids=tuple(sorted(cited)),
        dag_id=base.dag_id, base_plan_fingerprint=base_fingerprint,
        narrowed_plan_fingerprint=_sha(cap.canonical_json(narrowed)), base_max_workers=base_cap,
        occupied_slots=base.occupied_slots, headroom=headroom, max_workers=max_workers,
        runner_max_workers=runner_max, providers=provider_allocations, workers=worker_allocations,
        planning_order=narrowed.planning_order,
    )
    if len(sc._canonical(AllocationPlan.to_dict(plan))) > MAX_CANONICAL_JSON_BYTES:
        return _refused((REQUEST_TOO_LARGE,))
    return plan
