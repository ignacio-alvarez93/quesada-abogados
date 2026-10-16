# Runner V2.1 — Technical Reference (R21-F)

Governed execution engine for AI coding providers (Claude, Codex, ...) over Git
worktrees: one governed Work Order per invocation, evidence-backed safety,
durable multiworker/multiprovider orchestration, and a durable factory ledger
for cross-pipeline operational history. This document is the concise public
reference for the contracts R21-A through R21-E built; it does not change any
of them.

Modules: `claude_runner.py` (single governed execution), `runner_providers.py`
(provider abstraction), `runner_process_supervision.py` (process containment),
`runner_provider_availability.py` (quota/auth classification), `runner_pipeline.py`
(durable multiworker/multiprovider orchestrator + factory-status/history),
`runner_factory_ledger.py` (append-only operational history), `runner_module_governance.py`
(ownership/lifecycle/handoff contracts layered on the ledger).

---

## 1. Execution core (`claude_runner.execute_work_order`)

One Work Order = one fresh, non-interactive provider CLI invocation. Never
passes the provider's own session-resume flag; never runs `git commit/push/
merge/reset/clean/checkout` itself (the one exception is `create_checkpoint`,
§4). Bash/PowerShell/REPL tools are never granted to the model in either mode.

**Modes**

| Mode | Tools granted | Guards enforced |
|---|---|---|
| `read-only` (default) | Read, Grep, Glob | any repository mutation after the run → `FAILED_SAFETY` |
| `write` (opt-in) | + Edit, Write, NotebookEdit | branch guard, write-scope guard, dirty-tree guard (below) |

**Write-mode guards, evaluated before the provider is ever invoked:**

1. **Branch guard** — refuses `main`/`master`/`develop` and detached HEAD.
2. **Write-scope guard** — requires ≥1 `--authorize-path` (repo-relative path
   or glob); absolute paths and `..` segments are rejected. Refused as a whole
   (never silently narrowed) if any scope is malformed.
3. **Dirty-tree guard** — refuses ANY dirty working tree, unconditionally.
   `--allow-dirty` is accepted for backward CLI compatibility only and has no
   effect. The only way past a dirty tree is a validated `--resume-from`
   (§3).

**After invocation:** a branch or HEAD change is always `FAILED_SAFETY` in
write mode (no granted tool can produce one). Every runner-caused changed path
is checked against the authorized scope; anything outside it is
`FAILED_SAFETY` too. Offending files are preserved for inspection — never
reverted. In-scope working-tree changes are the expected, authorized effect of
the run and are reported, not flagged.

### State model

`RunState` (see `claude_runner.RunState`) with a fixed exit-code map
(`EXIT_CODES`): `SUCCESS`(0) … governance refusals (20-25) … work outcomes
(6-9, 12-15). Two independent axes are never conflated:

* **WORK_STATUS** (`SUCCESS|PARTIAL|BLOCKED|FAILED|UNVERIFIED|INVALID_VERDICT`)
  — what the Work Order's own `VERDICT=` contract claims.
* **Evidence completeness** (`WorkOrderResult.evidence_complete`/
  `evidence_error`) — whether every evidence artifact was actually persisted.
  A provider that completed successfully but left an evidence artifact
  unwritten (disk/permission/race) is **never** reported `WORK_FAILED`: the
  pipeline layer classifies it `PARTIAL` / `EVIDENCE_FINALIZATION_FAILED`
  while the attempt record still carries `work_status=SUCCESS` (Scenario A).

### Evidence

Every attempt writes, under `<repo>/runtime/claude_runner/runs/<run_id>/` (or
`--run-root`): `prompt.txt`, `stdout.txt`, `stderr.txt`, `git_before.txt`,
`git_after.txt`, `metadata.json`, `preflight.json`, `result.json`, and
(write mode, when work is left behind) `work_product.json`. Secondary
evidence-artifact failures are recorded, never raised — a write failure can
never overwrite an already-completed provider result with an uncaught
exception.

---

## 2. Work-product preservation

`WorkOrderResult.work_product_present` (bool) is the REQUIRED-MODEL signal:
true whenever this attempt left durable, authorized, safety-clean changes
behind — including an INTERRUPTED or quota-exhausted attempt. The record
(`work_product.json`, schema `WORK_PRODUCT_SCHEMA_VERSION=1`) carries:
`worktree`, `branch`, `base_head`, `authorized_scopes`,
`authorized_changed_paths` (PROVIDER_WORK_PRODUCT), `runner_owned_paths`
(exact-path RUNNER_OWNED_EVIDENCE — the run's own evidence artifact lines,
never a directory-prefix exemption), `process_confirmed_stopped`, `state`.

## 3. Governed resume (`--resume-from`)

Only takes effect when the tree is **currently dirty**. `evaluate_resume`
validates, in order, against the CURRENT repository state: schema version →
malformed-field checks → worktree match → branch match → `base_head == current
HEAD` (write mode never commits, so any drift means provenance is gone) →
`process_confirmed_stopped is True` → every current dirty line is either
`runner_owned_paths` or in `authorized_changed_paths` → every such line is
still inside the CURRENTLY authorized scope. Any failure → `RESUME_REFUSED`,
tree left untouched (Scenario C: an unrelated/unknown dirty tree — no matching
record, or none supplied — always fails closed exactly this way). Success →
`ALLOWED_RESUMED`; nothing is ever reset or deleted either way (Scenario B).

## 4. Governed checkpoint (`create_checkpoint`)

Separate, explicitly-invoked utility — never called implicitly by
`execute_work_order`. Turns one completed write-mode attempt's own
`work_product.json` into exactly one deterministic WIP commit
(`runner-checkpoint(wip): <pipeline>/<worker> attempt=N provider=P`) —
never a merge, push, or PR. Every check is re-verified against the CURRENT
repo state (branch/HEAD unmoved, only recorded paths dirty, `git diff --check`
clean, index matches exactly after `git add`, worktree clean after commit).
Any refusal stages/commits nothing and unstages anything partially staged.

`CHECKPOINT_OK_DECISIONS = {CREATED, SKIPPED_NO_WORK_PRODUCT}`; every other
decision is a refusal.

---

## 5. Pipeline orchestrator (`runner_pipeline.PipelineRunner`)

Durable multiworker/multiprovider orchestration over a JSON manifest
(`pipeline_id`, `workers[]`, `max_workers`, `provider_limits`,
`not_before_utc`/`deadline_utc`). Reuses `execute_work_order` unchanged as its
only execution path; never creates worktrees, never installs providers.

**Worker states:** `QUEUED, WAITING_DEPENDENCY, READY, RUNNING, RETRY_WAIT,
WAITING_PROVIDER_QUOTA, BLOCKED_PROVIDER_AUTH, SUCCESS, PARTIAL, BLOCKED,
FAILED, CANCELLED, INTERRUPTED`. Terminal: `SUCCESS|PARTIAL|BLOCKED|FAILED|
CANCELLED`. `INTERRUPTED` (RUNNING when its orchestrator died) is never
auto-retried; re-queue requires `--requeue-interrupted` or `--rerun <id>`, and
still hits the same dirty-tree guard as any other write-mode attempt.

**Dependency gating** (`dependency_policy`): `success` (default) |
`success_or_partial` | `completed`. A dependency landing on a state outside
the accepted set and inside `TERMINAL_STATES` makes every dependent
`CANCELLED` (`DEPENDENCY_UNSATISFIED`) — this is how a checkpoint failure
(worker → `BLOCKED`, not `SUCCESS`) prevents a `CLOSER` from ever starting
(Scenario E). A `BLOCKED:PROVIDER_PROCESS_UNRESOLVED` dependency is always
`UNSATISFIABLE` regardless of policy — a worker whose provider process death
was never confirmed can never release dependents.

**Builder → checkpoint → closer handoff (Scenario D):** a WRITE worker opts in
via manifest `checkpoint_policy: "ON_SUCCESS"` (absent/None = prior behavior,
unchanged). On `SUCCESS` with complete evidence, the pipeline calls
`create_checkpoint`; on `CREATED`/`SKIPPED_NO_WORK_PRODUCT` the worker reports
`SUCCESS` with `attempt.checkpoint` recorded and a `CHECKPOINT_CREATED` ledger
event; on any other checkpoint decision the worker lands on
`BLOCKED/CHECKPOINT_FAILED` — never silently downgraded to `SUCCESS` with an
uncommitted tree — so a `dependency_policy=success` CLOSER worker never starts
against a dirty or unfinished worktree.

**Concurrency/safety:** in-process same-worktree exclusion
(`_same_worktree_conflict`) plus a durable, cross-process OS-lock write lease
per worktree (`DirLease`, stored inside the worktree's own git dir, never part
of the diff). A provider process whose death cannot be confirmed keeps its
lease held (`_unresolved_leases`) rather than releasing it — a later run can
never assume the previous one is gone.

**Manifest CLI:**

```bash
python scripts/ai/runner_pipeline.py validate --manifest pipeline.json
python scripts/ai/runner_pipeline.py pipeline --manifest pipeline.json \
    --max-workers 2 --provider-limit claude=2 --keep-awake
python scripts/ai/runner_pipeline.py status --pipeline-id my-pipeline
```

---

## 6. Factory ledger (`runner_factory_ledger.FactoryLedger`)

Optional (`None` by default — complete no-op, zero extra I/O when disabled),
durable, append-only cross-pipeline history: `<factory_root>/events.jsonl`
(source of truth) + `<factory_root>/modules.json` (disposable, rebuildable
cache). Never stores prompts/transcripts/credentials — `extra` is scrubbed of
secret-shaped keys and oversized values before being written.

**Event types:** `WORKER_STARTED`, `WORKER_FINISHED`, `WORK_PRODUCT_CREATED`,
`CHECKPOINT_CREATED`, `CERTIFICATION_STARTED`, `CERTIFICATION_FINISHED`,
`MODULE_STATE_CHANGED`, `MODULE_CERTIFIED`, `MODULE_CLOSED`. Fields (all
optional): `project, module, module_version, pipeline_id, worker_id,
provider, role, worktree, branch, base_commit, result_commit, state,
state_reason, certification_status, closer` + scrubbed `extra`.

`PipelineRunner` is today's only automatic producer and only emits
`WORKER_STARTED/WORKER_FINISHED/WORK_PRODUCT_CREATED/MODULE_STATE_CHANGED/
CHECKPOINT_CREATED` — it never certifies or closes anything. An external
certifier/closer (or a future Fabric orchestrator) writes
`CERTIFICATION_*/MODULE_CERTIFIED/MODULE_CLOSED` through the same API.

**Reads are pure folds over the event log** (`materialize_modules`,
`factory_status`), so replaying the same events in the same order is always
deterministic regardless of how many pipelines/providers contributed
(Scenario F). A torn/corrupt trailing line is skipped, never raised.

```bash
python scripts/ai/runner_pipeline.py factory-status \
    --state-root runtime/claude_runner/pipelines --factory-root runtime/claude_runner/factory
python scripts/ai/runner_pipeline.py factory-history \
    --factory-root runtime/claude_runner/factory --module qcc-auto-twin --role BUILDER
```

`factory-status` combines LIVE queued/waiting/active state (read straight from
every pipeline's own `pipeline_result.json`) with the ledger's durable
per-module state; `factory-history` is the durable event timeline alone,
filterable by `module/role/provider/pipeline_id/worker_id/event_type`.

## 7. Module governance (`runner_module_governance`)

Provider-neutral ownership + lifecycle layered on the ledger, without any
ledger schema change: lifecycle transitions are carried in
`extra["lifecycle_state"]`, a namespace the ledger itself never reads, kept
strictly separate from ordinary worker-attempt `state` values folded by
`materialize_modules`.

**Roles:** `OWNER, BUILDER, CONTRIBUTOR, AUDITOR, CLOSER` — policy data
(`OwnershipPolicy`, always caller-supplied) decides *which* provider may hold
each role; the engine only enforces it (`is_role_permitted`).

**Lifecycle:** `PLANNED → ARCHITECTED → BUILDING → READY_FOR_REVIEW →
AUDITING → CERTIFYING → CLOSED`, with `REWORK_REQUIRED` reachable from
`BUILDING/READY_FOR_REVIEW/AUDITING/CERTIFYING` and looping back to
`BUILDING`. `CLOSED` is reachable only from `CERTIFYING`, always its own
explicit `CLOSER`-driven event — a successful build or a passed audit never
implies closure by itself.

**Handoff record** (`HandoffRecord`, schema `HANDOFF_SCHEMA_VERSION=1`):
versioned, reference-only (`checkpoint_commit`, short `evidence_refs`, short
`known_debt` — never prompts/transcripts) BUILDER → READY_FOR_REVIEW →
AUDITOR/CLOSER payload, recorded on the same ledger event as the
`READY_FOR_REVIEW` transition.

---

## 8. Fabric boundary

**Runner owns (and Fabric must consume, never reimplement):**
execute workers/providers; process containment; worktree safety
(branch/dirty-tree/write-scope guards); authorization scope; checkpoint/resume
primitives; dependency execution within one pipeline; result/evidence
contracts (`WorkOrderResult`, evidence artifacts); durable execution/module
ledger primitives (`FactoryLedger`, `ModuleGovernance`).

**Fabric owns (out of scope here — not built in R21-F):**
portfolio/project planning; module scheduling across pipelines; higher-level
orchestration/assignment strategy; UI/dashboard; cross-project planning;
policy composition (deciding *which* `OwnershipPolicy`/manifest to submit);
user-facing factory management.

Fabric is expected to: submit Runner pipeline manifests, read
`factory-status`/`factory-history`/`ModuleGovernance` state, and drive
`ModuleGovernance` transitions through the same API a human/CI operator would
— never reach into worktrees, provider processes, or the ledger's on-disk
files directly.

---

## 9. CLI quick reference

```bash
# Single governed Work Order, read-only (default)
python scripts/ai/claude_runner.py --repo <path> --work-order wo.txt

# Single governed Work Order, write mode
python scripts/ai/claude_runner.py --repo <path> --work-order wo.txt \
    --mode write --authorize-path "scripts/ai/**"

# Resume a dirty tree left by a prior write-mode attempt
python scripts/ai/claude_runner.py --repo <path> --work-order wo.txt \
    --mode write --authorize-path "scripts/ai/**" \
    --resume-from runtime/claude_runner/runs/<prior_run_id>/work_product.json

# Manifest-driven pipeline
python scripts/ai/runner_pipeline.py validate --manifest pipeline.json
python scripts/ai/runner_pipeline.py pipeline --manifest pipeline.json
python scripts/ai/runner_pipeline.py status --pipeline-id <id>
python scripts/ai/runner_pipeline.py factory-status
python scripts/ai/runner_pipeline.py factory-history --module <name>
```

Windows/Git Bash: `scripts/ai/claude_runner.sh` is a thin `exec python
claude_runner.py "$@"` wrapper (`PYTHON_BIN` override supported); process
containment uses Windows Job Objects (suspended-create → assign → resume,
`KILL_ON_JOB_CLOSE`) on `win32` and POSIX process groups elsewhere — both
paths are covered directly in `runner_process_supervision.py`, never shelled
out to platform-specific commands.
