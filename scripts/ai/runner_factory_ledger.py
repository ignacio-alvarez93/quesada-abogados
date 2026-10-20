"""Runner V2.1 (R21-C) factory ledger: persistent operational history.

Gives Runner a durable answer to questions no single pipeline's own state can
answer alone: what is running right now (across every pipeline), what ran
previously, which provider/role worked which module, what worktree/branch/
commit was involved, what the result was, whether it was certified, and who
closed it. This is infrastructure for a future multi-module "Fabric"; nothing
here depends on Fabric existing yet.

Layout (under `<factory_root>/`, a sibling of `<state_root>/<pipeline_id>/`)::

    events.jsonl   append-only event log - the ONLY source of truth.
    modules.json   materialized current-state cache, fully rebuildable from
                   events.jsonl by `materialize_modules` and rewritten after
                   every append (mirrors the `pipeline_result.json` pattern in
                   `runner_pipeline.py`: a derived, disposable convenience
                   file). A missing or corrupt cache never loses history - it
                   is not read back by anything here, only served to callers
                   as a fast path; `factory-status`/`factory-history` can
                   equally be answered by replaying `events.jsonl` alone.

Deliberately no `executions/` directory: an execution's full evidence
(stdout/stderr/prompt/etc.) already lives under the owning pipeline's own
`workers/<id>/evidence/`. The ledger stores only identifiers, short result
codes and commit hashes - never prompts, transcripts or credentials - so
`extra` is scrubbed of anything secret-shaped or transcript-sized before it
is ever written (see `_scrub_extra`).

Event families (each has a real reader below: `materialize_modules` and/or
`factory_status` fold every one of them into what they report):

    WORKER_STARTED / WORKER_FINISHED   one governed attempt (module optional)
    WORK_PRODUCT_CREATED               attempt left a resumable checkpoint
    CHECKPOINT_CREATED                 a module's work was checkpointed
    CERTIFICATION_STARTED/FINISHED     an external certification pass
    MODULE_STATE_CHANGED               a module-scoped attempt's outcome
    MODULE_CERTIFIED                   a module was certified
    MODULE_CLOSED                      a module's lifecycle was closed

`runner_pipeline.PipelineRunner` is today's only automatic producer, and it
only emits WORKER_STARTED/WORKER_FINISHED/WORK_PRODUCT_CREATED/
MODULE_STATE_CHANGED (the ones it can truthfully observe: it never certifies
or closes anything). CHECKPOINT_CREATED/CERTIFICATION_*/MODULE_CERTIFIED/
MODULE_CLOSED are for an external certifier/closer (this project's own
"checkpoint" / "close" workflow, or a future Fabric orchestrator) to record
through this same API; the read side (`materialize_modules`, `factory_status`,
`factory-history`) already understands them.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

try:
    from scripts.ai import claude_queue as queue
except ImportError:  # pragma: no cover - direct script execution
    _this_dir = Path(__file__).resolve().parent
    if str(_this_dir) not in sys.path:
        sys.path.insert(0, str(_this_dir))
    import claude_queue as queue  # type: ignore[no-redef]


LEDGER_SCHEMA_VERSION = 1

EVENTS_FILENAME = "events.jsonl"
MODULES_FILENAME = "modules.json"
LOCK_DIRNAME = "lock"

WORKER_STARTED = "WORKER_STARTED"
WORKER_FINISHED = "WORKER_FINISHED"
WORK_PRODUCT_CREATED = "WORK_PRODUCT_CREATED"
CHECKPOINT_CREATED = "CHECKPOINT_CREATED"
CERTIFICATION_STARTED = "CERTIFICATION_STARTED"
CERTIFICATION_FINISHED = "CERTIFICATION_FINISHED"
MODULE_STATE_CHANGED = "MODULE_STATE_CHANGED"
MODULE_CERTIFIED = "MODULE_CERTIFIED"
MODULE_CLOSED = "MODULE_CLOSED"

EVENT_TYPES = frozenset({
    WORKER_STARTED, WORKER_FINISHED, WORK_PRODUCT_CREATED, CHECKPOINT_CREATED,
    CERTIFICATION_STARTED, CERTIFICATION_FINISHED, MODULE_STATE_CHANGED,
    MODULE_CERTIFIED, MODULE_CLOSED,
})

_CERTIFICATION_EVENTS = frozenset({CERTIFICATION_STARTED, CERTIFICATION_FINISHED, MODULE_CERTIFIED})

# Every field an event MAY carry ("where relevant" - None otherwise). Never
# extend this with anything credential-, prompt- or transcript-shaped.
_EVENT_FIELDS = (
    "project", "module", "module_version",
    "pipeline_id", "worker_id", "provider", "role",
    "worktree", "branch", "base_commit", "result_commit",
    "state", "state_reason", "certification_status", "closer",
)

_SECRET_LIKE_KEYS = frozenset({
    "prompt", "prompt_text", "transcript", "token", "api_key", "apikey", "credential",
    "credentials", "authorization", "password", "secret", "stdout", "stderr",
})
_MAX_EXTRA_VALUE_LEN = 500


class FactoryLedgerError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _scrub_extra(extra: dict) -> dict:
    """`extra` is for small descriptive tags only. Anything secret-shaped by
    name, or too large to plausibly be a tag (a transcript, not a label), is
    dropped rather than truncated - truncating a secret still leaks a
    prefix of it."""
    clean = {}
    for key, value in extra.items():
        if not isinstance(key, str) or key.lower() in _SECRET_LIKE_KEYS:
            continue
        if isinstance(value, str) and len(value) > _MAX_EXTRA_VALUE_LEN:
            continue
        clean[key] = value
    return clean


def _build_event(event_type: str, event_id: str, timestamp_utc: str, fields: dict, extra: Optional[dict]) -> dict:
    event = {
        "schema_version": LEDGER_SCHEMA_VERSION, "event_id": event_id, "event_type": event_type,
        "timestamp_utc": timestamp_utc,
    }
    for name in _EVENT_FIELDS:
        event[name] = fields.get(name)
    if extra:
        scrubbed = _scrub_extra(extra)
        if scrubbed:
            event["extra"] = scrubbed
    return event


class FactoryLedger:
    """Append-only operational history plus a materialized-state cache. See
    the module docstring for the on-disk layout and durability model."""

    def __init__(
        self, root, *,
        clock: Optional[Callable[[], datetime]] = None,
        id_factory: Optional[Callable[[], str]] = None,
    ):
        self.root = Path(root)
        self.events_path = self.root / EVENTS_FILENAME
        self.modules_path = self.root / MODULES_FILENAME
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)

    def append(self, event_type: str, *, extra: Optional[dict] = None, **fields) -> dict:
        if event_type not in EVENT_TYPES:
            raise FactoryLedgerError("UNKNOWN_EVENT_TYPE", f"unknown factory event type {event_type!r}")
        unknown = set(fields) - set(_EVENT_FIELDS)
        if unknown:
            raise FactoryLedgerError(
                "UNKNOWN_EVENT_FIELD", f"unknown factory event field(s): {sorted(unknown)}",
            )
        event = _build_event(event_type, self._id_factory(), _iso(self._clock()), fields, extra)
        self.root.mkdir(parents=True, exist_ok=True)
        # Serializes concurrent appenders (threads within one orchestrator, or
        # several orchestrator processes) so the JSONL append and the derived
        # modules.json rewrite never interleave with another one's.
        lock = queue.QueueLock(self.root / LOCK_DIRNAME)
        lock.acquire(blocking=True)
        try:
            self._append_line(event)
            events, _skipped = read_events(self.root)
            try:
                queue._atomic_write_json(self.modules_path, materialize_modules(events))
            except OSError:
                # The cache is disposable; a failure to (re)write it must
                # never be mistaken for the append itself having failed.
                pass
        finally:
            lock.release()
        return event

    def _append_line(self, event: dict) -> None:
        line = json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n"
        with open(self.events_path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(line)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass

    def events(self, **filters) -> list:
        all_events, _skipped = read_events(self.root)
        return filter_events(all_events, **filters)

    def status(self) -> dict:
        all_events, _skipped = read_events(self.root)
        return factory_status(all_events)

    def modules(self) -> dict:
        all_events, _skipped = read_events(self.root)
        return materialize_modules(all_events)


def read_events(root) -> tuple:
    """Tolerant JSONL reader. Returns `(events, skipped_line_count)`, sorted
    by `(timestamp_utc, event_id)` for a deterministic order regardless of
    how they were appended. Any line that is not valid JSON, not an object,
    or not a recognized event type is skipped rather than raising - covers
    both a torn trailing line from a crash mid-write and any other form of
    corruption - so a damaged ledger degrades to "missing some history",
    never to a crash that could be mistaken for lost work results."""
    path = Path(root) / EVENTS_FILENAME
    events, skipped = [], 0
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return events, skipped
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            skipped += 1
            continue
        if isinstance(parsed, dict) and parsed.get("event_type") in EVENT_TYPES:
            events.append(parsed)
        else:
            skipped += 1
    events.sort(key=lambda e: (e.get("timestamp_utc") or "", e.get("event_id") or ""))
    return events, skipped


def filter_events(
    events, *, module=None, role=None, provider=None, pipeline_id=None, worker_id=None, event_type=None,
) -> list:
    def match(e: dict) -> bool:
        return (
            (module is None or e.get("module") == module)
            and (role is None or e.get("role") == role)
            and (provider is None or e.get("provider") == provider)
            and (pipeline_id is None or e.get("pipeline_id") == pipeline_id)
            and (worker_id is None or e.get("worker_id") == worker_id)
            and (event_type is None or e.get("event_type") == event_type)
        )
    return [e for e in events if match(e)]


def _module_key(event: dict) -> Optional[str]:
    module = event.get("module")
    if not module:
        return None
    version = event.get("module_version")
    return f"{module}@{version}" if version else module


def materialize_modules(events: list) -> dict:
    """Deterministic module lifecycle state folded from events IN ORDER
    (as returned by `read_events`/`FactoryLedger.events`). Same input order
    always yields the same output - nothing here reads the clock or the
    environment. Events without a `module` are execution history only
    (visible via `factory-history`) and never create a module entry."""
    modules: dict = {}
    for event in events:
        key = _module_key(event)
        if key is None:
            continue
        slot = modules.setdefault(key, {
            "module": event.get("module"), "module_version": event.get("module_version"),
            "state": None, "state_reason": None, "provider": None, "role": None,
            "pipeline_id": None, "worker_id": None, "worktree": None, "branch": None,
            "base_commit": None, "result_commit": None, "certification_status": None,
            "closer": None, "first_seen_utc": event.get("timestamp_utc"), "last_event_utc": None,
            "last_event_type": None, "event_count": 0,
        })
        slot["event_count"] += 1
        slot["last_event_utc"] = event.get("timestamp_utc")
        slot["last_event_type"] = event.get("event_type")
        for name in ("provider", "role", "pipeline_id", "worker_id", "worktree", "branch"):
            if event.get(name) is not None:
                slot[name] = event[name]
        if event.get("base_commit") is not None:
            slot["base_commit"] = event["base_commit"]
        if event.get("result_commit") is not None:
            slot["result_commit"] = event["result_commit"]
        if event.get("state") is not None:
            slot["state"] = event["state"]
            slot["state_reason"] = event.get("state_reason")
        if event["event_type"] in _CERTIFICATION_EVENTS and event.get("certification_status") is not None:
            slot["certification_status"] = event["certification_status"]
        if event["event_type"] == MODULE_CLOSED:
            slot["closer"] = event.get("closer")
    return modules


def factory_status(events: list) -> dict:
    """Currently-running workers, derived purely from the ledger: a
    WORKER_STARTED for a (pipeline_id, worker_id) pair with no later
    WORKER_FINISHED for that same pair is still active. Queued/waiting
    worker states live in each pipeline's own durable state (see
    `runner_pipeline.scan_factory_pipelines`), not in this event log."""
    open_by_key: dict = {}
    for event in events:
        key = (event.get("pipeline_id"), event.get("worker_id"))
        if key == (None, None):
            continue
        if event["event_type"] == WORKER_STARTED:
            open_by_key[key] = event
        elif event["event_type"] == WORKER_FINISHED:
            open_by_key.pop(key, None)
    active = [
        {
            "pipeline_id": k[0], "worker_id": k[1], "provider": e.get("provider"), "role": e.get("role"),
            "module": e.get("module"), "module_version": e.get("module_version"),
            "worktree": e.get("worktree"), "branch": e.get("branch"), "base_commit": e.get("base_commit"),
            "started_at_utc": e.get("timestamp_utc"),
        }
        for k, e in sorted(open_by_key.items(), key=lambda kv: kv[1].get("timestamp_utc") or "")
    ]
    return {
        "schema_version": LEDGER_SCHEMA_VERSION, "active_workers": active, "modules": materialize_modules(events),
    }
