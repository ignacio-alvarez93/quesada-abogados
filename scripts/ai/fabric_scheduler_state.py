"""FCP-9C-02: Scheduler state projection and reliable tracking - pure,
deterministic, fail-closed, provider-neutral, NON-AUTHORITATIVE.

Answers ONE question: given what the Director's public query interfaces
already returned for one DAG run (`result_blueprint`, optionally `status`)
and the FCP-8 evaluations of that same projection, what is the tracked state
of every node and of the run, and how much of it is actually proven? It never
answers "may I dispatch / retry / resume now?".

Sources (the only authority of the projection)
----------------------------------------------
* `DirectorDagRunSummary` (`FabricDirectorService.result_blueprint`): the
  native worker states, state reasons, provider conditions, quota
  eligibility instants and the Director's own `runner_proven_success`.
* optionally the Runner pipeline status (`FabricDirectorService.status`, i.e.
  `runner_pipeline.read_pipeline_status`), read only for what the summary
  does not carry: per-RUNNING-worker `liveness` / `last_heartbeat_utc`, the
  run's `started_at_utc` / `ended_at_utc`, the native counts and
  `max_observed_concurrency` (the Runner's per-orchestrator-process maximum).
* optionally the FCP-8 evaluations: `DagRunObservation` (FCP-8B-01) and
  `EvidenceClassification` (FCP-8B-02). They are never trusted as given: each
  must be exactly what `observe_dag_run` / `classify_evidence` derive from
  this very summary (re-derived in memory over the already-read value, never
  by a second Director read), otherwise it is a mismatch.

`project_state(request)` is pure: no I/O, clock, environment, process, Git or
network; the evaluation instant is the explicit `as_of_utc`.
`observe_scheduler_state(service, run_id, ...)` is the only reader: it calls
`service.result_blueprint(run_id)` and then `service.status(run_id)` exactly
once each and nothing else - no `submit*`, `run*`, `recover`, ledger, lease,
pool, stdout/stderr or provider evidence is ever touched, and nothing
persisted is modified. No ledger, schema store or worker pool of its own
exists. Provider prose (`state_reason` text, `stop_reason`, provider output)
is never interpreted: a native reason is projected only as its leading
UPPER_SNAKE code, anything else is UNRECOGNIZED.

Node status (per worker, from its native `WorkerState`)
-------------------------------------------------------
QUEUED / WAITING_DEPENDENCY / RETRY_WAIT -> PENDING; READY -> READY;
RUNNING -> RUNNING; WAITING_PROVIDER_QUOTA -> WAITING_PROVIDER_QUOTA;
BLOCKED / BLOCKED_PROVIDER_AUTH / INTERRUPTED -> BLOCKED; FAILED / PARTIAL ->
FAILED; CANCELLED -> CANCELLED; SUCCESS -> SUCCESS only when the Director's
`runner_proven_success` is True AND a bound FCP-8 observation shows the worker
`work_proven` and `evidence_certain`, else UNVERIFIED. An unrecognized state,
an internally inconsistent record (FCP-8B-01 inconsistency codes), a state
contradicting the Runner status or a mismatched FCP-8 evaluation is UNKNOWN -
never SUCCESS. The native state is always echoed (validated) alongside.

A RUNNING node's `heartbeat` is VERIFIED only when the Runner status reports
`liveness=ALIVE` with a parseable `last_heartbeat_utc` no later than
`as_of_utc` and no older than `max_heartbeat_age_seconds` (at most the
Runner's own `DEFAULT_LEASE_SECONDS`); STALE when the Runner reports STALE or
the beat is too old; otherwise UNVERIFIABLE (status not observed, no beat, a
future beat, a PID-only liveness). Every other node is NOT_APPLICABLE.

Run outcome (most cautious first)
---------------------------------
REFUSED (invalid request, nothing echoed) / UNOBSERVABLE (the read failed) >
UNKNOWN (corrupt summary, any UNKNOWN node, any status / count / FCP-8
mismatch, contradictory aggregate or timestamps) > IN_PROGRESS (a node
PENDING/READY/RUNNING, or the Runner still RUNNING/DRAINING) > PAUSED (only
provider-quota waits or operator-recoverable holds remain) > UNVERIFIED (all
native-terminal, but the Runner or FCP-8 proof is missing or partial) >
NOT_SUCCESSFUL (terminal, non-success, confirmed by FCP-8 NOT_SUCCESSFUL) /
SUCCESS (every node SUCCESS, Runner SUCCESS aggregate, FCP-8
ALL_WORKERS_PROVEN and, when given, a bound classification with
`work_success`). Only SUCCESS and NOT_SUCCESSFUL are `finished`.

Metrics are counts of what was observed (workers, native-terminal workers,
per-status counts, verified heartbeats, pauses) plus the native
`max_observed_concurrency` when the Runner reported it; no duration, ETA or
rate is ever computed. Output (`StateProjection`, schema
`fcp9c02-scheduler-state-projection-v1`) holds only validated ids, enumerated
codes, normalized UTC timestamps, integers and digests, and fixes every
FCP-9A-01 zero-authority flag to False as read-only properties.
"""

from __future__ import annotations

import dataclasses
import hashlib
import re
from dataclasses import dataclass
from typing import Optional

try:
    from scripts.ai import fabric_director as fd
    from scripts.ai import fabric_scheduler_contract as sc
    from scripts.ai import fabric_scheduler_window as sw
    from scripts.ai import fabric_validation_dag as vd
    from scripts.ai import fabric_validation_rules as vr
    from scripts.ai import runner_pipeline as pipeline
except ImportError:  # pragma: no cover - direct script execution
    import fabric_director as fd  # type: ignore[no-redef]
    import fabric_scheduler_contract as sc  # type: ignore[no-redef]
    import fabric_scheduler_window as sw  # type: ignore[no-redef]
    import fabric_validation_dag as vd  # type: ignore[no-redef]
    import fabric_validation_rules as vr  # type: ignore[no-redef]
    import runner_pipeline as pipeline  # type: ignore[no-redef]

REQUEST_SCHEMA_VERSION = 1
SCHEMA = "fcp9c02-scheduler-state-projection-v1"
SCHEMA_VERSION = 1
STATE_MARKER = "FCP9C02_STATE_PROJECTION_ADVISORY_ONLY_NOT_CERTIFIED_NOT_AUTHORIZED"

MAX_NODES = vd.MAX_WORKERS
MAX_OBSERVED_CONCURRENCY = pipeline.MAX_PIPELINE_WORKERS
MAX_HEARTBEAT_AGE_SECONDS = int(pipeline.DEFAULT_LEASE_SECONDS)
MAX_CANONICAL_JSON_BYTES = 262144

_W = pipeline.WorkerState
_PS = pipeline.PipelineStatus
NATIVE_STATES = tuple(s.value for s in _W)
PIPELINE_STATUSES = tuple(s.value for s in _PS)
_NATIVE_TERMINAL = frozenset(s.value for s in pipeline.TERMINAL_STATES)
_NATIVE_CODE_RE = re.compile(r"[A-Z][A-Z0-9_]{0,63}")
UNRECOGNIZED = "UNRECOGNIZED"

# Node statuses.
PENDING = "PENDING"
READY = "READY"
RUNNING = "RUNNING"
SUCCESS = "SUCCESS"
UNVERIFIED = "UNVERIFIED"
FAILED = "FAILED"
WAITING_PROVIDER_QUOTA = "WAITING_PROVIDER_QUOTA"
BLOCKED = "BLOCKED"
CANCELLED = "CANCELLED"
UNKNOWN = "UNKNOWN"
NODE_STATUSES = (PENDING, READY, RUNNING, SUCCESS, UNVERIFIED, FAILED, WAITING_PROVIDER_QUOTA, BLOCKED, CANCELLED,
                 UNKNOWN)

# Native WorkerState -> node status (SUCCESS is further gated by proof).
STATUS_OF_NATIVE = {
    _W.QUEUED.value: PENDING, _W.WAITING_DEPENDENCY.value: PENDING, _W.RETRY_WAIT.value: PENDING,
    _W.READY.value: READY, _W.RUNNING.value: RUNNING, _W.WAITING_PROVIDER_QUOTA.value: WAITING_PROVIDER_QUOTA,
    _W.BLOCKED.value: BLOCKED, _W.BLOCKED_PROVIDER_AUTH.value: BLOCKED, _W.INTERRUPTED.value: BLOCKED,
    _W.FAILED.value: FAILED, _W.PARTIAL.value: FAILED, _W.CANCELLED.value: CANCELLED, _W.SUCCESS.value: SUCCESS,
}
_PROGRESSING = frozenset({PENDING, READY, RUNNING})
# Native non-terminal holds only the Runner or an operator can release.
_PAUSING_NATIVE = frozenset({_W.WAITING_PROVIDER_QUOTA.value, _W.BLOCKED_PROVIDER_AUTH.value, _W.INTERRUPTED.value})
_OPERATOR_HOLD_NATIVE = frozenset({_W.BLOCKED_PROVIDER_AUTH.value, _W.INTERRUPTED.value})

# Heartbeat evidence of a RUNNING node.
HB_VERIFIED = "VERIFIED"
HB_STALE = "STALE"
HB_UNVERIFIABLE = "UNVERIFIABLE"
HB_NOT_APPLICABLE = "NOT_APPLICABLE"
HEARTBEATS = (HB_VERIFIED, HB_STALE, HB_UNVERIFIABLE, HB_NOT_APPLICABLE)
LIVENESS_ALIVE = "ALIVE"
LIVENESS_STALE = "STALE"

# Run outcomes.
REFUSED = "REFUSED"
UNOBSERVABLE = "UNOBSERVABLE"
IN_PROGRESS = "IN_PROGRESS"
PAUSED = "PAUSED"
NOT_SUCCESSFUL = "NOT_SUCCESSFUL"
OUTCOMES = (REFUSED, UNOBSERVABLE, UNKNOWN, IN_PROGRESS, PAUSED, UNVERIFIED, NOT_SUCCESSFUL, SUCCESS)
FINISHED_OUTCOMES = (NOT_SUCCESSFUL, SUCCESS)

# Request-level refusal / unobservable codes, in their fixed canonical order.
REQUEST_NOT_TYPED = "REQUEST_NOT_TYPED"
SCHEMA_VERSION_UNSUPPORTED = "SCHEMA_VERSION_UNSUPPORTED"
RUN_ID_INVALID = "RUN_ID_INVALID"
AS_OF_INVALID = "AS_OF_INVALID"
MAX_HEARTBEAT_AGE_INVALID = "MAX_HEARTBEAT_AGE_INVALID"
EXPECTED_DIGEST_INVALID = "EXPECTED_DIGEST_INVALID"
SUMMARY_NOT_TYPED = "SUMMARY_NOT_TYPED"
FCP8_OBSERVATION_NOT_TYPED = "FCP8_OBSERVATION_NOT_TYPED"
FCP8_CLASSIFICATION_NOT_TYPED = "FCP8_CLASSIFICATION_NOT_TYPED"
CLASSIFICATION_WITHOUT_OBSERVATION = "CLASSIFICATION_WITHOUT_OBSERVATION"
READ_FAILED = "READ_FAILED"
PROVENANCE_REFUSED = "PROVENANCE_REFUSED"
REFUSAL_REASONS = (
    REQUEST_NOT_TYPED, SCHEMA_VERSION_UNSUPPORTED, RUN_ID_INVALID, AS_OF_INVALID, MAX_HEARTBEAT_AGE_INVALID,
    EXPECTED_DIGEST_INVALID, SUMMARY_NOT_TYPED, FCP8_OBSERVATION_NOT_TYPED, FCP8_CLASSIFICATION_NOT_TYPED,
    CLASSIFICATION_WITHOUT_OBSERVATION,
)
UNOBSERVABLE_REASONS = (READ_FAILED, PROVENANCE_REFUSED)
REQUEST_REASONS = REFUSAL_REASONS + UNOBSERVABLE_REASONS

# Node codes, grouped by the status they force, in their fixed order.
NATIVE_STATE_UNRECOGNIZED = "NATIVE_STATE_UNRECOGNIZED"
NODE_RECORD_INCONSISTENT = "NODE_RECORD_INCONSISTENT"
STATUS_ENTRY_MISMATCH = "STATUS_ENTRY_MISMATCH"
FCP8_OBSERVATION_MISMATCH = "FCP8_OBSERVATION_MISMATCH"
RUNNER_UNPROVEN = "RUNNER_UNPROVEN"
FCP8_EVALUATION_MISSING = "FCP8_EVALUATION_MISSING"
FCP8_WORK_UNPROVEN = "FCP8_WORK_UNPROVEN"
FCP8_EVIDENCE_UNCERTAIN = "FCP8_EVIDENCE_UNCERTAIN"
HEARTBEAT_NOT_OBSERVED = "HEARTBEAT_NOT_OBSERVED"
HEARTBEAT_UNVERIFIABLE = "HEARTBEAT_UNVERIFIABLE"
HEARTBEAT_FROM_FUTURE = "HEARTBEAT_FROM_FUTURE"
HEARTBEAT_STALE = "HEARTBEAT_STALE"
TIMESTAMP_INVALID = "TIMESTAMP_INVALID"
NATIVE_REASON_UNRECOGNIZED = "NATIVE_REASON_UNRECOGNIZED"
PROVIDER_CONDITION_UNRECOGNIZED = "PROVIDER_CONDITION_UNRECOGNIZED"
NODE_UNKNOWN_CODES = (NATIVE_STATE_UNRECOGNIZED, NODE_RECORD_INCONSISTENT, STATUS_ENTRY_MISMATCH,
                      FCP8_OBSERVATION_MISMATCH)
NODE_UNVERIFIED_CODES = (RUNNER_UNPROVEN, FCP8_EVALUATION_MISSING, FCP8_WORK_UNPROVEN, FCP8_EVIDENCE_UNCERTAIN)
HEARTBEAT_CODES = (HEARTBEAT_NOT_OBSERVED, HEARTBEAT_UNVERIFIABLE, HEARTBEAT_FROM_FUTURE, HEARTBEAT_STALE)
NODE_INFO_CODES = HEARTBEAT_CODES + (TIMESTAMP_INVALID, NATIVE_REASON_UNRECOGNIZED, PROVIDER_CONDITION_UNRECOGNIZED)
NODE_CODES = NODE_UNKNOWN_CODES + NODE_UNVERIFIED_CODES + NODE_INFO_CODES

# FCP-8B-01 worker codes that mean the Director record contradicts itself.
RECORD_INCONSISTENCY_CODES = ("FIELD_MALFORMED", "PROOF_MALFORMED", "PROOF_REASONS_DISAGREE",
                              "PROOF_CONTRADICTS_FIELDS", "REASON_CONTRADICTS_FIELDS", "EVIDENCE_HEALTH_MISMATCH")

# Run codes, grouped by whether they force UNKNOWN, in their fixed order.
SUMMARY_INVALID = "SUMMARY_INVALID"
PIPELINE_STATUS_UNKNOWN = "PIPELINE_STATUS_UNKNOWN"
STATUS_MALFORMED = "STATUS_MALFORMED"
STATUS_MISMATCH = "STATUS_MISMATCH"
FCP8_CLASSIFICATION_MISMATCH = "FCP8_CLASSIFICATION_MISMATCH"
METRICS_MISMATCH = "METRICS_MISMATCH"
TIMESTAMP_INCONSISTENT = "TIMESTAMP_INCONSISTENT"
AGGREGATE_STATE_MISMATCH = "AGGREGATE_STATE_MISMATCH"
NODE_UNKNOWN = "NODE_UNKNOWN"
STATUS_NOT_OBSERVED = "STATUS_NOT_OBSERVED"
STATUS_READ_FAILED = "STATUS_READ_FAILED"
FCP8_CLASSIFICATION_MISSING = "FCP8_CLASSIFICATION_MISSING"
FCP8_WORK_NOT_SUCCESSFUL = "FCP8_WORK_NOT_SUCCESSFUL"
CONCURRENCY_NOT_OBSERVED = "CONCURRENCY_NOT_OBSERVED"
RUN_TIMESTAMP_INVALID = "RUN_TIMESTAMP_INVALID"
RUN_TIMESTAMP_FROM_FUTURE = "RUN_TIMESTAMP_FROM_FUTURE"
RUNNING_HEARTBEAT_UNVERIFIED = "RUNNING_HEARTBEAT_UNVERIFIED"
RUN_UNKNOWN_CODES = (
    SUMMARY_INVALID, PIPELINE_STATUS_UNKNOWN, STATUS_MALFORMED, STATUS_MISMATCH, FCP8_OBSERVATION_MISMATCH,
    FCP8_CLASSIFICATION_MISMATCH, METRICS_MISMATCH, TIMESTAMP_INCONSISTENT, AGGREGATE_STATE_MISMATCH, NODE_UNKNOWN,
)
RUN_INFO_CODES = (
    STATUS_NOT_OBSERVED, STATUS_READ_FAILED, FCP8_EVALUATION_MISSING, FCP8_CLASSIFICATION_MISSING,
    FCP8_WORK_NOT_SUCCESSFUL, CONCURRENCY_NOT_OBSERVED, RUN_TIMESTAMP_INVALID, RUN_TIMESTAMP_FROM_FUTURE,
    RUNNING_HEARTBEAT_UNVERIFIED,
)
RUN_CODES = RUN_UNKNOWN_CODES + RUN_INFO_CODES

# Runner pipeline_result count keys -> native WorkerState they count.
_STATUS_COUNT_KEYS = (
    ("success", _W.SUCCESS.value), ("partial", _W.PARTIAL.value), ("blocked", _W.BLOCKED.value),
    ("failed", _W.FAILED.value), ("cancelled", _W.CANCELLED.value), ("interrupted", _W.INTERRUPTED.value),
    ("waiting_provider_quota", _W.WAITING_PROVIDER_QUOTA.value),
    ("blocked_provider_auth", _W.BLOCKED_PROVIDER_AUTH.value),
)


def _ordered(codes, vocabulary) -> tuple:
    return sc._ordered(codes, vocabulary)


def _codes_ok(codes, vocabulary) -> bool:
    return (type(codes) is tuple and all(type(c) is str and c in vocabulary for c in codes)
            and codes == _ordered(codes, vocabulary))


def _bounded_int(value, low: int, high: int) -> bool:
    return sc._is_int(value) and low <= value <= high


def _utc_ok(value) -> bool:
    return value is None or (type(value) is str and sw.parse_utc(value) is not None
                             and sc._utc_text(sw.parse_utc(value)) == value)


def _native_code(value) -> Optional[str]:
    """The leading UPPER_SNAKE code of a native reason; the rest (worker ids,
    details, prose) is never projected."""
    if value is None:
        return None
    if type(value) is not str:
        return UNRECOGNIZED
    head = value.split(":", 1)[0]
    return head if _NATIVE_CODE_RE.fullmatch(head) else UNRECOGNIZED


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StateProjectionRequest:
    """What the caller already read, verbatim. `runner_status` is the dict
    `FabricDirectorService.status(run_id)` returned (None = not read).
    Validated by `project_state` (fail closed), not here."""
    run_id: str
    as_of_utc: str
    dag_summary: object
    runner_status: Optional[object] = None
    dag_observation: Optional[object] = None
    evidence_classification: Optional[object] = None
    expected_manifest_sha256: Optional[str] = None
    expected_plan_fingerprint: Optional[str] = None
    max_heartbeat_age_seconds: int = MAX_HEARTBEAT_AGE_SECONDS
    schema_version: int = REQUEST_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def node_status_for(native_state: Optional[str], codes: tuple) -> str:
    """The single node-status derivation (also the construction guard)."""
    if any(c in NODE_UNKNOWN_CODES for c in codes) or native_state not in STATUS_OF_NATIVE:
        return UNKNOWN
    if native_state == _W.SUCCESS.value and any(c in NODE_UNVERIFIED_CODES for c in codes):
        return UNVERIFIED
    return STATUS_OF_NATIVE[native_state]


def heartbeat_for(status: str, codes: tuple) -> str:
    if status != RUNNING:
        return HB_NOT_APPLICABLE
    if HEARTBEAT_STALE in codes:
        return HB_STALE
    if any(c in HEARTBEAT_CODES for c in codes):
        return HB_UNVERIFIABLE
    return HB_VERIFIED


@dataclass(frozen=True)
class StateNode:
    """One tracked node. Construction re-derives `status` and `heartbeat`
    from the native state and codes, so a hand-made node cannot claim more
    than its codes prove."""
    node_id: str
    depends_on: tuple
    native_state: Optional[str]
    status: str
    heartbeat: str
    codes: tuple
    native_reason: Optional[str] = None
    provider_condition: Optional[str] = None
    last_heartbeat_utc: Optional[str] = None
    next_eligible_utc: Optional[str] = None

    def __post_init__(self):
        if not sc._safe_id(self.node_id):
            raise ValueError("node_id must be a safe id")
        if not (type(self.depends_on) is tuple and all(sc._safe_id(d) and d != self.node_id
                                                      for d in self.depends_on)):
            raise ValueError("depends_on must be other safe node ids")
        if not (self.native_state is None or self.native_state in NATIVE_STATES or self.native_state == UNRECOGNIZED):
            raise ValueError("native_state must be a native WorkerState, UNRECOGNIZED or None")
        if not _codes_ok(self.codes, NODE_CODES):
            raise ValueError("codes must be ordered node codes")
        if (self.native_state not in STATUS_OF_NATIVE) != (NATIVE_STATE_UNRECOGNIZED in self.codes):
            raise ValueError("an unrecognized native state is exactly NATIVE_STATE_UNRECOGNIZED")
        if type(self.status) is not str or self.status != node_status_for(self.native_state, self.codes):
            raise ValueError("status must be exactly the one derived from native state and codes")
        if type(self.heartbeat) is not str or self.heartbeat != heartbeat_for(self.status, self.codes):
            raise ValueError("heartbeat must be exactly the one derived from status and codes")
        if self.heartbeat == HB_VERIFIED and self.last_heartbeat_utc is None:
            raise ValueError("a VERIFIED heartbeat carries its instant")
        for value in (self.native_reason, self.provider_condition):
            if not (value is None or (type(value) is str and _NATIVE_CODE_RE.fullmatch(value))):
                raise ValueError("native codes must be UPPER_SNAKE tokens")
        if not (_utc_ok(self.last_heartbeat_utc) and _utc_ok(self.next_eligible_utc)):
            raise ValueError("timestamps must be normalized UTC or None")

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id, "depends_on": list(self.depends_on), "native_state": self.native_state,
            "status": self.status, "heartbeat": self.heartbeat, "codes": list(self.codes),
            "native_reason": self.native_reason, "provider_condition": self.provider_condition,
            "last_heartbeat_utc": self.last_heartbeat_utc, "next_eligible_utc": self.next_eligible_utc,
        }


def _metrics_of(nodes: tuple) -> dict:
    tracked = [n for n in nodes if n.status != UNKNOWN]
    return {
        "workers_total": len(nodes),
        "completed": sum(1 for n in tracked if n.native_state in _NATIVE_TERMINAL),
        "running_heartbeat_verified": sum(1 for n in nodes if n.heartbeat == HB_VERIFIED),
        "paused_provider_quota": sum(1 for n in tracked if n.native_state == _W.WAITING_PROVIDER_QUOTA.value),
        "paused_operator": sum(1 for n in tracked if n.native_state in _OPERATOR_HOLD_NATIVE),
        "status_counts": tuple((s, sum(1 for n in nodes if n.status == s)) for s in NODE_STATUSES),
    }


def outcome_for(nodes: tuple, codes: tuple, pipeline_status: Optional[str], fcp8_classification: Optional[str],
                fcp8_work_success: Optional[bool]) -> str:
    """The single run-outcome derivation (also the construction guard) for
    an accepted request."""
    if any(c in RUN_UNKNOWN_CODES for c in codes) or not nodes or any(n.status == UNKNOWN for n in nodes):
        return UNKNOWN
    if any(n.status in _PROGRESSING for n in nodes) or pipeline_status in (_PS.RUNNING.value, _PS.DRAINING.value):
        return IN_PROGRESS
    if any(n.native_state in _PAUSING_NATIVE for n in nodes):
        return PAUSED
    if fcp8_classification is None:
        return UNVERIFIED
    if pipeline_status == _PS.SUCCESS.value:
        proven = (all(n.status == SUCCESS for n in nodes) and fcp8_classification == vd.ALL_WORKERS_PROVEN
                  and fcp8_work_success is not False)
        return SUCCESS if proven else UNVERIFIED
    return NOT_SUCCESSFUL if fcp8_classification == vd.NOT_SUCCESSFUL else UNVERIFIED


class _StateGuarantees(sc._NotAuthorized):
    @staticmethod
    def _guarantees() -> dict:
        guarantees = sc._NotAuthorized._guarantees()
        guarantees["marker"] = STATE_MARKER
        return guarantees


@dataclass(frozen=True)
class StateProjection(_StateGuarantees):
    """Consultative tracked state of one DAG run. Echo fields hold only
    validated values (None and () when refused or unobservable).
    Construction re-derives the outcome, so a hand-made projection cannot
    claim a finish its nodes, codes and FCP-8 evaluation do not support."""
    outcome: str
    run_id: Optional[str]
    pipeline_status: Optional[str]
    aggregate_status: Optional[str]
    manifest_sha256: Optional[str]
    plan_fingerprint: Optional[str]
    fcp8_classification: Optional[str]
    fcp8_work_success: Optional[bool]
    fcp8_observation_sha256: Optional[str]
    started_at_utc: Optional[str]
    ended_at_utc: Optional[str]
    max_observed_concurrency: Optional[int]
    request_reasons: tuple
    codes: tuple
    fcp8_codes: tuple
    nodes: tuple

    def __post_init__(self):
        if type(self.outcome) is not str or self.outcome not in OUTCOMES:
            raise ValueError("unknown projection outcome")
        if not _codes_ok(self.request_reasons, REQUEST_REASONS):
            raise ValueError("request_reasons must be ordered request codes")
        if not _codes_ok(self.codes, RUN_CODES):
            raise ValueError("codes must be ordered run codes")
        if not _codes_ok(self.fcp8_codes, vd.DAG_CODES):
            raise ValueError("fcp8_codes must be ordered FCP-8B-01 codes")
        if not (type(self.nodes) is tuple and len(self.nodes) <= MAX_NODES
                and all(type(n) is StateNode for n in self.nodes)):
            raise ValueError("nodes must be a bounded tuple of StateNode")
        echo = (self.run_id, self.pipeline_status, self.aggregate_status, self.manifest_sha256, self.plan_fingerprint,
                self.fcp8_classification, self.fcp8_work_success, self.fcp8_observation_sha256, self.started_at_utc,
                self.ended_at_utc, self.max_observed_concurrency)
        if self.request_reasons:
            unobservable = all(r in UNOBSERVABLE_REASONS for r in self.request_reasons)
            if (self.outcome != (UNOBSERVABLE if unobservable else REFUSED) or self.nodes or self.codes
                    or self.fcp8_codes or echo != (None,) * len(echo)):
                raise ValueError("a refused or unobservable request echoes nothing and projects nothing")
            return
        if not fd._is_director_pipeline_id(self.run_id):
            raise ValueError("run_id must be a Director pipeline id")
        if self.outcome in (REFUSED, UNOBSERVABLE):
            raise ValueError("an accepted request is never REFUSED or UNOBSERVABLE")
        for value in (self.pipeline_status, self.aggregate_status):
            if not (value is None or value in PIPELINE_STATUSES + (fd.DAG_AGGREGATE_UNVERIFIED, fd.DAG_AGGREGATE_UNKNOWN,
                                                                     UNRECOGNIZED)):
                raise ValueError("pipeline/aggregate status must be native values")
        for value in (self.manifest_sha256, self.plan_fingerprint, self.fcp8_observation_sha256):
            if not (value is None or (type(value) is str and sc._FINGERPRINT_RE.fullmatch(value))):
                raise ValueError("digests must be sha256 hex")
        if not (self.fcp8_classification is None or self.fcp8_classification in vd.DAG_CLASSIFICATIONS):
            raise ValueError("fcp8_classification must be an FCP-8B-01 classification")
        if (self.fcp8_classification is None) != (self.fcp8_observation_sha256 is None):
            raise ValueError("an FCP-8 classification is bound to its observation digest")
        if not (self.fcp8_work_success is None or type(self.fcp8_work_success) is bool):
            raise ValueError("fcp8_work_success must be a bool or None")
        if not (_utc_ok(self.started_at_utc) and _utc_ok(self.ended_at_utc)):
            raise ValueError("timestamps must be normalized UTC or None")
        if self.max_observed_concurrency is not None and not _bounded_int(self.max_observed_concurrency, 0,
                                                                          MAX_OBSERVED_CONCURRENCY):
            raise ValueError("max_observed_concurrency must be None or 0..MAX_OBSERVED_CONCURRENCY")
        ids = [n.node_id for n in self.nodes]
        if len(set(ids)) != len(ids) or any(d not in ids for n in self.nodes for d in n.depends_on):
            raise ValueError("nodes must be unique and depend only on nodes of this run")
        if bool(self.fcp8_codes) != (SUMMARY_INVALID in self.codes) or (SUMMARY_INVALID in self.codes and self.nodes):
            raise ValueError("an invalid summary carries its FCP-8 codes and no node")
        if (NODE_UNKNOWN in self.codes) != any(n.status == UNKNOWN for n in self.nodes):
            raise ValueError("NODE_UNKNOWN is exactly the presence of an UNKNOWN node")
        if self.outcome != outcome_for(self.nodes, self.codes, self.pipeline_status, self.fcp8_classification,
                                       self.fcp8_work_success):
            raise ValueError("outcome must be exactly the one derived from nodes, codes and FCP-8")

    @property
    def finished(self) -> bool:
        """Informational only: a finish is claimed only when proven."""
        return self.outcome in FINISHED_OUTCOMES

    @property
    def metrics(self) -> dict:
        metrics = _metrics_of(self.nodes)
        metrics["max_observed_concurrency"] = self.max_observed_concurrency
        return metrics

    def node_of(self, node_id: str) -> Optional[StateNode]:
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        return None

    def to_dict(self) -> dict:
        metrics = self.metrics
        metrics["status_counts"] = dict(metrics["status_counts"])
        return {
            "schema": SCHEMA, "schema_version": SCHEMA_VERSION, "outcome": self.outcome, "finished": self.finished,
            "run_id": self.run_id, "pipeline_status": self.pipeline_status, "aggregate_status": self.aggregate_status,
            "manifest_sha256": self.manifest_sha256, "plan_fingerprint": self.plan_fingerprint,
            "fcp8_classification": self.fcp8_classification, "fcp8_work_success": self.fcp8_work_success,
            "fcp8_observation_sha256": self.fcp8_observation_sha256, "started_at_utc": self.started_at_utc,
            "ended_at_utc": self.ended_at_utc, "metrics": metrics, "request_reasons": list(self.request_reasons),
            "codes": list(self.codes), "fcp8_codes": list(self.fcp8_codes),
            "nodes": [n.to_dict() for n in self.nodes], **_StateGuarantees._guarantees(),
        }


def canonical_json(projection: StateProjection) -> str:
    """Stable, sorted, compact, size-bounded serialization of the exact
    contract type (a subclass cannot substitute `to_dict`)."""
    if type(projection) is not StateProjection:
        raise TypeError("canonical_json accepts only a StateProjection")
    text = sc._canonical(StateProjection.to_dict(projection))
    if len(text) > MAX_CANONICAL_JSON_BYTES:
        raise ValueError("canonical projection exceeds MAX_CANONICAL_JSON_BYTES")
    return text


def _rejected(reasons) -> StateProjection:
    reasons = _ordered(reasons, REQUEST_REASONS)
    outcome = UNOBSERVABLE if all(r in UNOBSERVABLE_REASONS for r in reasons) else REFUSED
    return StateProjection(
        outcome=outcome, run_id=None, pipeline_status=None, aggregate_status=None, manifest_sha256=None,
        plan_fingerprint=None, fcp8_classification=None, fcp8_work_success=None, fcp8_observation_sha256=None,
        started_at_utc=None, ended_at_utc=None, max_observed_concurrency=None, request_reasons=reasons, codes=(),
        fcp8_codes=(), nodes=(),
    )


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------

class _SummaryReader:
    """An in-memory stand-in exposing only `result_blueprint`, returning the
    summary the caller ALREADY read - so the FCP-8 observation is re-derived
    from the same value, never from a second Director read."""

    def __init__(self, summary):
        self._summary = summary

    def result_blueprint(self, run_id):
        return self._summary


def _request_reasons(request) -> tuple:
    if type(request) is not StateProjectionRequest:
        return (REQUEST_NOT_TYPED,)
    reasons = set()
    if not (sc._is_int(request.schema_version) and request.schema_version == REQUEST_SCHEMA_VERSION):
        reasons.add(SCHEMA_VERSION_UNSUPPORTED)
    if not fd._is_director_pipeline_id(request.run_id):
        reasons.add(RUN_ID_INVALID)
    if sw.parse_utc(request.as_of_utc) is None:
        reasons.add(AS_OF_INVALID)
    if not _bounded_int(request.max_heartbeat_age_seconds, 1, MAX_HEARTBEAT_AGE_SECONDS):
        reasons.add(MAX_HEARTBEAT_AGE_INVALID)
    if any(d is not None and not (type(d) is str and sc._FINGERPRINT_RE.fullmatch(d))
           for d in (request.expected_manifest_sha256, request.expected_plan_fingerprint)):
        reasons.add(EXPECTED_DIGEST_INVALID)
    if type(request.dag_summary) is not fd.DirectorDagRunSummary:
        reasons.add(SUMMARY_NOT_TYPED)
    if request.dag_observation is not None and type(request.dag_observation) is not vd.DagRunObservation:
        reasons.add(FCP8_OBSERVATION_NOT_TYPED)
    classification = request.evidence_classification
    if classification is not None:
        if type(classification) is not vr.EvidenceClassification:
            reasons.add(FCP8_CLASSIFICATION_NOT_TYPED)
        elif request.dag_observation is None:
            reasons.add(CLASSIFICATION_WITHOUT_OBSERVATION)
    return _ordered(reasons, REQUEST_REASONS)


def _same(a, b, canonical) -> bool:
    try:
        return canonical(a) == canonical(b)
    except (TypeError, ValueError):
        return False


def _status_view(status, summary) -> tuple:
    """(entries by id or None, run codes). The Runner status is read only for
    heartbeat, run timestamps, counts and concurrency; it must describe the
    same run, the same workers in the same order and the same states."""
    if status is None:
        return None, {STATUS_NOT_OBSERVED}
    entries = status.get("workers") if type(status) is dict else None
    if not (type(entries) is list and len(entries) <= MAX_NODES and all(type(e) is dict for e in entries)):
        return None, {STATUS_MALFORMED}
    codes = set()
    ids = [w.worker_id for w in summary.workers]
    if (status.get("pipeline_id") != summary.run_id or [e.get("id") for e in entries] != ids
            or status.get("status") != summary.pipeline_status):
        codes.add(STATUS_MISMATCH)
    by_id = {e.get("id"): e for e in entries if type(e.get("id")) is str}
    return by_id, codes


def _heartbeat_codes(entry, as_of, max_age: int) -> tuple:
    """(codes, normalized last beat) for a RUNNING node."""
    if entry is None:
        return {HEARTBEAT_NOT_OBSERVED}, None
    liveness = entry.get("liveness")
    beat = sw.parse_utc(entry.get("last_heartbeat_utc"))
    if liveness == LIVENESS_STALE:
        return {HEARTBEAT_STALE}, sc._utc_text(beat)
    if liveness != LIVENESS_ALIVE or beat is None:
        return {HEARTBEAT_UNVERIFIABLE}, sc._utc_text(beat)
    if beat > as_of:
        return {HEARTBEAT_FROM_FUTURE}, None
    if (as_of - beat).total_seconds() > max_age:
        return {HEARTBEAT_STALE}, sc._utc_text(beat)
    return set(), sc._utc_text(beat)


def _project_node(w, observed: vd.DagWorkerObservation, entry, fcp8_state: str, as_of, max_age: int) -> StateNode:
    """`fcp8_state`: BOUND, MISSING or MISMATCH for the caller's evaluation."""
    codes = set()
    native = w.worker_state if type(w.worker_state) is str and w.worker_state in NATIVE_STATES else None
    if native is None:
        codes.add(NATIVE_STATE_UNRECOGNIZED)
    if any(c in observed.observation_codes for c in RECORD_INCONSISTENCY_CODES):
        codes.add(NODE_RECORD_INCONSISTENT)
    if entry is not _NO_STATUS and (entry is None or entry.get("state") != w.worker_state):
        codes.add(STATUS_ENTRY_MISMATCH)
    if native == _W.SUCCESS.value:
        if w.runner_proven_success is not True:
            codes.add(RUNNER_UNPROVEN)
        if fcp8_state == "MISSING":
            codes.add(FCP8_EVALUATION_MISSING)
        elif fcp8_state == "MISMATCH":
            codes.add(FCP8_OBSERVATION_MISMATCH)
        if not observed.work_proven:
            codes.add(FCP8_WORK_UNPROVEN)
        if not observed.evidence_certain:
            codes.add(FCP8_EVIDENCE_UNCERTAIN)
    last_beat = None
    if native == _W.RUNNING.value:
        beat_codes, last_beat = _heartbeat_codes(None if entry is _NO_STATUS else entry, as_of, max_age)
        codes |= beat_codes
    next_eligible = None
    if native == _W.WAITING_PROVIDER_QUOTA.value and w.next_eligible_utc is not None:
        parsed = sw.parse_utc(w.next_eligible_utc)
        if parsed is None:
            codes.add(TIMESTAMP_INVALID)
        next_eligible = sc._utc_text(parsed)
    native_reason = _native_code(w.state_reason)
    if native_reason == UNRECOGNIZED:
        codes.add(NATIVE_REASON_UNRECOGNIZED)
        native_reason = None
    condition = w.provider_condition
    if condition is not None and not (type(condition) is str and condition in vd.PROVIDER_CONDITIONS):
        codes.add(PROVIDER_CONDITION_UNRECOGNIZED)
        condition = None
    ordered = _ordered(codes, NODE_CODES)
    status = node_status_for(native, ordered)
    return StateNode(
        node_id=w.worker_id, depends_on=tuple(w.depends_on), native_state=native if native else UNRECOGNIZED,
        status=status, heartbeat=heartbeat_for(status, ordered), codes=ordered, native_reason=native_reason,
        provider_condition=condition, last_heartbeat_utc=last_beat if status == RUNNING else None,
        next_eligible_utc=next_eligible,
    )


_NO_STATUS = object()


def _run_timestamps(status, as_of, codes: set) -> tuple:
    stamps = []
    for key in ("started_at_utc", "ended_at_utc"):
        raw = status.get(key)
        parsed = sw.parse_utc(raw) if raw is not None else None
        if raw is not None and parsed is None:
            codes.add(RUN_TIMESTAMP_INVALID)
        elif parsed is not None and parsed > as_of:
            codes.add(RUN_TIMESTAMP_FROM_FUTURE)
            parsed = None
        stamps.append(parsed)
    started, ended = stamps
    if ended is not None and (started is None or ended < started):
        codes.add(TIMESTAMP_INCONSISTENT)
    return sc._utc_text(started), sc._utc_text(ended)


def _native_counts_agree(status, summary) -> bool:
    states = [w.worker_state for w in summary.workers]
    if type(status.get("workers_total")) is not int or status["workers_total"] != len(states):
        return False
    for key, native in _STATUS_COUNT_KEYS:
        value = status.get(key)
        if type(value) is not int or value != states.count(native):
            return False
    counts = status.get("state_counts")
    return type(counts) is dict and counts == {s: states.count(s) for s in NATIVE_STATES}


def project_state(request: StateProjectionRequest) -> StateProjection:
    """Pure, deterministic state projection over what the caller already
    read. Never raises on bad input and never mutates it. The result never
    authorizes dispatch, execution, retry, resume, merge, a fallback or a
    provider switch, and never claims a finish it cannot prove."""
    reasons = _request_reasons(request)
    if reasons:
        return _rejected(reasons)
    summary = request.dag_summary
    as_of = sw.parse_utc(request.as_of_utc)
    derived = vd.observe_dag_run(_SummaryReader(summary), request.run_id,
                                 expected_manifest_sha256=request.expected_manifest_sha256,
                                 expected_plan_fingerprint=request.expected_plan_fingerprint)
    codes = set()
    invalid = derived.classification in (vd.UNOBSERVABLE, vd.INVALID_PROJECTION)
    if invalid or any(not sc._safe_id(w.worker_id) for w in summary.workers):
        # Corruption is UNKNOWN with the FCP-8 schema codes; no node is guessed.
        return StateProjection(
            outcome=UNKNOWN, run_id=request.run_id, pipeline_status=None, aggregate_status=None,
            manifest_sha256=None, plan_fingerprint=None, fcp8_classification=None, fcp8_work_success=None,
            fcp8_observation_sha256=None, started_at_utc=None, ended_at_utc=None, max_observed_concurrency=None,
            request_reasons=(), codes=(SUMMARY_INVALID,),
            fcp8_codes=derived.observation_codes if invalid else ("WORKER_ID_INVALID",), nodes=(),
        )

    observation = request.dag_observation
    if observation is None:
        fcp8_state = "MISSING"
        codes.add(FCP8_EVALUATION_MISSING)
    elif _same(observation, derived, vd.canonical_json):
        fcp8_state = "BOUND"
    else:
        fcp8_state = "MISMATCH"
        codes.add(FCP8_OBSERVATION_MISMATCH)
    work_success = None
    classification = request.evidence_classification
    if fcp8_state == "BOUND":
        if classification is None:
            codes.add(FCP8_CLASSIFICATION_MISSING)
        elif _same(classification, vr.classify_evidence(derived), vr.canonical_json):
            work_success = classification.work_success
            if not work_success:
                codes.add(FCP8_WORK_NOT_SUCCESSFUL)
        else:
            codes.add(FCP8_CLASSIFICATION_MISMATCH)

    entries, status_codes = _status_view(request.runner_status, summary)
    codes |= status_codes
    started = ended = concurrency = None
    if entries is not None:
        started, ended = _run_timestamps(request.runner_status, as_of, codes)
        if not _native_counts_agree(request.runner_status, summary):
            codes.add(METRICS_MISMATCH)
        raw = request.runner_status.get("max_observed_concurrency")
        if raw is None:
            codes.add(CONCURRENCY_NOT_OBSERVED)
        elif _bounded_int(raw, 0, MAX_OBSERVED_CONCURRENCY):
            concurrency = raw
        else:
            codes.add(METRICS_MISMATCH)
    else:
        codes.add(CONCURRENCY_NOT_OBSERVED)

    nodes = tuple(
        _project_node(w, observed, _NO_STATUS if entries is None else entries.get(w.worker_id), fcp8_state, as_of,
                      request.max_heartbeat_age_seconds)
        for w, observed in zip(summary.workers, derived.workers)
    )
    if any(n.status == UNKNOWN for n in nodes):
        codes.add(NODE_UNKNOWN)
    if any(n.status == RUNNING and n.heartbeat != HB_VERIFIED for n in nodes):
        codes.add(RUNNING_HEARTBEAT_UNVERIFIED)
    pipeline_status = derived.pipeline_status
    if pipeline_status is None or pipeline_status == vd.UNRECOGNIZED:
        codes.add(PIPELINE_STATUS_UNKNOWN)
    natives = [n.native_state for n in nodes]
    all_terminal = all(s in _NATIVE_TERMINAL for s in natives)
    if (pipeline_status in (_PS.SUCCESS.value, _PS.PARTIAL.value, _PS.BLOCKED.value, _PS.FAILED.value,
                            _PS.CANCELLED.value) and not all_terminal) or (
            pipeline_status == _PS.INCOMPLETE.value and all_terminal):
        codes.add(AGGREGATE_STATE_MISMATCH)

    ordered = _ordered(codes, RUN_CODES)
    fcp8_classification = derived.classification if fcp8_state == "BOUND" else None
    return StateProjection(
        outcome=outcome_for(nodes, ordered, pipeline_status, fcp8_classification, work_success),
        run_id=request.run_id, pipeline_status=pipeline_status, aggregate_status=derived.aggregate_status,
        manifest_sha256=summary.manifest_sha256, plan_fingerprint=summary.plan_fingerprint,
        fcp8_classification=fcp8_classification, fcp8_work_success=work_success,
        fcp8_observation_sha256=None if fcp8_classification is None else hashlib.sha256(
            vd.canonical_json(derived).encode("ascii")).hexdigest(),
        started_at_utc=started, ended_at_utc=ended, max_observed_concurrency=concurrency, request_reasons=(),
        codes=ordered, fcp8_codes=(), nodes=nodes,
    )


# ---------------------------------------------------------------------------
# Observation (the only reader)
# ---------------------------------------------------------------------------

def observe_scheduler_state(service, run_id, *, as_of_utc, read_status: bool = True,
                            expected_manifest_sha256=None, expected_plan_fingerprint=None,
                            max_heartbeat_age_seconds: int = MAX_HEARTBEAT_AGE_SECONDS) -> StateProjection:
    """Read `service.result_blueprint(run_id)` once and, when `read_status`,
    `service.status(run_id)` once, derive the FCP-8 evaluations from that
    same summary in memory, and project. Never raises on bad input or a
    failing read; never writes, dispatches, certifies or authorizes."""
    if not fd._is_director_pipeline_id(run_id):
        return _rejected((RUN_ID_INVALID,))
    try:
        summary = service.result_blueprint(run_id)
    except fd.DirectorError as exc:
        return _rejected((PROVENANCE_REFUSED if exc.code == "DAG_PROVENANCE_MISMATCH" else READ_FAILED,))
    except Exception:  # noqa: BLE001 - any read failure is UNOBSERVABLE, never success
        return _rejected((READ_FAILED,))
    status, status_failed = None, False
    if read_status:
        try:
            status = service.status(run_id)
        except Exception:  # noqa: BLE001 - an unreadable status only removes what it would prove
            status, status_failed = None, True
    observation = classification = None
    if type(summary) is fd.DirectorDagRunSummary:
        observation = vd.observe_dag_run(_SummaryReader(summary), run_id,
                                         expected_manifest_sha256=expected_manifest_sha256,
                                         expected_plan_fingerprint=expected_plan_fingerprint)
        classification = vr.classify_evidence(observation)
    projection = project_state(StateProjectionRequest(
        run_id=run_id, as_of_utc=as_of_utc, dag_summary=summary, runner_status=status,
        dag_observation=observation, evidence_classification=classification,
        expected_manifest_sha256=expected_manifest_sha256, expected_plan_fingerprint=expected_plan_fingerprint,
        max_heartbeat_age_seconds=max_heartbeat_age_seconds,
    ))
    if status_failed and not projection.request_reasons and STATUS_NOT_OBSERVED in projection.codes:
        projection = dataclasses.replace(projection, codes=_ordered(projection.codes + (STATUS_READ_FAILED,),
                                                                    RUN_CODES))
    return projection
