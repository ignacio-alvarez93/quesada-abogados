"""FCP-6C-01: Director recovery view - pure, read-only, observational
projection of ONE Director DAG run next to its FCP-6A/6B interpretation.

Answers ONE question: given the three sources the host has ALREADY read and
verified - a `fabric_director.DirectorDagRunSummary`, the Runner's
`pipeline_result.json` (Mapping) and `{worker_id: workers/<id>/result.json
or None}` - what do the Director, the FCP-6A-01 diagnostic and the FCP-6B-01
advisory say side by side, and do they agree on identity, order and status?

Why this is a view, not a new source of truth
---------------------------------------------
* The Runner stays the ONLY execution, retry, fallback, auth, quota, lease,
  ownership, `resume_from`, checkpoint, Git, promotion and recovery
  authority, and the Director keeps its own. Nothing here calls
  `result_blueprint`, schedules, retries, resumes, submits, runs a process,
  touches Git, or opens a file, socket or process: stdlib only, no I/O.
* It calls exactly `runner_failure_intelligence.assess_pipeline` and
  `runner_recovery_advisory.advise_pipeline` and embeds their `to_dict()`
  verbatim. The Director's own statuses are projected verbatim when they are
  in the Director/Runner vocabulary (else UNRECOGNIZED) - never re-decided.
* Only stable references and bounded codes are exported: ids, digests,
  states, reason codes. Evidence paths, provider ids, timestamps, messages,
  prompts and free text never leave the inputs.

What the view means
-------------------
Informational only. `consistency_codes` list every cross-source
disagreement found (identity, worker set/order, duplicates, missing or
extra results, per-worker state/record, status); `cross_source_consistent`
is True only when there are none, and it is NOT success, certification or
permission. A Director SUCCESS beside a non-SUCCESS diagnostic is reported
as DIRECTOR_SUCCESS_UNVERIFIED and is never elevated. Every view fixes
`certified`, `authorizes_action`, `auto_retry_allowed`, `execution_allowed`,
`resume_allowed` and `merging_allowed` to False as read-only properties.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Optional

from scripts.ai import fabric_director as fd
from scripts.ai import runner_failure_intelligence as fi
from scripts.ai import runner_recovery_advisory as ra

SCHEMA = "fcp6c01-director-recovery-view-v1"
SCHEMA_VERSION = 1
VIEW_MARKER = "FCP6C01_OBSERVATIONAL_NOT_CERTIFIED_NOT_AUTHORIZED"
UNRECOGNIZED = fi.UNRECOGNIZED

# Director aggregate vocabulary: Runner pipeline statuses plus the two
# fail-closed values `fabric_director._classify_dag_aggregate` adds.
DIRECTOR_AGGREGATE_STATUSES = fi.PIPELINE_STATUSES | {fd.DAG_AGGREGATE_UNVERIFIED, fd.DAG_AGGREGATE_UNKNOWN}
WORKER_RECORDS = frozenset({fd.WORKER_RECORD_PRESENT, fd.WORKER_RECORD_MISSING, fd.WORKER_RECORD_MISMATCH})
EVIDENCE_HEALTHS = frozenset({fd.EVIDENCE_HEALTH_COMPLETE, fd.EVIDENCE_HEALTH_INCOMPLETE, fd.EVIDENCE_HEALTH_UNKNOWN})

# Cross-source codes, highest precedence first (all fail-closed).
CONSISTENCY_CODES = (
    "SUMMARY_NOT_TYPED",
    "DIRECTOR_SUMMARY_MALFORMED",
    "PIPELINE_ID_MISMATCH",
    "DUPLICATE_WORKER_ID",
    "WORKER_SET_MISMATCH",
    "WORKER_ORDER_MISMATCH",
    "MISSING_WORKER_RESULT",
    "EXTRA_WORKER_RESULT",
    "WORKER_RECORD_MISMATCH",
    "WORKER_STATE_MISMATCH",
    "PIPELINE_STATUS_MISMATCH",
    "DIRECTOR_SUCCESS_UNVERIFIED",
    "AGGREGATE_STATUS_MISMATCH",
    "RUNNER_EVIDENCE_INCONSISTENT",
    "ADVISORY_DIAGNOSTIC_UNUSABLE",
)
_RANK = {code: i for i, code in enumerate(CONSISTENCY_CODES)}
# FCP-6A-01 codes that mean the Runner sources do not agree with themselves.
_RUNNER_INTEGRITY_CODES = frozenset({
    "MALFORMED_EVIDENCE", "IDENTITY_MISMATCH", "UNKNOWN_STATE", "AGGREGATE_CONTRADICTION",
    "CONFLICTING_EVIDENCE", "RETRY_DECISION_UNRECOGNIZED", "EMPTY_PIPELINE",
})

_TOKEN_RE = re.compile(r"[A-Z][A-Z0-9_]{0,63}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


def _safe_id(value) -> bool:
    # The id shape `runner_pipeline._safe_segment` accepts (as FCP-6A-01).
    return (
        isinstance(value, str) and 0 < len(value) <= 64
        and all(c.isascii() and (c.isalnum() or c in "-_.") for c in value)
        and not value.startswith(".")
    )


def _id(value) -> Optional[str]:
    return value if _safe_id(value) else None


def _bounded(value, vocabulary) -> Optional[str]:
    if value is None:
        return None
    return value if isinstance(value, str) and value in vocabulary else UNRECOGNIZED


def _token(value) -> Optional[str]:
    """Leading upper-case code of a native string; never free text."""
    if value is None:
        return None
    if not isinstance(value, str):
        return UNRECOGNIZED
    head = value.split(":", 1)[0]
    return head if _TOKEN_RE.fullmatch(head) else UNRECOGNIZED


def _reason(value) -> str:
    """A Director reason: a code, or `<worker_id>:<code>` (aggregate)."""
    if isinstance(value, str):
        wid, sep, code = value.rpartition(":")
        if not sep and _TOKEN_RE.fullmatch(value):
            return value
        if sep and _safe_id(wid) and _TOKEN_RE.fullmatch(code):
            return value
    return UNRECOGNIZED


def _reasons(value) -> list:
    return [_reason(r) for r in value] if isinstance(value, (tuple, list)) else [UNRECOGNIZED]


def _ordered(codes) -> tuple:
    return tuple(sorted(set(codes), key=_RANK.__getitem__))


def _has_duplicates(ids) -> bool:
    return any(n > 1 for wid, n in Counter(ids).items() if wid is not None)


class _NotAuthorized:
    """Fixed, read-only zero-authority guarantees (not dataclass fields)."""

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
            "marker": VIEW_MARKER, "certified": False, "authorizes_action": False, "auto_retry_allowed": False,
            "execution_allowed": False, "resume_allowed": False, "merging_allowed": False,
        }


@dataclass(frozen=True)
class DirectorRecoveryView(_NotAuthorized):
    director: str  # canonical JSON of the bounded Director projection
    diagnostic: str  # canonical JSON of `PipelineDiagnostic.to_dict()`
    advisory: str  # canonical JSON of `PipelineRecoveryAdvisory.to_dict()`
    workers: str  # canonical JSON of the reconciled worker rows
    consistency_codes: tuple

    def __post_init__(self):
        codes = self.consistency_codes
        if not (isinstance(codes, tuple) and all(isinstance(c, str) and c in _RANK for c in codes)
                and codes == _ordered(codes)):
            raise ValueError("view consistency codes must be ordered FCP-6C-01 codes")

    @property
    def cross_source_consistent(self) -> bool:
        return not self.consistency_codes

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA, "schema_version": SCHEMA_VERSION, "director": json.loads(self.director),
            "diagnostic": json.loads(self.diagnostic), "advisory": json.loads(self.advisory),
            "workers": json.loads(self.workers), "consistency_codes": list(self.consistency_codes),
            "cross_source_consistent": self.cross_source_consistent, **self._guarantees(),
        }


def _canonical(payload) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def canonical_json(view: DirectorRecoveryView) -> str:
    """Stable, sorted, compact serialization of a view."""
    return _canonical(view.to_dict())


# ---------------------------------------------------------------------------
def _director_worker(w) -> dict:
    if type(w) is not fd.DirectorDagWorkerSummary:
        return {"worker_id": None, "worker_state": None, "worker_record": None, "evidence_health": None,
                "runner_proven_success": False, "unproven_reasons": [UNRECOGNIZED], "typed": False}
    return {
        "worker_id": _id(w.worker_id), "worker_state": _bounded(w.worker_state, fi.WORKER_STATES),
        "worker_record": _bounded(w.worker_record, WORKER_RECORDS),
        "evidence_health": _bounded(w.evidence_health, EVIDENCE_HEALTHS),
        "runner_proven_success": w.runner_proven_success is True and not w.unproven_reasons,
        "unproven_reasons": _reasons(w.unproven_reasons), "typed": True,
    }


def _director(summary) -> tuple:
    """(bounded Director projection, raw-identity-valid flag)."""
    workers = summary.workers if isinstance(summary.workers, tuple) else ()
    projection = {
        "run_id": _id(summary.run_id), "pipeline_id": _id(summary.pipeline_id),
        "blueprint_pipeline_id": _id(summary.blueprint_pipeline_id),
        "manifest_sha256": summary.manifest_sha256 if isinstance(summary.manifest_sha256, str)
        and _SHA256_RE.fullmatch(summary.manifest_sha256) else None,
        "plan_fingerprint": summary.plan_fingerprint if isinstance(summary.plan_fingerprint, str)
        and _SHA256_RE.fullmatch(summary.plan_fingerprint) else None,
        "pipeline_status": _bounded(summary.pipeline_status, fi.PIPELINE_STATUSES),
        "stop_reason": _token(summary.stop_reason),
        "aggregate_status": _bounded(summary.aggregate_status, DIRECTOR_AGGREGATE_STATUSES),
        "aggregate_reasons": _reasons(summary.aggregate_reasons),
        "workers": [_director_worker(w) for w in workers],
    }
    valid = (
        isinstance(summary.workers, tuple) and None not in (
            projection["run_id"], projection["pipeline_id"], projection["blueprint_pipeline_id"],
            projection["manifest_sha256"], projection["plan_fingerprint"])
        and projection["run_id"] == projection["pipeline_id"]
        and UNRECOGNIZED not in (projection["pipeline_status"], projection["aggregate_status"])
        and UNRECOGNIZED not in projection["aggregate_reasons"]
        and all(w["typed"] and w["worker_id"] is not None and UNRECOGNIZED not in w["unproven_reasons"]
                and UNRECOGNIZED not in (w["worker_state"], w["worker_record"], w["evidence_health"])
                for w in projection["workers"])
    )
    for w in projection["workers"]:
        del w["typed"]
    return projection, valid


def build_view(summary, pipeline_result, worker_results) -> DirectorRecoveryView:
    """Observational view of one Director DAG run over the three already-read
    sources. Every worker declared by the Director or the Runner is kept, in
    Director (plan) order, then Runner-only workers in Runner order. Pure:
    the inputs are only read; nothing is executed, retried or authorized."""
    codes: set = set()
    diagnostic = fi.assess_pipeline(pipeline_result, worker_results)
    advisory = ra.advise_pipeline(diagnostic)

    if type(summary) is fd.DirectorDagRunSummary:
        director, valid = _director(summary)
        if not valid:
            codes.add("DIRECTOR_SUMMARY_MALFORMED")
    else:
        codes.add("SUMMARY_NOT_TYPED")
        director = None

    runner = pipeline_result if isinstance(pipeline_result, Mapping) else {}
    results = worker_results if isinstance(worker_results, Mapping) else {}
    declared = runner.get("workers") if isinstance(runner.get("workers"), list) else []
    runner_rows = [s if isinstance(s, Mapping) else {} for s in declared]
    runner_ids = [_id(s.get("id")) for s in runner_rows]
    director_rows = director["workers"] if director else []
    director_ids = [w["worker_id"] for w in director_rows]

    if director is not None and director["pipeline_id"] != diagnostic.pipeline_id:
        codes.add("PIPELINE_ID_MISMATCH")
    if _has_duplicates(director_ids) or _has_duplicates(runner_ids) \
            or "DUPLICATE_WORKER_ID" in diagnostic.reason_codes:
        codes.add("DUPLICATE_WORKER_ID")
    if director is not None:
        if set(director_ids) != set(runner_ids) or len(director_ids) != len(runner_ids):
            codes.add("WORKER_SET_MISMATCH")
        elif director_ids != runner_ids:
            codes.add("WORKER_ORDER_MISMATCH")
    if diagnostic.missing_worker_ids or "MISSING_WORKER_RESULT" in diagnostic.reason_codes:
        codes.add("MISSING_WORKER_RESULT")
    if diagnostic.extra_worker_ids or diagnostic.unidentified_extra_results:
        codes.add("EXTRA_WORKER_RESULT")

    # Reconciled rows: Director order first, then every unmatched Runner
    # entry in Runner order; nothing declared by either source is dropped.
    pairs, used = [], set()
    for i, wid in enumerate(director_ids):
        j = next((k for k, r in enumerate(runner_ids) if wid is not None and r == wid and k not in used), None)
        used.add(j)
        pairs.append((i, j))
    pairs += [(None, j) for j in range(len(runner_ids)) if j not in used]
    rows = []
    for i, j in pairs:
        d_row = director_rows[i] if i is not None else None
        wid = d_row["worker_id"] if d_row else runner_ids[j]
        diag = diagnostic.workers[j] if j is not None and j < len(diagnostic.workers) else None
        adv = advisory.workers[j] if j is not None and j < len(advisory.workers) else None
        runner_state = _bounded(runner_rows[j].get("state"), fi.WORKER_STATES) if j is not None else None
        result_known = wid is not None and wid in results
        result_present = result_known and isinstance(results.get(wid), Mapping)
        row_codes = set()
        if d_row is None or j is None:
            row_codes.add("WORKER_SET_MISMATCH")
        elif i != j:
            row_codes.add("WORKER_ORDER_MISMATCH")
        if not result_known:
            row_codes.add("MISSING_WORKER_RESULT")
        if d_row is not None:
            expected = fd.WORKER_RECORD_PRESENT if result_present else fd.WORKER_RECORD_MISSING
            if d_row["worker_record"] != expected:
                row_codes.add("WORKER_RECORD_MISMATCH")
            if j is not None and d_row["worker_state"] != runner_state:
                row_codes.add("WORKER_STATE_MISMATCH")
            if d_row["runner_proven_success"] and (diag is None or diag.reason_codes != ("SUCCESS_CONSISTENT",)):
                row_codes.add("DIRECTOR_SUCCESS_UNVERIFIED")
        codes |= row_codes
        rows.append({
            "position": len(rows), "worker_id": wid, "director_index": i, "runner_index": j,
            "director_state": d_row["worker_state"] if d_row else None,
            "director_record": d_row["worker_record"] if d_row else None,
            "director_runner_proven_success": bool(d_row and d_row["runner_proven_success"]),
            "runner_state": runner_state, "result_present": result_present,
            "diagnostic_primary_reason": diag.primary_reason if diag else None,
            "advisory_category": adv.category if adv else None,
            "consistency_codes": list(_ordered(row_codes)),
        })

    if director is not None:
        if director["pipeline_status"] != diagnostic.native_status:
            codes.add("PIPELINE_STATUS_MISMATCH")
        if director["aggregate_status"] == "SUCCESS" and diagnostic.diagnostic_status != "SUCCESS":
            codes.add("DIRECTOR_SUCCESS_UNVERIFIED")
        if director["aggregate_status"] != diagnostic.diagnostic_status:
            codes.add("AGGREGATE_STATUS_MISMATCH")
    if _RUNNER_INTEGRITY_CODES & set(diagnostic.reason_codes):
        codes.add("RUNNER_EVIDENCE_INCONSISTENT")
    if advisory.category == "DIAGNOSTIC_UNUSABLE":
        codes.add("ADVISORY_DIAGNOSTIC_UNUSABLE")

    return DirectorRecoveryView(
        director=_canonical(director), diagnostic=_canonical(diagnostic.to_dict()),
        advisory=_canonical(advisory.to_dict()), workers=_canonical(rows), consistency_codes=_ordered(codes),
    )
