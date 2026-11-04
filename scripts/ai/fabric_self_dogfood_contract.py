"""FCP-12A-01: Self-Dogfood & Closure contract V1 - pure, deterministic,
fail-closed, ADVISORY-ONLY assessment of one governed self-dogfood Work Order
attempt's request to be closed.

What it answers
---------------
"May this attempt be put in front of a human reviewer as a governed,
Runner-proven self-dogfood closure?" - and nothing more. The best possible
outcome is `REVIEW_REQUESTABLE`; it never approves, certifies, releases,
promotes, merges, commits or records anything. A `REQUEST_RELEASE` action is
always DENIED here: real promotion stays exclusively behind the existing
FCP-3 human authorization (`runner_promotion_human_authorization` and the
promotion gates), which this module neither creates nor can satisfy.

Reuse, never redefine
---------------------
* Worker state vocabulary: `runner_pipeline.WorkerState` (via the FCP-11A
  control-plane catalog `WORKER_STATES`).
* Checkpoint contract: `claude_runner.CHECKPOINT_POLICIES`,
  `CHECKPOINT_OK_DECISIONS` and `build_checkpoint_message` (the exact commit
  message the Runner writes, so a checkpoint is bound to its own
  pipeline / worker / attempt / provider / base head).
* Completion criteria: `claude_runner.COMPLETION_POLICY_RUNNER_ACCEPTANCE`,
  `WORK_STATUS_SOURCE_RUNNER_ACCEPTANCE` and the Director's own
  `_classify_completion_mode` (CHECKPOINT / SUCCESS_NOOP). The work/evidence
  verdict itself is the FCP-8A-01 `ValidationAssessment`, never re-derived.
* Ids, commits, attempt leaves and evidence references: FCP-11A-01
  `valid_id`, its commit / attempt-leaf grammar and `EvidenceRef`.
* Zero-authority flags extend FCP-8A-01 `_NotAuthorized`.

Inputs (`CloseRequest` and its parts, frozen, TAINTED)
------------------------------------------------------
Constructors validate nothing; `assess_closure` validates everything and
never raises: every malformed, missing or mistyped value yields an explained
DENIED / INVALID_REQUEST result. Raw input text is never echoed: the output
holds only enumerated codes.

* `DogfoodIdentity`: base commit (the FCP-11 commit the feature worktree
  starts from), the pinned detached controller commit and the controller /
  target HEADs observed after the attempt, plus `target_isolated` (the
  caller's evaluation of `not runner_pipeline.is_unsafe_self_target`).
* `DogfoodLineage`: pipeline / worker / provider ids, attempt number,
  attempt evidence leaf and the attempt's base HEAD.
* `RunnerCompletion`: the Runner-owned status as recorded in a Runner-owned
  evidence file (`STATUS_EVIDENCE_KINDS`), the completion / checkpoint
  facts and the attempt's authorized changed paths.
* `validation`: an exact FCP-8A-01 `ValidationAssessment`.
* `evidence`: a tuple of exact FCP-11A-01 `EvidenceRef`s.

Rules (all must hold for REVIEW_REQUESTABLE; any failure is a reason)
---------------------------------------------------------------------
* Version: `schema_version` is exactly int 1, and the validation contract
  this module was written against is still `fcp8a01-validation-assessment-v1`
  version 1 (a new version fails closed until reviewed).
* Identity: controller pinned at base; controller HEAD unchanged; target
  isolated from the controller; target HEAD is exactly the checkpoint
  commit (CHECKPOINT) or the attempt base HEAD (SUCCESS_NOOP).
* Status: SUCCESS recorded by the Runner, certified by Runner-owned
  acceptance (`work_status_source=RUNNER_ACCEPTANCE` under the
  `runner_acceptance` completion policy). A provider-sourced SUCCESS is
  provider words, never enough.
* Checkpoint: `ON_SUCCESS` policy, an OK decision consistent with the
  completion mode and, for CHECKPOINT, the exact Runner commit message.
* Scope: no authorized changed path is, aliases or covers a protected CI
  workflow (`is_protected_path`) - the historical FCP-10 / FCP-11 gates or
  the FCP-12 gate itself.
* Validation: READY_FOR_HUMAN_REVIEW.
* Evidence: every `REQUIRED_EVIDENCE_KINDS` entry exactly once; every
  reference PRESENT, unique and bound to this lineage.

Stdlib + sibling contracts only; no I/O, process, Git, network, clock or
environment access.
"""

from __future__ import annotations

import dataclasses
import fnmatch
import json
from dataclasses import dataclass
from typing import Optional

try:
    from scripts.ai import claude_runner as cr
    from scripts.ai import fabric_control_plane_contract as cp
    from scripts.ai import fabric_director as fd
    from scripts.ai import fabric_validation_contract as vc
    from scripts.ai import runner_pipeline as rp
except ImportError:  # pragma: no cover - direct script execution
    import claude_runner as cr  # type: ignore[no-redef]
    import fabric_control_plane_contract as cp  # type: ignore[no-redef]
    import fabric_director as fd  # type: ignore[no-redef]
    import fabric_validation_contract as vc  # type: ignore[no-redef]
    import runner_pipeline as rp  # type: ignore[no-redef]

SCHEMA = "fcp12a01-self-dogfood-closure-v1"
SCHEMA_VERSION = 1
DOGFOOD_MARKER = "FCP12A01_SELF_DOGFOOD_ADVISORY_ONLY_NOT_CERTIFIED_NOT_AUTHORIZED"

# The validation contract version this module was reviewed against.
SUPPORTED_VALIDATION_SCHEMA = "fcp8a01-validation-assessment-v1"
SUPPORTED_VALIDATION_SCHEMA_VERSION = 1

MAX_CHANGED_PATHS = 4096
MAX_PATH_CHARS = 4096

# Runner-owned evidence a closure must reference, each exactly once.
REQUIRED_EVIDENCE_KINDS = (
    "PIPELINE_RESULT", "WORKER_RECORD", "WORKER_RESULT", "ATTEMPT_METADATA", "ATTEMPT_RESULT",
    "ATTEMPT_WORK_PRODUCT", "FACTORY_EVENTS",
)
# Runner-written files whose recorded worker state is authoritative.
STATUS_EVIDENCE_KINDS = ("PIPELINE_RESULT", "WORKER_RESULT")
# CI that a self-dogfood attempt must never change: the historical FCP-10 /
# FCP-11 gates and FCP-12's own gate, so a self-dogfood work order can never
# weaken the workflow that judges it.
PROTECTED_PATHS = (
    ".github/workflows/fabric-ci.yml", ".github/workflows/fcp11-control-plane.yml",
    ".github/workflows/fcp12-self-dogfood.yml",
)

COMPLETION_MODES = (cr.COMPLETION_MODE_CHECKPOINT, cr.COMPLETION_MODE_SUCCESS_NOOP)
_CHECKPOINT_CREATED = "CREATED"
_CHECKPOINT_SKIPPED = "SKIPPED_NO_WORK_PRODUCT"

# Requested actions.
ACTION_REQUEST_HUMAN_REVIEW = "REQUEST_HUMAN_REVIEW"
ACTION_REQUEST_RELEASE = "REQUEST_RELEASE"
ACTIONS = (ACTION_REQUEST_HUMAN_REVIEW, ACTION_REQUEST_RELEASE)

# Decisions.
REVIEW_REQUESTABLE = "REVIEW_REQUESTABLE"
DENIED = "DENIED"
INVALID_REQUEST = "INVALID_REQUEST"
DECISIONS = (REVIEW_REQUESTABLE, DENIED, INVALID_REQUEST)

# Reason codes, in their fixed canonical order.
REQUEST_NOT_TYPED = "REQUEST_NOT_TYPED"
SCHEMA_UNSUPPORTED = "SCHEMA_UNSUPPORTED"
ACTION_UNKNOWN = "ACTION_UNKNOWN"
INVALID_REASONS = (REQUEST_NOT_TYPED, SCHEMA_UNSUPPORTED, ACTION_UNKNOWN)
IDENTITY_MALFORMED = "IDENTITY_MALFORMED"
CONTROLLER_NOT_AT_BASE = "CONTROLLER_NOT_AT_BASE"
CONTROLLER_HEAD_MOVED = "CONTROLLER_HEAD_MOVED"
TARGET_NOT_ISOLATED = "TARGET_NOT_ISOLATED"
TARGET_ISOLATION_UNKNOWN = "TARGET_ISOLATION_UNKNOWN"
TARGET_HEAD_UNEXPECTED = "TARGET_HEAD_UNEXPECTED"
LINEAGE_MALFORMED = "LINEAGE_MALFORMED"
COMPLETION_MALFORMED = "COMPLETION_MALFORMED"
STATUS_NOT_RUNNER_OWNED = "STATUS_NOT_RUNNER_OWNED"
STATUS_UNRECOGNIZED = "STATUS_UNRECOGNIZED"
WORKER_NOT_SUCCESS = "WORKER_NOT_SUCCESS"
COMPLETION_NOT_RUNNER_ACCEPTANCE = "COMPLETION_NOT_RUNNER_ACCEPTANCE"
SUCCESS_NOT_RUNNER_CERTIFIED = "SUCCESS_NOT_RUNNER_CERTIFIED"
CHECKPOINT_POLICY_MISSING = "CHECKPOINT_POLICY_MISSING"
CHECKPOINT_REFUSED = "CHECKPOINT_REFUSED"
CHECKPOINT_MALFORMED = "CHECKPOINT_MALFORMED"
CHECKPOINT_INCONSISTENT = "CHECKPOINT_INCONSISTENT"
CHECKPOINT_LINEAGE_MISMATCH = "CHECKPOINT_LINEAGE_MISMATCH"
COMPLETION_MODE_UNCLASSIFIED = "COMPLETION_MODE_UNCLASSIFIED"
PROTECTED_PATH_CHANGED = "PROTECTED_PATH_CHANGED"
VALIDATION_NOT_TYPED = "VALIDATION_NOT_TYPED"
VALIDATION_TAMPERED = "VALIDATION_TAMPERED"
VALIDATION_VERSION_UNSUPPORTED = "VALIDATION_VERSION_UNSUPPORTED"
VALIDATION_NOT_READY = "VALIDATION_NOT_READY"
EVIDENCE_NOT_TYPED = "EVIDENCE_NOT_TYPED"
EVIDENCE_REQUIRED_MISSING = "EVIDENCE_REQUIRED_MISSING"
EVIDENCE_DUPLICATE = "EVIDENCE_DUPLICATE"
EVIDENCE_NOT_PRESENT = "EVIDENCE_NOT_PRESENT"
EVIDENCE_PROVENANCE_MISMATCH = "EVIDENCE_PROVENANCE_MISMATCH"
RELEASE_REQUIRES_FCP3_HUMAN_AUTHORIZATION = "RELEASE_REQUIRES_FCP3_HUMAN_AUTHORIZATION"
REASONS = INVALID_REASONS + (
    IDENTITY_MALFORMED, CONTROLLER_NOT_AT_BASE, CONTROLLER_HEAD_MOVED, TARGET_NOT_ISOLATED, TARGET_ISOLATION_UNKNOWN,
    TARGET_HEAD_UNEXPECTED, LINEAGE_MALFORMED, COMPLETION_MALFORMED, STATUS_NOT_RUNNER_OWNED, STATUS_UNRECOGNIZED,
    WORKER_NOT_SUCCESS, COMPLETION_NOT_RUNNER_ACCEPTANCE, SUCCESS_NOT_RUNNER_CERTIFIED, CHECKPOINT_POLICY_MISSING,
    CHECKPOINT_REFUSED, CHECKPOINT_MALFORMED, CHECKPOINT_INCONSISTENT, CHECKPOINT_LINEAGE_MISMATCH,
    COMPLETION_MODE_UNCLASSIFIED, PROTECTED_PATH_CHANGED, VALIDATION_NOT_TYPED, VALIDATION_TAMPERED,
    VALIDATION_VERSION_UNSUPPORTED, VALIDATION_NOT_READY, EVIDENCE_NOT_TYPED, EVIDENCE_REQUIRED_MISSING,
    EVIDENCE_DUPLICATE, EVIDENCE_NOT_PRESENT, EVIDENCE_PROVENANCE_MISMATCH, RELEASE_REQUIRES_FCP3_HUMAN_AUTHORIZATION,
)


def _ordered(codes) -> tuple:
    return tuple(sorted(set(codes), key=REASONS.index))


def _commit(value) -> bool:
    return type(value) is str and cp._COMMIT_RE.fullmatch(value) is not None


def _in(value, vocabulary) -> bool:
    return type(value) is str and value in vocabulary


def _path_key(value: str) -> Optional[str]:
    """Case-folded, lexically resolved repository-relative key, used only to
    decide whether a path IS a protected path. Separators are unified;
    leading / redundant separators and `.` segments are dropped; `..` pops
    its parent; a Windows stream suffix (`:...`) and trailing dots / spaces
    of a segment are ignored, as Win32 does. Every folding can only make
    more paths match a protected key (deny more), never fewer. None when the
    path cannot be resolved without guessing: a `..` above the root or a
    segment that folds to nothing (`...`, `.. `, `:x`)."""
    segments = []
    for raw in value.strip().replace("\\", "/").split("/"):
        if raw in ("", "."):
            continue
        if raw == "..":
            if not segments:
                return None
            segments.pop()
            continue
        segment = raw.split(":", 1)[0].rstrip(". ")
        if segment == "":
            return None
        segments.append(segment)
    return "/".join(segments).casefold()


_PROTECTED_KEYS = frozenset(_path_key(p) for p in PROTECTED_PATHS)
_GLOB_CHARS = frozenset("*?[")


def is_protected_path(value) -> bool:
    """Fail-closed: True when `value` is, aliases or covers a protected path -
    any case / separator / dot-segment spelling, a parent directory (or the
    repository root) of one, a glob that `fnmatch` matches against one, or
    anything that is not a resolvable string. Canonical paths outside the
    protected set stay False."""
    if type(value) is not str:
        return True
    key = _path_key(value)
    if key is None:
        return True
    if key in _PROTECTED_KEYS or key == "" or any(p.startswith(key + "/") for p in _PROTECTED_KEYS):
        return True
    return any(ch in _GLOB_CHARS for ch in key) and any(fnmatch.fnmatchcase(p, key) for p in _PROTECTED_KEYS)


# ---------------------------------------------------------------------------
# Inputs (tainted; validated only by `assess_closure`)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DogfoodIdentity:
    base_commit: Optional[str] = None
    controller_commit: Optional[str] = None
    controller_head_observed: Optional[str] = None
    target_head_observed: Optional[str] = None
    target_isolated: Optional[bool] = None


@dataclass(frozen=True)
class DogfoodLineage:
    pipeline_id: Optional[str] = None
    worker_id: Optional[str] = None
    attempt: Optional[int] = None
    attempt_leaf: Optional[str] = None
    provider_id: Optional[str] = None
    attempt_base_head: Optional[str] = None


@dataclass(frozen=True)
class RunnerCompletion:
    status_evidence_kind: Optional[str] = None
    worker_state: Optional[str] = None
    completion_policy: Optional[str] = None
    work_status_source: Optional[str] = None
    checkpoint_policy: Optional[str] = None
    checkpoint_decision: Optional[str] = None
    checkpoint_commit: Optional[str] = None
    checkpoint_message: Optional[str] = None
    authorized_changed_paths: tuple = ()
    work_product_present: Optional[bool] = None


@dataclass(frozen=True)
class CloseRequest:
    schema_version: object = None
    action: Optional[str] = None
    identity: object = None
    lineage: object = None
    completion: object = None
    validation: object = None
    evidence: object = ()


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

class _DogfoodGuarantees(vc._NotAuthorized):
    """FCP-8A-01 zero-authority flags plus the closure-specific ones."""

    @property
    def release_allowed(self) -> bool:
        return False

    @property
    def human_approval_granted(self) -> bool:
        return False

    @property
    def host_ci_verified(self) -> bool:
        return False

    @property
    def closure_complete(self) -> bool:
        return False

    @property
    def git_allowed(self) -> bool:
        return False

    @property
    def ledger_write_allowed(self) -> bool:
        return False

    @staticmethod
    def _guarantees() -> dict:
        guarantees = vc._NotAuthorized._guarantees()
        guarantees.update(marker=DOGFOOD_MARKER, release_allowed=False, human_approval_granted=False,
                          host_ci_verified=False, closure_complete=False, git_allowed=False,
                          ledger_write_allowed=False)
        return guarantees


@dataclass(frozen=True)
class DogfoodClosureAssessment(_DogfoodGuarantees):
    """Explainable advisory closure result. Construction re-checks every
    invariant, so a hand-made assessment cannot claim more than its reasons
    allow."""
    decision: str
    reasons: tuple
    completion_mode: Optional[str] = None

    def __post_init__(self):
        if not _in(self.decision, DECISIONS):
            raise ValueError("unknown closure decision")
        if not (type(self.reasons) is tuple and all(_in(r, REASONS) for r in self.reasons)
                and self.reasons == _ordered(self.reasons)):
            raise ValueError("reasons must be ordered closure reason codes")
        if not (self.completion_mode is None or _in(self.completion_mode, COMPLETION_MODES)):
            raise ValueError("unknown completion mode")
        invalid = any(r in INVALID_REASONS for r in self.reasons)
        if self.decision == REVIEW_REQUESTABLE:
            if self.reasons or self.completion_mode is None:
                raise ValueError("REVIEW_REQUESTABLE needs no reasons and a classified completion mode")
        elif self.decision == DENIED:
            if not self.reasons or invalid:
                raise ValueError("DENIED needs at least one non-invalid reason")
        elif not invalid or self.completion_mode is not None:
            raise ValueError("INVALID_REQUEST needs an invalid-request reason and no completion mode")

    @property
    def review_requestable(self) -> bool:
        return self.decision == REVIEW_REQUESTABLE

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA, "schema_version": SCHEMA_VERSION, "decision": self.decision,
            "review_requestable": self.decision == REVIEW_REQUESTABLE, "completion_mode": self.completion_mode,
            "reasons": list(self.reasons), **_DogfoodGuarantees._guarantees(),
        }


def canonical_json(assessment: DogfoodClosureAssessment) -> str:
    """Stable, sorted, compact serialization of the exact contract type."""
    if type(assessment) is not DogfoodClosureAssessment:
        raise TypeError("canonical_json accepts only a DogfoodClosureAssessment")
    return json.dumps(DogfoodClosureAssessment.to_dict(assessment), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True)


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

def _rebuilt(value):
    """Re-run a frozen contract type's own constructor guard on its current
    field values, so an `object.__setattr__`-tampered instance is refused."""
    try:
        return type(value)(**{f.name: getattr(value, f.name) for f in dataclasses.fields(value)}) == value
    except (TypeError, ValueError):
        return False


def _lineage_ok(lineage) -> bool:
    return (
        type(lineage) is DogfoodLineage and cp.valid_id(lineage.pipeline_id) and cp.valid_id(lineage.worker_id)
        and cp.valid_id(lineage.provider_id) and type(lineage.attempt) is int
        and 1 <= lineage.attempt <= cp.MAX_ATTEMPTS and type(lineage.attempt_leaf) is str
        and cp._ATTEMPT_LEAF_RE.fullmatch(lineage.attempt_leaf) is not None and _commit(lineage.attempt_base_head)
    )


def _paths_ok(paths) -> bool:
    return type(paths) is tuple and len(paths) <= MAX_CHANGED_PATHS and all(
        type(p) is str and 0 < len(p) <= MAX_PATH_CHARS and "\x00" not in p for p in paths
    )


def _completion_reasons(completion, lineage, lineage_ok: bool) -> tuple:
    """(reasons, completion_mode)."""
    if type(completion) is not RunnerCompletion:
        return [COMPLETION_MALFORMED], None
    c = completion
    reasons = []
    if not _in(c.status_evidence_kind, STATUS_EVIDENCE_KINDS):
        reasons.append(STATUS_NOT_RUNNER_OWNED)
    if not _in(c.worker_state, cp.WORKER_STATES):
        reasons.append(STATUS_UNRECOGNIZED)
    elif c.worker_state != rp.WorkerState.SUCCESS.value:
        reasons.append(WORKER_NOT_SUCCESS)
    if not _in(c.completion_policy, (cr.COMPLETION_POLICY_RUNNER_ACCEPTANCE,)):
        reasons.append(COMPLETION_NOT_RUNNER_ACCEPTANCE)
    if not _in(c.work_status_source, (cr.WORK_STATUS_SOURCE_RUNNER_ACCEPTANCE,)):
        reasons.append(SUCCESS_NOT_RUNNER_CERTIFIED)
    if not _in(c.checkpoint_policy, cr.CHECKPOINT_POLICIES):
        reasons.append(CHECKPOINT_POLICY_MISSING)
    if not _in(c.checkpoint_decision, cr.CHECKPOINT_OK_DECISIONS):
        reasons.append(CHECKPOINT_REFUSED)
    paths_ok = _paths_ok(c.authorized_changed_paths)
    present_ok = c.work_product_present is None or type(c.work_product_present) is bool
    if not (paths_ok and present_ok):
        reasons.append(COMPLETION_MALFORMED)
    elif any(is_protected_path(p) for p in c.authorized_changed_paths):
        reasons.append(PROTECTED_PATH_CHANGED)
    if not (c.checkpoint_commit is None or _commit(c.checkpoint_commit)) or not (
            c.checkpoint_message is None or type(c.checkpoint_message) is str):
        reasons.append(CHECKPOINT_MALFORMED)
        return reasons, None
    if not (paths_ok and present_ok):
        return reasons, None
    mode = fd._classify_completion_mode(
        worker_state=c.worker_state if type(c.worker_state) is str else None,
        checkpoint_commit=c.checkpoint_commit, authorized_changed_paths=c.authorized_changed_paths,
        work_product_present=c.work_product_present,
    )
    if mode is None:
        reasons.append(COMPLETION_MODE_UNCLASSIFIED)
    elif mode == cr.COMPLETION_MODE_CHECKPOINT:
        if c.checkpoint_decision != _CHECKPOINT_CREATED or not c.authorized_changed_paths:
            reasons.append(CHECKPOINT_INCONSISTENT)
        if not lineage_ok:
            reasons.append(CHECKPOINT_LINEAGE_MISMATCH)
        else:
            expected = cr.build_checkpoint_message(
                pipeline_id=lineage.pipeline_id, worker_id=lineage.worker_id, attempt=lineage.attempt,
                provider_id=lineage.provider_id, base_head=lineage.attempt_base_head,
            )
            if c.checkpoint_message != expected or c.checkpoint_commit == lineage.attempt_base_head:
                reasons.append(CHECKPOINT_LINEAGE_MISMATCH)
    elif c.checkpoint_decision != _CHECKPOINT_SKIPPED or c.checkpoint_message is not None:
        reasons.append(CHECKPOINT_INCONSISTENT)
    return reasons, mode


def _identity_reasons(identity, completion, lineage, lineage_ok: bool, mode) -> list:
    if type(identity) is not DogfoodIdentity:
        return [IDENTITY_MALFORMED]
    i = identity
    commits = (i.base_commit, i.controller_commit, i.controller_head_observed, i.target_head_observed)
    reasons = []
    if not all(_commit(v) for v in commits):
        reasons.append(IDENTITY_MALFORMED)
    else:
        if i.controller_commit != i.base_commit:
            reasons.append(CONTROLLER_NOT_AT_BASE)
        if i.controller_head_observed != i.controller_commit:
            reasons.append(CONTROLLER_HEAD_MOVED)
        if mode == cr.COMPLETION_MODE_CHECKPOINT:
            expected_head = completion.checkpoint_commit
        elif mode == cr.COMPLETION_MODE_SUCCESS_NOOP and lineage_ok:
            expected_head = lineage.attempt_base_head
        else:
            expected_head = None
        if expected_head is None or i.target_head_observed != expected_head:
            reasons.append(TARGET_HEAD_UNEXPECTED)
    if i.target_isolated is False:
        reasons.append(TARGET_NOT_ISOLATED)
    elif i.target_isolated is not True:
        reasons.append(TARGET_ISOLATION_UNKNOWN)
    return reasons


def _validation_reasons(validation) -> list:
    if type(validation) is not vc.ValidationAssessment:
        return [VALIDATION_NOT_TYPED]
    if (vc.SCHEMA, vc.SCHEMA_VERSION) != (SUPPORTED_VALIDATION_SCHEMA, SUPPORTED_VALIDATION_SCHEMA_VERSION):
        return [VALIDATION_VERSION_UNSUPPORTED]
    if not _rebuilt(validation):
        return [VALIDATION_TAMPERED]
    if validation.classification != vc.READY_FOR_HUMAN_REVIEW or validation.ready_for_human_review is not True:
        return [VALIDATION_NOT_READY]
    return []


def _evidence_reasons(evidence, lineage, lineage_ok: bool) -> list:
    if not (type(evidence) is tuple and len(evidence) <= cp.MAX_EVIDENCE_REFS
            and all(type(e) is cp.EvidenceRef for e in evidence) and all(_rebuilt(e) for e in evidence)):
        return [EVIDENCE_NOT_TYPED]
    reasons = []
    kinds = [e.kind for e in evidence]
    if any(kinds.count(k) != 1 for k in REQUIRED_EVIDENCE_KINDS if k in kinds):
        reasons.append(EVIDENCE_DUPLICATE)
    if len({e.sort_key() for e in evidence}) != len(evidence):
        reasons.append(EVIDENCE_DUPLICATE)
    if any(k not in kinds for k in REQUIRED_EVIDENCE_KINDS):
        reasons.append(EVIDENCE_REQUIRED_MISSING)
    if any(e.condition != cp.PRESENT for e in evidence):
        reasons.append(EVIDENCE_NOT_PRESENT)
    for e in evidence:
        if not lineage_ok:
            reasons.append(EVIDENCE_PROVENANCE_MISMATCH)
            break
        bound = (
            e.pipeline_id in (None, lineage.pipeline_id) and e.worker_id in (None, lineage.worker_id)
            and e.attempt_leaf in (None, lineage.attempt_leaf)
        )
        if not bound:
            reasons.append(EVIDENCE_PROVENANCE_MISMATCH)
    return reasons


# ---------------------------------------------------------------------------
# Assessment
# ---------------------------------------------------------------------------

def _invalid(*reasons) -> DogfoodClosureAssessment:
    return DogfoodClosureAssessment(decision=INVALID_REQUEST, reasons=_ordered(reasons))


def assess_closure(request: CloseRequest) -> DogfoodClosureAssessment:
    """Pure, deterministic, deny-by-default closure assessment. Never raises
    on bad input and never certifies, approves, releases, promotes, merges,
    commits or records anything."""
    if type(request) is not CloseRequest:
        return _invalid(REQUEST_NOT_TYPED)
    invalid = []
    if type(request.schema_version) is not int or request.schema_version != SCHEMA_VERSION:
        invalid.append(SCHEMA_UNSUPPORTED)
    if not _in(request.action, ACTIONS):
        invalid.append(ACTION_UNKNOWN)
    if invalid:
        return _invalid(*invalid)
    lineage = request.lineage
    lineage_ok = _lineage_ok(lineage)
    reasons = [] if lineage_ok else [LINEAGE_MALFORMED]
    completion_reasons, mode = _completion_reasons(request.completion, lineage, lineage_ok)
    reasons += completion_reasons
    reasons += _identity_reasons(request.identity, request.completion, lineage, lineage_ok, mode)
    reasons += _validation_reasons(request.validation)
    reasons += _evidence_reasons(request.evidence, lineage, lineage_ok)
    if request.action == ACTION_REQUEST_RELEASE:
        reasons.append(RELEASE_REQUIRES_FCP3_HUMAN_AUTHORIZATION)
    reasons = _ordered(reasons)
    return DogfoodClosureAssessment(decision=DENIED if reasons else REVIEW_REQUESTABLE, reasons=reasons,
                                    completion_mode=mode)
