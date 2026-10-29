"""FCP-6C-02: local, read-only CLI that reports EXISTING durable Runner
evidence through the FCP-6A-01 diagnostic and the FCP-6B-01 advisory.

Why this is a reader, not a launcher
------------------------------------
* The Runner (`runner_pipeline.PipelineRunner`) stays the ONLY execution,
  retry, fallback, auth, quota, lease, ownership, `resume_from`, checkpoint,
  Git, promotion and recovery authority; the Director keeps its own. This
  CLI never writes or creates a file or directory, never runs a process or
  shell, never starts the Director, never calls a recovery path and never
  touches Git or the network. Stdlib only, plus the public FCP-6A/FCP-6B
  APIs (`assess_pipeline`, `advise_pipeline`, `to_dict`).
* It does NOT import `runner_pipeline`, `claude_runner`, the Director or any
  provider code, and it reimplements no diagnosis: its only job is the I/O
  boundary in front of the two pure modules.

What it reads
-------------
`python scripts/ai/fabric_recovery_report_cli.py --state-root R --run-id ID`
reads exactly `R/ID/pipeline_result.json` and, for every worker declared in
its `workers` list, the NOMINAL `R/ID/workers/<id>/result.json`. Persisted
paths (`result_path`, `worker_path`, `evidence_dir`, ...) are never opened.
`R/ID/workers/` is listed (names only, never opened) so undeclared worker
directories reach FCP-6A-01 as extra results instead of being dropped.

* `--run-id` and every worker id must be a safe ASCII segment (the Runner's
  `_safe_segment` shape: `[A-Za-z0-9._-]`, 1..64, no leading dot), with no
  trailing dot and no Windows device name. Unsafe, traversal or control
  characters are refused before any path is built; an unsafe DECLARED
  worker id is never opened and FCP-6A-01 reports it as malformed/missing.
* The state root, the run directory, `workers/`, each `workers/<id>/` and
  each file must not be a symlink or Windows reparse point (junction).
  Files must be regular, at most `MAX_JSON_BYTES` (2 MiB, checked before
  decoding), strict UTF-8 without BOM, one JSON document with no repeated
  key and no NaN/Infinity.
* `pipeline_result.json` must be a JSON object whose `pipeline_id` is the
  requested run id. Any failure of the run itself is a non-zero exit with
  `error: REPORT_<CODE>: ...` on stderr and nothing on stdout.
* A worker file that is absent is passed to FCP-6A-01 as None (UNVERIFIED,
  never success). A worker file that is refused (symlink, too large,
  invalid/duplicated JSON, ...) is passed as a non-mapping marker, which
  FCP-6A-01 diagnoses as MALFORMED_EVIDENCE. Either way the report says
  how each declared worker was read in `inputs.workers[*].read`.

What it prints
--------------
Exit 0 means only that a report was produced - for EVERY diagnostic and
advisory, including fail-closed ones - never that anything succeeded or may
be retried. Stdout is one versioned JSON object (`SCHEMA`, sorted keys,
ASCII): the run id, bounded read statuses, `diagnostic` =
`assess_pipeline(...).to_dict()` and `advisory` =
`advise_pipeline(...).to_dict()`. No raw payload, path, message, provider
text or secret is copied. `certified`, `authorizes_action`,
`auto_retry_allowed`, `execution_allowed`, `resume_allowed` and
`merging_allowed` are always false. Errors never echo paths or file bytes.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import stat
import sys
from pathlib import Path
from typing import Optional

# Same deterministic repository-root bootstrap as `fabric_director_cli.py`:
# direct-script execution puts this file's directory first on sys.path.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.ai import runner_failure_intelligence as fi  # noqa: E402
from scripts.ai import runner_recovery_advisory as ra  # noqa: E402

SCHEMA = "fcp6c02-runner-recovery-report-v1"
SCHEMA_VERSION = 1
REPORT_MARKER = "FCP6C02_READ_ONLY_REPORT_NOT_CERTIFIED_NOT_AUTHORIZED"
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_WORKER_ENTRIES = 4096
PIPELINE_RESULT_NAME = "pipeline_result.json"
WORKERS_DIRNAME = "workers"
WORKER_RESULT_NAME = "result.json"
EXIT_REPORT_REFUSED = 1

# Bounded per-worker read statuses (`inputs.workers[*].read`).
READ_OK = "READ"
READ_ABSENT = "ABSENT"
READ_UNSAFE_ID = "UNSAFE_ID"
READ_DUPLICATE_ID = "DUPLICATE_ID"

_UTF8_BOM = b"\xef\xbb\xbf"
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_WINDOWS_DEVICE_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}
)
_AUTHORITY = {
    "role": "READER", "launcher": False, "execution_authority": "RUNNER", "recovery_authority": "DIRECTOR",
}


class ReportError(Exception):
    """Refusal to report a run. `code` and `message` are fixed text: never a
    path, a run id, file bytes or an OS message."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class _ReadRefused(Exception):
    """A single file or directory could not be read safely; `reason` is a
    bounded token (`SYMLINK`, `TOO_LARGE`, `JSON_DUPLICATE_KEY`, ...)."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def safe_segment(value) -> bool:
    """A run/worker id that can name exactly one direct child directory."""
    return (
        isinstance(value, str) and 0 < len(value) <= 64
        and all(c.isascii() and (c.isalnum() or c in "-_.") for c in value)
        and not value.startswith(".") and not value.endswith(".")
        and value.split(".", 1)[0].upper() not in _WINDOWS_DEVICE_NAMES
    )


# ---------------------------------------------------------------------------
# Bounded, no-follow filesystem reads
# ---------------------------------------------------------------------------
def _is_link(st: os.stat_result) -> bool:
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & _REPARSE_POINT)


def _lstat(path: str) -> Optional[os.stat_result]:
    """lstat, or None when the entry does not exist."""
    try:
        return os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError:
        raise _ReadRefused("UNREADABLE") from None


def _check_dir(path: str) -> bool:
    """True for a real directory, False when absent; refuses links/files."""
    st = _lstat(path)
    if st is None:
        return False
    if _is_link(st):
        raise _ReadRefused("SYMLINK")
    if not stat.S_ISDIR(st.st_mode):
        raise _ReadRefused("NOT_DIRECTORY")
    return True


def _read_regular(path: str) -> Optional[bytes]:
    """Bytes of one regular, non-link file of at most MAX_JSON_BYTES, or None
    when absent. The opened handle must be the entry that was lstat-ed."""
    st = _lstat(path)
    if st is None:
        return None
    if _is_link(st):
        raise _ReadRefused("SYMLINK")
    if not stat.S_ISREG(st.st_mode):
        raise _ReadRefused("NOT_REGULAR_FILE")
    if st.st_size > MAX_JSON_BYTES:
        raise _ReadRefused("TOO_LARGE")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        raise _ReadRefused("UNREADABLE") from None
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or (
            st.st_ino and opened.st_ino and (st.st_dev, st.st_ino) != (opened.st_dev, opened.st_ino)
        ):
            raise _ReadRefused("CHANGED_WHILE_READING")
        chunks, total = [], 0
        while total <= MAX_JSON_BYTES:
            chunk = os.read(fd, MAX_JSON_BYTES + 1 - total)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
    except OSError:
        raise _ReadRefused("UNREADABLE") from None
    finally:
        os.close(fd)
    if total > MAX_JSON_BYTES:
        raise _ReadRefused("TOO_LARGE")
    return b"".join(chunks)


def _reject_duplicate_keys(pairs: list) -> dict:
    obj: dict = {}
    for key, value in pairs:
        if key in obj:
            raise _ReadRefused("JSON_DUPLICATE_KEY")
        obj[key] = value
    return obj


def _reject_constant(_name: str):
    raise _ReadRefused("JSON_INVALID")


def _finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise _ReadRefused("JSON_INVALID")
    return value


def _decode_json(data: bytes):
    if data.startswith(_UTF8_BOM):
        raise _ReadRefused("NOT_UTF8")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise _ReadRefused("NOT_UTF8") from None
    try:
        return json.loads(
            text, object_pairs_hook=_reject_duplicate_keys, parse_constant=_reject_constant, parse_float=_finite_float,
        )
    except _ReadRefused:
        raise
    except (ValueError, RecursionError):
        # JSONDecodeError included; its message quotes positions only, but
        # nothing from the document is ever surfaced.
        raise _ReadRefused("JSON_INVALID") from None


# ---------------------------------------------------------------------------
# Run boundary
# ---------------------------------------------------------------------------
def _run_dir(state_root: str, run_id: str) -> str:
    if not safe_segment(run_id):
        raise ReportError("REPORT_RUN_ID_INVALID", "--run-id must be a safe ASCII segment [A-Za-z0-9._-]{1,64}")
    if not isinstance(state_root, str) or not state_root or "\x00" in state_root:
        raise ReportError("REPORT_STATE_ROOT_INVALID", "--state-root must be an existing directory")
    try:
        if not _check_dir(state_root):
            raise ReportError("REPORT_STATE_ROOT_INVALID", "--state-root must be an existing directory")
    except _ReadRefused as exc:
        raise ReportError("REPORT_STATE_ROOT_INVALID", f"--state-root refused ({exc.reason})") from None
    run_dir = os.path.join(state_root, run_id)
    try:
        if not _check_dir(run_dir):
            raise ReportError("REPORT_RUN_NOT_FOUND", "no run directory for --run-id under --state-root")
    except _ReadRefused as exc:
        raise ReportError("REPORT_RUN_DIR_REFUSED", f"run directory refused ({exc.reason})") from None
    return run_dir


def _load_pipeline_result(run_dir: str, run_id: str) -> dict:
    try:
        data = _read_regular(os.path.join(run_dir, PIPELINE_RESULT_NAME))
        if data is None:
            raise ReportError("REPORT_PIPELINE_RESULT_MISSING", f"the run has no {PIPELINE_RESULT_NAME}")
        pipeline_result = _decode_json(data)
    except _ReadRefused as exc:
        raise ReportError(f"REPORT_PIPELINE_RESULT_{exc.reason}", f"{PIPELINE_RESULT_NAME} refused") from None
    if not isinstance(pipeline_result, dict):
        raise ReportError("REPORT_PIPELINE_RESULT_NOT_OBJECT", f"{PIPELINE_RESULT_NAME} is not a JSON object")
    if pipeline_result.get("pipeline_id") != run_id:
        raise ReportError("REPORT_RUN_IDENTITY_MISMATCH", f"{PIPELINE_RESULT_NAME} does not belong to --run-id")
    return pipeline_result


def _read_worker(workers_dir: str, worker_id: str) -> tuple:
    """(read status, value passed to FCP-6A-01) for one declared, safe id."""
    try:
        worker_dir = os.path.join(workers_dir, worker_id)
        if not _check_dir(worker_dir):
            return READ_ABSENT, None
        data = _read_regular(os.path.join(worker_dir, WORKER_RESULT_NAME))
        if data is None:
            return READ_ABSENT, None
        return READ_OK, _decode_json(data)
    except _ReadRefused as exc:
        status = f"REFUSED_{exc.reason}"
        # A non-mapping marker: FCP-6A-01 reports it as MALFORMED_EVIDENCE.
        return status, status


def _undeclared_entries(workers_dir: str, declared: set) -> list:
    """Names (never opened) of `workers/` entries no summary declares."""
    try:
        with os.scandir(workers_dir) as entries:
            names = []
            for entry in entries:
                names.append(entry.name)
                if len(names) > MAX_WORKER_ENTRIES:
                    raise ReportError("REPORT_TOO_MANY_WORKER_ENTRIES", f"more than {MAX_WORKER_ENTRIES} worker entries")
    except OSError:
        raise ReportError("REPORT_WORKERS_DIR_REFUSED", "workers directory refused (UNREADABLE)") from None
    return sorted(n for n in names if n not in declared)


def collect(state_root: str, run_id: str) -> tuple:
    """Read one run: (pipeline_result, worker_results, worker read records).
    `worker_results` is the `{worker_id: result | None}` mapping
    `assess_pipeline` expects; nothing is written anywhere."""
    run_dir = _run_dir(state_root, run_id)
    pipeline_result = _load_pipeline_result(run_dir, run_id)

    declared = pipeline_result.get("workers")
    declared = declared if isinstance(declared, list) else []
    ids = [s.get("id") if isinstance(s, dict) else None for s in declared]
    if len(ids) > MAX_WORKER_ENTRIES:
        raise ReportError("REPORT_TOO_MANY_WORKER_ENTRIES", f"more than {MAX_WORKER_ENTRIES} declared workers")

    workers_dir = os.path.join(run_dir, WORKERS_DIRNAME)
    try:
        has_workers_dir = _check_dir(workers_dir)
    except _ReadRefused as exc:
        raise ReportError("REPORT_WORKERS_DIR_REFUSED", f"workers directory refused ({exc.reason})") from None

    worker_results: dict = {}
    records = []
    for index, wid in enumerate(ids):
        if not safe_segment(wid):
            status = READ_UNSAFE_ID  # never opened; FCP-6A-01 reports it
        elif wid in worker_results:
            status = READ_DUPLICATE_ID  # read once; FCP-6A-01 flags the duplicate
        elif not has_workers_dir:
            status, worker_results[wid] = READ_ABSENT, None
        else:
            status, worker_results[wid] = _read_worker(workers_dir, wid)
        records.append({"index": index, "worker_id": wid if safe_segment(wid) else None, "read": status})

    if has_workers_dir:
        declared_ids = {w for w in ids if isinstance(w, str)}
        for name in _undeclared_entries(workers_dir, declared_ids):
            worker_results[name] = None  # extra evidence: reported, never opened
    return pipeline_result, worker_results, records


def build_report(state_root: str, run_id: str) -> dict:
    pipeline_result, worker_results, records = collect(state_root, run_id)
    diagnostic = fi.assess_pipeline(pipeline_result, worker_results)
    advisory = ra.advise_pipeline(diagnostic)
    return {
        "schema": SCHEMA, "schema_version": SCHEMA_VERSION, "marker": REPORT_MARKER, "run_id": run_id,
        "authority": dict(_AUTHORITY),
        "inputs": {"pipeline_result": READ_OK, "workers": records},
        "diagnostic": diagnostic.to_dict(), "advisory": advisory.to_dict(),
        "certified": False, "authorizes_action": False, "auto_retry_allowed": False, "execution_allowed": False,
        "resume_allowed": False, "merging_allowed": False,
    }


def render(report: dict) -> str:
    return json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message):  # never echo argument values (paths, ids)
        self.exit(2, "error: REPORT_USAGE_INVALID: expected --state-root DIR --run-id ID\n")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        prog="fabric_recovery_report_cli",
        description="Read-only FCP-6A/FCP-6B report over one Runner run's durable evidence. "
                    "Never executes, retries, resumes or writes anything.",
    )
    parser.add_argument("--state-root", required=True, help="existing Runner state root directory")
    parser.add_argument("--run-id", required=True, help="pipeline id (safe segment) under --state-root")
    return parser


def main(argv: Optional[list] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        payload = render(build_report(args.state_root, args.run_id))
    except ReportError as exc:
        print(f"error: {exc.code}: {exc.message}", file=sys.stderr)
        return EXIT_REPORT_REFUSED
    except Exception:  # noqa: BLE001 - fail closed without a traceback or leaked bytes
        print("error: REPORT_INTERNAL_ERROR: the report could not be produced", file=sys.stderr)
        return EXIT_REPORT_REFUSED
    print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
