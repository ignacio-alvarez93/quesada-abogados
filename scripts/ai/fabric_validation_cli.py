"""FCP-8D-01: consultative, read-only CLI that lets an operator inspect ONE
Director run through the FCP-8 Validation & Evidence Engine.

    python -m scripts.ai.fabric_validation_cli single --run-id ID \
        --state-root DIR --director-root DIR [--format json|text]
    python -m scripts.ai.fabric_validation_cli dag --run-id ID \
        --state-root DIR --director-root DIR [--format json|text]

Why this is a reader, not a launcher
------------------------------------
* The only data path is the EXISTING `fabric_director.FabricDirectorService`
  read projections, consumed through the FCP-8 engine: `single` calls
  `fabric_validation_single.observe_single_run` (result/evidence/decision)
  and `dag` calls `fabric_validation_dag.observe_dag_run`
  (result_blueprint). The observation is composed with
  `fabric_validation_report.build_report` and re-verified, bound to that
  observation, with `verify_report`. Nothing is re-derived here and no
  Runner file is parsed by this module. The adapters see the service only
  through a pass-through view exposing exactly those read methods; every
  projection it returns must carry `pipeline_id == --run-id`.
* There is no `submit`, `run`, `recover`, `--execute-confirm`, `--merge`,
  `--push`, job, scraping or network path. Nothing is written or created;
  this module starts no process, shell or Git command. (The existing
  `FabricDirectorService` constructor itself resolves its own source
  repository with a read-only `git rev-parse --show-toplevel`; that is
  Director behaviour, unchanged here, and touches no run state.)
* `--state-root` and `--director-root` are REQUIRED explicit operator paths
  passed verbatim to `FabricDirectorService(state_root=, director_root=)`;
  the CLI never resolves a default runtime root and never invents a store.
  Both must be existing, non-link directories; the run directory
  `<state-root>/<run-id>` must exist (and, for `dag`, the Director request
  `<director-root>/<run-id>`). These are existence checks only.

Fail-closed refusals (exit 1, stderr only, nothing on stdout)
-------------------------------------------------------------
Missing roots, unknown run, an unsafe run id, an unreadable/corrupt or
mistyped projection, a cross-run identity mismatch, a stale or foreign DAG
provenance and a multi-worker run asked for as `single` are refused as
`error: VALIDATION_<CODE>: <fixed text> [codes=<engine codes>]`. The text
is fixed; the codes are the engine's own enumerated tokens. No path, run id,
exception message, traceback or file byte is ever printed.

Output (exit 0 / 3 / 4)
-----------------------
Stdout is one compact canonical JSON envelope (schema `SCHEMA`): the
command, the sealed FCP-8C-02 report (`report`, verifiable on its own with
`verify_report`), its schema and `report_sha256`, the verdict, and every
authority flag fixed to False. `--format text` prints the same facts as
plain token lines. Exit 0 = VALIDATION_COMPLETE, 3 = UNPROVEN,
4 = HUMAN_REVIEW_REQUIRED; 2 = usage error. Every exit is ADVISORY: no exit
code certifies, approves or permits anything, and this CLI cannot stand in
for the FCP-3 remote PR / CI authority, nor for Runner's safety, auth/quota,
execution, acceptance or permission authority.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path
from typing import Optional

# Same deterministic repository-root bootstrap as `fabric_recovery_report_cli`.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.ai import fabric_director as fd  # noqa: E402
from scripts.ai import fabric_validation_dag as vd  # noqa: E402
from scripts.ai import fabric_validation_report as rp  # noqa: E402
from scripts.ai import fabric_validation_rules as vr  # noqa: E402
from scripts.ai import fabric_validation_single as vs  # noqa: E402
from scripts.ai.fabric_recovery_report_cli import safe_segment  # noqa: E402

SCHEMA = "fcp8d01-validation-cli-output-v1"
SCHEMA_VERSION = 1
OUTPUT_MARKER = "FCP8D01_CONSULTATIVE_READ_ONLY_NOT_CERTIFIED_NOT_AUTHORIZED"

COMMAND_SINGLE = "single"
COMMAND_DAG = "dag"
COMMANDS = (COMMAND_SINGLE, COMMAND_DAG)
FORMAT_JSON = "json"
FORMAT_TEXT = "text"

EXIT_COMPLETE = 0
EXIT_REFUSED = 1
EXIT_USAGE = 2
EXIT_UNPROVEN = 3
EXIT_HUMAN_REVIEW = 4
_EXIT_OF_VERDICT = {
    vr.VALIDATION_COMPLETE: EXIT_COMPLETE, vr.UNPROVEN: EXIT_UNPROVEN, vr.HUMAN_REVIEW_REQUIRED: EXIT_HUMAN_REVIEW,
}

PIPELINE_RESULT_NAME = "pipeline_result.json"
AUTHORITY = {
    "role": "CONSULTATIVE_READER", "launcher": False, "execution_authority": "RUNNER",
    "director_authority": "FABRIC_DIRECTOR", "pr_ci_authority": "REMOTE_PR_CI",
}
AUTHORITY_FLAGS = rp.AUTHORITY_FLAGS

_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)

# Engine observation codes that mean the run could not be observed at all,
# mapped to the CLI refusal they produce (first match in this order wins).
_SINGLE_REFUSALS = (
    ("VALIDATION_RUN_ID_INVALID", ("RUN_ID_INVALID",)),
    ("VALIDATION_MULTIWORKER_RUN", ("MULTIWORKER_REFUSED",)),
    ("VALIDATION_IDENTITY_MISMATCH", ("RUN_ID_MISMATCH", "PIPELINE_ID_MISMATCH", "WORKER_ID_MISMATCH")),
    ("VALIDATION_EVIDENCE_UNREADABLE", ("RESULT_READ_FAILED", "EVIDENCE_READ_FAILED", "DECISION_READ_FAILED")),
    ("VALIDATION_PROJECTION_NOT_TYPED", ("RESULT_NOT_TYPED", "EVIDENCE_NOT_TYPED", "DECISION_NOT_TYPED")),
    ("VALIDATION_PROJECTION_MALFORMED", ("DECISION_CODE_UNRECOGNIZED", "IDENTITY_MALFORMED")),
    ("VALIDATION_IDENTITY_MISSING", ("PIPELINE_ID_MISSING", "WORKER_ID_MISSING")),
)
_DAG_REFUSALS = (
    ("VALIDATION_RUN_ID_INVALID", ("RUN_ID_INVALID", "EXPECTED_DIGEST_INVALID")),
    ("VALIDATION_IDENTITY_MISMATCH", ("PROVENANCE_REFUSED", "RUN_ID_MISMATCH", "PIPELINE_ID_MISMATCH",
                                      "STALE_PROVENANCE")),
    ("VALIDATION_EVIDENCE_UNREADABLE", ("READ_FAILED",)),
    ("VALIDATION_PROJECTION_NOT_TYPED", ("SUMMARY_NOT_TYPED",)),
)
_REFUSAL_MESSAGES = {
    "VALIDATION_RUN_ID_INVALID": "--run-id is not a valid run id for this command",
    "VALIDATION_STATE_ROOT_INVALID": "--state-root must be an existing, non-link directory",
    "VALIDATION_DIRECTOR_ROOT_INVALID": "--director-root must be an existing, non-link directory",
    "VALIDATION_RUN_NOT_FOUND": "no run with --run-id under --state-root",
    "VALIDATION_DAG_REQUEST_NOT_FOUND": "no Director DAG request with --run-id under --director-root",
    "VALIDATION_MULTIWORKER_RUN": "the run is a multi-worker DAG run; use the dag command",
    "VALIDATION_IDENTITY_MISMATCH": "the projected evidence does not belong to --run-id",
    "VALIDATION_EVIDENCE_UNREADABLE": "the run's evidence could not be read",
    "VALIDATION_PROJECTION_NOT_TYPED": "the Director returned an unexpected projection type",
    "VALIDATION_PROJECTION_MALFORMED": "the Director projection is malformed",
    "VALIDATION_PROJECTION_INVALID": "the DAG projection failed schema/provenance validation",
    "VALIDATION_IDENTITY_MISSING": "the projected evidence carries no pipeline/worker identity",
    "VALIDATION_REPORT_UNVERIFIED": "the composed report failed its own verification",
    "VALIDATION_INTERNAL_ERROR": "the report could not be produced",
}


class ValidationCliError(Exception):
    """Refusal to report. `code` and `message` are fixed text; `codes` holds
    only engine-enumerated tokens. Never a path, run id or OS message."""

    def __init__(self, code: str, codes: tuple = ()):
        super().__init__(code)
        self.code = code
        self.message = _REFUSAL_MESSAGES[code]
        self.codes = tuple(codes)

    def render(self) -> str:
        suffix = f" [codes={','.join(self.codes)}]" if self.codes else ""
        return f"error: {self.code}: {self.message}{suffix}"


# ---------------------------------------------------------------------------
# Existence checks (lstat only; nothing is opened, parsed or created)
# ---------------------------------------------------------------------------
def _kind(path: str) -> Optional[str]:
    """DIR, FILE, LINK, OTHER, or None when absent / not inspectable."""
    try:
        st = os.lstat(path)
    except (OSError, ValueError):
        return None
    if stat.S_ISLNK(st.st_mode) or getattr(st, "st_file_attributes", 0) & _REPARSE_POINT:
        return "LINK"
    if stat.S_ISDIR(st.st_mode):
        return "DIR"
    return "FILE" if stat.S_ISREG(st.st_mode) else "OTHER"


def _require_root(path, code: str) -> str:
    if not isinstance(path, str) or not path or "\x00" in path or _kind(path) != "DIR":
        raise ValidationCliError(code)
    return path


def _check_run(command: str, run_id, state_root, director_root) -> None:
    valid_id = fd._is_director_pipeline_id(run_id) if command == COMMAND_DAG else safe_segment(run_id)
    if not valid_id:
        raise ValidationCliError("VALIDATION_RUN_ID_INVALID")
    _require_root(state_root, "VALIDATION_STATE_ROOT_INVALID")
    _require_root(director_root, "VALIDATION_DIRECTOR_ROOT_INVALID")
    run_dir = os.path.join(state_root, run_id)
    if _kind(run_dir) != "DIR" or _kind(os.path.join(run_dir, PIPELINE_RESULT_NAME)) != "FILE":
        raise ValidationCliError("VALIDATION_RUN_NOT_FOUND")
    if command == COMMAND_DAG and _kind(os.path.join(director_root, run_id)) != "DIR":
        raise ValidationCliError("VALIDATION_DAG_REQUEST_NOT_FOUND")


# ---------------------------------------------------------------------------
# Observation -> sealed report
# ---------------------------------------------------------------------------
def build_service(state_root: str, director_root: str) -> "fd.FabricDirectorService":
    """The existing Director facade over the operator's explicit roots."""
    return fd.FabricDirectorService(state_root=state_root, director_root=director_root)


_READS = {COMMAND_SINGLE: ("result", "evidence", "decision"), COMMAND_DAG: ("result_blueprint",)}


class _ReadOnlyReader:
    """Pass-through view of the service exposing ONLY the read projections
    the command's FCP-8 adapter calls; every returned projection is kept so
    its identity can be bound to --run-id. Any other attribute is refused."""

    def __init__(self, service, command: str):
        self._service = service
        self._allowed = _READS[command]
        self.projections = []

    def __getattr__(self, name):
        if name.startswith("_") or name not in self._allowed:
            raise AttributeError(name)
        method = getattr(self._service, name)

        def read(run_id):
            value = method(run_id)
            self.projections.append(value)
            return value
        return read


def _identity_bound(projections, run_id: str) -> bool:
    """Every projected `pipeline_id` names --run-id itself (the engine joins
    the projections with each other; this binds them to the request)."""
    return all(getattr(p, "pipeline_id", run_id) == run_id for p in projections)


def _refusal(observation, command: str) -> Optional[ValidationCliError]:
    codes = tuple(observation.observation_codes)
    if command == COMMAND_DAG:
        if observation.classification not in (vd.UNOBSERVABLE, vd.INVALID_PROJECTION):
            return None
        table, fallback = _DAG_REFUSALS, "VALIDATION_PROJECTION_INVALID"
    else:
        table, fallback = _SINGLE_REFUSALS, None
    for code, triggers in table:
        if any(c in triggers for c in codes):
            return ValidationCliError(code, codes)
    return ValidationCliError(fallback, codes) if fallback else None


def observe(command: str, service, run_id: str):
    """One FCP-8 observation of `run_id` through a read-only view of the
    service; refuses a projection that belongs to another run."""
    reader = _ReadOnlyReader(service, command)
    if command == COMMAND_DAG:
        observation = vd.observe_dag_run(reader, run_id)
    else:
        observation = vs.observe_single_run(reader, run_id)
    if not _identity_bound(reader.projections, run_id):
        raise ValidationCliError("VALIDATION_IDENTITY_MISMATCH", tuple(observation.observation_codes))
    return observation


def compose(command: str, observation) -> dict:
    """The output envelope for one observation; refuses unobservable runs."""
    refusal = _refusal(observation, command)
    if refusal is not None:
        raise refusal
    report = rp.build_report(observation)
    verification = rp.verify_report(report, observation=observation)
    if not verification.valid or verification.report_sha256 != report.report_sha256:
        raise ValidationCliError("VALIDATION_REPORT_UNVERIFIED", verification.codes)
    return {
        "schema": SCHEMA, "schema_version": SCHEMA_VERSION, "marker": OUTPUT_MARKER, "command": command,
        "report_schema": rp.SCHEMA, "report_schema_version": rp.SCHEMA_VERSION,
        "report_sha256": report.report_sha256, "verdict": report.verdict, "report": report.to_dict(),
        "authority": dict(AUTHORITY), **dict.fromkeys(AUTHORITY_FLAGS, False),
    }


def run_command(command: str, run_id, state_root, director_root) -> dict:
    _check_run(command, run_id, state_root, director_root)
    service = build_service(state_root, director_root)
    return compose(command, observe(command, service, run_id))


def render_json(envelope: dict) -> str:
    return json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def render_text(envelope: dict) -> str:
    report = envelope["report"]
    claims = report["claim_counts"]
    lines = [
        f"schema: {envelope['schema']}",
        f"command: {envelope['command']}",
        f"report_schema: {envelope['report_schema']}",
        f"report_sha256: {envelope['report_sha256']}",
        f"verdict: {envelope['verdict']}",
        f"source: {report['classification']['source']}",
        f"claims: verified={claims['verified']} unknown={claims['unknown']} failed={claims['failed']}",
        "reason_codes: " + (",".join(report["reason_codes"]) or "-"),
        "authority: ADVISORY ONLY - not certified, not authorized; "
        "Runner and remote PR/CI remain the authority",
    ]
    return "\n".join(lines)


def exit_code_for(envelope: dict) -> int:
    return _EXIT_OF_VERDICT.get(envelope.get("verdict"), EXIT_REFUSED)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
_USAGE = ("error: VALIDATION_USAGE_INVALID: expected {single|dag} --run-id ID --state-root DIR "
          "--director-root DIR [--format json|text]\n")


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message):  # never echo argument values (paths, ids)
        self.exit(EXIT_USAGE, _USAGE)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        prog="fabric_validation_cli", allow_abbrev=False,
        description="Read-only FCP-8 validation report over one Director run. Advisory only: never executes, "
                    "submits, recovers, merges, pushes or writes anything, and never replaces remote PR/CI.",
    )
    commands = parser.add_subparsers(dest="command", required=True, parser_class=_ArgumentParser)
    for name, summary in ((COMMAND_SINGLE, "observe one single-worker Director run"),
                          (COMMAND_DAG, "observe one Director DAG (multi-worker) run")):
        sub = commands.add_parser(name, help=summary, description=summary, allow_abbrev=False)
        sub.add_argument("--run-id", required=True, help="Director/Runner run id")
        sub.add_argument("--state-root", required=True, help="existing Runner state root (explicit)")
        sub.add_argument("--director-root", required=True, help="existing Director request root (explicit)")
        sub.add_argument("--format", choices=(FORMAT_JSON, FORMAT_TEXT), default=FORMAT_JSON,
                         help="compact canonical JSON (default) or plain token lines")
    return parser


def main(argv: Optional[list] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        envelope = run_command(args.command, args.run_id, args.state_root, args.director_root)
        payload = render_text(envelope) if args.format == FORMAT_TEXT else render_json(envelope)
    except ValidationCliError as exc:
        print(exc.render(), file=sys.stderr)
        return EXIT_REFUSED
    except Exception:  # noqa: BLE001 - fail closed without a traceback or leaked bytes
        print(ValidationCliError("VALIDATION_INTERNAL_ERROR").render(), file=sys.stderr)
        return EXIT_REFUSED
    print(payload)
    return exit_code_for(envelope)


if __name__ == "__main__":
    sys.exit(main())
