"""FCP-11G-07: Fabric Control Plane read gateway for UI / CLI - read-only,
bounded, deterministic, fail-closed, OBSERVATION-ONLY.

ONE Python entry point (`query`) that composes the sealed FCP-11 projections
for a consumer (the FCP-11 CLI, a future UI) without re-deciding anything:

    summary     FCP-11B-02 snapshot + FCP-11C-03 evidence + FCP-11F-06 attention
    pipelines   FCP-11B-02 snapshot (per pipeline / worker statuses) + attention
    worker      one (pipeline_id, worker_id): snapshot, contract view,
                evidence attempts and attention item
    activity    FCP-11D-04 factory-ledger page, correlated with the snapshot
    attention   FCP-11F-06 prioritized items
    resources   FCP-11E-05 providers / quota / cost (+ at most one report file)

Request (`GatewayRequest`)
--------------------------
`query`, `allowed_roots` (1..MAX_ALLOWED_ROOTS absolute, local, plain
directories that are their own real path), `state_root` (the Runner state
root), `observed_at_utc` (the caller's explicit instant: the gateway has no
clock), optional `factory_root` (required by `activity`), optional
`report_file` (FCP-10D-01 input document, `resources` only), optional
`pipeline_id` / `worker_id` (validated contract ids; `worker` needs both),
`event_type` (a native ledger event type), `offset` / `limit` (paging,
`limit` <= MAX_LIMIT). Every source path must be admissible (FCP-10D-01
`admit_path`: absolute, local, no `..`, NUL, stream, UNC or URL form) and lie,
both as spelled and as resolved, inside one allowed root; otherwise the
request is refused before anything is opened.

Response (`query(...)` dict, schema `SCHEMA`)
---------------------------------------------
`schema`, `schema_version`, `query`, `observed_at_utc`, `request` (ids,
event type, paging and WHICH optional sources were given - never a path),
`sources` (the revisions of every projection used), `result` (the query's
explicit field allowlist below), `page` (`offset`, `limit`, `total`,
`returned`, `next_offset`; None for summary / worker), the zero-authority
flags (FCP-11A-01 + FCP-11F-06 + `network_used` / `write_performed`, all
False) and `revision` (sha256 of the canonical rest).

Decisions
---------
* Director and Runner keep ALL execution, recovery, authorization, Git,
  process and resource authority. The gateway only calls the existing
  read-only projections (`take_snapshot`, `take_evidence`, `take_history`,
  `observe_resources`, `observe_attention`) with their defaults; it opens no
  file itself, writes nothing, has no clock, environment, network, HTTP
  server, socket, subprocess, Git or store, and never runs FCP-6 / C02
  (their advisories are not consolidated here: attention binds them ABSENT).
* Compose, never re-decide: lifecycles, outcomes, agreements, conditions,
  attention classes and holds are the projections' own values, copied
  through explicit allowlists. Counts are plain tallies of those values.
  Absence stays UNKNOWN / MISSING / UNAVAILABLE; nothing becomes SUCCESS.
* Safe output: after composition every string goes through `_sanitize`
  (secret-shaped -> REDACTED, path-shaped -> REDACTED, non-printable /
  non-ASCII -> '?', length <= MAX_STRING_CHARS); the canonical JSON is ASCII
  and bounded by MAX_RESPONSE_BYTES (refused, never truncated silently).
* Safe errors: a refusal is a `GatewayError` with a fixed code and text;
  never a path, id, value, OS message or traceback. Problems INSIDE an
  admitted root (missing, corrupt, link, too large) are reported in the
  result by the projections, never raised.
* Deterministic: equal requests over equal bytes give byte-equal
  `render_json` output.

Limitations (documented, not implemented here)
----------------------------------------------
* Snapshot / evidence limits are the projections' defaults (32 pipelines,
  32 workers per pipeline, 8 attempts per worker); omitted counts are shown.
* `activity` inherits FCP-11D-04's 256 KiB ledger cap (larger: UNAVAILABLE).
* Each query re-reads its sources; consecutive queries may observe different
  Runner writes (compare `sources` revisions).
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from typing import Optional

try:
    from scripts.ai import fabric_control_plane_attention as at
    from scripts.ai import fabric_control_plane_contract as cp
    from scripts.ai import fabric_control_plane_evidence as ev
    from scripts.ai import fabric_control_plane_history as hist
    from scripts.ai import fabric_control_plane_resources as res
    from scripts.ai import fabric_control_plane_snapshot as snap
    from scripts.ai import fabric_resource_quota_report as qrep
    from scripts.ai import fabric_scheduler_contract as sc
except ImportError:  # pragma: no cover - direct script execution
    import fabric_control_plane_attention as at  # type: ignore[no-redef]
    import fabric_control_plane_contract as cp  # type: ignore[no-redef]
    import fabric_control_plane_evidence as ev  # type: ignore[no-redef]
    import fabric_control_plane_history as hist  # type: ignore[no-redef]
    import fabric_control_plane_resources as res  # type: ignore[no-redef]
    import fabric_control_plane_snapshot as snap  # type: ignore[no-redef]
    import fabric_resource_quota_report as qrep  # type: ignore[no-redef]
    import fabric_scheduler_contract as sc  # type: ignore[no-redef]

SCHEMA = "fcp11g07-control-plane-gateway-v1"
SCHEMA_VERSION = 1

QUERY_SUMMARY = "summary"
QUERY_PIPELINES = "pipelines"
QUERY_WORKER = "worker"
QUERY_ACTIVITY = "activity"
QUERY_ATTENTION = "attention"
QUERY_RESOURCES = "resources"
QUERIES = (QUERY_SUMMARY, QUERY_PIPELINES, QUERY_WORKER, QUERY_ACTIVITY, QUERY_ATTENTION, QUERY_RESOURCES)

MAX_ALLOWED_ROOTS = 8
DEFAULT_LIMIT = 50
MAX_LIMIT = hist.MAX_PAGE_SIZE
MAX_OFFSET = hist.MAX_OFFSET
MAX_RESPONSE_BYTES = qrep.MAX_REPORT_BYTES
MAX_STRING_CHARS = qrep.MAX_STRING_CHARS
REDACTED = "[REDACTED]"

_PATH_SHAPED_RE = re.compile(r"^[A-Za-z]:|^[\\/~]|\\|/[^/]*/")
_PRINTABLE_RE = re.compile(r"[^\x20-\x7e]")
# Digests the projections already validated (sha256, Git commit, native
# ledger event id): entropy-shaped by nature, never a credential here.
_DIGEST_RE = re.compile(r"[0-9a-f]{32}|[0-9a-f]{40}|[0-9a-f]{64}")

_USAGE = "GATEWAY_USAGE_INVALID"
_MESSAGES = {
    _USAGE: "the request is invalid",
    "GATEWAY_QUERY_UNKNOWN": "the query is not one of the supported read queries",
    "GATEWAY_INSTANT_INVALID": "observed_at_utc must be a normalized UTC instant",
    "GATEWAY_ID_INVALID": "an id or event type is invalid",
    "GATEWAY_PAGE_INVALID": "offset or limit is out of range",
    "GATEWAY_SOURCE_REQUIRED": "the query needs a source that was not given",
    "GATEWAY_ROOTS_INVALID": "allowed roots must be absolute, local, plain directories",
    "GATEWAY_PATH_NOT_ADMISSIBLE": "a source path must be absolute and local without '..', NUL or streams",
    "GATEWAY_PATH_OUTSIDE_ROOTS": "a source path lies outside the allowed roots",
    "GATEWAY_RESPONSE_TOO_LARGE": "the response exceeds the size limit",
    "GATEWAY_INTERNAL_ERROR": "the response could not be produced",
}
USAGE_CODES = frozenset({_USAGE, "GATEWAY_QUERY_UNKNOWN", "GATEWAY_INSTANT_INVALID", "GATEWAY_ID_INVALID",
                         "GATEWAY_PAGE_INVALID", "GATEWAY_SOURCE_REQUIRED"})


class GatewayError(Exception):
    """Refusal to answer. `code` and `message` are fixed text; never a path,
    id, value or OS message. `usage` tells a caller error from a refusal."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code
        self.message = _MESSAGES[code]
        self.usage = code in USAGE_CODES

    def render(self) -> str:
        return f"error: {self.code}: {self.message}"


@dataclass(frozen=True)
class GatewayRequest:
    """One read query; see the module docstring for every field."""
    query: str
    allowed_roots: tuple
    state_root: str
    observed_at_utc: str
    factory_root: Optional[str] = None
    report_file: Optional[str] = None
    pipeline_id: Optional[str] = None
    worker_id: Optional[str] = None
    event_type: Optional[str] = None
    offset: int = 0
    limit: int = DEFAULT_LIMIT


# ---------------------------------------------------------------------------
# Request validation (nothing is opened before every check passed)
# ---------------------------------------------------------------------------

def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def _inside(path: str, root: str) -> bool:
    path, root = _norm(path), _norm(root)
    return path == root or path.startswith(root.rstrip("\\/") + os.sep)


def _admitted_roots(roots) -> tuple:
    if type(roots) not in (tuple, list) or not 1 <= len(roots) <= MAX_ALLOWED_ROOTS:
        raise GatewayError("GATEWAY_ROOTS_INVALID")
    for root in roots:
        try:
            qrep.admit_path(root)
        except qrep.ReportError:
            raise GatewayError("GATEWAY_ROOTS_INVALID") from None
        if snap._admit_root(root) is not None:
            raise GatewayError("GATEWAY_ROOTS_INVALID")
    return tuple(roots)


def _check_source(path, roots: tuple) -> None:
    """Admissible and inside an allowed root, as spelled and as resolved."""
    try:
        qrep.admit_path(path)
        real = os.path.realpath(path)
    except qrep.ReportError:
        raise GatewayError("GATEWAY_PATH_NOT_ADMISSIBLE") from None
    except (OSError, ValueError):
        raise GatewayError("GATEWAY_PATH_NOT_ADMISSIBLE") from None
    if not any(_inside(path, r) and _inside(real, r) for r in roots):
        raise GatewayError("GATEWAY_PATH_OUTSIDE_ROOTS")


def _check_request(request) -> None:
    if type(request) is not GatewayRequest:
        raise GatewayError(_USAGE)
    if not cp._in(request.query, QUERIES):
        raise GatewayError("GATEWAY_QUERY_UNKNOWN")
    if type(request.observed_at_utc) is not str or cp.normalized_utc(request.observed_at_utc) != request.observed_at_utc:
        raise GatewayError("GATEWAY_INSTANT_INVALID")
    if not (cp._optional(request.pipeline_id, cp.valid_id) and cp._optional(request.worker_id, cp.valid_id)
            and cp._optional(request.event_type, lambda v: cp._in(v, cp.LEDGER_EVENT_TYPES))):
        raise GatewayError("GATEWAY_ID_INVALID")
    if not (cp._bounded_int(request.offset, MAX_OFFSET) and cp._bounded_int(request.limit, MAX_LIMIT)
            and request.limit >= 1):
        raise GatewayError("GATEWAY_PAGE_INVALID")
    if request.query == QUERY_WORKER and (request.pipeline_id is None or request.worker_id is None):
        raise GatewayError("GATEWAY_SOURCE_REQUIRED")
    if request.query == QUERY_ACTIVITY and request.factory_root is None:
        raise GatewayError("GATEWAY_SOURCE_REQUIRED")
    if request.report_file is not None and request.query != QUERY_RESOURCES:
        raise GatewayError(_USAGE)
    roots = _admitted_roots(request.allowed_roots)
    _check_source(request.state_root, roots)
    for path in (request.factory_root, request.report_file):
        if path is not None:
            _check_source(path, roots)


# ---------------------------------------------------------------------------
# Sanitization and sealing
# ---------------------------------------------------------------------------

def _sanitize(value):
    """Defense in depth over already-allowlisted projections: ASCII,
    bounded, no secret- or path-shaped string. Anything else fails closed."""
    if value is None or type(value) in (bool, int):
        return value
    if type(value) is str:
        if _DIGEST_RE.fullmatch(value):
            return value
        if cp._secret_shaped(value) or _PATH_SHAPED_RE.search(value):
            return REDACTED
        return _PRINTABLE_RE.sub("?", value)[:MAX_STRING_CHARS]
    if type(value) in (list, tuple):
        return [_sanitize(v) for v in value]
    if type(value) is dict and all(type(k) is str for k in value):
        return {_sanitize(k): _sanitize(v) for k, v in value.items()}
    raise GatewayError("GATEWAY_INTERNAL_ERROR")


def _guarantees() -> dict:
    flags = at._AttentionGuarantees._guarantees()
    flags.update(network_used=False, write_performed=False)
    return flags


def _page(offset: int, limit: int, total: int, returned: int) -> dict:
    end = offset + returned
    return {"offset": offset, "limit": limit, "total": total, "returned": returned,
            "next_offset": end if end < total else None}


def _pick(items, request) -> tuple:
    items = list(items)
    chosen = items[request.offset:request.offset + request.limit]
    return chosen, _page(request.offset, request.limit, len(items), len(chosen))


# ---------------------------------------------------------------------------
# Field allowlists (copies of projection values, never new decisions)
# ---------------------------------------------------------------------------

def _status(view: cp.StatusView) -> dict:
    return {k: view.to_dict()[k] for k in ("condition", "source_value", "cause", "lifecycle", "runner_outcome",
                                           "actor")}


def _items_by_subject(attention) -> dict:
    return {(i.pipeline_id, i.worker_id): i for i in attention.items}


def _attention_head(attention) -> dict:
    body = attention.to_dict()
    return {k: body[k] for k in ("attention_class", "actor", "origin", "primary", "class_counts", "bindings",
                                 "causes")}


def _worker_row(w, item) -> dict:
    return {
        "worker_id": w.worker_id, "on_disk": w.on_disk, "listed": w.listed, "agreement": w.agreement,
        "listed_status": _status(w.listed_status), "record_status": _status(w.record_status),
        "result_status": _status(w.result_status), "record_updated_at_utc": w.record_updated_at_utc,
        "result_written_at_utc": w.result_written_at_utc,
        "attention_class": None if item is None else item.attention_class,
        "primary_reason": None if item is None else item.primary_reason,
    }


def _pipeline_row(p, items: dict) -> dict:
    view, item = p.view, items.get((p.pipeline_id, None))
    return {
        "pipeline_id": p.pipeline_id, "status": _status(view.status), "record_status": _status(p.record_status),
        "record_updated_at_utc": p.record_updated_at_utc, "agreement": p.agreement,
        "stop_reason": view.stop_reason, "started_at_utc": view.started_at_utc, "ended_at_utc": view.ended_at_utc,
        "workers_total": view.workers_total, "rejected_workers": view.rejected_workers,
        "malformed_fields": list(view.malformed_fields), "workers_condition": p.workers_condition,
        "workers_cause": p.workers_cause, "workers_omitted": p.workers_omitted,
        "attention_class": None if item is None else item.attention_class,
        "primary_reason": None if item is None else item.primary_reason,
        "workers": [_worker_row(w, items.get((p.pipeline_id, w.worker_id))) for w in p.workers],
    }


def _root(snapshot) -> dict:
    return {"root_condition": snapshot.root_condition, "root_cause": snapshot.root_cause,
            "root_actor": cp.CONDITION_ACTOR[snapshot.root_condition]}


def _tally(values) -> dict:
    counts: dict = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def _observed(request) -> tuple:
    snapshot = snap.take_snapshot(request.state_root, request.observed_at_utc)
    evidence = ev.take_evidence(request.state_root, snapshot)
    attention = at.observe_attention(snapshot, evidence=evidence)
    sources = {"snapshot": snapshot.revision, "evidence": evidence.revision, "attention": attention.revision}
    return snapshot, evidence, attention, sources


def _summary(request) -> tuple:
    snapshot, evidence, attention, sources = _observed(request)
    workers = [w for p in snapshot.pipelines for w in p.workers]
    result = {
        **_root(snapshot), "evidence_as_of_utc": snapshot.evidence_as_of_utc,
        "pipelines_shown": len(snapshot.pipelines), "pipelines_omitted": snapshot.pipelines_omitted,
        "workers_shown": len(workers), "workers_omitted": sum(p.workers_omitted for p in snapshot.pipelines),
        "pipeline_outcomes": _tally(p.view.status.runner_outcome for p in snapshot.pipelines),
        "worker_record_outcomes": _tally(w.record_status.runner_outcome for w in workers),
        "worker_agreements": _tally(w.agreement for w in workers),
        "evidence_workers_omitted": evidence.workers_omitted, **_attention_head(attention),
    }
    return result, sources, None


def _pipelines(request) -> tuple:
    snapshot, _, attention, sources = _observed(request)
    items = _items_by_subject(attention)
    selected = [p for p in snapshot.pipelines if request.pipeline_id in (None, p.pipeline_id)]
    chosen, page = _pick(selected, request)
    result = {**_root(snapshot), "pipelines_omitted": snapshot.pipelines_omitted,
              "pipelines": [_pipeline_row(p, items) for p in chosen]}
    return result, sources, page


def _worker(request) -> tuple:
    snapshot, evidence, attention, sources = _observed(request)
    key = (request.pipeline_id, request.worker_id)
    found = next((w for p in snapshot.pipelines for w in p.workers if (w.pipeline_id, w.worker_id) == key), None)
    listed = next((v for p in snapshot.observation.pipelines for v in p.workers
                   if (v.pipeline_id, v.worker_id) == key), None)
    attempts = next((w for w in evidence.workers if (w.pipeline_id, w.worker_id) == key), None)
    item = _items_by_subject(attention).get(key)
    result = {
        **_root(snapshot), "found": found is not None,
        "snapshot": None if found is None else _worker_row(found, item),
        "listed_view": None if listed is None else listed.to_dict(),
        "evidence": None if attempts is None else attempts.to_dict(),
        "attention": None if item is None else item.to_dict(),
    }
    return result, sources, None


def _activity(request) -> tuple:
    snapshot = snap.take_snapshot(request.state_root, request.observed_at_utc)
    history = hist.take_history(request.factory_root, request.observed_at_utc, snapshot=snapshot,
                                pipeline_id=request.pipeline_id, worker_id=request.worker_id,
                                event_type=request.event_type, offset=request.offset, limit=request.limit)
    body = history.to_dict()
    result = {k: body[k] for k in ("root_condition", "root_cause", "root_actor", "ledger_condition", "ledger_cause",
                                   "ledger_actor", "lines_total", "rejected", "events_total", "filters", "events",
                                   "correlations", "correlations_omitted")}
    page = _page(history.offset, history.limit, history.matching, len(history.events))
    return result, {"snapshot": snapshot.revision, "history": history.revision}, page


def _attention(request) -> tuple:
    snapshot, _, attention, sources = _observed(request)
    selected = [i for i in attention.items if request.pipeline_id in (None, i.pipeline_id)]
    chosen, page = _pick(selected, request)
    result = {**_root(snapshot), "evidence_as_of_utc": attention.evidence_as_of_utc, **_attention_head(attention),
              "items": [i.to_dict() for i in chosen]}
    return result, sources, page


def _resources(request) -> tuple:
    snapshot = snap.take_snapshot(request.state_root, request.observed_at_utc)
    resources = res.observe_resources(snapshot, report_file=request.report_file)
    body = resources.to_dict()
    selected = [w for w in body["workers"] if request.pipeline_id in (None, w["pipeline_id"])]
    chosen, page = _pick(selected, request)
    result = {k: body[k] for k in (
        "snapshot_complete", "report_condition", "report_cause", "report_code", "report_actor", "report_sha256",
        "report_as_of_utc", "report_status", "report_anomalies", "rejected_report_entries", "unattributed_workers",
        "providers", "global_cost_condition", "global_cost_reasons", "global_costs", "not_authorized_actions")}
    result.update(_root(snapshot), workers=chosen)
    return result, {"snapshot": snapshot.revision, "resources": resources.revision}, page


_HANDLERS = {QUERY_SUMMARY: _summary, QUERY_PIPELINES: _pipelines, QUERY_WORKER: _worker,
             QUERY_ACTIVITY: _activity, QUERY_ATTENTION: _attention, QUERY_RESOURCES: _resources}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def query(request: GatewayRequest) -> dict:
    """Answer one read query. Raises only `GatewayError` (fixed code/text)."""
    _check_request(request)
    try:
        result, sources, page = _HANDLERS[request.query](request)
        body = {
            "schema": SCHEMA, "schema_version": SCHEMA_VERSION, "query": request.query,
            "observed_at_utc": request.observed_at_utc,
            "request": {"pipeline_id": request.pipeline_id, "worker_id": request.worker_id,
                        "event_type": request.event_type, "offset": request.offset, "limit": request.limit,
                        "factory_root_given": request.factory_root is not None,
                        "report_file_given": request.report_file is not None},
            "sources": sources, "result": result, "page": page, **_guarantees(),
        }
        body = _sanitize(body)
    except GatewayError:
        raise
    except Exception:  # noqa: BLE001 - fail closed without a traceback or leaked bytes
        raise GatewayError("GATEWAY_INTERNAL_ERROR") from None
    body["revision"] = hashlib.sha256(sc._canonical(body).encode("ascii")).hexdigest()
    render_json(body)  # refuse an oversized response here, never truncate it
    return body


def _ask(name: str, allowed_roots, state_root, observed_at_utc, **kw) -> dict:
    return query(GatewayRequest(name, tuple(allowed_roots) if type(allowed_roots) in (tuple, list)
                                else allowed_roots, state_root, observed_at_utc, **kw))


def summary(allowed_roots, state_root, observed_at_utc, **kw) -> dict:
    return _ask(QUERY_SUMMARY, allowed_roots, state_root, observed_at_utc, **kw)


def pipelines(allowed_roots, state_root, observed_at_utc, **kw) -> dict:
    return _ask(QUERY_PIPELINES, allowed_roots, state_root, observed_at_utc, **kw)


def worker(allowed_roots, state_root, observed_at_utc, **kw) -> dict:
    return _ask(QUERY_WORKER, allowed_roots, state_root, observed_at_utc, **kw)


def activity(allowed_roots, state_root, observed_at_utc, **kw) -> dict:
    return _ask(QUERY_ACTIVITY, allowed_roots, state_root, observed_at_utc, **kw)


def attention(allowed_roots, state_root, observed_at_utc, **kw) -> dict:
    return _ask(QUERY_ATTENTION, allowed_roots, state_root, observed_at_utc, **kw)


def resources(allowed_roots, state_root, observed_at_utc, **kw) -> dict:
    return _ask(QUERY_RESOURCES, allowed_roots, state_root, observed_at_utc, **kw)


def render_json(response: dict) -> str:
    """Compact, sorted, ASCII canonical JSON, bounded by MAX_RESPONSE_BYTES."""
    text = sc._canonical(response)
    if len(text) > MAX_RESPONSE_BYTES:
        raise GatewayError("GATEWAY_RESPONSE_TOO_LARGE")
    return text


def _lines(prefix: str, value) -> list:
    if isinstance(value, dict):
        return [line for k in sorted(value) for line in _lines(f"{prefix}.{k}" if prefix else k, value[k])]
    if isinstance(value, list):
        if not value:
            return [f"{prefix}: []"]
        return [line for i, v in enumerate(value) for line in _lines(f"{prefix}[{i}]", v)]
    text = "-" if value is None else ("true" if value is True else "false" if value is False else str(value))
    return [f"{prefix}: {text}"]


def render_text(response: dict) -> str:
    """The same facts as `render_json`, one `path: value` token line each."""
    render_json(response)
    lines = _lines("", response)
    lines.append("authority: OBSERVATION ONLY - not certified, not authorized; Director and Runner remain the "
                 "only execution authorities")
    return "\n".join(lines)
