"""FCP-8B-01: MULTI-WORKER (DAG) validation evidence adapter - a pure,
read-only, fail-closed observation of ONE Director DAG run, built only from
the native `DirectorDagRunSummary` / `DirectorDagWorkerSummary` projection.

Source (the only authority of the observation)
----------------------------------------------
`observe_dag_run(service, run_id)` calls exactly
`service.result_blueprint(run_id)` once and nothing else. It never opens
`pipeline.json`, `dag_plan.json`, `manifest.json` or any worker/attempt
`result.json`/`metadata.json` itself, never trusts provider text, and never
calls `submit_blueprint`, `run_blueprint`, `run`, `recover`, `status`,
`PipelineRunner`, Git, a shell, a socket or a file. It creates, schedules,
approves, retries, resumes and dispatches nothing. A read that raises, or
returns anything other than the exact `DirectorDagRunSummary`, makes the whole
observation UNOBSERVABLE.

Schema / provenance (any violation: INVALID_PROJECTION, no worker projected)
---------------------------------------------------------------------------
`run_id == pipeline_id ==` the requested Director pipeline id; a non-empty
`blueprint_pipeline_id`; `manifest_sha256` and `plan_fingerprint` present as
SHA-256 hex digests (and equal to the caller's expected digests when given -
otherwise STALE_PROVENANCE); `workers` an exact tuple of
`DirectorDagWorkerSummary` with `MIN_BLUEPRINT_NODES..MAX_BLUEPRINT_NODES`
entries (2..64) and bounded worker ids, no duplicate worker id, every
`depends_on` a bounded, duplicate-free tuple of OTHER workers of this run, the
dependency graph acyclic; `aggregate_status` a Director aggregate value
consistent with Runner's verbatim `pipeline_status`. Cardinality is checked
before any per-worker iteration and every variable-length field is capped, so
memory stays bounded by the 64-worker limit.

Per-worker reading (native order kept; Runner verdicts never re-decided)
-----------------------------------------------------------------------
`runner_proven_success` and `unproven_reasons` are read verbatim. They are
never upgraded: an internally inconsistent proof (`runner_proven_success`
disagreeing with `unproven_reasons`, an unknown or duplicate reason, a proof
or a reason contradicting the projected fields it summarizes) only turns the
worker UNPROVEN and the facts that read it UNKNOWN. Per worker, onto the
FCP-8A-01 `ValidationFacts`:

* `work_success`: worker_state SUCCESS with work_status SUCCESS sourced from
  `RUNNER_ACCEPTANCE`, no provider condition, worker record PRESENT and a
  recorded `checkpoint_commit` (the DAG projection does not carry the
  checkpoint policy, so a missing commit cannot be shown to be allowed:
  UNKNOWN). Terminal non-success states are False; in-progress, quota waits
  and unrecognized states are UNKNOWN.
* `safety_clean` / `acceptance_proven`: not projected by the DAG summary -
  always UNKNOWN, never inferred.
* `scope_clean`: unauthorized paths present -> False; an empty list counts
  only when the worker record is PRESENT and names the attempt evidence
  directory the Director reads the change metadata from. Independent of
  evidence completeness.
* `evidence_complete`: the Director's value, verbatim, when it agrees with
  `evidence_health`.
* `provenance_bound`: worker record PRESENT -> True, MISMATCH (a stale or
  foreign `result.json`) -> False, MISSING -> UNKNOWN.

Two independent per-worker questions follow: `work_proven` (technical
success: work_success and scope_clean True) and `evidence_certain`
(evidence_complete and provenance_bound True AND the Director's own
`runner_proven_success`, with no inconsistency). Because safety and
acceptance are not projected, a worker's `assessment` is never
READY_FOR_HUMAN_REVIEW; the DAG-level answer is `evidence_sufficient`.

DAG classification (`DAG_CLASSIFICATIONS`)
------------------------------------------
UNOBSERVABLE / INVALID_PROJECTION / UNKNOWN_STATUS / NOT_SUCCESSFUL /
NOT_TERMINAL, then - for a native SUCCESS pipeline - ALL_WORKERS_PROVEN only
when every worker is both `work_proven` and `evidence_certain` and the
aggregate is consistent; TECHNICAL_SUCCESS_EVIDENCE_INSUFFICIENT when every
worker is `work_proven` but at least one is not `evidence_certain` (e.g. an
aggregate SUCCESS carrying a single UNPROVEN worker); otherwise
SUCCESS_REPORTED_EVIDENCE_INSUFFICIENT. `evidence_sufficient` is True only
for ALL_WORKERS_PROVEN.

Output (`DagRunObservation`, schema `fcp8b01-dag-validation-observation-v1`)
holds only enumerated codes, booleans, counts and positional indices - no
run/worker ids, digests, paths, provider text or Work Order text - and fixes
every authority flag to False.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Optional

try:
    from scripts.ai import fabric_director as fd
    from scripts.ai import fabric_validation_contract as vc
except ImportError:  # pragma: no cover - direct script execution
    import fabric_director as fd  # type: ignore[no-redef]
    import fabric_validation_contract as vc  # type: ignore[no-redef]

SCHEMA = "fcp8b01-dag-validation-observation-v1"
SCHEMA_VERSION = 1
OBSERVATION_MARKER = "FCP8B01_DAG_OBSERVATION_NOT_CERTIFIED_NOT_AUTHORIZED"
UNRECOGNIZED = "UNRECOGNIZED"

MIN_WORKERS = fd.blueprints.MIN_BLUEPRINT_NODES
MAX_WORKERS = fd.blueprints.MAX_BLUEPRINT_NODES
MAX_ID_LENGTH = 128
MAX_UNAUTHORIZED_PATHS = 4096

_WS = fd.pipeline.WorkerState
_PS = fd.pipeline.PipelineStatus
WORKER_STATES = frozenset(s.value for s in _WS)
WORK_STATUSES = frozenset(s.value for s in fd.providers.WorkStatus)
WORK_STATUS_SOURCES = fd.claude_runner.WORK_STATUS_SOURCES
PIPELINE_STATUSES = frozenset(s.value for s in _PS)
AGGREGATE_STATUSES = PIPELINE_STATUSES | {fd.DAG_AGGREGATE_UNVERIFIED, fd.DAG_AGGREGATE_UNKNOWN}
PROVIDER_CONDITIONS = frozenset({"PROVIDER_AUTH_BLOCKED", "PROVIDER_QUOTA_EXHAUSTED"})
WORKER_RECORDS = (fd.WORKER_RECORD_PRESENT, fd.WORKER_RECORD_MISSING, fd.WORKER_RECORD_MISMATCH)
EVIDENCE_HEALTHS = (fd.EVIDENCE_HEALTH_COMPLETE, fd.EVIDENCE_HEALTH_INCOMPLETE, fd.EVIDENCE_HEALTH_UNKNOWN)
_HEALTH_OF = {True: fd.EVIDENCE_HEALTH_COMPLETE, False: fd.EVIDENCE_HEALTH_INCOMPLETE,
              None: fd.EVIDENCE_HEALTH_UNKNOWN}

# Every reason `fabric_director._dag_unproven_reasons` can emit, in its order.
UNPROVEN_REASONS = (
    "WORKER_STATE_NOT_SUCCESS", "WORK_STATUS_NOT_SUCCESS", "WORKER_RECORD_MISSING", "WORKER_RECORD_MISMATCH",
    "EVIDENCE_INCOMPLETE", "EVIDENCE_UNKNOWN", "UNAUTHORIZED_PATHS",
)
PIPELINE_STATUS_UNKNOWN_REASON = "PIPELINE_STATUS_UNKNOWN"

_NOT_SUCCESS_TERMINAL_STATES = frozenset({
    _WS.FAILED.value, _WS.PARTIAL.value, _WS.BLOCKED.value, _WS.CANCELLED.value, _WS.INTERRUPTED.value,
    _WS.BLOCKED_PROVIDER_AUTH.value,
})
_NOT_TERMINAL_STATES = frozenset({
    _WS.QUEUED.value, _WS.WAITING_DEPENDENCY.value, _WS.READY.value, _WS.RUNNING.value, _WS.RETRY_WAIT.value,
    _WS.WAITING_PROVIDER_QUOTA.value,
})
_NOT_SUCCESS_PIPELINE = frozenset({_PS.FAILED.value, _PS.PARTIAL.value, _PS.BLOCKED.value, _PS.CANCELLED.value})
_NOT_TERMINAL_PIPELINE = frozenset({_PS.RUNNING.value, _PS.DRAINING.value, _PS.INCOMPLETE.value})

_SHA256_HEX = re.compile(r"[0-9a-f]{64}")

# Checkpoint observation values.
CHECKPOINT_RECORDED = "RECORDED"
CHECKPOINT_ABSENT = "ABSENT"
CHECKPOINT_UNKNOWN = "UNKNOWN"
CHECKPOINT_STATES = (CHECKPOINT_RECORDED, CHECKPOINT_ABSENT, CHECKPOINT_UNKNOWN)

# DAG classifications.
UNOBSERVABLE = "UNOBSERVABLE"
INVALID_PROJECTION = "INVALID_PROJECTION"
UNKNOWN_STATUS = "UNKNOWN_STATUS"
NOT_SUCCESSFUL = "NOT_SUCCESSFUL"
NOT_TERMINAL = "NOT_TERMINAL"
SUCCESS_REPORTED_EVIDENCE_INSUFFICIENT = "SUCCESS_REPORTED_EVIDENCE_INSUFFICIENT"
TECHNICAL_SUCCESS_EVIDENCE_INSUFFICIENT = "TECHNICAL_SUCCESS_EVIDENCE_INSUFFICIENT"
ALL_WORKERS_PROVEN = "ALL_WORKERS_PROVEN"
DAG_CLASSIFICATIONS = (
    UNOBSERVABLE, INVALID_PROJECTION, UNKNOWN_STATUS, NOT_SUCCESSFUL, NOT_TERMINAL,
    SUCCESS_REPORTED_EVIDENCE_INSUFFICIENT, TECHNICAL_SUCCESS_EVIDENCE_INSUFFICIENT, ALL_WORKERS_PROVEN,
)

# DAG-level observation codes, in their fixed canonical order.
DAG_CODES = (
    "RUN_ID_INVALID", "EXPECTED_DIGEST_INVALID",
    "READ_FAILED", "PROVENANCE_REFUSED", "SUMMARY_NOT_TYPED",
    "RUN_ID_MISMATCH", "PIPELINE_ID_MISMATCH", "BLUEPRINT_PIPELINE_ID_MISSING",
    "MANIFEST_DIGEST_MISSING", "PLAN_FINGERPRINT_MISSING", "STALE_PROVENANCE",
    "WORKERS_NOT_TUPLE", "TOO_FEW_WORKERS", "TOO_MANY_WORKERS", "WORKER_NOT_TYPED", "WORKER_ID_INVALID",
    "DUPLICATE_WORKER_ID", "DEPENDS_ON_MALFORMED", "DEPENDS_ON_UNKNOWN_WORKER", "DEPENDS_ON_SELF",
    "DEPENDS_ON_DUPLICATE", "DEPENDENCY_CYCLE",
    "AGGREGATE_STATUS_MALFORMED", "AGGREGATE_STATUS_MISMATCH", "AGGREGATE_REASONS_MALFORMED",
    "PIPELINE_STATUS_UNKNOWN", "AGGREGATE_UNKNOWN",
    "AGGREGATE_SUCCESS_WITH_UNPROVEN_WORKER", "AGGREGATE_UNVERIFIED_WITH_ALL_PROVEN",
    "AGGREGATE_REASONS_MISMATCH",
    "PIPELINE_NOT_SUCCESSFUL", "PIPELINE_NOT_TERMINAL",
    "WORKER_NOT_SUCCESSFUL", "WORKER_NOT_TERMINAL", "WORKER_UNPROVEN", "WORKER_EVIDENCE_UNCERTAIN",
    "WORKER_INCONSISTENT",
)

# Worker-level observation codes, in their fixed canonical order.
WORKER_CODES = (
    "FIELD_MALFORMED", "PROOF_MALFORMED", "PROOF_REASONS_DISAGREE", "PROOF_CONTRADICTS_FIELDS",
    "REASON_CONTRADICTS_FIELDS", "EVIDENCE_HEALTH_MISMATCH",
    "WORKER_STATE_UNKNOWN", "WORKER_NOT_TERMINAL", "WORKER_NOT_SUCCESSFUL",
    "WORK_STATUS_NOT_CERTIFIED_SUCCESS", "WORK_STATUS_SOURCE_MISSING", "WORK_STATUS_PROVIDER_ONLY",
    "WORK_STATUS_SOURCE_UNRECOGNIZED", "PROVIDER_CONDITION_PRESENT", "CHECKPOINT_UNVERIFIABLE",
    "WORKER_RECORD_MISSING", "WORKER_RECORD_STALE_OR_FOREIGN",
    "UNAUTHORIZED_PATHS_PRESENT", "SCOPE_UNOBSERVED",
    "EVIDENCE_INCOMPLETE", "EVIDENCE_COMPLETE_UNKNOWN",
    "SAFETY_NOT_PROJECTED", "ACCEPTANCE_NOT_PROJECTED",
    "RUNNER_UNPROVEN",
)


def _ordered(codes, vocabulary) -> tuple:
    return tuple(sorted(set(codes), key=vocabulary.index))


def _enum(value, vocabulary) -> Optional[str]:
    if value is None:
        return None
    return value if type(value) is str and value in vocabulary else UNRECOGNIZED


def _is_id(value) -> bool:
    return type(value) is str and 0 < len(value) <= MAX_ID_LENGTH


def _is_digest(value) -> bool:
    return type(value) is str and _SHA256_HEX.fullmatch(value) is not None


def _is_opt_str(value) -> bool:
    return value is None or type(value) is str


def _is_codes(value, vocabulary, limit: int) -> bool:
    return (type(value) is tuple and len(value) <= limit and all(type(c) is str and c in vocabulary for c in value)
            and len(set(value)) == len(value))


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DagWorkerObservation:
    """One worker, in native plan order. `index`/`depends_on` are positions in
    that order (never ids). `assessment` is exactly `assess_validation(facts)`.
    `runner_proven_success` is the Director's value verbatim, or None when
    malformed; `unproven_reasons` are the Director's codes when well formed."""
    index: int
    depends_on: tuple
    facts: vc.ValidationFacts
    assessment: vc.ValidationAssessment
    work_proven: bool
    evidence_certain: bool
    runner_proven_success: Optional[bool]
    unproven_reasons: tuple
    observation_codes: tuple
    worker_state: Optional[str] = None
    work_status: Optional[str] = None
    work_status_source: Optional[str] = None
    provider_condition: Optional[str] = None
    worker_record: Optional[str] = None
    evidence_health: Optional[str] = None
    checkpoint: str = CHECKPOINT_UNKNOWN

    def __post_init__(self):
        if type(self.index) is not int or not 0 <= self.index < MAX_WORKERS:
            raise ValueError("index out of range")
        if not (type(self.depends_on) is tuple and all(type(i) is int and 0 <= i < MAX_WORKERS and i != self.index
                                                      for i in self.depends_on)):
            raise ValueError("depends_on must be worker indices")
        if type(self.facts) is not vc.ValidationFacts:
            raise ValueError("facts must be ValidationFacts")
        if type(self.assessment) is not vc.ValidationAssessment or self.assessment != vc.assess_validation(self.facts):
            raise ValueError("assessment must be exactly assess_validation(facts)")
        if type(self.work_proven) is not bool or type(self.evidence_certain) is not bool:
            raise ValueError("work_proven/evidence_certain must be bools")
        if self.work_proven != (self.facts.work_success is True and self.facts.scope_clean is True):
            raise ValueError("work_proven must be exactly work_success and scope_clean")
        if self.evidence_certain and not (self.facts.evidence_complete is True and self.facts.provenance_bound is True
                                          and self.runner_proven_success is True):
            raise ValueError("evidence_certain requires complete, bound, Runner-proven evidence")
        if not (self.runner_proven_success is None or type(self.runner_proven_success) is bool):
            raise ValueError("runner_proven_success must be a bool or None")
        if not (_is_codes(self.unproven_reasons, UNPROVEN_REASONS, len(UNPROVEN_REASONS))
                and self.unproven_reasons == _ordered(self.unproven_reasons, UNPROVEN_REASONS)):
            raise ValueError("unproven_reasons must be ordered Director reasons")
        if not (type(self.observation_codes) is tuple
                and all(type(c) is str and c in WORKER_CODES for c in self.observation_codes)
                and self.observation_codes == _ordered(self.observation_codes, WORKER_CODES)):
            raise ValueError("observation_codes must be ordered worker codes")
        if self.checkpoint not in CHECKPOINT_STATES:
            raise ValueError("unknown checkpoint observation")

    def to_dict(self) -> dict:
        return {
            "index": self.index, "depends_on": list(self.depends_on),
            "assessment": vc.ValidationAssessment.to_dict(self.assessment),
            "work_proven": self.work_proven, "evidence_certain": self.evidence_certain,
            "runner_proven_success": self.runner_proven_success, "unproven_reasons": list(self.unproven_reasons),
            "observation_codes": list(self.observation_codes),
            "statuses": {
                "worker_state": self.worker_state, "work_status": self.work_status,
                "work_status_source": self.work_status_source, "provider_condition": self.provider_condition,
                "worker_record": self.worker_record, "evidence_health": self.evidence_health,
                "checkpoint": self.checkpoint,
            },
        }


@dataclass(frozen=True)
class DagRunObservation(vc._NotAuthorized):
    """Advisory observation of one DAG run. `workers` is empty unless the
    projection passed schema/provenance validation. `evidence_sufficient` is
    True only for ALL_WORKERS_PROVEN and is never a permit."""
    classification: str
    all_work_proven: bool
    evidence_sufficient: bool
    workers: tuple
    observation_codes: tuple
    pipeline_status: Optional[str] = None
    aggregate_status: Optional[str] = None

    def __post_init__(self):
        if self.classification not in DAG_CLASSIFICATIONS:
            raise ValueError("unknown DAG classification")
        if not (type(self.workers) is tuple and len(self.workers) <= MAX_WORKERS
                and all(type(w) is DagWorkerObservation for w in self.workers)
                and tuple(w.index for w in self.workers) == tuple(range(len(self.workers)))):
            raise ValueError("workers must be indexed DagWorkerObservations in order")
        if self.classification in (UNOBSERVABLE, INVALID_PROJECTION) and self.workers:
            raise ValueError("an unobservable or invalid projection carries no workers")
        if self.workers and any(i >= len(self.workers) for w in self.workers for i in w.depends_on):
            raise ValueError("depends_on must index workers of this run")
        if type(self.all_work_proven) is not bool or type(self.evidence_sufficient) is not bool:
            raise ValueError("all_work_proven/evidence_sufficient must be bools")
        if self.all_work_proven != (bool(self.workers) and all(w.work_proven for w in self.workers)):
            raise ValueError("all_work_proven must be exactly every worker's work_proven")
        if self.evidence_sufficient != (self.classification == ALL_WORKERS_PROVEN):
            raise ValueError("evidence_sufficient is exactly ALL_WORKERS_PROVEN")
        if self.evidence_sufficient and not (
                self.all_work_proven and all(w.evidence_certain for w in self.workers)
                and self.pipeline_status == _PS.SUCCESS.value and self.aggregate_status == _PS.SUCCESS.value):
            raise ValueError("ALL_WORKERS_PROVEN requires every worker proven under a SUCCESS aggregate")
        if self.classification == TECHNICAL_SUCCESS_EVIDENCE_INSUFFICIENT and not self.all_work_proven:
            raise ValueError("TECHNICAL_SUCCESS_EVIDENCE_INSUFFICIENT requires every worker work_proven")
        if not (type(self.observation_codes) is tuple
                and all(type(c) is str and c in DAG_CODES for c in self.observation_codes)
                and self.observation_codes == _ordered(self.observation_codes, DAG_CODES)):
            raise ValueError("observation_codes must be ordered DAG codes")

    @property
    def worker_count(self) -> int:
        return len(self.workers)

    @property
    def runner_proven_count(self) -> int:
        return sum(1 for w in self.workers if w.runner_proven_success is True)

    @property
    def evidence_certain_count(self) -> int:
        return sum(1 for w in self.workers if w.evidence_certain)

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA, "schema_version": SCHEMA_VERSION, "classification": self.classification,
            "all_work_proven": self.all_work_proven, "evidence_sufficient": self.evidence_sufficient,
            "pipeline_status": self.pipeline_status, "aggregate_status": self.aggregate_status,
            "worker_count": self.worker_count, "runner_proven_count": self.runner_proven_count,
            "evidence_certain_count": self.evidence_certain_count,
            "observation_codes": list(self.observation_codes),
            "workers": [DagWorkerObservation.to_dict(w) for w in self.workers],
            "marker": OBSERVATION_MARKER, "certified": False, "authorizes_action": False,
            "execution_allowed": False, "merging_allowed": False, "promotion_allowed": False,
            "auto_retry_allowed": False, "resume_allowed": False,
        }


def canonical_json(observation: DagRunObservation) -> str:
    """Stable, sorted, compact serialization of the exact contract type."""
    if type(observation) is not DagRunObservation:
        raise TypeError("canonical_json accepts only a DagRunObservation")
    return json.dumps(DagRunObservation.to_dict(observation), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True)


def _refused(classification: str, codes) -> DagRunObservation:
    return DagRunObservation(classification=classification, all_work_proven=False, evidence_sufficient=False,
                             workers=(), observation_codes=_ordered(codes, DAG_CODES))


# ---------------------------------------------------------------------------
# Observation
# ---------------------------------------------------------------------------

def observe_dag_run(service, run_id, *, expected_manifest_sha256=None,
                    expected_plan_fingerprint=None) -> DagRunObservation:
    """Read `result_blueprint(run_id)` once and observe it. The optional
    expected digests (e.g. from the submission handle the caller already
    holds) detect a stale projection. Never raises on bad input or a failing
    read; never writes, dispatches, certifies or authorizes."""
    if not fd._is_director_pipeline_id(run_id):
        return _refused(UNOBSERVABLE, ("RUN_ID_INVALID",))
    if any(d is not None and not _is_digest(d) for d in (expected_manifest_sha256, expected_plan_fingerprint)):
        return _refused(UNOBSERVABLE, ("EXPECTED_DIGEST_INVALID",))
    try:
        summary = service.result_blueprint(run_id)
    except fd.DirectorError as exc:
        return _refused(UNOBSERVABLE, ("PROVENANCE_REFUSED" if exc.code == "DAG_PROVENANCE_MISMATCH"
                                       else "READ_FAILED",))
    except Exception:  # noqa: BLE001 - any read failure is UNOBSERVABLE, never success
        return _refused(UNOBSERVABLE, ("READ_FAILED",))
    if type(summary) is not fd.DirectorDagRunSummary:
        return _refused(UNOBSERVABLE, ("SUMMARY_NOT_TYPED",))
    errors = _schema_errors(run_id, summary, expected_manifest_sha256, expected_plan_fingerprint)
    if errors:
        return _refused(INVALID_PROJECTION, errors)
    return _observe(summary)


def _schema_errors(run_id: str, summary, expected_manifest, expected_plan) -> list:
    errors = []
    if summary.run_id != run_id:
        errors.append("RUN_ID_MISMATCH")
    if summary.pipeline_id != run_id:
        errors.append("PIPELINE_ID_MISMATCH")
    if not _is_id(summary.blueprint_pipeline_id):
        errors.append("BLUEPRINT_PIPELINE_ID_MISSING")
    if not _is_digest(summary.manifest_sha256):
        errors.append("MANIFEST_DIGEST_MISSING")
    elif expected_manifest is not None and summary.manifest_sha256 != expected_manifest:
        errors.append("STALE_PROVENANCE")
    if not _is_digest(summary.plan_fingerprint):
        errors.append("PLAN_FINGERPRINT_MISSING")
    elif expected_plan is not None and summary.plan_fingerprint != expected_plan:
        errors.append("STALE_PROVENANCE")
    if not _is_opt_str(summary.pipeline_status):
        errors.append("AGGREGATE_STATUS_MALFORMED")
    aggregate = summary.aggregate_status
    if type(aggregate) is not str or aggregate not in AGGREGATE_STATUSES:
        errors.append("AGGREGATE_STATUS_MALFORMED")
    elif type(summary.pipeline_status) is str or summary.pipeline_status is None:
        status = summary.pipeline_status
        if status in PIPELINE_STATUSES:
            allowed = {status, fd.DAG_AGGREGATE_UNVERIFIED} if status == _PS.SUCCESS.value else {status}
        else:
            allowed = {fd.DAG_AGGREGATE_UNKNOWN}
        if aggregate not in allowed:
            errors.append("AGGREGATE_STATUS_MISMATCH")

    workers = summary.workers
    if type(workers) is not tuple:
        errors.append("WORKERS_NOT_TUPLE")
        return errors
    # Cardinality first: nothing below iterates more than MAX_WORKERS entries.
    if len(workers) < MIN_WORKERS:
        errors.append("TOO_FEW_WORKERS")
    if len(workers) > MAX_WORKERS:
        errors.append("TOO_MANY_WORKERS")
        return errors
    if any(type(w) is not fd.DirectorDagWorkerSummary for w in workers):
        errors.append("WORKER_NOT_TYPED")
        return errors
    ids = [w.worker_id for w in workers]
    if not all(_is_id(i) for i in ids):
        errors.append("WORKER_ID_INVALID")
        return errors
    if len(set(ids)) != len(ids):
        errors.append("DUPLICATE_WORKER_ID")
        return errors
    known = set(ids)
    for w in workers:
        deps = w.depends_on
        if not (type(deps) is tuple and len(deps) < MAX_WORKERS and all(type(d) is str for d in deps)):
            errors.append("DEPENDS_ON_MALFORMED")
            continue
        if len(set(deps)) != len(deps):
            errors.append("DEPENDS_ON_DUPLICATE")
        if w.worker_id in deps:
            errors.append("DEPENDS_ON_SELF")
        if any(d not in known for d in deps):
            errors.append("DEPENDS_ON_UNKNOWN_WORKER")
    if not errors and _has_cycle(workers):
        errors.append("DEPENDENCY_CYCLE")

    reasons = summary.aggregate_reasons
    limit = len(workers) * len(UNPROVEN_REASONS) + 1
    if not (type(reasons) is tuple and len(reasons) <= limit and all(type(r) is str for r in reasons)
            and len(set(reasons)) == len(reasons)):
        errors.append("AGGREGATE_REASONS_MALFORMED")
    else:
        for reason in reasons:
            if reason == PIPELINE_STATUS_UNKNOWN_REASON:
                continue
            worker_id, sep, code = reason.rpartition(":")
            if not sep or worker_id not in known or code not in UNPROVEN_REASONS:
                errors.append("AGGREGATE_REASONS_MALFORMED")
                break
    return errors


def _has_cycle(workers: tuple) -> bool:
    pending = {w.worker_id: set(w.depends_on) for w in workers}
    while pending:
        ready = [wid for wid, deps in pending.items() if not deps]
        if not ready:
            return True
        for wid in ready:
            del pending[wid]
        for deps in pending.values():
            deps.difference_update(ready)
    return False


def _observe(summary) -> DagRunObservation:
    workers = summary.workers
    position = {w.worker_id: i for i, w in enumerate(workers)}
    observed = tuple(_observe_worker(i, w, position) for i, w in enumerate(workers))
    codes = []

    pipeline_status = summary.pipeline_status
    aggregate = summary.aggregate_status
    all_runner_proven = all(w.runner_proven_success is True for w in observed)
    if aggregate == _PS.SUCCESS.value and not all_runner_proven:
        codes.append("AGGREGATE_SUCCESS_WITH_UNPROVEN_WORKER")
    aggregate_consistent = True
    if aggregate == fd.DAG_AGGREGATE_UNVERIFIED and all_runner_proven:
        codes.append("AGGREGATE_UNVERIFIED_WITH_ALL_PROVEN")
        aggregate_consistent = False
    expected_reasons = {f"{w.worker_id}:{r}" for w in workers
                        if _is_codes(w.unproven_reasons, UNPROVEN_REASONS, len(UNPROVEN_REASONS))
                        for r in w.unproven_reasons}
    status_reason_expected = pipeline_status not in PIPELINE_STATUSES
    if expected_reasons != set(summary.aggregate_reasons) - {PIPELINE_STATUS_UNKNOWN_REASON} \
            or status_reason_expected != (PIPELINE_STATUS_UNKNOWN_REASON in summary.aggregate_reasons):
        codes.append("AGGREGATE_REASONS_MISMATCH")
        aggregate_consistent = False

    for w in observed:
        if w.facts.work_success is False:
            codes.append("WORKER_NOT_SUCCESSFUL")
        if "WORKER_NOT_TERMINAL" in w.observation_codes:
            codes.append("WORKER_NOT_TERMINAL")
        if w.runner_proven_success is not True:
            codes.append("WORKER_UNPROVEN")
        if not w.evidence_certain:
            codes.append("WORKER_EVIDENCE_UNCERTAIN")
        if any(c in w.observation_codes for c in _INCONSISTENCY_CODES):
            codes.append("WORKER_INCONSISTENT")

    all_work = all(w.work_proven for w in observed)
    all_evidence = all(w.evidence_certain for w in observed)
    if pipeline_status not in PIPELINE_STATUSES:
        codes.append("PIPELINE_STATUS_UNKNOWN")
    if aggregate == fd.DAG_AGGREGATE_UNKNOWN:
        codes.append("AGGREGATE_UNKNOWN")

    if pipeline_status not in PIPELINE_STATUSES or aggregate == fd.DAG_AGGREGATE_UNKNOWN:
        classification = UNKNOWN_STATUS
    elif pipeline_status in _NOT_SUCCESS_PIPELINE or any(w.facts.work_success is False for w in observed):
        if pipeline_status in _NOT_SUCCESS_PIPELINE:
            codes.append("PIPELINE_NOT_SUCCESSFUL")
        classification = NOT_SUCCESSFUL
    elif pipeline_status in _NOT_TERMINAL_PIPELINE:
        codes.append("PIPELINE_NOT_TERMINAL")
        classification = NOT_TERMINAL
    elif all_work and all_evidence and aggregate_consistent and aggregate == _PS.SUCCESS.value:
        classification = ALL_WORKERS_PROVEN
    elif all_work:
        classification = TECHNICAL_SUCCESS_EVIDENCE_INSUFFICIENT
    else:
        classification = SUCCESS_REPORTED_EVIDENCE_INSUFFICIENT

    return DagRunObservation(
        classification=classification, all_work_proven=all_work,
        evidence_sufficient=classification == ALL_WORKERS_PROVEN, workers=observed,
        observation_codes=_ordered(codes, DAG_CODES), pipeline_status=_enum(pipeline_status, PIPELINE_STATUSES),
        aggregate_status=aggregate,
    )


_INCONSISTENCY_CODES = ("FIELD_MALFORMED", "PROOF_MALFORMED", "PROOF_REASONS_DISAGREE", "PROOF_CONTRADICTS_FIELDS",
                        "REASON_CONTRADICTS_FIELDS", "EVIDENCE_HEALTH_MISMATCH")

# reason -> predicate over (worker_state, work_status, record, health, unauthorized) that must hold for it.
_REASON_HOLDS = {
    "WORKER_STATE_NOT_SUCCESS": lambda f: f[0] != _WS.SUCCESS.value,
    "WORK_STATUS_NOT_SUCCESS": lambda f: f[1] != "SUCCESS",
    "WORKER_RECORD_MISSING": lambda f: f[2] == fd.WORKER_RECORD_MISSING,
    "WORKER_RECORD_MISMATCH": lambda f: f[2] == fd.WORKER_RECORD_MISMATCH,
    "EVIDENCE_INCOMPLETE": lambda f: f[3] == fd.EVIDENCE_HEALTH_INCOMPLETE,
    "EVIDENCE_UNKNOWN": lambda f: f[3] == fd.EVIDENCE_HEALTH_UNKNOWN,
    "UNAUTHORIZED_PATHS": lambda f: bool(f[4]),
}


def _observe_worker(index: int, w, position: dict) -> DagWorkerObservation:
    codes = ["SAFETY_NOT_PROJECTED", "ACCEPTANCE_NOT_PROJECTED"]
    fields_ok = all(_is_opt_str(v) for v in (w.worker_state, w.work_status, w.work_status_source,
                                               w.provider_condition, w.checkpoint_commit))
    record = w.worker_record if w.worker_record in WORKER_RECORDS else None
    health = w.evidence_health if w.evidence_health in EVIDENCE_HEALTHS else None
    unauthorized = w.unauthorized_changed_paths
    paths_ok = (type(unauthorized) is tuple and len(unauthorized) <= MAX_UNAUTHORIZED_PATHS
                and all(type(p) is str for p in unauthorized))
    if not (fields_ok and paths_ok and record and health):
        codes.append("FIELD_MALFORMED")
    ec_ok = w.evidence_complete is None or type(w.evidence_complete) is bool
    if not ec_ok:
        codes.append("FIELD_MALFORMED")
    elif health is not None and _HEALTH_OF[w.evidence_complete] != health:
        codes.append("EVIDENCE_HEALTH_MISMATCH")
        ec_ok = False

    # The Director's own proof, verbatim; checked only for contradictions.
    proven = w.runner_proven_success if type(w.runner_proven_success) is bool else None
    reasons_ok = _is_codes(w.unproven_reasons, UNPROVEN_REASONS, len(UNPROVEN_REASONS))
    reasons = _ordered(w.unproven_reasons, UNPROVEN_REASONS) if reasons_ok else ()
    proof_ok = proven is not None and reasons_ok
    if not proof_ok:
        codes.append("PROOF_MALFORMED")
    elif proven != (not reasons):
        codes.append("PROOF_REASONS_DISAGREE")
        proof_ok = False
    view = (w.worker_state, w.work_status, record, health, unauthorized if paths_ok else ("<malformed>",))
    if proof_ok and fields_ok and record and health:
        if proven and not all(not _REASON_HOLDS[r](view) for r in UNPROVEN_REASONS):
            codes.append("PROOF_CONTRADICTS_FIELDS")
            proof_ok = False
        elif any(not _REASON_HOLDS[r](view) for r in reasons):
            codes.append("REASON_CONTRADICTS_FIELDS")
            proof_ok = False
    if proven is not True:
        codes.append("RUNNER_UNPROVEN")

    worker_state = w.worker_state if fields_ok else None
    # work_success
    work_success = None
    if not fields_ok:
        pass
    elif worker_state in _NOT_SUCCESS_TERMINAL_STATES:
        work_success = False
        codes.append("WORKER_NOT_SUCCESSFUL")
    elif worker_state in _NOT_TERMINAL_STATES:
        codes.append("WORKER_NOT_TERMINAL")
    elif worker_state != _WS.SUCCESS.value:
        codes.append("WORKER_STATE_UNKNOWN")
    elif w.work_status != "SUCCESS":
        codes.append("WORK_STATUS_NOT_CERTIFIED_SUCCESS")
    elif w.work_status_source is None:
        codes.append("WORK_STATUS_SOURCE_MISSING")
    elif w.work_status_source == fd.claude_runner.WORK_STATUS_SOURCE_PROVIDER:
        codes.append("WORK_STATUS_PROVIDER_ONLY")
    elif w.work_status_source != fd.claude_runner.WORK_STATUS_SOURCE_RUNNER_ACCEPTANCE:
        codes.append("WORK_STATUS_SOURCE_UNRECOGNIZED")
    elif w.provider_condition is not None:
        codes.append("PROVIDER_CONDITION_PRESENT")
    elif not w.checkpoint_commit:
        codes.append("CHECKPOINT_UNVERIFIABLE")
    elif record == fd.WORKER_RECORD_PRESENT and not any(c in codes for c in _INCONSISTENCY_CODES):
        work_success = True

    # provenance_bound
    provenance_bound = None
    if record == fd.WORKER_RECORD_PRESENT:
        provenance_bound = True
    elif record == fd.WORKER_RECORD_MISMATCH:
        provenance_bound = False
        codes.append("WORKER_RECORD_STALE_OR_FOREIGN")
    elif record == fd.WORKER_RECORD_MISSING:
        codes.append("WORKER_RECORD_MISSING")

    # scope_clean
    scope_clean = None
    if not paths_ok or unauthorized:
        scope_clean = False
        codes.append("UNAUTHORIZED_PATHS_PRESENT")
    elif record == fd.WORKER_RECORD_PRESENT and type(w.evidence_dir) is str and w.evidence_dir:
        scope_clean = True
    else:
        codes.append("SCOPE_UNOBSERVED")

    # evidence_complete - verbatim when it agrees with evidence_health.
    evidence_complete = w.evidence_complete if ec_ok and health is not None else None
    if evidence_complete is None:
        codes.append("EVIDENCE_COMPLETE_UNKNOWN")
    elif evidence_complete is False:
        codes.append("EVIDENCE_INCOMPLETE")

    if not _is_opt_str(w.checkpoint_commit):
        checkpoint = CHECKPOINT_UNKNOWN
    else:
        checkpoint = CHECKPOINT_RECORDED if w.checkpoint_commit else CHECKPOINT_ABSENT

    facts = vc.ValidationFacts(
        work_success=work_success, safety_clean=None, scope_clean=scope_clean,
        evidence_complete=evidence_complete, provenance_bound=provenance_bound, acceptance_proven=None,
    )
    evidence_certain = (evidence_complete is True and provenance_bound is True and proven is True and proof_ok
                        and not any(c in codes for c in _INCONSISTENCY_CODES))
    return DagWorkerObservation(
        index=index, depends_on=tuple(position[d] for d in w.depends_on), facts=facts,
        assessment=vc.assess_validation(facts),
        work_proven=work_success is True and scope_clean is True, evidence_certain=evidence_certain,
        runner_proven_success=proven, unproven_reasons=reasons,
        observation_codes=_ordered(codes, WORKER_CODES),
        worker_state=_enum(w.worker_state, WORKER_STATES) if fields_ok else None,
        work_status=_enum(w.work_status, WORK_STATUSES) if fields_ok else None,
        work_status_source=_enum(w.work_status_source, WORK_STATUS_SOURCES) if fields_ok else None,
        provider_condition=_enum(w.provider_condition, PROVIDER_CONDITIONS) if fields_ok else None,
        worker_record=record, evidence_health=health, checkpoint=checkpoint,
    )
