"""FCP-12A-03: Self-Dogfood Runner evidence reader V1 - strictly READ-ONLY,
bounded, deterministic, fail-closed, ADVISORY-ONLY normalization of the REAL
Runner evidence of one governed self-dogfood worker attempt.

What it answers
---------------
"Does the Runner's own persisted evidence, read from the explicit Runner
state root and factory ledger root, corroborate that this worker's latest
attempt is a Runner-certified SUCCESS whose checkpoint commit is the target
HEAD the caller observed?" - and nothing more. The best outcome is
`CORROBORATED`: an evidence verdict, never an audit, a CI result, an
approval or an authorization. Provider words (`stdout.txt`, `stderr.txt`,
`prompt.txt`, the provider's own `work_status`) are never a status source.

Files opened (and only these, all under the caller's two roots)
---------------------------------------------------------------
Runner state root (`runner_pipeline` layout, FCP-11A-01 inventory)::

    <pipeline_id>/pipeline_result.json                  PIPELINE_RESULT
    <pipeline_id>/workers/<worker_id>/worker.json       WORKER_RECORD
    <pipeline_id>/workers/<worker_id>/result.json       WORKER_RESULT
    _evidence/<evidence_root_key>/<run_id>/metadata.json      ATTEMPT_METADATA
    _evidence/<evidence_root_key>/<run_id>/result.json        ATTEMPT_RESULT
    _evidence/<evidence_root_key>/<run_id>/work_product.json  ATTEMPT_WORK_PRODUCT

Factory ledger root (`runner_factory_ledger`)::

    events.jsonl                                        FACTORY_EVENTS

Paths are composed only by `EvidenceRef.relative_parts` from validated ids,
except the attempt directory, which is the `evidence_dir` the Runner
persisted. It is accepted only when it is canonical (FCP-12A-02
`canonical_path_key`: absolute, no `..`, no UNC / device prefix, no 8.3
alias), exactly the derived CURRENT layout for THIS worker and THIS run id
(FCP-11C-03 `_locate`: under the root, every component a plain directory
that is its own real path), and identical to what `result.json` and
`work_product.json` reference. Every file goes through FCP-10D-01
`read_input_bytes` (link / junction / alias refusal, descriptor identity,
bounded size) with an lstat identity re-check (changed during read: refused).

Reuse, never redefine
---------------------
Vocabularies and record grammar are the Runner's own (`WorkerState`,
`PIPELINE_SCHEMA_VERSION`, `WORK_PRODUCT_SCHEMA_VERSION`,
`WORK_STATUS_SOURCE_*`, `COMPLETION_POLICY_RUNNER_ACCEPTANCE`,
`CHECKPOINT_POLICY_ON_SUCCESS`, `build_checkpoint_message`,
`extract_paths_from_porcelain_line`, `path_is_authorized`,
`RUNNER_EVIDENCE_ARTIFACT_FILENAMES`, `LEDGER_SCHEMA_VERSION`,
`EVENT_TYPES`); the completion mode is the Director's
`_classify_completion_mode`; ids / commits / leaves / evidence references are
FCP-11A-01's; `pipeline_result.json` is projected by FCP-11A-01
`project_pipeline_result`; the zero-authority flags extend FCP-12A-01.

Rules (all must hold for CORROBORATED; every failure is a reason)
-----------------------------------------------------------------
* Ids: worker.json `spec.id`, both result files, `work_product.json` and
  `metadata.json` name this pipeline / worker / attempt / run id / provider.
* Freshness: the worker `result.json` reports exactly the attempts in
  `worker.json` and was written after the latest attempt ended;
  `pipeline_result.json` agrees on state, attempt count, checkpoint policy
  and commit. A re-queued or rewritten worker is STALE / DIVERGENT.
* Status: worker state SUCCESS everywhere; latest attempt COMPLETED,
  executed, process confirmed stopped, runner_state SUCCESS, retry decision
  `NONE:SUCCESS`; work_status SUCCESS certified by `RUNNER_ACCEPTANCE` under
  `runner_acceptance` with acceptance PASSED. The attempt's own provider
  `result.json` must stay provider-sourced and agree with the recorded raw
  provider status (a provider file claiming Runner certification is
  tampering, not proof).
* Completeness / safety: evidence_complete everywhere, no evidence errors,
  SAFE safety verdict, no unauthorized path, HEAD / branch unchanged by the
  provider, work product complete and identical in all three attempt files.
* Scope: every changed path is a safe repo-relative path inside both the
  manifest's `authorize_path` and the work product's scopes, never a
  protected historical CI workflow.
* Checkpoint: `ON_SUCCESS` policy, decision CREATED from the current
  attempt's work product, a commit other than the base HEAD, the exact
  Runner message and exactly the work product's pathspecs, identical in
  `worker.json` and `result.json`.
* Ledger: every line strict, versioned, known and uniquely identified; after
  the worker's latest WORKER_STARTED (base = attempt base HEAD) exactly one
  CHECKPOINT_CREATED (base -> commit), WORKER_FINISHED SUCCESS and
  WORK_PRODUCT_CREATED at that commit. Any certification / closure event or
  claim for this worker is refused: authorization is never read from
  evidence.
* HEAD: the caller-observed target HEAD (captured with governed Git, e.g.
  FCP-12A-02) equals the checkpoint commit.

Separate axes, never merged: `runner_state` is what the Runner recorded;
`evidence_verdict` is this reader's decision; `audit_verdict` is always
UNKNOWN (the Runner state holds no audit) and `authorization` is always NONE.

Limitations (documented, fail-closed)
-------------------------------------
* Only the CHECKPOINT completion mode is corroborated: a SUCCESS_NOOP attempt
  has no work product to bind, and a checkpoint from a RESUMED work product
  is refused (its source lies outside this attempt's directory).
* Every file is bounded by `max_file_bytes` (<= FCP-10D-01's 256 KiB cap);
  a larger ledger or provider transcript is UNAVAILABLE, never sampled.
* Attempt `metadata.json` / `result.json` embed provider output whose strings
  may exceed FCP-10D-01's 4096-char limit; for those two files only, long
  string VALUES are tolerated (every other strictness rule still applies)
  and never echoed.
* Directory listings are never used and nothing is cached; a file replaced
  between two reads of different files is caught only through the
  cross-file rules above.

Stdlib + sibling modules only; no write, Git, process, network, clock or
environment access. Never raises on bad input; outputs hold only enumerated
codes, validated ids / commits, digests and counts - never a path or prose.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Optional

try:
    from scripts.ai import claude_runner as cr
    from scripts.ai import fabric_control_plane_contract as cp
    from scripts.ai import fabric_control_plane_evidence as cpe
    from scripts.ai import fabric_control_plane_snapshot as snap
    from scripts.ai import fabric_director as fd
    from scripts.ai import fabric_resource_quota_contract as qc
    from scripts.ai import fabric_resource_quota_report as qrep
    from scripts.ai import fabric_self_dogfood_contract as dc
    from scripts.ai import fabric_self_dogfood_guardrails as g
    from scripts.ai import runner_factory_ledger as flog
    from scripts.ai import runner_pipeline as rp
except ImportError:  # pragma: no cover - direct script execution
    import claude_runner as cr  # type: ignore[no-redef]
    import fabric_control_plane_contract as cp  # type: ignore[no-redef]
    import fabric_control_plane_evidence as cpe  # type: ignore[no-redef]
    import fabric_control_plane_snapshot as snap  # type: ignore[no-redef]
    import fabric_director as fd  # type: ignore[no-redef]
    import fabric_resource_quota_contract as qc  # type: ignore[no-redef]
    import fabric_resource_quota_report as qrep  # type: ignore[no-redef]
    import fabric_self_dogfood_contract as dc  # type: ignore[no-redef]
    import fabric_self_dogfood_guardrails as g  # type: ignore[no-redef]
    import runner_factory_ledger as flog  # type: ignore[no-redef]
    import runner_pipeline as rp  # type: ignore[no-redef]

SCHEMA = "fcp12a03-self-dogfood-evidence-v1"
SCHEMA_VERSION = 1
EVIDENCE_MARKER = "FCP12A03_SELF_DOGFOOD_EVIDENCE_READ_ONLY_NOT_CERTIFIED_NOT_AUTHORIZED"

# The closure contract version this module was reviewed against.
SUPPORTED_CONTRACT_SCHEMA = "fcp12a01-self-dogfood-closure-v1"
SUPPORTED_CONTRACT_SCHEMA_VERSION = 1

MAX_FILE_BYTES = snap.MAX_FILE_BYTES
MAX_ROOT_CHARS = g.MAX_PATH_CHARS
MAX_LEDGER_EVENTS = 4096

# Decisions (the evidence verdict).
CORROBORATED = "CORROBORATED"
DENIED = "DENIED"
INVALID_REQUEST = "INVALID_REQUEST"
DECISIONS = (CORROBORATED, DENIED, INVALID_REQUEST)

# Axes that this reader never resolves.
AUDIT_VERDICT_UNKNOWN = cp.OUTCOME_UNKNOWN
AUTHORIZATION_NONE = "NONE"

# Reason codes, in their fixed canonical order.
REQUEST_NOT_TYPED = "REQUEST_NOT_TYPED"
SCHEMA_UNSUPPORTED = "SCHEMA_UNSUPPORTED"
REQUEST_MALFORMED = "REQUEST_MALFORMED"
INVALID_REASONS = (REQUEST_NOT_TYPED, SCHEMA_UNSUPPORTED, REQUEST_MALFORMED)
CONTRACT_VERSION_UNSUPPORTED = "CONTRACT_VERSION_UNSUPPORTED"
STATE_ROOT_REFUSED = "STATE_ROOT_REFUSED"
FACTORY_ROOT_REFUSED = "FACTORY_ROOT_REFUSED"
ROOTS_OVERLAP = "ROOTS_OVERLAP"
EVIDENCE_MISSING = "EVIDENCE_MISSING"
EVIDENCE_CORRUPT = "EVIDENCE_CORRUPT"
EVIDENCE_UNAVAILABLE = "EVIDENCE_UNAVAILABLE"
EVIDENCE_SCHEMA_UNSUPPORTED = "EVIDENCE_SCHEMA_UNSUPPORTED"
IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
EVIDENCE_PATH_REFUSED = "EVIDENCE_PATH_REFUSED"
REFERENCE_MISMATCH = "REFERENCE_MISMATCH"
STALE_EVIDENCE = "STALE_EVIDENCE"
STATE_DIVERGENT = "STATE_DIVERGENT"
STATUS_UNRECOGNIZED = "STATUS_UNRECOGNIZED"
WORKER_NOT_SUCCESS = "WORKER_NOT_SUCCESS"
ATTEMPT_NOT_COMPLETED = "ATTEMPT_NOT_COMPLETED"
SUCCESS_NOT_RUNNER_CERTIFIED = "SUCCESS_NOT_RUNNER_CERTIFIED"
STATUS_SOURCE_INCONSISTENT = "STATUS_SOURCE_INCONSISTENT"
EVIDENCE_INCOMPLETE = "EVIDENCE_INCOMPLETE"
SAFETY_NOT_PROVEN = "SAFETY_NOT_PROVEN"
WORK_PRODUCT_MISMATCH = "WORK_PRODUCT_MISMATCH"
SCOPE_VIOLATION = "SCOPE_VIOLATION"
PROTECTED_PATH_CHANGED = "PROTECTED_PATH_CHANGED"
CHECKPOINT_POLICY_MISSING = "CHECKPOINT_POLICY_MISSING"
CHECKPOINT_INVALID = "CHECKPOINT_INVALID"
COMMIT_MISMATCH = "COMMIT_MISMATCH"
COMPLETION_MODE_UNSUPPORTED = "COMPLETION_MODE_UNSUPPORTED"
LEDGER_MISMATCH = "LEDGER_MISMATCH"
LEDGER_UNACCEPTED_CLAIM = "LEDGER_UNACCEPTED_CLAIM"
TARGET_HEAD_MISMATCH = "TARGET_HEAD_MISMATCH"
READER_FAULT = "READER_FAULT"
REASONS = INVALID_REASONS + (
    CONTRACT_VERSION_UNSUPPORTED, STATE_ROOT_REFUSED, FACTORY_ROOT_REFUSED, ROOTS_OVERLAP, EVIDENCE_MISSING,
    EVIDENCE_CORRUPT, EVIDENCE_UNAVAILABLE, EVIDENCE_SCHEMA_UNSUPPORTED, IDENTITY_MISMATCH, EVIDENCE_PATH_REFUSED,
    REFERENCE_MISMATCH, STALE_EVIDENCE, STATE_DIVERGENT, STATUS_UNRECOGNIZED, WORKER_NOT_SUCCESS,
    ATTEMPT_NOT_COMPLETED, SUCCESS_NOT_RUNNER_CERTIFIED, STATUS_SOURCE_INCONSISTENT, EVIDENCE_INCOMPLETE,
    SAFETY_NOT_PROVEN, WORK_PRODUCT_MISMATCH, SCOPE_VIOLATION, PROTECTED_PATH_CHANGED, CHECKPOINT_POLICY_MISSING,
    CHECKPOINT_INVALID, COMMIT_MISMATCH, COMPLETION_MODE_UNSUPPORTED, LEDGER_MISMATCH, LEDGER_UNACCEPTED_CLAIM,
    TARGET_HEAD_MISMATCH, READER_FAULT,
)

_CONDITION_REASON = {cp.MISSING: EVIDENCE_MISSING, cp.CORRUPT: EVIDENCE_CORRUPT, cp.UNAVAILABLE: EVIDENCE_UNAVAILABLE}
_PATH_CAUSES = frozenset({cp.PATH_REFUSED, cp.LINK_REFUSED, cp.EVIDENCE_PATH_UNEXPECTED})
_STATE_KINDS = ("PIPELINE_RESULT", "WORKER_RECORD", "WORKER_RESULT")
_ATTEMPT_KINDS = cpe.ATTEMPT_ARTIFACT_KINDS
_TOLERANT_KINDS = frozenset({"ATTEMPT_METADATA", "ATTEMPT_RESULT"})
_SUCCESS = rp.WorkerState.SUCCESS.value
_COMPLETED = "COMPLETED"
_RETRY_SUCCESS = "NONE:SUCCESS"
_ACCEPTANCE_PASSED = "PASSED"
_SAFE = "SAFE"
_WRITE_MODE = "write"
_CHECKPOINT_CREATED = "CREATED"
_CURRENT_WORK_PRODUCT = "CURRENT_ATTEMPT_WORK_PRODUCT"
_AFTER_START_EVENTS = frozenset({flog.CHECKPOINT_CREATED, flog.WORKER_FINISHED, flog.WORK_PRODUCT_CREATED,
                                 flog.MODULE_STATE_CHANGED})
_CLAIM_EVENTS = frozenset({flog.CERTIFICATION_STARTED, flog.CERTIFICATION_FINISHED, flog.MODULE_CERTIFIED,
                           flog.MODULE_CLOSED})


def _ordered(codes) -> tuple:
    return tuple(sorted(set(codes), key=REASONS.index))


def _commit(value) -> bool:
    return type(value) is str and cp._COMMIT_RE.fullmatch(value) is not None


def _obj(value) -> dict:
    return value if type(value) is dict else {}


def _is(value, expected) -> bool:
    """Exact-type equality: `True` never equals 1, a str never equals a
    look-alike of another type."""
    return type(value) is type(expected) and value == expected


# ---------------------------------------------------------------------------
# Input (tainted; validated only by `read_evidence`)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EvidenceRequest:
    schema_version: object = None
    state_root: object = None
    factory_root: object = None
    pipeline_id: Optional[str] = None
    worker_id: Optional[str] = None
    observed_target_head: Optional[str] = None
    max_file_bytes: object = MAX_FILE_BYTES


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

class _EvidenceGuarantees(dc._DogfoodGuarantees):
    """FCP-12A-01 zero-authority flags plus the reader-specific ones."""

    @property
    def write_allowed(self) -> bool:
        return False

    @property
    def arbitrary_path_read_allowed(self) -> bool:
        return False

    @property
    def provider_words_trusted(self) -> bool:
        return False

    @staticmethod
    def _guarantees() -> dict:
        guarantees = dc._DogfoodGuarantees._guarantees()
        guarantees.update(evidence_marker=EVIDENCE_MARKER, write_allowed=False, arbitrary_path_read_allowed=False,
                          provider_words_trusted=False)
        return guarantees


@dataclass(frozen=True)
class SelfDogfoodEvidence(_EvidenceGuarantees):
    """Normalized, secret-free view of one attempt's Runner evidence.
    Construction re-checks every invariant, so a hand-made or tampered view
    cannot claim more than its reasons allow. `changed_paths` (repo-relative
    pathspecs) feed the closure contract only and are never serialized."""
    decision: str
    reasons: tuple
    pipeline_id: Optional[str] = None
    worker_id: Optional[str] = None
    runner_state: Optional[str] = None
    attempt: Optional[int] = None
    attempt_leaf: Optional[str] = None
    provider_id: Optional[str] = None
    attempt_base_head: Optional[str] = None
    completion_mode: Optional[str] = None
    checkpoint_commit: Optional[str] = None
    changed_paths: tuple = ()
    evidence: tuple = ()

    def __post_init__(self):
        if not (type(self.decision) is str and self.decision in DECISIONS):
            raise ValueError("unknown evidence decision")
        if not (type(self.reasons) is tuple and all(type(r) is str and r in REASONS for r in self.reasons)
                and self.reasons == _ordered(self.reasons)):
            raise ValueError("reasons must be ordered evidence reason codes")
        if not (cp._optional(self.pipeline_id, cp.valid_id) and cp._optional(self.worker_id, cp.valid_id)
                and cp._optional(self.provider_id, cp.valid_id)):
            raise ValueError("ids must be valid ids")
        if not cp._optional(self.runner_state, lambda v: cp._in(v, cp.WORKER_STATES)):
            raise ValueError("runner_state outside the Runner vocabulary")
        if not cp._optional(self.attempt, lambda v: cp._bounded_int(v, cp.MAX_ATTEMPTS) and v >= 1):
            raise ValueError("attempt must be a bounded positive int")
        if not cp._optional(self.attempt_leaf, lambda v: type(v) is str and cp._ATTEMPT_LEAF_RE.fullmatch(v)):
            raise ValueError("attempt_leaf invalid")
        if not (cp._optional(self.attempt_base_head, _commit) and cp._optional(self.checkpoint_commit, _commit)):
            raise ValueError("commits must be 40/64 hex")
        if not cp._optional(self.completion_mode, lambda v: cp._in(v, dc.COMPLETION_MODES)):
            raise ValueError("unknown completion mode")
        if not (type(self.changed_paths) is tuple and all(type(p) is str and g._changed_path_safe(p)
                                                          for p in self.changed_paths)):
            raise ValueError("changed_paths must be safe repo-relative paths")
        if not (type(self.evidence) is tuple and len(self.evidence) <= len(dc.REQUIRED_EVIDENCE_KINDS)
                and all(type(e) is cp.EvidenceRef for e in self.evidence)
                and [e.kind for e in self.evidence] == sorted({e.kind for e in self.evidence})):
            raise ValueError("evidence must be kind-sorted unique EvidenceRefs")
        invalid = any(r in INVALID_REASONS for r in self.reasons)
        if self.decision == CORROBORATED:
            self._check_corroborated()
        elif self.decision == DENIED:
            if not self.reasons or invalid or self.completion_mode is not None or self.changed_paths:
                raise ValueError("DENIED needs non-invalid reasons and proves no completion")
        elif not invalid or self.evidence or self.completion_mode is not None or self.changed_paths or any(
                v is not None for v in (self.pipeline_id, self.worker_id, self.runner_state, self.attempt,
                                        self.attempt_leaf, self.provider_id, self.attempt_base_head,
                                        self.checkpoint_commit)):
            raise ValueError("INVALID_REQUEST needs an invalid-request reason and shows nothing")

    def _check_corroborated(self) -> None:
        facts = (self.pipeline_id, self.worker_id, self.attempt, self.attempt_leaf, self.provider_id,
                 self.attempt_base_head, self.checkpoint_commit)
        if self.reasons or any(v is None for v in facts):
            raise ValueError("CORROBORATED needs no reasons and a complete lineage")
        if (self.runner_state, self.completion_mode) != (_SUCCESS, cr.COMPLETION_MODE_CHECKPOINT):
            raise ValueError("CORROBORATED is only a SUCCESS checkpoint")
        if self.checkpoint_commit == self.attempt_base_head or not self.changed_paths:
            raise ValueError("a checkpoint moves HEAD and commits paths")
        if tuple(e.kind for e in self.evidence) != tuple(sorted(dc.REQUIRED_EVIDENCE_KINDS)):
            raise ValueError("CORROBORATED references every required evidence kind exactly once")
        for e in self.evidence:
            if e.condition != cp.PRESENT or e.pipeline_id not in (None, self.pipeline_id) \
                    or e.worker_id not in (None, self.worker_id) or e.attempt_leaf not in (None, self.attempt_leaf):
                raise ValueError("CORROBORATED evidence must be PRESENT and bound to its lineage")

    @property
    def corroborated(self) -> bool:
        return self.decision == CORROBORATED

    @property
    def evidence_verdict(self) -> str:
        return self.decision

    @property
    def audit_verdict(self) -> str:
        """Always UNKNOWN: Runner state holds no audit evidence."""
        return AUDIT_VERDICT_UNKNOWN

    @property
    def authorization(self) -> str:
        """Always NONE: authorization is never read from evidence."""
        return AUTHORIZATION_NONE

    @property
    def expected_target_head(self) -> Optional[str]:
        return self.checkpoint_commit if self.decision == CORROBORATED else None

    def lineage(self) -> Optional[dc.DogfoodLineage]:
        """FCP-12A-01 lineage, only for CORROBORATED evidence."""
        if self.decision != CORROBORATED:
            return None
        return dc.DogfoodLineage(pipeline_id=self.pipeline_id, worker_id=self.worker_id, attempt=self.attempt,
                                 attempt_leaf=self.attempt_leaf, provider_id=self.provider_id,
                                 attempt_base_head=self.attempt_base_head)

    def completion(self) -> Optional[dc.RunnerCompletion]:
        """FCP-12A-01 Runner completion, only for CORROBORATED evidence. The
        checkpoint message is rebuilt by the Runner's own builder (it was
        verified equal), so no raw evidence text leaves this module."""
        if self.decision != CORROBORATED:
            return None
        return dc.RunnerCompletion(
            status_evidence_kind="WORKER_RESULT", worker_state=self.runner_state,
            completion_policy=cr.COMPLETION_POLICY_RUNNER_ACCEPTANCE,
            work_status_source=cr.WORK_STATUS_SOURCE_RUNNER_ACCEPTANCE,
            checkpoint_policy=cr.CHECKPOINT_POLICY_ON_SUCCESS, checkpoint_decision=_CHECKPOINT_CREATED,
            checkpoint_commit=self.checkpoint_commit,
            checkpoint_message=cr.build_checkpoint_message(
                pipeline_id=self.pipeline_id, worker_id=self.worker_id, attempt=self.attempt,
                provider_id=self.provider_id, base_head=self.attempt_base_head),
            authorized_changed_paths=self.changed_paths, work_product_present=True,
        )

    def closure_evidence(self) -> tuple:
        """The FCP-12A-01 evidence tuple, only for CORROBORATED evidence."""
        return self.evidence if self.decision == CORROBORATED else ()

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA, "schema_version": SCHEMA_VERSION, "decision": self.decision,
            "evidence_verdict": self.decision, "corroborated": self.decision == CORROBORATED,
            "runner_state": self.runner_state, "audit_verdict": AUDIT_VERDICT_UNKNOWN,
            "authorization": AUTHORIZATION_NONE, "reasons": list(self.reasons), "pipeline_id": self.pipeline_id,
            "worker_id": self.worker_id, "attempt": self.attempt, "attempt_leaf": self.attempt_leaf,
            "provider_id": self.provider_id, "attempt_base_head": self.attempt_base_head,
            "completion_mode": self.completion_mode, "checkpoint_commit": self.checkpoint_commit,
            "expected_target_head": self.expected_target_head, "changed_paths_count": len(self.changed_paths),
            "evidence": [e.to_dict() for e in self.evidence], **_EvidenceGuarantees._guarantees(),
        }


def canonical_json(evidence: SelfDogfoodEvidence) -> str:
    """Stable, sorted, compact serialization of the exact output type."""
    if type(evidence) is not SelfDogfoodEvidence:
        raise TypeError("canonical_json accepts only a SelfDogfoodEvidence")
    return json.dumps(SelfDogfoodEvidence.to_dict(evidence), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True)


# ---------------------------------------------------------------------------
# Bounded, fail-closed reads (FCP-10D-01 / FCP-11B-02 discipline)
# ---------------------------------------------------------------------------

def _check_tolerant_tree(value) -> None:
    """FCP-10D-01 `_check_tree` with long string VALUES allowed: depth,
    key length and lone surrogates are still refused."""
    stack = [(value, 1)]
    while stack:
        node, depth = stack.pop()
        if depth > qrep.MAX_JSON_DEPTH:
            raise qrep.ReportError("REPORT_INPUT_TOO_DEEP")
        if isinstance(node, dict):
            for key, item in node.items():
                qrep._check_string(key)
                stack.append((item, depth + 1))
        elif isinstance(node, list):
            stack.extend((item, depth + 1) for item in node)
        elif isinstance(node, str) and any("\ud800" <= c <= "\udfff" for c in node):
            raise qrep.ReportError("REPORT_INPUT_STRING_INVALID")


def _parse(data: bytes, tolerant: bool):
    try:
        return qrep.parse_document(data)
    except qrep.ReportError as exc:
        if not (tolerant and exc.code == "REPORT_INPUT_STRING_INVALID"):
            raise
    try:  # parse_document already proved UTF-8, no BOM, no duplicate key / NaN / oversized number
        document = json.loads(data.decode("utf-8"), object_pairs_hook=qrep._pairs_hook,
                              parse_float=qrep._bounded_float, parse_int=qrep._bounded_int,
                              parse_constant=qrep._no_constant)
    except (qrep._Refuse, ValueError, TypeError, RecursionError):
        raise qrep.ReportError("REPORT_INPUT_JSON_INVALID") from None
    _check_tolerant_tree(document)
    return document


def _read_bytes(path: str, max_bytes: int) -> tuple:
    """`(cause, data)` of one bounded, link-safe, identity-checked read."""
    kind, before, cause = snap._probe(path)
    if cause is not None:
        return cause, None
    if kind != snap._FILE:
        return (cp.LINK_REFUSED if kind == snap._LINK else cp.SOURCE_UNREADABLE), None
    if before.st_size > max_bytes:
        return cp.SOURCE_TOO_LARGE, None
    try:
        data = qrep.read_input_bytes(path)
    except qrep.ReportError as exc:
        return snap._REFUSAL_CAUSES.get(exc.code, cp.SOURCE_UNREADABLE), None
    except (OSError, ValueError):
        return cp.SOURCE_UNREADABLE, None
    if len(data) > max_bytes:
        return cp.SOURCE_TOO_LARGE, None
    _, after, _ = snap._probe(path)
    if after is None or snap._identity(after) != snap._identity(before) or len(data) != before.st_size:
        return cp.SOURCE_CHANGED_DURING_READ, None
    return None, data


def _read_json(path: str, max_bytes: int, *, tolerant: bool = False) -> snap._Read:
    cause, data = _read_bytes(path, max_bytes)
    if cause is not None:
        return snap._Read(cause)
    try:
        payload = _parse(data, tolerant)
    except qrep.ReportError as exc:
        return snap._Read(cp.SOURCE_TOO_LARGE if exc.code == "REPORT_INPUT_TOO_DEEP" else cp.SOURCE_NOT_JSON)
    return snap._Read(None, payload, hashlib.sha256(data).hexdigest(), len(data))


def _read_ledger(path: str, max_bytes: int) -> tuple:
    """`(read, events)`: every non-empty line must be a strict, versioned,
    known, uniquely identified event, else the whole ledger is CORRUPT (a
    skipped line could hide a contradicting event)."""
    cause, data = _read_bytes(path, max_bytes)
    if cause is not None:
        return snap._Read(cause), ()
    try:
        lines = [line for line in data.decode("utf-8", errors="strict").split("\n") if line.strip()]
        events = [qrep.parse_document(line.encode("utf-8")) for line in lines]
    except (UnicodeDecodeError, qrep.ReportError):
        return snap._Read(cp.SOURCE_NOT_JSON), ()
    if len(events) > MAX_LEDGER_EVENTS:
        return snap._Read(cp.SOURCE_TOO_LARGE), ()
    ids = [_obj(e).get("event_id") for e in events]
    for event in events:
        if type(event) is not dict or not _is(event.get("schema_version"), flog.LEDGER_SCHEMA_VERSION):
            return snap._Read(cp.SCHEMA_UNSUPPORTED), ()
        if not (cp._in(event.get("event_type"), flog.EVENT_TYPES) and type(event.get("event_id")) is str
                and event["event_id"] and cp.normalized_utc(event.get("timestamp_utc")) is not None):
            return snap._Read(cp.FIELD_MALFORMED), ()
    if len(set(ids)) != len(ids):
        return snap._Read(cp.FIELD_MALFORMED), ()
    events.sort(key=lambda e: (cp.normalized_utc(e["timestamp_utc"]), e["event_id"]))
    return snap._Read(None, events, hashlib.sha256(data).hexdigest(), len(data)), tuple(events)


# ---------------------------------------------------------------------------
# Reading one attempt
# ---------------------------------------------------------------------------

class _Facts:
    """Mutable working state of one read; never leaves this module."""

    def __init__(self):
        self.reasons: list = []
        self.reads: dict = {}
        self.causes: dict = {}
        self.leaf: Optional[str] = None

    def deny(self, *codes) -> None:
        self.reasons.extend(codes)

    def corrupt(self, kind: str, cause: str, reason: str) -> None:
        """A file that was read but whose own schema / identity is wrong."""
        if self.causes.get(kind) is None:
            self.causes[kind] = cause
        self.deny(reason)


def _admit_roots(state_root, factory_root, facts: _Facts) -> Optional[tuple]:
    roots = []
    for raw, reason in ((state_root, STATE_ROOT_REFUSED), (factory_root, FACTORY_ROOT_REFUSED)):
        text = os.fspath(raw) if isinstance(raw, os.PathLike) else raw
        if type(text) is not str or snap._admit_root(text) is not None or g.canonical_path_key(text) is None:
            facts.deny(reason)
            roots.append(None)
        else:
            roots.append(text)
    if None in roots:
        return None
    if g._overlap(g.canonical_path_key(roots[0]), g.canonical_path_key(roots[1])):
        facts.deny(ROOTS_OVERLAP)
        return None
    return tuple(roots)


def _ref_path(root: str, kind: str, pid: str, wid: str) -> str:
    """Path of a Runner-state file, composed only from validated ids."""
    ref = cp.EvidenceRef(kind, cp.MISSING, pid, wid if kind != "PIPELINE_RESULT" else None, None, cp.SOURCE_ABSENT)
    return os.path.join(root, *ref.relative_parts())


def _attempt_dir(state_root: str, pid: str, wid: str, attempt: dict, facts: _Facts) -> Optional[str]:
    """The persisted `evidence_dir`, only when canonical and governed."""
    raw, leaf = attempt.get("evidence_dir"), attempt.get("run_id")
    if leaf is None:  # an attempt still running has recorded no run yet
        facts.deny(EVIDENCE_MISSING)
        return None
    if not (type(leaf) is str and cp._ATTEMPT_LEAF_RE.fullmatch(leaf)):
        facts.deny(EVIDENCE_PATH_REFUSED, IDENTITY_MISMATCH)
        return None
    facts.leaf = leaf
    layout, cause, rel = cpe._locate(state_root, pid, wid, raw)
    if cause is None and (layout != cpe.LAYOUT_CURRENT or rel[-1] != leaf or g.canonical_path_key(raw) is None):
        cause = cp.EVIDENCE_PATH_UNEXPECTED
    if cause is not None:
        for kind in _ATTEMPT_KINDS:
            facts.causes[kind] = cause
        facts.deny(EVIDENCE_PATH_REFUSED if cause in _PATH_CAUSES or cause == cp.FIELD_MALFORMED
                   else _CONDITION_REASON[cp.CAUSE_CONDITION[cause]])
        return None
    return os.path.join(state_root, *rel)


def _pathspecs(lines) -> Optional[tuple]:
    if not (type(lines) is list and lines and all(type(line) is str for line in lines)):
        return None
    return tuple(sorted({p for line in lines for p in cr.extract_paths_from_porcelain_line(line)}))


def _check_worker(worker: dict, wid: str, facts: _Facts) -> Optional[dict]:
    """Latest attempt of a well-formed worker.json, or None."""
    if not _is(worker.get("schema_version"), rp.PIPELINE_SCHEMA_VERSION):
        facts.corrupt("WORKER_RECORD", cp.SCHEMA_UNSUPPORTED, EVIDENCE_SCHEMA_UNSUPPORTED)
        return None
    if _obj(worker.get("spec")).get("id") != wid:
        facts.corrupt("WORKER_RECORD", cp.IDENTITY_MISMATCH, IDENTITY_MISMATCH)
        return None
    attempts = worker.get("attempts")
    base = worker.get("attempt_base")
    if not (type(attempts) is list and 0 < len(attempts) <= cp.MAX_ATTEMPTS and all(type(a) is dict for a in attempts)
            and type(base) is int and 0 <= base < len(attempts)):
        facts.corrupt("WORKER_RECORD", cp.FIELD_MALFORMED, EVIDENCE_CORRUPT)
        return None
    numbers = [a.get("attempt") for a in attempts]
    if numbers != list(range(1, len(attempts) + 1)):
        facts.corrupt("WORKER_RECORD", cp.FIELD_MALFORMED, EVIDENCE_CORRUPT)
        return None
    return attempts[-1]


def _status_reasons(worker: dict, attempt: dict, facts: _Facts) -> None:
    spec = _obj(worker.get("spec"))
    state = worker.get("state")
    if not cp._in(state, cp.WORKER_STATES):
        facts.deny(STATUS_UNRECOGNIZED)
    elif state != _SUCCESS or worker.get("state_reason") is not None:
        facts.deny(WORKER_NOT_SUCCESS)
    if not (_is(attempt.get("status"), _COMPLETED) and attempt.get("executed") is True
            and attempt.get("process_confirmed_stopped") is True and _is(attempt.get("runner_state"), _SUCCESS)
            and _is(attempt.get("retry_decision"), _RETRY_SUCCESS)):
        facts.deny(ATTEMPT_NOT_COMPLETED)
    if not (_is(attempt.get("work_status"), _SUCCESS)
            and _is(attempt.get("work_status_source"), cr.WORK_STATUS_SOURCE_RUNNER_ACCEPTANCE)
            and _is(_obj(attempt.get("acceptance")).get("decision"), _ACCEPTANCE_PASSED)
            and _is(spec.get("completion_policy"), cr.COMPLETION_POLICY_RUNNER_ACCEPTANCE)):
        facts.deny(SUCCESS_NOT_RUNNER_CERTIFIED)
    if attempt.get("evidence_complete") is not True:
        facts.deny(EVIDENCE_INCOMPLETE)
    if not (_is(spec.get("checkpoint_policy"), cr.CHECKPOINT_POLICY_ON_SUCCESS)):
        facts.deny(CHECKPOINT_POLICY_MISSING)
    if attempt.get("provider") != worker.get("active_provider") or not cp.valid_id(attempt.get("provider")):
        facts.deny(IDENTITY_MISMATCH)


def _result_reasons(result: dict, worker: dict, attempt: dict, pid: str, wid: str, state_root: str,
                    evidence_dir: Optional[str], facts: _Facts) -> None:
    if (result.get("pipeline_id"), result.get("worker_id")) != (pid, wid):
        facts.corrupt("WORKER_RESULT", cp.IDENTITY_MISMATCH, IDENTITY_MISMATCH)
        return
    attempts = result.get("attempts")
    if not (type(attempts) is list and attempts == worker.get("attempts")):
        facts.deny(STALE_EVIDENCE)
    written, ended = qc.parse_utc(result.get("written_at_utc")), qc.parse_utc(attempt.get("ended_at_utc"))
    if written is None or ended is None or written < ended:
        facts.deny(STALE_EVIDENCE)
    if (result.get("state"), result.get("outcome"), result.get("state_reason")) != (worker.get("state"), _SUCCESS,
                                                                                    None):
        facts.deny(STATE_DIVERGENT)
    if (result.get("work_status"), result.get("work_status_source"), result.get("provider")) != (
            attempt.get("work_status"), attempt.get("work_status_source"), attempt.get("provider")):
        facts.deny(STATE_DIVERGENT)
    if result.get("checkpoint") != attempt.get("checkpoint") or result.get("acceptance") != attempt.get("acceptance"):
        facts.deny(COMMIT_MISMATCH)
    preflight = _ref_path(state_root, "WORKER_PREFLIGHT", pid, wid)
    if not (cpe._same_dir(result.get("evidence_dir"), attempt.get("evidence_dir"))
            and cpe._same_dir(result.get("preflight"), preflight)):
        facts.deny(REFERENCE_MISMATCH)
    artifacts = result.get("artifacts")
    if evidence_dir is not None:
        names = [os.path.basename(a) for a in artifacts] if type(artifacts) is list and all(
            type(a) is str for a in artifacts) else None
        if names is None or len(set(names)) != len(names) or not all(
                cpe._same_dir(os.path.dirname(a), evidence_dir) for a in artifacts) or not set(names) <= set(
                cr.RUNNER_EVIDENCE_ARTIFACT_FILENAMES) or not {"metadata.json", "result.json",
                                                               "work_product.json"} <= set(names):
            facts.deny(REFERENCE_MISMATCH)


def _pipeline_reasons(payload, worker: dict, attempt: dict, pid: str, wid: str, facts: _Facts) -> None:
    view = cp.project_pipeline_result(payload, pid)
    if view.status.condition != cp.PRESENT:
        cause = view.status.cause
        facts.corrupt("PIPELINE_RESULT", cause if cp.CAUSE_CONDITION[cause] == cp.CORRUPT else cp.FIELD_MALFORMED,
                      EVIDENCE_SCHEMA_UNSUPPORTED if cause == cp.SCHEMA_UNSUPPORTED else
                      IDENTITY_MISMATCH if cause == cp.IDENTITY_MISMATCH else EVIDENCE_CORRUPT)
        return
    mine = [w for w in view.workers if w.worker_id == wid]
    if len(mine) != 1 or view.rejected_workers:
        facts.deny(STATE_DIVERGENT)
        return
    w = mine[0]
    checkpoint = _obj(attempt.get("checkpoint"))
    if w.malformed_fields or w.status.source_value != worker.get("state") or w.attempts != len(worker["attempts"]):
        facts.deny(STATE_DIVERGENT)
    if w.checkpoint_policy != _obj(worker.get("spec")).get("checkpoint_policy") \
            or w.checkpoint_commit != checkpoint.get("commit_hash"):
        facts.deny(COMMIT_MISMATCH)


def _attempt_reasons(reads: dict, worker: dict, attempt: dict, pid: str, wid: str, evidence_dir: str,
                     facts: _Facts) -> Optional[tuple]:
    """`(base_head, pathspecs)` of a consistent attempt, else None."""
    meta, res, wp = (reads[k].payload for k in _ATTEMPT_KINDS)
    if not all(type(x) is dict for x in (meta, res, wp)):
        for kind, x in zip(_ATTEMPT_KINDS, (meta, res, wp)):
            if type(x) is not dict:
                facts.corrupt(kind, cp.SOURCE_NOT_JSON, EVIDENCE_CORRUPT)
        return None
    leaf, number, provider = facts.leaf, attempt.get("attempt"), attempt.get("provider")
    spec = _obj(worker.get("spec"))
    if not _is(wp.get("schema_version"), cr.WORK_PRODUCT_SCHEMA_VERSION):
        facts.corrupt("ATTEMPT_WORK_PRODUCT", cp.SCHEMA_UNSUPPORTED, EVIDENCE_SCHEMA_UNSUPPORTED)
        return None
    if not ((wp.get("pipeline_id"), wp.get("worker_id"), wp.get("run_id"), wp.get("provider")) == (
            pid, wid, leaf, provider) and _is(wp.get("attempt"), number)):
        facts.corrupt("ATTEMPT_WORK_PRODUCT", cp.IDENTITY_MISMATCH, IDENTITY_MISMATCH)
        return None
    if meta.get("run_id") != leaf or _obj(meta.get("provider")).get("provider_id") != provider \
            or _obj(res.get("provider")).get("provider_id") != provider:
        facts.deny(IDENTITY_MISMATCH)
    if not (cpe._same_dir(wp.get("evidence_dir"), evidence_dir)
            and cpe._same_dir(wp.get("runner_evidence_dir"), evidence_dir)
            and cpe._same_dir(wp.get("worktree"), spec.get("worktree_top"))):
        facts.deny(REFERENCE_MISMATCH)
    # -- provider-scoped attempt result: never a certification source ------
    if not (_is(res.get("work_status_source"), cr.WORK_STATUS_SOURCE_PROVIDER)
            and res.get("provider_work_status") == attempt.get("provider_work_status")
            and res.get("work_status") == attempt.get("provider_work_status")):
        facts.deny(STATUS_SOURCE_INCONSISTENT)
    if not (_is(res.get("state"), _SUCCESS) and _is(meta.get("state"), _SUCCESS)
            and res.get("state") == attempt.get("runner_state")):
        facts.deny(ATTEMPT_NOT_COMPLETED)
    # -- completeness ------------------------------------------------------
    for record in (meta, res):
        if record.get("evidence_complete") is not True or record.get("evidence_errors") != []:
            facts.deny(EVIDENCE_INCOMPLETE)
    # -- safety / HEAD -----------------------------------------------------
    base_head, branch = wp.get("base_head"), wp.get("branch")
    repo = _obj(meta.get("repository"))
    check = _obj(res.get("safety_check"))
    safe = (
        _commit(base_head) and type(branch) is str
        and (repo.get("head_before"), repo.get("head_after")) == (base_head, base_head)
        and (repo.get("branch_before"), repo.get("branch_after")) == (branch, branch)
        and all(_is(_obj(r.get("safety_verdict")).get("verdict"), _SAFE) for r in (meta, res))
        and meta.get("unauthorized_changed_paths") == [] and res.get("unauthorized_changed_paths") == []
        and check.get("head_changed") is False and check.get("branch_changed") is False
        and all(_is(r.get("execution_mode"), _WRITE_MODE) for r in (meta, res))
    )
    if not safe:
        facts.deny(SAFETY_NOT_PROVEN)
    # -- work product ------------------------------------------------------
    lines = wp.get("authorized_changed_paths")
    paths = _pathspecs(lines)
    if not (wp.get("incomplete") is False and _is(wp.get("state"), _SUCCESS)
            and wp.get("process_confirmed_stopped") is True and meta.get("work_product") == wp
            and res.get("work_product") == wp and meta.get("work_product_present") is True
            and res.get("work_product_present") is True and paths
            and meta.get("authorized_changed_paths") == lines and res.get("authorized_changed_paths") == lines):
        facts.deny(WORK_PRODUCT_MISMATCH)
    if not paths:
        return None
    scopes, spec_scopes = wp.get("authorized_scopes"), spec.get("authorize_path")
    if not (type(scopes) is list and type(spec_scopes) is list and all(type(s) is str for s in scopes + spec_scopes)
            and all(g._changed_path_safe(p) and cr.path_is_authorized(p, scopes)
                    and cr.path_is_authorized(p, spec_scopes) for p in paths)):
        facts.deny(SCOPE_VIOLATION)
    if any(dc._path_key(p) in dc._PROTECTED_KEYS for p in paths):
        facts.deny(PROTECTED_PATH_CHANGED)
    if not (_commit(base_head) and all(g._changed_path_safe(p) for p in paths)):
        return None
    return base_head, paths


def _checkpoint_reasons(attempt: dict, pid: str, wid: str, base_head: str, paths: tuple,
                        facts: _Facts) -> Optional[str]:
    checkpoint = attempt.get("checkpoint")
    if type(checkpoint) is not dict:
        facts.deny(CHECKPOINT_INVALID)
        return None
    commit = checkpoint.get("commit_hash")
    expected = cr.build_checkpoint_message(pipeline_id=pid, worker_id=wid, attempt=attempt.get("attempt"),
                                           provider_id=attempt.get("provider"), base_head=base_head)
    if not (_is(checkpoint.get("decision"), _CHECKPOINT_CREATED) and _commit(commit) and commit != base_head
            and checkpoint.get("message") == expected and checkpoint.get("committed_paths") == list(paths)
            and _is(checkpoint.get("work_product_source"), _CURRENT_WORK_PRODUCT)):
        facts.deny(CHECKPOINT_INVALID)
        return None
    return commit


def _ledger_reasons(events: tuple, pid: str, wid: str, provider, base_head: str, commit: str,
                    facts: _Facts) -> None:
    mine = [e for e in events if (e.get("pipeline_id"), e.get("worker_id")) == (pid, wid)]
    if any(e["event_type"] in _CLAIM_EVENTS or e.get("certification_status") is not None
           or e.get("closer") is not None for e in mine):
        facts.deny(LEDGER_UNACCEPTED_CLAIM)
    starts = [i for i, e in enumerate(mine) if e["event_type"] == flog.WORKER_STARTED]
    if not starts:
        facts.deny(LEDGER_MISMATCH)
        return
    start, after = mine[starts[-1]], mine[starts[-1] + 1:]
    by_type = {t: [e for e in after if e["event_type"] == t] for t in _AFTER_START_EVENTS}
    expected = (
        (start.get("base_commit"), start.get("provider")) == (base_head, provider)
        and all(e["event_type"] in _AFTER_START_EVENTS for e in after)
        and all(len(by_type[t]) == 1 for t in (flog.CHECKPOINT_CREATED, flog.WORKER_FINISHED,
                                                flog.WORK_PRODUCT_CREATED))
    )
    if expected:
        created, finished, product = (by_type[t][0] for t in (flog.CHECKPOINT_CREATED, flog.WORKER_FINISHED,
                                                              flog.WORK_PRODUCT_CREATED))
        expected = (
            (created.get("base_commit"), created.get("result_commit"), created.get("state")) == (
                base_head, commit, _CHECKPOINT_CREATED)
            and (finished.get("result_commit"), finished.get("state"), finished.get("state_reason")) == (
                commit, _SUCCESS, None)
            and (product.get("result_commit"), product.get("state")) == (commit, _SUCCESS)
            and all(e.get("provider") == provider for e in after)
        )
    if not expected:
        facts.deny(LEDGER_MISMATCH)


def _refs(facts: _Facts, pid: str, wid: str) -> tuple:
    refs = []
    for kind in dc.REQUIRED_EVIDENCE_KINDS:
        if kind in _ATTEMPT_KINDS and facts.leaf is None:
            continue
        read = facts.reads.get(kind)
        cause = facts.causes.get(kind) or (read.cause if read is not None else cp.SOURCE_ABSENT)
        has_pipeline = kind != "FACTORY_EVENTS"
        has_worker = kind not in ("PIPELINE_RESULT", "FACTORY_EVENTS")
        leaf = facts.leaf if kind in _ATTEMPT_KINDS else None
        condition = cp.PRESENT if cause is None else cp.CAUSE_CONDITION[cause]
        refs.append(cp.EvidenceRef(kind, condition, pid if has_pipeline else None, wid if has_worker else None, leaf,
                                   cause, read.sha256 if cause is None else None,
                                   read.size if cause is None else None))
        if cause is not None:
            facts.deny(_CONDITION_REASON[condition])
            if cause in _PATH_CAUSES:
                facts.deny(EVIDENCE_PATH_REFUSED)
    return tuple(sorted(refs, key=lambda r: r.kind))


def _read(request: EvidenceRequest) -> SelfDogfoodEvidence:
    pid, wid = request.pipeline_id, request.worker_id
    facts = _Facts()
    if (dc.SCHEMA, dc.SCHEMA_VERSION) != (SUPPORTED_CONTRACT_SCHEMA, SUPPORTED_CONTRACT_SCHEMA_VERSION):
        facts.deny(CONTRACT_VERSION_UNSUPPORTED)
    roots = _admit_roots(request.state_root, request.factory_root, facts)
    if roots is None:
        return SelfDogfoodEvidence(DENIED, _ordered(facts.reasons), pipeline_id=pid, worker_id=wid)
    state_root, factory_root = roots
    max_bytes = request.max_file_bytes
    for kind in _STATE_KINDS:
        facts.reads[kind] = _read_json(_ref_path(state_root, kind, pid, wid), max_bytes)
    facts.reads["FACTORY_EVENTS"], events = _read_ledger(os.path.join(factory_root, flog.EVENTS_FILENAME),
                                                         max_bytes)
    worker = facts.reads["WORKER_RECORD"].payload
    attempt = _check_worker(worker, wid, facts) if type(worker) is dict else None
    if facts.reads["WORKER_RECORD"].cause is None and type(worker) is not dict:
        facts.corrupt("WORKER_RECORD", cp.SOURCE_NOT_JSON, EVIDENCE_CORRUPT)
    state = worker.get("state") if attempt is not None and cp._in(worker.get("state"), cp.WORKER_STATES) else None
    evidence_dir = lineage = commit = None
    if attempt is not None:
        _status_reasons(worker, attempt, facts)
        evidence_dir = _attempt_dir(state_root, pid, wid, attempt, facts)
        if evidence_dir is not None:
            for kind in _ATTEMPT_KINDS:
                facts.reads[kind] = _read_json(os.path.join(evidence_dir, cpe._ARTIFACT_FILENAMES[kind]), max_bytes,
                                               tolerant=kind in _TOLERANT_KINDS)
            if all(facts.reads[k].cause is None for k in _ATTEMPT_KINDS):
                lineage = _attempt_reasons(facts.reads, worker, attempt, pid, wid, evidence_dir, facts)
        result = facts.reads["WORKER_RESULT"]
        if result.cause is None:
            if type(result.payload) is dict:
                _result_reasons(result.payload, worker, attempt, pid, wid, state_root, evidence_dir, facts)
            else:
                facts.corrupt("WORKER_RESULT", cp.SOURCE_NOT_JSON, EVIDENCE_CORRUPT)
        if facts.reads["PIPELINE_RESULT"].cause is None:
            _pipeline_reasons(facts.reads["PIPELINE_RESULT"].payload, worker, attempt, pid, wid, facts)
    if lineage is not None:
        base_head, paths = lineage
        commit = _checkpoint_reasons(attempt, pid, wid, base_head, paths, facts)
        mode = fd._classify_completion_mode(worker_state=state, checkpoint_commit=commit,
                                            authorized_changed_paths=paths, work_product_present=True)
        if mode != cr.COMPLETION_MODE_CHECKPOINT:
            facts.deny(COMPLETION_MODE_UNSUPPORTED)
        if commit is not None:
            if facts.reads["FACTORY_EVENTS"].cause is None:
                _ledger_reasons(events, pid, wid, attempt.get("provider"), base_head, commit, facts)
            if request.observed_target_head != commit:
                facts.deny(TARGET_HEAD_MISMATCH)
    elif attempt is not None and evidence_dir is not None:
        facts.deny(WORK_PRODUCT_MISMATCH)
    refs = _refs(facts, pid, wid)
    reasons = _ordered(facts.reasons)
    if attempt is None and not reasons:
        reasons = (EVIDENCE_CORRUPT,)
    provider = attempt.get("provider") if attempt is not None and cp.valid_id(attempt.get("provider")) else None
    number = attempt.get("attempt") if attempt is not None else None
    if reasons:
        return SelfDogfoodEvidence(DENIED, reasons, pipeline_id=pid, worker_id=wid, runner_state=state,
                                   attempt=number, attempt_leaf=facts.leaf, provider_id=provider,
                                   attempt_base_head=lineage[0] if lineage else None,
                                   checkpoint_commit=commit, evidence=refs)
    return SelfDogfoodEvidence(CORROBORATED, (), pipeline_id=pid, worker_id=wid, runner_state=state, attempt=number,
                               attempt_leaf=facts.leaf, provider_id=provider, attempt_base_head=lineage[0],
                               completion_mode=cr.COMPLETION_MODE_CHECKPOINT, checkpoint_commit=commit,
                               changed_paths=lineage[1], evidence=refs)


def _invalid(*reasons) -> SelfDogfoodEvidence:
    return SelfDogfoodEvidence(decision=INVALID_REQUEST, reasons=_ordered(reasons))


def read_evidence(request: EvidenceRequest) -> SelfDogfoodEvidence:
    """Read-only, deterministic, deny-by-default normalization of one
    worker's latest attempt evidence. Never raises on bad input; never
    writes, runs Git, certifies, authorizes, promotes or records anything."""
    if type(request) is not EvidenceRequest:
        return _invalid(REQUEST_NOT_TYPED)
    if not _is(request.schema_version, SCHEMA_VERSION):
        return _invalid(SCHEMA_UNSUPPORTED)
    roots_ok = all((isinstance(r, os.PathLike) or type(r) is str) for r in (request.state_root, request.factory_root))
    if not (cp.valid_id(request.pipeline_id) and cp.valid_id(request.worker_id) and _commit(request.observed_target_head)
            and roots_ok and cp._bounded_int(request.max_file_bytes, MAX_FILE_BYTES) and request.max_file_bytes >= 1):
        return _invalid(REQUEST_MALFORMED)
    try:
        return _read(request)
    except Exception:  # noqa: BLE001 - hostile evidence must fail closed, never crash the caller
        return SelfDogfoodEvidence(DENIED, (READER_FAULT,), pipeline_id=request.pipeline_id,
                                   worker_id=request.worker_id)
