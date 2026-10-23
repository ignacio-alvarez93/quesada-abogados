"""FCP-3A: deterministic, read-only promotion-readiness preflight.

The first incremental slice of FCP-3. It answers ONE question, without
changing anything: "is this governed feature worktree blocked, does it need
human reconciliation review, or may it be PRESENTED to a human for an
explicit promotion decision?"

It is NOT a promotion executor and it never approves anything. It never
merges, rebases, resets, checks out, commits, pushes, fetches or writes
refs, and it never reads Git itself: the SOLE source of repository,
ownership, evidence and reconciliation facts is one call of the approved
FCP-2B `runner_reconciliation.analyze_reconciliation`, which runs the FCP-1
assessment (twice when it analyzes, detecting drift) under the Runner
worktree lease and, with `ledger_root`, the FactoryLedger check.

Classification (`classify_promotion_readiness`, pure)
-----------------------------------------------------
- BLOCKED: anything unsafe, unknown, malformed, tampered, inconsistent or
  unproven - every FCP-1 classification other than the three below, every
  FCP-2B FAIL_CLOSED, a missing/unchecked ledger, and any received fact that
  FCP-1's own pure predicates do not re-confirm.
- RECONCILIATION_REVIEW_REQUIRED: FCP-1 STALE_BASE / NEEDS_RECONCILIATION
  with FCP-2B HUMAN_REQUIRED, SEMANTIC_REVIEW_REQUIRED or
  NO_TEXTUAL_CONFLICT. None of these authorizes integration: human semantic
  review and a fresh revalidation are still required.
- AWAITING_HUMAN_APPROVAL: ONLY a fresh FCP-1 ELIGIBLE_PENDING_APPROVAL with
  the exactly matching FCP-2B NOT_APPLICABLE analysis and every safety fact
  re-confirmed. It is NOT approval, NOT an executable promotion intent and
  NOT merge readiness.

The received results are re-verified, never trusted blindly: the FCP-2B
fingerprint and the FCP-1 fingerprint are recomputed with their own
modules' functions, and the FCP-1 facts are re-checked with FCP-1's own
pure predicates (`_findings`, `_unproven_safety_facts`) - no Git is read
and nothing of FCP-1/FCP-2B is reimplemented.

Every result has `human_approval_required=True`, `authorizes_action=False`
and `execution_allowed=False`. The fingerprint is a deterministic SHA-256
of canonical JSON identifying the inputs; it is NOT an authorization token
and a future executor (FCP-3B, separate Work Order) must not accept a
`PromotionReadiness` as authorization: it must define its own host
authorization binding, fresh revalidation, race control, postconditions and
rollback.
"""

from __future__ import annotations

import dataclasses
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    from scripts.ai import runner_integration as ri
    from scripts.ai import runner_reconciliation as rr
except ImportError:  # pragma: no cover - direct script execution
    _this_dir = Path(__file__).resolve().parent
    if str(_this_dir) not in sys.path:
        sys.path.insert(0, str(_this_dir))
    import runner_integration as ri  # type: ignore[no-redef]
    import runner_reconciliation as rr  # type: ignore[no-redef]


READINESS_SCHEMA = "fcp3a-promotion-readiness-v1"

# Classifications.
BLOCKED = "BLOCKED"
RECONCILIATION_REVIEW_REQUIRED = "RECONCILIATION_REVIEW_REQUIRED"
AWAITING_HUMAN_APPROVAL = "AWAITING_HUMAN_APPROVAL"
READINESS_CLASSIFICATIONS = (BLOCKED, RECONCILIATION_REVIEW_REQUIRED, AWAITING_HUMAN_APPROVAL)

REVIEWABLE_RECONCILIATIONS = frozenset({
    rr.HUMAN_REQUIRED, rr.SEMANTIC_REVIEW_REQUIRED, rr.NO_TEXTUAL_CONFLICT,
})

# Reason codes (every result).
PROMO_HUMAN_DECISION_REQUIRED = "PROMO_HUMAN_DECISION_REQUIRED"
PROMO_NOT_AUTHORIZATION = "PROMO_NOT_AUTHORIZATION"
# BLOCKED
PROMO_RECONCILIATION_FAILED = "PROMO_RECONCILIATION_FAILED"
PROMO_MALFORMED_ANALYSIS = "PROMO_MALFORMED_ANALYSIS"
PROMO_ANALYSIS_TAMPERED = "PROMO_ANALYSIS_TAMPERED"
PROMO_MALFORMED_ASSESSMENT = "PROMO_MALFORMED_ASSESSMENT"
PROMO_ASSESSMENT_TAMPERED = "PROMO_ASSESSMENT_TAMPERED"
PROMO_ASSESSMENT_MISMATCH = "PROMO_ASSESSMENT_MISMATCH"
PROMO_PROVENANCE_MISMATCH = "PROMO_PROVENANCE_MISMATCH"
PROMO_RECONCILIATION_FAIL_CLOSED = "PROMO_RECONCILIATION_FAIL_CLOSED"
PROMO_FCP1_NOT_PROMOTABLE = "PROMO_FCP1_NOT_PROMOTABLE"
PROMO_INCONSISTENT_CLASSIFICATION = "PROMO_INCONSISTENT_CLASSIFICATION"
PROMO_REASSESSMENT_UNPROVEN = "PROMO_REASSESSMENT_UNPROVEN"
PROMO_LEDGER_NOT_CHECKED = "PROMO_LEDGER_NOT_CHECKED"
PROMO_EVIDENCE_NOT_BOUND = "PROMO_EVIDENCE_NOT_BOUND"
PROMO_SAFETY_UNPROVEN = "PROMO_SAFETY_UNPROVEN"
# RECONCILIATION_REVIEW_REQUIRED
PROMO_RECONCILIATION_REVIEW = "PROMO_RECONCILIATION_REVIEW"
PROMO_SEMANTIC_REVIEW_REQUIRED = "PROMO_SEMANTIC_REVIEW_REQUIRED"
PROMO_FRESH_REVALIDATION_REQUIRED = "PROMO_FRESH_REVALIDATION_REQUIRED"
# AWAITING_HUMAN_APPROVAL
PROMO_ELIGIBLE_PENDING_HUMAN_APPROVAL = "PROMO_ELIGIBLE_PENDING_HUMAN_APPROVAL"

_ALWAYS = (PROMO_HUMAN_DECISION_REQUIRED, PROMO_NOT_AUTHORIZATION)


# ---------------------------------------------------------------------------
# Result (immutable)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PromotionReadiness:
    """Outcome of `classify_promotion_readiness`. Every value is copied
    verbatim from the FCP-2B analysis / FCP-1 assessment (None if absent),
    never invented or normalized. Nothing here approves, authorizes or
    allows any action, and it must never be accepted as authorization."""

    classification: str
    reason_codes: tuple
    fingerprint: str
    reconciliation_classification: Optional[str] = None
    reconciliation_fingerprint: Optional[str] = None
    reconciliation_reason_codes: tuple = ()
    assessment_classification: Optional[str] = None
    assessment_fingerprint: Optional[str] = None
    assessment_reason_codes: tuple = ()
    worktree_key: Optional[str] = None
    head_ref: Optional[str] = None
    head_sha: Optional[str] = None
    base_sha: Optional[str] = None
    attested_sha: Optional[str] = None
    base_status: Optional[str] = None
    merge_bases: tuple = ()
    evidence_status: Optional[str] = None
    ledger_checked: bool = False
    semantic_validation_required: bool = False
    human_approval_required: bool = True
    authorizes_action: bool = False
    execution_allowed: bool = False
    schema: str = READINESS_SCHEMA


class PromotionInputError(rr.ReconciliationInputError):
    """Refused input, before anything is read."""


# ---------------------------------------------------------------------------
# Fingerprint
# ---------------------------------------------------------------------------

def _readiness_payload(r: PromotionReadiness) -> dict:
    return {f.name: rr._canonical(getattr(r, f.name)) for f in dataclasses.fields(r) if f.name != "fingerprint"}


def readiness_fingerprint(readiness: PromotionReadiness) -> str:
    """Recomputes the canonical fingerprint (identity, not authorization)."""
    return rr._digest(_readiness_payload(readiness))


def _str_or_none(value) -> Optional[str]:
    return value if isinstance(value, str) else None


def _codes(value) -> tuple:
    if isinstance(value, tuple) and all(isinstance(v, str) for v in value):
        return value
    return ()


def _result(classification: str, reasons, analysis=None, assessment=None) -> PromotionReadiness:
    reasons = list(reasons)
    fields = {}
    if type(analysis) is rr.ReconciliationAnalysis:
        merge_bases = analysis.merge_bases
        fields.update(
            reconciliation_classification=_str_or_none(analysis.classification),
            reconciliation_fingerprint=_str_or_none(analysis.fingerprint),
            reconciliation_reason_codes=_codes(analysis.reason_codes),
            worktree_key=_str_or_none(analysis.worktree_key), head_ref=_str_or_none(analysis.head_ref),
            head_sha=_str_or_none(analysis.head_sha), base_sha=_str_or_none(analysis.base_sha),
            merge_bases=merge_bases if isinstance(merge_bases, tuple)
            and all(isinstance(m, str) for m in merge_bases) else (),
        )
        reasons.insert(0, f"FCP2B_{fields['reconciliation_classification']}")
    if isinstance(assessment, ri.IntegrationAssessment):
        base = assessment.base if isinstance(assessment.base, ri.CanonicalBase) else None
        candidate = assessment.candidate if isinstance(assessment.candidate, ri.IntegrationCandidate) else None
        evidence = assessment.evidence if isinstance(assessment.evidence, ri.EvidenceBinding) else None
        fields.update(
            assessment_classification=_str_or_none(assessment.classification),
            assessment_fingerprint=_str_or_none(assessment.fingerprint),
            assessment_reason_codes=_codes(assessment.reason_codes),
            attested_sha=_str_or_none(base.attested_sha) if base else None,
            base_status=_str_or_none(base.status) if base else None,
            evidence_status=_str_or_none(evidence.status) if evidence else None,
            ledger_checked=candidate is not None and candidate.ledger_checked is True,
        )
        reasons.insert(0, f"FCP1_{fields['assessment_classification']}")
    fields["semantic_validation_required"] = classification == RECONCILIATION_REVIEW_REQUIRED
    draft = PromotionReadiness(
        classification=classification, reason_codes=tuple(dict.fromkeys(reasons + list(_ALWAYS))),
        fingerprint="", **fields,
    )
    return dataclasses.replace(draft, fingerprint=readiness_fingerprint(draft))


def _blocked(reasons, analysis=None, assessment=None) -> PromotionReadiness:
    return _result(BLOCKED, reasons, analysis, assessment)


# ---------------------------------------------------------------------------
# Re-verification of the received FCP-2B / FCP-1 results (pure, no Git)
# ---------------------------------------------------------------------------

def _analysis_errors(analysis: rr.ReconciliationAnalysis) -> list:
    errors = []
    try:
        if analysis.fingerprint != rr._digest(rr._analysis_payload(analysis)):
            errors.append(PROMO_ANALYSIS_TAMPERED)
    except Exception:  # noqa: BLE001 - any failure is a fail-closed signal
        errors.append(PROMO_ANALYSIS_TAMPERED)
    if analysis.human_approval_required is not True or analysis.authorizes_action is not False \
            or analysis.schema != rr.ANALYSIS_SCHEMA \
            or analysis.classification not in rr.RECONCILIATION_PRECEDENCE \
            or not isinstance(analysis.reason_codes, tuple) \
            or not all(isinstance(code, str) for code in analysis.reason_codes):
        errors.append(PROMO_ANALYSIS_TAMPERED)
    return errors


def _assessment_errors(analysis: rr.ReconciliationAnalysis, a) -> list:
    if not isinstance(a, ri.IntegrationAssessment) or not isinstance(a.base, ri.CanonicalBase) \
            or not isinstance(a.candidate, ri.IntegrationCandidate) \
            or not isinstance(a.evidence, ri.EvidenceBinding) or not isinstance(a.classification, str) \
            or not isinstance(a.reason_codes, tuple):
        return [PROMO_MALFORMED_ASSESSMENT]
    errors = []
    if not isinstance(a.fingerprint, str) or rr._fcp1_fingerprint(a) != a.fingerprint:
        errors.append(PROMO_ASSESSMENT_TAMPERED)
    if a.human_approval_required is not True \
            or a.eligible is not (a.classification == ri.ELIGIBLE_PENDING_APPROVAL):
        errors.append(PROMO_ASSESSMENT_TAMPERED)
    if analysis.assessment_fingerprint != a.fingerprint or analysis.assessment_classification != a.classification:
        errors.append(PROMO_ASSESSMENT_MISMATCH)
    c = a.candidate
    provenance = (c.worktree_key, c.head_ref, c.head_sha, c.base_tracking_sha, tuple(c.merge_bases))
    # The candidate's own base equality is a safety fact, re-checked by
    # `_fcp1_reconfirmation` (UNPROVEN_CANDIDATE_BASE / CANDIDATE_BASE_MISMATCH).
    if (analysis.worktree_key, analysis.head_ref, analysis.head_sha, analysis.base_sha,
            analysis.merge_bases) != provenance:
        errors.append(PROMO_PROVENANCE_MISMATCH)
    return errors


def _ownership_errors(c: ri.IntegrationCandidate) -> list:
    """A promotion preflight requires the FactoryLedger to have been checked
    (FCP-1 skips it without `ledger_root`) and to show no active worker."""
    if c.ledger_checked is not True or c.ledger_error is not None or c.active_workers != ():
        return [PROMO_LEDGER_NOT_CHECKED]
    return []


def _fcp1_reconfirmation(a: ri.IntegrationAssessment, expected: str) -> list:
    """Re-checks the received FCP-1 facts with FCP-1's own pure predicates:
    every finding ranked above `expected` must be empty, `expected` itself
    must be found (unless it is the eligible outcome, which has none) and no
    mandatory safety fact may be unproven."""
    errors = []
    if a.evidence.status != ri.EVIDENCE_BOUND:
        errors.append(PROMO_EVIDENCE_NOT_BOUND)
    try:
        found = ri._findings(a.base, a.candidate, a.evidence)
        unproven = ri._unproven_safety_facts(a.base, a.candidate)
    except Exception:  # noqa: BLE001
        return errors + [PROMO_SAFETY_UNPROVEN]
    if expected == ri.ELIGIBLE_PENDING_APPROVAL:
        above = ri.CLASSIFICATION_PRECEDENCE
        c = a.candidate
        relation_known = isinstance(c.ahead, int) and not isinstance(c.ahead, bool) and c.ahead > 0 \
            and c.behind == 0 and len(c.merge_bases) == 1
        if not relation_known or a.reason_codes != ():
            errors.append(PROMO_SAFETY_UNPROVEN)
    else:
        above = ri.CLASSIFICATION_PRECEDENCE[:ri.CLASSIFICATION_PRECEDENCE.index(expected)]
        if not found[expected]:
            errors.append(PROMO_SAFETY_UNPROVEN)
    if any(found[name] for name in above if name != expected) or unproven:
        errors.append(PROMO_SAFETY_UNPROVEN)
    return errors


def _reassessment_errors(analysis: rr.ReconciliationAnalysis, a: ri.IntegrationAssessment) -> list:
    f = analysis.facts
    if type(f) is not rr.ReconciliationFacts or f.read_errors != () \
            or f.assessment_fingerprint != a.fingerprint \
            or (f.reassessment_fingerprint, f.reassessment_classification) != (a.fingerprint, a.classification):
        return [PROMO_REASSESSMENT_UNPROVEN]
    return []


def classify_promotion_readiness(analysis) -> PromotionReadiness:
    """Pure, fail-closed classification of one FCP-2B ReconciliationAnalysis.
    Never raises for any input; anything not proven is BLOCKED."""
    try:
        return _classify(analysis)
    except Exception:  # noqa: BLE001 - malformed input must never escape as success
        return _blocked([PROMO_MALFORMED_ANALYSIS])


def _classify(analysis) -> PromotionReadiness:
    if type(analysis) is not rr.ReconciliationAnalysis:
        return _blocked([PROMO_MALFORMED_ANALYSIS])
    errors = _analysis_errors(analysis)
    a = analysis.assessment
    if a is None:
        return _blocked(errors + ([PROMO_RECONCILIATION_FAIL_CLOSED] if analysis.classification == rr.FAIL_CLOSED
                                  else [PROMO_MALFORMED_ASSESSMENT]), analysis)
    errors += _assessment_errors(analysis, a)
    if PROMO_MALFORMED_ASSESSMENT in errors:
        return _blocked(errors, analysis)
    if errors:
        return _blocked(errors, analysis, a)

    recon, fcp1 = analysis.classification, a.classification
    if recon == rr.FAIL_CLOSED:
        return _blocked([PROMO_RECONCILIATION_FAIL_CLOSED], analysis, a)

    if fcp1 == ri.ELIGIBLE_PENDING_APPROVAL:
        exact = (
            recon == rr.NOT_APPLICABLE
            and analysis.reason_codes == (rr.RECON_NOT_APPLICABLE, f"FCP1_{ri.ELIGIBLE_PENDING_APPROVAL}")
            and analysis.facts is None and analysis.path_findings == ()
            and analysis.semantic_validation_required is False and a.eligible is True
        )
        if not exact:
            return _blocked([PROMO_INCONSISTENT_CLASSIFICATION], analysis, a)
        errors = _ownership_errors(a.candidate) + _fcp1_reconfirmation(a, fcp1)
        if errors:
            return _blocked(errors, analysis, a)
        return _result(AWAITING_HUMAN_APPROVAL, [PROMO_ELIGIBLE_PENDING_HUMAN_APPROVAL], analysis, a)

    if fcp1 in rr.RECONCILABLE_FCP1_CLASSIFICATIONS:
        consistent = (
            recon in REVIEWABLE_RECONCILIATIONS and a.eligible is False
            and analysis.semantic_validation_required is True
            and rr.RECON_SEMANTIC_VALIDATION_REQUIRED in analysis.reason_codes
        )
        if not consistent:
            return _blocked([PROMO_INCONSISTENT_CLASSIFICATION], analysis, a)
        errors = (_reassessment_errors(analysis, a) + _ownership_errors(a.candidate)
                  + _fcp1_reconfirmation(a, fcp1))
        if errors:
            return _blocked(errors, analysis, a)
        return _result(RECONCILIATION_REVIEW_REQUIRED, [
            PROMO_RECONCILIATION_REVIEW, PROMO_SEMANTIC_REVIEW_REQUIRED, PROMO_FRESH_REVALIDATION_REQUIRED,
        ], analysis, a)

    if recon != rr.NOT_APPLICABLE:
        return _blocked([PROMO_INCONSISTENT_CLASSIFICATION], analysis, a)
    return _blocked([PROMO_FCP1_NOT_PROMOTABLE], analysis, a)


# ---------------------------------------------------------------------------
# Read-only preflight
# ---------------------------------------------------------------------------

def _path_like(value) -> bool:
    if isinstance(value, os.PathLike):
        value = os.fspath(value)
    return isinstance(value, str) and bool(value) and "\0" not in value


def _check_inputs(worktree, attested_sha, authorized_scopes, expected_remote_url, ledger_root, lease_root,
                  max_paths) -> None:
    # The same refusal FCP-2B applies, kept ahead of any read (bool is not an int here).
    if not rr._is_int(max_paths, 1) or max_paths > rr.MAX_PATHS:
        raise rr.ReconciliationInputError(f"max_paths must be an int in 1..{rr.MAX_PATHS}")
    if not _path_like(worktree):
        raise PromotionInputError("worktree must be a non-empty path")
    if attested_sha is not None and not isinstance(attested_sha, str):
        raise PromotionInputError("attested_sha must be a string or None")
    if not isinstance(authorized_scopes, (list, tuple)) \
            or not all(isinstance(s, str) for s in authorized_scopes):
        raise PromotionInputError("authorized_scopes must be a list or tuple of strings")
    if expected_remote_url is not None and not isinstance(expected_remote_url, str):
        raise PromotionInputError("expected_remote_url must be a string or None")
    for name, root in (("ledger_root", ledger_root), ("lease_root", lease_root)):
        if root is not None and not _path_like(root):
            raise PromotionInputError(f"{name} must be a non-empty path or None")


def assess_promotion_readiness(
    worktree, *, attested_sha: Optional[str], authorized_scopes, expected_remote_url: Optional[str] = None,
    evidence=None, ledger_root=None, lease_root=None, max_paths: int = rr.MAX_PATHS,
) -> PromotionReadiness:
    """Read-only promotion-readiness preflight of `worktree`: exactly one
    FCP-2B `analyze_reconciliation` call with the inputs forwarded
    unchanged, then pure classification. Malformed inputs (including an
    invalid `max_paths`) are refused before anything is read; every other
    problem is a BLOCKED result. The result never authorizes anything."""
    _check_inputs(worktree, attested_sha, authorized_scopes, expected_remote_url, ledger_root, lease_root,
                  max_paths)
    try:
        analysis = rr.analyze_reconciliation(
            worktree, attested_sha=attested_sha, authorized_scopes=authorized_scopes,
            expected_remote_url=expected_remote_url, evidence=evidence, ledger_root=ledger_root,
            lease_root=lease_root, max_paths=max_paths,
        )
    except rr.ReconciliationInputError:
        raise
    except Exception:  # noqa: BLE001 - no detail is exposed; the result is BLOCKED
        return _blocked([PROMO_RECONCILIATION_FAILED])
    return classify_promotion_readiness(analysis)
