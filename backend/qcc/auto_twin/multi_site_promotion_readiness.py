"""QCC AUTO TWIN — Human Promotion Readiness Gate (UWT-12D).

Work Order UWT-12D asks for the final *governed readiness* layer that
sits in front of any future Twin promotion decision. It is explicitly
**not** a promotion engine: it never flips a candidate to ``ACTIVE``,
never writes to any store, and never replaces the human/governed
decision this Work Order keeps binding (``HUMAN_ONLY``).

Canonical source audit
-----------------------

Everything this gate needs to *judge* already exists and is reused
verbatim, never duplicated or re-derived:

- ``build_multi_site_certification`` (UWT-12A) already reduces
  structural fidelity, transition/behavior fidelity, network/local
  safety and governed exploration readiness into one deterministic
  ``certification_record`` bound to one site identity and one Twin
  candidate/revision identity. This gate never re-runs or
  re-implements that composition; it only reads a record the caller
  already built.
- ``AutoTwinCandidateRevisionStore`` already owns the live candidate
  lifecycle (``candidate_id``/``candidate_revision``/``status``). This
  gate reads it once, through ``get_candidate``, to detect whether the
  candidate has moved on (a new revision, a ``REJECTED`` decision)
  since the supplied certification record was built.
- ``AutoTwinValidationEvidenceStore`` already owns the persisted
  fidelity evidence a ``certification_record`` references. This gate
  reads it once, through ``candidate_snapshot``, to confirm that
  evidence is actually resolvable (present, non-empty, and bound to
  the same candidate revision) rather than trusting the record's own
  claim blindly.

What does not exist yet, and is the entire contribution of this
module, is the generic, provider-neutral composition that:

1. binds one *intended promotion target* (``managed_site`` +
   ``twin_key`` + ``candidate_id`` + ``candidate_revision``) to one
   already-built UWT-12A ``certification_record`` and checks they
   describe the exact same site + candidate/revision identity;
2. requires the certification's own overall verdict, and every
   required capability inside it, to themselves be ``PASS`` --
   anything else (``FAIL``, ``UNRESOLVED``, ``NOT_SUPPORTED``) is
   never silently treated as readiness;
3. re-resolves the validation evidence the certification claims to
   rest on, and re-fetches the candidate's *current* store state, so
   a stale, superseded or rejected candidate can never be reported
   ready just because an older certification record still says
   ``PASS``;
4. reduces all of that to the one explicit three-value vocabulary
   this Work Order requires -- ``READY_FOR_HUMAN_PROMOTION`` /
   ``BLOCKED`` / ``UNRESOLVED`` -- together with the fixed per-check
   matrix and explicit blocking/unresolved reasons a human reviewer
   needs to act on.

Governance this module preserves (never violates)
----------------------------------------------------

- Read-only: this module only ever calls ``get_candidate`` on
  ``AutoTwinCandidateRevisionStore`` and ``candidate_snapshot`` on
  ``AutoTwinValidationEvidenceStore``, both pure reads. It never calls
  ``transition_candidate_status``, never calls
  ``record_changed_observation``/``record_validation_evidence``, and
  never touches any materialization or managed-site store.
- No ACTIVE status mutation, no candidate-store promotion: this
  module never writes anything, under any verdict.
- No browser, no network, no filing/submission: purely a composition
  over evidence and identities already produced by other, already-
  governed components.
- ``HUMAN_ONLY`` remains binding: ``READY_FOR_HUMAN_PROMOTION`` is
  evidence for a later human/governed promotion decision, never the
  decision itself, and this module exposes no API that performs that
  decision.
- Deterministic: the same inputs always yield the same
  ``readiness_id`` (a stable sha256 digest over canonical JSON),
  independent of dict/set iteration order.
- Fail closed: any evidence that cannot be positively resolved
  (missing, malformed, or bound to a different site/twin/candidate/
  revision) always yields ``BLOCKED`` or ``UNRESOLVED``, never a
  guessed ``READY_FOR_HUMAN_PROMOTION``.
- Provider-neutral, site-neutral: every input is a generic identity
  or evidence object (``AutoTwinManagedSite``, stores, a
  certification record); no site-specific rule, selector or URL is
  ever referenced by name.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json

from .candidate_revision_store import (
    AUTO_TWIN_CANDIDATE_STATUS_PENDING_VALIDATION,
    AUTO_TWIN_CANDIDATE_STATUS_REJECTED,
    AUTO_TWIN_CANDIDATE_STATUS_VALIDATED,
    AutoTwinCandidateRevisionStore,
)
from .managed_site_registry import AutoTwinManagedSite
from .multi_site_certification import (
    AUTO_TWIN_CERTIFICATION_CAPABILITIES,
    AUTO_TWIN_CERTIFICATION_STATUS_FAIL,
    AUTO_TWIN_CERTIFICATION_STATUS_NOT_SUPPORTED,
    AUTO_TWIN_CERTIFICATION_STATUS_PASS,
    AUTO_TWIN_CERTIFICATION_STATUS_UNRESOLVED,
    AUTO_TWIN_CERTIFICATION_STATUSES,
    AUTO_TWIN_MULTI_SITE_CERTIFICATION_SCHEMA_VERSION,
    AUTO_TWIN_MULTI_SITE_CERTIFICATION_TYPE,
)
from .validation_evidence_store import AutoTwinValidationEvidenceStore


AUTO_TWIN_PROMOTION_READINESS_SCHEMA_VERSION = 1

AUTO_TWIN_PROMOTION_READINESS_TYPE = (
    "QCC_AUTO_TWIN_HUMAN_PROMOTION_READINESS"
)

# The one, fixed, explicit three-value gate vocabulary this Work
# Order requires.
AUTO_TWIN_PROMOTION_READINESS_STATUS_READY = "READY_FOR_HUMAN_PROMOTION"
AUTO_TWIN_PROMOTION_READINESS_STATUS_BLOCKED = "BLOCKED"
AUTO_TWIN_PROMOTION_READINESS_STATUS_UNRESOLVED = "UNRESOLVED"

AUTO_TWIN_PROMOTION_READINESS_STATUSES = frozenset(
    {
        AUTO_TWIN_PROMOTION_READINESS_STATUS_READY,
        AUTO_TWIN_PROMOTION_READINESS_STATUS_BLOCKED,
        AUTO_TWIN_PROMOTION_READINESS_STATUS_UNRESOLVED,
    }
)

# Per-check finding vocabulary (never exposed as the overall gate
# status, only as each fixed check's own outcome).
_FINDING_STATUS_PASS = "PASS"
_FINDING_STATUS_BLOCKED = "BLOCKED"
_FINDING_STATUS_UNRESOLVED = "UNRESOLVED"

_FINDING_STATUSES = frozenset(
    {
        _FINDING_STATUS_PASS,
        _FINDING_STATUS_BLOCKED,
        _FINDING_STATUS_UNRESOLVED,
    }
)

# Fixed check vocabulary (the required readiness check matrix rows).
# Order is pinned so two equal findings always serialize identically.
AUTO_TWIN_PROMOTION_READINESS_CHECK_CERTIFICATION_PRESENT = (
    "CERTIFICATION_RECORD_PRESENT"
)
AUTO_TWIN_PROMOTION_READINESS_CHECK_IDENTITY_BINDING = (
    "CERTIFICATION_IDENTITY_BINDING"
)
AUTO_TWIN_PROMOTION_READINESS_CHECK_OVERALL_VERDICT = (
    "CERTIFICATION_OVERALL_VERDICT"
)
AUTO_TWIN_PROMOTION_READINESS_CHECK_CAPABILITY_MATRIX = (
    "CERTIFICATION_CAPABILITY_MATRIX"
)
AUTO_TWIN_PROMOTION_READINESS_CHECK_EVIDENCE_RESOLVABLE = (
    "VALIDATION_EVIDENCE_RESOLVABLE"
)
AUTO_TWIN_PROMOTION_READINESS_CHECK_CANDIDATE_CURRENT = (
    "CANDIDATE_REVISION_CURRENT"
)

AUTO_TWIN_PROMOTION_READINESS_CHECKS = (
    AUTO_TWIN_PROMOTION_READINESS_CHECK_CERTIFICATION_PRESENT,
    AUTO_TWIN_PROMOTION_READINESS_CHECK_IDENTITY_BINDING,
    AUTO_TWIN_PROMOTION_READINESS_CHECK_OVERALL_VERDICT,
    AUTO_TWIN_PROMOTION_READINESS_CHECK_CAPABILITY_MATRIX,
    AUTO_TWIN_PROMOTION_READINESS_CHECK_EVIDENCE_RESOLVABLE,
    AUTO_TWIN_PROMOTION_READINESS_CHECK_CANDIDATE_CURRENT,
)

# Explicit reason used for every check once the certification record
# itself is missing -- always surfaced as UNRESOLVED, never silently
# skipped or upgraded.
AUTO_TWIN_PROMOTION_READINESS_REASON_CERTIFICATION_RECORD_MISSING = (
    "CERTIFICATION_RECORD_MISSING"
)


def _text(value) -> str:
    return str(value or "").strip()


def _required_text(value, *, error) -> str:
    result = _text(value)

    if not result:
        raise ValueError(error)

    return result


def _canonical_json(value) -> str:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )


def _finding(*, status, reason, references=None):
    if status not in _FINDING_STATUSES:
        raise ValueError(
            "QCC_AUTO_TWIN_PROMOTION_READINESS_FINDING_STATUS_INVALID"
        )

    return {
        "status": status,
        "reason": _text(reason) or None,
        "references": dict(references or {}),
    }


def _missing_certification_finding():
    return _finding(
        status=_FINDING_STATUS_UNRESOLVED,
        reason=(
            AUTO_TWIN_PROMOTION_READINESS_REASON_CERTIFICATION_RECORD_MISSING
        ),
    )


def _check_certification_present(certification_record):
    """Returns ``(finding, certification_record_is_usable)``."""

    if certification_record is None:
        return _missing_certification_finding(), False

    if (
        not isinstance(certification_record, dict)
        or certification_record.get("result_type")
        != AUTO_TWIN_MULTI_SITE_CERTIFICATION_TYPE
        or certification_record.get("schema_version")
        != AUTO_TWIN_MULTI_SITE_CERTIFICATION_SCHEMA_VERSION
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_PROMOTION_READINESS_CERTIFICATION_RECORD_INVALID"
        )

    return (
        _finding(
            status=_FINDING_STATUS_PASS,
            reason=None,
            references={
                "certification_id": certification_record.get(
                    "certification_id"
                )
            },
        ),
        True,
    )


def _check_identity_binding(certification_record, *, target_identity):
    site_identity = certification_record.get("site_identity")
    revision_identity = certification_record.get("twin_revision_identity")

    if not isinstance(site_identity, dict) or not isinstance(
        revision_identity, dict
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_PROMOTION_READINESS_CERTIFICATION_IDENTITY_INVALID"
        )

    certified_site_twin_key = _text(site_identity.get("twin_key"))
    certified_revision_twin_key = _text(revision_identity.get("twin_key"))

    if certified_site_twin_key != certified_revision_twin_key:
        # UWT-12A always binds these together at build time: a
        # divergence here means the record itself is inconsistent
        # (tampered or hand-built), never a legitimate evidence gap.
        raise ValueError(
            "QCC_AUTO_TWIN_PROMOTION_READINESS_CERTIFICATION_IDENTITY_"
            "INCONSISTENT"
        )

    certified_identity = {
        "site_code": _text(site_identity.get("site_code")),
        "twin_key": certified_revision_twin_key,
        "candidate_id": _text(revision_identity.get("candidate_id")),
        "candidate_revision": revision_identity.get("candidate_revision"),
    }

    mismatches = tuple(
        field
        for field in (
            "site_code",
            "twin_key",
            "candidate_id",
            "candidate_revision",
        )
        if certified_identity[field] != target_identity[field]
    )

    references = {
        "certified_identity": certified_identity,
        "target_identity": dict(target_identity),
        "mismatched_fields": mismatches,
    }

    if mismatches:
        return _finding(
            status=_FINDING_STATUS_BLOCKED,
            reason=f"{mismatches[0].upper()}_MISMATCH",
            references=references,
        )

    return _finding(
        status=_FINDING_STATUS_PASS, reason=None, references=references
    )


def _check_overall_verdict(certification_record):
    verdict = certification_record.get("certification_verdict")

    if verdict not in AUTO_TWIN_CERTIFICATION_STATUSES:
        raise ValueError(
            "QCC_AUTO_TWIN_PROMOTION_READINESS_CERTIFICATION_VERDICT_INVALID"
        )

    references = {"certification_verdict": verdict}

    if verdict == AUTO_TWIN_CERTIFICATION_STATUS_PASS:
        return _finding(
            status=_FINDING_STATUS_PASS, reason=None, references=references
        )

    if verdict == AUTO_TWIN_CERTIFICATION_STATUS_FAIL:
        return _finding(
            status=_FINDING_STATUS_BLOCKED,
            reason="CERTIFICATION_VERDICT_FAIL",
            references=references,
        )

    # UNRESOLVED or NOT_SUPPORTED: the certification evidence itself
    # could not positively resolve to PASS -- never a silent readiness
    # claim, always surfaced as an explicit evidence gap.
    return _finding(
        status=_FINDING_STATUS_UNRESOLVED,
        reason=f"CERTIFICATION_VERDICT_{verdict}",
        references=references,
    )


def _check_capability_matrix(certification_record):
    capability_matrix = certification_record.get("capability_matrix")

    if not isinstance(
        capability_matrix, dict
    ) or set(capability_matrix) != set(AUTO_TWIN_CERTIFICATION_CAPABILITIES):
        raise ValueError(
            "QCC_AUTO_TWIN_PROMOTION_READINESS_CAPABILITY_MATRIX_INVALID"
        )

    failing = []
    unresolved = []

    for capability in AUTO_TWIN_CERTIFICATION_CAPABILITIES:
        entry = capability_matrix.get(capability)

        if not isinstance(entry, dict):
            raise ValueError(
                "QCC_AUTO_TWIN_PROMOTION_READINESS_CAPABILITY_ENTRY_INVALID"
            )

        status = entry.get("status")

        if status == AUTO_TWIN_CERTIFICATION_STATUS_PASS:
            continue

        if status == AUTO_TWIN_CERTIFICATION_STATUS_FAIL:
            failing.append(capability)
            continue

        if status in (
            AUTO_TWIN_CERTIFICATION_STATUS_UNRESOLVED,
            AUTO_TWIN_CERTIFICATION_STATUS_NOT_SUPPORTED,
        ):
            unresolved.append(capability)
            continue

        raise ValueError(
            "QCC_AUTO_TWIN_PROMOTION_READINESS_CAPABILITY_STATUS_INVALID"
        )

    references = {
        "failing_capabilities": tuple(failing),
        "unresolved_capabilities": tuple(unresolved),
    }

    if failing:
        return _finding(
            status=_FINDING_STATUS_BLOCKED,
            reason=f"CAPABILITY_{failing[0]}_FAIL",
            references=references,
        )

    if unresolved:
        first = unresolved[0]

        return _finding(
            status=_FINDING_STATUS_UNRESOLVED,
            reason=f"CAPABILITY_{first}_{capability_matrix[first]['status']}",
            references=references,
        )

    return _finding(
        status=_FINDING_STATUS_PASS, reason=None, references=references
    )


def _check_evidence_resolvable(
    certification_record, *, evidence_store, target_identity
):
    evidence = certification_record.get("evidence")
    suite_result_id = _text(
        evidence.get("suite_result_id") if isinstance(evidence, dict) else None
    )

    if not suite_result_id:
        return _finding(
            status=_FINDING_STATUS_UNRESOLVED,
            reason="SUITE_RESULT_ID_MISSING",
        )

    snapshot = evidence_store.candidate_snapshot(
        target_identity["twin_key"], target_identity["candidate_id"]
    )

    candidate_projection = snapshot.get("candidate")

    if not snapshot.get("found") or not isinstance(
        candidate_projection, dict
    ) or not candidate_projection.get("evidence_count"):
        return _finding(
            status=_FINDING_STATUS_UNRESOLVED,
            reason="VALIDATION_EVIDENCE_NOT_FOUND",
            references={"suite_result_id": suite_result_id},
        )

    latest_evidence = candidate_projection.get("latest_evidence") or {}
    recorded = latest_evidence.get("validation_evidence") or {}
    recorded_candidate_revision = recorded.get("candidate_revision")

    references = {
        "suite_result_id": suite_result_id,
        "evidence_count": candidate_projection.get("evidence_count"),
        "evidence_candidate_revision": recorded_candidate_revision,
    }

    if recorded_candidate_revision != target_identity["candidate_revision"]:
        return _finding(
            status=_FINDING_STATUS_BLOCKED,
            reason="VALIDATION_EVIDENCE_REVISION_MISMATCH",
            references=references,
        )

    return _finding(
        status=_FINDING_STATUS_PASS, reason=None, references=references
    )


def _check_candidate_current(candidate_store, *, target_identity):
    current = candidate_store.get_candidate(
        target_identity["twin_key"], target_identity["candidate_id"]
    )

    if current is None:
        return _finding(
            status=_FINDING_STATUS_UNRESOLVED,
            reason="CANDIDATE_NOT_FOUND_IN_STORE",
        )

    current_revision = current.get("candidate_revision")

    if current_revision != target_identity["candidate_revision"]:
        return _finding(
            status=_FINDING_STATUS_BLOCKED,
            reason="CANDIDATE_REVISION_STALE",
            references={"current_candidate_revision": current_revision},
        )

    status = current.get("status")

    if status == AUTO_TWIN_CANDIDATE_STATUS_REJECTED:
        return _finding(
            status=_FINDING_STATUS_BLOCKED,
            reason="CANDIDATE_STATUS_REJECTED",
            references={"candidate_status": status},
        )

    if status not in (
        AUTO_TWIN_CANDIDATE_STATUS_PENDING_VALIDATION,
        AUTO_TWIN_CANDIDATE_STATUS_VALIDATED,
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_PROMOTION_READINESS_CANDIDATE_STATUS_INVALID"
        )

    return _finding(
        status=_FINDING_STATUS_PASS,
        reason=None,
        references={"candidate_status": status},
    )


def _overall_readiness_status(checks):
    statuses = tuple(
        checks[name]["status"] for name in AUTO_TWIN_PROMOTION_READINESS_CHECKS
    )

    if _FINDING_STATUS_BLOCKED in statuses:
        return AUTO_TWIN_PROMOTION_READINESS_STATUS_BLOCKED

    if _FINDING_STATUS_UNRESOLVED in statuses:
        return AUTO_TWIN_PROMOTION_READINESS_STATUS_UNRESOLVED

    return AUTO_TWIN_PROMOTION_READINESS_STATUS_READY


def _readiness_id(record) -> str:
    payload = deepcopy(record)
    payload.pop("readiness_id", None)

    return hashlib.sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()


def evaluate_multi_site_promotion_readiness(
    *,
    managed_site,
    twin_key,
    candidate_id,
    candidate_revision,
    candidate_store,
    evidence_store,
    certification_record,
):
    """Builds the UWT-12D human promotion readiness gate result.

    ``managed_site``/``twin_key``/``candidate_id``/``candidate_revision``
    together declare the exact site + Twin candidate/revision a human
    reviewer is considering promoting. ``certification_record`` is the
    exact ``dict`` an earlier call to ``build_multi_site_certification``
    (UWT-12A) already produced for that same identity, or ``None`` if
    that certification has not been produced yet.

    Returns a deterministic record whose ``readiness_status`` is one
    of ``READY_FOR_HUMAN_PROMOTION`` / ``BLOCKED`` / ``UNRESOLVED``,
    together with the fixed six-check matrix and explicit
    ``blocking_reasons``/``unresolved_reasons`` a reviewer needs to
    act on. Never mutates ``candidate_store``/``evidence_store``,
    never promotes anything, never executes a browser/network
    operation: purely a read-only composition over already-governed
    evidence and identities.

    ``READY_FOR_HUMAN_PROMOTION`` is evidence for a later human/
    governed promotion decision -- it is never that decision itself,
    and this function never performs or triggers any promotion.
    """

    if not isinstance(managed_site, AutoTwinManagedSite):
        raise TypeError(
            "QCC_AUTO_TWIN_PROMOTION_READINESS_MANAGED_SITE_INVALID"
        )

    if not isinstance(candidate_store, AutoTwinCandidateRevisionStore):
        raise TypeError(
            "QCC_AUTO_TWIN_PROMOTION_READINESS_CANDIDATE_STORE_INVALID"
        )

    if not isinstance(evidence_store, AutoTwinValidationEvidenceStore):
        raise TypeError(
            "QCC_AUTO_TWIN_PROMOTION_READINESS_EVIDENCE_STORE_INVALID"
        )

    normalized_twin_key = _required_text(
        twin_key, error="QCC_AUTO_TWIN_KEY_REQUIRED"
    )

    if managed_site.twin_key != normalized_twin_key:
        raise ValueError(
            "QCC_AUTO_TWIN_PROMOTION_READINESS_SITE_TWIN_MISMATCH"
        )

    normalized_candidate_id = _required_text(
        candidate_id, error="QCC_AUTO_TWIN_CANDIDATE_ID_REQUIRED"
    )

    if isinstance(candidate_revision, bool) or not isinstance(
        candidate_revision, int
    ) or candidate_revision <= 0:
        raise ValueError(
            "QCC_AUTO_TWIN_PROMOTION_READINESS_CANDIDATE_REVISION_INVALID"
        )

    target_identity = {
        "site_code": managed_site.site_code,
        "twin_key": normalized_twin_key,
        "candidate_id": normalized_candidate_id,
        "candidate_revision": candidate_revision,
    }

    checks = {}

    (
        checks[AUTO_TWIN_PROMOTION_READINESS_CHECK_CERTIFICATION_PRESENT],
        certification_usable,
    ) = _check_certification_present(certification_record)

    if certification_usable:
        checks[AUTO_TWIN_PROMOTION_READINESS_CHECK_IDENTITY_BINDING] = (
            _check_identity_binding(
                certification_record, target_identity=target_identity
            )
        )
        checks[AUTO_TWIN_PROMOTION_READINESS_CHECK_OVERALL_VERDICT] = (
            _check_overall_verdict(certification_record)
        )
        checks[AUTO_TWIN_PROMOTION_READINESS_CHECK_CAPABILITY_MATRIX] = (
            _check_capability_matrix(certification_record)
        )
        checks[AUTO_TWIN_PROMOTION_READINESS_CHECK_EVIDENCE_RESOLVABLE] = (
            _check_evidence_resolvable(
                certification_record,
                evidence_store=evidence_store,
                target_identity=target_identity,
            )
        )
        checks[AUTO_TWIN_PROMOTION_READINESS_CHECK_CANDIDATE_CURRENT] = (
            _check_candidate_current(
                candidate_store, target_identity=target_identity
            )
        )
    else:
        for check_name in AUTO_TWIN_PROMOTION_READINESS_CHECKS:
            checks.setdefault(check_name, _missing_certification_finding())

    readiness_status = _overall_readiness_status(checks)

    blocking_reasons = tuple(
        checks[name]["reason"]
        for name in AUTO_TWIN_PROMOTION_READINESS_CHECKS
        if checks[name]["status"] == _FINDING_STATUS_BLOCKED
    )

    unresolved_reasons = tuple(
        checks[name]["reason"]
        for name in AUTO_TWIN_PROMOTION_READINESS_CHECKS
        if checks[name]["status"] == _FINDING_STATUS_UNRESOLVED
    )

    record = {
        "schema_version": AUTO_TWIN_PROMOTION_READINESS_SCHEMA_VERSION,
        "result_type": AUTO_TWIN_PROMOTION_READINESS_TYPE,

        "promotion_target_identity": target_identity,

        "checks": checks,

        "readiness_status": readiness_status,

        # Mirrors UWT-12A's own ``certifiable``: only an explicit
        # READY_FOR_HUMAN_PROMOTION -- every check itself PASS -- is
        # ever treated as readiness. This flag never promotes
        # anything ACTIVE by itself; it is evidence for a later
        # human/governed decision.
        "ready_for_human_promotion": (
            readiness_status == AUTO_TWIN_PROMOTION_READINESS_STATUS_READY
        ),

        "blocking_reasons": blocking_reasons,
        "unresolved_reasons": unresolved_reasons,

        "evidence": {
            "certification_id": (
                certification_record.get("certification_id")
                if isinstance(certification_record, dict)
                else None
            ),
        },

        # Explicit, always-true marker: this record is never, by
        # itself, a promotion -- the human/governed decision this
        # Work Order keeps binding is always the next, separate step.
        "human_only": True,
    }

    record["readiness_id"] = _readiness_id(record)

    return record
