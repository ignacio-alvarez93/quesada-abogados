"""FCP-11A-01: Fabric Control Plane contract V1 - pure, deterministic,
fail-closed, provider-neutral, OBSERVATION-ONLY.

Defines the versioned, immutable vocabulary every later FCP-11 stage speaks
when it shows an operator what Fabric is doing: pipeline / worker identity,
the native evidence a reader may open (and only that), the SOURCE status as
the Runner / Director recorded it, its PRESENTATIONAL classification, the
explicit absence / corruption / unavailability conditions with their causes,
the actor that holds the authority to resolve each (never this module), the
public field catalog and a deterministic observation seal. It reads nothing,
opens nothing and decides nothing.

Native evidence inventory (FCP-11A, taken from the real `origin/develop` code)
-----------------------------------------------------------------------------
Runner state (`runner_pipeline`, `<state_root>/`)::

    <pipeline_id>/pipeline.json                     PIPELINE_RECORD
    <pipeline_id>/pipeline_result.json              PIPELINE_RESULT (rewritten on every save)
    <pipeline_id>/workers/<worker_id>/worker.json   WORKER_RECORD
    <pipeline_id>/workers/<worker_id>/heartbeat.json WORKER_HEARTBEAT
    <pipeline_id>/workers/<worker_id>/preflight.json WORKER_PREFLIGHT
    <pipeline_id>/workers/<worker_id>/result.json   WORKER_RESULT
    _evidence/<evidence_root_key>/<attempt_leaf>/metadata.json      ATTEMPT_METADATA
    _evidence/<evidence_root_key>/<attempt_leaf>/result.json        ATTEMPT_RESULT
    _evidence/<evidence_root_key>/<attempt_leaf>/work_product.json  ATTEMPT_WORK_PRODUCT

Factory ledger (`runner_factory_ledger`, `<factory_root>/`)::

    events.jsonl                                    FACTORY_EVENTS (the ONLY ledger truth)

Director (`fabric_director`, `<director_root>/`)::

    <pipeline_id>/manifest.json | dag_plan.json | dag_provenance.json  DIRECTOR_DAG_*

Deliberately NOT referenceable: `prompt.txt`, `stdout.txt`, `stderr.txt`
(provider prose / transcripts: sensitive, and never a status source),
`git_before.txt` and other raw attempt files, `modules.json` (a disposable
cache of `events.jsonl`, never authoritative), every `lock/` directory
(pid / hostname identities) and the Director's Work Order text.

Decisions
---------
* Director and Runner keep ALL execution, recovery, authorization, Git,
  process and resource authority. This module has no reader, writer, ledger,
  store, clock, environment, process or network access: it never writes a
  second ledger and invents no persisted state. The observation instant is
  the caller's explicit `observed_at_utc`.
* Reuse, never redefine: worker / pipeline vocabularies are
  `runner_pipeline.WorkerState` / `PipelineStatus`, lifecycle categories are
  `runner_pipeline._WORKER_CATEGORY`, the Director's DAG aggregate adds only
  its own UNVERIFIED / UNKNOWN, the attempt evidence root is
  `runner_pipeline.evidence_root_key`, ledger events / fields are the
  ledger's own, provider conditions are `ProviderCondition`, checkpoint
  policies are `claude_runner.CHECKPOINT_POLICIES`, actors are FCP-10C-02's
  `ACTORS`, the zero-authority flags extend FCP-9A-01 `_NotAuthorized`, and
  timestamps use the FCP-10A-01 strict UTC parser.
* Source status != presentation. `StatusView` keeps the verbatim source
  value next to its condition and DERIVES `lifecycle` and `runner_outcome`
  on construction (a hand-made view cannot claim more). `runner_outcome`
  SUCCESS means "the Runner recorded SUCCESS" only - not an audit, not CI,
  not approval - and exists only for a PRESENT, recognized SUCCESS value.
  Absent / corrupt / unavailable evidence is always lifecycle UNKNOWN and
  outcome UNKNOWN: success is never implicit.
* Conditions: PRESENT, MISSING (source or field absent), CORRUPT (present
  but unparsable, unsupported schema, unrecognized value, identity
  mismatch), UNAVAILABLE (could not be read safely: refused path, link /
  junction, oversize, unreadable, changed during read, unexpected evidence
  path). Each non-PRESENT condition carries exactly one `CAUSES` code whose
  condition is fixed by `CAUSE_CONDITION`; `CAUSE_ACTOR` names who could
  resolve it. The actor is information only: every view fixes the
  zero-authority flags to False as read-only properties.
* Public fields are an explicit allowlist (`*_PUBLIC_FIELDS`); every native
  key is classified public or withheld (`*_WITHHELD_FIELDS`), and the tests
  pin that partition against the native producers, so a new native field is
  never exposed by default. Paths are never public: `EvidenceRef.to_dict`
  names the root KIND and the ids, and `relative_parts()` (for later
  readers, under a root they hold explicitly) is not serialized.
  `state_reason` / `stop_reason` keep only their leading code: the Runner's
  `CODE:detail` suffix may carry ids, provider ids or other free text, and a
  reason with no leading code (WAITING_DEPENDENCY's native `waiting for a,b`
  prose) is withheld as None - native, so not reported malformed.
* Identifiers: ASCII Runner-safe segments (`runner_pipeline._safe_segment`
  AND FCP-9A-01 `_safe_id`: <= 64 chars, `[A-Za-z0-9._-]`, no leading dot),
  additionally no trailing dot and no Windows device name (both alias other
  paths on Windows) and nothing credential-shaped: the Runner's `redact`
  applied per `-`/`_`/`.` token (applied to the whole id, its 32+ run rule
  would flag every long readable id such as this campaign's) plus its
  `sk-` prefix rule. Codes are `[A-Z][A-Z0-9_]{1,63}`; commits are 40/64 hex.
* Projection never raises on native payloads (`project_pipeline_result`):
  anything malformed degrades to CORRUPT / None with the field named in
  `malformed_fields`; constructors DO raise `ValueError` on a view that
  violates its invariants (programming error, not data).
* Determinism: `ControlPlaneObservation.revision` is the sha256 of its
  canonical body (sorted keys, compact, ASCII, sorted unique collections);
  `canonical_json` adds it as the seal and is size-bounded. Equal inputs
  always produce byte-equal output.

Limitations (documented, not implemented here)
----------------------------------------------
* No reader: opening evidence fail-closed (absolute local roots, no
  traversal, no link / junction / 8.3 alias, descriptor identity re-checked
  against TOCTOU, bounded strict JSON) belongs to the next stage, which
  should reuse the FCP-10D-01 `fabric_resource_quota_report` admission /
  `read_input_bytes` discipline rather than a new one.
* Attempts recorded before RUNNER_EVIDENCE_PATH_FIX1 live under
  `workers/<id>/evidence/...`; they are not referenceable and a reader must
  report the persisted `evidence_dir` as UNAVAILABLE /
  EVIDENCE_PATH_UNEXPECTED whenever it is not the derived `_evidence` path.
* Ids are compared verbatim; on a case-insensitive filesystem two ids that
  differ only in case share one directory - a reader must compare the
  physical identity, never the name.
* Ledger events are catalogued (public / withheld) but not projected here;
  provider, cost, quota, duration and progress figures are not part of this
  contract and are never invented (`duration_seconds` is withheld: it is a
  write-time figure that goes stale for a live pipeline).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Optional

try:
    from scripts.ai import fabric_director as fd
    from scripts.ai import fabric_resource_quota_contract as qc
    from scripts.ai import fabric_resource_quota_recovery as qr
    from scripts.ai import fabric_scheduler_contract as sc
    from scripts.ai import runner_factory_ledger as flog
    from scripts.ai import runner_pipeline as rp
    from scripts.ai import runner_provider_availability as availability
except ImportError:  # pragma: no cover - direct script execution
    import fabric_director as fd  # type: ignore[no-redef]
    import fabric_resource_quota_contract as qc  # type: ignore[no-redef]
    import fabric_resource_quota_recovery as qr  # type: ignore[no-redef]
    import fabric_scheduler_contract as sc  # type: ignore[no-redef]
    import runner_factory_ledger as flog  # type: ignore[no-redef]
    import runner_pipeline as rp  # type: ignore[no-redef]
    import runner_provider_availability as availability  # type: ignore[no-redef]

SCHEMA = "fcp11a01-control-plane-observation-v1"
SCHEMA_VERSION = 1
CONTROL_PLANE_MARKER = "FCP11A01_OBSERVATION_ONLY_NOT_CERTIFIED_NOT_AUTHORIZED"

MAX_PIPELINES = 256
MAX_WORKERS = sc.MAX_ITEMS
MAX_EVIDENCE_REFS = 4096
MAX_ATTEMPTS = 100_000
MAX_EVIDENCE_BYTES = 16 * 1024 * 1024
MAX_CANONICAL_JSON_BYTES = 4 * 1024 * 1024

_CODE_RE = re.compile(r"[A-Z][A-Z0-9_]{1,63}")
_COMMIT_RE = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_ATTEMPT_LEAF_RE = re.compile(r"[0-9]{8}T[0-9]{6}Z_[0-9a-f]{8}(?:_[0-9a-f]{10})?")
_ID_TOKEN_SPLIT_RE = re.compile(r"[-_.]")
_CREDENTIAL_PREFIX_RE = re.compile(r"(?<![A-Za-z0-9_])sk-[A-Za-z0-9_-]{6,}")
_WINDOWS_DEVICE_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}
)

# ---------------------------------------------------------------------------
# Vocabularies
# ---------------------------------------------------------------------------

PRESENT = "PRESENT"
MISSING = "MISSING"
CORRUPT = "CORRUPT"
UNAVAILABLE = "UNAVAILABLE"
CONDITIONS = (PRESENT, MISSING, CORRUPT, UNAVAILABLE)

SOURCE_ABSENT = "SOURCE_ABSENT"
FIELD_ABSENT = "FIELD_ABSENT"
SOURCE_NOT_JSON = "SOURCE_NOT_JSON"
SCHEMA_UNSUPPORTED = "SCHEMA_UNSUPPORTED"
FIELD_MALFORMED = "FIELD_MALFORMED"
VALUE_UNRECOGNIZED = "VALUE_UNRECOGNIZED"
IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
PATH_REFUSED = "PATH_REFUSED"
LINK_REFUSED = "LINK_REFUSED"
SOURCE_TOO_LARGE = "SOURCE_TOO_LARGE"
SOURCE_UNREADABLE = "SOURCE_UNREADABLE"
SOURCE_CHANGED_DURING_READ = "SOURCE_CHANGED_DURING_READ"
EVIDENCE_PATH_UNEXPECTED = "EVIDENCE_PATH_UNEXPECTED"
CAUSE_CONDITION = {
    SOURCE_ABSENT: MISSING, FIELD_ABSENT: MISSING,
    SOURCE_NOT_JSON: CORRUPT, SCHEMA_UNSUPPORTED: CORRUPT, FIELD_MALFORMED: CORRUPT,
    VALUE_UNRECOGNIZED: CORRUPT, IDENTITY_MISMATCH: CORRUPT,
    PATH_REFUSED: UNAVAILABLE, LINK_REFUSED: UNAVAILABLE, SOURCE_TOO_LARGE: UNAVAILABLE,
    SOURCE_UNREADABLE: UNAVAILABLE, SOURCE_CHANGED_DURING_READ: UNAVAILABLE, EVIDENCE_PATH_UNEXPECTED: UNAVAILABLE,
}
CAUSES = tuple(CAUSE_CONDITION)

# Who could resolve a non-PRESENT condition (information only, never a
# permit): absent evidence is the Runner's to produce; anything corrupt or
# unreadable needs a human look.
ACTORS = qr.ACTORS
CONDITION_ACTOR = {PRESENT: qr.ACTOR_NONE, MISSING: qr.ACTOR_RUNNER, CORRUPT: qr.ACTOR_HUMAN, UNAVAILABLE: qr.ACTOR_HUMAN}

# Source status kinds and their native vocabularies.
SOURCE_WORKER_STATE = "WORKER_STATE"
SOURCE_PIPELINE_STATUS = "PIPELINE_STATUS"
SOURCE_DIRECTOR_DAG_AGGREGATE = "DIRECTOR_DAG_AGGREGATE"
WORKER_STATES = tuple(s.value for s in rp.WorkerState)
PIPELINE_STATUSES = tuple(s.value for s in rp.PipelineStatus)
DIRECTOR_DAG_AGGREGATES = PIPELINE_STATUSES + (fd.DAG_AGGREGATE_UNVERIFIED, fd.DAG_AGGREGATE_UNKNOWN)
SOURCE_VOCABULARIES = {
    SOURCE_WORKER_STATE: WORKER_STATES,
    SOURCE_PIPELINE_STATUS: PIPELINE_STATUSES,
    SOURCE_DIRECTOR_DAG_AGGREGATE: DIRECTOR_DAG_AGGREGATES,
}
SOURCE_KINDS = tuple(SOURCE_VOCABULARIES)

# Presentational classification (derived, never a source of truth).
LIFECYCLE_ACTIVE = "ACTIVE"
LIFECYCLE_QUEUED = "QUEUED"
LIFECYCLE_WAITING = "WAITING"
LIFECYCLE_TERMINAL = "TERMINAL"
LIFECYCLE_INCOMPLETE = "INCOMPLETE"
LIFECYCLE_UNKNOWN = "UNKNOWN"
LIFECYCLES = (LIFECYCLE_ACTIVE, LIFECYCLE_QUEUED, LIFECYCLE_WAITING, LIFECYCLE_TERMINAL, LIFECYCLE_INCOMPLETE,
              LIFECYCLE_UNKNOWN)
OUTCOME_NONE = "NONE"
OUTCOME_UNVERIFIED = fd.DAG_AGGREGATE_UNVERIFIED
OUTCOME_UNKNOWN = "UNKNOWN"
_TERMINAL_OUTCOMES = tuple(s.value for s in (
    rp.WorkerState.SUCCESS, rp.WorkerState.PARTIAL, rp.WorkerState.BLOCKED, rp.WorkerState.FAILED,
    rp.WorkerState.CANCELLED, rp.WorkerState.INTERRUPTED,
))
RUNNER_OUTCOMES = _TERMINAL_OUTCOMES + (OUTCOME_UNVERIFIED, OUTCOME_NONE, OUTCOME_UNKNOWN)

_PIPELINE_LIFECYCLE = {
    rp.PipelineStatus.RUNNING.value: LIFECYCLE_ACTIVE, rp.PipelineStatus.DRAINING.value: LIFECYCLE_ACTIVE,
    rp.PipelineStatus.INCOMPLETE.value: LIFECYCLE_INCOMPLETE,
}


def _present_classification(kind: str, value: str) -> tuple:
    if kind == SOURCE_WORKER_STATE:
        lifecycle = rp._WORKER_CATEGORY[value]
    elif value == fd.DAG_AGGREGATE_UNKNOWN:
        return LIFECYCLE_UNKNOWN, OUTCOME_UNKNOWN
    else:
        lifecycle = _PIPELINE_LIFECYCLE.get(value, LIFECYCLE_TERMINAL)
    return lifecycle, (value if lifecycle == LIFECYCLE_TERMINAL else OUTCOME_NONE)


def classify(kind: str, condition: str, value: Optional[str]) -> tuple:
    """`(lifecycle, runner_outcome)` of one source status. Anything but a
    PRESENT, recognized value is (UNKNOWN, UNKNOWN)."""
    if condition != PRESENT or kind not in SOURCE_VOCABULARIES or value not in SOURCE_VOCABULARIES[kind]:
        return LIFECYCLE_UNKNOWN, OUTCOME_UNKNOWN
    return _present_classification(kind, value)


# Native evidence inventory: root kind and path template. `{pipeline}`,
# `{worker}`, `{evidence_key}` and `{attempt}` are filled only from
# validated ids by `EvidenceRef.relative_parts`.
ROOT_RUNNER_STATE = "RUNNER_STATE_ROOT"
ROOT_FACTORY_LEDGER = "FACTORY_LEDGER_ROOT"
ROOT_DIRECTOR = "DIRECTOR_ROOT"
ROOT_KINDS = (ROOT_RUNNER_STATE, ROOT_FACTORY_LEDGER, ROOT_DIRECTOR)

_WORKER_DIR = ("{pipeline}", "workers", "{worker}")
_ATTEMPT_DIR = (rp.EVIDENCE_ROOT_DIRNAME, "{evidence_key}", "{attempt}")
EVIDENCE_INVENTORY = {
    "PIPELINE_RECORD": (ROOT_RUNNER_STATE, ("{pipeline}", "pipeline.json")),
    "PIPELINE_RESULT": (ROOT_RUNNER_STATE, ("{pipeline}", "pipeline_result.json")),
    "WORKER_RECORD": (ROOT_RUNNER_STATE, _WORKER_DIR + ("worker.json",)),
    "WORKER_HEARTBEAT": (ROOT_RUNNER_STATE, _WORKER_DIR + ("heartbeat.json",)),
    "WORKER_PREFLIGHT": (ROOT_RUNNER_STATE, _WORKER_DIR + ("preflight.json",)),
    "WORKER_RESULT": (ROOT_RUNNER_STATE, _WORKER_DIR + ("result.json",)),
    "ATTEMPT_METADATA": (ROOT_RUNNER_STATE, _ATTEMPT_DIR + ("metadata.json",)),
    "ATTEMPT_RESULT": (ROOT_RUNNER_STATE, _ATTEMPT_DIR + ("result.json",)),
    "ATTEMPT_WORK_PRODUCT": (ROOT_RUNNER_STATE, _ATTEMPT_DIR + ("work_product.json",)),
    "FACTORY_EVENTS": (ROOT_FACTORY_LEDGER, (flog.EVENTS_FILENAME,)),
    "DIRECTOR_DAG_MANIFEST": (ROOT_DIRECTOR, ("{pipeline}", fd.DAG_MANIFEST_FILENAME)),
    "DIRECTOR_DAG_PLAN": (ROOT_DIRECTOR, ("{pipeline}", fd.DAG_PLAN_FILENAME)),
    "DIRECTOR_DAG_PROVENANCE": (ROOT_DIRECTOR, ("{pipeline}", fd.DAG_PROVENANCE_FILENAME)),
}
EVIDENCE_KINDS = tuple(EVIDENCE_INVENTORY)


def _placeholders(kind: str) -> frozenset:
    return frozenset(p for p in EVIDENCE_INVENTORY[kind][1] if p.startswith("{"))


# Public field catalog: every native key is either public or withheld.
PIPELINE_PUBLIC_FIELDS = (
    "schema_version", "pipeline_id", "status", "stop_reason", "started_at_utc", "ended_at_utc", "workers_total",
    "max_observed_concurrency", "workers",
)
PIPELINE_WITHHELD_FIELDS = (
    # Derivable from the worker views (one source, not two) or a stale
    # write-time figure (`duration_seconds`).
    "duration_seconds", "success", "partial", "blocked", "failed", "cancelled", "interrupted",
    "waiting_provider_quota", "blocked_provider_auth", "state_counts", "provider_breakdown",
)
WORKER_PUBLIC_FIELDS = (
    "id", "provider", "requested_provider", "state", "state_reason", "attempts", "work_attempts_used",
    "availability_attempts", "provider_condition", "next_eligible_utc", "checkpoint_policy", "checkpoint_commit",
)
WORKER_WITHHELD_FIELDS = ("result_path", "worker_path")  # internal paths
LEDGER_PUBLIC_FIELDS = (
    "schema_version", "event_id", "event_type", "timestamp_utc", "project", "module", "module_version",
    "pipeline_id", "worker_id", "provider", "role", "base_commit", "result_commit", "state", "state_reason",
    "certification_status",
)
# `worktree` is a path, `branch` may embed a user / path, `closer` names a
# person and `extra` is free-form.
LEDGER_WITHHELD_FIELDS = ("worktree", "branch", "closer", "extra")
LEDGER_EVENT_TYPES = tuple(sorted(flog.EVENT_TYPES))

PROVIDER_CONDITIONS = tuple(c.value for c in availability.ProviderCondition)
CHECKPOINT_POLICIES = tuple(sorted(rp.claude_runner.CHECKPOINT_POLICIES))


# ---------------------------------------------------------------------------
# Small validators (never raise, never echo raw input)
# ---------------------------------------------------------------------------

def _secret_shaped(value: str) -> bool:
    spaced = " ".join(t for t in _ID_TOKEN_SPLIT_RE.split(value) if t)
    return availability.redact(spaced) != spaced or _CREDENTIAL_PREFIX_RE.search(value) is not None


def valid_id(value) -> bool:
    """A Runner-safe, ASCII, non-aliasing, non-credential id."""
    return (
        sc._safe_id(value) and rp._safe_segment(value) and not value.endswith(".")
        and value.split(".")[0].upper() not in _WINDOWS_DEVICE_NAMES and not _secret_shaped(value)
    )


def valid_code(value) -> bool:
    return type(value) is str and _CODE_RE.fullmatch(value) is not None and not _secret_shaped(value)


def reason_code(value) -> Optional[str]:
    """Leading code of a Runner `CODE` / `CODE:detail` reason, or None."""
    if type(value) is not str:
        return None
    code = value.split(":", 1)[0]
    return code if valid_code(code) else None


def normalized_utc(value) -> Optional[str]:
    parsed = qc.parse_utc(value)
    return None if parsed is None else sc._utc_text(parsed)


def _bounded_int(value, high: int) -> bool:
    return sc._is_int(value) and 0 <= value <= high


def _in(value, vocabulary) -> bool:
    return type(value) is str and value in vocabulary


def _optional(value, check) -> bool:
    return value is None or check(value)


# ---------------------------------------------------------------------------
# Guarantees
# ---------------------------------------------------------------------------

class _ControlPlaneGuarantees(sc._NotAuthorized):
    """FCP-9A-01 zero-authority flags plus the observer-specific ones."""

    @property
    def ledger_write_allowed(self) -> bool:
        return False

    @property
    def state_persisted(self) -> bool:
        return False

    @property
    def process_control_allowed(self) -> bool:
        return False

    @property
    def git_allowed(self) -> bool:
        return False

    @staticmethod
    def _guarantees() -> dict:
        guarantees = sc._NotAuthorized._guarantees()
        guarantees.update(marker=CONTROL_PLANE_MARKER, ledger_write_allowed=False, state_persisted=False,
                          process_control_allowed=False, git_allowed=False)
        return guarantees


def _check_condition(condition, cause) -> None:
    if not _in(condition, CONDITIONS):
        raise ValueError("unknown condition")
    if condition == PRESENT:
        if cause is not None:
            raise ValueError("a PRESENT source has no cause")
    elif not (_in(cause, CAUSES) and CAUSE_CONDITION[cause] == condition):
        raise ValueError("a non-PRESENT source needs a cause of that condition")


# ---------------------------------------------------------------------------
# Status: source value + derived presentation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StatusView(_ControlPlaneGuarantees):
    """One source status, verbatim, with its derived presentation."""
    source_kind: str
    condition: str
    source_value: Optional[str]
    cause: Optional[str] = None

    def __post_init__(self):
        if not _in(self.source_kind, SOURCE_KINDS):
            raise ValueError("unknown source kind")
        _check_condition(self.condition, self.cause)
        if self.condition == PRESENT:
            if not _in(self.source_value, SOURCE_VOCABULARIES[self.source_kind]):
                raise ValueError("a PRESENT source value must be in its native vocabulary")
        elif self.source_value is not None:
            raise ValueError("a non-PRESENT source carries no value")

    @property
    def lifecycle(self) -> str:
        return classify(self.source_kind, self.condition, self.source_value)[0]

    @property
    def runner_outcome(self) -> str:
        return classify(self.source_kind, self.condition, self.source_value)[1]

    @property
    def actor(self) -> str:
        return CONDITION_ACTOR[self.condition]

    def to_dict(self) -> dict:
        return {
            "source_kind": self.source_kind, "condition": self.condition, "source_value": self.source_value,
            "cause": self.cause, "lifecycle": self.lifecycle, "runner_outcome": self.runner_outcome,
            "actor": self.actor,
        }


def observe_status(kind: str, raw, *, condition: str = PRESENT, cause: Optional[str] = None) -> StatusView:
    """Fail-closed StatusView: a PRESENT raw value outside the native
    vocabulary becomes CORRUPT / VALUE_UNRECOGNIZED and a PRESENT None
    becomes MISSING / FIELD_ABSENT; the raw value is never echoed."""
    if condition == PRESENT:
        if raw is None:
            return StatusView(kind, MISSING, None, FIELD_ABSENT)
        if not _in(raw, SOURCE_VOCABULARIES.get(kind, ())):
            return StatusView(kind, CORRUPT, None, VALUE_UNRECOGNIZED)
        return StatusView(kind, PRESENT, raw)
    return StatusView(kind, condition, None, cause)


# ---------------------------------------------------------------------------
# Evidence references
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EvidenceRef(_ControlPlaneGuarantees):
    """A native evidence source, by kind and ids only (never a path).
    PRESENT carries the reader's sha256 and byte size; anything else
    carries neither."""
    kind: str
    condition: str
    pipeline_id: Optional[str] = None
    worker_id: Optional[str] = None
    attempt_leaf: Optional[str] = None
    cause: Optional[str] = None
    content_sha256: Optional[str] = None
    size_bytes: Optional[int] = None

    def __post_init__(self):
        if not _in(self.kind, EVIDENCE_KINDS):
            raise ValueError("unknown evidence kind")
        needed = _placeholders(self.kind)
        needs_pipeline = bool(needed & {"{pipeline}", "{evidence_key}"})
        needs_worker = "{worker}" in needed or "{evidence_key}" in needed
        if not (valid_id(self.pipeline_id) if needs_pipeline else self.pipeline_id is None):
            raise ValueError("pipeline_id invalid or not applicable to this kind")
        if not (valid_id(self.worker_id) if needs_worker else self.worker_id is None):
            raise ValueError("worker_id invalid or not applicable to this kind")
        if "{attempt}" in needed:
            if not (type(self.attempt_leaf) is str and _ATTEMPT_LEAF_RE.fullmatch(self.attempt_leaf)):
                raise ValueError("attempt_leaf invalid")
        elif self.attempt_leaf is not None:
            raise ValueError("attempt_leaf not applicable to this kind")
        _check_condition(self.condition, self.cause)
        if self.condition == PRESENT:
            if not (type(self.content_sha256) is str and sc._FINGERPRINT_RE.fullmatch(self.content_sha256)
                    and _bounded_int(self.size_bytes, MAX_EVIDENCE_BYTES)):
                raise ValueError("a PRESENT reference needs a sha256 and a bounded size")
        elif (self.content_sha256, self.size_bytes) != (None, None):
            raise ValueError("a non-PRESENT reference carries no content facts")

    @property
    def root_kind(self) -> str:
        return EVIDENCE_INVENTORY[self.kind][0]

    @property
    def actor(self) -> str:
        return CONDITION_ACTOR[self.condition]

    def relative_parts(self) -> tuple:
        """Path segments under the `root_kind` root a reader holds. Built
        only from validated ids; never serialized."""
        values = {"{pipeline}": self.pipeline_id, "{worker}": self.worker_id, "{attempt}": self.attempt_leaf}
        if "{evidence_key}" in _placeholders(self.kind):
            values["{evidence_key}"] = rp.evidence_root_key(self.pipeline_id, self.worker_id)
        return tuple(values.get(part, part) for part in EVIDENCE_INVENTORY[self.kind][1])

    def sort_key(self) -> tuple:
        return (self.kind, self.pipeline_id or "", self.worker_id or "", self.attempt_leaf or "")

    def to_dict(self) -> dict:
        return {
            "kind": self.kind, "root_kind": self.root_kind, "pipeline_id": self.pipeline_id,
            "worker_id": self.worker_id, "attempt_leaf": self.attempt_leaf, "condition": self.condition,
            "cause": self.cause, "content_sha256": self.content_sha256, "size_bytes": self.size_bytes,
            "actor": self.actor,
        }


# ---------------------------------------------------------------------------
# Pipeline / worker views
# ---------------------------------------------------------------------------

def _check_malformed(fields: tuple, catalog: tuple) -> None:
    if not (type(fields) is tuple and all(_in(f, catalog) for f in fields) and fields == sc._ordered(fields, catalog)):
        raise ValueError("malformed_fields must be ordered public field names")


@dataclass(frozen=True)
class WorkerView(_ControlPlaneGuarantees):
    """Allowlisted projection of one `pipeline_result.json` worker entry.
    Present-but-invalid public fields are None and named in
    `malformed_fields`."""
    pipeline_id: str
    worker_id: str
    status: StatusView
    provider_id: Optional[str] = None
    requested_provider_id: Optional[str] = None
    state_reason: Optional[str] = None
    attempts: Optional[int] = None
    work_attempts_used: Optional[int] = None
    availability_attempts: Optional[int] = None
    provider_condition: Optional[str] = None
    next_eligible_utc: Optional[str] = None
    checkpoint_policy: Optional[str] = None
    checkpoint_commit: Optional[str] = None
    malformed_fields: tuple = ()

    def __post_init__(self):
        if not (valid_id(self.pipeline_id) and valid_id(self.worker_id)):
            raise ValueError("worker identity must be valid ids")
        if type(self.status) is not StatusView or self.status.source_kind != SOURCE_WORKER_STATE:
            raise ValueError("status must be a worker StatusView")
        checks = (
            (self.provider_id, sc._valid_provider_id), (self.requested_provider_id, sc._valid_provider_id),
            (self.state_reason, valid_code), (self.attempts, lambda v: _bounded_int(v, MAX_ATTEMPTS)),
            (self.work_attempts_used, lambda v: _bounded_int(v, MAX_ATTEMPTS)),
            (self.availability_attempts, lambda v: _bounded_int(v, MAX_ATTEMPTS)),
            (self.provider_condition, lambda v: _in(v, PROVIDER_CONDITIONS)),
            (self.next_eligible_utc, lambda v: normalized_utc(v) == v),
            (self.checkpoint_policy, lambda v: _in(v, CHECKPOINT_POLICIES)),
            (self.checkpoint_commit, lambda v: type(v) is str and _COMMIT_RE.fullmatch(v) is not None),
        )
        if not all(_optional(value, check) for value, check in checks):
            raise ValueError("worker field outside its contract")
        _check_malformed(self.malformed_fields, WORKER_PUBLIC_FIELDS)

    def to_dict(self) -> dict:
        return {
            "pipeline_id": self.pipeline_id, "worker_id": self.worker_id, "status": self.status.to_dict(),
            "provider_id": self.provider_id, "requested_provider_id": self.requested_provider_id,
            "state_reason": self.state_reason, "attempts": self.attempts,
            "work_attempts_used": self.work_attempts_used, "availability_attempts": self.availability_attempts,
            "provider_condition": self.provider_condition, "next_eligible_utc": self.next_eligible_utc,
            "checkpoint_policy": self.checkpoint_policy, "checkpoint_commit": self.checkpoint_commit,
            "malformed_fields": list(self.malformed_fields),
        }


@dataclass(frozen=True)
class PipelineView(_ControlPlaneGuarantees):
    """Allowlisted projection of one `pipeline_result.json`. A non-PRESENT
    status holds no workers; `rejected_workers` counts entries that could
    not be identified (invalid / duplicate id) and were never shown."""
    pipeline_id: str
    status: StatusView
    stop_reason: Optional[str] = None
    started_at_utc: Optional[str] = None
    ended_at_utc: Optional[str] = None
    workers_total: Optional[int] = None
    max_observed_concurrency: Optional[int] = None
    workers: tuple = ()
    rejected_workers: int = 0
    malformed_fields: tuple = ()

    def __post_init__(self):
        if not valid_id(self.pipeline_id):
            raise ValueError("pipeline_id must be a valid id")
        if type(self.status) is not StatusView or self.status.source_kind != SOURCE_PIPELINE_STATUS:
            raise ValueError("status must be a pipeline StatusView")
        if not (type(self.workers) is tuple and len(self.workers) <= MAX_WORKERS
                and all(type(w) is WorkerView and w.pipeline_id == self.pipeline_id for w in self.workers)
                and [w.worker_id for w in self.workers] == sorted({w.worker_id for w in self.workers})):
            raise ValueError("workers must be sorted unique WorkerViews of this pipeline")
        if self.status.condition != PRESENT and (self.workers or self.rejected_workers):
            raise ValueError("an unreadable pipeline shows no workers")
        checks = (
            (self.stop_reason, valid_code),
            (self.started_at_utc, lambda v: normalized_utc(v) == v),
            (self.ended_at_utc, lambda v: normalized_utc(v) == v),
            (self.workers_total, lambda v: _bounded_int(v, MAX_WORKERS)),
            (self.max_observed_concurrency, lambda v: _bounded_int(v, rp.MAX_PIPELINE_WORKERS)),
        )
        if not all(_optional(value, check) for value, check in checks):
            raise ValueError("pipeline field outside its contract")
        if not _bounded_int(self.rejected_workers, MAX_WORKERS):
            raise ValueError("rejected_workers must be a bounded count")
        _check_malformed(self.malformed_fields, PIPELINE_PUBLIC_FIELDS)

    def to_dict(self) -> dict:
        return {
            "pipeline_id": self.pipeline_id, "status": self.status.to_dict(), "stop_reason": self.stop_reason,
            "started_at_utc": self.started_at_utc, "ended_at_utc": self.ended_at_utc,
            "workers_total": self.workers_total, "max_observed_concurrency": self.max_observed_concurrency,
            "workers": [w.to_dict() for w in self.workers], "rejected_workers": self.rejected_workers,
            "malformed_fields": list(self.malformed_fields),
        }


def unreadable_pipeline(pipeline_id: str, cause: str) -> PipelineView:
    """The view of a pipeline whose result could not be used at all."""
    return PipelineView(pipeline_id, observe_status(SOURCE_PIPELINE_STATUS, None,
                                                    condition=CAUSE_CONDITION[cause], cause=cause))


def _take(entry: dict, name: str, convert, malformed: list):
    """Converted public field, or None (recording it if present but bad)."""
    if name not in entry or entry[name] is None:
        return None
    value = convert(entry[name])
    if value is None:
        malformed.append(name)
    return value


def _reason(entry: dict, name: str, malformed: list) -> Optional[str]:
    """Leading reason code; native prose is withheld, a non-string is malformed."""
    raw = entry.get(name)
    if raw is not None and type(raw) is not str:
        malformed.append(name)
    return reason_code(raw)


def _as(check):
    return lambda v: v if check(v) else None


def _project_worker(pipeline_id: str, entry: dict) -> WorkerView:
    malformed: list = []
    counts = _as(lambda v: _bounded_int(v, MAX_ATTEMPTS))
    fields = {
        "provider_id": _take(entry, "provider", _as(sc._valid_provider_id), malformed),
        "requested_provider_id": _take(entry, "requested_provider", _as(sc._valid_provider_id), malformed),
        "state_reason": _reason(entry, "state_reason", malformed),
        "attempts": _take(entry, "attempts", counts, malformed),
        "work_attempts_used": _take(entry, "work_attempts_used", counts, malformed),
        "availability_attempts": _take(entry, "availability_attempts", counts, malformed),
        "provider_condition": _take(entry, "provider_condition", _as(lambda v: _in(v, PROVIDER_CONDITIONS)), malformed),
        "next_eligible_utc": _take(entry, "next_eligible_utc", normalized_utc, malformed),
        "checkpoint_policy": _take(entry, "checkpoint_policy", _as(lambda v: _in(v, CHECKPOINT_POLICIES)), malformed),
        "checkpoint_commit": _take(entry, "checkpoint_commit",
                                   _as(lambda v: type(v) is str and _COMMIT_RE.fullmatch(v) is not None), malformed),
    }
    status = observe_status(SOURCE_WORKER_STATE, entry.get("state"))
    if status.cause == VALUE_UNRECOGNIZED:
        malformed.append("state")
    return WorkerView(pipeline_id, entry["id"], status, malformed_fields=sc._ordered(malformed, WORKER_PUBLIC_FIELDS),
                      **fields)


def project_pipeline_result(payload, pipeline_id: str) -> PipelineView:
    """Pure, allowlisted projection of an already-parsed
    `pipeline_result.json` for the pipeline directory `pipeline_id` (which
    the caller must already have validated). Never raises on `payload`."""
    if not valid_id(pipeline_id):
        raise ValueError("pipeline_id must be a valid id")
    if type(payload) is not dict:
        return unreadable_pipeline(pipeline_id, SOURCE_NOT_JSON)
    if not (sc._is_int(payload.get("schema_version")) and payload["schema_version"] == rp.PIPELINE_SCHEMA_VERSION):
        return unreadable_pipeline(pipeline_id, SCHEMA_UNSUPPORTED)
    if payload.get("pipeline_id") != pipeline_id:
        return unreadable_pipeline(pipeline_id, IDENTITY_MISMATCH)
    malformed: list = []
    raw_workers = payload.get("workers")
    entries = []
    if type(raw_workers) is list and len(raw_workers) <= MAX_WORKERS:
        entries = raw_workers
    else:
        malformed.append("workers")
    ids = [e.get("id") if type(e) is dict else None for e in entries]
    usable = [e for e, wid in zip(entries, ids) if valid_id(wid) and ids.count(wid) == 1]
    workers = tuple(sorted((_project_worker(pipeline_id, e) for e in usable), key=lambda w: w.worker_id))
    fields = {
        "stop_reason": _reason(payload, "stop_reason", malformed),
        "started_at_utc": _take(payload, "started_at_utc", normalized_utc, malformed),
        "ended_at_utc": _take(payload, "ended_at_utc", normalized_utc, malformed),
        "workers_total": _take(payload, "workers_total", _as(lambda v: _bounded_int(v, MAX_WORKERS)), malformed),
        "max_observed_concurrency": _take(payload, "max_observed_concurrency",
                                          _as(lambda v: _bounded_int(v, rp.MAX_PIPELINE_WORKERS)), malformed),
    }
    if fields["workers_total"] is not None and fields["workers_total"] != len(entries):
        malformed.append("workers_total")
        fields["workers_total"] = None
    status = observe_status(SOURCE_PIPELINE_STATUS, payload.get("status"))
    if status.condition != PRESENT:
        if status.cause == VALUE_UNRECOGNIZED:
            return unreadable_pipeline(pipeline_id, VALUE_UNRECOGNIZED)
        return unreadable_pipeline(pipeline_id, FIELD_ABSENT)
    return PipelineView(pipeline_id, status, workers=workers, rejected_workers=len(entries) - len(usable),
                        malformed_fields=sc._ordered(malformed, PIPELINE_PUBLIC_FIELDS), **fields)


# ---------------------------------------------------------------------------
# Observation + seal
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ControlPlaneObservation(_ControlPlaneGuarantees):
    """One sealed observation: pipelines and evidence references as of the
    caller's explicit `observed_at_utc`. `revision` fingerprints the
    canonical body, so any material change yields a new revision."""
    observed_at_utc: str
    pipelines: tuple = ()
    evidence: tuple = ()

    def __post_init__(self):
        if type(self.observed_at_utc) is not str or normalized_utc(self.observed_at_utc) != self.observed_at_utc:
            raise ValueError("observed_at_utc must be a normalized UTC instant")
        if not (type(self.pipelines) is tuple and len(self.pipelines) <= MAX_PIPELINES
                and all(type(p) is PipelineView for p in self.pipelines)
                and [p.pipeline_id for p in self.pipelines] == sorted({p.pipeline_id for p in self.pipelines})):
            raise ValueError("pipelines must be sorted unique PipelineViews")
        keys = [e.sort_key() for e in self.evidence] if type(self.evidence) is tuple else None
        if not (keys is not None and len(keys) <= MAX_EVIDENCE_REFS
                and all(type(e) is EvidenceRef for e in self.evidence) and keys == sorted(set(keys))):
            raise ValueError("evidence must be sorted unique EvidenceRefs")

    def _body(self) -> dict:
        return {
            "schema": SCHEMA, "schema_version": SCHEMA_VERSION, "observed_at_utc": self.observed_at_utc,
            "pipelines": [p.to_dict() for p in self.pipelines], "evidence": [e.to_dict() for e in self.evidence],
            **_ControlPlaneGuarantees._guarantees(),
        }

    @property
    def revision(self) -> str:
        return hashlib.sha256(sc._canonical(self._body()).encode("ascii")).hexdigest()

    def to_dict(self) -> dict:
        return {**self._body(), "revision": self.revision}


def canonical_json(observation: ControlPlaneObservation) -> str:
    """Stable, sorted, compact, size-bounded serialization of the exact
    contract type (a subclass cannot substitute `to_dict`)."""
    if type(observation) is not ControlPlaneObservation:
        raise TypeError("canonical_json accepts only a ControlPlaneObservation")
    text = sc._canonical(ControlPlaneObservation.to_dict(observation))
    if len(text) > MAX_CANONICAL_JSON_BYTES:
        raise ValueError("canonical observation exceeds MAX_CANONICAL_JSON_BYTES")
    return text
