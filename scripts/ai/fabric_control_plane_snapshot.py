"""FCP-11B-02: Fabric Control Plane snapshot of Runner pipelines and workers -
read-only, bounded, deterministic, fail-closed, OBSERVATION-ONLY.

Projects ONE explicit Runner state root into the FCP-11A-01 contract
(`fabric_control_plane_contract`): for every pipeline directory it opens only

    <pipeline_id>/pipeline.json                     PIPELINE_RECORD  (status only)
    <pipeline_id>/pipeline_result.json              PIPELINE_RESULT  (contract projection)
    <pipeline_id>/workers/<worker_id>/worker.json   WORKER_RECORD    (state only)
    <pipeline_id>/workers/<worker_id>/result.json   WORKER_RESULT    (state only)

and returns a sealed `ControlPlaneSnapshot`. Nothing else is opened (no
heartbeat, preflight, attempt evidence, prompt, stdout / stderr, lock or
ledger), nothing is written, executed, retried or inferred from logs.

Decisions
---------
* Director and Runner keep ALL execution, recovery, authorization, Git,
  process and resource authority. This module reads files under the caller's
  explicit root and nothing more: no clock (the observation instant is the
  caller's `observed_at_utc`), no environment, process, network, Git, ledger
  or store; it persists nothing. Every view keeps the FCP-11A-01
  zero-authority flags.
* Reuse, never redefine. Paths come only from `EvidenceRef.relative_parts`
  over validated ids; `pipeline_result.json` is projected by
  `project_pipeline_result`; statuses go through `observe_status` (so
  lifecycle / runner_outcome are the contract's own derivation); ids are
  `valid_id`; instants are `normalized_utc`. Every file read uses FCP-10D-01
  `admit_path` / `read_input_bytes` (absolute local path, no `..`, no link /
  junction / 8.3 alias, descriptor identity and final handle path verified
  before reading, bounded) and `parse_document` (strict UTF-8 JSON, no
  duplicate key / NaN, bounded depth and strings). The Runner layout,
  vocabularies and `PIPELINE_SCHEMA_VERSION` are `runner_pipeline`'s.
* Discovery is by directory listing, never by trusting ids inside a file:
  a pipeline / worker directory is considered only when its exact name is a
  `valid_id` (the evidence dir `_evidence` is not a pipeline). A link /
  junction entry with a valid name is shown, UNAVAILABLE / LINK_REFUSED, and
  never followed; anything else is only counted (`ignored_entries`), never
  named. A directory with more than `MAX_DIR_ENTRIES` entries is refused as a
  whole (UNAVAILABLE / SOURCE_TOO_LARGE), never sampled.
* Limits are explicit and deterministic: ids are sorted and the first
  `max_pipelines` pipelines / `max_workers` workers per pipeline (over the
  union of listed ids and worker directories) are read; the rest are counted
  as omitted. Each file is bounded by `max_file_bytes` (<= the FCP-10D-01
  cap). `max_pipelines * (2 + 2 * max_workers)` must fit the contract's
  `MAX_EVIDENCE_REFS`, so every read leaves exactly one `EvidenceRef`.
* Readability != meaning. An `EvidenceRef` says whether the bytes were
  admissible strict JSON (PRESENT with their sha256 / size); a status says
  what they mean. A file read and parsed but with a wrong schema, a foreign
  id or an unrecognized state is a PRESENT reference with a CORRUPT status.
  A file replaced while being read (`lstat` identity / size / mtime changed
  across the read, e.g. the Runner's atomic rewrite) is UNAVAILABLE /
  SOURCE_CHANGED_DURING_READ - read again later, never merged.
* Cross-file agreement is reported, not resolved. The Runner writes
  `worker.json`, `pipeline.json` and `pipeline_result.json` separately (and
  an operator re-queue rewrites only `worker.json`), so a snapshot may catch
  them disagreeing. `agreement` (derived, never stored) is CONSISTENT,
  DIVERGENT (two PRESENT values differ), UNVERIFIABLE (a source needed for
  the comparison is not PRESENT), NOT_LISTED (a worker directory absent from
  a readable `pipeline_result.json`) or NOT_ON_DISK (a listed worker with no
  directory of that exact name). None of them picks a winner.
* Absence is never success. A missing / corrupt / unavailable source is
  lifecycle UNKNOWN and runner_outcome UNKNOWN (contract derivation). A
  runner_outcome SUCCESS only says the Runner recorded SUCCESS: it is not an
  audit, not CI, not acceptance and never closes anything.
* Freshness is evidence-based: `evidence_as_of_utc` is the newest instant the
  Runner itself wrote in what was read (`pipeline.json` / `worker.json`
  `updated_at_utc`, `result.json` `written_at_utc`), None when there is none.
  It is never compared with a clock and never used to reinterpret a status.
* Seal: `revision` is the sha256 of the canonical snapshot body, which embeds
  the observation's own revision; equal inputs give byte-equal
  `canonical_json`.

Limitations (documented, not implemented here)
----------------------------------------------
* Directory listings are by name: a directory swapped for a junction between
  the `lstat` check and the listing could expose names (only `valid_id` ones,
  never content); every FILE is still refused unless its open handle's final
  path is the approved one.
* `parse_document` refuses strings over 4096 characters, so a `worker.json` /
  `result.json` carrying such a native value (e.g. very long manifest
  metadata) is reported CORRUPT / SOURCE_NOT_JSON; nesting beyond its depth
  is UNAVAILABLE / SOURCE_TOO_LARGE. Files above `max_file_bytes` are never
  read.
* `result.json` has no schema_version in the Runner; its identity is checked
  by `pipeline_id` / `worker_id` only.
* Attempt evidence, heartbeats, the factory ledger and the Director DAG are
  out of this stage.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Optional

try:
    from scripts.ai import fabric_control_plane_contract as cp
    from scripts.ai import fabric_resource_quota_contract as qc
    from scripts.ai import fabric_resource_quota_report as qrep
    from scripts.ai import fabric_scheduler_contract as sc
    from scripts.ai import runner_pipeline as rp
except ImportError:  # pragma: no cover - direct script execution
    import fabric_control_plane_contract as cp  # type: ignore[no-redef]
    import fabric_resource_quota_contract as qc  # type: ignore[no-redef]
    import fabric_resource_quota_report as qrep  # type: ignore[no-redef]
    import fabric_scheduler_contract as sc  # type: ignore[no-redef]
    import runner_pipeline as rp  # type: ignore[no-redef]

SCHEMA = "fcp11b02-control-plane-snapshot-v1"
SCHEMA_VERSION = 1

MAX_FILE_BYTES = qrep.MAX_INPUT_BYTES
MAX_DIR_ENTRIES = 4096
DEFAULT_MAX_PIPELINES = 32
DEFAULT_MAX_WORKERS = 32
WORKERS_DIRNAME = "workers"

AGREEMENT_CONSISTENT = "CONSISTENT"
AGREEMENT_DIVERGENT = "DIVERGENT"
AGREEMENT_UNVERIFIABLE = "UNVERIFIABLE"
AGREEMENT_NOT_LISTED = "NOT_LISTED"
AGREEMENT_NOT_ON_DISK = "NOT_ON_DISK"
AGREEMENTS = (AGREEMENT_CONSISTENT, AGREEMENT_DIVERGENT, AGREEMENT_UNVERIFIABLE, AGREEMENT_NOT_LISTED,
              AGREEMENT_NOT_ON_DISK)

# FCP-10D-01 refusal code -> contract cause. Every other parse refusal is
# "not admissible strict JSON".
_REFUSAL_CAUSES = {
    "REPORT_PATH_NOT_ADMISSIBLE": cp.PATH_REFUSED, "REPORT_PATH_NETWORK_REFUSED": cp.PATH_REFUSED,
    "REPORT_PATH_LINK_REFUSED": cp.LINK_REFUSED, "REPORT_INPUT_FILE_INVALID": cp.SOURCE_UNREADABLE,
    "REPORT_INPUT_TOO_LARGE": cp.SOURCE_TOO_LARGE, "REPORT_INPUT_TOO_DEEP": cp.SOURCE_TOO_LARGE,
}

_DIR, _FILE, _LINK = "DIR", "FILE", "LINK"


# ---------------------------------------------------------------------------
# Bounded, fail-closed reads (FCP-10D-01 discipline, never a new one)
# ---------------------------------------------------------------------------

def _probe(path: str) -> tuple:
    """`(kind, stat, cause)`: kind DIR / FILE / LINK / OTHER, or a cause."""
    try:
        st = os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None, None, cp.SOURCE_ABSENT
    except (OSError, ValueError):
        return None, None, cp.SOURCE_UNREADABLE
    return qrep._classify(st), st, None


def _identity(st) -> tuple:
    return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns


@dataclass(frozen=True)
class _Read:
    cause: Optional[str] = None
    payload: object = None
    sha256: Optional[str] = None
    size: Optional[int] = None


def _read_json(path: str, max_bytes: int) -> _Read:
    """One bounded strict-JSON read; never raises, never echoes the path."""
    kind, before, cause = _probe(path)
    if cause is not None:
        return _Read(cause)
    if kind != _FILE:
        return _Read(cp.LINK_REFUSED if kind == _LINK else cp.SOURCE_UNREADABLE)
    if before.st_size > max_bytes:
        return _Read(cp.SOURCE_TOO_LARGE)
    try:
        data = qrep.read_input_bytes(path)
    except qrep.ReportError as exc:
        return _Read(_REFUSAL_CAUSES.get(exc.code, cp.SOURCE_UNREADABLE))
    except (OSError, ValueError):
        return _Read(cp.SOURCE_UNREADABLE)
    if len(data) > max_bytes:
        return _Read(cp.SOURCE_TOO_LARGE)
    _, after, _ = _probe(path)
    if after is None or _identity(after) != _identity(before) or len(data) != before.st_size:
        return _Read(cp.SOURCE_CHANGED_DURING_READ)
    try:
        payload = qrep.parse_document(data)
    except qrep.ReportError as exc:
        return _Read(cp.SOURCE_TOO_LARGE if exc.code == "REPORT_INPUT_TOO_DEEP" else cp.SOURCE_NOT_JSON)
    return _Read(None, payload, hashlib.sha256(data).hexdigest(), len(data))


def _list_dir(path: str) -> tuple:
    """`(cause, names, links, ignored)` of one plain directory: valid-id
    subdirectory names, valid-id link names, and a count of the rest."""
    kind, _, cause = _probe(path)
    if cause is not None:
        return cause, (), (), 0
    if kind != _DIR:
        return (cp.LINK_REFUSED if kind == _LINK else cp.SOURCE_UNREADABLE), (), (), 0
    names, links, ignored, seen = [], [], 0, 0
    try:
        with os.scandir(path) as entries:
            for entry in entries:
                seen += 1
                if seen > MAX_DIR_ENTRIES:
                    return cp.SOURCE_TOO_LARGE, (), (), 0
                found = qrep._classify(entry.stat(follow_symlinks=False))
                if not cp.valid_id(entry.name) or found not in (_DIR, _LINK):
                    ignored += 1
                else:
                    (names if found == _DIR else links).append(entry.name)
    except (OSError, ValueError):
        return cp.SOURCE_UNREADABLE, (), (), 0
    return None, tuple(sorted(names)), tuple(sorted(links)), ignored


def _admit_root(root) -> Optional[str]:
    """None when `root` is an absolute, local, plain directory that is its
    own real path; otherwise the cause."""
    if isinstance(root, os.PathLike):
        root = os.fspath(root)
    try:
        qrep.admit_path(root)
    except qrep.ReportError as exc:
        return _REFUSAL_CAUSES.get(exc.code, cp.PATH_REFUSED)
    kind, _, cause = _probe(root)
    if cause is not None:
        return cause
    if kind != _DIR:
        return cp.LINK_REFUSED if kind == _LINK else cp.SOURCE_UNREADABLE
    try:
        real = os.path.realpath(root)
    except (OSError, ValueError):
        return cp.SOURCE_UNREADABLE
    if os.path.normcase(real) != os.path.normcase(os.path.normpath(root)):
        return cp.LINK_REFUSED
    return None


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

def _not_present(kind: str, cause: str) -> cp.StatusView:
    return cp.observe_status(kind, None, condition=cp.CAUSE_CONDITION[cause], cause=cause)


def _agreement(*statuses) -> Optional[str]:
    """DIVERGENT when two PRESENT values differ, else None."""
    present = {s.source_value for s in statuses if s.condition == cp.PRESENT}
    return AGREEMENT_DIVERGENT if len(present) > 1 else None


def _optional_utc(value) -> bool:
    return value is None or (type(value) is str and cp.normalized_utc(value) == value)


@dataclass(frozen=True)
class WorkerSnapshot(cp._ControlPlaneGuarantees):
    """One worker as three independent sources: its `pipeline_result.json`
    entry (`listed_status`), its `worker.json` (`record_status`) and its
    `result.json` (`result_status`). `listed` is True / False when a readable
    `pipeline_result.json` does / does not hold the id, None when that cannot
    be told (result not PRESENT, or entries the contract rejected).
    `agreement` is derived."""
    pipeline_id: str
    worker_id: str
    on_disk: bool
    listed: Optional[bool]
    listed_status: cp.StatusView
    record_status: cp.StatusView
    result_status: cp.StatusView
    record_updated_at_utc: Optional[str] = None
    result_written_at_utc: Optional[str] = None

    def __post_init__(self):
        if not (cp.valid_id(self.pipeline_id) and cp.valid_id(self.worker_id)):
            raise ValueError("worker identity must be valid ids")
        if type(self.on_disk) is not bool or type(self.listed) not in (bool, type(None)):
            raise ValueError("on_disk must be a bool and listed a bool or None")
        if not (self.on_disk or self.listed is True):
            raise ValueError("a worker is known from its directory or its listing")
        if self.listed is not True and self.listed_status.condition == cp.PRESENT:
            raise ValueError("an unlisted worker has no listed status")
        for status in (self.listed_status, self.record_status, self.result_status):
            if type(status) is not cp.StatusView or status.source_kind != cp.SOURCE_WORKER_STATE:
                raise ValueError("statuses must be worker StatusViews")
        if not self.on_disk and (self.record_status.cause, self.result_status.cause) != (cp.SOURCE_ABSENT,) * 2:
            raise ValueError("a worker with no directory has no record or result")
        if not (_optional_utc(self.record_updated_at_utc) and _optional_utc(self.result_written_at_utc)):
            raise ValueError("instants must be normalized UTC")

    @property
    def agreement(self) -> str:
        if not self.on_disk:
            return AGREEMENT_NOT_ON_DISK
        if self.listed is False:
            return AGREEMENT_NOT_LISTED
        divergent = _agreement(self.listed_status, self.record_status, self.result_status)
        if divergent:
            return divergent
        if self.listed_status.condition == cp.PRESENT and self.record_status.condition == cp.PRESENT:
            return AGREEMENT_CONSISTENT
        return AGREEMENT_UNVERIFIABLE

    def instants(self) -> tuple:
        return tuple(v for v in (self.record_updated_at_utc, self.result_written_at_utc) if v is not None)

    def to_dict(self) -> dict:
        return {
            "pipeline_id": self.pipeline_id, "worker_id": self.worker_id, "on_disk": self.on_disk,
            "listed": self.listed, "listed_status": self.listed_status.to_dict(),
            "record_status": self.record_status.to_dict(),
            "result_status": self.result_status.to_dict(), "record_updated_at_utc": self.record_updated_at_utc,
            "result_written_at_utc": self.result_written_at_utc, "agreement": self.agreement,
        }


@dataclass(frozen=True)
class PipelineSnapshot(cp._ControlPlaneGuarantees):
    """One pipeline: the contract `PipelineView` of `pipeline_result.json`
    (serialized inside the observation), the `pipeline.json` status and the
    worker snapshots read under its `workers/` directory."""
    view: cp.PipelineView
    record_status: cp.StatusView
    record_updated_at_utc: Optional[str] = None
    workers_condition: str = cp.PRESENT
    workers_cause: Optional[str] = None
    workers: tuple = ()
    workers_omitted: int = 0
    ignored_entries: int = 0

    def __post_init__(self):
        if type(self.view) is not cp.PipelineView:
            raise ValueError("view must be a PipelineView")
        if type(self.record_status) is not cp.StatusView or self.record_status.source_kind != cp.SOURCE_PIPELINE_STATUS:
            raise ValueError("record_status must be a pipeline StatusView")
        if not _optional_utc(self.record_updated_at_utc):
            raise ValueError("instants must be normalized UTC")
        cp._check_condition(self.workers_condition, self.workers_cause)
        if not (type(self.workers) is tuple and all(type(w) is WorkerSnapshot and w.pipeline_id == self.pipeline_id
                                                    for w in self.workers)
                and [w.worker_id for w in self.workers] == sorted({w.worker_id for w in self.workers})):
            raise ValueError("workers must be sorted unique WorkerSnapshots of this pipeline")
        if not (cp._bounded_int(self.workers_omitted, cp.MAX_WORKERS + MAX_DIR_ENTRIES)
                and cp._bounded_int(self.ignored_entries, MAX_DIR_ENTRIES)):
            raise ValueError("counts must be bounded")

    @property
    def pipeline_id(self) -> str:
        return self.view.pipeline_id

    @property
    def agreement(self) -> str:
        divergent = _agreement(self.view.status, self.record_status)
        if divergent:
            return divergent
        if self.view.status.condition == cp.PRESENT and self.record_status.condition == cp.PRESENT:
            return AGREEMENT_CONSISTENT
        return AGREEMENT_UNVERIFIABLE

    def instants(self) -> tuple:
        own = (self.record_updated_at_utc,) if self.record_updated_at_utc is not None else ()
        return own + tuple(i for w in self.workers for i in w.instants())

    def to_dict(self) -> dict:
        return {
            "pipeline_id": self.pipeline_id, "record_status": self.record_status.to_dict(),
            "record_updated_at_utc": self.record_updated_at_utc, "agreement": self.agreement,
            "workers_condition": self.workers_condition, "workers_cause": self.workers_cause,
            "workers": [w.to_dict() for w in self.workers], "workers_omitted": self.workers_omitted,
            "ignored_entries": self.ignored_entries,
        }


@dataclass(frozen=True)
class ControlPlaneSnapshot(cp._ControlPlaneGuarantees):
    """A sealed snapshot of one Runner state root. A root that is not
    PRESENT holds no pipelines."""
    observation: cp.ControlPlaneObservation
    root_condition: str = cp.PRESENT
    root_cause: Optional[str] = None
    pipelines: tuple = ()
    pipelines_omitted: int = 0
    ignored_entries: int = 0

    def __post_init__(self):
        if type(self.observation) is not cp.ControlPlaneObservation:
            raise ValueError("observation must be a ControlPlaneObservation")
        cp._check_condition(self.root_condition, self.root_cause)
        if not (type(self.pipelines) is tuple and all(type(p) is PipelineSnapshot for p in self.pipelines)
                and tuple(p.view for p in self.pipelines) == self.observation.pipelines):
            raise ValueError("pipelines must be the observation's pipelines, in order")
        if self.root_condition != cp.PRESENT and (self.pipelines or self.observation.evidence):
            raise ValueError("an unreadable root shows nothing")
        if not (cp._bounded_int(self.pipelines_omitted, MAX_DIR_ENTRIES)
                and cp._bounded_int(self.ignored_entries, MAX_DIR_ENTRIES)):
            raise ValueError("counts must be bounded")

    @property
    def evidence_as_of_utc(self) -> Optional[str]:
        """Newest Runner-written instant among what was read; never a clock."""
        instants = [i for p in self.pipelines for i in p.instants()]
        return max(instants, key=qc.parse_utc) if instants else None

    def _body(self) -> dict:
        return {
            "schema": SCHEMA, "schema_version": SCHEMA_VERSION, "observation": self.observation.to_dict(),
            "root_condition": self.root_condition, "root_cause": self.root_cause,
            "root_actor": cp.CONDITION_ACTOR[self.root_condition],
            "pipelines": [p.to_dict() for p in self.pipelines], "pipelines_omitted": self.pipelines_omitted,
            "ignored_entries": self.ignored_entries, "evidence_as_of_utc": self.evidence_as_of_utc,
            **cp._ControlPlaneGuarantees._guarantees(),
        }

    @property
    def revision(self) -> str:
        return hashlib.sha256(sc._canonical(self._body()).encode("ascii")).hexdigest()

    def to_dict(self) -> dict:
        return {**self._body(), "revision": self.revision}


def canonical_json(snapshot: ControlPlaneSnapshot) -> str:
    """Stable, sorted, compact, size-bounded serialization of the exact type."""
    if type(snapshot) is not ControlPlaneSnapshot:
        raise TypeError("canonical_json accepts only a ControlPlaneSnapshot")
    text = sc._canonical(ControlPlaneSnapshot.to_dict(snapshot))
    if len(text) > cp.MAX_CANONICAL_JSON_BYTES:
        raise ValueError("canonical snapshot exceeds MAX_CANONICAL_JSON_BYTES")
    return text


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------

class _Reader:
    """Reads one evidence kind under the root and records its EvidenceRef."""

    def __init__(self, root: str, max_bytes: int):
        self.root, self.max_bytes, self.refs = root, max_bytes, []

    def path(self, *parts) -> str:
        return os.path.join(self.root, *parts)

    def read(self, kind: str, **ids) -> _Read:
        parts = self.unread(kind, cp.SOURCE_ABSENT, **ids).relative_parts()
        result = _read_json(self.path(*parts), self.max_bytes)
        self.refs.append(self.unread(kind, result.cause, **ids) if result.cause else cp.EvidenceRef(
            kind, cp.PRESENT, content_sha256=result.sha256, size_bytes=result.size, **ids))
        return result

    def skip(self, kind: str, cause: str, **ids) -> _Read:
        self.refs.append(self.unread(kind, cause, **ids))
        return _Read(cause)

    @staticmethod
    def unread(kind: str, cause: str, **ids) -> cp.EvidenceRef:
        return cp.EvidenceRef(kind, cp.CAUSE_CONDITION[cause], cause=cause, **ids)


def _status_of(read: _Read, kind: str, field: str, identity: dict, *, versioned: bool) -> cp.StatusView:
    """The native status `field` of a read file, fail-closed."""
    if read.cause is not None:
        return _not_present(kind, read.cause)
    payload = read.payload
    if type(payload) is not dict:
        return _not_present(kind, cp.SOURCE_NOT_JSON)
    if versioned and not (sc._is_int(payload.get("schema_version"))
                          and payload["schema_version"] == rp.PIPELINE_SCHEMA_VERSION):
        return _not_present(kind, cp.SCHEMA_UNSUPPORTED)
    for path, expected in identity.items():
        node = payload
        for key in path:
            node = node.get(key) if type(node) is dict else None
        if type(node) is not str or node != expected:
            return _not_present(kind, cp.IDENTITY_MISMATCH)
    return cp.observe_status(kind, payload.get(field))


def _instant(read: _Read, status: cp.StatusView, field: str) -> Optional[str]:
    """A Runner-written instant, only from a file whose identity held."""
    if status.cause in (None, cp.FIELD_ABSENT, cp.VALUE_UNRECOGNIZED):
        return cp.normalized_utc(read.payload.get(field))
    return None


def _listing(view: cp.PipelineView, worker_id: str) -> tuple:
    """`(listed, listed_status)` of one worker id in a projected result."""
    listed = {w.worker_id: w for w in view.workers}
    if worker_id in listed:
        return True, listed[worker_id].status
    if view.status.condition != cp.PRESENT:
        return None, _not_present(cp.SOURCE_WORKER_STATE, view.status.cause)
    if view.rejected_workers:  # an entry the contract rejected may be this one
        return None, _not_present(cp.SOURCE_WORKER_STATE, cp.FIELD_MALFORMED)
    return False, _not_present(cp.SOURCE_WORKER_STATE, cp.FIELD_ABSENT)


def _worker(reader: _Reader, view: cp.PipelineView, wid: str, kind_on_disk: Optional[str]) -> WorkerSnapshot:
    pid = view.pipeline_id
    ids = {"pipeline_id": pid, "worker_id": wid}
    listed, listed_status = _listing(view, wid)
    if kind_on_disk is None or kind_on_disk == _LINK:
        cause = cp.SOURCE_ABSENT if kind_on_disk is None else cp.LINK_REFUSED
        record, result = reader.skip("WORKER_RECORD", cause, **ids), reader.skip("WORKER_RESULT", cause, **ids)
    else:
        record, result = reader.read("WORKER_RECORD", **ids), reader.read("WORKER_RESULT", **ids)
    record_status = _status_of(record, cp.SOURCE_WORKER_STATE, "state", {("spec", "id"): wid}, versioned=True)
    result_status = _status_of(result, cp.SOURCE_WORKER_STATE, "state",
                               {("pipeline_id",): pid, ("worker_id",): wid}, versioned=False)
    return WorkerSnapshot(
        pid, wid, kind_on_disk is not None, listed, listed_status, record_status, result_status,
        record_updated_at_utc=_instant(record, record_status, "updated_at_utc"),
        result_written_at_utc=_instant(result, result_status, "written_at_utc"),
    )


def _pipeline(reader: _Reader, pid: str, is_link: bool, max_workers: int) -> PipelineSnapshot:
    if is_link:
        result = reader.skip("PIPELINE_RESULT", cp.LINK_REFUSED, pipeline_id=pid)
        record = reader.skip("PIPELINE_RECORD", cp.LINK_REFUSED, pipeline_id=pid)
    else:
        result = reader.read("PIPELINE_RESULT", pipeline_id=pid)
        record = reader.read("PIPELINE_RECORD", pipeline_id=pid)
    if result.cause:
        view = cp.unreadable_pipeline(pid, result.cause)
    else:
        view = cp.project_pipeline_result(result.payload, pid)
    record_status = _status_of(record, cp.SOURCE_PIPELINE_STATUS, "status", {("pipeline_id",): pid}, versioned=True)
    if is_link:
        cause, dirs, links, ignored = cp.LINK_REFUSED, (), (), 0
    else:
        cause, dirs, links, ignored = _list_dir(reader.path(pid, WORKERS_DIRNAME))
    on_disk = {**{w: _DIR for w in dirs}, **{w: _LINK for w in links}}
    universe = sorted(set(on_disk) | {w.worker_id for w in view.workers})
    workers = tuple(_worker(reader, view, wid, on_disk.get(wid)) for wid in universe[:max_workers])
    return PipelineSnapshot(
        view, record_status, record_updated_at_utc=_instant(record, record_status, "updated_at_utc"),
        workers_condition=cp.CAUSE_CONDITION[cause] if cause else cp.PRESENT, workers_cause=cause,
        workers=workers, workers_omitted=max(len(universe) - max_workers, 0), ignored_entries=ignored,
    )


def _check_limits(max_pipelines, max_workers, max_file_bytes) -> None:
    if not (cp._bounded_int(max_pipelines, cp.MAX_PIPELINES) and max_pipelines >= 1):
        raise ValueError("max_pipelines must be an int in 1..MAX_PIPELINES")
    if not (cp._bounded_int(max_workers, cp.MAX_WORKERS) and max_workers >= 1):
        raise ValueError("max_workers must be an int in 1..MAX_WORKERS")
    if not (cp._bounded_int(max_file_bytes, MAX_FILE_BYTES) and max_file_bytes >= 1):
        raise ValueError("max_file_bytes must be an int in 1..MAX_FILE_BYTES")
    if max_pipelines * (2 + 2 * max_workers) > cp.MAX_EVIDENCE_REFS:
        raise ValueError("max_pipelines * (2 + 2 * max_workers) exceeds MAX_EVIDENCE_REFS")


def take_snapshot(state_root, observed_at_utc: str, *, max_pipelines: int = DEFAULT_MAX_PIPELINES,
                  max_workers: int = DEFAULT_MAX_WORKERS, max_file_bytes: int = MAX_FILE_BYTES) -> ControlPlaneSnapshot:
    """Read-only snapshot of the Runner state root `state_root` as of the
    caller's explicit `observed_at_utc`. Raises `ValueError` only for a bad
    instant or limit (caller error); every problem with the root or its
    files is reported in the snapshot, never raised and never echoed."""
    _check_limits(max_pipelines, max_workers, max_file_bytes)
    if type(observed_at_utc) is not str or cp.normalized_utc(observed_at_utc) != observed_at_utc:
        raise ValueError("observed_at_utc must be a normalized UTC instant")
    root_cause = _admit_root(state_root)
    cause, dirs, links, ignored = (root_cause, (), (), 0) if root_cause else _list_dir(os.fspath(state_root))
    if cause is not None:
        return ControlPlaneSnapshot(cp.ControlPlaneObservation(observed_at_utc),
                                    root_condition=cp.CAUSE_CONDITION[cause], root_cause=cause)
    candidates = {**{p: False for p in dirs}, **{p: True for p in links}}
    if candidates.pop(rp.EVIDENCE_ROOT_DIRNAME, None) is not None:
        ignored += 1
    ordered = sorted(candidates)
    reader = _Reader(os.fspath(state_root), max_file_bytes)
    pipelines = tuple(_pipeline(reader, pid, candidates[pid], max_workers) for pid in ordered[:max_pipelines])
    observation = cp.ControlPlaneObservation(observed_at_utc, pipelines=tuple(p.view for p in pipelines),
                                             evidence=tuple(sorted(reader.refs, key=cp.EvidenceRef.sort_key)))
    return ControlPlaneSnapshot(observation, pipelines=pipelines,
                                pipelines_omitted=max(len(ordered) - max_pipelines, 0), ignored_entries=ignored)
