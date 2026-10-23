"""FCP-3B-1: approval-bound promotion INTENT and fresh revalidation.

The first incremental slice of FCP-3B. It builds, without changing anything,
an immutable, reviewable PROPOSAL of one future promotion of one specific
feature commit onto one specific canonical base, and later revalidates that
proposal against independently re-read FCP-3A facts.

It is NOT an approval, NOT an authorization receipt and NOT an executor. It
never merges, rebases, resets, checks out, commits, pushes, fetches or
writes refs, never reads Git itself and keeps no durable state. Its only
read is ONE call of the approved FCP-3A
`runner_promotion.assess_promotion_readiness` (which itself performs exactly
one FCP-2B analysis under the Runner worktree lease and, with
`ledger_root`, the FactoryLedger check).

Intent (`prepare_promotion_intent`, pure)
-----------------------------------------
Only a self-consistent FCP-3A AWAITING_HUMAN_APPROVAL readiness (exact
eligible FCP-1 / FCP-2B outcome, verified base, bound evidence, checked
ledger) may be proposed. The intent binds the exact FCP-3A, FCP-2B and FCP-1
fingerprints and classifications, the worktree key, branch ref, feature
HEAD, canonical base SHA, host-attested SHA, merge base(s), ONE named
descriptive action (`PROPOSED_ACTIONS`) and an explicit, non-empty set of
authorized scopes. Anything else is refused with `PromotionIntentRefused`
carrying stable reason codes; no intent object exists for refused input.

Scopes are explicit repository-relative path subtrees in the exact form
FCP-1's own normalizer (`claude_runner.normalize_authorized_scope`) keeps
unchanged; globs and duplicates are refused, so no path outside them is
implied safe. A readiness does not record its scopes: the binding is proven
only by a fresh FCP-3A read performed WITH the intent's scopes, because the
FCP-1 fingerprint covers the normalized scopes (`revalidate_promotion_intent`).

Validation (`validate_promotion_intent`, pure)
----------------------------------------------
Recomputes the intent fingerprint and re-checks every invariant, then
re-derives the intent the supplied fresh readiness would yield (same action
and scopes) and compares every field. Any tampering, drift (HEAD, base,
branch, worktree, merge base, attestation, evidence, FCP-1/FCP-2B/FCP-3A
fingerprint or classification), ineligible fresh readiness or malformed
object is a non-valid result. The pure validator cannot prove that the
supplied readiness is fresh (it carries `INTENT_FRESHNESS_NOT_PROVEN`);
`revalidate_promotion_intent` performs the read itself.

Every intent and validation has `human_approval_required=True`,
`authorizes_action=False` and `execution_allowed=False`. A fingerprint is a
deterministic SHA-256 identity digest of canonical JSON, never a proof of
human consent, and `valid=True` only means "the proposal still matches".
Trusted authenticated approval, revocation/expiry, replay protection,
atomic ref race control, postconditions and rollback belong to the
separately reviewed FCP-3B-2 execution contract, which must not accept an
intent or a validation from this module as permission to mutate anything.
"""

from __future__ import annotations

import dataclasses
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    from scripts.ai import claude_runner
    from scripts.ai import runner_integration as ri
    from scripts.ai import runner_promotion as rp
    from scripts.ai import runner_reconciliation as rr
except ImportError:  # pragma: no cover - direct script execution
    _this_dir = Path(__file__).resolve().parent
    if str(_this_dir) not in sys.path:
        sys.path.insert(0, str(_this_dir))
    import claude_runner  # type: ignore[no-redef]
    import runner_integration as ri  # type: ignore[no-redef]
    import runner_promotion as rp  # type: ignore[no-redef]
    import runner_reconciliation as rr  # type: ignore[no-redef]


INTENT_SCHEMA = "fcp3b1-promotion-intent-v1"
VALIDATION_SCHEMA = "fcp3b1-promotion-intent-validation-v1"

STATUS_PROPOSED = "PROPOSED"

# The ONE named future mechanism an intent may describe. Descriptive only:
# it is never a command, a ref update or anything this module executes.
FAST_FORWARD_CANDIDATE_TO_DEVELOP = "FAST_FORWARD_CANDIDATE_TO_DEVELOP"
PROPOSED_ACTIONS = (FAST_FORWARD_CANDIDATE_TO_DEVELOP,)

# Validation outcomes and modes.
MATCHES_PROPOSAL = "MATCHES_PROPOSAL"
REJECTED = "REJECTED"
MODE_SUPPLIED_READINESS = "SUPPLIED_READINESS"
MODE_FRESH_FCP3A_READ = "FRESH_FCP3A_READ"

# Reason codes (every intent).
INTENT_PROPOSAL_ONLY = "INTENT_PROPOSAL_ONLY"
INTENT_HUMAN_APPROVAL_REQUIRED = "INTENT_HUMAN_APPROVAL_REQUIRED"
INTENT_NOT_AUTHORIZATION = "INTENT_NOT_AUTHORIZATION"
INTENT_FRESH_REVALIDATION_REQUIRED = "INTENT_FRESH_REVALIDATION_REQUIRED"
INTENT_EXECUTION_CONTRACT_REQUIRED = "INTENT_EXECUTION_CONTRACT_REQUIRED"
# Refusals (prepare; also reported for an ineligible fresh readiness).
INTENT_READINESS_MALFORMED = "INTENT_READINESS_MALFORMED"
INTENT_READINESS_TAMPERED = "INTENT_READINESS_TAMPERED"
INTENT_READINESS_BLOCKED = "INTENT_READINESS_BLOCKED"
INTENT_READINESS_REVIEW_REQUIRED = "INTENT_READINESS_REVIEW_REQUIRED"
INTENT_READINESS_NOT_ELIGIBLE = "INTENT_READINESS_NOT_ELIGIBLE"
INTENT_LEDGER_NOT_CHECKED = "INTENT_LEDGER_NOT_CHECKED"
INTENT_IDENTITY_INVALID = "INTENT_IDENTITY_INVALID"
INTENT_SHA_INVALID = "INTENT_SHA_INVALID"
INTENT_HEAD_EQUALS_BASE = "INTENT_HEAD_EQUALS_BASE"
INTENT_ATTESTATION_MISMATCH = "INTENT_ATTESTATION_MISMATCH"
INTENT_NOT_FAST_FORWARD = "INTENT_NOT_FAST_FORWARD"
INTENT_ACTION_INVALID = "INTENT_ACTION_INVALID"
INTENT_SCOPE_MISSING = "INTENT_SCOPE_MISSING"
INTENT_SCOPE_INVALID = "INTENT_SCOPE_INVALID"
# Validation.
INTENT_MALFORMED = "INTENT_MALFORMED"
INTENT_TAMPERED = "INTENT_TAMPERED"
INTENT_FRESH_READINESS_MISSING = "INTENT_FRESH_READINESS_MISSING"
INTENT_FRESH_READINESS_INELIGIBLE = "INTENT_FRESH_READINESS_INELIGIBLE"
INTENT_FRESH_READ_FAILED = "INTENT_FRESH_READ_FAILED"
INTENT_STALE_READINESS = "INTENT_STALE_READINESS"
INTENT_STALE_RECONCILIATION = "INTENT_STALE_RECONCILIATION"
INTENT_STALE_ASSESSMENT = "INTENT_STALE_ASSESSMENT"
INTENT_STALE_WORKTREE = "INTENT_STALE_WORKTREE"
INTENT_STALE_BRANCH = "INTENT_STALE_BRANCH"
INTENT_STALE_HEAD = "INTENT_STALE_HEAD"
INTENT_STALE_BASE = "INTENT_STALE_BASE"
INTENT_STALE_ATTESTATION = "INTENT_STALE_ATTESTATION"
INTENT_STALE_MERGE_BASE = "INTENT_STALE_MERGE_BASE"
INTENT_STALE_BINDING = "INTENT_STALE_BINDING"
INTENT_SCOPE_DRIFT = "INTENT_SCOPE_DRIFT"
INTENT_MATCHES_FRESH_READINESS = "INTENT_MATCHES_FRESH_READINESS"
INTENT_FRESHNESS_NOT_PROVEN = "INTENT_FRESHNESS_NOT_PROVEN"
INTENT_FRESH_FCP3A_READ = "INTENT_FRESH_FCP3A_READ"
INTENT_VALIDATION_NOT_APPROVAL = "INTENT_VALIDATION_NOT_APPROVAL"

_INTENT_REASONS = (
    INTENT_PROPOSAL_ONLY, INTENT_HUMAN_APPROVAL_REQUIRED, INTENT_NOT_AUTHORIZATION,
    INTENT_FRESH_REVALIDATION_REQUIRED, INTENT_EXECUTION_CONTRACT_REQUIRED,
)
_VALIDATION_ALWAYS = (INTENT_VALIDATION_NOT_APPROVAL, INTENT_HUMAN_APPROVAL_REQUIRED, INTENT_NOT_AUTHORIZATION)

# The exact reason codes FCP-3A gives its only proposable outcome.
_ELIGIBLE_READINESS_REASONS = (
    f"FCP1_{ri.ELIGIBLE_PENDING_APPROVAL}", f"FCP2B_{rr.NOT_APPLICABLE}",
    rp.PROMO_ELIGIBLE_PENDING_HUMAN_APPROVAL, rp.PROMO_HUMAN_DECISION_REQUIRED, rp.PROMO_NOT_AUTHORIZATION,
)
_ELIGIBLE_RECONCILIATION_REASONS = (rr.RECON_NOT_APPLICABLE, f"FCP1_{ri.ELIGIBLE_PENDING_APPROVAL}")

_DIGEST_RE = re.compile(r"[0-9a-f]{64}")
_GLOB_CHARS = frozenset("*?[")


# ---------------------------------------------------------------------------
# Results (immutable)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PromotionIntent:
    """An untrusted, reviewable PROPOSAL of one future promotion. Every bound
    identity is copied verbatim from one FCP-3A readiness. It is not an
    approval, not a credential and never authorizes or allows any action."""

    status: str
    proposed_action: str
    reason_codes: tuple
    fingerprint: str
    readiness_fingerprint: str
    readiness_classification: str
    reconciliation_fingerprint: str
    reconciliation_classification: str
    assessment_fingerprint: str
    assessment_classification: str
    worktree_key: str
    head_ref: str
    head_sha: str
    canonical_base_ref: str
    base_sha: str
    attested_sha: str
    merge_bases: tuple
    authorized_scopes: tuple
    human_approval_required: bool = True
    authorizes_action: bool = False
    execution_allowed: bool = False
    schema: str = INTENT_SCHEMA


@dataclass(frozen=True)
class PromotionIntentValidation:
    """Outcome of revalidating one intent. `valid=True` (MATCHES_PROPOSAL)
    only means the proposal still matches the fresh FCP-3A facts; it is NOT
    a human approval and never authorizes or allows any action."""

    valid: bool
    outcome: str
    reason_codes: tuple
    fingerprint: str
    mode: str
    intent_fingerprint: Optional[str] = None
    fresh_readiness_fingerprint: Optional[str] = None
    fresh_readiness_classification: Optional[str] = None
    mismatched_fields: tuple = ()
    human_approval_required: bool = True
    authorizes_action: bool = False
    execution_allowed: bool = False
    schema: str = VALIDATION_SCHEMA


class PromotionIntentRefused(ValueError):
    """`prepare_promotion_intent` refused its input. Carries only stable
    reason codes, never input values."""

    def __init__(self, reason_codes):
        self.reason_codes = tuple(dict.fromkeys(reason_codes))
        super().__init__(", ".join(self.reason_codes))


# ---------------------------------------------------------------------------
# Fingerprints
# ---------------------------------------------------------------------------

def _payload(value) -> dict:
    return {f.name: rr._canonical(getattr(value, f.name)) for f in dataclasses.fields(value) if f.name != "fingerprint"}


def intent_fingerprint(intent: PromotionIntent) -> str:
    """Recomputes the canonical intent fingerprint (identity, not consent)."""
    return rr._digest(_payload(intent))


def validation_fingerprint(validation: PromotionIntentValidation) -> str:
    """Recomputes the canonical validation fingerprint (identity, not consent)."""
    return rr._digest(_payload(validation))


# ---------------------------------------------------------------------------
# Pure checks
# ---------------------------------------------------------------------------

def _plain(value) -> bool:
    """Only exact built-in scalars and tuples of them: comparisons and
    digests of such values cannot be subverted by overridden methods."""
    if value is None or type(value) in (str, bool, int):
        return True
    return type(value) is tuple and all(_plain(v) for v in value)


def _all_plain(obj) -> bool:
    return all(_plain(getattr(obj, f.name)) for f in dataclasses.fields(obj))


def _text(value) -> bool:
    return type(value) is str and value != "" and value.strip() == value \
        and not any(ord(ch) < 32 or ord(ch) == 127 for ch in value)


def _binding_errors(worktree_key, head_ref, head_sha, base_sha, attested_sha, merge_bases, digests) -> list:
    """Identity checks shared by a readiness being proposed and a received
    intent. The readiness does not carry the repository object format, so
    every SHA must be a full FCP-1 SHA of the SAME format as the HEAD."""
    errors = []
    if not _text(worktree_key) or not _text(head_ref) or not head_ref.startswith("refs/heads/") \
            or head_ref == "refs/heads/" or head_ref == ri.LOCAL_BRANCH_REF or " " in head_ref \
            or not all(type(d) is str and _DIGEST_RE.fullmatch(d) for d in digests):
        errors.append(INTENT_IDENTITY_INVALID)
    fmt = next((f for f in ri._SHA_PATTERNS if ri._is_sha(head_sha, f)), None)
    shas_ok = fmt is not None and type(merge_bases) is tuple \
        and all(type(s) is str and ri._is_sha(s, fmt) for s in (head_sha, base_sha, attested_sha, *merge_bases))
    if not shas_ok:
        return errors + [INTENT_SHA_INVALID]
    if head_sha == base_sha:
        errors.append(INTENT_HEAD_EQUALS_BASE)
    if attested_sha != base_sha:
        errors.append(INTENT_ATTESTATION_MISMATCH)
    # A fast-forward candidate's sole merge base is the canonical base itself.
    if merge_bases != (base_sha,):
        errors.append(INTENT_NOT_FAST_FORWARD)
    return errors


def _readiness_errors(r) -> list:
    """Why `r` may not be proposed ([] if it may). Self-consistency only:
    whether `r` is FRESH is never decided here."""
    if type(r) is not rp.PromotionReadiness or not _all_plain(r):
        return [INTENT_READINESS_MALFORMED]
    try:
        tampered = r.fingerprint != rp.readiness_fingerprint(r)
    except Exception:  # noqa: BLE001 - any failure is a fail-closed signal
        tampered = True
    if tampered or r.schema != rp.READINESS_SCHEMA or r.human_approval_required is not True \
            or r.authorizes_action is not False or r.execution_allowed is not False:
        return [INTENT_READINESS_TAMPERED]  # nothing else in it is trusted
    ledger = [INTENT_LEDGER_NOT_CHECKED] if r.ledger_checked is not True \
        or rp.PROMO_LEDGER_NOT_CHECKED in r.reason_codes else []
    if r.classification == rp.BLOCKED:
        return [INTENT_READINESS_BLOCKED] + ledger
    if r.classification == rp.RECONCILIATION_REVIEW_REQUIRED:
        return [INTENT_READINESS_REVIEW_REQUIRED] + ledger
    exact = (
        r.classification == rp.AWAITING_HUMAN_APPROVAL and r.reason_codes == _ELIGIBLE_READINESS_REASONS
        and r.assessment_classification == ri.ELIGIBLE_PENDING_APPROVAL and r.assessment_reason_codes == ()
        and r.reconciliation_classification == rr.NOT_APPLICABLE
        and r.reconciliation_reason_codes == _ELIGIBLE_RECONCILIATION_REASONS
        and r.base_status == ri.BASE_VERIFIED and r.evidence_status == ri.EVIDENCE_BOUND
        and r.semantic_validation_required is False
    )
    errors = ledger + ([] if exact else [INTENT_READINESS_NOT_ELIGIBLE])
    return errors + _binding_errors(r.worktree_key, r.head_ref, r.head_sha, r.base_sha, r.attested_sha,
                                    r.merge_bases, (r.fingerprint, r.reconciliation_fingerprint,
                                                    r.assessment_fingerprint))


def _action_errors(action) -> list:
    return [] if type(action) is str and action in PROPOSED_ACTIONS else [INTENT_ACTION_INVALID]


def _canonical_scopes(raw):
    """(sorted scope tuple, errors). Each scope must already be in the exact
    form FCP-1's normalizer keeps unchanged (no implicit rewriting), be a
    path subtree rather than a glob, and appear once."""
    if type(raw) not in (list, tuple):
        return (), [INTENT_SCOPE_INVALID]
    if not raw:
        return (), [INTENT_SCOPE_MISSING]
    for scope in raw:
        if type(scope) is not str or not _text(scope) or _GLOB_CHARS & set(scope):
            return (), [INTENT_SCOPE_INVALID]
        try:
            if claude_runner.normalize_authorized_scope(scope) != scope:
                return (), [INTENT_SCOPE_INVALID]
        except ValueError:
            return (), [INTENT_SCOPE_INVALID]
    if len(set(raw)) != len(raw):
        return (), [INTENT_SCOPE_INVALID]
    return tuple(sorted(raw)), []


def _build(readiness, proposed_action, authorized_scopes) -> PromotionIntent:
    errors = _readiness_errors(readiness) + _action_errors(proposed_action)
    scopes, scope_errors = _canonical_scopes(authorized_scopes)
    errors += scope_errors
    if errors:
        raise PromotionIntentRefused(errors)
    r = readiness
    draft = PromotionIntent(
        status=STATUS_PROPOSED, proposed_action=proposed_action, reason_codes=_INTENT_REASONS, fingerprint="",
        readiness_fingerprint=r.fingerprint, readiness_classification=r.classification,
        reconciliation_fingerprint=r.reconciliation_fingerprint,
        reconciliation_classification=r.reconciliation_classification,
        assessment_fingerprint=r.assessment_fingerprint, assessment_classification=r.assessment_classification,
        worktree_key=r.worktree_key, head_ref=r.head_ref, head_sha=r.head_sha, canonical_base_ref=ri.TRACKING_REF,
        base_sha=r.base_sha, attested_sha=r.attested_sha, merge_bases=r.merge_bases, authorized_scopes=scopes,
    )
    return dataclasses.replace(draft, fingerprint=intent_fingerprint(draft))


def prepare_promotion_intent(readiness, *, proposed_action, authorized_scopes) -> PromotionIntent:
    """Pure: the PROPOSED intent for one FCP-3A AWAITING_HUMAN_APPROVAL
    readiness, `proposed_action` (one of PROPOSED_ACTIONS) and explicit
    `authorized_scopes`. Raises `PromotionIntentRefused` (stable reason
    codes) for anything else. The intent authorizes nothing."""
    try:
        return _build(readiness, proposed_action, authorized_scopes)
    except PromotionIntentRefused:
        raise
    except Exception:  # noqa: BLE001 - malformed input must never escape as success
        raise PromotionIntentRefused([INTENT_READINESS_MALFORMED]) from None


def _intent_errors(intent) -> list:
    if type(intent) is not PromotionIntent or not _all_plain(intent):
        return [INTENT_MALFORMED]
    try:
        tampered = intent.fingerprint != intent_fingerprint(intent)
    except Exception:  # noqa: BLE001
        tampered = True
    scopes, scope_errors = _canonical_scopes(intent.authorized_scopes)
    invariants = (
        intent.schema == INTENT_SCHEMA and intent.status == STATUS_PROPOSED
        and intent.reason_codes == _INTENT_REASONS and intent.human_approval_required is True
        and intent.authorizes_action is False and intent.execution_allowed is False
        and not _action_errors(intent.proposed_action)
        and intent.readiness_classification == rp.AWAITING_HUMAN_APPROVAL
        and intent.reconciliation_classification == rr.NOT_APPLICABLE
        and intent.assessment_classification == ri.ELIGIBLE_PENDING_APPROVAL
        and intent.canonical_base_ref == ri.TRACKING_REF
        and not scope_errors and scopes == intent.authorized_scopes
        and not _binding_errors(intent.worktree_key, intent.head_ref, intent.head_sha, intent.base_sha,
                                intent.attested_sha, intent.merge_bases,
                                (intent.readiness_fingerprint, intent.reconciliation_fingerprint,
                                 intent.assessment_fingerprint))
    )
    return [INTENT_TAMPERED] if tampered or not invariants else []


# Each bound field and the stable code reported when it no longer matches.
_STALE_CODES = (
    ("readiness_fingerprint", INTENT_STALE_READINESS),
    ("reconciliation_fingerprint", INTENT_STALE_RECONCILIATION),
    ("reconciliation_classification", INTENT_STALE_RECONCILIATION),
    ("assessment_fingerprint", INTENT_STALE_ASSESSMENT),
    ("assessment_classification", INTENT_STALE_ASSESSMENT),
    ("worktree_key", INTENT_STALE_WORKTREE),
    ("head_ref", INTENT_STALE_BRANCH),
    ("head_sha", INTENT_STALE_HEAD),
    ("base_sha", INTENT_STALE_BASE),
    ("attested_sha", INTENT_STALE_ATTESTATION),
    ("merge_bases", INTENT_STALE_MERGE_BASE),
)
_STALE_BY_FIELD = dict(_STALE_CODES)


def _validation(valid: bool, reasons, mode: str, intent=None, fresh=None, mismatched=()) -> PromotionIntentValidation:
    mode_code = INTENT_FRESH_FCP3A_READ if mode == MODE_FRESH_FCP3A_READ else INTENT_FRESHNESS_NOT_PROVEN
    fields = {}
    if type(intent) is PromotionIntent and type(intent.fingerprint) is str and _DIGEST_RE.fullmatch(intent.fingerprint):
        fields["intent_fingerprint"] = intent.fingerprint
    if type(fresh) is rp.PromotionReadiness:
        if type(fresh.fingerprint) is str and _DIGEST_RE.fullmatch(fresh.fingerprint):
            fields["fresh_readiness_fingerprint"] = fresh.fingerprint
        if type(fresh.classification) is str and fresh.classification in rp.READINESS_CLASSIFICATIONS:
            fields["fresh_readiness_classification"] = fresh.classification
    draft = PromotionIntentValidation(
        valid=valid, outcome=MATCHES_PROPOSAL if valid else REJECTED,
        reason_codes=tuple(dict.fromkeys(list(reasons) + [mode_code] + list(_VALIDATION_ALWAYS))),
        fingerprint="", mode=mode, mismatched_fields=tuple(mismatched), **fields,
    )
    return dataclasses.replace(draft, fingerprint=validation_fingerprint(draft))


def _validate(intent, fresh, mode: str, forwarded_scopes=None) -> PromotionIntentValidation:
    errors = _intent_errors(intent)
    if errors:
        return _validation(False, errors, mode, intent, fresh)
    scope_drift = []
    if mode == MODE_FRESH_FCP3A_READ:
        scopes, scope_errors = _canonical_scopes(forwarded_scopes)
        if scope_errors or scopes != intent.authorized_scopes:
            scope_drift = [INTENT_SCOPE_DRIFT]
    if fresh is None:
        return _validation(False, scope_drift + [INTENT_FRESH_READINESS_MISSING], mode, intent)
    try:
        expected = _build(fresh, intent.proposed_action, intent.authorized_scopes)
    except PromotionIntentRefused as exc:
        return _validation(False, scope_drift + [INTENT_FRESH_READINESS_INELIGIBLE, *exc.reason_codes],
                           mode, intent, fresh)
    mismatched = tuple(f.name for f in dataclasses.fields(PromotionIntent)
                       if f.name != "fingerprint" and getattr(expected, f.name) != getattr(intent, f.name))
    stale = [_STALE_BY_FIELD.get(name, INTENT_STALE_BINDING) for name in mismatched]
    if expected.fingerprint != intent.fingerprint and not mismatched:
        stale.append(INTENT_STALE_BINDING)  # unreachable for plain fields; fail closed regardless
    if stale or scope_drift:
        return _validation(False, scope_drift + stale, mode, intent, fresh, mismatched)
    return _validation(True, [INTENT_MATCHES_FRESH_READINESS], mode, intent, fresh)


def validate_promotion_intent(intent, fresh_readiness) -> PromotionIntentValidation:
    """Pure, fail-closed comparison of `intent` with a caller-supplied
    FCP-3A readiness. Never raises. It cannot prove the readiness is fresh
    (INTENT_FRESHNESS_NOT_PROVEN); `valid=True` authorizes nothing."""
    try:
        return _validate(intent, fresh_readiness, MODE_SUPPLIED_READINESS)
    except Exception:  # noqa: BLE001 - malformed input must never escape as success
        return _validation(False, [INTENT_MALFORMED], MODE_SUPPLIED_READINESS)


# ---------------------------------------------------------------------------
# Read-only revalidation
# ---------------------------------------------------------------------------

def revalidate_promotion_intent(
    intent, worktree, *, attested_sha: Optional[str], authorized_scopes, expected_remote_url: Optional[str] = None,
    evidence=None, ledger_root=None, lease_root=None, max_paths: int = rr.MAX_PATHS,
) -> PromotionIntentValidation:
    """Read-only revalidation: exactly one FCP-3A `assess_promotion_readiness`
    call with the inputs forwarded unchanged, then the pure comparison. The
    forwarded scopes must equal the intent's (INTENT_SCOPE_DRIFT otherwise).
    FCP-3A's input refusals propagate unchanged; any other failure is a
    non-valid result. The host must pass its real governed ledger and lease
    roots: without `ledger_root` FCP-3A is BLOCKED, so this is never valid."""
    try:
        fresh = rp.assess_promotion_readiness(
            worktree, attested_sha=attested_sha, authorized_scopes=authorized_scopes,
            expected_remote_url=expected_remote_url, evidence=evidence, ledger_root=ledger_root,
            lease_root=lease_root, max_paths=max_paths,
        )
    except rr.ReconciliationInputError:
        raise
    except Exception:  # noqa: BLE001 - no detail is exposed; the result is not valid
        return _validation(False, [INTENT_FRESH_READ_FAILED], MODE_FRESH_FCP3A_READ, intent)
    try:
        return _validate(intent, fresh, MODE_FRESH_FCP3A_READ, forwarded_scopes=authorized_scopes)
    except Exception:  # noqa: BLE001
        return _validation(False, [INTENT_MALFORMED], MODE_FRESH_FCP3A_READ, fresh=fresh)
