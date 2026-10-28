"""FDB-4A1: thin, provider-neutral host CLI over the EXISTING
`FabricDirectorService` (see `fabric_director.py`).

Why this is a CLI wrapper, not a second engine
------------------------------------------------
Every command below does nothing but (1) parse CLI arguments into the
SAME dataclasses `FabricDirectorService` already accepts
(`DirectorWorkOrderSpec`), (2) call the corresponding EXISTING service
method (`project_state`, `submit`, `submit_and_run`, `status`, `result`, `evidence`, `decision`),
and (3) serialize the EXISTING return value (a dict, or a dataclass via
`dataclasses.asdict`) to stdout as JSON. It never:

* builds a manifest, parses one, or calls `runner_pipeline` itself -
  `FabricDirectorService.submit`/`submit_and_run` do that;
* reconstructs evidence or computes decisions independently - the read-only
  commands delegate entirely to FabricDirectorService;
* calls `claude_runner.execute_work_order` or any other execution path
  directly - only `FabricDirectorService.run`, via `submit_and_run`, does;
* persists a handle/run store of its own - `director_root`/`state_root`
  remain the only durable roots, both owned by `FabricDirectorService`.

Why there is no standalone `run` command
-----------------------------------------
`FabricDirectorService.run(handle)` takes a `DirectorRunHandle` - the
in-memory return value of `submit()` - not a `run_id`. The service has no
"load a handle back from a `run_id`" accessor (by design: the Director's
only durable state is the persisted Work Order/manifest, not a reloadable
handle object). A standalone `fabric_director_cli.py run --run-id ...`
command would therefore have to invent a NEW durable handle store (or
reconstruct a handle by re-deriving `worker_id`/`manifest_path` from
`run_id`/`director_root` outside the service) to let a second CLI
invocation resume where `submit` left off. Section B forbids inventing
that persistence abstraction in A1, so `run` is not implemented here;
`submit-run` (-> `FabricDirectorService.submit_and_run`, which holds the
handle in-process for the one process that both submits and runs) is the
canonical A1 execution command.

FCP-1C: `assess-integration`
-----------------------------
A read-only projection of `FabricDirectorService.assess_integration` (the
FCP-1B assessment core) as JSON. The exit status reports only whether an
assessment was produced: exit 0 for EVERY classification, including every
fail-closed one, so callers must read `classification`/`eligible`. Even
ELIGIBLE_PENDING_APPROVAL is not approval (`human_approval_required` is
always true) and nothing is ever integrated, promoted or written to Git.

FCP-2C: `assess-reconciliation`
--------------------------------
A read-only projection of `FabricDirectorService.assess_reconciliation`
(the FCP-2B analysis core) with the same host inputs as
`assess-integration`, plus `--max-paths` and an OPTIONAL proposed review
plan. Output is exactly `{"analysis": asdict(analysis), "plan":
asdict(plan) | null}`: without `--acceptance-command` the plan is null;
with it, `FabricDirectorService.propose_reconciliation_plan` is called and
returns null for a non-plannable analysis. A plan is only ever PROPOSED,
holds the host's commands verbatim (never run) and authorizes nothing.
Exit 0 means only that an analysis was produced - for EVERY classification -
never success or approval; NO_TEXTUAL_CONFLICT is not semantic safety.

FCP-4C-01: `inventory-worktrees`
--------------------------------
A read-only projection of `FabricDirectorService.inventory_worktrees` as
JSON (`dataclasses.asdict` of the inventory). Exit 0 means only that an
inventory was produced - including a FAILED_CLOSED one (`status`,
`complete` and `global_errors` say why) - never that any worktree may be
pruned or removed: `authorizes_action` is always false.

FCP-4D-02: `assess-worktree-retirement`
---------------------------------------
A read-only projection of `FabricDirectorService.assess_worktree_retirement`
as JSON (`dataclasses.asdict` of the report). `--queue-root` (repeatable)
declares the only queues consulted; `--queue-roots-complete` records the
host's claim that they are the complete known set (verbatim, never a
proof). Exit 0 means only that a report was produced - including a
FAILED_CLOSED one - NOT that anything is safe: every record keeps
`authorizes_action` and `deletion_authorized` false, and even
CANDIDATE_FOR_HUMAN_REVIEW is an informational shortlist only.

FCP-5B-02: `submit-blueprint`, `submit-run-blueprint`, `result-blueprint`
-------------------------------------------------------------------------
Host entry points for 2+ Work Orders over the EXISTING FCP-5B-01 Director
DAG gateway - no second engine, scheduler or worker:

* `submit-blueprint --blueprint-file F` converts ONE JSON declaration into
  the existing frozen `fabric_dag_blueprint.DagBlueprint`/`BlueprintNode`
  and calls `FabricDirectorService.submit_blueprint` once. Nothing runs.
* `submit-run-blueprint --blueprint-file F --execute-confirm RUN_BLUEPRINT`
  is the same conversion, `submit_blueprint` once, then `run_blueprint`
  once with the returned in-memory `DirectorDagHandle`. The confirmation is
  a CLI safety gate only; it grants no write/shell/recovery power - the
  Director and Runner alone govern execution.
* `result-blueprint --run-id ID` is `FabricDirectorService.result_blueprint`
  verbatim: Runner's aggregate plus EVERY worker, never a single-worker
  `result`/`evidence`/`decision` projection.

There is no `run-blueprint --run-id`, for the same reason there is no `run`:
`run_blueprint` needs the binding-validated in-memory handle, and the CLI
never reconstructs one from a run id or guessed paths.

The blueprint file (see `BLUEPRINT_JSON_EXAMPLE`) is a regular local file of
at most `BLUEPRINT_FILE_MAX_BYTES` bytes (checked before decoding), strict
UTF-8 without BOM, holding one JSON object whose keys are exactly the
dataclass fields: required keys present, optional keys omitted (never
null), no unknown or repeated key at any level, exact JSON types (a boolean
is not an integer; NaN/Infinity are refused). JSON arrays become tuples
only at the declared sequence fields: `nodes`, `depends_on`,
`required_capabilities`, `authorize_path`, `acceptance_commands`, and
`provider_limits` as `[[provider_id, limit], ...]`. That typed conversion is
the CLI's ONLY check: graph, edge, worktree, path, provider, mode, policy,
limit and time decisions stay with `compile_blueprint`/`parse_manifest`.
Any input failure is `error: BLUEPRINT_<CODE>: ...` on stderr with exit 1,
raised before the Director is called; messages name locations and dataclass
fields only, never the file's content. Exit 0 means only that the Director
returned a result: `pipeline_status`/`aggregate_status` are reported as the
Director produced them, never upgraded to SUCCESS here.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import sys
import textwrap
from pathlib import Path
from typing import Optional

# Direct-script execution (`python scripts/ai/fabric_director_cli.py`) sets
# sys.path[0] to this file's own directory, not the repository root, so
# `scripts.ai` would otherwise only resolve via (unreliable) ambient
# PYTHONPATH - and could silently resolve against a *different* checkout's
# `scripts/ai` if one happens to be on PYTHONPATH. Deterministically
# computing the repository root from `__file__` and putting it first on
# `sys.path` makes the canonical package import correct and unambiguous
# under every supported invocation (direct script, absolute path, `-m`).
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.ai import fabric_director as director
from scripts.ai import runner_factory_ledger as flog

# The SAME module object the Director type-checks a `DagBlueprint` against.
blueprints = director.blueprints


class CLIError(Exception):
    """CLI-level input failure; nothing on the Director/Runner side was
    touched. Always surfaces as a non-zero exit, never as JSON on stdout."""


def _build_service(args: argparse.Namespace) -> "director.FabricDirectorService":
    kwargs = {}
    if args.state_root is not None:
        kwargs["state_root"] = args.state_root
    if args.factory_root is not None:
        kwargs["factory_root"] = args.factory_root
    if args.director_root is not None:
        kwargs["director_root"] = args.director_root
    if args.self_worktree is not None:
        kwargs["self_worktree"] = args.self_worktree
    service = director.FabricDirectorService(**kwargs)
    # FCP-FIX-09: mirror the `runner_pipeline pipeline` CLI contract - an
    # ordinary host run records factory history through the EXISTING
    # FactoryLedger, which PipelineRunner alone feeds (best-effort) from its
    # own worker lifecycle. Rooted at the service's resolved factory_root so
    # `factory_state()` reads the same ledger. The library default stays None.
    if not args.no_factory_ledger:
        service.factory_ledger = flog.FactoryLedger(service.factory_root)
    return service


def _parse_metadata(pairs: Optional[list]) -> dict:
    metadata: dict = {}
    for item in pairs or []:
        key, sep, value = item.partition("=")
        if not sep or not key:
            raise CLIError(f"--metadata expects KEY=VALUE, got {item!r}")
        metadata[key] = value
    return metadata


def _read_work_order_text(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise CLIError(f"cannot read --work-order-file {path!r}: {exc}") from exc


def _spec_from_args(args: argparse.Namespace) -> "director.DirectorWorkOrderSpec":
    work_order_text = _read_work_order_text(args.work_order_file)
    metadata = _parse_metadata(args.metadata)
    acceptance_commands = list(args.acceptance_command or [])

    if args.audit:
        # FABRIC H2-C: --audit is sugar over the EXISTING
        # `director.build_audit_spec` - the CLI never hand-assembles the
        # safe read-only + runner_acceptance combination itself, and every
        # explicit/incompatible flag (--mode, --authorize-path,
        # --allow-shell, --checkpoint-policy, --completion-policy) is
        # forwarded verbatim so `build_audit_spec` can refuse BEFORE
        # anything is submitted rather than silently rewriting it.
        audit_kwargs: dict = {
            "worktree": args.worktree,
            "work_order_text": work_order_text,
            "acceptance_commands": acceptance_commands,
            "required_capabilities": list(args.capability or []),
            "timeout_seconds": args.timeout_seconds,
            "metadata": metadata,
            "mode": args.mode,
            "authorize_paths": args.authorize_path,
            "allow_shell": args.allow_shell,
            "checkpoint_policy": args.checkpoint_policy,
            "completion_policy": args.completion_policy,
        }
        if args.provider is not None:
            audit_kwargs["provider"] = args.provider
        if args.model is not None:
            audit_kwargs["model"] = args.model
        return director.build_audit_spec(**audit_kwargs)

    # Only arguments the host actually supplied are forwarded; every
    # omitted field falls through to DirectorWorkOrderSpec's OWN default
    # (never a value duplicated/guessed here), so CLI defaults always
    # match the dataclass's defaults by construction.
    spec_kwargs: dict = {
        "worktree": args.worktree,
        "work_order_text": work_order_text,
        "authorize_paths": list(args.authorize_path or []),
        "required_capabilities": list(args.capability or []),
        "allow_shell": args.allow_shell,
        "metadata": metadata,
    }
    if args.mode is not None:
        spec_kwargs["mode"] = args.mode
    if args.provider is not None:
        spec_kwargs["provider"] = args.provider
    if args.model is not None:
        spec_kwargs["model"] = args.model
    if args.checkpoint_policy is not None:
        spec_kwargs["checkpoint_policy"] = args.checkpoint_policy
    if args.timeout_seconds is not None:
        spec_kwargs["timeout_seconds"] = args.timeout_seconds
    if args.completion_policy is not None:
        spec_kwargs["completion_policy"] = args.completion_policy
    spec_kwargs["acceptance_commands"] = acceptance_commands
    return director.DirectorWorkOrderSpec(**spec_kwargs)


# ---------------------------------------------------------------------------
# Command handlers - each is a direct, faithful call into the EXISTING
# service API; none re-reads/re-parses/re-executes anything on its own.
# ---------------------------------------------------------------------------

def _cmd_project_state(args: argparse.Namespace, service: "director.FabricDirectorService"):
    return service.project_state(args.worktree)


def _cmd_submit(args: argparse.Namespace, service: "director.FabricDirectorService"):
    handle = service.submit(_spec_from_args(args))
    return dataclasses.asdict(handle)


def _cmd_submit_run(args: argparse.Namespace, service: "director.FabricDirectorService"):
    summary = service.submit_and_run(_spec_from_args(args))
    return dataclasses.asdict(summary)


def _cmd_status(args: argparse.Namespace, service: "director.FabricDirectorService"):
    return service.status(args.run_id)


def _cmd_result(args: argparse.Namespace, service: "director.FabricDirectorService"):
    summary = service.result(args.run_id)
    return dataclasses.asdict(summary)


def _cmd_evidence(args: argparse.Namespace, service: "director.FabricDirectorService"):
    evidence = service.evidence(args.run_id)
    return dataclasses.asdict(evidence)


def _cmd_decision(args: argparse.Namespace, service: "director.FabricDirectorService"):
    decision = service.decision(args.run_id)
    return dataclasses.asdict(decision)


def _read_evidence_file(path: Optional[str]):
    # Host-supplied structured run evidence, decoded and passed verbatim;
    # its validity and binding are judged only by the assessment core.
    if path is None:
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise CLIError(f"cannot read --evidence-file {path!r}: {exc}") from exc
    except ValueError as exc:
        raise CLIError(f"--evidence-file {path!r} is not valid JSON: {exc}") from exc


def _cmd_assess_integration(args: argparse.Namespace, service: "director.FabricDirectorService"):
    assessment = service.assess_integration(
        args.worktree,
        attested_sha=args.attested_sha,
        authorized_scopes=list(args.authorize_path or []),
        expected_remote_url=args.expected_remote_url,
        evidence=_read_evidence_file(args.evidence_file),
    )
    return dataclasses.asdict(assessment)


def _cmd_assess_reconciliation(args: argparse.Namespace, service: "director.FabricDirectorService"):
    kwargs: dict = {
        "attested_sha": args.attested_sha,
        "authorized_scopes": list(args.authorize_path or []),
        "expected_remote_url": args.expected_remote_url,
        "evidence": _read_evidence_file(args.evidence_file),
    }
    # Omitted: the Director's (= the core's) own default applies.
    if args.max_paths is not None:
        kwargs["max_paths"] = args.max_paths
    analysis = service.assess_reconciliation(args.worktree, **kwargs)
    plan = None
    if args.acceptance_command is not None:
        plan = service.propose_reconciliation_plan(analysis, acceptance_commands=list(args.acceptance_command))
    return {
        "analysis": dataclasses.asdict(analysis),
        "plan": None if plan is None else dataclasses.asdict(plan),
    }


def _cmd_inventory_worktrees(args: argparse.Namespace, service: "director.FabricDirectorService"):
    return dataclasses.asdict(service.inventory_worktrees(args.repository))


def _cmd_assess_worktree_retirement(args: argparse.Namespace, service: "director.FabricDirectorService"):
    return dataclasses.asdict(service.assess_worktree_retirement(
        args.repository, queue_roots=list(args.queue_root or []),
        queue_roots_complete=args.queue_roots_complete,
    ))


def _recovery_spec_from_args(args: argparse.Namespace) -> "director.DirectorRecoverySpec":
    # Shared, provider-neutral recovery specification. The existing Director
    # remains sole authority on eligibility, scopes and durable provenance.
    return director.DirectorRecoverySpec(
        prior_run_id=args.prior_run_id,
        recovery_work_order_text=_read_work_order_text(args.work_order_file),
        action=args.action,
        prior_worker_id=args.prior_worker_id,
        provider_override=args.provider,
        model=args.model,
        authorize_paths=args.authorize_path,
        required_capabilities=list(args.capability or []),
        allow_shell=args.allow_shell,
        checkpoint_policy=args.checkpoint_policy,
        timeout_seconds=args.timeout_seconds,
        metadata=_parse_metadata(args.metadata),
        # FCP-FIX-04: None (flag omitted) carries the prior worker's own
        # certification forward; the Director validates explicit values.
        completion_policy=args.completion_policy,
        acceptance_commands=args.acceptance_command,
    )


def _cmd_recover_submit(args: argparse.Namespace, service: "director.FabricDirectorService"):
    # Submission-only: deliberately does not call run().
    return dataclasses.asdict(service.recover(_recovery_spec_from_args(args)))


def _cmd_recover_run(args: argparse.Namespace, service: "director.FabricDirectorService"):
    # No new handle store and no second Runner path: recover() creates a
    # validated handle and run(handle) executes the existing PipelineRunner.
    # argparse requires a separate affirmative execution confirmation.
    handle = service.recover(_recovery_spec_from_args(args))
    return dataclasses.asdict(service.run(handle))


# ---------------------------------------------------------------------------
# FCP-5B-02: blueprint file -> existing frozen DagBlueprint (typed only)
# ---------------------------------------------------------------------------

BLUEPRINT_FILE_MAX_BYTES = 1024 * 1024
_UTF8_BOM = b"\xef\xbb\xbf"

# A complete, valid declaration (paths are placeholders); see module docstring.
BLUEPRINT_JSON_EXAMPLE = """\
{
  "pipeline_id": "example-dag",
  "max_workers": 2,
  "provider_limits": [["claude", 1]],
  "nodes": [
    {"id": "a", "worktree": "/abs/repo-a", "work_order": "/abs/wo-a.md",
     "provider": "claude", "mode": "read-only", "depends_on": []},
    {"id": "b", "worktree": "/abs/repo-b", "work_order": "/abs/wo-b.md",
     "provider": "claude", "mode": "read-only", "depends_on": []},
    {"id": "c", "worktree": "/abs/repo-c", "work_order": "/abs/wo-c.md",
     "provider": "claude", "mode": "read-only", "depends_on": ["a", "b"],
     "completion_policy": "runner_acceptance",
     "acceptance_commands": ["python -m unittest -q"]}
  ]
}"""

_JSON_TYPES = {"int": ((int,), "an integer"), "bool": ((bool,), "a boolean"), "float": ((int, float), "a number")}


def _blueprint_error(code: str, message: str) -> CLIError:
    return CLIError(f"{code}: {message}")


def _schema_error(where: str, message: str) -> CLIError:
    return _blueprint_error("BLUEPRINT_SCHEMA_INVALID", f"{where} {message}")


def _read_blueprint_bytes(path: str) -> bytes:
    # Bounded read of one regular file; the size limit holds before decoding.
    file_path = Path(path)
    try:
        if not file_path.is_file():
            raise _blueprint_error("BLUEPRINT_FILE_UNREADABLE", f"--blueprint-file {path!r} is not a regular file")
        with file_path.open("rb") as handle:
            data = handle.read(BLUEPRINT_FILE_MAX_BYTES + 1)
    except OSError as exc:
        raise _blueprint_error(
            "BLUEPRINT_FILE_UNREADABLE", f"cannot read --blueprint-file {path!r}: {exc.strerror or type(exc).__name__}",
        ) from None
    if len(data) > BLUEPRINT_FILE_MAX_BYTES:
        raise _blueprint_error("BLUEPRINT_FILE_TOO_LARGE", f"--blueprint-file exceeds {BLUEPRINT_FILE_MAX_BYTES} bytes")
    return data


def _reject_duplicate_keys(pairs: list) -> dict:
    obj: dict = {}
    for key, value in pairs:
        if key in obj:
            raise _blueprint_error("BLUEPRINT_JSON_DUPLICATE_KEY", "a JSON object repeats a key")
        obj[key] = value
    return obj


def _reject_constant(_name: str):
    raise _blueprint_error("BLUEPRINT_JSON_INVALID", "NaN/Infinity are not JSON numbers")


def _finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise _blueprint_error("BLUEPRINT_JSON_INVALID", "a JSON number is out of range")
    return value


def _decode_blueprint_json(data: bytes):
    if data.startswith(_UTF8_BOM):
        raise _blueprint_error("BLUEPRINT_FILE_NOT_UTF8", "a UTF-8 byte order mark is not supported")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _blueprint_error("BLUEPRINT_FILE_NOT_UTF8", f"invalid UTF-8 at byte offset {exc.start}") from None
    try:
        return json.loads(
            text, object_pairs_hook=_reject_duplicate_keys, parse_constant=_reject_constant, parse_float=_finite_float,
        )
    except json.JSONDecodeError as exc:
        raise _blueprint_error(
            "BLUEPRINT_JSON_INVALID", f"line {exc.lineno} column {exc.colno}: {exc.msg}",
        ) from None
    except ValueError:
        raise _blueprint_error("BLUEPRINT_JSON_INVALID", "not a valid JSON document") from None
    except RecursionError:
        raise _blueprint_error("BLUEPRINT_JSON_INVALID", "JSON nesting is too deep") from None


def _json_text(value, where: str) -> str:
    if type(value) is not str:
        raise _schema_error(where, "must be a string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise _schema_error(where, "must be valid Unicode text") from None
    return value


def _json_field(value, annotation, where: str):
    """One dataclass field from its OWN declared annotation. Optional
    fields are omitted, never null, so `Optional[X]` accepts only X."""
    base = annotation[len("Optional["):-1] if isinstance(annotation, str) and annotation.startswith("Optional[") \
        else annotation
    if base == "str":
        return _json_text(value, where)
    if base == "tuple":
        if type(value) is not list:
            raise _schema_error(where, "must be a JSON array")
        return tuple(_json_text(item, f"{where}[{index}]") for index, item in enumerate(value))
    if base not in _JSON_TYPES:
        raise _schema_error(where, "has no supported JSON form")
    accepted, label = _JSON_TYPES[base]
    if type(value) not in accepted:
        raise _schema_error(where, f"must be {label}")
    return value


def _json_dataclass(value, cls, where: str, special: dict):
    """`cls(**kwargs)` with exactly `cls`'s own init fields: no unknown,
    missing-required or defaulted key; nothing is dropped or rewritten."""
    if type(value) is not dict:
        raise _schema_error(where, "must be a JSON object")
    fields = {f.name: f for f in dataclasses.fields(cls) if f.init}
    unknown = sum(1 for key in value if key not in fields)
    if unknown:
        raise _schema_error(where, f"has {unknown} unsupported key(s)")
    missing = [
        name for name, f in fields.items()
        if f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING and name not in value
    ]
    if missing:
        raise _schema_error(where, f"is missing required key(s): {', '.join(missing)}")
    kwargs = {}
    for name, f in fields.items():
        if name in value:
            convert = special.get(name)
            kwargs[name] = convert(value[name], f"{where}.{name}") if convert \
                else _json_field(value[name], f.type, f"{where}.{name}")
    return cls(**kwargs)


def _json_nodes(value, where: str) -> tuple:
    if type(value) is not list:
        raise _schema_error(where, "must be a JSON array")
    return tuple(
        _json_dataclass(item, blueprints.BlueprintNode, f"{where}[{index}]", {}) for index, item in enumerate(value)
    )


def _json_provider_limits(value, where: str) -> tuple:
    if type(value) is not list:
        raise _schema_error(where, "must be a JSON array")
    pairs = []
    for index, pair in enumerate(value):
        label = f"{where}[{index}]"
        if type(pair) is not list or len(pair) != 2:
            raise _schema_error(label, "must be a [provider_id, limit] array")
        pairs.append((_json_text(pair[0], f"{label}[0]"), _json_field(pair[1], "int", f"{label}[1]")))
    return tuple(pairs)


def parse_blueprint_bytes(data: bytes) -> "blueprints.DagBlueprint":
    """Bounded bytes of a blueprint file -> the existing frozen
    `DagBlueprint`, or `CLIError`. Typed conversion only (module docstring)."""
    if len(data) > BLUEPRINT_FILE_MAX_BYTES:
        raise _blueprint_error("BLUEPRINT_FILE_TOO_LARGE", f"--blueprint-file exceeds {BLUEPRINT_FILE_MAX_BYTES} bytes")
    return _json_dataclass(
        _decode_blueprint_json(data), blueprints.DagBlueprint, "blueprint",
        {"nodes": _json_nodes, "provider_limits": _json_provider_limits},
    )


def _blueprint_from_args(args: argparse.Namespace) -> "blueprints.DagBlueprint":
    return parse_blueprint_bytes(_read_blueprint_bytes(args.blueprint_file))


def _cmd_submit_blueprint(args: argparse.Namespace, service: "director.FabricDirectorService"):
    # Submission-only: persists the governed binding, executes nothing.
    return dataclasses.asdict(service.submit_blueprint(_blueprint_from_args(args)))


def _cmd_submit_run_blueprint(args: argparse.Namespace, service: "director.FabricDirectorService"):
    # Submit once, run once with the in-memory handle submit returned;
    # argparse requires the separate RUN_BLUEPRINT confirmation.
    handle = service.submit_blueprint(_blueprint_from_args(args))
    return dataclasses.asdict(service.run_blueprint(handle))


def _cmd_result_blueprint(args: argparse.Namespace, service: "director.FabricDirectorService"):
    return dataclasses.asdict(service.result_blueprint(args.run_id))


def _add_global_service_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--state-root", default=None,
        help="Override FabricDirectorService(state_root=...). Default: service default.",
    )
    parser.add_argument(
        "--factory-root", default=None,
        help="Override FabricDirectorService(factory_root=...). Default: service default.",
    )
    parser.add_argument(
        "--no-factory-ledger", dest="no_factory_ledger", action="store_true", default=False,
        help="Disable factory ledger events for runs started by this invocation.",
    )
    parser.add_argument(
        "--director-root", default=None,
        help="Override FabricDirectorService(director_root=...). Default: service default.",
    )
    parser.add_argument(
        "--self-worktree", default=None,
        help="Override FabricDirectorService(self_worktree=...). Default: service default.",
    )


def _add_spec_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--worktree", required=True, help="Target Git repository/worktree root.")
    parser.add_argument(
        "--work-order-file", dest="work_order_file", required=True,
        help="Path to a UTF-8 text file containing the Work Order. Read verbatim; never rewritten.",
    )
    parser.add_argument(
        "--mode", choices=[director.providers.MODE_READ_ONLY, director.providers.MODE_WRITE], default=None,
        help="Execution mode. Default: DirectorWorkOrderSpec default (read-only).",
    )
    parser.add_argument(
        "--provider", default=None, metavar="ID",
        help="Execution provider id. Default: DirectorWorkOrderSpec default.",
    )
    parser.add_argument("--model", default=None, help="Optional model override.")
    parser.add_argument(
        "--authorize-path", dest="authorize_path", action="append", default=None, metavar="PATH",
        help="Authorized write-scope path/glob. Repeatable.",
    )
    parser.add_argument(
        "--capability", dest="capability", action="append", default=None, metavar="CAPABILITY",
        help="Required provider capability (e.g. SHELL). Repeatable.",
    )
    parser.add_argument(
        "--allow-shell", dest="allow_shell", action="store_true", default=False,
        help="Explicit opt-in into shell-class provider capabilities. Default: disabled.",
    )
    parser.add_argument("--checkpoint-policy", dest="checkpoint_policy", default=None, help="Optional checkpoint policy.")
    parser.add_argument(
        "--timeout-seconds", dest="timeout_seconds", type=int, default=None,
        help="Optional per-attempt timeout in seconds.",
    )
    parser.add_argument(
        "--metadata", action="append", default=None, metavar="KEY=VALUE",
        help="Opaque string metadata entry. Repeatable.",
    )
    parser.add_argument(
        "--acceptance-command", dest="acceptance_command", action="append", default=None, metavar="COMMAND",
        help=(
            "Runner-owned acceptance command, repeatable. Each command runs synchronously in the target "
            "worktree, after provider work and before an ON_SUCCESS checkpoint, through the same governed "
            "process-supervision transport a provider invocation uses; every command must exit zero. Only "
            "consulted when --completion-policy=runner_acceptance (ignored otherwise). Default: none."
        ),
    )
    parser.add_argument(
        "--completion-policy", dest="completion_policy", default=None,
        choices=[
            director.claude_runner.COMPLETION_POLICY_PROVIDER_VERDICT,
            director.claude_runner.COMPLETION_POLICY_RUNNER_ACCEPTANCE,
        ],
        help=(
            "Completion certification policy. 'provider_verdict' (default: DirectorWorkOrderSpec default) "
            "never changes existing behavior - a missing/invalid provider VERDICT is always a failure. "
            "'runner_acceptance' additionally permits a missing/invalid VERDICT to be superseded by "
            "passing --acceptance-command results; requires at least one --acceptance-command."
        ),
    )
    parser.add_argument(
        "--audit", action="store_true", default=False,
        help=(
            "First-class read-only AUDIT PROFILE: a safe, fixed expansion into mode=read-only, "
            "authorize_paths=[], allow_shell=False, checkpoint_policy=None, "
            "completion_policy=runner_acceptance (the provider gets read/search capability only - never "
            "edit/write/shell - and Runner's own --acceptance-command execution is the sole success "
            "certification). Requires at least one --acceptance-command. Rejected BEFORE submission if "
            "combined with an explicit, incompatible --mode, --authorize-path, --allow-shell, "
            "--checkpoint-policy, or --completion-policy other than 'runner_acceptance'."
        ),
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fabric_director_cli",
        description=(
            "Host-facing CLI over the existing FabricDirectorService - the "
            "same governed Director -> PipelineRunner -> Runner path, "
            "reachable without a throwaway Python wrapper. Machine-readable "
            "JSON on stdout is the output contract; non-zero exit on any "
            "DirectorError, governed PipelineError or CLI validation failure."
        ),
    )
    _add_global_service_args(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_project_state = subparsers.add_parser(
        "project-state", help="Project compact git state (branch/head/clean) for a worktree.",
    )
    p_project_state.add_argument("--worktree", required=True)
    p_project_state.set_defaults(handler=_cmd_project_state)

    p_submit = subparsers.add_parser(
        "submit", help="Submit a Work Order (persists it + a manifest); does not execute it.",
    )
    _add_spec_args(p_submit)
    p_submit.set_defaults(handler=_cmd_submit)

    p_submit_run = subparsers.add_parser(
        "submit-run", help="Submit a Work Order and run it to completion (the canonical A1 execution command).",
    )
    _add_spec_args(p_submit_run)
    p_submit_run.set_defaults(handler=_cmd_submit_run)

    p_status = subparsers.add_parser("status", help="Read a pipeline's durable status.")
    p_status.add_argument("--run-id", dest="run_id", required=True)
    p_status.set_defaults(handler=_cmd_status)

    p_result = subparsers.add_parser("result", help="Project a pipeline's compact DirectorRunSummary.")
    p_result.add_argument("--run-id", dest="run_id", required=True)
    p_result.set_defaults(handler=_cmd_result)

    p_evidence = subparsers.add_parser("evidence", help="Project durable Runner evidence as JSON (read-only).")
    p_evidence.add_argument("--run-id", dest="run_id", required=True)
    p_evidence.set_defaults(handler=_cmd_evidence)

    p_decision = subparsers.add_parser("decision", help="Project the existing deterministic Director decision as JSON (read-only).")
    p_decision.add_argument("--run-id", dest="run_id", required=True)
    p_decision.set_defaults(handler=_cmd_decision)

    p_recover = subparsers.add_parser(
        "recover-submit", help="Explicitly submit (never execute) a governed recovery pipeline."
    )
    p_recover.add_argument("--prior-run-id", required=True)
    p_recover.add_argument("--work-order-file", required=True,
                           help="New UTF-8 recovery Work Order; original is never reused.")
    p_recover.add_argument("--action", choices=["RESUME_WORK_PRODUCT"], required=True,
                           help="Mandatory explicit host recovery authorization.")
    p_recover.add_argument("--prior-worker-id", default=None)
    p_recover.add_argument("--provider", default=None)
    p_recover.add_argument("--model", default=None)
    p_recover.add_argument("--authorize-path", action="append", default=None,
                           help="Optional replacement scope (validated by Director).")
    p_recover.add_argument("--capability", action="append", default=None)
    p_recover.add_argument("--allow-shell", action="store_true", default=False)
    p_recover.add_argument("--checkpoint-policy", default=None)
    p_recover.add_argument("--timeout-seconds", type=int, default=None)
    p_recover.add_argument("--metadata", action="append", default=None)
    p_recover.add_argument(
        "--completion-policy", dest="completion_policy", default=None,
        choices=[
            director.claude_runner.COMPLETION_POLICY_PROVIDER_VERDICT,
            director.claude_runner.COMPLETION_POLICY_RUNNER_ACCEPTANCE,
        ],
        help=(
            "Explicit recovery completion certification. Omitted: the prior worker's own policy and "
            "acceptance commands are carried forward from Runner's manifest snapshot. Downgrading a "
            "runner_acceptance prior run to provider_verdict is refused."
        ),
    )
    p_recover.add_argument(
        "--acceptance-command", dest="acceptance_command", action="append", default=None, metavar="COMMAND",
        help=(
            "Runner-owned acceptance command, repeatable; replaces (never extends) the prior run's "
            "commands. Requires a runner_acceptance policy (explicit or carried forward)."
        ),
    )
    p_recover.set_defaults(handler=_cmd_recover_submit)

    p_recover_run = subparsers.add_parser(
        "recover-run", help="Explicitly submit and execute a governed recovery in one process.",
        parents=[p_recover], add_help=False,
    )
    # argparse's documented parents mechanism reuses the exact recovery
    # option contract; no independent parser or validation rules.
    p_recover_run.add_argument(
        "--execute-confirm", choices=["RUN_RECOVERY"], required=True,
        help="Additional, explicit confirmation before starting Runner execution.",
    )
    p_recover_run.set_defaults(handler=_cmd_recover_run)

    p_assess = subparsers.add_parser(
        "assess-integration",
        help="Read-only FCP-1B integration assessment of a feature worktree (never integrates anything).",
    )
    p_assess.add_argument("--worktree", required=True, help="Candidate feature worktree.")
    p_assess.add_argument(
        "--attested-sha", dest="attested_sha", default=None, metavar="SHA",
        help="Host-attested commit of the remote integration branch. Omitted: base is unattested (fail-closed).",
    )
    p_assess.add_argument(
        "--authorize-path", dest="authorize_path", action="append", default=None, metavar="PATH",
        help="Authorized change-scope path/glob. Repeatable. Omitted: scope unproven (never eligible).",
    )
    p_assess.add_argument(
        "--expected-remote-url", dest="expected_remote_url", default=None, metavar="URL",
        help="Optional exact expected remote.origin.url.",
    )
    p_assess.add_argument(
        "--evidence-file", dest="evidence_file", default=None, metavar="PATH",
        help=(
            "UTF-8 JSON run evidence (run_id, decision_code, safety_verdict, evidence_complete, head_sha, "
            "branch_ref, optional worktree), passed verbatim. Omitted: evidence missing (fail-closed)."
        ),
    )
    p_assess.set_defaults(handler=_cmd_assess_integration)

    p_reconcile = subparsers.add_parser(
        "assess-reconciliation",
        help=(
            "Read-only FCP-2B reconciliation analysis (+ optional PROPOSED review plan) of a feature "
            "worktree; never reconciles, executes or approves anything."
        ),
        parents=[p_assess], add_help=False,
    )
    # Same parents mechanism as recover-run: the exact assess-integration
    # host inputs, with no independent parser or validation rules.
    p_reconcile.add_argument(
        "--max-paths", dest="max_paths", type=int, default=None, metavar="N",
        help=(
            f"Path-record bound for the analysis, 1..{director.reconciliation.MAX_PATHS}. Out-of-range "
            f"values are refused, never clamped. Default: the core's own ({director.reconciliation.MAX_PATHS})."
        ),
    )
    p_reconcile.add_argument(
        "--acceptance-command", dest="acceptance_command", action="append", default=None, metavar="COMMAND",
        help=(
            "Host-supplied acceptance command for an OPTIONAL proposed review plan, repeatable; kept "
            "verbatim and NEVER run. Omitted: plan is null. Empty/duplicate/multi-line commands are refused."
        ),
    )
    p_reconcile.set_defaults(handler=_cmd_assess_reconciliation)

    p_inventory = subparsers.add_parser(
        "inventory-worktrees",
        help=(
            "Read-only FCP-4C-01 inventory and ownership check of every registered worktree; never "
            "prunes, removes, moves, locks or unlocks anything and authorizes nothing."
        ),
    )
    p_inventory.add_argument(
        "--repository", required=True, help="Any worktree of the repository whose worktrees are inventoried.",
    )
    p_inventory.set_defaults(handler=_cmd_inventory_worktrees)

    p_retirement = subparsers.add_parser(
        "assess-worktree-retirement",
        help=(
            "Read-only FCP-4D-02 retirement ASSESSMENT of every registered worktree; never prunes, "
            "removes, locks or unlocks anything, writes no report and authorizes nothing."
        ),
    )
    p_retirement.add_argument(
        "--repository", required=True, help="Any worktree of the repository whose worktrees are assessed.",
    )
    p_retirement.add_argument(
        "--queue-root", action="append", default=None,
        help="A queue root to consult (repeatable). Only declared roots are ever read.",
    )
    p_retirement.add_argument(
        "--queue-roots-complete", action="store_true", default=False,
        help="Host claim that the declared queue roots are the complete known set (recorded verbatim).",
    )
    p_retirement.set_defaults(handler=_cmd_assess_worktree_retirement)

    blueprint_format = textwrap.fill(
        f"--blueprint-file: a regular UTF-8 JSON file (no BOM, at most {BLUEPRINT_FILE_MAX_BYTES} bytes) holding "
        "one object with exactly the fabric_dag_blueprint.DagBlueprint fields - required pipeline_id and nodes; "
        "optional max_workers, provider_limits ([[provider_id, limit], ...]), not_before_utc, deadline_utc. Each "
        "node has exactly the BlueprintNode fields - required id, worktree, work_order, provider, mode, depends_on; "
        "optional " + ", ".join(
            f.name for f in dataclasses.fields(blueprints.BlueprintNode) if f.default is not dataclasses.MISSING
        ) + ". Optional keys are omitted, never null; unknown or repeated keys and wrong JSON types are refused "
        "before the Director is called. Graph, path, provider, mode and policy checks are the Director's/Runner's.",
        width=79,
    ) + "\n\nExample:\n" + BLUEPRINT_JSON_EXAMPLE
    p_submit_blueprint = subparsers.add_parser(
        "submit-blueprint",
        help="Submit a 2+ Work Order DAG blueprint (persists the governed binding); does not execute it.",
        description=blueprint_format, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_submit_blueprint.add_argument(
        "--blueprint-file", dest="blueprint_file", required=True, metavar="PATH",
        help="Path to the JSON blueprint declaration. Read once; never rewritten or echoed.",
    )
    p_submit_blueprint.set_defaults(handler=_cmd_submit_blueprint)

    p_submit_run_blueprint = subparsers.add_parser(
        "submit-run-blueprint",
        help="Submit a DAG blueprint and run it once through the existing Director/Runner in one process.",
        description=blueprint_format, formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[p_submit_blueprint], add_help=False,
    )
    p_submit_run_blueprint.add_argument(
        "--execute-confirm", choices=["RUN_BLUEPRINT"], required=True,
        help="Additional, explicit confirmation before starting Runner execution. Authorizes nothing else.",
    )
    p_submit_run_blueprint.set_defaults(handler=_cmd_submit_run_blueprint)

    p_result_blueprint = subparsers.add_parser(
        "result-blueprint",
        help="Project a Director DAG run's aggregate and every worker's Runner evidence as JSON (read-only).",
    )
    p_result_blueprint.add_argument("--run-id", dest="run_id", required=True, help="Director DAG pipeline id.")
    p_result_blueprint.set_defaults(handler=_cmd_result_blueprint)

    return parser


def main(argv: Optional[list] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    try:
        service = _build_service(args)
        payload = args.handler(args, service)
    except director.DirectorError as exc:
        print(f"error: {exc.code}: {exc.message}", file=sys.stderr)
        return 1
    except director.pipeline.PipelineError as exc:
        # FCP-FIX-09: a governed Runner refusal/condition (e.g. unknown
        # run id, corrupt pipeline state, refused lease). Same message
        # shape and exit code as the runner_pipeline CLI; Runner remains
        # the authority - this only reports it. Anything else propagates.
        print(f"error: {exc.code}: {exc.message}", file=sys.stderr)
        return director.pipeline.EXIT_PIPELINE_REFUSED
    except CLIError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
