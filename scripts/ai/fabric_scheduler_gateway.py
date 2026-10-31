"""FCP-9D-01: Director gateway with explicit Host authorization - thin,
deterministic, fail-closed, provider-neutral.

Answers TWO questions about ONE blueprint the Director already compiled and
persisted (`FabricDirectorService.submit_blueprint` -> `DirectorDagHandle`):

* `preview(handle, context)`: what exactly would be dispatched, bound to
  which manifest digest, and is it reviewable now? Pure: no service, no I/O,
  no clock, no process, no Git, no network. It never dispatches.
* `submit(service, handle, review, confirmation)`: hand that SAME handle to
  `service.run_blueprint` exactly once, and only when the Host explicitly
  confirmed exactly this review and nothing changed since.

Authority boundary
------------------
* `FabricDirectorService.run_blueprint` and the Runner are the ONLY
  execution authorities. `run_blueprint` is the only service method this
  module ever calls, at most once per `submit`, and only after every check
  below passed. There is no pool, lease, queue, ledger, schema store, retry,
  fallback, provider switch, merge, PR, push, shell or credential here.
  `submit_blueprint`, `submit_and_run`, `recover` and `run` are never called.
* The Runner still decides everything at execution time (branch guard,
  dirty tree, write scope, lease, provider preflight, self target, quota);
  `run_blueprint` re-derives the handle from the durable Director binding
  and re-validates the manifest to the same digest. This gateway only
  refuses earlier; it never relaxes anything.
* Nothing is invented. The Host confirmation is an explicit, typed,
  content-bound statement (`host_confirmed=True` plus a token derived from
  the review fingerprint and confirmation instant). It is integrity-binding,
  NOT an authentication secret, NOT Direction approval and NOT human
  approval; results report `direction_approval` / `human_approval` as False
  read-only properties. Base commits are Host OBSERVATIONS (Git is never
  read here); a missing or malformed one is refused, never guessed.

TOCTOU binding
--------------
A review carries the handle's `manifest_sha256` and `plan_fingerprint` plus
one digest per bound group (`GROUPS`): WORKTREE, BASE, PLAN, PROVIDER, MODE,
SCOPE, LIMIT, PERMISSION, DATE, and a `review_fingerprint` over all of them.
`submit` never trusts the review as given: it re-derives it from the handle
it is about to dispatch and refuses any difference with the group's
`*_CHANGED` code. The Host's re-observed base commits must equal the
reviewed ones (BASE_CHANGED), the confirmation instant must be on the same
UTC date as the review (DATE_CHANGED), not before it, within
`max_review_age_seconds`, and inside the manifest's own window. After
dispatch the Director's summary must name the same run, digest, plan
fingerprint and workers, otherwise the outcome is UNKNOWN - never success.

Outcomes (`SubmitResult`): REFUSED (the Director was never called),
DIRECTOR_REFUSED (`run_blueprint` raised a `DirectorError`; only its code is
echoed), UNKNOWN (any other exception or an unbound summary) and DISPATCHED
(the Director's own summary, bound to the review; its `aggregate_status` is
echoed verbatim and is NOT a success certification). No retry ever follows.
Every review/result fixes the FCP-9A-01 zero-authority flags to False.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

try:
    from scripts.ai import fabric_dag_blueprint as bp
    from scripts.ai import fabric_director as fd
    from scripts.ai import fabric_scheduler_contract as sc
    from scripts.ai import fabric_scheduler_window as sw
except ImportError:  # pragma: no cover - direct script execution
    import fabric_dag_blueprint as bp  # type: ignore[no-redef]
    import fabric_director as fd  # type: ignore[no-redef]
    import fabric_scheduler_contract as sc  # type: ignore[no-redef]
    import fabric_scheduler_window as sw  # type: ignore[no-redef]

CONTEXT_SCHEMA_VERSION = 1
REVIEW_SCHEMA = "fcp9d01-scheduler-gateway-review-v1"
RESULT_SCHEMA = "fcp9d01-scheduler-gateway-submit-v1"
SCHEMA_VERSION = 1
GATEWAY_MARKER = "FCP9D01_GATEWAY_DIRECTOR_IS_THE_ONLY_EXECUTION_AUTHORITY_NOT_CERTIFIED"
TOKEN_DOMAIN = "fcp9d01-host-confirmation-v1"

DEFAULT_MAX_REVIEW_AGE_SECONDS = 900
MAX_REVIEW_AGE_SECONDS = 3600
MAX_NODES = bp.MAX_BLUEPRINT_NODES

_COMMIT_RE = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_NATIVE_CODE_RE = re.compile(r"[A-Z][A-Z0-9_]{0,63}")

EXECUTION_TIME_GUARDS_NOT_EVALUATED = bp.EXECUTION_TIME_GUARDS_NOT_EVALUATED + (
    "WRITE_LEASE", "SELF_TARGET", "PROCESS_CONFIRMED_STOPPED", "PROVIDER_QUOTA_ELIGIBILITY",
    "DURABLE_DIRECTOR_BINDING",
)

PERMISSION_READ_ONLY = "READ_ONLY"
PERMISSION_WRITE = "WRITE"
PERMISSION_WRITE_SHELL = "WRITE_SHELL"
PERMISSION_LEVELS = (PERMISSION_READ_ONLY, PERMISSION_WRITE, PERMISSION_WRITE_SHELL)

# Bound groups, in their fixed canonical order, and their change codes.
GROUP_WORKTREE = "WORKTREE"
GROUP_BASE = "BASE"
GROUP_PLAN = "PLAN"
GROUP_PROVIDER = "PROVIDER"
GROUP_MODE = "MODE"
GROUP_SCOPE = "SCOPE"
GROUP_LIMIT = "LIMIT"
GROUP_PERMISSION = "PERMISSION"
GROUP_DATE = "DATE"
GROUPS = (GROUP_WORKTREE, GROUP_BASE, GROUP_PLAN, GROUP_PROVIDER, GROUP_MODE, GROUP_SCOPE, GROUP_LIMIT,
          GROUP_PERMISSION, GROUP_DATE)

REVIEWED = "REVIEWED"
REFUSED = "REFUSED"
REVIEW_OUTCOMES = (REVIEWED, REFUSED)
DIRECTOR_REFUSED = "DIRECTOR_REFUSED"
UNKNOWN = "UNKNOWN"
DISPATCHED = "DISPATCHED"
SUBMIT_OUTCOMES = (REFUSED, DIRECTOR_REFUSED, UNKNOWN, DISPATCHED)

# Preview refusal codes, in their fixed canonical order.
CONTEXT_NOT_TYPED = "CONTEXT_NOT_TYPED"
HANDLE_NOT_TYPED = "HANDLE_NOT_TYPED"
SCHEMA_VERSION_UNSUPPORTED = "SCHEMA_VERSION_UNSUPPORTED"
AS_OF_INVALID = "AS_OF_INVALID"
BASE_MALFORMED = "BASE_MALFORMED"
RUN_ID_INVALID = "RUN_ID_INVALID"
HANDLE_INCONSISTENT = "HANDLE_INCONSISTENT"
PLAN_UNVERIFIED = "PLAN_UNVERIFIED"
MANIFEST_UNREADABLE = "MANIFEST_UNREADABLE"
MANIFEST_MISMATCH = "MANIFEST_MISMATCH"
MANIFEST_KEY_UNSUPPORTED = "MANIFEST_KEY_UNSUPPORTED"
FALLBACK_DECLARED = "FALLBACK_DECLARED"
RESUME_DECLARED = "RESUME_DECLARED"
NODE_ID_UNSUPPORTED = "NODE_ID_UNSUPPORTED"
PROVIDER_ID_UNSUPPORTED = "PROVIDER_ID_UNSUPPORTED"
MODE_UNKNOWN = "MODE_UNKNOWN"
BASE_COVERAGE_MISMATCH = "BASE_COVERAGE_MISMATCH"
WINDOW_INVALID = "WINDOW_INVALID"
WINDOW_NOT_OPEN = "WINDOW_NOT_OPEN"
WINDOW_EXPIRED = "WINDOW_EXPIRED"
REVIEW_REASONS = (
    CONTEXT_NOT_TYPED, HANDLE_NOT_TYPED, SCHEMA_VERSION_UNSUPPORTED, AS_OF_INVALID, BASE_MALFORMED, RUN_ID_INVALID,
    HANDLE_INCONSISTENT, PLAN_UNVERIFIED, MANIFEST_UNREADABLE, MANIFEST_MISMATCH, MANIFEST_KEY_UNSUPPORTED,
    FALLBACK_DECLARED, RESUME_DECLARED, NODE_ID_UNSUPPORTED, PROVIDER_ID_UNSUPPORTED, MODE_UNKNOWN,
    BASE_COVERAGE_MISMATCH, WINDOW_INVALID, WINDOW_NOT_OPEN, WINDOW_EXPIRED,
)

# Submit codes, in their fixed canonical order.
SERVICE_UNSUPPORTED = "SERVICE_UNSUPPORTED"
REVIEW_NOT_TYPED = "REVIEW_NOT_TYPED"
REVIEW_NOT_REVIEWED = "REVIEW_NOT_REVIEWED"
CONFIRMATION_MISSING = "CONFIRMATION_MISSING"
CONFIRMATION_NOT_TYPED = "CONFIRMATION_NOT_TYPED"
HOST_CONFIRMATION_NOT_EXPLICIT = "HOST_CONFIRMATION_NOT_EXPLICIT"
CONFIRMATION_REVIEW_MISMATCH = "CONFIRMATION_REVIEW_MISMATCH"
CONFIRMATION_TOKEN_INVALID = "CONFIRMATION_TOKEN_INVALID"
CONFIRMED_AT_INVALID = "CONFIRMED_AT_INVALID"
MAX_REVIEW_AGE_INVALID = "MAX_REVIEW_AGE_INVALID"
HANDLE_REFUSED = "HANDLE_REFUSED"
WORKTREE_CHANGED = "WORKTREE_CHANGED"
BASE_CHANGED = "BASE_CHANGED"
PLAN_CHANGED = "PLAN_CHANGED"
PROVIDER_CHANGED = "PROVIDER_CHANGED"
MODE_CHANGED = "MODE_CHANGED"
SCOPE_CHANGED = "SCOPE_CHANGED"
LIMIT_CHANGED = "LIMIT_CHANGED"
PERMISSION_CHANGED = "PERMISSION_CHANGED"
DATE_CHANGED = "DATE_CHANGED"
REVIEW_MISMATCH = "REVIEW_MISMATCH"
CONFIRMED_BEFORE_REVIEW = "CONFIRMED_BEFORE_REVIEW"
REVIEW_EXPIRED = "REVIEW_EXPIRED"
DIRECTOR_REFUSAL = "DIRECTOR_REFUSAL"
DISPATCH_RAISED = "DISPATCH_RAISED"
SUMMARY_NOT_TYPED = "SUMMARY_NOT_TYPED"
SUMMARY_MISMATCH = "SUMMARY_MISMATCH"
CHANGE_CODES = {
    GROUP_WORKTREE: WORKTREE_CHANGED, GROUP_BASE: BASE_CHANGED, GROUP_PLAN: PLAN_CHANGED,
    GROUP_PROVIDER: PROVIDER_CHANGED, GROUP_MODE: MODE_CHANGED, GROUP_SCOPE: SCOPE_CHANGED,
    GROUP_LIMIT: LIMIT_CHANGED, GROUP_PERMISSION: PERMISSION_CHANGED, GROUP_DATE: DATE_CHANGED,
}
SUBMIT_REASONS = (
    SERVICE_UNSUPPORTED, HANDLE_NOT_TYPED, REVIEW_NOT_TYPED, REVIEW_NOT_REVIEWED, CONFIRMATION_MISSING,
    CONFIRMATION_NOT_TYPED, HOST_CONFIRMATION_NOT_EXPLICIT, CONFIRMATION_REVIEW_MISMATCH, CONFIRMATION_TOKEN_INVALID,
    CONFIRMED_AT_INVALID, MAX_REVIEW_AGE_INVALID, BASE_MALFORMED, HANDLE_REFUSED,
) + tuple(CHANGE_CODES[g] for g in GROUPS) + (
    REVIEW_MISMATCH, CONFIRMED_BEFORE_REVIEW, REVIEW_EXPIRED, WINDOW_INVALID, WINDOW_NOT_OPEN, WINDOW_EXPIRED,
    DIRECTOR_REFUSAL, DISPATCH_RAISED, SUMMARY_NOT_TYPED, SUMMARY_MISMATCH,
)
_POST_DISPATCH_REASONS = frozenset({DIRECTOR_REFUSAL, DISPATCH_RAISED, SUMMARY_NOT_TYPED, SUMMARY_MISMATCH})

# Manifest keys the Director's blueprint compiler can produce; anything else
# (incl. `metadata` and the `dependencies` alias) is refused.
_PIPELINE_KEYS = frozenset({"pipeline_id", "workers", "max_workers", "provider_limits", "not_before_utc",
                            "deadline_utc"})
_WORKER_KEYS = frozenset({"id", "worktree", "work_order", "provider", "mode", "depends_on"}
                         | set(bp._OPTIONAL_SCALAR_FIELDS) | set(bp._OPTIONAL_TUPLE_FIELDS))
_AGGREGATE_STATUSES = frozenset(fd._PIPELINE_STATUS_VALUES | {fd.DAG_AGGREGATE_UNVERIFIED, fd.DAG_AGGREGATE_UNKNOWN})


def _ordered(codes, vocabulary) -> tuple:
    return sc._ordered(codes, vocabulary)


def _digest(payload) -> str:
    return hashlib.sha256(sc._canonical(payload).encode("ascii")).hexdigest()


def _is_digest(value) -> bool:
    return type(value) is str and sc._FINGERPRINT_RE.fullmatch(value) is not None


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReviewContext:
    """What the Host observed when reviewing: the explicit evaluation instant
    and, per node id, the base commit of that node's worktree. Validated by
    `preview` (fail closed), not here."""
    as_of_utc: str
    base_commits: tuple
    schema_version: int = CONTEXT_SCHEMA_VERSION


@dataclass(frozen=True)
class HostConfirmation:
    """The Host's explicit confirmation of ONE review. `base_commits` are
    re-observed by the Host at confirmation time. Not Direction approval,
    not human approval, not a credential."""
    review_fingerprint: str
    confirmation_token: str
    confirmed_at_utc: str
    base_commits: tuple
    host_confirmed: bool = False


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

class _GatewayGuarantees(sc._NotAuthorized):
    @property
    def direction_approval(self) -> bool:
        return False

    @property
    def human_approval(self) -> bool:
        return False

    @staticmethod
    def _guarantees() -> dict:
        guarantees = sc._NotAuthorized._guarantees()
        guarantees.update(marker=GATEWAY_MARKER, direction_approval=False, human_approval=False)
        return guarantees


def _review_fingerprint(run_id, manifest_sha256, plan_fingerprint, as_of_utc, groups) -> str:
    return _digest({
        "schema": REVIEW_SCHEMA, "run_id": run_id, "manifest_sha256": manifest_sha256,
        "plan_fingerprint": plan_fingerprint, "as_of_utc": as_of_utc, "groups": [list(g) for g in groups],
    })


@dataclass(frozen=True)
class GatewayReview(_GatewayGuarantees):
    """Read-only preview of one Director DAG handle. Echoes only validated
    ids, enumerated codes, normalized instants and digests - no path, Work
    Order text or command. Construction re-checks every invariant, so a
    hand-made review cannot carry a fingerprint its content does not support."""
    outcome: str
    reasons: tuple
    run_id: Optional[str]
    manifest_sha256: Optional[str]
    plan_fingerprint: Optional[str]
    as_of_utc: Optional[str]
    review_date: Optional[str]
    base_commits: tuple
    worker_ids: tuple
    permission_levels: tuple
    groups: tuple
    review_fingerprint: Optional[str]

    def __post_init__(self):
        if type(self.outcome) is not str or self.outcome not in REVIEW_OUTCOMES:
            raise ValueError("unknown review outcome")
        if not (type(self.reasons) is tuple and all(type(r) is str and r in REVIEW_REASONS for r in self.reasons)
                and self.reasons == _ordered(self.reasons, REVIEW_REASONS)):
            raise ValueError("reasons must be ordered review reason codes")
        echo = (self.run_id, self.manifest_sha256, self.plan_fingerprint, self.as_of_utc, self.review_date,
                self.review_fingerprint)
        if self.outcome == REFUSED:
            if not self.reasons or echo != (None,) * len(echo) or self.base_commits or self.worker_ids \
                    or self.permission_levels or self.groups:
                raise ValueError("a refused review carries reasons and echoes nothing")
            return
        if self.reasons:
            raise ValueError("a reviewed handle carries no reasons")
        if not fd._is_director_pipeline_id(self.run_id):
            raise ValueError("run_id must be a Director pipeline id")
        if not (_is_digest(self.manifest_sha256) and _is_digest(self.plan_fingerprint)):
            raise ValueError("manifest_sha256 and plan_fingerprint must be sha256 digests")
        parsed = sw.parse_utc(self.as_of_utc)
        if parsed is None or sc._utc_text(parsed) != self.as_of_utc or parsed.date().isoformat() != self.review_date:
            raise ValueError("as_of_utc / review_date must be a normalized UTC instant and its date")
        ids = self.worker_ids
        if not (type(ids) is tuple and 1 <= len(ids) <= MAX_NODES and all(sc._safe_id(i) for i in ids)
                and len(set(ids)) == len(ids)):
            raise ValueError("worker_ids must be unique safe ids")
        if _base_reasons(self.base_commits) or tuple(sorted(p[0] for p in self.base_commits)) != tuple(sorted(ids)) \
                or list(self.base_commits) != sorted(self.base_commits):
            raise ValueError("base_commits must be sorted and cover every worker exactly once")
        if not (type(self.permission_levels) is tuple
                and tuple(p[0] for p in self.permission_levels if type(p) is tuple and len(p) == 2) == ids
                and all(p[1] in PERMISSION_LEVELS for p in self.permission_levels)):
            raise ValueError("permission_levels must name every worker in order")
        if not (type(self.groups) is tuple and tuple(g[0] for g in self.groups if type(g) is tuple) == GROUPS
                and all(len(g) == 2 and _is_digest(g[1]) for g in self.groups)):
            raise ValueError("groups must be one digest per bound group, in order")
        if self.review_fingerprint != _review_fingerprint(self.run_id, self.manifest_sha256, self.plan_fingerprint,
                                                          self.as_of_utc, self.groups):
            raise ValueError("review_fingerprint must be derived from the review's content")

    @property
    def reviewed(self) -> bool:
        """Informational only: the handle may be confirmed. Not a permit."""
        return self.outcome == REVIEWED

    def group_digest(self, group: str) -> Optional[str]:
        return dict(self.groups).get(group)

    def to_dict(self) -> dict:
        return {
            "schema": REVIEW_SCHEMA, "schema_version": SCHEMA_VERSION, "outcome": self.outcome,
            "reasons": list(self.reasons), "run_id": self.run_id, "manifest_sha256": self.manifest_sha256,
            "plan_fingerprint": self.plan_fingerprint, "as_of_utc": self.as_of_utc, "review_date": self.review_date,
            "base_commits": [list(p) for p in self.base_commits], "worker_ids": list(self.worker_ids),
            "permission_levels": [list(p) for p in self.permission_levels],
            "groups": [list(g) for g in self.groups], "review_fingerprint": self.review_fingerprint,
            "execution_time_guards_not_evaluated": list(EXECUTION_TIME_GUARDS_NOT_EVALUATED),
            **_GatewayGuarantees._guarantees(),
        }


@dataclass(frozen=True)
class SubmitResult(_GatewayGuarantees):
    """What one `submit` did. `summary` is the Director's own object (kept for
    the caller, never serialized: it may hold evidence paths). Construction
    re-checks that the outcome, reasons and dispatch flag agree."""
    outcome: str
    reasons: tuple
    run_id: Optional[str]
    review_fingerprint: Optional[str]
    dispatch_attempted: bool
    director_error_code: Optional[str] = None
    runner_aggregate_status: Optional[str] = None
    review_reasons: tuple = ()
    summary: Optional[fd.DirectorDagRunSummary] = None

    def __post_init__(self):
        if type(self.outcome) is not str or self.outcome not in SUBMIT_OUTCOMES:
            raise ValueError("unknown submit outcome")
        if not (type(self.reasons) is tuple and all(type(r) is str and r in SUBMIT_REASONS for r in self.reasons)
                and self.reasons == _ordered(self.reasons, SUBMIT_REASONS)):
            raise ValueError("reasons must be ordered submit reason codes")
        if not (type(self.review_reasons) is tuple and all(r in REVIEW_REASONS for r in self.review_reasons)):
            raise ValueError("review_reasons must be review reason codes")
        if self.review_reasons and HANDLE_REFUSED not in self.reasons:
            raise ValueError("review_reasons accompany HANDLE_REFUSED only")
        if type(self.dispatch_attempted) is not bool or self.dispatch_attempted != (self.outcome != REFUSED):
            raise ValueError("the Director is called exactly when the gateway did not refuse")
        post = set(self.reasons) & _POST_DISPATCH_REASONS
        if self.outcome == REFUSED:
            if not self.reasons or post:
                raise ValueError("a refusal carries pre-dispatch reasons only")
        elif set(self.reasons) != post:
            raise ValueError("a dispatched submit carries post-dispatch reasons only")
        if (self.outcome == DIRECTOR_REFUSED) != (self.director_error_code is not None) or (
                self.director_error_code is not None and not _NATIVE_CODE_RE.fullmatch(self.director_error_code)):
            raise ValueError("a native Director code accompanies DIRECTOR_REFUSED only")
        if self.outcome == DIRECTOR_REFUSED and self.reasons != (DIRECTOR_REFUSAL,):
            raise ValueError("DIRECTOR_REFUSED carries DIRECTOR_REFUSAL only")
        if self.outcome == DISPATCHED:
            if self.reasons or type(self.summary) is not fd.DirectorDagRunSummary \
                    or self.runner_aggregate_status not in _AGGREGATE_STATUSES:
                raise ValueError("DISPATCHED carries the Director's bound summary")
        elif self.outcome == UNKNOWN:
            if not post or self.runner_aggregate_status is not None:
                raise ValueError("UNKNOWN carries a post-dispatch reason and no status")
        elif self.summary is not None or self.runner_aggregate_status is not None:
            raise ValueError("only a dispatched submit carries a summary")

    @property
    def dispatched(self) -> bool:
        """Informational only: the Director returned a summary bound to the
        review. Never a success certification."""
        return self.outcome == DISPATCHED

    def to_dict(self) -> dict:
        return {
            "schema": RESULT_SCHEMA, "schema_version": SCHEMA_VERSION, "outcome": self.outcome,
            "reasons": list(self.reasons), "review_reasons": list(self.review_reasons), "run_id": self.run_id,
            "review_fingerprint": self.review_fingerprint, "dispatch_attempted": self.dispatch_attempted,
            "director_error_code": self.director_error_code, "runner_aggregate_status": self.runner_aggregate_status,
            **_GatewayGuarantees._guarantees(),
        }


def canonical_json(value) -> str:
    """Stable, sorted, compact serialization of the exact gateway types."""
    if type(value) is GatewayReview:
        return sc._canonical(GatewayReview.to_dict(value))
    if type(value) is SubmitResult:
        return sc._canonical(SubmitResult.to_dict(value))
    raise TypeError("canonical_json accepts only a GatewayReview or a SubmitResult")


def confirmation_token_for(review: GatewayReview, confirmed_at_utc: str) -> str:
    """The token a Host states to confirm exactly `review` at exactly
    `confirmed_at_utc`. Content-binding only; it is not a secret and carries
    no approval of anyone."""
    if type(review) is not GatewayReview or not review.reviewed:
        raise ValueError("only a REVIEWED GatewayReview can be confirmed")
    parsed = sw.parse_utc(confirmed_at_utc)
    if parsed is None:
        raise ValueError("confirmed_at_utc must be a strict timezone-aware instant")
    text = "\n".join((TOKEN_DOMAIN, review.review_fingerprint, sc._utc_text(parsed)))
    return hashlib.sha256(text.encode("ascii")).hexdigest()


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------

def _base_reasons(pairs) -> set:
    if not (type(pairs) is tuple and 1 <= len(pairs) <= MAX_NODES and all(
            type(p) is tuple and len(p) == 2 and sc._safe_id(p[0]) and type(p[1]) is str
            and _COMMIT_RE.fullmatch(p[1]) for p in pairs) and len({p[0] for p in pairs}) == len(pairs)):
        return {BASE_MALFORMED}
    return set()


def _refused_review(reasons) -> GatewayReview:
    return GatewayReview(
        outcome=REFUSED, reasons=_ordered(reasons, REVIEW_REASONS), run_id=None, manifest_sha256=None,
        plan_fingerprint=None, as_of_utc=None, review_date=None, base_commits=(), worker_ids=(),
        permission_levels=(), groups=(), review_fingerprint=None,
    )


def _handle_reasons(handle) -> set:
    """Self-consistency of the handle and its verified plan (no I/O)."""
    if not fd._is_director_pipeline_id(handle.pipeline_id):
        return {RUN_ID_INVALID}
    plan = handle.plan
    try:
        verified = bp.verify_plan(plan)
    except Exception:  # noqa: BLE001 - an unevaluable plan is unverified: fail closed
        verified = False
    if not verified:
        return {PLAN_UNVERIFIED}
    if not (type(plan.nodes) is tuple and all(type(n) is bp.PlanNode for n in plan.nodes)):
        return {HANDLE_INCONSISTENT}
    if not (handle.director_run_id == handle.pipeline_id == plan.pipeline_id
            and handle.manifest_sha256 == plan.manifest_sha256 and handle.plan_fingerprint == plan.fingerprint
            and type(handle.worker_ids) is tuple and handle.worker_ids == tuple(n.id for n in plan.nodes)
            and 1 <= len(plan.nodes) <= MAX_NODES):
        return {HANDLE_INCONSISTENT}
    return set()


def _manifest_of(plan) -> tuple:
    """(reasons, manifest dict). The manifest is the plan's own canonical
    JSON, re-checked against the plan's digest and nodes."""
    text = plan.manifest_json
    try:
        data = json.loads(text) if type(text) is str else None
    except ValueError:
        data = None
    if type(data) is not dict or type(data.get("workers")) is not list \
            or any(type(w) is not dict for w in data["workers"]):
        return {MANIFEST_UNREADABLE}, None
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != plan.manifest_sha256 \
            or data.get("pipeline_id") != plan.pipeline_id \
            or tuple(w.get("id") for w in data["workers"]) != tuple(n.id for n in plan.nodes) \
            or any(w.get("provider") != n.provider or w.get("mode") != n.mode
                   or w.get("depends_on") != list(n.depends_on) for w, n in zip(data["workers"], plan.nodes)):
        return {MANIFEST_MISMATCH}, None
    reasons = set()
    for worker in data["workers"]:
        if worker.get("fallback_providers"):
            reasons.add(FALLBACK_DECLARED)
        if worker.get("resume_from") is not None:
            reasons.add(RESUME_DECLARED)
        if set(worker) - _WORKER_KEYS - {"fallback_providers", "resume_from"}:
            reasons.add(MANIFEST_KEY_UNSUPPORTED)
    if set(data) - _PIPELINE_KEYS:
        reasons.add(MANIFEST_KEY_UNSUPPORTED)
    return reasons, data


def permission_level_for(node) -> str:
    if node.mode != sc.MODE_WRITE:
        return PERMISSION_READ_ONLY
    return PERMISSION_WRITE_SHELL if node.allow_shell is True else PERMISSION_WRITE


def _groups(plan, data: dict, base: tuple, as_of_text: str, review_date: str) -> tuple:
    workers = list(zip(plan.nodes, data["workers"]))
    limits = data.get("provider_limits")
    material = {
        GROUP_WORKTREE: [[n.id, n.worktree_top, w.get("worktree")] for n, w in workers],
        GROUP_BASE: [list(p) for p in base],
        GROUP_PLAN: {
            "run_id": plan.pipeline_id, "manifest_sha256": plan.manifest_sha256,
            "plan_fingerprint": plan.fingerprint,
            "nodes": [[n.id, list(n.depends_on), n.dependency_policy, n.priority, n.work_order] for n, _ in workers],
        },
        GROUP_PROVIDER: [[n.id, n.provider, w.get("model")] for n, w in workers],
        GROUP_MODE: [[n.id, n.mode] for n, _ in workers],
        GROUP_SCOPE: [[n.id, w.get("authorize_path"), w.get("required_capabilities")] for n, w in workers],
        GROUP_LIMIT: {
            "max_workers": data.get("max_workers"),
            "provider_limits": sorted([k, v] for k, v in limits.items()) if type(limits) is dict else limits,
            "nodes": [[n.id, w.get("max_attempts"), w.get("timeout_seconds"), w.get("backoff_seconds")]
                      for n, w in workers],
        },
        GROUP_PERMISSION: [
            [n.id, permission_level_for(n), n.allow_shell, w.get("checkpoint_policy"), w.get("completion_policy"),
             w.get("acceptance_commands")]
            for n, w in workers
        ],
        GROUP_DATE: {
            "as_of_utc": as_of_text, "review_date": review_date,
            "not_before_utc": data.get("not_before_utc"), "deadline_utc": data.get("deadline_utc"),
        },
    }
    return tuple((group, _digest(material[group])) for group in GROUPS)


_WINDOW_REASON = {sw.INVALID: WINDOW_INVALID, sw.WAIT_UNTIL: WINDOW_NOT_OPEN, sw.EXPIRED: WINDOW_EXPIRED}


def preview(handle, context) -> GatewayReview:
    """Pure, deterministic review of one Director DAG handle. Takes no
    service: it cannot dispatch, persist or read anything. Never raises on
    bad input and never mutates it; every refusal is explained."""
    reasons = set()
    if type(context) is not ReviewContext:
        reasons.add(CONTEXT_NOT_TYPED)
    if type(handle) is not fd.DirectorDagHandle:
        reasons.add(HANDLE_NOT_TYPED)
    if reasons:
        return _refused_review(reasons)
    if not (sc._is_int(context.schema_version) and context.schema_version == CONTEXT_SCHEMA_VERSION):
        reasons.add(SCHEMA_VERSION_UNSUPPORTED)
    as_of = sw.parse_utc(context.as_of_utc)
    if as_of is None:
        reasons.add(AS_OF_INVALID)
    reasons |= _base_reasons(context.base_commits)
    reasons |= _handle_reasons(handle)
    if reasons:
        return _refused_review(reasons)

    plan = handle.plan
    manifest_reasons, data = _manifest_of(plan)
    reasons |= manifest_reasons
    if data is None:
        return _refused_review(reasons)
    if not all(sc._safe_id(n.id) for n in plan.nodes):
        reasons.add(NODE_ID_UNSUPPORTED)
    if not all(sc._valid_provider_id(n.provider) for n in plan.nodes):
        reasons.add(PROVIDER_ID_UNSUPPORTED)
    if not all(type(n.mode) is str and n.mode in sc.MODES for n in plan.nodes):
        reasons.add(MODE_UNKNOWN)
    if sorted(p[0] for p in context.base_commits) != sorted(n.id for n in plan.nodes):
        reasons.add(BASE_COVERAGE_MISMATCH)
    window = sw.evaluate_window(data, as_of=as_of)
    if window.status in _WINDOW_REASON:
        reasons.add(_WINDOW_REASON[window.status])
    if reasons:
        return _refused_review(reasons)

    as_of_text = sc._utc_text(as_of)
    review_date = as_of.date().isoformat()
    base = tuple(sorted(context.base_commits))
    groups = _groups(plan, data, base, as_of_text, review_date)
    return GatewayReview(
        outcome=REVIEWED, reasons=(), run_id=plan.pipeline_id, manifest_sha256=plan.manifest_sha256,
        plan_fingerprint=plan.fingerprint, as_of_utc=as_of_text, review_date=review_date, base_commits=base,
        worker_ids=tuple(n.id for n in plan.nodes),
        permission_levels=tuple((n.id, permission_level_for(n)) for n in plan.nodes), groups=groups,
        review_fingerprint=_review_fingerprint(plan.pipeline_id, plan.manifest_sha256, plan.fingerprint,
                                               as_of_text, groups),
    )


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------

def _refused_submit(reasons, review=None, review_reasons: tuple = ()) -> SubmitResult:
    reviewed = type(review) is GatewayReview and review.reviewed
    return SubmitResult(
        outcome=REFUSED, reasons=_ordered(reasons, SUBMIT_REASONS), run_id=review.run_id if reviewed else None,
        review_fingerprint=review.review_fingerprint if reviewed else None, dispatch_attempted=False,
        review_reasons=review_reasons,
    )


def _confirmation_reasons(review: GatewayReview, confirmation) -> set:
    if confirmation is None:
        return {CONFIRMATION_MISSING}
    if type(confirmation) is not HostConfirmation:
        return {CONFIRMATION_NOT_TYPED}
    reasons = set()
    if confirmation.host_confirmed is not True:
        reasons.add(HOST_CONFIRMATION_NOT_EXPLICIT)
    if confirmation.review_fingerprint != review.review_fingerprint:
        reasons.add(CONFIRMATION_REVIEW_MISMATCH)
    if sw.parse_utc(confirmation.confirmed_at_utc) is None:
        reasons.add(CONFIRMED_AT_INVALID)
    elif not (_is_digest(confirmation.confirmation_token)
              and confirmation.confirmation_token == confirmation_token_for(review, confirmation.confirmed_at_utc)):
        reasons.add(CONFIRMATION_TOKEN_INVALID)
    reasons |= _base_reasons(confirmation.base_commits)
    return reasons


def _date_reasons(review: GatewayReview, confirmed_at, max_age: int, manifest: dict) -> set:
    reviewed_at = sw.parse_utc(review.as_of_utc)
    reasons = set()
    if confirmed_at < reviewed_at:
        reasons.add(CONFIRMED_BEFORE_REVIEW)
    elif confirmed_at - reviewed_at > timedelta(seconds=max_age):
        reasons.add(REVIEW_EXPIRED)
    if confirmed_at.date() != reviewed_at.date():
        reasons.add(DATE_CHANGED)
    window = sw.evaluate_window(manifest, as_of=confirmed_at)
    if window.status in _WINDOW_REASON:
        reasons.add(_WINDOW_REASON[window.status])
    return reasons


def _summary_bound(summary, review: GatewayReview) -> bool:
    return (summary.run_id == summary.pipeline_id == review.run_id
            and summary.manifest_sha256 == review.manifest_sha256
            and summary.plan_fingerprint == review.plan_fingerprint
            and type(summary.workers) is tuple
            and tuple(getattr(w, "worker_id", None) for w in summary.workers) == review.worker_ids)


def submit(service, handle, review, confirmation, *,
           max_review_age_seconds: int = DEFAULT_MAX_REVIEW_AGE_SECONDS) -> SubmitResult:
    """Dispatches `handle` through `service.run_blueprint` exactly once, and
    only when `confirmation` is the Host's explicit confirmation of `review`
    and the handle still re-derives to exactly that review. Any refusal
    happens before the Director is called. Never retries."""
    reasons = set()
    if not callable(getattr(type(service), "run_blueprint", None)):
        reasons.add(SERVICE_UNSUPPORTED)
    if type(handle) is not fd.DirectorDagHandle:
        reasons.add(HANDLE_NOT_TYPED)
    if type(review) is not GatewayReview:
        reasons.add(REVIEW_NOT_TYPED)
    elif not review.reviewed:
        reasons.add(REVIEW_NOT_REVIEWED)
    if not (sc._is_int(max_review_age_seconds) and 1 <= max_review_age_seconds <= MAX_REVIEW_AGE_SECONDS):
        reasons.add(MAX_REVIEW_AGE_INVALID)
    if reasons:
        return _refused_submit(reasons, review)
    reasons |= _confirmation_reasons(review, confirmation)
    if reasons:
        return _refused_submit(reasons, review)

    # Never trust the review as given: re-derive it from the handle about to
    # be dispatched, under the context it was reviewed with.
    fresh = preview(handle, ReviewContext(as_of_utc=review.as_of_utc, base_commits=review.base_commits))
    if not fresh.reviewed:
        return _refused_submit({HANDLE_REFUSED}, review, fresh.reasons)
    for group in GROUPS:
        if fresh.group_digest(group) != review.group_digest(group):
            reasons.add(CHANGE_CODES[group])
    if not reasons and canonical_json(fresh) != canonical_json(review):
        reasons.add(REVIEW_MISMATCH)
    if tuple(sorted(confirmation.base_commits)) != review.base_commits:
        reasons.add(BASE_CHANGED)
    _, manifest = _manifest_of(handle.plan)
    reasons |= _date_reasons(review, sw.parse_utc(confirmation.confirmed_at_utc), max_review_age_seconds, manifest)
    if reasons:
        return _refused_submit(reasons, review)

    def dispatched(outcome, codes=(), **fields) -> SubmitResult:
        return SubmitResult(
            outcome=outcome, reasons=_ordered(codes, SUBMIT_REASONS), run_id=review.run_id,
            review_fingerprint=review.review_fingerprint, dispatch_attempted=True, **fields,
        )

    # The ONE mutating call. Whatever happens next, nothing is retried.
    try:
        summary = service.run_blueprint(handle)
    except fd.DirectorError as exc:
        code = exc.code if type(exc.code) is str and _NATIVE_CODE_RE.fullmatch(exc.code) else "UNRECOGNIZED"
        return dispatched(DIRECTOR_REFUSED, (DIRECTOR_REFUSAL,), director_error_code=code)
    except Exception:  # noqa: BLE001 - an unexplained dispatch failure is UNKNOWN: fail closed
        return dispatched(UNKNOWN, (DISPATCH_RAISED,))
    if type(summary) is not fd.DirectorDagRunSummary:
        return dispatched(UNKNOWN, (SUMMARY_NOT_TYPED,))
    if not _summary_bound(summary, review):
        return dispatched(UNKNOWN, (SUMMARY_MISMATCH,))
    status = summary.aggregate_status
    if type(status) is not str or status not in _AGGREGATE_STATUSES:
        status = fd.DAG_AGGREGATE_UNKNOWN
    return dispatched(DISPATCHED, runner_aggregate_status=status, summary=summary)
