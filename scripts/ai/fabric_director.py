"""FDB-1: local application-facing Director facade over the existing
Fabric / Runner infrastructure.

Architecture (why this is a facade, not a second engine)
----------------------------------------------------------
`FabricDirectorService` lets a Python caller submit a single governed Work
Order and run it to a compact result WITHOUT constructing manifest JSON by
hand, invoking `runner_pipeline.py` through a subprocess, or re-implementing
any Runner safety/governance decision. Every actual decision (provider
resolution, preflight, quota/auth handling, retry, checkpoint, evidence
persistence, worktree leasing) stays inside `runner_pipeline.PipelineRunner`
and `claude_runner.execute_work_order`; this module only:

* validates Director-level input and generates the execution-plan details
  (`pipeline_id`, `worker_id`, manifest) the caller must never choose itself;
* persists the caller's Work Order text and the generated manifest under a
  Director-owned durable directory, for audit, separate from both the
  target worktree and the Runner's own `state_root`;
* calls `runner_pipeline.parse_manifest` / `load_manifest` for validation and
  `runner_pipeline.PipelineRunner` for execution - never a parallel
  validator or a parallel execution engine;
* projects the Runner's own durable, machine-readable artifacts
  (`pipeline_result.json`, `workers/<id>/result.json`, `metadata.json`) into
  a small, stable `DirectorRunSummary` - never by parsing provider terminal
  output or prose.

FDB-1 is intentionally single-worker: one Director submission == one Work
Order == one Runner pipeline with exactly one worker. Multi-Work-Order
orchestration, merge/push/integrate and a generic shell/exec API are out of
scope here by design (see the FDB-1 work order).

FDB-2-1 adds `evidence(run_id) -> DirectorRunEvidence`: a wider, still
read-only projection of the SAME durable Runner artifacts `result()` already
reads (`pipeline_result.json`, `workers/<id>/result.json`,
`workers/<id>/preflight.json`, and the attempt's own `<evidence_dir>/
result.json` / `metadata.json` / `work_product.json`). It is not a second
evidence store: nothing is written, recomputed or reinterpreted here. Safety
verdicts, resume decisions and provider-availability classifications are
projected exactly as Runner recorded them; the Director does not rerun
`evaluate_write_mode_safety`, does not evaluate resume eligibility, and never
parses provider prose (`stdout.txt`/`stderr.txt`) to decide anything. A field
with no corresponding durable structured evidence is `None`/`()`, never
invented.

FDB-2-2 adds `decision(run_id) -> DirectorRunDecision`: a deterministic,
read-only mechanical classification of the SAME `result()`/`evidence()`
projections into one of a fixed set of operational decision codes (fail-
closed precedence: safety, then evidence health, then provider auth, then
provider quota, then transient pipeline state, then interrupted/terminal
worker states). It consumes no artifact `result()`/`evidence()` do not
already read, recomputes no Runner safety/resume/availability verdict,
parses no provider prose, and persists nothing - it is a pure function of
already-persisted structured state.

FDB-3-1 adds `recover(spec) -> DirectorRunHandle`: the governed recovery/
resume gateway. A HOST that has looked at a prior run's `decision()` and
explicitly chosen to ask for a resume supplies a `DirectorRecoverySpec`
(with `action="RESUME_WORK_PRODUCT"` as proof of that explicit choice);
`recover()` reads ONLY the prior run's existing `evidence()`/`decision()`
projections (never stdout/stderr/provider prose) to check eligibility and to
source the prior attempt's structured `worktree`/`authorized_scopes`, then
PREPARES/SUBMITS (via the SAME `_submit` helper `submit()` uses) a BRAND NEW
pipeline - a new `pipeline_id`, a new Director run directory, a host-supplied
recovery Work Order - whose single worker's manifest entry carries an
explicit `resume_from` pointing at the prior attempt's own
`work_product_path`. `recover()` never executes anything: exactly like
`submit()`, the caller still calls `run(handle)` to drive the SAME
`PipelineRunner` -> `claude_runner.execute_work_order` path, where
`claude_runner.evaluate_resume` remains the sole, unchanged resume
authority. The original pipeline's files/directories are never touched -
recovery is strictly additive.
"""

from __future__ import annotations

import json
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    from scripts.ai import claude_runner
    from scripts.ai import runner_pipeline as pipeline
    from scripts.ai import runner_providers as providers
except ImportError:  # pragma: no cover - direct script execution
    _this_dir = Path(__file__).resolve().parent
    if str(_this_dir) not in sys.path:
        sys.path.insert(0, str(_this_dir))
    import claude_runner  # type: ignore[no-redef]
    import runner_pipeline as pipeline  # type: ignore[no-redef]
    import runner_providers as providers  # type: ignore[no-redef]


class DirectorError(Exception):
    """Director-level refusal; nothing was executed."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------

@dataclass
class DirectorWorkOrderSpec:
    """Caller-provided WHAT/WHY/SCOPE/ACCEPTANCE/GOVERNANCE. The Director
    never rewrites `work_order_text`; it only generates the execution-plan
    details (pipeline_id/worker_id/manifest) around it."""

    worktree: str
    work_order_text: str
    mode: str = providers.MODE_READ_ONLY
    provider: str = providers.DEFAULT_PROVIDER_ID
    model: Optional[str] = None
    authorize_paths: list = field(default_factory=list)
    required_capabilities: list = field(default_factory=list)
    allow_shell: bool = False
    checkpoint_policy: Optional[str] = None
    timeout_seconds: Optional[int] = None
    metadata: dict = field(default_factory=dict)
    # FABRIC runner-owned-acceptance V1: OPTIONAL opt-in into Runner-owned
    # completion certification (see `runner_pipeline.WorkerSpec.
    # completion_policy`/`acceptance_commands`). "provider_verdict" (default,
    # every pre-existing caller) preserves exact prior behavior.
    completion_policy: str = claude_runner.COMPLETION_POLICY_PROVIDER_VERDICT
    acceptance_commands: list = field(default_factory=list)


@dataclass
class DirectorRecoverySpec:
    """Caller-provided, explicit host recovery decision (FDB-3-1). The
    Director never infers a recovery intent from a prior run's state on its
    own - `action` has NO default, so a caller must explicitly confirm
    `action="RESUME_WORK_PRODUCT"` (anything else is refused). `metadata`
    MUST NOT set any of the four reserved `recovered_from_*` lineage keys -
    `recover()` adds those itself from structured prior-run evidence."""

    prior_run_id: str
    recovery_work_order_text: str
    action: str

    prior_worker_id: Optional[str] = None
    provider_override: Optional[str] = None
    model: Optional[str] = None

    authorize_paths: Optional[list] = None
    required_capabilities: list = field(default_factory=list)

    allow_shell: bool = False
    checkpoint_policy: Optional[str] = None
    timeout_seconds: Optional[int] = None

    metadata: dict = field(default_factory=dict)


@dataclass
class DirectorRunHandle:
    """Everything `run`/`validate` need to act on a submitted request. The
    caller never had to choose `pipeline_id`/`worker_id`/manifest/result
    paths - the Director owns them."""

    director_run_id: str
    pipeline_id: str
    worker_id: str
    worktree: str
    director_dir: str
    work_order_path: str
    manifest_path: str
    state_root: str
    validated: bool
    validation_errors: list = field(default_factory=list)


@dataclass
class DirectorRunSummary:
    """Compact, stable operational contract over Runner's durable artifacts.
    A field that cannot be resolved from durable evidence is None/empty,
    never invented."""

    run_id: str
    pipeline_id: str
    status: Optional[str] = None
    stop_reason: Optional[str] = None

    worker_id: Optional[str] = None
    provider: Optional[str] = None
    requested_provider: Optional[str] = None
    worker_state: Optional[str] = None
    state_reason: Optional[str] = None

    work_status: Optional[str] = None
    runner_state: Optional[str] = None

    attempts: Optional[int] = None
    work_attempts_used: Optional[int] = None
    availability_attempts: Optional[int] = None

    provider_condition: Optional[str] = None
    next_eligible_utc: Optional[str] = None

    checkpoint_commit: Optional[str] = None

    evidence_dir: Optional[str] = None
    evidence_complete: Optional[bool] = None
    evidence_error: Optional[str] = None

    changed_paths: tuple = ()
    authorized_changed_paths: tuple = ()
    unauthorized_changed_paths: tuple = ()

    work_product_present: Optional[bool] = None

    decision_required: Optional[bool] = None
    decision_type: Optional[str] = None

    # FABRIC runner-owned-acceptance V1 (Problem 1): an explicit, additive
    # classification of an already-SUCCESS worker - CHECKPOINT (material
    # authorized changes + an ON_SUCCESS checkpoint exists) or SUCCESS_NOOP
    # (no changed paths, no work product, nothing to persist). A pure,
    # mechanical function of the fields already projected above; None for
    # every non-SUCCESS worker_state (never guessed) - see
    # `_classify_completion_mode`.
    completion_mode: Optional[str] = None


@dataclass
class DirectorRunEvidence:
    """Wider, read-only evidence projection over the SAME durable Runner
    artifacts `DirectorRunSummary` already reads, for callers that need more
    than the compact operational summary (safety/resume/work-product/process
    detail). Every field is projected from an existing Runner artifact -
    never recomputed, reinterpreted or parsed from provider prose. A field
    unavailable from durable structured evidence is None/()/{}; it is never
    invented."""

    run_id: str
    pipeline_id: Optional[str] = None
    worker_id: Optional[str] = None
    provider: Optional[str] = None
    requested_provider: Optional[str] = None
    worker_state: Optional[str] = None
    state_reason: Optional[str] = None
    work_status: Optional[str] = None
    runner_state: Optional[str] = None
    execution_mode: Optional[str] = None
    attempts: Optional[int] = None
    work_attempts_used: Optional[int] = None
    availability_attempts: Optional[int] = None

    # Safety: projected from the attempt's OWN result.json; the Director
    # never calls `evaluate_write_mode_safety` or any equivalent logic.
    safety_verdict: Optional[str] = None
    safety_reasons: tuple = ()
    changed_paths: tuple = ()
    authorized_changed_paths: tuple = ()
    unauthorized_changed_paths: tuple = ()
    branch_guard: Optional[dict] = None
    write_scope: Optional[dict] = None
    dirty_tree_policy: Optional[dict] = None

    # Evidence health: whether the attempt's OWN secondary artifacts were
    # fully written. Never reclassified as work failure.
    evidence_dir: Optional[str] = None
    evidence_complete: Optional[bool] = None
    evidence_errors: tuple = ()

    # Provider availability: structured classification only, never parsed
    # from provider prose.
    provider_condition: Optional[str] = None
    next_eligible_utc: Optional[str] = None
    preflight: Optional[dict] = None

    # Runner's own structured provider-output normalization - never raw
    # stdout/stderr prose.
    normalized_result: Optional[dict] = None

    # Work product / resume evidence. Reported only - the Director never
    # decides resume is permitted; that authority stays with Runner.
    work_product_present: Optional[bool] = None
    work_product_path: Optional[str] = None
    work_product: Optional[dict] = None
    resume: Optional[dict] = None

    process_supervision: Optional[dict] = None

    checkpoint_policy: Optional[str] = None
    checkpoint_commit: Optional[str] = None

    # FABRIC runner-owned-acceptance V1 (Problem 2): the last attempt's own
    # Runner-owned acceptance-command execution record (see
    # `runner_pipeline.PipelineRunner._apply_acceptance`) - command, exit
    # code, stdout/stderr per command, and the overall PASSED/FAILED
    # decision. Projected verbatim from the SAME worker result.json
    # `work_status`/`runner_state` above already read; None when
    # `completion_policy` was never `runner_acceptance` or no attempt ran yet.
    acceptance: Optional[dict] = None


@dataclass
class DirectorRunDecision:
    """Deterministic, read-only operational decision projection over
    `result()`/`evidence()`. Every field is a mechanical classification of
    already-persisted structured state - never a recomputation of Runner
    safety/resume/availability, never a parse of provider prose. See the
    FDB-2-2 work order for the fixed precedence (fail-closed) and the fixed
    set of V1 decision codes."""

    run_id: str
    pipeline_id: Optional[str] = None
    worker_id: Optional[str] = None

    decision_code: str = "REVIEW_REQUIRED"
    terminal: bool = True
    human_action_required: bool = True
    next_action: str = "REVIEW_STRUCTURED_STATE"
    reason_codes: tuple = ()

    worker_state: Optional[str] = None
    provider_condition: Optional[str] = None
    next_eligible_utc: Optional[str] = None

    safety_verdict: Optional[str] = None
    evidence_complete: Optional[bool] = None
    work_product_present: Optional[bool] = None

    checkpoint_policy: Optional[str] = None
    checkpoint_commit: Optional[str] = None


# Transient pipeline worker states that merely mean "Runner is still working
# this" - never a human decision point, never a retry/resume re-decision.
_TRANSIENT_WORKER_STATES = frozenset({
    pipeline.WorkerState.QUEUED.value,
    pipeline.WorkerState.WAITING_DEPENDENCY.value,
    pipeline.WorkerState.READY.value,
    pipeline.WorkerState.RUNNING.value,
    pipeline.WorkerState.RETRY_WAIT.value,
})


def _classify_decision(
    summary: "DirectorRunSummary", evidence: "DirectorRunEvidence",
) -> DirectorRunDecision:
    """Pure, fail-closed classification of already-projected structured
    fields. See FDB-2-2 PRECEDENCE for the authoritative ordering; this
    function must not read any artifact `result()`/`evidence()` did not
    already read, and must not interpret provider prose."""

    worker_state = summary.worker_state
    unauthorized = evidence.unauthorized_changed_paths or summary.unauthorized_changed_paths
    safety_verdict = evidence.safety_verdict
    provider_condition = summary.provider_condition or evidence.provider_condition

    base = dict(
        run_id=summary.run_id,
        pipeline_id=summary.pipeline_id,
        worker_id=summary.worker_id,
        worker_state=worker_state,
        provider_condition=provider_condition,
        next_eligible_utc=summary.next_eligible_utc or evidence.next_eligible_utc,
        safety_verdict=safety_verdict,
        evidence_complete=summary.evidence_complete,
        work_product_present=summary.work_product_present,
        checkpoint_policy=evidence.checkpoint_policy,
        checkpoint_commit=evidence.checkpoint_commit,
    )

    # 1. SAFETY - fail-closed, highest precedence; never recomputed.
    if unauthorized or (safety_verdict is not None and safety_verdict != "SAFE"):
        reasons = []
        if unauthorized:
            reasons.append("UNAUTHORIZED_PATHS")
        if safety_verdict is not None and safety_verdict != "SAFE":
            reasons.append("SAFETY_VERDICT_NOT_SAFE")
        return DirectorRunDecision(
            decision_code="SAFETY_REVIEW_REQUIRED", terminal=True, human_action_required=True,
            next_action="REVIEW_RUNNER_SAFETY_EVIDENCE", reason_codes=tuple(reasons), **base,
        )

    # 2. EVIDENCE HEALTH
    if summary.evidence_complete is False:
        return DirectorRunDecision(
            decision_code="EVIDENCE_REVIEW_REQUIRED", terminal=True, human_action_required=True,
            next_action="REVIEW_RUNNER_EVIDENCE", reason_codes=("EVIDENCE_INCOMPLETE",), **base,
        )

    # 3. PROVIDER AUTH
    if worker_state == pipeline.WorkerState.BLOCKED_PROVIDER_AUTH.value or provider_condition == "PROVIDER_AUTH_BLOCKED":
        return DirectorRunDecision(
            decision_code="PROVIDER_AUTH_REQUIRED", terminal=True, human_action_required=True,
            next_action="RESTORE_PROVIDER_AUTH", reason_codes=("PROVIDER_AUTH_BLOCKED",), **base,
        )

    # 4. PROVIDER QUOTA / AVAILABILITY WAIT
    if worker_state == pipeline.WorkerState.WAITING_PROVIDER_QUOTA.value or provider_condition == "PROVIDER_QUOTA_EXHAUSTED":
        return DirectorRunDecision(
            decision_code="WAITING_PROVIDER", terminal=False, human_action_required=False,
            next_action="WAIT_UNTIL_PROVIDER_ELIGIBLE", reason_codes=("PROVIDER_QUOTA_EXHAUSTED",), **base,
        )

    # 5. TRANSIENT PIPELINE STATES
    if worker_state in _TRANSIENT_WORKER_STATES:
        return DirectorRunDecision(
            decision_code="IN_PROGRESS", terminal=False, human_action_required=False,
            next_action="WAIT_FOR_RUNNER", reason_codes=("PIPELINE_IN_PROGRESS",), **base,
        )

    # 6. INTERRUPTED
    if worker_state == pipeline.WorkerState.INTERRUPTED.value:
        return DirectorRunDecision(
            decision_code="RECOVERY_REVIEW_REQUIRED", terminal=True, human_action_required=True,
            next_action="REVIEW_RUNNER_RECOVERY", reason_codes=("RUN_INTERRUPTED",), **base,
        )

    # 7. SUCCESS
    if worker_state == pipeline.WorkerState.SUCCESS.value and summary.work_status == "SUCCESS":
        if evidence.checkpoint_policy == "ON_SUCCESS" and not evidence.checkpoint_commit:
            return DirectorRunDecision(
                decision_code="CHECKPOINT_REVIEW_REQUIRED", terminal=True, human_action_required=True,
                next_action="REVIEW_CHECKPOINT_EVIDENCE", reason_codes=("CHECKPOINT_MISSING",), **base,
            )
        return DirectorRunDecision(
            decision_code="READY_FOR_HOST_AUDIT", terminal=True, human_action_required=False,
            next_action="HOST_AUDIT", reason_codes=(), **base,
        )

    # 8. PARTIAL
    if worker_state == pipeline.WorkerState.PARTIAL.value:
        return DirectorRunDecision(
            decision_code="PARTIAL_REVIEW_REQUIRED", terminal=True, human_action_required=True,
            next_action="REVIEW_WORK_PRODUCT", reason_codes=("PARTIAL_RESULT",), **base,
        )

    # 9. BLOCKED
    if worker_state == pipeline.WorkerState.BLOCKED.value:
        return DirectorRunDecision(
            decision_code="BLOCKED_REVIEW_REQUIRED", terminal=True, human_action_required=True,
            next_action="REVIEW_BLOCK_REASON", reason_codes=("WORKER_BLOCKED",), **base,
        )

    # 10. FAILED
    if worker_state == pipeline.WorkerState.FAILED.value:
        return DirectorRunDecision(
            decision_code="FAILED_REVIEW_REQUIRED", terminal=True, human_action_required=True,
            next_action="REVIEW_FAILURE_EVIDENCE", reason_codes=("WORKER_FAILED",), **base,
        )

    # 11. CANCELLED
    if worker_state == pipeline.WorkerState.CANCELLED.value:
        return DirectorRunDecision(
            decision_code="CANCELLED", terminal=True, human_action_required=False,
            next_action="NONE", reason_codes=("WORKER_CANCELLED",), **base,
        )

    # 12. UNKNOWN / MISSING / CONTRADICTORY - fail closed.
    return DirectorRunDecision(
        decision_code="REVIEW_REQUIRED", terminal=True, human_action_required=True,
        next_action="REVIEW_STRUCTURED_STATE", reason_codes=("UNKNOWN_STRUCTURED_STATE",), **base,
    )


# Worker-state -> (decision_required, decision_type). V1 maps ONLY the states
# with unambiguous structural evidence (see FDB-1 section 18); every other
# worker state is listed here explicitly rather than inferred, so nothing is
# ever classified ARCHITECTURE/FUNCTIONAL/SECURITY from provider prose.
_DECISION_MAP = {
    pipeline.WorkerState.QUEUED.value: (False, None),
    pipeline.WorkerState.WAITING_DEPENDENCY.value: (False, None),
    pipeline.WorkerState.READY.value: (False, None),
    pipeline.WorkerState.RUNNING.value: (False, None),
    pipeline.WorkerState.RETRY_WAIT.value: (False, None),
    pipeline.WorkerState.WAITING_PROVIDER_QUOTA.value: (False, None),
    pipeline.WorkerState.BLOCKED_PROVIDER_AUTH.value: (True, "PROVIDER_AUTH"),
    pipeline.WorkerState.SUCCESS.value: (False, None),
    pipeline.WorkerState.PARTIAL.value: (False, None),
    pipeline.WorkerState.BLOCKED.value: (True, None),
    pipeline.WorkerState.FAILED.value: (True, None),
    pipeline.WorkerState.CANCELLED.value: (False, None),
    pipeline.WorkerState.INTERRUPTED.value: (True, "OPERATOR_RECOVERY"),
}


def _decision_for(worker_state: Optional[str]) -> tuple:
    return _DECISION_MAP.get(worker_state, (None, None))


def _classify_completion_mode(
    *, worker_state: Optional[str], checkpoint_commit: Optional[str],
    authorized_changed_paths: tuple, work_product_present: Optional[bool],
) -> Optional[str]:
    """FABRIC runner-owned-acceptance V1 (Problem 1): a pure, mechanical
    classification of fields `result()` already projects - never a new
    read, never a recomputation of Runner's own checkpoint/safety verdicts.
    Only ever classified for an already-SUCCESS worker; every other
    worker_state is None (not applicable), never guessed."""
    if worker_state != pipeline.WorkerState.SUCCESS.value:
        return None
    if checkpoint_commit:
        return claude_runner.COMPLETION_MODE_CHECKPOINT
    if authorized_changed_paths or work_product_present:
        # Material authorized changes/work product exist but no ON_SUCCESS
        # checkpoint was recorded for them (e.g. checkpoint_policy was never
        # set) - not SUCCESS_NOOP's "nothing to persist" contract either;
        # left unclassified rather than guessed.
        return None
    return claude_runner.COMPLETION_MODE_SUCCESS_NOOP


# FDB-3-1: the fixed set of `decision()` codes a HOST may request recovery
# from. Eligibility here is NOT Runner resume approval - it only permits the
# host to ASK `claude_runner.evaluate_resume` (via `recover()` -> a new
# `PipelineRunner` run) for resume; every other decision code (safety,
# evidence-incomplete, ready-for-audit, checkpoint-review, provider wait/
# auth, in-progress, cancelled, unknown) is refused as RECOVERY_NOT_ELIGIBLE.
_RECOVERY_ELIGIBLE_DECISION_CODES = frozenset({
    "FAILED_REVIEW_REQUIRED", "PARTIAL_REVIEW_REQUIRED",
    "RECOVERY_REVIEW_REQUIRED", "BLOCKED_REVIEW_REQUIRED",
})

# Reserved recovery lineage metadata keys (section M): `recover()` alone sets
# these, sourced only from structured prior-run evidence; a caller-supplied
# `DirectorRecoverySpec.metadata` collision fails closed.
_RECOVERY_RESERVED_METADATA_KEYS = (
    "recovered_from_director_run_id", "recovered_from_worker_id",
    "recovered_from_attempt", "recovered_from_work_product",
)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class FabricDirectorService:
    """Local application-facing Director facade. Never relies on the
    process's current working directory - every durable root is either
    passed explicitly or resolved once, at construction time, from the
    Runner repository this module's own source lives in."""

    def __init__(
        self,
        *,
        state_root=None,
        factory_root=None,
        director_root=None,
        self_worktree=None,
        registered_providers: Optional[list] = None,
        provider_resolver=None,
        executor=None,
        factory_ledger=None,
        pipeline_runner_options: Optional[dict] = None,
    ):
        repo = pipeline.default_self_worktree()
        self.state_root = Path(state_root) if state_root is not None else (
            Path(repo) / "runtime" / "claude_runner" / "pipelines"
        )
        self.factory_root = Path(factory_root) if factory_root is not None else (
            Path(repo) / "runtime" / "claude_runner" / "factory"
        )
        self.director_root = Path(director_root) if director_root is not None else (
            Path(repo) / "runtime" / "fabric_director" / "requests"
        )
        self.self_worktree = self_worktree
        self.registered_providers = registered_providers
        self.provider_resolver = provider_resolver
        self.executor = executor
        self.factory_ledger = factory_ledger
        self.pipeline_runner_options = dict(pipeline_runner_options or {})

    # -- project state (read-only) ------------------------------------------

    def project_state(self, worktree) -> dict:
        """Compact structural git state. Read-only: only `git rev-parse` /
        `git status` are ever invoked - never fetch/pull/reset."""
        top = pipeline.git_toplevel(worktree)
        if top is None:
            raise DirectorError("INVALID_WORKTREE", f"not an existing git worktree: {worktree}")
        snapshot = claude_runner.capture_git_snapshot(top)
        clean = not claude_runner.parse_porcelain_lines(snapshot.porcelain_status)
        return {
            "worktree": str(top),
            "branch": snapshot.branch,
            "head": snapshot.head,
            "clean": clean,
            "porcelain_status": snapshot.porcelain_status,
        }

    # -- submit ---------------------------------------------------------------

    def _generate_pipeline_id(self) -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dt%H%M%S%f")
        return f"fdb-{stamp}-{uuid.uuid4().hex[:8]}"

    def _validate_spec(self, spec: DirectorWorkOrderSpec) -> None:
        def fail(message: str) -> None:
            raise DirectorError("INVALID_SPEC", message)

        if not isinstance(spec.worktree, str) or not spec.worktree.strip():
            fail("worktree must be a non-empty string")
        if not isinstance(spec.work_order_text, str):
            fail("work_order_text must be a string")
        if not isinstance(spec.mode, str):
            fail("mode must be a string")
        if not isinstance(spec.provider, str):
            fail("provider must be a string")
        if spec.model is not None and not isinstance(spec.model, str):
            fail("model must be a string or None")
        if not isinstance(spec.authorize_paths, list) or any(not isinstance(p, str) for p in spec.authorize_paths):
            fail("authorize_paths must be a list of strings")
        if not isinstance(spec.required_capabilities, list) or any(
            not isinstance(c, str) for c in spec.required_capabilities
        ):
            fail("required_capabilities must be a list of strings")
        if not isinstance(spec.allow_shell, bool):
            fail("allow_shell must be a boolean")
        if spec.checkpoint_policy is not None and not isinstance(spec.checkpoint_policy, str):
            fail("checkpoint_policy must be a string or None")
        if spec.timeout_seconds is not None and (
            isinstance(spec.timeout_seconds, bool) or not isinstance(spec.timeout_seconds, int) or spec.timeout_seconds < 1
        ):
            fail("timeout_seconds must be a positive integer or None")
        if not isinstance(spec.metadata, dict):
            fail("metadata must be an object")
        if not isinstance(spec.completion_policy, str):
            fail("completion_policy must be a string")
        if not isinstance(spec.acceptance_commands, list) or any(
            not isinstance(c, str) for c in spec.acceptance_commands
        ):
            fail("acceptance_commands must be a list of strings")

    def _build_manifest_data(
        self, pipeline_id: str, worker_id: str, spec: DirectorWorkOrderSpec, worktree_top: Path, work_order_path: Path,
        *, resume_from: Optional[str] = None,
    ) -> dict:
        worker_entry = {
            "id": worker_id,
            "worktree": str(worktree_top),
            "work_order": str(work_order_path),
            "provider": spec.provider,
            "model": spec.model,
            "mode": spec.mode,
            "required_capabilities": list(spec.required_capabilities),
            "authorize_path": list(spec.authorize_paths),
            "metadata": dict(spec.metadata),
            "allow_shell": spec.allow_shell,
            "checkpoint_policy": spec.checkpoint_policy,
            "timeout_seconds": spec.timeout_seconds,
            "completion_policy": spec.completion_policy,
            "acceptance_commands": list(spec.acceptance_commands),
        }
        # FDB-3-1: `resume_from` is added ONLY for an explicit recovery
        # submission - an ordinary manifest never gains a `"resume_from":
        # null` key merely because the field now exists (see `parse_manifest`
        # / `WorkerSpec`).
        if resume_from is not None:
            worker_entry["resume_from"] = resume_from
        return {"pipeline_id": pipeline_id, "workers": [worker_entry]}

    def submit(self, spec: DirectorWorkOrderSpec) -> DirectorRunHandle:
        return self._submit(spec)

    def _submit(self, spec: DirectorWorkOrderSpec, *, resume_from: Optional[str] = None) -> DirectorRunHandle:
        self._validate_spec(spec)
        worktree_top = pipeline.git_toplevel(spec.worktree)
        if worktree_top is None:
            raise DirectorError("INVALID_WORKTREE", f"not an existing git worktree: {spec.worktree}")

        pipeline_id = self._generate_pipeline_id()
        worker_id = "w1"
        director_dir = self.director_root / pipeline_id
        try:
            director_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            raise DirectorError(
                "DIRECTOR_RUN_COLLISION", f"director run directory already exists: {director_dir}",
            )

        # Persist the Work Order byte-for-byte as UTF-8, except a trailing
        # newline is appended when absent (the only documented normalization -
        # see FDB-1 section 9); write_bytes avoids any newline translation.
        normalized_text = spec.work_order_text if spec.work_order_text.endswith("\n") else spec.work_order_text + "\n"
        work_order_path = director_dir / "work_order.md"
        work_order_path.write_bytes(normalized_text.encode("utf-8"))

        manifest_data = self._build_manifest_data(
            pipeline_id, worker_id, spec, worktree_top, work_order_path, resume_from=resume_from,
        )
        manifest_path = director_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest_data, indent=2, ensure_ascii=False), encoding="utf-8")

        validated, errors = True, []
        try:
            pipeline.parse_manifest(
                manifest_data, director_dir, self_worktree=self.self_worktree,
                registered_providers=self.registered_providers,
            )
        except pipeline.ManifestError as exc:
            validated, errors = False, list(exc.errors)

        return DirectorRunHandle(
            director_run_id=pipeline_id, pipeline_id=pipeline_id, worker_id=worker_id,
            worktree=str(worktree_top), director_dir=str(director_dir),
            work_order_path=str(work_order_path), manifest_path=str(manifest_path),
            state_root=str(self.state_root), validated=validated, validation_errors=errors,
        )

    # -- recover ------------------------------------------------------------

    def recover(self, spec: DirectorRecoverySpec) -> DirectorRunHandle:
        """FDB-3-1 governed recovery gateway. PREPARES/SUBMITS a brand NEW
        pipeline that asks Runner to resume a prior write-mode attempt's own
        work product - it never executes it (the caller still calls
        `run(handle)`, the SAME single `PipelineRunner` path `submit()`
        uses). Eligibility and the resumed worktree/scopes come ONLY from
        this service's own existing `decision()`/`evidence()` projections -
        never stdout/stderr/provider prose, never a second resume/work-
        product/pipeline store. Decision eligibility only permits the HOST to
        ASK Runner for resume; `claude_runner.evaluate_resume` remains the
        sole authority on whether the resume is actually allowed."""
        if spec.action != "RESUME_WORK_PRODUCT":
            raise DirectorError(
                "RECOVERY_ACTION_NOT_CONFIRMED",
                "spec.action must be exactly 'RESUME_WORK_PRODUCT' to confirm an explicit host recovery decision",
            )
        if not isinstance(spec.recovery_work_order_text, str) or not spec.recovery_work_order_text.strip():
            raise DirectorError("RECOVERY_WORK_ORDER_REQUIRED", "recovery_work_order_text must be a non-empty string")

        reserved_hit = sorted(k for k in _RECOVERY_RESERVED_METADATA_KEYS if k in (spec.metadata or {}))
        if reserved_hit:
            raise DirectorError(
                "RECOVERY_METADATA_RESERVED_KEY",
                f"spec.metadata may not set reserved lineage key(s): {', '.join(reserved_hit)}",
            )

        # Eligibility is a mechanical read of the prior run's OWN decision()
        # projection - never Runner resume approval, only host permission to
        # ask Runner for resume (see FDB-3-1 section C).
        decision = self.decision(spec.prior_run_id)
        if decision.decision_code not in _RECOVERY_ELIGIBLE_DECISION_CODES:
            raise DirectorError(
                "RECOVERY_NOT_ELIGIBLE",
                f"prior run {spec.prior_run_id!r} decision {decision.decision_code!r} is not recovery-eligible",
            )

        evidence = self.evidence(spec.prior_run_id)
        if not evidence.work_product_path or not isinstance(evidence.work_product, dict):
            raise DirectorError("NO_WORK_PRODUCT", f"prior run {spec.prior_run_id!r} has no structured work product")

        if spec.prior_worker_id is not None and spec.prior_worker_id != evidence.worker_id:
            raise DirectorError(
                "UNKNOWN_WORKER",
                f"prior_worker_id {spec.prior_worker_id!r} does not match prior run worker {evidence.worker_id!r}",
            )

        work_product = evidence.work_product
        worktree = work_product.get("worktree")
        authorized_scopes = work_product.get("authorized_scopes")
        if (
            not isinstance(worktree, str) or not worktree.strip()
            or not isinstance(authorized_scopes, list) or not authorized_scopes
            or any(not isinstance(p, str) or not p.strip() for p in authorized_scopes)
        ):
            raise DirectorError(
                "WORK_PRODUCT_INVALID",
                f"prior run {spec.prior_run_id!r} work product has no valid worktree/authorized_scopes",
            )

        if spec.authorize_paths is None:
            # Default: the prior attempt's OWN authorized scopes, copied
            # verbatim - never silently unioned/broadened (see section G).
            authorize_paths = list(authorized_scopes)
        else:
            if not isinstance(spec.authorize_paths, list) or any(not isinstance(p, str) for p in spec.authorize_paths):
                raise DirectorError("INVALID_SPEC", "authorize_paths must be a list of strings")
            authorize_paths = list(spec.authorize_paths)

        if spec.provider_override is not None:
            provider = spec.provider_override
        elif isinstance(work_product.get("provider"), str) and work_product.get("provider"):
            provider = work_product["provider"]
        elif isinstance(evidence.provider, str) and evidence.provider:
            provider = evidence.provider
        else:
            provider = providers.DEFAULT_PROVIDER_ID

        # Durable lineage (section M): reserved keys sourced ONLY from
        # structured prior-run evidence, never from caller-supplied metadata.
        metadata = dict(spec.metadata or {})
        metadata.update({
            "recovered_from_director_run_id": spec.prior_run_id,
            "recovered_from_worker_id": evidence.worker_id,
            "recovered_from_attempt": work_product.get("attempt"),
            "recovered_from_work_product": evidence.work_product_path,
        })

        recovery_spec = DirectorWorkOrderSpec(
            worktree=worktree,
            # Host-supplied recovery content ONLY - the original Work Order
            # is never read/reused (see section J).
            work_order_text=spec.recovery_work_order_text,
            mode=providers.MODE_WRITE,
            provider=provider,
            model=spec.model,
            authorize_paths=authorize_paths,
            required_capabilities=list(spec.required_capabilities),
            allow_shell=spec.allow_shell,
            checkpoint_policy=spec.checkpoint_policy,
            timeout_seconds=spec.timeout_seconds,
            metadata=metadata,
        )
        # Always a NEW pipeline_id (via `_submit` -> `_generate_pipeline_id`);
        # the original pipeline's files/directories are never touched.
        return self._submit(recovery_spec, resume_from=evidence.work_product_path)

    # -- validate ---------------------------------------------------------------

    def validate(self, handle: DirectorRunHandle) -> dict:
        """Re-validates the persisted manifest through the SAME Runner
        parser `submit` used - never a weaker parallel validator."""
        try:
            pipeline.load_manifest(
                handle.manifest_path, self_worktree=self.self_worktree, registered_providers=self.registered_providers,
            )
        except pipeline.ManifestError as exc:
            return {"validated": False, "errors": list(exc.errors)}
        return {"validated": True, "errors": []}

    # -- run ---------------------------------------------------------------

    def run(self, handle: DirectorRunHandle) -> DirectorRunSummary:
        try:
            manifest = pipeline.load_manifest(
                handle.manifest_path, self_worktree=self.self_worktree, registered_providers=self.registered_providers,
            )
        except pipeline.ManifestError as exc:
            raise DirectorError(
                "MANIFEST_INVALID", "; ".join(f"{e['code']}: {e['message']}" for e in exc.errors),
            )

        runner_kwargs = dict(self.pipeline_runner_options)
        runner_kwargs.setdefault("self_worktree", self.self_worktree)
        runner_kwargs.setdefault("provider_resolver", self.provider_resolver)
        runner_kwargs.setdefault("executor", self.executor)
        runner_kwargs.setdefault("factory_ledger", self.factory_ledger)
        runner = pipeline.PipelineRunner(manifest, self.state_root, **runner_kwargs)
        runner.run()
        return self.result(handle.pipeline_id)

    def submit_and_run(self, spec: DirectorWorkOrderSpec) -> DirectorRunSummary:
        handle = self.submit(spec)
        return self.run(handle)

    # -- status / result ---------------------------------------------------

    def status(self, run_id: str) -> dict:
        return pipeline.read_pipeline_status(self.state_root, run_id)

    def _load_json(self, path: Path) -> Optional[dict]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def result(self, run_id: str) -> DirectorRunSummary:
        status = self.status(run_id)
        workers = status.get("workers") or []
        worker_summary = workers[0] if workers else {}
        worker_id = worker_summary.get("id")

        worker_result = None
        if worker_id:
            worker_result = self._load_json(self.state_root / run_id / "workers" / worker_id / "result.json")

        attempts = (worker_result or {}).get("attempts") or []
        last_attempt = attempts[-1] if attempts else {}
        evidence_dir = (worker_result or {}).get("evidence_dir")
        metadata = self._load_json(Path(evidence_dir) / "metadata.json") if evidence_dir else None

        worker_state = worker_summary.get("state")
        decision_required, decision_type = _decision_for(worker_state)

        work_product_present = None
        if metadata is not None:
            work_product_present = bool(metadata.get("work_product_present"))

        authorized_changed_paths = tuple((metadata or {}).get("authorized_changed_paths") or ())
        completion_mode = _classify_completion_mode(
            worker_state=worker_state, checkpoint_commit=worker_summary.get("checkpoint_commit"),
            authorized_changed_paths=authorized_changed_paths, work_product_present=work_product_present,
        )

        return DirectorRunSummary(
            run_id=run_id,
            pipeline_id=status.get("pipeline_id", run_id),
            status=status.get("status"),
            stop_reason=status.get("stop_reason"),
            worker_id=worker_id,
            provider=worker_summary.get("provider"),
            requested_provider=worker_summary.get("requested_provider"),
            worker_state=worker_state,
            state_reason=worker_summary.get("state_reason"),
            work_status=(worker_result or {}).get("work_status"),
            runner_state=(worker_result or {}).get("runner_state"),
            attempts=worker_summary.get("attempts"),
            work_attempts_used=worker_summary.get("work_attempts_used"),
            availability_attempts=worker_summary.get("availability_attempts"),
            provider_condition=worker_summary.get("provider_condition"),
            next_eligible_utc=worker_summary.get("next_eligible_utc"),
            checkpoint_commit=worker_summary.get("checkpoint_commit"),
            evidence_dir=evidence_dir,
            evidence_complete=last_attempt.get("evidence_complete", True) if attempts else None,
            evidence_error=last_attempt.get("evidence_error"),
            changed_paths=tuple((metadata or {}).get("changed_paths_after_run") or ()),
            authorized_changed_paths=authorized_changed_paths,
            unauthorized_changed_paths=tuple((metadata or {}).get("unauthorized_changed_paths") or ()),
            work_product_present=work_product_present,
            decision_required=decision_required,
            decision_type=decision_type,
            completion_mode=completion_mode,
        )

    def evidence(self, run_id: str) -> DirectorRunEvidence:
        """Wider structured evidence projection alongside `result()`. Reads
        the SAME durable Runner artifacts `result()` reads, plus the
        attempt's own `<evidence_dir>/result.json` (safety/resume/branch-
        guard/write-scope/dirty-tree/normalized-result authority),
        `<evidence_dir>/work_product.json` and the worker's own
        `preflight.json` - never a parallel evidence store. Missing optional
        artifacts fail softly (None/()), never raising and never inventing a
        value."""
        status = self.status(run_id)
        workers = status.get("workers") or []
        worker_summary = workers[0] if workers else {}
        worker_id = worker_summary.get("id")

        worker_result = None
        if worker_id:
            worker_result = self._load_json(self.state_root / run_id / "workers" / worker_id / "result.json")

        attempts_list = (worker_result or {}).get("attempts") or []
        last_attempt = attempts_list[-1] if attempts_list else {}
        evidence_dir = (worker_result or {}).get("evidence_dir")

        metadata = self._load_json(Path(evidence_dir) / "metadata.json") if evidence_dir else None
        attempt_result = self._load_json(Path(evidence_dir) / "result.json") if evidence_dir else None

        work_product_path = None
        work_product = None
        if evidence_dir:
            candidate = Path(evidence_dir) / "work_product.json"
            if candidate.exists():
                work_product_path = str(candidate)
                work_product = self._load_json(candidate)

        preflight = None
        if worker_id:
            preflight = self._load_json(self.state_root / run_id / "workers" / worker_id / "preflight.json")

        safety_verdict_dict = (attempt_result or {}).get("safety_verdict") or {}

        work_product_present = None
        if metadata is not None:
            work_product_present = bool(metadata.get("work_product_present"))
        elif work_product is not None:
            work_product_present = True

        evidence_errors_source = None
        if attempt_result is not None and attempt_result.get("evidence_errors") is not None:
            evidence_errors_source = attempt_result.get("evidence_errors")
        elif metadata is not None and metadata.get("evidence_errors") is not None:
            evidence_errors_source = metadata.get("evidence_errors")
        elif last_attempt.get("evidence_error"):
            evidence_errors_source = [last_attempt.get("evidence_error")]

        return DirectorRunEvidence(
            run_id=run_id,
            pipeline_id=status.get("pipeline_id", run_id),
            worker_id=worker_id,
            provider=worker_summary.get("provider"),
            requested_provider=worker_summary.get("requested_provider"),
            worker_state=worker_summary.get("state"),
            state_reason=worker_summary.get("state_reason"),
            work_status=(worker_result or {}).get("work_status"),
            runner_state=(worker_result or {}).get("runner_state"),
            execution_mode=(attempt_result or {}).get("execution_mode"),
            attempts=worker_summary.get("attempts"),
            work_attempts_used=worker_summary.get("work_attempts_used"),
            availability_attempts=worker_summary.get("availability_attempts"),
            safety_verdict=safety_verdict_dict.get("verdict"),
            safety_reasons=tuple(safety_verdict_dict.get("reasons") or ()),
            changed_paths=tuple((metadata or {}).get("changed_paths_after_run") or ()),
            authorized_changed_paths=tuple((metadata or {}).get("authorized_changed_paths") or ()),
            unauthorized_changed_paths=tuple((metadata or {}).get("unauthorized_changed_paths") or ()),
            branch_guard=(attempt_result or {}).get("branch_guard"),
            write_scope=(attempt_result or {}).get("write_scope"),
            dirty_tree_policy=(attempt_result or {}).get("dirty_tree_policy"),
            evidence_dir=evidence_dir,
            evidence_complete=last_attempt.get("evidence_complete", True) if attempts_list else None,
            evidence_errors=tuple(evidence_errors_source or ()),
            provider_condition=worker_summary.get("provider_condition"),
            next_eligible_utc=worker_summary.get("next_eligible_utc"),
            preflight=preflight,
            normalized_result=(attempt_result or {}).get("normalized_result"),
            work_product_present=work_product_present,
            work_product_path=work_product_path,
            work_product=work_product,
            resume=(attempt_result or {}).get("resume"),
            process_supervision=(metadata or {}).get("process_supervision"),
            checkpoint_policy=worker_summary.get("checkpoint_policy"),
            checkpoint_commit=worker_summary.get("checkpoint_commit"),
            acceptance=last_attempt.get("acceptance"),
        )

    def decision(self, run_id: str) -> DirectorRunDecision:
        """Deterministic operational decision projection over `result()`/
        `evidence()` - reuses those two existing projections rather than
        reading any artifact a third time; see FDB-2-2 PRECEDENCE for the
        fixed, fail-closed classification order."""
        summary = self.result(run_id)
        evidence = self.evidence(run_id)
        return _classify_decision(summary, evidence)

    # -- factory state (read-only, secondary) -------------------------------

    def factory_state(self) -> dict:
        return pipeline.factory_status_report(self.state_root, self.factory_root)
