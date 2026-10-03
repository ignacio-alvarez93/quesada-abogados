"""FDB-4A1: thin, provider-neutral host CLI over the EXISTING
`FabricDirectorService` (see `fabric_director.py`).

Why this is a CLI wrapper, not a second engine
------------------------------------------------
Every command below does nothing but (1) parse CLI arguments into the
SAME dataclasses `FabricDirectorService` already accepts
(`DirectorWorkOrderSpec`), (2) call the corresponding EXISTING service
method (`project_state`, `submit`, `submit_and_run`, `status`, `result`),
and (3) serialize the EXISTING return value (a dict, or a dataclass via
`dataclasses.asdict`) to stdout as JSON. It never:

* builds a manifest, parses one, or calls `runner_pipeline` itself -
  `FabricDirectorService.submit`/`submit_and_run` do that;
* projects evidence or computes a decision - out of scope for A1;
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
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path
from typing import Optional

try:
    from scripts.ai import fabric_director as director
except ImportError:  # pragma: no cover - direct script execution
    _this_dir = Path(__file__).resolve().parent
    if str(_this_dir) not in sys.path:
        sys.path.insert(0, str(_this_dir))
    import fabric_director as director  # type: ignore[no-redef]


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
    return director.FabricDirectorService(**kwargs)


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
    # Only arguments the host actually supplied are forwarded; every
    # omitted field falls through to DirectorWorkOrderSpec's OWN default
    # (never a value duplicated/guessed here), so CLI defaults always
    # match the dataclass's defaults by construction.
    spec_kwargs: dict = {
        "worktree": args.worktree,
        "work_order_text": _read_work_order_text(args.work_order_file),
        "authorize_paths": list(args.authorize_path or []),
        "required_capabilities": list(args.capability or []),
        "allow_shell": args.allow_shell,
        "metadata": _parse_metadata(args.metadata),
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


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fabric_director_cli",
        description=(
            "Host-facing CLI over the existing FabricDirectorService - the "
            "same governed Director -> PipelineRunner -> Runner path, "
            "reachable without a throwaway Python wrapper. Machine-readable "
            "JSON on stdout is the output contract; non-zero exit on any "
            "DirectorError or CLI validation failure."
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
    except CLIError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
