"""FCP-10B-02: Budgets and estimated accounting with evidence - pure,
deterministic, fail-closed, provider-neutral, NON-AUTHORITATIVE.

Answers ONE question: given authorized budget maxima the caller DECLARES, the
executions and structured usage receipts the Host ALREADY holds and the
tariffs the Host SUPPLIES, how much of each budget is accounted (observed and
estimated, tokens / units / seconds / money) inside its window, how uncertain
is that, and would an optional prospective execution (an FCP-10A-01
`AdvisoryReservation`) still fit? It never answers "may I dispatch now?".

Why this is a read-only projection, not a ledger or a billing system
--------------------------------------------------------------------
* Director and Runner stay the ONLY execution and Git authorities. Nothing
  here starts, queues, leases, reserves, retries, switches a provider, buys,
  subscribes, charges, calls a provider or remote API, runs a process or
  touches Git, the filesystem, the clock, the environment or the network. No
  ledger, store or price table of its own exists: the Runner's
  `runner_factory_ledger` stays the only persistent history, and every
  result is an immutable projection of the explicit request. The instant is
  the explicit `as_of_utc`.
* No price is ever invented. Money exists only as `decimal.Decimal` (never
  float, never int, never a Decimal subclass) in the policy's single
  ISO-4217-shaped currency; a tariff in another currency is refused (no
  conversion). A unit carried by a receipt without a Host tariff in force at
  the execution's instant is TARIFF_MISSING (a free unit needs an explicit
  zero tariff; TOTAL_TOKENS is covered by tariffed INPUT / OUTPUT tokens);
  a tariffed unit a receipt does not report is USAGE_UNKNOWN.
* Rounding is conservative and directed: every upper bound (observed and
  estimated-high cost, reserved cost) is computed with ROUND_CEILING and
  every lower bound (estimated-low cost) with ROUND_FLOOR, then quantized to
  the policy `granularity` in the same direction. Usage units are exact ints.
* Executions are declared by the Host (e.g. from the Runner's own attempt
  records): the declared set is the claimed complete population. A receipt
  is an execution's cumulative usage for each unit it lists, so receipts of
  one execution are never summed: equal OBSERVED quantities are one value
  (counted once), different ones are EVIDENCE_CONTRADICTORY; OBSERVED
  supersedes ESTIMATED per unit; several ESTIMATED ranges widen to their
  envelope. A declared execution without any receipt is USAGE_UNKNOWN. A
  receipt naming an undeclared execution, an execution declared twice, or
  overlapping / double-counting tariffs (TOTAL_TOKENS with INPUT or OUTPUT
  of the same provider) are refused.
* Fail closed: future-dated executions or receipts, UNVERIFIED receipts,
  contradictory evidence, missing usage or tariffs make the affected budget
  UNKNOWN and report no amount. Over budget (accounted above the maximum) is
  BUDGET_OVERRUN and LIMIT_SATURATED; a budget whose remaining amount cannot
  absorb the reservation (or, without one, is exhausted) is LIMIT_SATURATED;
  a reservation that alone exceeds the maximum is RESERVATION_EXCEEDS_LIMIT.

Verdicts (contract `VERDICTS`, none is a permit): REFUSE > UNKNOWN > WAIT >
READY, per budget and global. READY globally needs at least one cited
receipt, so success is never inferred from missing evidence. Output
(`BudgetEvaluation`, schema `fcp10b02-resource-quota-budget-evaluation-v1`)
holds only validated ids, enumerated codes, normalized UTC instants, ints,
Decimal amounts quantized to the granularity and a fingerprint, and fixes
every FCP-10A-01 zero-authority flag plus `charge_made`,
`provider_api_called` and `ledger_written` to False as read-only properties.
"""

from __future__ import annotations

import decimal
import hashlib
import re
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Optional

try:
    from scripts.ai import fabric_resource_quota_contract as qc
    from scripts.ai import fabric_scheduler_contract as sc
except ImportError:  # pragma: no cover - direct script execution
    import fabric_resource_quota_contract as qc  # type: ignore[no-redef]
    import fabric_scheduler_contract as sc  # type: ignore[no-redef]

REQUEST_SCHEMA = "fcp10b02-resource-quota-budget-request-v1"
REQUEST_SCHEMA_VERSION = 1
SCHEMA = "fcp10b02-resource-quota-budget-evaluation-v1"
SCHEMA_VERSION = 1
BUDGET_MARKER = "FCP10B02_BUDGET_ESTIMATE_ONLY_NOT_CERTIFIED_NOT_AUTHORIZED"

MAX_LIMITS = qc.MAX_LIMITS
MAX_EXECUTIONS = 128
MAX_RECEIPTS = 256
MAX_TARIFFS = 64
MAX_PER_QUANTITY = 1_000_000_000
MAX_CANONICAL_JSON_BYTES = 4 * qc.MAX_CANONICAL_JSON_BYTES
# Money bounds: amounts up to 10**12, rates down to 10**-18 per unit, and a
# granularity (rounding quantum) that is a power of ten from 10**-8 to 1.
MAX_MONEY = Decimal(10) ** 12
MIN_RATE_EXPONENT = -18
MIN_GRANULARITY_EXPONENT = -8

_CURRENCY_RE = re.compile(r"[A-Z]{3}")
_TRAPS = [decimal.InvalidOperation, decimal.Overflow, decimal.DivisionByZero]
# Private contexts (the thread's own context is never read nor changed).
_EXACT = decimal.Context(prec=60, rounding=decimal.ROUND_HALF_EVEN, traps=_TRAPS + [decimal.Inexact])
_UP = decimal.Context(prec=60, rounding=decimal.ROUND_CEILING, traps=_TRAPS)
_DOWN = decimal.Context(prec=60, rounding=decimal.ROUND_FLOOR, traps=_TRAPS)

UNIT_COST = "COST"
# Accountable usage units: the contract's cumulative ones (an instantaneous
# unit has no budget).
USAGE_UNITS = tuple(u for u in qc.UNITS if u not in qc.INSTANT_UNITS)
BUDGET_UNITS = USAGE_UNITS + (UNIT_COST,)
_TOKEN_PARTS = (qc.UNIT_INPUT_TOKENS, qc.UNIT_OUTPUT_TOKENS)

BASIS_OBSERVED = "OBSERVED"
BASIS_ESTIMATED = "ESTIMATED"
BASES = (BASIS_OBSERVED, BASIS_ESTIMATED)
RELIABILITIES = qc.RELIABILITIES
# The Runner classifies no usage: a Host receipt claims at most CALLER_OBSERVED.
RECEIPT_MAX_RELIABILITY = qc.RELIABILITY_CALLER_OBSERVED

READY = qc.READY
WAIT = qc.WAIT
REFUSE = qc.REFUSE
UNKNOWN = qc.UNKNOWN
VERDICTS = qc.VERDICTS

# Request-level refusal codes (the contract's where they exist), in their
# fixed canonical order.
REQUEST_NOT_TYPED = qc.REQUEST_NOT_TYPED
SCHEMA_VERSION_UNSUPPORTED = qc.SCHEMA_VERSION_UNSUPPORTED
REQUEST_ID_INVALID = qc.REQUEST_ID_INVALID
ID_SECRET_SHAPED = qc.ID_SECRET_SHAPED
ID_DUPLICATE = qc.ID_DUPLICATE
AS_OF_INVALID = qc.AS_OF_INVALID
POLICY_NOT_TYPED = qc.POLICY_NOT_TYPED
POLICY_SCHEMA_VERSION_UNSUPPORTED = qc.POLICY_SCHEMA_VERSION_UNSUPPORTED
POLICY_ID_INVALID = qc.POLICY_ID_INVALID
CURRENCY_INVALID = "CURRENCY_INVALID"
GRANULARITY_INVALID = "GRANULARITY_INVALID"
LIMITS_MALFORMED = qc.LIMITS_MALFORMED
LIMITS_EMPTY = qc.LIMITS_EMPTY
LIMIT_ID_INVALID = qc.LIMIT_ID_INVALID
LIMIT_SCOPE_UNKNOWN = qc.LIMIT_SCOPE_UNKNOWN
LIMIT_SCOPE_TARGET_INVALID = qc.LIMIT_SCOPE_TARGET_INVALID
LIMIT_UNIT_UNKNOWN = qc.LIMIT_UNIT_UNKNOWN
LIMIT_UNIT_NOT_CUMULATIVE = "LIMIT_UNIT_NOT_CUMULATIVE"
LIMIT_MAXIMUM_INVALID = qc.LIMIT_MAXIMUM_INVALID
LIMIT_WINDOW_REQUIRED = qc.LIMIT_WINDOW_REQUIRED
LIMIT_WINDOW_FORBIDDEN = qc.LIMIT_WINDOW_FORBIDDEN
WINDOW_NOT_TYPED = qc.WINDOW_NOT_TYPED
WINDOW_KIND_UNKNOWN = qc.WINDOW_KIND_UNKNOWN
WINDOW_DURATION_INVALID = qc.WINDOW_DURATION_INVALID
WINDOW_ANCHOR_INVALID = qc.WINDOW_ANCHOR_INVALID
COST_MAXIMUM_INVALID = "COST_MAXIMUM_INVALID"
LIMIT_AMBIGUOUS = qc.LIMIT_AMBIGUOUS
EXECUTIONS_MALFORMED = "EXECUTIONS_MALFORMED"
EXECUTION_ID_INVALID = "EXECUTION_ID_INVALID"
EXECUTION_DUPLICATE = "EXECUTION_DUPLICATE"
EXECUTION_PROVIDER_INVALID = "EXECUTION_PROVIDER_INVALID"
EXECUTION_RESOURCE_INVALID = "EXECUTION_RESOURCE_INVALID"
EXECUTION_TIME_INVALID = "EXECUTION_TIME_INVALID"
RECEIPTS_MALFORMED = "RECEIPTS_MALFORMED"
RECEIPT_ID_INVALID = "RECEIPT_ID_INVALID"
RECEIPT_EXECUTION_UNDECLARED = "RECEIPT_EXECUTION_UNDECLARED"
RECEIPT_BASIS_UNKNOWN = "RECEIPT_BASIS_UNKNOWN"
RECEIPT_RELIABILITY_UNKNOWN = "RECEIPT_RELIABILITY_UNKNOWN"
RECEIPT_RELIABILITY_OVERCLAIMED = "RECEIPT_RELIABILITY_OVERCLAIMED"
RECEIPT_TIME_INVALID = "RECEIPT_TIME_INVALID"
RECEIPT_QUANTITIES_MALFORMED = "RECEIPT_QUANTITIES_MALFORMED"
RECEIPT_UNIT_INVALID = "RECEIPT_UNIT_INVALID"
RECEIPT_UNIT_DUPLICATE = "RECEIPT_UNIT_DUPLICATE"
RECEIPT_RANGE_INVALID = "RECEIPT_RANGE_INVALID"
TARIFFS_MALFORMED = "TARIFFS_MALFORMED"
TARIFF_ID_INVALID = "TARIFF_ID_INVALID"
TARIFF_PROVIDER_INVALID = "TARIFF_PROVIDER_INVALID"
TARIFF_UNIT_INVALID = "TARIFF_UNIT_INVALID"
TARIFF_RATE_INVALID = "TARIFF_RATE_INVALID"
TARIFF_PER_QUANTITY_INVALID = "TARIFF_PER_QUANTITY_INVALID"
TARIFF_CURRENCY_MISMATCH = "TARIFF_CURRENCY_MISMATCH"
TARIFF_PERIOD_INVALID = "TARIFF_PERIOD_INVALID"
TARIFF_AMBIGUOUS = "TARIFF_AMBIGUOUS"
TARIFF_DOUBLE_COUNTING = "TARIFF_DOUBLE_COUNTING"
RESERVATION_NOT_TYPED = qc.RESERVATION_NOT_TYPED
RESERVATION_ID_INVALID = qc.RESERVATION_ID_INVALID
RESERVATION_TARGET_INVALID = qc.RESERVATION_TARGET_INVALID
RESERVATION_AMOUNTS_MALFORMED = qc.RESERVATION_AMOUNTS_MALFORMED
RESERVATION_UNIT_DUPLICATE = qc.RESERVATION_UNIT_DUPLICATE
RESERVATION_UNIT_NOT_CUMULATIVE = "RESERVATION_UNIT_NOT_CUMULATIVE"
REQUEST_TOO_LARGE = qc.REQUEST_TOO_LARGE
REQUEST_REASONS = (
    REQUEST_NOT_TYPED, SCHEMA_VERSION_UNSUPPORTED, REQUEST_ID_INVALID, ID_SECRET_SHAPED, ID_DUPLICATE, AS_OF_INVALID,
    POLICY_NOT_TYPED, POLICY_SCHEMA_VERSION_UNSUPPORTED, POLICY_ID_INVALID, CURRENCY_INVALID, GRANULARITY_INVALID,
    LIMITS_MALFORMED, LIMITS_EMPTY, LIMIT_ID_INVALID, LIMIT_SCOPE_UNKNOWN, LIMIT_SCOPE_TARGET_INVALID,
    LIMIT_UNIT_UNKNOWN, LIMIT_UNIT_NOT_CUMULATIVE, LIMIT_MAXIMUM_INVALID, LIMIT_WINDOW_REQUIRED,
    LIMIT_WINDOW_FORBIDDEN, WINDOW_NOT_TYPED, WINDOW_KIND_UNKNOWN, WINDOW_DURATION_INVALID, WINDOW_ANCHOR_INVALID,
    COST_MAXIMUM_INVALID, LIMIT_AMBIGUOUS, EXECUTIONS_MALFORMED, EXECUTION_ID_INVALID, EXECUTION_DUPLICATE,
    EXECUTION_PROVIDER_INVALID, EXECUTION_RESOURCE_INVALID, EXECUTION_TIME_INVALID, RECEIPTS_MALFORMED,
    RECEIPT_ID_INVALID, RECEIPT_EXECUTION_UNDECLARED, RECEIPT_BASIS_UNKNOWN, RECEIPT_RELIABILITY_UNKNOWN,
    RECEIPT_RELIABILITY_OVERCLAIMED, RECEIPT_TIME_INVALID, RECEIPT_QUANTITIES_MALFORMED, RECEIPT_UNIT_INVALID,
    RECEIPT_UNIT_DUPLICATE, RECEIPT_RANGE_INVALID, TARIFFS_MALFORMED, TARIFF_ID_INVALID, TARIFF_PROVIDER_INVALID,
    TARIFF_UNIT_INVALID, TARIFF_RATE_INVALID, TARIFF_PER_QUANTITY_INVALID, TARIFF_CURRENCY_MISMATCH,
    TARIFF_PERIOD_INVALID, TARIFF_AMBIGUOUS, TARIFF_DOUBLE_COUNTING, RESERVATION_NOT_TYPED, RESERVATION_ID_INVALID,
    RESERVATION_TARGET_INVALID, RESERVATION_AMOUNTS_MALFORMED, RESERVATION_UNIT_DUPLICATE,
    RESERVATION_UNIT_NOT_CUMULATIVE, REQUEST_TOO_LARGE,
)

# Evaluation reason codes (the contract's where they exist), grouped by the
# verdict they force, in their fixed canonical order.
RESERVATION_EXCEEDS_LIMIT = qc.RESERVATION_EXCEEDS_LIMIT
NO_EVIDENCE = qc.NO_EVIDENCE
EVIDENCE_FROM_FUTURE = qc.EVIDENCE_FROM_FUTURE
EVIDENCE_UNVERIFIED = qc.EVIDENCE_UNVERIFIED
EVIDENCE_CONTRADICTORY = qc.EVIDENCE_CONTRADICTORY
USAGE_UNKNOWN = qc.USAGE_UNKNOWN
TARIFF_MISSING = "TARIFF_MISSING"
BUDGET_OVERRUN = "BUDGET_OVERRUN"
LIMIT_SATURATED = qc.LIMIT_SATURATED
REFUSING_REASONS = (RESERVATION_EXCEEDS_LIMIT,)
# Doubts of one budget (NO_EVIDENCE is global only).
LIMIT_UNKNOWN_REASONS = (EVIDENCE_FROM_FUTURE, EVIDENCE_UNVERIFIED, EVIDENCE_CONTRADICTORY, USAGE_UNKNOWN,
                         TARIFF_MISSING)
UNKNOWN_REASONS = (NO_EVIDENCE,) + LIMIT_UNKNOWN_REASONS
WAITING_REASONS = (BUDGET_OVERRUN, LIMIT_SATURATED)
RESULT_REASONS = REFUSING_REASONS + UNKNOWN_REASONS + WAITING_REASONS
LIMIT_REASONS = tuple(r for r in RESULT_REASONS if r != NO_EVIDENCE)


def _ordered(codes, vocabulary) -> tuple:
    return sc._ordered(codes, vocabulary)


def _codes_ok(codes, vocabulary) -> bool:
    return (type(codes) is tuple and all(qc._in(c, vocabulary) for c in codes)
            and codes == _ordered(codes, vocabulary))


def _sorted_ids(values, limit: int) -> bool:
    return (type(values) is tuple and len(values) <= limit and all(qc._valid_id(v) for v in values)
            and list(values) == sorted(set(values)))


def _normalized_utc(value) -> bool:
    return type(value) is str and qc.parse_utc(value) is not None and sc._utc_text(qc.parse_utc(value)) == value


def verdict_for(reasons: tuple) -> str:
    """REFUSE > UNKNOWN > WAIT > READY."""
    if any(r in REFUSING_REASONS for r in reasons):
        return REFUSE
    if any(r in UNKNOWN_REASONS for r in reasons):
        return UNKNOWN
    return WAIT if reasons else READY


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------

def _decimal_ok(value, min_exponent: int = MIN_RATE_EXPONENT) -> bool:
    """An exact, finite, non-negative, bounded Decimal (never a float, an int,
    a subclass, NaN, an infinity or a signed zero)."""
    return (type(value) is Decimal and value.is_finite() and not value.is_signed()
            and value.as_tuple().exponent >= min_exponent and value <= MAX_MONEY)


def granularity_ok(value) -> bool:
    """A canonical power of ten from 10**-8 to 1 (e.g. Decimal("0.01"))."""
    return (type(value) is Decimal and value.is_finite() and not value.is_signed()
            and value.as_tuple().digits == (1,)
            and MIN_GRANULARITY_EXPONENT <= value.as_tuple().exponent <= 0)


def _quantized(value: Decimal, granularity: Decimal) -> bool:
    return value == value.quantize(granularity, context=_DOWN)


def _on_grid(value: Decimal, granularity: Decimal) -> bool:
    """Reported money carries exactly the granularity's exponent."""
    return value.as_tuple().exponent == granularity.as_tuple().exponent


def _money_text(value: Decimal) -> str:
    return format(value, "f")


def _decimal_text(value: Decimal) -> str:
    """Value-canonical text (1.0 and 1.00 fingerprint alike)."""
    return format(value.normalize(_EXACT), "f")


def _plus(a, b):
    """Exact sum (money never goes through the thread's own context)."""
    return _EXACT.add(a, b) if type(a) is Decimal else a + b


def _minus(a, b):
    return _EXACT.subtract(a, b) if type(a) is Decimal else a - b


def _zero(unit: str):
    return Decimal(0) if unit == UNIT_COST else 0


def _cost(quantity: int, tariff, context) -> Decimal:
    """quantity * rate / per_quantity, every operation rounded in the
    context's direction (exact except for the division)."""
    return context.divide(context.multiply(Decimal(quantity), tariff.rate), Decimal(tariff.per_quantity))


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CostLimit:
    """An authorized monetary maximum (Decimal, in the policy currency and a
    multiple of its granularity) over `window` for one scope, with the same
    GLOBAL / PROVIDER / RESOURCE shape as a contract `QuotaLimit`."""
    limit_id: str
    scope: str
    maximum: Decimal
    window: object
    provider_id: Optional[str] = None
    resource_id: Optional[str] = None


@dataclass(frozen=True)
class BudgetPolicy:
    """Caller-declared budget maxima. `limits` holds contract `QuotaLimit`s of
    cumulative usage units and `CostLimit`s. It narrows; it never creates
    capacity or money."""
    policy_id: str
    currency: str
    granularity: Decimal
    limits: tuple
    schema_version: int = REQUEST_SCHEMA_VERSION


@dataclass(frozen=True)
class BudgetExecution:
    """One execution the Host declares (opaque `execution_id`, e.g. a Runner
    attempt identity) on one provider (and optionally one resource), with
    the UTC instant its usage was incurred."""
    execution_id: str
    provider_id: str
    incurred_at_utc: str
    resource_id: Optional[str] = None


@dataclass(frozen=True)
class UsageQuantity:
    """`minimum..maximum` of one cumulative unit; exact when equal."""
    unit: str
    minimum: int
    maximum: int


@dataclass(frozen=True)
class UsageReceipt:
    """An explicit structured receipt (never prose) of one execution's
    cumulative usage. OBSERVED quantities are exact; ESTIMATED may be a
    range. `recorded_at_utc` is when the Host recorded it."""
    receipt_id: str
    execution_id: str
    basis: str
    reliability: str
    recorded_at_utc: str
    quantities: tuple


@dataclass(frozen=True)
class Tariff:
    """A Host-supplied rate: `rate` (Decimal, `currency`) per `per_quantity`
    of `unit` on `provider_id`, in force from `effective_from_utc`
    (inclusive) until `effective_until_utc` (exclusive, None: open)."""
    tariff_id: str
    provider_id: str
    unit: str
    rate: Decimal
    per_quantity: int
    currency: str
    effective_from_utc: str
    effective_until_utc: Optional[str] = None


@dataclass(frozen=True)
class BudgetRequest:
    """Explicit, immutable budget question. `reservation` is an optional
    FCP-10A-01 `AdvisoryReservation` (priced at `as_of_utc`). Validated by
    `evaluate_budget` (fail closed), not here."""
    request_id: str
    as_of_utc: str
    policy: object
    executions: tuple = ()
    receipts: tuple = ()
    tariffs: tuple = ()
    reservation: Optional[object] = None
    schema_version: int = REQUEST_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

_AMOUNT_FIELDS = ("observed", "estimated_low", "estimated_high", "accounted", "uncertainty", "projected", "remaining")


def _amount_ok(unit: str, value) -> bool:
    if unit == UNIT_COST:
        return type(value) is Decimal and value.is_finite() and not value.is_signed()
    return sc._is_int(value) and value >= 0


@dataclass(frozen=True)
class BudgetAccount:
    """What one budget's evidence supports inside its current window.
    Amounts only when certain (`reserved` whenever it is known). Usage units
    are ints, COST is Decimal. Construction re-derives the verdict and every
    amount relation, so a hand-made account cannot claim more headroom."""
    limit_id: str
    scope: str
    unit: str
    provider_id: Optional[str]
    resource_id: Optional[str]
    window_kind: str
    window_start_utc: str
    window_end_utc: str
    verdict: str
    reasons: tuple
    evidence_ids: tuple
    execution_ids: tuple
    maximum: object
    reservation_in_scope: bool
    reserved: object = None
    observed: object = None
    estimated_low: object = None
    estimated_high: object = None
    accounted: object = None
    uncertainty: object = None
    projected: object = None
    remaining: object = None

    def __post_init__(self):
        if not (qc._valid_id(self.limit_id) and qc._in(self.scope, qc.LIMIT_SCOPES)
                and qc._in(self.unit, BUDGET_UNITS)):
            raise ValueError("limit_id / scope / unit must be valid")
        if not (qc._in(self.window_kind, qc.WINDOW_KINDS) and _normalized_utc(self.window_start_utc)
                and _normalized_utc(self.window_end_utc)
                and qc.parse_utc(self.window_start_utc) < qc.parse_utc(self.window_end_utc)):
            raise ValueError("window bounds must be ordered normalized UTC")
        if not _codes_ok(self.reasons, LIMIT_REASONS):
            raise ValueError("reasons must be ordered budget reason codes")
        if self.verdict != verdict_for(self.reasons):
            raise ValueError("verdict must be exactly the one derived from reasons")
        if not (_sorted_ids(self.evidence_ids, MAX_RECEIPTS) and _sorted_ids(self.execution_ids, MAX_EXECUTIONS)):
            raise ValueError("evidence_ids / execution_ids must be sorted unique ids")
        if not (_amount_ok(self.unit, self.maximum) and self.maximum > 0):
            raise ValueError("maximum must be a positive amount of the unit")
        if type(self.reservation_in_scope) is not bool:
            raise ValueError("reservation_in_scope must be a bool")
        if self.reserved is not None and not (self.reservation_in_scope and _amount_ok(self.unit, self.reserved)):
            raise ValueError("only an in-scope reservation has a reserved amount")
        if (RESERVATION_EXCEEDS_LIMIT in self.reasons) != (self.reserved is not None
                                                            and self.reserved > self.maximum):
            raise ValueError("RESERVATION_EXCEEDS_LIMIT exactly when the reservation alone exceeds the maximum")
        amounts = tuple(getattr(self, name) for name in _AMOUNT_FIELDS)
        if any(r in LIMIT_UNKNOWN_REASONS for r in self.reasons):
            if amounts != (None,) * len(amounts):
                raise ValueError("an uncertain budget reports no accounted amount")
            if BUDGET_OVERRUN in self.reasons or LIMIT_SATURATED in self.reasons:
                raise ValueError("saturation is only claimed from certain amounts")
            return
        if not all(_amount_ok(self.unit, a) for a in amounts):
            raise ValueError("amounts must be non-negative amounts of the unit")
        if self.reservation_in_scope and self.reserved is None:
            raise ValueError("a certain in-scope reservation has a reserved amount")
        zero = _zero(self.unit)
        reserved = self.reserved if self.reserved is not None else zero
        if (self.estimated_low > self.estimated_high
                or self.accounted != _plus(self.observed, self.estimated_high)
                or self.uncertainty != _minus(self.estimated_high, self.estimated_low)
                or self.projected != _plus(self.accounted, reserved)
                or self.remaining != max(_minus(self.maximum, self.accounted), zero)):
            raise ValueError("amounts must satisfy the accounting relations")
        if (BUDGET_OVERRUN in self.reasons) != (self.accounted > self.maximum):
            raise ValueError("BUDGET_OVERRUN exactly when accounted exceeds the maximum")
        saturated = self.projected > self.maximum if self.reservation_in_scope else self.accounted >= self.maximum
        if (LIMIT_SATURATED in self.reasons) != saturated:
            raise ValueError("LIMIT_SATURATED exactly when the budget cannot absorb the next execution")

    @property
    def over_budget(self) -> bool:
        return BUDGET_OVERRUN in self.reasons

    def to_dict(self) -> dict:
        def text(value):
            return _money_text(value) if self.unit == UNIT_COST and value is not None else value
        return {
            "limit_id": self.limit_id, "scope": self.scope, "unit": self.unit, "provider_id": self.provider_id,
            "resource_id": self.resource_id, "window_kind": self.window_kind,
            "window_start_utc": self.window_start_utc, "window_end_utc": self.window_end_utc,
            "verdict": self.verdict, "reasons": list(self.reasons), "evidence_ids": list(self.evidence_ids),
            "execution_ids": list(self.execution_ids), "maximum": text(self.maximum),
            "reservation_in_scope": self.reservation_in_scope, "reserved": text(self.reserved),
            **{name: text(getattr(self, name)) for name in _AMOUNT_FIELDS},
        }


class _BudgetGuarantees(qc._QuotaGuarantees):
    """FCP-10A-01 zero-authority flags plus: no charge, no provider API, no
    ledger write."""

    @property
    def charge_made(self) -> bool:
        return False

    @property
    def provider_api_called(self) -> bool:
        return False

    @property
    def ledger_written(self) -> bool:
        return False

    @staticmethod
    def _guarantees() -> dict:
        guarantees = qc._QuotaGuarantees._guarantees()
        guarantees.update(marker=BUDGET_MARKER, charge_made=False, provider_api_called=False, ledger_written=False)
        return guarantees


@dataclass(frozen=True)
class BudgetEvaluation(_BudgetGuarantees):
    """Advisory accounting. Echo fields hold only validated values (None and
    () when refused). Construction re-derives the global reasons and verdict
    from the budgets, so a hand-made evaluation cannot claim more."""
    verdict: str
    request_id: Optional[str]
    request_fingerprint: Optional[str]
    request_reasons: tuple
    reasons: tuple
    evidence_ids: tuple
    currency: Optional[str]
    granularity: Optional[Decimal]
    accounts: tuple

    def __post_init__(self):
        if not qc._in(self.verdict, VERDICTS):
            raise ValueError("unknown verdict")
        if not _codes_ok(self.request_reasons, REQUEST_REASONS):
            raise ValueError("request_reasons must be ordered request reason codes")
        if self.request_reasons:
            if (self.verdict != REFUSE or self.reasons or self.evidence_ids or self.accounts
                    or (self.request_id, self.request_fingerprint, self.currency, self.granularity) != (None,) * 4):
                raise ValueError("a refused request echoes nothing and decides nothing")
            return
        if not qc._valid_id(self.request_id):
            raise ValueError("request_id must be a valid id")
        if not (type(self.request_fingerprint) is str and sc._FINGERPRINT_RE.fullmatch(self.request_fingerprint)):
            raise ValueError("request_fingerprint must be a sha256 hex digest")
        if not (type(self.currency) is str and _CURRENCY_RE.fullmatch(self.currency)
                and granularity_ok(self.granularity)):
            raise ValueError("currency / granularity must be validated")
        if not (type(self.accounts) is tuple and 1 <= len(self.accounts) <= MAX_LIMITS
                and all(type(a) is BudgetAccount for a in self.accounts)):
            raise ValueError("accounts must be 1..MAX_LIMITS BudgetAccounts")
        ids = [a.limit_id for a in self.accounts]
        if ids != sorted(set(ids)):
            raise ValueError("accounts must be sorted and unique")
        for account in self.accounts:
            if account.unit == UNIT_COST and not all(
                    _on_grid(v, self.granularity) for v in [account.maximum, account.reserved]
                    + [getattr(account, n) for n in _AMOUNT_FIELDS] if v is not None):
                raise ValueError("money must be quantized to the granularity")
        cited = tuple(sorted({e for a in self.accounts for e in a.evidence_ids}))
        if self.evidence_ids != cited:
            raise ValueError("evidence_ids must be exactly the budgets' cited receipts")
        expected = {r for a in self.accounts for r in a.reasons}
        if not cited:
            expected.add(NO_EVIDENCE)
        if self.reasons != _ordered(expected, RESULT_REASONS):
            raise ValueError("reasons must be exactly the ones derived from the budgets")
        if self.verdict != verdict_for(self.reasons):
            raise ValueError("verdict must be exactly the one derived from reasons")

    @property
    def over_budget(self) -> bool:
        return any(a.over_budget for a in self.accounts)

    def account(self, limit_id: str) -> Optional[BudgetAccount]:
        for account in self.accounts:
            if account.limit_id == limit_id:
                return account
        return None

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA, "schema_version": SCHEMA_VERSION, "verdict": self.verdict,
            "request_id": self.request_id, "request_fingerprint": self.request_fingerprint,
            "request_reasons": list(self.request_reasons), "reasons": list(self.reasons),
            "evidence_ids": list(self.evidence_ids), "currency": self.currency,
            "granularity": None if self.granularity is None else _money_text(self.granularity),
            "accounts": [a.to_dict() for a in self.accounts], **_BudgetGuarantees._guarantees(),
        }


def canonical_json(evaluation: BudgetEvaluation) -> str:
    """Stable, sorted, compact, size-bounded serialization of the exact
    evaluation type (a subclass cannot substitute `to_dict`)."""
    if type(evaluation) is not BudgetEvaluation:
        raise TypeError("canonical_json accepts only a BudgetEvaluation")
    text = sc._canonical(BudgetEvaluation.to_dict(evaluation))
    if len(text) > MAX_CANONICAL_JSON_BYTES:
        raise ValueError("canonical evaluation exceeds MAX_CANONICAL_JSON_BYTES")
    return text


def _refused(reasons) -> BudgetEvaluation:
    return BudgetEvaluation(
        verdict=REFUSE, request_id=None, request_fingerprint=None, request_reasons=_ordered(reasons, REQUEST_REASONS),
        reasons=(), evidence_ids=(), currency=None, granularity=None, accounts=(),
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _scope_reasons(scope, provider_id, resource_id) -> set:
    """The contract's `QuotaLimit` scope shape, for a `CostLimit`."""
    if not qc._in(scope, qc.LIMIT_SCOPES):
        return {LIMIT_SCOPE_UNKNOWN}
    provider_ok = provider_id is None or sc._valid_provider_id(provider_id)
    resource_ok = resource_id is None or qc._valid_id(resource_id)
    shape = {
        qc.SCOPE_GLOBAL: provider_id is None and resource_id is None,
        qc.SCOPE_PROVIDER: provider_id is not None and resource_id is None,
        qc.SCOPE_RESOURCE: resource_id is not None,
    }[scope]
    return set() if provider_ok and resource_ok and shape else {LIMIT_SCOPE_TARGET_INVALID}


def _cost_limit_reasons(limit: CostLimit, granularity) -> set:
    reasons = set()
    if not qc._valid_id(limit.limit_id):
        reasons.add(LIMIT_ID_INVALID)
    reasons |= _scope_reasons(limit.scope, limit.provider_id, limit.resource_id)
    if limit.window is None:
        reasons.add(LIMIT_WINDOW_REQUIRED)
    else:
        reasons |= qc._window_reasons(limit.window)
    if not (_decimal_ok(limit.maximum) and limit.maximum > 0
            and (not granularity_ok(granularity) or _quantized(limit.maximum, granularity))):
        reasons.add(COST_MAXIMUM_INVALID)
    return reasons


def _limit_unit(limit) -> str:
    return UNIT_COST if type(limit) is CostLimit else limit.unit


def _limit_key(limit) -> tuple:
    window = limit.window
    return (limit.scope, limit.provider_id, limit.resource_id, _limit_unit(limit),
            (window.kind, window.duration_seconds, sc._utc_text(qc.parse_utc(window.anchor_utc))))


def _policy_reasons(policy) -> set:
    if type(policy) is not BudgetPolicy:
        return {POLICY_NOT_TYPED}
    reasons = set()
    if not (sc._is_int(policy.schema_version) and policy.schema_version == REQUEST_SCHEMA_VERSION):
        reasons.add(POLICY_SCHEMA_VERSION_UNSUPPORTED)
    if not qc._valid_id(policy.policy_id):
        reasons.add(POLICY_ID_INVALID)
    if not (type(policy.currency) is str and _CURRENCY_RE.fullmatch(policy.currency)):
        reasons.add(CURRENCY_INVALID)
    if not granularity_ok(policy.granularity):
        reasons.add(GRANULARITY_INVALID)
    limits = policy.limits
    if not (type(limits) is tuple and len(limits) <= MAX_LIMITS
            and all(type(lim) in (qc.QuotaLimit, CostLimit) for lim in limits)):
        reasons.add(LIMITS_MALFORMED)
        return reasons
    if not limits:
        reasons.add(LIMITS_EMPTY)
    clean = []
    for limit in limits:
        if type(limit) is CostLimit:
            limit_reasons = _cost_limit_reasons(limit, policy.granularity)
        else:
            limit_reasons = qc._limit_reasons(limit)
            if qc._in(limit.unit, qc.INSTANT_UNITS):
                limit_reasons.add(LIMIT_UNIT_NOT_CUMULATIVE)
        reasons |= limit_reasons
        if not limit_reasons:
            clean.append(limit)
    if len({_limit_key(lim) for lim in clean}) != len(clean):
        reasons.add(LIMIT_AMBIGUOUS)
    return reasons


def _execution_reasons(execution: BudgetExecution) -> set:
    reasons = set()
    if not qc._valid_id(execution.execution_id):
        reasons.add(EXECUTION_ID_INVALID)
    if not sc._valid_provider_id(execution.provider_id):
        reasons.add(EXECUTION_PROVIDER_INVALID)
    if execution.resource_id is not None and not qc._valid_id(execution.resource_id):
        reasons.add(EXECUTION_RESOURCE_INVALID)
    if qc.parse_utc(execution.incurred_at_utc) is None:
        reasons.add(EXECUTION_TIME_INVALID)
    return reasons


def _quantity_ok(quantity) -> bool:
    return (type(quantity) is UsageQuantity and qc._in(quantity.unit, USAGE_UNITS)
            and qc._bounded_int(quantity.minimum, 0, qc.UNIT_MAXIMUM[quantity.unit])
            and qc._bounded_int(quantity.maximum, 0, qc.UNIT_MAXIMUM[quantity.unit]))


def _receipt_reasons(receipt: UsageReceipt, declared: Optional[set]) -> set:
    reasons = set()
    if not qc._valid_id(receipt.receipt_id):
        reasons.add(RECEIPT_ID_INVALID)
    if declared is not None and receipt.execution_id not in declared:
        reasons.add(RECEIPT_EXECUTION_UNDECLARED)
    if not qc._in(receipt.basis, BASES):
        reasons.add(RECEIPT_BASIS_UNKNOWN)
    if not qc._in(receipt.reliability, RELIABILITIES):
        reasons.add(RECEIPT_RELIABILITY_UNKNOWN)
    elif RELIABILITIES.index(receipt.reliability) > RELIABILITIES.index(RECEIPT_MAX_RELIABILITY):
        reasons.add(RECEIPT_RELIABILITY_OVERCLAIMED)
    if qc.parse_utc(receipt.recorded_at_utc) is None:
        reasons.add(RECEIPT_TIME_INVALID)
    quantities = receipt.quantities
    if not (type(quantities) is tuple and 1 <= len(quantities) <= len(USAGE_UNITS)
            and all(type(q) is UsageQuantity for q in quantities)):
        reasons.add(RECEIPT_QUANTITIES_MALFORMED)
        return reasons
    if not all(_quantity_ok(q) for q in quantities):
        reasons.add(RECEIPT_UNIT_INVALID)
        return reasons
    if len({q.unit for q in quantities}) != len(quantities):
        reasons.add(RECEIPT_UNIT_DUPLICATE)
    if any(q.minimum > q.maximum or (receipt.basis == BASIS_OBSERVED and q.minimum != q.maximum)
           for q in quantities):
        reasons.add(RECEIPT_RANGE_INVALID)
    return reasons


def _tariff_period(tariff: Tariff) -> tuple:
    return qc.parse_utc(tariff.effective_from_utc), qc.parse_utc(tariff.effective_until_utc)


def _tariff_reasons(tariff: Tariff, currency) -> set:
    reasons = set()
    if not qc._valid_id(tariff.tariff_id):
        reasons.add(TARIFF_ID_INVALID)
    if not sc._valid_provider_id(tariff.provider_id):
        reasons.add(TARIFF_PROVIDER_INVALID)
    if not qc._in(tariff.unit, USAGE_UNITS):
        reasons.add(TARIFF_UNIT_INVALID)
    if not _decimal_ok(tariff.rate):
        reasons.add(TARIFF_RATE_INVALID)
    if not qc._bounded_int(tariff.per_quantity, 1, MAX_PER_QUANTITY):
        reasons.add(TARIFF_PER_QUANTITY_INVALID)
    if type(tariff.currency) is not str or tariff.currency != currency:
        reasons.add(TARIFF_CURRENCY_MISMATCH)
    start, end = _tariff_period(tariff)
    if start is None or (tariff.effective_until_utc is not None and (end is None or end <= start)):
        reasons.add(TARIFF_PERIOD_INVALID)
    return reasons


def _overlap(a: Tariff, b: Tariff) -> bool:
    (a_from, a_until), (b_from, b_until) = _tariff_period(a), _tariff_period(b)
    return (b_until is None or a_from < b_until) and (a_until is None or b_from < a_until)


def _tariff_set_reasons(tariffs: list) -> set:
    reasons = set()
    for i, a in enumerate(tariffs):
        for b in tariffs[i + 1:]:
            if a.provider_id != b.provider_id or not _overlap(a, b):
                continue
            if a.unit == b.unit:
                reasons.add(TARIFF_AMBIGUOUS)
            elif {a.unit, b.unit} & {qc.UNIT_TOTAL_TOKENS} and {a.unit, b.unit} & set(_TOKEN_PARTS):
                reasons.add(TARIFF_DOUBLE_COUNTING)
    return reasons


def _reservation_reasons(reservation) -> set:
    if reservation is None:
        return set()
    reasons = qc._reservation_reasons(reservation)
    if RESERVATION_AMOUNTS_MALFORMED not in reasons and type(reservation) is qc.AdvisoryReservation and any(
            unit in qc.INSTANT_UNITS for unit, _ in reservation.amounts):
        reasons.add(RESERVATION_UNIT_NOT_CUMULATIVE)
    return reasons


def _typed(values, kind, limit: int) -> bool:
    return type(values) is tuple and len(values) <= limit and all(type(v) is kind for v in values)


def _structural_reasons(request) -> tuple:
    if type(request) is not BudgetRequest:
        return (REQUEST_NOT_TYPED,)
    reasons = set()
    if not (sc._is_int(request.schema_version) and request.schema_version == REQUEST_SCHEMA_VERSION):
        reasons.add(SCHEMA_VERSION_UNSUPPORTED)
    if not qc._valid_id(request.request_id):
        reasons.add(REQUEST_ID_INVALID)
    if qc.parse_utc(request.as_of_utc) is None:
        reasons.add(AS_OF_INVALID)
    policy = request.policy
    reasons |= _policy_reasons(policy)
    executions, receipts, tariffs = request.executions, request.receipts, request.tariffs
    declared = None
    if not _typed(executions, BudgetExecution, MAX_EXECUTIONS):
        reasons.add(EXECUTIONS_MALFORMED)
        executions = ()
    else:
        for execution in executions:
            reasons |= _execution_reasons(execution)
        ids = [e.execution_id for e in executions]
        if len(set(ids)) != len(ids):
            reasons.add(EXECUTION_DUPLICATE)
        declared = set(ids)
    if not _typed(receipts, UsageReceipt, MAX_RECEIPTS):
        reasons.add(RECEIPTS_MALFORMED)
        receipts = ()
    for receipt in receipts:
        reasons |= _receipt_reasons(receipt, declared)
    if not _typed(tariffs, Tariff, MAX_TARIFFS):
        reasons.add(TARIFFS_MALFORMED)
        tariffs = ()
    currency = policy.currency if type(policy) is BudgetPolicy else None
    clean = []
    for tariff in tariffs:
        tariff_reasons = _tariff_reasons(tariff, currency)
        reasons |= tariff_reasons
        if not tariff_reasons:
            clean.append(tariff)
    reasons |= _tariff_set_reasons(clean)
    reasons |= _reservation_reasons(request.reservation)
    ids = [request.request_id] + [r.receipt_id for r in receipts] + [t.tariff_id for t in tariffs]
    if type(policy) is BudgetPolicy:
        ids.append(policy.policy_id)
        if type(policy.limits) is tuple:
            ids += [lim.limit_id for lim in policy.limits if type(lim) in (qc.QuotaLimit, CostLimit)]
    if type(request.reservation) is qc.AdvisoryReservation:
        ids.append(request.reservation.reservation_id)
    named = ids + [e.execution_id for e in executions] + [e.resource_id for e in executions] + [
        r.execution_id for r in receipts]
    if any(qc._secret_shaped(i) for i in named):
        reasons.add(ID_SECRET_SHAPED)
    strings = [i for i in ids if type(i) is str]
    if len(strings) != len(set(strings)):
        reasons.add(ID_DUPLICATE)
    return _ordered(reasons, REQUEST_REASONS)


def _utc(value) -> Optional[str]:
    return None if value is None else sc._utc_text(qc.parse_utc(value))


def _limit_dict(limit) -> dict:
    window = limit.window
    cost = type(limit) is CostLimit
    return {
        "limit_id": limit.limit_id, "scope": limit.scope, "unit": _limit_unit(limit),
        "maximum": _decimal_text(limit.maximum) if cost else limit.maximum, "provider_id": limit.provider_id,
        "resource_id": limit.resource_id,
        "window": {"kind": window.kind, "duration_seconds": window.duration_seconds,
                   "anchor_utc": _utc(window.anchor_utc)},
    }


def _request_dict(request: BudgetRequest) -> dict:
    policy, reservation = request.policy, request.reservation
    return {
        "schema": REQUEST_SCHEMA, "schema_version": REQUEST_SCHEMA_VERSION, "request_id": request.request_id,
        "as_of_utc": _utc(request.as_of_utc),
        "policy": {
            "policy_id": policy.policy_id, "currency": policy.currency,
            "granularity": _decimal_text(policy.granularity),
            "limits": sorted((_limit_dict(lim) for lim in policy.limits), key=lambda d: d["limit_id"]),
        },
        "executions": sorted(
            ({"execution_id": e.execution_id, "provider_id": e.provider_id, "resource_id": e.resource_id,
              "incurred_at_utc": _utc(e.incurred_at_utc)} for e in request.executions),
            key=lambda d: d["execution_id"]),
        "receipts": sorted(
            ({"receipt_id": r.receipt_id, "execution_id": r.execution_id, "basis": r.basis,
              "reliability": r.reliability, "recorded_at_utc": _utc(r.recorded_at_utc),
              "quantities": sorted([q.unit, q.minimum, q.maximum] for q in r.quantities)}
             for r in request.receipts), key=lambda d: d["receipt_id"]),
        "tariffs": sorted(
            ({"tariff_id": t.tariff_id, "provider_id": t.provider_id, "unit": t.unit, "rate": _decimal_text(t.rate),
              "per_quantity": t.per_quantity, "currency": t.currency,
              "effective_from_utc": _utc(t.effective_from_utc), "effective_until_utc": _utc(t.effective_until_utc)}
             for t in request.tariffs), key=lambda d: d["tariff_id"]),
        "reservation": None if reservation is None else {
            "reservation_id": reservation.reservation_id, "provider_id": reservation.provider_id,
            "resource_id": reservation.resource_id, "amounts": sorted([u, a] for u, a in reservation.amounts),
        },
    }


def validate_request(request) -> tuple:
    """Ordered request refusal codes; () for a valid request. Never raises
    and never echoes raw input."""
    reasons = _structural_reasons(request)
    if reasons:
        return reasons
    if len(sc._canonical(_request_dict(request))) > MAX_CANONICAL_JSON_BYTES:
        return (REQUEST_TOO_LARGE,)
    return ()


def request_fingerprint(request: BudgetRequest) -> str:
    """sha256 of the canonical request (raises ValueError if invalid)."""
    reasons = validate_request(request)
    if reasons:
        raise ValueError("request_fingerprint accepts only a valid BudgetRequest: " + ",".join(reasons))
    return hashlib.sha256(sc._canonical(_request_dict(request)).encode("ascii")).hexdigest()


# ---------------------------------------------------------------------------
# Accounting
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _Resolved:
    """One execution's usage: unit -> (low, high, basis), its doubts and its
    cited receipts."""
    units: dict
    doubts: frozenset
    receipt_ids: frozenset


def _resolve(execution: BudgetExecution, receipts: list, as_of) -> _Resolved:
    incurred = qc.parse_utc(execution.incurred_at_utc)
    doubts = set()
    if incurred > as_of:
        doubts.add(EVIDENCE_FROM_FUTURE)
    observed, estimated = {}, {}
    for receipt in receipts:
        recorded = qc.parse_utc(receipt.recorded_at_utc)
        if recorded > as_of:
            doubts.add(EVIDENCE_FROM_FUTURE)
        if receipt.reliability == qc.RELIABILITY_UNVERIFIED:
            doubts.add(EVIDENCE_UNVERIFIED)
        if receipt.basis == BASIS_OBSERVED and recorded < incurred:
            doubts.add(EVIDENCE_CONTRADICTORY)
        target = observed if receipt.basis == BASIS_OBSERVED else estimated
        for quantity in receipt.quantities:
            target.setdefault(quantity.unit, set()).add((quantity.minimum, quantity.maximum))
    units = {}
    for unit, values in observed.items():
        if len(values) > 1:
            doubts.add(EVIDENCE_CONTRADICTORY)
        units[unit] = (max(v[0] for v in values), max(v[1] for v in values), BASIS_OBSERVED)
    for unit, values in estimated.items():
        if unit not in units:
            units[unit] = (min(v[0] for v in values), max(v[1] for v in values), BASIS_ESTIMATED)
    total = units.get(qc.UNIT_TOTAL_TOKENS)
    if total is not None and total[1] < sum(units[u][0] for u in _TOKEN_PARTS if u in units):
        doubts.add(EVIDENCE_CONTRADICTORY)
    return _Resolved(units=units, doubts=frozenset(doubts), receipt_ids=frozenset(r.receipt_id for r in receipts))


def _in_scope(limit, provider_id: str, resource_id: Optional[str]) -> bool:
    if limit.scope == qc.SCOPE_GLOBAL:
        return True
    if limit.scope == qc.SCOPE_PROVIDER:
        return provider_id == limit.provider_id
    return resource_id == limit.resource_id and limit.provider_id in (None, provider_id)


def _window_bounds(window, as_of) -> tuple:
    """ROLLING: (as_of - duration, as_of], start exclusive. FIXED: the
    [start, end) period of the anchored grid that contains as_of."""
    span = timedelta(seconds=window.duration_seconds)
    if window.kind == qc.WINDOW_ROLLING:
        return as_of - span, as_of
    anchor = qc.parse_utc(window.anchor_utc)
    start = anchor + ((as_of - anchor) // span) * span
    return start, start + span


def _in_window(window, bounds: tuple, instant) -> bool:
    start, end = bounds
    if window.kind == qc.WINDOW_ROLLING:
        return start < instant <= end
    return start <= instant < end


def _tariffs_at(tariffs: tuple, provider_id: str, instant) -> dict:
    """unit -> the one Host tariff of `provider_id` in force at `instant`
    (validation already refused overlaps)."""
    found = {}
    for tariff in tariffs:
        start, end = _tariff_period(tariff)
        if tariff.provider_id == provider_id and start <= instant and (end is None or instant < end):
            found[tariff.unit] = tariff
    return found


def _priced(units: dict, tariffs: dict, reasons: set) -> bool:
    """Every reported unit needs a tariff and every tariffed unit a report.
    A TOTAL_TOKENS report is covered (never priced again) by tariffed
    INPUT / OUTPUT tokens."""
    reported = set(units)
    if set(tariffs) & set(_TOKEN_PARTS):
        reported.discard(qc.UNIT_TOTAL_TOKENS)
    ok = True
    if not tariffs or reported - set(tariffs):
        reasons.add(TARIFF_MISSING)
        ok = False
    if set(tariffs) - set(units):
        reasons.add(USAGE_UNKNOWN)
        ok = False
    return ok


def _account(limit, request: BudgetRequest, resolved: dict, as_of) -> BudgetAccount:
    unit = _limit_unit(limit)
    cost = unit == UNIT_COST
    granularity = request.policy.granularity
    bounds = _window_bounds(limit.window, as_of)
    reasons, evidence, executions = set(), set(), []
    zero = _zero(unit).quantize(granularity, context=_EXACT) if cost else _zero(unit)
    observed = estimated_low = estimated_high = zero
    for execution in request.executions:
        if not _in_scope(limit, execution.provider_id, execution.resource_id):
            continue
        incurred = qc.parse_utc(execution.incurred_at_utc)
        usage = resolved[execution.execution_id]
        if incurred <= as_of and not _in_window(limit.window, bounds, incurred):
            continue
        executions.append(execution.execution_id)
        evidence |= usage.receipt_ids
        reasons |= usage.doubts
        if not usage.units:
            reasons.add(USAGE_UNKNOWN)
            continue
        if not cost:
            if unit not in usage.units:
                reasons.add(USAGE_UNKNOWN)
                continue
            low, high, basis = usage.units[unit]
            if basis == BASIS_OBSERVED:
                observed += high
            else:
                estimated_low, estimated_high = estimated_low + low, estimated_high + high
            continue
        tariffs = _tariffs_at(request.tariffs, execution.provider_id, incurred)
        if not _priced(usage.units, tariffs, reasons):
            continue
        for part, tariff in tariffs.items():
            low, high, basis = usage.units[part]
            if basis == BASIS_OBSERVED:
                observed = _UP.add(observed, _cost(high, tariff, _UP))
            else:
                estimated_low = _DOWN.add(estimated_low, _cost(low, tariff, _DOWN))
                estimated_high = _UP.add(estimated_high, _cost(high, tariff, _UP))

    reservation, reserved, in_scope = request.reservation, None, False
    if reservation is not None and _in_scope(limit, reservation.provider_id, reservation.resource_id):
        in_scope = True
        amounts = dict(reservation.amounts)
        if not cost:
            if unit in amounts:
                reserved = amounts[unit]
            else:
                reasons.add(USAGE_UNKNOWN)
        else:
            tariffs = _tariffs_at(request.tariffs, reservation.provider_id, as_of)
            if _priced(amounts, tariffs, reasons):
                exact = Decimal(0)
                for part, tariff in tariffs.items():
                    exact = _UP.add(exact, _cost(amounts[part], tariff, _UP))
                reserved = exact.quantize(granularity, context=_UP)

    maximum = limit.maximum.quantize(granularity, context=_EXACT) if cost else limit.maximum
    if reserved is not None and reserved > maximum:
        reasons.add(RESERVATION_EXCEEDS_LIMIT)
    amounts = {}
    if not any(r in LIMIT_UNKNOWN_REASONS for r in reasons):
        if cost:
            observed = observed.quantize(granularity, context=_UP)
            estimated_low = estimated_low.quantize(granularity, context=_DOWN)
            estimated_high = estimated_high.quantize(granularity, context=_UP)
        accounted = _plus(observed, estimated_high)
        projected = _plus(accounted, reserved if reserved is not None else zero)
        if accounted > maximum:
            reasons.add(BUDGET_OVERRUN)
        if (projected > maximum) if in_scope else (accounted >= maximum):
            reasons.add(LIMIT_SATURATED)
        amounts = dict(observed=observed, estimated_low=estimated_low, estimated_high=estimated_high,
                       accounted=accounted, uncertainty=_minus(estimated_high, estimated_low), projected=projected,
                       remaining=max(_minus(maximum, accounted), zero))
    ordered = _ordered(reasons, LIMIT_REASONS)
    return BudgetAccount(
        limit_id=limit.limit_id, scope=limit.scope, unit=unit, provider_id=limit.provider_id,
        resource_id=limit.resource_id, window_kind=limit.window.kind, window_start_utc=sc._utc_text(bounds[0]),
        window_end_utc=sc._utc_text(bounds[1]), verdict=verdict_for(ordered), reasons=ordered,
        evidence_ids=tuple(sorted(evidence)), execution_ids=tuple(sorted(executions)),
        maximum=maximum, reservation_in_scope=in_scope, reserved=reserved, **amounts,
    )


def evaluate_budget(request: BudgetRequest) -> BudgetEvaluation:
    """Pure, deterministic accounting of explicit Host receipts against
    declared budget maxima with Host tariffs. Never raises on bad input and
    never mutates it: an invalid request is an explained REFUSE. The result
    never authorizes dispatch, charges, calls a provider, writes a ledger,
    holds a reservation, switches a provider or buys anything."""
    reasons = validate_request(request)
    if reasons:
        return _refused(reasons)
    as_of = qc.parse_utc(request.as_of_utc)
    by_execution = {e.execution_id: [] for e in request.executions}
    for receipt in request.receipts:
        by_execution[receipt.execution_id].append(receipt)
    resolved = {e.execution_id: _resolve(e, by_execution[e.execution_id], as_of) for e in request.executions}
    accounts = tuple(sorted((_account(lim, request, resolved, as_of) for lim in request.policy.limits),
                            key=lambda a: a.limit_id))
    cited = tuple(sorted({e for a in accounts for e in a.evidence_ids}))
    global_reasons = {r for a in accounts for r in a.reasons}
    if not cited:
        global_reasons.add(NO_EVIDENCE)
    ordered = _ordered(global_reasons, RESULT_REASONS)
    evaluation = BudgetEvaluation(
        verdict=verdict_for(ordered), request_id=request.request_id,
        request_fingerprint=hashlib.sha256(sc._canonical(_request_dict(request)).encode("ascii")).hexdigest(),
        request_reasons=(), reasons=ordered, evidence_ids=cited, currency=request.policy.currency,
        granularity=request.policy.granularity, accounts=accounts,
    )
    if len(sc._canonical(BudgetEvaluation.to_dict(evaluation))) > MAX_CANONICAL_JSON_BYTES:
        return _refused((REQUEST_TOO_LARGE,))
    return evaluation
