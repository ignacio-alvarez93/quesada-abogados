"""FCP-9D-02: small operator CLI over the FCP-9 scheduler - consultative,
deterministic, fail-closed, provider-neutral.

    python -m scripts.ai.fabric_scheduler_cli plan --blueprint-file FILE \
        --as-of UTC [--node-state ID=STATE ...] [--max-workers N] \
        [--provider-limit ID=N ...] [--allowed-root DIR ...] [--format json|text]
    python -m scripts.ai.fabric_scheduler_cli status --run-id ID \
        --state-root DIR --director-root DIR --as-of UTC [--format json|text]

Why this is a reader/planner, not a launcher
--------------------------------------------
* `plan` parses the blueprint file with the EXISTING
  `fabric_director_cli.parse_blueprint_bytes` (same typed conversion and
  `BLUEPRINT_*` codes as `submit-blueprint`) and hands it to FCP-9B-02
  `fabric_scheduler_plan.plan_dag` once. It never calls the Director: no
  binding is persisted and nothing runs. The compiler's own read-only
  worktree / Work Order inspection is the only I/O after the file read.
* `status` calls FCP-9C-02 `fabric_scheduler_state.observe_scheduler_state`
  over the EXISTING `FabricDirectorService`, seen through a pass-through view
  exposing ONLY `result_blueprint` and `status`. Both roots are REQUIRED,
  explicit and passed verbatim; no default runtime root is ever resolved.
* There is deliberately NO `submit`. The FCP-9D-01 gateway
  (`fabric_scheduler_gateway.submit`) needs the in-memory `DirectorDagHandle`
  that `submit_blueprint` returns, and a Host confirmation token bound to a
  review of THAT handle. A handle cannot be reloaded from a run id (see
  `fabric_director_cli`), and re-submitting creates a new Director pipeline id
  (clock + random suffix), so a review confirmed in one invocation can never
  bind the handle of the next. A governed submit is therefore not supported
  by the existing contracts and is not offered. Execution stays on the
  native `fabric_director_cli submit-run-blueprint` path; there is no merge,
  push, retry, resume, recovery or provider switch option either.

Admissible paths (lstat only before any read)
---------------------------------------------
Every operator path must be absolute, without `..` components or NUL. Roots
must be existing directories; the blueprint a regular file of at most
`BLUEPRINT_FILE_MAX_BYTES`. A symlink, junction or other reparse point at
any checked path is refused (`SCHEDULER_PATH_LINK_REFUSED`); the blueprint is
re-checked by identity after opening. For `status`, `<state-root>/<run-id>`
must hold `pipeline_result.json` and `pipeline.json`, and
`<director-root>/<run-id>` must hold the DAG provenance and plan, all
non-link; anything else is an unknown run. With `--allowed-root`, each node
worktree's link state is OBSERVED by lstat of every component below its
root and handed to FCP-9B-01 as `NO_LINK` / `LINK` / `UNKNOWN` - never
assumed. Without it, conflicts stay unassessed and pending nodes UNKNOWN.

Output and exit codes
---------------------
Stdout is one compact canonical JSON envelope (schema `SCHEMA`) holding the
engine's own sealed result (`DagPlan` / `StateProjection`), its
`result_sha256`, the outcome and every authority flag fixed to False;
`--format text` prints the same facts as token lines. No path, Work Order
text, token, exception message or provider prose is ever printed. Refusals
go to stderr only as `error: SCHEDULER_<CODE>: <fixed text> [codes=...]`.

0 = plan ADMISSIBLE / status SUCCESS; 3 = nothing admissible now (plan
WAITING or IDLE) / run still IN_PROGRESS or PAUSED; 4 = UNKNOWN (plan
UNKNOWN; status UNKNOWN or UNVERIFIED); 5 = plan nodes REFUSED / run
NOT_SUCCESSFUL; 1 = refused (nothing on stdout); 2 = usage error. Every exit
is ADVISORY: none certifies, authorizes or dispatches anything; Director and
Runner remain the only execution authorities.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from pathlib import Path
from typing import Optional

# Same deterministic repository-root bootstrap as `fabric_validation_cli`.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.ai import fabric_director as fd  # noqa: E402
from scripts.ai import fabric_director_cli as dcli  # noqa: E402
from scripts.ai import fabric_scheduler_conflicts as cf  # noqa: E402
from scripts.ai import fabric_scheduler_contract as sc  # noqa: E402
from scripts.ai import fabric_scheduler_plan as pl  # noqa: E402
from scripts.ai import fabric_scheduler_state as st  # noqa: E402
from scripts.ai import fabric_scheduler_window as sw  # noqa: E402
from scripts.ai.fabric_recovery_report_cli import safe_segment  # noqa: E402

SCHEMA = "fcp9d02-scheduler-cli-output-v1"
SCHEMA_VERSION = 1
OUTPUT_MARKER = "FCP9D02_SCHEDULER_CLI_ADVISORY_ONLY_NOT_CERTIFIED_NOT_AUTHORIZED"

COMMAND_PLAN = "plan"
COMMAND_STATUS = "status"
COMMANDS = (COMMAND_PLAN, COMMAND_STATUS)
FORMAT_JSON = "json"
FORMAT_TEXT = "text"

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_USAGE = 2
EXIT_WAITING = 3
EXIT_UNKNOWN = 4
EXIT_NOT_SUCCESSFUL = 5
_EXIT_OF_OUTCOME = {
    COMMAND_PLAN: {
        pl.ADMISSIBLE: EXIT_OK, pl.WAITING: EXIT_WAITING, pl.IDLE: EXIT_WAITING, pl.UNKNOWN: EXIT_UNKNOWN,
        pl.REFUSED: EXIT_NOT_SUCCESSFUL,
    },
    COMMAND_STATUS: {
        st.SUCCESS: EXIT_OK, st.IN_PROGRESS: EXIT_WAITING, st.PAUSED: EXIT_WAITING, st.UNKNOWN: EXIT_UNKNOWN,
        st.UNVERIFIED: EXIT_UNKNOWN, st.NOT_SUCCESSFUL: EXIT_NOT_SUCCESSFUL,
    },
}

BLUEPRINT_FILE_MAX_BYTES = dcli.BLUEPRINT_FILE_MAX_BYTES
PIPELINE_RESULT_NAME = "pipeline_result.json"
PIPELINE_STATE_NAME = "pipeline.json"
_RUN_FILES = (PIPELINE_RESULT_NAME, PIPELINE_STATE_NAME)
_REQUEST_FILES = (fd.DAG_PROVENANCE_FILENAME, fd.DAG_PLAN_FILENAME)

AUTHORITY = {
    "role": "CONSULTATIVE_PLANNER_READER", "launcher": False, "execution_authority": "RUNNER",
    "director_authority": "FABRIC_DIRECTOR", "execution_path": "fabric_director_cli",
}
AUTHORITY_FLAGS = tuple(k for k in sc._NotAuthorized._guarantees() if k != "marker")

_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)

_REFUSAL_MESSAGES = {
    "SCHEDULER_ARGUMENT_INVALID": "an option value is malformed",
    "SCHEDULER_AS_OF_INVALID": "--as-of must be a strict timezone-aware instant",
    "SCHEDULER_PATH_NOT_ADMISSIBLE": "operator paths must be absolute, without '..' components",
    "SCHEDULER_PATH_LINK_REFUSED": "a symlink, junction or reparse point was found on an operator path",
    "SCHEDULER_BLUEPRINT_FILE_INVALID": "--blueprint-file must be an existing regular file",
    "SCHEDULER_BLUEPRINT_FILE_TOO_LARGE": "--blueprint-file exceeds the size limit",
    "SCHEDULER_BLUEPRINT_INVALID": "the blueprint declaration was refused by the typed parser",
    "SCHEDULER_ALLOWED_ROOT_INVALID": "--allowed-root must be an existing, non-link directory",
    "SCHEDULER_PLAN_REFUSED": "the planning request was refused",
    "SCHEDULER_RUN_ID_INVALID": "--run-id is not a Director DAG run id",
    "SCHEDULER_STATE_ROOT_INVALID": "--state-root must be an existing, non-link directory",
    "SCHEDULER_DIRECTOR_ROOT_INVALID": "--director-root must be an existing, non-link directory",
    "SCHEDULER_RUN_NOT_FOUND": "no Runner state for --run-id under --state-root",
    "SCHEDULER_DAG_REQUEST_NOT_FOUND": "no Director DAG request for --run-id under --director-root",
    "SCHEDULER_IDENTITY_MISMATCH": "the projected state does not belong to --run-id",
    "SCHEDULER_STATE_REFUSED": "the state projection request was refused",
    "SCHEDULER_STATE_UNOBSERVABLE": "the run's state could not be observed",
    "SCHEDULER_INTERNAL_ERROR": "the result could not be produced",
}


class SchedulerCliError(Exception):
    """Refusal to report. `code` and `message` are fixed text; `codes` holds
    only engine-enumerated tokens. Never a path, id or OS message."""

    def __init__(self, code: str, codes: tuple = ()):
        super().__init__(code)
        self.code = code
        self.message = _REFUSAL_MESSAGES[code]
        self.codes = tuple(codes)

    def render(self) -> str:
        suffix = f" [codes={','.join(self.codes)}]" if self.codes else ""
        return f"error: {self.code}: {self.message}{suffix}"


# ---------------------------------------------------------------------------
# Path admission (lstat only; nothing is created or followed)
# ---------------------------------------------------------------------------
def _kind(path: str) -> Optional[str]:
    """DIR, FILE, LINK, OTHER, or None when absent / not inspectable."""
    try:
        st_ = os.lstat(path)
    except (OSError, ValueError):
        return None
    if stat.S_ISLNK(st_.st_mode) or getattr(st_, "st_file_attributes", 0) & _REPARSE_POINT:
        return "LINK"
    if stat.S_ISDIR(st_.st_mode):
        return "DIR"
    return "FILE" if stat.S_ISREG(st_.st_mode) else "OTHER"


def _admissible(path) -> str:
    if not isinstance(path, str) or not path or "\x00" in path or not os.path.isabs(path) \
            or ".." in Path(path).parts:
        raise SchedulerCliError("SCHEDULER_PATH_NOT_ADMISSIBLE")
    return path


def _require(path: str, kind: str, code: str) -> str:
    found = _kind(path)
    if found == "LINK":
        raise SchedulerCliError("SCHEDULER_PATH_LINK_REFUSED")
    if found != kind:
        raise SchedulerCliError(code)
    return path


def _require_root(path, code: str) -> str:
    return _require(_admissible(path), "DIR", code)


def check_run(run_id, state_root, director_root) -> None:
    """Existence and link checks of the explicit runtime of one DAG run."""
    if not (fd._is_director_pipeline_id(run_id) and safe_segment(run_id)):
        raise SchedulerCliError("SCHEDULER_RUN_ID_INVALID")
    _require_root(state_root, "SCHEDULER_STATE_ROOT_INVALID")
    _require_root(director_root, "SCHEDULER_DIRECTOR_ROOT_INVALID")
    for root, names, code in ((state_root, _RUN_FILES, "SCHEDULER_RUN_NOT_FOUND"),
                              (director_root, _REQUEST_FILES, "SCHEDULER_DAG_REQUEST_NOT_FOUND")):
        run_dir = _require(os.path.join(root, run_id), "DIR", code)
        for name in names:
            _require(os.path.join(run_dir, name), "FILE", code)


def read_blueprint_bytes(path) -> bytes:
    """Bounded read of one regular, non-link file, re-checked by identity
    after opening so a swapped path is refused."""
    _require(_admissible(path), "FILE", "SCHEDULER_BLUEPRINT_FILE_INVALID")
    try:
        before = os.lstat(path)
        with open(path, "rb") as handle:
            opened = os.fstat(handle.fileno())
            data = handle.read(BLUEPRINT_FILE_MAX_BYTES + 1)
    except OSError:
        raise SchedulerCliError("SCHEDULER_BLUEPRINT_FILE_INVALID") from None
    if not stat.S_ISREG(opened.st_mode) or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
        raise SchedulerCliError("SCHEDULER_PATH_LINK_REFUSED")
    if len(data) > BLUEPRINT_FILE_MAX_BYTES:
        raise SchedulerCliError("SCHEDULER_BLUEPRINT_FILE_TOO_LARGE")
    return data


def parse_blueprint(data: bytes):
    """The existing typed parser; only its leading BLUEPRINT_* code is kept."""
    try:
        return dcli.parse_blueprint_bytes(data)
    except dcli.CLIError as exc:
        head = str(exc).split(":", 1)[0]
        native = head.startswith("BLUEPRINT_") and all(
            c.isascii() and (c.isupper() or c.isdigit() or c == "_") for c in head)
        codes = (head,) if native else ()
        raise SchedulerCliError("SCHEDULER_BLUEPRINT_INVALID", codes) from None


def observe_link_state(worktree, roots: tuple) -> str:
    """NO_LINK when every component from the enclosing allowed root down to
    `worktree` is a real directory; LINK when any is a link; UNKNOWN when it
    cannot be shown (outside every root, absent, not inspectable)."""
    if not isinstance(worktree, str) or not os.path.isabs(worktree) or ".." in Path(worktree).parts:
        return cf.LINK_UNKNOWN
    target = os.path.normcase(os.path.normpath(worktree))
    for root in roots:
        base = os.path.normcase(os.path.normpath(root))
        try:
            if os.path.commonpath([base, target]) != base:
                continue
        except ValueError:
            continue
        current = os.path.normpath(root)
        for part in Path(os.path.relpath(os.path.normpath(worktree), current)).parts:
            if part == os.curdir:
                break
            current = os.path.join(current, part)
            found = _kind(current)
            if found == "LINK":
                return cf.LINK_PRESENT
            if found != "DIR":
                return cf.LINK_UNKNOWN
        return cf.LINK_NONE
    return cf.LINK_UNKNOWN


def conflict_request_for(blueprint, roots: tuple) -> Optional[cf.ConflictRequest]:
    """FCP-9B-01 request over each node's DECLARED worktree and mode, with
    the observed link state; no extra claim is invented."""
    if not roots:
        return None
    workers = tuple(
        cf.WorkerClaims(worker_id=n.id, mode=n.mode, worktree=n.worktree,
                        worktree_link_state=observe_link_state(n.worktree, roots))
        for n in blueprint.nodes
    )
    return cf.ConflictRequest(dag_id=blueprint.pipeline_id, allowed_roots=tuple(roots), workers=workers)


def _pairs(values, convert) -> tuple:
    pairs = []
    for item in values or ():
        key, sep, value = item.partition("=")
        if not sep or not key or not value:
            raise SchedulerCliError("SCHEDULER_ARGUMENT_INVALID")
        pairs.append((key, convert(value)))
    return tuple(pairs)


def _limit(text: str) -> int:
    if not (text.isascii() and text.isdigit()):
        raise SchedulerCliError("SCHEDULER_ARGUMENT_INVALID")
    return int(text)


def _require_as_of(as_of) -> str:
    if sw.parse_utc(as_of) is None:
        raise SchedulerCliError("SCHEDULER_AS_OF_INVALID")
    return as_of


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def _envelope(command: str, outcome: str, result_dict: dict, canonical: str, result_schema: str) -> dict:
    return {
        "schema": SCHEMA, "schema_version": SCHEMA_VERSION, "marker": OUTPUT_MARKER, "command": command,
        "outcome": outcome, "result_schema": result_schema,
        "result_sha256": hashlib.sha256(canonical.encode("ascii")).hexdigest(), "result": result_dict,
        "authority": dict(AUTHORITY), **dict.fromkeys(AUTHORITY_FLAGS, False),
    }


def run_plan(blueprint_file, as_of, node_states=(), max_workers=None, provider_limits=(), allowed_roots=()) -> dict:
    """Parse, then plan once. Never reaches the Director."""
    _require_as_of(as_of)
    states = _pairs(node_states, str)
    limits = _pairs(provider_limits, _limit)
    roots = tuple(_require_root(r, "SCHEDULER_ALLOWED_ROOT_INVALID") for r in allowed_roots or ())
    blueprint = parse_blueprint(read_blueprint_bytes(blueprint_file))
    request = pl.DagPlanRequest(
        blueprint=blueprint, as_of_utc=as_of, node_states=states, conflict_request=conflict_request_for(blueprint,
                                                                                                         roots),
        max_workers=max_workers, provider_limits=limits,
    )
    plan = pl.plan_dag(request)
    if plan.request_reasons:
        raise SchedulerCliError("SCHEDULER_PLAN_REFUSED", plan.request_reasons + plan.blueprint_error_codes)
    return _envelope(COMMAND_PLAN, plan.outcome, pl.DagPlan.to_dict(plan), pl.canonical_json(plan), pl.SCHEMA)


def build_service(state_root: str, director_root: str) -> "fd.FabricDirectorService":
    """The existing Director facade over the operator's explicit roots."""
    return fd.FabricDirectorService(state_root=state_root, director_root=director_root)


class _ReadOnlyReader:
    """Pass-through view of the service exposing ONLY the two reads FCP-9C-02
    performs; every returned value is kept so its identity can be bound to
    --run-id. Any other attribute is refused."""

    _ALLOWED = ("result_blueprint", "status")

    def __init__(self, service):
        self._service = service
        self.projections = []

    def __getattr__(self, name):
        if name.startswith("_") or name not in self._ALLOWED:
            raise AttributeError(name)
        method = getattr(self._service, name)

        def read(run_id):
            value = method(run_id)
            self.projections.append(value)
            return value
        return read


def _identity_bound(projections, run_id: str) -> bool:
    for value in projections:
        ids = (value.get("pipeline_id"),) if type(value) is dict else (
            getattr(value, "pipeline_id", run_id), getattr(value, "run_id", run_id))
        if any(i != run_id for i in ids):
            return False
    return True


def run_status(run_id, state_root, director_root, as_of) -> dict:
    _require_as_of(as_of)
    check_run(run_id, state_root, director_root)
    reader = _ReadOnlyReader(build_service(state_root, director_root))
    projection = st.observe_scheduler_state(reader, run_id, as_of_utc=as_of)
    if projection.outcome == st.REFUSED:
        raise SchedulerCliError("SCHEDULER_STATE_REFUSED", projection.request_reasons)
    if projection.outcome == st.UNOBSERVABLE:
        raise SchedulerCliError("SCHEDULER_STATE_UNOBSERVABLE", projection.request_reasons)
    if not _identity_bound(reader.projections, run_id):
        raise SchedulerCliError("SCHEDULER_IDENTITY_MISMATCH")
    return _envelope(COMMAND_STATUS, projection.outcome, st.StateProjection.to_dict(projection),
                     st.canonical_json(projection), st.SCHEMA)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def render_json(envelope: dict) -> str:
    return json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def render_text(envelope: dict) -> str:
    result = envelope["result"]
    lines = [
        f"schema: {envelope['schema']}",
        f"command: {envelope['command']}",
        f"result_schema: {envelope['result_schema']}",
        f"result_sha256: {envelope['result_sha256']}",
        f"outcome: {envelope['outcome']}",
    ]
    if envelope["command"] == COMMAND_PLAN:
        lines.append(f"window: {result['window_status']}")
        lines.append("counts: " + " ".join(f"{k}={v}" for k, v in sorted(result["counts"].items())))
        for d in result["decisions"]:
            slot = "-" if d["slot"] is None else d["slot"]
            lines.append(f"node: {d['node_id']} {d['decision']} slot={slot} "
                         f"reasons={','.join(d['reasons']) or '-'}")
    else:
        lines.append(f"finished: {str(result['finished']).lower()}")
        lines.append("codes: " + (",".join(result["codes"]) or "-"))
        for n in result["nodes"]:
            lines.append(f"node: {n['node_id']} {n['status']} heartbeat={n['heartbeat']} "
                         f"codes={','.join(n['codes']) or '-'}")
    lines.append("authority: ADVISORY ONLY - not certified, not authorized; Director and Runner remain the "
                 "only execution authorities")
    return "\n".join(lines)


def exit_code_for(envelope: dict) -> int:
    return _EXIT_OF_OUTCOME.get(envelope.get("command"), {}).get(envelope.get("outcome"), EXIT_REFUSED)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
_USAGE = ("error: SCHEDULER_USAGE_INVALID: expected plan --blueprint-file FILE --as-of UTC [...] | "
          "status --run-id ID --state-root DIR --director-root DIR --as-of UTC [--format json|text]\n")


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message):  # never echo argument values (paths, ids)
        self.exit(EXIT_USAGE, _USAGE)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        prog="fabric_scheduler_cli", allow_abbrev=False,
        description="Consultative FCP-9 scheduler plan and state. Advisory only: never submits, executes, "
                    "retries, resumes, merges, pushes or writes anything.",
    )
    commands = parser.add_subparsers(dest="command", required=True, parser_class=_ArgumentParser)
    p_plan = commands.add_parser(COMMAND_PLAN, allow_abbrev=False,
                                 help="propose the next admissible batch of a blueprint (never executes)")
    p_plan.add_argument("--blueprint-file", required=True, help="absolute path of the JSON blueprint")
    p_plan.add_argument("--as-of", required=True, help="explicit evaluation instant (timezone-aware)")
    p_plan.add_argument("--node-state", action="append", default=None, metavar="ID=STATE",
                        help="observed Runner WorkerState of a node (repeatable; omitted = UNKNOWN)")
    p_plan.add_argument("--max-workers", type=int, default=None, help="narrow the manifest's worker cap")
    p_plan.add_argument("--provider-limit", action="append", default=None, metavar="ID=N",
                        help="narrow a provider limit (repeatable)")
    p_plan.add_argument("--allowed-root", action="append", default=None, metavar="DIR",
                        help="allowed worktree root for conflict analysis (repeatable)")
    p_status = commands.add_parser(COMMAND_STATUS, allow_abbrev=False,
                                   help="project the tracked state of one Director DAG run (read-only)")
    p_status.add_argument("--run-id", required=True, help="Director DAG run id")
    p_status.add_argument("--state-root", required=True, help="existing Runner state root (explicit)")
    p_status.add_argument("--director-root", required=True, help="existing Director request root (explicit)")
    p_status.add_argument("--as-of", required=True, help="explicit evaluation instant (timezone-aware)")
    for sub in (p_plan, p_status):
        sub.add_argument("--format", choices=(FORMAT_JSON, FORMAT_TEXT), default=FORMAT_JSON,
                         help="compact canonical JSON (default) or plain token lines")
    return parser


def main(argv: Optional[list] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        if args.command == COMMAND_PLAN:
            envelope = run_plan(args.blueprint_file, args.as_of, args.node_state, args.max_workers,
                                args.provider_limit, args.allowed_root)
        else:
            envelope = run_status(args.run_id, args.state_root, args.director_root, args.as_of)
        payload = render_text(envelope) if args.format == FORMAT_TEXT else render_json(envelope)
    except SchedulerCliError as exc:
        print(exc.render(), file=sys.stderr)
        return EXIT_REFUSED
    except Exception:  # noqa: BLE001 - fail closed without a traceback or leaked bytes
        print(SchedulerCliError("SCHEDULER_INTERNAL_ERROR").render(), file=sys.stderr)
        return EXIT_REFUSED
    print(payload)
    return exit_code_for(envelope)


if __name__ == "__main__":
    sys.exit(main())
