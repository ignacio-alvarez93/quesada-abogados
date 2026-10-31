"""FCP-10B-01: Host / Runner resource inventory and constraints - pure,
deterministic, fail-closed, provider-neutral, NON-AUTHORITATIVE.

Answers ONE question: given host resource observations the caller ALREADY
holds (CPU, memory, process slots, special resources), the per-execution
demand it declares, a native `runner_pipeline.Manifest` and the FCP-9C-01
`CapacityPlan` evaluated over it, how far must `max_workers` and each
provider limit be NARROWED so no started execution can over-allocate the
host? It never answers "may I dispatch now?".

Why this is a consultative narrowing, not a resource manager
-------------------------------------------------------------
* Director and Runner stay the ONLY execution and Git authorities. The
  Runner's own `PipelineRunner._start_ready` (`max_workers`,
  `provider_limits`, provider holds, worktree conflicts, write leases)
  decides at execution time. Nothing here enumerates, probes or monitors the
  host (no psutil, no OS call), starts, queues, leases, reserves, switches a
  provider or touches Git, the filesystem, the clock, the environment, a
  process or the network: no pool, lease, ledger, store or gateway of its
  own exists. The instant is the explicit `as_of_utc`.
* Limits are read, never invented or raised. The base is the CapacityPlan's
  `effective_max_workers` / `effective_provider_limits`, which must not
  exceed the Manifest's own (`max_workers`, Runner `DEFAULT_MAX_WORKERS`
  when absent; `provider_limits`). Occupancy is the plan's (FCP-9C-01 counts
  a worker of UNKNOWN state on every provider it could be using). Every
  output limit is `min(base, occupied + headroom)`, so it only narrows.
* Observations always carry a unit (one fixed unit per kind), a capacity,
  the amount in use, the amount held in reserve, a source, a reliability
  (quality) and a UTC instant. A CALLER_HOST_SNAPSHOT may claim at most
  CALLER_OBSERVED; an OPERATOR_DECLARATION is UNVERIFIED. Observations are
  aggregated per resource most restrictively (max in use, max reserve).
* Fail closed: a demanded resource that is unobserved, stale, future-dated,
  unverified or contradictory (in use above capacity, disagreeing
  capacities) is UNKNOWN and enables no headroom; every provider must
  declare a demand for CPU, MEMORY and PROCESS_SLOTS (DEMAND_UNDECLARED
  otherwise). Global headroom uses, per resource, the LARGEST demand of any
  provider that could still start, so no mix of starts can exceed it.
* Shared resources: when any SPECIAL resource is demanded, the FCP-9B-01
  `ConflictGraph` of the same DAG must be supplied and fully identified
  (CONFLICTS_UNASSESSED / CONFLICT_UNIDENTIFIED otherwise). Its edges are
  never relaxed: a narrowed limit never claims two workers are compatible.
* Provider-neutral: provider ids are opaque and only compared for equality.

Verdicts (contract `VERDICTS`, none is a permit), per provider and global:
REFUSE (DEMAND_EXCEEDS_CAPACITY: one execution can never fit) > UNKNOWN >
WAIT (RESOURCE_SATURATED) > READY (at least one more start fits, cited
evidence). Not READY always means `limit == min(base, occupied)`: no new
start. A limit of 0 is advisory only: the Runner treats a falsy provider
limit as unlimited and refuses `max_workers=0`, so `runner_representable`
is False and only the verdict can hold. Output (`ResourceEvaluation`, schema
`fcp10b01-resource-quota-resource-evaluation-v1`) holds only validated ids,
enumerated codes, integers and a fingerprint, and fixes every FCP-10A-01
zero-authority flag plus `lock_acquired`, `lease_acquired` and
`host_probed` to False as read-only properties.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Optional

try:
    from scripts.ai import fabric_resource_quota_contract as qc
    from scripts.ai import fabric_scheduler_capacity as cap
    from scripts.ai import fabric_scheduler_conflicts as cf
    from scripts.ai import fabric_scheduler_contract as sc
except ImportError:  # pragma: no cover - direct script execution
    import fabric_resource_quota_contract as qc  # type: ignore[no-redef]
    import fabric_scheduler_capacity as cap  # type: ignore[no-redef]
    import fabric_scheduler_conflicts as cf  # type: ignore[no-redef]
    import fabric_scheduler_contract as sc  # type: ignore[no-redef]

REQUEST_SCHEMA = "fcp10b01-resource-quota-resource-request-v1"
REQUEST_SCHEMA_VERSION = 1
SCHEMA = "fcp10b01-resource-quota-resource-evaluation-v1"
SCHEMA_VERSION = 1
RESOURCE_MARKER = "FCP10B01_RESOURCE_ADVISORY_ONLY_NOT_CERTIFIED_NOT_AUTHORIZED"

MAX_WORKERS = cap.MAX_WORKERS
MAX_OBSERVATIONS = qc.MAX_OBSERVATIONS
MAX_DEMANDS = 64
MAX_CANONICAL_JSON_BYTES = cap.MAX_CANONICAL_JSON_BYTES

KIND_CPU = "CPU"
KIND_MEMORY = "MEMORY"
KIND_PROCESS_SLOTS = "PROCESS_SLOTS"
KIND_SPECIAL = "SPECIAL"
RESOURCE_KINDS = (KIND_CPU, KIND_MEMORY, KIND_PROCESS_SLOTS, KIND_SPECIAL)
# Kinds every provider must declare a per-execution demand for.
CORE_KINDS = (KIND_CPU, KIND_MEMORY, KIND_PROCESS_SLOTS)

UNIT_CPU_MILLICORES = "CPU_MILLICORES"
UNIT_MEMORY_MIB = "MEMORY_MIB"
UNIT_PROCESSES = "PROCESSES"
UNIT_SPECIAL_UNITS = "SPECIAL_UNITS"
UNITS = (UNIT_CPU_MILLICORES, UNIT_MEMORY_MIB, UNIT_PROCESSES, UNIT_SPECIAL_UNITS)
# The one unit of each kind, and the upper bound of any amount in it.
KIND_UNIT = {
    KIND_CPU: UNIT_CPU_MILLICORES, KIND_MEMORY: UNIT_MEMORY_MIB, KIND_PROCESS_SLOTS: UNIT_PROCESSES,
    KIND_SPECIAL: UNIT_SPECIAL_UNITS,
}
UNIT_MAXIMUM = {
    UNIT_CPU_MILLICORES: 1024 * 1000, UNIT_MEMORY_MIB: 16 * 1024 * 1024, UNIT_PROCESSES: 4_194_304,
    UNIT_SPECIAL_UNITS: 1024,
}

# Host evidence sources and the reliability (quality) each may claim at most.
SOURCE_CALLER_HOST_SNAPSHOT = "CALLER_HOST_SNAPSHOT"
SOURCE_OPERATOR_DECLARATION = qc.SOURCE_OPERATOR_DECLARATION
SOURCES = (SOURCE_CALLER_HOST_SNAPSHOT, SOURCE_OPERATOR_DECLARATION)
RELIABILITIES = qc.RELIABILITIES
SOURCE_MAX_RELIABILITY = {
    SOURCE_CALLER_HOST_SNAPSHOT: qc.RELIABILITY_CALLER_OBSERVED,
    SOURCE_OPERATOR_DECLARATION: qc.RELIABILITY_UNVERIFIED,
}

READY = qc.READY
WAIT = qc.WAIT
REFUSE = qc.REFUSE
UNKNOWN = qc.UNKNOWN
VERDICTS = qc.VERDICTS
CONFLICT_OUTCOMES = (cf.COMPATIBLE, cf.CONFLICTS, cf.UNKNOWN)

# Request-level refusal codes, in their fixed canonical order.
REQUEST_NOT_TYPED = qc.REQUEST_NOT_TYPED
SCHEMA_VERSION_UNSUPPORTED = qc.SCHEMA_VERSION_UNSUPPORTED
REQUEST_ID_INVALID = qc.REQUEST_ID_INVALID
ID_SECRET_SHAPED = qc.ID_SECRET_SHAPED
ID_DUPLICATE = qc.ID_DUPLICATE
AS_OF_INVALID = qc.AS_OF_INVALID
MAX_EVIDENCE_AGE_INVALID = qc.MAX_EVIDENCE_AGE_INVALID
MANIFEST_NOT_TYPED = cap.MANIFEST_NOT_TYPED
MANIFEST_INVALID = cap.MANIFEST_INVALID
CAPACITY_PLAN_NOT_TYPED = "CAPACITY_PLAN_NOT_TYPED"
CAPACITY_PLAN_REFUSED = "CAPACITY_PLAN_REFUSED"
CAPACITY_PLAN_MISMATCH = "CAPACITY_PLAN_MISMATCH"
CAPACITY_PLAN_EXCEEDS_MANIFEST = "CAPACITY_PLAN_EXCEEDS_MANIFEST"
CONFLICT_GRAPH_NOT_TYPED = "CONFLICT_GRAPH_NOT_TYPED"
CONFLICT_GRAPH_REFUSED = "CONFLICT_GRAPH_REFUSED"
CONFLICT_GRAPH_MISMATCH = "CONFLICT_GRAPH_MISMATCH"
OBSERVATIONS_MALFORMED = qc.OBSERVATIONS_MALFORMED
OBSERVATION_ID_INVALID = qc.OBSERVATION_ID_INVALID
OBSERVATION_RESOURCE_INVALID = qc.OBSERVATION_RESOURCE_INVALID
OBSERVATION_KIND_UNKNOWN = "OBSERVATION_KIND_UNKNOWN"
OBSERVATION_UNIT_MISMATCH = "OBSERVATION_UNIT_MISMATCH"
OBSERVATION_AMOUNT_INVALID = "OBSERVATION_AMOUNT_INVALID"
OBSERVATION_SOURCE_UNKNOWN = qc.OBSERVATION_SOURCE_UNKNOWN
OBSERVATION_RELIABILITY_UNKNOWN = qc.OBSERVATION_RELIABILITY_UNKNOWN
OBSERVATION_RELIABILITY_OVERCLAIMED = qc.OBSERVATION_RELIABILITY_OVERCLAIMED
OBSERVATION_TIME_INVALID = qc.OBSERVATION_TIME_INVALID
RESOURCE_KIND_AMBIGUOUS = "RESOURCE_KIND_AMBIGUOUS"
DEMANDS_MALFORMED = "DEMANDS_MALFORMED"
DEMANDS_EMPTY = "DEMANDS_EMPTY"
DEMAND_RESOURCE_INVALID = "DEMAND_RESOURCE_INVALID"
DEMAND_KIND_UNKNOWN = "DEMAND_KIND_UNKNOWN"
DEMAND_UNIT_MISMATCH = "DEMAND_UNIT_MISMATCH"
DEMAND_AMOUNT_INVALID = "DEMAND_AMOUNT_INVALID"
DEMAND_PROVIDER_UNKNOWN = "DEMAND_PROVIDER_UNKNOWN"
DEMAND_DUPLICATE = "DEMAND_DUPLICATE"
REQUEST_TOO_LARGE = qc.REQUEST_TOO_LARGE
REQUEST_REASONS = (
    REQUEST_NOT_TYPED, SCHEMA_VERSION_UNSUPPORTED, REQUEST_ID_INVALID, ID_SECRET_SHAPED, ID_DUPLICATE,
    AS_OF_INVALID, MAX_EVIDENCE_AGE_INVALID, MANIFEST_NOT_TYPED, MANIFEST_INVALID, CAPACITY_PLAN_NOT_TYPED,
    CAPACITY_PLAN_REFUSED, CAPACITY_PLAN_MISMATCH, CAPACITY_PLAN_EXCEEDS_MANIFEST, CONFLICT_GRAPH_NOT_TYPED,
    CONFLICT_GRAPH_REFUSED, CONFLICT_GRAPH_MISMATCH, OBSERVATIONS_MALFORMED, OBSERVATION_ID_INVALID,
    OBSERVATION_RESOURCE_INVALID, OBSERVATION_KIND_UNKNOWN, OBSERVATION_UNIT_MISMATCH, OBSERVATION_AMOUNT_INVALID,
    OBSERVATION_SOURCE_UNKNOWN, OBSERVATION_RELIABILITY_UNKNOWN, OBSERVATION_RELIABILITY_OVERCLAIMED,
    OBSERVATION_TIME_INVALID, RESOURCE_KIND_AMBIGUOUS, DEMANDS_MALFORMED, DEMANDS_EMPTY, DEMAND_RESOURCE_INVALID,
    DEMAND_KIND_UNKNOWN, DEMAND_UNIT_MISMATCH, DEMAND_AMOUNT_INVALID, DEMAND_PROVIDER_UNKNOWN, DEMAND_DUPLICATE,
    REQUEST_TOO_LARGE,
)

# Evaluation reason codes (the contract's and FCP-9C-01's own where they
# exist), grouped by the verdict they force, in their fixed canonical order.
DEMAND_EXCEEDS_CAPACITY = "DEMAND_EXCEEDS_CAPACITY"
NO_EVIDENCE = qc.NO_EVIDENCE
EVIDENCE_STALE = qc.EVIDENCE_STALE
EVIDENCE_FROM_FUTURE = qc.EVIDENCE_FROM_FUTURE
EVIDENCE_UNVERIFIED = qc.EVIDENCE_UNVERIFIED
EVIDENCE_CONTRADICTORY = qc.EVIDENCE_CONTRADICTORY
DEMAND_UNDECLARED = "DEMAND_UNDECLARED"
CONFLICTS_UNASSESSED = cap.CONFLICTS_UNASSESSED
CONFLICT_UNIDENTIFIED = cap.CONFLICT_UNIDENTIFIED
RESOURCE_SATURATED = "RESOURCE_SATURATED"
REFUSING_REASONS = (DEMAND_EXCEEDS_CAPACITY,)
# Evidence-quality reasons of one resource.
RESOURCE_REASONS = (NO_EVIDENCE, EVIDENCE_STALE, EVIDENCE_FROM_FUTURE, EVIDENCE_UNVERIFIED, EVIDENCE_CONTRADICTORY)
CONFLICT_REASONS = (CONFLICTS_UNASSESSED, CONFLICT_UNIDENTIFIED)
UNKNOWN_REASONS = RESOURCE_REASONS + (DEMAND_UNDECLARED,) + CONFLICT_REASONS
WAITING_REASONS = (RESOURCE_SATURATED,)
RESULT_REASONS = REFUSING_REASONS + UNKNOWN_REASONS + WAITING_REASONS


def _ordered(codes, vocabulary) -> tuple:
    return sc._ordered(codes, vocabulary)


def _codes_ok(codes, vocabulary) -> bool:
    return (type(codes) is tuple and all(qc._in(c, vocabulary) for c in codes)
            and codes == _ordered(codes, vocabulary))


def _sorted_ids(values) -> bool:
    return (type(values) is tuple and all(qc._valid_id(v) for v in values)
            and list(values) == sorted(set(values)))


def verdict_for(reasons: tuple) -> str:
    """REFUSE > UNKNOWN > WAIT > READY."""
    if any(r in REFUSING_REASONS for r in reasons):
        return REFUSE
    if any(r in UNKNOWN_REASONS for r in reasons):
        return UNKNOWN
    return WAIT if reasons else READY


def _headroom_ok(reasons: tuple, headroom) -> bool:
    """No reason: at least one more start fits. Any reason: none does."""
    if not qc._bounded_int(headroom, 0, MAX_WORKERS):
        return False
    return headroom >= 1 if not reasons else headroom == 0


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HostResourceObservation:
    """One caller-held observation of one host resource, in `unit` (the
    kind's own): total `capacity`, amount `in_use` and amount held back in
    `reserve`, with its `source`, `reliability` and UTC instant."""
    evidence_id: str
    resource_id: str
    kind: str
    unit: str
    capacity: int
    in_use: int
    reserve: int
    source: str
    reliability: str
    observed_at_utc: str


@dataclass(frozen=True)
class ResourceDemand:
    """Amount of `resource_id` ONE execution consumes, for every provider
    (`provider_id` None) or one provider (overrides the general demand)."""
    resource_id: str
    kind: str
    unit: str
    amount: int
    provider_id: Optional[str] = None


@dataclass(frozen=True)
class ResourceRequest:
    """Explicit, immutable resource question over one native Manifest and the
    FCP-9C-01 CapacityPlan evaluated over it. Validated by
    `evaluate_resources` (fail closed), not here."""
    request_id: str
    as_of_utc: str
    manifest: object
    capacity_plan: object
    observations: tuple = ()
    demands: tuple = ()
    conflict_graph: Optional[object] = None
    max_evidence_age_seconds: int = qc.DEFAULT_MAX_EVIDENCE_AGE_SECONDS
    schema_version: int = REQUEST_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ResourceView:
    """What one resource's evidence supports. Amounts only when certain."""
    resource_id: str
    kind: str
    unit: str
    reasons: tuple
    evidence_ids: tuple
    capacity: Optional[int] = None
    in_use: Optional[int] = None
    reserve: Optional[int] = None
    free: Optional[int] = None

    def __post_init__(self):
        if not (qc._valid_id(self.resource_id) and qc._in(self.kind, RESOURCE_KINDS)):
            raise ValueError("resource_id / kind must be valid")
        if self.unit != KIND_UNIT[self.kind]:
            raise ValueError("unit must be the kind's own")
        if not _codes_ok(self.reasons, RESOURCE_REASONS):
            raise ValueError("reasons must be ordered resource reason codes")
        if not (_sorted_ids(self.evidence_ids) and len(self.evidence_ids) <= MAX_OBSERVATIONS):
            raise ValueError("evidence_ids must be sorted unique ids")
        if (NO_EVIDENCE in self.reasons) != (not self.evidence_ids):
            raise ValueError("NO_EVIDENCE exactly when nothing is cited")
        amounts = (self.capacity, self.in_use, self.reserve, self.free)
        if self.reasons:
            if amounts != (None,) * 4:
                raise ValueError("an uncertain resource reports no amount")
            return
        if not all(qc._bounded_int(a, 0, UNIT_MAXIMUM[self.unit]) for a in amounts):
            raise ValueError("amounts must be bounded non-negative ints")
        if self.in_use > self.capacity or self.free != max(0, self.capacity - self.in_use - self.reserve):
            raise ValueError("free must be capacity minus in_use minus reserve")

    def to_dict(self) -> dict:
        return {
            "resource_id": self.resource_id, "kind": self.kind, "unit": self.unit, "reasons": list(self.reasons),
            "evidence_ids": list(self.evidence_ids), "capacity": self.capacity, "in_use": self.in_use,
            "reserve": self.reserve, "free": self.free,
        }


@dataclass(frozen=True)
class ProviderResourceBudget:
    """Narrowed concurrent limit of one provider. Construction re-derives the
    verdict and the limit, which never exceeds `base_limit`."""
    provider_id: str
    verdict: str
    reasons: tuple
    resource_ids: tuple
    base_limit: int
    occupied: int
    headroom: int
    limit: int

    def __post_init__(self):
        if not sc._valid_provider_id(self.provider_id):
            raise ValueError("provider_id must be a valid provider id")
        if not _codes_ok(self.reasons, RESULT_REASONS):
            raise ValueError("reasons must be ordered result reason codes")
        if self.verdict != verdict_for(self.reasons):
            raise ValueError("verdict must be exactly the one derived from reasons")
        if not (_sorted_ids(self.resource_ids) and len(self.resource_ids) <= MAX_DEMANDS):
            raise ValueError("resource_ids must be sorted unique ids")
        if not (qc._bounded_int(self.base_limit, 1, MAX_WORKERS) and qc._bounded_int(self.occupied, 0, cap.MAX_ITEMS)):
            raise ValueError("base_limit / occupied out of bounds")
        if not _headroom_ok(self.reasons, self.headroom):
            raise ValueError("headroom must match the reasons")
        if self.limit != min(self.base_limit, self.occupied + self.headroom):
            raise ValueError("limit must be min(base_limit, occupied + headroom)")

    def to_dict(self) -> dict:
        return {
            "provider_id": self.provider_id, "verdict": self.verdict, "reasons": list(self.reasons),
            "resource_ids": list(self.resource_ids), "base_limit": self.base_limit, "occupied": self.occupied,
            "headroom": self.headroom, "limit": self.limit,
        }


class _ResourceGuarantees(qc._QuotaGuarantees):
    """FCP-10A-01 zero-authority flags plus: no lock, no lease, no probe."""

    @property
    def lock_acquired(self) -> bool:
        return False

    @property
    def lease_acquired(self) -> bool:
        return False

    @property
    def host_probed(self) -> bool:
        return False

    @staticmethod
    def _guarantees() -> dict:
        guarantees = qc._QuotaGuarantees._guarantees()
        guarantees.update(marker=RESOURCE_MARKER, lock_acquired=False, lease_acquired=False, host_probed=False)
        return guarantees


@dataclass(frozen=True)
class ResourceEvaluation(_ResourceGuarantees):
    """Advisory narrowing. Echo fields hold only validated values (None and
    () when refused). Construction re-checks every invariant, so a hand-made
    evaluation cannot raise a limit or claim more than its reasons."""
    verdict: str
    request_id: Optional[str]
    request_fingerprint: Optional[str]
    request_reasons: tuple
    reasons: tuple
    evidence_ids: tuple
    base_max_workers: Optional[int]
    occupied_slots: Optional[int]
    headroom: Optional[int]
    max_workers: Optional[int]
    providers: tuple
    resources: tuple
    conflict_outcome: Optional[str] = None

    def __post_init__(self):
        if not qc._in(self.verdict, VERDICTS):
            raise ValueError("unknown verdict")
        if not _codes_ok(self.request_reasons, REQUEST_REASONS):
            raise ValueError("request_reasons must be ordered request reason codes")
        if self.request_reasons:
            echo = (self.request_id, self.request_fingerprint, self.base_max_workers, self.occupied_slots,
                    self.headroom, self.max_workers, self.conflict_outcome)
            if (self.verdict != REFUSE or self.reasons or self.evidence_ids or self.providers or self.resources
                    or echo != (None,) * len(echo)):
                raise ValueError("a refused request echoes nothing and decides nothing")
            return
        if not qc._valid_id(self.request_id):
            raise ValueError("request_id must be a valid id")
        if not (type(self.request_fingerprint) is str and sc._FINGERPRINT_RE.fullmatch(self.request_fingerprint)):
            raise ValueError("request_fingerprint must be a sha256 hex digest")
        if not _codes_ok(self.reasons, RESULT_REASONS):
            raise ValueError("reasons must be ordered result reason codes")
        if self.verdict != verdict_for(self.reasons):
            raise ValueError("verdict must be exactly the one derived from reasons")
        if not (_sorted_ids(self.evidence_ids) and len(self.evidence_ids) <= MAX_OBSERVATIONS):
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
        if self.conflict_outcome is not None and not qc._in(self.conflict_outcome, CONFLICT_OUTCOMES):
            raise ValueError("conflict_outcome must be a non-refused graph outcome")
        if not (type(self.resources) is tuple and all(type(r) is ResourceView for r in self.resources)):
            raise ValueError("resources must be ResourceViews")
        if [r.resource_id for r in self.resources] != sorted({r.resource_id for r in self.resources}):
            raise ValueError("resources must be sorted and unique")
        if not (type(self.providers) is tuple and 1 <= len(self.providers) <= qc.MAX_PROVIDERS
                and all(type(p) is ProviderResourceBudget for p in self.providers)):
            raise ValueError("providers must be 1..MAX_PROVIDERS ProviderResourceBudgets")
        ids = [p.provider_id for p in self.providers]
        if ids != sorted(set(ids)):
            raise ValueError("providers must be sorted and unique")
        known = {r.resource_id for r in self.resources}
        for budget in self.providers:
            if budget.base_limit > self.base_max_workers or not set(budget.resource_ids) <= known:
                raise ValueError("a provider never exceeds the global base nor cites unknown resources")
            if any(r in UNKNOWN_REASONS and r not in self.reasons for r in budget.reasons):
                raise ValueError("every provider doubt is a global doubt")
        if (DEMAND_EXCEEDS_CAPACITY in self.reasons) != all(DEMAND_EXCEEDS_CAPACITY in p.reasons
                                                            for p in self.providers):
            raise ValueError("globally refused exactly when no provider can ever fit")
        if any(self.headroom > p.headroom for p in self.providers if p.verdict != REFUSE):
            raise ValueError("global headroom never exceeds a startable provider's")

    @property
    def provider_limits(self) -> tuple:
        """Narrowed `(provider_id, limit)` pairs. Informational only."""
        return tuple((p.provider_id, p.limit) for p in self.providers)

    @property
    def runner_representable(self) -> bool:
        """True only when every narrowed value is one the Runner can hold
        (its `provider_limits` treat 0 as unlimited; `max_workers` >= 1)."""
        return (not self.request_reasons and self.max_workers >= 1
                and all(p.limit >= 1 for p in self.providers))

    def provider_budget(self, provider_id: str) -> Optional[ProviderResourceBudget]:
        for budget in self.providers:
            if budget.provider_id == provider_id:
                return budget
        return None

    def resource_view(self, resource_id: str) -> Optional[ResourceView]:
        for view in self.resources:
            if view.resource_id == resource_id:
                return view
        return None

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA, "schema_version": SCHEMA_VERSION, "verdict": self.verdict,
            "request_id": self.request_id, "request_fingerprint": self.request_fingerprint,
            "request_reasons": list(self.request_reasons), "reasons": list(self.reasons),
            "evidence_ids": list(self.evidence_ids), "base_max_workers": self.base_max_workers,
            "occupied_slots": self.occupied_slots, "headroom": self.headroom, "max_workers": self.max_workers,
            "providers": [p.to_dict() for p in self.providers], "resources": [r.to_dict() for r in self.resources],
            "conflict_outcome": self.conflict_outcome, **_ResourceGuarantees._guarantees(),
        }


def canonical_json(evaluation: ResourceEvaluation) -> str:
    """Stable, sorted, compact, size-bounded serialization of the exact
    evaluation type (a subclass cannot substitute `to_dict`)."""
    if type(evaluation) is not ResourceEvaluation:
        raise TypeError("canonical_json accepts only a ResourceEvaluation")
    text = sc._canonical(ResourceEvaluation.to_dict(evaluation))
    if len(text) > MAX_CANONICAL_JSON_BYTES:
        raise ValueError("canonical evaluation exceeds MAX_CANONICAL_JSON_BYTES")
    return text


def _refused(reasons) -> ResourceEvaluation:
    return ResourceEvaluation(
        verdict=REFUSE, request_id=None, request_fingerprint=None, request_reasons=_ordered(reasons, REQUEST_REASONS),
        reasons=(), evidence_ids=(), base_max_workers=None, occupied_slots=None, headroom=None, max_workers=None,
        providers=(), resources=(),
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _manifest_providers(manifest) -> set:
    return {p for s in manifest.workers for p in [s.provider] + list(s.fallback_providers)}


def _plan_reasons(plan, manifest, manifest_ok: bool) -> set:
    if type(plan) is not cap.CapacityPlan:
        return {CAPACITY_PLAN_NOT_TYPED}
    if plan.request_reasons:
        return {CAPACITY_PLAN_REFUSED}
    if not manifest_ok:
        return set()
    reasons = set()
    budgets = {b.provider_id for b in plan.provider_budgets}
    if (plan.dag_id != manifest.pipeline_id
            or sorted(d.item_id for d in plan.decisions) != sorted(s.id for s in manifest.workers)
            or not _manifest_providers(manifest) <= budgets
            or any(p not in budgets for p, _ in plan.effective_provider_limits)):
        reasons.add(CAPACITY_PLAN_MISMATCH)
    if plan.effective_max_workers > (manifest.max_workers or cap.DEFAULT_MAX_WORKERS) or any(
            limit > manifest.provider_limits.get(p, limit) for p, limit in plan.effective_provider_limits):
        reasons.add(CAPACITY_PLAN_EXCEEDS_MANIFEST)
    return reasons


def _graph_reasons(graph, manifest, manifest_ok: bool) -> set:
    if graph is None:
        return set()
    if type(graph) is not cf.ConflictGraph:
        return {CONFLICT_GRAPH_NOT_TYPED}
    if graph.request_reasons:
        return {CONFLICT_GRAPH_REFUSED}
    if manifest_ok and (graph.dag_id != manifest.pipeline_id or sorted(n.worker_id for n in graph.nodes)
                        != sorted(s.id for s in manifest.workers)):
        return {CONFLICT_GRAPH_MISMATCH}
    return set()


def _observation_reasons(obs: HostResourceObservation) -> set:
    reasons = set()
    if not qc._valid_id(obs.evidence_id):
        reasons.add(OBSERVATION_ID_INVALID)
    if not qc._valid_id(obs.resource_id):
        reasons.add(OBSERVATION_RESOURCE_INVALID)
    if not qc._in(obs.kind, RESOURCE_KINDS):
        reasons.add(OBSERVATION_KIND_UNKNOWN)
    elif type(obs.unit) is not str or obs.unit != KIND_UNIT[obs.kind]:
        reasons.add(OBSERVATION_UNIT_MISMATCH)
    elif not all(qc._bounded_int(a, 0, UNIT_MAXIMUM[obs.unit]) for a in (obs.capacity, obs.in_use, obs.reserve)):
        reasons.add(OBSERVATION_AMOUNT_INVALID)
    source_ok = qc._in(obs.source, SOURCES)
    if not source_ok:
        reasons.add(OBSERVATION_SOURCE_UNKNOWN)
    if not qc._in(obs.reliability, RELIABILITIES):
        reasons.add(OBSERVATION_RELIABILITY_UNKNOWN)
    elif source_ok and RELIABILITIES.index(obs.reliability) > RELIABILITIES.index(SOURCE_MAX_RELIABILITY[obs.source]):
        reasons.add(OBSERVATION_RELIABILITY_OVERCLAIMED)
    if qc.parse_utc(obs.observed_at_utc) is None:
        reasons.add(OBSERVATION_TIME_INVALID)
    return reasons


def _demand_reasons(demand: ResourceDemand, providers: Optional[set]) -> set:
    reasons = set()
    if not qc._valid_id(demand.resource_id):
        reasons.add(DEMAND_RESOURCE_INVALID)
    if not qc._in(demand.kind, RESOURCE_KINDS):
        reasons.add(DEMAND_KIND_UNKNOWN)
    elif type(demand.unit) is not str or demand.unit != KIND_UNIT[demand.kind]:
        reasons.add(DEMAND_UNIT_MISMATCH)
    elif not qc._bounded_int(demand.amount, 1, UNIT_MAXIMUM[demand.unit]):
        reasons.add(DEMAND_AMOUNT_INVALID)
    if demand.provider_id is not None and not (
            sc._valid_provider_id(demand.provider_id) and (providers is None or demand.provider_id in providers)):
        reasons.add(DEMAND_PROVIDER_UNKNOWN)
    return reasons


def _structural_reasons(request) -> tuple:
    if type(request) is not ResourceRequest:
        return (REQUEST_NOT_TYPED,)
    reasons = set()
    if not (sc._is_int(request.schema_version) and request.schema_version == REQUEST_SCHEMA_VERSION):
        reasons.add(SCHEMA_VERSION_UNSUPPORTED)
    if not qc._valid_id(request.request_id):
        reasons.add(REQUEST_ID_INVALID)
    if qc.parse_utc(request.as_of_utc) is None:
        reasons.add(AS_OF_INVALID)
    if not qc._bounded_int(request.max_evidence_age_seconds, 1, qc.MAX_EVIDENCE_AGE_SECONDS):
        reasons.add(MAX_EVIDENCE_AGE_INVALID)
    manifest = request.manifest
    manifest_reasons = cap._manifest_reasons(manifest)
    if manifest_reasons:
        reasons.add(MANIFEST_NOT_TYPED if MANIFEST_NOT_TYPED in manifest_reasons else MANIFEST_INVALID)
    plan_reasons = _plan_reasons(request.capacity_plan, manifest, not manifest_reasons)
    reasons |= plan_reasons
    reasons |= _graph_reasons(request.conflict_graph, manifest, not manifest_reasons)
    kinds = {}
    observations = request.observations
    if not (type(observations) is tuple and len(observations) <= MAX_OBSERVATIONS
            and all(type(o) is HostResourceObservation for o in observations)):
        reasons.add(OBSERVATIONS_MALFORMED)
        observations = ()
    for obs in observations:
        obs_reasons = _observation_reasons(obs)
        reasons |= obs_reasons
        if not obs_reasons & {OBSERVATION_RESOURCE_INVALID, OBSERVATION_KIND_UNKNOWN}:
            kinds.setdefault(obs.resource_id, set()).add(obs.kind)
    providers = None if plan_reasons else {b.provider_id for b in request.capacity_plan.provider_budgets}
    demands = request.demands
    if not (type(demands) is tuple and len(demands) <= MAX_DEMANDS
            and all(type(d) is ResourceDemand for d in demands)):
        reasons.add(DEMANDS_MALFORMED)
        demands = ()
    elif not demands:
        reasons.add(DEMANDS_EMPTY)
    for demand in demands:
        demand_reasons = _demand_reasons(demand, providers)
        reasons |= demand_reasons
        if not demand_reasons & {DEMAND_RESOURCE_INVALID, DEMAND_KIND_UNKNOWN}:
            kinds.setdefault(demand.resource_id, set()).add(demand.kind)
    keys = [(d.resource_id, d.provider_id) for d in demands]
    if len(set(keys)) != len(keys):
        reasons.add(DEMAND_DUPLICATE)
    if any(len(k) > 1 for k in kinds.values()):
        reasons.add(RESOURCE_KIND_AMBIGUOUS)
    ids = [request.request_id] + [o.evidence_id for o in observations]
    named = ids + [o.resource_id for o in observations] + [d.resource_id for d in demands] + [
        d.provider_id for d in demands if d.provider_id is not None]
    if any(qc._secret_shaped(i) for i in named):
        reasons.add(ID_SECRET_SHAPED)
    strings = [i for i in ids if type(i) is str]
    if len(strings) != len(set(strings)):
        reasons.add(ID_DUPLICATE)
    return _ordered(reasons, REQUEST_REASONS)


def _utc(value) -> Optional[str]:
    return None if value is None else sc._utc_text(qc.parse_utc(value))


def _request_dict(request: ResourceRequest) -> dict:
    manifest, plan, graph = request.manifest, request.capacity_plan, request.conflict_graph
    return {
        "schema": REQUEST_SCHEMA, "schema_version": REQUEST_SCHEMA_VERSION, "request_id": request.request_id,
        "as_of_utc": _utc(request.as_of_utc), "max_evidence_age_seconds": request.max_evidence_age_seconds,
        "manifest": {
            "pipeline_id": manifest.pipeline_id, "sha256": manifest.sha256 if type(manifest.sha256) is str else None,
            "max_workers": manifest.max_workers, "provider_limits": sorted([p, v] for p, v in
                                                                           manifest.provider_limits.items()),
            "workers": sorted(s.id for s in manifest.workers),
        },
        "capacity_plan_sha256": hashlib.sha256(cap.canonical_json(plan).encode("ascii")).hexdigest(),
        "conflict_graph_sha256": None if graph is None else hashlib.sha256(
            cf.canonical_json(graph).encode("ascii")).hexdigest(),
        "observations": sorted(
            ({"evidence_id": o.evidence_id, "resource_id": o.resource_id, "kind": o.kind, "unit": o.unit,
              "capacity": o.capacity, "in_use": o.in_use, "reserve": o.reserve, "source": o.source,
              "reliability": o.reliability, "observed_at_utc": _utc(o.observed_at_utc)}
             for o in request.observations), key=lambda d: d["evidence_id"]),
        "demands": sorted(
            ({"resource_id": d.resource_id, "kind": d.kind, "unit": d.unit, "amount": d.amount,
              "provider_id": d.provider_id} for d in request.demands),
            key=lambda d: (d["resource_id"], d["provider_id"] or "")),
    }


def validate_request(request) -> tuple:
    """Ordered request refusal codes; () for a valid request. Never raises
    and never echoes raw input."""
    reasons = _structural_reasons(request)
    if reasons:
        return reasons
    if len(sc._canonical(_request_dict(request))) > MAX_CANONICAL_JSON_BYTES:
        return (REQUEST_TOO_LARGE,)
    return ()


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def _resource_view(resource_id: str, kind: str, observations: list, as_of, max_age: int) -> ResourceView:
    reasons = set()
    if not observations:
        reasons.add(NO_EVIDENCE)
    for obs in observations:
        observed = qc.parse_utc(obs.observed_at_utc)
        if observed > as_of:
            reasons.add(EVIDENCE_FROM_FUTURE)
        elif (as_of - observed).total_seconds() > max_age:
            reasons.add(EVIDENCE_STALE)
        if obs.reliability != qc.RELIABILITY_CALLER_OBSERVED:
            reasons.add(EVIDENCE_UNVERIFIED)
        if obs.in_use > obs.capacity:
            reasons.add(EVIDENCE_CONTRADICTORY)
    if len({o.capacity for o in observations}) > 1:
        reasons.add(EVIDENCE_CONTRADICTORY)
    fields = dict(resource_id=resource_id, kind=kind, unit=KIND_UNIT[kind],
                  reasons=_ordered(reasons, RESOURCE_REASONS),
                  evidence_ids=tuple(sorted(o.evidence_id for o in observations)))
    if reasons:
        return ResourceView(**fields)
    capacity = observations[0].capacity
    in_use, reserve = max(o.in_use for o in observations), max(o.reserve for o in observations)
    return ResourceView(capacity=capacity, in_use=in_use, reserve=reserve,
                        free=max(0, capacity - in_use - reserve), **fields)


def _demands_of(provider: str, demands: tuple) -> dict:
    """resource_id -> (kind, amount): general demands, then the provider's
    own overriding them."""
    applicable = {d.resource_id: (d.kind, d.amount) for d in demands if d.provider_id is None}
    applicable.update({d.resource_id: (d.kind, d.amount) for d in demands if d.provider_id == provider})
    return applicable


def _fits(free: int, amount: int) -> int:
    return min(free // amount, MAX_WORKERS)


def evaluate_resources(request: ResourceRequest) -> ResourceEvaluation:
    """Pure, deterministic narrowing of the Manifest / Runner concurrency
    limits by injected host resource observations. Never raises on bad input
    and never mutates it: an invalid request is an explained REFUSE. The
    result never authorizes dispatch, raises a limit, holds a lease or a
    reservation, probes the host, switches a provider or buys anything."""
    reasons = validate_request(request)
    if reasons:
        return _refused(reasons)
    as_of = qc.parse_utc(request.as_of_utc)
    plan, graph, demands = request.capacity_plan, request.conflict_graph, request.demands

    kind_of = {d.resource_id: d.kind for d in demands}
    kind_of.update({o.resource_id: o.kind for o in request.observations})
    views = {
        rid: _resource_view(rid, kind_of[rid], [o for o in request.observations if o.resource_id == rid], as_of,
                            request.max_evidence_age_seconds)
        for rid in sorted(kind_of)
    }

    conflict_reasons = set()
    if any(d.kind == KIND_SPECIAL for d in demands):
        if graph is None:
            conflict_reasons.add(CONFLICTS_UNASSESSED)
        elif graph.outcome == cf.UNKNOWN:
            conflict_reasons.add(CONFLICT_UNIDENTIFIED)

    base = plan.effective_max_workers
    limit_of = dict(plan.effective_provider_limits)
    budgets = []
    applicable_of = {}
    for budget in plan.provider_budgets:
        provider = budget.provider_id
        applicable = _demands_of(provider, demands)
        applicable_of[provider] = applicable
        provider_reasons = set()
        if not {kind for kind, _ in applicable.values()} >= set(CORE_KINDS):
            provider_reasons.add(DEMAND_UNDECLARED)
        if any(kind == KIND_SPECIAL for kind, _ in applicable.values()):
            provider_reasons |= conflict_reasons
        for rid, (_, amount) in applicable.items():
            view = views[rid]
            if view.reasons:
                provider_reasons |= set(view.reasons)
            elif amount > view.capacity - view.reserve:
                provider_reasons.add(DEMAND_EXCEEDS_CAPACITY)
        headroom = 0
        if not provider_reasons:
            headroom = min(_fits(views[rid].free, amount) for rid, (_, amount) in applicable.items())
            if headroom == 0:
                provider_reasons.add(RESOURCE_SATURATED)
        ordered = _ordered(provider_reasons, RESULT_REASONS)
        base_limit = min(limit_of.get(provider, base), base)
        budgets.append(ProviderResourceBudget(
            provider_id=provider, verdict=verdict_for(ordered), reasons=ordered,
            resource_ids=tuple(sorted(applicable)), base_limit=base_limit, occupied=budget.occupied,
            headroom=headroom, limit=min(base_limit, budget.occupied + headroom),
        ))

    global_reasons = {r for b in budgets for r in b.reasons if r in UNKNOWN_REASONS} | conflict_reasons
    startable = [b.provider_id for b in budgets if DEMAND_EXCEEDS_CAPACITY not in b.reasons]
    if not startable:
        global_reasons.add(DEMAND_EXCEEDS_CAPACITY)
    headroom = 0
    if not global_reasons:
        # Per resource, the largest demand any startable provider could
        # place: no mix of `headroom` starts can exceed what is free.
        largest = {}
        for provider in startable:
            for rid, (_, amount) in applicable_of[provider].items():
                largest[rid] = max(largest.get(rid, 0), amount)
        headroom = min(_fits(views[rid].free, amount) for rid, amount in largest.items())
        if headroom == 0:
            global_reasons.add(RESOURCE_SATURATED)
    ordered = _ordered(global_reasons, RESULT_REASONS)
    cited = {e for rid in {d.resource_id for d in demands} for e in views[rid].evidence_ids}
    return ResourceEvaluation(
        verdict=verdict_for(ordered), request_id=request.request_id,
        request_fingerprint=hashlib.sha256(sc._canonical(_request_dict(request)).encode("ascii")).hexdigest(),
        request_reasons=(), reasons=ordered, evidence_ids=tuple(sorted(cited)), base_max_workers=base,
        occupied_slots=plan.occupied_slots, headroom=headroom,
        max_workers=min(base, plan.occupied_slots + headroom), providers=tuple(budgets),
        resources=tuple(views[rid] for rid in sorted(views)),
        conflict_outcome=None if graph is None else graph.outcome,
    )
