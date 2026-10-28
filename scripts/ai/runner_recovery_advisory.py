"""FCP-6B-01: Recovery Decision Intelligence V1 - pure, read-only,
nonbinding recovery ADVISORY composed over FCP-6A-01 diagnostics.

Answers ONE question: given a precomputed `WorkerDiagnostic` or
`PipelineDiagnostic` (`runner_failure_intelligence`), what kind of follow-up
does the existing Runner evidence suggest, and which component alone can
decide it? It never answers "may I execute now?".

Why this is advice, not recovery machinery
------------------------------------------
* The Runner (`runner_pipeline.PipelineRunner`) and the Director
  (`fabric_director.FabricDirector.recover`) stay the ONLY execution, retry,
  backoff, resume, provider, quota, ownership, safety and recovery
  authorities. Nothing here schedules, retries, resumes, computes a deadline
  or a `resume_from`, submits a Work Order, runs a process or shell, touches
  Git, or opens a file, socket or process: stdlib only, no I/O, no mutable
  global state.
* Input is ONLY the typed FCP-6A-01 diagnostic (exact type; no raw Runner
  dictionaries, no subclasses). Only its bounded vocabulary is read
  (`primary_reason`, `reason_codes`, `native_state`, `native_status`,
  `retry_decision_kind`, `diagnostic_status`, ids, worker order). Native
  codes outside that vocabulary are never echoed.
* Diagnostics are re-checked for internal consistency against the FCP-6A-01
  contract; anything untyped, contradictory or outside the vocabulary is
  DIAGNOSTIC_UNUSABLE with responsibility UNKNOWN (fail-closed).

What an advisory means
----------------------
Informational only. The category is the rule of the first reason in
`ADVISORY_PRECEDENCE` (evidence integrity and conflict, process
uncertainty, safety, auth and interruption outrank checkpoint, acceptance,
preflight, evidence gaps, native outcomes, existing waits and success).
`responsibility` names who alone may decide; `observation` is a bounded,
non-executable review code. Every advisory fixes `certified`,
`authorizes_action`, `auto_retry_allowed`, `execution_allowed`,
`resume_allowed` and `merging_allowed` to False as read-only properties.
`OBSERVE_EXISTING_WAIT` describes a Runner-managed wait, never a licence for
a new attempt; `HISTORICAL_SUCCESS` / `NO_FOLLOWUP_INDICATED` is a past
observation, never certification and never new work.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from scripts.ai import runner_failure_intelligence as fi

SCHEMA_WORKER = "fcp6b01-runner-worker-recovery-advisory-v1"
SCHEMA_PIPELINE = "fcp6b01-runner-pipeline-recovery-advisory-v1"
SCHEMA_VERSION = 1
ADVISORY_MARKER = "FCP6B01_ADVISORY_ONLY_NOT_CERTIFIED_NOT_AUTHORIZED"
UNRECOGNIZED = fi.UNRECOGNIZED

RESPONSIBILITIES = ("RUNNER_NATIVE", "HUMAN_REVIEW", "CORRECT_WORK", "EVIDENCE_REVIEW", "NONE", "UNKNOWN")

# Advisory-only integrity codes (the diagnostic itself cannot be relied on).
DIAGNOSTIC_NOT_TYPED = "DIAGNOSTIC_NOT_TYPED"
DIAGNOSTIC_INCONSISTENT = "DIAGNOSTIC_INCONSISTENT"

# category -> (responsibility, observation). Bounded, non-executable.
CATEGORY_RULES = {
    "DIAGNOSTIC_UNUSABLE": ("UNKNOWN", "REVIEW_DIAGNOSTIC_INTEGRITY"),
    "EVIDENCE_INVALID": ("UNKNOWN", "REVIEW_EVIDENCE_INTEGRITY"),
    "EVIDENCE_CONFLICT": ("UNKNOWN", "REVIEW_EVIDENCE_CONFLICT"),
    "PROCESS_UNRESOLVED": ("HUMAN_REVIEW", "REVIEW_PROCESS_OWNERSHIP"),
    "SAFETY_REFUSED": ("HUMAN_REVIEW", "REVIEW_SAFETY_REFUSAL"),
    "PROVIDER_AUTH_BLOCKED": ("HUMAN_REVIEW", "REVIEW_PROVIDER_CREDENTIALS"),
    "INTERRUPTED": ("HUMAN_REVIEW", "REVIEW_PROCESS_OWNERSHIP"),
    "CHECKPOINT_FAILED": ("HUMAN_REVIEW", "REVIEW_CHECKPOINT_FAILURE"),
    "ACCEPTANCE_FAILED": ("CORRECT_WORK", "REVIEW_WORK_AND_TESTS"),
    "PREFLIGHT_REFUSED": ("HUMAN_REVIEW", "REVIEW_PREFLIGHT_REFUSAL"),
    "EVIDENCE_GAP": ("EVIDENCE_REVIEW", "INVESTIGATE_EVIDENCE"),
    "NATIVE_FAILED": ("HUMAN_REVIEW", "REVIEW_NATIVE_FAILURE"),
    "NATIVE_BLOCKED": ("HUMAN_REVIEW", "REVIEW_NATIVE_BLOCK"),
    "PARTIAL_COMPLETION": ("CORRECT_WORK", "REVIEW_PARTIAL_WORK"),
    "DEPENDENCY_CANCELLED": ("HUMAN_REVIEW", "REVIEW_UPSTREAM_DEPENDENCY"),
    "NATIVE_CANCELLED": ("HUMAN_REVIEW", "REVIEW_NATIVE_CANCELLATION"),
    "EXISTING_PROVIDER_QUOTA_WAIT": ("RUNNER_NATIVE", "OBSERVE_EXISTING_WAIT"),
    "EXISTING_RETRY_WAIT": ("RUNNER_NATIVE", "OBSERVE_EXISTING_WAIT"),
    "EXISTING_RUN_IN_PROGRESS": ("RUNNER_NATIVE", "OBSERVE_EXISTING_RUN"),
    "HISTORICAL_SUCCESS": ("NONE", "NO_FOLLOWUP_INDICATED"),
}

# (reason code, category), highest advisory precedence first. Covers every
# FCP-6A-01 reason code exactly once (pinned by tests) plus the two
# advisory integrity codes.
_REASON_CATEGORY = (
    (DIAGNOSTIC_NOT_TYPED, "DIAGNOSTIC_UNUSABLE"),
    (DIAGNOSTIC_INCONSISTENT, "DIAGNOSTIC_UNUSABLE"),
    ("MALFORMED_EVIDENCE", "EVIDENCE_INVALID"),
    ("IDENTITY_MISMATCH", "EVIDENCE_INVALID"),
    ("DUPLICATE_WORKER_ID", "EVIDENCE_INVALID"),
    ("UNKNOWN_STATE", "EVIDENCE_INVALID"),
    ("RETRY_DECISION_UNRECOGNIZED", "EVIDENCE_INVALID"),
    ("EMPTY_PIPELINE", "EVIDENCE_INVALID"),
    ("AGGREGATE_CONTRADICTION", "EVIDENCE_CONFLICT"),
    ("CONFLICTING_EVIDENCE", "EVIDENCE_CONFLICT"),
    ("PROCESS_TERMINATION_UNRESOLVED", "PROCESS_UNRESOLVED"),
    ("SAFETY_REFUSAL", "SAFETY_REFUSED"),
    ("PROVIDER_AUTH_BLOCKED", "PROVIDER_AUTH_BLOCKED"),
    ("INTERRUPTED_OPERATOR_REVIEW", "INTERRUPTED"),
    ("CHECKPOINT_FAILED", "CHECKPOINT_FAILED"),
    ("ACCEPTANCE_FAILED", "ACCEPTANCE_FAILED"),
    ("PREFLIGHT_REFUSED", "PREFLIGHT_REFUSED"),
    ("EVIDENCE_INCOMPLETE", "EVIDENCE_GAP"),
    ("EVIDENCE_MISSING", "EVIDENCE_GAP"),
    ("MISSING_WORKER_RESULT", "EVIDENCE_GAP"),
    ("EXTRA_WORKER_RESULT", "EVIDENCE_GAP"),
    ("EVIDENCE_UNPROVEN", "EVIDENCE_GAP"),
    ("NATIVE_FAILED", "NATIVE_FAILED"),
    ("NATIVE_BLOCKED", "NATIVE_BLOCKED"),
    ("PARTIAL_COMPLETION", "PARTIAL_COMPLETION"),
    ("DEPENDENCY_CANCELLED", "DEPENDENCY_CANCELLED"),
    ("NATIVE_CANCELLED", "NATIVE_CANCELLED"),
    ("PROVIDER_QUOTA_WAIT", "EXISTING_PROVIDER_QUOTA_WAIT"),
    ("TRANSIENT_RETRY_WAIT", "EXISTING_RETRY_WAIT"),
    ("NOT_TERMINAL", "EXISTING_RUN_IN_PROGRESS"),
    ("SUCCESS_CONSISTENT", "HISTORICAL_SUCCESS"),
)
ADVISORY_PRECEDENCE = tuple(code for code, _ in _REASON_CATEGORY)
_CATEGORY_OF = dict(_REASON_CATEGORY)
_RANK = {code: i for i, code in enumerate(ADVISORY_PRECEDENCE)}
_SOURCE_VOCAB = frozenset(fi.REASON_PRECEDENCE)

# Native worker state -> FCP-6A-01 codes of which at least one must be present.
_STATE_REQUIRES = {
    "FAILED": {"NATIVE_FAILED"}, "BLOCKED": {"NATIVE_BLOCKED"}, "PARTIAL": {"PARTIAL_COMPLETION"},
    "CANCELLED": {"DEPENDENCY_CANCELLED", "NATIVE_CANCELLED"}, "INTERRUPTED": {"INTERRUPTED_OPERATOR_REVIEW"},
    "BLOCKED_PROVIDER_AUTH": {"PROVIDER_AUTH_BLOCKED"}, "WAITING_PROVIDER_QUOTA": {"PROVIDER_QUOTA_WAIT"},
    "RETRY_WAIT": {"TRANSIENT_RETRY_WAIT"}, "QUEUED": {"NOT_TERMINAL"}, "WAITING_DEPENDENCY": {"NOT_TERMINAL"},
    "READY": {"NOT_TERMINAL"}, "RUNNING": {"NOT_TERMINAL"},
}
# Native retry decision kind -> FCP-6A-01 code it always implies.
_KIND_REQUIRES = {"RETRY": "TRANSIENT_RETRY_WAIT", "WAIT": "PROVIDER_QUOTA_WAIT",
                  UNRECOGNIZED: "RETRY_DECISION_UNRECOGNIZED"}
_RETRY_KINDS = fi.RETRY_DECISION_KINDS | {fi.RETRY_KIND_ABSENT, UNRECOGNIZED}
_DIAGNOSTIC_STATUSES = fi.PIPELINE_STATUSES | {fi.DIAGNOSTIC_UNKNOWN, fi.DIAGNOSTIC_UNVERIFIED}


def _ordered(codes) -> tuple:
    codes = set(codes)
    if codes != {"SUCCESS_CONSISTENT"}:
        codes.discard("SUCCESS_CONSISTENT")  # success is never reported beside anything else
    return tuple(sorted(codes, key=_RANK.__getitem__))


def _bounded(value, vocabulary) -> Optional[str]:
    if value is None:
        return None
    return value if isinstance(value, str) and value in vocabulary else UNRECOGNIZED


def _valid_source_codes(codes, primary) -> bool:
    """FCP-6A-01 contract: a non-empty tuple of known codes, unique, in
    `fi.REASON_PRECEDENCE` order, headed by `primary_reason`."""
    return (
        isinstance(codes, tuple) and bool(codes)
        and all(isinstance(c, str) and c in _SOURCE_VOCAB for c in codes)
        and codes == tuple(sorted(set(codes), key=fi.REASON_PRECEDENCE.index))
        and primary == codes[0]
    )


class _NotAuthorized:
    """Fixed, read-only zero-authority guarantees (not dataclass fields, so no
    constructor, `dataclasses.replace` or serialization input can set them)."""

    @property
    def certified(self) -> bool:
        return False

    @property
    def authorizes_action(self) -> bool:
        return False

    @property
    def auto_retry_allowed(self) -> bool:
        return False

    @property
    def execution_allowed(self) -> bool:
        return False

    @property
    def resume_allowed(self) -> bool:
        return False

    @property
    def merging_allowed(self) -> bool:
        return False

    def _guarantees(self) -> dict:
        return {
            "marker": ADVISORY_MARKER, "certified": False, "authorizes_action": False,
            "auto_retry_allowed": False, "execution_allowed": False, "resume_allowed": False,
            "merging_allowed": False,
        }

    def _check_rule(self) -> None:
        # Construction-time guard: an advisory can only carry the fixed rule
        # of its own first reason - never a hand-made category or authority.
        reasons = self.reasons
        if not (isinstance(reasons, tuple) and reasons and all(isinstance(r, str) and r in _RANK for r in reasons)
                and reasons == _ordered(reasons)):
            raise ValueError("advisory reasons must be ordered advisory reason codes")
        if self.category != _CATEGORY_OF[reasons[0]] or \
                (self.responsibility, self.observation) != CATEGORY_RULES[self.category]:
            raise ValueError("advisory category/responsibility/observation must follow its first reason")


@dataclass(frozen=True)
class WorkerRecoveryAdvisory(_NotAuthorized):
    worker_id: Optional[str]
    source_schema: Optional[str]
    source_primary_reason: Optional[str]
    native_state: Optional[str]
    retry_decision_kind: Optional[str]
    category: str
    responsibility: str
    observation: str
    reasons: tuple

    def __post_init__(self):
        self._check_rule()

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA_WORKER, "schema_version": SCHEMA_VERSION, "worker_id": self.worker_id,
            "source_schema": self.source_schema, "source_primary_reason": self.source_primary_reason,
            "native_state": self.native_state, "retry_decision_kind": self.retry_decision_kind,
            "category": self.category, "responsibility": self.responsibility, "observation": self.observation,
            "reasons": list(self.reasons), **self._guarantees(),
        }


@dataclass(frozen=True)
class PipelineRecoveryAdvisory(_NotAuthorized):
    pipeline_id: Optional[str]
    source_schema: Optional[str]
    source_primary_reason: Optional[str]
    native_status: Optional[str]
    diagnostic_status: Optional[str]
    category: str
    responsibility: str
    observation: str
    reasons: tuple
    workers: tuple

    def __post_init__(self):
        self._check_rule()
        if not (isinstance(self.workers, tuple) and all(isinstance(w, WorkerRecoveryAdvisory) for w in self.workers)):
            raise ValueError("pipeline advisory workers must be a tuple of WorkerRecoveryAdvisory")

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA_PIPELINE, "schema_version": SCHEMA_VERSION, "pipeline_id": self.pipeline_id,
            "source_schema": self.source_schema, "source_primary_reason": self.source_primary_reason,
            "native_status": self.native_status, "diagnostic_status": self.diagnostic_status,
            "category": self.category, "responsibility": self.responsibility, "observation": self.observation,
            "reasons": list(self.reasons), "workers": [w.to_dict() for w in self.workers], **self._guarantees(),
        }


def canonical_json(advisory) -> str:
    """Stable, sorted, compact serialization of an advisory's own fields."""
    return json.dumps(advisory.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _rule(reasons: tuple) -> dict:
    category = _CATEGORY_OF[reasons[0]]
    responsibility, observation = CATEGORY_RULES[category]
    return {"category": category, "responsibility": responsibility, "observation": observation, "reasons": reasons}


# ---------------------------------------------------------------------------
def _worker_consistent(d: "fi.WorkerDiagnostic") -> bool:
    codes = d.reason_codes
    if not _valid_source_codes(codes, d.primary_reason):
        return False
    present = set(codes)
    wid = d.worker_id
    if wid is None:
        if "MALFORMED_EVIDENCE" not in present:
            return False
    elif not fi._safe_id(wid):
        return False
    state = d.native_state
    if state is not None and not (isinstance(state, str) and state in fi.WORKER_STATES) \
            and not present & {"UNKNOWN_STATE", "MALFORMED_EVIDENCE"}:
        return False
    if isinstance(state, str) and state in _STATE_REQUIRES and not present & _STATE_REQUIRES[state]:
        return False
    kind = d.retry_decision_kind
    if not (isinstance(kind, str) and kind in _RETRY_KINDS):
        return False
    if kind in _KIND_REQUIRES and _KIND_REQUIRES[kind] not in present:
        return False
    if "SUCCESS_CONSISTENT" in present and not (codes == ("SUCCESS_CONSISTENT",) and state == "SUCCESS"
                                                and kind == "NONE"):
        return False
    return True


def advise_worker(diagnostic) -> WorkerRecoveryAdvisory:
    """Nonbinding advisory for one FCP-6A-01 `WorkerDiagnostic`. Anything
    that is not exactly that type, or is internally inconsistent, is
    DIAGNOSTIC_UNUSABLE (UNKNOWN). Pure: the diagnostic is only read."""
    if type(diagnostic) is not fi.WorkerDiagnostic:
        return WorkerRecoveryAdvisory(
            worker_id=None, source_schema=None, source_primary_reason=None, native_state=None,
            retry_decision_kind=None, **_rule((DIAGNOSTIC_NOT_TYPED,)),
        )
    codes = diagnostic.reason_codes
    known = {c for c in codes if isinstance(c, str) and c in _SOURCE_VOCAB} if isinstance(codes, tuple) else set()
    if not _worker_consistent(diagnostic):
        known.add(DIAGNOSTIC_INCONSISTENT)
    wid = diagnostic.worker_id
    primary = diagnostic.primary_reason
    return WorkerRecoveryAdvisory(
        worker_id=wid if fi._safe_id(wid) else None,
        source_schema=fi.SCHEMA_WORKER,
        source_primary_reason=_bounded(primary, _SOURCE_VOCAB),
        native_state=_bounded(diagnostic.native_state, fi.WORKER_STATES),
        retry_decision_kind=_bounded(diagnostic.retry_decision_kind, _RETRY_KINDS),
        **_rule(_ordered(known)),
    )


# ---------------------------------------------------------------------------
def _pipeline_consistent(d: "fi.PipelineDiagnostic", advisories: tuple) -> bool:
    codes = d.reason_codes
    if not _valid_source_codes(codes, d.primary_reason):
        return False
    present = set(codes)
    pid = d.pipeline_id
    if pid is None:
        if "MALFORMED_EVIDENCE" not in present:
            return False
    elif not fi._safe_id(pid):
        return False
    if not isinstance(d.workers, tuple) or (not d.workers) != ("EMPTY_PIPELINE" in present):
        return False
    # FCP-6A-01 reports every worker code at pipeline level (success aside).
    worker_codes = {c for w in d.workers if type(w) is fi.WorkerDiagnostic and isinstance(w.reason_codes, tuple)
                    for c in w.reason_codes}
    if not worker_codes - {"SUCCESS_CONSISTENT"} <= present:
        return False
    missing, extra, unidentified = d.missing_worker_ids, d.extra_worker_ids, d.unidentified_extra_results
    if not (isinstance(missing, tuple) and isinstance(extra, tuple)
            and type(unidentified) is int and unidentified >= 0):
        return False
    if missing and "MISSING_WORKER_RESULT" not in present:
        return False
    if (extra or unidentified) and "EXTRA_WORKER_RESULT" not in present:
        return False
    native, status = d.native_status, d.diagnostic_status
    if not (isinstance(status, str) and status in _DIAGNOSTIC_STATUSES):
        return False
    native_known = isinstance(native, str) and native in fi.PIPELINE_STATUSES
    if not native_known:
        if status != fi.DIAGNOSTIC_UNKNOWN:
            return False
    elif native == "SUCCESS":
        if status == "SUCCESS":
            clean = (codes == ("SUCCESS_CONSISTENT",) and bool(advisories) and not missing and not extra
                     and not unidentified and all(a.category == "HISTORICAL_SUCCESS" for a in advisories))
            if not clean:
                return False
        elif status != fi.DIAGNOSTIC_UNVERIFIED:
            return False
    elif status != native:  # a non-success native status is never upgraded
        return False
    if "SUCCESS_CONSISTENT" in present and status != "SUCCESS":
        return False
    return True


def advise_pipeline(diagnostic) -> PipelineRecoveryAdvisory:
    """Nonbinding advisory for one FCP-6A-01 `PipelineDiagnostic`. Every
    worker is advised and reported in the diagnostic's own order; untyped,
    duplicated or inconsistent entries fail closed instead of being dropped.
    The pipeline reasons are the union of its own and every worker's; only a
    precomputed `SUCCESS` with all workers consistently successful yields
    NO_FOLLOWUP_INDICATED. Pure: the diagnostic is only read."""
    if type(diagnostic) is not fi.PipelineDiagnostic:
        return PipelineRecoveryAdvisory(
            pipeline_id=None, source_schema=None, source_primary_reason=None, native_status=None,
            diagnostic_status=None, workers=(), **_rule((DIAGNOSTIC_NOT_TYPED,)),
        )
    # A non-tuple worker sequence is already inconsistent; still advise every entry.
    raw_workers = tuple(diagnostic.workers) if isinstance(diagnostic.workers, (tuple, list)) else ()
    advisories = tuple(advise_worker(w) for w in raw_workers)

    codes = diagnostic.reason_codes
    known = {c for c in codes if isinstance(c, str) and c in _SOURCE_VOCAB} if isinstance(codes, tuple) else set()
    if not _pipeline_consistent(diagnostic, advisories):
        known.add(DIAGNOSTIC_INCONSISTENT)
    for advisory in advisories:
        known.update(advisory.reasons)
    ids = [a.worker_id for a in advisories if a.worker_id is not None]
    if len(ids) != len(set(ids)):
        known.add("DUPLICATE_WORKER_ID")
        if "DUPLICATE_WORKER_ID" not in (codes if isinstance(codes, tuple) else ()):
            known.add(DIAGNOSTIC_INCONSISTENT)
    if not advisories:
        known.add("EMPTY_PIPELINE")

    pid = diagnostic.pipeline_id
    return PipelineRecoveryAdvisory(
        pipeline_id=pid if fi._safe_id(pid) else None,
        source_schema=fi.SCHEMA_PIPELINE,
        source_primary_reason=_bounded(diagnostic.primary_reason, _SOURCE_VOCAB),
        native_status=_bounded(diagnostic.native_status, fi.PIPELINE_STATUSES),
        diagnostic_status=_bounded(diagnostic.diagnostic_status, _DIAGNOSTIC_STATUSES),
        workers=advisories, **_rule(_ordered(known)),
    )
