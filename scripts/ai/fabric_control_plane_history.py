"""FCP-11D-04: Fabric Control Plane history of the factory ledger - read-only,
bounded, deterministic, fail-closed, OBSERVATION-ONLY.

Projects the native `runner_factory_ledger` event log of ONE explicit
factory root (`<factory_root>/events.jsonl`, the ledger's ONLY truth) into a
sealed, paginated `ControlPlaneHistory` of historical events - start, finish,
work produced, state change - optionally correlated with one FCP-11B-02
`ControlPlaneSnapshot`. Nothing else is opened: `modules.json` (a disposable
cache, never authoritative) and the `lock/` directory are never read; nothing
is written, appended, materialized or persisted.

Public schema (`ControlPlaneHistory.to_dict`)
---------------------------------------------
Per event (`LedgerEvent`): `source_event_id` (native `event_id`, verbatim),
`source_line` (1-based physical line in `events.jsonl`), `order` (1-based
position in the native order), `fingerprint` (sha256 of the line's bytes),
`copies` (identical lines collapsed into it), `event_type` (native),
`category` (START / FINISH / WORK_PRODUCED / STATE_CHANGE), `schema_version`,
`timestamp_utc` (the ledger's append instant, normalized), `project`,
`module`, `module_version`, `pipeline_id`, `worker_id`, `provider`, `role`,
`base_commit`, `result_commit`, `recorded_state` (native `state`, verbatim
code), `state_reason` (leading code only), `certification_status`,
`malformed_fields` and `anomalies`.
Per correlation (`LedgerCorrelation`): ids, `in_snapshot`, `snapshot_record`
(the snapshot's `worker.json` StatusView), `ledger_events` / `ledger_starts` /
`ledger_finishes`, `ledger_last_event_type`, `ledger_last_at_utc`,
`ledger_last_recorded_state` (of the last WORKER_STARTED / WORKER_FINISHED),
`ledger_unmatched_start` and `agreement`.
Never public: `worktree` (a path), `branch`, `closer`, `extra` (the
contract's `LEDGER_WITHHELD_FIELDS`), any other native key, any path and any
rejected line's content.

Decisions
---------
* Director and Runner keep ALL execution, recovery, authorization, Git,
  process and resource authority. This module has no clock (the instant is
  the caller's `observed_at_utc`), environment, process, network, Git or
  store, never calls `FactoryLedger` (whose `append` writes and whose readers
  are not fail-closed) and keeps the FCP-11A-01 zero-authority flags.
* Adapt, never clone, the ledger: its event vocabulary
  (`LEDGER_EVENT_TYPES`), `LEDGER_SCHEMA_VERSION`, `EVENTS_FILENAME` (through
  the contract's FACTORY_EVENTS `EvidenceRef`), its order (`read_events`:
  `(timestamp_utc, event_id)`, here on the parsed instant with the physical
  line as last tie-break), its filter (`filter_events`, applied to the public
  events) and its start / finish pairing (`factory_status`, whose
  `active_workers` becomes `ledger_unmatched_start`). Reads reuse FCP-11B-02
  `_admit_root` / `_probe` / `_identity` and FCP-10D-01 `read_input_bytes`
  (no `..`, link, junction or 8.3 alias; descriptor identity and final handle
  path verified; bounded); each line is strict JSON via `parse_document`.
* The native reader skips bad lines silently; here every rejected line is
  counted by cause (`rejected`: SOURCE_NOT_JSON, SOURCE_TOO_LARGE,
  VALUE_UNRECOGNIZED event type, SCHEMA_UNSUPPORTED, FIELD_ABSENT /
  FIELD_MALFORMED `event_id` or `timestamp_utc`) and never echoed. An event
  that cannot be identified or ordered is not shown. A present-but-invalid
  optional field is None and named in `malformed_fields`. Native ids are
  `uuid4().hex`; `source_event_id` accepts exactly that shape or a contract
  `valid_id`.
* Duplicates are reported, never resolved: lines with the same event id and
  byte-identical content are one event with `copies` > 1 and anomaly
  DUPLICATE_EVENT_COPIES; the same id with different content keeps every
  copy, each flagged EVENT_ID_CONFLICT and excluded from correlation.
* History is never current state. `recorded_state` is what the ledger wrote
  at `timestamp_utc`; it is not classified into a lifecycle / runner
  outcome, and the module fold (`materialize_modules` / `modules.json`) is
  not presented. `ledger_unmatched_start` only says the ledger holds a
  WORKER_STARTED with no later WORKER_FINISHED for that pair: it is NOT
  "running" (the Runner may have crashed or the ledger append failed). A
  WORK_PRODUCED event is the Runner's record, not verified evidence
  (FCP-11C-03 verifies attempt evidence).
* Correlation only by validated identity: an event joins a snapshot worker
  only on the exact `(pipeline_id, worker_id)` pair; two pipelines with equal
  worker ids never mix. `agreement` is CONSISTENT / DIVERGENT (the last
  worker-level `recorded_state` vs the snapshot's PRESENT `worker.json`
  state), UNVERIFIABLE (either side missing, conflicting events, an
  incomplete ledger or snapshot), NOT_IN_LEDGER or NOT_IN_SNAPSHOT (only when
  the other side is complete). Neither side wins.
* Absence is never success: a missing / unreadable root or ledger shows no
  events and no correlations (`root_condition` / `ledger_condition` with the
  contract cause and actor).
* Bounded and deterministic: the file is bounded by `max_file_bytes` (<= the
  FCP-10D-01 cap); filters (ids, provider, event type, `since_utc` inclusive,
  `until_utc` exclusive) select from the ordered events, `offset` / `limit`
  (<= MAX_PAGE_SIZE) page them, `next_offset` continues; correlations are
  capped at MAX_CORRELATIONS (rest counted). An offset is only meaningful for
  the same ledger bytes (`FACTORY_EVENTS` sha256 in `observation`). The seal
  (`revision`) is the sha256 of the canonical body; equal inputs give
  byte-equal `canonical_json`.

Limitations (documented, not implemented here)
----------------------------------------------
* `events.jsonl` larger than the FCP-10D-01 cap (256 KiB) is UNAVAILABLE /
  SOURCE_TOO_LARGE as a whole: no tail or range read exists in the governed
  reader. A bounded ranged reader is a separate WO.
* The ledger is append-only: a Runner append during the read is UNAVAILABLE
  / SOURCE_CHANGED_DURING_READ; read again later.
* Ids are compared verbatim (case-sensitive), never by physical identity.
* WORK_PRODUCT_CREATED / CHECKPOINT_CREATED are not cross-checked against
  FCP-11C-03 attempt evidence; the Director's own history is not read.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from typing import Optional

try:
    from scripts.ai import fabric_control_plane_contract as cp
    from scripts.ai import fabric_control_plane_snapshot as snap
    from scripts.ai import fabric_resource_quota_contract as qc
    from scripts.ai import fabric_resource_quota_report as qrep
    from scripts.ai import fabric_scheduler_contract as sc
    from scripts.ai import runner_factory_ledger as flog
except ImportError:  # pragma: no cover - direct script execution
    import fabric_control_plane_contract as cp  # type: ignore[no-redef]
    import fabric_control_plane_snapshot as snap  # type: ignore[no-redef]
    import fabric_resource_quota_contract as qc  # type: ignore[no-redef]
    import fabric_resource_quota_report as qrep  # type: ignore[no-redef]
    import fabric_scheduler_contract as sc  # type: ignore[no-redef]
    import runner_factory_ledger as flog  # type: ignore[no-redef]

SCHEMA = "fcp11d04-control-plane-history-v1"
SCHEMA_VERSION = 1

MAX_FILE_BYTES = snap.MAX_FILE_BYTES
MAX_PAGE_SIZE = 500
DEFAULT_PAGE_SIZE = 100
MAX_OFFSET = MAX_FILE_BYTES  # a line is at least one byte
MAX_CORRELATIONS = 2048

CATEGORY_START = "START"
CATEGORY_FINISH = "FINISH"
CATEGORY_WORK_PRODUCED = "WORK_PRODUCED"
CATEGORY_STATE_CHANGE = "STATE_CHANGE"
CATEGORIES = (CATEGORY_START, CATEGORY_FINISH, CATEGORY_WORK_PRODUCED, CATEGORY_STATE_CHANGE)
EVENT_CATEGORY = {
    flog.WORKER_STARTED: CATEGORY_START, flog.WORKER_FINISHED: CATEGORY_FINISH,
    flog.WORK_PRODUCT_CREATED: CATEGORY_WORK_PRODUCED, flog.CHECKPOINT_CREATED: CATEGORY_WORK_PRODUCED,
    **{t: CATEGORY_STATE_CHANGE for t in (flog.CERTIFICATION_STARTED, flog.CERTIFICATION_FINISHED,
                                          flog.MODULE_STATE_CHANGED, flog.MODULE_CERTIFIED, flog.MODULE_CLOSED)},
}
_WORKER_EVENTS = (flog.WORKER_STARTED, flog.WORKER_FINISHED)

DUPLICATE_EVENT_COPIES = "DUPLICATE_EVENT_COPIES"
EVENT_ID_CONFLICT = "EVENT_ID_CONFLICT"
ANOMALIES = (DUPLICATE_EVENT_COPIES, EVENT_ID_CONFLICT)

AGREEMENT_NOT_IN_LEDGER = "NOT_IN_LEDGER"
AGREEMENT_NOT_IN_SNAPSHOT = "NOT_IN_SNAPSHOT"
AGREEMENTS = (snap.AGREEMENT_CONSISTENT, snap.AGREEMENT_DIVERGENT, snap.AGREEMENT_UNVERIFIABLE,
              AGREEMENT_NOT_IN_LEDGER, AGREEMENT_NOT_IN_SNAPSHOT)

# Native ledger key -> public name; every other public key keeps its name.
_RENAMED = {"event_id": "source_event_id", "state": "recorded_state"}
_NATIVE_NAME = {public: native for native, public in _RENAMED.items()}
_OPTIONAL_FIELDS = ("project", "module", "module_version", "pipeline_id", "worker_id", "provider", "role",
                    "base_commit", "result_commit", "recorded_state", "state_reason", "certification_status")
EVENT_PUBLIC_FIELDS = ("source_event_id", "event_type", "schema_version", "timestamp_utc") + _OPTIONAL_FIELDS
_NATIVE_EVENT_ID_RE = re.compile(r"[0-9a-f]{32}")


def _commit(value) -> bool:
    return type(value) is str and cp._COMMIT_RE.fullmatch(value) is not None


_FIELD_CHECKS = {
    "project": cp.valid_id, "module": cp.valid_id, "module_version": cp.valid_id, "pipeline_id": cp.valid_id,
    "worker_id": cp.valid_id, "provider": sc._valid_provider_id, "role": cp.valid_id, "base_commit": _commit,
    "result_commit": _commit, "recorded_state": cp.valid_code, "certification_status": cp.valid_code,
}


def valid_event_id(value) -> bool:
    """The ledger's own `uuid4().hex`, or a contract-safe id."""
    return type(value) is str and (_NATIVE_EVENT_ID_RE.fullmatch(value) is not None or cp.valid_id(value))


def _utc(value) -> bool:
    return type(value) is str and cp.normalized_utc(value) == value


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LedgerEvent(cp._ControlPlaneGuarantees):
    """One historical ledger event, allowlisted. See the module docstring."""
    source_event_id: str
    source_line: int
    order: int
    fingerprint: str
    event_type: str
    timestamp_utc: str
    copies: int = 1
    project: Optional[str] = None
    module: Optional[str] = None
    module_version: Optional[str] = None
    pipeline_id: Optional[str] = None
    worker_id: Optional[str] = None
    provider: Optional[str] = None
    role: Optional[str] = None
    base_commit: Optional[str] = None
    result_commit: Optional[str] = None
    recorded_state: Optional[str] = None
    state_reason: Optional[str] = None
    certification_status: Optional[str] = None
    malformed_fields: tuple = ()
    anomalies: tuple = ()

    def __post_init__(self):
        if not valid_event_id(self.source_event_id):
            raise ValueError("source_event_id invalid")
        if not (cp._bounded_int(self.source_line, MAX_OFFSET) and cp._bounded_int(self.order, MAX_OFFSET)
                and self.source_line >= 1 and self.order >= 1
                and cp._bounded_int(self.copies, MAX_OFFSET) and self.copies >= 1):
            raise ValueError("line, order and copies must be bounded positive ints")
        if not (type(self.fingerprint) is str and sc._FINGERPRINT_RE.fullmatch(self.fingerprint)):
            raise ValueError("fingerprint must be a sha256")
        if not cp._in(self.event_type, cp.LEDGER_EVENT_TYPES) or not _utc(self.timestamp_utc):
            raise ValueError("event type or timestamp outside the ledger contract")
        checks = dict(_FIELD_CHECKS, state_reason=cp.valid_code)
        if not all(cp._optional(getattr(self, name), check) for name, check in checks.items()):
            raise ValueError("event field outside its contract")
        cp._check_malformed(self.malformed_fields, EVENT_PUBLIC_FIELDS)
        if not (type(self.anomalies) is tuple and all(cp._in(a, ANOMALIES) for a in self.anomalies)
                and self.anomalies == sc._ordered(self.anomalies, ANOMALIES)):
            raise ValueError("anomalies must be ordered known codes")
        if (self.copies > 1) != (DUPLICATE_EVENT_COPIES in self.anomalies):
            raise ValueError("collapsed copies are exactly the DUPLICATE_EVENT_COPIES anomaly")

    @property
    def category(self) -> str:
        return EVENT_CATEGORY[self.event_type]

    @property
    def conflicted(self) -> bool:
        return EVENT_ID_CONFLICT in self.anomalies

    def to_dict(self) -> dict:
        body = {name: getattr(self, name) for name in _OPTIONAL_FIELDS}
        body.update(
            source_event_id=self.source_event_id, source_line=self.source_line, order=self.order,
            fingerprint=self.fingerprint, copies=self.copies, event_type=self.event_type, category=self.category,
            schema_version=flog.LEDGER_SCHEMA_VERSION, timestamp_utc=self.timestamp_utc,
            malformed_fields=list(self.malformed_fields), anomalies=list(self.anomalies),
        )
        return body


@dataclass(frozen=True)
class LedgerCorrelation(cp._ControlPlaneGuarantees):
    """One (pipeline_id, worker_id) pair as the ledger recorded it and as the
    snapshot read it. Historical counts and the snapshot status side by side;
    `agreement` is reported, never resolved."""
    pipeline_id: str
    worker_id: str
    in_snapshot: bool
    agreement: str
    snapshot_record: Optional[cp.StatusView] = None
    ledger_events: int = 0
    ledger_starts: int = 0
    ledger_finishes: int = 0
    ledger_last_event_type: Optional[str] = None
    ledger_last_at_utc: Optional[str] = None
    ledger_last_recorded_state: Optional[str] = None
    ledger_unmatched_start: bool = False

    def __post_init__(self):
        if not (cp.valid_id(self.pipeline_id) and cp.valid_id(self.worker_id)):
            raise ValueError("correlation identity must be valid ids")
        if type(self.in_snapshot) is not bool or type(self.ledger_unmatched_start) is not bool:
            raise ValueError("flags must be bools")
        if self.in_snapshot != (type(self.snapshot_record) is cp.StatusView):
            raise ValueError("a snapshot record is shown exactly for a snapshot worker")
        if self.snapshot_record is not None and self.snapshot_record.source_kind != cp.SOURCE_WORKER_STATE:
            raise ValueError("snapshot_record must be a worker StatusView")
        if not (cp._bounded_int(self.ledger_events, MAX_OFFSET)
                and cp._bounded_int(self.ledger_starts, self.ledger_events)
                and cp._bounded_int(self.ledger_finishes, self.ledger_events - self.ledger_starts)):
            raise ValueError("ledger counts must add up")
        seen = self.ledger_events > 0
        if seen != (self.ledger_last_event_type is not None) or seen != (self.ledger_last_at_utc is not None):
            raise ValueError("a last event is shown exactly when the ledger has events")
        if not (cp._optional(self.ledger_last_event_type, lambda v: cp._in(v, cp.LEDGER_EVENT_TYPES))
                and cp._optional(self.ledger_last_at_utc, _utc)
                and cp._optional(self.ledger_last_recorded_state, cp.valid_code)):
            raise ValueError("last event outside the ledger contract")
        if self.ledger_unmatched_start and not self.ledger_starts:
            raise ValueError("an unmatched start needs a start")
        if not cp._in(self.agreement, AGREEMENTS):
            raise ValueError("unknown agreement")
        if self.agreement == AGREEMENT_NOT_IN_LEDGER and not (self.in_snapshot and not seen):
            raise ValueError("NOT_IN_LEDGER is a snapshot worker with no ledger events")
        if self.agreement == AGREEMENT_NOT_IN_SNAPSHOT and self.in_snapshot:
            raise ValueError("NOT_IN_SNAPSHOT is a ledger pair absent from the snapshot")
        if self.agreement in (snap.AGREEMENT_CONSISTENT, snap.AGREEMENT_DIVERGENT) and not (
                self.in_snapshot and self.snapshot_record.condition == cp.PRESENT
                and cp._in(self.ledger_last_recorded_state, cp.WORKER_STATES)):
            raise ValueError("agreement needs both PRESENT sides")

    def to_dict(self) -> dict:
        return {
            "pipeline_id": self.pipeline_id, "worker_id": self.worker_id, "in_snapshot": self.in_snapshot,
            "snapshot_record": None if self.snapshot_record is None else self.snapshot_record.to_dict(),
            "ledger_events": self.ledger_events, "ledger_starts": self.ledger_starts,
            "ledger_finishes": self.ledger_finishes, "ledger_last_event_type": self.ledger_last_event_type,
            "ledger_last_at_utc": self.ledger_last_at_utc,
            "ledger_last_recorded_state": self.ledger_last_recorded_state,
            "ledger_unmatched_start": self.ledger_unmatched_start, "agreement": self.agreement,
        }


@dataclass(frozen=True)
class ControlPlaneHistory(cp._ControlPlaneGuarantees):
    """A sealed page of one factory ledger. `observation` seals the
    FACTORY_EVENTS reference (none when the root itself is not PRESENT)."""
    observation: cp.ControlPlaneObservation
    root_condition: str = cp.PRESENT
    root_cause: Optional[str] = None
    lines_total: int = 0
    rejected: tuple = ()
    events_total: int = 0
    matching: int = 0
    offset: int = 0
    limit: int = DEFAULT_PAGE_SIZE
    events: tuple = ()
    filters: tuple = ()
    snapshot_revision: Optional[str] = None
    correlations: tuple = ()
    correlations_omitted: int = 0

    def __post_init__(self):
        if type(self.observation) is not cp.ControlPlaneObservation or self.observation.pipelines:
            raise ValueError("observation must be a ControlPlaneObservation of evidence only")
        cp._check_condition(self.root_condition, self.root_cause)
        refs = self.observation.evidence
        if self.root_condition != cp.PRESENT:
            if refs:
                raise ValueError("an unreadable root seals no ledger")
        elif not (len(refs) == 1 and refs[0].kind == "FACTORY_EVENTS"):
            raise ValueError("a readable root seals exactly its FACTORY_EVENTS reference")
        if not (type(self.rejected) is tuple and all(type(r) is tuple and len(r) == 2 and cp._in(r[0], cp.CAUSES)
                                                     and cp._bounded_int(r[1], MAX_OFFSET) and r[1] >= 1
                                                     for r in self.rejected)
                and [r[0] for r in self.rejected] == list(sc._ordered([r[0] for r in self.rejected], cp.CAUSES))):
            raise ValueError("rejected must be ordered (cause, count) pairs")
        counts = (self.lines_total, self.events_total, self.matching, self.offset)
        if not all(cp._bounded_int(c, MAX_OFFSET) for c in counts):
            raise ValueError("counts must be bounded")
        if not (self.matching <= self.events_total <= self.lines_total - sum(r[1] for r in self.rejected)):
            raise ValueError("counts must add up")
        if not (cp._bounded_int(self.limit, MAX_PAGE_SIZE) and self.limit >= 1):
            raise ValueError("limit must be in 1..MAX_PAGE_SIZE")
        if not (type(self.events) is tuple and all(type(e) is LedgerEvent for e in self.events)
                and len(self.events) == max(min(self.limit, self.matching - self.offset), 0)
                and [e.order for e in self.events] == sorted({e.order for e in self.events})):
            raise ValueError("events must be the page's LedgerEvents in order")
        if self.ledger_condition != cp.PRESENT and (self.lines_total or self.correlations):
            raise ValueError("an unreadable ledger shows nothing")
        if not (type(self.filters) is tuple and all(type(f) is tuple and len(f) == 2 for f in self.filters)
                and [f[0] for f in self.filters] == sorted({f[0] for f in self.filters})):
            raise ValueError("filters must be sorted (name, value) pairs")
        if not cp._optional(self.snapshot_revision, lambda v: type(v) is str and sc._FINGERPRINT_RE.fullmatch(v)):
            raise ValueError("snapshot_revision must be a sha256")
        keys = [(c.pipeline_id, c.worker_id) for c in self.correlations] if type(self.correlations) is tuple else None
        if not (keys is not None and all(type(c) is LedgerCorrelation for c in self.correlations)
                and keys == sorted(set(keys)) and len(keys) <= MAX_CORRELATIONS):
            raise ValueError("correlations must be sorted unique LedgerCorrelations")
        if self.snapshot_revision is None and (self.correlations or self.correlations_omitted):
            raise ValueError("correlations need a snapshot")
        if not cp._bounded_int(self.correlations_omitted, MAX_OFFSET + cp.MAX_PIPELINES * cp.MAX_WORKERS):
            raise ValueError("correlations_omitted must be bounded")

    @property
    def ledger_condition(self) -> str:
        refs = self.observation.evidence
        return refs[0].condition if refs else self.root_condition

    @property
    def ledger_cause(self) -> Optional[str]:
        refs = self.observation.evidence
        return refs[0].cause if refs else self.root_cause

    @property
    def next_offset(self) -> Optional[int]:
        end = self.offset + len(self.events)
        return end if end < self.matching else None

    def _body(self) -> dict:
        return {
            "schema": SCHEMA, "schema_version": SCHEMA_VERSION, "observation": self.observation.to_dict(),
            "root_condition": self.root_condition, "root_cause": self.root_cause,
            "root_actor": cp.CONDITION_ACTOR[self.root_condition], "ledger_condition": self.ledger_condition,
            "ledger_cause": self.ledger_cause, "ledger_actor": cp.CONDITION_ACTOR[self.ledger_condition],
            "lines_total": self.lines_total, "rejected": dict(self.rejected), "events_total": self.events_total,
            "filters": dict(self.filters), "matching": self.matching, "offset": self.offset, "limit": self.limit,
            "next_offset": self.next_offset, "events": [e.to_dict() for e in self.events],
            "snapshot_revision": self.snapshot_revision, "correlations": [c.to_dict() for c in self.correlations],
            "correlations_omitted": self.correlations_omitted, **cp._ControlPlaneGuarantees._guarantees(),
        }

    @property
    def revision(self) -> str:
        return hashlib.sha256(sc._canonical(self._body()).encode("ascii")).hexdigest()

    def to_dict(self) -> dict:
        return {**self._body(), "revision": self.revision}


def canonical_json(history: ControlPlaneHistory) -> str:
    """Stable, sorted, compact, size-bounded serialization of the exact type."""
    if type(history) is not ControlPlaneHistory:
        raise TypeError("canonical_json accepts only a ControlPlaneHistory")
    text = sc._canonical(ControlPlaneHistory.to_dict(history))
    if len(text) > cp.MAX_CANONICAL_JSON_BYTES:
        raise ValueError("canonical history exceeds MAX_CANONICAL_JSON_BYTES")
    return text


# ---------------------------------------------------------------------------
# Reading and parsing
# ---------------------------------------------------------------------------

def _read_bytes(path: str, max_bytes: int) -> tuple:
    """`(cause, data)` of one bounded raw read (the FCP-11B-02 `_read_json`
    discipline without its whole-document parse); never raises."""
    kind, before, cause = snap._probe(path)
    if cause is not None:
        return cause, None
    if kind != snap._FILE:
        return (cp.LINK_REFUSED if kind == snap._LINK else cp.SOURCE_UNREADABLE), None
    if before.st_size > max_bytes:
        return cp.SOURCE_TOO_LARGE, None
    try:
        data = qrep.read_input_bytes(path)
    except qrep.ReportError as exc:
        return snap._REFUSAL_CAUSES.get(exc.code, cp.SOURCE_UNREADABLE), None
    except (OSError, ValueError):
        return cp.SOURCE_UNREADABLE, None
    if len(data) > max_bytes:
        return cp.SOURCE_TOO_LARGE, None
    _, after, _ = snap._probe(path)
    if after is None or snap._identity(after) != snap._identity(before) or len(data) != before.st_size:
        return cp.SOURCE_CHANGED_DURING_READ, None
    return None, data


def _parse_line(raw: bytes) -> tuple:
    """`(cause, payload)` of one non-empty line: strict JSON of a known,
    identifiable, orderable event of the supported schema."""
    try:
        payload = qrep.parse_document(raw)
    except qrep.ReportError as exc:
        return (cp.SOURCE_TOO_LARGE if exc.code == "REPORT_INPUT_TOO_DEEP" else cp.SOURCE_NOT_JSON), None
    if type(payload) is not dict:
        return cp.SOURCE_NOT_JSON, None
    if not cp._in(payload.get("event_type"), cp.LEDGER_EVENT_TYPES):
        return cp.VALUE_UNRECOGNIZED, None
    if not (sc._is_int(payload.get("schema_version")) and payload["schema_version"] == flog.LEDGER_SCHEMA_VERSION):
        return cp.SCHEMA_UNSUPPORTED, None
    for name, check in (("event_id", valid_event_id), ("timestamp_utc", cp.normalized_utc)):
        if payload.get(name) is None:
            return cp.FIELD_ABSENT, None
        if not check(payload[name]):
            return cp.FIELD_MALFORMED, None
    return None, payload


def _project(payload: dict) -> dict:
    """Allowlisted, validated public fields of one accepted event."""
    malformed, fields = [], {}
    for public in _OPTIONAL_FIELDS:
        raw = payload.get(_NATIVE_NAME.get(public, public))
        if public == "state_reason":
            if raw is not None and type(raw) is not str:
                malformed.append(public)
            fields[public] = cp.reason_code(raw)
        elif raw is None or _FIELD_CHECKS[public](raw):
            fields[public] = raw
        else:
            malformed.append(public)
            fields[public] = None
    return {"event_type": payload["event_type"], "source_event_id": payload["event_id"],
            "timestamp_utc": cp.normalized_utc(payload["timestamp_utc"]),
            "malformed_fields": sc._ordered(malformed, EVENT_PUBLIC_FIELDS), **fields}


def _events(data: bytes) -> tuple:
    """`(lines_total, rejected, events)`: every accepted event in the native
    order, duplicates collapsed or flagged (see the module docstring)."""
    rejected: dict = {}
    accepted = []  # (instant, event_id, line, fingerprint, fields)
    lines_total = 0
    for number, line in enumerate(data.split(b"\n"), start=1):
        line = line.strip()
        if not line:
            continue
        lines_total += 1
        cause, payload = _parse_line(line)
        if cause is not None:
            rejected[cause] = rejected.get(cause, 0) + 1
            continue
        fields = _project(payload)
        accepted.append((qc.parse_utc(fields["timestamp_utc"]), fields["source_event_id"], number,
                         hashlib.sha256(line).hexdigest(), fields))
    accepted.sort(key=lambda a: a[:3])
    by_id: dict = {}
    for item in accepted:
        by_id.setdefault(item[1], []).append(item)
    kept = []
    for item in accepted:
        group = by_id[item[1]]
        if len({g[3] for g in group}) > 1:
            kept.append((item, 1, (EVENT_ID_CONFLICT,)))
        elif item is min(group, key=lambda g: g[2]):
            kept.append((item, len(group), (DUPLICATE_EVENT_COPIES,) if len(group) > 1 else ()))
    events = tuple(
        LedgerEvent(source_line=item[2], order=order, fingerprint=item[3], copies=copies, anomalies=anomalies,
                    **item[4])
        for order, (item, copies, anomalies) in enumerate(kept, start=1)
    )
    return lines_total, tuple((c, rejected[c]) for c in cp.CAUSES if c in rejected), events


# ---------------------------------------------------------------------------
# Correlation with a snapshot
# ---------------------------------------------------------------------------

def _snapshot_covers(snapshot, pipelines: dict, pid: str) -> bool:
    """True when the snapshot would have shown `pid`'s every worker."""
    if snapshot.root_condition != cp.PRESENT:
        return False
    pipeline = pipelines.get(pid)
    if pipeline is None:
        return snapshot.pipelines_omitted == 0
    return pipeline.workers_condition == cp.PRESENT and pipeline.workers_omitted == 0


def _correlations(events: tuple, ledger_complete: bool, snapshot) -> tuple:
    pipelines = {p.pipeline_id: p for p in snapshot.pipelines}
    workers = {(p.pipeline_id, w.worker_id): w for p in snapshot.pipelines for w in p.workers}
    paired = [e for e in events if e.pipeline_id is not None and e.worker_id is not None]
    trusted = [e for e in paired if not e.conflicted]
    conflicted = {(e.pipeline_id, e.worker_id) for e in paired if e.conflicted}
    unmatched = {(w["pipeline_id"], w["worker_id"])
                 for w in flog.factory_status([e.to_dict() for e in trusted])["active_workers"]}
    keys = sorted(set(workers) | {(e.pipeline_id, e.worker_id) for e in trusted} | conflicted)
    views = []
    for key in keys[:MAX_CORRELATIONS]:
        own = [e for e in trusted if (e.pipeline_id, e.worker_id) == key]
        worker_level = [e for e in own if e.event_type in _WORKER_EVENTS]
        last_state = worker_level[-1].recorded_state if worker_level else None
        worker = workers.get(key)
        record = worker.record_status if worker is not None else None
        if key in conflicted:
            agreement = snap.AGREEMENT_UNVERIFIABLE
        elif worker is None:
            agreement = AGREEMENT_NOT_IN_SNAPSHOT if _snapshot_covers(snapshot, pipelines, key[0]) \
                else snap.AGREEMENT_UNVERIFIABLE
        elif not own:
            agreement = AGREEMENT_NOT_IN_LEDGER if ledger_complete else snap.AGREEMENT_UNVERIFIABLE
        elif record.condition == cp.PRESENT and cp._in(last_state, cp.WORKER_STATES):
            agreement = snap.AGREEMENT_CONSISTENT if record.source_value == last_state else snap.AGREEMENT_DIVERGENT
        else:
            agreement = snap.AGREEMENT_UNVERIFIABLE
        views.append(LedgerCorrelation(
            key[0], key[1], worker is not None, agreement, snapshot_record=record, ledger_events=len(own),
            ledger_starts=sum(e.event_type == flog.WORKER_STARTED for e in own),
            ledger_finishes=sum(e.event_type == flog.WORKER_FINISHED for e in own),
            ledger_last_event_type=own[-1].event_type if own else None,
            ledger_last_at_utc=own[-1].timestamp_utc if own else None,
            ledger_last_recorded_state=last_state, ledger_unmatched_start=key in unmatched,
        ))
    return tuple(views), max(len(keys) - MAX_CORRELATIONS, 0)


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------

_ID_FILTERS = ("module", "role", "pipeline_id", "worker_id")


def _check_arguments(observed_at_utc, snapshot, filters: dict, offset, limit, max_file_bytes) -> None:
    if not _utc(observed_at_utc):
        raise ValueError("observed_at_utc must be a normalized UTC instant")
    if snapshot is not None and type(snapshot) is not snap.ControlPlaneSnapshot:
        raise TypeError("snapshot must be a ControlPlaneSnapshot")
    checks = {**{n: cp.valid_id for n in _ID_FILTERS}, "provider": sc._valid_provider_id,
              "event_type": lambda v: cp._in(v, cp.LEDGER_EVENT_TYPES), "since_utc": _utc, "until_utc": _utc}
    for name, value in filters.items():
        if not checks[name](value):
            raise ValueError(f"filter {name} is invalid")
    if not cp._bounded_int(offset, MAX_OFFSET):
        raise ValueError("offset must be an int in 0..MAX_OFFSET")
    if not (cp._bounded_int(limit, MAX_PAGE_SIZE) and limit >= 1):
        raise ValueError("limit must be an int in 1..MAX_PAGE_SIZE")
    if not (cp._bounded_int(max_file_bytes, MAX_FILE_BYTES) and max_file_bytes >= 1):
        raise ValueError("max_file_bytes must be an int in 1..MAX_FILE_BYTES")


def _select(events: tuple, filters: dict) -> list:
    identity = {k: v for k, v in filters.items() if k not in ("since_utc", "until_utc")}
    chosen = {e["order"] for e in flog.filter_events([e.to_dict() for e in events], **identity)}
    since, until = qc.parse_utc(filters.get("since_utc")), qc.parse_utc(filters.get("until_utc"))
    return [e for e in events if e.order in chosen
            and (since is None or qc.parse_utc(e.timestamp_utc) >= since)
            and (until is None or qc.parse_utc(e.timestamp_utc) < until)]


def take_history(factory_root, observed_at_utc: str, *, snapshot=None, module=None, role=None, provider=None,
                 pipeline_id=None, worker_id=None, event_type=None, since_utc=None, until_utc=None, offset: int = 0,
                 limit: int = DEFAULT_PAGE_SIZE, max_file_bytes: int = MAX_FILE_BYTES) -> ControlPlaneHistory:
    """Read-only, paginated history of the factory ledger under the explicit
    `factory_root` as of the caller's `observed_at_utc`, optionally
    correlated with `snapshot` (a `ControlPlaneSnapshot`). Raises only for a
    caller error (bad instant, filter, page or limit; wrong snapshot type);
    every problem with the root or the ledger is reported, never raised and
    never echoed."""
    filters = {k: v for k, v in (("module", module), ("role", role), ("provider", provider),
                                 ("pipeline_id", pipeline_id), ("worker_id", worker_id), ("event_type", event_type),
                                 ("since_utc", since_utc), ("until_utc", until_utc)) if v is not None}
    _check_arguments(observed_at_utc, snapshot, filters, offset, limit, max_file_bytes)
    page = {"offset": offset, "limit": limit, "filters": tuple(sorted(filters.items())),
            "snapshot_revision": None if snapshot is None else snapshot.revision}
    root_cause = snap._admit_root(factory_root)
    if root_cause is not None:
        return ControlPlaneHistory(cp.ControlPlaneObservation(observed_at_utc),
                                   root_condition=cp.CAUSE_CONDITION[root_cause], root_cause=root_cause, **page)
    unread = cp.EvidenceRef("FACTORY_EVENTS", cp.MISSING, cause=cp.SOURCE_ABSENT)
    cause, data = _read_bytes(os.path.join(os.fspath(factory_root), *unread.relative_parts()), max_file_bytes)
    if cause is not None:
        ref = cp.EvidenceRef("FACTORY_EVENTS", cp.CAUSE_CONDITION[cause], cause=cause)
        return ControlPlaneHistory(cp.ControlPlaneObservation(observed_at_utc, evidence=(ref,)), **page)
    ref = cp.EvidenceRef("FACTORY_EVENTS", cp.PRESENT, content_sha256=hashlib.sha256(data).hexdigest(),
                         size_bytes=len(data))
    lines_total, rejected, events = _events(data)
    selected = _select(events, filters)
    correlations, omitted = ((), 0) if snapshot is None else _correlations(
        events, not rejected and not any(e.conflicted for e in events), snapshot)
    return ControlPlaneHistory(
        cp.ControlPlaneObservation(observed_at_utc, evidence=(ref,)), lines_total=lines_total, rejected=rejected,
        events_total=len(events), matching=len(selected), events=tuple(selected[offset:offset + limit]),
        correlations=correlations, correlations_omitted=omitted, **page,
    )
