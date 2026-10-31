"""FCP-9C-01: Concurrent capacity and provider limits - pure, deterministic,
fail-closed, provider-neutral, NON-AUTHORITATIVE.

Answers ONE question: given a native `runner_pipeline.Manifest`, the worker
states the caller OBSERVED, structured provider capacity facts and declared
resource groups, how many simultaneous slots does each provider and each
resource group have right now, and which pending workers would fill them?
It never answers "may I dispatch now?".

Why this is a consultative budget, not a scheduler
--------------------------------------------------
* Director and Runner stay the ONLY execution authorities. The Runner's own
  `PipelineRunner._start_ready` (`max_workers`, `provider_limits`,
  `_provider_start_held`, `_same_worktree_conflict`, write leases) decides
  at execution time. Nothing here starts, queues, leases, retries, merges,
  switches a provider, runs a process or touches Git, the filesystem, the
  clock, the environment or the network; no pool, lease, ledger or schema
  of its own exists. The evaluation instant is the explicit `as_of_utc`.
* Limits are read, never invented or raised. The global cap is the
  manifest's `max_workers` (Runner `DEFAULT_MAX_WORKERS` when absent, never
  1 by default) bounded by `MAX_PIPELINE_WORKERS`; per-provider caps are the
  manifest's `provider_limits`. The request may only NARROW them. A
  provider's budget is additionally bounded by its PROVEN concurrent slots.
* Verdicts are reused, never reinterpreted: availability/capacity use the
  Provider Router's own vocabulary and exclusion codes
  (`fabric_provider_routing_policy`), the last classified failure uses
  `runner_provider_availability.ProviderCondition`, a `RoutingAdvisory` is
  read only through its rationale and selected provider, dependency
  acceptance is the Runner's `DEPENDENCY_POLICIES` (via FCP-9B-02) and
  worktree exclusion is FCP-9B-01 `analyze_conflicts`.
* Fail closed: `UNKNOWN`, `QUOTA_WAIT`, `AUTH_BLOCKED`, `FULL`, stale,
  future-dated or contradictory facts never enable a slot. A worker of
  UNKNOWN state is assumed to occupy a slot of every provider it could be
  using. No alternative provider, fallback, paid API or switch is ever
  proposed: a held provider simply has zero slots.
* Provider-neutral: provider ids are opaque and only compared for equality.

Contention
----------
Planning order is the Runner's dispatch order: highest `priority` first,
then declared worker order (total and stable). Once the global cap is
reached every later worker waits; a worker is passed over earlier only for
a concrete reason of its own (provider/group budget, conflict).

Decisions (per worker; none is a permit): INACTIVE (running, terminal or a
Runner-owned wait) > REFUSED > UNKNOWN > WAITING > SCHEDULABLE (slot 0..n-1
in planning order). Outcome: REFUSED for an invalid request (nothing
echoed), else UNKNOWN, SCHEDULABLE, WAITING, REFUSED if any worker is, else
IDLE. Output (`CapacityPlan`, schema `fcp9c01-scheduler-capacity-plan-v1`)
holds only validated ids, enumerated codes, integers and a fingerprint, and
fixes every FCP-9A-01 zero-authority flag to False as read-only properties.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Optional

try:
    from scripts.ai import fabric_provider_routing_policy as rt
    from scripts.ai import fabric_scheduler_conflicts as cf
    from scripts.ai import fabric_scheduler_contract as sc
    from scripts.ai import fabric_scheduler_plan as pl
    from scripts.ai import fabric_scheduler_window as sw
    from scripts.ai import runner_pipeline as pipeline
    from scripts.ai import runner_provider_availability as availability
except ImportError:  # pragma: no cover - direct script execution
    import fabric_provider_routing_policy as rt  # type: ignore[no-redef]
    import fabric_scheduler_conflicts as cf  # type: ignore[no-redef]
    import fabric_scheduler_contract as sc  # type: ignore[no-redef]
    import fabric_scheduler_plan as pl  # type: ignore[no-redef]
    import fabric_scheduler_window as sw  # type: ignore[no-redef]
    import runner_pipeline as pipeline  # type: ignore[no-redef]
    import runner_provider_availability as availability  # type: ignore[no-redef]

REQUEST_SCHEMA = "fcp9c01-scheduler-capacity-request-v1"
REQUEST_SCHEMA_VERSION = 1
SCHEMA = "fcp9c01-scheduler-capacity-plan-v1"
SCHEMA_VERSION = 1
CAPACITY_MARKER = "FCP9C01_CAPACITY_ADVISORY_ONLY_NOT_CERTIFIED_NOT_AUTHORIZED"

MAX_WORKERS = pipeline.MAX_PIPELINE_WORKERS
DEFAULT_MAX_WORKERS = pipeline.DEFAULT_MAX_WORKERS
MAX_ITEMS = pl.MAX_NODES
MAX_PROVIDERS = rt.MAX_PROVIDERS
MAX_GROUPS = 16
MAX_PROVEN_SLOTS = MAX_WORKERS
DEFAULT_MAX_FACT_AGE_SECONDS = 900
MAX_FACT_AGE_SECONDS = 86400
MAX_CANONICAL_JSON_BYTES = 262144

# Runner guards this preview never evaluates; they stay the Runner's.
EXECUTION_TIME_GUARDS_NOT_EVALUATED = pl.EXECUTION_TIME_GUARDS_NOT_EVALUATED

_W = pipeline.WorkerState
STATE_UNKNOWN = pl.STATE_UNKNOWN
NODE_STATES = pl.NODE_STATES
_PENDING_STATES = pl._PENDING_STATES
_TERMINAL_STATES = pl._TERMINAL_STATES
_PROVIDER_HOLDING_STATES = pl._PROVIDER_HOLDING_STATES
# States that occupy (or, unobserved, may occupy) a Runner execution slot.
_OCCUPYING_STATES = frozenset({_W.RUNNING.value, STATE_UNKNOWN})

_CONDITIONS = tuple(c.value for c in availability.ProviderCondition)
# The only availability each classified condition is consistent with
# (None: not an availability hold at all).
_CONDITION_AVAILABILITY = {
    availability.ProviderCondition.QUOTA_EXHAUSTED.value: "QUOTA_WAIT",
    availability.ProviderCondition.AUTH_BLOCKED.value: "AUTH_BLOCKED",
    availability.ProviderCondition.TRANSIENT_ERROR.value: None,
    availability.ProviderCondition.EXECUTION_ERROR.value: None,
}
_GROUP_ID_RE = re.compile(r"[a-z][a-z0-9._-]{0,63}")

# Batch outcomes and worker decisions.
SCHEDULABLE = sc.SCHEDULABLE
WAITING = sc.WAITING
REFUSED = sc.REFUSED
UNKNOWN = sc.UNKNOWN
INACTIVE = pl.INACTIVE
IDLE = pl.IDLE
DECISIONS = (SCHEDULABLE, WAITING, REFUSED, UNKNOWN, INACTIVE)
OUTCOMES = (SCHEDULABLE, WAITING, REFUSED, UNKNOWN, IDLE)

# Budget statuses (providers and groups).
AVAILABLE = "AVAILABLE"
SATURATED = "SATURATED"
HELD = "HELD"
BUDGET_STATUSES = (AVAILABLE, SATURATED, HELD, UNKNOWN)

# Request-level refusal codes, in their fixed canonical order.
REQUEST_NOT_TYPED = "REQUEST_NOT_TYPED"
SCHEMA_VERSION_UNSUPPORTED = "SCHEMA_VERSION_UNSUPPORTED"
AS_OF_INVALID = "AS_OF_INVALID"
MANIFEST_NOT_TYPED = "MANIFEST_NOT_TYPED"
MANIFEST_INVALID = "MANIFEST_INVALID"
MANIFEST_LIMITS_INVALID = "MANIFEST_LIMITS_INVALID"
ITEMS_MALFORMED = "ITEMS_MALFORMED"
ITEM_UNKNOWN_WORKER = "ITEM_UNKNOWN_WORKER"
ITEM_DUPLICATE = "ITEM_DUPLICATE"
ITEM_STATE_INVALID = "ITEM_STATE_INVALID"
ACTIVE_PROVIDER_NOT_DECLARED = "ACTIVE_PROVIDER_NOT_DECLARED"
ROUTING_ADVISORY_NOT_TYPED = "ROUTING_ADVISORY_NOT_TYPED"
FACTS_MALFORMED = "FACTS_MALFORMED"
FACTS_DUPLICATE = "FACTS_DUPLICATE"
FACTS_TIME_INVALID = "FACTS_TIME_INVALID"
MAX_FACT_AGE_INVALID = "MAX_FACT_AGE_INVALID"
GROUPS_MALFORMED = "GROUPS_MALFORMED"
GROUP_DUPLICATE = "GROUP_DUPLICATE"
GROUP_MEMBER_UNKNOWN = "GROUP_MEMBER_UNKNOWN"
MAX_WORKERS_INVALID = "MAX_WORKERS_INVALID"
PROVIDER_LIMITS_MALFORMED = "PROVIDER_LIMITS_MALFORMED"
PROVIDER_LIMIT_DUPLICATE = "PROVIDER_LIMIT_DUPLICATE"
CONFLICT_REQUEST_NOT_TYPED = "CONFLICT_REQUEST_NOT_TYPED"
CONFLICT_DAG_MISMATCH = "CONFLICT_DAG_MISMATCH"
CONFLICT_WORKERS_MISMATCH = "CONFLICT_WORKERS_MISMATCH"
CONFLICT_MODE_MISMATCH = "CONFLICT_MODE_MISMATCH"
CONFLICT_WORKTREE_MISMATCH = "CONFLICT_WORKTREE_MISMATCH"
CONFLICT_REQUEST_REFUSED = "CONFLICT_REQUEST_REFUSED"
REQUEST_TOO_LARGE = "REQUEST_TOO_LARGE"
REQUEST_REASONS = (
    REQUEST_NOT_TYPED, SCHEMA_VERSION_UNSUPPORTED, AS_OF_INVALID, MANIFEST_NOT_TYPED, MANIFEST_INVALID,
    MANIFEST_LIMITS_INVALID, ITEMS_MALFORMED, ITEM_UNKNOWN_WORKER, ITEM_DUPLICATE, ITEM_STATE_INVALID,
    ACTIVE_PROVIDER_NOT_DECLARED, ROUTING_ADVISORY_NOT_TYPED, FACTS_MALFORMED, FACTS_DUPLICATE, FACTS_TIME_INVALID,
    MAX_FACT_AGE_INVALID, GROUPS_MALFORMED, GROUP_DUPLICATE, GROUP_MEMBER_UNKNOWN, MAX_WORKERS_INVALID,
    PROVIDER_LIMITS_MALFORMED, PROVIDER_LIMIT_DUPLICATE, CONFLICT_REQUEST_NOT_TYPED, CONFLICT_DAG_MISMATCH,
    CONFLICT_WORKERS_MISMATCH, CONFLICT_MODE_MISMATCH, CONFLICT_WORKTREE_MISMATCH, CONFLICT_REQUEST_REFUSED,
    REQUEST_TOO_LARGE,
)

# Provider budget reason codes (the Router's own codes where they exist),
# grouped by the status they force, in their fixed canonical order.
NO_FACTS = rt.NO_FACTS
FACTS_STALE = "FACTS_STALE"
FACTS_FROM_FUTURE = "FACTS_FROM_FUTURE"
AVAILABILITY_UNKNOWN = rt.AVAILABILITY_UNKNOWN
CAPACITY_UNKNOWN = rt.CAPACITY_UNKNOWN
PROVEN_SLOTS_UNKNOWN = "PROVEN_SLOTS_UNKNOWN"
CONDITION_DISCREPANCY = "CONDITION_DISCREPANCY"
CAPACITY_DISCREPANCY = "CAPACITY_DISCREPANCY"
OCCUPANCY_DISCREPANCY = "OCCUPANCY_DISCREPANCY"
AVAILABILITY_QUOTA_WAIT = rt.AVAILABILITY_QUOTA_WAIT
AVAILABILITY_AUTH_BLOCKED = rt.AVAILABILITY_AUTH_BLOCKED
CAPACITY_FULL = rt.CAPACITY_FULL
RUNNER_PROVIDER_HOLD = "RUNNER_PROVIDER_HOLD"
PROVIDER_UNKNOWN_REASONS = (
    NO_FACTS, FACTS_STALE, FACTS_FROM_FUTURE, AVAILABILITY_UNKNOWN, CAPACITY_UNKNOWN, PROVEN_SLOTS_UNKNOWN,
    CONDITION_DISCREPANCY, CAPACITY_DISCREPANCY, OCCUPANCY_DISCREPANCY,
)
PROVIDER_HELD_REASONS = (AVAILABILITY_QUOTA_WAIT, AVAILABILITY_AUTH_BLOCKED, CAPACITY_FULL, RUNNER_PROVIDER_HOLD)
PROVIDER_REASONS = PROVIDER_UNKNOWN_REASONS + PROVIDER_HELD_REASONS

# Worker-level reason codes, grouped by the decision they force, in their
# fixed canonical order.
ITEM_RUNNING = pl.NODE_RUNNING
ITEM_TERMINAL = pl.NODE_TERMINAL
ITEM_NOT_PENDING = pl.NODE_NOT_PENDING
DEPENDENCY_UNSATISFIABLE = pl.DEPENDENCY_UNSATISFIABLE
ROUTING_REFUSED = "ROUTING_REFUSED"
ITEM_STATE_UNKNOWN = pl.NODE_STATE_UNKNOWN
DEPENDENCY_STATE_UNKNOWN = pl.DEPENDENCY_STATE_UNKNOWN
DEPENDENCY_STATE_AMBIGUOUS = pl.DEPENDENCY_STATE_AMBIGUOUS
ACTIVE_PROVIDER_UNOBSERVED = "ACTIVE_PROVIDER_UNOBSERVED"
ROUTING_DISCREPANCY = "ROUTING_DISCREPANCY"
PROVIDER_CAPACITY_UNKNOWN = "PROVIDER_CAPACITY_UNKNOWN"
WORKER_OCCUPANCY_UNKNOWN = "WORKER_OCCUPANCY_UNKNOWN"
CONFLICTS_UNASSESSED = pl.CONFLICTS_UNASSESSED
CONFLICT_UNIDENTIFIED = pl.CONFLICT_UNIDENTIFIED
DEPENDENCY_PENDING = pl.DEPENDENCY_PENDING
PROVIDER_HELD = pl.PROVIDER_HELD
CONFLICT_WITH_RUNNING = pl.CONFLICT_WITH_RUNNING
WORKER_LIMIT_REACHED = pl.WORKER_LIMIT_REACHED
PROVIDER_LIMIT_REACHED = pl.PROVIDER_LIMIT_REACHED
GROUP_LIMIT_REACHED = "GROUP_LIMIT_REACHED"
CONFLICT_WITH_ADMITTED = pl.CONFLICT_WITH_ADMITTED
INACTIVE_REASONS = (ITEM_RUNNING, ITEM_TERMINAL, ITEM_NOT_PENDING)
REFUSING_REASONS = (DEPENDENCY_UNSATISFIABLE, ROUTING_REFUSED)
UNKNOWN_REASONS = (
    ITEM_STATE_UNKNOWN, DEPENDENCY_STATE_UNKNOWN, DEPENDENCY_STATE_AMBIGUOUS, ACTIVE_PROVIDER_UNOBSERVED,
    ROUTING_DISCREPANCY, PROVIDER_CAPACITY_UNKNOWN, WORKER_OCCUPANCY_UNKNOWN, CONFLICTS_UNASSESSED,
    CONFLICT_UNIDENTIFIED,
)
WAITING_REASONS = (
    DEPENDENCY_PENDING, PROVIDER_HELD, CONFLICT_WITH_RUNNING, WORKER_LIMIT_REACHED, PROVIDER_LIMIT_REACHED,
    GROUP_LIMIT_REACHED, CONFLICT_WITH_ADMITTED,
)
ITEM_REASONS = INACTIVE_REASONS + REFUSING_REASONS + UNKNOWN_REASONS + WAITING_REASONS


def _ordered(codes, vocabulary) -> tuple:
    return sc._ordered(codes, vocabulary)


def _bounded_int(value, low: int, high: int) -> bool:
    return sc._is_int(value) and low <= value <= high


def _limit_pairs_ok(limits, max_value: int) -> bool:
    return type(limits) is tuple and len(limits) <= MAX_PROVIDERS and all(
        type(p) is tuple and len(p) == 2 and sc._valid_provider_id(p[0]) and _bounded_int(p[1], 1, max_value)
        for p in limits)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CapacityItem:
    """One OBSERVED manifest worker. `active_provider` is the provider the
    Runner is using for it (None = not observed); `routing_advisory` is an
    optional FCP-7 `RoutingAdvisory` for it, read only through its verdict.
    Validated by `evaluate_capacity` (fail closed), not here."""
    item_id: str
    state: str = STATE_UNKNOWN
    active_provider: Optional[str] = None
    routing_advisory: Optional[object] = None


@dataclass(frozen=True)
class ProviderCapacityFacts:
    """Structured observation of one provider's concurrency (never prose).
    `availability` / `capacity` use the Provider Router vocabulary;
    `proven_slots` is the proven number of simultaneous executions (None =
    unknown); `last_condition` is the last `ProviderCondition` the Runner
    classified for it (None = none observed)."""
    provider_id: str
    availability: str
    capacity: str
    proven_slots: Optional[int]
    observed_at_utc: str
    last_condition: Optional[str] = None


@dataclass(frozen=True)
class ResourceGroup:
    """A shared resource that at most `limit` of its `members` (manifest
    worker ids) may use simultaneously."""
    group_id: str
    limit: int
    members: tuple


@dataclass(frozen=True)
class CapacityRequest:
    """Explicit, immutable capacity request over one native manifest.
    Workers without an item are of UNKNOWN state. `max_workers` and
    `provider_limits` may only narrow the manifest's own limits."""
    manifest: object
    as_of_utc: str
    items: tuple = ()
    provider_facts: tuple = ()
    resource_groups: tuple = ()
    conflict_request: Optional[cf.ConflictRequest] = None
    max_workers: Optional[int] = None
    provider_limits: tuple = ()
    max_fact_age_seconds: int = DEFAULT_MAX_FACT_AGE_SECONDS
    schema_version: int = REQUEST_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _classify(reasons: tuple) -> str:
    if any(r in INACTIVE_REASONS for r in reasons):
        return INACTIVE
    if any(r in REFUSING_REASONS for r in reasons):
        return REFUSED
    if any(r in UNKNOWN_REASONS for r in reasons):
        return UNKNOWN
    return WAITING if reasons else SCHEDULABLE


def _plan_outcome(decisions: tuple) -> str:
    present = {d.decision for d in decisions}
    for outcome in (UNKNOWN, SCHEDULABLE, WAITING, REFUSED):
        if outcome in present:
            return outcome
    return IDLE


def _provider_status(reasons: tuple, free: int) -> str:
    if any(r in PROVIDER_UNKNOWN_REASONS for r in reasons):
        return UNKNOWN
    if reasons:
        return HELD
    return AVAILABLE if free > 0 else SATURATED


@dataclass(frozen=True)
class ProviderBudget:
    """Simultaneous-slot budget of one provider. Construction re-derives
    `status`; only an AVAILABLE provider has free slots or assignments."""
    provider_id: str
    status: str
    reasons: tuple
    proven_slots: Optional[int]
    limit: Optional[int]
    occupied: int
    budget: int
    free: int
    assigned: int

    def __post_init__(self):
        if not sc._valid_provider_id(self.provider_id):
            raise ValueError("provider_id must be a valid provider id")
        if not (type(self.reasons) is tuple and all(type(r) is str and r in PROVIDER_REASONS for r in self.reasons)
                and self.reasons == _ordered(self.reasons, PROVIDER_REASONS)):
            raise ValueError("reasons must be ordered provider reason codes")
        if self.proven_slots is not None and not _bounded_int(self.proven_slots, 0, MAX_PROVEN_SLOTS):
            raise ValueError("proven_slots must be None or 0..MAX_PROVEN_SLOTS")
        if self.limit is not None and not _bounded_int(self.limit, 1, MAX_WORKERS):
            raise ValueError("limit must be None or 1..MAX_WORKERS")
        for value in (self.occupied, self.budget, self.free, self.assigned):
            if not _bounded_int(value, 0, MAX_ITEMS):
                raise ValueError("counts must be bounded non-negative ints")
        if self.reasons and (self.budget, self.free, self.assigned) != (0, 0, 0):
            raise ValueError("a held or unknown provider enables no slot")
        if not self.reasons:
            bound = min(v for v in (self.proven_slots, self.limit, MAX_WORKERS) if v is not None)
            if self.proven_slots is None or self.budget > bound or self.free != max(0, self.budget - self.occupied):
                raise ValueError("budget must be bounded by proven slots and limits")
        if self.assigned > self.free:
            raise ValueError("assigned slots exceed the free budget")
        if self.status != _provider_status(self.reasons, self.free):
            raise ValueError("status must be exactly the one derived from reasons")

    def to_dict(self) -> dict:
        return {
            "provider_id": self.provider_id, "status": self.status, "reasons": list(self.reasons),
            "proven_slots": self.proven_slots, "limit": self.limit, "occupied": self.occupied,
            "budget": self.budget, "free": self.free, "assigned": self.assigned,
        }


@dataclass(frozen=True)
class GroupBudget:
    """Simultaneous-slot budget of one declared resource group."""
    group_id: str
    status: str
    limit: int
    members: tuple
    occupied: int
    free: int
    assigned: int

    def __post_init__(self):
        if not (type(self.group_id) is str and _GROUP_ID_RE.fullmatch(self.group_id)):
            raise ValueError("group_id must be a valid group id")
        if not _bounded_int(self.limit, 1, MAX_WORKERS):
            raise ValueError("limit must be 1..MAX_WORKERS")
        if not (type(self.members) is tuple and all(sc._safe_id(m) for m in self.members)
                and self.members == tuple(sorted(set(self.members)))):
            raise ValueError("members must be sorted unique safe ids")
        for value in (self.occupied, self.free, self.assigned):
            if not _bounded_int(value, 0, MAX_ITEMS):
                raise ValueError("counts must be bounded non-negative ints")
        if self.free != max(0, self.limit - self.occupied) or self.assigned > self.free:
            raise ValueError("group assignments must fit the free budget")
        if self.status != (AVAILABLE if self.free > 0 else SATURATED):
            raise ValueError("status must be exactly the one derived from the free budget")

    def to_dict(self) -> dict:
        return {
            "group_id": self.group_id, "status": self.status, "limit": self.limit, "members": list(self.members),
            "occupied": self.occupied, "free": self.free, "assigned": self.assigned,
        }


@dataclass(frozen=True)
class ItemDecision:
    """Per-worker advisory decision. Construction re-derives `decision` from
    `reasons`, so a hand-made decision cannot claim more than its reasons."""
    item_id: str
    state: str
    provider: str
    priority: int
    decision: str
    reasons: tuple
    slot: Optional[int]

    def __post_init__(self):
        if not sc._safe_id(self.item_id):
            raise ValueError("item_id must be a safe id")
        if type(self.state) is not str or self.state not in NODE_STATES:
            raise ValueError("state must be an observed worker state")
        if not sc._valid_provider_id(self.provider):
            raise ValueError("provider must be a valid provider id")
        if not sc._is_int(self.priority):
            raise ValueError("priority must be an int")
        if not (type(self.reasons) is tuple and all(type(r) is str and r in ITEM_REASONS for r in self.reasons)
                and self.reasons == _ordered(self.reasons, ITEM_REASONS)):
            raise ValueError("reasons must be ordered item reason codes")
        if type(self.decision) is not str or self.decision != _classify(self.reasons):
            raise ValueError("decision must be exactly the one derived from reasons")
        if self.state == STATE_UNKNOWN and self.reasons != (ITEM_STATE_UNKNOWN,):
            raise ValueError("a worker of unknown state is UNKNOWN for that reason only")
        if self.decision == SCHEDULABLE and self.state not in _PENDING_STATES:
            raise ValueError("only a pending worker is schedulable")
        if self.decision == SCHEDULABLE:
            if not _bounded_int(self.slot, 0, MAX_WORKERS - 1):
                raise ValueError("a SCHEDULABLE worker carries a slot")
        elif self.slot is not None:
            raise ValueError("only a SCHEDULABLE worker carries a slot")

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id, "state": self.state, "provider": self.provider, "priority": self.priority,
            "decision": self.decision, "reasons": list(self.reasons), "slot": self.slot,
        }


class _CapacityGuarantees(sc._NotAuthorized):
    @staticmethod
    def _guarantees() -> dict:
        guarantees = sc._NotAuthorized._guarantees()
        guarantees["marker"] = CAPACITY_MARKER
        return guarantees


@dataclass(frozen=True)
class CapacityPlan(_CapacityGuarantees):
    """Consultative capacity budget. Echo fields hold only validated values
    (None and () when refused). Construction re-checks every invariant, so a
    hand-made plan cannot exceed the global, provider or group budget."""
    outcome: str
    dag_id: Optional[str]
    request_fingerprint: Optional[str]
    effective_max_workers: Optional[int]
    occupied_slots: Optional[int]
    free_slots: Optional[int]
    effective_provider_limits: tuple
    provider_budgets: tuple
    group_budgets: tuple
    planning_order: tuple
    request_reasons: tuple
    decisions: tuple

    def __post_init__(self):
        if type(self.outcome) is not str or self.outcome not in OUTCOMES:
            raise ValueError("unknown plan outcome")
        if not (type(self.request_reasons) is tuple
                and all(type(r) is str and r in REQUEST_REASONS for r in self.request_reasons)
                and self.request_reasons == _ordered(self.request_reasons, REQUEST_REASONS)):
            raise ValueError("request_reasons must be ordered request reason codes")
        for name, kind in (("decisions", ItemDecision), ("provider_budgets", ProviderBudget),
                           ("group_budgets", GroupBudget)):
            value = getattr(self, name)
            if not (type(value) is tuple and all(type(v) is kind for v in value)):
                raise ValueError(f"{name} must be a tuple of {kind.__name__}")
        echo = (self.dag_id, self.request_fingerprint, self.effective_max_workers, self.occupied_slots,
                self.free_slots)
        if self.request_reasons:
            if (self.outcome != REFUSED or self.decisions or self.planning_order or self.provider_budgets
                    or self.group_budgets or self.effective_provider_limits or echo != (None,) * len(echo)):
                raise ValueError("a refused request echoes nothing and decides nothing")
            return
        if not sc._safe_id(self.dag_id):
            raise ValueError("dag_id must be a safe id")
        if not (type(self.request_fingerprint) is str and sc._FINGERPRINT_RE.fullmatch(self.request_fingerprint)):
            raise ValueError("request_fingerprint must be a sha256 hex digest")
        if not _bounded_int(self.effective_max_workers, 1, MAX_WORKERS):
            raise ValueError("effective_max_workers must be in 1..MAX_WORKERS")
        if not (_bounded_int(self.occupied_slots, 0, MAX_ITEMS)
                and self.free_slots == max(0, self.effective_max_workers - self.occupied_slots)):
            raise ValueError("free_slots must be the cap minus occupied slots")
        limits = self.effective_provider_limits
        if not (_limit_pairs_ok(limits, MAX_WORKERS) and list(limits) == sorted(limits)
                and len({p[0] for p in limits}) == len(limits)):
            raise ValueError("effective_provider_limits must be sorted unique bounded pairs")
        ids = [d.item_id for d in self.decisions]
        if not 1 <= len(ids) <= MAX_ITEMS or len(set(ids)) != len(ids):
            raise ValueError("decisions must name each worker once")
        if not (type(self.planning_order) is tuple and sorted(self.planning_order) == sorted(ids)):
            raise ValueError("planning_order must be a permutation of the workers")
        by_id = {d.item_id: d for d in self.decisions}
        admitted = [by_id[i] for i in self.planning_order if by_id[i].decision == SCHEDULABLE]
        if [d.slot for d in admitted] != list(range(len(admitted))):
            raise ValueError("slots must be 0..n-1 in planning order")
        if len(admitted) > self.free_slots:
            raise ValueError("schedulable workers exceed the free global slots")
        budgets = {b.provider_id: b for b in self.provider_budgets}
        if list(budgets) != sorted(budgets) or len(budgets) != len(self.provider_budgets):
            raise ValueError("provider_budgets must be sorted and unique")
        limit_of = dict(limits)
        for budget in self.provider_budgets:
            used = sum(1 for d in admitted if d.provider == budget.provider_id)
            if used != budget.assigned or (budget.limit != limit_of.get(budget.provider_id)):
                raise ValueError("provider budget does not match its assignments or limit")
        if any(d.provider not in budgets for d in admitted):
            raise ValueError("every schedulable worker needs an AVAILABLE provider budget")
        groups = [g.group_id for g in self.group_budgets]
        if groups != sorted(set(groups)):
            raise ValueError("group_budgets must be sorted and unique")
        for group in self.group_budgets:
            if sum(1 for d in admitted if d.item_id in group.members) != group.assigned:
                raise ValueError("group budget does not match its assignments")
        if self.outcome != _plan_outcome(self.decisions):
            raise ValueError("outcome must be exactly the one derived from decisions")

    def decision_of(self, item_id: str) -> Optional[ItemDecision]:
        for decision in self.decisions:
            if decision.item_id == item_id:
                return decision
        return None

    def budget_of(self, provider_id: str) -> Optional[ProviderBudget]:
        for budget in self.provider_budgets:
            if budget.provider_id == provider_id:
                return budget
        return None

    @property
    def admitted(self) -> tuple:
        """Informational only, never a permit: SCHEDULABLE ids by slot."""
        chosen = [d for d in self.decisions if d.decision == SCHEDULABLE]
        return tuple(d.item_id for d in sorted(chosen, key=lambda d: d.slot))

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA, "schema_version": SCHEMA_VERSION, "outcome": self.outcome, "dag_id": self.dag_id,
            "request_fingerprint": self.request_fingerprint, "effective_max_workers": self.effective_max_workers,
            "occupied_slots": self.occupied_slots, "free_slots": self.free_slots,
            "effective_provider_limits": [list(p) for p in self.effective_provider_limits],
            "provider_budgets": [b.to_dict() for b in self.provider_budgets],
            "group_budgets": [g.to_dict() for g in self.group_budgets],
            "planning_order": list(self.planning_order), "request_reasons": list(self.request_reasons),
            "counts": {d: sum(1 for x in self.decisions if x.decision == d) for d in DECISIONS},
            "decisions": [d.to_dict() for d in self.decisions],
            "execution_time_guards_not_evaluated": list(EXECUTION_TIME_GUARDS_NOT_EVALUATED),
            **_CapacityGuarantees._guarantees(),
        }


def canonical_json(plan: CapacityPlan) -> str:
    """Stable, sorted, compact, size-bounded serialization of the exact
    contract type (a subclass cannot substitute `to_dict`)."""
    if type(plan) is not CapacityPlan:
        raise TypeError("canonical_json accepts only a CapacityPlan")
    text = sc._canonical(CapacityPlan.to_dict(plan))
    if len(text) > MAX_CANONICAL_JSON_BYTES:
        raise ValueError("canonical plan exceeds MAX_CANONICAL_JSON_BYTES")
    return text


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _manifest_reasons(manifest) -> set:
    """The manifest is read, never re-parsed or mutated: only the fields this
    budget needs are checked, failing closed on anything unexpected."""
    if type(manifest) is not pipeline.Manifest:
        return {MANIFEST_NOT_TYPED}
    reasons = set()
    workers = manifest.workers
    if not (sc._safe_id(manifest.pipeline_id) and type(workers) is list and 1 <= len(workers) <= MAX_ITEMS
            and all(type(w) is pipeline.WorkerSpec for w in workers)):
        return {MANIFEST_INVALID}
    ids = [w.id for w in workers]
    known = set(ids)
    for spec in workers:
        if not (sc._safe_id(spec.id) and sc._valid_provider_id(spec.provider)
                and type(spec.mode) is str and spec.mode in sc.MODES and sc._is_int(spec.priority)
                and type(spec.depends_on) is list and all(type(d) is str and d in known and d != spec.id
                                                         for d in spec.depends_on)
                and len(set(spec.depends_on)) == len(spec.depends_on)
                and type(spec.dependency_policy) is str and spec.dependency_policy in pipeline.DEPENDENCY_POLICIES
                and type(spec.fallback_providers) is list
                and all(sc._valid_provider_id(p) for p in spec.fallback_providers)
                and type(spec.worktree_top) is str):
            reasons.add(MANIFEST_INVALID)
    if len(known) != len(ids):
        reasons.add(MANIFEST_INVALID)
    if not reasons and sc._has_cycle({w.id: tuple(w.depends_on) for w in workers}):
        reasons.add(MANIFEST_INVALID)
    if manifest.max_workers is not None and not _bounded_int(manifest.max_workers, 1, MAX_WORKERS):
        reasons.add(MANIFEST_LIMITS_INVALID)
    limits = manifest.provider_limits
    if not (type(limits) is dict and len(limits) <= MAX_PROVIDERS and all(
            sc._valid_provider_id(p) and sc._is_int(v) and v >= 1 for p, v in limits.items())):
        reasons.add(MANIFEST_LIMITS_INVALID)
    return reasons


def _possible_providers(spec) -> frozenset:
    return frozenset([spec.provider] + list(spec.fallback_providers))


def _item_reasons(items, specs: dict) -> set:
    if not (type(items) is tuple and len(items) <= MAX_ITEMS and all(type(i) is CapacityItem for i in items)):
        return {ITEMS_MALFORMED}
    reasons = set()
    ids = []
    for item in items:
        if type(item.item_id) is not str or item.item_id not in specs:
            reasons.add(ITEM_UNKNOWN_WORKER)
            continue
        ids.append(item.item_id)
        if type(item.state) is not str or item.state not in NODE_STATES:
            reasons.add(ITEM_STATE_INVALID)
        if item.active_provider is not None and (
                not sc._valid_provider_id(item.active_provider)
                or item.active_provider not in _possible_providers(specs[item.item_id])):
            reasons.add(ACTIVE_PROVIDER_NOT_DECLARED)
        if item.routing_advisory is not None and type(item.routing_advisory) is not rt.RoutingAdvisory:
            reasons.add(ROUTING_ADVISORY_NOT_TYPED)
    if len(ids) != len(set(ids)):
        reasons.add(ITEM_DUPLICATE)
    return reasons


def _facts_reasons(facts) -> set:
    if not (type(facts) is tuple and len(facts) <= MAX_PROVIDERS
            and all(type(f) is ProviderCapacityFacts for f in facts)):
        return {FACTS_MALFORMED}
    reasons = set()
    for fact in facts:
        if not (sc._valid_provider_id(fact.provider_id)
                and type(fact.availability) is str and fact.availability in rt.AVAILABILITY_STATES
                and type(fact.capacity) is str and fact.capacity in rt.CAPACITY_STATES
                and (fact.proven_slots is None or _bounded_int(fact.proven_slots, 0, MAX_PROVEN_SLOTS))
                and (fact.last_condition is None
                     or (type(fact.last_condition) is str and fact.last_condition in _CONDITIONS))):
            reasons.add(FACTS_MALFORMED)
        if sw.parse_utc(fact.observed_at_utc) is None:
            reasons.add(FACTS_TIME_INVALID)
    if FACTS_MALFORMED not in reasons and len({f.provider_id for f in facts}) != len(facts):
        reasons.add(FACTS_DUPLICATE)
    return reasons


def _group_reasons(groups, specs: dict) -> set:
    if not (type(groups) is tuple and len(groups) <= MAX_GROUPS and all(type(g) is ResourceGroup for g in groups)):
        return {GROUPS_MALFORMED}
    reasons = set()
    for group in groups:
        if not (type(group.group_id) is str and _GROUP_ID_RE.fullmatch(group.group_id)
                and _bounded_int(group.limit, 1, MAX_WORKERS) and type(group.members) is tuple
                and 1 <= len(group.members) <= MAX_ITEMS and all(type(m) is str for m in group.members)
                and len(set(group.members)) == len(group.members)):
            reasons.add(GROUPS_MALFORMED)
        elif any(m not in specs for m in group.members):
            reasons.add(GROUP_MEMBER_UNKNOWN)
    if GROUPS_MALFORMED not in reasons and len({g.group_id for g in groups}) != len(groups):
        reasons.add(GROUP_DUPLICATE)
    return reasons


def _conflict_reasons(conflict, manifest) -> set:
    if type(conflict) is not cf.ConflictRequest:
        return {CONFLICT_REQUEST_NOT_TYPED}
    reasons = set()
    if conflict.dag_id != manifest.pipeline_id:
        reasons.add(CONFLICT_DAG_MISMATCH)
    workers = conflict.workers if type(conflict.workers) is tuple else ()
    typed = [w for w in workers if type(w) is cf.WorkerClaims and type(w.worker_id) is str]
    specs = {s.id: s for s in manifest.workers}
    if len(typed) != len(workers) or not workers or sorted(w.worker_id for w in typed) != sorted(specs):
        reasons.add(CONFLICT_WORKERS_MISMATCH)
        return reasons
    for worker in typed:
        spec = specs[worker.worker_id]
        if worker.mode != spec.mode:
            reasons.add(CONFLICT_MODE_MISMATCH)
        claimed = pl._worktree_key(worker.worktree) if type(worker.worktree) is str else None
        # An unidentifiable claimed worktree is the conflict analysis' own
        # UNKNOWN; an identified one must be the worker's native worktree.
        if claimed is not None and claimed != pl._worktree_key(spec.worktree_top):
            reasons.add(CONFLICT_WORKTREE_MISMATCH)
    return reasons


def _request_reasons(request) -> tuple:
    """Returns (reasons, graph). Never echoes raw input."""
    if type(request) is not CapacityRequest:
        return (REQUEST_NOT_TYPED,), None
    reasons = set()
    if not (sc._is_int(request.schema_version) and request.schema_version == REQUEST_SCHEMA_VERSION):
        reasons.add(SCHEMA_VERSION_UNSUPPORTED)
    if sw.parse_utc(request.as_of_utc) is None:
        reasons.add(AS_OF_INVALID)
    manifest_reasons = _manifest_reasons(request.manifest)
    reasons |= manifest_reasons
    if request.max_workers is not None and not _bounded_int(request.max_workers, 1, MAX_WORKERS):
        reasons.add(MAX_WORKERS_INVALID)
    if not _limit_pairs_ok(request.provider_limits, MAX_WORKERS):
        reasons.add(PROVIDER_LIMITS_MALFORMED)
    elif len({p[0] for p in request.provider_limits}) != len(request.provider_limits):
        reasons.add(PROVIDER_LIMIT_DUPLICATE)
    if not _bounded_int(request.max_fact_age_seconds, 1, MAX_FACT_AGE_SECONDS):
        reasons.add(MAX_FACT_AGE_INVALID)
    reasons |= _facts_reasons(request.provider_facts)
    if manifest_reasons & {MANIFEST_NOT_TYPED, MANIFEST_INVALID}:
        return _ordered(reasons, REQUEST_REASONS), None
    specs = {s.id: s for s in request.manifest.workers}
    reasons |= _item_reasons(request.items, specs)
    reasons |= _group_reasons(request.resource_groups, specs)
    graph = None
    if request.conflict_request is not None:
        conflict_reasons = _conflict_reasons(request.conflict_request, request.manifest)
        reasons |= conflict_reasons
        if not conflict_reasons:
            graph = cf.analyze_conflicts(request.conflict_request)
            if graph.outcome == cf.REFUSED:
                reasons.add(CONFLICT_REQUEST_REFUSED)
    return _ordered(reasons, REQUEST_REASONS), graph


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def _effective_limits(manifest, request: CapacityRequest) -> tuple:
    """(max_workers, provider limits): the manifest's, only ever narrowed and
    never above MAX_WORKERS."""
    cap = manifest.max_workers or DEFAULT_MAX_WORKERS
    if request.max_workers is not None:
        cap = min(cap, request.max_workers)
    limits = {p: min(v, MAX_WORKERS) for p, v in manifest.provider_limits.items()}
    for provider, limit in request.provider_limits:
        limits[provider] = min(limits.get(provider, limit), limit)
    return cap, tuple(sorted(limits.items()))


def _fact_reasons(fact: Optional[ProviderCapacityFacts], as_of, max_age: int, running: int) -> set:
    """The facts' own verdicts, never reinterpreted; contradictions and
    staleness fail closed."""
    if fact is None:
        return {NO_FACTS}
    reasons = set()
    observed = sw.parse_utc(fact.observed_at_utc)
    if observed > as_of:
        reasons.add(FACTS_FROM_FUTURE)
    elif (as_of - observed).total_seconds() > max_age:
        reasons.add(FACTS_STALE)
    if fact.availability in rt._AVAILABILITY_REASON:
        reasons.add(rt._AVAILABILITY_REASON[fact.availability])
    if fact.capacity in rt._CAPACITY_REASON:
        reasons.add(rt._CAPACITY_REASON[fact.capacity])
    if fact.proven_slots is None:
        reasons.add(PROVEN_SLOTS_UNKNOWN)
    if fact.last_condition is not None and fact.availability != "UNKNOWN":
        held_as = fact.availability if fact.availability in ("QUOTA_WAIT", "AUTH_BLOCKED") else None
        if _CONDITION_AVAILABILITY[fact.last_condition] != held_as:
            reasons.add(CONDITION_DISCREPANCY)
    if fact.capacity == "AVAILABLE" and fact.proven_slots is not None:
        if fact.proven_slots == 0:
            reasons.add(CAPACITY_DISCREPANCY)
        elif running > fact.proven_slots:
            reasons.add(OCCUPANCY_DISCREPANCY)
    return reasons


def _request_dict(request: CapacityRequest, graph, cap: int, limits: tuple, as_of) -> dict:
    manifest = request.manifest
    return {
        "schema": REQUEST_SCHEMA, "schema_version": REQUEST_SCHEMA_VERSION, "dag_id": manifest.pipeline_id,
        "manifest_sha256": manifest.sha256 if type(manifest.sha256) is str else None,
        "workers": [
            {"id": s.id, "provider": s.provider, "mode": s.mode, "priority": s.priority,
             "depends_on": sorted(s.depends_on), "dependency_policy": s.dependency_policy,
             "fallback_providers": list(s.fallback_providers)}
            for s in manifest.workers
        ],
        "manifest_max_workers": manifest.max_workers,
        "manifest_provider_limits": sorted([p, v] for p, v in manifest.provider_limits.items()),
        "as_of_utc": sc._utc_text(as_of), "max_fact_age_seconds": request.max_fact_age_seconds,
        "items": sorted(
            [i.item_id, i.state, i.active_provider,
             None if i.routing_advisory is None else hashlib.sha256(
                 rt.canonical_json(i.routing_advisory).encode("ascii")).hexdigest()]
            for i in request.items),
        "provider_facts": sorted(
            [f.provider_id, f.availability, f.capacity, f.proven_slots, sc._utc_text(sw.parse_utc(f.observed_at_utc)),
             f.last_condition]
            for f in request.provider_facts),
        "resource_groups": sorted([g.group_id, g.limit, sorted(g.members)] for g in request.resource_groups),
        "conflict_fingerprint": None if graph is None else graph.request_fingerprint,
        "max_workers": request.max_workers, "provider_limits": sorted([list(p) for p in request.provider_limits]),
        "effective_max_workers": cap, "effective_provider_limits": [list(p) for p in limits],
    }


def _refused(reasons) -> CapacityPlan:
    return CapacityPlan(
        outcome=REFUSED, dag_id=None, request_fingerprint=None, effective_max_workers=None, occupied_slots=None,
        free_slots=None, effective_provider_limits=(), provider_budgets=(), group_budgets=(), planning_order=(),
        request_reasons=_ordered(reasons, REQUEST_REASONS), decisions=(),
    )


def _routing_reasons(advisory, spec, provider: str) -> set:
    """Reads the Router's verdict as is: a refusal holds the worker, a
    proposal for anything else is a discrepancy. Never a substitute."""
    if advisory is None:
        return set()
    if advisory.rationale in rt.REFUSED_RATIONALES:
        return {ROUTING_REFUSED}
    if advisory.selected_provider != provider or advisory.mode != spec.mode:
        return {ROUTING_DISCREPANCY}
    return set()


def evaluate_capacity(request: CapacityRequest) -> CapacityPlan:
    """Pure, deterministic capacity budget over one native manifest. Never
    raises on bad input and never mutates it: every malformed or mismatched
    request is an explained refusal. The result never authorizes dispatch,
    execution, retry, resume, merge, a fallback or a provider switch."""
    reasons, graph = _request_reasons(request)
    if reasons:
        return _refused(reasons)
    manifest = request.manifest
    as_of = sw.parse_utc(request.as_of_utc)
    cap, limits = _effective_limits(manifest, request)
    request_text = sc._canonical(_request_dict(request, graph, cap, limits, as_of))
    if len(request_text) > MAX_CANONICAL_JSON_BYTES:
        return _refused((REQUEST_TOO_LARGE,))

    specs = manifest.workers
    observed = {i.item_id: i for i in request.items}
    states = {s.id: observed[s.id].state if s.id in observed else STATE_UNKNOWN for s in specs}

    def providers_of(spec) -> frozenset:
        """The provider(s) a worker uses: the observed one, else every one it
        could be using (fail closed)."""
        item = observed.get(spec.id)
        if item is not None and item.active_provider is not None:
            return frozenset({item.active_provider})
        return _possible_providers(spec)

    occupying = [s for s in specs if states[s.id] in _OCCUPYING_STATES]
    running_count = sum(1 for s in specs if states[s.id] == _W.RUNNING.value)
    held_by_runner = set()
    for spec in specs:
        if states[spec.id] in _PROVIDER_HOLDING_STATES:
            held_by_runner |= providers_of(spec)

    facts = {f.provider_id: f for f in request.provider_facts}
    limit_of = dict(limits)
    budgets = {}
    for provider in sorted(set(facts).union(*(providers_of(s) for s in specs))):
        occupied = sum(1 for s in occupying if provider in providers_of(s))
        running = sum(1 for s in specs if states[s.id] == _W.RUNNING.value and provider in providers_of(s))
        fact = facts.get(provider)
        provider_reasons = _fact_reasons(fact, as_of, request.max_fact_age_seconds, running)
        if provider in held_by_runner:
            provider_reasons.add(RUNNER_PROVIDER_HOLD)
        limit = limit_of.get(provider)
        budget = free = 0
        if not provider_reasons:
            budget = min(v for v in (fact.proven_slots, limit, cap) if v is not None)
            free = max(0, budget - occupied)
        ordered = _ordered(provider_reasons, PROVIDER_REASONS)
        budgets[provider] = {
            "provider_id": provider, "status": _provider_status(ordered, free), "reasons": ordered,
            "proven_slots": None if fact is None else fact.proven_slots, "limit": limit, "occupied": occupied,
            "budget": budget, "free": free, "assigned": 0,
        }

    groups = {}
    for group in request.resource_groups:
        occupied = sum(1 for m in group.members if states[m] in _OCCUPYING_STATES)
        groups[group.group_id] = {
            "group_id": group.group_id, "limit": group.limit, "members": tuple(sorted(group.members)),
            "occupied": occupied, "free": max(0, group.limit - occupied), "assigned": 0,
        }
    groups_of = {s.id: [g for g in groups.values() if s.id in g["members"]] for s in specs}

    held = {}
    for spec in specs:
        state = states[spec.id]
        if state == STATE_UNKNOWN:
            held[spec.id] = {ITEM_STATE_UNKNOWN}
            continue
        if state == _W.RUNNING.value:
            held[spec.id] = {ITEM_RUNNING}
            continue
        if state in _TERMINAL_STATES:
            held[spec.id] = {ITEM_TERMINAL}
            continue
        if state not in _PENDING_STATES:
            held[spec.id] = {ITEM_NOT_PENDING}
            continue
        item_reasons = pl._dependency_reasons(spec, states)
        item = observed[spec.id]
        if item.active_provider is None and spec.fallback_providers:
            item_reasons.add(ACTIVE_PROVIDER_UNOBSERVED)
        provider = item.active_provider or spec.provider
        item_reasons |= _routing_reasons(item.routing_advisory, spec, provider)
        status = budgets[provider]["status"]
        if status == UNKNOWN:
            item_reasons.add(PROVIDER_CAPACITY_UNKNOWN)
        elif status == HELD:
            item_reasons.add(PROVIDER_HELD)
        if running_count > MAX_WORKERS:
            item_reasons.add(WORKER_OCCUPANCY_UNKNOWN)
        if graph is None:
            item_reasons.add(CONFLICTS_UNASSESSED)
        elif graph.node_of(spec.id).status == cf.UNKNOWN:
            item_reasons.add(CONFLICT_UNIDENTIFIED)
        elif any(not graph.compatible(spec.id, other.id) for other in occupying):
            item_reasons.add(CONFLICT_WITH_RUNNING)
        held[spec.id] = item_reasons

    # Runner dispatch order: highest priority first, then declared order.
    order = sorted(range(len(specs)), key=lambda i: (-specs[i].priority, i))
    free_slots = max(0, cap - len(occupying))
    admitted = []
    slots = {}
    for index in order:
        spec = specs[index]
        if held[spec.id]:
            continue
        provider = observed[spec.id].active_provider or spec.provider
        budget = budgets[provider]
        if len(admitted) >= free_slots:
            held[spec.id].add(WORKER_LIMIT_REACHED)
        elif budget["assigned"] >= budget["free"]:
            held[spec.id].add(PROVIDER_LIMIT_REACHED)
        elif any(g["assigned"] >= g["free"] for g in groups_of[spec.id]):
            held[spec.id].add(GROUP_LIMIT_REACHED)
        elif any(not graph.compatible(spec.id, other) for other in admitted):
            held[spec.id].add(CONFLICT_WITH_ADMITTED)
        else:
            budget["assigned"] += 1
            for group in groups_of[spec.id]:
                group["assigned"] += 1
            slots[spec.id] = len(admitted)
            admitted.append(spec.id)

    decisions = tuple(
        ItemDecision(
            item_id=s.id, state=states[s.id],
            provider=(observed[s.id].active_provider if s.id in observed else None) or s.provider,
            priority=s.priority, decision=_classify(_ordered(held[s.id], ITEM_REASONS)),
            reasons=_ordered(held[s.id], ITEM_REASONS), slot=slots.get(s.id),
        )
        for s in specs
    )
    return CapacityPlan(
        outcome=_plan_outcome(decisions), dag_id=manifest.pipeline_id,
        request_fingerprint=hashlib.sha256(request_text.encode("ascii")).hexdigest(),
        effective_max_workers=cap, occupied_slots=len(occupying), free_slots=free_slots,
        effective_provider_limits=limits,
        provider_budgets=tuple(ProviderBudget(**b) for b in budgets.values()),
        group_budgets=tuple(GroupBudget(status=AVAILABLE if g["free"] > 0 else SATURATED, **g)
                            for _, g in sorted(groups.items())),
        planning_order=tuple(specs[i].id for i in order), request_reasons=(), decisions=decisions,
    )
