"""FCP-2B-CORE: deterministic, read-only semantic reconciliation analysis.

Built strictly ON TOP of the approved FCP-1B integration assessment. It
answers ONE question, without changing anything: "for a candidate FCP-1
classified STALE_BASE or NEEDS_RECONCILIATION, what does the textual
relation between the candidate's changes and the base's changes look
like, and how much human attention does a later reconciliation need?"

It is NOT a reconciliation executor. It never merges (not even
`merge-tree`), rebases, checks out, resets, commits, updates refs, fetches
or pushes, never runs a merge driver and never writes to any object store.
A human must approve any later execution mechanism (FCP-2D/FCP-3), which
must revalidate everything recorded here.

Execution (`analyze_reconciliation`)
------------------------------------
1. `runner_integration.assess_integration` runs with the exact caller
   inputs. Only STALE_BASE / NEEDS_RECONCILIATION enter analysis; every
   other FCP-1 classification is NOT_APPLICABLE and nothing else is read.
2. Immutable, SHA-addressed diffs (merge-base..HEAD and merge-base..base)
   are read through `runner_integration._git` ONLY - the same governed,
   read-only `runner_git.run` path FCP-1 uses (hooks, fsmonitor, external
   diff, textconv and content filters neutralized or refused there). Every
   output-shaping diff setting is pinned on the command line so repository
   or user config cannot change the result (see `_PINNED_DIFF_OPTIONS`);
   pathspecs carry `:(literal)` magic and every Git name is matched
   literally from `-z` output.
   Numeric numstat is not trusted as proof of text (a `diff` attribute
   forces it): every changed regular blob, both sides, is size-checked
   (`cat-file -s`) and, within MAX_BLOB_BYTES / MAX_BLOB_TOTAL_BYTES, read
   by SHA (`cat-file blob`, never filtered or converted) and scanned for
   NUL. Every added path is checked for case/normalization collisions
   against the immutable merge-base tree (`cat-file tree`, bounded by the
   MAX_TREE_* limits); the tips are that tree plus the diffs, whose paths
   are checked against each other. Hunk output is requested only once
   blob sizes prove it fits MAX_HUNK_BYTES (`_hunk_bound`). Anything not
   provable within the bounds is HUMAN_REQUIRED, never NO_TEXTUAL_CONFLICT.
3. FCP-1 is re-run after the reads; any difference in fingerprint or
   classification is FAIL_CLOSED - never an optimistic result.
4. Nothing is persisted: no lease store, schema or file of its own. The
   FCP-1 passes take the Runner worktree lease and (with `ledger_root`) the
   FactoryLedger check exactly as FCP-1 does; Director-governed callers
   must pass the Director's ledger/lease roots, as the Director's own
   `assess_integration` does.

Classification (`classify_reconciliation`, pure)
------------------------------------------------
Fixed precedence (`RECONCILIATION_PRECEDENCE`): NOT_APPLICABLE, FAIL_CLOSED,
HUMAN_REQUIRED, SEMANTIC_REVIEW_REQUIRED, NO_TEXTUAL_CONFLICT. Adjacent and
touching hunks count as overlapping. NO_TEXTUAL_CONFLICT only means that
no textual conflict was proven: it is NEVER a semantic-safety or
merge-readiness verdict, and always carries RECON_SEMANTIC_VALIDATION_
REQUIRED.

Plans (`propose_reconciliation_plan` / `validate_reconciliation_plan`,
pure) are always PROPOSED, never approved; they use only host-supplied
acceptance commands, and validating one grants no action. Every result
has `human_approval_required=True` and `authorizes_action=False`.
Fingerprints are deterministic SHA-256 digests of canonical JSON; they
identify inputs and are NOT authorization tokens.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    from scripts.ai import claude_runner
    from scripts.ai import runner_integration as ri
except ImportError:  # pragma: no cover - direct script execution
    _this_dir = Path(__file__).resolve().parent
    if str(_this_dir) not in sys.path:
        sys.path.insert(0, str(_this_dir))
    import claude_runner  # type: ignore[no-redef]
    import runner_integration as ri  # type: ignore[no-redef]


ANALYSIS_SCHEMA = "fcp2b-reconciliation-analysis-v1"
FACTS_SCHEMA = "fcp2b-reconciliation-facts-v1"
PLAN_SCHEMA = "fcp2b-reconciliation-plan-v1"

# Conservative local fail-closed bounds (subject to later governance review).
MAX_PATHS = 256                       # path records, both sides together
MAX_HUNK_BYTES = 2 * 1024 * 1024      # decoded -U0 output per comparison (side)
_MAX_PATHSPEC_CHARS = 8000            # per diff invocation; more paths are batched
MAX_BLOB_BYTES = 2 * 1024 * 1024      # largest blob read for the text (NUL) proof
MAX_BLOB_TOTAL_BYTES = 32 * 1024 * 1024  # all blobs read for the text proof
MAX_TREE_BYTES = 1024 * 1024          # largest merge-base tree read for the case proof
MAX_TREE_TOTAL_BYTES = 8 * 1024 * 1024   # all trees read for the case proof
MAX_TREE_READS = 256                  # distinct trees read for the case proof
_HUNK_HEADER_BYTES = 256              # >= "@@ -a,b +c,d @@" (4 longs) + xdiff's 80-byte funcname
_NO_NEWLINE_BYTES = 32                # >= "\n\\ No newline at end of file\n"

# Classifications.
NOT_APPLICABLE = "NOT_APPLICABLE"
FAIL_CLOSED = "FAIL_CLOSED"
HUMAN_REQUIRED = "HUMAN_REQUIRED"
SEMANTIC_REVIEW_REQUIRED = "SEMANTIC_REVIEW_REQUIRED"
NO_TEXTUAL_CONFLICT = "NO_TEXTUAL_CONFLICT"
RECONCILIATION_PRECEDENCE = (
    NOT_APPLICABLE, FAIL_CLOSED, HUMAN_REQUIRED, SEMANTIC_REVIEW_REQUIRED, NO_TEXTUAL_CONFLICT,
)
RECONCILABLE_FCP1_CLASSIFICATIONS = frozenset({ri.STALE_BASE, ri.NEEDS_RECONCILIATION})
PLANNABLE_CLASSIFICATIONS = frozenset({NO_TEXTUAL_CONFLICT, SEMANTIC_REVIEW_REQUIRED})

PLAN_PROPOSED = "PROPOSED"

# Reason codes.
RECON_NOT_APPLICABLE = "RECON_NOT_APPLICABLE"
RECON_SEMANTIC_VALIDATION_REQUIRED = "RECON_SEMANTIC_VALIDATION_REQUIRED"
# FAIL_CLOSED
RECON_ASSESSMENT_FAILED = "RECON_ASSESSMENT_FAILED"
RECON_MALFORMED_ASSESSMENT = "RECON_MALFORMED_ASSESSMENT"
RECON_ASSESSMENT_TAMPERED = "RECON_ASSESSMENT_TAMPERED"
RECON_ASSESSMENT_DRIFT = "RECON_ASSESSMENT_DRIFT"
RECON_READ_FAILED = "RECON_READ_FAILED"
RECON_UNEXPECTED_RAW = "RECON_UNEXPECTED_RAW"
RECON_UNEXPECTED_NUMSTAT = "RECON_UNEXPECTED_NUMSTAT"
RECON_UNEXPECTED_HUNK = "RECON_UNEXPECTED_HUNK"
RECON_UNEXPECTED_OBJECT = "RECON_UNEXPECTED_OBJECT"
RECON_UNDECODABLE_PATH = "RECON_UNDECODABLE_PATH"
RECON_PATH_LIMIT_EXCEEDED = "RECON_PATH_LIMIT_EXCEEDED"
RECON_HUNK_LIMIT_EXCEEDED = "RECON_HUNK_LIMIT_EXCEEDED"
RECON_MALFORMED_FACTS = "RECON_MALFORMED_FACTS"
RECON_MISSING_SAFETY_FACT = "RECON_MISSING_SAFETY_FACT"
RECON_FACTS_MISMATCH = "RECON_FACTS_MISMATCH"
RECON_CONTRADICTORY_OVERLAP = "RECON_CONTRADICTORY_OVERLAP"
RECON_CONTRADICTORY_CHANGE = "RECON_CONTRADICTORY_CHANGE"
RECON_CONTRADICTORY_HUNKS = "RECON_CONTRADICTORY_HUNKS"
RECON_SCOPE_VIOLATION = "RECON_SCOPE_VIOLATION"
# HUMAN_REQUIRED
RECON_UNRELATED_HISTORIES = "RECON_UNRELATED_HISTORIES"
RECON_MULTIPLE_MERGE_BASES = "RECON_MULTIPLE_MERGE_BASES"
RECON_MODIFY_DELETE = "RECON_MODIFY_DELETE"
RECON_ADD_ADD_DIFFERENT = "RECON_ADD_ADD_DIFFERENT"
RECON_MODE_CONFLICT = "RECON_MODE_CONFLICT"
RECON_TYPE_CHANGE = "RECON_TYPE_CHANGE"
RECON_UNSAFE_MODE = "RECON_UNSAFE_MODE"
RECON_SYMLINK = "RECON_SYMLINK"
RECON_GITLINK = "RECON_GITLINK"
RECON_BINARY = "RECON_BINARY"
RECON_CASE_COLLISION = "RECON_CASE_COLLISION"
RECON_TEXT_SAFETY_UNPROVEN = "RECON_TEXT_SAFETY_UNPROVEN"
RECON_CASE_SAFETY_UNPROVEN = "RECON_CASE_SAFETY_UNPROVEN"
RECON_RENAME_IN_OVERLAP = "RECON_RENAME_IN_OVERLAP"
RECON_AMBIGUOUS_HUNK_GEOMETRY = "RECON_AMBIGUOUS_HUNK_GEOMETRY"
RECON_AMBIGUOUS_HANDLING = "RECON_AMBIGUOUS_HANDLING"
# SEMANTIC_REVIEW_REQUIRED
RECON_OVERLAPPING_HUNKS = "RECON_OVERLAPPING_HUNKS"
RECON_TOUCHING_HUNKS = "RECON_TOUCHING_HUNKS"
# NO_TEXTUAL_CONFLICT (evidence of what was proven - textual only)
RECON_NO_TEXTUAL_CONFLICT = "RECON_NO_TEXTUAL_CONFLICT"
RECON_DISJOINT_PATHS = "RECON_DISJOINT_PATHS"
RECON_DISJOINT_HUNKS = "RECON_DISJOINT_HUNKS"
RECON_CONVERGENT_CHANGES = "RECON_CONVERGENT_CHANGES"

# Read-error codes a facts record may carry; anything else is RECON_READ_FAILED.
_READ_ERROR_CODES = frozenset({
    RECON_ASSESSMENT_FAILED, RECON_READ_FAILED, RECON_UNEXPECTED_RAW, RECON_UNEXPECTED_NUMSTAT,
    RECON_UNEXPECTED_HUNK, RECON_UNDECODABLE_PATH, RECON_PATH_LIMIT_EXCEEDED, RECON_HUNK_LIMIT_EXCEEDED,
    RECON_UNEXPECTED_OBJECT,
})

# Text proof of one blob, and case proof of one added path.
BLOB_TEXT = "TEXT"
BLOB_BINARY = "BINARY"
BLOB_UNPROVEN = "UNPROVEN"
_BLOB_VERDICTS = frozenset({BLOB_TEXT, BLOB_BINARY, BLOB_UNPROVEN})
CASE_SAFE = "CASE_SAFE"
CASE_COLLISION = "CASE_COLLISION"
CASE_UNPROVEN = "CASE_UNPROVEN"
_CASE_VERDICTS = frozenset({CASE_SAFE, CASE_COLLISION, CASE_UNPROVEN})

# Plan validation reason codes.
PLAN_INVALID_INPUT = "PLAN_INVALID_INPUT"
PLAN_TAMPERED = "PLAN_TAMPERED"
PLAN_NOT_PROPOSED = "PLAN_NOT_PROPOSED"
PLAN_AUTHORIZATION_CLAIMED = "PLAN_AUTHORIZATION_CLAIMED"
PLAN_ANALYSIS_INVALID = "PLAN_ANALYSIS_INVALID"
PLAN_ANALYSIS_NOT_PLANNABLE = "PLAN_ANALYSIS_NOT_PLANNABLE"
PLAN_CLASSIFICATION_CHANGED = "PLAN_CLASSIFICATION_CHANGED"
PLAN_ASSESSMENT_CHANGED = "PLAN_ASSESSMENT_CHANGED"
PLAN_FACTS_CHANGED = "PLAN_FACTS_CHANGED"
PLAN_HEAD_CHANGED = "PLAN_HEAD_CHANGED"
PLAN_BASE_CHANGED = "PLAN_BASE_CHANGED"
PLAN_MERGE_BASE_CHANGED = "PLAN_MERGE_BASE_CHANGED"
PLAN_WORKTREE_CHANGED = "PLAN_WORKTREE_CHANGED"
PLAN_SCOPE_VIOLATION = "PLAN_SCOPE_VIOLATION"

# Plan steps: descriptive review checkpoints, never executable commands.
STEP_HUMAN_REVIEW_ANALYSIS = "HUMAN_REVIEW_ANALYSIS"
STEP_HUMAN_SEMANTIC_REVIEW = "HUMAN_SEMANTIC_REVIEW_OF_OVERLAPPING_HUNKS"
STEP_HUMAN_APPROVE_MECHANISM = "HUMAN_APPROVE_RECONCILIATION_MECHANISM"
STEP_REVALIDATE_PLAN = "REVALIDATE_PLAN_AGAINST_FRESH_ANALYSIS"
STEP_RUN_ACCEPTANCE = "RUN_HOST_ACCEPTANCE_COMMANDS"
STEP_SEMANTIC_VALIDATION = "SEMANTIC_VALIDATION"
STEP_REASSESS_FCP1 = "REASSESS_FCP1_INTEGRATION"

# Path outcomes.
PATH_HEAD_ONLY = "HEAD_ONLY"
PATH_BASE_ONLY = "BASE_ONLY"
PATH_CONVERGENT = "CONVERGENT"
PATH_DISJOINT_HUNKS = "DISJOINT_HUNKS"
PATH_OVERLAPPING_HUNKS = "OVERLAPPING_HUNKS"
PATH_HUMAN_REQUIRED = "HUMAN_REQUIRED"

SIDE_HEAD = "HEAD"
SIDE_BASE = "BASE"

_ABSENT_MODE = "000000"
_REGULAR_MODES = frozenset({"100644", "100755"})
_SYMLINK_MODE = "120000"
_GITLINK_MODE = "160000"
_RAW_STATUSES = frozenset({"A", "D", "M", "T"})
_TREE_MODE = "40000"
_HASH_BYTES = {"sha1": 20, "sha256": 32}

# Every diff setting that shapes the parsed output, pinned so no config
# (repository, user, system or inherited GIT_CONFIG_*) can change it.
# runner_git adds --no-ext-diff --no-textconv --submodule=short.
_PINNED_DIFF_OPTIONS = (
    "--no-color", "--no-renames", "--no-relative", "--ignore-submodules=none",
    "--diff-algorithm=myers", "--no-indent-heuristic",
)
_RAW_OPTIONS = ("--raw", "-z", "--no-abbrev")
_NUMSTAT_OPTIONS = ("--numstat", "-z")
_HUNK_OPTIONS = ("-U0", "--inter-hunk-context=0", "--src-prefix=a/", "--dst-prefix=b/")

_RAW_META = re.compile(r":([0-7]{6}) ([0-7]{6}) ([0-9a-f]+) ([0-9a-f]+) ([A-Z][0-9]*)")
_COUNT = re.compile(r"[0-9]+")
_HUNK_HEADER = re.compile(r"@@ -([0-9]+)(?:,([0-9]+))? \+([0-9]+)(?:,([0-9]+))? @@(?: .*)?")
_HEADER_LINE_PREFIXES = ("index ", "--- ", "+++ ")
_C_ESCAPES = {7: b"\\a", 8: b"\\b", 9: b"\\t", 10: b"\\n", 11: b"\\v", 12: b"\\f", 13: b"\\r",
              34: b'\\"', 92: b"\\\\"}


# ---------------------------------------------------------------------------
# Results (immutable)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PathChange:
    """One `--raw` record joined with its `--numstat` record. `added`/
    `deleted` are None exactly when git reports the change as binary."""

    path: str
    status: str
    old_mode: str
    new_mode: str
    old_sha: str
    new_sha: str
    binary: Optional[bool]
    added: Optional[int]
    deleted: Optional[int]


@dataclass(frozen=True)
class PathHunks:
    """Zero-context hunks of one side for one path, as
    (old_start, old_len, new_start, new_len) in merge-base coordinates, plus
    the +/- line counts and whether any hunk line carried a NUL byte."""

    path: str
    hunks: tuple
    added: int
    deleted: int
    binary_content: bool


@dataclass(frozen=True)
class ReconciliationFacts:
    """Everything read for one analysis. Built by `analyze_reconciliation`;
    `classify_reconciliation` trusts none of it without cross-checking it
    against the FCP-1 assessment."""

    schema: str = FACTS_SCHEMA
    assessment_fingerprint: Optional[str] = None
    head_sha: Optional[str] = None
    base_sha: Optional[str] = None
    merge_bases: tuple = ()
    head_changes: tuple = ()
    base_changes: tuple = ()
    head_hunks: tuple = ()
    base_hunks: tuple = ()
    head_hunk_bytes: int = 0
    base_hunk_bytes: int = 0
    max_paths: int = MAX_PATHS
    reassessment_fingerprint: Optional[str] = None
    reassessment_classification: Optional[str] = None
    read_errors: tuple = ()  # ((code, detail), ...)
    blob_checks: Optional[tuple] = None  # ((sha, size, BLOB_*), ...) per changed regular blob
    case_checks: Optional[tuple] = None  # ((path, CASE_*), ...) per added path


@dataclass(frozen=True)
class PathFinding:
    path: str
    outcome: str
    reason_codes: tuple = ()


@dataclass(frozen=True)
class ReconciliationAnalysis:
    """Outcome of `classify_reconciliation`. `assessment` is the FCP-1
    assessment exactly as received and `assessment_fingerprint` its
    original fingerprint. NO_TEXTUAL_CONFLICT is not semantic safety and
    not merge readiness; nothing here authorizes any action."""

    classification: str
    reason_codes: tuple
    fingerprint: str
    assessment: Optional[ri.IntegrationAssessment] = None
    assessment_fingerprint: Optional[str] = None
    assessment_classification: Optional[str] = None
    facts: Optional[ReconciliationFacts] = None
    worktree_key: Optional[str] = None
    head_ref: Optional[str] = None
    head_sha: Optional[str] = None
    base_sha: Optional[str] = None
    merge_bases: tuple = ()
    scope: tuple = ()
    authorized_scopes: tuple = ()
    path_findings: tuple = ()
    semantic_validation_required: bool = False
    human_approval_required: bool = True
    authorizes_action: bool = False
    schema: str = ANALYSIS_SCHEMA


@dataclass(frozen=True)
class ReconciliationPlan:
    """A PROPOSED reconciliation plan. Never approved, never executable:
    `steps` are review checkpoints and `acceptance_commands` are the host's
    own, verbatim and never run here."""

    status: str
    fingerprint: str
    analysis_fingerprint: str
    assessment_fingerprint: str
    classification: str
    worktree_key: Optional[str]
    head_ref: Optional[str]
    head_sha: str
    base_sha: str
    merge_bases: tuple
    scope: tuple
    authorized_scopes: tuple
    review_paths: tuple
    acceptance_commands: tuple
    steps: tuple
    reason_codes: tuple
    semantic_validation_required: bool = True
    human_approval_required: bool = True
    authorizes_action: bool = False
    schema: str = PLAN_SCHEMA


@dataclass(frozen=True)
class PlanValidation:
    """Whether a plan still matches a fresh analysis. `valid` grants no
    action: a human must still approve any execution mechanism."""

    valid: bool
    reason_codes: tuple
    plan_fingerprint: Optional[str] = None
    analysis_fingerprint: Optional[str] = None
    human_approval_required: bool = True
    authorizes_action: bool = False


class ReconciliationInputError(ValueError):
    """Refused input (invalid parameters, analysis or acceptance commands)."""


# ---------------------------------------------------------------------------
# Canonical fingerprints
# ---------------------------------------------------------------------------

def _digest(payload) -> str:
    # ensure_ascii keeps any surrogate-escaped byte representable.
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def _canonical(value):
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _canonical(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, (tuple, list)):
        return [_canonical(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)


def _analysis_payload(a: ReconciliationAnalysis) -> dict:
    payload = {f.name: _canonical(getattr(a, f.name)) for f in dataclasses.fields(a)
               if f.name not in ("fingerprint", "assessment")}
    return payload


def _plan_payload(p: ReconciliationPlan) -> dict:
    return {f.name: _canonical(getattr(p, f.name)) for f in dataclasses.fields(p) if f.name != "fingerprint"}


def _fcp1_fingerprint(a: ri.IntegrationAssessment) -> Optional[str]:
    """FCP-1's own fingerprint recomputed from the assessment's fields, or
    None if it cannot be (malformed fields)."""
    try:
        return ri._fingerprint(a.base, a.candidate, a.evidence, a.classification, a.reason_codes)
    except Exception:  # noqa: BLE001 - any failure is a fail-closed signal
        return None


# ---------------------------------------------------------------------------
# Governed read-only diff reads (through runner_integration._git only)
# ---------------------------------------------------------------------------

class _ReadFailure(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def _has_surrogates(text: str) -> bool:
    return any("\udc80" <= ch <= "\udcff" for ch in text)


def _read_git(worktree, *args) -> str:
    _, out = ri._git(worktree, *args)
    return out


def _diff(worktree, options: tuple, old: str, new: str, pathspecs=()) -> str:
    return _read_git(worktree, "diff", *options, *_PINNED_DIFF_OPTIONS, old, new, "--", *pathspecs)


def _object_size(worktree, sha: str) -> int:
    """Size of an object from its header only; nothing of its content is read."""
    out = _read_git(worktree, "cat-file", "-s", sha)
    if not re.fullmatch(r"[0-9]+\n?", out):
        raise _ReadFailure(RECON_UNEXPECTED_OBJECT, f"unexpected size {out[:40]!r} of {sha}")
    return int(out)


def _object_bytes(worktree, kind: str, sha: str, size: int) -> bytes:
    """Raw content of a `kind` object whose header size was read first. cat-file
    of a type never applies filters or textconv; the type is checked by git."""
    data = _read_git(worktree, "cat-file", kind, sha).encode("utf-8", "surrogateescape")
    if len(data) != size:
        raise _ReadFailure(RECON_UNEXPECTED_OBJECT, f"{kind} {sha} is not {size} bytes")
    return data


def _split_z(out: str) -> list:
    fields = out.split("\0")
    if fields and fields[-1] == "":
        fields.pop()
    return fields


def _check_path(path: str, code: str) -> None:
    if not path:
        raise _ReadFailure(code, "empty path")
    if _has_surrogates(path):
        raise _ReadFailure(RECON_UNDECODABLE_PATH, f"undecodable path {path!r}")


def _parse_raw(out: str, object_format: str) -> dict:
    fields = _split_z(out)
    if len(fields) % 2:
        raise _ReadFailure(RECON_UNEXPECTED_RAW, "odd number of raw fields")
    records = {}
    for i in range(0, len(fields), 2):
        meta, path = fields[i], fields[i + 1]
        match = _RAW_META.fullmatch(meta)
        if match is None:
            raise _ReadFailure(RECON_UNEXPECTED_RAW, f"unexpected raw record {meta!r}")
        old_mode, new_mode, old_sha, new_sha, status = match.groups()
        _check_path(path, RECON_UNEXPECTED_RAW)
        if status not in _RAW_STATUSES:
            raise _ReadFailure(RECON_UNEXPECTED_RAW, f"unexpected raw status {status!r}")
        if not (ri._is_sha(old_sha, object_format) and ri._is_sha(new_sha, object_format)):
            raise _ReadFailure(RECON_UNEXPECTED_RAW, f"unexpected object names for {path!r}")
        if path in records:
            raise _ReadFailure(RECON_UNEXPECTED_RAW, f"duplicate raw record for {path!r}")
        records[path] = (status, old_mode, new_mode, old_sha, new_sha)
    return records


def _parse_numstat(out: str) -> dict:
    records = {}
    for entry in _split_z(out):
        parts = entry.split("\t", 2)
        if len(parts) != 3:
            raise _ReadFailure(RECON_UNEXPECTED_NUMSTAT, f"unexpected numstat record {entry!r}")
        added, deleted, path = parts
        _check_path(path, RECON_UNEXPECTED_NUMSTAT)
        if added == "-" and deleted == "-":
            counts = None
        elif _COUNT.fullmatch(added) and _COUNT.fullmatch(deleted):
            counts = (int(added), int(deleted))
        else:
            raise _ReadFailure(RECON_UNEXPECTED_NUMSTAT, f"unexpected numstat counts for {path!r}")
        if path in records:
            raise _ReadFailure(RECON_UNEXPECTED_NUMSTAT, f"duplicate numstat record for {path!r}")
        records[path] = counts
    return records


def _read_changes(worktree, old: str, new: str, object_format: str) -> tuple:
    raw = _parse_raw(_diff(worktree, _RAW_OPTIONS, old, new), object_format)
    numstat = _parse_numstat(_diff(worktree, _NUMSTAT_OPTIONS, old, new))
    if set(raw) != set(numstat):
        raise _ReadFailure(RECON_UNEXPECTED_NUMSTAT, "numstat paths differ from raw paths")
    changes = []
    for path in sorted(raw):
        status, old_mode, new_mode, old_sha, new_sha = raw[path]
        counts = numstat[path]
        changes.append(PathChange(
            path=path, status=status, old_mode=old_mode, new_mode=new_mode, old_sha=old_sha, new_sha=new_sha,
            binary=counts is None, added=None if counts is None else counts[0],
            deleted=None if counts is None else counts[1],
        ))
    return tuple(changes)


def _c_quote(raw: bytes, quote_high: bool) -> Optional[bytes]:
    """git's quote_c_style: the quoted body, or None if no quoting is needed."""
    out, needed = bytearray(), False
    for b in raw:
        if b in _C_ESCAPES:
            out += _C_ESCAPES[b]
            needed = True
        elif b < 0x20 or b == 0x7F or (quote_high and b >= 0x80):
            out += b"\\%03o" % b
            needed = True
        else:
            out.append(b)
    return bytes(out) if needed else None


def _expected_headers(path: str) -> set:
    """Every `diff --git` header git can print for `path` with the pinned
    a/ b/ prefixes, under either core.quotePath setting."""
    raw = path.encode("utf-8", "surrogateescape")
    headers = set()
    for quote_high in (True, False):
        tokens = []
        for prefix in (b"a/", b"b/"):
            quoted = _c_quote(prefix + raw, quote_high)
            tokens.append(b'"' + quoted + b'"' if quoted is not None else prefix + raw)
        headers.add((b"diff --git " + tokens[0] + b" " + tokens[1]).decode("utf-8", "surrogateescape"))
    return headers


def _parse_hunks(out: str, paths) -> dict:
    """{path: PathHunks} from zero-context patch output for exactly `paths`.
    Hunk bodies are consumed by the counts in their headers, so content
    lines are never mistaken for structure."""
    by_header = {}
    for path in paths:
        for header in _expected_headers(path):
            by_header[header] = path
    lines = out.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    parsed, current, i, n = {}, None, 0, len(lines)
    while i < n:
        line = lines[i]
        if line.startswith("diff --git "):
            path = by_header.get(line)
            if path is None or path in parsed:
                raise _ReadFailure(RECON_UNEXPECTED_HUNK, f"unexpected diff header {line!r}")
            current = parsed[path] = {"hunks": [], "added": 0, "deleted": 0, "nul": False, "binary": False}
            i += 1
            while i < n and not lines[i].startswith(("@@", "diff --git ")):
                if lines[i].startswith("Binary files "):
                    current["binary"] = True
                elif not lines[i].startswith(_HEADER_LINE_PREFIXES):
                    raise _ReadFailure(RECON_UNEXPECTED_HUNK, f"unexpected header line {lines[i]!r}")
                i += 1
            continue
        match = _HUNK_HEADER.fullmatch(line)
        if current is None or match is None or current["binary"]:
            raise _ReadFailure(RECON_UNEXPECTED_HUNK, f"unexpected hunk line {line!r}")
        old_start, old_len, new_start, new_len = (
            int(match.group(1)), int(match.group(2) or "1"), int(match.group(3)), int(match.group(4) or "1"),
        )
        i += 1
        minus, plus, after_content = old_len, new_len, False
        while minus or plus or (i < n and after_content and lines[i].startswith("\\")):
            if i >= n:
                raise _ReadFailure(RECON_UNEXPECTED_HUNK, "truncated hunk")
            body = lines[i]
            if body.startswith("\\") and after_content:
                after_content = False
            elif body.startswith("-") and minus and plus == new_len:
                minus -= 1
                after_content = True
            elif body.startswith("+") and plus and not minus:
                plus -= 1
                after_content = True
            else:
                raise _ReadFailure(RECON_UNEXPECTED_HUNK, f"unexpected hunk body line {body[:80]!r}")
            if "\0" in body:
                current["nul"] = True
            i += 1
        current["hunks"].append((old_start, old_len, new_start, new_len))
        current["added"] += new_len
        current["deleted"] += old_len
    missing = set(paths) - set(parsed)
    if missing:
        raise _ReadFailure(RECON_UNEXPECTED_HUNK, f"no hunk output for {sorted(missing)[0]!r}")
    return {
        path: PathHunks(path=path, hunks=tuple(v["hunks"]), added=v["added"], deleted=v["deleted"],
                        binary_content=v["nul"] or v["binary"])
        for path, v in parsed.items()
    }


def _hunk_bound(paths, changes: dict, sizes: dict) -> Optional[int]:
    """Upper bound of the -U0 output bytes for `paths` of one side, from the
    pinned blob sizes and line counts (None if a size is unknown): headers,
    every changed line's content (within its blob) plus its prefix, one hunk
    header per changed line at most, and two no-newline markers."""
    total = 0
    for path in paths:
        ch = changes[path]
        if ch.old_sha not in sizes or ch.new_sha not in sizes:
            return None
        quoted = 4 * len(path.encode("utf-8", "surrogateescape")) + 4  # "a/..." with \ooo escapes
        total += 4 * quoted + 2 * len(ch.old_sha) + 64                 # diff --git / index / --- / +++
        total += sizes[ch.old_sha] + sizes[ch.new_sha] + 2 * _NO_NEWLINE_BYTES
        total += (ch.added + ch.deleted) * (1 + _HUNK_HEADER_BYTES)
    return total


def _read_hunks(worktree, old: str, new: str, paths: list, changes: dict, sizes: dict) -> tuple:
    """(tuple of PathHunks, decoded byte count) for the text paths of one side.
    No hunk output is requested unless `_hunk_bound` proves it fits."""
    if not paths:
        return (), 0
    lower_bound = sum(2 * (changes[p].added + changes[p].deleted) for p in paths)  # >= "+\n" per line
    if lower_bound > MAX_HUNK_BYTES:
        raise _ReadFailure(RECON_HUNK_LIMIT_EXCEEDED, f"at least {lower_bound} bytes of hunks")
    upper_bound = _hunk_bound(paths, changes, sizes)
    if upper_bound is None or upper_bound > MAX_HUNK_BYTES:
        raise _ReadFailure(RECON_HUNK_LIMIT_EXCEEDED, f"hunk output not provably within {MAX_HUNK_BYTES} bytes")
    batches, batch, size = [], [], 0
    for path in paths:
        spec = ":(literal)" + path
        if batch and size + len(spec) > _MAX_PATHSPEC_CHARS:
            batches.append(batch)
            batch, size = [], 0
        batch.append(path)
        size += len(spec) + 1
    batches.append(batch)
    hunks, total = {}, 0
    for batch in batches:
        out = _diff(worktree, _HUNK_OPTIONS, old, new, [":(literal)" + p for p in batch])
        total += len(out.encode("utf-8", "surrogateescape"))
        if total > MAX_HUNK_BYTES:
            raise _ReadFailure(RECON_HUNK_LIMIT_EXCEEDED, f"more than {MAX_HUNK_BYTES} bytes of hunks")
        hunks.update(_parse_hunks(out, batch))
    return tuple(hunks[p] for p in sorted(hunks)), total


def _needs_hunks(h: PathChange, b: PathChange) -> bool:
    """Both sides modified the same regular text file, without mode change,
    to different results: only then is hunk geometry needed."""
    modes = {h.old_mode, h.new_mode, b.old_mode, b.new_mode}
    return (
        h.status == "M" and b.status == "M" and len(modes) == 1 and modes <= _REGULAR_MODES
        and h.binary is False and b.binary is False and h.new_sha != b.new_sha
    )


def _regular_blobs(ch: PathChange) -> list:
    """The regular-file blobs (old and/or new) a change involves."""
    return [sha for mode, sha in ((ch.old_mode, ch.old_sha), (ch.new_mode, ch.new_sha)) if mode in _REGULAR_MODES]


def _read_blob_checks(worktree, changes) -> tuple:
    """((sha, size, verdict), ...) for every changed regular blob, by SHA.
    Numstat counts are no proof of text (a `diff` attribute forces them),
    so each blob within the limits is read and scanned for NUL; a larger
    one, or one past the total budget, stays UNPROVEN."""
    checks, budget = [], MAX_BLOB_TOTAL_BYTES
    for sha in sorted({sha for ch in changes for sha in _regular_blobs(ch)}):
        size = _object_size(worktree, sha)
        if size > MAX_BLOB_BYTES or size > budget:
            checks.append((sha, size, BLOB_UNPROVEN))
            continue
        budget -= size
        binary = b"\0" in _object_bytes(worktree, "blob", sha, size)
        checks.append((sha, size, BLOB_BINARY if binary else BLOB_TEXT))
    return tuple(checks)


def _parse_tree(data: bytes, object_format: str) -> list:
    """[(mode, name, sha)] of a raw tree object."""
    width, entries, i = _HASH_BYTES[object_format], [], 0
    while i < len(data):
        space = data.find(b" ", i)
        nul = data.find(b"\0", space + 1) if space >= 0 else -1
        if nul < 0 or nul + 1 + width > len(data) or not re.fullmatch(rb"[0-7]{5,6}", data[i:space]) \
                or nul == space + 1 or b"/" in data[space + 1:nul]:
            raise _ReadFailure(RECON_UNEXPECTED_OBJECT, "malformed tree object")
        entries.append((data[i:space].decode("ascii"), data[space + 1:nul].decode("utf-8", "surrogateescape"),
                        data[nul + 1:nul + 1 + width].hex()))
        i = nul + 1 + width
    return entries


class _TreeReader:
    """Bounded, cached reads of immutable trees by SHA. `entries` is None
    once a tree is over a limit: whatever depends on it is unproven."""

    def __init__(self, worktree, object_format: str):
        self.worktree, self.object_format = worktree, object_format
        self.cache, self.reads, self.budget = {}, 0, MAX_TREE_TOTAL_BYTES

    def entries(self, sha: str) -> Optional[list]:
        if sha not in self.cache:
            self.cache[sha] = None
            if self.reads < MAX_TREE_READS:
                self.reads += 1
                size = _object_size(self.worktree, sha)
                if size <= MAX_TREE_BYTES and size <= self.budget:
                    self.budget -= size
                    data = _object_bytes(self.worktree, "tree", sha, size)
                    self.cache[sha] = _parse_tree(data, self.object_format)
        return self.cache[sha]


def _case_verdict(reader: _TreeReader, root: str, path: str) -> str:
    """Whether an added path, or any of its directories, collides by case /
    normalization (`_case_key`) with a differently named entry of the same
    directory of the merge-base tree."""
    parts = path.split("/")
    tree = root
    for depth, part in enumerate(parts):
        entries = reader.entries(tree)
        if entries is None:
            return CASE_UNPROVEN
        key, child, undecodable = _case_key(part), None, False
        for mode, name, sha in entries:
            if name == part:
                child = (mode, sha)
            elif _has_surrogates(name):
                undecodable = True
            elif _case_key(name) == key:
                return CASE_COLLISION
        if undecodable:
            return CASE_UNPROVEN
        if child is None or child[0] != _TREE_MODE or depth == len(parts) - 1:
            return CASE_SAFE  # nothing of the merge base lies below this level
        tree = child[1]
    return CASE_SAFE


def _read_case_checks(worktree, merge_base: str, added, object_format: str) -> tuple:
    """((path, verdict), ...) for every added path against the merge-base
    tree. Changed paths are checked against each other by the classifier."""
    if not added:
        return ()
    root = _read_git(worktree, "rev-parse", "--verify", "--quiet", merge_base + "^{tree}").strip()
    if not ri._is_sha(root, object_format):
        raise _ReadFailure(RECON_UNEXPECTED_OBJECT, f"unexpected tree of {merge_base}")
    reader = _TreeReader(worktree, object_format)
    return tuple((path, _case_verdict(reader, root, path)) for path in sorted(added))


def _read_facts(worktree, assessment: ri.IntegrationAssessment, max_paths: int) -> ReconciliationFacts:
    c = assessment.candidate
    fields = dict(
        assessment_fingerprint=assessment.fingerprint, head_sha=c.head_sha, base_sha=c.base_tracking_sha,
        merge_bases=tuple(c.merge_bases), max_paths=max_paths,
    )
    try:
        if len(c.merge_bases) != 1:
            # Unrelated or criss-cross histories: nothing to diff against.
            return ReconciliationFacts(**fields)
        if len(c.changed_paths) + len(c.base_changed_paths) > max_paths:
            raise _ReadFailure(RECON_PATH_LIMIT_EXCEEDED, "FCP-1 reports more path records than allowed")
        merge_base, fmt = c.merge_bases[0], c.object_format
        head_changes = _read_changes(worktree, merge_base, c.head_sha, fmt)
        base_changes = _read_changes(worktree, merge_base, c.base_tracking_sha, fmt)
        fields.update(head_changes=head_changes, base_changes=base_changes)
        if len(head_changes) + len(base_changes) > max_paths:
            raise _ReadFailure(RECON_PATH_LIMIT_EXCEEDED, "more path records than allowed")
        fields["blob_checks"] = _read_blob_checks(worktree, head_changes + base_changes)
        added = {ch.path for ch in head_changes + base_changes if ch.status == "A"}
        fields["case_checks"] = _read_case_checks(worktree, merge_base, added, fmt)
        sizes = {sha: size for sha, size, _ in fields["blob_checks"]}
        head_map = {ch.path: ch for ch in head_changes}
        base_map = {ch.path: ch for ch in base_changes}
        text = sorted(p for p in set(head_map) & set(base_map) if _needs_hunks(head_map[p], base_map[p]))
        fields["head_hunks"], fields["head_hunk_bytes"] = _read_hunks(
            worktree, merge_base, c.head_sha, text, head_map, sizes)
        fields["base_hunks"], fields["base_hunk_bytes"] = _read_hunks(
            worktree, merge_base, c.base_tracking_sha, text, base_map, sizes)
    except _ReadFailure as exc:
        return ReconciliationFacts(read_errors=((exc.code, exc.detail),), **fields)
    except (ri._GitReadError, ValueError, OSError) as exc:
        return ReconciliationFacts(read_errors=((RECON_READ_FAILED, str(exc)),), **fields)
    return ReconciliationFacts(**fields)


# ---------------------------------------------------------------------------
# Classification (pure)
# ---------------------------------------------------------------------------

def _is_int(value, minimum: int = 0) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _change_errors(ch, fmt: str) -> list:
    if type(ch) is not PathChange:
        return [RECON_MALFORMED_FACTS]
    errors = []
    if not isinstance(ch.path, str) or not ch.path or "\0" in ch.path or _has_surrogates(ch.path):
        errors.append(RECON_MALFORMED_FACTS)
    if ch.status not in _RAW_STATUSES:
        errors.append(RECON_MALFORMED_FACTS)
    mode_ok = all(isinstance(m, str) and re.fullmatch(r"[0-7]{6}", m) for m in (ch.old_mode, ch.new_mode))
    if not mode_ok or not (ri._is_sha(ch.old_sha, fmt) and ri._is_sha(ch.new_sha, fmt)):
        return errors + [RECON_MALFORMED_FACTS]
    zero = "0" * len(ch.old_sha)
    old_absent = ch.old_mode == _ABSENT_MODE and ch.old_sha == zero
    new_absent = ch.new_mode == _ABSENT_MODE and ch.new_sha == zero
    consistent = {
        "A": old_absent and ch.new_mode != _ABSENT_MODE and ch.new_sha != zero,
        "D": new_absent and ch.old_mode != _ABSENT_MODE and ch.old_sha != zero,
        "M": ch.old_mode != _ABSENT_MODE and ch.new_mode != _ABSENT_MODE and ch.old_sha != zero
        and ch.new_sha != zero and ch.old_mode[:2] == ch.new_mode[:2],
        "T": ch.old_mode != _ABSENT_MODE and ch.new_mode != _ABSENT_MODE and ch.old_mode[:2] != ch.new_mode[:2],
    }.get(ch.status, False)
    if not consistent:
        errors.append(RECON_CONTRADICTORY_CHANGE)
    if not isinstance(ch.binary, bool):
        errors.append(RECON_MISSING_SAFETY_FACT)
    elif ch.binary and (ch.added is not None or ch.deleted is not None):
        errors.append(RECON_MALFORMED_FACTS)
    elif not ch.binary and not (_is_int(ch.added) and _is_int(ch.deleted)):
        errors.append(RECON_MALFORMED_FACTS)
    return errors


def _hunks_errors(entries, required: set, changes: dict) -> list:
    errors, seen = [], set()
    if not isinstance(entries, tuple):
        return [RECON_MALFORMED_FACTS]
    for entry in entries:
        if type(entry) is not PathHunks or not isinstance(entry.hunks, tuple) \
                or not isinstance(entry.binary_content, bool) \
                or not (_is_int(entry.added) and _is_int(entry.deleted)) \
                or any(not (isinstance(h, tuple) and len(h) == 4 and all(_is_int(v) for v in h))
                       for h in entry.hunks):
            return [RECON_MALFORMED_FACTS]
        if entry.path in seen or entry.path not in required:
            errors.append(RECON_CONTRADICTORY_HUNKS)
            continue
        seen.add(entry.path)
        counted = (sum(h[3] for h in entry.hunks), sum(h[1] for h in entry.hunks))
        change = changes[entry.path]
        if counted != (entry.added, entry.deleted) or counted != (change.added, change.deleted) \
                or not entry.hunks and not entry.binary_content:
            errors.append(RECON_CONTRADICTORY_HUNKS)
    if required - seen:
        errors.append(RECON_MISSING_SAFETY_FACT)
    return errors


def _checks_errors(checks, required: set, valid_entry) -> list:
    """Errors of a blob_checks / case_checks tuple that must hold exactly one
    well-formed entry per `required` key."""
    if checks is None:
        return [RECON_MISSING_SAFETY_FACT] if required else []
    if not isinstance(checks, tuple) or not all(valid_entry(e) for e in checks):
        return [RECON_MALFORMED_FACTS]
    keys = [e[0] for e in checks]
    errors = []
    if len(set(keys)) != len(keys) or not set(keys) <= required:
        errors.append(RECON_CONTRADICTORY_CHANGE)
    if required - set(keys):
        errors.append(RECON_MISSING_SAFETY_FACT)
    return errors


def _valid_blob_check(entry) -> bool:
    return isinstance(entry, tuple) and len(entry) == 3 and isinstance(entry[0], str) and _is_int(entry[1]) \
        and entry[2] in _BLOB_VERDICTS and (entry[2] == BLOB_UNPROVEN or entry[1] <= MAX_BLOB_BYTES)


def _valid_case_check(entry) -> bool:
    return isinstance(entry, tuple) and len(entry) == 2 and isinstance(entry[0], str) and entry[1] in _CASE_VERDICTS


def _facts_errors(a: ri.IntegrationAssessment, f: ReconciliationFacts) -> list:
    """FAIL_CLOSED reason codes for facts that are unreadable, malformed,
    drifted, over limits or inconsistent with the assessment."""
    c, errors = a.candidate, []
    if f.schema != FACTS_SCHEMA:
        errors.append(RECON_MALFORMED_FACTS)
    if not isinstance(f.read_errors, tuple):
        errors.append(RECON_MALFORMED_FACTS)
    else:
        for entry in f.read_errors:
            ok = isinstance(entry, tuple) and len(entry) == 2 and all(isinstance(x, str) for x in entry)
            errors.append(entry[0] if ok and entry[0] in _READ_ERROR_CODES else RECON_READ_FAILED)
    if f.reassessment_fingerprint is None or f.reassessment_classification is None:
        errors.append(RECON_MISSING_SAFETY_FACT)
    elif (f.reassessment_fingerprint, f.reassessment_classification) != (a.fingerprint, a.classification):
        errors.append(RECON_ASSESSMENT_DRIFT)
    if f.assessment_fingerprint != a.fingerprint:
        errors.append(RECON_FACTS_MISMATCH)
    if errors:
        return errors  # incomplete or untrustworthy: nothing below is meaningful

    fmt = c.object_format
    if (f.head_sha, f.base_sha) != (c.head_sha, c.base_tracking_sha) or f.base_sha != a.base.tracking_sha \
            or not ri._is_sha(f.head_sha, fmt) or not ri._is_sha(f.base_sha, fmt) \
            or f.merge_bases != tuple(c.merge_bases):
        errors.append(RECON_FACTS_MISMATCH)
    if not _is_int(f.max_paths, 1) or f.max_paths > MAX_PATHS:
        errors.append(RECON_MALFORMED_FACTS)
    if not (_is_int(f.head_hunk_bytes) and _is_int(f.base_hunk_bytes)):
        errors.append(RECON_MALFORMED_FACTS)
    if not (isinstance(f.head_changes, tuple) and isinstance(f.base_changes, tuple)):
        errors.append(RECON_MALFORMED_FACTS)
    if errors:
        return errors
    for ch in f.head_changes + f.base_changes:
        errors.extend(_change_errors(ch, fmt))
    if errors:
        return errors

    if len(f.head_changes) + len(f.base_changes) > f.max_paths:
        errors.append(RECON_PATH_LIMIT_EXCEEDED)
    if max(f.head_hunk_bytes, f.base_hunk_bytes) > MAX_HUNK_BYTES:
        errors.append(RECON_HUNK_LIMIT_EXCEEDED)
    head = {ch.path: ch for ch in f.head_changes}
    base = {ch.path: ch for ch in f.base_changes}
    if len(head) != len(f.head_changes) or len(base) != len(f.base_changes):
        errors.append(RECON_MALFORMED_FACTS)
        return errors

    if len(f.merge_bases) != 1:
        if f.head_changes or f.base_changes or f.head_hunks or f.base_hunks or f.blob_checks or f.case_checks:
            errors.append(RECON_CONTRADICTORY_CHANGE)
    else:
        if {(ch.status, ch.path) for ch in f.head_changes} != set(map(tuple, c.changed_paths)) \
                or {(ch.status, ch.path) for ch in f.base_changes} != set(map(tuple, c.base_changed_paths)):
            errors.append(RECON_FACTS_MISMATCH)
        overlap = set(head) & set(base)
        if tuple(sorted(overlap)) != tuple(c.overlapping_paths):
            errors.append(RECON_CONTRADICTORY_OVERLAP)
        for path in overlap:
            h, b = head[path], base[path]
            if (h.old_mode, h.old_sha) != (b.old_mode, b.old_sha):
                errors.append(RECON_CONTRADICTORY_CHANGE)
        required = {p for p in overlap if _needs_hunks(head[p], base[p])}
        errors.extend(_hunks_errors(f.head_hunks, required, head))
        errors.extend(_hunks_errors(f.base_hunks, required, base))
        blob_errors = _checks_errors(f.blob_checks, {sha for ch in f.head_changes + f.base_changes
                                                     for sha in _regular_blobs(ch)}, _valid_blob_check)
        errors.extend(blob_errors)
        added = {ch.path for ch in f.head_changes + f.base_changes if ch.status == "A"}
        errors.extend(_checks_errors(f.case_checks, added, _valid_case_check))
        if not blob_errors:
            # The hunks must have been provably bounded before they were read.
            sizes = {sha: size for sha, size, _ in f.blob_checks or ()}
            for side in (head, base):
                bound = _hunk_bound(sorted(required), side, sizes)
                if bound is None:
                    errors.append(RECON_MISSING_SAFETY_FACT)
                elif bound > MAX_HUNK_BYTES:
                    errors.append(RECON_HUNK_LIMIT_EXCEEDED)

    if c.scope_error is not None or c.unauthorized_changed_paths or not c.authorized_scopes \
            or not all(claude_runner.path_is_authorized(p, list(c.authorized_scopes)) for p in head):
        errors.append(RECON_SCOPE_VIOLATION)
    return errors


def _change_hazards(ch: PathChange, hunks: Optional[PathHunks], blobs: dict) -> list:
    hazards = []
    for sha in _regular_blobs(ch):
        if blobs.get(sha) == BLOB_BINARY:
            hazards.append(RECON_BINARY)
        elif blobs.get(sha) != BLOB_TEXT:
            hazards.append(RECON_TEXT_SAFETY_UNPROVEN)
    for mode in (ch.old_mode, ch.new_mode):
        if mode == _SYMLINK_MODE:
            hazards.append(RECON_SYMLINK)
        elif mode == _GITLINK_MODE:
            hazards.append(RECON_GITLINK)
        elif mode != _ABSENT_MODE and mode not in _REGULAR_MODES:
            hazards.append(RECON_UNSAFE_MODE)
    if ch.status == "T":
        hazards.append(RECON_TYPE_CHANGE)
    if ch.binary or (hunks is not None and hunks.binary_content):
        hazards.append(RECON_BINARY)
    return hazards


def _interval(hunk: tuple) -> tuple:
    """Closed interval in "gap" coordinates (line k at 2k, the gap after it
    at 2k+1). A replacement covers its lines plus both bounding gaps, a pure
    insertion is the single gap it is inserted into - so any two changes
    that share or touch a boundary intersect."""
    start, length = hunk[0], hunk[1]
    if length:
        return 2 * start - 1, 2 * (start + length) - 1
    return 2 * start + 1, 2 * start + 1


def _geometry_ambiguous(hunks: tuple) -> bool:
    previous = None
    for hunk in hunks:
        start, length, new_start, new_len = hunk
        if (length and start < 1) or (new_len and new_start < 1) or (length == 0 and new_len == 0):
            return True
        lo, hi = _interval(hunk)
        if previous is not None and lo <= previous:
            return True  # unsorted, overlapping or touching within one side
        previous = hi
    return not hunks


def _hunk_relation(left: tuple, right: tuple) -> Optional[str]:
    """RECON_OVERLAPPING_HUNKS, RECON_TOUCHING_HUNKS or None (disjoint)."""
    relation = None
    for a in left:
        for b in right:
            (alo, ahi), (blo, bhi) = _interval(a), _interval(b)
            lo, hi = max(alo, blo), min(ahi, bhi)
            if lo > hi:
                continue
            a_point, b_point = alo == ahi, blo == bhi
            inside = (a_point and blo < alo < bhi) or (b_point and alo < blo < ahi)
            if lo < hi or (a_point and b_point) or inside:
                return RECON_OVERLAPPING_HUNKS
            relation = RECON_TOUCHING_HUNKS
    return relation


def _case_key(path: str) -> str:
    return unicodedata.normalize("NFC", path).casefold()


def _case_collisions(paths) -> set:
    """Paths (or directory prefixes) that differ but collide on a case-
    insensitive / normalization-insensitive filesystem."""
    seen = {}
    for path in paths:
        parts = path.split("/")
        for depth in range(1, len(parts) + 1):
            name = "/".join(parts[:depth])
            seen.setdefault(_case_key(name), set()).add(name)
    colliding = {name for names in seen.values() if len(names) > 1 for name in names}
    return {p for p in paths if any(p == n or p.startswith(n + "/") for n in colliding)}


def _renamed_paths(changes: dict) -> set:
    """Both paths of every rename-like D+A pair (same blob) within one side."""
    deleted = {}
    for ch in changes.values():
        if ch.status == "D":
            deleted.setdefault(ch.old_sha, set()).add(ch.path)
    renamed = set()
    for ch in changes.values():
        if ch.status == "A" and ch.new_sha in deleted:
            renamed |= deleted[ch.new_sha] | {ch.path}
    return renamed


def _path_analysis(f: ReconciliationFacts) -> tuple:
    head = {ch.path: ch for ch in f.head_changes}
    base = {ch.path: ch for ch in f.base_changes}
    head_hunks = {h.path: h for h in f.head_hunks}
    base_hunks = {h.path: h for h in f.base_hunks}
    overlap = set(head) & set(base)
    collisions = _case_collisions(set(head) | set(base))
    renames = (_renamed_paths(head) | _renamed_paths(base)) & overlap
    blobs = {sha: verdict for sha, _, verdict in f.blob_checks or ()}
    cases = dict(f.case_checks or ())
    findings = []
    for path in sorted(set(head) | set(base)):
        h, b = head.get(path), base.get(path)
        human = []
        if h is not None:
            human += _change_hazards(h, head_hunks.get(path), blobs)
        if b is not None:
            human += _change_hazards(b, base_hunks.get(path), blobs)
        if path in collisions or cases.get(path) == CASE_COLLISION:
            human.append(RECON_CASE_COLLISION)
        if path in cases and cases[path] not in (CASE_SAFE, CASE_COLLISION):
            human.append(RECON_CASE_SAFETY_UNPROVEN)
        if path in renames:
            human.append(RECON_RENAME_IN_OVERLAP)
        outcome, other = (PATH_HEAD_ONLY if b is None else PATH_BASE_ONLY), []
        if h is not None and b is not None:
            if (h.status == "D" and b.status == "D") or (h.new_sha, h.new_mode) == (b.new_sha, b.new_mode):
                outcome = PATH_CONVERGENT
            elif "D" in (h.status, b.status):
                human.append(RECON_MODIFY_DELETE)
            elif h.status == "A" and b.status == "A":
                human.append(RECON_ADD_ADD_DIFFERENT)
            elif h.status == "M" and b.status == "M" and (h.old_mode != h.new_mode or b.old_mode != b.new_mode):
                human.append(RECON_MODE_CONFLICT)
            elif _needs_hunks(h, b):
                left, right = head_hunks[path].hunks, base_hunks[path].hunks
                if _geometry_ambiguous(left) or _geometry_ambiguous(right):
                    human.append(RECON_AMBIGUOUS_HUNK_GEOMETRY)
                else:
                    relation = _hunk_relation(left, right)
                    outcome = PATH_OVERLAPPING_HUNKS if relation else PATH_DISJOINT_HUNKS
                    other = [relation] if relation else []
            else:
                human.append(RECON_AMBIGUOUS_HANDLING)
        if human:
            findings.append(PathFinding(path, PATH_HUMAN_REQUIRED, tuple(dict.fromkeys(human))))
        else:
            findings.append(PathFinding(path, outcome, tuple(other)))
    return tuple(findings)


def _result(classification: str, reasons, *, assessment=None, facts=None, findings=()) -> ReconciliationAnalysis:
    c = assessment.candidate if assessment is not None else None
    reasons = list(dict.fromkeys(reasons))
    validation = classification in (HUMAN_REQUIRED, SEMANTIC_REVIEW_REQUIRED, NO_TEXTUAL_CONFLICT)
    if validation:
        reasons.append(RECON_SEMANTIC_VALIDATION_REQUIRED)
    fields = dict(
        classification=classification, reason_codes=tuple(dict.fromkeys(reasons)),
        assessment=assessment,
        assessment_fingerprint=assessment.fingerprint if assessment is not None else None,
        assessment_classification=assessment.classification if assessment is not None else None,
        facts=facts, path_findings=tuple(findings), semantic_validation_required=validation,
    )
    if c is not None:
        fields.update(
            worktree_key=c.worktree_key, head_ref=c.head_ref, head_sha=c.head_sha,
            base_sha=c.base_tracking_sha, merge_bases=tuple(c.merge_bases),
            scope=tuple(sorted({p for _, p in c.changed_paths})),
            authorized_scopes=tuple(sorted(c.authorized_scopes)),
        )
    draft = ReconciliationAnalysis(fingerprint="", **fields)
    return dataclasses.replace(draft, fingerprint=_digest(_analysis_payload(draft)))


def _assessment_errors(a: ri.IntegrationAssessment) -> list:
    errors = []
    if not isinstance(a.fingerprint, str) or _fcp1_fingerprint(a) != a.fingerprint:
        errors.append(RECON_ASSESSMENT_TAMPERED)
    if a.human_approval_required is not True or a.eligible is not False:
        errors.append(RECON_ASSESSMENT_TAMPERED)
    if not isinstance(a.candidate, ri.IntegrationCandidate) or not isinstance(a.base, ri.CanonicalBase):
        errors.append(RECON_MALFORMED_ASSESSMENT)
    return errors


def classify_reconciliation(assessment, facts) -> ReconciliationAnalysis:
    """Pure, fail-closed classification with the fixed precedence of
    RECONCILIATION_PRECEDENCE. `assessment` is an FCP-1 IntegrationAssessment
    (exposed unchanged); `facts` the ReconciliationFacts read for it."""
    facts_ok = type(facts) is ReconciliationFacts
    if not isinstance(assessment, ri.IntegrationAssessment) or not isinstance(assessment.classification, str):
        reasons = []
        if facts_ok and isinstance(facts.read_errors, tuple):
            reasons = [e[0] for e in facts.read_errors if isinstance(e, tuple) and e and e[0] in _READ_ERROR_CODES]
        if assessment is not None or not reasons:
            reasons.insert(0, RECON_MALFORMED_ASSESSMENT)
        return _result(FAIL_CLOSED, reasons, facts=facts if facts_ok else None)
    if assessment.classification not in RECONCILABLE_FCP1_CLASSIFICATIONS:
        return _result(NOT_APPLICABLE, [RECON_NOT_APPLICABLE, f"FCP1_{assessment.classification}"],
                       assessment=assessment)

    fail = _assessment_errors(assessment)
    if not facts_ok:
        fail.append(RECON_MISSING_SAFETY_FACT if facts is None else RECON_MALFORMED_FACTS)
    elif not fail:
        try:
            fail += _facts_errors(assessment, facts)
        except Exception:  # noqa: BLE001 - malformed facts must never escape as success
            fail.append(RECON_MALFORMED_FACTS)
    if fail:
        return _result(FAIL_CLOSED, fail, assessment=assessment, facts=facts if facts_ok else None)

    human = []
    if not assessment.candidate.merge_bases:
        human.append(RECON_UNRELATED_HISTORIES)
    elif len(assessment.candidate.merge_bases) > 1:
        human.append(RECON_MULTIPLE_MERGE_BASES)
    findings = _path_analysis(facts)
    for finding in findings:
        if finding.outcome == PATH_HUMAN_REQUIRED:
            human.extend(finding.reason_codes)
    semantic = [code for fd in findings if fd.outcome == PATH_OVERLAPPING_HUNKS for code in fd.reason_codes]
    if human:
        return _result(HUMAN_REQUIRED, human + semantic, assessment=assessment, facts=facts, findings=findings)
    if semantic:
        return _result(SEMANTIC_REVIEW_REQUIRED, semantic, assessment=assessment, facts=facts, findings=findings)

    proven = [RECON_NO_TEXTUAL_CONFLICT]
    outcomes = {fd.outcome for fd in findings}
    if outcomes & {PATH_HEAD_ONLY, PATH_BASE_ONLY}:
        proven.append(RECON_DISJOINT_PATHS)
    if PATH_DISJOINT_HUNKS in outcomes:
        proven.append(RECON_DISJOINT_HUNKS)
    if PATH_CONVERGENT in outcomes:
        proven.append(RECON_CONVERGENT_CHANGES)
    return _result(NO_TEXTUAL_CONFLICT, proven, assessment=assessment, facts=facts, findings=findings)


# ---------------------------------------------------------------------------
# Read-only analysis
# ---------------------------------------------------------------------------

def analyze_reconciliation(
    worktree, *, attested_sha: Optional[str], authorized_scopes, expected_remote_url: Optional[str] = None,
    evidence=None, ledger_root=None, lease_root=None, max_paths: int = MAX_PATHS,
) -> ReconciliationAnalysis:
    """Read-only reconciliation analysis of `worktree`: FCP-1 assessment,
    SHA-addressed diff reads, FCP-1 re-assessment, pure classification.
    Only an invalid `max_paths` is refused (ReconciliationInputError) before
    anything is read; every other problem is a FAIL_CLOSED result."""
    if not _is_int(max_paths, 1) or max_paths > MAX_PATHS:
        raise ReconciliationInputError(f"max_paths must be an int in 1..{MAX_PATHS}")
    inputs = dict(attested_sha=attested_sha, authorized_scopes=authorized_scopes,
                  expected_remote_url=expected_remote_url, evidence=evidence, ledger_root=ledger_root,
                  lease_root=lease_root)
    try:
        first = ri.assess_integration(worktree, **inputs)
    except Exception as exc:  # noqa: BLE001 - e.g. an unencodable path in FCP-1's fingerprint
        return classify_reconciliation(None, ReconciliationFacts(
            read_errors=((RECON_ASSESSMENT_FAILED, f"{type(exc).__name__}: {exc}"),), max_paths=max_paths))
    if first.classification not in RECONCILABLE_FCP1_CLASSIFICATIONS:
        return classify_reconciliation(first, None)

    facts = _read_facts(worktree, first, max_paths)
    try:
        second = ri.assess_integration(worktree, **inputs)
        facts = dataclasses.replace(facts, reassessment_fingerprint=second.fingerprint,
                                    reassessment_classification=second.classification)
    except Exception as exc:  # noqa: BLE001
        facts = dataclasses.replace(
            facts, read_errors=facts.read_errors + ((RECON_ASSESSMENT_FAILED, f"{type(exc).__name__}: {exc}"),))
    return classify_reconciliation(first, facts)


# ---------------------------------------------------------------------------
# Plans (pure)
# ---------------------------------------------------------------------------

def _analysis_errors(analysis) -> list:
    if type(analysis) is not ReconciliationAnalysis:
        return [PLAN_INVALID_INPUT]
    errors = []
    try:
        if analysis.fingerprint != _digest(_analysis_payload(analysis)):
            errors.append(PLAN_ANALYSIS_INVALID)
    except Exception:  # noqa: BLE001
        errors.append(PLAN_ANALYSIS_INVALID)
    if analysis.human_approval_required is not True or analysis.authorizes_action is not False \
            or analysis.classification not in RECONCILIATION_PRECEDENCE or analysis.schema != ANALYSIS_SCHEMA:
        errors.append(PLAN_ANALYSIS_INVALID)
    a = analysis.assessment
    if a is not None and (not isinstance(a, ri.IntegrationAssessment) or a.fingerprint != analysis.assessment_fingerprint
                          or _fcp1_fingerprint(a) != a.fingerprint):
        errors.append(PLAN_ANALYSIS_INVALID)
    return errors


def _scope_ok(scope, authorized_scopes) -> bool:
    return bool(authorized_scopes) and all(
        isinstance(p, str) and claude_runner.path_is_authorized(p, list(authorized_scopes)) for p in scope)


def _acceptance_commands(commands) -> tuple:
    if not isinstance(commands, (list, tuple)) or not commands:
        raise ReconciliationInputError("acceptance_commands must be a non-empty list of host-provided commands")
    for command in commands:
        if not isinstance(command, str) or not command.strip() or any(ch in command for ch in "\0\r\n"):
            raise ReconciliationInputError(f"invalid acceptance command: {command!r}")
    if len(set(commands)) != len(commands):
        raise ReconciliationInputError("duplicate acceptance commands")
    return tuple(commands)


def propose_reconciliation_plan(analysis, *, acceptance_commands) -> Optional[ReconciliationPlan]:
    """A PROPOSED plan for a NO_TEXTUAL_CONFLICT or SEMANTIC_REVIEW_REQUIRED
    analysis, else None. Refuses (ReconciliationInputError) an invalid or
    tampered analysis and missing/invalid acceptance commands; the commands
    are kept verbatim and never run, and no test is ever invented."""
    if _analysis_errors(analysis):
        raise ReconciliationInputError("analysis is not a valid, untampered ReconciliationAnalysis")
    commands = _acceptance_commands(acceptance_commands)
    if analysis.classification not in PLANNABLE_CLASSIFICATIONS:
        return None
    if not _scope_ok(analysis.scope, analysis.authorized_scopes):
        raise ReconciliationInputError("analysis scope is not within its assessed authorized scope")
    review = tuple(fd.path for fd in analysis.path_findings if fd.outcome == PATH_OVERLAPPING_HUNKS)
    steps = (STEP_HUMAN_REVIEW_ANALYSIS,)
    if review:
        steps += (STEP_HUMAN_SEMANTIC_REVIEW,)
    steps += (STEP_HUMAN_APPROVE_MECHANISM, STEP_REVALIDATE_PLAN, STEP_RUN_ACCEPTANCE,
              STEP_SEMANTIC_VALIDATION, STEP_REASSESS_FCP1)
    draft = ReconciliationPlan(
        status=PLAN_PROPOSED, fingerprint="", analysis_fingerprint=analysis.fingerprint,
        assessment_fingerprint=analysis.assessment_fingerprint, classification=analysis.classification,
        worktree_key=analysis.worktree_key, head_ref=analysis.head_ref, head_sha=analysis.head_sha,
        base_sha=analysis.base_sha, merge_bases=analysis.merge_bases, scope=analysis.scope,
        authorized_scopes=analysis.authorized_scopes, review_paths=review, acceptance_commands=commands,
        steps=steps, reason_codes=analysis.reason_codes,
    )
    return dataclasses.replace(draft, fingerprint=_digest(_plan_payload(draft)))


def validate_reconciliation_plan(plan, fresh_analysis) -> PlanValidation:
    """Re-checks a plan against a FRESH analysis: plan integrity, status,
    classification, facts (analysis fingerprint), assessment, HEAD, base,
    merge base, worktree and scope. Never raises; `valid` grants nothing."""
    if type(plan) is not ReconciliationPlan:
        return PlanValidation(valid=False, reason_codes=(PLAN_INVALID_INPUT,))
    reasons = []
    try:
        if plan.fingerprint != _digest(_plan_payload(plan)):
            reasons.append(PLAN_TAMPERED)
    except Exception:  # noqa: BLE001
        reasons.append(PLAN_TAMPERED)
    if plan.status != PLAN_PROPOSED or plan.schema != PLAN_SCHEMA:
        reasons.append(PLAN_NOT_PROPOSED)
    if plan.authorizes_action is not False or plan.human_approval_required is not True:
        reasons.append(PLAN_AUTHORIZATION_CLAIMED)
    analysis_errors = _analysis_errors(fresh_analysis)
    if analysis_errors:
        reasons.extend(analysis_errors)
        return PlanValidation(valid=False, reason_codes=tuple(dict.fromkeys(reasons)),
                              plan_fingerprint=plan.fingerprint)
    fresh = fresh_analysis
    if fresh.classification not in PLANNABLE_CLASSIFICATIONS:
        reasons.append(PLAN_ANALYSIS_NOT_PLANNABLE)
    if fresh.classification != plan.classification:
        reasons.append(PLAN_CLASSIFICATION_CHANGED)
    if fresh.head_sha != plan.head_sha or fresh.head_ref != plan.head_ref:
        reasons.append(PLAN_HEAD_CHANGED)
    if fresh.base_sha != plan.base_sha:
        reasons.append(PLAN_BASE_CHANGED)
    if fresh.merge_bases != plan.merge_bases:
        reasons.append(PLAN_MERGE_BASE_CHANGED)
    if fresh.worktree_key != plan.worktree_key:
        reasons.append(PLAN_WORKTREE_CHANGED)
    if fresh.assessment_fingerprint != plan.assessment_fingerprint:
        reasons.append(PLAN_ASSESSMENT_CHANGED)
    if fresh.fingerprint != plan.analysis_fingerprint:
        reasons.append(PLAN_FACTS_CHANGED)
    if plan.scope != fresh.scope or plan.authorized_scopes != fresh.authorized_scopes \
            or not _scope_ok(plan.scope, fresh.authorized_scopes):
        reasons.append(PLAN_SCOPE_VIOLATION)
    return PlanValidation(valid=not reasons, reason_codes=tuple(dict.fromkeys(reasons)),
                          plan_fingerprint=plan.fingerprint, analysis_fingerprint=fresh.fingerprint)
