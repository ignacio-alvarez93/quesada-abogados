"""FCP-9A-01: Scheduler contract V1 - pure, deterministic, fail-closed,
provider-neutral, NON-AUTHORITATIVE batch planning advisory.

Answers ONE question: given an explicit, immutable `ScheduleRequest` (one
batch of Work Order items of one DAG plus caller-supplied facts), which
items would be SCHEDULABLE now, which are WAITING, REFUSED or UNKNOWN, and
why? It never answers "may I dispatch now?".

Why this is a consultative plan, not a scheduler
------------------------------------------------
* Director and Runner stay the ONLY execution authorities. The Runner's own
  `PipelineRunner._start_ready` (leases, provider holds, `max_workers`,
  `provider_limits`, same-worktree conflicts, self-target refusal) decides
  at execution time. Nothing here starts, queues, leases, retries, merges,
  switches a provider, runs a process or shell, or touches Git, the
  filesystem, the clock, the environment or the network: stdlib only, no
  I/O, no mutable global state. The evaluation instant is the explicit
  `as_of_utc` input, never read from a clock.
* The planning order mirrors the Runner's dispatch order: highest
  `priority` first, then declared item order. The global cap mirrors
  `max_workers` (1..16, `runner_pipeline.MAX_PIPELINE_WORKERS`) and per-
  provider caps mirror `provider_limits`. A batch holds at most 64 items
  (`fabric_dag_blueprint.MAX_BLUEPRINT_NODES`). These are pinned by tests,
  not imported, so the contract never loads the Runner or a provider.
* Provider-neutral: `provider_id` is an optional, opaque, bounded id; no
  provider is named, preferred or special-cased anywhere in this module.
* Facts (`upstream_state`, `attested_capabilities`) are caller-supplied
  structured OBSERVATIONS, never provider prose. They only ever hold an
  item back; they can never widen what the item requested.

Request (`ScheduleRequest` + `ScheduleItem`, frozen; validated by
`plan_batch`, never by the constructor, so every malformed request yields an
explained refusal)
-----------------------------------------------------------------------------
* `dag_id`, `item_id`: safe single path segments (ASCII letters, digits,
  '-', '_', '.'; no leading '.'; at most 64 chars) - every accepted id is
  also a valid Runner worker/pipeline id. Separators, drive letters, '..'
  and control characters are refused, so no id can carry a path.
* `item_count`: the declared count; must equal `len(items)` (1..64).
* `items`: tuple of `ScheduleItem`, unique `item_id`.
* `priority`: real int in -1000..1000 (bool refused).
* `mode`: exactly "read-only" or "write" (Runner `MODE_*`).
* `required_capabilities` / `attested_capabilities`: tuples of exact Runner
  `Capability` names, no duplicates. `READ_FILES`/`SEARCH_FILES` are always
  required and `EDIT_FILES`/`WRITE_FILES` in write mode, exactly as
  `runner_providers.required_capabilities`. `SHELL` requires write mode.
  `attested_capabilities=None` means UNKNOWN.
* `depends_on`: tuple (at most 16) of OTHER item ids of this batch; self,
  unknown, duplicate and cyclic edges are refused.
* `upstream_state`: state of dependencies OUTSIDE this batch, one of
  `UPSTREAM_STATES`; defaults to UNKNOWN (fail closed).
* `as_of_utc`, `not_before_utc`, `deadline_utc`: timezone-aware ISO-8601
  strings (at most 40 ASCII chars); not_before must precede deadline.
* `concurrency_preference`: "SERIAL" (one slot) or "PARALLEL" (up to
  `max_concurrency`, 1..16). `provider_limits`: tuple of unique
  `(provider_id, limit)` pairs, limit 1..16.
* Every sequence must be a tuple and every scalar its exact type:
  lists/dicts/sets, bool-as-int and str/int subclasses are refused.

Decisions (per item; fixed vocabulary, none of them is a permit)
-----------------------------------------------------------------
* REFUSED: a definitive hold for this batch - window expired, upstream
  blocked, or a required capability not attested.
* UNKNOWN: a fact needed to decide is missing - upstream state unknown,
  capabilities unattested, or provider unassigned while provider limits
  apply. UNKNOWN is never schedulable and never consumes a slot.
* WAITING: window not open yet, upstream pending, an in-batch dependency
  (never planned concurrently with it), or no slot left (global or
  provider limit).
* SCHEDULABLE: no reason at all and a slot was assigned (`slot` 0..n-1 in
  planning order). Informational only.
Precedence: REFUSED > UNKNOWN > WAITING. Slots are assigned only to items
with no other reason, in planning order.

Batch outcome (most cautious summary): REFUSED for an invalid request
(no item is echoed), else UNKNOWN if any item is UNKNOWN, else SCHEDULABLE
if any item is, else WAITING if any item is, else REFUSED.

Output (`BatchPlan`, schema `fcp9a01-scheduler-batch-plan-v1`, version 1).
`to_dict()` / `canonical_json()` are deterministic, bounded by
`MAX_CANONICAL_JSON_BYTES`, and contain only validated ids, enumerated codes,
integers, a request fingerprint and booleans - there is no free-text input
field, so no Work Order text, path, secret or personal data can reach them.
Every plan fixes `certified`, `authorizes_action`, `execution_allowed`,
`dispatch_allowed`, `auto_retry_allowed`, `resume_allowed`,
`merging_allowed` and `provider_switch_authorized` to False as read-only
properties (not dataclass fields: no constructor, `dataclasses.replace` or
serialized input can set them).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

REQUEST_SCHEMA = "fcp9a01-scheduler-request-v1"
REQUEST_SCHEMA_VERSION = 1
SCHEMA = "fcp9a01-scheduler-batch-plan-v1"
SCHEMA_VERSION = 1
SCHEDULER_MARKER = "FCP9A01_SCHEDULE_ADVISORY_ONLY_NOT_CERTIFIED_NOT_AUTHORIZED"

# Mirrors runner_pipeline / fabric_dag_blueprint / runner_providers (pinned
# by tests; not imported, so the contract never loads the Runner).
MAX_ITEMS = 64
MAX_CONCURRENCY = 16
MAX_PROVIDER_LIMIT = 16
MAX_DEPENDS_ON = 16
MIN_PRIORITY = -1000
MAX_PRIORITY = 1000
MAX_TIMESTAMP_CHARS = 40
MAX_CANONICAL_JSON_BYTES = 131072

MODE_READ_ONLY = "read-only"
MODE_WRITE = "write"
MODES = (MODE_READ_ONLY, MODE_WRITE)
CAPABILITIES = (
    "READ_FILES", "SEARCH_FILES", "EDIT_FILES", "WRITE_FILES", "SHELL", "TEST_EXECUTION", "STRUCTURED_RESULT",
)
BASE_CAPABILITIES = frozenset({"READ_FILES", "SEARCH_FILES"})
WRITE_MODE_CAPABILITIES = frozenset({"EDIT_FILES", "WRITE_FILES"})
_CAPABILITY_SET = frozenset(CAPABILITIES)

_SAFE_ID_RE = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9._-]{0,63}")
_PROVIDER_ID_RE = re.compile(r"[a-z][a-z0-9-]{0,31}")
_FINGERPRINT_RE = re.compile(r"[0-9a-f]{64}")

CONCURRENCY_SERIAL = "SERIAL"
CONCURRENCY_PARALLEL = "PARALLEL"
CONCURRENCY_PREFERENCES = (CONCURRENCY_SERIAL, CONCURRENCY_PARALLEL)

UPSTREAM_NONE = "NONE"
UPSTREAM_SATISFIED = "SATISFIED"
UPSTREAM_PENDING = "PENDING"
UPSTREAM_BLOCKED = "BLOCKED"
UPSTREAM_UNKNOWN = "UNKNOWN"
UPSTREAM_STATES = (UPSTREAM_NONE, UPSTREAM_SATISFIED, UPSTREAM_PENDING, UPSTREAM_BLOCKED, UPSTREAM_UNKNOWN)

# Decisions (per item) and batch outcomes share one vocabulary.
SCHEDULABLE = "SCHEDULABLE"
WAITING = "WAITING"
REFUSED = "REFUSED"
UNKNOWN = "UNKNOWN"
DECISIONS = (SCHEDULABLE, WAITING, REFUSED, UNKNOWN)

# Request-level refusal codes, in their fixed canonical order.
REQUEST_NOT_TYPED = "REQUEST_NOT_TYPED"
SCHEMA_VERSION_UNSUPPORTED = "SCHEMA_VERSION_UNSUPPORTED"
DAG_ID_INVALID = "DAG_ID_INVALID"
ITEM_COUNT_INVALID = "ITEM_COUNT_INVALID"
ITEM_COUNT_MISMATCH = "ITEM_COUNT_MISMATCH"
ITEMS_NOT_TUPLE = "ITEMS_NOT_TUPLE"
ITEMS_EMPTY = "ITEMS_EMPTY"
ITEMS_TOO_MANY = "ITEMS_TOO_MANY"
ITEM_NOT_TYPED = "ITEM_NOT_TYPED"
ITEM_ID_INVALID = "ITEM_ID_INVALID"
ITEM_ID_DUPLICATE = "ITEM_ID_DUPLICATE"
PRIORITY_INVALID = "PRIORITY_INVALID"
MODE_UNKNOWN = "MODE_UNKNOWN"
PROVIDER_ID_INVALID = "PROVIDER_ID_INVALID"
CAPABILITIES_MALFORMED = "CAPABILITIES_MALFORMED"
CAPABILITY_UNKNOWN = "CAPABILITY_UNKNOWN"
CAPABILITY_DUPLICATE = "CAPABILITY_DUPLICATE"
SHELL_REQUIRES_WRITE_MODE = "SHELL_REQUIRES_WRITE_MODE"
ATTESTED_CAPABILITIES_MALFORMED = "ATTESTED_CAPABILITIES_MALFORMED"
DEPENDS_ON_MALFORMED = "DEPENDS_ON_MALFORMED"
DEPENDENCY_SELF = "DEPENDENCY_SELF"
DEPENDENCY_UNKNOWN = "DEPENDENCY_UNKNOWN"
DEPENDENCY_DUPLICATE = "DEPENDENCY_DUPLICATE"
DEPENDENCY_CYCLE = "DEPENDENCY_CYCLE"
UPSTREAM_STATE_INVALID = "UPSTREAM_STATE_INVALID"
CONCURRENCY_PREFERENCE_UNKNOWN = "CONCURRENCY_PREFERENCE_UNKNOWN"
MAX_CONCURRENCY_INVALID = "MAX_CONCURRENCY_INVALID"
PROVIDER_LIMITS_MALFORMED = "PROVIDER_LIMITS_MALFORMED"
PROVIDER_LIMIT_DUPLICATE = "PROVIDER_LIMIT_DUPLICATE"
AS_OF_INVALID = "AS_OF_INVALID"
WINDOW_INVALID = "WINDOW_INVALID"
WINDOW_INVERTED = "WINDOW_INVERTED"
REQUEST_TOO_LARGE = "REQUEST_TOO_LARGE"
REQUEST_REASONS = (
    REQUEST_NOT_TYPED, SCHEMA_VERSION_UNSUPPORTED, DAG_ID_INVALID, ITEM_COUNT_INVALID, ITEM_COUNT_MISMATCH,
    ITEMS_NOT_TUPLE, ITEMS_EMPTY, ITEMS_TOO_MANY, ITEM_NOT_TYPED, ITEM_ID_INVALID, ITEM_ID_DUPLICATE,
    PRIORITY_INVALID, MODE_UNKNOWN, PROVIDER_ID_INVALID, CAPABILITIES_MALFORMED, CAPABILITY_UNKNOWN,
    CAPABILITY_DUPLICATE, SHELL_REQUIRES_WRITE_MODE, ATTESTED_CAPABILITIES_MALFORMED, DEPENDS_ON_MALFORMED,
    DEPENDENCY_SELF, DEPENDENCY_UNKNOWN, DEPENDENCY_DUPLICATE, DEPENDENCY_CYCLE, UPSTREAM_STATE_INVALID,
    CONCURRENCY_PREFERENCE_UNKNOWN, MAX_CONCURRENCY_INVALID, PROVIDER_LIMITS_MALFORMED, PROVIDER_LIMIT_DUPLICATE,
    AS_OF_INVALID, WINDOW_INVALID, WINDOW_INVERTED, REQUEST_TOO_LARGE,
)

# Item-level reason codes, grouped by the decision they force, in their
# fixed canonical order.
WINDOW_EXPIRED = "WINDOW_EXPIRED"
UPSTREAM_IS_BLOCKED = "UPSTREAM_IS_BLOCKED"
CAPABILITY_NOT_ATTESTED = "CAPABILITY_NOT_ATTESTED"
UPSTREAM_STATE_UNKNOWN = "UPSTREAM_STATE_UNKNOWN"
CAPABILITIES_UNATTESTED = "CAPABILITIES_UNATTESTED"
PROVIDER_UNASSIGNED = "PROVIDER_UNASSIGNED"
WINDOW_NOT_OPEN = "WINDOW_NOT_OPEN"
UPSTREAM_IS_PENDING = "UPSTREAM_IS_PENDING"
DEPENDENCY_IN_BATCH = "DEPENDENCY_IN_BATCH"
CONCURRENCY_LIMIT_REACHED = "CONCURRENCY_LIMIT_REACHED"
PROVIDER_LIMIT_REACHED = "PROVIDER_LIMIT_REACHED"
REFUSING_REASONS = (WINDOW_EXPIRED, UPSTREAM_IS_BLOCKED, CAPABILITY_NOT_ATTESTED)
UNKNOWN_REASONS = (UPSTREAM_STATE_UNKNOWN, CAPABILITIES_UNATTESTED, PROVIDER_UNASSIGNED)
WAITING_REASONS = (
    WINDOW_NOT_OPEN, UPSTREAM_IS_PENDING, DEPENDENCY_IN_BATCH, CONCURRENCY_LIMIT_REACHED, PROVIDER_LIMIT_REACHED,
)
ITEM_REASONS = REFUSING_REASONS + UNKNOWN_REASONS + WAITING_REASONS

_UPSTREAM_REASON = {
    UPSTREAM_PENDING: UPSTREAM_IS_PENDING, UPSTREAM_BLOCKED: UPSTREAM_IS_BLOCKED,
    UPSTREAM_UNKNOWN: UPSTREAM_STATE_UNKNOWN,
}


def _is_int(value) -> bool:
    return type(value) is int


def _safe_id(value) -> bool:
    return type(value) is str and _SAFE_ID_RE.fullmatch(value) is not None


def _valid_provider_id(value) -> bool:
    return type(value) is str and _PROVIDER_ID_RE.fullmatch(value) is not None


def _str_tuple(value, limit: int) -> bool:
    return type(value) is tuple and len(value) <= limit and all(type(v) is str for v in value)


def _ordered(codes, vocabulary) -> tuple:
    return tuple(sorted(set(codes), key=vocabulary.index))


def _parse_utc(value) -> Optional[datetime]:
    if type(value) is not str or not 0 < len(value) <= MAX_TIMESTAMP_CHARS or not value.isascii():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _utc_text(value: Optional[datetime]) -> Optional[str]:
    return None if value is None else value.isoformat().replace("+00:00", "Z")


def _canonical(payload) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ScheduleItem:
    """One Work Order of the batch, by opaque id only (never its text).
    Validated by `plan_batch` (fail closed), not here."""
    item_id: str
    mode: str
    priority: int = 0
    provider_id: Optional[str] = None
    required_capabilities: tuple = ()
    attested_capabilities: Optional[tuple] = None
    depends_on: tuple = ()
    upstream_state: str = UPSTREAM_UNKNOWN


@dataclass(frozen=True)
class ScheduleRequest:
    """Explicit, immutable planning request for one batch of one DAG.
    Validated by `plan_batch` (fail closed), not here."""
    dag_id: str
    item_count: int
    items: tuple
    as_of_utc: str
    not_before_utc: Optional[str] = None
    deadline_utc: Optional[str] = None
    concurrency_preference: str = CONCURRENCY_SERIAL
    max_concurrency: int = 1
    provider_limits: tuple = ()
    schema_version: int = REQUEST_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _decision_for(reasons: tuple) -> str:
    if any(r in REFUSING_REASONS for r in reasons):
        return REFUSED
    if any(r in UNKNOWN_REASONS for r in reasons):
        return UNKNOWN
    if reasons:
        return WAITING
    return SCHEDULABLE


def _batch_outcome(decisions: tuple) -> str:
    present = {d.decision for d in decisions}
    for outcome in (UNKNOWN, SCHEDULABLE, WAITING):
        if outcome in present:
            return outcome
    return REFUSED


@dataclass(frozen=True)
class ItemDecision:
    """Per-item advisory decision. Construction re-derives `decision` from
    `reasons`, so a hand-made decision cannot claim more than its reasons."""
    item_id: str
    decision: str
    reasons: tuple
    priority: int
    slot: Optional[int]

    def __post_init__(self):
        if not _safe_id(self.item_id):
            raise ValueError("item_id must be a safe id")
        if not (type(self.reasons) is tuple and all(type(r) is str and r in ITEM_REASONS for r in self.reasons)
                and self.reasons == _ordered(self.reasons, ITEM_REASONS)):
            raise ValueError("reasons must be ordered item reason codes")
        if type(self.decision) is not str or self.decision != _decision_for(self.reasons):
            raise ValueError("decision must be exactly the one derived from reasons")
        if not (_is_int(self.priority) and MIN_PRIORITY <= self.priority <= MAX_PRIORITY):
            raise ValueError("priority must be a bounded int")
        if self.decision == SCHEDULABLE:
            if not (_is_int(self.slot) and 0 <= self.slot < MAX_CONCURRENCY):
                raise ValueError("a SCHEDULABLE item carries a slot")
        elif self.slot is not None:
            raise ValueError("only a SCHEDULABLE item carries a slot")

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id, "decision": self.decision, "reasons": list(self.reasons),
            "priority": self.priority, "slot": self.slot,
        }


class _NotAuthorized:
    """Fixed, read-only zero-authority guarantees (not dataclass fields, so no
    constructor, `dataclasses.replace` or serialization input can set them)."""

    @property
    def certified(self) -> bool:
        return False

    @property
    def authorizes_action(self) -> bool:
        return False

    @property
    def execution_allowed(self) -> bool:
        return False

    @property
    def dispatch_allowed(self) -> bool:
        return False

    @property
    def auto_retry_allowed(self) -> bool:
        return False

    @property
    def resume_allowed(self) -> bool:
        return False

    @property
    def merging_allowed(self) -> bool:
        return False

    @property
    def provider_switch_authorized(self) -> bool:
        return False

    @staticmethod
    def _guarantees() -> dict:
        return {
            "marker": SCHEDULER_MARKER, "certified": False, "authorizes_action": False, "execution_allowed": False,
            "dispatch_allowed": False, "auto_retry_allowed": False, "resume_allowed": False,
            "merging_allowed": False, "provider_switch_authorized": False,
        }


@dataclass(frozen=True)
class BatchPlan(_NotAuthorized):
    """Consultative batch plan. Echo fields hold only validated values (None
    and () when the request was refused). Construction re-checks every
    invariant, so a hand-made plan cannot exceed its own capacity or claim
    an outcome its decisions do not support."""
    outcome: str
    dag_id: Optional[str]
    item_count: Optional[int]
    request_fingerprint: Optional[str]
    concurrency_preference: Optional[str]
    effective_concurrency: Optional[int]
    request_reasons: tuple
    decisions: tuple

    def __post_init__(self):
        if type(self.outcome) is not str or self.outcome not in DECISIONS:
            raise ValueError("unknown batch outcome")
        if not (type(self.request_reasons) is tuple
                and all(type(r) is str and r in REQUEST_REASONS for r in self.request_reasons)
                and self.request_reasons == _ordered(self.request_reasons, REQUEST_REASONS)):
            raise ValueError("request_reasons must be ordered request reason codes")
        if not (type(self.decisions) is tuple and all(type(d) is ItemDecision for d in self.decisions)):
            raise ValueError("decisions must be a tuple of ItemDecision")
        echo = (self.dag_id, self.item_count, self.request_fingerprint, self.concurrency_preference,
                self.effective_concurrency)
        if self.request_reasons:
            if self.outcome != REFUSED or self.decisions or echo != (None,) * len(echo):
                raise ValueError("a refused request echoes nothing and decides nothing")
            return
        if not _safe_id(self.dag_id):
            raise ValueError("dag_id must be a safe id")
        if not (_is_int(self.item_count) and self.item_count == len(self.decisions) and 1 <= self.item_count <= MAX_ITEMS):
            raise ValueError("item_count must equal the number of decisions")
        if not (type(self.request_fingerprint) is str and _FINGERPRINT_RE.fullmatch(self.request_fingerprint)):
            raise ValueError("request_fingerprint must be a sha256 hex digest")
        if self.concurrency_preference not in CONCURRENCY_PREFERENCES:
            raise ValueError("unknown concurrency preference")
        if not (_is_int(self.effective_concurrency) and 1 <= self.effective_concurrency <= MAX_CONCURRENCY):
            raise ValueError("effective_concurrency must be in 1..MAX_CONCURRENCY")
        if self.concurrency_preference == CONCURRENCY_SERIAL and self.effective_concurrency != 1:
            raise ValueError("a SERIAL plan has exactly one slot")
        if len({d.item_id for d in self.decisions}) != len(self.decisions):
            raise ValueError("decisions must name each item once")
        slots = sorted(d.slot for d in self.decisions if d.decision == SCHEDULABLE)
        if len(slots) > self.effective_concurrency or slots != list(range(len(slots))):
            raise ValueError("schedulable slots must be 0..n-1 within effective_concurrency")
        if self.outcome != _batch_outcome(self.decisions):
            raise ValueError("outcome must be exactly the one derived from decisions")

    def decision_of(self, item_id: str) -> Optional[ItemDecision]:
        for decision in self.decisions:
            if decision.item_id == item_id:
                return decision
        return None

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA, "schema_version": SCHEMA_VERSION, "outcome": self.outcome, "dag_id": self.dag_id,
            "item_count": self.item_count, "request_fingerprint": self.request_fingerprint,
            "concurrency_preference": self.concurrency_preference,
            "effective_concurrency": self.effective_concurrency, "request_reasons": list(self.request_reasons),
            "counts": {d: sum(1 for x in self.decisions if x.decision == d) for d in DECISIONS},
            "decisions": [d.to_dict() for d in self.decisions], **_NotAuthorized._guarantees(),
        }


def canonical_json(plan: BatchPlan) -> str:
    """Stable, sorted, compact, size-bounded serialization. Only the exact
    contract type is accepted, so a subclass cannot substitute `to_dict`."""
    if type(plan) is not BatchPlan:
        raise TypeError("canonical_json accepts only a BatchPlan")
    text = _canonical(BatchPlan.to_dict(plan))
    if len(text) > MAX_CANONICAL_JSON_BYTES:
        raise ValueError("canonical plan exceeds MAX_CANONICAL_JSON_BYTES")
    return text


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _capability_reasons(caps) -> set:
    if not _str_tuple(caps, len(CAPABILITIES)):
        return {CAPABILITIES_MALFORMED}
    reasons = set()
    if any(c not in _CAPABILITY_SET for c in caps):
        reasons.add(CAPABILITY_UNKNOWN)
    if len(caps) != len(set(caps)):
        reasons.add(CAPABILITY_DUPLICATE)
    return reasons


def _item_reasons(item: ScheduleItem) -> set:
    reasons = set()
    if not _safe_id(item.item_id):
        reasons.add(ITEM_ID_INVALID)
    if not (_is_int(item.priority) and MIN_PRIORITY <= item.priority <= MAX_PRIORITY):
        reasons.add(PRIORITY_INVALID)
    mode_ok = type(item.mode) is str and item.mode in MODES
    if not mode_ok:
        reasons.add(MODE_UNKNOWN)
    if item.provider_id is not None and not _valid_provider_id(item.provider_id):
        reasons.add(PROVIDER_ID_INVALID)
    cap_reasons = _capability_reasons(item.required_capabilities)
    reasons |= cap_reasons
    if not cap_reasons and "SHELL" in item.required_capabilities and mode_ok and item.mode != MODE_WRITE:
        reasons.add(SHELL_REQUIRES_WRITE_MODE)
    attested = item.attested_capabilities
    if attested is not None and _capability_reasons(attested):
        reasons.add(ATTESTED_CAPABILITIES_MALFORMED)
    if not _str_tuple(item.depends_on, MAX_DEPENDS_ON) or not all(_safe_id(d) for d in item.depends_on):
        reasons.add(DEPENDS_ON_MALFORMED)
    elif len(item.depends_on) != len(set(item.depends_on)):
        reasons.add(DEPENDENCY_DUPLICATE)
    if type(item.upstream_state) is not str or item.upstream_state not in UPSTREAM_STATES:
        reasons.add(UPSTREAM_STATE_INVALID)
    return reasons


def _has_cycle(graph: dict) -> bool:
    """Kahn's algorithm over in-batch edges only (already validated)."""
    pending = {node: len(deps) for node, deps in graph.items()}
    dependents = {node: [] for node in graph}
    for node, deps in graph.items():
        for dep in deps:
            dependents[dep].append(node)
    ready = [node for node, count in pending.items() if count == 0]
    done = 0
    while ready:
        node = ready.pop()
        done += 1
        for child in dependents[node]:
            pending[child] -= 1
            if pending[child] == 0:
                ready.append(child)
    return done != len(graph)


def _validate_request(request) -> tuple:
    """Returns (reasons, window) where window is (as_of, not_before,
    deadline) as UTC datetimes for a valid request. Never echoes raw input."""
    if type(request) is not ScheduleRequest:
        return (REQUEST_NOT_TYPED,), None
    reasons = set()
    if not (_is_int(request.schema_version) and request.schema_version == REQUEST_SCHEMA_VERSION):
        reasons.add(SCHEMA_VERSION_UNSUPPORTED)
    if not _safe_id(request.dag_id):
        reasons.add(DAG_ID_INVALID)

    items = request.items
    if type(items) is not tuple:
        reasons.add(ITEMS_NOT_TUPLE)
        items = ()
    elif not items:
        reasons.add(ITEMS_EMPTY)
    elif len(items) > MAX_ITEMS:
        reasons.add(ITEMS_TOO_MANY)
        items = ()
    if not (_is_int(request.item_count) and 1 <= request.item_count <= MAX_ITEMS):
        reasons.add(ITEM_COUNT_INVALID)
    elif type(request.items) is tuple and request.item_count != len(request.items):
        reasons.add(ITEM_COUNT_MISMATCH)

    typed = []
    for item in items:
        if type(item) is not ScheduleItem:
            reasons.add(ITEM_NOT_TYPED)
            continue
        item_reasons = _item_reasons(item)
        reasons |= item_reasons
        if ITEM_ID_INVALID not in item_reasons:
            typed.append((item, item_reasons))
    ids = [item.item_id for item, _ in typed]
    if len(ids) != len(set(ids)):
        reasons.add(ITEM_ID_DUPLICATE)
    known = set(ids)
    graph = {}
    for item, item_reasons in typed:
        if DEPENDS_ON_MALFORMED in item_reasons or DEPENDENCY_DUPLICATE in item_reasons:
            continue
        for dep in item.depends_on:
            if dep == item.item_id:
                reasons.add(DEPENDENCY_SELF)
            elif dep not in known:
                reasons.add(DEPENDENCY_UNKNOWN)
        graph[item.item_id] = item.depends_on
    if not reasons and _has_cycle(graph):
        reasons.add(DEPENDENCY_CYCLE)

    if type(request.concurrency_preference) is not str or request.concurrency_preference not in CONCURRENCY_PREFERENCES:
        reasons.add(CONCURRENCY_PREFERENCE_UNKNOWN)
    if not (_is_int(request.max_concurrency) and 1 <= request.max_concurrency <= MAX_CONCURRENCY):
        reasons.add(MAX_CONCURRENCY_INVALID)

    limits = request.provider_limits
    if not (type(limits) is tuple and len(limits) <= MAX_CONCURRENCY and all(
            type(p) is tuple and len(p) == 2 and _valid_provider_id(p[0])
            and _is_int(p[1]) and 1 <= p[1] <= MAX_PROVIDER_LIMIT for p in limits)):
        reasons.add(PROVIDER_LIMITS_MALFORMED)
    elif len({p[0] for p in limits}) != len(limits):
        reasons.add(PROVIDER_LIMIT_DUPLICATE)

    as_of = _parse_utc(request.as_of_utc)
    if as_of is None:
        reasons.add(AS_OF_INVALID)
    not_before = _parse_utc(request.not_before_utc) if request.not_before_utc is not None else None
    deadline = _parse_utc(request.deadline_utc) if request.deadline_utc is not None else None
    if (request.not_before_utc is not None and not_before is None) or (
            request.deadline_utc is not None and deadline is None):
        reasons.add(WINDOW_INVALID)
    elif not_before is not None and deadline is not None and not_before >= deadline:
        reasons.add(WINDOW_INVERTED)

    if reasons:
        return _ordered(reasons, REQUEST_REASONS), None
    return (), (as_of, not_before, deadline)


def _request_dict(request: ScheduleRequest, window: tuple) -> dict:
    as_of, not_before, deadline = window
    return {
        "schema": REQUEST_SCHEMA, "schema_version": REQUEST_SCHEMA_VERSION, "dag_id": request.dag_id,
        "item_count": request.item_count, "as_of_utc": _utc_text(as_of), "not_before_utc": _utc_text(not_before),
        "deadline_utc": _utc_text(deadline), "concurrency_preference": request.concurrency_preference,
        "max_concurrency": request.max_concurrency,
        "provider_limits": [[pid, limit] for pid, limit in sorted(request.provider_limits)],
        "items": [
            {
                "item_id": i.item_id, "mode": i.mode, "priority": i.priority, "provider_id": i.provider_id,
                "required_capabilities": sorted(i.required_capabilities),
                "attested_capabilities": None if i.attested_capabilities is None else sorted(i.attested_capabilities),
                "depends_on": sorted(i.depends_on), "upstream_state": i.upstream_state,
            }
            for i in request.items
        ],
    }


def canonical_request_json(request: ScheduleRequest) -> str:
    """Stable, size-bounded serialization of a VALID request (timestamps
    normalized to UTC; order-free sets sorted; item order kept, as it is the
    planning tie-break). Raises ValueError for an invalid request."""
    reasons, window = _validate_request(request)
    if reasons:
        raise ValueError("canonical_request_json accepts only a valid ScheduleRequest: " + ",".join(reasons))
    text = _canonical(_request_dict(request, window))
    if len(text) > MAX_CANONICAL_JSON_BYTES:
        raise ValueError("canonical request exceeds MAX_CANONICAL_JSON_BYTES")
    return text


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------

def required_capabilities_for(item: ScheduleItem) -> tuple:
    """Base + mode + explicitly requested capabilities, sorted. Assumes an
    item already accepted by `plan_batch`."""
    required = set(BASE_CAPABILITIES) | set(item.required_capabilities)
    if item.mode == MODE_WRITE:
        required |= WRITE_MODE_CAPABILITIES
    return tuple(sorted(required))


def _refused(reasons: tuple) -> BatchPlan:
    return BatchPlan(
        outcome=REFUSED, dag_id=None, item_count=None, request_fingerprint=None, concurrency_preference=None,
        effective_concurrency=None, request_reasons=reasons, decisions=(),
    )


def plan_batch(request: ScheduleRequest) -> BatchPlan:
    """Pure, deterministic batch planning advisory. Never raises on bad
    input and never mutates it: every malformed request is an explained
    refusal. The result never authorizes dispatch, execution, retry, resume,
    merge or a provider switch."""
    reasons, window = _validate_request(request)
    if reasons:
        return _refused(reasons)
    request_text = _canonical(_request_dict(request, window))
    if len(request_text) > MAX_CANONICAL_JSON_BYTES:
        return _refused((REQUEST_TOO_LARGE,))

    as_of, not_before, deadline = window
    window_reasons = set()
    if deadline is not None and as_of >= deadline:
        window_reasons.add(WINDOW_EXPIRED)
    elif not_before is not None and as_of < not_before:
        window_reasons.add(WINDOW_NOT_OPEN)
    limits = dict(request.provider_limits)

    items = request.items
    held = []
    for item in items:
        item_reasons = set(window_reasons)
        if item.upstream_state in _UPSTREAM_REASON:
            item_reasons.add(_UPSTREAM_REASON[item.upstream_state])
        if item.depends_on:
            item_reasons.add(DEPENDENCY_IN_BATCH)
        if item.attested_capabilities is None:
            item_reasons.add(CAPABILITIES_UNATTESTED)
        elif set(required_capabilities_for(item)) - set(item.attested_capabilities):
            item_reasons.add(CAPABILITY_NOT_ATTESTED)
        if limits and item.provider_id is None:
            item_reasons.add(PROVIDER_UNASSIGNED)
        held.append(item_reasons)

    # Runner dispatch order: highest priority first, then declared order.
    capacity = 1 if request.concurrency_preference == CONCURRENCY_SERIAL else request.max_concurrency
    slots = [None] * len(items)
    per_provider: dict = {}
    assigned = 0
    for index in sorted(range(len(items)), key=lambda i: (-items[i].priority, i)):
        if held[index]:
            continue
        provider = items[index].provider_id
        if assigned >= capacity:
            held[index].add(CONCURRENCY_LIMIT_REACHED)
        elif provider in limits and per_provider.get(provider, 0) >= limits[provider]:
            held[index].add(PROVIDER_LIMIT_REACHED)
        else:
            per_provider[provider] = per_provider.get(provider, 0) + 1
            slots[index] = assigned
            assigned += 1

    decisions = tuple(
        ItemDecision(
            item_id=item.item_id, decision=_decision_for(_ordered(held[i], ITEM_REASONS)),
            reasons=_ordered(held[i], ITEM_REASONS), priority=item.priority, slot=slots[i],
        )
        for i, item in enumerate(items)
    )
    return BatchPlan(
        outcome=_batch_outcome(decisions), dag_id=request.dag_id, item_count=request.item_count,
        request_fingerprint=hashlib.sha256(request_text.encode("ascii")).hexdigest(),
        concurrency_preference=request.concurrency_preference, effective_concurrency=capacity,
        request_reasons=(), decisions=decisions,
    )
