"""FCP-11G-07: Fabric Control Plane operator CLI - read-only, deterministic,
fail-closed, OBSERVATION-ONLY.

    python -m scripts.ai.fabric_control_plane_cli \
        --query summary|pipelines|worker|activity|attention|resources \
        --allowed-root DIR [--allowed-root DIR ...] --state-root DIR \
        --observed-at-utc UTC [--factory-root DIR] [--report-file FILE] \
        [--pipeline-id ID] [--worker-id ID] [--event-type TYPE] \
        [--offset N] [--limit N] [--format json|text]

A thin argument adapter over `fabric_control_plane_gateway.query`: every
answer, refusal, limit and field allowlist is the gateway's, so the CLI and
the Python API give byte-equal JSON for the same request. Only read flags
exist: no watch / daemon / server mode, no write, retry, resume, dispatch or
Git action. The instant is the caller's `--observed-at-utc` (no clock).

The gateway (and through it every projection) is imported only after the
arguments parsed: `--help` and usage errors open no root, ledger, report,
endpoint or provider.

Output and exit codes
---------------------
Stdout is the gateway's canonical ASCII JSON (`--format json`, default) or
its `path: value` token lines (`--format text`). Refusals go to stderr only as
`error: <CODE>: <fixed text>` - never a path, id, value or traceback.

0 = answered (whatever the observed states: the answer is ADVISORY and
certifies, authorizes or dispatches nothing); 1 = refused (nothing on
stdout); 2 = usage error.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

# Same deterministic repository-root bootstrap as `fabric_scheduler_cli`.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Mirrors `fabric_control_plane_gateway.QUERIES` (pinned by the tests) so that
# `--help` needs no gateway import.
QUERIES = ("summary", "pipelines", "worker", "activity", "attention", "resources")
FORMAT_JSON = "json"
FORMAT_TEXT = "text"

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_USAGE = 2

_USAGE = ("error: GATEWAY_USAGE_INVALID: expected --query QUERY --allowed-root DIR --state-root DIR "
          "--observed-at-utc UTC [read-only options]; see --help\n")


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message):  # never echo argument values (paths, ids)
        self.exit(EXIT_USAGE, _USAGE)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        prog="fabric_control_plane_cli", allow_abbrev=False,
        description="Read-only FCP-11 control plane queries over explicit allowed roots. Observation only: never "
                    "dispatches, retries, resumes, writes, watches, serves HTTP, calls a network or touches Git.",
    )
    parser.add_argument("--query", required=True, choices=QUERIES, help="the read query")
    parser.add_argument("--allowed-root", required=True, action="append", dest="allowed_roots",
                        help="absolute plain directory every source must lie in (repeatable)")
    parser.add_argument("--state-root", required=True, help="absolute Runner state root")
    parser.add_argument("--observed-at-utc", required=True, help="explicit observation instant, e.g. "
                                                                 "2026-11-03T12:00:00Z")
    parser.add_argument("--factory-root", help="absolute factory ledger root (activity)")
    parser.add_argument("--report-file", help="absolute FCP-10D-01 input document (resources)")
    parser.add_argument("--pipeline-id", help="filter / subject pipeline id")
    parser.add_argument("--worker-id", help="filter / subject worker id")
    parser.add_argument("--event-type", help="ledger event type filter (activity)")
    parser.add_argument("--offset", type=int, default=0, help="page offset")
    parser.add_argument("--limit", type=int, default=None, help="page size")
    parser.add_argument("--format", choices=(FORMAT_JSON, FORMAT_TEXT), default=FORMAT_JSON,
                        help="compact canonical JSON (default) or path: value lines")
    return parser


def main(argv: Optional[list] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    from scripts.ai import fabric_control_plane_gateway as gw

    extra = {} if args.limit is None else {"limit": args.limit}
    request = gw.GatewayRequest(
        args.query, tuple(args.allowed_roots), args.state_root, args.observed_at_utc,
        factory_root=args.factory_root, report_file=args.report_file, pipeline_id=args.pipeline_id,
        worker_id=args.worker_id, event_type=args.event_type, offset=args.offset, **extra,
    )
    try:
        response = gw.query(request)
        payload = gw.render_text(response) if args.format == FORMAT_TEXT else gw.render_json(response)
    except gw.GatewayError as exc:
        print(exc.render(), file=sys.stderr)
        return EXIT_USAGE if exc.usage else EXIT_REFUSED
    except Exception:  # noqa: BLE001 - fail closed without a traceback or leaked bytes
        print(gw.GatewayError("GATEWAY_INTERNAL_ERROR").render(), file=sys.stderr)
        return EXIT_REFUSED
    print(payload)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
