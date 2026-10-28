"""FCP-6A-01: Failure Intelligence V1 - pure, read-only, fail-closed
interpretation of EXISTING Runner failure/retry evidence.

Answers ONE question: given structured Runner dictionaries the caller has
ALREADY read (`pipeline_result.json` and `workers/<id>/result.json`), what
does that evidence say about each worker and the pipeline, and how sure can
a reader be? It returns frozen, deterministic diagnostics - never an action.

Why this is a reader, not retry machinery
-----------------------------------------
* The Runner (`runner_pipeline.PipelineRunner`) stays the ONLY execution,
  provider-availability, retry, resume, lease, process-control and durable-
  state authority. Nothing here schedules, retries, resumes, derives a
  `resume_from`, runs a process or shell, checkpoints, touches Git, or opens
  a file, socket or process: stdlib only, no I/O, no mutable global state.
* Only exact persisted Runner keys are read (`state`, `state_reason`,
  `outcome`, `code`, `attempts[-1].retry_decision`, `evidence_complete`,
  `process_confirmed_stopped`, ...). `stdout`/`stderr`, provider prose,
  `message`, `error`, Work Order bodies, prompts, metadata and paths are
  never parsed and never copied into a diagnostic. Native codes are kept
  only as bounded upper-case tokens; anything else becomes `UNRECOGNIZED`.
* The Runner vocabulary is mirrored as constants instead of imported, so
  this module never imports `runner_pipeline` (and its process/Git
  dependencies); the test suite pins the mirror to the Runner's own enums.

What a diagnostic means
-----------------------
Informational only. Reason codes are ordered by `REASON_PRECEDENCE`
(fail-closed: identity/shape problems, process-termination uncertainty and
safety refusals outrank quota, transient and provider conditions) and are
NOT prescriptions. Every diagnostic fixes `certified`, `authorizes_action`,
`auto_retry_allowed` and `execution_allowed` to False as read-only
properties. `WAITING_PROVIDER_QUOTA` and `RETRY_WAIT` describe the Runner's
current wait, never a new eligibility schedule or a licence for another
retry; `BLOCKED_PROVIDER_AUTH` is never retryable. Absent evidence is
UNVERIFIED, never success; a native `SUCCESS` is reported as
`SUCCESS_CONSISTENT` only when its structured evidence agrees, and even then
it is not certified.
"""

from __future__ import annotations

import dataclasses
import json
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Optional

SCHEMA_WORKER = "fcp6a01-runner-worker-diagnostic-v1"
SCHEMA_PIPELINE = "fcp6a01-runner-pipeline-diagnostic-v1"
SCHEMA_VERSION = 1
DIAGNOSTIC_MARKER = "FCP6A01_INFORMATIONAL_NOT_CERTIFIED_NOT_AUTHORIZED"
# `pipeline_result.json` schema this reader understands
# (`runner_pipeline.PIPELINE_SCHEMA_VERSION`); any other is fail-closed.
SUPPORTED_RUNNER_SCHEMA_VERSION = 1

# Mirror of `runner_pipeline.WorkerState` / `PipelineStatus` (pinned by tests).
WORKER_STATES = frozenset({
    "QUEUED", "WAITING_DEPENDENCY", "READY", "RUNNING", "RETRY_WAIT", "WAITING_PROVIDER_QUOTA",
    "BLOCKED_PROVIDER_AUTH", "SUCCESS", "PARTIAL", "BLOCKED", "FAILED", "CANCELLED", "INTERRUPTED",
})
PIPELINE_STATUSES = frozenset({
    "RUNNING", "DRAINING", "SUCCESS", "PARTIAL", "BLOCKED", "FAILED", "CANCELLED", "INCOMPLETE",
})
TERMINAL_STATES = frozenset({"SUCCESS", "PARTIAL", "BLOCKED", "FAILED", "CANCELLED"})
_PENDING_STATES = frozenset({"QUEUED", "WAITING_DEPENDENCY", "READY", "RUNNING"})
# Mirror of `claude_runner.WORK_STATUS_SOURCES`.
WORK_STATUS_SOURCES = frozenset({"PROVIDER", "RUNNER_ACCEPTANCE"})
# The `outcome` `_write_result` records alongside each state.
_OUTCOME_FOR_STATE = {
    s: s for s in ("SUCCESS", "PARTIAL", "BLOCKED", "FAILED", "CANCELLED", "INTERRUPTED",
                   "BLOCKED_PROVIDER_AUTH", "WAITING_PROVIDER_QUOTA")
}
# Prefixes of the Runner's own `attempt["retry_decision"]` strings.
RETRY_DECISION_KINDS = frozenset({"NONE", "NO_RETRY", "RETRY", "WAIT", "FALLBACK"})
RETRY_KIND_ABSENT = "ABSENT"
UNRECOGNIZED = "UNRECOGNIZED"

_PREFLIGHT_CODES = frozenset({"PROVIDER_UNKNOWN", "PROVIDER_UNAVAILABLE", "CAPABILITY_MISMATCH"})
_SAFETY_CODES = frozenset({
    "FAILED_SAFETY", "SELF_MODIFICATION_REFUSED", "BRANCH_GUARD_REFUSED", "DIRTY_TREE_REFUSED",
    "WRITE_SCOPE_REQUIRED", "WRITE_SCOPE_INVALID", "ALLOW_SHELL_REQUIRES_WRITE_MODE", "RESUME_REFUSED",
})
_UNRESOLVED_CODE = "PROVIDER_PROCESS_UNRESOLVED"

# Reason codes, highest precedence first. A diagnostic's `primary_reason` is
# its first code in this order; every code observed is still reported.
REASON_PRECEDENCE = (
    "MALFORMED_EVIDENCE",
    "IDENTITY_MISMATCH",
    "DUPLICATE_WORKER_ID",
    "UNKNOWN_STATE",
    "AGGREGATE_CONTRADICTION",
    "CONFLICTING_EVIDENCE",
    "RETRY_DECISION_UNRECOGNIZED",
    "PROCESS_TERMINATION_UNRESOLVED",
    "SAFETY_REFUSAL",
    "INTERRUPTED_OPERATOR_REVIEW",
    "PROVIDER_AUTH_BLOCKED",
    "CHECKPOINT_FAILED",
    "ACCEPTANCE_FAILED",
    "PREFLIGHT_REFUSED",
    "DEPENDENCY_CANCELLED",
    "NATIVE_CANCELLED",
    "NATIVE_FAILED",
    "NATIVE_BLOCKED",
    "PARTIAL_COMPLETION",
    "EVIDENCE_INCOMPLETE",
    "PROVIDER_QUOTA_WAIT",
    "TRANSIENT_RETRY_WAIT",
    "NOT_TERMINAL",
    "MISSING_WORKER_RESULT",
    "EXTRA_WORKER_RESULT",
    "EVIDENCE_MISSING",
    "EVIDENCE_UNPROVEN",
    "EMPTY_PIPELINE",
    "SUCCESS_CONSISTENT",
)
_RANK = {code: i for i, code in enumerate(REASON_PRECEDENCE)}

DIAGNOSTIC_UNKNOWN = "UNKNOWN"
DIAGNOSTIC_UNVERIFIED = "UNVERIFIED"

_TOKEN_RE = re.compile(r"[A-Z][A-Z0-9_]{0,63}")


def _safe_id(value) -> bool:
    # Same shape `runner_pipeline._safe_segment` accepts for pipeline/worker ids.
    return (
        isinstance(value, str) and 0 < len(value) <= 64
        and all(c.isascii() and (c.isalnum() or c in "-_.") for c in value)
        and not value.startswith(".")
    )


def _member(value, names) -> bool:
    # Hash-safe membership: tampered input may carry unhashable values.
    return isinstance(value, str) and value in names


def _token(value) -> Optional[str]:
    """Bounded code for a native string: its first `:`-segment when that is
    an upper-case identifier, else UNRECOGNIZED. None stays None. Never
    echoes free text (provider ids, timestamps, prose)."""
    if value is None:
        return None
    if not isinstance(value, str):
        return UNRECOGNIZED
    head = value.split(":", 1)[0]
    return head if _TOKEN_RE.fullmatch(head) else UNRECOGNIZED


def _ordered(codes) -> tuple:
    return tuple(sorted(set(codes), key=_RANK.__getitem__))


def _retry_decision(raw) -> tuple:
    """(kind, code) of a native `retry_decision`, e.g.
    `RETRY:TRANSIENT:CLAUDE_ERROR:backoff=30s` -> ("RETRY", "TRANSIENT").
    Timestamps, backoff values and fallback provider ids are dropped."""
    if raw is None:
        return RETRY_KIND_ABSENT, None
    if not isinstance(raw, str):
        return UNRECOGNIZED, None
    parts = raw.split(":")
    if parts[0] not in RETRY_DECISION_KINDS:
        return UNRECOGNIZED, None
    if parts[0] == "FALLBACK" or len(parts) < 2:
        return parts[0], None
    code = parts[1] if _TOKEN_RE.fullmatch(parts[1]) else UNRECOGNIZED
    return parts[0], code


class _NotAuthorized:
    """Fixed, read-only zero-action guarantees (not dataclass fields, so no
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

    def _guarantees(self) -> dict:
        return {
            "marker": DIAGNOSTIC_MARKER, "certified": False, "authorizes_action": False,
            "auto_retry_allowed": False, "execution_allowed": False,
        }


@dataclass(frozen=True)
class WorkerDiagnostic(_NotAuthorized):
    worker_id: Optional[str]
    primary_reason: str
    reason_codes: tuple
    native_state: Optional[str]
    native_state_reason: Optional[str]
    native_outcome: Optional[str]
    native_code: Optional[str]
    native_runner_state: Optional[str]
    native_work_status_source: Optional[str]
    retry_decision_kind: str
    retry_decision_code: Optional[str]
    attempts_recorded: Optional[int]
    evidence_refs: tuple

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA_WORKER, "schema_version": SCHEMA_VERSION, "worker_id": self.worker_id,
            "primary_reason": self.primary_reason, "reason_codes": list(self.reason_codes),
            "native_state": self.native_state, "native_state_reason": self.native_state_reason,
            "native_outcome": self.native_outcome, "native_code": self.native_code,
            "native_runner_state": self.native_runner_state,
            "native_work_status_source": self.native_work_status_source,
            "retry_decision_kind": self.retry_decision_kind, "retry_decision_code": self.retry_decision_code,
            "attempts_recorded": self.attempts_recorded, "evidence_refs": list(self.evidence_refs),
            **self._guarantees(),
        }


@dataclass(frozen=True)
class PipelineDiagnostic(_NotAuthorized):
    pipeline_id: Optional[str]
    native_status: Optional[str]
    diagnostic_status: str
    primary_reason: str
    reason_codes: tuple
    workers: tuple
    missing_worker_ids: tuple
    extra_worker_ids: tuple
    unidentified_extra_results: int

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA_PIPELINE, "schema_version": SCHEMA_VERSION, "pipeline_id": self.pipeline_id,
            "native_status": self.native_status, "diagnostic_status": self.diagnostic_status,
            "primary_reason": self.primary_reason, "reason_codes": list(self.reason_codes),
            "workers": [w.to_dict() for w in self.workers],
            "missing_worker_ids": list(self.missing_worker_ids), "extra_worker_ids": list(self.extra_worker_ids),
            "unidentified_extra_results": self.unidentified_extra_results, **self._guarantees(),
        }


def canonical_json(diagnostic) -> str:
    """Stable, sorted, compact serialization of a diagnostic's own fields."""
    return json.dumps(diagnostic.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


# ---------------------------------------------------------------------------
def _state_value(raw, codes: set) -> Optional[str]:
    if raw is None:
        return None
    if not isinstance(raw, str):
        codes.add("MALFORMED_EVIDENCE")
        return UNRECOGNIZED
    if raw in WORKER_STATES:
        return raw
    codes.add("UNKNOWN_STATE")
    return _token(raw)


def _last_attempt(result, codes: set) -> tuple:
    attempts = result.get("attempts")
    if attempts is None:
        return None, None
    if not isinstance(attempts, list) or not all(isinstance(a, Mapping) for a in attempts):
        codes.add("MALFORMED_EVIDENCE")
        return None, None
    return (attempts[-1] if attempts else None), len(attempts)


def _process_unresolved(last: Mapping, result: Mapping, codes_seen: tuple) -> bool:
    if _UNRESOLVED_CODE in codes_seen:
        return True
    if last.get("process_termination_unresolved") is True or last.get("acceptance_termination_unresolved") is True:
        return True
    if "process_confirmed_stopped" in last and last.get("process_confirmed_stopped") is not True:
        return True
    recovery = last.get("process_recovery")
    if isinstance(recovery, Mapping) and recovery.get("resolution") == "UNRESOLVED":
        return True
    for acceptance in (last.get("acceptance"), result.get("acceptance")):
        if isinstance(acceptance, Mapping) and (
            acceptance.get("termination_unresolved") is True or acceptance.get("decision") == "PROCESS_UNRESOLVED"
        ):
            return True
    return False


def _safety_refused(last: Mapping, result: Mapping, codes_seen: tuple) -> bool:
    if any(c in _SAFETY_CODES for c in codes_seen):
        return True
    for source in (result, last):
        paths = source.get("unauthorized_changed_paths")
        if paths is not None and (not isinstance(paths, list) or paths):
            return True
        verdict = source.get("safety_verdict")
        if isinstance(verdict, Mapping) and verdict.get("verdict") == "FAILED_SAFETY":
            return True
    return False


def _success_proven(result, last, outcome, kind, retry_code) -> bool:
    return (
        isinstance(result, Mapping) and isinstance(last, Mapping)
        and outcome == "SUCCESS" and kind == "NONE" and retry_code == "SUCCESS"
        and last.get("status") == "COMPLETED"
        and last.get("evidence_complete") is True
        and last.get("process_confirmed_stopped") is True
        and last.get("work_status") == "SUCCESS"
        and _member(last.get("work_status_source"), WORK_STATUS_SOURCES)
        and result.get("work_status") == last.get("work_status")
        and result.get("work_status_source") == last.get("work_status_source")
    )


def assess_worker(worker_id, result, *, pipeline_id=None, summary=None, summary_index=None) -> WorkerDiagnostic:
    """Diagnose one worker from its already-read `workers/<id>/result.json`
    (`result`, or None when absent) and, optionally, its entry in
    `pipeline_result.json["workers"]` (`summary`). `pipeline_id`, when given,
    must match the result's own. Pure: the inputs are only read."""
    codes: set = set()
    refs = []
    wid = worker_id if _safe_id(worker_id) else None
    if wid is None:
        codes.add("MALFORMED_EVIDENCE")

    if summary is not None and not isinstance(summary, Mapping):
        codes.add("MALFORMED_EVIDENCE")
        summary = None
    if result is not None and not isinstance(result, Mapping):
        codes.add("MALFORMED_EVIDENCE")
        result = None
        refs.append("worker_result")
    if summary is not None:
        refs.append(f"pipeline_result.workers[{summary_index}]" if isinstance(summary_index, int)
                    else "pipeline_result.workers")
        if summary.get("id") != worker_id:
            codes.add("IDENTITY_MISMATCH")

    summary_state = _state_value(summary.get("state"), codes) if summary is not None else None
    result_state = None
    last, attempts_recorded = None, None
    outcome = native_code = runner_state = source = None
    if result is not None:
        refs.append("worker_result")
        if result.get("worker_id") != worker_id:
            codes.add("IDENTITY_MISMATCH")
        if pipeline_id is not None and result.get("pipeline_id") != pipeline_id:
            codes.add("IDENTITY_MISMATCH")
        result_state = _state_value(result.get("state"), codes)
        if result_state is None:
            codes.add("MALFORMED_EVIDENCE")
        outcome, native_code = _token(result.get("outcome")), _token(result.get("code"))
        if result_state in _OUTCOME_FOR_STATE and outcome != _OUTCOME_FOR_STATE[result_state]:
            codes.add("CONFLICTING_EVIDENCE")
        last, attempts_recorded = _last_attempt(result, codes)
        if last is not None:
            refs.append(f"worker_result.attempts[{attempts_recorded - 1}]")
            runner_state = _token(last.get("runner_state"))
            raw_source = last.get("work_status_source")
            source = raw_source if _member(raw_source, WORK_STATUS_SOURCES) else (
                None if raw_source is None else UNRECOGNIZED)
        if summary is not None and summary.get("result_path", "") is None:
            # The Runner clears `result_path` on requeue: this result is stale.
            codes.add("CONFLICTING_EVIDENCE")
    elif summary is None or summary.get("result_path") is not None:
        codes.add("EVIDENCE_MISSING")
    elif summary_state in TERMINAL_STATES:
        codes.add("EVIDENCE_MISSING")

    if summary_state is not None and result_state is not None and summary_state != result_state:
        codes.add("CONFLICTING_EVIDENCE")
    state = summary_state if summary_state is not None else result_state
    if state is None and (result is not None or summary is not None):
        codes.add("MALFORMED_EVIDENCE")  # evidence present but stateless

    reasons = [_token(summary.get("state_reason")) if summary is not None else None,
               _token(result.get("state_reason")) if result is not None else None]
    if summary_state == result_state and None not in reasons and reasons[0] != reasons[1]:
        codes.add("CONFLICTING_EVIDENCE")
    state_reason = reasons[0] if summary is not None else reasons[1]

    kind, retry_code = _retry_decision(last.get("retry_decision") if last is not None else None)
    if kind == UNRECOGNIZED:
        codes.add("RETRY_DECISION_UNRECOGNIZED")

    seen = tuple(c for c in (state_reason, native_code, runner_state, retry_code) if c)
    last_view = last if last is not None else {}
    result_view = result if result is not None else {}
    condition = _token(summary.get("provider_condition")) if summary is not None else None

    if _process_unresolved(last_view, result_view, seen):
        codes.add("PROCESS_TERMINATION_UNRESOLVED")
    if _safety_refused(last_view, result_view, seen):
        codes.add("SAFETY_REFUSAL")
    if state == "INTERRUPTED" or any(c in ("INTERRUPTED", "ACCEPTANCE_INTERRUPTED") for c in seen):
        codes.add("INTERRUPTED_OPERATOR_REVIEW")
    if state == "BLOCKED_PROVIDER_AUTH" or "PROVIDER_AUTH_BLOCKED" in seen or condition == "PROVIDER_AUTH_BLOCKED":
        codes.add("PROVIDER_AUTH_BLOCKED")
    if "CHECKPOINT_FAILED" in seen:
        codes.add("CHECKPOINT_FAILED")
    if "ACCEPTANCE_FAILED" in seen:
        codes.add("ACCEPTANCE_FAILED")
    if any(c in _PREFLIGHT_CODES for c in seen):
        codes.add("PREFLIGHT_REFUSED")
    if state == "CANCELLED":
        codes.add("DEPENDENCY_CANCELLED" if "DEPENDENCY_UNSATISFIED" in seen else "NATIVE_CANCELLED")
    if state == "FAILED":
        codes.add("NATIVE_FAILED")
    if state == "BLOCKED":
        codes.add("NATIVE_BLOCKED")
    if state == "PARTIAL":
        codes.add("PARTIAL_COMPLETION")
    if last_view.get("evidence_complete") is False or "EVIDENCE_FINALIZATION_FAILED" in seen:
        codes.add("EVIDENCE_INCOMPLETE")
    if state == "WAITING_PROVIDER_QUOTA" or kind == "WAIT" or "PROVIDER_QUOTA_EXHAUSTED" in seen \
            or condition == "PROVIDER_QUOTA_EXHAUSTED":
        codes.add("PROVIDER_QUOTA_WAIT")
    if state == "RETRY_WAIT" or kind == "RETRY":
        codes.add("TRANSIENT_RETRY_WAIT")
    if state in _PENDING_STATES:
        codes.add("NOT_TERMINAL")

    if state == "SUCCESS":
        if not _success_proven(result, last, outcome, kind, retry_code):
            codes.add("EVIDENCE_UNPROVEN")
        if codes - {"EVIDENCE_UNPROVEN", "EVIDENCE_MISSING"}:
            # Any failure/wait signal beside a native SUCCESS contradicts it.
            codes.add("CONFLICTING_EVIDENCE")
        if not codes:
            codes.add("SUCCESS_CONSISTENT")
    if not codes:
        # A recognized state with no interpretable evidence is never a pass.
        codes.add("EVIDENCE_UNPROVEN")

    ordered = _ordered(codes)
    return WorkerDiagnostic(
        worker_id=wid, primary_reason=ordered[0], reason_codes=ordered, native_state=state,
        native_state_reason=state_reason, native_outcome=outcome, native_code=native_code,
        native_runner_state=runner_state, native_work_status_source=source,
        retry_decision_kind=kind, retry_decision_code=retry_code, attempts_recorded=attempts_recorded,
        evidence_refs=tuple(dict.fromkeys(refs)),
    )


# ---------------------------------------------------------------------------
def _native_overall(states: list) -> Optional[str]:
    """`runner_pipeline.PipelineRunner._overall_status` over native states."""
    if any(s not in TERMINAL_STATES for s in states):
        return "INCOMPLETE"
    if all(s == "SUCCESS" for s in states):
        return "SUCCESS"
    for sev in ("FAILED", "BLOCKED", "CANCELLED", "PARTIAL"):
        if sev in states:
            return sev
    return None


def _aggregate_contradicts(pipeline_result: Mapping, states: list, status: str) -> bool:
    if pipeline_result.get("workers_total") != len(states):
        return True
    counts = pipeline_result.get("state_counts")
    if counts is not None:
        if not isinstance(counts, Mapping):
            return True
        for name, n in counts.items():
            if n != states.count(name):
                return True
    for key, name in (("success", "SUCCESS"), ("failed", "FAILED"), ("blocked", "BLOCKED"),
                      ("partial", "PARTIAL"), ("cancelled", "CANCELLED"), ("interrupted", "INTERRUPTED"),
                      ("waiting_provider_quota", "WAITING_PROVIDER_QUOTA"),
                      ("blocked_provider_auth", "BLOCKED_PROVIDER_AUTH")):
        if key in pipeline_result and pipeline_result.get(key) != states.count(name):
            return True
    if status in ("RUNNING", "DRAINING"):
        return False
    return bool(states) and _native_overall(states) != status


def assess_pipeline(pipeline_result, worker_results) -> PipelineDiagnostic:
    """Diagnose an already-read `pipeline_result.json` together with the
    caller-supplied mapping `{worker_id: workers/<id>/result.json or None}`.
    Every declared worker is assessed in native order; missing, duplicate
    and extra workers are reported, never dropped. Pure: inputs only read."""
    codes: set = set()
    if not isinstance(pipeline_result, Mapping):
        pipeline_result = {}
        codes.add("MALFORMED_EVIDENCE")
    if not isinstance(worker_results, Mapping):
        worker_results = {}
        codes.add("MALFORMED_EVIDENCE")

    raw_pid = pipeline_result.get("pipeline_id")
    pipeline_id = raw_pid if _safe_id(raw_pid) else None
    if pipeline_id is None or pipeline_result.get("schema_version") != SUPPORTED_RUNNER_SCHEMA_VERSION:
        codes.add("MALFORMED_EVIDENCE")
    raw_status = pipeline_result.get("status")
    if _member(raw_status, PIPELINE_STATUSES):
        native_status = raw_status
    else:
        native_status = _token(raw_status)
        codes.add("UNKNOWN_STATE" if isinstance(raw_status, str) else "MALFORMED_EVIDENCE")

    declared = pipeline_result.get("workers")
    if not isinstance(declared, list):
        codes.add("MALFORMED_EVIDENCE")
        declared = []
    if not declared:
        codes.add("EMPTY_PIPELINE")

    ids = [s.get("id") if isinstance(s, Mapping) else None for s in declared]
    seen_ids = Counter(w for w in ids if isinstance(w, str))
    workers, states = [], []
    for index, (summary, wid) in enumerate(zip(declared, ids)):
        present = isinstance(wid, str) and wid in worker_results
        diag = assess_worker(
            wid, worker_results.get(wid) if present else None, pipeline_id=raw_pid,
            summary=summary, summary_index=index,
        )
        if isinstance(wid, str) and seen_ids[wid] > 1:
            codes.add("DUPLICATE_WORKER_ID")
            diag = _with_code(diag, "DUPLICATE_WORKER_ID")
        workers.append(diag)
        states.append(diag.native_state)
        if not present:
            codes.add("MISSING_WORKER_RESULT")

    missing = tuple(dict.fromkeys(w for w in ids if _safe_id(w) and w not in worker_results))
    extra_keys = [k for k in worker_results if not (isinstance(k, str) and k in seen_ids)]
    extra = tuple(sorted(k for k in extra_keys if _safe_id(k)))
    unidentified = len(extra_keys) - len(extra)
    if extra_keys:
        codes.add("EXTRA_WORKER_RESULT")

    if isinstance(pipeline_result.get("workers"), list) and native_status in PIPELINE_STATUSES \
            and _aggregate_contradicts(pipeline_result, states, native_status):
        codes.add("AGGREGATE_CONTRADICTION")

    worker_codes = {c for w in workers for c in w.reason_codes}
    all_codes = codes | worker_codes
    if native_status not in PIPELINE_STATUSES:
        diagnostic_status = DIAGNOSTIC_UNKNOWN
    elif native_status == "SUCCESS":
        clean = workers and not codes and all(w.reason_codes == ("SUCCESS_CONSISTENT",) for w in workers)
        diagnostic_status = "SUCCESS" if clean else DIAGNOSTIC_UNVERIFIED
    else:
        diagnostic_status = native_status  # never optimistically upgraded
    if not all_codes:
        all_codes.add("EVIDENCE_UNPROVEN")
    if diagnostic_status != "SUCCESS":
        all_codes.discard("SUCCESS_CONSISTENT")
        if not all_codes:
            all_codes.add("EVIDENCE_UNPROVEN")
    ordered = _ordered(all_codes)
    return PipelineDiagnostic(
        pipeline_id=pipeline_id, native_status=native_status, diagnostic_status=diagnostic_status,
        primary_reason=ordered[0], reason_codes=ordered, workers=tuple(workers),
        missing_worker_ids=missing, extra_worker_ids=extra, unidentified_extra_results=unidentified,
    )


def _with_code(diag: WorkerDiagnostic, code: str) -> WorkerDiagnostic:
    codes = set(diag.reason_codes) | {code}
    codes.discard("SUCCESS_CONSISTENT")
    ordered = _ordered(codes)
    return dataclasses.replace(diag, primary_reason=ordered[0], reason_codes=ordered)
