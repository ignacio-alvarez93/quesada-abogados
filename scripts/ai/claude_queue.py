"""Durable single-worker queue storage foundation for Claude Runner V1.5.

RUNNER-1.5C added persistence only: enqueue/load/list, the state machine,
the durable OS lock, and orphan RUNNING recovery. RUNNER-1.5D adds a
single-worker `run_next()` primitive that connects that durable queue to
the governed Runner (`claude_runner.execute_work_order()`) for exactly one
QUEUED item per call. This module still does NOT replay/reconcile
checkpoints on its own, does NOT retry anything automatically, and does
NOT commit/push/merge/switch branches/create worktrees or schedule
multiple concurrent workers.

Every queue item is a directory containing:

* item.json     - schema_version, item_id, timestamps, state, repository
                   identity/path, requested execution mode, authorized
                   paths, timeout/model/label, durable work_order filename
                   and SHA-256, and an append-only event history.
* work_order.txt - the complete Work Order text, copied in at enqueue time
                   so the queue never depends on /tmp or any external
                   source afterward.

No conversational session ID is ever stored and no --resume/--continue
semantics are introduced anywhere in this module (mirrors claude_runner.py's
one-Work-Order-per-fresh-invocation contract).

RUNNER-1.5E adds durable repository checkpoint capture for items that reach
BLOCKED_ON_CHECKPOINT (write-mode mutation, executor exception, or orphan
recovery) and an explicit, governed human-reconciliation primitive
(`reconcile_checkpoint`) with exactly three operator resolutions - ACCEPT,
FAIL, RETRY. Checkpoint capture reads the target repository through
explicit, read-only, argv-only `git` subprocess calls (shell=False); it
never invokes Claude or claude_runner, and it never stages, commits,
resets, restores or cleans the target repository. Checkpoint payloads are
durable, under the queue item directory (never /tmp, never conversational
storage) and never contain Claude stdout/stderr/transcripts.

RUNNER-1.5F-A adds conservative Claude quota detection and a WAITING_QUOTA
item state, plus an explicit, governed fresh-requeue primitive
(`resume_waiting_quota`) with exactly one operator resolution (WAITING_
QUOTA -> QUEUED). A completed attempt maps to WAITING_QUOTA only when
trustworthy post-invocation Runner evidence (never Work Order text, never
successful Claude answer content) conservatively confirms a Claude
provider usage/quota failure AND the attempt is otherwise safe to leave
without checkpoint reconciliation (read-only, or write mode with verified
repository_mutated=false). FAILED_SAFETY and BLOCKED_ON_CHECKPOINT always
take precedence over a quota classification. WAITING_QUOTA has no
automatic resume, sleep, timer, reset-time parsing, polling or scheduler
in 1.5F-A (that belongs to a later, separate Work Order); resuming a
WAITING_QUOTA item is always an explicit, governed, human-invoked action
that never itself invokes Claude, and the following run_next always
creates a brand-new attempt_id (a fresh Claude invocation), never a
--resume/--continue/session-reuse of the prior attempt.

RUNNER-1.5F-B1 extends the already-trusted quota signal (never any new
text/prompt/answer source) with optional durable provider reset metadata: it
parses the epoch that follows the exact `Claude AI usage limit reached|
<epoch>` signal only after that signal has already matched, converts it
deterministically to a timezone-aware UTC ISO-8601 string using only the
standard library, and persists both the raw epoch and the converted retry-
not-before instant on the WAITING_QUOTA attempt only. When the signal
matches but the epoch cannot be safely represented as a UTC datetime, the
classification remains CONFIRMED_QUOTA but no retry timestamp is persisted,
leaving the item manual-resume-only - never a guessed time zone, duration or
provider policy. RUNNER-1.5F-B1 also adds a pure, side-effect-free predicate,
`is_waiting_quota_due()`, for a later supervisor to consult: it performs no
mutation, locking, Git call or sleep, and fails closed (False) for any old
item without trusted reset metadata, any non-quota/ambiguous latest attempt,
or a malformed/naive timestamp. RUNNER-1.5F-B1 does NOT add automatic
resume, polling, a supervisor loop, grace periods, retry counts or backoff -
those remain out of scope for a later, separate Work Order; the manual
`resume_waiting_quota` primitive above continues to work exactly as before,
regardless of whether the persisted retry-not-before instant is in the past
or the future, because resuming is always an explicit operator action.

RUNNER-1.5F-B2A adds `supervisor_once()`, a single governed dispatch cycle
built entirely on top of the existing durable state and the existing
`run_next()`/`resume_waiting_quota()` governance - it never duplicates
Claude execution logic and never invokes the executor more than once per
call. Its policy, in order: an orphaned RUNNING item defers to `run_next()`'s
own orphan-recovery path (no dispatch); any BLOCKED_ON_CHECKPOINT item stops
with an operator-required outcome (no dispatch); any WAITING_QUOTA item acts
as a global barrier for this single-provider queue - a barrier item without
trusted RUNNER-1.5F-B1 reset metadata (or otherwise ambiguous) stops with a
manual/operator-required outcome, a barrier that is not yet fully due
returns a compact deterministic `next_wake_utc` without sleeping or
mutating, and a barrier where every item is due auto-requeues at most one
deterministic item (governed by the same integrity/checkpoint/Git-
cleanliness checks as `resume_waiting_quota`, re-validated fresh under the
lock immediately before mutation) via a distinct, machine-generated,
auditable `AUTO_RESUME_WAITING_QUOTA:WAITING_QUOTA->QUEUED` event - never a
human-authored note - before performing at most one ordinary `run_next()`
dispatch. With no barriers present, it delegates directly to `run_next()`.
`supervisor_once()` never sleeps, never polls and is not itself a loop -
looping/daemonization is out of scope for this Work Order.

RUNNER-1.5F-B2A-FIX1 hardens `supervisor_once()` against a TOCTOU window
that previously existed between its global policy observation
(`list_items()`) and its authoritative dispatch: `run_next()`'s execution
body is now factored into a private lock-held primitive,
`_run_next_locked()`, and quota auto-resume into
`_auto_resume_one_waiting_quota_item_locked()` - both require an already,
actively held `QueueLock` for the exact queue root (fail closed via
`_require_held_lock()` otherwise) and never acquire or release a lock
themselves. `supervisor_once()` now acquires exactly ONE authoritative
`QueueLock` before its first `list_items()` observation and holds that same
lock continuously through policy evaluation and, when applicable, orphan
recovery, quota auto-resume, fresh attempt creation, executor invocation
and final attempt persistence, releasing only in `finally`. There is no
unlock gap between an all-due quota auto-resume and the subsequent
dispatch. `run_next()` and `_auto_resume_one_waiting_quota_item()` remain
backward-compatible: each acquires exactly one `QueueLock`, delegates to
its lock-held primitive, and releases in `finally` - identical externally
observable behavior to before this hardening.

RUNNER-1.5F-B2B adds `run_supervisor_loop()`, a foreground, single-worker,
governed supervisor loop built entirely as a thin orchestration layer over
`supervisor_once()` - it never duplicates queue policy or Claude execution
logic and never invokes the Claude executor more than once per underlying
`supervisor_once()` call. Per cycle it calls `supervisor_once()` exactly
once: NO_WORK terminates immediately (a preloaded queue is drained, never
polled for future work); OPERATOR_REQUIRED, RECOVERY_REQUIRED and
SAFETY_STOP terminate immediately with no automatic retry, because human
intervention is required; DISPATCHED begins another cycle immediately,
subject to the optional positive `max_cycles`/`max_runtime_seconds` safety
bounds, so a preloaded durable queue can process many Work Orders
sequentially over hours; WAITING_QUOTA is the only outcome that may cause
sleeping, and only when `supervisor_once()`'s `next_wake_utc` is itself
independently re-validated (never a guessed duration, grace period or text
scan) as a well-formed, timezone-aware UTC instant - an already-due instant
causes no positive sleep, and a malformed/naive/unusable one stops
fail-closed (SAFETY_STOP) instead of guessing. RUNNER-1.5F-B2B-FIX1 closes a
runtime-budget boundary gap: when a positive `max_runtime_seconds` is
configured and the trusted quota delay is positive, the authoritative
remaining budget is recomputed from the injected `monotonic_clock`
immediately before sleeping; if that remaining budget is already exhausted,
or the quota delay is greater than or equal to it, the loop terminates
immediately with `LIMIT_REACHED`/`MAX_RUNTIME_REACHED` without ever calling
`sleeper` and without mutating durable queue state, carrying the triggering
`WAITING_QUOTA` result and its re-validated `next_wake_utc` as evidence. The
sleep delay is never truncated to fit the remaining budget - reaching the
configured runtime without being able to complete the next governed cycle
provides no useful automatic progress, so a deterministic `LIMIT_REACHED` is
returned instead. Only when the quota delay is strictly less than the
remaining budget (or `max_runtime_seconds` is `None`) does `sleeper` run for
the full trusted delay. Reaching a configured bound never itself mutates
durable queue state - it leaves remaining items untouched for a later, fresh
supervisor invocation, and is reported through a distinct `LIMIT_REACHED`
outcome. The wall clock (`clock`), the monotonic
runtime clock (`monotonic_clock`), the `sleeper` and even `supervisor`
itself are dependency-injectable, mirroring `executor`, so tests never
really wait and never depend on real Claude/Git; the production defaults
use only the Python standard library (`datetime`, `time`) and the real
`supervisor_once()`. A `KeyboardInterrupt` raised by the injected `sleeper`
during a quota wait terminates the loop cleanly with `INTERRUPTED` and
mutates nothing; a `KeyboardInterrupt` occurring during `supervisor_once()`
itself (i.e. during actual Runner execution) is never caught here, because
existing orphan-recovery/checkpoint fail-closed semantics remain the correct
recovery mechanism for that case, not an automatic retry. RUNNER-1.5F-B2B
does not daemonize, detach, create services, spawn workers or add any
platform-specific process manager - it is a foreground loop suitable to be
left running in a terminal.

RUNNER-1.5E-FIX1 hardens checkpoint capture/reconciliation after a real
operational incident: an operator's explicit FAIL reconciliation of a
BLOCKED_ON_CHECKPOINT item whose checkpoint had a missing blob previously
raised CHECKPOINT_INTEGRITY_FAILED and left the item permanently stuck,
because `reconcile_checkpoint` validated the attached checkpoint's full
structural/content integrity unconditionally, before branching on the
operator's resolution - so even a terminal FAIL/reject decision, which
never trusts or applies checkpoint content, was blocked by the very
corruption it was meant to reject. `reconcile_checkpoint` now still fails
ACCEPT and RETRY closed with CHECKPOINT_INTEGRITY_FAILED on any missing/
unreadable blob, hash mismatch or durable-record mismatch (unchanged), but
FAIL is now permitted to terminally reject a corrupted checkpoint
(BLOCKED_ON_CHECKPOINT -> FAILED), recording the integrity failure detail
on both the item history and the checkpoint's own durable record, and
never depending on or gating on the current target-repository state for
that specific path. RUNNER-1.5E-FIX1 additionally hardens the checkpoint
creation invariant: `_capture_new_checkpoint` now re-reads and re-
validates the just-published checkpoint directory from disk (the same
`_load_and_validate_checkpoint` reconciliation later uses) before ever
reporting status="CAPTURED", so an item can never enter BLOCKED_ON_CHECKPOINT
referencing a checkpoint that would immediately fail its own integrity
check; and blob validation now also verifies each entry's recorded byte
size, not only its SHA-256, before trusting a blob's contents. No cleanup/
pruning/garbage-collection of checkpoint blobs exists anywhere in this
module (confirmed by inspection), so no such code needed hardening against
removing blobs referenced by nonterminal items.

RUNNER-V2A-MULTIWORKER-CORE adds exactly one small, additive, behavior-
preserving hook for the separate `scripts/ai/claude_multiworker.py`
coordinator: `recover_single_running_item_locked()` factors the single-item
body out of `recover_orphaned_running_items()` (identical checkpoint-
governed recovery semantics, requires the caller's own already-held
`QueueLock`) so a caller with a more precise, liveness-aware orphan
determination than V1.5's blanket "any RUNNING item found while I hold the
lock is orphaned" rule (V2A's durable per-claim PID/host liveness check
across a coordinator restart) can reuse the exact same fail-closed
checkpoint recovery for one item at a time, instead of duplicating it.
`recover_orphaned_running_items()` itself is unchanged in every externally
observable way - it now simply calls this helper once per RUNNING item
found. Nothing else in this module changed for V2A: the single-worker
`run_next()`/`supervisor_once()`/`run_supervisor_loop()` lock-holds-through-
Claude-invocation contract this docstring describes throughout remains
exactly as implemented above, and the V2A coordinator never mutates
durable queue state through any path other than the already-governed
primitives this module exports (`start_attempt`, `finalize_attempt`,
`capture_or_reuse_checkpoint`, `recover_single_running_item_locked`, the
quota classifier/auto-resume primitives, `QueueLock`), reused exactly as
written, never reimplemented.

RUNNER-V2B-FIX0 fixes a checkpoint publication/integrity defect exposed by
V2A's first real concurrent write-mode dispatch: two independent items each
completed a successful Claude invocation, were correctly routed to
checkpoint capture, and each checkpoint's own self-check
(`_load_and_validate_checkpoint`, immediately after publish) then failed
with a referenced blob "missing/unreadable". The root cause was not
concurrency between two `_capture_new_checkpoint` calls (those already only
ever run serialized, one at a time, under the single exclusive `QueueLock`
held throughout capture) - it was that `resolve_queue_root`'s own default
convention nests this Runner's entire durable governance state (every
item's `queue/` metadata/checkpoints/blobs, claude_runner.py's own
RUNTIME_SUBDIR Claude evidence, and claude_multiworker.py's `.multiworker`
claim/lease sidecar) INSIDE the target repository's own working tree
whenever that target repository's Git configuration does not already
exclude "runtime/claude_runner" (an assumption this module's own test
fixtures already documented but never enforced in production code).
Checkpoint capture's `git diff --name-status`/`git ls-files --others`
snapshot then genuinely, correctly reports that governance state as part of
the target's "changes" - including paths this Runner's own concurrent
activity (another item's staging-directory publish rename, a multiworker
heartbeat rewrite, a sibling item's evidence write) is actively churning -
so a path git reports at snapshot time can legitimately vanish/relocate
before checkpoint capture ever reads it, producing exactly this failure
class. `_queue_governance_exclusion_prefixes` now computes, fresh per
capture, the repo-relative prefixes for that governance state (whether or
not it is actually nested inside the current target repository - empty,
and therefore a complete no-op, whenever it is not, which is every existing
test and the recommended deployment), and `_capture_new_checkpoint` filters
every git-reported tracked/untracked path - and scopes the recorded
`patch.diff` via `git diff`'s own `:(exclude)` pathspec magic - against it
before anything is read or hashed. This is deliberately never a recovery/
repair step and never silent in the sense of hiding a real defect: excluded
paths were never part of what a Work Order was ever authorized to mutate in
the first place (this module's own governance bookkeeping, and Claude's own
evidence/transcripts - which RUNNER-1.5E already promised a checkpoint would
never contain), and every exclusion is durably recorded, per capture, in the
manifest's `excluded_governance_paths` field for audit. All V1.5.1 fail-
closed invariants for a checkpoint that is genuinely corrupt (a real target-
repository path whose content changes between snapshot and read, a hash/
size mismatch, a truly missing blob) are completely unchanged - this fix
only narrows what a checkpoint may ever reference in the first place, never
loosens how a referenced entry is validated once captured.

RUNNER-V2B-FIX2 addresses what RUNNER-V2B-FIX0 left unsolved: a real
productive dual-target write-mode run, with `queue_root` deliberately placed
OUTSIDE both target repositories (the recommended deployment
`_queue_governance_exclusion_prefixes` already documents as "most common"),
still reached BLOCKED_ON_CHECKPOINT with a checkpoint reported FAILED
("missing/unreadable" blob) - the same failure *class* RUNNER-V2B-FIX0
already closes for `queue_root` nested inside a target. Re-reading
`_queue_governance_exclusion_prefixes` confirms its first candidate
(`<repo>/runtime/claude_runner`) is unconditional - independent of where
`queue_root` itself lives - so it already excludes claude_runner.py's own
target-local `RUNTIME_SUBDIR` evidence from checkpoint content in this exact
"external queue_root" topology too (a new regression test below makes this
explicit and closes the coverage gap that previously left it unverified).
The actual defect RUNNER-V2B-FIX0 left standing is architectural, not a hole
in that name-prefix filter: `claude_multiworker.py`'s coordinator never told
`claude_runner.execute_work_order()` where to put Claude execution evidence
(`WorkOrderRequest.run_root`), so V2's own Claude evidence always defaulted
target-local regardless of how deliberately external `queue_root` was placed
- silently reintroducing, inside every target repository V2 ever touches in
write mode, exactly the class of live, Runner-owned filesystem churn (an
evidence directory being created, written and renamed while checkpoint
capture's own several sequential, non-atomic `git` subprocess calls observe
that same working tree) that RUNNER-V2B-FIX0's exclusion-by-name-prefix can
only ever paper over, never eliminate, and that depends on that filter
staying exhaustively correct forever. RUNNER-V2B-FIX2 removes the coupling
instead: `claude_multiworker.py` now passes an explicit, deterministic,
coordinator-owned `run_root` - `_multiworker_evidence_root(queue_root)`, a
sibling of `queue_root` exactly like the existing `.multiworker` claims
sidecar, one durable sub-root per queue item - for every job it claims, so a
V2 write-mode run's Claude evidence is never part of any target repository's
own working tree at all in the recommended (external `queue_root`)
deployment; checkpoint capture for it then needs no governance-path
exclusion to stay clean, because there is nothing Runner-owned left in the
target tree to exclude. `_build_work_order_request()` gains an optional,
backward-compatible `run_root` keyword (default `None` preserves the exact
legacy target-local placement `run_next()`/`supervisor_once()` - V1.5's
still-single-worker, still-unchanged path - have always used).
`_resolve_verified_evidence_dir()` (and, through it,
`_verify_write_evidence_mutation()` and `classify_quota_default()`) gains a
matching optional `expected_run_root` so post-invocation evidence trust
verification recomputes the SAME base its own caller just told the Runner
to use, rather than assuming target-local unconditionally - both call sites
(`_run_next_locked()` and `claude_multiworker._finalize_claimed_job_locked()`)
now pass the exact `request.run_root` (`None` for V1.5, the externalized
sidecar path for V2) they themselves used to build the request, so this is
never a second, independently-guessable source of truth. `_queue_governance_
exclusion_prefixes()` additionally excludes this new evidence sidecar's
location as defense-in-depth (mirroring how it already excludes the
`.multiworker` claims sidecar), for the case where an operator's `queue_root`
happens to place it inside a target repository after all. Standalone
`claude_runner.py` (direct CLI invocation, never through the queue) is
completely unaffected: it has no `_build_work_order_request()` call in its
path at all.

RUNNER-V2B-FIX4 fixes a real Windows checkpoint defect proven by direct
operator probe: a real Claude WRITE canary correctly mutated exactly
canary.txt, Runner reported SUCCESS, and checkpoint capture correctly wrote
manifest.json, patch.diff and a 41-byte blob whose SHA-256 the manifest,
the blob file and the canary file all agreed on - yet the checkpoint's own
immediate self-check (`_load_and_validate_checkpoint`) raised
FileNotFoundError reading that exact blob back. The operator probe
isolated the cause precisely: the blob's ordinary absolute path was 269
characters, `Path.read_bytes()` on that ordinary path failed, and the
identical physical file addressed through the Windows extended-length path
syntax (`\\\\?\\C:\\...`) read back successfully with the exact expected size
and hash. This is a Windows MAX_PATH (legacy 260-character) limit on
checkpoint storage's own deeply nested layout
(queue_root/<item_id>/checkpoints/<checkpoint_id>/blobs/<blob_filename>) -
never corruption, concurrency, publication visibility, evidence placement
or Git snapshot churn (all already addressed by earlier fixes above).
`_windows_long_path` converts an already-resolved absolute path into
Windows' extended-length syntax (local drive paths to `\\\\?\\C:\\...`, UNC
paths to `\\\\?\\UNC\\server\\share\\...`), is the identity function on
non-Windows platforms, and is idempotent for a path already carrying
either prefix; `_long_path_exists`/`_long_path_read_bytes`/
`_long_path_mkdir`/`_long_path_replace` apply it at every actual `os`-level
checkpoint filesystem syscall (`_atomic_write_bytes` - shared with every
other durable write in this module, so item metadata/work-order writes get
the identical safety net rather than a second, divergent implementation -
`_capture_new_checkpoint`'s directory creation and staging-to-published
publish rename, `_load_and_validate_checkpoint`'s manifest/patch/blob
reads, `capture_or_reuse_checkpoint`'s existing-checkpoint probe, and
`_rmtree_best_effort`'s staging cleanup). The extended-length form is
strictly an OS I/O transport detail: it is never persisted into a
manifest's `repository_path`, a checkpoint id, an item metadata field or
any other durable/logical filename, and every one of those durable values
remains byte-for-byte exactly as before this fix. Non-Windows platforms are
completely unaffected, since every helper above is the identity function
there.

Governance: docs/resolutions/20260912_resolucion_modelo_direccion_tecnica_y_
ejecucion_claude.md and CLAUDE.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

# claude_runner is imported by fully-qualified package path first so that
# `from scripts.ai import claude_queue` (tests, and any other module-style
# import) resolves it identically to `test_claude_runner.py`. Running this
# file directly as a script (`python scripts/ai/claude_queue.py ...`) has no
# `scripts` package on sys.path, so that import fails there; the fallback
# below is a plain sibling import, which works because Python always puts a
# directly-run script's own directory at the front of sys.path.
try:
    from scripts.ai import claude_runner
except ImportError:  # pragma: no cover - exercised only via direct-script execution
    _this_dir = Path(__file__).resolve().parent
    if str(_this_dir) not in sys.path:
        sys.path.insert(0, str(_this_dir))
    import claude_runner


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1
DEFAULT_QUEUE_SUBDIR = Path("runtime") / "claude_runner" / "queue"
ITEM_METADATA_FILENAME = "item.json"
WORK_ORDER_FILENAME = "work_order.txt"
LOCK_FILENAME = "queue.lock"
MAX_WORK_ORDER_CHARS = 200_000

# RUNNER-1.5E: durable checkpoint storage (never /tmp, never conversational).
CHECKPOINTS_SUBDIR_NAME = "checkpoints"
CHECKPOINT_MANIFEST_FILENAME = "manifest.json"
CHECKPOINT_PATCH_FILENAME = "patch.diff"
CHECKPOINT_BLOBS_DIRNAME = "blobs"
CHECKPOINT_SCHEMA_VERSION = 1
RECONCILE_RESOLUTIONS = ("ACCEPT", "FAIL", "RETRY")

# RUNNER-V2B-FIX0: the Runner's own durable governance state (the queue
# root's default location, and claude_runner.py's own RUNTIME_SUBDIR evidence
# root) shares one well-known parent, "runtime/claude_runner", inside the
# target repository whenever no explicit --queue-root override moves it
# elsewhere. Checkpoint capture must never treat that governance state as
# part of the target repository's own authorized mutation - see
# `_queue_governance_exclusion_prefixes` below.
_GOVERNANCE_ROOT_SUBDIR = DEFAULT_QUEUE_SUBDIR.parent
# Deterministic sidecar metadata root suffix claude_multiworker.py derives
# from a queue root (its own MULTIWORKER_META_SUFFIX); duplicated here as a
# literal (never imported - claude_multiworker.py imports claude_queue.py,
# not the reverse) so an explicit --queue-root override outside
# "runtime/claude_runner" is still excluded end-to-end.
_QUEUE_SIDECAR_META_SUFFIX = ".multiworker"
# RUNNER-V2B-FIX2: matching sidecar suffix for claude_multiworker.py's own
# externalized Claude-evidence root (its MULTIWORKER_EVIDENCE_SUFFIX),
# duplicated here for the identical reason as `_QUEUE_SIDECAR_META_SUFFIX`
# above - defense-in-depth in case that evidence sidecar ever ends up
# nested inside a target repository after all.
_QUEUE_EVIDENCE_SIDECAR_SUFFIX = ".evidence"


class QueueError(Exception):
    """Raised for queue validation/integrity failures with a known reason."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason
        self.message = message


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

class QueueState(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_QUOTA = "WAITING_QUOTA"
    BLOCKED_ON_CHECKPOINT = "BLOCKED_ON_CHECKPOINT"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    FAILED_SAFETY = "FAILED_SAFETY"


# Central, explicit transition table. Anything not listed here is illegal.
# WAITING_QUOTA and BLOCKED_ON_CHECKPOINT deliberately have NO outgoing
# transitions here: reconciling BLOCKED_ON_CHECKPOINT (`reconcile_checkpoint`,
# RUNNER-1.5E) and resuming WAITING_QUOTA (`resume_waiting_quota`,
# RUNNER-1.5F-A) are separate, explicit, governed primitives that bypass this
# generic table deliberately - the generic transition_item()/validate_
# transition() must keep refusing any outgoing move from either state.
# FAILED_SAFETY and SUCCEEDED and FAILED are terminal: no automatic retry.
_ALLOWED_TRANSITIONS = {
    QueueState.QUEUED: {QueueState.RUNNING},
    QueueState.RUNNING: {
        QueueState.WAITING_QUOTA,
        QueueState.BLOCKED_ON_CHECKPOINT,
        QueueState.SUCCEEDED,
        QueueState.FAILED,
        QueueState.FAILED_SAFETY,
    },
    QueueState.WAITING_QUOTA: set(),
    QueueState.BLOCKED_ON_CHECKPOINT: set(),
    QueueState.SUCCEEDED: set(),
    QueueState.FAILED: set(),
    QueueState.FAILED_SAFETY: set(),
}


def validate_transition(from_state: QueueState, to_state: QueueState) -> None:
    """Fails closed (raises QueueError) on any transition not explicitly
    allowed above, including no-op self-transitions and any attempt to
    move a terminal or manual-reconciliation-only state elsewhere."""
    allowed = _ALLOWED_TRANSITIONS.get(from_state, set())
    if to_state not in allowed:
        raise QueueError(
            "ILLEGAL_TRANSITION",
            f"Illegal queue state transition: {from_state.value} -> {to_state.value}",
        )


# ---------------------------------------------------------------------------
# Item metadata
# ---------------------------------------------------------------------------

@dataclass
class QueueEvent:
    event: str
    at_utc: str
    detail: Optional[str] = None


@dataclass
class QueueAttempt:
    """One durable execution attempt of a queue item (RUNNER-1.5D).

    Deliberately minimal: no conversational/session id and no Claude
    transcript or stdout/stderr copied here - only enough to reconcile a
    queue item with its Runner evidence directory.
    """

    attempt_id: str
    started_at_utc: str
    ended_at_utc: Optional[str]
    status: str  # "RUNNING" | "COMPLETED" | "EXCEPTION"
    runner_state: Optional[str]
    runner_exit_code: Optional[int]
    runner_run_id: Optional[str]
    runner_evidence_dir: Optional[str]
    final_queue_state: Optional[str]


@dataclass
class QueueItem:
    schema_version: int
    item_id: str
    created_at_utc: str
    updated_at_utc: str
    state: str
    repository_path: str
    mode: str
    authorize_path: list
    timeout_seconds: Optional[int]
    model: Optional[str]
    label: Optional[str]
    work_order_filename: str
    work_order_sha256: str
    history: list
    attempts: list
    # RUNNER-1.5E: append-only references to durable checkpoints (the full
    # payload lives under checkpoints/<checkpoint_id>/, never inline here).
    checkpoints: list = field(default_factory=list)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Windows long-path-safe filesystem I/O (RUNNER-V2B-FIX4)
# ---------------------------------------------------------------------------
#
# Checkpoint storage nests deeply (queue_root/<item_id>/checkpoints/
# <checkpoint_id>/blobs/<blob_filename>), and item_id/checkpoint_id are
# already long, deterministic identifiers, so a checkpoint's physical
# absolute path can exceed the traditional Windows MAX_PATH (260-character)
# limit even when nothing about the checkpoint is corrupt. A real Windows
# operator probe proved exactly this: an ordinary absolute blob path of 269
# characters raised FileNotFoundError from `Path.read_bytes()`, while the
# identical physical file addressed through the Windows extended-length
# path syntax (`\\?\C:\...`) read back successfully with the exact expected
# size and SHA-256. `_windows_long_path` below converts an already-resolved
# absolute path into that syntax (`\\?\C:\...` for a local drive path,
# `\\?\UNC\server\share\...` for a UNC path); it is the identity function on
# non-Windows platforms and idempotent for a path that already carries
# either extended-length prefix. This is purely an OS I/O transport detail:
# the extended-length form is never persisted into a manifest's
# `repository_path`, a checkpoint id, an item metadata field or any other
# durable/logical filename - only ever passed to the actual `os`-level
# filesystem call.
_WIN_EXTENDED_PREFIX = "\\\\?\\"
_WIN_EXTENDED_UNC_PREFIX = "\\\\?\\UNC\\"


def _is_windows_platform() -> bool:
    return platform.system() == "Windows"


def _windows_long_path(path: Path) -> str:
    """Returns a path string safe for Windows filesystem syscalls beyond
    MAX_PATH. Identity function (`str(path)`) on non-Windows platforms.
    Already-prefixed paths are returned unchanged (idempotent)."""
    raw = str(path)
    if not _is_windows_platform():
        return raw
    if raw.startswith(_WIN_EXTENDED_PREFIX):
        return raw
    if raw.startswith("\\\\"):
        # UNC: \\server\share\... -> \\?\UNC\server\share\...
        return _WIN_EXTENDED_UNC_PREFIX + raw[2:]
    return _WIN_EXTENDED_PREFIX + raw


def _long_path_exists(path: Path) -> bool:
    return os.path.exists(_windows_long_path(path))


def _long_path_read_bytes(path: Path) -> bytes:
    with open(_windows_long_path(path), "rb") as f:
        return f.read()


def _long_path_mkdir(path: Path, *, parents: bool = False, exist_ok: bool = False) -> None:
    target = _windows_long_path(path)
    if parents:
        os.makedirs(target, exist_ok=exist_ok)
        return
    try:
        os.mkdir(target)
    except FileExistsError:
        if not exist_ok:
            raise


def _long_path_replace(src: Path, dst: Path) -> None:
    os.replace(_windows_long_path(src), _windows_long_path(dst))


def _atomic_write_bytes(target: Path, data: bytes) -> None:
    """Writes `data` to `target` via a same-directory temporary file,
    flush+fsync, then os.replace, so a process killed mid-write can never
    leave a partially written file at `target`."""
    _long_path_mkdir(target.parent, parents=True, exist_ok=True)
    # Keep temporary filenames deliberately short. Queue/checkpoint paths
    # are already nested deeply on Windows; repeating the full target name
    # here can exceed legacy MAX_PATH even when the final artifact would fit.
    # `dir` is already long-path-safe here, so the name mkstemp returns is
    # too - no separate conversion needed for `tmp_name` below.
    fd, tmp_name = tempfile.mkstemp(
        dir=_windows_long_path(target.parent), prefix=".tmp-", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, _windows_long_path(target))
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _atomic_write_json(target: Path, payload: dict) -> None:
    data = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False).encode("utf-8")
    _atomic_write_bytes(target, data)


def _item_to_dict(item: QueueItem) -> dict:
    return asdict(item)


def _dict_to_item(payload: dict) -> QueueItem:
    return QueueItem(
        schema_version=payload["schema_version"],
        item_id=payload["item_id"],
        created_at_utc=payload["created_at_utc"],
        updated_at_utc=payload["updated_at_utc"],
        state=payload["state"],
        repository_path=payload["repository_path"],
        mode=payload["mode"],
        authorize_path=payload.get("authorize_path") or [],
        timeout_seconds=payload.get("timeout_seconds"),
        model=payload.get("model"),
        label=payload.get("label"),
        work_order_filename=payload["work_order_filename"],
        work_order_sha256=payload["work_order_sha256"],
        history=payload.get("history") or [],
        # schema-version-1 items predate the attempts list (RUNNER-1.5D); a
        # missing field means "no attempts recorded yet", never a corrupt item.
        attempts=payload.get("attempts") or [],
        # schema-version-1 items predate the checkpoints list (RUNNER-1.5E);
        # a missing field means "no checkpoints recorded yet", never corrupt.
        checkpoints=payload.get("checkpoints") or [],
    )


_REQUIRED_ITEM_FIELDS = (
    "schema_version",
    "item_id",
    "created_at_utc",
    "updated_at_utc",
    "state",
    "repository_path",
    "mode",
    "work_order_filename",
    "work_order_sha256",
)


# ---------------------------------------------------------------------------
# Queue root / item paths
# ---------------------------------------------------------------------------

def resolve_queue_root(repo: Path, queue_root_arg: Optional[str] = None) -> Path:
    """Default queue root is <repo>/runtime/claude_runner/queue; explicitly
    overrideable (tests and future callers) via `queue_root_arg`."""
    if queue_root_arg:
        return Path(queue_root_arg).resolve()
    return (repo / DEFAULT_QUEUE_SUBDIR).resolve()


def _validate_item_id(item_id: str) -> str:
    """Queue item ids are single safe path segments.

    Generated ids use timestamp_UUID, but load callers may supply ids
    obtained from durable state or operator input. Never allow an id to
    escape the queue root through path separators or traversal.
    """
    if not isinstance(item_id, str) or not item_id:
        raise QueueError("INVALID_ITEM_ID", "Queue item_id must be a non-empty string")
    if item_id in {".", ".."} or "/" in item_id or "\\" in item_id:
        raise QueueError("INVALID_ITEM_ID", f"Unsafe queue item_id: {item_id!r}")
    if not all(ch.isalnum() or ch in "._-" for ch in item_id):
        raise QueueError("INVALID_ITEM_ID", f"Unsafe queue item_id: {item_id!r}")
    return item_id


def _item_dir(queue_root: Path, item_id: str) -> Path:
    return queue_root / _validate_item_id(item_id)


def _item_metadata_path(queue_root: Path, item_id: str) -> Path:
    return _item_dir(queue_root, item_id) / ITEM_METADATA_FILENAME


# ---------------------------------------------------------------------------
# Enqueue
# ---------------------------------------------------------------------------

def validate_work_order_source(text: str) -> str:
    if text is None or not isinstance(text, str):
        raise QueueError("INVALID_WORK_ORDER", "Work Order source must be a UTF-8 text string")
    if not text.strip():
        raise QueueError("INVALID_WORK_ORDER", "Work Order source must not be empty")
    if len(text) > MAX_WORK_ORDER_CHARS:
        raise QueueError(
            "INVALID_WORK_ORDER",
            f"Work Order source exceeds {MAX_WORK_ORDER_CHARS} characters ({len(text)})",
        )
    return text


def generate_item_id() -> str:
    """Collision-resistant: UTC timestamp (sortable, diagnostic) plus a
    random UUID4 suffix (collision resistance), matching claude_runner.py's
    run-directory naming convention."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = uuid.uuid4().hex
    return f"{timestamp}_{suffix}"


def enqueue(
    queue_root: Path,
    *,
    work_order_text: str,
    repository_path: str,
    mode: str,
    authorize_path: Optional[list] = None,
    timeout_seconds: Optional[int] = None,
    model: Optional[str] = None,
    label: Optional[str] = None,
) -> QueueItem:
    """Validates the Work Order source, generates an item_id, publishes one
    durable item directory atomically (no half-created item ever visible at
    its final path), copies the Work Order in as work_order.txt, persists
    its SHA-256, and writes item.json with an initial QUEUED history event."""
    text = validate_work_order_source(work_order_text)
    work_order_bytes = text.encode("utf-8")
    work_order_sha256 = hashlib.sha256(work_order_bytes).hexdigest()

    item_id = generate_item_id()
    queue_root.mkdir(parents=True, exist_ok=True)
    final_dir = _item_dir(queue_root, item_id)

    # Publish via a temporary sibling directory + atomic rename, so a
    # concurrent reader never observes a partially populated item
    # directory at its final, well-known path.
    staging_dir = queue_root / f".{item_id}.staging-{uuid.uuid4().hex[:8]}"
    staging_dir.mkdir(parents=False, exist_ok=False)
    try:
        (staging_dir / WORK_ORDER_FILENAME).write_bytes(work_order_bytes)

        now = _now_iso()
        history = [asdict(QueueEvent(event="ENQUEUED", at_utc=now, detail=f"item_id={item_id}"))]
        item = QueueItem(
            schema_version=SCHEMA_VERSION,
            item_id=item_id,
            created_at_utc=now,
            updated_at_utc=now,
            state=QueueState.QUEUED.value,
            repository_path=str(repository_path),
            mode=mode,
            authorize_path=list(authorize_path) if authorize_path else [],
            timeout_seconds=timeout_seconds,
            model=model,
            label=label,
            work_order_filename=WORK_ORDER_FILENAME,
            work_order_sha256=work_order_sha256,
            history=history,
            attempts=[],
            checkpoints=[],
        )
        _atomic_write_json(staging_dir / ITEM_METADATA_FILENAME, _item_to_dict(item))

        os.replace(str(staging_dir), str(final_dir))
    except BaseException:
        if staging_dir.exists():
            _rmtree_best_effort(staging_dir)
        raise

    return item


def _rmtree_best_effort(path: Path) -> None:
    import shutil

    shutil.rmtree(_windows_long_path(path), ignore_errors=True)


# ---------------------------------------------------------------------------
# Load / list
# ---------------------------------------------------------------------------

def load_item(queue_root: Path, item_id: str) -> QueueItem:
    """Fails closed on malformed/corrupt JSON, missing required fields,
    missing durable Work Order file, hash mismatch, or item_id/path
    inconsistency."""
    item_dir = _item_dir(queue_root, item_id)
    metadata_path = item_dir / ITEM_METADATA_FILENAME
    if not metadata_path.exists():
        raise QueueError("MISSING_ITEM", f"Queue item metadata not found: {metadata_path}")

    try:
        raw = metadata_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as exc:
        raise QueueError("CORRUPT_METADATA", f"Queue item metadata unreadable: {exc}")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise QueueError("CORRUPT_METADATA", f"Queue item metadata is not valid JSON: {exc}")

    missing = [f for f in _REQUIRED_ITEM_FIELDS if f not in payload]
    if missing:
        raise QueueError(
            "SCHEMA_MISMATCH", f"Queue item metadata missing required field(s): {missing}"
        )

    if payload["item_id"] != item_id:
        raise QueueError(
            "ITEM_ID_MISMATCH",
            f"item_id in metadata ({payload['item_id']!r}) does not match "
            f"directory name ({item_id!r})",
        )

    if payload["schema_version"] != SCHEMA_VERSION:
        raise QueueError(
            "SCHEMA_MISMATCH",
            f"Unsupported schema_version {payload['schema_version']!r} "
            f"(expected {SCHEMA_VERSION})",
        )

    if payload["work_order_filename"] != WORK_ORDER_FILENAME:
        raise QueueError(
            "SCHEMA_MISMATCH",
            f"Unsupported work_order_filename {payload['work_order_filename']!r}; "
            f"expected canonical {WORK_ORDER_FILENAME!r}",
        )

    try:
        QueueState(payload["state"])
    except ValueError:
        raise QueueError("SCHEMA_MISMATCH", f"Unknown queue state: {payload['state']!r}")

    work_order_path = item_dir / payload["work_order_filename"]
    if not work_order_path.exists():
        raise QueueError(
            "MISSING_WORK_ORDER", f"Durable Work Order file not found: {work_order_path}"
        )

    actual_bytes = work_order_path.read_bytes()
    actual_hash = hashlib.sha256(actual_bytes).hexdigest()
    if actual_hash != payload["work_order_sha256"]:
        raise QueueError(
            "HASH_MISMATCH",
            f"Durable Work Order hash mismatch for {item_id}: "
            f"expected {payload['work_order_sha256']}, got {actual_hash}",
        )

    return _dict_to_item(payload)


def list_items(queue_root: Path) -> list:
    """Deterministic order: created_at_utc then item_id.

    Fail closed on every published item that cannot be validated. A corrupt
    item must never become silently invisible to status, recovery or a future
    worker, because that could make an unhealthy queue appear safe.
    Temporary/staging directories remain ignored because they are not
    published queue items.
    """
    if not queue_root.exists():
        return []
    items = []
    for entry in queue_root.iterdir():
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        items.append(load_item(queue_root, entry.name))
    items.sort(key=lambda it: (it.created_at_utc, it.item_id))
    return items


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------

def transition_item(
    queue_root: Path, item_id: str, to_state: QueueState, *, detail: Optional[str] = None
) -> QueueItem:
    """Validates the transition centrally (fail closed on illegal moves),
    appends an audit event, and persists item.json atomically."""
    item = load_item(queue_root, item_id)
    from_state = QueueState(item.state)
    validate_transition(from_state, to_state)

    now = _now_iso()
    item.state = to_state.value
    item.updated_at_utc = now
    item.history = list(item.history) + [
        asdict(
            QueueEvent(
                event=f"TRANSITION:{from_state.value}->{to_state.value}",
                at_utc=now,
                detail=detail,
            )
        )
    ]
    _atomic_write_json(_item_metadata_path(queue_root, item_id), _item_to_dict(item))
    return item


# ---------------------------------------------------------------------------
# Attempts (RUNNER-1.5D)
# ---------------------------------------------------------------------------

def generate_attempt_id() -> str:
    """Collision-resistant, matching generate_item_id()'s convention: a
    sortable UTC timestamp plus a random UUID4 suffix."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = uuid.uuid4().hex
    return f"attempt_{timestamp}_{suffix}"


def start_attempt(queue_root: Path, item_id: str, attempt: QueueAttempt) -> QueueItem:
    """Atomically transitions QUEUED->RUNNING and appends `attempt` (already
    status="RUNNING") to the item's durable attempts list in the same
    write, so the attempt is always visibly RUNNING in item.json before any
    executor is invoked, and the item is never RUNNING without a matching
    durable attempt record."""
    item = load_item(queue_root, item_id)
    from_state = QueueState(item.state)
    validate_transition(from_state, QueueState.RUNNING)

    now = _now_iso()
    item.state = QueueState.RUNNING.value
    item.updated_at_utc = now
    item.attempts = list(item.attempts) + [asdict(attempt)]
    item.history = list(item.history) + [
        asdict(
            QueueEvent(
                event=f"TRANSITION:{from_state.value}->{QueueState.RUNNING.value}",
                at_utc=now,
                detail=f"attempt_id={attempt.attempt_id}",
            )
        )
    ]
    _atomic_write_json(_item_metadata_path(queue_root, item_id), _item_to_dict(item))
    return item


def finalize_attempt(
    queue_root: Path,
    item_id: str,
    attempt_id: str,
    *,
    to_state: QueueState,
    status: str,
    ended_at_utc: str,
    runner_state: Optional[str],
    runner_exit_code: Optional[int],
    runner_run_id: Optional[str],
    runner_evidence_dir: Optional[str],
    detail: Optional[str] = None,
    checkpoint_record: Optional["CheckpointRecord"] = None,
    quota_record: Optional["QuotaClassificationResult"] = None,
) -> QueueItem:
    """Atomically transitions RUNNING->`to_state` and finalizes the matching
    attempt record in the same write, so item.json can never claim a
    terminal/manual-reconciliation queue state while its corresponding
    attempt still shows status="RUNNING".

    `checkpoint_record` (RUNNER-1.5E) is optional and backward-compatible:
    when provided (only ever for `to_state=BLOCKED_ON_CHECKPOINT`), its
    reference is appended to `item.checkpoints` and
    checkpoint_id/checkpoint_status/checkpoint_error are added to the
    finalized attempt dict in the same atomic write; when omitted, the
    attempt dict is shaped exactly as before RUNNER-1.5E.

    `quota_record` (RUNNER-1.5F-A, extended RUNNER-1.5F-B1) is likewise
    optional and backward-compatible: when provided (only ever for
    `to_state=WAITING_QUOTA`), compact quota audit fields (classification/
    reason_code/detected_at_utc/evidence_run_id/evidence_path/
    quota_reset_epoch/quota_retry_not_before_utc - never Claude transcript/
    output) are added to the finalized attempt dict; when omitted, the
    attempt dict carries no quota fields at all, exactly as before
    RUNNER-1.5F-A. `quota_reset_epoch`/`quota_retry_not_before_utc` are
    always present as keys once a quota_record is provided, but their
    values are `None` whenever the epoch could not be safely converted to a
    representable UTC datetime, so the item remains manual-resume-only.
    """
    item = load_item(queue_root, item_id)
    from_state = QueueState(item.state)
    validate_transition(from_state, to_state)

    updated_attempts = []
    found = False
    for raw in item.attempts:
        if raw.get("attempt_id") == attempt_id:
            found = True
            raw = dict(raw)
            raw["ended_at_utc"] = ended_at_utc
            raw["status"] = status
            raw["runner_state"] = runner_state
            raw["runner_exit_code"] = runner_exit_code
            raw["runner_run_id"] = runner_run_id
            raw["runner_evidence_dir"] = runner_evidence_dir
            raw["final_queue_state"] = to_state.value
            if checkpoint_record is not None:
                raw["checkpoint_id"] = checkpoint_record.checkpoint_id
                raw["checkpoint_status"] = checkpoint_record.status
                raw["checkpoint_error"] = checkpoint_record.error
            if quota_record is not None:
                raw["quota_classification"] = quota_record.classification
                raw["quota_reason_code"] = quota_record.reason_code
                raw["quota_detected_at_utc"] = quota_record.detected_at_utc
                raw["quota_evidence_run_id"] = quota_record.evidence_run_id
                raw["quota_evidence_path"] = quota_record.evidence_path
                raw["quota_reset_epoch"] = quota_record.quota_reset_epoch
                raw["quota_retry_not_before_utc"] = quota_record.quota_retry_not_before_utc
        updated_attempts.append(raw)
    if not found:
        raise QueueError(
            "MISSING_ATTEMPT", f"Attempt {attempt_id!r} not found on item {item_id!r}"
        )

    now = _now_iso()
    item.attempts = updated_attempts
    if checkpoint_record is not None:
        item.checkpoints = list(item.checkpoints) + [asdict(checkpoint_record)]
    item.state = to_state.value
    item.updated_at_utc = now
    item.history = list(item.history) + [
        asdict(
            QueueEvent(
                event=f"TRANSITION:{from_state.value}->{to_state.value}",
                at_utc=now,
                detail=detail or f"attempt_id={attempt_id}",
            )
        )
    ]
    _atomic_write_json(_item_metadata_path(queue_root, item_id), _item_to_dict(item))
    return item


# ---------------------------------------------------------------------------
# Checkpoints (RUNNER-1.5E): durable repository snapshot capture
# ---------------------------------------------------------------------------
#
# A checkpoint is a durable, read-only snapshot of the target repository's
# state relative to HEAD, captured when a queue item reaches
# BLOCKED_ON_CHECKPOINT so a human can later inspect and reconcile exactly
# what happened, without depending on the live (possibly since-modified)
# working tree. Capture NEVER mutates the target repository: only
# read-only `git` subcommands (rev-parse, diff, ls-files, status) are ever
# invoked, always as explicit argv lists with shell=False, always via the
# standard library `subprocess` module. Claude and claude_runner are never
# invoked from this module.

class CheckpointCaptureError(Exception):
    """Internal, expected capture/validation failure (bad git output, path
    escaping the repository, unreadable/corrupt existing checkpoint, ...).
    Always caught by the capture entry point and turned into a FAILED
    CheckpointRecord rather than propagated, so a checkpoint failure alone
    never crashes run_next/orphan recovery."""


@dataclass
class CheckpointRecord:
    """Durable reference stored in item.json's `checkpoints` list. The full
    manifest/patch/blobs payload lives on disk under
    checkpoints/<checkpoint_id>/ inside the queue item directory; this
    record is deliberately small and carries no Claude stdout/stderr/
    transcript data."""

    checkpoint_id: str
    item_id: str
    attempt_id: Optional[str]
    captured_at_utc: str
    repository_path: str
    head: Optional[str]
    status: str  # "CAPTURED" | "FAILED"
    error: Optional[str]
    manifest_filename: Optional[str]
    manifest_sha256: Optional[str]
    patch_filename: Optional[str]
    patch_sha256: Optional[str]
    entry_count: Optional[int]
    resolved: bool = False
    resolution: Optional[str] = None
    resolved_at_utc: Optional[str] = None
    resolution_note: Optional[str] = None


def compute_checkpoint_id(item_id: str, attempt_id: Optional[str]) -> str:
    """Deterministic, collision-safe checkpoint identity derived from the
    item/attempt pair (or `item_id:legacy` for a pre-1.5D item with no
    attempt), so crash recovery and explicit capture-checkpoint can
    discover/reuse a previously published checkpoint instead of
    duplicating it."""
    basis = f"{item_id}:{attempt_id}" if attempt_id else f"{item_id}:legacy"
    digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()
    # 128 deterministic bits are ample for checkpoint identity while keeping
    # durable Windows paths comfortably below legacy path-length limits.
    return "cp_" + digest[:32]


def _blob_filename_for_digest(digest: str) -> str:
    """Return a compact deterministic blob filename.

    The manifest still stores and verifies the complete SHA-256.  The
    filename only needs to be a stable local locator; 128 digest bits keep
    paths short while collision checks below fail closed.
    """
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(ch not in "0123456789abcdef" for ch in digest)
    ):
        raise CheckpointCaptureError(f"invalid SHA-256 digest for blob: {digest!r}")
    return f"b_{digest[:32]}.blob"


def _checkpoints_root(queue_root: Path, item_id: str) -> Path:
    return _item_dir(queue_root, item_id) / CHECKPOINTS_SUBDIR_NAME


def _run_git(repo: Path, args: list, *, binary: bool = False) -> subprocess.CompletedProcess:
    cmd = ["git", "-C", str(repo)] + list(args)
    if binary:
        return subprocess.run(cmd, shell=False, capture_output=True)
    return subprocess.run(
        cmd, shell=False, capture_output=True, text=True,
        encoding="utf-8", errors="surrogateescape",
    )


def _git_is_worktree(repo: Path) -> bool:
    try:
        result = _run_git(repo, ["rev-parse", "--is-inside-work-tree"])
    except OSError as exc:
        raise CheckpointCaptureError(f"git executable unavailable: {exc}")
    return result.returncode == 0 and result.stdout.strip() == "true"


def _git_head(repo: Path) -> Optional[str]:
    result = _run_git(repo, ["rev-parse", "HEAD"])
    if result.returncode != 0:
        return None
    head = result.stdout.strip()
    return head or None


def _git_repository_is_clean(repo: Path) -> bool:
    result = _run_git(repo, ["status", "--porcelain=v1", "--untracked-files=all"])
    if result.returncode != 0:
        raise CheckpointCaptureError(f"git status failed: {result.stderr.strip()}")
    return result.stdout.strip() == ""


_NAME_STATUS_CHANGE_TYPES = {"A": "added", "M": "modified", "D": "deleted", "T": "type_changed"}


def _split_nul_terminated(raw: str) -> list:
    parts = raw.split("\0")
    if parts and parts[-1] == "":
        parts = parts[:-1]
    return parts


def _parse_name_status_z(raw: str) -> list:
    """Parses `git diff --name-status -z --no-renames HEAD --` output into
    `(status_code, path)` tuples. Fails closed on anything not A/M/D/T
    (including a rename/copy pair, which --no-renames should prevent but is
    still rejected defensively) and on malformed/truncated NUL framing."""
    parts = _split_nul_terminated(raw)
    entries = []
    i = 0
    while i < len(parts):
        status = parts[i]
        i += 1
        if not status:
            raise CheckpointCaptureError("malformed git diff --name-status output: empty status")
        code = status[0]
        if code not in _NAME_STATUS_CHANGE_TYPES:
            raise CheckpointCaptureError(f"unsupported/ambiguous git status code: {status!r}")
        if i >= len(parts):
            raise CheckpointCaptureError("malformed git diff --name-status output: missing path")
        path = parts[i]
        i += 1
        entries.append((code, path))
    return entries


def _git_tracked_changes(repo: Path) -> list:
    result = _run_git(repo, ["diff", "--name-status", "-z", "--no-renames", "HEAD", "--"])
    if result.returncode != 0:
        raise CheckpointCaptureError(f"git diff --name-status failed: {result.stderr.strip()}")
    return _parse_name_status_z(result.stdout)


def _git_untracked_files(repo: Path) -> list:
    result = _run_git(repo, ["ls-files", "--others", "--exclude-standard", "-z"])
    if result.returncode != 0:
        raise CheckpointCaptureError(f"git ls-files failed: {result.stderr.strip()}")
    return _split_nul_terminated(result.stdout)


def _git_binary_patch(repo: Path, *, exclude_prefixes: Optional[list] = None) -> bytes:
    args = ["diff", "--binary", "--full-index", "HEAD", "--", "."]
    for prefix in exclude_prefixes or []:
        args.append(f":(exclude){prefix}")
    result = _run_git(repo, args, binary=True)
    if result.returncode != 0:
        raise CheckpointCaptureError(
            f"git diff --binary failed: {result.stderr.decode('utf-8', 'replace').strip()}"
        )
    return result.stdout


def _validate_repo_relative_path(repo: Path, raw_path: str) -> Path:
    """Refuses path traversal and any path resolving outside the repository.
    The final path component is deliberately never resolved (only its
    parent directory chain is), so a symlink's target is recorded, not
    silently followed/dereferenced."""
    if not raw_path:
        raise CheckpointCaptureError("empty path in git output")
    normalized = raw_path.replace("\\", "/")
    if normalized.startswith("/"):
        raise CheckpointCaptureError(f"unexpected absolute path from git output: {raw_path!r}")
    segments = normalized.split("/")
    if any(seg in ("", ".", "..") for seg in segments):
        raise CheckpointCaptureError(f"unsafe path segment from git output: {raw_path!r}")

    repo_resolved = repo.resolve()
    full_path = repo_resolved.joinpath(*segments)
    try:
        parent_resolved = full_path.parent.resolve()
        parent_resolved.relative_to(repo_resolved)
    except (OSError, ValueError):
        raise CheckpointCaptureError(f"path escapes repository root: {raw_path!r}")
    return full_path


def _build_manifest_entry(repo: Path, raw_path: str, *, origin: str, change_type: str, blob_registry: dict) -> dict:
    full_path = _validate_repo_relative_path(repo, raw_path)
    normalized_path = raw_path.replace("\\", "/")
    entry = {
        "path": normalized_path,
        "origin": origin,
        "change_type": change_type,
        "exists": False,
        "is_symlink": False,
        "symlink_target": None,
        "size": None,
        "sha256": None,
        "blob_filename": None,
    }
    if change_type == "deleted":
        return entry

    if full_path.is_symlink():
        entry["exists"] = True
        entry["is_symlink"] = True
        entry["change_type"] = "symlink"
        target = os.readlink(full_path)
        entry["symlink_target"] = target
        target_bytes = target.encode("utf-8", errors="surrogateescape")
        entry["sha256"] = hashlib.sha256(target_bytes).hexdigest()
        entry["size"] = len(target_bytes)
        return entry

    if not full_path.exists():
        raise CheckpointCaptureError(f"path reported changed but missing on disk: {raw_path!r}")
    if not full_path.is_file():
        raise CheckpointCaptureError(
            f"unsupported path type (not a regular file or symlink): {raw_path!r}"
        )

    data = full_path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    entry["exists"] = True
    entry["size"] = len(data)
    entry["sha256"] = digest
    blob_filename = _blob_filename_for_digest(digest)
    entry["blob_filename"] = blob_filename
    blob_registry.setdefault(digest, data)
    return entry


def _resolved_relative_posix(base: Path, candidate: Path) -> Optional[str]:
    """Returns `candidate`'s path relative to `base` as a forward-slash
    string, or None when `candidate` does not resolve to a location under
    `base` (including `candidate == base` itself, which has no meaningful
    "under" prefix) or resolution fails. Never raises.

    Falls back to an `os.path.normcase`-based comparison (mirroring
    `claude_multiworker.canonical_target_key`'s existing Windows path-
    identity normalization) when the exact-string `Path.relative_to` misses
    a genuinely nested path only because the two `Path` objects were built
    with different casing on a case-insensitive filesystem (e.g. an
    operator-supplied --queue-root) - this may only ever widen a match to
    something genuinely on-disk-identical, never invent a false one."""
    try:
        resolved_base = base.resolve()
        resolved_candidate = candidate.resolve()
    except OSError:
        return None
    try:
        rel = resolved_candidate.relative_to(resolved_base)
    except ValueError:
        base_str = os.path.normcase(str(resolved_base))
        candidate_str = os.path.normcase(str(resolved_candidate))
        if candidate_str == base_str or not candidate_str.startswith(base_str + os.sep):
            return None
        rel = Path(str(resolved_candidate)[len(str(resolved_base)) + 1:])
    rel_posix = rel.as_posix()
    return None if rel_posix == "." else rel_posix


def _queue_governance_exclusion_prefixes(repo: Path, queue_root: Path) -> list:
    """Repo-relative, forward-slash path prefixes that are this Runner's own
    durable governance state - never the target repository's own authorized
    mutation - and therefore must never be captured into a checkpoint:

    * the well-known default governance parent, "runtime/claude_runner"
      (hosting both this queue's `queue/` subtree - every item's durable
      metadata, checkpoints, blobs, claims, lock file - and claude_runner.py's
      own RUNTIME_SUBDIR evidence root, "runtime/claude_runner/runs");
    * the actual `queue_root` in effect (covers an explicit --queue-root
      override that does not follow that default convention);
    * that queue root's deterministic multiworker sidecar metadata sibling
      (claude_multiworker.py's claim/lease directory);
    * that queue root's deterministic multiworker evidence sidecar sibling
      (RUNNER-V2B-FIX2: claude_multiworker.py's externalized Claude
      execution evidence root, `_multiworker_evidence_root()`).

    Returns an empty list whenever none of the above resolve to a location
    nested inside `repo` (the recommended - and most common non-default -
    deployment shape, where the queue lives entirely outside the target
    repository), in which case checkpoint capture behaves exactly as before
    this hardening. Computed fresh for every capture, never cached, and used
    ONLY to filter which git-reported paths a checkpoint may ever reference -
    never to delete, rename or otherwise touch anything on disk."""
    resolved_repo = repo.resolve()
    resolved_queue_root = Path(queue_root).resolve()
    candidates = [
        resolved_repo / _GOVERNANCE_ROOT_SUBDIR,
        resolved_queue_root,
        resolved_queue_root.parent / f"{resolved_queue_root.name}{_QUEUE_SIDECAR_META_SUFFIX}",
        resolved_queue_root.parent / f"{resolved_queue_root.name}{_QUEUE_EVIDENCE_SIDECAR_SUFFIX}",
    ]
    prefixes = []
    for candidate in candidates:
        rel = _resolved_relative_posix(resolved_repo, candidate)
        if rel is not None and rel not in prefixes:
            prefixes.append(rel)
    return prefixes


def _is_queue_governance_path(raw_path: str, exclusion_prefixes: list) -> bool:
    if not exclusion_prefixes:
        return False
    normalized = raw_path.replace("\\", "/")
    for prefix in exclusion_prefixes:
        if normalized == prefix or normalized.startswith(prefix + "/"):
            return True
    return False


def _capture_new_checkpoint(
    checkpoints_root: Path, checkpoint_id: str, item: QueueItem, attempt_id: Optional[str],
    queue_root: Path,
) -> CheckpointRecord:
    repo_arg = Path(item.repository_path)
    if not repo_arg.exists() or not repo_arg.is_dir():
        raise CheckpointCaptureError(f"repository path does not exist: {repo_arg}")
    if not _git_is_worktree(repo_arg):
        raise CheckpointCaptureError(f"repository path is not a git work tree: {repo_arg}")
    repo = repo_arg.resolve()

    # RUNNER-V2B-FIX0: exclude this Runner's own governance state (queue
    # metadata, checkpoints/blobs, multiworker claims, Claude evidence/
    # transcripts) from what a checkpoint may ever observe as "the target
    # repository's changes" - see `_queue_governance_exclusion_prefixes`.
    # This is never a recovery/repair step: it is scoping the checkpoint to
    # what the Work Order was ever authorized to mutate in the first place,
    # applied before any git-reported path is read/hashed.
    exclusion_prefixes = _queue_governance_exclusion_prefixes(repo, queue_root)

    head = _git_head(repo)
    tracked_changes_raw = _git_tracked_changes(repo)
    untracked_files_raw = _git_untracked_files(repo)
    patch_bytes = _git_binary_patch(repo, exclude_prefixes=exclusion_prefixes)

    excluded_governance_paths = []
    tracked_changes = []
    for code, raw_path in tracked_changes_raw:
        if _is_queue_governance_path(raw_path, exclusion_prefixes):
            excluded_governance_paths.append(raw_path.replace("\\", "/"))
            continue
        tracked_changes.append((code, raw_path))

    untracked_files = []
    for raw_path in untracked_files_raw:
        if _is_queue_governance_path(raw_path, exclusion_prefixes):
            excluded_governance_paths.append(raw_path.replace("\\", "/"))
            continue
        untracked_files.append(raw_path)
    excluded_governance_paths.sort()

    _long_path_mkdir(checkpoints_root, parents=True, exist_ok=True)
    # Staging is a private sibling and does not need to repeat checkpoint_id.
    # Keep it short for Windows path safety; publication renames it atomically
    # to the deterministic final checkpoint directory.
    staging_dir = checkpoints_root / f".tmp-{uuid.uuid4().hex[:12]}"
    _long_path_mkdir(staging_dir, parents=False, exist_ok=False)
    try:
        blob_registry: dict = {}
        entries = []
        seen_paths = set()

        for code, raw_path in tracked_changes:
            entry = _build_manifest_entry(
                repo, raw_path, origin="tracked",
                change_type=_NAME_STATUS_CHANGE_TYPES[code], blob_registry=blob_registry,
            )
            if entry["path"] in seen_paths:
                raise CheckpointCaptureError(f"duplicate changed path reported by git: {entry['path']!r}")
            seen_paths.add(entry["path"])
            entries.append(entry)

        for raw_path in untracked_files:
            entry = _build_manifest_entry(
                repo, raw_path, origin="untracked", change_type="added", blob_registry=blob_registry,
            )
            if entry["path"] in seen_paths:
                raise CheckpointCaptureError(
                    f"duplicate path reported by git (tracked+untracked): {entry['path']!r}"
                )
            seen_paths.add(entry["path"])
            entries.append(entry)

        entries.sort(key=lambda e: e["path"])

        if blob_registry:
            blobs_dir = staging_dir / CHECKPOINT_BLOBS_DIRNAME
            _long_path_mkdir(blobs_dir, parents=True, exist_ok=True)
            blob_name_to_digest = {}
            for digest, data in sorted(blob_registry.items()):
                blob_filename = _blob_filename_for_digest(digest)
                previous_digest = blob_name_to_digest.get(blob_filename)
                if previous_digest is not None and previous_digest != digest:
                    raise CheckpointCaptureError(
                        "compact blob filename collision between distinct SHA-256 digests"
                    )
                blob_name_to_digest[blob_filename] = digest
                _atomic_write_bytes(blobs_dir / blob_filename, data)

        patch_sha256 = hashlib.sha256(patch_bytes).hexdigest()
        _atomic_write_bytes(staging_dir / CHECKPOINT_PATCH_FILENAME, patch_bytes)

        captured_at_utc = _now_iso()
        manifest_payload = {
            "checkpoint_schema_version": CHECKPOINT_SCHEMA_VERSION,
            "checkpoint_id": checkpoint_id,
            "item_id": item.item_id,
            "attempt_id": attempt_id,
            "captured_at_utc": captured_at_utc,
            "repository_path": str(repo),
            "head": head,
            "patch_filename": CHECKPOINT_PATCH_FILENAME,
            "patch_sha256": patch_sha256,
            "entries": entries,
            # RUNNER-V2B-FIX0: audit-only record of git-reported paths that
            # were excluded as this Runner's own governance state (never
            # part of checkpoint content/integrity - absent or empty on a
            # deployment where queue_root/runtime/claude_runner lives
            # outside the target repository).
            "excluded_governance_paths": excluded_governance_paths,
        }
        manifest_bytes = json.dumps(
            manifest_payload, indent=2, ensure_ascii=False, sort_keys=False
        ).encode("utf-8")
        manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
        _atomic_write_bytes(staging_dir / CHECKPOINT_MANIFEST_FILENAME, manifest_bytes)

        published_dir = checkpoints_root / checkpoint_id
        _long_path_replace(staging_dir, published_dir)
    except BaseException:
        _rmtree_best_effort(staging_dir)
        raise

    # RUNNER-1.5E-FIX1 capture-time invariant: a checkpoint may never be
    # reported CAPTURED (and therefore never let its item enter
    # BLOCKED_ON_CHECKPOINT) unless it independently passes the exact same
    # structural/content-integrity validation later used by reconciliation.
    # This re-reads the just-published directory from disk (not the
    # in-memory data just written) so any gap between "written" and
    # "durably readable back" is caught immediately, at capture time,
    # rather than surfacing later as an unrecoverable surprise during
    # reconciliation. `published_dir` is deliberately left on disk for
    # forensics if this ever fails - it is never deleted or "repaired" -
    # and capture_or_reuse_checkpoint's caller converts the resulting
    # CheckpointCaptureError into a FAILED (not CAPTURED) CheckpointRecord.
    self_check = _load_and_validate_checkpoint(
        published_dir, item.item_id, attempt_id, str(repo)
    )
    if self_check.manifest_sha256 != manifest_sha256 or self_check.patch_sha256 != patch_sha256:
        raise CheckpointCaptureError(
            "freshly published checkpoint failed self-validation "
            "(manifest/patch hash mismatch immediately after publish)"
        )

    return CheckpointRecord(
        checkpoint_id=checkpoint_id, item_id=item.item_id, attempt_id=attempt_id,
        captured_at_utc=captured_at_utc, repository_path=str(repo), head=head,
        status="CAPTURED", error=None,
        manifest_filename=CHECKPOINT_MANIFEST_FILENAME, manifest_sha256=manifest_sha256,
        patch_filename=CHECKPOINT_PATCH_FILENAME, patch_sha256=patch_sha256,
        entry_count=len(entries),
    )


def _load_and_validate_checkpoint(
    published_dir: Path, item_id: str, attempt_id: Optional[str], repository_path: str
) -> CheckpointRecord:
    """Validates a previously published checkpoint directory (manifest
    identity, patch hash, every blob hash) before it may be reused or
    reconciled. Fails closed (raises CheckpointCaptureError) on any
    corruption or identity mismatch; never mutates or deletes anything."""
    manifest_path = published_dir / CHECKPOINT_MANIFEST_FILENAME
    patch_path = published_dir / CHECKPOINT_PATCH_FILENAME
    if not _long_path_exists(manifest_path) or not _long_path_exists(patch_path):
        raise CheckpointCaptureError(
            f"existing checkpoint directory missing manifest/patch: {published_dir}"
        )

    try:
        manifest_raw = _long_path_read_bytes(manifest_path)
        manifest_payload = json.loads(manifest_raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CheckpointCaptureError(f"existing checkpoint manifest corrupt: {exc}")

    if manifest_payload.get("checkpoint_schema_version") != CHECKPOINT_SCHEMA_VERSION:
        raise CheckpointCaptureError(
            "existing checkpoint manifest schema version mismatch"
        )

    if manifest_payload.get("checkpoint_id") != published_dir.name:
        raise CheckpointCaptureError("existing checkpoint_id mismatch with directory name")
    if manifest_payload.get("item_id") != item_id:
        raise CheckpointCaptureError("existing checkpoint item_id mismatch")
    if manifest_payload.get("attempt_id") != attempt_id:
        raise CheckpointCaptureError("existing checkpoint attempt_id mismatch")

    try:
        stored_repo = Path(manifest_payload.get("repository_path", "")).resolve()
        current_repo = Path(repository_path).resolve()
    except OSError as exc:
        raise CheckpointCaptureError(f"cannot resolve repository path for identity check: {exc}")
    if stored_repo != current_repo:
        raise CheckpointCaptureError("existing checkpoint repository identity mismatch")

    try:
        patch_bytes = _long_path_read_bytes(patch_path)
    except OSError as exc:
        raise CheckpointCaptureError(f"existing checkpoint patch unreadable: {exc}")
    if hashlib.sha256(patch_bytes).hexdigest() != manifest_payload.get("patch_sha256"):
        raise CheckpointCaptureError("existing checkpoint patch hash mismatch")

    entries = manifest_payload.get("entries")
    if not isinstance(entries, list):
        raise CheckpointCaptureError("existing checkpoint manifest entries missing/invalid")

    blobs_dir = published_dir / CHECKPOINT_BLOBS_DIRNAME
    for entry in entries:
        if not isinstance(entry, dict):
            raise CheckpointCaptureError("existing checkpoint manifest entry malformed")
        blob_filename = entry.get("blob_filename")
        if not blob_filename:
            continue

        entry_digest = entry.get("sha256")
        expected_blob_filename = _blob_filename_for_digest(entry_digest)
        if blob_filename != expected_blob_filename:
            raise CheckpointCaptureError(
                f"existing checkpoint blob filename is non-canonical: {blob_filename!r}"
            )

        blob_path = blobs_dir / blob_filename
        try:
            blob_bytes = _long_path_read_bytes(blob_path)
        except OSError as exc:
            raise CheckpointCaptureError(f"existing checkpoint blob missing/unreadable: {exc}")
        expected_size = entry.get("size")
        if not isinstance(expected_size, int) or expected_size != len(blob_bytes):
            raise CheckpointCaptureError(f"existing checkpoint blob size mismatch: {blob_filename}")
        if hashlib.sha256(blob_bytes).hexdigest() != entry_digest:
            raise CheckpointCaptureError(f"existing checkpoint blob hash mismatch: {blob_filename}")

    manifest_sha256 = hashlib.sha256(manifest_raw).hexdigest()
    return CheckpointRecord(
        checkpoint_id=published_dir.name, item_id=item_id, attempt_id=attempt_id,
        captured_at_utc=manifest_payload.get("captured_at_utc"),
        repository_path=manifest_payload.get("repository_path", repository_path),
        head=manifest_payload.get("head"), status="CAPTURED", error=None,
        manifest_filename=CHECKPOINT_MANIFEST_FILENAME, manifest_sha256=manifest_sha256,
        patch_filename=CHECKPOINT_PATCH_FILENAME, patch_sha256=manifest_payload.get("patch_sha256"),
        entry_count=len(entries),
    )


def capture_or_reuse_checkpoint(
    queue_root: Path, item: QueueItem, *, attempt_id: Optional[str]
) -> CheckpointRecord:
    """Captures a new durable checkpoint for `item`'s current repository
    state, or validates and reuses a previously published one with the same
    deterministic identity. Never raises for an expected capture/validation
    failure (git error, unreadable repository, path-safety violation,
    corrupt/inconsistent existing checkpoint): callers must be able to rely
    on always getting a CheckpointRecord back (status CAPTURED or FAILED)
    so run_next/orphan recovery can finalize BLOCKED_ON_CHECKPOINT without
    guessing or retrying."""
    checkpoint_id = compute_checkpoint_id(item.item_id, attempt_id)
    checkpoints_root = _checkpoints_root(queue_root, item.item_id)
    published_dir = checkpoints_root / checkpoint_id
    try:
        if _long_path_exists(published_dir):
            return _load_and_validate_checkpoint(
                published_dir, item.item_id, attempt_id, item.repository_path
            )
        return _capture_new_checkpoint(checkpoints_root, checkpoint_id, item, attempt_id, queue_root)
    except Exception as exc:  # noqa: BLE001 - deliberately fail-closed, never re-raised
        return CheckpointRecord(
            checkpoint_id=checkpoint_id, item_id=item.item_id, attempt_id=attempt_id,
            captured_at_utc=_now_iso(), repository_path=item.repository_path, head=None,
            status="FAILED", error=f"{type(exc).__name__}: {exc}",
            manifest_filename=None, manifest_sha256=None,
            patch_filename=None, patch_sha256=None, entry_count=None,
        )


def _find_latest_checkpoint_record(item: QueueItem, checkpoint_id: str) -> Optional[dict]:
    for raw in reversed(item.checkpoints):
        if isinstance(raw, dict) and raw.get("checkpoint_id") == checkpoint_id:
            return raw
    return None


def _latest_blocked_attempt(item: QueueItem) -> Optional[dict]:
    """Returns the most recent attempt dict finalized to BLOCKED_ON_CHECKPOINT,
    or None for a legacy item with no matching attempt (pre-1.5D item-level
    orphan recovery)."""
    for raw in reversed(item.attempts):
        if isinstance(raw, dict) and raw.get("final_queue_state") == QueueState.BLOCKED_ON_CHECKPOINT.value:
            return raw
    return None


# ---------------------------------------------------------------------------
# OS advisory exclusive lock
# ---------------------------------------------------------------------------

class QueueLockError(Exception):
    pass


class QueueLock:
    """Real OS advisory exclusive lock over one lock file inside the queue
    root, using fcntl.flock on POSIX and msvcrt.locking on Windows.
    PID/hostname/timestamps written into the file are diagnostic only -
    they are never consulted to decide whether the lock is held; only the
    OS lock call itself decides that. A second process cannot acquire this
    lock while the first holds it, and process death releases it through
    OS semantics (the OS releases file locks when the owning process exits
    or its file descriptor is closed, even on a crash)."""

    def __init__(self, queue_root: Path):
        self.queue_root = Path(queue_root).resolve()
        self.lock_path = self.queue_root / LOCK_FILENAME
        self._fh = None

    @property
    def is_held(self) -> bool:
        return self._fh is not None

    def acquire(self, blocking: bool = False) -> None:
        self.queue_root.mkdir(parents=True, exist_ok=True)
        # Never truncate an existing lock file (another process may be
        # about to lock it); only create it if it does not exist yet.
        if not self.lock_path.exists():
            with open(self.lock_path, "ab"):
                pass
        fh = open(self.lock_path, "r+b")
        try:
            # msvcrt.locking requires at least one byte to lock, and an
            # existing-but-empty lock file (e.g. left by a prior version,
            # or a process that created it but crashed before writing to
            # it) must not silently fail to lock. Guarantee >=1 byte here
            # rather than only at creation time.
            fh.seek(0, os.SEEK_END)
            if fh.tell() == 0:
                fh.write(b"\0")
                fh.flush()
                fh.seek(0)
            if platform.system() == "Windows":
                import msvcrt

                mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
                try:
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), mode, 1)
                except OSError as exc:
                    fh.close()
                    raise QueueLockError(f"Could not acquire queue lock: {exc}") from exc
            else:
                import fcntl

                flags = fcntl.LOCK_EX if blocking else (fcntl.LOCK_EX | fcntl.LOCK_NB)
                try:
                    fcntl.flock(fh.fileno(), flags)
                except OSError as exc:
                    fh.close()
                    raise QueueLockError(f"Could not acquire queue lock: {exc}") from exc
        except BaseException:
            fh.close()
            raise
        self._fh = fh
        try:
            self._fh.seek(0)
            self._fh.write(b"\0")
            diag = f"pid={os.getpid()} host={socket.gethostname()} at={_now_iso()}\n".encode(
                "utf-8"
            )
            self._fh.write(diag)
            self._fh.flush()
        except OSError:
            pass

    def release(self) -> None:
        if self._fh is None:
            return
        try:
            if platform.system() == "Windows":
                import msvcrt

                try:
                    self._fh.seek(0)
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl

                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        finally:
            self._fh.close()
            self._fh = None

    def __enter__(self) -> "QueueLock":
        self.acquire(blocking=False)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


def _require_held_lock(queue_root: Path, lock: QueueLock) -> None:
    """Fails closed (QueueLockError) unless `lock` is a QueueLock instance
    actively held for this exact resolved queue root (RUNNER-1.5F-B2A-
    FIX1). Shared by every lock-held primitive (`_run_next_locked`,
    `_auto_resume_one_waiting_quota_item_locked`) that must never itself
    acquire or release a lock, so a caller cannot bypass single-worker/
    single-supervisor exclusivity by passing an unheld lock or a lock
    belonging to a different queue root."""
    resolved_root = Path(queue_root).resolve()
    if not isinstance(lock, QueueLock) or not lock.is_held:
        raise QueueLockError(
            "This operation requires an actively held exclusive QueueLock"
        )
    if lock.queue_root != resolved_root:
        raise QueueLockError(
            "QueueLock belongs to a different queue root; operation refused"
        )


# ---------------------------------------------------------------------------
# Crash recovery (orphaned RUNNING items)
# ---------------------------------------------------------------------------

_DEFAULT_ORPHAN_RECOVERY_DETAIL = (
    "orphaned-RUNNING: item was RUNNING when the current process "
    "acquired the exclusive queue lock, indicating a previous "
    "owner did not reach a terminal state (crash or kill); "
    "recovered fail-closed rather than requeued/retried because "
    "a partial authorized repository change may exist"
)


def recover_single_running_item_locked(
    queue_root: Path, item: QueueItem, *, lock: QueueLock, detail: Optional[str] = None,
) -> QueueItem:
    """Finalizes exactly one already-loaded RUNNING `item` to
    BLOCKED_ON_CHECKPOINT (durable checkpoint capture, fail-closed, never an
    automatic retry) - the single-item body factored out of
    `recover_orphaned_running_items` (RUNNER-1.5E) so a caller with its own,
    more precise orphan/liveness determination (RUNNER-V2A multiworker: PID/
    host liveness against a durable worker claim, rather than V1.5's blanket
    "any RUNNING item found while I hold the lock is orphaned" assumption)
    can reuse the exact same checkpoint-governed recovery semantics for one
    item at a time instead of duplicating them. Requires the caller's own
    already-held `QueueLock` for this exact queue root (`_require_held_lock`
    fails closed otherwise) and never itself acquires/releases a lock.
    `recover_orphaned_running_items` is unchanged behaviorally: it now calls
    this helper once per RUNNING item found, with the same default detail
    text as before this refactor."""
    _require_held_lock(queue_root, lock)
    if QueueState(item.state) != QueueState.RUNNING:
        raise QueueError(
            "INVALID_STATE_FOR_ORPHAN_RECOVERY",
            f"Item {item.item_id!r} is not RUNNING (state={item.state})",
        )

    recovery_detail = detail or _DEFAULT_ORPHAN_RECOVERY_DETAIL

    # Pre-1.5D schema-v1 items may legitimately have no attempt record.
    # Preserve that backward-compatible recovery path, capturing a
    # deterministic item-level "legacy" checkpoint (RUNNER-1.5E) before the
    # item is finalized blocked.
    if not item.attempts:
        checkpoint_record = capture_or_reuse_checkpoint(queue_root, item, attempt_id=None)
        return _transition_item_with_checkpoint(
            queue_root,
            item.item_id,
            QueueState.BLOCKED_ON_CHECKPOINT,
            checkpoint_record,
            detail=_with_checkpoint_note(recovery_detail, checkpoint_record),
        )

    # RUNNER-1.5D+: a crashed worker may leave exactly one active RUNNING
    # attempt. Recovery must finalize that same attempt atomically with
    # RUNNING -> BLOCKED_ON_CHECKPOINT; otherwise durable state would claim
    # the item is blocked while its corresponding attempt remains RUNNING.
    running_attempts = [
        raw for raw in item.attempts
        if isinstance(raw, dict) and raw.get("status") == "RUNNING"
    ]
    if len(running_attempts) != 1:
        raise QueueError(
            "CORRUPT_ATTEMPT",
            f"RUNNING item {item.item_id!r} has {len(running_attempts)} "
            "RUNNING attempts; orphan recovery refused fail-closed",
        )

    attempt_id = running_attempts[0].get("attempt_id")
    if not isinstance(attempt_id, str) or not attempt_id:
        raise QueueError(
            "CORRUPT_ATTEMPT",
            f"RUNNING item {item.item_id!r} has an invalid active attempt_id",
        )

    checkpoint_record = capture_or_reuse_checkpoint(queue_root, item, attempt_id=attempt_id)
    return finalize_attempt(
        queue_root,
        item.item_id,
        attempt_id,
        to_state=QueueState.BLOCKED_ON_CHECKPOINT,
        status="ORPHANED",
        ended_at_utc=_now_iso(),
        runner_state=None,
        runner_exit_code=None,
        runner_run_id=None,
        runner_evidence_dir=None,
        detail=_with_checkpoint_note(recovery_detail, checkpoint_record),
        checkpoint_record=checkpoint_record,
    )


def recover_orphaned_running_items(
    queue_root: Path, *, lock: QueueLock
) -> list:
    """Recover orphaned RUNNING items only under the real exclusive OS lock.

    The caller must pass the QueueLock instance that it currently owns for
    this exact queue root. This makes the single-worker recovery precondition
    executable rather than a docstring-only convention.
    """
    resolved_root = Path(queue_root).resolve()
    if not isinstance(lock, QueueLock) or not lock.is_held:
        raise QueueLockError(
            "Orphan recovery requires an actively held exclusive QueueLock"
        )
    if lock.queue_root != resolved_root:
        raise QueueLockError(
            "QueueLock belongs to a different queue root; orphan recovery refused"
        )

    recovered = []
    for item in list_items(queue_root):
        if QueueState(item.state) != QueueState.RUNNING:
            continue
        recovered_item = recover_single_running_item_locked(queue_root, item, lock=lock)
        recovered.append(recovered_item)

    return recovered


def _with_checkpoint_note(detail: str, checkpoint_record: "CheckpointRecord") -> str:
    note = f"checkpoint_id={checkpoint_record.checkpoint_id} checkpoint_status={checkpoint_record.status}"
    if checkpoint_record.error:
        note += f" checkpoint_error={checkpoint_record.error}"
    return f"{detail}; {note}"


def _transition_item_with_checkpoint(
    queue_root: Path,
    item_id: str,
    to_state: QueueState,
    checkpoint_record: "CheckpointRecord",
    *,
    detail: Optional[str] = None,
) -> QueueItem:
    """Like `transition_item`, but atomically appends `checkpoint_record` to
    `item.checkpoints` in the same write - used for item-level (attempt-less)
    checkpoint-bearing transitions (RUNNER-1.5E legacy orphan recovery)."""
    item = load_item(queue_root, item_id)
    from_state = QueueState(item.state)
    validate_transition(from_state, to_state)

    now = _now_iso()
    item.state = to_state.value
    item.updated_at_utc = now
    item.checkpoints = list(item.checkpoints) + [asdict(checkpoint_record)]
    item.history = list(item.history) + [
        asdict(
            QueueEvent(
                event=f"TRANSITION:{from_state.value}->{to_state.value}",
                at_utc=now,
                detail=detail,
            )
        )
    ]
    _atomic_write_json(_item_metadata_path(queue_root, item_id), _item_to_dict(item))
    return item


# ---------------------------------------------------------------------------
# Explicit retryable checkpoint capture (RUNNER-1.5E)
# ---------------------------------------------------------------------------

def capture_checkpoint_for_item(
    queue_root: Path, item_id: str, *, wait_for_lock: bool = False
) -> QueueItem:
    """Governed, explicitly-invoked primitive to (re)capture the durable
    checkpoint for an item that is currently BLOCKED_ON_CHECKPOINT and whose
    earlier checkpoint capture failed (or to confirm/reuse an already-good
    one). Acquires the exclusive QueueLock, validates queue/item state,
    captures the current repository state without modifying it, and
    atomically attaches the resulting CheckpointRecord. Never invokes
    Claude or claude_runner. Raises QueueError (fail-closed, non-retrying)
    if the capture itself still fails, after durably recording that
    failure for audit."""
    lock = QueueLock(queue_root)
    lock.acquire(blocking=wait_for_lock)
    try:
        item = load_item(queue_root, item_id)
        if QueueState(item.state) != QueueState.BLOCKED_ON_CHECKPOINT:
            raise QueueError(
                "INVALID_STATE_FOR_CHECKPOINT_CAPTURE",
                f"Item {item_id!r} is not BLOCKED_ON_CHECKPOINT (state={item.state})",
            )

        blocked_attempt = _latest_blocked_attempt(item)
        attempt_id = blocked_attempt.get("attempt_id") if blocked_attempt else None

        checkpoint_record = capture_or_reuse_checkpoint(queue_root, item, attempt_id=attempt_id)

        now = _now_iso()
        item.checkpoints = list(item.checkpoints) + [asdict(checkpoint_record)]
        item.updated_at_utc = now
        event = "CHECKPOINT_CAPTURE" if checkpoint_record.status == "CAPTURED" else "CHECKPOINT_CAPTURE_FAILED"
        detail = f"checkpoint_id={checkpoint_record.checkpoint_id} attempt_id={attempt_id}"
        if checkpoint_record.error:
            detail += f" error={checkpoint_record.error}"
        item.history = list(item.history) + [asdict(QueueEvent(event=event, at_utc=now, detail=detail))]
        _atomic_write_json(_item_metadata_path(queue_root, item_id), _item_to_dict(item))

        if checkpoint_record.status != "CAPTURED":
            raise QueueError(
                "CHECKPOINT_CAPTURE_FAILED",
                checkpoint_record.error or "checkpoint capture failed for an unknown reason",
            )
        return item
    finally:
        lock.release()


# ---------------------------------------------------------------------------
# Explicit human reconciliation (RUNNER-1.5E)
# ---------------------------------------------------------------------------

def reconcile_checkpoint(
    queue_root: Path,
    item_id: str,
    resolution: str,
    *,
    note: str,
    wait_for_lock: bool = False,
) -> QueueItem:
    """Governed, explicit human-reconciliation primitive for a
    BLOCKED_ON_CHECKPOINT item. Requires the exclusive QueueLock, a valid
    attached (integrity-verified) checkpoint, and a clean target repository
    at reconciliation time. Never itself commits, restores, resets, cleans,
    stages or modifies repository files - it only reads Git state to verify
    cleanliness. Exactly three resolutions are supported:

    * ACCEPT - only when the blocked attempt's recorded runner_state was
      SUCCESS; moves the item to SUCCEEDED. Refused for a legacy blocked
      item with no corresponding attempt.
    * FAIL - moves the item to FAILED.
    * RETRY - moves the item back to QUEUED (after the same clean-tree
      verification) so the next run-next dispatch creates a fresh attempt
      and a fresh Claude session; reconcile_checkpoint never itself invokes
      the executor.

    Every reconciliation appends an auditable history event (resolution,
    timestamp, checkpoint_id, the operator-supplied note, current HEAD, and
    the prior blocked attempt id where applicable) and marks the checkpoint
    `resolved` without deleting it; a resolved checkpoint is never reused
    as the checkpoint for a later attempt (its identity is tied to the
    attempt that produced it, and that attempt is already terminal).

    Corrupted-checkpoint terminal rejection (RUNNER-1.5E-FIX1): ACCEPT and
    RETRY always require the attached checkpoint to pass the exact same
    structural/content-integrity validation used at capture time
    (`_load_and_validate_checkpoint`) - a missing/unreadable blob, a
    manifest/patch hash mismatch, or a durable-record hash mismatch always
    fails both closed with `CHECKPOINT_INTEGRITY_FAILED`, exactly as
    before this hardening. FAIL is the sole exception: when the attached
    checkpoint fails that same validation, FAIL is still permitted to
    terminally reject the item (BLOCKED_ON_CHECKPOINT -> FAILED), because a
    corrupted checkpoint must never become a permanent dead end for an
    operator. This path never trusts, restores or applies anything from
    the unverifiable checkpoint content, never depends on the current
    (possibly since-changed) target-repository contents, and records the
    integrity failure (reason and checkpoint id) in both the item history
    and the checkpoint's own durable record. Once resolved this way the
    item is terminal (FAILED); a second reconciliation attempt is refused
    exactly like any other already-terminal item.
    """
    if resolution not in RECONCILE_RESOLUTIONS:
        raise QueueError(
            "INVALID_RESOLUTION",
            f"Unknown reconciliation resolution {resolution!r}; expected one of {RECONCILE_RESOLUTIONS}",
        )
    if not isinstance(note, str) or not note.strip():
        raise QueueError("MISSING_NOTE", "Reconciliation requires a non-empty operator note")

    lock = QueueLock(queue_root)
    lock.acquire(blocking=wait_for_lock)
    try:
        item = load_item(queue_root, item_id)
        if QueueState(item.state) != QueueState.BLOCKED_ON_CHECKPOINT:
            raise QueueError(
                "INVALID_STATE_FOR_RECONCILIATION",
                f"Item {item_id!r} is not BLOCKED_ON_CHECKPOINT (state={item.state})",
            )

        blocked_attempt = _latest_blocked_attempt(item)
        attempt_id = blocked_attempt.get("attempt_id") if blocked_attempt else None
        checkpoint_id = compute_checkpoint_id(item.item_id, attempt_id)

        checkpoint_ref = _find_latest_checkpoint_record(item, checkpoint_id)
        if checkpoint_ref is None:
            raise QueueError(
                "MISSING_CHECKPOINT",
                f"No checkpoint recorded for item {item_id!r}; run capture-checkpoint first",
            )
        # A checkpoint whose capture itself never succeeded (status FAILED,
        # e.g. the target repository disappeared) is another form of an
        # untrustworthy checkpoint. ACCEPT/RETRY still refuse it exactly as
        # before (CHECKPOINT_NOT_CAPTURED); FAIL may terminally reject it
        # for the same liveness reason a corrupted-but-captured checkpoint
        # may be rejected below.
        capture_failed = checkpoint_ref.get("status") != "CAPTURED"
        if capture_failed and resolution != "FAIL":
            raise QueueError(
                "CHECKPOINT_NOT_CAPTURED",
                "Checkpoint capture previously failed for this item; run capture-checkpoint first",
            )
        if checkpoint_ref.get("resolved"):
            raise QueueError(
                "CHECKPOINT_ALREADY_RESOLVED",
                f"Checkpoint {checkpoint_id!r} was already reconciled and is immutable",
            )

        published_dir = _checkpoints_root(queue_root, item.item_id) / checkpoint_id
        integrity_error: Optional[str] = None
        validated_checkpoint = None
        if capture_failed:
            integrity_error = checkpoint_ref.get("error") or "checkpoint capture previously failed"
        else:
            try:
                validated_checkpoint = _load_and_validate_checkpoint(
                    published_dir,
                    item.item_id,
                    attempt_id,
                    item.repository_path,
                )
            except CheckpointCaptureError as exc:
                integrity_error = str(exc)
                validated_checkpoint = None

        if integrity_error is None:
            expected_manifest_sha256 = checkpoint_ref.get("manifest_sha256")
            expected_patch_sha256 = checkpoint_ref.get("patch_sha256")

            if (
                not isinstance(expected_manifest_sha256, str)
                or len(expected_manifest_sha256) != 64
                or validated_checkpoint.manifest_sha256 != expected_manifest_sha256
            ):
                integrity_error = "Checkpoint manifest SHA-256 no longer matches the durable item record"
            elif (
                not isinstance(expected_patch_sha256, str)
                or len(expected_patch_sha256) != 64
                or validated_checkpoint.patch_sha256 != expected_patch_sha256
            ):
                integrity_error = "Checkpoint patch SHA-256 no longer matches the durable item record"

        # A corrupted/unverifiable checkpoint always fails ACCEPT and RETRY
        # closed - neither may ever trust, restore or requeue on top of
        # content that cannot be proven intact. FAIL is the sole governed
        # escape hatch (RUNNER-1.5E-FIX1): it terminally rejects the item
        # without trusting the checkpoint, so BLOCKED_ON_CHECKPOINT never
        # becomes a permanent dead end for a genuinely corrupted checkpoint.
        if integrity_error is not None and resolution != "FAIL":
            raise QueueError("CHECKPOINT_INTEGRITY_FAILED", integrity_error)

        repo = Path(item.repository_path)
        head = None
        if integrity_error is None:
            # The clean-repository precondition only matters when the
            # checkpoint itself is trusted (ACCEPT/RETRY/ordinary FAIL): it
            # exists to keep reconciliation decisions anchored to a known
            # repository state. A corrupted-checkpoint FAIL never reads,
            # trusts or depends on the target repository at all, so it must
            # not be blocked by the repository's current condition.
            try:
                is_worktree = _git_is_worktree(repo)
            except CheckpointCaptureError as exc:
                raise QueueError("GIT_ERROR", str(exc))
            if not is_worktree:
                raise QueueError(
                    "INVALID_REPOSITORY", f"Repository path is not a git work tree: {repo}"
                )
            try:
                clean = _git_repository_is_clean(repo)
            except CheckpointCaptureError as exc:
                raise QueueError("GIT_ERROR", str(exc))
            if not clean:
                raise QueueError(
                    "DIRTY_REPOSITORY",
                    "Repository is not clean at reconciliation time; reconciliation refused",
                )
            head = _git_head(repo)
        else:
            # Best-effort audit metadata only; never gates the corrupted-
            # checkpoint rejection path on the target repository's state.
            try:
                head = _git_head(repo)
            except CheckpointCaptureError:
                head = None

        if integrity_error is not None:
            to_state = QueueState.FAILED
        elif resolution == "ACCEPT":
            if blocked_attempt is None:
                raise QueueError(
                    "ACCEPT_REQUIRES_ATTEMPT",
                    "ACCEPT is refused for a legacy blocked item with no corresponding attempt",
                )
            if blocked_attempt.get("runner_state") != "SUCCESS":
                raise QueueError(
                    "ACCEPT_REQUIRES_SUCCESS",
                    "ACCEPT is only allowed when the blocked attempt's recorded "
                    "runner_state was SUCCESS",
                )
            to_state = QueueState.SUCCEEDED
        elif resolution == "FAIL":
            to_state = QueueState.FAILED
        else:
            to_state = QueueState.QUEUED

        now = _now_iso()

        updated_checkpoints = []
        for raw in item.checkpoints:
            raw = dict(raw)
            if raw.get("checkpoint_id") == checkpoint_id and not raw.get("resolved"):
                raw["resolved"] = True
                raw["resolution"] = resolution
                raw["resolved_at_utc"] = now
                raw["resolution_note"] = note
                raw["integrity_failed_at_reconciliation"] = integrity_error is not None
                raw["integrity_failure_detail"] = integrity_error
            updated_checkpoints.append(raw)

        item.checkpoints = updated_checkpoints
        item.state = to_state.value
        item.updated_at_utc = now
        history_detail = (
            f"resolution={resolution} checkpoint_id={checkpoint_id} note={note} "
            f"head={head} prior_attempt_id={attempt_id}"
        )
        event = f"RECONCILE:{resolution}:BLOCKED_ON_CHECKPOINT->{to_state.value}"
        if integrity_error is not None:
            history_detail += f" checkpoint_integrity_failed=true checkpoint_integrity_error={integrity_error}"
            event = f"RECONCILE_CORRUPT_CHECKPOINT_REJECTED:BLOCKED_ON_CHECKPOINT->{to_state.value}"
        item.history = list(item.history) + [
            asdict(QueueEvent(event=event, at_utc=now, detail=history_detail))
        ]
        _atomic_write_json(_item_metadata_path(queue_root, item.item_id), _item_to_dict(item))
        return item
    finally:
        lock.release()


# ---------------------------------------------------------------------------
# Explicit fresh requeue from WAITING_QUOTA (RUNNER-1.5F-A)
# ---------------------------------------------------------------------------

def resume_waiting_quota(
    queue_root: Path,
    item_id: str,
    *,
    note: str,
    wait_for_lock: bool = False,
) -> QueueItem:
    """Governed, explicit fresh-requeue primitive for a WAITING_QUOTA item.

    Requires the exclusive QueueLock, item state WAITING_QUOTA, a non-empty
    operator note, and a clean target repository verified through the
    existing read-only Git helpers (never mutates the repository itself).
    Refuses if the repository is dirty or not a Git work tree, if any
    checkpoint recorded on this item is still unresolved (an unreconciled
    BLOCKED_ON_CHECKPOINT episode would make a fresh retry unsafe), or if
    the item's own integrity does not load cleanly (`load_item` already
    fails closed on that).

    Atomically transitions WAITING_QUOTA -> QUEUED and appends an auditable
    history event referencing the prior attempt id, its quota reason code,
    the operator note, and current HEAD. Never invokes Claude or
    claude_runner: the next `run_next()` dispatch is what creates a
    completely fresh attempt_id and therefore a fresh, non-resumed Claude
    invocation.
    """
    if not isinstance(note, str) or not note.strip():
        raise QueueError("MISSING_NOTE", "Resume requires a non-empty operator note")

    lock = QueueLock(queue_root)
    lock.acquire(blocking=wait_for_lock)
    try:
        item = load_item(queue_root, item_id)
        if QueueState(item.state) != QueueState.WAITING_QUOTA:
            raise QueueError(
                "INVALID_STATE_FOR_RESUME",
                f"Item {item_id!r} is not WAITING_QUOTA (state={item.state})",
            )

        unresolved = [
            cp for cp in item.checkpoints
            if isinstance(cp, dict) and not cp.get("resolved")
        ]
        if unresolved:
            raise QueueError(
                "UNRESOLVED_CHECKPOINT",
                f"Item {item_id!r} has {len(unresolved)} unresolved checkpoint(s); "
                "resolve via reconcile before resuming from WAITING_QUOTA",
            )

        repo = Path(item.repository_path)
        try:
            is_worktree = _git_is_worktree(repo)
        except CheckpointCaptureError as exc:
            raise QueueError("GIT_ERROR", str(exc))
        if not is_worktree:
            raise QueueError(
                "INVALID_REPOSITORY", f"Repository path is not a git work tree: {repo}"
            )
        try:
            clean = _git_repository_is_clean(repo)
        except CheckpointCaptureError as exc:
            raise QueueError("GIT_ERROR", str(exc))
        if not clean:
            raise QueueError(
                "DIRTY_REPOSITORY",
                "Repository is not clean at resume time; resume refused",
            )

        prior_attempt = item.attempts[-1] if item.attempts else None
        prior_attempt_id = prior_attempt.get("attempt_id") if prior_attempt else None
        prior_quota_reason = prior_attempt.get("quota_reason_code") if prior_attempt else None

        head = _git_head(repo)
        now = _now_iso()
        item.state = QueueState.QUEUED.value
        item.updated_at_utc = now
        history_detail = (
            f"note={note} prior_attempt_id={prior_attempt_id} "
            f"quota_reason_code={prior_quota_reason} head={head}"
        )
        item.history = list(item.history) + [
            asdict(
                QueueEvent(
                    event="RESUME_WAITING_QUOTA:WAITING_QUOTA->QUEUED",
                    at_utc=now,
                    detail=history_detail,
                )
            )
        ]
        _atomic_write_json(_item_metadata_path(queue_root, item_id), _item_to_dict(item))
        return item
    finally:
        lock.release()


# ---------------------------------------------------------------------------
# Pure due-time predicate (RUNNER-1.5F-B1): for a later supervisor only
# ---------------------------------------------------------------------------

def _latest_waiting_quota_attempt(item: QueueItem) -> Optional[dict]:
    """Returns the most recent attempt dict finalized to WAITING_QUOTA, or
    None when there is no attempt at all, or when the most recent attempt's
    `final_queue_state` is not WAITING_QUOTA (fail-closed: an item whose
    latest attempt does not match its own WAITING_QUOTA state is treated as
    ambiguous durable state, never guessed at)."""
    if not item.attempts:
        return None
    latest = item.attempts[-1]
    if not isinstance(latest, dict):
        return None
    if latest.get("final_queue_state") != QueueState.WAITING_QUOTA.value:
        return None
    return latest


def is_waiting_quota_due(item: QueueItem, now_utc: Optional[datetime] = None) -> bool:
    """Pure, side-effect-free predicate for a later supervisor (RUNNER-
    1.5F-B1) to decide whether a WAITING_QUOTA item's provider-reported
    reset time has already passed. Performs NO mutation, NO locking, NO Git
    call and NO sleeping - it only inspects the in-memory `item` (and the
    supplied/current time) and returns a plain bool.

    Returns True only when ALL of the following hold:

    * `item.state` is exactly WAITING_QUOTA;
    * the item's latest attempt was finalized to WAITING_QUOTA (see
      `_latest_waiting_quota_attempt`) with `quota_classification`
      CONFIRMED_QUOTA;
    * that attempt carries a valid, timezone-aware
      `quota_retry_not_before_utc` (RUNNER-1.5F-B1 durable metadata); and
    * the supplied `now_utc` (or, when omitted, the current UTC time) is at
      or after that instant.

    Fails closed (returns False) for every ambiguous or malformed durable
    state instead of guessing: a non-WAITING_QUOTA item, an old WAITING_
    QUOTA item with no trusted reset metadata (pre-1.5F-B1), a missing or
    non-quota latest attempt, an unparsable or naive persisted timestamp,
    and a naive (or otherwise not-`datetime`) `now_utc`. This function
    intentionally has no opinion on grace periods, retry counts or backoff -
    that policy belongs to a later, separate supervisor Work Order.
    """
    if item.state != QueueState.WAITING_QUOTA.value:
        return False

    latest_attempt = _latest_waiting_quota_attempt(item)
    if latest_attempt is None:
        return False
    if latest_attempt.get("quota_classification") != QuotaClassification.CONFIRMED_QUOTA.value:
        return False

    retry_not_before_raw = latest_attempt.get("quota_retry_not_before_utc")
    if not isinstance(retry_not_before_raw, str) or not retry_not_before_raw:
        return False
    try:
        retry_not_before = datetime.fromisoformat(retry_not_before_raw)
    except ValueError:
        return False
    if retry_not_before.tzinfo is None or retry_not_before.utcoffset() is None:
        return False
    try:
        retry_not_before = retry_not_before.astimezone(timezone.utc)
    except (OverflowError, ValueError):
        return False

    if now_utc is None:
        now = datetime.now(timezone.utc)
    else:
        if not isinstance(now_utc, datetime):
            return False
        if now_utc.tzinfo is None or now_utc.utcoffset() is None:
            return False
        try:
            now = now_utc.astimezone(timezone.utc)
        except (OverflowError, ValueError):
            return False

    return now >= retry_not_before


# ---------------------------------------------------------------------------
# Single-worker run-next (RUNNER-1.5D)
# ---------------------------------------------------------------------------

def _build_work_order_request(
    queue_root: Path, item: QueueItem, *, run_root: Optional[str] = None,
) -> "claude_runner.WorkOrderRequest":
    """Builds exactly one claude_runner.WorkOrderRequest from durable queue
    data: the durable item work_order.txt path (never the original enqueue
    source), the persisted mode/authorize_path/model/label, and timeout
    only when the item explicitly requested one (otherwise the Runner's own
    default applies).

    `run_root` (RUNNER-V2B-FIX2) is optional and backward-compatible:
    omitted (the default, and always what `run_next()`/`supervisor_once()`
    pass), the Runner's own default target-local evidence placement applies
    unchanged - the exact V1.5 behavior. `claude_multiworker.py` passes its
    own externalized, coordinator-owned evidence root explicitly here so V2
    Claude evidence is never part of the target repository's working tree."""
    work_order_path = _item_dir(queue_root, item.item_id) / item.work_order_filename
    kwargs = dict(
        repo=item.repository_path,
        work_order=str(work_order_path),
        mode=item.mode,
        authorize_path=list(item.authorize_path),
        model=item.model,
        label=item.label,
    )
    if item.timeout_seconds is not None:
        kwargs["timeout_seconds"] = item.timeout_seconds
    if run_root is not None:
        kwargs["run_root"] = run_root
    return claude_runner.WorkOrderRequest(**kwargs)


def _resolve_verified_evidence_dir(
    item: QueueItem, result: "claude_runner.WorkOrderResult", *, expected_run_root: Optional[str] = None,
) -> Optional[Path]:
    """Returns the Runner evidence directory for `result` only if it is
    trustworthy: present, an actual directory, named exactly `result.run_id`
    (never trusting an attacker/bug-supplied mismatched pair), and located
    under the expected evidence base (never an arbitrary path elsewhere on
    disk). Returns None on any inconsistency - callers must fail closed
    rather than guess. Shared by write-mode mutation verification and quota
    classification so both read evidence through the identical trust
    boundary.

    `expected_run_root` (RUNNER-V2B-FIX2) is optional and backward-
    compatible: omitted (the default), the expected base is this exact
    item's own repository's `runtime/claude_runner/runs` - the legacy V1.5
    target-local placement, unchanged. When given, it must be the exact
    `run_root` the caller itself already passed to
    `claude_runner.execute_work_order()` for this attempt (never guessed,
    never derived from `result` itself), so this never becomes a second,
    independently-spoofable source of truth."""
    if result.evidence_dir is None or result.run_id is None:
        return None
    try:
        evidence_dir = Path(result.evidence_dir).resolve()
    except OSError:
        return None
    if not evidence_dir.is_dir() or evidence_dir.name != result.run_id:
        return None

    try:
        if expected_run_root is not None:
            expected_base = Path(expected_run_root).resolve()
        else:
            expected_base = (Path(item.repository_path).resolve() / claude_runner.RUNTIME_SUBDIR).resolve()
        evidence_dir.relative_to(expected_base)
    except (OSError, ValueError):
        return None
    return evidence_dir


def _load_verified_result_json(evidence_dir: Path, result: "claude_runner.WorkOrderResult") -> Optional[dict]:
    """Reads and validates `result.json` under an already-trust-verified
    evidence directory. Returns None on missing/unreadable/malformed JSON
    or a `state` field inconsistent with the returned WorkOrderResult."""
    result_json_path = evidence_dir / "result.json"
    if not result_json_path.exists():
        return None
    try:
        payload = json.loads(result_json_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("state") != result.state.value:
        return None
    return payload


def _verify_write_evidence_mutation(
    item: QueueItem, result: "claude_runner.WorkOrderResult", *, expected_run_root: Optional[str] = None,
):
    """Returns True/False for a post-invocation write-mode attempt's
    verified `safety_check.repository_mutated`, or None if the Runner
    evidence cannot be trusted (missing, unreadable, malformed, or
    inconsistent with the returned run_id/evidence_dir/state) - callers
    must fail closed to FAILED_SAFETY on None rather than guess.
    `expected_run_root` (RUNNER-V2B-FIX2) is forwarded unchanged to
    `_resolve_verified_evidence_dir()` - see its docstring."""
    evidence_dir = _resolve_verified_evidence_dir(item, result, expected_run_root=expected_run_root)
    if evidence_dir is None:
        return None
    payload = _load_verified_result_json(evidence_dir, result)
    if payload is None:
        return None
    safety_check = payload.get("safety_check")
    if not isinstance(safety_check, dict):
        return None
    mutated = safety_check.get("repository_mutated")
    if not isinstance(mutated, bool):
        return None
    return mutated


# ---------------------------------------------------------------------------
# Quota classification (RUNNER-1.5F-A): conservative, evidence-only
# ---------------------------------------------------------------------------
#
# Classifies a completed (non-pre-invocation-refusal) attempt as a Claude
# provider usage/quota failure using ONLY trustworthy, structured,
# post-invocation Runner evidence: the parsed Claude CLI JSON result
# (`cli_output.cli_result`, only when the CLI itself reported `is_error:
# true`) and, as a narrow fallback, `stderr.txt` - both already produced by
# claude_runner and read through the same evidence-directory trust boundary
# as write-mode mutation verification. This module deliberately never reads
# `prompt.txt` or the durable Work Order text, and never reads a successful
# run's answer content (`is_error: false`), because both can legitimately
# contain the word "quota" or similar phrasing without any actual provider
# quota failure having occurred. Ambiguous, missing, or malformed evidence
# is always NOT_CONFIRMED - this classifier never guesses.

class QuotaClassification(str, Enum):
    CONFIRMED_QUOTA = "CONFIRMED_QUOTA"
    NOT_CONFIRMED = "NOT_CONFIRMED"


@dataclass
class QuotaClassificationResult:
    """Durable-safe classification outcome. Deliberately carries no Claude
    transcript/stdout/prompt content - only a reason code and a reference
    (run_id/evidence path) back to the Runner evidence that produced it.

    `quota_reset_epoch`/`quota_retry_not_before_utc` (RUNNER-1.5F-B1) are
    optional, backward-compatible additions: populated only when the exact
    trusted quota signal carried a provider epoch that could be safely
    converted to a representable, timezone-aware UTC datetime; `None`
    otherwise (including for NOT_CONFIRMED, and for a CONFIRMED_QUOTA whose
    epoch could not be safely converted), so an item without them simply has
    no durable automatic retry time and remains manual-resume-only.
    """

    classification: str  # QuotaClassification value
    reason_code: Optional[str]
    detected_at_utc: str
    evidence_run_id: Optional[str]
    evidence_path: Optional[str]
    quota_reset_epoch: Optional[int] = None
    quota_retry_not_before_utc: Optional[str] = None


def _not_confirmed(result: "claude_runner.WorkOrderResult") -> QuotaClassificationResult:
    return QuotaClassificationResult(
        classification=QuotaClassification.NOT_CONFIRMED.value,
        reason_code=None,
        detected_at_utc=_now_iso(),
        evidence_run_id=result.run_id,
        evidence_path=str(result.evidence_dir) if result.evidence_dir else None,
    )


# The only structural signal this classifier trusts: the Claude CLI's own,
# well-known usage-limit message ("Claude AI usage limit reached|<epoch
# seconds>"), matched narrowly and anchored to the whole line/field so it
# cannot be triggered by a substring appearing incidentally elsewhere. This
# pattern must only ever be widened by an operator against confirmed live
# evidence, never by broad keyword matching. The captured group is the
# provider epoch, extracted (RUNNER-1.5F-B1) only after this exact signal has
# already matched - never parsed out of any other text.
_QUOTA_USAGE_LIMIT_RE = re.compile(r"^Claude AI usage limit reached\|(\d+)$")


def _epoch_seconds_to_utc_iso(epoch_seconds: int) -> Optional[str]:
    """Deterministically converts a provider-supplied Unix epoch (seconds)
    to a timezone-aware UTC ISO-8601 string using only the standard
    library. Returns None (never raises) when the value is outside what
    this platform's `datetime` can safely represent, so callers can keep
    CONFIRMED_QUOTA without persisting a guessed or out-of-range retry
    timestamp."""
    try:
        return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _cli_error_result_text(result_payload: dict) -> Optional[str]:
    """Returns the CLI's own structured error-result text, but ONLY when the
    parsed CLI JSON explicitly reported `is_error: true`. A successful run's
    `result` text is Claude's conversational answer and is never inspected
    here - that is exactly the false-positive source this classifier must
    avoid."""
    cli_output = result_payload.get("cli_output")
    if not isinstance(cli_output, dict) or cli_output.get("parsed") is not True:
        return None
    cli_result = cli_output.get("cli_result")
    if not isinstance(cli_result, dict) or cli_result.get("is_error") is not True:
        return None
    text = cli_result.get("result")
    return text.strip() if isinstance(text, str) else None


def _stderr_quota_line(evidence_dir: Path) -> Optional[str]:
    """Narrow fallback for a CLI/provider-level failure that never produced
    parseable stdout JSON at all (`cli_output.parsed` False): scans
    `stderr.txt` - the CLI's own error channel, never a conversational
    channel - for an exact, anchored match of the same usage-limit line."""
    stderr_path = evidence_dir / "stderr.txt"
    try:
        stderr_text = stderr_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    for line in stderr_text.splitlines():
        stripped = line.strip()
        if _QUOTA_USAGE_LIMIT_RE.match(stripped):
            return stripped
    return None


def classify_quota_default(
    item: QueueItem, result: "claude_runner.WorkOrderResult", *, expected_run_root: Optional[str] = None,
) -> QuotaClassificationResult:
    """Safe production default quota classifier (RUNNER-1.5F-A).

    Only ever considers CONFIRMED_QUOTA when `result.state` is
    `RunState.CLAUDE_ERROR` (an actual invocation happened and the CLI/
    provider itself reported failure - never SUCCESS, never TIMEOUT/
    INTERRUPTED, never FAILED_SAFETY, and never a pre-invocation refusal,
    which `result.error_message is not None` would indicate and which
    callers must never route here in the first place). Returns
    NOT_CONFIRMED for any evidence that is missing, unreadable, malformed,
    or does not carry the narrow trustworthy quota signal above.

    `expected_run_root` (RUNNER-V2B-FIX2, optional/backward-compatible) is
    forwarded unchanged to `_resolve_verified_evidence_dir()` - a directly
    injected custom `quota_classifier` (test or otherwise) keeps its
    existing two-argument call signature unaffected; only
    `_map_runner_result_to_queue_state()`'s own use of this default
    classifier supplies it.
    """
    if result.state != claude_runner.RunState.CLAUDE_ERROR or result.error_message is not None:
        return _not_confirmed(result)

    evidence_dir = _resolve_verified_evidence_dir(item, result, expected_run_root=expected_run_root)
    if evidence_dir is None:
        return _not_confirmed(result)

    payload = _load_verified_result_json(evidence_dir, result)
    reason_code = None
    quota_match = None
    if payload is not None:
        error_text = _cli_error_result_text(payload)
        if error_text:
            match = _QUOTA_USAGE_LIMIT_RE.match(error_text)
            if match:
                reason_code = "CLI_RESULT_USAGE_LIMIT_MESSAGE"
                quota_match = match
    if reason_code is None:
        stderr_line = _stderr_quota_line(evidence_dir)
        if stderr_line is not None:
            reason_code = "CLI_STDERR_USAGE_LIMIT_MESSAGE"
            quota_match = _QUOTA_USAGE_LIMIT_RE.match(stderr_line)

    if reason_code is None:
        return _not_confirmed(result)

    # RUNNER-1.5F-B1: the epoch is parsed ONLY from the digits captured by
    # the already-matched trusted quota signal above - never re-derived from
    # any other text - and converted deterministically; an unrepresentable
    # epoch leaves both fields None (CONFIRMED_QUOTA, no automatic retry).
    quota_reset_epoch = None
    if quota_match is not None:
        try:
            quota_reset_epoch = int(quota_match.group(1))
        except ValueError:
            # The quota signal itself is still trusted/confirmed, but reset
            # metadata that cannot be represented safely must never drive
            # automatic scheduling.
            quota_reset_epoch = None

    quota_retry_not_before_utc = (
        _epoch_seconds_to_utc_iso(quota_reset_epoch)
        if quota_reset_epoch is not None
        else None
    )

    return QuotaClassificationResult(
        classification=QuotaClassification.CONFIRMED_QUOTA.value,
        reason_code=reason_code,
        detected_at_utc=_now_iso(),
        evidence_run_id=result.run_id,
        evidence_path=str(evidence_dir),
        quota_reset_epoch=quota_reset_epoch,
        quota_retry_not_before_utc=quota_retry_not_before_utc,
    )


def _with_quota_note(detail: Optional[str], quota_record: QuotaClassificationResult) -> str:
    note = (
        f"quota_classification={quota_record.classification} "
        f"quota_reason_code={quota_record.reason_code} "
        f"quota_evidence_run_id={quota_record.evidence_run_id}"
    )
    return f"{detail or 'confirmed quota'}; {note}"


def _map_runner_result_to_queue_state(
    item: QueueItem, result: "claude_runner.WorkOrderResult", *, quota_classifier=None,
    expected_run_root: Optional[str] = None,
) -> tuple:
    """Fail-closed result mapping (RUNNER-1.5D, extended RUNNER-1.5F-A).

    Returns `(QueueState, Optional[QuotaClassificationResult])`; the second
    element is populated only when the mapped state is WAITING_QUOTA.

    RunState.FAILED_SAFETY always maps to FAILED_SAFETY, unconditionally -
    checked before quota classification is even considered. A deterministic
    pre-invocation Runner refusal (WorkOrderResult.error_message set - the
    Work Order file was never sent to Claude) maps to FAILED and is never
    quota-classified either. Otherwise, an actual invocation happened: in
    write mode the verified repository_mutated flag from the Runner's own
    evidence always takes precedence over quota - missing/corrupt write
    safety evidence is FAILED_SAFETY regardless of any quota signal, and a
    mutated tree always maps to BLOCKED_ON_CHECKPOINT (human reconciliation
    required) regardless of any quota signal, both without ever consulting
    the quota classifier. Only an otherwise-safe non-success outcome (read-
    only always; write mode only once repository_mutated is verified false)
    is passed to the quota classifier: CONFIRMED_QUOTA maps to WAITING_
    QUOTA, anything else maps to FAILED exactly as before RUNNER-1.5F-A.

    `expected_run_root` (RUNNER-V2B-FIX2, optional/backward-compatible) is
    the exact `run_root` the caller already passed to
    `claude_runner.execute_work_order()` for this attempt (`None` for
    V1.5's still-target-local `run_next()`/`supervisor_once()`, the
    externalized evidence-sidecar path for `claude_multiworker.py`); it is
    forwarded to write-mode mutation verification, and - only when the
    caller did not inject its own `quota_classifier` - to the default quota
    classifier too. An explicitly injected `quota_classifier` keeps its
    original two-argument `(item, result)` call signature unchanged.
    """
    if result.state == claude_runner.RunState.FAILED_SAFETY:
        return QueueState.FAILED_SAFETY, None
    if result.error_message is not None:
        return QueueState.FAILED, None

    if quota_classifier is not None:
        classifier = quota_classifier
    else:
        def classifier(it, res):
            return classify_quota_default(it, res, expected_run_root=expected_run_root)

    if item.mode == claude_runner.MODE_WRITE:
        mutated = _verify_write_evidence_mutation(item, result, expected_run_root=expected_run_root)
        if mutated is None:
            return QueueState.FAILED_SAFETY, None
        if mutated:
            return QueueState.BLOCKED_ON_CHECKPOINT, None
        if result.state == claude_runner.RunState.SUCCESS:
            return QueueState.SUCCEEDED, None
        quota = classifier(item, result)
        if quota.classification == QuotaClassification.CONFIRMED_QUOTA.value:
            return QueueState.WAITING_QUOTA, quota
        return QueueState.FAILED, None

    if result.state == claude_runner.RunState.SUCCESS:
        return QueueState.SUCCEEDED, None
    quota = classifier(item, result)
    if quota.classification == QuotaClassification.CONFIRMED_QUOTA.value:
        return QueueState.WAITING_QUOTA, quota
    return QueueState.FAILED, None


class RunNextOutcome(str, Enum):
    NO_WORK = "NO_WORK"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    DISPATCHED = "DISPATCHED"


@dataclass
class RunNextResult:
    outcome: str
    item_id: Optional[str] = None
    attempt_id: Optional[str] = None
    queue_state: Optional[str] = None
    runner_state: Optional[str] = None
    recovered_item_ids: list = field(default_factory=list)
    checkpoint_id: Optional[str] = None


def _run_next_locked(
    queue_root: Path,
    *,
    lock: QueueLock,
    executor=None,
    quota_classifier=None,
) -> RunNextResult:
    """Lock-held run-next primitive (RUNNER-1.5F-B2A-FIX1): the complete
    run-next dispatch body (orphan recovery, deterministic QUEUED
    selection, attempt creation, executor invocation, checkpoint/quota
    result mapping, and final persistence), requiring the caller to already
    hold the exclusive QueueLock for this exact queue root. Never itself
    acquires or releases a lock - fails closed (QueueLockError) if `lock`
    is unheld or belongs to a different queue root, via
    `_require_held_lock`. This lets a caller that must observe queue state
    and then dispatch (e.g. `supervisor_once`) do so within one
    uninterrupted lock scope instead of releasing and re-acquiring the
    lock between observation and dispatch. `run_next()` itself is now a
    thin wrapper: acquire exactly one QueueLock, delegate here, release in
    finally - identical externally observable behavior to before this
    refactor."""
    _require_held_lock(queue_root, lock)
    if executor is None:
        executor = claude_runner.execute_work_order

    recovered = recover_orphaned_running_items(queue_root, lock=lock)
    if recovered:
        return RunNextResult(
            outcome=RunNextOutcome.RECOVERY_REQUIRED.value,
            recovered_item_ids=[it.item_id for it in recovered],
        )

    queued = [it for it in list_items(queue_root) if QueueState(it.state) == QueueState.QUEUED]
    if not queued:
        return RunNextResult(outcome=RunNextOutcome.NO_WORK.value)

    selected = queued[0]
    attempt_id = generate_attempt_id()
    attempt = QueueAttempt(
        attempt_id=attempt_id,
        started_at_utc=_now_iso(),
        ended_at_utc=None,
        status="RUNNING",
        runner_state=None,
        runner_exit_code=None,
        runner_run_id=None,
        runner_evidence_dir=None,
        final_queue_state=None,
    )
    item = start_attempt(queue_root, selected.item_id, attempt)
    request = _build_work_order_request(queue_root, item)

    try:
        result = executor(request)
    except Exception as exc:
        checkpoint_record = capture_or_reuse_checkpoint(queue_root, item, attempt_id=attempt_id)
        item = finalize_attempt(
            queue_root, item.item_id, attempt_id,
            to_state=QueueState.BLOCKED_ON_CHECKPOINT,
            status="EXCEPTION",
            ended_at_utc=_now_iso(),
            runner_state=None,
            runner_exit_code=None,
            runner_run_id=None,
            runner_evidence_dir=None,
            detail=_with_checkpoint_note(
                f"executor raised {type(exc).__name__}: {exc}; execution outcome "
                "is uncertain, recovered fail-closed without an automatic retry",
                checkpoint_record,
            ),
            checkpoint_record=checkpoint_record,
        )
        return RunNextResult(
            outcome=RunNextOutcome.DISPATCHED.value,
            item_id=item.item_id,
            attempt_id=attempt_id,
            queue_state=item.state,
            runner_state=None,
            checkpoint_id=checkpoint_record.checkpoint_id,
        )

    to_state, quota_record = _map_runner_result_to_queue_state(
        item, result, quota_classifier=quota_classifier, expected_run_root=request.run_root,
    )
    checkpoint_record = None
    detail = result.error_message
    if to_state == QueueState.BLOCKED_ON_CHECKPOINT:
        checkpoint_record = capture_or_reuse_checkpoint(queue_root, item, attempt_id=attempt_id)
        detail = _with_checkpoint_note(detail or "write-mode mutation detected", checkpoint_record)
    elif to_state == QueueState.WAITING_QUOTA:
        detail = _with_quota_note(detail, quota_record)
    item = finalize_attempt(
        queue_root, item.item_id, attempt_id,
        to_state=to_state,
        status="COMPLETED",
        ended_at_utc=_now_iso(),
        runner_state=result.state.value,
        runner_exit_code=result.exit_code,
        runner_run_id=result.run_id,
        runner_evidence_dir=str(result.evidence_dir) if result.evidence_dir else None,
        detail=detail,
        checkpoint_record=checkpoint_record,
        quota_record=quota_record,
    )
    return RunNextResult(
        outcome=RunNextOutcome.DISPATCHED.value,
        item_id=item.item_id,
        attempt_id=attempt_id,
        queue_state=item.state,
        runner_state=result.state.value,
        checkpoint_id=checkpoint_record.checkpoint_id if checkpoint_record else None,
    )


def run_next(
    queue_root: Path,
    *,
    executor=None,
    quota_classifier=None,
    wait_for_lock: bool = False,
) -> RunNextResult:
    """Single-worker run-next (RUNNER-1.5D, extended RUNNER-1.5F-A; now a
    thin wrapper around `_run_next_locked` as of RUNNER-1.5F-B2A-FIX1).

    Acquires exactly one exclusive QueueLock and holds it for the complete
    dispatch lifecycle (orphan recovery through final queue-state
    persistence), so a second worker can never execute concurrently, then
    releases it in `finally`. Immediately recovers orphaned RUNNING items
    under that same held lock; if any were recovered, stops and dispatches
    nothing this call (deterministic RECOVERY_REQUIRED), so an operator can
    reconcile checkpoints first. If none were recovered, selects the first
    QUEUED item in the existing deterministic order (or returns NO_WORK
    without invoking anything), atomically transitions it QUEUED->RUNNING
    with a durable attempt record visible before the executor runs, invokes
    the executor (by default claude_runner.execute_work_order - the sole
    place any Runner branch/dirty-tree/write-scope/safety guard lives), and
    finalizes the attempt and queue state atomically from the fail-closed
    result mapping. An executor that raises instead of returning a
    WorkOrderResult is treated as an uncertain outcome and finalized
    fail-closed to BLOCKED_ON_CHECKPOINT without any automatic second
    attempt.

    `quota_classifier` (RUNNER-1.5F-A) is optional and dependency-
    injectable, mirroring `executor`: defaults to `classify_quota_default`
    (a conservative, evidence-only production classifier) and is called
    with `(item, result)` only for an otherwise-safe non-success outcome
    (never for FAILED_SAFETY, a pre-invocation refusal, or a write-mode
    mutation/uncertain-evidence outcome, all of which are decided first and
    never consult the classifier at all).
    """
    lock = QueueLock(queue_root)
    lock.acquire(blocking=wait_for_lock)
    try:
        return _run_next_locked(
            queue_root, lock=lock, executor=executor, quota_classifier=quota_classifier,
        )
    finally:
        lock.release()


# ---------------------------------------------------------------------------
# Governed single-worker supervisor cycle (RUNNER-1.5F-B2A)
# ---------------------------------------------------------------------------
#
# `supervisor_once()` is a single, non-looping, non-sleeping dispatch cycle
# built entirely on `run_next()`/`resume_waiting_quota()`-equivalent
# governance. It never invokes the Claude executor more than once per call
# and never duplicates Runner/queue execution logic; it only adds a
# cross-item barrier policy (BLOCKED_ON_CHECKPOINT/WAITING_QUOTA block
# ordinary dispatch queue-wide) and one narrow, explicitly governed
# automatic action (auto-requeuing a single due WAITING_QUOTA item) on top
# of the existing primitives.

class SupervisorOutcome(str, Enum):
    NO_WORK = "NO_WORK"
    DISPATCHED = "DISPATCHED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    OPERATOR_REQUIRED = "OPERATOR_REQUIRED"
    WAITING_QUOTA = "WAITING_QUOTA"
    SAFETY_STOP = "SAFETY_STOP"


class SupervisorReason(str, Enum):
    NO_QUEUED_WORK = "NO_QUEUED_WORK"
    DISPATCHED_QUEUED_ITEM = "DISPATCHED_QUEUED_ITEM"
    ORPHAN_RECOVERY_REQUIRED = "ORPHAN_RECOVERY_REQUIRED"
    CHECKPOINT_PENDING_RECONCILIATION = "CHECKPOINT_PENDING_RECONCILIATION"
    QUOTA_MANUAL_RESUME_REQUIRED = "QUOTA_MANUAL_RESUME_REQUIRED"
    QUOTA_BARRIER_NOT_DUE = "QUOTA_BARRIER_NOT_DUE"
    QUOTA_AUTO_RESUMED_THEN_DISPATCHED = "QUOTA_AUTO_RESUMED_THEN_DISPATCHED"
    QUOTA_AUTO_RESUMED_THEN_NO_WORK = "QUOTA_AUTO_RESUMED_THEN_NO_WORK"
    QUOTA_AUTO_RESUME_SAFETY_STOP = "QUOTA_AUTO_RESUME_SAFETY_STOP"


@dataclass
class SupervisorResult:
    """Compact, structured outcome of one `supervisor_once()` cycle. Carries
    no conversational/session content - only enough for a later looping
    supervisor (RUNNER-1.5F-B2B) to decide STOP/WAIT/OPERATOR_REQUIRED/
    CONTINUE without parsing prose."""

    outcome: str
    reason: str
    item_id: Optional[str] = None
    attempt_id: Optional[str] = None
    queue_state: Optional[str] = None
    runner_state: Optional[str] = None
    next_wake_utc: Optional[str] = None
    recovered_item_ids: list = field(default_factory=list)
    auto_resumed_item_id: Optional[str] = None


def _resolve_now_utc(now_utc: Optional[datetime]) -> datetime:
    if now_utc is None:
        return datetime.now(timezone.utc)
    if not isinstance(now_utc, datetime) or now_utc.tzinfo is None or now_utc.utcoffset() is None:
        raise QueueError(
            "INVALID_NOW_UTC", "supervisor_once now_utc must be a timezone-aware datetime"
        )
    return now_utc.astimezone(timezone.utc)


def _reason_for_run_next_outcome(outcome: str, *, context: str) -> str:
    if outcome == RunNextOutcome.RECOVERY_REQUIRED.value:
        return SupervisorReason.ORPHAN_RECOVERY_REQUIRED.value
    if outcome == RunNextOutcome.NO_WORK.value:
        if context == "QUOTA_AUTO_RESUME":
            return SupervisorReason.QUOTA_AUTO_RESUMED_THEN_NO_WORK.value
        return SupervisorReason.NO_QUEUED_WORK.value
    if context == "QUOTA_AUTO_RESUME":
        return SupervisorReason.QUOTA_AUTO_RESUMED_THEN_DISPATCHED.value
    return SupervisorReason.DISPATCHED_QUEUED_ITEM.value


def _from_run_next_result(
    result: RunNextResult, *, context: str, auto_resumed_item_id: Optional[str] = None
) -> SupervisorResult:
    if result.outcome == RunNextOutcome.NO_WORK.value:
        outcome = SupervisorOutcome.NO_WORK.value
    elif result.outcome == RunNextOutcome.RECOVERY_REQUIRED.value:
        outcome = SupervisorOutcome.RECOVERY_REQUIRED.value
    else:
        outcome = SupervisorOutcome.DISPATCHED.value
    return SupervisorResult(
        outcome=outcome,
        reason=_reason_for_run_next_outcome(result.outcome, context=context),
        item_id=result.item_id,
        attempt_id=result.attempt_id,
        queue_state=result.queue_state,
        runner_state=result.runner_state,
        recovered_item_ids=list(result.recovered_item_ids),
        auto_resumed_item_id=auto_resumed_item_id,
    )


def _parse_trusted_retry_not_before(item: QueueItem) -> Optional[datetime]:
    """Returns the parsed, timezone-aware UTC retry-not-before instant for
    `item`'s latest WAITING_QUOTA attempt when - and only when - it carries
    the same trusted RUNNER-1.5F-B1 metadata `is_waiting_quota_due()`
    requires (CONFIRMED_QUOTA classification, a valid timezone-aware
    timestamp). Mirrors `is_waiting_quota_due()`'s own validation exactly,
    minus the now-comparison. Returns None for every ambiguous/malformed/
    manual-resume-only case - never a guess."""
    if item.state != QueueState.WAITING_QUOTA.value:
        return None
    latest = _latest_waiting_quota_attempt(item)
    if latest is None:
        return None
    if latest.get("quota_classification") != QuotaClassification.CONFIRMED_QUOTA.value:
        return None
    raw = latest.get("quota_retry_not_before_utc")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    try:
        return parsed.astimezone(timezone.utc)
    except (OverflowError, ValueError):
        return None


def _auto_resume_one_waiting_quota_item_locked(
    queue_root: Path, item_id: str, *, lock: QueueLock, now_utc: datetime,
) -> QueueItem:
    """Lock-held quota auto-resume primitive (RUNNER-1.5F-B2A-FIX1):
    requires the caller to already hold the exclusive QueueLock for this
    exact queue root (fails closed via `_require_held_lock` on an unheld
    lock or a lock for a different root) and never itself acquires or
    releases a lock. Performs a fresh reload of `item_id` plus the identical
    due/checkpoint/Git-cleanliness safety checks as the lock-acquiring
    `_auto_resume_one_waiting_quota_item` wrapper below, so a state change
    between an earlier planning read and this call is always caught and
    refused fail-closed rather than assumed stale-but-safe. Recording a
    distinct, machine-generated auditable event that never pretends to be
    an operator note."""
    _require_held_lock(queue_root, lock)
    item = load_item(queue_root, item_id)
    if QueueState(item.state) != QueueState.WAITING_QUOTA:
        raise QueueError(
            "INVALID_STATE_FOR_AUTO_RESUME",
            f"Item {item_id!r} is not WAITING_QUOTA (state={item.state})",
        )
    if not is_waiting_quota_due(item, now_utc=now_utc):
        raise QueueError(
            "QUOTA_NOT_DUE_AT_MUTATION_TIME",
            f"Item {item_id!r} is not due for automatic resume at mutation time",
        )

    unresolved = [
        cp for cp in item.checkpoints if isinstance(cp, dict) and not cp.get("resolved")
    ]
    if unresolved:
        raise QueueError(
            "UNRESOLVED_CHECKPOINT",
            f"Item {item_id!r} has {len(unresolved)} unresolved checkpoint(s); "
            "resolve via reconcile before auto-resuming from WAITING_QUOTA",
        )

    repo = Path(item.repository_path)
    try:
        is_worktree = _git_is_worktree(repo)
    except CheckpointCaptureError as exc:
        raise QueueError("GIT_ERROR", str(exc))
    if not is_worktree:
        raise QueueError(
            "INVALID_REPOSITORY", f"Repository path is not a git work tree: {repo}"
        )
    try:
        clean = _git_repository_is_clean(repo)
    except CheckpointCaptureError as exc:
        raise QueueError("GIT_ERROR", str(exc))
    if not clean:
        raise QueueError(
            "DIRTY_REPOSITORY",
            "Repository is not clean at auto-resume time; auto-resume refused",
        )

    latest_attempt = _latest_waiting_quota_attempt(item)
    prior_attempt_id = latest_attempt.get("attempt_id") if latest_attempt else None
    prior_quota_reason = latest_attempt.get("quota_reason_code") if latest_attempt else None
    retry_not_before = latest_attempt.get("quota_retry_not_before_utc") if latest_attempt else None

    head = _git_head(repo)
    now_iso = _now_iso()
    item.state = QueueState.QUEUED.value
    item.updated_at_utc = now_iso
    history_detail = (
        f"machine-generated: trusted quota_retry_not_before_utc={retry_not_before} reached; "
        f"prior_attempt_id={prior_attempt_id} quota_reason_code={prior_quota_reason} head={head}"
    )
    item.history = list(item.history) + [
        asdict(
            QueueEvent(
                event="AUTO_RESUME_WAITING_QUOTA:WAITING_QUOTA->QUEUED",
                at_utc=now_iso,
                detail=history_detail,
            )
        )
    ]
    _atomic_write_json(_item_metadata_path(queue_root, item_id), _item_to_dict(item))
    return item


def _auto_resume_one_waiting_quota_item(
    queue_root: Path, item_id: str, *, now_utc: datetime, wait_for_lock: bool = False,
) -> QueueItem:
    """Governed automatic fresh-requeue of exactly one WAITING_QUOTA item
    (RUNNER-1.5F-B2A; now a thin lock-acquiring wrapper around
    `_auto_resume_one_waiting_quota_item_locked` as of RUNNER-1.5F-B2A-
    FIX1), applying the same safety checks as the explicit
    `resume_waiting_quota` primitive (item integrity via `load_item`, no
    unresolved checkpoint, a clean Git work tree) but recording a distinct,
    machine-generated auditable event that never pretends to be an operator
    note. Acquires its own exclusive QueueLock, delegates, and releases in
    `finally`. Callers that already hold the exclusive QueueLock for this
    queue root (e.g. `supervisor_once`, via `_handle_quota_barrier`) must
    call `_auto_resume_one_waiting_quota_item_locked` directly instead of
    this wrapper - this wrapper's own lock acquisition would simply fail to
    acquire against an already-held in-process lock (or block forever with
    `wait_for_lock=True`, self-deadlocking), never succeed."""
    lock = QueueLock(queue_root)
    lock.acquire(blocking=wait_for_lock)
    try:
        return _auto_resume_one_waiting_quota_item_locked(
            queue_root, item_id, lock=lock, now_utc=now_utc,
        )
    finally:
        lock.release()


def _handle_quota_barrier(
    queue_root: Path,
    waiting_quota_items: list,
    now: datetime,
    *,
    lock: QueueLock,
    executor,
    quota_classifier,
) -> SupervisorResult:
    """WAITING_QUOTA acts as a global dispatch barrier for this single-
    provider V1.5 queue. Returns operator-required (manual) if any barrier
    item lacks trusted reset metadata, a non-mutating WAITING_QUOTA result
    with a conservative `next_wake_utc` if any trusted barrier item is not
    yet due, or - only when every barrier item is due - auto-requeues
    exactly one deterministic item before dispatching at most once, both
    under the same already-held `lock` (RUNNER-1.5F-B2A-FIX1: no unlock gap
    between auto-resume and dispatch) via the lock-held primitives
    `_auto_resume_one_waiting_quota_item_locked`/`_run_next_locked` -
    never the lock-acquiring `resume`/`run_next` wrappers, which would
    attempt to acquire a second QueueLock while this one is already held."""
    trusted = []
    for candidate in waiting_quota_items:
        retry_not_before = _parse_trusted_retry_not_before(candidate)
        if retry_not_before is None:
            return SupervisorResult(
                outcome=SupervisorOutcome.OPERATOR_REQUIRED.value,
                reason=SupervisorReason.QUOTA_MANUAL_RESUME_REQUIRED.value,
                item_id=candidate.item_id,
                queue_state=QueueState.WAITING_QUOTA.value,
            )
        trusted.append((candidate, retry_not_before))

    latest_barrier_instant = max(retry_not_before for _, retry_not_before in trusted)
    if any(now < retry_not_before for _, retry_not_before in trusted):
        return SupervisorResult(
            outcome=SupervisorOutcome.WAITING_QUOTA.value,
            reason=SupervisorReason.QUOTA_BARRIER_NOT_DUE.value,
            queue_state=QueueState.WAITING_QUOTA.value,
            next_wake_utc=latest_barrier_instant.isoformat(),
        )

    chosen = waiting_quota_items[0]
    try:
        _auto_resume_one_waiting_quota_item_locked(
            queue_root, chosen.item_id, lock=lock, now_utc=now,
        )
    except QueueError as exc:
        return SupervisorResult(
            outcome=SupervisorOutcome.SAFETY_STOP.value,
            reason=f"{SupervisorReason.QUOTA_AUTO_RESUME_SAFETY_STOP.value}:{exc.reason}",
            item_id=chosen.item_id,
            queue_state=QueueState.WAITING_QUOTA.value,
        )

    result = _run_next_locked(
        queue_root, lock=lock, executor=executor, quota_classifier=quota_classifier,
    )
    return _from_run_next_result(result, context="QUOTA_AUTO_RESUME", auto_resumed_item_id=chosen.item_id)


def supervisor_once(
    queue_root: Path,
    *,
    executor=None,
    quota_classifier=None,
    wait_for_lock: bool = False,
    now_utc: Optional[datetime] = None,
) -> SupervisorResult:
    """Executes at most one governed dispatch cycle (RUNNER-1.5F-B2A;
    hardened RUNNER-1.5F-B2A-FIX1 to close the TOCTOU window between policy
    planning and dispatch).

    Never sleeps, never polls and invokes the Claude executor at most once.
    Acquires exactly ONE authoritative exclusive QueueLock before its first
    `list_items()`/global-state observation and holds that SAME lock
    continuously through policy evaluation and, when applicable, orphan
    recovery, quota auto-resume, fresh attempt creation, executor
    invocation and final attempt persistence - released only in `finally`
    once the cycle is fully decided/dispatched. There is no unlock gap
    between an all-due quota auto-resume and the subsequent dispatch: both
    happen via lock-held primitives (`_run_next_locked`,
    `_auto_resume_one_waiting_quota_item_locked`) that require this same
    held lock and never acquire or release one themselves, so a governed
    concurrent mutation can never occur between this cycle's policy
    observation and its authoritative dispatch. Policy, in strict order,
    all evaluated under that one held lock:

    1. Any RUNNING item defers entirely to `_run_next_locked`'s own orphan-
       recovery path (which stops before dispatching anything), so no
       Claude invocation happens this cycle.
    2. Any BLOCKED_ON_CHECKPOINT item stops with an operator-required
       outcome; nothing is dispatched.
    3. Any WAITING_QUOTA item is a global barrier for this single-provider
       queue (see `_handle_quota_barrier`): manual/operator-required when
       reset timing cannot be trusted, a non-mutating wait with a
       conservative `next_wake_utc` when not yet due, or an at-most-one
       automatic requeue plus at most one ordinary dispatch (both under the
       same held lock) when every barrier item is due.
    4. Otherwise, delegates directly to `_run_next_locked` for at most one
       ordinary dispatch (or NO_WORK).

    Reuses the same dispatch body `run_next()` uses (via `_run_next_locked`)
    for every actual Claude dispatch; never duplicates Runner/queue
    execution logic, and never recursively acquires a second QueueLock.
    """
    now = _resolve_now_utc(now_utc)

    lock = QueueLock(queue_root)
    lock.acquire(blocking=wait_for_lock)
    try:
        items = list_items(queue_root)

        if any(QueueState(it.state) == QueueState.RUNNING for it in items):
            result = _run_next_locked(
                queue_root, lock=lock, executor=executor, quota_classifier=quota_classifier,
            )
            return _from_run_next_result(result, context="PLAIN")

        blocked = [it for it in items if QueueState(it.state) == QueueState.BLOCKED_ON_CHECKPOINT]
        if blocked:
            first = blocked[0]
            return SupervisorResult(
                outcome=SupervisorOutcome.OPERATOR_REQUIRED.value,
                reason=SupervisorReason.CHECKPOINT_PENDING_RECONCILIATION.value,
                item_id=first.item_id,
                queue_state=first.state,
            )

        waiting_quota = [it for it in items if QueueState(it.state) == QueueState.WAITING_QUOTA]
        if waiting_quota:
            return _handle_quota_barrier(
                queue_root, waiting_quota, now,
                lock=lock, executor=executor, quota_classifier=quota_classifier,
            )

        result = _run_next_locked(
            queue_root, lock=lock, executor=executor, quota_classifier=quota_classifier,
        )
        return _from_run_next_result(result, context="PLAIN")
    finally:
        lock.release()


# ---------------------------------------------------------------------------
# Foreground governed long-running supervisor loop (RUNNER-1.5F-B2B)
# ---------------------------------------------------------------------------
#
# `run_supervisor_loop()` is a thin orchestration layer over `supervisor_
# once()`: it never duplicates queue policy or Claude execution logic, and
# it never invokes the Claude executor more than once per underlying
# `supervisor_once()` call. See the RUNNER-1.5F-B2B module docstring
# paragraph above for the full per-outcome policy.

class SupervisorLoopOutcome(str, Enum):
    NO_WORK = "NO_WORK"
    LIMIT_REACHED = "LIMIT_REACHED"
    OPERATOR_REQUIRED = "OPERATOR_REQUIRED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    SAFETY_STOP = "SAFETY_STOP"
    INTERRUPTED = "INTERRUPTED"


class SupervisorLoopReason(str, Enum):
    """Loop-only termination reasons. A pass-through termination (NO_WORK,
    OPERATOR_REQUIRED, RECOVERY_REQUIRED, SAFETY_STOP) instead reuses the
    triggering `SupervisorResult.reason` verbatim, so operator evidence
    keeps the full detail `supervisor_once()` already produced."""

    MAX_CYCLES_REACHED = "MAX_CYCLES_REACHED"
    MAX_RUNTIME_REACHED = "MAX_RUNTIME_REACHED"
    INTERRUPTED_DURING_QUOTA_SLEEP = "INTERRUPTED_DURING_QUOTA_SLEEP"
    UNUSABLE_NEXT_WAKE_UTC = "UNUSABLE_NEXT_WAKE_UTC"


@dataclass
class SupervisorLoopResult:
    """Compact, structured outcome of one `run_supervisor_loop()` call.
    Carries no conversational/session/Claude transcript content - only
    enough for an operator (or the `supervise` CLI) to see what happened
    across an entire unattended foreground run."""

    outcome: str
    reason: str
    cycles: int = 0
    dispatch_count: int = 0
    elapsed_seconds: float = 0.0
    last_item_id: Optional[str] = None
    last_attempt_id: Optional[str] = None
    last_queue_state: Optional[str] = None
    last_runner_state: Optional[str] = None
    next_wake_utc: Optional[str] = None


def _default_wall_clock() -> datetime:
    return datetime.now(timezone.utc)


def _parse_aware_utc(raw) -> Optional[datetime]:
    """Conservative ISO-8601 parse/validate helper for a `next_wake_utc`
    value returned by `supervisor_once()`. Returns a timezone-aware UTC
    `datetime`, or `None` for anything malformed, naive, or otherwise
    unusable - this loop never guesses a duration or scans arbitrary text."""
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    try:
        return parsed.astimezone(timezone.utc)
    except (OverflowError, ValueError):
        return None


def _validate_positive_int(value, name: str) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise QueueError("INVALID_LOOP_BOUND", f"{name} must be a positive integer when provided")
    return value


def _validate_positive_number(value, name: str) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise QueueError("INVALID_LOOP_BOUND", f"{name} must be a positive number when provided")
    return float(value)


def _loop_result(
    outcome: SupervisorLoopOutcome,
    reason: str,
    *,
    cycles: int,
    dispatch_count: int,
    elapsed_seconds: float,
    source: Optional[SupervisorResult] = None,
    next_wake_utc: Optional[str] = None,
) -> SupervisorLoopResult:
    return SupervisorLoopResult(
        outcome=outcome.value,
        reason=reason,
        cycles=cycles,
        dispatch_count=dispatch_count,
        elapsed_seconds=elapsed_seconds,
        last_item_id=source.item_id if source else None,
        last_attempt_id=source.attempt_id if source else None,
        last_queue_state=source.queue_state if source else None,
        last_runner_state=source.runner_state if source else None,
        next_wake_utc=next_wake_utc,
    )


_LOOP_STOP_OUTCOME_BY_SUPERVISOR_OUTCOME = {
    SupervisorOutcome.OPERATOR_REQUIRED.value: SupervisorLoopOutcome.OPERATOR_REQUIRED,
    SupervisorOutcome.RECOVERY_REQUIRED.value: SupervisorLoopOutcome.RECOVERY_REQUIRED,
    SupervisorOutcome.SAFETY_STOP.value: SupervisorLoopOutcome.SAFETY_STOP,
}


def run_supervisor_loop(
    queue_root: Path,
    *,
    executor=None,
    quota_classifier=None,
    wait_for_lock: bool = False,
    supervisor=None,
    max_cycles: Optional[int] = None,
    max_runtime_seconds: Optional[float] = None,
    clock=None,
    monotonic_clock=None,
    sleeper=None,
) -> SupervisorLoopResult:
    """Foreground, single-worker, governed supervisor loop (RUNNER-1.5F-B2B).

    Repeatedly calls `supervisor_once()` (or the injected `supervisor`,
    which mirrors `executor` purely for isolating loop policy in tests -
    production always defaults to the real `supervisor_once()`) exactly
    once per cycle and decides STOP/WAIT/CONTINUE from its structured
    `SupervisorResult` alone; it never invokes an executor directly and
    never bypasses `supervisor_once()`. See the RUNNER-1.5F-B2B module
    docstring paragraph for the exact per-outcome policy, including the
    `max_cycles`/`max_runtime_seconds` safety bounds and the sole
    WAITING_QUOTA sleeping condition.

    `max_cycles` and `max_runtime_seconds` (RUNNER-1.5F-B2B), when provided,
    must be positive; `max_runtime_seconds` is measured with the
    injectable `monotonic_clock` (default `time.monotonic`), never the wall
    clock. `clock` (default: `datetime.now(timezone.utc)`) supplies the
    aware UTC "now" used both to call `supervisor_once(now_utc=...)` and to
    compute the WAITING_QUOTA sleep delay; a naive or otherwise non-aware
    return value fails closed (`QueueError`). `sleeper` (default
    `time.sleep`) is only ever called with a strictly positive delay, and
    only when that delay is strictly less than the remaining
    `max_runtime_seconds` budget (RUNNER-1.5F-B2B-FIX1), recomputed from
    `monotonic_clock` immediately before sleeping; a delay that is greater
    than or equal to the remaining budget - or a remaining budget that is
    already exhausted - returns `LIMIT_REACHED`/`MAX_RUNTIME_REACHED`
    immediately instead of sleeping or truncating the delay.
    """
    max_cycles = _validate_positive_int(max_cycles, "max_cycles")
    max_runtime_seconds = _validate_positive_number(max_runtime_seconds, "max_runtime_seconds")

    supervisor_fn = supervisor or supervisor_once
    clock_fn = clock or _default_wall_clock
    monotonic_fn = monotonic_clock or time.monotonic
    sleeper_fn = sleeper or time.sleep

    start_monotonic = monotonic_fn()
    cycles = 0
    dispatch_count = 0
    last_dispatch: Optional[SupervisorResult] = None

    def _elapsed() -> float:
        return monotonic_fn() - start_monotonic

    while True:
        if max_cycles is not None and cycles >= max_cycles:
            return _loop_result(
                SupervisorLoopOutcome.LIMIT_REACHED, SupervisorLoopReason.MAX_CYCLES_REACHED.value,
                cycles=cycles, dispatch_count=dispatch_count, elapsed_seconds=_elapsed(),
                source=last_dispatch,
            )
        if max_runtime_seconds is not None and _elapsed() >= max_runtime_seconds:
            return _loop_result(
                SupervisorLoopOutcome.LIMIT_REACHED, SupervisorLoopReason.MAX_RUNTIME_REACHED.value,
                cycles=cycles, dispatch_count=dispatch_count, elapsed_seconds=_elapsed(),
                source=last_dispatch,
            )

        now = clock_fn()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise QueueError("INVALID_CLOCK", "clock() must return a timezone-aware datetime")
        now = now.astimezone(timezone.utc)

        result = supervisor_fn(
            queue_root, executor=executor, quota_classifier=quota_classifier,
            wait_for_lock=wait_for_lock, now_utc=now,
        )
        cycles += 1

        if result.outcome == SupervisorOutcome.DISPATCHED.value:
            dispatch_count += 1
            last_dispatch = result
            continue

        if result.outcome == SupervisorOutcome.NO_WORK.value:
            return _loop_result(
                SupervisorLoopOutcome.NO_WORK, result.reason,
                cycles=cycles, dispatch_count=dispatch_count, elapsed_seconds=_elapsed(),
                source=result,
            )

        stop_outcome = _LOOP_STOP_OUTCOME_BY_SUPERVISOR_OUTCOME.get(result.outcome)
        if stop_outcome is not None:
            return _loop_result(
                stop_outcome, result.reason,
                cycles=cycles, dispatch_count=dispatch_count, elapsed_seconds=_elapsed(),
                source=result,
            )

        if result.outcome == SupervisorOutcome.WAITING_QUOTA.value:
            next_wake = _parse_aware_utc(result.next_wake_utc)
            if next_wake is None:
                return _loop_result(
                    SupervisorLoopOutcome.SAFETY_STOP, SupervisorLoopReason.UNUSABLE_NEXT_WAKE_UTC.value,
                    cycles=cycles, dispatch_count=dispatch_count, elapsed_seconds=_elapsed(),
                    source=result, next_wake_utc=result.next_wake_utc,
                )
            delay = (next_wake - now).total_seconds()
            if delay > 0:
                if max_runtime_seconds is not None:
                    remaining = max_runtime_seconds - _elapsed()
                    if remaining <= 0 or delay >= remaining:
                        return _loop_result(
                            SupervisorLoopOutcome.LIMIT_REACHED, SupervisorLoopReason.MAX_RUNTIME_REACHED.value,
                            cycles=cycles, dispatch_count=dispatch_count, elapsed_seconds=_elapsed(),
                            source=result, next_wake_utc=next_wake.isoformat(),
                        )
                try:
                    sleeper_fn(delay)
                except KeyboardInterrupt:
                    return _loop_result(
                        SupervisorLoopOutcome.INTERRUPTED,
                        SupervisorLoopReason.INTERRUPTED_DURING_QUOTA_SLEEP.value,
                        cycles=cycles, dispatch_count=dispatch_count, elapsed_seconds=_elapsed(),
                        source=last_dispatch, next_wake_utc=next_wake.isoformat(),
                    )
            continue

        raise QueueError(
            "UNKNOWN_SUPERVISOR_OUTCOME",
            f"run_supervisor_loop received an unrecognized supervisor_once outcome: {result.outcome!r}",
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _default_repo_path() -> str:
    return str(Path.cwd())


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="claude_queue",
        description=(
            "Durable single-worker queue and governed run-next dispatcher for "
            "Claude Runner V1.5. May execute at most one queued Work Order per "
            "run-next through claude_runner.execute_work_order, with "
            "conservative post-invocation quota detection (RUNNER-1.5F-A). "
            "Does not replay checkpoints or resume quota automatically, retry "
            "automatically, commit, push, merge, switch branches, create "
            "worktrees, or schedule multiple workers."
        ),
    )
    parser.add_argument(
        "--queue-root", default=None,
        help="Queue root directory (default: <repo>/runtime/claude_runner/queue).",
    )
    parser.add_argument(
        "--repo", default=None,
        help="Repository path associated with the queue root default (default: cwd).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    enqueue_p = subparsers.add_parser("enqueue", help="Enqueue one Work Order.")
    enqueue_p.add_argument("--work-order", required=True, help="Path to a UTF-8 Work Order text file.")
    enqueue_p.add_argument("--repository-path", required=True, help="Target repository path for this item.")
    enqueue_p.add_argument("--mode", default="read-only", help="Requested execution mode (default: read-only).")
    enqueue_p.add_argument("--authorize-path", dest="authorize_path", action="append", default=None)
    enqueue_p.add_argument("--timeout-seconds", type=int, default=None)
    enqueue_p.add_argument("--model", default=None)
    enqueue_p.add_argument("--label", default=None)

    subparsers.add_parser("status", help="List all queue items (deterministic order).")

    recover_p = subparsers.add_parser(
        "recover", help="Acquire the exclusive queue lock and recover orphaned RUNNING items."
    )
    recover_p.add_argument("--wait", action="store_true", help="Block until the lock is available.")

    run_next_p = subparsers.add_parser(
        "run-next",
        help=(
            "Acquire the exclusive queue lock, recover orphaned RUNNING "
            "items if any (stopping without dispatch when it does), "
            "otherwise execute at most one QUEUED item through the "
            "governed Claude Runner."
        ),
    )
    run_next_p.add_argument(
        "--wait", action="store_true", help="Block until the queue lock is available."
    )

    capture_checkpoint_p = subparsers.add_parser(
        "capture-checkpoint",
        help=(
            "Acquire the exclusive queue lock and (re)capture the durable "
            "repository checkpoint for a BLOCKED_ON_CHECKPOINT item whose "
            "earlier capture failed. Never invokes Claude/claude_runner."
        ),
    )
    capture_checkpoint_p.add_argument("--item-id", required=True, help="Queue item id.")
    capture_checkpoint_p.add_argument(
        "--wait", action="store_true", help="Block until the queue lock is available."
    )

    reconcile_p = subparsers.add_parser(
        "reconcile",
        help=(
            "Acquire the exclusive queue lock and explicitly reconcile a "
            "BLOCKED_ON_CHECKPOINT item with a verified checkpoint and a "
            "clean target repository. Never commits/restores/resets/cleans. "
            "FAIL may also terminally reject an item whose checkpoint fails "
            "its own integrity check (missing/corrupt blob, hash mismatch) "
            "so a corrupted checkpoint is never a permanent dead end; ACCEPT "
            "and RETRY always still fail closed on a corrupted checkpoint."
        ),
    )
    reconcile_p.add_argument("--item-id", required=True, help="Queue item id.")
    reconcile_p.add_argument(
        "--resolution", required=True, choices=list(RECONCILE_RESOLUTIONS),
        help="Exactly one operator resolution: ACCEPT, FAIL or RETRY.",
    )
    reconcile_p.add_argument(
        "--note", required=True, help="Non-empty operator note/reason for this reconciliation."
    )
    reconcile_p.add_argument(
        "--wait", action="store_true", help="Block until the queue lock is available."
    )

    resume_quota_p = subparsers.add_parser(
        "resume-quota",
        help=(
            "Acquire the exclusive queue lock and explicitly requeue a "
            "WAITING_QUOTA item as a fresh attempt (WAITING_QUOTA->QUEUED). "
            "Requires a clean target repository and a non-empty operator "
            "note. Never invokes Claude/claude_runner."
        ),
    )
    resume_quota_p.add_argument("--item-id", required=True, help="Queue item id.")
    resume_quota_p.add_argument(
        "--note", required=True, help="Non-empty operator note/reason for this resume."
    )
    resume_quota_p.add_argument(
        "--wait", action="store_true", help="Block until the queue lock is available."
    )

    supervisor_once_p = subparsers.add_parser(
        "supervisor-once",
        help=(
            "Execute exactly one governed supervisor dispatch cycle: defers "
            "to run-next's orphan recovery for a RUNNING item, stops for a "
            "BLOCKED_ON_CHECKPOINT item, honors the WAITING_QUOTA barrier "
            "(manual/operator-required, a deterministic next_wake_utc, or "
            "at most one automatic requeue), then performs at most one "
            "ordinary run-next dispatch. Never sleeps, polls or loops."
        ),
    )
    supervisor_once_p.add_argument(
        "--wait", action="store_true", help="Block until the queue lock is available."
    )

    supervise_p = subparsers.add_parser(
        "supervise",
        help=(
            "Foreground, single-worker, governed supervisor loop (RUNNER-1.5F-B2B): "
            "repeatedly runs supervisor-once's cycle, continuing immediately on "
            "DISPATCHED, sleeping only for a trusted WAITING_QUOTA next_wake_utc, "
            "and stopping immediately (no automatic retry) on NO_WORK, "
            "OPERATOR_REQUIRED, RECOVERY_REQUIRED, SAFETY_STOP, or an optional "
            "--max-cycles/--max-runtime-seconds bound. Does not daemonize, detach "
            "or spawn workers; suitable to leave running in a terminal."
        ),
    )
    supervise_p.add_argument(
        "--wait", action="store_true", help="Block on lock contention within each cycle."
    )
    supervise_p.add_argument(
        "--max-cycles", type=int, default=None,
        help="Optional positive cap on the number of supervisor-once cycles.",
    )
    supervise_p.add_argument(
        "--max-runtime-seconds", type=float, default=None,
        help="Optional positive monotonic runtime budget in seconds.",
    )

    return parser


def _resolve_queue_root_from_args(args: argparse.Namespace) -> Path:
    repo = Path(args.repo).resolve() if args.repo else Path(_default_repo_path()).resolve()
    return resolve_queue_root(repo, args.queue_root)


def _cmd_enqueue(args: argparse.Namespace) -> int:
    wo_path = Path(args.work_order)
    try:
        text = wo_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"error: could not read Work Order file as UTF-8: {exc}", file=sys.stderr)
        return 11
    queue_root = _resolve_queue_root_from_args(args)
    try:
        item = enqueue(
            queue_root,
            work_order_text=text,
            repository_path=args.repository_path,
            mode=args.mode,
            authorize_path=args.authorize_path,
            timeout_seconds=args.timeout_seconds,
            model=args.model,
            label=args.label,
        )
    except QueueError as exc:
        print(f"error: {exc.reason}: {exc.message}", file=sys.stderr)
        return 1
    print(f"item_id={item.item_id} state={item.state}")
    print(f"queue_root={queue_root}")
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    queue_root = _resolve_queue_root_from_args(args)
    try:
        items = list_items(queue_root)
    except QueueError as exc:
        print(f"error: {exc.reason}: {exc.message}", file=sys.stderr)
        return 1
    for item in items:
        print(f"{item.item_id}\t{item.state}\t{item.created_at_utc}\t{item.repository_path}")
    return 0


def _cmd_recover(args: argparse.Namespace) -> int:
    queue_root = _resolve_queue_root_from_args(args)
    lock = QueueLock(queue_root)
    try:
        lock.acquire(blocking=args.wait)
    except QueueLockError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    try:
        try:
            recovered = recover_orphaned_running_items(queue_root, lock=lock)
        except QueueError as exc:
            print(f"error: {exc.reason}: {exc.message}", file=sys.stderr)
            return 1
    finally:
        lock.release()
    for item in recovered:
        print(f"recovered item_id={item.item_id} -> {item.state}")
    print(f"recovered_count={len(recovered)}")
    return 0


def _cmd_run_next(args: argparse.Namespace) -> int:
    queue_root = _resolve_queue_root_from_args(args)
    try:
        result = run_next(queue_root, wait_for_lock=args.wait)
    except QueueLockError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except QueueError as exc:
        print(f"error: {exc.reason}: {exc.message}", file=sys.stderr)
        return 1

    if result.outcome == RunNextOutcome.NO_WORK.value:
        print("outcome=NO_WORK")
        return 0
    if result.outcome == RunNextOutcome.RECOVERY_REQUIRED.value:
        print(
            "outcome=RECOVERY_REQUIRED recovered_item_ids="
            + ",".join(result.recovered_item_ids)
        )
        return 0
    print(
        f"outcome=DISPATCHED item_id={result.item_id} attempt_id={result.attempt_id} "
        f"queue_state={result.queue_state} runner_state={result.runner_state}"
    )
    return 0


def _cmd_capture_checkpoint(args: argparse.Namespace) -> int:
    queue_root = _resolve_queue_root_from_args(args)
    try:
        item = capture_checkpoint_for_item(queue_root, args.item_id, wait_for_lock=args.wait)
    except QueueLockError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except QueueError as exc:
        print(f"error: {exc.reason}: {exc.message}", file=sys.stderr)
        return 1
    checkpoint_id = item.checkpoints[-1]["checkpoint_id"] if item.checkpoints else None
    print(f"item_id={item.item_id} state={item.state} checkpoint_id={checkpoint_id}")
    return 0


def _cmd_reconcile(args: argparse.Namespace) -> int:
    queue_root = _resolve_queue_root_from_args(args)
    try:
        item = reconcile_checkpoint(
            queue_root, args.item_id, args.resolution, note=args.note, wait_for_lock=args.wait,
        )
    except QueueLockError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except QueueError as exc:
        print(f"error: {exc.reason}: {exc.message}", file=sys.stderr)
        return 1
    print(f"item_id={item.item_id} resolution={args.resolution} state={item.state}")
    return 0


def _cmd_resume_quota(args: argparse.Namespace) -> int:
    queue_root = _resolve_queue_root_from_args(args)
    try:
        item = resume_waiting_quota(
            queue_root, args.item_id, note=args.note, wait_for_lock=args.wait,
        )
    except QueueLockError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except QueueError as exc:
        print(f"error: {exc.reason}: {exc.message}", file=sys.stderr)
        return 1
    print(f"item_id={item.item_id} state={item.state}")
    return 0


def _cmd_supervisor_once(args: argparse.Namespace) -> int:
    queue_root = _resolve_queue_root_from_args(args)
    try:
        result = supervisor_once(queue_root, wait_for_lock=args.wait)
    except QueueLockError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except QueueError as exc:
        print(f"error: {exc.reason}: {exc.message}", file=sys.stderr)
        return 1

    fields = [f"outcome={result.outcome}", f"reason={result.reason}"]
    if result.item_id is not None:
        fields.append(f"item_id={result.item_id}")
    if result.attempt_id is not None:
        fields.append(f"attempt_id={result.attempt_id}")
    if result.queue_state is not None:
        fields.append(f"queue_state={result.queue_state}")
    if result.runner_state is not None:
        fields.append(f"runner_state={result.runner_state}")
    if result.next_wake_utc is not None:
        fields.append(f"next_wake_utc={result.next_wake_utc}")
    if result.recovered_item_ids:
        fields.append("recovered_item_ids=" + ",".join(result.recovered_item_ids))
    if result.auto_resumed_item_id is not None:
        fields.append(f"auto_resumed_item_id={result.auto_resumed_item_id}")
    print(" ".join(fields))
    return 0


# Exit codes are stable/machine-readable: clean/non-error termination (drained
# queue or a configured limit) is 0; every governed stop that requires human
# intervention gets its own distinct nonzero code so scripts/operators can
# branch on it without parsing text; INTERRUPTED uses the conventional
# SIGINT shell exit code (128 + SIGINT).
_SUPERVISE_EXIT_CODES = {
    SupervisorLoopOutcome.NO_WORK.value: 0,
    SupervisorLoopOutcome.LIMIT_REACHED.value: 0,
    SupervisorLoopOutcome.OPERATOR_REQUIRED.value: 3,
    SupervisorLoopOutcome.RECOVERY_REQUIRED.value: 4,
    SupervisorLoopOutcome.SAFETY_STOP.value: 5,
    SupervisorLoopOutcome.INTERRUPTED.value: 130,
}


def _cmd_supervise(args: argparse.Namespace) -> int:
    queue_root = _resolve_queue_root_from_args(args)
    try:
        result = run_supervisor_loop(
            queue_root,
            wait_for_lock=args.wait,
            max_cycles=args.max_cycles,
            max_runtime_seconds=args.max_runtime_seconds,
        )
    except QueueLockError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except QueueError as exc:
        print(f"error: {exc.reason}: {exc.message}", file=sys.stderr)
        return 1

    fields = [
        f"outcome={result.outcome}",
        f"reason={result.reason}",
        f"cycles={result.cycles}",
        f"dispatch_count={result.dispatch_count}",
        f"elapsed_seconds={result.elapsed_seconds:.3f}",
    ]
    if result.last_item_id is not None:
        fields.append(f"last_item_id={result.last_item_id}")
    if result.last_attempt_id is not None:
        fields.append(f"last_attempt_id={result.last_attempt_id}")
    if result.last_queue_state is not None:
        fields.append(f"last_queue_state={result.last_queue_state}")
    if result.last_runner_state is not None:
        fields.append(f"last_runner_state={result.last_runner_state}")
    if result.next_wake_utc is not None:
        fields.append(f"next_wake_utc={result.next_wake_utc}")
    print(" ".join(fields))
    return _SUPERVISE_EXIT_CODES.get(result.outcome, 1)


def main(argv: Optional[list] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.command == "enqueue":
        return _cmd_enqueue(args)
    if args.command == "status":
        return _cmd_status(args)
    if args.command == "recover":
        return _cmd_recover(args)
    if args.command == "run-next":
        return _cmd_run_next(args)
    if args.command == "capture-checkpoint":
        return _cmd_capture_checkpoint(args)
    if args.command == "reconcile":
        return _cmd_reconcile(args)
    if args.command == "resume-quota":
        return _cmd_resume_quota(args)
    if args.command == "supervisor-once":
        return _cmd_supervisor_once(args)
    if args.command == "supervise":
        return _cmd_supervise(args)
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
