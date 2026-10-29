"""FCP-7C-01: governed routed-execution host CLI over the EXISTING FCP-7B
provider routing gateway and the EXISTING `FabricDirectorService`.

Why this is a CLI entry point, not a new execution machine
-----------------------------------------------------------
* Selection is computed ONLY by `fabric_provider_router_gateway.
  route_work_order` (which defers to the FCP-7A policy). This module never
  ranks, filters, scores or substitutes a provider itself.
* The ONLY dispatch is one call to `FabricDirectorService.submit_and_run(
  DirectorWorkOrderSpec(...))`, which descends to `PipelineRunner`. Nothing
  here builds a manifest, calls `runner_pipeline`/`claude_runner` directly,
  starts a shell or a provider, retries, falls back, or keeps a store or
  ledger of its own. The Runner (preflight, provider lock, quota/auth holds,
  limits, worktree lease, checkpoint, evidence) stays the execution authority
  and re-validates everything.

`route-preview`
---------------
Reads an explicit Work Order file, the host's explicit execution flags and a
routing file (Direction preference/pin, lock facts and caller-vouched
availability/capacity observations - see `ROUTING_JSON_EXAMPLE`), asks the
gateway for a proposal and prints it with its reason, exclusions, issues,
provenance and an informational `selected_provider`. It also prints a
`binding_sha256`: the sha256 of the canonical binding of the Work Order
bytes, the target worktree string, every execution flag, the routing input
and the gateway result. Preview constructs no Director, touches no worktree,
writes nothing and grants nothing. No eligible provider (including missing
or unreliable auth/quota/capacity facts, which degrade to UNKNOWN) is a
structured refusal with exit `EXIT_ROUTE_REFUSED`.

`route-submit-run`
------------------
Same inputs, plus three host confirmations that are all required:
`--execute-confirm RUN_ROUTED_WORK_ORDER`, `--expect-binding-sha256` (the
preview's binding) and `--expect-provider` (the provider the host read).
The gateway is re-run FRESH just before dispatch (adapter probe, policy and
capabilities under the exact requested policy) and the binding recomputed;
any difference - Work Order bytes, worktree, flags, preference, pin, locks,
observations, adapter facts, rationale - refuses with `BINDING_MISMATCH`.
Confirming the command is not certifying the proposal: dispatch is also
refused when nothing is selected, when the selection is not the expected
provider, or when a prior attempt already executed (that is a governed
recovery, `fabric_director_cli recover-run`, never a new routed submission
and never a provider switch). On any refusal the Director is never
constructed. Otherwise exactly one `submit_and_run` runs with the selected
provider and EXACTLY the host's `mode`, `allow_shell`, capabilities,
`authorize_paths`, model, checkpoint, timeout, completion policy and
acceptance commands - the selection never widens any of them. Host metadata
is passed verbatim plus the reserved `ROUTE_METADATA_KEYS` provenance (a host
key colliding with them is refused). Runner's status is reported verbatim.

Exit codes: 0 a proposal was selected (preview) or the Director returned a
summary (submit-run; read its status); `EXIT_ROUTE_REFUSED` structured
refusal on stdout, nothing dispatched; 1 input error or `DirectorError` on
stderr; `runner_pipeline.EXIT_PIPELINE_REFUSED` a governed Runner refusal.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import sys
from pathlib import Path
from typing import Callable, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.ai import fabric_director_cli as director_cli
from scripts.ai import fabric_provider_router_gateway as gateway

director = director_cli.director
providers = director.providers
CLIError = director_cli.CLIError

PREVIEW_SCHEMA = "fcp7c01-route-preview-v1"
SUBMIT_SCHEMA = "fcp7c01-route-submit-run-v1"
BINDING_SCHEMA = "fcp7c01-routed-binding-v1"
SCHEMA_VERSION = 1
CLI_MARKER = "FCP7C01_ROUTE_IS_A_PROPOSAL_DISPATCH_ONLY_VIA_DIRECTOR_ON_EXPLICIT_HOST_CONFIRMATION"
EXECUTE_CONFIRMATION = "RUN_ROUTED_WORK_ORDER"

EXIT_OK = 0
EXIT_INPUT_ERROR = 1
EXIT_ROUTE_REFUSED = 3

ROUTING_FILE_MAX_BYTES = 64 * 1024
WORK_ORDER_FILE_MAX_BYTES = 1024 * 1024
_UTF8_BOM = b"\xef\xbb\xbf"

# Dispatch refusal codes (ordered; nothing is dispatched when any is present).
ROUTE_NOT_SELECTED = "ROUTE_NOT_SELECTED"
PRIOR_ATTEMPT_REQUIRES_GOVERNED_RECOVERY = "PRIOR_ATTEMPT_REQUIRES_GOVERNED_RECOVERY"
CONFIRMATION_INVALID = "CONFIRMATION_INVALID"
BINDING_MISMATCH = "BINDING_MISMATCH"
EXPECTED_PROVIDER_MISMATCH = "EXPECTED_PROVIDER_MISMATCH"
DISPATCH_REFUSALS = (
    ROUTE_NOT_SELECTED, PRIOR_ATTEMPT_REQUIRES_GOVERNED_RECOVERY, CONFIRMATION_INVALID, BINDING_MISMATCH,
    EXPECTED_PROVIDER_MISMATCH,
)

# Provenance the CLI adds to the dispatched Work Order's metadata.
META_BINDING = "fcp7c_route_binding_sha256"
META_RATIONALE = "fcp7c_route_rationale"
META_SELECTED = "fcp7c_route_selected_provider"
ROUTE_METADATA_KEYS = (META_BINDING, META_RATIONALE, META_SELECTED)

_ROUTING_REQUIRED_KEYS = ("preference_order", "observations")
_ROUTING_OPTIONAL_KEYS = {
    "pinned_provider": str, "owner_provider": str, "prior_attempt_executed": bool, "provider_locked": bool,
}
_OBSERVATION_KEYS = ("provider_id", "availability", "capacity", "source")

ROUTING_JSON_EXAMPLE = """\
{
  "preference_order": ["claude", "codex"],
  "observations": [
    {"provider_id": "claude", "availability": "NONE", "capacity": "AVAILABLE",
     "source": "DIRECTION_DECLARED"},
    {"provider_id": "codex", "availability": "UNKNOWN", "capacity": "UNKNOWN",
     "source": "RUNNER_STATE_OBSERVED"}
  ]
}"""


# ---------------------------------------------------------------------------
# Inputs (typed conversion only; every value decision is the gateway's)
# ---------------------------------------------------------------------------

def _input_error(code: str, message: str) -> CLIError:
    return CLIError(f"{code}: {message}")


def _read_bounded(path: str, limit: int, code_prefix: str, flag: str) -> bytes:
    file_path = Path(path)
    try:
        if not file_path.is_file():
            raise _input_error(f"{code_prefix}_FILE_UNREADABLE", f"{flag} is not a regular file")
        with file_path.open("rb") as handle:
            data = handle.read(limit + 1)
    except OSError as exc:
        raise _input_error(
            f"{code_prefix}_FILE_UNREADABLE", f"cannot read {flag}: {exc.strerror or type(exc).__name__}",
        ) from None
    if len(data) > limit:
        raise _input_error(f"{code_prefix}_FILE_TOO_LARGE", f"{flag} exceeds {limit} bytes")
    return data


def read_work_order(path: str) -> tuple:
    """(text, sha256 of the exact bytes). The text dispatched is decoded from
    the same bytes that are hashed - no newline translation."""
    data = _read_bounded(path, WORK_ORDER_FILE_MAX_BYTES, "WORK_ORDER", "--work-order-file")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _input_error("WORK_ORDER_FILE_NOT_UTF8", f"invalid UTF-8 at byte offset {exc.start}") from None
    if not text.strip():
        raise _input_error("WORK_ORDER_EMPTY", "--work-order-file holds no Work Order text")
    return text, hashlib.sha256(data).hexdigest()


def _reject_duplicate_keys(pairs: list) -> dict:
    obj: dict = {}
    for key, value in pairs:
        if key in obj:
            raise _input_error("ROUTING_JSON_DUPLICATE_KEY", "a JSON object repeats a key")
        obj[key] = value
    return obj


def _reject_constant(_name: str):
    raise _input_error("ROUTING_JSON_INVALID", "NaN/Infinity are not JSON numbers")


def _schema_error(where: str, message: str) -> CLIError:
    return _input_error("ROUTING_SCHEMA_INVALID", f"{where} {message}")


def _str_list(value, where: str) -> tuple:
    if type(value) is not list:
        raise _schema_error(where, "must be a JSON array")
    for index, item in enumerate(value):
        if type(item) is not str:
            raise _schema_error(f"{where}[{index}]", "must be a string")
    return tuple(value)


def _exact_keys(value, where: str, required, optional=()) -> None:
    if type(value) is not dict:
        raise _schema_error(where, "must be a JSON object")
    unknown = sum(1 for key in value if key not in required and key not in optional)
    if unknown:
        raise _schema_error(where, f"has {unknown} unsupported key(s)")
    missing = [key for key in required if key not in value]
    if missing:
        raise _schema_error(where, f"is missing required key(s): {', '.join(missing)}")


def parse_routing_bytes(data: bytes) -> dict:
    """Bounded bytes of a routing file -> {"config", "observations",
    "lock": {...}}; typed conversion only, or `CLIError`."""
    if len(data) > ROUTING_FILE_MAX_BYTES:
        raise _input_error("ROUTING_FILE_TOO_LARGE", f"--routing-file exceeds {ROUTING_FILE_MAX_BYTES} bytes")
    if data.startswith(_UTF8_BOM):
        raise _input_error("ROUTING_FILE_NOT_UTF8", "a UTF-8 byte order mark is not supported")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _input_error("ROUTING_FILE_NOT_UTF8", f"invalid UTF-8 at byte offset {exc.start}") from None
    try:
        raw = json.loads(text, object_pairs_hook=_reject_duplicate_keys, parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        raise _input_error("ROUTING_JSON_INVALID", f"line {exc.lineno} column {exc.colno}: {exc.msg}") from None
    except RecursionError:
        raise _input_error("ROUTING_JSON_INVALID", "JSON nesting is too deep") from None

    _exact_keys(raw, "routing", _ROUTING_REQUIRED_KEYS, _ROUTING_OPTIONAL_KEYS)
    lock = {"prior_attempt_executed": False, "provider_locked": False, "owner_provider": None}
    pinned = None
    for key, kind in _ROUTING_OPTIONAL_KEYS.items():
        if key not in raw:
            continue
        if type(raw[key]) is not kind:
            raise _schema_error(f"routing.{key}", "must be a string" if kind is str else "must be a boolean")
        if key == "pinned_provider":
            pinned = raw[key]
        else:
            lock[key] = raw[key]
    order = _str_list(raw["preference_order"], "routing.preference_order")
    if type(raw["observations"]) is not list:
        raise _schema_error("routing.observations", "must be a JSON array")
    observations = []
    for index, entry in enumerate(raw["observations"]):
        where = f"routing.observations[{index}]"
        _exact_keys(entry, where, _OBSERVATION_KEYS)
        for key in _OBSERVATION_KEYS:
            if type(entry[key]) is not str:
                raise _schema_error(f"{where}.{key}", "must be a string")
        observations.append(gateway.ProviderObservation(**{key: entry[key] for key in _OBSERVATION_KEYS}))
    return {
        "config": gateway.DirectionRoutingConfig(preference_order=order, pinned_provider=pinned),
        "observations": tuple(observations),
        "lock": lock,
    }


def _host_metadata(args: argparse.Namespace) -> dict:
    metadata = director_cli._parse_metadata(args.metadata)
    reserved = sorted(set(metadata) & set(ROUTE_METADATA_KEYS))
    if reserved:
        raise _input_error("ROUTE_METADATA_RESERVED", f"--metadata may not set reserved key(s): {', '.join(reserved)}")
    return metadata


def _execution_params(args: argparse.Namespace, metadata: dict) -> dict:
    """The host's explicit execution flags, exactly as dispatched."""
    return {
        "mode": args.mode, "allow_shell": args.allow_shell, "required_capabilities": list(args.capability or []),
        "authorize_paths": list(args.authorize_path or []), "model": args.model,
        "checkpoint_policy": args.checkpoint_policy, "timeout_seconds": args.timeout_seconds,
        "completion_policy": args.completion_policy, "acceptance_commands": list(args.acceptance_command or []),
        "metadata": dict(metadata),
    }


# ---------------------------------------------------------------------------
# Route + binding
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class RoutedProposal:
    """One fresh gateway proposal bound to one Work Order and its flags."""
    work_order_text: str
    worktree: str
    execution: dict
    lock: dict
    result: gateway.GatewayResult
    binding: dict
    binding_sha256: str

    @property
    def selected_provider(self) -> Optional[str]:
        return self.result.selected_provider

    def dispatch_blockers(self) -> tuple:
        """Refusals intrinsic to the proposal (no host confirmation yet)."""
        codes = []
        if self.result.selected_provider is None:
            codes.append(ROUTE_NOT_SELECTED)
        if self.lock["prior_attempt_executed"] is True:
            codes.append(PRIOR_ATTEMPT_REQUIRES_GOVERNED_RECOVERY)
        return tuple(codes)


def _canonical(payload) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def build_proposal(args: argparse.Namespace, *, registry=None) -> RoutedProposal:
    """Reads the explicit inputs and asks the gateway for a FRESH proposal.
    Read-only: no Director, no worktree access, nothing written."""
    text, wo_sha = read_work_order(args.work_order_file)
    routing = parse_routing_bytes(_read_bounded(args.routing_file, ROUTING_FILE_MAX_BYTES, "ROUTING", "--routing-file"))
    execution = _execution_params(args, _host_metadata(args))
    lock = routing["lock"]
    intent = gateway.WorkOrderRoutingIntent(
        mode=execution["mode"], allow_shell=execution["allow_shell"],
        required_capabilities=tuple(execution["required_capabilities"]),
        prior_attempt_executed=lock["prior_attempt_executed"], provider_locked=lock["provider_locked"],
        owner_provider=lock["owner_provider"],
    )
    config = routing["config"]
    result = gateway.route_work_order(intent, config, routing["observations"], registry=registry)
    binding = {
        "schema": BINDING_SCHEMA, "schema_version": SCHEMA_VERSION, "work_order_sha256": wo_sha,
        "worktree": args.worktree, "execution": execution,
        "routing": {
            "preference_order": list(config.preference_order), "pinned_provider": config.pinned_provider,
            **lock, "observations": [dataclasses.asdict(o) for o in routing["observations"]],
        },
        "route": result.to_dict(),
    }
    return RoutedProposal(
        work_order_text=text, worktree=args.worktree, execution=execution, lock=lock, result=result,
        binding=binding, binding_sha256=hashlib.sha256(_canonical(binding).encode("ascii")).hexdigest(),
    )


def _zero_authority() -> dict:
    return {
        "marker": CLI_MARKER, "certified": False, "authorizes_action": False, "auto_retry_allowed": False,
        "fallback_allowed": False, "merging_allowed": False, "provider_switch_authorized": False,
    }


def preview_payload(proposal: RoutedProposal) -> dict:
    blockers = proposal.dispatch_blockers()
    return {
        "schema": PREVIEW_SCHEMA, "schema_version": SCHEMA_VERSION, "rationale": proposal.result.rationale,
        "selected_provider": proposal.selected_provider, "binding_sha256": proposal.binding_sha256,
        "dispatch_blockers": list(blockers), "dispatched": False, "execution_allowed": False,
        "execute_confirmation": None if blockers else EXECUTE_CONFIRMATION,
        "binding": proposal.binding, **_zero_authority(),
    }


def confirmation_refusals(proposal: RoutedProposal, args: argparse.Namespace) -> tuple:
    """Every reason the host's confirmation does not cover THIS proposal."""
    codes = set(proposal.dispatch_blockers())
    if args.execute_confirm != EXECUTE_CONFIRMATION:
        codes.add(CONFIRMATION_INVALID)
    if args.expect_binding_sha256 != proposal.binding_sha256:
        codes.add(BINDING_MISMATCH)
    if proposal.selected_provider is None or args.expect_provider != proposal.selected_provider:
        codes.add(EXPECTED_PROVIDER_MISMATCH)
    return tuple(sorted(codes, key=DISPATCH_REFUSALS.index))


def build_director_spec(proposal: RoutedProposal) -> "director.DirectorWorkOrderSpec":
    """The one DirectorWorkOrderSpec: selected provider + the host's flags
    verbatim. Only arguments the host gave are forwarded; the rest fall
    through to the dataclass's own defaults."""
    ex = proposal.execution
    metadata = dict(ex["metadata"])
    metadata.update({
        META_BINDING: proposal.binding_sha256, META_RATIONALE: proposal.result.rationale,
        META_SELECTED: proposal.selected_provider,
    })
    kwargs: dict = {
        "worktree": proposal.worktree, "work_order_text": proposal.work_order_text, "mode": ex["mode"],
        "provider": proposal.selected_provider, "allow_shell": ex["allow_shell"],
        "required_capabilities": list(ex["required_capabilities"]), "authorize_paths": list(ex["authorize_paths"]),
        "metadata": metadata, "acceptance_commands": list(ex["acceptance_commands"]),
    }
    for key in ("model", "checkpoint_policy", "timeout_seconds", "completion_policy"):
        if ex[key] is not None:
            kwargs[key] = ex[key]
    return director.DirectorWorkOrderSpec(**kwargs)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def _cmd_route_preview(args, *, registry, service_factory) -> tuple:
    proposal = build_proposal(args, registry=registry)
    payload = preview_payload(proposal)
    return (EXIT_ROUTE_REFUSED if proposal.selected_provider is None else EXIT_OK), payload


def _cmd_route_submit_run(args, *, registry, service_factory) -> tuple:
    proposal = build_proposal(args, registry=registry)
    refusals = confirmation_refusals(proposal, args)
    base = {
        "schema": SUBMIT_SCHEMA, "schema_version": SCHEMA_VERSION, "rationale": proposal.result.rationale,
        "selected_provider": proposal.selected_provider, "binding_sha256": proposal.binding_sha256,
        "expected_binding_sha256": args.expect_binding_sha256, "expected_provider": args.expect_provider,
    }
    if refusals:
        return EXIT_ROUTE_REFUSED, {
            **base, "dispatched": False, "refusal_codes": list(refusals), "binding": proposal.binding,
            **_zero_authority(),
        }
    spec = build_director_spec(proposal)
    service = service_factory(args)
    summary = service.submit_and_run(spec)
    return EXIT_OK, {
        **base, "dispatched": True, "refusal_codes": [], "route": proposal.binding["route"],
        "summary": dataclasses.asdict(summary), **_zero_authority(),
    }


def _add_routed_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--worktree", required=True, help="Target Git repository/worktree root (bound, not read).")
    parser.add_argument(
        "--work-order-file", dest="work_order_file", required=True,
        help="UTF-8 Work Order file; its exact bytes are hashed into the binding and dispatched verbatim.",
    )
    parser.add_argument(
        "--routing-file", dest="routing_file", required=True,
        help="JSON routing input (preference, pin, locks, observations); see the module docstring.",
    )
    parser.add_argument(
        "--mode", required=True, choices=[providers.MODE_READ_ONLY, providers.MODE_WRITE],
        help="Explicit execution mode (no default): routed and dispatched exactly.",
    )
    parser.add_argument(
        "--allow-shell", dest="allow_shell", action="store_true", default=False,
        help="Explicit shell opt-in. Never enabled by the selected provider.",
    )
    parser.add_argument("--capability", action="append", default=None, metavar="CAPABILITY",
                        help="Required provider capability. Repeatable.")
    parser.add_argument("--authorize-path", dest="authorize_path", action="append", default=None, metavar="PATH",
                        help="Authorized write-scope path/glob. Repeatable. Never widened.")
    parser.add_argument("--model", default=None, help="Optional explicit model. Never derived from the selection.")
    parser.add_argument("--checkpoint-policy", dest="checkpoint_policy", default=None)
    parser.add_argument("--timeout-seconds", dest="timeout_seconds", type=int, default=None)
    parser.add_argument("--metadata", action="append", default=None, metavar="KEY=VALUE",
                        help="Opaque string metadata, passed verbatim. Repeatable.")
    parser.add_argument(
        "--completion-policy", dest="completion_policy", default=None,
        choices=[
            director.claude_runner.COMPLETION_POLICY_PROVIDER_VERDICT,
            director.claude_runner.COMPLETION_POLICY_RUNNER_ACCEPTANCE,
        ],
    )
    parser.add_argument("--acceptance-command", dest="acceptance_command", action="append", default=None,
                        metavar="COMMAND", help="Runner-owned acceptance command. Repeatable.")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fabric_provider_router_cli",
        description=(
            "Governed routed execution: preview an FCP-7B routing proposal for a new Work Order, and only on "
            "explicit host confirmation dispatch it once through FabricDirectorService.submit_and_run."
        ),
    )
    director_cli._add_global_service_args(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_preview = subparsers.add_parser(
        "route-preview", help="Read-only routing proposal + binding; never dispatches.",
        description="Routing file example:\n" + ROUTING_JSON_EXAMPLE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_routed_args(p_preview)
    p_preview.set_defaults(handler=_cmd_route_preview)

    p_submit = subparsers.add_parser(
        "route-submit-run", help="Re-route fresh and, on matching confirmation, submit_and_run exactly once.",
        description="Routing file example:\n" + ROUTING_JSON_EXAMPLE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_routed_args(p_submit)
    p_submit.add_argument("--execute-confirm", dest="execute_confirm", choices=[EXECUTE_CONFIRMATION], required=True,
                          help="Explicit host confirmation for THIS routed Work Order. Authorizes nothing else.")
    p_submit.add_argument("--expect-binding-sha256", dest="expect_binding_sha256", required=True, metavar="SHA256",
                          help="The binding_sha256 printed by route-preview for the same inputs.")
    p_submit.add_argument("--expect-provider", dest="expect_provider", required=True, metavar="ID",
                          help="The provider the host confirms; must equal the fresh selection.")
    p_submit.set_defaults(handler=_cmd_route_submit_run)
    return parser


def main(argv: Optional[list] = None, *, registry=None, service_factory: Optional[Callable] = None) -> int:
    """`registry` (gateway adapter facts) and `service_factory(args)` are
    injection points; by default the native registry and the Director CLI's
    own service construction are used."""
    args = build_arg_parser().parse_args(argv)
    factory = service_factory if service_factory is not None else director_cli._build_service
    try:
        code, payload = args.handler(args, registry=registry, service_factory=factory)
    except director.DirectorError as exc:
        print(f"error: {exc.code}: {exc.message}", file=sys.stderr)
        return EXIT_INPUT_ERROR
    except director.pipeline.PipelineError as exc:
        print(f"error: {exc.code}: {exc.message}", file=sys.stderr)
        return director.pipeline.EXIT_PIPELINE_REFUSED
    except CLIError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR
    print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
