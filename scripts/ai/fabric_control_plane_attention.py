"""FCP-11F-06: Fabric Control Plane human attention view and blocking priority -
pure, deterministic, fail-closed, CONSULTATIVE / OBSERVATION-ONLY.

Consolidates, for ONE FCP-11B-02 `ControlPlaneSnapshot`, what needs a human,
the Direction, the Runner or a provider - and in which order - from:

* the snapshot itself (current Runner state: `pipeline_result.json`,
  `pipeline.json`, `worker.json`, `result.json`, their conditions and their
  cross-file agreement);
* optionally, the FCP-11C-03 `ControlPlaneEvidence` sealed for that same
  snapshot (attempt evidence, anomalies, completeness);
* optionally, FCP-6B-01 `PipelineRecoveryAdvisory` objects (one per pipeline)
  the caller's own FCP-6A-01 / 6B-01 run produced;
* optionally, FCP-10C-02 `RecoveryAdvice` objects keyed by pipeline id.

Nothing is read from disk, executed, retried, scheduled, authorized or
recommended in a binding way. The output names a cause, an attention class,
WHO could act (information only) and WHERE the condition originates; it
never carries an action, command or next step.

Public schema (`ControlPlaneAttention.to_dict`)
-----------------------------------------------
Per cause (`AttentionCause`): `source` (FCP11B_SNAPSHOT / FCP11C_EVIDENCE /
FCP6B_ADVISORY / FCP10C02_ADVICE), `source_code` (the source's own bounded
code: a Runner state, a contract cause, an agreement, an anomaly, an FCP-6 or
C02 reason), `reason` (local, `REASONS`), and the derived `attention_class`,
`actor` and `origin` fixed by `REASON_RULES`.
Per subject (`AttentionItem`, one per pipeline and per snapshot worker):
`pipeline_id`, `worker_id` (None for the pipeline itself), `attention_class`,
`actor`, `origin`, `primary_reason`, `causes` and `evidence` (the
`(kind, content_sha256)` of the PRESENT current sources it was derived
from).
Top level: `snapshot_revision`, `evidence_revision`, `observed_at_utc`,
`evidence_as_of_utc`, `attention_class`, `actor`, `origin`, `primary`
(subject + reason of the highest-priority cause, None when CLEAR),
`class_counts`, `bindings` (per source / pipeline: BOUND, ABSENT, NOT_BOUND,
STALE, REJECTED), view-level `causes`, prioritized `items`, the
zero-authority flags and `revision`.
Never public: any path, provider id or prose, message, branch, Work Order,
FCP-6 `observation` / `responsibility`, C02 `action`, deadline or verdict
text, and every other native field.

Decisions
---------
* Director and Runner keep ALL execution, recovery, authorization, Git,
  process and resource authority. No clock (the instant is the snapshot's),
  environment, file, process, network or store; FCP-11A-01 zero-authority
  flags plus `action_executable`, `recommendation_binding` and
  `authorization_created`, all False as read-only properties.
* Precedence is fixed and fail-closed (`ATTENTION_CLASSES`, highest first):
  SAFETY > PROCESS > EVIDENCE (incomplete / corrupt / unavailable /
  divergent evidence) > FAILURE (current failure) > AUTH > QUOTA > WAITING >
  UNKNOWN > CLEAR. Within a class, `REASONS` order decides; then source,
  source code, pipeline id and worker id. Equal inputs always give
  byte-equal output.
* Every PRESENT status contributes: a worker whose `worker.json` still says
  WAITING_PROVIDER_QUOTA while its `result.json` says FAILED shows both, plus
  STATUS_DIVERGENT; a WAIT never hides a FAIL. Neither side wins.
* CLEAR is earned, never defaulted. A worker is CLEAR only when every
  PRESENT status is SUCCESS, its agreement is CONSISTENT, and a BOUND
  FCP-11C-03 projection proves its last attempt (COMPLETED, work_status
  SUCCESS, evidence_complete TRUE, no anomaly, metadata / result PRESENT,
  reference agreement CONSISTENT); the item must cite those current
  sources (enforced on construction). Runner SUCCESS without that proof is
  SUCCESS_UNPROVEN (UNKNOWN). CLEAR is NOT an audit, CI, acceptance or
  approval; UNKNOWN is never promoted to READY / CLEAR, and nothing observed
  is NOTHING_OBSERVED (UNKNOWN).
* Advice is bound to current evidence or ignored. FCP-11C-03 must carry this
  snapshot's revision. An FCP-6B-01 advisory is BOUND only when its
  pipeline status, worker set and every worker `native_state` equal the
  snapshot's current `pipeline_result.json` values; a C02 advice only when
  each of its workers' `native_state` equals the current one and its
  `as_of_utc` lies between this pipeline's newest Runner write and the
  observation. Anything else is STALE (ADVISORY_STALE) or REJECTED
  (ADVISORY_REJECTED), and none of its reasons is used: an old WAIT advisory
  cannot add a wait, and cannot remove a current failure either.
* Reuse, never redefine: statuses, conditions, causes and agreements are
  FCP-11A-01 / 11B-02's; evidence facts are FCP-11C-03's; actors are
  FCP-10C-02 `ACTORS`; C02 is consumed by exact type. FCP-6A/6B are NOT
  imported (the FCP-6C-04 guard admits only its two approved adapters): as
  in FCP-10C-02, the advisory is recognized by type name and module, its
  zero-authority flags must read False, and its reason codes must belong to
  FCP-10C-02's pinned FCP-6A-01 mirror plus the two FCP-6B-01 integrity
  codes (`FCP6_REASON`, pinned to FCP-6 by the tests).

Limitations (documented, not implemented here)
-----------------------------------------------
* The factory ledger history (FCP-11D-04) and the resources view (FCP-11E-05)
  are not consolidated here; C02 provider-level recoveries (deadline,
  provider unknown) are not attributed to workers.
* An FCP-6B-01 advisory has no instant; its binding is by current values
  only, so a re-run that lands on identical values is indistinguishable.
* The type-name recognition of FCP-6 objects proves shape, not provenance:
  a forged object with the right name, flags and codes is consumed, but it
  can only ADD causes - it can never remove or lower a snapshot cause.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Optional

try:
    from scripts.ai import fabric_control_plane_contract as cp
    from scripts.ai import fabric_control_plane_evidence as ev
    from scripts.ai import fabric_control_plane_snapshot as snap
    from scripts.ai import fabric_resource_quota_contract as qc
    from scripts.ai import fabric_resource_quota_recovery as rq
    from scripts.ai import fabric_scheduler_contract as sc
    from scripts.ai import runner_pipeline as rp
except ImportError:  # pragma: no cover - direct script execution
    import fabric_control_plane_contract as cp  # type: ignore[no-redef]
    import fabric_control_plane_evidence as ev  # type: ignore[no-redef]
    import fabric_control_plane_snapshot as snap  # type: ignore[no-redef]
    import fabric_resource_quota_contract as qc  # type: ignore[no-redef]
    import fabric_resource_quota_recovery as rq  # type: ignore[no-redef]
    import fabric_scheduler_contract as sc  # type: ignore[no-redef]
    import runner_pipeline as rp  # type: ignore[no-redef]

SCHEMA = "fcp11f06-control-plane-attention-v1"
SCHEMA_VERSION = 1
MAX_ITEMS = cp.MAX_EVIDENCE_REFS

# ---------------------------------------------------------------------------
# Vocabularies
# ---------------------------------------------------------------------------

SAFETY = "SAFETY"
PROCESS = "PROCESS"
EVIDENCE = "EVIDENCE"
FAILURE = "FAILURE"
AUTH = "AUTH"
QUOTA = "QUOTA"
WAITING = "WAITING"
UNKNOWN = cp.OUTCOME_UNKNOWN
CLEAR = "CLEAR"
ATTENTION_CLASSES = (SAFETY, PROCESS, EVIDENCE, FAILURE, AUTH, QUOTA, WAITING, UNKNOWN, CLEAR)
_CLASS_RANK = {c: i for i, c in enumerate(ATTENTION_CLASSES)}

ACTORS = rq.ACTORS
_HUMAN, _DIRECTION, _RUNNER, _NONE = rq.ACTOR_HUMAN, rq.ACTOR_DIRECTION, rq.ACTOR_RUNNER, rq.ACTOR_NONE

ORIGIN_PROVIDER = "PROVIDER"
ORIGIN_RUNNER = "RUNNER"
ORIGIN_WORK = "WORK"
ORIGIN_EVIDENCE = "EVIDENCE"
ORIGIN_NONE = "NONE"
ORIGINS = (ORIGIN_PROVIDER, ORIGIN_RUNNER, ORIGIN_WORK, ORIGIN_EVIDENCE, ORIGIN_NONE)

SOURCE_SNAPSHOT = "FCP11B_SNAPSHOT"
SOURCE_EVIDENCE = "FCP11C_EVIDENCE"
SOURCE_FCP6 = "FCP6B_ADVISORY"
SOURCE_C02 = "FCP10C02_ADVICE"
SOURCES = (SOURCE_SNAPSHOT, SOURCE_EVIDENCE, SOURCE_FCP6, SOURCE_C02)

BOUND = "BOUND"
ABSENT = "ABSENT"
NOT_BOUND = "NOT_BOUND"
STALE = "STALE"
REJECTED = "REJECTED"
BINDINGS = (BOUND, ABSENT, NOT_BOUND, STALE, REJECTED)

EVIDENCE_PATH_REFUSED = "EVIDENCE_PATH_REFUSED"
SAFETY_REFUSAL = "SAFETY_REFUSAL"
PROCESS_UNRESOLVED = "PROCESS_UNRESOLVED"
INTERRUPTED = "INTERRUPTED"
EVIDENCE_CORRUPT = "EVIDENCE_CORRUPT"
EVIDENCE_UNAVAILABLE = "EVIDENCE_UNAVAILABLE"
RUNNER_EVIDENCE_INTEGRITY = "RUNNER_EVIDENCE_INTEGRITY"
STATUS_DIVERGENT = "STATUS_DIVERGENT"
EVIDENCE_ANOMALY = "EVIDENCE_ANOMALY"
EVIDENCE_INCOMPLETE = "EVIDENCE_INCOMPLETE"
CURRENT_FAILED = "CURRENT_FAILED"
CURRENT_BLOCKED = "CURRENT_BLOCKED"
CURRENT_PARTIAL = "CURRENT_PARTIAL"
CURRENT_CANCELLED = "CURRENT_CANCELLED"
CHECKPOINT_FAILED = "CHECKPOINT_FAILED"
ACCEPTANCE_FAILED = "ACCEPTANCE_FAILED"
PREFLIGHT_REFUSED = "PREFLIGHT_REFUSED"
VERDICT_NOT_PASS = "VERDICT_NOT_PASS"
PROVIDER_AUTH_BLOCKED = "PROVIDER_AUTH_BLOCKED"
PROVIDER_QUOTA_WAIT = "PROVIDER_QUOTA_WAIT"
RETRY_WAIT = "RETRY_WAIT"
IN_PROGRESS = "IN_PROGRESS"
AUDIT_PENDING = "AUDIT_PENDING"
ADVISORY_REJECTED = "ADVISORY_REJECTED"
ADVISORY_STALE = "ADVISORY_STALE"
SOURCE_NOT_BOUND = "SOURCE_NOT_BOUND"
PIPELINE_INCOMPLETE = "PIPELINE_INCOMPLETE"
OBSERVATION_INCOMPLETE = "OBSERVATION_INCOMPLETE"
STATUS_UNVERIFIABLE = "STATUS_UNVERIFIABLE"
EVIDENCE_MISSING = "EVIDENCE_MISSING"
WORK_UNVERIFIED = "WORK_UNVERIFIED"
SUCCESS_UNPROVEN = "SUCCESS_UNPROVEN"
NOTHING_OBSERVED = "NOTHING_OBSERVED"

# (reason, attention class, actor, origin), in canonical precedence. The
# actor is who COULD act (information only, never a permit); the origin is
# where the condition arises.
REASON_RULES = (
    (EVIDENCE_PATH_REFUSED, SAFETY, _HUMAN, ORIGIN_EVIDENCE),
    (SAFETY_REFUSAL, SAFETY, _HUMAN, ORIGIN_RUNNER),
    (PROCESS_UNRESOLVED, PROCESS, _HUMAN, ORIGIN_RUNNER),
    (INTERRUPTED, PROCESS, _HUMAN, ORIGIN_RUNNER),
    (EVIDENCE_CORRUPT, EVIDENCE, _HUMAN, ORIGIN_EVIDENCE),
    (EVIDENCE_UNAVAILABLE, EVIDENCE, _HUMAN, ORIGIN_EVIDENCE),
    (RUNNER_EVIDENCE_INTEGRITY, EVIDENCE, _HUMAN, ORIGIN_RUNNER),
    (STATUS_DIVERGENT, EVIDENCE, _HUMAN, ORIGIN_EVIDENCE),
    (EVIDENCE_ANOMALY, EVIDENCE, _HUMAN, ORIGIN_EVIDENCE),
    (EVIDENCE_INCOMPLETE, EVIDENCE, _HUMAN, ORIGIN_RUNNER),
    (CURRENT_FAILED, FAILURE, _DIRECTION, ORIGIN_WORK),
    (CURRENT_BLOCKED, FAILURE, _DIRECTION, ORIGIN_WORK),
    (CURRENT_PARTIAL, FAILURE, _DIRECTION, ORIGIN_WORK),
    (CURRENT_CANCELLED, FAILURE, _DIRECTION, ORIGIN_WORK),
    (CHECKPOINT_FAILED, FAILURE, _HUMAN, ORIGIN_RUNNER),
    (ACCEPTANCE_FAILED, FAILURE, _DIRECTION, ORIGIN_WORK),
    (PREFLIGHT_REFUSED, FAILURE, _HUMAN, ORIGIN_RUNNER),
    (VERDICT_NOT_PASS, FAILURE, _DIRECTION, ORIGIN_WORK),
    (PROVIDER_AUTH_BLOCKED, AUTH, _HUMAN, ORIGIN_PROVIDER),
    (PROVIDER_QUOTA_WAIT, QUOTA, _RUNNER, ORIGIN_PROVIDER),
    (RETRY_WAIT, WAITING, _RUNNER, ORIGIN_RUNNER),
    (IN_PROGRESS, WAITING, _RUNNER, ORIGIN_RUNNER),
    (AUDIT_PENDING, WAITING, _DIRECTION, ORIGIN_WORK),
    (ADVISORY_REJECTED, UNKNOWN, _HUMAN, ORIGIN_EVIDENCE),
    (ADVISORY_STALE, UNKNOWN, _HUMAN, ORIGIN_EVIDENCE),
    (SOURCE_NOT_BOUND, UNKNOWN, _HUMAN, ORIGIN_EVIDENCE),
    (PIPELINE_INCOMPLETE, UNKNOWN, _HUMAN, ORIGIN_RUNNER),
    (OBSERVATION_INCOMPLETE, UNKNOWN, _HUMAN, ORIGIN_EVIDENCE),
    (STATUS_UNVERIFIABLE, UNKNOWN, _RUNNER, ORIGIN_EVIDENCE),
    (EVIDENCE_MISSING, UNKNOWN, _RUNNER, ORIGIN_EVIDENCE),
    (WORK_UNVERIFIED, UNKNOWN, _HUMAN, ORIGIN_WORK),
    (SUCCESS_UNPROVEN, UNKNOWN, _HUMAN, ORIGIN_EVIDENCE),
    (NOTHING_OBSERVED, UNKNOWN, _HUMAN, ORIGIN_EVIDENCE),
)
REASONS = tuple(rule[0] for rule in REASON_RULES)
_RULE = {rule[0]: rule[1:] for rule in REASON_RULES}
_REASON_RANK = {r: i for i, r in enumerate(REASONS)}

# Current Runner state -> reason (None: SUCCESS needs proof, see `_worker`).
_W = rp.WorkerState
WORKER_STATE_REASON = {
    _W.FAILED.value: CURRENT_FAILED, _W.BLOCKED.value: CURRENT_BLOCKED, _W.PARTIAL.value: CURRENT_PARTIAL,
    _W.CANCELLED.value: CURRENT_CANCELLED, _W.INTERRUPTED.value: INTERRUPTED,
    _W.BLOCKED_PROVIDER_AUTH.value: PROVIDER_AUTH_BLOCKED, _W.WAITING_PROVIDER_QUOTA.value: PROVIDER_QUOTA_WAIT,
    _W.RETRY_WAIT.value: RETRY_WAIT, _W.QUEUED.value: IN_PROGRESS, _W.WAITING_DEPENDENCY.value: IN_PROGRESS,
    _W.READY.value: IN_PROGRESS, _W.RUNNING.value: IN_PROGRESS, _W.SUCCESS.value: None,
}
_P = rp.PipelineStatus
PIPELINE_STATUS_REASON = {
    _P.RUNNING.value: IN_PROGRESS, _P.DRAINING.value: IN_PROGRESS, _P.INCOMPLETE.value: PIPELINE_INCOMPLETE,
    _P.FAILED.value: CURRENT_FAILED, _P.BLOCKED.value: CURRENT_BLOCKED, _P.PARTIAL.value: CURRENT_PARTIAL,
    _P.CANCELLED.value: CURRENT_CANCELLED, _P.SUCCESS.value: None,
}
AGREEMENT_REASON = {
    snap.AGREEMENT_CONSISTENT: None, snap.AGREEMENT_DIVERGENT: STATUS_DIVERGENT,
    snap.AGREEMENT_NOT_LISTED: STATUS_DIVERGENT, snap.AGREEMENT_NOT_ON_DISK: STATUS_DIVERGENT,
    snap.AGREEMENT_UNVERIFIABLE: STATUS_UNVERIFIABLE,
}
_CONDITION_REASON = {cp.MISSING: EVIDENCE_MISSING, cp.CORRUPT: EVIDENCE_CORRUPT, cp.UNAVAILABLE: EVIDENCE_UNAVAILABLE}
_REFUSED_CAUSES = frozenset({cp.PATH_REFUSED, cp.LINK_REFUSED})

# FCP-6B-01, recognized without importing it (see the module docstring).
FCP6_MODULE = "runner_recovery_advisory"
FCP6_PIPELINE_TYPE = "PipelineRecoveryAdvisory"
FCP6_WORKER_TYPE = "WorkerRecoveryAdvisory"
FCP6_FLAGS = ("certified", "authorizes_action", "auto_retry_allowed", "execution_allowed", "resume_allowed",
              "merging_allowed")
FCP6_INTEGRITY_CODES = ("DIAGNOSTIC_NOT_TYPED", "DIAGNOSTIC_INCONSISTENT")
_FCP6_LOCAL = {
    "MALFORMED_EVIDENCE": RUNNER_EVIDENCE_INTEGRITY, "IDENTITY_MISMATCH": RUNNER_EVIDENCE_INTEGRITY,
    "DUPLICATE_WORKER_ID": RUNNER_EVIDENCE_INTEGRITY, "UNKNOWN_STATE": RUNNER_EVIDENCE_INTEGRITY,
    "RETRY_DECISION_UNRECOGNIZED": RUNNER_EVIDENCE_INTEGRITY, "EMPTY_PIPELINE": RUNNER_EVIDENCE_INTEGRITY,
    "AGGREGATE_CONTRADICTION": STATUS_DIVERGENT, "CONFLICTING_EVIDENCE": STATUS_DIVERGENT,
    "EXTRA_WORKER_RESULT": STATUS_DIVERGENT, "PROCESS_TERMINATION_UNRESOLVED": PROCESS_UNRESOLVED,
    "SAFETY_REFUSAL": SAFETY_REFUSAL, "INTERRUPTED_OPERATOR_REVIEW": INTERRUPTED,
    "PROVIDER_AUTH_BLOCKED": PROVIDER_AUTH_BLOCKED, "CHECKPOINT_FAILED": CHECKPOINT_FAILED,
    "ACCEPTANCE_FAILED": ACCEPTANCE_FAILED, "PREFLIGHT_REFUSED": PREFLIGHT_REFUSED,
    "DEPENDENCY_CANCELLED": CURRENT_CANCELLED, "NATIVE_CANCELLED": CURRENT_CANCELLED,
    "NATIVE_FAILED": CURRENT_FAILED, "NATIVE_BLOCKED": CURRENT_BLOCKED, "PARTIAL_COMPLETION": CURRENT_PARTIAL,
    "EVIDENCE_INCOMPLETE": EVIDENCE_INCOMPLETE, "PROVIDER_QUOTA_WAIT": PROVIDER_QUOTA_WAIT,
    "TRANSIENT_RETRY_WAIT": RETRY_WAIT, "NOT_TERMINAL": IN_PROGRESS, "MISSING_WORKER_RESULT": EVIDENCE_MISSING,
    "EVIDENCE_MISSING": EVIDENCE_MISSING, "EVIDENCE_UNPROVEN": SUCCESS_UNPROVEN, "SUCCESS_CONSISTENT": None,
}
FCP6_REASON = {code: _FCP6_LOCAL[code] for code in rq.FI_REASON_PRECEDENCE}
FCP6_REASON.update({code: RUNNER_EVIDENCE_INTEGRITY for code in FCP6_INTEGRITY_CODES})

C02_REASON = {
    rq.RUNNER_EVIDENCE_INTEGRITY: RUNNER_EVIDENCE_INTEGRITY, rq.WORKER_PROVIDER_MISMATCH: RUNNER_EVIDENCE_INTEGRITY,
    rq.PROCESS_TERMINATION_UNRESOLVED: PROCESS_UNRESOLVED, rq.SAFETY_REFUSAL: SAFETY_REFUSAL,
    rq.INTERRUPTED_OPERATOR_REVIEW: INTERRUPTED, rq.PROVIDER_AUTH_BLOCKED: PROVIDER_AUTH_BLOCKED,
    rq.CONTINUATION_EVIDENCE_UNRECOGNIZED: RUNNER_EVIDENCE_INTEGRITY, rq.RUNNER_WORK_FAILED: CURRENT_FAILED,
    rq.RUNNER_WORK_BLOCKED: CURRENT_BLOCKED, rq.NATIVE_CONTINUATION_PENDING: IN_PROGRESS,
    rq.PROVIDER_QUOTA_WAIT: PROVIDER_QUOTA_WAIT, rq.TRANSIENT_RETRY_WAIT: RETRY_WAIT, rq.NOT_TERMINAL: IN_PROGRESS,
    rq.PROVIDER_VERDICT_DIVERGENT: VERDICT_NOT_PASS, rq.AUDITOR_VERDICT_NOT_PASS: VERDICT_NOT_PASS,
    rq.PROVIDER_VERDICT_NOT_PASS: VERDICT_NOT_PASS, rq.WORK_UNVERIFIED: WORK_UNVERIFIED,
    rq.AUDITOR_VERDICT_ABSENT: AUDIT_PENDING,
}

# Current sources a CLEAR subject must cite.
_WORKER_PROOF = ("WORKER_RECORD", "WORKER_RESULT", "ATTEMPT_METADATA", "ATTEMPT_RESULT")
_PIPELINE_PROOF = ("PIPELINE_RECORD", "PIPELINE_RESULT")
_MAX_ITEM_EVIDENCE = len(_WORKER_PROOF) + 1


# ---------------------------------------------------------------------------
# Guarantees
# ---------------------------------------------------------------------------

class _AttentionGuarantees(cp._ControlPlaneGuarantees):
    """FCP-11A-01 flags plus: no executable action, no binding
    recommendation, no authorization."""

    @property
    def action_executable(self) -> bool:
        return False

    @property
    def recommendation_binding(self) -> bool:
        return False

    @property
    def authorization_created(self) -> bool:
        return False

    @staticmethod
    def _guarantees() -> dict:
        guarantees = cp._ControlPlaneGuarantees._guarantees()
        guarantees.update(action_executable=False, recommendation_binding=False, authorization_created=False)
        return guarantees


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AttentionCause(_AttentionGuarantees):
    """One traced cause: the source, its own code and the local reason."""
    source: str
    source_code: str
    reason: str

    def __post_init__(self):
        if not (cp._in(self.source, SOURCES) and cp.valid_code(self.source_code) and cp._in(self.reason, REASONS)):
            raise ValueError("cause outside its vocabulary")

    @property
    def attention_class(self) -> str:
        return _RULE[self.reason][0]

    @property
    def actor(self) -> str:
        return _RULE[self.reason][1]

    @property
    def origin(self) -> str:
        return _RULE[self.reason][2]

    def sort_key(self) -> tuple:
        return _REASON_RANK[self.reason], SOURCES.index(self.source), self.source_code

    def to_dict(self) -> dict:
        return {"source": self.source, "source_code": self.source_code, "reason": self.reason,
                "attention_class": self.attention_class, "actor": self.actor, "origin": self.origin}


def _check_causes(causes) -> None:
    keys = [c.sort_key() for c in causes] if type(causes) is tuple and all(
        type(c) is AttentionCause for c in causes) else None
    if keys is None or keys != sorted(set(keys)):
        raise ValueError("causes must be sorted unique AttentionCauses")


@dataclass(frozen=True)
class AttentionItem(_AttentionGuarantees):
    """One pipeline (`worker_id` None) or worker. CLEAR exactly when it has
    no cause, and then it must cite the current sources that prove it."""
    pipeline_id: str
    worker_id: Optional[str]
    causes: tuple = ()
    evidence: tuple = ()  # sorted unique (kind, content_sha256)

    def __post_init__(self):
        if not (cp.valid_id(self.pipeline_id) and cp._optional(self.worker_id, cp.valid_id)):
            raise ValueError("subject must be valid ids")
        _check_causes(self.causes)
        if not (type(self.evidence) is tuple and len(self.evidence) <= _MAX_ITEM_EVIDENCE
                and all(type(e) is tuple and len(e) == 2 and cp._in(e[0], cp.EVIDENCE_KINDS)
                        and type(e[1]) is str and sc._FINGERPRINT_RE.fullmatch(e[1]) for e in self.evidence)
                and list(self.evidence) == sorted(set(self.evidence))):
            raise ValueError("evidence must be sorted unique (kind, sha256) pairs")
        proof = _PIPELINE_PROOF if self.worker_id is None else _WORKER_PROOF
        if not self.causes and not set(proof) <= {kind for kind, _ in self.evidence}:
            raise ValueError("CLEAR must cite the current sources that prove it")

    @property
    def attention_class(self) -> str:
        return self.causes[0].attention_class if self.causes else CLEAR

    @property
    def actor(self) -> str:
        return self.causes[0].actor if self.causes else _NONE

    @property
    def origin(self) -> str:
        return self.causes[0].origin if self.causes else ORIGIN_NONE

    @property
    def primary_reason(self) -> Optional[str]:
        return self.causes[0].reason if self.causes else None

    def sort_key(self) -> tuple:
        first = self.causes[0].sort_key() if self.causes else (len(REASONS), 0, "")
        return (_CLASS_RANK[self.attention_class],) + first + (self.pipeline_id, self.worker_id or "")

    def to_dict(self) -> dict:
        return {
            "pipeline_id": self.pipeline_id, "worker_id": self.worker_id, "attention_class": self.attention_class,
            "actor": self.actor, "origin": self.origin, "primary_reason": self.primary_reason,
            "causes": [c.to_dict() for c in self.causes],
            "evidence": [{"kind": k, "content_sha256": s} for k, s in self.evidence],
        }


def _binding_key(binding) -> tuple:
    return SOURCES.index(binding[0]), binding[1] or "", BINDINGS.index(binding[2])


@dataclass(frozen=True)
class ControlPlaneAttention(_AttentionGuarantees):
    """Sealed, prioritized attention view of one snapshot. `causes` are the
    view-level ones (root, unbound sources, nothing observed)."""
    snapshot_revision: str
    observed_at_utc: str
    evidence_as_of_utc: Optional[str] = None
    evidence_revision: Optional[str] = None
    bindings: tuple = ()  # sorted (source, pipeline_id or None, binding)
    causes: tuple = ()
    items: tuple = ()

    def __post_init__(self):
        sha = lambda v: type(v) is str and sc._FINGERPRINT_RE.fullmatch(v) is not None  # noqa: E731
        utc = lambda v: type(v) is str and cp.normalized_utc(v) == v  # noqa: E731
        if not (sha(self.snapshot_revision) and cp._optional(self.evidence_revision, sha)):
            raise ValueError("revisions must be sha256")
        if not (utc(self.observed_at_utc) and cp._optional(self.evidence_as_of_utc, utc)):
            raise ValueError("instants must be normalized UTC")
        if not (type(self.bindings) is tuple and all(
                type(b) is tuple and len(b) == 3 and cp._in(b[0], SOURCES) and cp._optional(b[1], cp.valid_id)
                and cp._in(b[2], BINDINGS) for b in self.bindings)
                and list(self.bindings) == sorted(self.bindings, key=_binding_key)):
            raise ValueError("bindings must be sorted (source, pipeline_id, binding) triples")
        _check_causes(self.causes)
        keys = [(i.pipeline_id, i.worker_id or "") for i in self.items] if type(self.items) is tuple and all(
            type(i) is AttentionItem for i in self.items) else None
        if keys is None or len(keys) != len(set(keys)) or len(keys) > MAX_ITEMS \
                or [i.sort_key() for i in self.items] != sorted(i.sort_key() for i in self.items):
            raise ValueError("items must be unique AttentionItems in priority order")
        if not (self.causes or self.items):
            raise ValueError("an empty view is NOTHING_OBSERVED, never CLEAR")

    def _top(self) -> Optional[tuple]:
        """`(pipeline_id, worker_id, cause)` of the highest-priority cause."""
        ranked = [((_CLASS_RANK[c.attention_class],) + c.sort_key() + ("", ""), (None, None, c)) for c in self.causes]
        ranked += [((_CLASS_RANK[i.attention_class],) + i.causes[0].sort_key() + (i.pipeline_id, i.worker_id or ""),
                    (i.pipeline_id, i.worker_id, i.causes[0])) for i in self.items if i.causes]
        return min(ranked, key=lambda r: r[0])[1] if ranked else None

    @property
    def attention_class(self) -> str:
        top = self._top()
        return CLEAR if top is None else top[2].attention_class

    @property
    def class_counts(self) -> dict:
        counts = {c: 0 for c in ATTENTION_CLASSES}
        for item in self.items:
            counts[item.attention_class] += 1
        return counts

    def _body(self) -> dict:
        top = self._top()
        return {
            "schema": SCHEMA, "schema_version": SCHEMA_VERSION, "snapshot_revision": self.snapshot_revision,
            "evidence_revision": self.evidence_revision, "observed_at_utc": self.observed_at_utc,
            "evidence_as_of_utc": self.evidence_as_of_utc, "attention_class": self.attention_class,
            "actor": _NONE if top is None else top[2].actor,
            "origin": ORIGIN_NONE if top is None else top[2].origin,
            "primary": None if top is None else {"pipeline_id": top[0], "worker_id": top[1], **top[2].to_dict()},
            "class_counts": self.class_counts,
            "bindings": [{"source": s, "pipeline_id": p, "binding": b} for s, p, b in self.bindings],
            "causes": [c.to_dict() for c in self.causes], "items": [i.to_dict() for i in self.items],
            **_AttentionGuarantees._guarantees(),
        }

    @property
    def revision(self) -> str:
        return hashlib.sha256(sc._canonical(self._body()).encode("ascii")).hexdigest()

    def to_dict(self) -> dict:
        return {**self._body(), "revision": self.revision}


def canonical_json(attention: ControlPlaneAttention) -> str:
    """Stable, sorted, compact, size-bounded serialization of the exact type."""
    if type(attention) is not ControlPlaneAttention:
        raise TypeError("canonical_json accepts only a ControlPlaneAttention")
    text = sc._canonical(ControlPlaneAttention.to_dict(attention))
    if len(text) > cp.MAX_CANONICAL_JSON_BYTES:
        raise ValueError("canonical attention exceeds MAX_CANONICAL_JSON_BYTES")
    return text


# ---------------------------------------------------------------------------
# Causes from the current sources
# ---------------------------------------------------------------------------

class _Causes:
    """Collects (source, code, reason) triples, deduplicated."""

    def __init__(self):
        self.found: set = set()

    def add(self, source: str, code: str, reason: Optional[str]) -> None:
        if reason is not None:
            self.found.add((source, code, reason))

    def condition(self, source: str, condition: str, cause: Optional[str]) -> None:
        if condition != cp.PRESENT:
            self.add(source, cause, EVIDENCE_PATH_REFUSED if cause in _REFUSED_CAUSES else _CONDITION_REASON[condition])

    def status(self, source: str, status: cp.StatusView, vocabulary: dict) -> None:
        if status.condition == cp.PRESENT:
            self.add(source, status.source_value, vocabulary[status.source_value])
        else:
            self.condition(source, status.condition, status.cause)

    def ordered(self) -> tuple:
        return tuple(sorted((AttentionCause(*f) for f in self.found), key=AttentionCause.sort_key))


def _refs(snapshot) -> dict:
    """`(kind, pipeline_id, worker_id) -> sha256` of the snapshot's PRESENT refs."""
    return {(r.kind, r.pipeline_id, r.worker_id): r.content_sha256
            for r in snapshot.observation.evidence if r.condition == cp.PRESENT}


def _cite(refs: dict, kinds: tuple, pid: str, wid: Optional[str]) -> list:
    return [(k, refs[(k, pid, wid)]) for k in kinds if (k, pid, wid) in refs]


def _last_attempt_proven(we) -> bool:
    if we is None or we.record_condition != cp.PRESENT or not we.attempts:
        return False
    last = we.attempts[-1]
    present = {a.kind for a in last.artifacts if a.condition == cp.PRESENT}
    return (we.reference_agreement == snap.AGREEMENT_CONSISTENT and last.attempt_status == ev._ATTEMPT_COMPLETED
            and last.work_status == _W.SUCCESS.value and last.evidence_complete == ev.TRUE and not last.anomalies
            and {"ATTEMPT_METADATA", "ATTEMPT_RESULT"} <= present)


def _evidence_causes(found: _Causes, we) -> None:
    S = SOURCE_EVIDENCE
    found.condition(S, we.record_condition, we.record_cause)
    found.add(S, we.reference_agreement, AGREEMENT_REASON[we.reference_agreement])
    for attempt in we.attempts:
        for anomaly in attempt.anomalies:
            found.add(S, anomaly, EVIDENCE_ANOMALY)
        if attempt.location_condition != cp.MISSING:
            found.condition(S, attempt.location_condition, attempt.location_cause)
        for artifact in attempt.artifacts:
            if artifact.condition != cp.MISSING:
                found.condition(S, artifact.condition, artifact.cause)
    if we.attempts and we.attempts[-1].evidence_complete == ev.FALSE:
        found.add(S, EVIDENCE_INCOMPLETE, EVIDENCE_INCOMPLETE)


def _worker(w, refs: dict, we, evidence_bound: bool, advised: list) -> AttentionItem:
    found = _Causes()
    S = SOURCE_SNAPSHOT
    statuses = ((w.listed_status,) if w.listed is True else ()) + (w.record_status,)
    for status in statuses:
        found.status(S, status, WORKER_STATE_REASON)
    present = [s for s in statuses + (w.result_status,) if s.condition == cp.PRESENT]
    terminal = any(s.lifecycle == cp.LIFECYCLE_TERMINAL for s in present)
    if w.result_status.condition != cp.MISSING or terminal:  # no result yet is normal before a terminal state
        found.status(S, w.result_status, WORKER_STATE_REASON)
    found.add(S, w.agreement, AGREEMENT_REASON[w.agreement])
    if evidence_bound and we is not None:
        _evidence_causes(found, we)
    for source, code, reason in advised:
        found.add(source, code, reason)
    claims_success = any(s.source_value == _W.SUCCESS.value for s in present)
    proven = evidence_bound and _last_attempt_proven(we)
    if claims_success and not proven:
        found.add(S, _W.SUCCESS.value, SUCCESS_UNPROVEN)
    if not present:
        found.add(S, w.agreement, STATUS_UNVERIFIABLE)
    cited = _cite(refs, ("WORKER_RECORD", "WORKER_RESULT"), w.pipeline_id, w.worker_id)
    if proven:
        cited += [(a.kind, a.content_sha256) for a in we.attempts[-1].artifacts if a.condition == cp.PRESENT]
    return AttentionItem(w.pipeline_id, w.worker_id, found.ordered(), tuple(sorted(set(cited))))


def _pipeline(p, refs: dict, workers: tuple, advised: list) -> AttentionItem:
    found = _Causes()
    S = SOURCE_SNAPSHOT
    view = p.view
    found.status(S, view.status, PIPELINE_STATUS_REASON)
    found.status(S, p.record_status, PIPELINE_STATUS_REASON)
    found.add(S, p.agreement, AGREEMENT_REASON[p.agreement])
    found.condition(S, p.workers_condition, p.workers_cause)
    if p.workers_omitted:
        found.add(S, "WORKERS_OMITTED", OBSERVATION_INCOMPLETE)
    if view.rejected_workers or view.malformed_fields:
        found.add(S, cp.FIELD_MALFORMED, RUNNER_EVIDENCE_INTEGRITY)
    if not p.workers:
        found.add(S, "NO_WORKERS", NOTHING_OBSERVED)
    for source, code, reason in advised:
        found.add(source, code, reason)
    succeeded = _P.SUCCESS.value in {view.status.source_value, p.record_status.source_value}
    if succeeded and any(w.causes for w in workers):
        found.add(S, _P.SUCCESS.value, SUCCESS_UNPROVEN)
    cited = _cite(refs, _PIPELINE_PROOF, p.pipeline_id, None)
    return AttentionItem(p.pipeline_id, None, found.ordered(), tuple(sorted(cited)))


# ---------------------------------------------------------------------------
# Advice binding (FCP-6B-01 / FCP-10C-02)
# ---------------------------------------------------------------------------

def _fcp6_reasons(obj, type_name: str) -> Optional[tuple]:
    """The advisory's reason codes when it is an FCP-6B-01 object of
    `type_name` with every zero-authority flag False; else None."""
    try:
        kind = type(obj)
        if kind.__name__ != type_name or kind.__module__.rsplit(".", 1)[-1] != FCP6_MODULE:
            return None
        if any(getattr(obj, flag) is not False for flag in FCP6_FLAGS):
            return None
        reasons = obj.reasons
    except Exception:  # noqa: BLE001 - a foreign object fails closed
        return None
    if type(reasons) is not tuple or not reasons or not all(cp._in(r, FCP6_REASON) for r in reasons):
        return None
    return reasons


def _listed(p) -> dict:
    return {w.worker_id: w.status for w in p.view.workers}


def _same_state(listed: dict, wid, state) -> bool:
    status = listed.get(wid) if type(wid) is str else None
    return status is not None and status.condition == cp.PRESENT and status.source_value == state


def _bind_fcp6(advisory, p) -> tuple:
    """`(binding, pipeline_reasons, {worker_id: reasons})`."""
    reasons = _fcp6_reasons(advisory, FCP6_PIPELINE_TYPE)
    try:
        workers, native = advisory.workers, advisory.native_status
    except Exception:  # noqa: BLE001
        return REJECTED, (), {}
    if reasons is None or type(workers) is not tuple:
        return REJECTED, (), {}
    per = {}
    for w in workers:
        own = _fcp6_reasons(w, FCP6_WORKER_TYPE)
        try:
            wid, state = w.worker_id, w.native_state
        except Exception:  # noqa: BLE001
            return REJECTED, (), {}
        if own is None or not cp.valid_id(wid) or wid in per:
            return REJECTED, (), {}
        per[wid] = (state, own)
    view, listed = p.view, _listed(p)
    if (view.status.condition != cp.PRESENT or native != view.status.source_value or view.rejected_workers
            or set(per) != set(listed) or not all(_same_state(listed, wid, s) for wid, (s, _) in per.items())):
        return STALE, (), {}
    return BOUND, reasons, {wid: own for wid, (_, own) in per.items()}


def _bind_c02(advice, p, observed_at_utc: str) -> tuple:
    """`(binding, {worker_id: reasons})`. The advice must postdate this
    pipeline's newest Runner write and not postdate the observation."""
    if type(advice) is not rq.RecoveryAdvice or advice.outcome == rq.REFUSED:
        return REJECTED, {}
    as_of = qc.parse_utc(advice.as_of_utc)
    if as_of is None or as_of > qc.parse_utc(observed_at_utc) or any(as_of < qc.parse_utc(i) for i in p.instants()):
        return STALE, {}
    listed = _listed(p)
    if not all(_same_state(listed, w.worker_id, w.native_state) for w in advice.workers):
        return STALE, {}
    return BOUND, {w.worker_id: w.reasons for w in advice.workers}


def _pipeline_id_of(advisory) -> Optional[str]:
    try:
        pid = advisory.pipeline_id
    except Exception:  # noqa: BLE001
        return None
    return pid if cp.valid_id(pid) else None


def _advice(snapshot, fcp6_advisories, c02_advice) -> tuple:
    """`(bindings, view_causes, pipeline_advised, worker_advised)` where the
    advised maps hold (source, code, reason) triples of BOUND advice only."""
    pipelines = {p.pipeline_id: p for p in snapshot.pipelines}
    bindings, view, by_pipeline, by_worker = [], _Causes(), {}, {}

    def unbound(source, pid, binding):
        bindings.append((source, pid, binding))
        reason = {NOT_BOUND: SOURCE_NOT_BOUND, STALE: ADVISORY_STALE, REJECTED: ADVISORY_REJECTED}[binding]
        target = by_pipeline.setdefault(pid, []) if pid in pipelines else None
        if target is None:
            view.add(source, source, reason)
        else:
            target.append((source, source, reason))

    def advised(source, pid, wid, codes, mapping):
        target = by_pipeline.setdefault(pid, []) if wid is None else by_worker.setdefault((pid, wid), [])
        target.extend((source, code, mapping[code]) for code in codes if mapping[code] is not None)

    grouped: dict = {}
    for advisory in fcp6_advisories:
        grouped.setdefault(_pipeline_id_of(advisory), []).append(advisory)
    for pid in sorted(grouped, key=lambda k: k or ""):
        group = grouped[pid]
        if pid is None or len(group) > 1:
            for _ in group:
                unbound(SOURCE_FCP6, pid, REJECTED)
        elif pid not in pipelines:
            unbound(SOURCE_FCP6, pid, NOT_BOUND)
        else:
            binding, own, per = _bind_fcp6(group[0], pipelines[pid])
            if binding != BOUND:
                unbound(SOURCE_FCP6, pid, binding)
                continue
            bindings.append((SOURCE_FCP6, pid, BOUND))
            advised(SOURCE_FCP6, pid, None, own, FCP6_REASON)
            for wid, codes in per.items():
                advised(SOURCE_FCP6, pid, wid, codes, FCP6_REASON)
    for pid, advice in sorted(c02_advice.items(), key=lambda kv: kv[0] if type(kv[0]) is str else ""):
        pid = pid if cp.valid_id(pid) else None
        if pid is None:
            unbound(SOURCE_C02, None, REJECTED)
            continue
        if pid not in pipelines:
            unbound(SOURCE_C02, pid, NOT_BOUND)
            continue
        binding, per = _bind_c02(advice, pipelines[pid], snapshot.observation.observed_at_utc)
        if binding != BOUND:
            unbound(SOURCE_C02, pid, binding)
            continue
        bindings.append((SOURCE_C02, pid, BOUND))
        for wid, codes in per.items():
            advised(SOURCE_C02, pid, wid, codes, C02_REASON)
    return bindings, view, by_pipeline, by_worker


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------

def observe_attention(snapshot, *, evidence=None, fcp6_advisories=(), c02_advice=None) -> ControlPlaneAttention:
    """Consultative attention view of `snapshot` (an FCP-11B-02
    `ControlPlaneSnapshot`) with, optionally, the FCP-11C-03 `evidence` of
    that snapshot, FCP-6B-01 `PipelineRecoveryAdvisory` objects
    (`fcp6_advisories`, a tuple / list) and FCP-10C-02 `RecoveryAdvice`
    objects keyed by pipeline id (`c02_advice`). Raises `TypeError` only
    for a wrong container / projection type (caller error); everything
    stale, unbound or malformed is reported, never raised nor echoed."""
    if type(snapshot) is not snap.ControlPlaneSnapshot:
        raise TypeError("snapshot must be a ControlPlaneSnapshot")
    if evidence is not None and type(evidence) is not ev.ControlPlaneEvidence:
        raise TypeError("evidence must be a ControlPlaneEvidence")
    if type(fcp6_advisories) not in (tuple, list):
        raise TypeError("fcp6_advisories must be a tuple or list")
    if c02_advice is None:
        c02_advice = {}
    if not isinstance(c02_advice, Mapping):
        raise TypeError("c02_advice must be a mapping of pipeline id to RecoveryAdvice")
    if len(fcp6_advisories) > cp.MAX_PIPELINES or len(c02_advice) > cp.MAX_PIPELINES:
        raise ValueError("at most MAX_PIPELINES advisories per source")

    bindings, view, by_pipeline, by_worker = _advice(snapshot, tuple(fcp6_advisories), dict(c02_advice))
    bindings.append((SOURCE_SNAPSHOT, None, BOUND))
    view.condition(SOURCE_SNAPSHOT, snapshot.root_condition, snapshot.root_cause)
    if snapshot.pipelines_omitted:
        view.add(SOURCE_SNAPSHOT, "PIPELINES_OMITTED", OBSERVATION_INCOMPLETE)
    if snapshot.root_condition == cp.PRESENT and not snapshot.pipelines:
        view.add(SOURCE_SNAPSHOT, "NO_PIPELINES", NOTHING_OBSERVED)

    evidence_bound = evidence is not None and evidence.snapshot_revision == snapshot.revision
    if evidence is None:
        bindings.append((SOURCE_EVIDENCE, None, ABSENT))
    elif not evidence_bound:
        bindings.append((SOURCE_EVIDENCE, None, NOT_BOUND))
        view.add(SOURCE_EVIDENCE, SOURCE_EVIDENCE, SOURCE_NOT_BOUND)
    else:
        bindings.append((SOURCE_EVIDENCE, None, BOUND))
        view.condition(SOURCE_EVIDENCE, evidence.root_condition, evidence.root_cause)
        if evidence.workers_omitted:
            view.add(SOURCE_EVIDENCE, "WORKERS_OMITTED", OBSERVATION_INCOMPLETE)
    worker_evidence = {(w.pipeline_id, w.worker_id): w for w in evidence.workers} if evidence_bound else {}

    refs = _refs(snapshot)
    items = []
    for p in snapshot.pipelines:
        workers = tuple(_worker(w, refs, worker_evidence.get((p.pipeline_id, w.worker_id)), evidence_bound,
                                by_worker.get((p.pipeline_id, w.worker_id), [])) for w in p.workers)
        items.append(_pipeline(p, refs, workers, by_pipeline.get(p.pipeline_id, [])))
        items.extend(workers)
    return ControlPlaneAttention(
        snapshot.revision, snapshot.observation.observed_at_utc, evidence_as_of_utc=snapshot.evidence_as_of_utc,
        evidence_revision=evidence.revision if evidence_bound else None,
        bindings=tuple(sorted(bindings, key=_binding_key)), causes=view.ordered(),
        items=tuple(sorted(items, key=AttentionItem.sort_key)),
    )
