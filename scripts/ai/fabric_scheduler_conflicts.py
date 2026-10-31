"""FCP-9B-01: Worktree isolation and shared-resource conflict analysis -
pure, deterministic, fail-closed, provider-neutral, NON-AUTHORITATIVE.

Answers ONE question: given the worktrees and resources a batch of workers
DECLARES it will touch, which pairs of workers must never run at the same
time, and why? The output is an incompatibility graph with stable reason
codes. It never answers "may I dispatch now?" and never takes, checks or
releases a lock.

Why this is a consultative analysis, not a lock manager
-------------------------------------------------------
* Director and Runner stay the ONLY execution authorities. The Runner's own
  `PipelineRunner._same_worktree_conflict` (in-process exclusion) and the
  durable OS-lock write lease (`DirLease` over `worktree_lease_dir`) decide
  at execution time; nothing here acquires, inspects or duplicates a lease,
  lock or ownership record, starts or blocks a process, or touches Git, the
  filesystem, the clock, the environment or the network: stdlib only, no
  I/O, no mutable global state.
* The worktree rule mirrors `_same_worktree_conflict` exactly (pinned by
  tests): a WRITE worker needs its worktree to itself; a READ-ONLY worker
  only conflicts with a WRITE worker there; readers never conflict with
  readers. Nested/enclosing paths are treated like the Runner's
  `_paths_overlap` (equal, ancestor or descendant), which is STRICTER than
  the Runner's same-key check - the analysis may hold back more, never less.
* Target identity mirrors `claude_multiworker.canonical_target_key`
  (separator- and, for Windows paths, case-insensitive; pinned by tests)
  but is computed LEXICALLY: no path is ever resolved, so a link can never
  redirect the analysis outside the declared roots. Whatever a lexical key
  cannot prove identical-or-distinct fails closed instead:
  - `..` components (PATH_TRAVERSAL) are refused, never collapsed;
  - relative, drive-relative, root-relative, empty, over-long, wildcard or
    control-character paths are PATH_INDETERMINATE;
  - UNC, device-namespace (`\\\\?\\`, `\\\\.\\`), `//` and reserved device
    names are PATH_UNSUPPORTED_FORM;
  - spellings the OS may alias (8.3 short names `~N`, trailing dot/space,
    alternate data streams `:`, non-ASCII, a backslash in a POSIX path) are
    PATH_AMBIGUOUS_ALIAS;
  - a path whose flavor differs from the allowed roots (e.g. Git-Bash
    `/c/...` against `C:\\...` roots) is PATH_FLAVOR_MISMATCH;
  - a path outside every declared allowed root is PATH_OUTSIDE_ALLOWED_ROOTS;
  - link state is a caller-supplied OBSERVATION: `NO_LINK` (verified: no
    symlink/junction on the path below its root), `LINK` (PATH_LINK_AMBIGUOUS)
    or `UNKNOWN`, the default (PATH_LINK_UNVERIFIED).
* Provider-neutral: no provider field exists; no provider is named.

Request (`ConflictRequest` + `WorkerClaims` + `PathClaim` / `SourceClaim`,
frozen; validated by `analyze_conflicts`, never by the constructor)
--------------------------------------------------------------------------
* `dag_id`, `worker_id`: safe ids (FCP-9A-01 `ScheduleRequest` rules).
* `allowed_roots`: tuple (1..16) of clean absolute paths, all of one flavor.
* `workers`: tuple (1..64) of `WorkerClaims`, unique `worker_id`.
* `mode`: "read-only" or "write" (Runner `MODE_*`); the worker's worktree
  is claimed READ or WRITE accordingly.
* `worktree`: the worker's worktree top path (None = unidentified).
* `claims`: tuple (at most 16) of `PathClaim(path, access, link_state)` or
  `SourceClaim(source_id, access)`; `access` is "READ" or "WRITE". A
  read-only worker may not claim WRITE (CLAIM_EXCEEDS_MODE). A source of
  truth is an opaque safe id compared case-insensitively (e.g. a ledger).
* Structural errors (types, ids, duplicates, vocabularies) REFUSE the whole
  request. Any resource that cannot be identified (a None target, a claim of
  an unknown type, an unprovable path) makes its worker UNKNOWN.

Graph (`ConflictGraph`, schema `fcp9b01-scheduler-conflict-graph-v1`)
---------------------------------------------------------------------
* `nodes`: one `WorkerNode` per worker (`IDENTIFIED` or `UNKNOWN` + reasons).
* `edges`: one `ConflictEdge(worker_a < worker_b, reasons)` per incompatible
  pair. An UNKNOWN worker is incompatible with EVERY other worker
  (RESOURCE_UNIDENTIFIED_PEER). ALIAS_DETECTED accompanies a conflict found
  through differently-spelled but identical targets.
* `outcome`: REFUSED (invalid request), else UNKNOWN if any node is
  UNKNOWN, else CONFLICTS if any edge exists, else COMPATIBLE.
The serialization holds only validated ids, enumerated codes and a request
fingerprint: no path text reaches it. Every graph fixes the FCP-9A-01
zero-authority flags plus `lock_acquired` / `lease_acquired` to False as
read-only properties.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Optional

try:
    from scripts.ai import fabric_scheduler_contract as sc
except ImportError:  # pragma: no cover - direct script execution
    import fabric_scheduler_contract as sc  # type: ignore[no-redef]

REQUEST_SCHEMA = "fcp9b01-scheduler-conflict-request-v1"
REQUEST_SCHEMA_VERSION = 1
SCHEMA = "fcp9b01-scheduler-conflict-graph-v1"
SCHEMA_VERSION = 1
CONFLICT_MARKER = "FCP9B01_CONFLICT_ADVISORY_ONLY_NOT_CERTIFIED_NOT_AUTHORIZED"

MAX_WORKERS = sc.MAX_ITEMS
MAX_CLAIMS_PER_WORKER = 16
MAX_ALLOWED_ROOTS = 16
MAX_PATH_CHARS = 1024
MAX_CANONICAL_JSON_BYTES = 262144

MODES = sc.MODES
ACCESS_READ = "READ"
ACCESS_WRITE = "WRITE"
ACCESSES = (ACCESS_READ, ACCESS_WRITE)
LINK_NONE = "NO_LINK"
LINK_PRESENT = "LINK"
LINK_UNKNOWN = "UNKNOWN"
LINK_STATES = (LINK_NONE, LINK_PRESENT, LINK_UNKNOWN)

FLAVOR_WINDOWS = "windows"
FLAVOR_POSIX = "posix"

# Batch outcomes and node statuses.
COMPATIBLE = "COMPATIBLE"
CONFLICTS = "CONFLICTS"
UNKNOWN = "UNKNOWN"
REFUSED = "REFUSED"
OUTCOMES = (COMPATIBLE, CONFLICTS, UNKNOWN, REFUSED)
IDENTIFIED = "IDENTIFIED"
NODE_STATUSES = (IDENTIFIED, UNKNOWN)

# Request-level refusal codes, in their fixed canonical order.
REQUEST_NOT_TYPED = "REQUEST_NOT_TYPED"
SCHEMA_VERSION_UNSUPPORTED = "SCHEMA_VERSION_UNSUPPORTED"
DAG_ID_INVALID = "DAG_ID_INVALID"
ALLOWED_ROOTS_MALFORMED = "ALLOWED_ROOTS_MALFORMED"
ALLOWED_ROOT_INVALID = "ALLOWED_ROOT_INVALID"
ALLOWED_ROOTS_MIXED_FLAVOR = "ALLOWED_ROOTS_MIXED_FLAVOR"
WORKERS_NOT_TUPLE = "WORKERS_NOT_TUPLE"
WORKERS_EMPTY = "WORKERS_EMPTY"
WORKERS_TOO_MANY = "WORKERS_TOO_MANY"
WORKER_NOT_TYPED = "WORKER_NOT_TYPED"
WORKER_ID_INVALID = "WORKER_ID_INVALID"
WORKER_ID_DUPLICATE = "WORKER_ID_DUPLICATE"
MODE_UNKNOWN = "MODE_UNKNOWN"
WORKTREE_NOT_TEXT = "WORKTREE_NOT_TEXT"
LINK_STATE_INVALID = "LINK_STATE_INVALID"
CLAIMS_MALFORMED = "CLAIMS_MALFORMED"
ACCESS_UNKNOWN = "ACCESS_UNKNOWN"
PATH_NOT_TEXT = "PATH_NOT_TEXT"
SOURCE_ID_INVALID = "SOURCE_ID_INVALID"
CLAIM_EXCEEDS_MODE = "CLAIM_EXCEEDS_MODE"
REQUEST_TOO_LARGE = "REQUEST_TOO_LARGE"
REQUEST_REASONS = (
    REQUEST_NOT_TYPED, SCHEMA_VERSION_UNSUPPORTED, DAG_ID_INVALID, ALLOWED_ROOTS_MALFORMED, ALLOWED_ROOT_INVALID,
    ALLOWED_ROOTS_MIXED_FLAVOR, WORKERS_NOT_TUPLE, WORKERS_EMPTY, WORKERS_TOO_MANY, WORKER_NOT_TYPED,
    WORKER_ID_INVALID, WORKER_ID_DUPLICATE, MODE_UNKNOWN, WORKTREE_NOT_TEXT, LINK_STATE_INVALID, CLAIMS_MALFORMED,
    ACCESS_UNKNOWN, PATH_NOT_TEXT, SOURCE_ID_INVALID, CLAIM_EXCEEDS_MODE, REQUEST_TOO_LARGE,
)

# Node-level UNKNOWN codes (fail closed), in their fixed canonical order.
RESOURCE_UNIDENTIFIED = "RESOURCE_UNIDENTIFIED"
PATH_INDETERMINATE = "PATH_INDETERMINATE"
PATH_UNSUPPORTED_FORM = "PATH_UNSUPPORTED_FORM"
PATH_TRAVERSAL = "PATH_TRAVERSAL"
PATH_AMBIGUOUS_ALIAS = "PATH_AMBIGUOUS_ALIAS"
PATH_FLAVOR_MISMATCH = "PATH_FLAVOR_MISMATCH"
PATH_OUTSIDE_ALLOWED_ROOTS = "PATH_OUTSIDE_ALLOWED_ROOTS"
PATH_LINK_AMBIGUOUS = "PATH_LINK_AMBIGUOUS"
PATH_LINK_UNVERIFIED = "PATH_LINK_UNVERIFIED"
NODE_REASONS = (
    RESOURCE_UNIDENTIFIED, PATH_INDETERMINATE, PATH_UNSUPPORTED_FORM, PATH_TRAVERSAL, PATH_AMBIGUOUS_ALIAS,
    PATH_FLAVOR_MISMATCH, PATH_OUTSIDE_ALLOWED_ROOTS, PATH_LINK_AMBIGUOUS, PATH_LINK_UNVERIFIED,
)

# Edge (incompatibility) codes, in their fixed canonical order.
WORKTREE_WRITE_WRITE = "WORKTREE_WRITE_WRITE"
WORKTREE_READ_WRITE = "WORKTREE_READ_WRITE"
WORKTREE_NESTED = "WORKTREE_NESTED"
PATH_OVERLAP_WRITE_WRITE = "PATH_OVERLAP_WRITE_WRITE"
PATH_OVERLAP_READ_WRITE = "PATH_OVERLAP_READ_WRITE"
SOURCE_OF_TRUTH_WRITE_WRITE = "SOURCE_OF_TRUTH_WRITE_WRITE"
SOURCE_OF_TRUTH_READ_WRITE = "SOURCE_OF_TRUTH_READ_WRITE"
RESOURCE_UNIDENTIFIED_PEER = "RESOURCE_UNIDENTIFIED_PEER"
ALIAS_DETECTED = "ALIAS_DETECTED"
EDGE_REASONS = (
    WORKTREE_WRITE_WRITE, WORKTREE_READ_WRITE, WORKTREE_NESTED, PATH_OVERLAP_WRITE_WRITE, PATH_OVERLAP_READ_WRITE,
    SOURCE_OF_TRUTH_WRITE_WRITE, SOURCE_OF_TRUTH_READ_WRITE, RESOURCE_UNIDENTIFIED_PEER, ALIAS_DETECTED,
)
# ALIAS_DETECTED is informational: it never forms an edge on its own.
BLOCKING_EDGE_REASONS = EDGE_REASONS[:-1]

_DRIVE_RE = re.compile(r"([A-Za-z]):([\\/].*)?", re.DOTALL)
_WIN_SEP_RE = re.compile(r"[\\/]")
_SHORT_NAME_RE = re.compile(r"~[0-9]")
_RESERVED_RE = re.compile(r"(con|prn|aux|nul|com[0-9]|lpt[0-9]|conin\$|conout\$)(\..*)?", re.IGNORECASE)
_WILDCARDS = frozenset('<>"|?*')


def _ordered(codes, vocabulary) -> tuple:
    return tuple(sorted(set(codes), key=vocabulary.index))


# ---------------------------------------------------------------------------
# Lexical target identity (never resolves anything)
# ---------------------------------------------------------------------------

def _components(parts, flavor: str) -> tuple:
    """Returns (reasons, key components) for already-split components."""
    reasons = set()
    out = []
    for part in parts:
        if part in ("", "."):
            continue
        if part == "..":
            reasons.add(PATH_TRAVERSAL)
            continue
        if flavor == FLAVOR_WINDOWS:
            if any(ch in _WILDCARDS for ch in part):
                reasons.add(PATH_INDETERMINATE)
            if _RESERVED_RE.fullmatch(part.rstrip(". ")):
                reasons.add(PATH_UNSUPPORTED_FORM)
            if part[-1] in ". " or ":" in part or _SHORT_NAME_RE.search(part):
                reasons.add(PATH_AMBIGUOUS_ALIAS)
            part = part.lower()
        out.append(part)
    return reasons, tuple(out)


def target_key(path) -> tuple:
    """Lexical comparison key for one absolute path: (reasons, key), where
    key is (flavor, root, *components) or None when reasons is non-empty.
    Equal keys name the same target; a key that is a prefix of another
    encloses it. Pure: no resolution, no I/O."""
    if type(path) is not str or not 0 < len(path) <= MAX_PATH_CHARS:
        return (PATH_INDETERMINATE,), None
    if not path.isascii():
        return (PATH_AMBIGUOUS_ALIAS,), None
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in path):
        return (PATH_INDETERMINATE,), None
    if path[:2] in ("\\\\", "//", "\\/", "/\\"):
        return (PATH_UNSUPPORTED_FORM,), None
    drive = _DRIVE_RE.fullmatch(path)
    if drive is not None:
        if drive.group(2) is None:
            return (PATH_INDETERMINATE,), None  # drive-relative "C:foo" / "C:"
        flavor, root = FLAVOR_WINDOWS, drive.group(1).lower() + ":"
        reasons, parts = _components(_WIN_SEP_RE.split(drive.group(2)), flavor)
    elif path.startswith("/"):
        if "\\" in path:
            return (PATH_AMBIGUOUS_ALIAS,), None
        flavor, root = FLAVOR_POSIX, "/"
        reasons, parts = _components(path.split("/"), flavor)
    else:
        return (PATH_INDETERMINATE,), None  # relative or root-relative "\\foo"
    if reasons:
        return _ordered(reasons, NODE_REASONS), None
    return (), (flavor, root) + parts


def encloses(outer: tuple, inner: tuple) -> bool:
    """True when `inner` is `outer` or nested below it (keys from
    `target_key`)."""
    return len(outer) <= len(inner) and inner[:len(outer)] == outer


def overlaps(a: tuple, b: tuple) -> bool:
    """Equal, ancestor or descendant - the Runner's `_paths_overlap`."""
    return encloses(a, b) or encloses(b, a)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PathClaim:
    """A file or directory a worker declares it will READ or WRITE."""
    path: Optional[str]
    access: str
    link_state: str = LINK_UNKNOWN


@dataclass(frozen=True)
class SourceClaim:
    """A declared source of truth (opaque id, e.g. a ledger) a worker will
    READ or WRITE."""
    source_id: Optional[str]
    access: str


@dataclass(frozen=True)
class WorkerClaims:
    """One worker's declared footprint. Validated by `analyze_conflicts`
    (fail closed), not here."""
    worker_id: str
    mode: str
    worktree: Optional[str]
    worktree_link_state: str = LINK_UNKNOWN
    claims: tuple = ()


@dataclass(frozen=True)
class ConflictRequest:
    """Explicit, immutable conflict-analysis request for one batch."""
    dag_id: str
    allowed_roots: tuple
    workers: tuple
    schema_version: int = REQUEST_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WorkerNode:
    """Per-worker identification status. Construction re-derives `status`
    from `reasons`."""
    worker_id: str
    status: str
    reasons: tuple

    def __post_init__(self):
        if not sc._safe_id(self.worker_id):
            raise ValueError("worker_id must be a safe id")
        if not (type(self.reasons) is tuple and all(type(r) is str and r in NODE_REASONS for r in self.reasons)
                and self.reasons == _ordered(self.reasons, NODE_REASONS)):
            raise ValueError("reasons must be ordered node reason codes")
        if type(self.status) is not str or self.status != (UNKNOWN if self.reasons else IDENTIFIED):
            raise ValueError("status must be exactly the one derived from reasons")

    def to_dict(self) -> dict:
        return {"worker_id": self.worker_id, "status": self.status, "reasons": list(self.reasons)}


@dataclass(frozen=True)
class ConflictEdge:
    """One incompatible worker pair, ordered (worker_a < worker_b)."""
    worker_a: str
    worker_b: str
    reasons: tuple

    def __post_init__(self):
        if not (sc._safe_id(self.worker_a) and sc._safe_id(self.worker_b) and self.worker_a < self.worker_b):
            raise ValueError("an edge joins two distinct safe ids in sorted order")
        if not (type(self.reasons) is tuple and all(type(r) is str and r in EDGE_REASONS for r in self.reasons)
                and self.reasons == _ordered(self.reasons, EDGE_REASONS)):
            raise ValueError("reasons must be ordered edge reason codes")
        if not set(self.reasons) & set(BLOCKING_EDGE_REASONS):
            raise ValueError("an edge needs at least one blocking reason")

    def to_dict(self) -> dict:
        return {"worker_a": self.worker_a, "worker_b": self.worker_b, "reasons": list(self.reasons)}


class _NoLocks(sc._NotAuthorized):
    """FCP-9A-01 zero-authority flags plus: this analysis holds no lock or
    lease, ever."""

    @property
    def lock_acquired(self) -> bool:
        return False

    @property
    def lease_acquired(self) -> bool:
        return False

    @staticmethod
    def _guarantees() -> dict:
        guarantees = sc._NotAuthorized._guarantees()
        guarantees.update(marker=CONFLICT_MARKER, lock_acquired=False, lease_acquired=False)
        return guarantees


def _graph_outcome(nodes: tuple, edges: tuple) -> str:
    if any(n.status == UNKNOWN for n in nodes):
        return UNKNOWN
    return CONFLICTS if edges else COMPATIBLE


@dataclass(frozen=True)
class ConflictGraph(_NoLocks):
    """Consultative incompatibility graph. Construction re-checks every
    invariant, so a hand-made graph cannot claim compatibility its nodes and
    edges do not support."""
    outcome: str
    dag_id: Optional[str]
    request_fingerprint: Optional[str]
    request_reasons: tuple
    nodes: tuple
    edges: tuple

    def __post_init__(self):
        if type(self.outcome) is not str or self.outcome not in OUTCOMES:
            raise ValueError("unknown graph outcome")
        if not (type(self.request_reasons) is tuple
                and all(type(r) is str and r in REQUEST_REASONS for r in self.request_reasons)
                and self.request_reasons == _ordered(self.request_reasons, REQUEST_REASONS)):
            raise ValueError("request_reasons must be ordered request reason codes")
        if not (type(self.nodes) is tuple and all(type(n) is WorkerNode for n in self.nodes)):
            raise ValueError("nodes must be a tuple of WorkerNode")
        if not (type(self.edges) is tuple and all(type(e) is ConflictEdge for e in self.edges)):
            raise ValueError("edges must be a tuple of ConflictEdge")
        if self.request_reasons:
            if (self.outcome != REFUSED or self.nodes or self.edges
                    or (self.dag_id, self.request_fingerprint) != (None, None)):
                raise ValueError("a refused request echoes nothing and decides nothing")
            return
        if not sc._safe_id(self.dag_id):
            raise ValueError("dag_id must be a safe id")
        if not (type(self.request_fingerprint) is str and sc._FINGERPRINT_RE.fullmatch(self.request_fingerprint)):
            raise ValueError("request_fingerprint must be a sha256 hex digest")
        ids = [n.worker_id for n in self.nodes]
        if not 1 <= len(ids) <= MAX_WORKERS or len(set(ids)) != len(ids):
            raise ValueError("nodes must name each worker once")
        pairs = [(e.worker_a, e.worker_b) for e in self.edges]
        if pairs != sorted(set(pairs)) or not all(a in ids and b in ids for a, b in pairs):
            raise ValueError("edges must be unique, sorted and between known workers")
        unknown = {n.worker_id for n in self.nodes if n.status == UNKNOWN}
        peer = {(e.worker_a, e.worker_b) for e in self.edges if RESOURCE_UNIDENTIFIED_PEER in e.reasons}
        expected = {(a, b) for a in ids for b in ids if a < b and (a in unknown or b in unknown)}
        if peer != expected:
            raise ValueError("RESOURCE_UNIDENTIFIED_PEER joins exactly every pair with an UNKNOWN worker")
        if self.outcome != _graph_outcome(self.nodes, self.edges):
            raise ValueError("outcome must be exactly the one derived from nodes and edges")

    def edge_between(self, a: str, b: str) -> Optional[ConflictEdge]:
        lo, hi = (a, b) if a < b else (b, a)
        for edge in self.edges:
            if (edge.worker_a, edge.worker_b) == (lo, hi):
                return edge
        return None

    def node_of(self, worker_id: str) -> Optional[WorkerNode]:
        for node in self.nodes:
            if node.worker_id == worker_id:
                return node
        return None

    def compatible(self, a: str, b: str) -> bool:
        """Informational only, never a permit: True only for two distinct,
        IDENTIFIED workers of a non-refused graph with no edge between
        them. Anything else (unknown id, UNKNOWN worker) is False."""
        na, nb = self.node_of(a), self.node_of(b)
        if na is None or nb is None or a == b or UNKNOWN in (na.status, nb.status):
            return False
        return self.edge_between(a, b) is None

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA, "schema_version": SCHEMA_VERSION, "outcome": self.outcome, "dag_id": self.dag_id,
            "request_fingerprint": self.request_fingerprint, "request_reasons": list(self.request_reasons),
            "counts": {"workers": len(self.nodes), "unknown_workers": sum(1 for n in self.nodes if n.status == UNKNOWN),
                       "edges": len(self.edges)},
            "nodes": [n.to_dict() for n in self.nodes], "edges": [e.to_dict() for e in self.edges],
            **_NoLocks._guarantees(),
        }


def canonical_json(graph: ConflictGraph) -> str:
    """Stable, sorted, compact, size-bounded serialization of the exact
    contract type (a subclass cannot substitute `to_dict`)."""
    if type(graph) is not ConflictGraph:
        raise TypeError("canonical_json accepts only a ConflictGraph")
    text = sc._canonical(ConflictGraph.to_dict(graph))
    if len(text) > MAX_CANONICAL_JSON_BYTES:
        raise ValueError("canonical graph exceeds MAX_CANONICAL_JSON_BYTES")
    return text


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _claim_reasons(claim, mode_ok: bool, mode: str) -> set:
    """Structural refusal codes of one claim (unknown claim types are not
    structural: they are an unidentified resource, see `_resources`)."""
    reasons = set()
    if type(claim) not in (PathClaim, SourceClaim):
        return reasons
    if type(claim.access) is not str or claim.access not in ACCESSES:
        reasons.add(ACCESS_UNKNOWN)
    elif mode_ok and mode == sc.MODE_READ_ONLY and claim.access == ACCESS_WRITE:
        reasons.add(CLAIM_EXCEEDS_MODE)
    if type(claim) is PathClaim:
        if claim.path is not None and type(claim.path) is not str:
            reasons.add(PATH_NOT_TEXT)
        if type(claim.link_state) is not str or claim.link_state not in LINK_STATES:
            reasons.add(LINK_STATE_INVALID)
    elif claim.source_id is not None and not sc._safe_id(claim.source_id):
        reasons.add(SOURCE_ID_INVALID)
    return reasons


def _worker_reasons(worker: WorkerClaims) -> set:
    reasons = set()
    if not sc._safe_id(worker.worker_id):
        reasons.add(WORKER_ID_INVALID)
    mode_ok = type(worker.mode) is str and worker.mode in MODES
    if not mode_ok:
        reasons.add(MODE_UNKNOWN)
    if worker.worktree is not None and type(worker.worktree) is not str:
        reasons.add(WORKTREE_NOT_TEXT)
    if type(worker.worktree_link_state) is not str or worker.worktree_link_state not in LINK_STATES:
        reasons.add(LINK_STATE_INVALID)
    if type(worker.claims) is not tuple or len(worker.claims) > MAX_CLAIMS_PER_WORKER:
        reasons.add(CLAIMS_MALFORMED)
    else:
        for claim in worker.claims:
            reasons |= _claim_reasons(claim, mode_ok, worker.mode)
    return reasons


def _validate_request(request) -> tuple:
    """Returns (reasons, root keys). Never echoes raw input."""
    if type(request) is not ConflictRequest:
        return (REQUEST_NOT_TYPED,), None
    reasons = set()
    if not (sc._is_int(request.schema_version) and request.schema_version == REQUEST_SCHEMA_VERSION):
        reasons.add(SCHEMA_VERSION_UNSUPPORTED)
    if not sc._safe_id(request.dag_id):
        reasons.add(DAG_ID_INVALID)

    roots = []
    if not (sc._str_tuple(request.allowed_roots, MAX_ALLOWED_ROOTS) and request.allowed_roots):
        reasons.add(ALLOWED_ROOTS_MALFORMED)
    else:
        for root in request.allowed_roots:
            root_reasons, key = target_key(root)
            if root_reasons:
                reasons.add(ALLOWED_ROOT_INVALID)
            else:
                roots.append(key)
        if len({k[0] for k in roots}) > 1:
            reasons.add(ALLOWED_ROOTS_MIXED_FLAVOR)

    workers = request.workers
    if type(workers) is not tuple:
        reasons.add(WORKERS_NOT_TUPLE)
        workers = ()
    elif not workers:
        reasons.add(WORKERS_EMPTY)
    elif len(workers) > MAX_WORKERS:
        reasons.add(WORKERS_TOO_MANY)
        workers = ()
    ids = []
    for worker in workers:
        if type(worker) is not WorkerClaims:
            reasons.add(WORKER_NOT_TYPED)
            continue
        worker_reasons = _worker_reasons(worker)
        reasons |= worker_reasons
        if WORKER_ID_INVALID not in worker_reasons:
            ids.append(worker.worker_id)
    if len(ids) != len(set(ids)):
        reasons.add(WORKER_ID_DUPLICATE)

    if reasons:
        return _ordered(reasons, REQUEST_REASONS), None
    return (), tuple(sorted(set(roots)))


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

_KIND_WORKTREE = "worktree"
_KIND_PATH = "path"
_KIND_SOURCE = "source"


@dataclass(frozen=True)
class _Resource:
    kind: str
    key: tuple
    access: str
    spelling: str


def _path_resource(path, link_state: str, roots: tuple, reasons: set) -> Optional[tuple]:
    if path is None:
        reasons.add(RESOURCE_UNIDENTIFIED)
        return None
    path_reasons, key = target_key(path)
    if path_reasons:
        reasons.update(path_reasons)
        return None
    if key[0] != roots[0][0]:
        reasons.add(PATH_FLAVOR_MISMATCH)
        return None
    if not any(encloses(root, key) for root in roots):
        reasons.add(PATH_OUTSIDE_ALLOWED_ROOTS)
        return None
    if link_state == LINK_PRESENT:
        reasons.add(PATH_LINK_AMBIGUOUS)
        return None
    if link_state != LINK_NONE:
        reasons.add(PATH_LINK_UNVERIFIED)
        return None
    return key


def _resources(worker: WorkerClaims, roots: tuple) -> tuple:
    """Returns (node reasons, identified resources) of one valid worker."""
    reasons: set = set()
    resources = []
    access = ACCESS_WRITE if worker.mode == sc.MODE_WRITE else ACCESS_READ
    key = _path_resource(worker.worktree, worker.worktree_link_state, roots, reasons)
    if key is not None:
        resources.append(_Resource(_KIND_WORKTREE, key, access, worker.worktree))
    for claim in worker.claims:
        if type(claim) is PathClaim:
            key = _path_resource(claim.path, claim.link_state, roots, reasons)
            if key is not None:
                resources.append(_Resource(_KIND_PATH, key, claim.access, claim.path))
        elif type(claim) is SourceClaim and claim.source_id is not None:
            resources.append(_Resource(_KIND_SOURCE, (claim.source_id.lower(),), claim.access, claim.source_id))
        else:
            reasons.add(RESOURCE_UNIDENTIFIED)
    return _ordered(reasons, NODE_REASONS), tuple(resources)


def _pair_reasons(mine: tuple, theirs: tuple) -> set:
    reasons = set()
    for a in mine:
        for b in theirs:
            if ACCESS_WRITE not in (a.access, b.access):
                continue  # readers never conflict with readers
            both_write = a.access == b.access
            if (a.kind == _KIND_SOURCE) != (b.kind == _KIND_SOURCE):
                continue  # a source id and a path never name the same thing
            if a.kind == _KIND_SOURCE:
                if a.key != b.key:
                    continue
                reasons.add(SOURCE_OF_TRUTH_WRITE_WRITE if both_write else SOURCE_OF_TRUTH_READ_WRITE)
            elif not overlaps(a.key, b.key):
                continue
            elif a.kind == b.kind == _KIND_WORKTREE:
                if a.key == b.key:
                    reasons.add(WORKTREE_WRITE_WRITE if both_write else WORKTREE_READ_WRITE)
                else:
                    reasons.add(WORKTREE_NESTED)
            else:
                reasons.add(PATH_OVERLAP_WRITE_WRITE if both_write else PATH_OVERLAP_READ_WRITE)
            if a.key == b.key and a.spelling != b.spelling:
                reasons.add(ALIAS_DETECTED)
    return reasons


def _request_dict(request: ConflictRequest, roots: tuple) -> dict:
    def claim_dict(claim):
        if type(claim) is PathClaim:
            return {"type": "path", "path": claim.path, "access": claim.access, "link_state": claim.link_state}
        if type(claim) is SourceClaim:
            return {"type": "source", "source_id": claim.source_id, "access": claim.access}
        return {"type": "unidentified"}
    return {
        "schema": REQUEST_SCHEMA, "schema_version": REQUEST_SCHEMA_VERSION, "dag_id": request.dag_id,
        "allowed_roots": [list(k) for k in roots],
        "workers": [
            {"worker_id": w.worker_id, "mode": w.mode, "worktree": w.worktree,
             "worktree_link_state": w.worktree_link_state, "claims": [claim_dict(c) for c in w.claims]}
            for w in request.workers
        ],
    }


def _refused(reasons: tuple) -> ConflictGraph:
    return ConflictGraph(outcome=REFUSED, dag_id=None, request_fingerprint=None, request_reasons=reasons,
                         nodes=(), edges=())


def analyze_conflicts(request: ConflictRequest) -> ConflictGraph:
    """Pure, deterministic pre-dispatch conflict analysis. Never raises on
    bad input and never mutates it: every malformed request is an explained
    refusal and every unprovable resource an UNKNOWN worker. The result never
    authorizes dispatch or execution, and never takes or checks a lock."""
    reasons, roots = _validate_request(request)
    if reasons:
        return _refused(reasons)
    request_text = sc._canonical(_request_dict(request, roots))
    if len(request_text) > MAX_CANONICAL_JSON_BYTES:
        return _refused((REQUEST_TOO_LARGE,))

    workers = request.workers
    analysed = [_resources(w, roots) for w in workers]
    nodes = tuple(WorkerNode(w.worker_id, UNKNOWN if r else IDENTIFIED, r) for w, (r, _) in zip(workers, analysed))
    edges = []
    for i in range(len(workers)):
        for j in range(i + 1, len(workers)):
            pair = _pair_reasons(analysed[i][1], analysed[j][1])
            if analysed[i][0] or analysed[j][0]:
                pair.add(RESOURCE_UNIDENTIFIED_PEER)
            if pair & set(BLOCKING_EDGE_REASONS):
                a, b = sorted((workers[i].worker_id, workers[j].worker_id))
                edges.append(ConflictEdge(a, b, _ordered(pair, EDGE_REASONS)))
    edges.sort(key=lambda e: (e.worker_a, e.worker_b))
    edges = tuple(edges)
    return ConflictGraph(
        outcome=_graph_outcome(nodes, edges), dag_id=request.dag_id,
        request_fingerprint=hashlib.sha256(request_text.encode("ascii")).hexdigest(),
        request_reasons=(), nodes=nodes, edges=edges,
    )
