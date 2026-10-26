"""FCP-4E-02a: worktree retirement PROPOSAL contracts (non-live, pure).

Answers ONE question, without changing or reading anything: "does this
already-assessed CANDIDATE_FOR_HUMAN_REVIEW, together with the original
inventory record that names its exact Git identity, form one internally
consistent, fully scoped proposal a human could later consider?" It is NOT
an approval, authorization, permit or execution capability. No code path
here issues, signs, stores or consumes anything, starts a process, calls
Git, takes a queue lock or lease, opens a ledger or touches the filesystem
(paths are compared as strings only: `os.path.normpath`/`normcase`).
`RETIREMENT_AUTHORIZATION_LIVE` and `RETIREMENT_EXECUTION_CAPABLE` are
constant False, and every proposal carries `authorizes_action=False`,
`deletion_authorized=False`, `issued=False`,
`host_identity_authenticated=False` and `queue_scope_attested=False`
(fixed, not constructor arguments).

Inputs (all untrusted)
----------------------
* `runner_worktree_retirement.RetirementReport`: must be COMPLETE, with no
  global errors, two COMPLETE inventories with identical fingerprints, the
  source LIMITATIONS verbatim and exactly one record for the target key.
  The report does NOT carry the per-worktree Git identity (git_dir,
  HEAD sha, object format), so it can never be a proposal on its own.
* `runner_worktree_inventory.WorktreeRecord`: the original FCP-4C record of
  the target, which supplies that identity. Its fingerprint must equal
  BOTH record fingerprints the assessment recorded.
* `host_id`: a caller label, never an authenticated host identity.
Both classifications are recomputed with the real pure classifiers
(`classify_retirement`, `classify_record`); a record that does not
reproduce itself exactly is refused as tampered. That proves internal
consistency ONLY: anyone can build facts that classify as a CANDIDATE, so
a proposal is never a trusted certificate. A later trusted host must
re-read every fact itself.

Known residual limitations (`PROPOSAL_LIMITATIONS`)
---------------------------------------------------
* The report fingerprint is carried verbatim but not recomputed: its
  formula resolves paths on the filesystem. `report_content_digest` is a
  pure digest of the whole report instead.
* Path keys are string-normalized, never resolved: symlink, junction or
  8.3 aliases of a root are not detected here.
* `object_format` is outside the inventory record fingerprint; it is only
  checked for consistency with the HEAD sha length.
* The worktree directory's file object id (st_dev, st_ino) is not
  available from the report and is left absent/unverified.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    from scripts.ai import claude_runner
    from scripts.ai import runner_worktree_inventory as inv
    from scripts.ai import runner_worktree_retirement as wr
except ImportError:  # pragma: no cover - direct script execution
    _this_dir = Path(__file__).resolve().parent
    if str(_this_dir) not in sys.path:
        sys.path.insert(0, str(_this_dir))
    import claude_runner  # type: ignore[no-redef]
    import runner_worktree_inventory as inv  # type: ignore[no-redef]
    import runner_worktree_retirement as wr  # type: ignore[no-redef]


RETIREMENT_AUTHORIZATION_LIVE = False
RETIREMENT_EXECUTION_CAPABLE = False

TARGET_SCHEMA = "fcp4e02a-retirement-target-identity-v1"
SCOPE_SCHEMA = "fcp4e02a-retirement-scope-v1"
PROPOSAL_SCHEMA = "fcp4e02a-retirement-proposal-v1"

# What a pure proposal can never establish (in addition to the source
# assessment LIMITATIONS, which are carried verbatim).
PROPOSAL_LIMITATIONS = (
    "HOST_IDENTITY_NOT_AUTHENTICATED",
    "QUEUE_SCOPE_NOT_ATTESTED",
    "REPORT_FINGERPRINT_NOT_RECOMPUTED",
    "PATH_ALIASES_NOT_RESOLVED",
    "OBJECT_FORMAT_OUTSIDE_RECORD_FINGERPRINT",
    "FILE_OBJECT_ID_NOT_VERIFIED",
    "GIT_STATE_NOT_RECHECKED",
    "CALLER_CRAFTED_CANDIDATE_INDISTINGUISHABLE",
)

# Stable refusal codes.
REFUSED_SCHEMA = "REFUSED_SCHEMA"
REFUSED_UNTRUSTED_FIELD = "REFUSED_UNTRUSTED_FIELD"
REFUSED_LIMITATIONS_ALTERED = "REFUSED_LIMITATIONS_ALTERED"
REFUSED_INCOMPLETE = "REFUSED_INCOMPLETE"
REFUSED_TAMPERED = "REFUSED_TAMPERED"
REFUSED_TARGET_ABSENT = "REFUSED_TARGET_ABSENT"
REFUSED_AMBIGUOUS = "REFUSED_AMBIGUOUS"
REFUSED_BLOCKED = "REFUSED_BLOCKED"
REFUSED_INSUFFICIENT_EVIDENCE = "REFUSED_INSUFFICIENT_EVIDENCE"
REFUSED_REVIEW_REQUIRED = "REFUSED_REVIEW_REQUIRED"
REFUSED_UNKNOWN_CLASSIFICATION = "REFUSED_UNKNOWN_CLASSIFICATION"
REFUSED_IDENTITY_INCOMPLETE = "REFUSED_IDENTITY_INCOMPLETE"
REFUSED_IDENTITY_MISMATCH = "REFUSED_IDENTITY_MISMATCH"
REFUSED_PROTECTED_TARGET = "REFUSED_PROTECTED_TARGET"
REFUSED_SCOPE_MISSING = "REFUSED_SCOPE_MISSING"
REFUSED_SCOPE_ALIAS = "REFUSED_SCOPE_ALIAS"
REFUSED_SCOPE_OVERLAP = "REFUSED_SCOPE_OVERLAP"

REFUSAL_CODES = (
    REFUSED_SCHEMA, REFUSED_UNTRUSTED_FIELD, REFUSED_LIMITATIONS_ALTERED, REFUSED_INCOMPLETE, REFUSED_TAMPERED,
    REFUSED_TARGET_ABSENT, REFUSED_AMBIGUOUS, REFUSED_BLOCKED, REFUSED_INSUFFICIENT_EVIDENCE,
    REFUSED_REVIEW_REQUIRED, REFUSED_UNKNOWN_CLASSIFICATION, REFUSED_IDENTITY_INCOMPLETE,
    REFUSED_IDENTITY_MISMATCH, REFUSED_PROTECTED_TARGET, REFUSED_SCOPE_MISSING, REFUSED_SCOPE_ALIAS,
    REFUSED_SCOPE_OVERLAP,
)

# Stable `validate_proposal_against_report` findings (besides REFUSAL_CODES).
PROPOSAL_TYPE_INVALID = "PROPOSAL_TYPE_INVALID"
PROPOSAL_SCHEMA_MISMATCH = "PROPOSAL_SCHEMA_MISMATCH"
PROPOSAL_FLAG_ALTERED = "PROPOSAL_FLAG_ALTERED"
TARGET_DIGEST_MISMATCH = "TARGET_DIGEST_MISMATCH"
SCOPE_DIGEST_MISMATCH = "SCOPE_DIGEST_MISMATCH"
PROPOSAL_DIGEST_MISMATCH = "PROPOSAL_DIGEST_MISMATCH"
TARGET_MISMATCH = "TARGET_MISMATCH"
SCOPE_MISMATCH = "SCOPE_MISMATCH"
PROPOSAL_CONTENT_MISMATCH = "PROPOSAL_CONTENT_MISMATCH"

_CLASS_REFUSALS = {
    wr.BLOCKED: REFUSED_BLOCKED,
    wr.INSUFFICIENT_EVIDENCE: REFUSED_INSUFFICIENT_EVIDENCE,
    wr.REVIEW_REQUIRED: REFUSED_REVIEW_REQUIRED,
}

_SHA_LENGTHS = {"sha1": 40, "sha256": 64}
_HEADS = "refs/heads/"
_HOST_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")


class RetirementProposalRefused(Exception):
    """Fail-closed refusal: no proposal object exists when this is raised."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


# ---------------------------------------------------------------------------
# Schemas (immutable)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RetirementTargetIdentity:
    """Exact identity of ONE worktree as the caller's inventory record
    states it. Every field is an untrusted label until a host re-reads it."""

    schema: str
    host_id_label: str
    worktree_key: str
    path: str
    worktree_top: str
    git_dir: str
    common_dir: str
    admin_entry: str
    head_ref: str
    head_sha: str
    listed_branch: str
    listed_head: str
    object_format: str
    inventory_record_fingerprint: str
    assessment_fingerprint: str
    identity_digest: str
    file_object_id: None = field(default=None, init=False)
    file_object_id_verified: bool = field(default=False, init=False)
    host_identity_authenticated: bool = field(default=False, init=False)


@dataclass(frozen=True)
class RetirementScope:
    """Report-derived roots the proposal is bound to, as string-normalized
    keys. `queue_roots_complete_claim` is the host's claim, recorded
    verbatim and never verified or attested here."""

    schema: str
    requested_path: str
    repository_top: str
    common_dir: str
    state_root: str
    ledger_root: str
    lease_root: Optional[str]
    self_worktree: str
    governed_roots: tuple
    queue_roots: tuple
    queue_roots_complete_claim: bool
    scope_digest: str
    queue_roots_complete_claim_verified: bool = field(default=False, init=False)
    queue_scope_attested: bool = field(default=False, init=False)


@dataclass(frozen=True)
class RetirementProposal:
    """A non-authorizing proposal for a HUMAN to consider. It carries no
    eligibility, permit or execution capability and no trusted time."""

    schema: str
    target: RetirementTargetIdentity
    scope: RetirementScope
    report_fingerprint: str
    report_content_digest: str
    assessment_classification: str
    limitations: tuple
    advisories: tuple
    proposal_limitations: tuple
    proposal_digest: str
    human_review_required: bool = field(default=True, init=False)
    authorizes_action: bool = field(default=False, init=False)
    deletion_authorized: bool = field(default=False, init=False)
    human_command_present: bool = field(default=False, init=False)
    issued: bool = field(default=False, init=False)
    host_identity_authenticated: bool = field(default=False, init=False)
    queue_scope_attested: bool = field(default=False, init=False)


_PROPOSAL_FLAGS = (
    ("human_review_required", True), ("authorizes_action", False), ("deletion_authorized", False),
    ("human_command_present", False), ("issued", False), ("host_identity_authenticated", False),
    ("queue_scope_attested", False),
)
_TARGET_FLAGS = (("file_object_id", None), ("file_object_id_verified", False),
                 ("host_identity_authenticated", False))
_SCOPE_FLAGS = (("queue_roots_complete_claim_verified", False), ("queue_scope_attested", False))


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def _refuse(code: str, detail: str):
    raise RetirementProposalRefused(code, detail)


def _jsonable(value):
    if isinstance(value, tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if value is None or isinstance(value, (str, bool, int)):
        return value
    raise TypeError(f"not a canonical value: {type(value).__name__}")


def _digest(payload) -> str:
    canonical = json.dumps(_jsonable(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _material(obj, digest_field: str) -> dict:
    """Every field of a schema object except its own digest (nested schema
    objects are represented by their digests, which cover them)."""
    out = {}
    for f in dataclasses.fields(obj):
        if f.name == digest_field:
            continue
        value = getattr(obj, f.name)
        if isinstance(value, RetirementTargetIdentity):
            value = value.identity_digest
        elif isinstance(value, RetirementScope):
            value = value.scope_digest
        out[f.name] = value
    return out


def identity_digest(target: RetirementTargetIdentity) -> str:
    return _digest(_material(target, "identity_digest"))


def scope_digest(scope: RetirementScope) -> str:
    return _digest(_material(scope, "scope_digest"))


def proposal_digest(proposal: RetirementProposal) -> str:
    return _digest(_material(proposal, "proposal_digest"))


def _is_label(value) -> bool:
    return isinstance(value, str) and bool(value) and value == value.strip() and "\0" not in value


def _path_key(value) -> Optional[str]:
    """String-normalized comparison key of an absolute path, or None. Never
    touches the filesystem (no resolve: aliases are NOT detected)."""
    if not _is_label(value) or not os.path.isabs(value):
        return None
    if os.name == "nt" and not os.path.splitdrive(value)[0]:
        return None
    return os.path.normcase(os.path.normpath(value))


def _within(child: str, parent: str) -> bool:
    prefix = parent if parent.endswith(os.sep) else parent + os.sep
    return child == parent or child.startswith(prefix)


def _overlaps(a: str, b: str) -> bool:
    return _within(a, b) or _within(b, a)


def _content_digest(report) -> str:
    try:
        return _digest({"schema": PROPOSAL_SCHEMA, "report": dataclasses.asdict(report)})
    except (TypeError, ValueError) as exc:
        _refuse(REFUSED_UNTRUSTED_FIELD, f"report is not canonical data: {exc}")


# ---------------------------------------------------------------------------
# Checks (pure, fail-closed)
# ---------------------------------------------------------------------------

def _check_report(report) -> None:
    if type(report) is not wr.RetirementReport:
        _refuse(REFUSED_SCHEMA, "report is not a RetirementReport")
    if report.schema != wr.SCHEMA or report.classification_precedence != wr.CLASSIFICATION_PRECEDENCE:
        _refuse(REFUSED_SCHEMA, "report schema or classification precedence differs from the source")
    if report.limitations != wr.LIMITATIONS:
        _refuse(REFUSED_LIMITATIONS_ALTERED, "report limitations differ from the source constant")
    if (report.human_review_required is not True or report.authorizes_action is not False
            or report.deletion_authorized is not False):
        _refuse(REFUSED_UNTRUSTED_FIELD, "report safety flags altered")
    if type(report.queue_roots_complete_claim) is not bool:
        _refuse(REFUSED_UNTRUSTED_FIELD, "queue_roots_complete_claim is not a bool")
    if not _is_label(report.fingerprint):
        _refuse(REFUSED_INCOMPLETE, "report fingerprint is missing")
    if not isinstance(report.records, tuple) or not isinstance(report.global_errors, tuple):
        _refuse(REFUSED_SCHEMA, "report records/global_errors are not tuples")
    if any(type(r) is not wr.WorktreeRetirementAssessment or type(r.facts) is not wr.RetirementFacts
           for r in report.records):
        _refuse(REFUSED_SCHEMA, "report record is not a WorktreeRetirementAssessment")
    if report.status != wr.REPORT_COMPLETE or report.global_errors:
        _refuse(REFUSED_INCOMPLETE, f"report status {report.status!r} with {len(report.global_errors)} global error(s)")
    if (report.first_inventory_status != inv.INVENTORY_COMPLETE
            or report.second_inventory_status != inv.INVENTORY_COMPLETE):
        _refuse(REFUSED_INCOMPLETE, "an inventory is not COMPLETE")
    if not _is_label(report.first_inventory_fingerprint) or (
            report.first_inventory_fingerprint != report.second_inventory_fingerprint):
        _refuse(REFUSED_INCOMPLETE, "inventory fingerprints are missing or changed between inventories")
    if report.counts != wr._counts(report.records):
        _refuse(REFUSED_TAMPERED, "report counts do not match its records")


def _select(report, key: str):
    keys = [r.worktree_key for r in report.records]
    if len(set(keys)) != len(keys):
        _refuse(REFUSED_AMBIGUOUS, "report contains duplicate worktree keys")
    matches = [r for r in report.records if r.worktree_key == key]
    if not matches:
        _refuse(REFUSED_TARGET_ABSENT, f"no report record for {key!r}")
    return matches[0]


def _check_assessment(report, assessment) -> None:
    if (assessment.human_review_required is not True or assessment.authorizes_action is not False
            or assessment.deletion_authorized is not False):
        _refuse(REFUSED_UNTRUSTED_FIELD, "assessment safety flags altered")
    if assessment.limitations != wr.LIMITATIONS:
        _refuse(REFUSED_LIMITATIONS_ALTERED, "assessment limitations differ from the source constant")
    if wr.classify_retirement(assessment.facts) != assessment:
        _refuse(REFUSED_TAMPERED, "assessment does not reproduce from its own facts")
    classification = assessment.classification
    if classification != wr.CANDIDATE_FOR_HUMAN_REVIEW:
        _refuse(_CLASS_REFUSALS.get(classification, REFUSED_UNKNOWN_CLASSIFICATION),
                f"classification {classification!r}: {', '.join(assessment.reason_codes)}")
    if assessment.reason_codes:
        _refuse(REFUSED_TAMPERED, "a CANDIDATE carries reason codes")
    f = assessment.facts
    if (f.first_inventory_status != report.first_inventory_status
            or f.second_inventory_status != report.second_inventory_status
            or f.queue_roots_complete_claim is not report.queue_roots_complete_claim
            or f.queue_roots_declared is not bool(report.queue_roots)):
        _refuse(REFUSED_IDENTITY_MISMATCH, "assessment facts disagree with the report")


def _check_record(record, assessment) -> None:
    if type(record) is not inv.WorktreeRecord:
        _refuse(REFUSED_SCHEMA, "inventory record is not a WorktreeRecord")
    if record.human_review_required is not True or record.authorizes_action is not False:
        _refuse(REFUSED_UNTRUSTED_FIELD, "inventory record safety flags altered")
    if record.duplicate_checkouts or record.pipeline_workers or record.ledger_open_workers:
        _refuse(REFUSED_BLOCKED, "inventory record has duplicate checkouts or bound workers")
    if inv.classify_record(record) != record:
        _refuse(REFUSED_TAMPERED, "inventory record does not reproduce its classification/fingerprint")
    f = assessment.facts
    if not _is_label(record.fingerprint) or not (
            record.fingerprint == f.first_record_fingerprint == f.second_record_fingerprint):
        _refuse(REFUSED_IDENTITY_MISMATCH, "inventory record fingerprint differs from the assessed fingerprints")
    if (record.path != assessment.path or record.classification != f.inventory_classification
            or record.classification != f.second_inventory_classification
            or record.reason_codes != f.inventory_reason_codes or record.advisories != f.inventory_advisories
            or record.lease_state != f.inventory_lease_state):
        _refuse(REFUSED_IDENTITY_MISMATCH, "inventory record disagrees with the assessment facts")
    if record.classification != inv.IDLE_CLEAN_UNBOUND or record.reason_codes:
        _refuse(REFUSED_INSUFFICIENT_EVIDENCE, f"inventory classification {record.classification!r}")
    if record.is_main or record.bare or record.protected_branch is not False:
        _refuse(REFUSED_PROTECTED_TARGET, "main, bare or protected-branch worktree")
    if (record.registered is not True or record.path_exists is not True or record.locked or record.prunable
            or record.detached is not False or record.listed_detached or record.clean is not True
            or record.read_errors or record.drift_reasons or record.runner_state_readable is not True):
        _refuse(REFUSED_BLOCKED, "inventory record is not registered, present, unlocked, attached and clean")
    for name in ("path", "worktree_top", "git_dir", "common_dir", "head_ref", "head_sha", "listed_branch",
                 "listed_head", "object_format"):
        if not _is_label(getattr(record, name)):
            _refuse(REFUSED_IDENTITY_INCOMPLETE, f"inventory record {name} is missing or blank")
    branch = record.head_ref[len(_HEADS):] if record.head_ref.startswith(_HEADS) else ""
    if not branch or record.listed_branch != record.head_ref:
        _refuse(REFUSED_IDENTITY_MISMATCH, "head_ref is not a branch or differs from the listed branch")
    if branch in claude_runner.PROTECTED_BRANCHES:
        _refuse(REFUSED_PROTECTED_TARGET, f"protected branch {branch!r}")
    length = _SHA_LENGTHS.get(record.object_format)
    if length is None or not re.fullmatch(f"[0-9a-f]{{{length}}}", record.head_sha):
        _refuse(REFUSED_IDENTITY_MISMATCH, "head_sha does not match the object format")
    if record.listed_head != record.head_sha:
        _refuse(REFUSED_IDENTITY_MISMATCH, "listed HEAD differs from HEAD")


def _target_keys(report, record) -> tuple:
    """(worktree_key, git_dir_key, common_dir_key, admin_entry). The linked
    worktree's admin dir must be `<common_dir>/worktrees/<entry>`."""
    key = record.worktree_key
    if _path_key(key) != key:
        _refuse(REFUSED_IDENTITY_MISMATCH, "worktree_key is not a canonical absolute key")
    if _path_key(record.worktree_top) != key or _path_key(record.path) != key:
        _refuse(REFUSED_IDENTITY_MISMATCH, "worktree path/top do not match the worktree key")
    common = _path_key(record.common_dir)
    git_dir = _path_key(record.git_dir)
    if common is None or git_dir is None or common != _path_key(report.common_dir):
        _refuse(REFUSED_IDENTITY_MISMATCH, "record common dir differs from the report common dir")
    admin_entry = os.path.basename(git_dir)
    if not admin_entry or os.path.dirname(git_dir) != os.path.normcase(os.path.join(common, "worktrees")):
        _refuse(REFUSED_IDENTITY_MISMATCH, "git_dir is not a linked-worktree admin entry of the common dir")
    return key, git_dir, common, admin_entry


def _build_scope(report, target_key: str, git_dir: str, common: str) -> RetirementScope:
    def required(name, value):
        k = _path_key(value)
        if k is None:
            _refuse(REFUSED_SCOPE_MISSING, f"{name} is missing or not an absolute path")
        return k

    requested = required("requested_path", report.requested_path)
    top = required("repository_top", report.repository_top)
    state = required("state_root", report.state_root)
    ledger = required("ledger_root", report.ledger_root)
    lease = None if report.lease_root is None else required("lease_root", report.lease_root)
    self_wt = required("self_worktree", report.self_worktree)
    if not isinstance(report.queue_roots, tuple) or not report.queue_roots:
        _refuse(REFUSED_SCOPE_MISSING, "no declared queue roots")
    if not isinstance(report.governed_roots, tuple):
        _refuse(REFUSED_SCOPE_MISSING, "governed_roots is not a tuple")
    queues = tuple(required("queue_root", q) for q in report.queue_roots)
    governed = tuple(required("governed_root", g) for g in report.governed_roots)
    if report.queue_roots_complete_claim is not True:
        _refuse(REFUSED_SCOPE_MISSING, "queue roots were not claimed complete")

    named = [("state_root", state), ("ledger_root", ledger), ("self_worktree", self_wt)]
    named += [("lease_root", lease)] if lease is not None else []
    named += [("queue_root", q) for q in queues] + [("governed_root", g) for g in governed]
    keys = [k for _, k in named]
    if len(set(keys)) != len(keys):
        _refuse(REFUSED_SCOPE_ALIAS, "two scope roots share one canonical key")
    for kind, k in named + [("common_dir", common)]:
        if _overlaps(k, target_key):
            _refuse(REFUSED_SCOPE_OVERLAP, f"target overlaps {kind}")
    if _within(top, target_key) or _overlaps(git_dir, target_key):
        _refuse(REFUSED_SCOPE_OVERLAP, "target is or encloses the repository top, or overlaps its admin dir")

    staged = RetirementScope(
        schema=SCOPE_SCHEMA, requested_path=requested, repository_top=top, common_dir=common,
        state_root=state, ledger_root=ledger, lease_root=lease, self_worktree=self_wt,
        governed_roots=tuple(sorted(governed)), queue_roots=tuple(sorted(queues)),
        queue_roots_complete_claim=True, scope_digest="",
    )
    return dataclasses.replace(staged, scope_digest=scope_digest(staged))


# ---------------------------------------------------------------------------
# Public pure interface
# ---------------------------------------------------------------------------

def build_retirement_proposal(report, inventory_record, *, host_id: str) -> RetirementProposal:
    """Pure, fail-closed proposal for the ONE report record selected by
    `inventory_record.worktree_key`. Raises RetirementProposalRefused on
    any doubt. The result authorizes nothing and proves nothing to a host."""
    try:
        return _build(report, inventory_record, host_id)
    except RetirementProposalRefused:
        raise
    except (TypeError, ValueError, AttributeError, KeyError) as exc:
        # Malformed field types: fail closed, never a partial proposal.
        raise RetirementProposalRefused(REFUSED_UNTRUSTED_FIELD, f"{type(exc).__name__}: {exc}") from None


def _build(report, inventory_record, host_id) -> RetirementProposal:
    if not isinstance(host_id, str) or not _HOST_LABEL.fullmatch(host_id):
        _refuse(REFUSED_UNTRUSTED_FIELD, "host_id label is not a plain identifier")
    _check_report(report)
    content = _content_digest(report)
    if type(inventory_record) is not inv.WorktreeRecord:
        _refuse(REFUSED_SCHEMA, "inventory record is not a WorktreeRecord")
    if not _is_label(inventory_record.worktree_key):
        _refuse(REFUSED_IDENTITY_INCOMPLETE, "inventory record has no worktree key")
    assessment = _select(report, inventory_record.worktree_key)
    _check_assessment(report, assessment)
    _check_record(inventory_record, assessment)
    key, git_dir, common, admin_entry = _target_keys(report, inventory_record)
    scope = _build_scope(report, key, git_dir, common)

    r = inventory_record
    staged_target = RetirementTargetIdentity(
        schema=TARGET_SCHEMA, host_id_label=host_id, worktree_key=key, path=r.path,
        worktree_top=r.worktree_top, git_dir=r.git_dir, common_dir=r.common_dir, admin_entry=admin_entry,
        head_ref=r.head_ref, head_sha=r.head_sha, listed_branch=r.listed_branch, listed_head=r.listed_head,
        object_format=r.object_format, inventory_record_fingerprint=r.fingerprint,
        assessment_fingerprint=assessment.fingerprint, identity_digest="",
    )
    target = dataclasses.replace(staged_target, identity_digest=identity_digest(staged_target))
    staged = RetirementProposal(
        schema=PROPOSAL_SCHEMA, target=target, scope=scope,
        report_fingerprint=report.fingerprint,
        report_content_digest=content, assessment_classification=assessment.classification,
        limitations=assessment.limitations, advisories=assessment.advisories,
        proposal_limitations=PROPOSAL_LIMITATIONS, proposal_digest="",
    )
    return dataclasses.replace(staged, proposal_digest=proposal_digest(staged))


def validate_proposal_against_report(proposal, report, record) -> tuple:
    """Stable finding codes for `proposal` versus the given report and
    record; empty when nothing differs. Pure and NOT host authentication:
    an empty result is never a permission, an approval or an attestation."""
    if type(proposal) is not RetirementProposal or type(proposal.target) is not RetirementTargetIdentity \
            or type(proposal.scope) is not RetirementScope:
        return (PROPOSAL_TYPE_INVALID,)
    findings = []
    if (proposal.schema, proposal.target.schema, proposal.scope.schema) != (
            PROPOSAL_SCHEMA, TARGET_SCHEMA, SCOPE_SCHEMA):
        findings.append(PROPOSAL_SCHEMA_MISMATCH)
    for obj, flags in ((proposal, _PROPOSAL_FLAGS), (proposal.target, _TARGET_FLAGS),
                       (proposal.scope, _SCOPE_FLAGS)):
        if any(getattr(obj, name) is not value for name, value in flags):
            findings.append(PROPOSAL_FLAG_ALTERED)
    for obj, stored, compute, code in (
            (proposal.target, proposal.target.identity_digest, identity_digest, TARGET_DIGEST_MISMATCH),
            (proposal.scope, proposal.scope.scope_digest, scope_digest, SCOPE_DIGEST_MISMATCH),
            (proposal, proposal.proposal_digest, proposal_digest, PROPOSAL_DIGEST_MISMATCH)):
        try:
            if stored != compute(obj):
                findings.append(code)
        except (TypeError, ValueError):
            findings.append(code)
    try:
        expected = build_retirement_proposal(report, record, host_id=proposal.target.host_id_label)
    except RetirementProposalRefused as exc:
        findings.append(exc.code)
    else:
        if proposal.target != expected.target:
            findings.append(TARGET_MISMATCH)
        if proposal.scope != expected.scope:
            findings.append(SCOPE_MISMATCH)
        if proposal != expected:
            findings.append(PROPOSAL_CONTENT_MISMATCH)
    return tuple(dict.fromkeys(findings))
