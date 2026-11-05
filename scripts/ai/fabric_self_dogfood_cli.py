"""FCP-12A-06: Self-Dogfood operator CLI - read-only, deterministic,
fail-closed, OBSERVATION-ONLY report of one governed self-dogfood attempt.

    python -m scripts.ai.fabric_self_dogfood_cli \
        --query status|evidence|readiness \
        --state-root DIR --factory-root DIR \
        --pipeline-id ID --worker-id ID --observed-target-head SHA \
        [--max-file-bytes N] [--format json|text]

A thin argument adapter over FCP-12A-03 `read_evidence`: the Runner state
root and the factory ledger root are the ONLY sources, read with that
module's bounded, link-safe, identity-checked reads. The observed target
HEAD is the caller's (captured with governed Git, e.g. FCP-12A-02); the CLI
runs no Git, no provider, no network, no clock and writes nothing.

Queries
-------
* `status`    - what the Runner RECORDED (`runner_state`, attempt, provider,
  checkpoint) next to this reader's `evidence_verdict`. A Runner SUCCESS is
  only a Runner record: `runner_success_is_certification` is always false.
* `evidence`  - the full FCP-12A-03 `SelfDogfoodEvidence` (codes, ids,
  commits, digests, counts; never a path or provider prose).
* `readiness` - `LOCAL_EVIDENCE_CORROBORATED` or `BLOCKED`. Even the best
  answer is NOT end-to-end certification: the FCP-12A-02 isolation
  confirmation and FCP-12A-05 certification (which need the governed Git
  snapshots this CLI never takes), host CI on a PR, the existing FCP-3 human
  authorization and the final host audit are always listed as pending.

No action flags exist. `--promote`, `--merge`, `--push` (and any other
action-looking flag) are refused before parsing with exit 2: promotion stays
behind the existing FCP-3 human authorization, never behind this CLI.

The reader is imported only after the arguments parsed: `--help` and usage
errors open no root, ledger or file.

Output and exit codes
---------------------
Stdout is canonical ASCII JSON (`--format json`, default) or sorted
`path: value` lines (`--format text`). Errors go to stderr only as
`error: <CODE>: <fixed text>` - never a path, id, value or traceback.

0 = answered and the Runner evidence is CORROBORATED; 1 = answered but the
evidence is not corroborated (report on stdout, fail closed) or an internal
fault (nothing on stdout); 2 = usage error, forbidden action flag or a
request the reader rejects as malformed (nothing on stdout). Exit 0 is
ADVISORY: it certifies, authorizes, promotes or merges nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

# Same deterministic repository-root bootstrap as `fabric_control_plane_cli`.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

SCHEMA = "fcp12a06-self-dogfood-cli-v1"
SCHEMA_VERSION = 1
CLI_MARKER = "FCP12A06_SELF_DOGFOOD_CLI_READ_ONLY_NOT_CERTIFIED_NOT_AUTHORIZED"

# The evidence reader version this CLI was reviewed against (pinned by tests).
SUPPORTED_EVIDENCE_SCHEMA = "fcp12a03-self-dogfood-evidence-v1"
SUPPORTED_EVIDENCE_SCHEMA_VERSION = 1

QUERY_STATUS = "status"
QUERY_EVIDENCE = "evidence"
QUERY_READINESS = "readiness"
QUERIES = (QUERY_STATUS, QUERY_EVIDENCE, QUERY_READINESS)
FORMAT_JSON = "json"
FORMAT_TEXT = "text"

READINESS_LOCAL_CORROBORATED = "LOCAL_EVIDENCE_CORROBORATED"
READINESS_BLOCKED = "BLOCKED"
READINESS_STATES = (READINESS_LOCAL_CORROBORATED, READINESS_BLOCKED)

# Always pending, whatever the local answer: the CLI never takes Git
# snapshots (FCP-12A-02 / -05) and never reads host CI or authorizations.
# The last three mirror `fabric_self_dogfood_certification.PENDING_HOST_REQUIREMENTS`
# (pinned by the tests) so that `--help` needs no sibling import.
PENDING_REQUIREMENTS = (
    "FCP12A02_ISOLATION_CONFIRMATION", "FCP12A05_CERTIFICATION", "HOST_CI_ON_PULL_REQUEST",
    "FCP3_HUMAN_AUTHORIZATION", "FINAL_HOST_AUDIT",
)
HOST_CI_UNKNOWN = "UNKNOWN"
HUMAN_AUTHORIZATION_NONE = "NONE"

# Action-looking flags that must never exist; refused before argparse so the
# refusal is explicit rather than a generic usage error.
FORBIDDEN_FLAGS = (
    "--promote", "--merge", "--push", "--commit", "--checkout", "--reset", "--approve", "--authorize",
    "--certify", "--close", "--release", "--retry", "--resume", "--dispatch", "--run", "--execute", "--write",
)

EXIT_OK = 0
EXIT_NOT_CORROBORATED = 1
EXIT_USAGE = 2

_USAGE = ("error: SELF_DOGFOOD_CLI_USAGE_INVALID: expected --query QUERY --state-root DIR --factory-root DIR "
          "--pipeline-id ID --worker-id ID --observed-target-head SHA [read-only options]; see --help\n")
_FORBIDDEN = ("error: SELF_DOGFOOD_CLI_ACTION_FORBIDDEN: this CLI is read-only; promotion, merge and push stay "
              "behind the existing FCP-3 human authorization\n")
_REQUEST_INVALID = "error: SELF_DOGFOOD_CLI_REQUEST_INVALID: the evidence reader rejected the request"
_INTERNAL = "error: SELF_DOGFOOD_CLI_INTERNAL_ERROR: fail closed"

_CLI_GUARANTEES = {
    "cli_marker": CLI_MARKER, "provider_executed": False, "git_invoked": False, "network_used": False,
    "promotion_available": False, "merge_available": False, "push_available": False,
    "end_to_end_certified": False, "runner_success_is_certification": False,
}


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message):  # never echo argument values (paths, ids)
        self.exit(EXIT_USAGE, _USAGE)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        prog="fabric_self_dogfood_cli", allow_abbrev=False,
        description="Read-only FCP-12 self-dogfood status / evidence / readiness from local Runner sources. "
                    "Never runs a provider or Git, never writes, promotes, merges or pushes.",
    )
    parser.add_argument("--query", required=True, choices=QUERIES, help="the read query")
    parser.add_argument("--state-root", required=True, help="absolute Runner state root")
    parser.add_argument("--factory-root", required=True, help="absolute factory ledger root (events.jsonl)")
    parser.add_argument("--pipeline-id", required=True, help="pipeline id")
    parser.add_argument("--worker-id", required=True, help="worker id")
    parser.add_argument("--observed-target-head", required=True,
                        help="target HEAD (40/64 hex) the caller observed with governed Git")
    parser.add_argument("--max-file-bytes", type=int, default=None, help="per-file read bound (<= reader cap)")
    parser.add_argument("--format", choices=(FORMAT_JSON, FORMAT_TEXT), default=FORMAT_JSON,
                        help="compact canonical JSON (default) or path: value lines")
    return parser


def _forbidden(argv: list) -> bool:
    for token in argv:
        if type(token) is str and token.split("=", 1)[0].lower() in FORBIDDEN_FLAGS:
            return True
    return False


def _status(evidence) -> dict:
    return {
        "runner_state": evidence.runner_state, "evidence_verdict": evidence.evidence_verdict,
        "pipeline_id": evidence.pipeline_id, "worker_id": evidence.worker_id, "attempt": evidence.attempt,
        "attempt_leaf": evidence.attempt_leaf, "provider_id": evidence.provider_id,
        "attempt_base_head": evidence.attempt_base_head, "completion_mode": evidence.completion_mode,
        "checkpoint_commit": evidence.checkpoint_commit, "reasons": list(evidence.reasons),
    }


def _readiness(evidence) -> dict:
    corroborated = evidence.corroborated
    return {
        "readiness": READINESS_LOCAL_CORROBORATED if corroborated else READINESS_BLOCKED,
        "evidence_verdict": evidence.evidence_verdict, "runner_state": evidence.runner_state,
        "audit_verdict": evidence.audit_verdict, "authorization": evidence.authorization,
        "host_ci_status": HOST_CI_UNKNOWN, "human_authorization": HUMAN_AUTHORIZATION_NONE,
        "expected_target_head": evidence.expected_target_head, "reasons": list(evidence.reasons),
        "pending_requirements": list(PENDING_REQUIREMENTS),
    }


def build_report(query: str, evidence) -> dict:
    """The CLI report for one query over one `SelfDogfoodEvidence`."""
    from scripts.ai import fabric_self_dogfood_evidence as ev

    if type(evidence) is not ev.SelfDogfoodEvidence or query not in QUERIES:
        raise TypeError("build_report needs a known query and a SelfDogfoodEvidence")
    if query == QUERY_STATUS:
        body = _status(evidence)
    elif query == QUERY_READINESS:
        body = _readiness(evidence)
    else:
        body = ev.SelfDogfoodEvidence.to_dict(evidence)
    report = {"schema": SCHEMA, "schema_version": SCHEMA_VERSION, "query": query, query: body}
    # Reader guarantees first, CLI guarantees last: neither can be loosened.
    report.update(ev._EvidenceGuarantees._guarantees())
    report.update(_CLI_GUARANTEES)
    return report


def render_json(report: dict) -> str:
    return json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _flatten(prefix: str, value, out: list) -> None:
    if isinstance(value, dict):
        if not value:
            out.append((prefix, "{}"))
        for key in sorted(value):
            _flatten(f"{prefix}.{key}" if prefix else key, value[key], out)
    elif isinstance(value, list):
        if not value:
            out.append((prefix, "[]"))
        for index, item in enumerate(value):
            _flatten(f"{prefix}[{index}]", item, out)
    else:
        out.append((prefix, json.dumps(value, ensure_ascii=True)))


def render_text(report: dict) -> str:
    lines: list = []
    _flatten("", report, lines)
    return "\n".join(f"{path}: {value}" for path, value in lines)


def main(argv: Optional[list] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if _forbidden(argv):
        sys.stderr.write(_FORBIDDEN)
        return EXIT_USAGE
    args = build_arg_parser().parse_args(argv)
    try:
        from scripts.ai import fabric_self_dogfood_evidence as ev

        if (ev.SCHEMA, ev.SCHEMA_VERSION) != (SUPPORTED_EVIDENCE_SCHEMA, SUPPORTED_EVIDENCE_SCHEMA_VERSION):
            raise RuntimeError("evidence reader version unsupported")
        extra = {} if args.max_file_bytes is None else {"max_file_bytes": args.max_file_bytes}
        evidence = ev.read_evidence(ev.EvidenceRequest(
            schema_version=ev.SCHEMA_VERSION, state_root=args.state_root, factory_root=args.factory_root,
            pipeline_id=args.pipeline_id, worker_id=args.worker_id, observed_target_head=args.observed_target_head,
            **extra))
        if evidence.decision == ev.INVALID_REQUEST:
            print(_REQUEST_INVALID, file=sys.stderr)
            return EXIT_USAGE
        report = build_report(args.query, evidence)
        payload = render_text(report) if args.format == FORMAT_TEXT else render_json(report)
    except Exception:  # noqa: BLE001 - fail closed without a traceback or leaked bytes
        print(_INTERNAL, file=sys.stderr)
        return EXIT_NOT_CORROBORATED
    print(payload)
    return EXIT_OK if evidence.corroborated else EXIT_NOT_CORROBORATED


if __name__ == "__main__":
    sys.exit(main())
