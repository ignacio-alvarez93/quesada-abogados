"""FCP-9B-02: DAG planning and governed admission - deterministic,
fail-closed, provider-neutral, NON-AUTHORITATIVE.

Answers ONE question: given a native `fabric_dag_blueprint.DagBlueprint`, an
explicit evaluation instant, the node states the caller OBSERVED and the
workers' declared footprints, which ready nodes would form the next
admissible batch, which wait, which are refused or unknown, and why? It never
answers "may I dispatch now?".

Why this is a consultative plan, not a scheduler
------------------------------------------------
* Structure is never re-validated here. The blueprint is handed to
  `fabric_dag_blueprint.compile_blueprint` EXACTLY ONCE, which delegates to
  `runner_pipeline.parse_manifest`; cycles, unknown/self dependencies,
  providers, modes, policies and limits are refused there and surface here
  only as the native error CODES (`BLUEPRINT_REFUSED`). Edges, priorities,
  dependency policies, providers and modes are read from the compiled
  `PlanNode`s / native `Manifest`, never from the raw declaration. The only
  I/O is that compiler's own established read-only worktree/Work Order
  inspection; everything after it is pure.
* Director and Runner stay the ONLY execution authorities. Nothing here
  starts, queues, leases, retries, merges, switches a provider, runs a
  process, or writes anything; no pool, lease, lock, ledger or schema of
  its own exists. `EXECUTION_TIME_GUARDS_NOT_EVALUATED` lists what the
  Runner still decides at execution time.
* Composition, not duplication: the window is FCP-9A-02 `evaluate_window`
  over the native `Manifest` bounds; worker incompatibility is FCP-9B-01
  `analyze_conflicts`; dependency acceptance is the Runner's own
  `DEPENDENCY_POLICIES`.
* Nothing is invented: node states are caller-supplied OBSERVATIONS in the
  Runner's `WorkerState` vocabulary (omitted = UNKNOWN), no duration, finish
  time or future state is assumed, and only the CURRENT batch is proposed.
* Limits are upper bounds and are never raised: the global cap is the
  manifest's `max_workers` (Runner default `DEFAULT_MAX_WORKERS` when
  absent) and per-provider caps are the manifest's `provider_limits`; the
  request may only NARROW them (the lower value always wins). RUNNING nodes
  occupy their slots and their provider's quota.
* Provider-neutral: provider ids are opaque and only ever compared for
  equality; none is named, preferred or special-cased.

Planning order and fairness
---------------------------
The order is the Runner's dispatch order: highest `priority` first, then
declared node order (a total, stable key). Tied nodes are therefore admitted
strictly in declared order; a node is passed over only for a concrete reason
of its own (provider limit or hold, conflict) and never by an arbitrary
choice, and once the global cap is reached every later node waits, so no
later tied node can overtake an earlier one for a slot.

Decisions (per node; none of them is a permit)
----------------------------------------------
* INACTIVE: the node is not pending (RUNNING, terminal, or in a Runner-owned
  wait/hold state such as RETRY_WAIT).
* REFUSED: window expired, or a dependency ended in a state its policy does
  not accept (the Runner would cancel it).
* UNKNOWN: a needed fact is missing - own or a dependency's state unknown,
  a BLOCKED dependency under a policy that may or may not accept it (the
  Runner's block reason is not observed), any peer's state unknown (it may
  be running), conflicts not assessed, or the node's footprint unidentified.
* WAITING: window not open, dependency pending, provider held, conflict with
  a running or an already admitted node, or no global/provider slot left.
* ADMISSIBLE: none of the above and a slot was assigned (`slot` 0..n-1 in
  planning order). Informational only.
Precedence: INACTIVE > REFUSED > UNKNOWN > WAITING.

Outcome: REFUSED for an invalid request (nothing echoed), else UNKNOWN if
any node is UNKNOWN, else ADMISSIBLE, WAITING, REFUSED if any node is, else
IDLE. Output (`DagPlan`, schema `fcp9b02-scheduler-dag-plan-v1`) holds only
validated ids, enumerated codes, integers and fingerprints - no path, Work
Order text, capability, authorization or shell grant ever reaches it - and
fixes every FCP-9A-01 zero-authority flag to False as read-only properties.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Optional

try:
    from scripts.ai import fabric_dag_blueprint as bp
    from scripts.ai import fabric_scheduler_conflicts as cf
    from scripts.ai import fabric_scheduler_contract as sc
    from scripts.ai import fabric_scheduler_window as sw
    from scripts.ai import runner_pipeline as pipeline
except ImportError:  # pragma: no cover - direct script execution
    import fabric_dag_blueprint as bp  # type: ignore[no-redef]
    import fabric_scheduler_conflicts as cf  # type: ignore[no-redef]
    import fabric_scheduler_contract as sc  # type: ignore[no-redef]
    import fabric_scheduler_window as sw  # type: ignore[no-redef]
    import runner_pipeline as pipeline  # type: ignore[no-redef]

REQUEST_SCHEMA = "fcp9b02-scheduler-dag-plan-request-v1"
REQUEST_SCHEMA_VERSION = 1
SCHEMA = "fcp9b02-scheduler-dag-plan-v1"
SCHEMA_VERSION = 1
PLAN_MARKER = "FCP9B02_DAG_PLAN_ADVISORY_ONLY_NOT_CERTIFIED_NOT_AUTHORIZED"

MAX_NODES = bp.MAX_BLUEPRINT_NODES
MAX_WORKERS = pipeline.MAX_PIPELINE_WORKERS
DEFAULT_MAX_WORKERS = pipeline.DEFAULT_MAX_WORKERS
MAX_CANONICAL_JSON_BYTES = 131072

# Runner guards this preview never evaluates; they stay the Runner's.
EXECUTION_TIME_GUARDS_NOT_EVALUATED = bp.EXECUTION_TIME_GUARDS_NOT_EVALUATED + (
    "WRITE_LEASE", "SELF_TARGET", "PROCESS_CONFIRMED_STOPPED", "PROVIDER_QUOTA_ELIGIBILITY",
)

_W = pipeline.WorkerState
STATE_UNKNOWN = "UNKNOWN"
NODE_STATES = tuple(s.value for s in _W) + (STATE_UNKNOWN,)
_PENDING_STATES = frozenset({_W.QUEUED.value, _W.WAITING_DEPENDENCY.value, _W.READY.value})
_TERMINAL_STATES = frozenset(s.value for s in pipeline.TERMINAL_STATES)
# States that hold every start of the same provider (`_provider_start_held`;
# the quota eligibility instant is not observed here, so it always holds).
_PROVIDER_HOLDING_STATES = frozenset({_W.BLOCKED_PROVIDER_AUTH.value, _W.WAITING_PROVIDER_QUOTA.value})

_NATIVE_CODE_RE = re.compile(r"[A-Z][A-Z0-9_]{0,63}")

# Batch outcomes and node decisions.
ADMISSIBLE = "ADMISSIBLE"
WAITING = "WAITING"
REFUSED = "REFUSED"
UNKNOWN = "UNKNOWN"
INACTIVE = "INACTIVE"
IDLE = "IDLE"
DECISIONS = (ADMISSIBLE, WAITING, REFUSED, UNKNOWN, INACTIVE)
OUTCOMES = (ADMISSIBLE, WAITING, REFUSED, UNKNOWN, IDLE)

# Request-level refusal codes, in their fixed canonical order.
REQUEST_NOT_TYPED = "REQUEST_NOT_TYPED"
SCHEMA_VERSION_UNSUPPORTED = "SCHEMA_VERSION_UNSUPPORTED"
AS_OF_INVALID = "AS_OF_INVALID"
NODE_STATES_MALFORMED = "NODE_STATES_MALFORMED"
NODE_STATE_INVALID = "NODE_STATE_INVALID"
NODE_STATE_DUPLICATE = "NODE_STATE_DUPLICATE"
CONFLICT_REQUEST_NOT_TYPED = "CONFLICT_REQUEST_NOT_TYPED"
MAX_WORKERS_INVALID = "MAX_WORKERS_INVALID"
PROVIDER_LIMITS_MALFORMED = "PROVIDER_LIMITS_MALFORMED"
PROVIDER_LIMIT_DUPLICATE = "PROVIDER_LIMIT_DUPLICATE"
BLUEPRINT_REFUSED = "BLUEPRINT_REFUSED"
BLUEPRINT_UNEVALUABLE = "BLUEPRINT_UNEVALUABLE"
BLUEPRINT_IDENTITY_MISMATCH = "BLUEPRINT_IDENTITY_MISMATCH"
NODE_ID_UNSUPPORTED = "NODE_ID_UNSUPPORTED"
PROVIDER_ID_UNSUPPORTED = "PROVIDER_ID_UNSUPPORTED"
NODE_STATE_UNKNOWN_NODE = "NODE_STATE_UNKNOWN_NODE"
WINDOW_INVALID = "WINDOW_INVALID"
CONFLICT_DAG_MISMATCH = "CONFLICT_DAG_MISMATCH"
CONFLICT_WORKERS_MISMATCH = "CONFLICT_WORKERS_MISMATCH"
CONFLICT_MODE_MISMATCH = "CONFLICT_MODE_MISMATCH"
CONFLICT_WORKTREE_MISMATCH = "CONFLICT_WORKTREE_MISMATCH"
CONFLICT_REQUEST_REFUSED = "CONFLICT_REQUEST_REFUSED"
REQUEST_TOO_LARGE = "REQUEST_TOO_LARGE"
REQUEST_REASONS = (
    REQUEST_NOT_TYPED, SCHEMA_VERSION_UNSUPPORTED, AS_OF_INVALID, NODE_STATES_MALFORMED, NODE_STATE_INVALID,
    NODE_STATE_DUPLICATE, CONFLICT_REQUEST_NOT_TYPED, MAX_WORKERS_INVALID, PROVIDER_LIMITS_MALFORMED,
    PROVIDER_LIMIT_DUPLICATE, BLUEPRINT_REFUSED, BLUEPRINT_UNEVALUABLE, BLUEPRINT_IDENTITY_MISMATCH,
    NODE_ID_UNSUPPORTED, PROVIDER_ID_UNSUPPORTED, NODE_STATE_UNKNOWN_NODE, WINDOW_INVALID, CONFLICT_DAG_MISMATCH,
    CONFLICT_WORKERS_MISMATCH, CONFLICT_MODE_MISMATCH, CONFLICT_WORKTREE_MISMATCH, CONFLICT_REQUEST_REFUSED,
    REQUEST_TOO_LARGE,
)

# Node-level reason codes, grouped by the decision they force, in their
# fixed canonical order.
NODE_RUNNING = "NODE_RUNNING"
NODE_TERMINAL = "NODE_TERMINAL"
NODE_NOT_PENDING = "NODE_NOT_PENDING"
WINDOW_EXPIRED = "WINDOW_EXPIRED"
DEPENDENCY_UNSATISFIABLE = "DEPENDENCY_UNSATISFIABLE"
NODE_STATE_UNKNOWN = "NODE_STATE_UNKNOWN"
DEPENDENCY_STATE_UNKNOWN = "DEPENDENCY_STATE_UNKNOWN"
DEPENDENCY_STATE_AMBIGUOUS = "DEPENDENCY_STATE_AMBIGUOUS"
PEER_STATE_UNKNOWN = "PEER_STATE_UNKNOWN"
CONFLICTS_UNASSESSED = "CONFLICTS_UNASSESSED"
CONFLICT_UNIDENTIFIED = "CONFLICT_UNIDENTIFIED"
WINDOW_NOT_OPEN = "WINDOW_NOT_OPEN"
DEPENDENCY_PENDING = "DEPENDENCY_PENDING"
PROVIDER_HELD = "PROVIDER_HELD"
CONFLICT_WITH_RUNNING = "CONFLICT_WITH_RUNNING"
WORKER_LIMIT_REACHED = "WORKER_LIMIT_REACHED"
PROVIDER_LIMIT_REACHED = "PROVIDER_LIMIT_REACHED"
CONFLICT_WITH_ADMITTED = "CONFLICT_WITH_ADMITTED"
INACTIVE_REASONS = (NODE_RUNNING, NODE_TERMINAL, NODE_NOT_PENDING)
REFUSING_REASONS = (WINDOW_EXPIRED, DEPENDENCY_UNSATISFIABLE)
UNKNOWN_REASONS = (
    NODE_STATE_UNKNOWN, DEPENDENCY_STATE_UNKNOWN, DEPENDENCY_STATE_AMBIGUOUS, PEER_STATE_UNKNOWN,
    CONFLICTS_UNASSESSED, CONFLICT_UNIDENTIFIED,
)
WAITING_REASONS = (
    WINDOW_NOT_OPEN, DEPENDENCY_PENDING, PROVIDER_HELD, CONFLICT_WITH_RUNNING, WORKER_LIMIT_REACHED,
    PROVIDER_LIMIT_REACHED, CONFLICT_WITH_ADMITTED,
)
NODE_REASONS = INACTIVE_REASONS + REFUSING_REASONS + UNKNOWN_REASONS + WAITING_REASONS

_WINDOW_STATUSES = (sw.READY, sw.WAIT_UNTIL, sw.EXPIRED)


def _ordered(codes, vocabulary) -> tuple:
    return sc._ordered(codes, vocabulary)


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DagPlanRequest:
    """Explicit, immutable planning request over one native blueprint.
    `node_states` is a tuple of `(node_id, state)` observations in the
    Runner's `WorkerState` vocabulary (or "UNKNOWN"); `max_workers` and
    `provider_limits` may only narrow the manifest's own limits. Validated by
    `plan_dag` (fail closed), not here."""
    blueprint: object
    as_of_utc: str
    node_states: tuple = ()
    conflict_request: Optional[cf.ConflictRequest] = None
    max_workers: Optional[int] = None
    provider_limits: tuple = ()
    schema_version: int = REQUEST_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _decision_for(reasons: tuple) -> str:
    if any(r in INACTIVE_REASONS for r in reasons):
        return INACTIVE
    if any(r in REFUSING_REASONS for r in reasons):
        return REFUSED
    if any(r in UNKNOWN_REASONS for r in reasons):
        return UNKNOWN
    return WAITING if reasons else ADMISSIBLE


def _plan_outcome(decisions: tuple) -> str:
    present = {d.decision for d in decisions}
    for outcome in (UNKNOWN, ADMISSIBLE, WAITING, REFUSED):
        if outcome in present:
            return outcome
    return IDLE


@dataclass(frozen=True)
class NodeDecision:
    """Per-node advisory decision. Construction re-derives `decision` from
    `reasons`, so a hand-made decision cannot claim more than its reasons."""
    node_id: str
    state: str
    provider: str
    mode: str
    priority: int
    decision: str
    reasons: tuple
    slot: Optional[int]

    def __post_init__(self):
        if not sc._safe_id(self.node_id):
            raise ValueError("node_id must be a safe id")
        if type(self.state) is not str or self.state not in NODE_STATES:
            raise ValueError("state must be an observed node state")
        if not sc._valid_provider_id(self.provider):
            raise ValueError("provider must be a valid provider id")
        if type(self.mode) is not str or self.mode not in sc.MODES:
            raise ValueError("unknown mode")
        if not sc._is_int(self.priority):
            raise ValueError("priority must be an int")
        if not (type(self.reasons) is tuple and all(type(r) is str and r in NODE_REASONS for r in self.reasons)
                and self.reasons == _ordered(self.reasons, NODE_REASONS)):
            raise ValueError("reasons must be ordered node reason codes")
        if type(self.decision) is not str or self.decision != _decision_for(self.reasons):
            raise ValueError("decision must be exactly the one derived from reasons")
        if self.decision == INACTIVE and len(self.reasons) != 1:
            raise ValueError("an INACTIVE node carries exactly one inactive reason")
        if (self.state in _PENDING_STATES) != (self.decision != INACTIVE and self.state != STATE_UNKNOWN):
            raise ValueError("only a pending node is a candidate")
        if self.state == STATE_UNKNOWN and self.reasons != (NODE_STATE_UNKNOWN,):
            raise ValueError("a node of unknown state is UNKNOWN for that reason only")
        if self.decision == ADMISSIBLE:
            if not (sc._is_int(self.slot) and 0 <= self.slot < MAX_WORKERS):
                raise ValueError("an ADMISSIBLE node carries a slot")
        elif self.slot is not None:
            raise ValueError("only an ADMISSIBLE node carries a slot")

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id, "state": self.state, "provider": self.provider, "mode": self.mode,
            "priority": self.priority, "decision": self.decision, "reasons": list(self.reasons), "slot": self.slot,
        }


class _PlanGuarantees(sc._NotAuthorized):
    @staticmethod
    def _guarantees() -> dict:
        guarantees = sc._NotAuthorized._guarantees()
        guarantees["marker"] = PLAN_MARKER
        return guarantees


@dataclass(frozen=True)
class DagPlan(_PlanGuarantees):
    """Consultative DAG admission plan. Echo fields hold only validated values
    (None and () when the request was refused). Construction re-checks every
    invariant, so a hand-made plan cannot exceed its limits, admit outside an
    open window or claim an outcome its decisions do not support."""
    outcome: str
    dag_id: Optional[str]
    blueprint_fingerprint: Optional[str]
    request_fingerprint: Optional[str]
    window_status: Optional[str]
    effective_max_workers: Optional[int]
    effective_provider_limits: tuple
    planning_order: tuple
    request_reasons: tuple
    blueprint_error_codes: tuple
    decisions: tuple

    def __post_init__(self):
        if type(self.outcome) is not str or self.outcome not in OUTCOMES:
            raise ValueError("unknown plan outcome")
        if not (type(self.request_reasons) is tuple
                and all(type(r) is str and r in REQUEST_REASONS for r in self.request_reasons)
                and self.request_reasons == _ordered(self.request_reasons, REQUEST_REASONS)):
            raise ValueError("request_reasons must be ordered request reason codes")
        codes = self.blueprint_error_codes
        if not (type(codes) is tuple and all(type(c) is str and _NATIVE_CODE_RE.fullmatch(c) for c in codes)
                and codes == tuple(sorted(set(codes)))):
            raise ValueError("blueprint_error_codes must be sorted unique native codes")
        if codes and BLUEPRINT_REFUSED not in self.request_reasons:
            raise ValueError("native codes accompany BLUEPRINT_REFUSED only")
        if not (type(self.decisions) is tuple and all(type(d) is NodeDecision for d in self.decisions)):
            raise ValueError("decisions must be a tuple of NodeDecision")
        echo = (self.dag_id, self.blueprint_fingerprint, self.request_fingerprint, self.window_status,
                self.effective_max_workers)
        if self.request_reasons:
            if (self.outcome != REFUSED or self.decisions or self.planning_order or self.effective_provider_limits
                    or echo != (None,) * len(echo)):
                raise ValueError("a refused request echoes nothing and decides nothing")
            return
        if not sc._safe_id(self.dag_id):
            raise ValueError("dag_id must be a safe id")
        for fingerprint in (self.blueprint_fingerprint, self.request_fingerprint):
            if not (type(fingerprint) is str and sc._FINGERPRINT_RE.fullmatch(fingerprint)):
                raise ValueError("fingerprints must be sha256 hex digests")
        if self.window_status not in _WINDOW_STATUSES:
            raise ValueError("window_status must be a non-INVALID window status")
        if not (sc._is_int(self.effective_max_workers) and 1 <= self.effective_max_workers <= MAX_WORKERS):
            raise ValueError("effective_max_workers must be in 1..MAX_WORKERS")
        limits = self.effective_provider_limits
        if not (type(limits) is tuple and all(
                type(p) is tuple and len(p) == 2 and sc._valid_provider_id(p[0]) and sc._is_int(p[1]) and p[1] >= 1
                for p in limits) and list(limits) == sorted(limits) and len({p[0] for p in limits}) == len(limits)):
            raise ValueError("effective_provider_limits must be sorted unique positive pairs")
        ids = [d.node_id for d in self.decisions]
        if not 1 <= len(ids) <= MAX_NODES or len(set(ids)) != len(ids):
            raise ValueError("decisions must name each node once")
        if not (type(self.planning_order) is tuple and sorted(self.planning_order) == sorted(ids)):
            raise ValueError("planning_order must be a permutation of the nodes")
        by_id = {d.node_id: d for d in self.decisions}
        admitted = [by_id[i] for i in self.planning_order if by_id[i].decision == ADMISSIBLE]
        if [d.slot for d in admitted] != list(range(len(admitted))):
            raise ValueError("slots must be 0..n-1 in planning order")
        if admitted and self.window_status != sw.READY:
            raise ValueError("nothing is admissible outside an open window")
        running = [d for d in self.decisions if d.state == _W.RUNNING.value]
        if len(admitted) + len(running) > self.effective_max_workers and admitted:
            raise ValueError("admitted plus running nodes exceed effective_max_workers")
        for provider, limit in limits:
            used = sum(1 for d in admitted + running if d.provider == provider)
            if used > limit and any(d.provider == provider for d in admitted):
                raise ValueError("admitted plus running nodes exceed a provider limit")
        if self.outcome != _plan_outcome(self.decisions):
            raise ValueError("outcome must be exactly the one derived from decisions")

    def decision_of(self, node_id: str) -> Optional[NodeDecision]:
        for decision in self.decisions:
            if decision.node_id == node_id:
                return decision
        return None

    @property
    def admitted(self) -> tuple:
        """Informational only, never a permit: ADMISSIBLE node ids by slot."""
        chosen = [d for d in self.decisions if d.decision == ADMISSIBLE]
        return tuple(d.node_id for d in sorted(chosen, key=lambda d: d.slot))

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA, "schema_version": SCHEMA_VERSION, "outcome": self.outcome, "dag_id": self.dag_id,
            "blueprint_fingerprint": self.blueprint_fingerprint, "request_fingerprint": self.request_fingerprint,
            "window_status": self.window_status, "effective_max_workers": self.effective_max_workers,
            "effective_provider_limits": [list(p) for p in self.effective_provider_limits],
            "planning_order": list(self.planning_order), "request_reasons": list(self.request_reasons),
            "blueprint_error_codes": list(self.blueprint_error_codes),
            "counts": {d: sum(1 for x in self.decisions if x.decision == d) for d in DECISIONS},
            "decisions": [d.to_dict() for d in self.decisions],
            "execution_time_guards_not_evaluated": list(EXECUTION_TIME_GUARDS_NOT_EVALUATED),
            **_PlanGuarantees._guarantees(),
        }


def canonical_json(plan: DagPlan) -> str:
    """Stable, sorted, compact, size-bounded serialization of the exact
    contract type (a subclass cannot substitute `to_dict`)."""
    if type(plan) is not DagPlan:
        raise TypeError("canonical_json accepts only a DagPlan")
    text = sc._canonical(DagPlan.to_dict(plan))
    if len(text) > MAX_CANONICAL_JSON_BYTES:
        raise ValueError("canonical plan exceeds MAX_CANONICAL_JSON_BYTES")
    return text


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _request_reasons(request) -> tuple:
    """Checks everything that needs no compilation (so an invalid request
    never reaches the compiler)."""
    if type(request) is not DagPlanRequest:
        return (REQUEST_NOT_TYPED,)
    reasons = set()
    if not (sc._is_int(request.schema_version) and request.schema_version == REQUEST_SCHEMA_VERSION):
        reasons.add(SCHEMA_VERSION_UNSUPPORTED)
    if sw.parse_utc(request.as_of_utc) is None:
        reasons.add(AS_OF_INVALID)
    states = request.node_states
    if not (type(states) is tuple and len(states) <= MAX_NODES
            and all(type(p) is tuple and len(p) == 2 and sc._safe_id(p[0]) for p in states)):
        reasons.add(NODE_STATES_MALFORMED)
    else:
        if any(type(p[1]) is not str or p[1] not in NODE_STATES for p in states):
            reasons.add(NODE_STATE_INVALID)
        if len({p[0] for p in states}) != len(states):
            reasons.add(NODE_STATE_DUPLICATE)
    if request.conflict_request is not None and type(request.conflict_request) is not cf.ConflictRequest:
        reasons.add(CONFLICT_REQUEST_NOT_TYPED)
    if request.max_workers is not None and not (
            sc._is_int(request.max_workers) and 1 <= request.max_workers <= MAX_WORKERS):
        reasons.add(MAX_WORKERS_INVALID)
    limits = request.provider_limits
    if not (type(limits) is tuple and len(limits) <= MAX_WORKERS and all(
            type(p) is tuple and len(p) == 2 and sc._valid_provider_id(p[0])
            and sc._is_int(p[1]) and 1 <= p[1] <= MAX_WORKERS for p in limits)):
        reasons.add(PROVIDER_LIMITS_MALFORMED)
    elif len({p[0] for p in limits}) != len(limits):
        reasons.add(PROVIDER_LIMIT_DUPLICATE)
    return _ordered(reasons, REQUEST_REASONS)


def _native_codes(exc) -> tuple:
    errors = getattr(exc, "errors", None)
    codes = set()
    if type(errors) is list:
        for entry in errors:
            code = entry.get("code") if type(entry) is dict else None
            if type(code) is str and _NATIVE_CODE_RE.fullmatch(code):
                codes.add(code)
    return tuple(sorted(codes))


def _compile(blueprint, self_worktree, registered_providers) -> tuple:
    """Returns (reasons, native codes, compilation). The ONLY structural
    validation is the native compiler's."""
    try:
        compilation = bp.compile_blueprint(
            blueprint, self_worktree=self_worktree, registered_providers=registered_providers,
        )
    except (bp.BlueprintError, pipeline.ManifestError) as exc:
        return (BLUEPRINT_REFUSED,), _native_codes(exc), None
    except Exception:  # noqa: BLE001 - an unevaluable blueprint is UNKNOWN: fail closed
        return (BLUEPRINT_UNEVALUABLE,), (), None
    return (), (), compilation


def _identity_reasons(blueprint, compilation, request: DagPlanRequest) -> set:
    reasons = set()
    plan, manifest = compilation.plan, compilation.manifest
    declared = tuple(n.id for n in blueprint.nodes)
    if not (type(plan) is bp.BlueprintPlan and bp.verify_plan(plan) and type(manifest) is pipeline.Manifest
            and plan.pipeline_id == manifest.pipeline_id == blueprint.pipeline_id
            and tuple(n.id for n in plan.nodes) == declared == tuple(s.id for s in manifest.workers)
            and len(declared) <= MAX_NODES):
        reasons.add(BLUEPRINT_IDENTITY_MISMATCH)
        return reasons
    if not sc._safe_id(plan.pipeline_id) or not all(sc._safe_id(i) for i in declared):
        reasons.add(NODE_ID_UNSUPPORTED)
    providers = [n.provider for n in plan.nodes] + list(manifest.provider_limits)
    if not all(sc._valid_provider_id(p) for p in providers):
        reasons.add(PROVIDER_ID_UNSUPPORTED)
    if any(p[0] not in declared for p in request.node_states):
        reasons.add(NODE_STATE_UNKNOWN_NODE)
    return reasons


def _worktree_key(path) -> Optional[tuple]:
    reasons, key = cf.target_key(path)
    return None if reasons else key


def _conflict_reasons(conflict: cf.ConflictRequest, plan: bp.BlueprintPlan) -> set:
    reasons = set()
    if conflict.dag_id != plan.pipeline_id:
        reasons.add(CONFLICT_DAG_MISMATCH)
    workers = conflict.workers if type(conflict.workers) is tuple else ()
    typed = [w for w in workers if type(w) is cf.WorkerClaims and type(w.worker_id) is str]
    nodes = {n.id: n for n in plan.nodes}
    if len(typed) != len(workers) or sorted(w.worker_id for w in typed) != sorted(nodes):
        reasons.add(CONFLICT_WORKERS_MISMATCH)
        return reasons
    for worker in typed:
        node = nodes[worker.worker_id]
        if worker.mode != node.mode:
            reasons.add(CONFLICT_MODE_MISMATCH)
        claimed = _worktree_key(worker.worktree) if type(worker.worktree) is str else None
        # An unidentifiable claimed worktree is the conflict analysis' own
        # UNKNOWN; an identified one must be the node's native worktree.
        if claimed is not None and claimed != _worktree_key(node.worktree_top):
            reasons.add(CONFLICT_WORKTREE_MISMATCH)
    return reasons


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------

def _effective_limits(manifest, request: DagPlanRequest) -> tuple:
    """(max_workers, provider limits): the manifest's, only ever narrowed."""
    cap = manifest.max_workers or DEFAULT_MAX_WORKERS
    if request.max_workers is not None:
        cap = min(cap, request.max_workers)
    limits = dict(manifest.provider_limits)
    for provider, limit in request.provider_limits:
        limits[provider] = min(limits.get(provider, limit), limit)
    return cap, tuple(sorted(limits.items()))


def _dependency_reasons(node, states: dict) -> set:
    """The Runner's `DEPENDENCY_POLICIES` over OBSERVED dependency states."""
    accepted = {s.value for s in pipeline.DEPENDENCY_POLICIES[node.dependency_policy]}
    reasons = set()
    for dep in node.depends_on:
        state = states[dep]
        if state == STATE_UNKNOWN:
            reasons.add(DEPENDENCY_STATE_UNKNOWN)
        elif state == _W.BLOCKED.value and state in accepted:
            # The Runner refuses a BLOCKED dependency whose provider process
            # is unresolved; that block reason is not observed here.
            reasons.add(DEPENDENCY_STATE_AMBIGUOUS)
        elif state in accepted:
            continue
        elif state in _TERMINAL_STATES:
            reasons.add(DEPENDENCY_UNSATISFIABLE)
        else:
            reasons.add(DEPENDENCY_PENDING)
    return reasons


def _request_dict(request: DagPlanRequest, compilation, graph, cap: int, limits: tuple, as_of) -> dict:
    return {
        "schema": REQUEST_SCHEMA, "schema_version": REQUEST_SCHEMA_VERSION,
        "blueprint_fingerprint": compilation.plan.fingerprint, "manifest_sha256": compilation.manifest.sha256,
        "as_of_utc": sc._utc_text(as_of), "node_states": sorted([list(p) for p in request.node_states]),
        "conflict_fingerprint": None if graph is None else graph.request_fingerprint,
        "max_workers": request.max_workers, "provider_limits": sorted([list(p) for p in request.provider_limits]),
        "effective_max_workers": cap, "effective_provider_limits": [list(p) for p in limits],
    }


def _refused(reasons, codes: tuple = ()) -> DagPlan:
    return DagPlan(
        outcome=REFUSED, dag_id=None, blueprint_fingerprint=None, request_fingerprint=None, window_status=None,
        effective_max_workers=None, effective_provider_limits=(), planning_order=(),
        request_reasons=_ordered(reasons, REQUEST_REASONS), blueprint_error_codes=codes, decisions=(),
    )


def plan_dag(request: DagPlanRequest, *, self_worktree=None, registered_providers=None) -> DagPlan:
    """Compiles the blueprint once through `compile_blueprint` (forwarding
    `self_worktree` / `registered_providers` unchanged) and proposes the next
    admissible batch. Never raises on bad input and never mutates it: every
    malformed or mismatched request is an explained refusal. The result never
    authorizes dispatch, execution, retry, resume, merge or a provider
    switch."""
    reasons = _request_reasons(request)
    if reasons:
        return _refused(reasons)
    blueprint = request.blueprint
    reasons, codes, compilation = _compile(blueprint, self_worktree, registered_providers)
    if reasons:
        return _refused(reasons, codes)

    reasons = _identity_reasons(blueprint, compilation, request)
    if reasons & {BLUEPRINT_IDENTITY_MISMATCH}:
        return _refused(reasons)
    plan, manifest = compilation.plan, compilation.manifest
    window = sw.evaluate_window(manifest, as_of=request.as_of_utc)
    if window.status == sw.INVALID:
        reasons.add(WINDOW_INVALID)
    graph = None
    if request.conflict_request is not None:
        conflict_reasons = _conflict_reasons(request.conflict_request, plan)
        reasons |= conflict_reasons
        if not conflict_reasons:
            graph = cf.analyze_conflicts(request.conflict_request)
            if graph.outcome == cf.REFUSED:
                reasons.add(CONFLICT_REQUEST_REFUSED)
    if reasons:
        return _refused(reasons)

    cap, limits = _effective_limits(manifest, request)
    request_text = sc._canonical(_request_dict(request, compilation, graph, cap, limits,
                                               sw.parse_utc(request.as_of_utc)))
    if len(request_text) > MAX_CANONICAL_JSON_BYTES:
        return _refused((REQUEST_TOO_LARGE,))

    nodes = plan.nodes
    states = {n.id: STATE_UNKNOWN for n in nodes}
    states.update(dict(request.node_states))
    running = [n for n in nodes if states[n.id] == _W.RUNNING.value]
    held_providers = {n.provider for n in nodes if states[n.id] in _PROVIDER_HOLDING_STATES}
    peer_unknown = STATE_UNKNOWN in states.values()
    window_reason = {sw.EXPIRED: WINDOW_EXPIRED, sw.WAIT_UNTIL: WINDOW_NOT_OPEN}.get(window.status)

    held = {}
    for node in nodes:
        state = states[node.id]
        if state == STATE_UNKNOWN:
            held[node.id] = {NODE_STATE_UNKNOWN}
            continue
        if state == _W.RUNNING.value:
            held[node.id] = {NODE_RUNNING}
            continue
        if state in _TERMINAL_STATES:
            held[node.id] = {NODE_TERMINAL}
            continue
        if state not in _PENDING_STATES:
            held[node.id] = {NODE_NOT_PENDING}
            continue
        node_reasons = _dependency_reasons(node, states)
        if window_reason is not None:
            node_reasons.add(window_reason)
        if peer_unknown:
            node_reasons.add(PEER_STATE_UNKNOWN)
        if graph is None:
            node_reasons.add(CONFLICTS_UNASSESSED)
        elif graph.node_of(node.id).status == cf.UNKNOWN:
            node_reasons.add(CONFLICT_UNIDENTIFIED)
        elif any(not graph.compatible(node.id, r.id) for r in running):
            node_reasons.add(CONFLICT_WITH_RUNNING)
        if node.provider in held_providers:
            node_reasons.add(PROVIDER_HELD)
        held[node.id] = node_reasons

    # Runner dispatch order: highest priority first, then declared order.
    order = sorted(range(len(nodes)), key=lambda i: (-nodes[i].priority, i))
    limit_of = dict(limits)
    used = {}
    for node in running:
        used[node.provider] = used.get(node.provider, 0) + 1
    free = max(0, cap - len(running))
    admitted = []
    slots = {}
    for index in order:
        node = nodes[index]
        if held[node.id]:
            continue
        if len(admitted) >= free:
            held[node.id].add(WORKER_LIMIT_REACHED)
        elif node.provider in limit_of and used.get(node.provider, 0) >= limit_of[node.provider]:
            held[node.id].add(PROVIDER_LIMIT_REACHED)
        elif any(not graph.compatible(node.id, other) for other in admitted):
            held[node.id].add(CONFLICT_WITH_ADMITTED)
        else:
            used[node.provider] = used.get(node.provider, 0) + 1
            slots[node.id] = len(admitted)
            admitted.append(node.id)

    decisions = tuple(
        NodeDecision(
            node_id=n.id, state=states[n.id], provider=n.provider, mode=n.mode, priority=n.priority,
            decision=_decision_for(_ordered(held[n.id], NODE_REASONS)), reasons=_ordered(held[n.id], NODE_REASONS),
            slot=slots.get(n.id),
        )
        for n in nodes
    )
    return DagPlan(
        outcome=_plan_outcome(decisions), dag_id=plan.pipeline_id, blueprint_fingerprint=plan.fingerprint,
        request_fingerprint=hashlib.sha256(request_text.encode("ascii")).hexdigest(),
        window_status=window.status, effective_max_workers=cap, effective_provider_limits=limits,
        planning_order=tuple(nodes[i].id for i in order), request_reasons=(), blueprint_error_codes=(),
        decisions=decisions,
    )
