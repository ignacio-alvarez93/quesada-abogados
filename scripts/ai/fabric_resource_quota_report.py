"""FCP-10D-01: Resource / Quota Manager consultative report and CLI -
read-only, deterministic, fail-closed, provider-neutral, NON-AUTHORITATIVE.

    python -m scripts.ai.fabric_resource_quota_report --input-file FILE \
        [--format json|text]

Answers ONE question: given ONE JSON document of quota / availability
observations (and, optionally, declared budgets with their receipts, tariffs
and an advisory reservation) that the operator ALREADY holds, what do the
existing FCP-10 engines say about each provider's quota, the reserved
capacity, the budgets, the decisions and their reasons, the blocking risk and
the next safe step, and which actions remain NOT authorized? It never answers
"may I dispatch / retry / resume / switch / buy now?".

Why this is a report, not a manager
-----------------------------------
* Director and Runner stay the ONLY execution and Git authorities. This CLI
  reads one explicit file and prints; it has no cron, daemon, server, socket,
  shell, process, Git, clock, environment or configuration write, and no
  pool, lease, ledger or store of its own. The instant is the document's
  explicit `as_of_utc`.
* Composition, not duplication. The document is mapped verbatim onto the
  native types the engines already consume, and every decision is theirs:
  - each record becomes an FCP-10A-02 `SourceRecord` whose payload is the
    source's own native type (`rt.ProviderFacts`,
    `cap.ProviderCapacityFacts`, `availability.ProviderClassification`, or a
    Runner `worker.json` loaded by `runner_pipeline.WorkerRuntime.from_dict`);
    a payload that cannot be built is handed over as None, so A02 itself
    rejects the record (fail closed, never dropped);
  - `adapt_observations` gives the quota per provider;
  - FCP-10C-02 `advise_recovery` over that same A02 request (no workers, no
    composite) gives each provider's recovery status, actor and action;
  - the optional budget section becomes an FCP-10B-02 `BudgetRequest`
    evaluated by `evaluate_budget` (money only as exact decimal STRINGS).
  The engines are imported lazily (on the first report), so usage errors and
  `--help` load none of them.
* Status (`STATUSES`, most severe first): BLOCKED > UNKNOWN > WAITING >
  CLEAR. Provider decisions are C02's own status; rejected or unattributed
  A02 evidence, and uncertain A02 evidence (e.g. CAPACITY_UNKNOWN) of a
  provider C02 would call CLEAR, add a QUOTA_EVIDENCE decision UNKNOWN
  (HUMAN_OPERATOR / REVIEW_QUOTA_EVIDENCE); a budget verdict maps REFUSE ->
  BLOCKED (DIRECTION / REQUEST_DIRECTION), UNKNOWN -> UNKNOWN
  (HUMAN_OPERATOR / REVIEW_QUOTA_EVIDENCE), WAIT -> WAITING (DIRECTION /
  REQUEST_DIRECTION), READY -> CLEAR. CLEAR needs cited evidence; nothing is upgraded:
  AUTH_BLOCKED / QUOTA_WAIT / UNKNOWN stay held and their evidence ids are
  echoed.

Admissible input (verified on the opened descriptor before any read)
-------------------------------------------------------------------
`--input-file` must be absolute, local (no UNC, device, `//` or URL form), a
drive path on Windows, without `..`, NUL or stream (`:`) components, and an
existing regular non-link file of at most `MAX_INPUT_BYTES` whose real path
is itself (no link, junction or 8.3 alias anywhere on it). Its identity is
snapshotted before the name is resolved and the opened descriptor must be that
same object; on Windows the final path of the open handle must be the
approved physical path, on POSIX no component is followed (O_NOFOLLOW walk);
all before any byte is read. The bytes must be strict UTF-8 JSON (no BOM, no
duplicate key, no NaN / Infinity, bounded finite numbers, depth and
strings, no lone surrogate; money only as decimal strings) with exactly the documented keys.

Output and exit codes
---------------------
Stdout is one compact canonical JSON report (schema `SCHEMA`, sorted keys,
ASCII) whose `report_sha256` is the sha256 of the canonical report without
that field, holding only validated ids, enumerated codes, normalized UTC
instants, integers, decimal strings and the engines' own fingerprints - a
stable shape for later consumers (FCP-11). `--format text` prints the same
facts as token lines. No path, provider prose, raw input, exception text or
secret is ever printed. Refusals go to stderr only as
`error: REPORT_<CODE>: <fixed text> [codes=...]`.

0 = CLEAR; 3 = WAITING; 4 = UNKNOWN; 5 = BLOCKED; 1 = refused (nothing on
stdout); 2 = usage error. Every exit is ADVISORY: none certifies, authorizes
or dispatches anything.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import os
import re
import stat
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

# Same deterministic repository-root bootstrap as `fabric_scheduler_cli`.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

INPUT_SCHEMA = "fcp10d01-resource-quota-report-input-v1"
INPUT_SCHEMA_VERSION = 1
SCHEMA = "fcp10d01-resource-quota-report-v1"
SCHEMA_VERSION = 1
REPORT_MARKER = "FCP10D01_QUOTA_REPORT_ADVISORY_ONLY_READ_ONLY_NOT_CERTIFIED_NOT_AUTHORIZED"

MAX_INPUT_BYTES = 262144
MAX_REPORT_BYTES = 1048576
MAX_JSON_DEPTH = 12
MAX_INT_DIGITS = 19
MAX_FLOAT_CHARS = 32
MAX_STRING_CHARS = 4096

FORMAT_JSON = "json"
FORMAT_TEXT = "text"

BLOCKED = "BLOCKED"
UNKNOWN = "UNKNOWN"
WAITING = "WAITING"
CLEAR = "CLEAR"
STATUSES = (BLOCKED, UNKNOWN, WAITING, CLEAR)  # most severe first

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_USAGE = 2
EXIT_WAITING = 3
EXIT_UNKNOWN = 4
EXIT_BLOCKED = 5
EXIT_OF_STATUS = {CLEAR: EXIT_OK, WAITING: EXIT_WAITING, UNKNOWN: EXIT_UNKNOWN, BLOCKED: EXIT_BLOCKED}

SUBJECT_PROVIDER = "PROVIDER"
SUBJECT_QUOTA_EVIDENCE = "QUOTA_EVIDENCE"
SUBJECT_BUDGET = "BUDGET"
SUBJECT_BUDGET_LIMIT = "BUDGET_LIMIT"
SUBJECTS = (SUBJECT_PROVIDER, SUBJECT_QUOTA_EVIDENCE, SUBJECT_BUDGET, SUBJECT_BUDGET_LIMIT)

# Report-level actor / action of a budget verdict and of doubtful A02
# evidence; the C02 vocabulary, never a new action.
ACTOR_HUMAN = "HUMAN_OPERATOR"
ACTOR_DIRECTION = "DIRECTION"
ACTOR_NONE = "NONE"
REVIEW_QUOTA_EVIDENCE = "REVIEW_QUOTA_EVIDENCE"
REQUEST_DIRECTION = "REQUEST_DIRECTION"
NO_ACTION = "NO_ACTION"
EVIDENCE_REJECTED = "EVIDENCE_REJECTED"
_BUDGET_RULES = {
    "REFUSE": (BLOCKED, ACTOR_DIRECTION, REQUEST_DIRECTION),
    "UNKNOWN": (UNKNOWN, ACTOR_HUMAN, REVIEW_QUOTA_EVIDENCE),
    "WAIT": (WAITING, ACTOR_DIRECTION, REQUEST_DIRECTION),
    "READY": (CLEAR, ACTOR_NONE, NO_ACTION),
}

# Never authorized by this report, whatever its status.
NOT_AUTHORIZED_ACTIONS = (
    "DISPATCH", "RETRY", "RESUME", "PROVIDER_SWITCH", "FALLBACK_PROPOSAL", "RESERVATION_HOLD", "LIMIT_RAISE",
    "PURCHASE", "SUBSCRIPTION", "REMOTE_API_CALL", "PROCESS_EXECUTION", "SHELL_EXECUTION", "GIT_OPERATION",
    "COMMIT", "CHECKPOINT_CONSOLIDATION", "PUSH", "MERGE", "CONFIG_WRITE", "LEDGER_WRITE", "VERDICT_UPGRADE",
)
AUTHORITY = {
    "role": "CONSULTATIVE_QUOTA_REPORTER", "launcher": False, "execution_authority": "RUNNER",
    "director_authority": "FABRIC_DIRECTOR",
}
AUTHORITY_FLAGS = (
    "certified", "authorizes_action", "execution_allowed", "dispatch_allowed", "auto_retry_allowed",
    "resume_allowed", "merging_allowed", "provider_switch_authorized", "reservation_held", "quota_authority",
    "purchase_allowed", "remote_api_allowed", "state_mutated", "retry_scheduled", "resume_from_derived",
    "commit_created", "history_rewritten", "checkpoint_consolidated", "verdict_upgraded", "charge_made",
    "provider_api_called", "ledger_written", "network_used", "process_started", "file_written",
)

_TOP_REQUIRED = frozenset({"schema", "schema_version", "request_id", "as_of_utc", "records"})
_TOP_OPTIONAL = frozenset({"max_evidence_age_seconds", "provider_ids", "deadline_utc", "budget"})
_RECORD_REQUIRED = frozenset({"evidence_id", "source", "provider_id", "payload"})
_RECORD_OPTIONAL = frozenset({"observed_at_utc"})
_BUDGET_REQUIRED = frozenset({"policy"})
_BUDGET_OPTIONAL = frozenset({"executions", "receipts", "tariffs", "reservation"})
_POLICY_KEYS = frozenset({"policy_id", "currency", "granularity", "limits"})
_LIMIT_REQUIRED = frozenset({"limit_id", "scope", "unit", "maximum"})
_LIMIT_OPTIONAL = frozenset({"window", "provider_id", "resource_id"})
_WINDOW_REQUIRED = frozenset({"kind", "duration_seconds"})
_WINDOW_OPTIONAL = frozenset({"anchor_utc"})
_EXECUTION_REQUIRED = frozenset({"execution_id", "provider_id", "incurred_at_utc"})
_EXECUTION_OPTIONAL = frozenset({"resource_id"})
_RECEIPT_KEYS = frozenset({"receipt_id", "execution_id", "basis", "reliability", "recorded_at_utc", "quantities"})
_QUANTITY_KEYS = frozenset({"unit", "minimum", "maximum"})
_TARIFF_REQUIRED = frozenset({"tariff_id", "provider_id", "unit", "rate", "per_quantity", "currency",
                              "effective_from_utc"})
_TARIFF_OPTIONAL = frozenset({"effective_until_utc"})
_RESERVATION_REQUIRED = frozenset({"reservation_id", "provider_id", "amounts"})
_RESERVATION_OPTIONAL = frozenset({"resource_id"})
_CLASSIFICATION_KEYS = frozenset({"condition", "reason", "http_status", "terminal_reason", "reset_hint",
                                  "message_excerpt"})
_COST_UNIT = "COST"

_DECIMAL_RE = re.compile(r"(0|[1-9][0-9]{0,12})(\.[0-9]{1,18})?")
_DRIVE_RE = re.compile(r"[A-Za-z]:")
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)

_REFUSAL_MESSAGES = {
    "REPORT_PATH_NOT_ADMISSIBLE": "--input-file must be an absolute local path without '..', NUL or streams",
    "REPORT_PATH_NETWORK_REFUSED": "network, device and URL paths are refused",
    "REPORT_PATH_LINK_REFUSED": "a symlink, junction or reparse point was found on --input-file",
    "REPORT_INPUT_FILE_INVALID": "--input-file must be an existing regular file",
    "REPORT_INPUT_TOO_LARGE": "--input-file exceeds the size limit",
    "REPORT_INPUT_NOT_UTF8": "the input is not strict UTF-8 without BOM",
    "REPORT_INPUT_JSON_INVALID": "the input is not strict JSON",
    "REPORT_INPUT_DUPLICATE_KEY": "the input repeats a JSON object key",
    "REPORT_INPUT_NUMBER_FORBIDDEN": "NaN, Infinity and oversized numbers are refused",
    "REPORT_INPUT_TOO_DEEP": "the input nests too deeply",
    "REPORT_INPUT_STRING_INVALID": "the input holds an oversized string or a lone surrogate",
    "REPORT_INPUT_SCHEMA_UNSUPPORTED": "the input schema or schema_version is not supported",
    "REPORT_INPUT_FIELD_UNKNOWN": "the input holds an undocumented key",
    "REPORT_INPUT_FIELD_MISSING": "the input lacks a required key",
    "REPORT_INPUT_SHAPE_INVALID": "an input section has the wrong JSON type",
    "REPORT_QUOTA_REFUSED": "the quota observation request was refused",
    "REPORT_RECOVERY_REFUSED": "the quota recovery request was refused",
    "REPORT_BUDGET_REFUSED": "the budget request was refused",
    "REPORT_OUTPUT_TOO_LARGE": "the report exceeds the size limit",
    "REPORT_INTERNAL_ERROR": "the report could not be produced",
}


class ReportError(Exception):
    """Refusal to report. `code` and `message` are fixed text; `codes` holds
    only engine-enumerated tokens. Never a path, id, value or OS message."""

    def __init__(self, code: str, codes: tuple = ()):
        super().__init__(code)
        self.code = code
        self.message = _REFUSAL_MESSAGES[code]
        self.codes = tuple(codes)

    def render(self) -> str:
        suffix = f" [codes={','.join(self.codes)}]" if self.codes else ""
        return f"error: {self.code}: {self.message}{suffix}"


# ---------------------------------------------------------------------------
# Lazy engine import
# ---------------------------------------------------------------------------
_ENGINES = None


def engines() -> SimpleNamespace:
    """The existing engines, imported on first use only."""
    global _ENGINES
    if _ENGINES is None:
        from scripts.ai import fabric_provider_routing_policy as rt
        from scripts.ai import fabric_resource_quota_budget as bg
        from scripts.ai import fabric_resource_quota_contract as qc
        from scripts.ai import fabric_resource_quota_observation as qo
        from scripts.ai import fabric_resource_quota_recovery as rq
        from scripts.ai import fabric_scheduler_capacity as cap
        from scripts.ai import fabric_scheduler_contract as sc
        from scripts.ai import runner_pipeline as pipeline
        from scripts.ai import runner_provider_availability as availability
        _ENGINES = SimpleNamespace(rt=rt, bg=bg, qc=qc, qo=qo, rq=rq, cap=cap, sc=sc, pipeline=pipeline,
                                   availability=availability)
    return _ENGINES


# ---------------------------------------------------------------------------
# Path admission (nothing is created; the opened object itself is verified)
# ---------------------------------------------------------------------------
def _classify(st_) -> str:
    if stat.S_ISLNK(st_.st_mode) or (getattr(st_, "st_file_attributes", 0) or 0) & _REPARSE_POINT:
        return "LINK"
    if stat.S_ISDIR(st_.st_mode):
        return "DIR"
    return "FILE" if stat.S_ISREG(st_.st_mode) else "OTHER"


def _kind(path: str) -> Optional[str]:
    """DIR, FILE, LINK, OTHER, or None when absent / not inspectable."""
    try:
        return _classify(os.lstat(path))
    except (OSError, ValueError):
        return None


def admit_path(path) -> str:
    """The operator's path, only when it is an absolute, local, plain one."""
    if not isinstance(path, str) or not path or "\x00" in path:
        raise ReportError("REPORT_PATH_NOT_ADMISSIBLE")
    if "://" in path or path[:2] in ("\\\\", "//", "\\/", "/\\"):
        raise ReportError("REPORT_PATH_NETWORK_REFUSED")
    if os.name == "nt":
        drive, rest = os.path.splitdrive(path)
        if not _DRIVE_RE.fullmatch(drive) or rest[:1] not in ("\\", "/") or ":" in rest:
            raise ReportError("REPORT_PATH_NOT_ADMISSIBLE")
    elif not path.startswith("/"):
        raise ReportError("REPORT_PATH_NOT_ADMISSIBLE")
    if not os.path.isabs(path) or ".." in Path(path).parts:
        raise ReportError("REPORT_PATH_NOT_ADMISSIBLE")
    return path


def same_physical_path(final, approved) -> bool:
    """True only when `final` (a Windows handle's final path, `\\\\?\\X:\\...`
    or `X:\\...`) is a plain local drive path naming the same file as the
    approved spelling, compared case-insensitively. A UNC, device, volume-GUID
    or stream form never matches. Pure string comparison: nothing is resolved."""
    import ntpath
    if type(final) is not str or type(approved) is not str or "\x00" in final or "/" in final:
        return False
    if final.startswith("\\\\?\\"):
        final = final[4:]
    drive, rest = ntpath.splitdrive(final)
    if not _DRIVE_RE.fullmatch(drive) or rest[:1] != "\\" or ":" in rest or ntpath.normpath(final) != final:
        return False
    return ntpath.normcase(final) == ntpath.normcase(ntpath.normpath(approved))


def _handle_final_path(descriptor) -> str:
    """The final physical path of the object behind an open descriptor, from
    the OS (`GetFinalPathNameByHandleW` on its handle), never by name."""
    import ctypes
    import msvcrt
    from ctypes import wintypes
    getter = ctypes.WinDLL("kernel32", use_last_error=True).GetFinalPathNameByHandleW
    getter.argtypes = (wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD)
    getter.restype = wintypes.DWORD
    buffer = ctypes.create_unicode_buffer(32768)
    length = getter(msvcrt.get_osfhandle(descriptor), buffer, len(buffer), 0)  # NORMALIZED | VOLUME_NAME_DOS
    if not 0 < length < len(buffer):
        raise OSError("final path unavailable")
    return buffer.value


def _open_without_links(path: str, flags: int) -> int:
    """POSIX: open `path` one component at a time from `/`, each relative to
    the directory already held and with O_NOFOLLOW, so no symlink anywhere on
    it is ever followed. Unavailable primitives refuse (fail closed)."""
    nofollow, directory = getattr(os, "O_NOFOLLOW", 0), getattr(os, "O_DIRECTORY", 0)
    if not nofollow or not directory or os.open not in os.supports_dir_fd:
        raise ReportError("REPORT_INPUT_FILE_INVALID")
    parts = os.path.normpath(path).split("/")[1:]
    parent = os.open("/", os.O_RDONLY | directory)
    try:
        for index, name in enumerate(parts):
            last = index == len(parts) - 1
            try:
                child = os.open(name, (flags if last else os.O_RDONLY | directory) | nofollow, dir_fd=parent)
            except OSError:
                if stat.S_ISLNK(os.lstat(name, dir_fd=parent).st_mode):
                    raise ReportError("REPORT_PATH_LINK_REFUSED") from None
                raise
            if last:
                return child
            os.close(parent)
            parent = child
        raise ReportError("REPORT_INPUT_FILE_INVALID")
    finally:
        os.close(parent)


def read_input_bytes(path) -> bytes:
    """Bounded read of one regular, non-link file whose real path is itself.

    TOCTOU: the identity snapshot (lstat) is taken FIRST, before the name is
    resolved; the descriptor actually opened must then be that same regular,
    non-reparse object (dev / ino) within the size limit. On Windows its final
    path is read from the open HANDLE and must be the approved physical path,
    so a parent directory swapped for a junction between check and open is
    refused even if the identity were made to match; on POSIX every component
    is opened relative to the held parent with O_NOFOLLOW. All of this happens
    before the first byte is read, and the descriptor is always closed.
    Limit: what is proven is the object actually opened and its final path at
    verification; not that no reparse point ever existed during the window."""
    admit_path(path)
    try:
        before = os.lstat(path)
    except (OSError, ValueError):
        raise ReportError("REPORT_INPUT_FILE_INVALID") from None
    found = _classify(before)
    if found == "LINK":
        raise ReportError("REPORT_PATH_LINK_REFUSED")
    if found != "FILE":
        raise ReportError("REPORT_INPUT_FILE_INVALID")
    if before.st_size > MAX_INPUT_BYTES:
        raise ReportError("REPORT_INPUT_TOO_LARGE")
    try:
        real = os.path.realpath(path)
    except (OSError, ValueError):
        raise ReportError("REPORT_INPUT_FILE_INVALID") from None
    if os.path.normcase(real) != os.path.normcase(os.path.normpath(path)):
        raise ReportError("REPORT_PATH_LINK_REFUSED")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags) if os.name == "nt" else _open_without_links(path, flags)
        try:
            opened = os.fstat(descriptor)
            if _classify(opened) != "FILE" or not before.st_ino \
                    or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                raise ReportError("REPORT_PATH_LINK_REFUSED")
            if opened.st_size > MAX_INPUT_BYTES:
                raise ReportError("REPORT_INPUT_TOO_LARGE")
            if os.name == "nt":
                try:
                    final = _handle_final_path(descriptor)
                except Exception:  # noqa: BLE001 - an unprovable binding is refused
                    raise ReportError("REPORT_INPUT_FILE_INVALID") from None
                if not same_physical_path(final, path):
                    raise ReportError("REPORT_PATH_LINK_REFUSED")
            chunks, size = [], 0
            while size <= MAX_INPUT_BYTES:
                chunk = os.read(descriptor, MAX_INPUT_BYTES + 1 - size)
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
        finally:
            os.close(descriptor)
    except OSError:
        raise ReportError("REPORT_INPUT_FILE_INVALID") from None
    data = b"".join(chunks)
    if len(data) > MAX_INPUT_BYTES:
        raise ReportError("REPORT_INPUT_TOO_LARGE")
    return data


# ---------------------------------------------------------------------------
# Strict JSON
# ---------------------------------------------------------------------------
class _Refuse(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _pairs_hook(pairs):
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        raise _Refuse("REPORT_INPUT_DUPLICATE_KEY")
    return dict(pairs)


def _no_constant(_text):
    raise _Refuse("REPORT_INPUT_NUMBER_FORBIDDEN")


def _bounded_float(text):
    """A finite, short JSON float (the Runner's own worker.json carries
    `backoff_seconds`); no engine accepts a float where it needs an int or a
    Decimal, so money must be a decimal STRING."""
    value = float(text) if len(text) <= MAX_FLOAT_CHARS else math.inf
    if not math.isfinite(value):
        raise _Refuse("REPORT_INPUT_NUMBER_FORBIDDEN")
    return value


def _bounded_int(text):
    if len(text.lstrip("-")) > MAX_INT_DIGITS:
        raise _Refuse("REPORT_INPUT_NUMBER_FORBIDDEN")
    return int(text)


def _check_tree(value) -> None:
    """Iterative depth / string check of the parsed document."""
    stack = [(value, 1)]
    while stack:
        node, depth = stack.pop()
        if depth > MAX_JSON_DEPTH:
            raise ReportError("REPORT_INPUT_TOO_DEEP")
        if isinstance(node, dict):
            for key, item in node.items():
                _check_string(key)
                stack.append((item, depth + 1))
        elif isinstance(node, list):
            stack.extend((item, depth + 1) for item in node)
        elif isinstance(node, str):
            _check_string(node)


def _check_string(text: str) -> None:
    if len(text) > MAX_STRING_CHARS or any("\ud800" <= c <= "\udfff" for c in text):
        raise ReportError("REPORT_INPUT_STRING_INVALID")


def parse_document(data: bytes):
    """Strict UTF-8 JSON: no BOM, duplicate key, NaN / Infinity, non-finite
    or oversized number or string, lone surrogate or excessive depth."""
    if type(data) is not bytes:
        raise ReportError("REPORT_INPUT_JSON_INVALID")
    if data.startswith(b"\xef\xbb\xbf"):
        raise ReportError("REPORT_INPUT_NOT_UTF8")
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise ReportError("REPORT_INPUT_NOT_UTF8") from None
    try:
        document = json.loads(text, object_pairs_hook=_pairs_hook, parse_float=_bounded_float, parse_int=_bounded_int,
                              parse_constant=_no_constant)
    except _Refuse as exc:
        raise ReportError(exc.code) from None
    except RecursionError:
        raise ReportError("REPORT_INPUT_TOO_DEEP") from None
    except (ValueError, TypeError):
        raise ReportError("REPORT_INPUT_JSON_INVALID") from None
    _check_tree(document)
    return document


# ---------------------------------------------------------------------------
# Document -> native engine types
# ---------------------------------------------------------------------------
def _object(value, required: frozenset, optional: frozenset = frozenset()) -> dict:
    if type(value) is not dict:
        raise ReportError("REPORT_INPUT_SHAPE_INVALID")
    keys = set(value)
    if keys - required - optional:
        raise ReportError("REPORT_INPUT_FIELD_UNKNOWN")
    if required - keys:
        raise ReportError("REPORT_INPUT_FIELD_MISSING")
    return value


def _array(value) -> list:
    if type(value) is not list:
        raise ReportError("REPORT_INPUT_SHAPE_INVALID")
    return value


def _tuple(value):
    """A JSON array as the tuple the engines expect; anything else as is (the
    engine refuses it with its own code)."""
    return tuple(value) if type(value) is list else value


def _decimal(value):
    """An exact decimal STRING as Decimal; anything else as is, so the budget
    engine refuses it with its own code (never a float)."""
    if type(value) is str and _DECIMAL_RE.fullmatch(value):
        return Decimal(value)
    return value


def _router_facts(payload):
    rt = engines().rt
    fields = set(rt.ProviderFacts.__dataclass_fields__)
    if type(payload) is not dict or set(payload) != fields:
        return None
    return rt.ProviderFacts(**{k: _tuple(v) for k, v in payload.items()})


def _capacity_facts(payload):
    cap = engines().cap
    fields = cap.ProviderCapacityFacts.__dataclass_fields__
    required = {k for k, f in fields.items() if f.default is dataclasses.MISSING}
    if type(payload) is not dict or not required <= set(payload) <= set(fields):
        return None
    return cap.ProviderCapacityFacts(**payload)


def _classification(payload):
    availability = engines().availability
    if type(payload) is not dict or "condition" not in payload or not set(payload) <= _CLASSIFICATION_KEYS:
        return None
    condition = payload["condition"]
    if type(condition) is not str or condition not in {c.value for c in availability.ProviderCondition}:
        return None
    fields = {k: v for k, v in payload.items() if k != "condition"}
    fields.setdefault("reason", "")
    return availability.ProviderClassification(condition=availability.ProviderCondition(condition), **fields)


def _worker_runtime(payload):
    """The Runner's own `worker.json` loader; prose and paths are carried
    but never read by A02 nor echoed."""
    if type(payload) is not dict or type(payload.get("spec")) is not dict:
        return None
    return engines().pipeline.WorkerRuntime.from_dict(payload)


def native_payload(source, payload):
    """The source's native payload type, or None (A02 then rejects the
    record: PAYLOAD_NOT_TYPED / SOURCE_NOT_ADAPTABLE / SOURCE_UNKNOWN)."""
    qc = engines().qc
    builders = {
        qc.SOURCE_ROUTER_PROVIDER_FACTS: _router_facts,
        qc.SOURCE_SCHEDULER_CAPACITY_FACTS: _capacity_facts,
        qc.SOURCE_RUNNER_PROVIDER_CONDITION: _classification,
        qc.SOURCE_RUNNER_PROVIDER_WAIT: _worker_runtime,
    }
    builder = builders.get(source) if type(source) is str else None
    if builder is None:
        return None
    try:
        return builder(payload)
    except (TypeError, ValueError, KeyError, AttributeError, OverflowError):
        return None


def _source_record(raw):
    qo = engines().qo
    record = _object(raw, _RECORD_REQUIRED, _RECORD_OPTIONAL)
    return qo.SourceRecord(
        evidence_id=record["evidence_id"], source=record["source"], provider_id=record["provider_id"],
        payload=native_payload(record["source"], record["payload"]),
        observed_at_utc=record.get("observed_at_utc"),
    )


def _window(raw):
    if raw is None:
        return None
    window = _object(raw, _WINDOW_REQUIRED, _WINDOW_OPTIONAL)
    return engines().qc.QuotaWindow(kind=window["kind"], duration_seconds=window["duration_seconds"],
                                    anchor_utc=window.get("anchor_utc"))


def _limit(raw):
    e = engines()
    limit = _object(raw, _LIMIT_REQUIRED, _LIMIT_OPTIONAL)
    common = dict(limit_id=limit["limit_id"], scope=limit["scope"], window=_window(limit.get("window")),
                  provider_id=limit.get("provider_id"), resource_id=limit.get("resource_id"))
    if limit["unit"] == _COST_UNIT:
        return e.bg.CostLimit(maximum=_decimal(limit["maximum"]), **common)
    return e.qc.QuotaLimit(unit=limit["unit"], maximum=limit["maximum"], **common)


def _reservation(raw):
    if raw is None:
        return None
    reservation = _object(raw, _RESERVATION_REQUIRED, _RESERVATION_OPTIONAL)
    amounts = reservation["amounts"]
    if type(amounts) is list:
        amounts = tuple(_tuple(pair) for pair in amounts)
    return engines().qc.AdvisoryReservation(
        reservation_id=reservation["reservation_id"], provider_id=reservation["provider_id"], amounts=amounts,
        resource_id=reservation.get("resource_id"))


def budget_request(raw, request_id, as_of):
    """The FCP-10B-02 request of the optional budget section, or None."""
    if raw is None:
        return None
    bg = engines().bg
    section = _object(raw, _BUDGET_REQUIRED, _BUDGET_OPTIONAL)
    policy = _object(section["policy"], _POLICY_KEYS)
    executions = []
    for item in _array(section.get("executions", [])):
        execution = _object(item, _EXECUTION_REQUIRED, _EXECUTION_OPTIONAL)
        executions.append(bg.BudgetExecution(
            execution_id=execution["execution_id"], provider_id=execution["provider_id"],
            incurred_at_utc=execution["incurred_at_utc"], resource_id=execution.get("resource_id")))
    receipts = []
    for item in _array(section.get("receipts", [])):
        receipt = _object(item, _RECEIPT_KEYS)
        quantities = tuple(bg.UsageQuantity(**_object(q, _QUANTITY_KEYS)) for q in _array(receipt["quantities"]))
        receipts.append(bg.UsageReceipt(
            receipt_id=receipt["receipt_id"], execution_id=receipt["execution_id"], basis=receipt["basis"],
            reliability=receipt["reliability"], recorded_at_utc=receipt["recorded_at_utc"], quantities=quantities))
    tariffs = []
    for item in _array(section.get("tariffs", [])):
        tariff = _object(item, _TARIFF_REQUIRED, _TARIFF_OPTIONAL)
        tariffs.append(bg.Tariff(
            tariff_id=tariff["tariff_id"], provider_id=tariff["provider_id"], unit=tariff["unit"],
            rate=_decimal(tariff["rate"]), per_quantity=tariff["per_quantity"], currency=tariff["currency"],
            effective_from_utc=tariff["effective_from_utc"], effective_until_utc=tariff.get("effective_until_utc")))
    return bg.BudgetRequest(
        request_id=request_id, as_of_utc=as_of,
        policy=bg.BudgetPolicy(policy_id=policy["policy_id"], currency=policy["currency"],
                               granularity=_decimal(policy["granularity"]),
                               limits=tuple(_limit(lim) for lim in _array(policy["limits"]))),
        executions=tuple(executions), receipts=tuple(receipts), tariffs=tuple(tariffs),
        reservation=_reservation(section.get("reservation")),
    )


def build_requests(document) -> tuple:
    """(A02 ObservationRequest, C02 RecoveryRequest, B02 BudgetRequest or
    None) of the document; structure is checked here, values by the engines."""
    e = engines()
    top = _object(document, _TOP_REQUIRED, _TOP_OPTIONAL)
    if top["schema"] != INPUT_SCHEMA or type(top["schema_version"]) is not int \
            or top["schema_version"] != INPUT_SCHEMA_VERSION:
        raise ReportError("REPORT_INPUT_SCHEMA_UNSUPPORTED")
    records = tuple(_source_record(r) for r in _array(top["records"]))
    quota_fields = dict(request_id=top["request_id"], as_of_utc=top["as_of_utc"], records=records,
                        provider_ids=_tuple(_array(top.get("provider_ids", []))))
    if "max_evidence_age_seconds" in top:
        quota_fields["max_evidence_age_seconds"] = top["max_evidence_age_seconds"]
    quota = e.qo.ObservationRequest(**quota_fields)
    recovery = e.rq.RecoveryRequest(request_id=top["request_id"], quota_request=quota,
                                    deadline_utc=top.get("deadline_utc"))
    budget = budget_request(top.get("budget"), top["request_id"], top["as_of_utc"])
    return quota, recovery, budget


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def _canonical(payload) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _worst(statuses) -> str:
    return min(statuses, key=STATUSES.index) if statuses else UNKNOWN


def _decision(subject, subject_id, status, actor, action, reasons, evidence_ids=()) -> dict:
    return {"subject": subject, "id": subject_id, "status": status, "actor": actor, "action": action,
            "reasons": list(reasons), "evidence_ids": list(evidence_ids)}


def evaluate(quota_request, recovery_request, budget) -> tuple:
    """Run each engine once: (A02 snapshot, C02 advice, B02 evaluation or
    None). Any engine refusal is a report refusal with its own codes."""
    e = engines()
    snapshot = e.qo.adapt_observations(quota_request)
    if snapshot.request_reasons:
        raise ReportError("REPORT_QUOTA_REFUSED", snapshot.request_reasons)
    advice = e.rq.advise_recovery(recovery_request)
    if advice.request_reasons:
        raise ReportError("REPORT_RECOVERY_REFUSED", advice.request_reasons)
    if advice.quota_snapshot_fingerprint != snapshot.snapshot_fingerprint:
        raise ReportError("REPORT_INTERNAL_ERROR")
    evaluation = None
    if budget is not None:
        evaluation = e.bg.evaluate_budget(budget)
        if evaluation.request_reasons:
            raise ReportError("REPORT_BUDGET_REFUSED", evaluation.request_reasons)
    return snapshot, advice, evaluation


def build_report(snapshot, advice, evaluation) -> dict:
    """The canonical report of the three engine results (no new decision)."""
    e = engines()
    quota_providers = [view.to_dict() for view in snapshot.providers]
    rejected = [{"index": r.index, "reasons": list(r.reasons), "provider_id": r.provider_id,
                 "evidence_id": r.evidence_id} for r in snapshot.records if r.status == e.qo.REJECTED]
    decisions = [_decision(SUBJECT_PROVIDER, p.provider_id, p.status, p.actor, p.action,
                           (p.recovery,) + p.reasons, p.evidence_ids) for p in advice.providers]
    if snapshot.snapshot_reasons or rejected or not advice.providers:
        codes = set(snapshot.snapshot_reasons) | set(advice.reasons) | ({EVIDENCE_REJECTED} if rejected else set())
        decisions.append(_decision(SUBJECT_QUOTA_EVIDENCE, snapshot.request_id, UNKNOWN, ACTOR_HUMAN,
                                   REVIEW_QUOTA_EVIDENCE, sorted(codes)))
    for recovery in advice.providers:
        view = snapshot.provider_view(recovery.provider_id)
        if recovery.status == CLEAR and (view is None or view.certainty != e.qo.CERTAIN):
            codes = () if view is None else tuple(r for r in view.reasons if r in e.qo.UNCERTAIN_REASONS)
            decisions.append(_decision(SUBJECT_QUOTA_EVIDENCE, recovery.provider_id, UNKNOWN, ACTOR_HUMAN,
                                       REVIEW_QUOTA_EVIDENCE, codes or (e.qo.NO_EVIDENCE,), recovery.evidence_ids))
    budget = None
    reserved_accounts = []
    if evaluation is not None:
        status, actor, action = _BUDGET_RULES[evaluation.verdict]
        decisions.append(_decision(SUBJECT_BUDGET, evaluation.request_id, status, actor, action,
                                   evaluation.reasons, evaluation.evidence_ids))
        for account in evaluation.accounts:
            status, actor, action = _BUDGET_RULES[account.verdict]
            decisions.append(_decision(SUBJECT_BUDGET_LIMIT, account.limit_id, status, actor, action,
                                       account.reasons, account.evidence_ids))
        accounts = [account.to_dict() for account in evaluation.accounts]
        budget = {"verdict": evaluation.verdict, "reasons": list(evaluation.reasons),
                  "evidence_ids": list(evaluation.evidence_ids), "currency": evaluation.currency,
                  "granularity": e.bg._money_text(evaluation.granularity), "accounts": accounts}
        reserved_accounts = [
            {k: a[k] for k in ("limit_id", "unit", "maximum", "reservation_in_scope", "reserved", "projected",
                               "remaining")} for a in accounts if a["reservation_in_scope"]]
    status = _worst({d["status"] for d in decisions})
    if status == CLEAR and not advice.evidence_ids:
        status = UNKNOWN
    worst = [d for d in decisions if d["status"] == status]
    report = {
        "schema": SCHEMA, "schema_version": SCHEMA_VERSION, "marker": REPORT_MARKER,
        "request_id": snapshot.request_id, "as_of_utc": snapshot.as_of_utc, "deadline_utc": advice.deadline_utc,
        "status": status,
        "quota": {"outcome": snapshot.outcome, "snapshot_reasons": list(snapshot.snapshot_reasons),
                  "max_evidence_age_seconds": snapshot.max_evidence_age_seconds, "providers": quota_providers,
                  "rejected_records": rejected},
        "reserved_capacity": {
            "proven_slots": [{"provider_id": v["provider_id"], "capacity": v["capacity"],
                              "proven_slots": v["proven_slots"]} for v in quota_providers],
            "budget_reservations": reserved_accounts,
        },
        "budget": budget,
        "decisions": decisions,
        "blocking_risk": {"status": status, **{s.lower(): sorted({f"{d['subject']}:{d['id']}" for d in decisions
                                                                  if d["status"] == s}) for s in STATUSES}},
        "next_safe_step": {"actor": worst[0]["actor"], "action": worst[0]["action"]} if worst else
        {"actor": ACTOR_HUMAN, "action": REVIEW_QUOTA_EVIDENCE},
        "next_safe_steps": sorted({(d["actor"], d["action"]) for d in decisions if d["status"] != CLEAR}),
        "not_authorized_actions": list(NOT_AUTHORIZED_ACTIONS),
        "sources": {
            "quota": {"schema": e.qo.SCHEMA, "fingerprint": snapshot.snapshot_fingerprint,
                      "sha256": _sha(e.qo.canonical_json(snapshot))},
            "recovery": {"schema": e.rq.SCHEMA, "fingerprint": advice.request_fingerprint,
                         "sha256": _sha(e.rq.canonical_json(advice))},
            "budget": None if evaluation is None else {
                "schema": e.bg.SCHEMA, "fingerprint": evaluation.request_fingerprint,
                "sha256": _sha(e.bg.canonical_json(evaluation))},
        },
        "authority": dict(AUTHORITY),
        **dict.fromkeys(AUTHORITY_FLAGS, False),
    }
    report["next_safe_steps"] = [{"actor": a, "action": b} for a, b in report["next_safe_steps"]]
    report["report_sha256"] = _sha(_canonical(report))
    return report


def run_report(input_file) -> dict:
    """Read, parse, map, evaluate once, report. Never writes anything."""
    document = parse_document(read_input_bytes(input_file))
    quota, recovery, budget = build_requests(document)
    return build_report(*evaluate(quota, recovery, budget))


def verify_report(report: dict) -> bool:
    """True when `report_sha256` is the sha256 of the rest of the report."""
    if type(report) is not dict or type(report.get("report_sha256")) is not str:
        return False
    body = {k: v for k, v in report.items() if k != "report_sha256"}
    return _sha(_canonical(body)) == report["report_sha256"]


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def render_json(report: dict) -> str:
    text = _canonical(report)
    if len(text) > MAX_REPORT_BYTES:
        raise ReportError("REPORT_OUTPUT_TOO_LARGE")
    return text


def _text(value) -> str:
    return "-" if value is None else str(value)


def render_text(report: dict) -> str:
    def codes(values):
        return ",".join(values) or "-"

    lines = [
        f"schema: {report['schema']}",
        f"report_sha256: {report['report_sha256']}",
        f"request_id: {report['request_id']}",
        f"as_of_utc: {report['as_of_utc']}",
        f"status: {report['status']}",
        f"quota_outcome: {report['quota']['outcome']}",
    ]
    for p in report["quota"]["providers"]:
        lines.append(f"quota: {p['provider_id']} availability={p['availability']} capacity={p['capacity']} "
                     f"certainty={p['certainty']} next_eligible={p['next_eligible_utc'] or '-'} "
                     f"reasons={codes(p['reasons'])} evidence={codes(p['evidence_ids'])}")
    for r in report["quota"]["rejected_records"]:
        lines.append(f"rejected_record: {r['index']} reasons={codes(r['reasons'])}")
    for s in report["reserved_capacity"]["proven_slots"]:
        lines.append(f"capacity: {s['provider_id']} capacity={s['capacity']} proven_slots={_text(s['proven_slots'])}")
    for a in report["reserved_capacity"]["budget_reservations"]:
        lines.append(f"reserved: {a['limit_id']} unit={a['unit']} reserved={_text(a['reserved'])} "
                     f"projected={_text(a['projected'])} maximum={a['maximum']}")
    if report["budget"] is not None:
        lines.append(f"budget: verdict={report['budget']['verdict']} reasons={codes(report['budget']['reasons'])}")
    for d in report["decisions"]:
        lines.append(f"decision: {d['subject']}:{d['id']} {d['status']} actor={d['actor']} action={d['action']} "
                     f"reasons={codes(d['reasons'])}")
    lines.append(f"blocking_risk: {report['blocking_risk']['status']}")
    lines.append(f"next_safe_step: {report['next_safe_step']['actor']} {report['next_safe_step']['action']}")
    lines.append("not_authorized: " + ",".join(report["not_authorized_actions"]))
    lines.append("authority: ADVISORY ONLY - not certified, not authorized; Director and Runner remain the "
                 "only execution authorities")
    return "\n".join(lines)


def exit_code_for(report) -> int:
    if type(report) is not dict:
        return EXIT_REFUSED
    return EXIT_OF_STATUS.get(report.get("status"), EXIT_REFUSED)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
_USAGE = "error: REPORT_USAGE_INVALID: expected --input-file FILE [--format json|text]\n"


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message):  # never echo argument values (paths, ids)
        self.exit(EXIT_USAGE, _USAGE)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        prog="fabric_resource_quota_report", allow_abbrev=False,
        description="Consultative FCP-10 quota / budget report over one explicit JSON file. Advisory only: "
                    "never dispatches, retries, resumes, switches providers, buys, calls a network or writes.",
    )
    parser.add_argument("--input-file", required=True, help="absolute path of the JSON observation document")
    parser.add_argument("--format", choices=(FORMAT_JSON, FORMAT_TEXT), default=FORMAT_JSON,
                        help="compact canonical JSON (default) or plain token lines")
    return parser


def main(argv: Optional[list] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        report = run_report(args.input_file)
        payload = render_text(report) if args.format == FORMAT_TEXT else render_json(report)
    except ReportError as exc:
        print(exc.render(), file=sys.stderr)
        return EXIT_REFUSED
    except Exception:  # noqa: BLE001 - fail closed without a traceback or leaked bytes
        print(ReportError("REPORT_INTERNAL_ERROR").render(), file=sys.stderr)
        return EXIT_REFUSED
    print(payload)
    return exit_code_for(report)


if __name__ == "__main__":
    sys.exit(main())
