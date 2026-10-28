"""FCP-5A-01: declarative DAG blueprint bridge over the EXISTING Runner pipeline.

Answers ONE question: does an immutable, explicit declaration of 2+ Work
Orders (nodes) with explicit `depends_on` edges compile to a Runner manifest
that the EXISTING `runner_pipeline.parse_manifest` accepts? It returns a
frozen, deterministic `BlueprintPlan` preview plus the native
`runner_pipeline.Manifest` that parser produced - never anything executed.

Why this is a compiler, not a second engine
-------------------------------------------
* Every graph, branch, dependency, worktree, provider, mode, capability,
  policy and limit decision is `runner_pipeline.parse_manifest`'s: a valid
  declaration is composed into native manifest JSON and handed to it EXACTLY
  ONCE. Its `ManifestError` propagates unchanged (same object, native codes);
  the adapter never fixes, narrows, reorders or reinterprets it.
* No cycle finder, topological sort, scheduler, retry/lease logic, provider
  registry or state store exists here. Edges are forwarded verbatim, in the
  declared order; no dependency is inferred and no node is selected or
  dropped. Node order is forwarded verbatim too (it is the Runner's
  scheduling tie-break after `priority`).
* The adapter itself only refuses what the Runner cannot see: the
  declaration's own exact types, tuple-only (immutable) sequences, explicit
  absolute paths without control characters, the multi-node bounds and
  duplicated `provider_limits` pairs. Those refusals are `BlueprintError`
  and happen BEFORE delegation - the parser is then never called.

Pass-through contract (bounded, explicit)
-----------------------------------------
Required per node: `id`, `worktree`, `work_order` (an EXISTING file; never
generated or written here), `provider`, `mode`, `depends_on`. Optional per
node, forwarded ONLY when not None (None = key omitted = Runner's own
default): `dependency_policy`, `priority`, `model`, `required_capabilities`,
`authorize_path`, `allow_shell`, `checkpoint_policy`, `timeout_seconds`,
`max_attempts`, `backoff_seconds`, `completion_policy`,
`acceptance_commands`. Deliberately NOT supported in V1: `fallback_providers`
(no fallback providers), `metadata` (no secret/token/envelope surface),
`resume_from` (never implicit approval; recovery stays the Director's
`recover()`), and the `dependencies` alias (one explicit spelling only).

What a valid plan means
-----------------------
STRUCTURALLY_VALID only: the Runner parser accepted the manifest. It is NOT
executed, approved, merged or integrated, and it is not a permit. Execution-
time Runner guards (branch guard incl. protected `develop`, dirty tree,
write scope, provider preflight, resume) are NOT evaluated here and remain
the Runner's at execution time. Nothing here runs a worker, a process or a
shell, creates a worktree or directory, writes a file or a manifest, touches
the factory ledger, or changes a checkout; the only I/O is the parser's own
established read-only worktree/Work Order inspection. No worktree-
retirement, promotion or D-1..D-12 policy feature is wired in.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    from scripts.ai import runner_pipeline as pipeline
except ImportError:  # pragma: no cover - direct script execution
    _this_dir = Path(__file__).resolve().parent
    if str(_this_dir) not in sys.path:
        sys.path.insert(0, str(_this_dir))
    import runner_pipeline as pipeline  # type: ignore[no-redef]


PLAN_SCHEMA = "fcp5a01-dag-blueprint-plan-v1"
PLAN_MARKER = "FCP5A01_BLUEPRINT_STRUCTURALLY_VALID_NOT_EXECUTED_NOT_A_PERMIT"
STATUS_STRUCTURALLY_VALID = "STRUCTURALLY_VALID"

MIN_BLUEPRINT_NODES = 2
MAX_BLUEPRINT_NODES = 64

# Runner guards that only run at execution time; listed so a reader of the
# preview cannot mistake structural validity for having passed them.
EXECUTION_TIME_GUARDS_NOT_EVALUATED = (
    "BRANCH_GUARD", "DIRTY_TREE", "WRITE_SCOPE", "PROVIDER_PREFLIGHT", "RESUME",
)

# Optional node fields forwarded verbatim when not None, in manifest-key form.
_OPTIONAL_SCALAR_FIELDS = (
    "dependency_policy", "priority", "model", "allow_shell", "checkpoint_policy", "timeout_seconds",
    "max_attempts", "backoff_seconds", "completion_policy",
)
_OPTIONAL_TUPLE_FIELDS = ("required_capabilities", "authorize_path", "acceptance_commands")

# Every forwarded path is absolute (enforced before delegation), so the
# parser never consults `base_dir`. This relative sentinel is passed only
# because the native signature requires one: were a relative path ever to
# reach the parser it would resolve beneath this non-provisioned name and be
# refused there (INVALID_WORKTREE / INVALID_WORK_ORDER), never silently found.
_ABSOLUTE_PATHS_ONLY_BASE_DIR = Path("fcp5a01-absolute-paths-only-base-dir-never-consulted")


class BlueprintError(Exception):
    """Adapter-level declaration refusal raised BEFORE delegation; the
    Runner parser was not called and nothing was compiled. Entries use the
    same `{"code", "worker", "message"}` shape as `ManifestError`."""

    def __init__(self, errors: list):
        self.errors = errors
        super().__init__("; ".join(f"{e['code']}: {e['message']}" for e in errors))


# ---------------------------------------------------------------------------
# Declarations (immutable; sequences are tuples)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BlueprintNode:
    """One Work Order in the intended DAG. `work_order` must be an EXISTING
    file path; nothing is generated or written for it here."""

    id: str
    worktree: str
    work_order: str
    provider: str
    mode: str
    depends_on: tuple
    dependency_policy: Optional[str] = None
    priority: Optional[int] = None
    model: Optional[str] = None
    required_capabilities: Optional[tuple] = None
    authorize_path: Optional[tuple] = None
    allow_shell: Optional[bool] = None
    checkpoint_policy: Optional[str] = None
    timeout_seconds: Optional[int] = None
    max_attempts: Optional[int] = None
    backoff_seconds: Optional[float] = None
    completion_policy: Optional[str] = None
    acceptance_commands: Optional[tuple] = None


@dataclass(frozen=True)
class DagBlueprint:
    """The whole intended DAG. `provider_limits` is a tuple of
    `(provider_id, limit)` pairs; pipeline-level options are forwarded only
    when not None."""

    pipeline_id: str
    nodes: tuple
    max_workers: Optional[int] = None
    provider_limits: Optional[tuple] = None
    not_before_utc: Optional[str] = None
    deadline_utc: Optional[str] = None


# ---------------------------------------------------------------------------
# Results (read-only preview; never a permit)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PlanNode:
    """A node as the Runner parser understood it (taken from the native
    `WorkerSpec`, never re-derived here)."""

    id: str
    provider: str
    mode: str
    depends_on: tuple
    dependency_policy: str
    priority: int
    worktree_top: str
    work_order: str
    allow_shell: bool


@dataclass(frozen=True)
class BlueprintPlan:
    pipeline_id: str
    nodes: tuple
    manifest_json: str
    manifest_sha256: str
    fingerprint: str
    schema: str = field(default=PLAN_SCHEMA, init=False)
    marker: str = field(default=PLAN_MARKER, init=False)
    status: str = field(default=STATUS_STRUCTURALLY_VALID, init=False)
    execution_time_guards_not_evaluated: tuple = field(default=EXECUTION_TIME_GUARDS_NOT_EVALUATED, init=False)
    executed: bool = field(default=False, init=False)
    approved: bool = field(default=False, init=False)
    merged: bool = field(default=False, init=False)
    integrated: bool = field(default=False, init=False)
    execution_permit: bool = field(default=False, init=False)


@dataclass(frozen=True)
class BlueprintCompilation:
    """`plan` is the read-only, fingerprinted preview. `manifest` is the
    native object `parse_manifest` returned, for a later governed caller to
    hand to the Runner; this module never does."""

    plan: BlueprintPlan
    manifest: pipeline.Manifest


# ---------------------------------------------------------------------------
# Declaration checks (adapter-owned only)
# ---------------------------------------------------------------------------

def _path_errors(value, name: str, label: str) -> list:
    if not isinstance(value, str):
        return [{"code": "BLUEPRINT_INVALID_TYPE", "worker": label, "message": f"{name} must be a string"}]
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        return [{"code": "BLUEPRINT_PATH_INVALID", "worker": label, "message": f"{name} contains control characters"}]
    if not Path(value).is_absolute():
        return [{"code": "BLUEPRINT_PATH_NOT_ABSOLUTE", "worker": label, "message": f"{name} must be an absolute path"}]
    return []


def _node_errors(node, index: int) -> list:
    if type(node) is not BlueprintNode:
        return [{"code": "BLUEPRINT_INVALID_TYPE", "worker": f"#{index}", "message": "node must be a BlueprintNode"}]
    label = node.id if isinstance(node.id, str) else f"#{index}"
    errors = _path_errors(node.worktree, "worktree", label) + _path_errors(node.work_order, "work_order", label)
    if type(node.depends_on) is not tuple:
        errors.append({"code": "BLUEPRINT_NOT_IMMUTABLE", "worker": label, "message": "depends_on must be a tuple"})
    for name in _OPTIONAL_TUPLE_FIELDS:
        value = getattr(node, name)
        if value is not None and type(value) is not tuple:
            errors.append({"code": "BLUEPRINT_NOT_IMMUTABLE", "worker": label, "message": f"{name} must be a tuple"})
    return errors


def blueprint_errors(blueprint) -> tuple:
    """Adapter-owned refusals only; empty when the declaration may be handed
    to the Runner parser. Graph/provider/mode/worktree/policy/limit
    decisions are intentionally absent: they are the parser's."""
    if type(blueprint) is not DagBlueprint:
        return ({"code": "BLUEPRINT_INVALID_TYPE", "worker": None, "message": "blueprint must be a DagBlueprint"},)
    if type(blueprint.nodes) is not tuple:
        return ({"code": "BLUEPRINT_NOT_IMMUTABLE", "worker": None, "message": "nodes must be a tuple"},)
    errors: list = []
    # An empty graph is left to the parser (native NO_WORKERS); a single node
    # is the single-worker Director's contract, not a multi-Work-Order DAG.
    if len(blueprint.nodes) == 1:
        errors.append({
            "code": "BLUEPRINT_TOO_FEW_NODES", "worker": None,
            "message": f"a DAG blueprint declares at least {MIN_BLUEPRINT_NODES} nodes",
        })
    if len(blueprint.nodes) > MAX_BLUEPRINT_NODES:
        errors.append({
            "code": "BLUEPRINT_TOO_MANY_NODES", "worker": None,
            "message": f"a DAG blueprint declares at most {MAX_BLUEPRINT_NODES} nodes",
        })
    else:
        for index, node in enumerate(blueprint.nodes):
            errors.extend(_node_errors(node, index))
    limits = blueprint.provider_limits
    if limits is not None:
        if type(limits) is not tuple or any(type(p) is not tuple or len(p) != 2 for p in limits):
            errors.append({
                "code": "BLUEPRINT_NOT_IMMUTABLE", "worker": None,
                "message": "provider_limits must be a tuple of (provider_id, limit) tuples",
            })
        elif any(not isinstance(p[0], str) for p in limits):
            errors.append({
                "code": "BLUEPRINT_INVALID_TYPE", "worker": None, "message": "provider_limits ids must be strings",
            })
        elif len({p[0] for p in limits}) != len(limits):
            errors.append({
                "code": "BLUEPRINT_DUPLICATE_PROVIDER_LIMIT", "worker": None,
                "message": "provider_limits names a provider more than once",
            })
    return tuple(errors)


# ---------------------------------------------------------------------------
# Composition + delegation
# ---------------------------------------------------------------------------

def compose_manifest_data(blueprint: DagBlueprint) -> dict:
    """Native manifest JSON for an already-checked declaration: a fresh
    structure (tuples become NEW lists), nodes and edges in declared order,
    optional keys present only when explicitly declared."""
    workers = []
    for node in blueprint.nodes:
        entry = {
            "id": node.id, "worktree": node.worktree, "work_order": node.work_order,
            "provider": node.provider, "mode": node.mode, "depends_on": list(node.depends_on),
        }
        for name in _OPTIONAL_SCALAR_FIELDS:
            if getattr(node, name) is not None:
                entry[name] = getattr(node, name)
        for name in _OPTIONAL_TUPLE_FIELDS:
            if getattr(node, name) is not None:
                entry[name] = list(getattr(node, name))
        workers.append(entry)
    data = {"pipeline_id": blueprint.pipeline_id, "workers": workers}
    if blueprint.max_workers is not None:
        data["max_workers"] = blueprint.max_workers
    if blueprint.provider_limits is not None:
        data["provider_limits"] = {p: limit for p, limit in blueprint.provider_limits}
    for name in ("not_before_utc", "deadline_utc"):
        if getattr(blueprint, name) is not None:
            data[name] = getattr(blueprint, name)
    return data


def _canonical(payload) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _plan_material(plan: BlueprintPlan) -> dict:
    material = dataclasses.asdict(plan)
    material.pop("fingerprint")
    return material


def plan_fingerprint(plan: BlueprintPlan) -> str:
    return hashlib.sha256(_canonical(_plan_material(plan)).encode("utf-8")).hexdigest()


def canonical_plan_json(plan: BlueprintPlan) -> str:
    return _canonical(dataclasses.asdict(plan))


def verify_plan(plan) -> bool:
    """True only for an untampered plan: exact type, constant flags intact
    and fingerprint matching its content. Re-parses nothing."""
    if type(plan) is not BlueprintPlan:
        return False
    constants = (
        plan.schema == PLAN_SCHEMA and plan.marker == PLAN_MARKER and plan.status == STATUS_STRUCTURALLY_VALID
        and plan.execution_time_guards_not_evaluated == EXECUTION_TIME_GUARDS_NOT_EVALUATED
        and plan.executed is False and plan.approved is False and plan.merged is False
        and plan.integrated is False and plan.execution_permit is False
    )
    return constants and plan.fingerprint == plan_fingerprint(plan)


def compile_blueprint(
    blueprint: DagBlueprint, *, self_worktree: Optional[Path] = None, registered_providers: Optional[list] = None,
) -> BlueprintCompilation:
    """Checks the declaration, composes native manifest JSON and calls
    `runner_pipeline.parse_manifest` exactly once. Raises `BlueprintError`
    (parser not called) or the parser's own `ManifestError` unchanged.
    `self_worktree=None` means the Runner's own `default_self_worktree()`,
    exactly as `PipelineRunner` and the pipeline CLI resolve it, so the
    native write-mode self-target refusal is never disabled by omission."""
    errors = blueprint_errors(blueprint)
    if errors:
        raise BlueprintError(list(errors))
    data = compose_manifest_data(blueprint)
    manifest = pipeline.parse_manifest(
        data, _ABSOLUTE_PATHS_ONLY_BASE_DIR,
        self_worktree=self_worktree if self_worktree is not None else pipeline.default_self_worktree(),
        registered_providers=registered_providers,
    )
    nodes = tuple(
        PlanNode(
            id=s.id, provider=s.provider, mode=s.mode, depends_on=tuple(s.depends_on),
            dependency_policy=s.dependency_policy, priority=s.priority, worktree_top=s.worktree_top,
            work_order=s.work_order, allow_shell=s.allow_shell,
        )
        for s in manifest.workers
    )
    draft = BlueprintPlan(
        pipeline_id=manifest.pipeline_id, nodes=nodes, manifest_json=_canonical(data),
        manifest_sha256=manifest.sha256, fingerprint="",
    )
    plan = dataclasses.replace(draft, fingerprint=plan_fingerprint(draft))
    return BlueprintCompilation(plan=plan, manifest=manifest)
