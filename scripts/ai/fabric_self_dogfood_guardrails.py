"""FCP-12A-02: Self-Dogfood isolation guardrails V1 - pure, deterministic,
fail-closed, ADVISORY-ONLY check that a governed self-dogfood attempt keeps
the stable controller apart from the feature worktree it develops.

What it answers
---------------
"Do these caller-captured snapshots prove that the controller cannot modify
itself and that the target worktree is not being used as the controller?" -
and nothing more. The best possible outcome is `ISOLATION_HOLDS`; it never
authorizes, approves, promotes, merges, commits or records anything. A
`SELF_PROMOTE` action is always DENIED: real promotion stays exclusively
behind the existing FCP-3 human authorization, which this module neither
creates nor can satisfy, and no externally supplied authorization is ever
accepted as authority here.

No Git, no filesystem
---------------------
This library never runs Git (mutating or not), never resolves paths and
never reads the filesystem, the environment or the clock. The Runner (or an
operator) captures the facts with its own governed Git (`runner_git`) and
path resolution and hands them over as frozen snapshots; this module only
judges them. Symlinks, junctions and aliases are therefore judged from the
observed facts: the declared path must equal the resolved path and the
caller must positively report that no link component was observed.

Reuse, never redefine
---------------------
* Self-target rule: `runner_pipeline.is_unsafe_self_target` (applied in
  addition to the stricter canonical-key overlap below).
* Branch guard: `claude_runner.evaluate_branch_guard` / `GitSnapshot` /
  `PROTECTED_BRANCHES`; status sentinel `GIT_STATUS_UNAVAILABLE`.
* Write scope: `claude_runner.evaluate_write_scope`, `path_is_authorized`,
  `classify_changed_paths` and `extract_paths_from_porcelain_line`.
* Commit grammar: FCP-11A-01 control-plane contract.
* Protected CI paths (historical FCP-10 / FCP-11 and FCP-12's own gate),
  `is_protected_path` and zero-authority flags: the FCP-12A-01 closure
  contract (`fabric_self_dogfood_contract`), whose `DogfoodIdentity`
  `closure_identity` fills from a re-run assessment. A scope that names,
  aliases or covers a protected path is `SCOPE_TOO_BROAD`; a changed path
  that does is `PROTECTED_PATH_CHANGED`.

Inputs (frozen, TAINTED; validated only by `assess_guardrails`)
---------------------------------------------------------------
* `IsolationPlan`: declared, pinned facts (base / controller commits,
  controller and target worktree paths, target branch, attempt base HEAD,
  authorized write scopes).
* `WorktreeSnapshot`: one observation of one worktree (declared / resolved
  path, link observation, git dir, common dir, branch, HEAD, porcelain v1).
* `ControllerProcess`: where the running controller executes from.
* `GuardrailRequest`: action, plan, process, controller / target snapshots
  before (and, for CONFIRM_ISOLATION / SELF_PROMOTE, after) the attempt, the
  optional checkpoint commit the Runner wrote, and `external_authorization`
  (must be None; any value is refused, never trusted).

Stdlib + sibling contracts only; never raises on bad input; raw input text
is never echoed: the output holds only enumerated codes and a digest.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Optional

try:
    from scripts.ai import claude_runner as cr
    from scripts.ai import fabric_control_plane_contract as cp
    from scripts.ai import fabric_self_dogfood_contract as dc
    from scripts.ai import runner_pipeline as rp
except ImportError:  # pragma: no cover - direct script execution
    import claude_runner as cr  # type: ignore[no-redef]
    import fabric_control_plane_contract as cp  # type: ignore[no-redef]
    import fabric_self_dogfood_contract as dc  # type: ignore[no-redef]
    import runner_pipeline as rp  # type: ignore[no-redef]

SCHEMA = "fcp12a02-self-dogfood-guardrails-v1"
SCHEMA_VERSION = 1
GUARDRAILS_MARKER = "FCP12A02_SELF_DOGFOOD_GUARDRAILS_ADVISORY_ONLY_NOT_AUTHORIZED"

# The closure contract version this module was reviewed against.
SUPPORTED_CONTRACT_SCHEMA = "fcp12a01-self-dogfood-closure-v1"
SUPPORTED_CONTRACT_SCHEMA_VERSION = 1

MAX_PATH_CHARS = 1024
MAX_BRANCH_CHARS = 200
MAX_SCOPES = 64
MAX_STATUS_LINES = 4096

# Requested actions.
ACTION_ADMIT_ATTEMPT = "ADMIT_ATTEMPT"
ACTION_CONFIRM_ISOLATION = "CONFIRM_ISOLATION"
ACTION_SELF_PROMOTE = "SELF_PROMOTE"
ACTIONS = (ACTION_ADMIT_ATTEMPT, ACTION_CONFIRM_ISOLATION, ACTION_SELF_PROMOTE)
_POST_ACTIONS = (ACTION_CONFIRM_ISOLATION, ACTION_SELF_PROMOTE)

# Decisions.
ISOLATION_HOLDS = "ISOLATION_HOLDS"
DENIED = "DENIED"
INVALID_REQUEST = "INVALID_REQUEST"
DECISIONS = (ISOLATION_HOLDS, DENIED, INVALID_REQUEST)

# Reason codes, in their fixed canonical order.
REQUEST_NOT_TYPED = "REQUEST_NOT_TYPED"
SCHEMA_UNSUPPORTED = "SCHEMA_UNSUPPORTED"
ACTION_UNKNOWN = "ACTION_UNKNOWN"
INVALID_REASONS = (REQUEST_NOT_TYPED, SCHEMA_UNSUPPORTED, ACTION_UNKNOWN)
CONTRACT_VERSION_UNSUPPORTED = "CONTRACT_VERSION_UNSUPPORTED"
PLAN_MALFORMED = "PLAN_MALFORMED"
SNAPSHOT_MALFORMED = "SNAPSHOT_MALFORMED"
PATH_MALFORMED = "PATH_MALFORMED"
CONTROLLER_NOT_AT_BASE = "CONTROLLER_NOT_AT_BASE"
REPOSITORY_MISMATCH = "REPOSITORY_MISMATCH"
SAME_WORKTREE = "SAME_WORKTREE"
WORKTREE_OVERLAP = "WORKTREE_OVERLAP"
PATH_MISMATCH = "PATH_MISMATCH"
PATH_NOT_CANONICAL = "PATH_NOT_CANONICAL"
SYMLINK_PRESENT = "SYMLINK_PRESENT"
SYMLINK_UNPROVEN = "SYMLINK_UNPROVEN"
CONTROLLER_RUNS_FROM_TARGET = "CONTROLLER_RUNS_FROM_TARGET"
CONTROLLER_LOCATION_UNPROVEN = "CONTROLLER_LOCATION_UNPROVEN"
CONTROLLER_NOT_DETACHED = "CONTROLLER_NOT_DETACHED"
CONTROLLER_HEAD_UNEXPECTED = "CONTROLLER_HEAD_UNEXPECTED"
CONTROLLER_DIRTY = "CONTROLLER_DIRTY"
CONTROLLER_DRIFT = "CONTROLLER_DRIFT"
TARGET_BRANCH_PROTECTED = "TARGET_BRANCH_PROTECTED"
TARGET_BRANCH_UNEXPECTED = "TARGET_BRANCH_UNEXPECTED"
TARGET_HEAD_UNEXPECTED = "TARGET_HEAD_UNEXPECTED"
TARGET_DIRTY_AT_START = "TARGET_DIRTY_AT_START"
TARGET_DRIFT = "TARGET_DRIFT"
TARGET_HEAD_DRIFT = "TARGET_HEAD_DRIFT"
STATUS_UNAVAILABLE = "STATUS_UNAVAILABLE"
SCOPE_MISSING = "SCOPE_MISSING"
SCOPE_INVALID = "SCOPE_INVALID"
SCOPE_TOO_BROAD = "SCOPE_TOO_BROAD"
SCOPE_VIOLATION = "SCOPE_VIOLATION"
PROTECTED_PATH_CHANGED = "PROTECTED_PATH_CHANGED"
EXTERNAL_AUTHORIZATION_NOT_ACCEPTED = "EXTERNAL_AUTHORIZATION_NOT_ACCEPTED"
SELF_PROMOTION_REQUIRES_FCP3_HUMAN_AUTHORIZATION = "SELF_PROMOTION_REQUIRES_FCP3_HUMAN_AUTHORIZATION"
REASONS = INVALID_REASONS + (
    CONTRACT_VERSION_UNSUPPORTED, PLAN_MALFORMED, SNAPSHOT_MALFORMED, PATH_MALFORMED, CONTROLLER_NOT_AT_BASE,
    REPOSITORY_MISMATCH, SAME_WORKTREE, WORKTREE_OVERLAP, PATH_MISMATCH, PATH_NOT_CANONICAL, SYMLINK_PRESENT,
    SYMLINK_UNPROVEN, CONTROLLER_RUNS_FROM_TARGET, CONTROLLER_LOCATION_UNPROVEN, CONTROLLER_NOT_DETACHED,
    CONTROLLER_HEAD_UNEXPECTED, CONTROLLER_DIRTY, CONTROLLER_DRIFT, TARGET_BRANCH_PROTECTED,
    TARGET_BRANCH_UNEXPECTED, TARGET_HEAD_UNEXPECTED, TARGET_DIRTY_AT_START, TARGET_DRIFT, TARGET_HEAD_DRIFT,
    STATUS_UNAVAILABLE, SCOPE_MISSING, SCOPE_INVALID, SCOPE_TOO_BROAD, SCOPE_VIOLATION, PROTECTED_PATH_CHANGED,
    EXTERNAL_AUTHORIZATION_NOT_ACCEPTED, SELF_PROMOTION_REQUIRES_FCP3_HUMAN_AUTHORIZATION,
)

# `git rev-parse --abbrev-ref HEAD` prints "HEAD" on a detached checkout.
_DETACHED = "HEAD"
_DRIVE_RE = re.compile(r"[A-Za-z]:/")
_FORBIDDEN_SEGMENT_CHARS = frozenset('<>:"|?*')
_SHORT_NAME_RE = re.compile(r".*~[0-9].*")
_BRANCH_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")
_GIT_SEGMENT = ".git"
_GIT_PROBE = ".git/config"


def _ordered(codes) -> tuple:
    return tuple(sorted(set(codes), key=REASONS.index))


def _commit(value) -> bool:
    return type(value) is str and cp._COMMIT_RE.fullmatch(value) is not None


def canonical_path_key(value) -> Optional[str]:
    """Comparison key of an absolute, already-resolved, canonical path, or
    None for anything relative, aliasing or hostile: control characters,
    UNC / device prefixes (`\\\\server`, `\\\\?\\`), `.` / `..` / empty
    segments, a trailing separator, Windows stream / wildcard characters,
    trailing dots or spaces, 8.3 short names and bare roots. The key is
    case-folded, which can only make paths compare equal or overlapping more
    often - i.e. deny more, never less."""
    if type(value) is not str or not 0 < len(value) <= MAX_PATH_CHARS:
        return None
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        return None
    path = value.replace("\\", "/")
    if path.startswith("//"):
        return None
    if _DRIVE_RE.match(path):
        root, rest = path[:2].lower(), path[3:]
    elif path.startswith("/"):
        root, rest = "", path[1:]
    else:
        return None
    segments = rest.split("/")
    for segment in segments:
        if segment in ("", ".", "..") or segment[-1] in ". " or segment.startswith(" "):
            return None
        if any(ch in _FORBIDDEN_SEGMENT_CHARS for ch in segment) or _SHORT_NAME_RE.fullmatch(segment):
            return None
    return (root + "/" + "/".join(segments)).casefold()


def _overlap(a: str, b: str) -> bool:
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def _branch_ok(value) -> bool:
    return (
        type(value) is str and 0 < len(value) <= MAX_BRANCH_CHARS and _BRANCH_RE.fullmatch(value) is not None
        and ".." not in value and "//" not in value and not value.endswith(("/", ".", ".lock"))
        and all(not s.startswith(".") for s in value.split("/")) and value != _DETACHED
    )


# ---------------------------------------------------------------------------
# Inputs (tainted; validated only by `assess_guardrails`)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class IsolationPlan:
    base_commit: Optional[str] = None
    controller_commit: Optional[str] = None
    controller_path: Optional[str] = None
    target_path: Optional[str] = None
    target_branch: Optional[str] = None
    attempt_base_head: Optional[str] = None
    authorized_scopes: tuple = ()


@dataclass(frozen=True)
class WorktreeSnapshot:
    declared_path: Optional[str] = None
    resolved_path: Optional[str] = None
    link_component_observed: Optional[bool] = None
    git_dir: Optional[str] = None
    git_common_dir: Optional[str] = None
    branch: Optional[str] = None
    head: Optional[str] = None
    porcelain_status: Optional[str] = None


@dataclass(frozen=True)
class ControllerProcess:
    module_path: Optional[str] = None
    worktree_top: Optional[str] = None


@dataclass(frozen=True)
class GuardrailRequest:
    schema_version: object = None
    action: Optional[str] = None
    plan: object = None
    process: object = None
    controller_before: object = None
    target_before: object = None
    controller_after: object = None
    target_after: object = None
    target_checkpoint_commit: Optional[str] = None
    external_authorization: object = None


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

class _GuardrailGuarantees(dc._DogfoodGuarantees):
    """FCP-12A-01 zero-authority flags plus the guardrail-specific ones."""

    @property
    def self_promotion_allowed(self) -> bool:
        return False

    @property
    def external_authorization_accepted(self) -> bool:
        return False

    @staticmethod
    def _guarantees() -> dict:
        guarantees = dc._DogfoodGuarantees._guarantees()
        guarantees.update(guardrails_marker=GUARDRAILS_MARKER, self_promotion_allowed=False,
                          external_authorization_accepted=False)
        return guarantees


@dataclass(frozen=True)
class GuardrailAssessment(_GuardrailGuarantees):
    """Explainable advisory isolation result. Construction re-checks every
    invariant, so a hand-made assessment cannot claim more than its reasons
    allow. `binding` digests the validated facts the decision is bound to."""
    decision: str
    reasons: tuple
    action: Optional[str] = None
    binding: Optional[str] = None

    def __post_init__(self):
        if not (type(self.decision) is str and self.decision in DECISIONS):
            raise ValueError("unknown guardrail decision")
        if not (type(self.reasons) is tuple and all(type(r) is str and r in REASONS for r in self.reasons)
                and self.reasons == _ordered(self.reasons)):
            raise ValueError("reasons must be ordered guardrail reason codes")
        if not (self.action is None or (type(self.action) is str and self.action in ACTIONS)):
            raise ValueError("unknown guardrail action")
        if not (self.binding is None or (type(self.binding) is str and re.fullmatch(r"[0-9a-f]{64}", self.binding))):
            raise ValueError("binding must be a sha256 hex digest")
        invalid = any(r in INVALID_REASONS for r in self.reasons)
        if self.decision == ISOLATION_HOLDS:
            if self.reasons or self.binding is None or self.action not in (ACTION_ADMIT_ATTEMPT,
                                                                           ACTION_CONFIRM_ISOLATION):
                raise ValueError("ISOLATION_HOLDS needs no reasons, a binding and a non-promotion action")
        elif self.decision == DENIED:
            if not self.reasons or invalid or self.binding is not None or self.action is None:
                raise ValueError("DENIED needs non-invalid reasons, an action and no binding")
        elif not invalid or self.binding is not None:
            raise ValueError("INVALID_REQUEST needs an invalid-request reason and no binding")

    @property
    def isolation_holds(self) -> bool:
        return self.decision == ISOLATION_HOLDS

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA, "schema_version": SCHEMA_VERSION, "decision": self.decision,
            "isolation_holds": self.decision == ISOLATION_HOLDS, "action": self.action,
            "binding": self.binding, "reasons": list(self.reasons), **_GuardrailGuarantees._guarantees(),
        }


def canonical_json(assessment: GuardrailAssessment) -> str:
    """Stable, sorted, compact serialization of the exact contract type."""
    if type(assessment) is not GuardrailAssessment:
        raise TypeError("canonical_json accepts only a GuardrailAssessment")
    return json.dumps(GuardrailAssessment.to_dict(assessment), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True)


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

def _plan_reasons(plan) -> tuple:
    """(reasons, normalized_scopes or None)."""
    if type(plan) is not IsolationPlan:
        return [PLAN_MALFORMED], None
    p = plan
    reasons = []
    if not all(_commit(v) for v in (p.base_commit, p.controller_commit, p.attempt_base_head)):
        reasons.append(PLAN_MALFORMED)
    elif p.controller_commit != p.base_commit:
        reasons.append(CONTROLLER_NOT_AT_BASE)
    if not _branch_ok(p.target_branch):
        reasons.append(PLAN_MALFORMED)
    elif p.target_branch in cr.PROTECTED_BRANCHES:
        reasons.append(TARGET_BRANCH_PROTECTED)
    controller, target = canonical_path_key(p.controller_path), canonical_path_key(p.target_path)
    if controller is None or target is None:
        reasons.append(PATH_MALFORMED)
    else:
        if controller == target:
            reasons.append(SAME_WORKTREE)
        elif _overlap(controller, target):
            reasons.append(WORKTREE_OVERLAP)
        if rp.is_unsafe_self_target(target, controller):
            reasons.append(WORKTREE_OVERLAP if controller != target else SAME_WORKTREE)
    scopes = p.authorized_scopes
    if not (type(scopes) is tuple and len(scopes) <= MAX_SCOPES and all(type(s) is str for s in scopes)):
        reasons.append(PLAN_MALFORMED)
        return reasons, None
    if not scopes:
        reasons.append(SCOPE_MISSING)
        return reasons, None
    if any(len(s) > MAX_PATH_CHARS or any(ord(ch) < 32 or ord(ch) == 127 for ch in s) for s in scopes):
        reasons.append(SCOPE_INVALID)
        return reasons, None
    decision = cr.evaluate_write_scope(list(scopes))
    if decision.decision != "ALLOWED":
        reasons.append(SCOPE_INVALID)
        return reasons, None
    normalized = tuple(decision.authorized_scopes)
    folded = [s.casefold() for s in normalized]
    probes = tuple(dc.PROTECTED_PATHS) + (_GIT_PROBE,)
    if (any(_GIT_SEGMENT in s.split("/") for s in folded)
            or any(cr.path_is_authorized(probe, folded) for probe in probes)
            or any(dc.is_protected_path(s) for s in normalized)):
        reasons.append(SCOPE_TOO_BROAD)
    return reasons, normalized


def _snapshot_keys(snapshot) -> Optional[tuple]:
    """(declared, resolved, git_dir, common_dir) keys, or None if malformed."""
    if type(snapshot) is not WorktreeSnapshot:
        return None
    keys = tuple(canonical_path_key(v) for v in (snapshot.declared_path, snapshot.resolved_path,
                                                 snapshot.git_dir, snapshot.git_common_dir))
    return None if any(k is None for k in keys) else keys


def _snapshot_shape_ok(snapshot) -> bool:
    s = snapshot
    return (
        type(s) is WorktreeSnapshot and _commit(s.head) and type(s.porcelain_status) is str
        and (s.link_component_observed is None or type(s.link_component_observed) is bool)
        and type(s.branch) is str and 0 < len(s.branch) <= MAX_BRANCH_CHARS
    )


def _link_reasons(snapshot, keys) -> list:
    reasons = []
    if keys[0] != keys[1]:
        reasons.append(PATH_NOT_CANONICAL)
    if snapshot.link_component_observed is True:
        reasons.append(SYMLINK_PRESENT)
    elif snapshot.link_component_observed is not False:
        reasons.append(SYMLINK_UNPROVEN)
    return reasons


def _status_lines(status: str) -> Optional[list]:
    """Porcelain v1 entry lines, [] when clean, None when unavailable or
    malformed."""
    if status == cr.GIT_STATUS_UNAVAILABLE:
        return None
    lines = [line for line in status.splitlines() if line != ""]
    if len(lines) > MAX_STATUS_LINES or any(len(line) < 4 or "\x00" in line for line in lines):
        return None
    return lines


def _changed_path_safe(path: str) -> bool:
    candidate = path.strip().replace("\\", "/")
    segments = candidate.split("/")
    return (
        candidate != "" and not candidate.startswith("/") and not (len(candidate) >= 2 and candidate[1] == ":")
        and ".." not in segments and _GIT_SEGMENT not in (s.casefold() for s in segments)
    )


def _scope_reasons(lines: list, scopes: tuple) -> list:
    reasons = []
    paths = [p for line in lines for p in cr.extract_paths_from_porcelain_line(line)]
    if any(dc.is_protected_path(p) for p in paths):
        reasons.append(PROTECTED_PATH_CHANGED)
    _authorized, unauthorized = cr.classify_changed_paths(lines, list(scopes))
    if unauthorized or not all(_changed_path_safe(p) for p in paths):
        reasons.append(SCOPE_VIOLATION)
    return reasons


def _process_reasons(process, controller: Optional[str], target: Optional[str]) -> list:
    if type(process) is not ControllerProcess:
        return [CONTROLLER_LOCATION_UNPROVEN]
    module, top = canonical_path_key(process.module_path), canonical_path_key(process.worktree_top)
    if module is None or top is None:
        return [PATH_MALFORMED, CONTROLLER_LOCATION_UNPROVEN]
    reasons = []
    if target is not None and (_overlap(module, target) or _overlap(top, target)
                               or rp.is_unsafe_self_target(target, top)):
        reasons.append(CONTROLLER_RUNS_FROM_TARGET)
    if controller is None or top != controller or not module.startswith(controller + "/"):
        reasons.append(CONTROLLER_LOCATION_UNPROVEN)
    return reasons


def _branch_guard(snapshot) -> str:
    return cr.evaluate_branch_guard(cr.GitSnapshot(branch=snapshot.branch, head=snapshot.head,
                                                   porcelain_status=snapshot.porcelain_status, raw_text="",
                                                   captured_at="")).decision


def _controller_reasons(snapshot, keys, plan, plan_ok: bool, controller_key) -> list:
    reasons = _link_reasons(snapshot, keys)
    if controller_key is not None and keys[1] != controller_key:
        reasons.append(PATH_MISMATCH)
    if _branch_guard(snapshot) != "REFUSED_DETACHED_HEAD":
        reasons.append(CONTROLLER_NOT_DETACHED)
    if plan_ok and snapshot.head != plan.controller_commit:
        reasons.append(CONTROLLER_HEAD_UNEXPECTED)
    lines = _status_lines(snapshot.porcelain_status)
    if lines is None:
        reasons.append(STATUS_UNAVAILABLE)
    elif lines:
        reasons.append(CONTROLLER_DIRTY)
    return reasons


def _target_reasons(snapshot, keys, plan, target_key) -> list:
    reasons = _link_reasons(snapshot, keys)
    if target_key is not None and keys[1] != target_key:
        reasons.append(PATH_MISMATCH)
    guard = _branch_guard(snapshot)
    if guard == "REFUSED_PROTECTED_BRANCH":
        reasons.append(TARGET_BRANCH_PROTECTED)
    if guard != "ALLOWED" or not (type(plan) is IsolationPlan and snapshot.branch == plan.target_branch):
        reasons.append(TARGET_BRANCH_UNEXPECTED)
    return reasons


def _binding(request: GuardrailRequest, scopes: tuple) -> str:
    plan = request.plan
    after = request.action in _POST_ACTIONS
    facts = {
        "schema": SCHEMA, "action": request.action, "base_commit": plan.base_commit,
        "controller_commit": plan.controller_commit, "attempt_base_head": plan.attempt_base_head,
        "controller_path": canonical_path_key(plan.controller_path),
        "target_path": canonical_path_key(plan.target_path), "target_branch": plan.target_branch,
        "authorized_scopes": list(scopes),
        "controller_head": (request.controller_after if after else request.controller_before).head,
        "target_head": (request.target_after if after else request.target_before).head,
        "target_checkpoint_commit": request.target_checkpoint_commit,
    }
    payload = json.dumps(facts, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


# ---------------------------------------------------------------------------
# Assessment
# ---------------------------------------------------------------------------

def _invalid(*reasons) -> GuardrailAssessment:
    return GuardrailAssessment(decision=INVALID_REQUEST, reasons=_ordered(reasons))


def _assess(request: GuardrailRequest) -> tuple:
    """(assessment, normalized_scopes or None)."""
    if type(request) is not GuardrailRequest:
        return _invalid(REQUEST_NOT_TYPED), None
    invalid = []
    if type(request.schema_version) is not int or request.schema_version != SCHEMA_VERSION:
        invalid.append(SCHEMA_UNSUPPORTED)
    if not (type(request.action) is str and request.action in ACTIONS):
        invalid.append(ACTION_UNKNOWN)
    if invalid:
        return _invalid(*invalid), None
    post = request.action in _POST_ACTIONS
    reasons = []
    if (dc.SCHEMA, dc.SCHEMA_VERSION) != (SUPPORTED_CONTRACT_SCHEMA, SUPPORTED_CONTRACT_SCHEMA_VERSION):
        reasons.append(CONTRACT_VERSION_UNSUPPORTED)
    plan = request.plan
    plan_reasons, scopes = _plan_reasons(plan)
    reasons += plan_reasons
    plan_commits_ok = type(plan) is IsolationPlan and all(
        _commit(v) for v in (plan.base_commit, plan.controller_commit, plan.attempt_base_head))
    controller_key = canonical_path_key(plan.controller_path) if type(plan) is IsolationPlan else None
    target_key = canonical_path_key(plan.target_path) if type(plan) is IsolationPlan else None
    reasons += _process_reasons(request.process, controller_key, target_key)

    pairs = [(request.controller_before, request.target_before)]
    if post:
        pairs.append((request.controller_after, request.target_after))
    elif request.controller_after is not None or request.target_after is not None or \
            request.target_checkpoint_commit is not None:
        reasons.append(SNAPSHOT_MALFORMED)
    snapshots_ok = True
    for controller, target in pairs:
        if not (_snapshot_shape_ok(controller) and _snapshot_shape_ok(target)):
            reasons.append(SNAPSHOT_MALFORMED)
            snapshots_ok = False
            continue
        c_keys, t_keys = _snapshot_keys(controller), _snapshot_keys(target)
        if c_keys is None or t_keys is None:
            reasons.append(PATH_MALFORMED)
            snapshots_ok = False
            continue
        reasons += _controller_reasons(controller, c_keys, plan, plan_commits_ok, controller_key)
        reasons += _target_reasons(target, t_keys, plan, target_key)
        if c_keys[3] != t_keys[3]:
            reasons.append(REPOSITORY_MISMATCH)
        if c_keys[2] == t_keys[2] or c_keys[1] == t_keys[1]:
            reasons.append(SAME_WORKTREE)
        elif _overlap(c_keys[1], t_keys[1]) or _overlap(c_keys[2], t_keys[1]) or _overlap(t_keys[2], c_keys[1]):
            reasons.append(WORKTREE_OVERLAP)

    if snapshots_ok:
        tb = request.target_before
        if plan_commits_ok and tb.head != plan.attempt_base_head:
            reasons.append(TARGET_HEAD_UNEXPECTED)
        lines = _status_lines(tb.porcelain_status)
        if lines is None:
            reasons.append(STATUS_UNAVAILABLE)
        elif lines:
            reasons.append(TARGET_DIRTY_AT_START)
        if post:
            reasons += _post_reasons(request, scopes)

    if request.external_authorization is not None:
        reasons.append(EXTERNAL_AUTHORIZATION_NOT_ACCEPTED)
    if request.action == ACTION_SELF_PROMOTE:
        reasons.append(SELF_PROMOTION_REQUIRES_FCP3_HUMAN_AUTHORIZATION)
    reasons = _ordered(reasons)
    if reasons:
        return GuardrailAssessment(decision=DENIED, reasons=reasons, action=request.action), None
    return GuardrailAssessment(decision=ISOLATION_HOLDS, reasons=(), action=request.action,
                               binding=_binding(request, scopes)), scopes


def _post_reasons(request: GuardrailRequest, scopes) -> list:
    cb, ca, tb, ta = request.controller_before, request.controller_after, request.target_before, request.target_after
    reasons = []
    controller_same = (
        _snapshot_keys(cb) == _snapshot_keys(ca) and cb.link_component_observed == ca.link_component_observed
        and (cb.branch, cb.head, cb.porcelain_status) == (ca.branch, ca.head, ca.porcelain_status)
    )
    if not controller_same:
        reasons.append(CONTROLLER_DRIFT)
    if _snapshot_keys(tb) != _snapshot_keys(ta) or tb.branch != ta.branch \
            or tb.link_component_observed != ta.link_component_observed:
        reasons.append(TARGET_DRIFT)
    checkpoint = request.target_checkpoint_commit
    if checkpoint is not None and (not _commit(checkpoint) or checkpoint == tb.head):
        reasons.append(SNAPSHOT_MALFORMED)
    elif ta.head != tb.head and ta.head != checkpoint:
        reasons.append(TARGET_HEAD_DRIFT)
    lines = _status_lines(ta.porcelain_status)
    if lines is None:
        reasons.append(STATUS_UNAVAILABLE)
    elif scopes is not None:
        reasons += _scope_reasons(lines, scopes)
    elif lines:
        reasons.append(SCOPE_VIOLATION)
    return reasons


def assess_guardrails(request: GuardrailRequest) -> GuardrailAssessment:
    """Pure, deterministic, deny-by-default isolation assessment. Never
    raises on bad input; never runs Git, touches the filesystem, authorizes,
    promotes, merges, commits or records anything."""
    try:
        return _assess(request)[0]
    except Exception:  # noqa: BLE001 - a hostile input must fail closed, never crash the caller
        action = getattr(request, "action", None) if type(request) is GuardrailRequest else None
        if not (type(action) is str and action in ACTIONS):
            return _invalid(ACTION_UNKNOWN)
        return GuardrailAssessment(decision=DENIED, reasons=(SNAPSHOT_MALFORMED,), action=action)


def closure_identity(request: GuardrailRequest) -> dc.DogfoodIdentity:
    """The FCP-12A-01 `DogfoodIdentity` for a post-attempt request. The
    guardrails are re-run here (a caller-made assessment is never trusted),
    and `target_isolated` is True only for a CONFIRM_ISOLATION request whose
    isolation holds; anything else yields False. Commits are copied as
    given; the closure contract validates them itself."""
    assessment = assess_guardrails(request)
    isolated = assessment.isolation_holds and assessment.action == ACTION_CONFIRM_ISOLATION
    plan = request.plan if type(request) is GuardrailRequest and type(request.plan) is IsolationPlan else None
    ca = request.controller_after if type(request) is GuardrailRequest else None
    ta = request.target_after if type(request) is GuardrailRequest else None
    return dc.DogfoodIdentity(
        base_commit=plan.base_commit if plan else None,
        controller_commit=plan.controller_commit if plan else None,
        controller_head_observed=ca.head if type(ca) is WorktreeSnapshot else None,
        target_head_observed=ta.head if type(ta) is WorktreeSnapshot else None,
        target_isolated=isolated,
    )
