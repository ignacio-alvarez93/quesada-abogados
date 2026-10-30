"""FCP-9E-01: Recovery, provider-quota waits and continuity - pure,
deterministic, fail-closed, provider-neutral, NON-AUTHORITATIVE adapter.

Answers ONE question: given what the Director already returned for one DAG
run (`DirectorDagRunSummary`, via `FabricDirectorService.result_blueprint`),
an explicit evaluation instant (or an injected clock) and the Host's
observation of the worktree, WHY is each node not progressing, does that
hold consume the work budget, and what is the next action and who alone may
take it? It never answers "may I dispatch / retry / resume now?".

Why this is an advisory adapter, not a second recovery mechanism
----------------------------------------------------------------
* The Runner (`runner_pipeline.PipelineRunner`) stays the ONLY component
  that waits for provider quota (`_refresh` -> `PROVIDER_QUOTA_ELIGIBLE`),
  retries transient failures (`RETRY_WAIT`, bounded by `max_attempts`),
  drains at a deadline, cancels dependents and reconciles prior work; the
  Director (`FabricDirectorService.recover`) and the operator's explicit
  `--requeue-interrupted` / `--rerun` stay the ONLY re-queue / resume paths.
  There is no retry, backoff, timer, sleep, poll, queue, lease, pool,
  ledger, schema store, fallback or provider switch here, and no
  `resume_from` is ever derived - least of all from a dirty worktree.
* `assess_resilience(request, clock=...)` is pure: no I/O, Git, process,
  environment or network. The instant is the explicit `as_of_utc` or the
  return value of an injected `clock` called exactly once (resolved by the
  FCP-9A-02 `evaluate_window`), never the wall clock.
  `observe_resilience(service, ...)` is the only reader and calls
  `service.result_blueprint(run_id)` exactly once - nothing else, and
  nothing persisted is modified.
* The summary is validated by the FCP-9C-02 `project_state` (itself bound to
  FCP-8B-01); a corrupt summary or an UNKNOWN node is never guessed.
* Provider prose (`state_reason` text, `stop_reason` text, messages) is never
  interpreted: only the Runner's leading UPPER_SNAKE codes are read, and a
  `stop_reason` outside `RUNNER_STOP_REASONS` is UNKNOWN. No provider id,
  path or evidence directory is echoed.

Runner states reused verbatim (reasons, highest precedence first)
-----------------------------------------------------------------
UNKNOWN_STATE (fail closed) > PROCESS_UNRESOLVED (native BLOCKED with
reason PROVIDER_PROCESS_UNRESOLVED) > BLOCKED_PROVIDER_AUTH > INTERRUPTED >
DEADLINE_REACHED (Runner stop reason, or the given window EXPIRED; applies to
not-yet-running, not operator-held nodes) > WAITING_PROVIDER_QUOTA >
DEPENDENCY_HELD (an upstream, transitively, is held) > TRANSIENT_RETRY_WAIT >
RUNNING > PENDING > WORK_NOT_SUCCESSFUL > CANCELLED > COMPLETED.

Availability vs work failure
----------------------------
`budget_class` mirrors the Runner's own attempt classes: a node natively in
WAITING_PROVIDER_QUOTA / BLOCKED_PROVIDER_AUTH is PROVIDER_AVAILABILITY and
never consumes `max_attempts` (its `availability_attempts` must be >= 1);
RETRY_WAIT / FAILED / PARTIAL are WORK. Only WORK consumes the budget.

Dependents never fire on a hold
-------------------------------
A not-yet-running node with any upstream (transitively) held is
DEPENDENCY_HELD, with `held_by` naming its held direct dependencies. A node
that already RUNNING or finished (other than CANCELLED) while an upstream is
in a hold the Runner never releases (quota, auth, interrupted, process
unresolved) contradicts the Runner and is UNKNOWN_STATE.

Output (`ResilienceAssessment`, schema `fcp9e01-scheduler-resilience-v1`)
holds only validated ids, enumerated codes, normalized UTC instants,
integers and a fingerprint. It fixes every FCP-9A-01 zero-authority flag to
False as read-only properties, plus `derives_resume_from`,
`dispatches_dependents`, `adds_retry`, `mutates_pipeline_state` and
`activates_process`.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

try:
    from scripts.ai import fabric_director as fd
    from scripts.ai import fabric_scheduler_contract as sc
    from scripts.ai import fabric_scheduler_state as ss
    from scripts.ai import fabric_scheduler_window as sw
    from scripts.ai import runner_pipeline as pipeline
except ImportError:  # pragma: no cover - direct script execution
    import fabric_director as fd  # type: ignore[no-redef]
    import fabric_scheduler_contract as sc  # type: ignore[no-redef]
    import fabric_scheduler_state as ss  # type: ignore[no-redef]
    import fabric_scheduler_window as sw  # type: ignore[no-redef]
    import runner_pipeline as pipeline  # type: ignore[no-redef]

REQUEST_SCHEMA_VERSION = 1
SCHEMA = "fcp9e01-scheduler-resilience-v1"
SCHEMA_VERSION = 1
RESILIENCE_MARKER = "FCP9E01_RESILIENCE_ADVISORY_ONLY_RUNNER_OWNS_RECOVERY_NOT_AUTHORIZED"

MAX_NODES = ss.MAX_NODES
MAX_ATTEMPT_COUNT = 10000
MAX_CANONICAL_JSON_BYTES = 262144

_W = pipeline.WorkerState
NATIVE_STATES = ss.NATIVE_STATES
UNRECOGNIZED = ss.UNRECOGNIZED
_NATIVE_TERMINAL = frozenset(s.value for s in pipeline.TERMINAL_STATES)
PROCESS_UNRESOLVED_NATIVE_REASON = "PROVIDER_PROCESS_UNRESOLVED"

# Every `stop_reason` the Runner assigns (pinned by tests against its source).
RUNNER_STOP_REASONS = (
    "SHUTDOWN_REQUESTED", "DEADLINE_REACHED", "FORCED_SHUTDOWN", "PROVIDER_AUTH_BLOCKED",
    "WAITING_PROVIDER_QUOTA", "NO_PROGRESSABLE_WORK", "WORKTREE_LEASE_HELD_BY_OTHER_OWNER",
)

# Host observation of the shared worktree (never read here).
WORKTREE_CLEAN = "CLEAN"
WORKTREE_DIRTY = "DIRTY"
WORKTREE_UNKNOWN = "UNKNOWN"
WORKTREE_STATES = (WORKTREE_CLEAN, WORKTREE_DIRTY, WORKTREE_UNKNOWN)

# Node reasons, highest precedence first. The five Runner holds keep their
# exact Runner names.
UNKNOWN_STATE = "UNKNOWN_STATE"
PROCESS_UNRESOLVED = "PROCESS_UNRESOLVED"
BLOCKED_PROVIDER_AUTH = _W.BLOCKED_PROVIDER_AUTH.value
INTERRUPTED = _W.INTERRUPTED.value
DEADLINE_REACHED = "DEADLINE_REACHED"
WAITING_PROVIDER_QUOTA = _W.WAITING_PROVIDER_QUOTA.value
DEPENDENCY_HELD = "DEPENDENCY_HELD"
TRANSIENT_RETRY_WAIT = "TRANSIENT_RETRY_WAIT"
RUNNING = "RUNNING"
PENDING = "PENDING"
WORK_NOT_SUCCESSFUL = "WORK_NOT_SUCCESSFUL"
CANCELLED = "CANCELLED"
COMPLETED = "COMPLETED"
REASONS = (UNKNOWN_STATE, PROCESS_UNRESOLVED, BLOCKED_PROVIDER_AUTH, INTERRUPTED, DEADLINE_REACHED,
           WAITING_PROVIDER_QUOTA, DEPENDENCY_HELD, TRANSIENT_RETRY_WAIT, RUNNING, PENDING, WORK_NOT_SUCCESSFUL,
           CANCELLED, COMPLETED)
RUNNER_HOLD_REASONS = (PROCESS_UNRESOLVED, BLOCKED_PROVIDER_AUTH, INTERRUPTED, DEADLINE_REACHED,
                       WAITING_PROVIDER_QUOTA)
# Reasons that hold every (transitive) dependent.
_HOLDING_REASONS = frozenset(RUNNER_HOLD_REASONS + (UNKNOWN_STATE, DEPENDENCY_HELD))
# Native holds the Runner never releases on its own to a dependent.
_NEVER_RELEASING_NATIVE = frozenset({_W.WAITING_PROVIDER_QUOTA.value, _W.BLOCKED_PROVIDER_AUTH.value,
                                     _W.INTERRUPTED.value})

# Categories.
CATEGORY_INTEGRITY = "INTEGRITY"
CATEGORY_AVAILABILITY = "AVAILABILITY"
CATEGORY_CONTINUITY = "CONTINUITY"
CATEGORY_DEPENDENCY = "DEPENDENCY"
CATEGORY_WORK = "WORK"
CATEGORY_FLOW = "FLOW"
CATEGORIES = (CATEGORY_INTEGRITY, CATEGORY_AVAILABILITY, CATEGORY_CONTINUITY, CATEGORY_DEPENDENCY, CATEGORY_WORK,
              CATEGORY_FLOW)

# Actors: who alone may take the next action.
ACTOR_HUMAN = "HUMAN_OPERATOR"
ACTOR_RUNNER = "RUNNER"
ACTOR_NONE = "NONE"
ACTORS = (ACTOR_HUMAN, ACTOR_RUNNER, ACTOR_NONE)

# Next actions (bounded, non-executable review codes).
REVIEW_STATE_INTEGRITY = "REVIEW_STATE_INTEGRITY"
CONFIRM_PROVIDER_PROCESS_STOPPED = "CONFIRM_PROVIDER_PROCESS_STOPPED"
RESTORE_PROVIDER_AUTH = "RESTORE_PROVIDER_AUTH"
REVIEW_INTERRUPTED_WORK = "REVIEW_INTERRUPTED_WORK"
REVIEW_DIRTY_WORKTREE = "REVIEW_DIRTY_WORKTREE"
DECIDE_NEW_EXECUTION_WINDOW = "DECIDE_NEW_EXECUTION_WINDOW"
AWAIT_PROVIDER_QUOTA_RECOVERY = "AWAIT_PROVIDER_QUOTA_RECOVERY"
OBSERVE_RUNNER_QUOTA_REEVALUATION = "OBSERVE_RUNNER_QUOTA_REEVALUATION"
RESOLVE_UPSTREAM_HOLD = "RESOLVE_UPSTREAM_HOLD"
AWAIT_UPSTREAM = "AWAIT_UPSTREAM"
OBSERVE_RUNNER_RETRY = "OBSERVE_RUNNER_RETRY"
OBSERVE_RUNNER = "OBSERVE_RUNNER"
REVIEW_WORK_OUTCOME = "REVIEW_WORK_OUTCOME"
REVIEW_CANCELLATION = "REVIEW_CANCELLATION"
NO_ACTION = "NO_ACTION"
ACTIONS = (REVIEW_STATE_INTEGRITY, CONFIRM_PROVIDER_PROCESS_STOPPED, RESTORE_PROVIDER_AUTH, REVIEW_INTERRUPTED_WORK,
           REVIEW_DIRTY_WORKTREE, DECIDE_NEW_EXECUTION_WINDOW, AWAIT_PROVIDER_QUOTA_RECOVERY,
           OBSERVE_RUNNER_QUOTA_REEVALUATION, RESOLVE_UPSTREAM_HOLD, AWAIT_UPSTREAM, OBSERVE_RUNNER_RETRY,
           OBSERVE_RUNNER, REVIEW_WORK_OUTCOME, REVIEW_CANCELLATION, NO_ACTION)
ACTOR_OF_ACTION = {
    REVIEW_STATE_INTEGRITY: ACTOR_HUMAN, CONFIRM_PROVIDER_PROCESS_STOPPED: ACTOR_HUMAN,
    RESTORE_PROVIDER_AUTH: ACTOR_HUMAN, REVIEW_INTERRUPTED_WORK: ACTOR_HUMAN, REVIEW_DIRTY_WORKTREE: ACTOR_HUMAN,
    DECIDE_NEW_EXECUTION_WINDOW: ACTOR_HUMAN, AWAIT_PROVIDER_QUOTA_RECOVERY: ACTOR_RUNNER,
    OBSERVE_RUNNER_QUOTA_REEVALUATION: ACTOR_RUNNER, RESOLVE_UPSTREAM_HOLD: ACTOR_HUMAN, AWAIT_UPSTREAM: ACTOR_RUNNER,
    OBSERVE_RUNNER_RETRY: ACTOR_RUNNER, OBSERVE_RUNNER: ACTOR_RUNNER, REVIEW_WORK_OUTCOME: ACTOR_HUMAN,
    REVIEW_CANCELLATION: ACTOR_HUMAN, NO_ACTION: ACTOR_NONE,
}

# reason -> (category, allowed next actions).
REASON_RULES = {
    UNKNOWN_STATE: (CATEGORY_INTEGRITY, (REVIEW_STATE_INTEGRITY,)),
    PROCESS_UNRESOLVED: (CATEGORY_CONTINUITY, (CONFIRM_PROVIDER_PROCESS_STOPPED,)),
    BLOCKED_PROVIDER_AUTH: (CATEGORY_AVAILABILITY, (RESTORE_PROVIDER_AUTH,)),
    INTERRUPTED: (CATEGORY_CONTINUITY, (REVIEW_INTERRUPTED_WORK, REVIEW_DIRTY_WORKTREE)),
    DEADLINE_REACHED: (CATEGORY_CONTINUITY, (DECIDE_NEW_EXECUTION_WINDOW,)),
    WAITING_PROVIDER_QUOTA: (CATEGORY_AVAILABILITY, (AWAIT_PROVIDER_QUOTA_RECOVERY,
                                                     OBSERVE_RUNNER_QUOTA_REEVALUATION)),
    DEPENDENCY_HELD: (CATEGORY_DEPENDENCY, (RESOLVE_UPSTREAM_HOLD, AWAIT_UPSTREAM)),
    TRANSIENT_RETRY_WAIT: (CATEGORY_WORK, (OBSERVE_RUNNER_RETRY,)),
    RUNNING: (CATEGORY_FLOW, (OBSERVE_RUNNER,)),
    PENDING: (CATEGORY_FLOW, (OBSERVE_RUNNER,)),
    WORK_NOT_SUCCESSFUL: (CATEGORY_WORK, (REVIEW_WORK_OUTCOME,)),
    CANCELLED: (CATEGORY_FLOW, (REVIEW_CANCELLATION,)),
    COMPLETED: (CATEGORY_FLOW, (NO_ACTION,)),
}

# Attempt budget classes (the Runner's own vocabulary).
BUDGET_WORK = pipeline.BUDGET_WORK
BUDGET_PROVIDER_AVAILABILITY = pipeline.BUDGET_PROVIDER_AVAILABILITY
BUDGET_NOT_APPLICABLE = "NOT_APPLICABLE"
BUDGET_CLASSES = (BUDGET_WORK, BUDGET_PROVIDER_AVAILABILITY, BUDGET_NOT_APPLICABLE)
_AVAILABILITY_NATIVE = frozenset({_W.WAITING_PROVIDER_QUOTA.value, _W.BLOCKED_PROVIDER_AUTH.value})
_WORK_NATIVE = frozenset({_W.RETRY_WAIT.value, _W.FAILED.value, _W.PARTIAL.value})
_PENDING_NATIVE = frozenset({_W.QUEUED.value, _W.WAITING_DEPENDENCY.value, _W.READY.value})
_DEADLINE_AFFECTED_NATIVE = _PENDING_NATIVE | {_W.RETRY_WAIT.value, _W.WAITING_PROVIDER_QUOTA.value}
_OPERATOR_RELEASED = frozenset({PROCESS_UNRESOLVED, BLOCKED_PROVIDER_AUTH, INTERRUPTED, DEADLINE_REACHED,
                                UNKNOWN_STATE})

# Node codes, in their fixed order.
STATE_PROJECTION_UNKNOWN = "STATE_PROJECTION_UNKNOWN"
PROVIDER_CONDITION_MISMATCH = "PROVIDER_CONDITION_MISMATCH"
QUOTA_ELIGIBILITY_UNKNOWN = "QUOTA_ELIGIBILITY_UNKNOWN"
ATTEMPT_ACCOUNTING_INCONSISTENT = "ATTEMPT_ACCOUNTING_INCONSISTENT"
DEPENDENT_ADVANCED_PAST_HOLD = "DEPENDENT_ADVANCED_PAST_HOLD"
QUOTA_ELIGIBILITY_REACHED = "QUOTA_ELIGIBILITY_REACHED"
UPSTREAM_REQUIRES_HUMAN = "UPSTREAM_REQUIRES_HUMAN"
WORKTREE_DIRTY_NO_DERIVED_RESUME = "WORKTREE_DIRTY_NO_DERIVED_RESUME"
WORKTREE_STATE_UNOBSERVED = "WORKTREE_STATE_UNOBSERVED"
NODE_UNKNOWN_CODES = (STATE_PROJECTION_UNKNOWN, PROVIDER_CONDITION_MISMATCH, QUOTA_ELIGIBILITY_UNKNOWN,
                      ATTEMPT_ACCOUNTING_INCONSISTENT, DEPENDENT_ADVANCED_PAST_HOLD)
NODE_INFO_CODES = (QUOTA_ELIGIBILITY_REACHED, UPSTREAM_REQUIRES_HUMAN, WORKTREE_DIRTY_NO_DERIVED_RESUME,
                   WORKTREE_STATE_UNOBSERVED)
NODE_CODES = NODE_UNKNOWN_CODES + NODE_INFO_CODES

# Run outcomes (most cautious first).
REFUSED = "REFUSED"
UNOBSERVABLE = "UNOBSERVABLE"
UNKNOWN = "UNKNOWN"
HUMAN_ACTION_REQUIRED = "HUMAN_ACTION_REQUIRED"
IN_PROGRESS = "IN_PROGRESS"
SETTLED = "SETTLED"
OUTCOMES = (REFUSED, UNOBSERVABLE, UNKNOWN, HUMAN_ACTION_REQUIRED, WAITING_PROVIDER_QUOTA, IN_PROGRESS, SETTLED)

# Request-level refusal / unobservable codes, in their fixed order.
REQUEST_NOT_TYPED = "REQUEST_NOT_TYPED"
SCHEMA_VERSION_UNSUPPORTED = "SCHEMA_VERSION_UNSUPPORTED"
RUN_ID_INVALID = "RUN_ID_INVALID"
SUMMARY_NOT_TYPED = "SUMMARY_NOT_TYPED"
WORKTREE_STATE_INVALID = "WORKTREE_STATE_INVALID"
WINDOW_NOT_TYPED = "WINDOW_NOT_TYPED"
AS_OF_INVALID = "AS_OF_INVALID"
CLOCK_UNAVAILABLE = "CLOCK_UNAVAILABLE"
AS_OF_SOURCE_INVALID = "AS_OF_SOURCE_INVALID"
WINDOW_INVALID = "WINDOW_INVALID"
READ_FAILED = "READ_FAILED"
PROVENANCE_REFUSED = "PROVENANCE_REFUSED"
REFUSAL_REASONS = (REQUEST_NOT_TYPED, SCHEMA_VERSION_UNSUPPORTED, RUN_ID_INVALID, SUMMARY_NOT_TYPED,
                   WORKTREE_STATE_INVALID, WINDOW_NOT_TYPED, AS_OF_INVALID, CLOCK_UNAVAILABLE, AS_OF_SOURCE_INVALID,
                   WINDOW_INVALID)
UNOBSERVABLE_REASONS = (READ_FAILED, PROVENANCE_REFUSED)
REQUEST_REASONS = REFUSAL_REASONS + UNOBSERVABLE_REASONS

# Run codes, grouped by whether they force UNKNOWN, in their fixed order.
SUMMARY_INVALID = "SUMMARY_INVALID"
STOP_REASON_UNRECOGNIZED = "STOP_REASON_UNRECOGNIZED"
NODE_UNKNOWN = "NODE_UNKNOWN"
DEADLINE_REACHED_BY_RUNNER = "DEADLINE_REACHED_BY_RUNNER"
DEADLINE_PASSED_PER_WINDOW = "DEADLINE_PASSED_PER_WINDOW"
WINDOW_NOT_OPEN = "WINDOW_NOT_OPEN"
RUN_UNKNOWN_CODES = (SUMMARY_INVALID, STOP_REASON_UNRECOGNIZED, NODE_UNKNOWN)
RUN_INFO_CODES = (DEADLINE_REACHED_BY_RUNNER, DEADLINE_PASSED_PER_WINDOW, WINDOW_NOT_OPEN)
RUN_CODES = RUN_UNKNOWN_CODES + RUN_INFO_CODES

_SW_CLOCK_REASONS = frozenset({sw.CLOCK_UNAVAILABLE})
_SW_SOURCE_REASONS = frozenset({sw.AS_OF_MISSING, sw.AS_OF_SOURCE_AMBIGUOUS})
_SW_AS_OF_REASONS = frozenset(r for r in sw.INVALID_REASONS if r.startswith("AS_OF_")) - _SW_SOURCE_REASONS


def _ordered(codes, vocabulary) -> tuple:
    return sc._ordered(codes, vocabulary)


def _codes_ok(codes, vocabulary) -> bool:
    return (type(codes) is tuple and all(type(c) is str and c in vocabulary for c in codes)
            and codes == _ordered(codes, vocabulary))


def _opt_count(value) -> bool:
    return value is None or (sc._is_int(value) and 0 <= value <= MAX_ATTEMPT_COUNT)


def budget_class_for(native_state: Optional[str]) -> str:
    """The Runner attempt class a node's native state implies."""
    if native_state in _AVAILABILITY_NATIVE:
        return BUDGET_PROVIDER_AVAILABILITY
    if native_state in _WORK_NATIVE:
        return BUDGET_WORK
    return BUDGET_NOT_APPLICABLE


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ResilienceRequest:
    """What the caller already read, verbatim. `as_of_utc` may be None only
    when a clock is injected into `assess_resilience`. `window` is the run's
    own `ExecutionWindow` (manifest bounds) or None. `worktree_state` is the
    Host's observation, UNKNOWN by default (fail closed). Validated by
    `assess_resilience`, not here."""
    run_id: str
    dag_summary: object
    as_of_utc: Optional[str] = None
    window: Optional[object] = None
    worktree_state: str = WORKTREE_UNKNOWN
    schema_version: int = REQUEST_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

class _ResilienceGuarantees(sc._NotAuthorized):
    """FCP-9A-01 zero-authority flags plus this adapter's own limits, all
    read-only properties fixed to False."""

    @property
    def derives_resume_from(self) -> bool:
        return False

    @property
    def dispatches_dependents(self) -> bool:
        return False

    @property
    def adds_retry(self) -> bool:
        return False

    @property
    def mutates_pipeline_state(self) -> bool:
        return False

    @property
    def activates_process(self) -> bool:
        return False

    @staticmethod
    def _guarantees() -> dict:
        guarantees = sc._NotAuthorized._guarantees()
        guarantees.update(marker=RESILIENCE_MARKER, derives_resume_from=False, dispatches_dependents=False,
                          adds_retry=False, mutates_pipeline_state=False, activates_process=False)
        return guarantees


@dataclass(frozen=True)
class ResilienceNode:
    """One node's operational reason and next action. Category, actor and
    budget class are derived (properties), and construction re-checks that
    the reason, action and codes agree, so a hand-made node cannot claim a
    reason or an actor its codes and native state do not support."""
    node_id: str
    depends_on: tuple
    native_state: str
    reason: str
    next_action: str
    codes: tuple
    held_by: tuple = ()
    work_attempts_used: Optional[int] = None
    availability_attempts: Optional[int] = None
    next_eligible_utc: Optional[str] = None
    seconds_until_eligible: Optional[int] = None

    def __post_init__(self):
        if not sc._safe_id(self.node_id):
            raise ValueError("node_id must be a safe id")
        if not (type(self.depends_on) is tuple and len(set(self.depends_on)) == len(self.depends_on)
                and all(sc._safe_id(d) and d != self.node_id for d in self.depends_on)):
            raise ValueError("depends_on must be unique other safe node ids")
        if not (type(self.native_state) is str and (self.native_state in NATIVE_STATES
                                                    or self.native_state == UNRECOGNIZED)):
            raise ValueError("native_state must be a native WorkerState or UNRECOGNIZED")
        if type(self.reason) is not str or self.reason not in REASON_RULES:
            raise ValueError("unknown node reason")
        if type(self.next_action) is not str or self.next_action not in REASON_RULES[self.reason][1]:
            raise ValueError("next_action is not allowed for this reason")
        if not _codes_ok(self.codes, NODE_CODES):
            raise ValueError("codes must be ordered node codes")
        if (self.reason == UNKNOWN_STATE) != any(c in NODE_UNKNOWN_CODES for c in self.codes):
            raise ValueError("UNKNOWN_STATE is exactly the presence of an unknown code")
        if self.native_state == UNRECOGNIZED and self.reason != UNKNOWN_STATE:
            raise ValueError("an unrecognized native state is UNKNOWN_STATE")
        if not (type(self.held_by) is tuple and all(d in self.depends_on for d in self.held_by)
                and self.held_by == tuple(d for d in self.depends_on if d in self.held_by)):
            raise ValueError("held_by must be direct dependencies in declared order")
        if (self.reason == DEPENDENCY_HELD) != bool(self.held_by):
            raise ValueError("held_by is exactly a dependency hold")
        if self.reason == DEPENDENCY_HELD and (self.next_action == RESOLVE_UPSTREAM_HOLD) != (
                UPSTREAM_REQUIRES_HUMAN in self.codes):
            raise ValueError("a human upstream resolution is exactly UPSTREAM_REQUIRES_HUMAN")
        if self.reason == WAITING_PROVIDER_QUOTA:
            if self.next_eligible_utc is None or not sc._is_int(self.seconds_until_eligible):
                raise ValueError("a quota wait carries its eligibility")
            reached = self.seconds_until_eligible == 0
            if reached != (QUOTA_ELIGIBILITY_REACHED in self.codes) or reached != (
                    self.next_action == OBSERVE_RUNNER_QUOTA_REEVALUATION):
                raise ValueError("quota eligibility, code and action must agree")
        if self.reason == INTERRUPTED and (self.next_action == REVIEW_DIRTY_WORKTREE) != (
                WORKTREE_DIRTY_NO_DERIVED_RESUME in self.codes):
            raise ValueError("a dirty-worktree review is exactly WORKTREE_DIRTY_NO_DERIVED_RESUME")
        if not (_opt_count(self.work_attempts_used) and _opt_count(self.availability_attempts)):
            raise ValueError("attempt counts must be bounded non-negative ints or None")
        if self.budget_class == BUDGET_PROVIDER_AVAILABILITY and self.reason != UNKNOWN_STATE and not (
                sc._is_int(self.availability_attempts) and self.availability_attempts >= 1
                and sc._is_int(self.work_attempts_used)):
            raise ValueError("an availability hold is accounted as availability, never as work")
        if not ss._utc_ok(self.next_eligible_utc):
            raise ValueError("next_eligible_utc must be normalized UTC or None")
        if not (self.seconds_until_eligible is None or (sc._is_int(self.seconds_until_eligible)
                                                        and self.seconds_until_eligible >= 0)):
            raise ValueError("seconds_until_eligible must be a non-negative int or None")
        if (self.next_eligible_utc is None) != (self.seconds_until_eligible is None):
            raise ValueError("eligibility instant and seconds come together")

    @property
    def category(self) -> str:
        return REASON_RULES[self.reason][0]

    @property
    def actor(self) -> str:
        return ACTOR_OF_ACTION[self.next_action]

    @property
    def budget_class(self) -> str:
        return budget_class_for(self.native_state)

    @property
    def consumes_max_attempts(self) -> bool:
        """Informational: only WORK attempts count against `max_attempts`."""
        return self.budget_class == BUDGET_WORK

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id, "depends_on": list(self.depends_on), "native_state": self.native_state,
            "reason": self.reason, "category": self.category, "next_action": self.next_action,
            "actor": self.actor, "budget_class": self.budget_class,
            "consumes_max_attempts": self.consumes_max_attempts, "codes": list(self.codes),
            "held_by": list(self.held_by), "work_attempts_used": self.work_attempts_used,
            "availability_attempts": self.availability_attempts, "next_eligible_utc": self.next_eligible_utc,
            "seconds_until_eligible": self.seconds_until_eligible,
        }


def outcome_for(nodes: tuple, codes: tuple) -> str:
    """The single run-outcome derivation (also the construction guard) for
    an accepted request."""
    if any(c in RUN_UNKNOWN_CODES for c in codes) or not nodes or any(n.reason == UNKNOWN_STATE for n in nodes):
        return UNKNOWN
    if any(n.reason in _OPERATOR_RELEASED for n in nodes):
        return HUMAN_ACTION_REQUIRED
    if any(n.reason == WAITING_PROVIDER_QUOTA for n in nodes):
        return WAITING_PROVIDER_QUOTA
    if any(n.native_state not in _NATIVE_TERMINAL for n in nodes):
        return IN_PROGRESS
    return SETTLED


def _primary(nodes: tuple) -> Optional[ResilienceNode]:
    """The first node (plan order) with the highest-precedence reason."""
    if not nodes:
        return None
    return min(nodes, key=lambda n: (REASONS.index(n.reason), nodes.index(n)))


@dataclass(frozen=True)
class ResilienceAssessment(_ResilienceGuarantees):
    """Consultative continuity assessment of one DAG run. Echo fields hold
    only validated values (None and () when refused or unobservable).
    Construction re-derives the outcome and the primary reason/action, so a
    hand-made assessment cannot claim more than its nodes support."""
    outcome: str
    run_id: Optional[str]
    as_of_utc: Optional[str]
    worktree_state: Optional[str]
    stop_reason: Optional[str]
    operational_reason: Optional[str]
    next_action: Optional[str]
    earliest_quota_eligible_utc: Optional[str]
    request_reasons: tuple
    codes: tuple
    nodes: tuple

    def __post_init__(self):
        if type(self.outcome) is not str or self.outcome not in OUTCOMES:
            raise ValueError("unknown assessment outcome")
        if not _codes_ok(self.request_reasons, REQUEST_REASONS):
            raise ValueError("request_reasons must be ordered request codes")
        if not _codes_ok(self.codes, RUN_CODES):
            raise ValueError("codes must be ordered run codes")
        if not (type(self.nodes) is tuple and len(self.nodes) <= MAX_NODES
                and all(type(n) is ResilienceNode for n in self.nodes)):
            raise ValueError("nodes must be a bounded tuple of ResilienceNode")
        echo = (self.run_id, self.as_of_utc, self.worktree_state, self.stop_reason, self.operational_reason,
                self.next_action, self.earliest_quota_eligible_utc)
        if self.request_reasons:
            unobservable = all(r in UNOBSERVABLE_REASONS for r in self.request_reasons)
            if (self.outcome != (UNOBSERVABLE if unobservable else REFUSED) or self.nodes or self.codes
                    or echo != (None,) * len(echo)):
                raise ValueError("a refused or unobservable request echoes nothing and assesses nothing")
            return
        if self.outcome in (REFUSED, UNOBSERVABLE):
            raise ValueError("an accepted request is never REFUSED or UNOBSERVABLE")
        if not fd._is_director_pipeline_id(self.run_id):
            raise ValueError("run_id must be a Director pipeline id")
        if self.as_of_utc is None or not ss._utc_ok(self.as_of_utc):
            raise ValueError("as_of_utc must be normalized UTC")
        if self.worktree_state not in WORKTREE_STATES:
            raise ValueError("worktree_state must be a Host worktree observation")
        if not (self.stop_reason is None or self.stop_reason in RUNNER_STOP_REASONS + (UNRECOGNIZED,)):
            raise ValueError("stop_reason must be a Runner stop reason code")
        if (self.stop_reason == UNRECOGNIZED) != (STOP_REASON_UNRECOGNIZED in self.codes):
            raise ValueError("an unrecognized stop reason is exactly STOP_REASON_UNRECOGNIZED")
        if (self.stop_reason == DEADLINE_REACHED) != (DEADLINE_REACHED_BY_RUNNER in self.codes):
            raise ValueError("a Runner deadline stop is exactly DEADLINE_REACHED_BY_RUNNER")
        ids = [n.node_id for n in self.nodes]
        if len(set(ids)) != len(ids) or any(d not in ids for n in self.nodes for d in n.depends_on):
            raise ValueError("nodes must be unique and depend only on nodes of this run")
        if (SUMMARY_INVALID in self.codes) == bool(self.nodes):
            raise ValueError("an invalid summary is exactly the absence of nodes")
        if (NODE_UNKNOWN in self.codes) != any(n.reason == UNKNOWN_STATE for n in self.nodes):
            raise ValueError("NODE_UNKNOWN is exactly the presence of an UNKNOWN_STATE node")
        if self.outcome != outcome_for(self.nodes, self.codes):
            raise ValueError("outcome must be exactly the one derived from nodes and codes")
        primary = _primary(self.nodes)
        expected = (UNKNOWN_STATE, REVIEW_STATE_INTEGRITY) if primary is None else (primary.reason,
                                                                                     primary.next_action)
        if (self.operational_reason, self.next_action) != expected:
            raise ValueError("operational reason and next action are the primary node's")
        quota = sorted(n.next_eligible_utc for n in self.nodes if n.next_eligible_utc is not None)
        if self.earliest_quota_eligible_utc != (quota[0] if quota else None):
            raise ValueError("earliest_quota_eligible_utc must be the earliest node eligibility")

    @property
    def actor(self) -> Optional[str]:
        return None if self.next_action is None else ACTOR_OF_ACTION[self.next_action]

    @property
    def human_action_required(self) -> bool:
        """Informational: the next action belongs to a human operator."""
        return self.actor == ACTOR_HUMAN

    @property
    def held_dependents(self) -> tuple:
        return tuple(n.node_id for n in self.nodes if n.held_by)

    def node_of(self, node_id: str) -> Optional[ResilienceNode]:
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        return None

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA, "schema_version": SCHEMA_VERSION, "outcome": self.outcome, "run_id": self.run_id,
            "as_of_utc": self.as_of_utc, "worktree_state": self.worktree_state, "stop_reason": self.stop_reason,
            "operational_reason": self.operational_reason, "next_action": self.next_action, "actor": self.actor,
            "human_action_required": self.human_action_required,
            "earliest_quota_eligible_utc": self.earliest_quota_eligible_utc,
            "held_dependents": list(self.held_dependents), "request_reasons": list(self.request_reasons),
            "codes": list(self.codes), "nodes": [n.to_dict() for n in self.nodes],
            **_ResilienceGuarantees._guarantees(),
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical_json(self).encode("ascii")).hexdigest()


def canonical_json(assessment: ResilienceAssessment) -> str:
    """Stable, sorted, compact, size-bounded serialization of the exact
    contract type (a subclass cannot substitute `to_dict`)."""
    if type(assessment) is not ResilienceAssessment:
        raise TypeError("canonical_json accepts only a ResilienceAssessment")
    text = sc._canonical(ResilienceAssessment.to_dict(assessment))
    if len(text) > MAX_CANONICAL_JSON_BYTES:
        raise ValueError("canonical assessment exceeds MAX_CANONICAL_JSON_BYTES")
    return text


def _rejected(reasons) -> ResilienceAssessment:
    reasons = _ordered(reasons, REQUEST_REASONS)
    outcome = UNOBSERVABLE if all(r in UNOBSERVABLE_REASONS for r in reasons) else REFUSED
    return ResilienceAssessment(
        outcome=outcome, run_id=None, as_of_utc=None, worktree_state=None, stop_reason=None,
        operational_reason=None, next_action=None, earliest_quota_eligible_utc=None, request_reasons=reasons,
        codes=(), nodes=(),
    )


# ---------------------------------------------------------------------------
# Assessment
# ---------------------------------------------------------------------------

def _request_reasons(request) -> tuple:
    if type(request) is not ResilienceRequest:
        return (REQUEST_NOT_TYPED,)
    reasons = set()
    if not (sc._is_int(request.schema_version) and request.schema_version == REQUEST_SCHEMA_VERSION):
        reasons.add(SCHEMA_VERSION_UNSUPPORTED)
    if not fd._is_director_pipeline_id(request.run_id):
        reasons.add(RUN_ID_INVALID)
    if type(request.dag_summary) is not fd.DirectorDagRunSummary:
        reasons.add(SUMMARY_NOT_TYPED)
    if type(request.worktree_state) is not str or request.worktree_state not in WORKTREE_STATES:
        reasons.add(WORKTREE_STATE_INVALID)
    if request.window is not None and type(request.window) is not sw.ExecutionWindow:
        reasons.add(WINDOW_NOT_TYPED)
    return _ordered(reasons, REQUEST_REASONS)


def _evaluate_instant(request: ResilienceRequest, clock) -> tuple:
    """(WindowEvaluation or None, refusal reasons). The clock, when given,
    is called exactly once by `evaluate_window`."""
    window = request.window if request.window is not None else sw.ExecutionWindow()
    evaluation = sw.evaluate_window(window, as_of=request.as_of_utc, clock=clock)
    if evaluation.status != sw.INVALID:
        return evaluation, ()
    reasons = set()
    for code in evaluation.reasons:
        if code in _SW_CLOCK_REASONS:
            reasons.add(CLOCK_UNAVAILABLE)
        elif code in _SW_SOURCE_REASONS:
            reasons.add(AS_OF_SOURCE_INVALID)
        elif code in _SW_AS_OF_REASONS:
            reasons.add(AS_OF_INVALID)
        else:
            reasons.add(WINDOW_INVALID)
    return None, _ordered(reasons, REQUEST_REASONS)


def _stop_reason_code(value) -> Optional[str]:
    if value is None:
        return None
    code = ss._native_code(value)
    return code if code in RUNNER_STOP_REASONS else UNRECOGNIZED


def _base_node(w, state_node, as_of: datetime, worktree: str) -> tuple:
    """(reason, action, codes, next_eligible, seconds) for one worker before
    dependency and deadline propagation."""
    codes = set()
    native = state_node.native_state
    if state_node.status == ss.UNKNOWN:
        codes.add(STATE_PROJECTION_UNKNOWN)
    work_used, availability_used = w.work_attempts_used, w.availability_attempts
    if not (_opt_count(work_used) and _opt_count(availability_used)):
        codes.add(ATTEMPT_ACCOUNTING_INCONSISTENT)
    next_eligible = seconds = None
    if native in _AVAILABILITY_NATIVE:
        expected = ("PROVIDER_QUOTA_EXHAUSTED" if native == WAITING_PROVIDER_QUOTA else "PROVIDER_AUTH_BLOCKED")
        if state_node.provider_condition != expected:
            codes.add(PROVIDER_CONDITION_MISMATCH)
        if not (sc._is_int(availability_used) and availability_used >= 1 and sc._is_int(work_used)):
            codes.add(ATTEMPT_ACCOUNTING_INCONSISTENT)
    if native == WAITING_PROVIDER_QUOTA:
        eligible = sw.parse_utc(state_node.next_eligible_utc)
        if eligible is None or ss.TIMESTAMP_INVALID in state_node.codes:
            codes.add(QUOTA_ELIGIBILITY_UNKNOWN)
        else:
            next_eligible = sc._utc_text(eligible)
            seconds = max(sw._ceil_seconds(eligible - as_of), 0)
            if seconds == 0:
                codes.add(QUOTA_ELIGIBILITY_REACHED)
    if native in (INTERRUPTED, BLOCKED_PROVIDER_AUTH) or (
            native == _W.BLOCKED.value and state_node.native_reason == PROCESS_UNRESOLVED_NATIVE_REASON):
        if worktree == WORKTREE_DIRTY:
            codes.add(WORKTREE_DIRTY_NO_DERIVED_RESUME)
        elif worktree == WORKTREE_UNKNOWN:
            codes.add(WORKTREE_STATE_UNOBSERVED)

    if any(c in NODE_UNKNOWN_CODES for c in codes):
        return UNKNOWN_STATE, REVIEW_STATE_INTEGRITY, codes, None, None
    if native == _W.BLOCKED.value and state_node.native_reason == PROCESS_UNRESOLVED_NATIVE_REASON:
        return PROCESS_UNRESOLVED, CONFIRM_PROVIDER_PROCESS_STOPPED, codes, None, None
    if native == BLOCKED_PROVIDER_AUTH:
        return BLOCKED_PROVIDER_AUTH, RESTORE_PROVIDER_AUTH, codes, None, None
    if native == INTERRUPTED:
        action = REVIEW_DIRTY_WORKTREE if WORKTREE_DIRTY_NO_DERIVED_RESUME in codes else REVIEW_INTERRUPTED_WORK
        return INTERRUPTED, action, codes, None, None
    if native == WAITING_PROVIDER_QUOTA:
        action = OBSERVE_RUNNER_QUOTA_REEVALUATION if seconds == 0 else AWAIT_PROVIDER_QUOTA_RECOVERY
        return WAITING_PROVIDER_QUOTA, action, codes, next_eligible, seconds
    if native == _W.RETRY_WAIT.value:
        return TRANSIENT_RETRY_WAIT, OBSERVE_RUNNER_RETRY, codes, None, None
    if native == _W.RUNNING.value:
        return RUNNING, OBSERVE_RUNNER, codes, None, None
    if native in _PENDING_NATIVE:
        return PENDING, OBSERVE_RUNNER, codes, None, None
    if native in (_W.FAILED.value, _W.PARTIAL.value, _W.BLOCKED.value):
        return WORK_NOT_SUCCESSFUL, REVIEW_WORK_OUTCOME, codes, None, None
    if native == _W.CANCELLED.value:
        return CANCELLED, REVIEW_CANCELLATION, codes, None, None
    return COMPLETED, NO_ACTION, codes, None, None


def _assess_nodes(summary, projection, as_of: datetime, worktree: str, deadline: bool) -> tuple:
    workers = summary.workers
    base = {w.worker_id: list(_base_node(w, sn, as_of, worktree)) for w, sn in zip(workers, projection.nodes)}
    native = {sn.node_id: sn.native_state for sn in projection.nodes}
    never_releasing = frozenset(i for i, entry in base.items() if native[i] in _NEVER_RELEASING_NATIVE
                                or entry[0] == PROCESS_UNRESOLVED)

    def to_unknown(node_id, code):
        entry = base[node_id]
        entry[0], entry[1], entry[3], entry[4] = UNKNOWN_STATE, REVIEW_STATE_INTEGRITY, None, None
        entry[2].discard(QUOTA_ELIGIBILITY_REACHED)
        entry[2].add(code)

    # A node already past a hold the Runner never releases contradicts it.
    for w in workers:
        if native[w.worker_id] not in _PENDING_NATIVE | {_W.CANCELLED.value} and any(
                d in never_releasing for d in w.depends_on):
            to_unknown(w.worker_id, DEPENDENT_ADVANCED_PAST_HOLD)
    # Deadline: nothing not yet running (and not operator-held) starts again.
    if deadline:
        for w in workers:
            entry = base[w.worker_id]
            if entry[0] != UNKNOWN_STATE and native[w.worker_id] in _DEADLINE_AFFECTED_NATIVE:
                entry[0], entry[1], entry[3], entry[4] = DEADLINE_REACHED, DECIDE_NEW_EXECUTION_WINDOW, None, None
                entry[2].discard(QUOTA_ELIGIBILITY_REACHED)

    # Dependency holds, resolved upstream-first. The summary is acyclic
    # (FCP-8B-01 refuses cycles) and a visited node is never re-entered.
    deps = {w.worker_id: tuple(w.depends_on) for w in workers}
    held_by: dict = {}
    human: dict = {}

    def resolve(node_id):
        if node_id in human:
            return
        entry = base[node_id]
        held_by[node_id], human[node_id] = (), entry[0] in _OPERATOR_RELEASED
        if entry[0] != PENDING:
            return
        for d in deps[node_id]:
            resolve(d)
        held = tuple(d for d in deps[node_id] if base[d][0] in _HOLDING_REASONS)
        if held:
            needs_human = any(human[d] for d in held)
            entry[0] = DEPENDENCY_HELD
            entry[1] = RESOLVE_UPSTREAM_HOLD if needs_human else AWAIT_UPSTREAM
            if needs_human:
                entry[2].add(UPSTREAM_REQUIRES_HUMAN)
            held_by[node_id], human[node_id] = held, needs_human

    for w in workers:
        resolve(w.worker_id)

    nodes = []
    for w, sn in zip(workers, projection.nodes):
        reason, action, codes, next_eligible, seconds = base[w.worker_id]
        held = held_by[w.worker_id]
        nodes.append(ResilienceNode(
            node_id=w.worker_id, depends_on=tuple(w.depends_on), native_state=sn.native_state, reason=reason,
            next_action=action, codes=_ordered(codes, NODE_CODES), held_by=held,
            work_attempts_used=w.work_attempts_used if _opt_count(w.work_attempts_used) else None,
            availability_attempts=w.availability_attempts if _opt_count(w.availability_attempts) else None,
            next_eligible_utc=next_eligible, seconds_until_eligible=seconds,
        ))
    return tuple(nodes)


def assess_resilience(request: ResilienceRequest, *, clock=None) -> ResilienceAssessment:
    """Pure, deterministic continuity advisory over what the caller already
    read. Exactly one of `request.as_of_utc` or `clock` (called once) gives
    the instant. Never raises on bad input and never mutates it. The result
    never dispatches a dependent, retries, derives a resume, switches a
    provider, starts a process or writes pipeline state."""
    reasons = _request_reasons(request)
    if reasons:
        return _rejected(reasons)
    evaluation, reasons = _evaluate_instant(request, clock)
    if reasons:
        return _rejected(reasons)
    as_of_text = evaluation.as_of_utc
    as_of = sw.parse_utc(as_of_text)
    summary = request.dag_summary
    projection = ss.project_state(ss.StateProjectionRequest(run_id=request.run_id, as_of_utc=as_of_text,
                                                            dag_summary=summary))
    stop_reason = _stop_reason_code(summary.stop_reason)
    codes = set()
    if stop_reason == UNRECOGNIZED:
        codes.add(STOP_REASON_UNRECOGNIZED)
    if stop_reason == DEADLINE_REACHED:
        codes.add(DEADLINE_REACHED_BY_RUNNER)
    if evaluation.status == sw.EXPIRED:
        codes.add(DEADLINE_PASSED_PER_WINDOW)
    elif evaluation.status == sw.WAIT_UNTIL:
        codes.add(WINDOW_NOT_OPEN)
    if projection.request_reasons or ss.SUMMARY_INVALID in projection.codes or not projection.nodes:
        codes.add(SUMMARY_INVALID)
        nodes = ()
    else:
        deadline = DEADLINE_REACHED_BY_RUNNER in codes or DEADLINE_PASSED_PER_WINDOW in codes
        nodes = _assess_nodes(summary, projection, as_of, request.worktree_state, deadline)
    if any(n.reason == UNKNOWN_STATE for n in nodes):
        codes.add(NODE_UNKNOWN)
    ordered = _ordered(codes, RUN_CODES)
    primary = _primary(nodes)
    quota = sorted(n.next_eligible_utc for n in nodes if n.next_eligible_utc is not None)
    return ResilienceAssessment(
        outcome=outcome_for(nodes, ordered), run_id=request.run_id, as_of_utc=as_of_text,
        worktree_state=request.worktree_state, stop_reason=stop_reason,
        operational_reason=UNKNOWN_STATE if primary is None else primary.reason,
        next_action=REVIEW_STATE_INTEGRITY if primary is None else primary.next_action,
        earliest_quota_eligible_utc=quota[0] if quota else None, request_reasons=(), codes=ordered, nodes=nodes,
    )


# ---------------------------------------------------------------------------
# Observation (the only reader)
# ---------------------------------------------------------------------------

def observe_resilience(service, run_id, *, as_of_utc=None, clock=None, window=None,
                       worktree_state: str = WORKTREE_UNKNOWN) -> ResilienceAssessment:
    """Read `service.result_blueprint(run_id)` exactly once and assess it.
    Nothing else of the service is ever touched. Never raises on bad input
    or a failing read; never writes, dispatches, retries or resumes."""
    if not fd._is_director_pipeline_id(run_id):
        return _rejected((RUN_ID_INVALID,))
    try:
        summary = service.result_blueprint(run_id)
    except fd.DirectorError as exc:
        return _rejected((PROVENANCE_REFUSED if exc.code == "DAG_PROVENANCE_MISMATCH" else READ_FAILED,))
    except Exception:  # noqa: BLE001 - any read failure is UNOBSERVABLE, never progress
        return _rejected((READ_FAILED,))
    return assess_resilience(ResilienceRequest(run_id=run_id, dag_summary=summary, as_of_utc=as_of_utc,
                                               window=window, worktree_state=worktree_state), clock=clock)
