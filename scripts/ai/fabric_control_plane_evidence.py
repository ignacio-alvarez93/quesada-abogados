"""FCP-11C-03: Fabric Control Plane projection of worker / attempt evidence and
checkpoints - read-only, bounded, deterministic, fail-closed,
OBSERVATION-ONLY.

Bound to ONE FCP-11B-02 `ControlPlaneSnapshot` of the same Runner state root,
it re-reads each worker's `worker.json` / `result.json` (refused unless their
sha256 equals the one the snapshot sealed) and, for every recorded attempt,
follows ONLY the `evidence_dir` the Runner persisted for that attempt::

    _evidence/<evidence_root_key(pipeline_id, worker_id)>/<attempt_leaf>/   CURRENT
    <pipeline_id>/workers/<worker_id>/evidence/<attempt_leaf>/              HISTORICAL

(HISTORICAL is the layout written before RUNNER_EVIDENCE_PATH_FIX1, which the
Runner keeps "untouched"). Inside it, only `metadata.json`, `result.json` and
`work_product.json` are opened. `prompt.txt`, `stdout.txt`, `stderr.txt`,
`git_*.txt`, process / acceptance evidence and the Work Order are never
opened: provider prose is never a status source.

Public schema (`ControlPlaneEvidence.to_dict`)
----------------------------------------------
Per attempt (`AttemptEvidence`): `attempt`, `attempt_status` (Runner code),
`work_status` (`runner_providers.WorkStatus` value or UNKNOWN),
`work_status_source`, `acceptance_decision` (Runner acceptance, NOT an
audit), `layout`, `location_condition` / `location_cause` / `location_actor`,
`attempt_leaf`, `artifacts` (kind, condition, cause, sha256, size),
`evidence_complete`, `work_product_present`, `work_product_complete`,
`checkpoint_decision`, `checkpoint_commit`, `checkpoint_created`,
`audit_verdict` and `anomalies`. Tri-states are TRUE / FALSE / UNKNOWN.
Per worker (`WorkerEvidence`): ids, `record_condition` / `record_cause`,
`attempts_total`, `attempts_omitted`, `reference_agreement`, `attempts`.
Never public: any path (`evidence_dir`, `work_product_path`, worktree), the
branch, provider prose (`reason`, `message`, `error*`), committed paths,
acceptance commands and every other native field.

Decisions
---------
* Director and Runner keep ALL execution, recovery, authorization, Git,
  process and resource authority; this module reads files under the
  caller's explicit root, persists nothing, has no clock (the instant is the
  snapshot's) and keeps the FCP-11A-01 zero-authority flags.
* Reuse, never redefine: every file read is FCP-11B-02 `_read_json` (FCP-10D-01
  `read_input_bytes` / `parse_document`), the root is admitted by FCP-11B-02
  `_admit_root`, the evidence key is `runner_pipeline.evidence_root_key`,
  attempt leaves / ids / codes / commits are the contract's validators, the
  vocabularies are the Runner's (`WorkStatus`, `WORK_STATUS_SOURCES`,
  `WORK_PRODUCT_SCHEMA_VERSION`, `EVIDENCE_ROOT_DIRNAME`) and
  `reference_agreement` reuses the snapshot's agreement codes.
* Persisted references, never recomposed: an attempt's evidence directory is
  its recorded `evidence_dir`, accepted only when it is admissible (absolute,
  local, no `..`), lies under the root, matches exactly one governed layout
  FOR THIS worker (a foreign worker's key, an extra / missing segment or a
  malformed leaf is UNAVAILABLE / EVIDENCE_PATH_UNEXPECTED), and every
  directory from the root down is a plain directory that is its own real
  path (link / junction / 8.3 alias: LINK_REFUSED). Ids alone never produce a
  path to open.
* Separate axes, each shown only from trustworthy evidence. `work_status` is
  the attempt's recorded value. `evidence_complete` TRUE needs the recorded
  True AND a governed location whose `metadata.json` / `result.json` are
  PRESENT; recorded False is FALSE. `work_product_present` is TRUE only for a
  PRESENT `work_product.json` with the supported schema whose
  pipeline / worker / attempt / run_id / evidence_dir all name this attempt,
  FALSE only when it is absent from a governed location.
  `checkpoint_created` is TRUE only for a recorded CREATED decision with a
  valid commit on a COMPLETED attempt whose work_status is SUCCESS (no
  checkpoint without a result); FALSE for a recorded non-CREATED decision.
  `audit_verdict` is always UNKNOWN: the Runner state holds no audit
  evidence, and Runner SUCCESS / acceptance PASSED / checkpoint CREATED are
  never an audit or CI verdict. Anything else is UNKNOWN - never success.
* Anomalies are reported, never resolved, and any anomaly turns the
  attempt's evidence_complete / work_product_* / checkpoint_created into
  UNKNOWN: duplicate attempt numbers or evidence references, a checkpoint
  without result or with a bad commit, a malformed checkpoint record, a work
  product of another attempt or schema, an unverifiable completeness claim,
  and a `result.json` whose evidence_dir / checkpoint commit disagrees with
  the attempt it reports (`reference_agreement` DIVERGENT).
* Limits are explicit and deterministic: the newest `max_attempts_per_worker`
  recorded attempts per worker are shown (the rest counted), workers are
  taken in (pipeline, worker) order while their shown attempts fit
  `max_attempt_reads` (the rest counted as `workers_omitted`), every file is
  bounded by `max_file_bytes`, and the CURRENT-layout artifacts become
  contract `EvidenceRef`s sealed in a `ControlPlaneObservation`.

Limitations (documented, not implemented here)
----------------------------------------------
* `metadata.json` / attempt `result.json` are checked for presence and
  strict-JSON admissibility only; their content is not projected. Native
  strings over 4096 characters make them CORRUPT, so completeness abstains.
* HISTORICAL artifacts have no contract `EvidenceRef` kind (FCP-11A-01 only
  inventories `_evidence`); they appear in `artifacts` but not in the sealed
  observation's `evidence`.
* The factory ledger's CHECKPOINT_CREATED events and the Director's own
  evidence projection are not cross-checked here (later stage).
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Optional

try:
    from scripts.ai import fabric_control_plane_contract as cp
    from scripts.ai import fabric_control_plane_snapshot as snap
    from scripts.ai import fabric_resource_quota_report as qrep
    from scripts.ai import fabric_scheduler_contract as sc
    from scripts.ai import runner_pipeline as rp
except ImportError:  # pragma: no cover - direct script execution
    import fabric_control_plane_contract as cp  # type: ignore[no-redef]
    import fabric_control_plane_snapshot as snap  # type: ignore[no-redef]
    import fabric_resource_quota_report as qrep  # type: ignore[no-redef]
    import fabric_scheduler_contract as sc  # type: ignore[no-redef]
    import runner_pipeline as rp  # type: ignore[no-redef]

SCHEMA = "fcp11c03-control-plane-evidence-v1"
SCHEMA_VERSION = 1

ATTEMPT_ARTIFACT_KINDS = ("ATTEMPT_METADATA", "ATTEMPT_RESULT", "ATTEMPT_WORK_PRODUCT")
_ARTIFACT_FILENAMES = {kind: cp.EVIDENCE_INVENTORY[kind][1][-1] for kind in ATTEMPT_ARTIFACT_KINDS}
MAX_ATTEMPT_READS = cp.MAX_EVIDENCE_REFS // len(ATTEMPT_ARTIFACT_KINDS)
DEFAULT_MAX_ATTEMPT_READS = 256
DEFAULT_MAX_ATTEMPTS_PER_WORKER = 8
MAX_EVIDENCE_DIR_CHARS = 1024
HISTORICAL_EVIDENCE_DIRNAME = "evidence"

TRUE, FALSE, UNKNOWN = "TRUE", "FALSE", cp.OUTCOME_UNKNOWN
TRISTATES = (TRUE, FALSE, UNKNOWN)

LAYOUT_CURRENT = "CURRENT"
LAYOUT_HISTORICAL = "HISTORICAL"
LAYOUT_NONE = "NONE"
LAYOUTS = (LAYOUT_CURRENT, LAYOUT_HISTORICAL, LAYOUT_NONE)

WORK_STATUSES = tuple(s.value for s in rp.providers.WorkStatus)
WORK_STATUS_SOURCES = tuple(sorted(rp.claude_runner.WORK_STATUS_SOURCES))
CHECKPOINT_DECISION_CREATED = "CREATED"
_ATTEMPT_COMPLETED = "COMPLETED"

DUPLICATE_ATTEMPT_NUMBER = "DUPLICATE_ATTEMPT_NUMBER"
DUPLICATE_EVIDENCE_REFERENCE = "DUPLICATE_EVIDENCE_REFERENCE"
CHECKPOINT_MALFORMED = "CHECKPOINT_MALFORMED"
CHECKPOINT_COMMIT_INVALID = "CHECKPOINT_COMMIT_INVALID"
CHECKPOINT_WITHOUT_RESULT = "CHECKPOINT_WITHOUT_RESULT"
WORK_PRODUCT_SCHEMA_UNSUPPORTED = "WORK_PRODUCT_SCHEMA_UNSUPPORTED"
WORK_PRODUCT_IDENTITY_MISMATCH = "WORK_PRODUCT_IDENTITY_MISMATCH"
EVIDENCE_CLAIM_UNVERIFIED = "EVIDENCE_CLAIM_UNVERIFIED"
RESULT_REFERENCE_MISMATCH = "RESULT_REFERENCE_MISMATCH"
ANOMALIES = (
    DUPLICATE_ATTEMPT_NUMBER, DUPLICATE_EVIDENCE_REFERENCE, CHECKPOINT_MALFORMED, CHECKPOINT_COMMIT_INVALID,
    CHECKPOINT_WITHOUT_RESULT, WORK_PRODUCT_SCHEMA_UNSUPPORTED, WORK_PRODUCT_IDENTITY_MISMATCH,
    EVIDENCE_CLAIM_UNVERIFIED, RESULT_REFERENCE_MISMATCH,
)
REFERENCE_AGREEMENTS = (snap.AGREEMENT_CONSISTENT, snap.AGREEMENT_DIVERGENT, snap.AGREEMENT_UNVERIFIABLE)


def _tristate(value: Optional[bool]) -> str:
    return UNKNOWN if value is None else (TRUE if value else FALSE)


def _commit(value) -> Optional[str]:
    return value if type(value) is str and cp._COMMIT_RE.fullmatch(value) else None


def _check_anomalies(anomalies) -> None:
    if not (type(anomalies) is tuple and all(cp._in(a, ANOMALIES) for a in anomalies)
            and anomalies == sc._ordered(anomalies, ANOMALIES)):
        raise ValueError("anomalies must be ordered known codes")


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ArtifactView(cp._ControlPlaneGuarantees):
    """One attempt artifact as read (never its path or content)."""
    kind: str
    condition: str
    cause: Optional[str] = None
    content_sha256: Optional[str] = None
    size_bytes: Optional[int] = None

    def __post_init__(self):
        if not cp._in(self.kind, ATTEMPT_ARTIFACT_KINDS):
            raise ValueError("unknown attempt artifact kind")
        cp._check_condition(self.condition, self.cause)
        if self.condition == cp.PRESENT:
            if not (type(self.content_sha256) is str and sc._FINGERPRINT_RE.fullmatch(self.content_sha256)
                    and cp._bounded_int(self.size_bytes, cp.MAX_EVIDENCE_BYTES)):
                raise ValueError("a PRESENT artifact needs a sha256 and a bounded size")
        elif (self.content_sha256, self.size_bytes) != (None, None):
            raise ValueError("a non-PRESENT artifact carries no content facts")

    def to_dict(self) -> dict:
        return {"kind": self.kind, "condition": self.condition, "cause": self.cause,
                "content_sha256": self.content_sha256, "size_bytes": self.size_bytes,
                "actor": cp.CONDITION_ACTOR[self.condition]}


@dataclass(frozen=True)
class AttemptEvidence(cp._ControlPlaneGuarantees):
    """One recorded attempt: its Runner-recorded result and what its
    persisted evidence directory proves. See the module docstring."""
    attempt: Optional[int]
    attempt_status: Optional[str]
    work_status: str
    work_status_source: Optional[str]
    acceptance_decision: Optional[str]
    layout: str
    location_condition: str
    location_cause: Optional[str]
    attempt_leaf: Optional[str] = None
    artifacts: tuple = ()
    evidence_complete: str = UNKNOWN
    work_product_present: str = UNKNOWN
    work_product_complete: str = UNKNOWN
    checkpoint_decision: Optional[str] = None
    checkpoint_commit: Optional[str] = None
    checkpoint_created: str = UNKNOWN
    anomalies: tuple = ()

    def __post_init__(self):
        if not cp._optional(self.attempt, lambda v: cp._bounded_int(v, cp.MAX_ATTEMPTS) and v >= 1):
            raise ValueError("attempt must be a bounded positive int")
        for code in (self.attempt_status, self.acceptance_decision, self.checkpoint_decision):
            if not cp._optional(code, cp.valid_code):
                raise ValueError("codes must be valid codes")
        if not (cp._in(self.work_status, WORK_STATUSES + (UNKNOWN,))
                and cp._optional(self.work_status_source, lambda v: cp._in(v, WORK_STATUS_SOURCES))):
            raise ValueError("work status outside the Runner vocabulary")
        if not cp._in(self.layout, LAYOUTS):
            raise ValueError("unknown layout")
        cp._check_condition(self.location_condition, self.location_cause)
        located = self.location_condition == cp.PRESENT
        if located != (self.layout != LAYOUT_NONE) or located != (self.attempt_leaf is not None):
            raise ValueError("only a governed, present location has a layout and a leaf")
        if self.attempt_leaf is not None and not cp._ATTEMPT_LEAF_RE.fullmatch(self.attempt_leaf):
            raise ValueError("attempt_leaf invalid")
        if not (type(self.artifacts) is tuple and all(type(a) is ArtifactView for a in self.artifacts)
                and tuple(a.kind for a in self.artifacts) == (ATTEMPT_ARTIFACT_KINDS if located else ())):
            raise ValueError("a present location has exactly its artifacts, any other none")
        tristates = (self.evidence_complete, self.work_product_present, self.work_product_complete,
                     self.checkpoint_created)
        if not all(cp._in(t, TRISTATES) for t in tristates):
            raise ValueError("tri-states must be TRUE / FALSE / UNKNOWN")
        _check_anomalies(self.anomalies)
        if self.anomalies and any(t != UNKNOWN for t in tristates):
            raise ValueError("an attempt with anomalies proves nothing")
        if TRUE in (self.evidence_complete, self.work_product_present, self.work_product_complete) and not located:
            raise ValueError("evidence claims need a governed location")
        if self.work_product_complete != UNKNOWN and self.work_product_present != TRUE:
            raise ValueError("work product completeness needs a work product")
        if (self.checkpoint_created == TRUE) != (_commit(self.checkpoint_commit) is not None):
            raise ValueError("a checkpoint commit is shown exactly when the checkpoint is proven")
        if self.checkpoint_created == TRUE and not (
                self.checkpoint_decision == CHECKPOINT_DECISION_CREATED and self.attempt_status == _ATTEMPT_COMPLETED
                and self.work_status == rp.providers.WorkStatus.SUCCESS.value):
            raise ValueError("no checkpoint without a successful result")

    @property
    def audit_verdict(self) -> str:
        """Always UNKNOWN: no audit evidence exists in the Runner state."""
        return UNKNOWN

    def evidence_refs(self, pipeline_id: str, worker_id: str) -> tuple:
        """Contract `EvidenceRef`s of a CURRENT-layout attempt; () otherwise."""
        if self.layout != LAYOUT_CURRENT or self.location_condition != cp.PRESENT:
            return ()
        return tuple(cp.EvidenceRef(a.kind, a.condition, pipeline_id, worker_id, self.attempt_leaf, a.cause,
                                    a.content_sha256, a.size_bytes) for a in self.artifacts)

    def to_dict(self) -> dict:
        return {
            "attempt": self.attempt, "attempt_status": self.attempt_status, "work_status": self.work_status,
            "work_status_source": self.work_status_source, "acceptance_decision": self.acceptance_decision,
            "layout": self.layout, "location_condition": self.location_condition,
            "location_cause": self.location_cause, "location_actor": cp.CONDITION_ACTOR[self.location_condition],
            "attempt_leaf": self.attempt_leaf, "artifacts": [a.to_dict() for a in self.artifacts],
            "evidence_complete": self.evidence_complete, "work_product_present": self.work_product_present,
            "work_product_complete": self.work_product_complete, "checkpoint_decision": self.checkpoint_decision,
            "checkpoint_commit": self.checkpoint_commit, "checkpoint_created": self.checkpoint_created,
            "audit_verdict": self.audit_verdict, "anomalies": list(self.anomalies),
        }


@dataclass(frozen=True)
class WorkerEvidence(cp._ControlPlaneGuarantees):
    """The evidence of one worker's recorded attempts (oldest first). A
    `worker.json` that is not PRESENT (or changed since the snapshot) shows
    no attempts."""
    pipeline_id: str
    worker_id: str
    record_condition: str
    record_cause: Optional[str] = None
    attempts_total: Optional[int] = None
    attempts_omitted: int = 0
    reference_agreement: str = snap.AGREEMENT_UNVERIFIABLE
    attempts: tuple = ()

    def __post_init__(self):
        if not (cp.valid_id(self.pipeline_id) and cp.valid_id(self.worker_id)):
            raise ValueError("worker identity must be valid ids")
        cp._check_condition(self.record_condition, self.record_cause)
        if not cp._in(self.reference_agreement, REFERENCE_AGREEMENTS):
            raise ValueError("unknown reference agreement")
        if not (type(self.attempts) is tuple and all(type(a) is AttemptEvidence for a in self.attempts)):
            raise ValueError("attempts must be AttemptEvidence")
        if self.record_condition != cp.PRESENT:
            if self.attempts or self.attempts_total is not None or self.attempts_omitted:
                raise ValueError("an unreadable record shows no attempts")
        elif not (cp._bounded_int(self.attempts_total, cp.MAX_ATTEMPTS)
                  and self.attempts_omitted == self.attempts_total - len(self.attempts) >= 0):
            raise ValueError("attempt counts must add up")

    def evidence_refs(self) -> tuple:
        return tuple(r for a in self.attempts for r in a.evidence_refs(self.pipeline_id, self.worker_id))

    def to_dict(self) -> dict:
        return {
            "pipeline_id": self.pipeline_id, "worker_id": self.worker_id,
            "record_condition": self.record_condition, "record_cause": self.record_cause,
            "record_actor": cp.CONDITION_ACTOR[self.record_condition], "attempts_total": self.attempts_total,
            "attempts_omitted": self.attempts_omitted, "reference_agreement": self.reference_agreement,
            "attempts": [a.to_dict() for a in self.attempts],
        }


@dataclass(frozen=True)
class ControlPlaneEvidence(cp._ControlPlaneGuarantees):
    """Sealed evidence projection bound to one snapshot `snapshot_revision`;
    `observation` seals the CURRENT-layout artifacts as contract refs."""
    snapshot_revision: str
    observation: cp.ControlPlaneObservation
    root_condition: str = cp.PRESENT
    root_cause: Optional[str] = None
    workers: tuple = ()
    workers_omitted: int = 0

    def __post_init__(self):
        if not (type(self.snapshot_revision) is str and sc._FINGERPRINT_RE.fullmatch(self.snapshot_revision)):
            raise ValueError("snapshot_revision must be a sha256")
        if type(self.observation) is not cp.ControlPlaneObservation or self.observation.pipelines:
            raise ValueError("observation must be a ControlPlaneObservation of evidence only")
        cp._check_condition(self.root_condition, self.root_cause)
        keys = [(w.pipeline_id, w.worker_id) for w in self.workers] if type(self.workers) is tuple else None
        if not (keys is not None and all(type(w) is WorkerEvidence for w in self.workers)
                and keys == sorted(set(keys))):
            raise ValueError("workers must be sorted unique WorkerEvidence")
        refs = tuple(sorted((r for w in self.workers for r in w.evidence_refs()), key=cp.EvidenceRef.sort_key))
        if refs != self.observation.evidence:
            raise ValueError("observation must seal exactly the workers' evidence refs")
        if self.root_condition != cp.PRESENT and self.workers:
            raise ValueError("an unreadable root shows nothing")
        if not cp._bounded_int(self.workers_omitted, cp.MAX_PIPELINES * cp.MAX_WORKERS):
            raise ValueError("workers_omitted must be bounded")

    def _body(self) -> dict:
        return {
            "schema": SCHEMA, "schema_version": SCHEMA_VERSION, "snapshot_revision": self.snapshot_revision,
            "observation": self.observation.to_dict(), "root_condition": self.root_condition,
            "root_cause": self.root_cause, "root_actor": cp.CONDITION_ACTOR[self.root_condition],
            "workers": [w.to_dict() for w in self.workers], "workers_omitted": self.workers_omitted,
            **cp._ControlPlaneGuarantees._guarantees(),
        }

    @property
    def revision(self) -> str:
        return hashlib.sha256(sc._canonical(self._body()).encode("ascii")).hexdigest()

    def to_dict(self) -> dict:
        return {**self._body(), "revision": self.revision}


def canonical_json(evidence: ControlPlaneEvidence) -> str:
    """Stable, sorted, compact, size-bounded serialization of the exact type."""
    if type(evidence) is not ControlPlaneEvidence:
        raise TypeError("canonical_json accepts only a ControlPlaneEvidence")
    text = sc._canonical(ControlPlaneEvidence.to_dict(evidence))
    if len(text) > cp.MAX_CANONICAL_JSON_BYTES:
        raise ValueError("canonical evidence exceeds MAX_CANONICAL_JSON_BYTES")
    return text


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def _bound_read(root: str, snapshot, kind: str, pid: str, wid: str, max_bytes: int) -> snap._Read:
    """`worker.json` / `result.json`, only if byte-identical to the snapshot's."""
    ref = next((e for e in snapshot.observation.evidence
                if (e.kind, e.pipeline_id, e.worker_id) == (kind, pid, wid)), None)
    if ref is None:
        return snap._Read(cp.SOURCE_ABSENT)
    if ref.condition != cp.PRESENT:
        return snap._Read(ref.cause)
    read = snap._read_json(os.path.join(root, *ref.relative_parts()), max_bytes)
    if read.cause is None and read.sha256 != ref.content_sha256:
        return snap._Read(cp.SOURCE_CHANGED_DURING_READ)
    return read


def _locate(root: str, pid: str, wid: str, raw) -> tuple:
    """`(layout, cause, relative_parts)` of a persisted `evidence_dir`."""
    if raw is None:
        return LAYOUT_NONE, cp.FIELD_ABSENT, ()
    if type(raw) is not str or not raw or len(raw) > MAX_EVIDENCE_DIR_CHARS:
        return LAYOUT_NONE, cp.FIELD_MALFORMED, ()
    try:
        qrep.admit_path(raw)
    except qrep.ReportError as exc:
        return LAYOUT_NONE, snap._REFUSAL_CAUSES.get(exc.code, cp.PATH_REFUSED), ()
    root_parts = tuple(os.path.normcase(p) for p in _split(root))
    parts = _split(raw)
    if tuple(os.path.normcase(p) for p in parts[:len(root_parts)]) != root_parts:
        return LAYOUT_NONE, cp.PATH_REFUSED, ()
    rel = parts[len(root_parts):]
    if rel[:2] == (rp.EVIDENCE_ROOT_DIRNAME, rp.evidence_root_key(pid, wid)) and len(rel) == 3:
        layout = LAYOUT_CURRENT
    elif rel[:4] == (pid, snap.WORKERS_DIRNAME, wid, HISTORICAL_EVIDENCE_DIRNAME) and len(rel) == 5:
        layout = LAYOUT_HISTORICAL
    else:
        return LAYOUT_NONE, cp.EVIDENCE_PATH_UNEXPECTED, ()
    if not cp._ATTEMPT_LEAF_RE.fullmatch(rel[-1]):
        return LAYOUT_NONE, cp.EVIDENCE_PATH_UNEXPECTED, ()
    path = root
    for name in rel:
        path = os.path.join(path, name)
        kind, _, cause = snap._probe(path)
        if cause is not None:
            return layout, cause, rel
        if kind != snap._DIR:
            return layout, (cp.LINK_REFUSED if kind == snap._LINK else cp.SOURCE_UNREADABLE), rel
    try:
        real = os.path.realpath(path)
    except (OSError, ValueError):
        return layout, cp.SOURCE_UNREADABLE, rel
    if os.path.normcase(real) != os.path.normcase(os.path.normpath(path)):
        return layout, cp.LINK_REFUSED, rel
    return layout, None, rel


def _split(path: str) -> tuple:
    head, parts = os.path.normpath(path), []
    while True:
        head, tail = os.path.split(head)
        if not tail:
            return (head,) + tuple(reversed(parts))
        parts.append(tail)


def _same_dir(a, b) -> bool:
    return type(a) is str and type(b) is str and os.path.normcase(os.path.normpath(a)) == \
        os.path.normcase(os.path.normpath(b))


def _work_product(read: snap._Read, pid: str, wid: str, number, leaf: str, evidence_dir: str) -> tuple:
    """`(present, complete, anomaly)` of one PRESENT `work_product.json`."""
    record = read.payload
    if type(record) is not dict or not (sc._is_int(record.get("schema_version"))
                                        and record["schema_version"] == rp.claude_runner.WORK_PRODUCT_SCHEMA_VERSION):
        return None, None, WORK_PRODUCT_SCHEMA_UNSUPPORTED
    if not ((record.get("pipeline_id"), record.get("worker_id"), record.get("run_id")) == (pid, wid, leaf)
            and sc._is_int(record.get("attempt")) and record["attempt"] == number
            and _same_dir(record.get("evidence_dir"), evidence_dir)):
        return None, None, WORK_PRODUCT_IDENTITY_MISMATCH
    incomplete = record.get("incomplete")
    return True, (not incomplete if type(incomplete) is bool else None), None


def _attempt(root: str, pid: str, wid: str, raw: dict, extra: set, max_bytes: int) -> AttemptEvidence:
    anomalies = set(extra)
    number = raw.get("attempt") if cp._bounded_int(raw.get("attempt"), cp.MAX_ATTEMPTS) and raw["attempt"] else None
    status = raw.get("status") if cp.valid_code(raw.get("status")) else None
    work_status = raw.get("work_status") if cp._in(raw.get("work_status"), WORK_STATUSES) else UNKNOWN
    acceptance = raw.get("acceptance")
    layout, cause, rel = (LAYOUT_NONE, cp.EVIDENCE_PATH_UNEXPECTED, ()) \
        if DUPLICATE_EVIDENCE_REFERENCE in anomalies else _locate(root, pid, wid, raw.get("evidence_dir"))
    located, artifacts, reads = cause is None, (), {}
    if located:
        directory = os.path.join(root, *rel)
        for kind in ATTEMPT_ARTIFACT_KINDS:
            reads[kind] = snap._read_json(os.path.join(directory, _ARTIFACT_FILENAMES[kind]), max_bytes)
        artifacts = tuple(ArtifactView(k, cp.CAUSE_CONDITION[r.cause] if r.cause else cp.PRESENT, r.cause,
                                       r.sha256, r.size) for k, r in reads.items())
    # -- work product ------------------------------------------------------
    wp_present = wp_complete = None
    if located:
        wp = reads["ATTEMPT_WORK_PRODUCT"]
        if wp.cause == cp.SOURCE_ABSENT:
            wp_present = False
        elif wp.cause is None:
            wp_present, wp_complete, anomaly = _work_product(wp, pid, wid, number, rel[-1], raw.get("evidence_dir"))
            if anomaly:
                anomalies.add(anomaly)
    # -- evidence completeness ---------------------------------------------
    recorded = raw.get("evidence_complete")
    complete = None
    if recorded is False:
        complete = False
    elif recorded is True:
        if located and all(reads[k].cause is None for k in ("ATTEMPT_METADATA", "ATTEMPT_RESULT")):
            complete = True
        else:
            anomalies.add(EVIDENCE_CLAIM_UNVERIFIED)
    # -- checkpoint --------------------------------------------------------
    checkpoint, decision, commit, created = raw.get("checkpoint"), None, None, None
    if checkpoint is not None:
        decision = checkpoint.get("decision") if type(checkpoint) is dict else None
        decision = decision if cp.valid_code(decision) else None
        if decision is None:
            anomalies.add(CHECKPOINT_MALFORMED)
        elif decision != CHECKPOINT_DECISION_CREATED:
            created = False
        elif _commit(checkpoint.get("commit_hash")) is None:
            anomalies.add(CHECKPOINT_COMMIT_INVALID)
        elif status != _ATTEMPT_COMPLETED or work_status != rp.providers.WorkStatus.SUCCESS.value:
            anomalies.add(CHECKPOINT_WITHOUT_RESULT)
        else:
            created, commit = True, checkpoint["commit_hash"]
    trusted = not anomalies
    return AttemptEvidence(
        attempt=number, attempt_status=status, work_status=work_status,
        work_status_source=raw.get("work_status_source") if cp._in(raw.get("work_status_source"),
                                                                   WORK_STATUS_SOURCES) else None,
        acceptance_decision=acceptance.get("decision") if type(acceptance) is dict
        and cp.valid_code(acceptance.get("decision")) else None,
        layout=layout if located else LAYOUT_NONE,
        location_condition=cp.PRESENT if located else cp.CAUSE_CONDITION[cause], location_cause=cause,
        attempt_leaf=rel[-1] if located else None, artifacts=artifacts,
        evidence_complete=_tristate(complete if trusted else None),
        work_product_present=_tristate(wp_present if trusted else None),
        work_product_complete=_tristate(wp_complete if trusted and wp_present else None),
        checkpoint_decision=decision, checkpoint_commit=commit if trusted else None,
        checkpoint_created=_tristate(created if trusted else None),
        anomalies=sc._ordered(sorted(anomalies), ANOMALIES),
    )


def _result_agreement(result: snap._Read, pid: str, wid: str, attempts: list) -> tuple:
    """`(agreement, attempt_number)`: does `result.json` reference the same
    evidence_dir / checkpoint commit as the attempt it reports?"""
    payload = result.payload
    if result.cause is not None or type(payload) is not dict \
            or (payload.get("pipeline_id"), payload.get("worker_id")) != (pid, wid):
        return snap.AGREEMENT_UNVERIFIABLE, None
    reported = payload.get("attempts")
    last = reported[-1] if type(reported) is list and reported and type(reported[-1]) is dict else None
    number = last.get("attempt") if last is not None else None
    if not sc._is_int(number):
        return snap.AGREEMENT_UNVERIFIABLE, None
    matches = [a for a in attempts if sc._is_int(a.get("attempt")) and a["attempt"] == number]
    if not matches:  # it reports an attempt the record does not hold: none is proven
        return snap.AGREEMENT_DIVERGENT, None
    own = matches[-1]
    same_dir = payload.get("evidence_dir") == own.get("evidence_dir")
    checkpoint = payload.get("checkpoint")
    own_checkpoint = own.get("checkpoint") if type(own.get("checkpoint")) is dict else {}
    same_commit = checkpoint is None or (type(checkpoint) is dict
                                         and checkpoint.get("commit_hash") == own_checkpoint.get("commit_hash"))
    return (snap.AGREEMENT_CONSISTENT if same_dir and same_commit else snap.AGREEMENT_DIVERGENT), number


def _worker(root: str, snapshot, pid: str, wid: str, max_attempts: int, max_bytes: int) -> WorkerEvidence:
    record = _bound_read(root, snapshot, "WORKER_RECORD", pid, wid, max_bytes)
    cause = record.cause
    payload = record.payload
    if cause is None and type(payload) is not dict:
        cause = cp.SOURCE_NOT_JSON
    elif cause is None and not (sc._is_int(payload.get("schema_version"))
                                and payload["schema_version"] == rp.PIPELINE_SCHEMA_VERSION):
        cause = cp.SCHEMA_UNSUPPORTED
    elif cause is None and not (type(payload.get("spec")) is dict and payload["spec"].get("id") == wid):
        cause = cp.IDENTITY_MISMATCH
    elif cause is None and not (type(payload.get("attempts")) is list and len(payload["attempts"]) <= cp.MAX_ATTEMPTS
                                and all(type(a) is dict for a in payload["attempts"])):
        cause = cp.FIELD_MALFORMED
    if cause is not None:
        return WorkerEvidence(pid, wid, cp.CAUSE_CONDITION[cause], cause)
    attempts = payload["attempts"]
    numbers = [a.get("attempt") if cp._bounded_int(a.get("attempt"), cp.MAX_ATTEMPTS) else None for a in attempts]
    dirs = [os.path.normcase(os.path.normpath(a["evidence_dir"])) if type(a.get("evidence_dir")) is str
            and a["evidence_dir"] else None for a in attempts]
    agreement, reported = _result_agreement(
        _bound_read(root, snapshot, "WORKER_RESULT", pid, wid, max_bytes), pid, wid, attempts)
    shown = range(max(len(attempts) - max_attempts, 0), len(attempts))
    views = []
    for i in shown:
        extra = set()
        if numbers[i] is not None and numbers.count(numbers[i]) > 1:
            extra.add(DUPLICATE_ATTEMPT_NUMBER)
        if dirs[i] is not None and dirs.count(dirs[i]) > 1:
            extra.add(DUPLICATE_EVIDENCE_REFERENCE)
        if agreement == snap.AGREEMENT_DIVERGENT and (reported is None or numbers[i] == reported):
            extra.add(RESULT_REFERENCE_MISMATCH)
        views.append(_attempt(root, pid, wid, attempts[i], extra, max_bytes))
    return WorkerEvidence(pid, wid, cp.PRESENT, attempts_total=len(attempts),
                          attempts_omitted=len(attempts) - len(views), reference_agreement=agreement,
                          attempts=tuple(views))


def _check_limits(max_attempts_per_worker, max_attempt_reads, max_file_bytes) -> None:
    if not (cp._bounded_int(max_attempts_per_worker, MAX_ATTEMPT_READS) and max_attempts_per_worker >= 1):
        raise ValueError("max_attempts_per_worker must be an int in 1..MAX_ATTEMPT_READS")
    if not (cp._bounded_int(max_attempt_reads, MAX_ATTEMPT_READS) and max_attempt_reads >= max_attempts_per_worker):
        raise ValueError("max_attempt_reads must be an int in max_attempts_per_worker..MAX_ATTEMPT_READS")
    if not (cp._bounded_int(max_file_bytes, snap.MAX_FILE_BYTES) and max_file_bytes >= 1):
        raise ValueError("max_file_bytes must be an int in 1..MAX_FILE_BYTES")


def take_evidence(state_root, snapshot, *, max_attempts_per_worker: int = DEFAULT_MAX_ATTEMPTS_PER_WORKER,
                  max_attempt_reads: int = DEFAULT_MAX_ATTEMPT_READS,
                  max_file_bytes: int = snap.MAX_FILE_BYTES) -> ControlPlaneEvidence:
    """Read-only evidence projection of the on-disk workers of `snapshot`,
    which must be a `ControlPlaneSnapshot` of this same `state_root`.
    Raises only for a caller error (wrong type, bad limit); every problem
    with the root or its files is reported, never raised and never echoed."""
    if type(snapshot) is not snap.ControlPlaneSnapshot:
        raise TypeError("snapshot must be a ControlPlaneSnapshot")
    _check_limits(max_attempts_per_worker, max_attempt_reads, max_file_bytes)
    observed_at = snapshot.observation.observed_at_utc
    cause = snapshot.root_cause or snap._admit_root(state_root)
    if cause is not None:
        return ControlPlaneEvidence(snapshot.revision, cp.ControlPlaneObservation(observed_at),
                                    root_condition=cp.CAUSE_CONDITION[cause], root_cause=cause)
    root = os.fspath(state_root)
    targets = [(p.pipeline_id, w.worker_id) for p in snapshot.pipelines for w in p.workers if w.on_disk]
    workers, budget = [], max_attempt_reads
    for pid, wid in targets:
        if budget < max_attempts_per_worker:
            break
        view = _worker(root, snapshot, pid, wid, max_attempts_per_worker, max_file_bytes)
        budget -= len(view.attempts)
        workers.append(view)
    refs = tuple(sorted((r for w in workers for r in w.evidence_refs()), key=cp.EvidenceRef.sort_key))
    return ControlPlaneEvidence(snapshot.revision, cp.ControlPlaneObservation(observed_at, evidence=refs),
                                workers=tuple(workers), workers_omitted=len(targets) - len(workers))
