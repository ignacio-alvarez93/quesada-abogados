"""FCP-10A-01: Resource / Quota Manager typed contract V1 - pure,
deterministic, fail-closed, provider-neutral, NON-AUTHORITATIVE.

Defines the versioned, immutable vocabulary every later FCP-10 stage speaks:
quota policy, observed evidence, global / provider / resource limits,
windows, consumption units, evidence reliability, an advisory reservation,
refusal codes and the advisory result. It answers no "may I dispatch now?"
question and evaluates no quota: it only says whether a request is
well-formed (`validate_request`) and fixes what a result may claim
(`QuotaResult` re-checks its own invariants on construction).

Why this is a contract, not a quota authority
---------------------------------------------
* Director and Runner stay the ONLY execution and Git authorities. The
  Runner's own quota/auth holds (`PipelineRunner._hold_for_provider`:
  `WAITING_PROVIDER_QUOTA` with `next_eligible_utc` and
  `eligibility_source` RESET_HINT / BACKOFF_PROBE, `BLOCKED_PROVIDER_AUTH`),
  `max_workers` and `provider_limits` decide at execution time. Nothing here
  starts, queues, leases, reserves, retries, switches a provider, buys,
  subscribes, calls a remote API, runs a process or touches Git, the
  filesystem, the clock, the environment or the network: no pool, lease,
  ledger, gateway or store of its own exists. The instant is the explicit
  `as_of_utc`.
* No new source of truth: limits are what a caller DECLARES in a policy and
  evidence is what the caller OBSERVED from existing sources (Runner
  `ProviderCondition` / provider wait, FCP-7 Router facts, FCP-9C-01
  capacity facts, operator declaration). The source bounds the reliability
  an observation may claim. This contract prices nothing by itself: it has
  no price, cost, currency or score, and its units are counts, tokens or
  seconds only. Money is FCP-10B-02's (`fabric_resource_quota_budget`)
  alone, as exact `decimal.Decimal` in one policy currency, priced only
  through explicit tariffs the Host supplies (never invented here or
  there).
* Verdicts are reused, never reinterpreted: availability uses the Provider
  Router vocabulary (`fabric_provider_routing_policy.AVAILABILITY_STATES`),
  conditions are `runner_provider_availability.ProviderCondition` values,
  and a condition must agree with the availability it is reported with
  (the FCP-9C-01 mapping). Timestamps use the FCP-9A-02 strict parser and
  must additionally carry a zero UTC offset (`Z` or `+00:00`).
* Provider-neutral: provider ids are opaque and only compared for equality.
* No secrets and no client data: there is no free-text field at all; every
  id is a bounded lowercase id and any id the Runner's own `redact` would
  alter (credential-shaped) is refused.

Validation is in `validate_request`, never in the constructors, so every
malformed request is an explained REFUSE. Every sequence must be a tuple and
every scalar its exact type: lists/dicts/sets, bool-as-int and str/int
subclasses are refused.

Verdicts (`VERDICTS`, none of them is a permit): READY, WAIT, REFUSE,
UNKNOWN. Precedence REFUSE > UNKNOWN > WAIT > READY, derived from the reason
codes; READY needs at least one cited evidence id and no reason at all, so
success is never inferred from missing evidence. Output (`QuotaResult`,
schema `fcp10a01-resource-quota-result-v1`) holds only validated ids,
enumerated codes, a normalized UTC instant and a fingerprint, and fixes
every FCP-9A-01 zero-authority flag plus `reservation_held`,
`quota_authority`, `purchase_allowed` and `remote_api_allowed` to False as
read-only properties.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Optional

try:
    from scripts.ai import fabric_provider_routing_policy as rt
    from scripts.ai import fabric_scheduler_capacity as cap
    from scripts.ai import fabric_scheduler_contract as sc
    from scripts.ai import fabric_scheduler_window as sw
    from scripts.ai import runner_provider_availability as availability
except ImportError:  # pragma: no cover - direct script execution
    import fabric_provider_routing_policy as rt  # type: ignore[no-redef]
    import fabric_scheduler_capacity as cap  # type: ignore[no-redef]
    import fabric_scheduler_contract as sc  # type: ignore[no-redef]
    import fabric_scheduler_window as sw  # type: ignore[no-redef]
    import runner_provider_availability as availability  # type: ignore[no-redef]

REQUEST_SCHEMA = "fcp10a01-resource-quota-request-v1"
REQUEST_SCHEMA_VERSION = 1
SCHEMA = "fcp10a01-resource-quota-result-v1"
SCHEMA_VERSION = 1
QUOTA_MARKER = "FCP10A01_QUOTA_ADVISORY_ONLY_NOT_CERTIFIED_NOT_AUTHORIZED"

MAX_CONCURRENT = cap.MAX_WORKERS
MAX_LIMITS = 64
MAX_OBSERVATIONS = 64
MAX_PROVIDERS = rt.MAX_PROVIDERS
DEFAULT_MAX_EVIDENCE_AGE_SECONDS = cap.DEFAULT_MAX_FACT_AGE_SECONDS
MAX_EVIDENCE_AGE_SECONDS = cap.MAX_FACT_AGE_SECONDS
MAX_WINDOW_SECONDS = int(sw.MAX_HORIZON.total_seconds())
MAX_CANONICAL_JSON_BYTES = 131072

_ID_RE = re.compile(r"[a-z][a-z0-9._-]{0,47}")

# Consumption units: unambiguous counts, tokens or seconds - never money.
UNIT_CONCURRENT_EXECUTIONS = "CONCURRENT_EXECUTIONS"
UNIT_EXECUTIONS = "EXECUTIONS"
UNIT_ATTEMPTS = "ATTEMPTS"
UNIT_REQUESTS = "REQUESTS"
UNIT_INPUT_TOKENS = "INPUT_TOKENS"
UNIT_OUTPUT_TOKENS = "OUTPUT_TOKENS"
UNIT_TOTAL_TOKENS = "TOTAL_TOKENS"
UNIT_WALL_CLOCK_SECONDS = "WALL_CLOCK_SECONDS"
UNITS = (
    UNIT_CONCURRENT_EXECUTIONS, UNIT_EXECUTIONS, UNIT_ATTEMPTS, UNIT_REQUESTS, UNIT_INPUT_TOKENS,
    UNIT_OUTPUT_TOKENS, UNIT_TOTAL_TOKENS, UNIT_WALL_CLOCK_SECONDS,
)
# Upper bound of any amount expressed in each unit.
UNIT_MAXIMUM = {
    UNIT_CONCURRENT_EXECUTIONS: MAX_CONCURRENT, UNIT_EXECUTIONS: 1_000_000, UNIT_ATTEMPTS: 1_000_000,
    UNIT_REQUESTS: 1_000_000, UNIT_INPUT_TOKENS: 1_000_000_000, UNIT_OUTPUT_TOKENS: 1_000_000_000,
    UNIT_TOTAL_TOKENS: 1_000_000_000, UNIT_WALL_CLOCK_SECONDS: MAX_WINDOW_SECONDS,
}
# An instantaneous unit has no window; every cumulative unit needs one.
INSTANT_UNITS = frozenset({UNIT_CONCURRENT_EXECUTIONS})

SCOPE_GLOBAL = "GLOBAL"
SCOPE_PROVIDER = "PROVIDER"
SCOPE_RESOURCE = "RESOURCE"
LIMIT_SCOPES = (SCOPE_GLOBAL, SCOPE_PROVIDER, SCOPE_RESOURCE)

WINDOW_ROLLING = "ROLLING"
WINDOW_FIXED = "FIXED"
WINDOW_KINDS = (WINDOW_ROLLING, WINDOW_FIXED)

# Evidence sources (all pre-existing) and the reliability each may claim at
# most, in increasing order.
SOURCE_RUNNER_PROVIDER_CONDITION = "RUNNER_PROVIDER_CONDITION"
SOURCE_RUNNER_PROVIDER_WAIT = "RUNNER_PROVIDER_WAIT"
SOURCE_ROUTER_PROVIDER_FACTS = "ROUTER_PROVIDER_FACTS"
SOURCE_SCHEDULER_CAPACITY_FACTS = "SCHEDULER_CAPACITY_FACTS"
SOURCE_OPERATOR_DECLARATION = "OPERATOR_DECLARATION"
EVIDENCE_SOURCES = (
    SOURCE_RUNNER_PROVIDER_CONDITION, SOURCE_RUNNER_PROVIDER_WAIT, SOURCE_ROUTER_PROVIDER_FACTS,
    SOURCE_SCHEDULER_CAPACITY_FACTS, SOURCE_OPERATOR_DECLARATION,
)
RELIABILITY_UNVERIFIED = "UNVERIFIED"
RELIABILITY_CALLER_OBSERVED = "CALLER_OBSERVED"
RELIABILITY_RUNNER_CLASSIFIED = "RUNNER_CLASSIFIED"
RELIABILITIES = (RELIABILITY_UNVERIFIED, RELIABILITY_CALLER_OBSERVED, RELIABILITY_RUNNER_CLASSIFIED)
SOURCE_MAX_RELIABILITY = {
    SOURCE_RUNNER_PROVIDER_CONDITION: RELIABILITY_RUNNER_CLASSIFIED,
    SOURCE_RUNNER_PROVIDER_WAIT: RELIABILITY_RUNNER_CLASSIFIED,
    SOURCE_ROUTER_PROVIDER_FACTS: RELIABILITY_CALLER_OBSERVED,
    SOURCE_SCHEDULER_CAPACITY_FACTS: RELIABILITY_CALLER_OBSERVED,
    SOURCE_OPERATOR_DECLARATION: RELIABILITY_UNVERIFIED,
}

AVAILABILITY_STATES = rt.AVAILABILITY_STATES
CONDITIONS = tuple(c.value for c in availability.ProviderCondition)
# The only availability each classified condition is consistent with (the
# FCP-9C-01 mapping; None: not an availability hold).
CONDITION_AVAILABILITY = cap._CONDITION_AVAILABILITY
# The Runner's own `eligibility_source` values of a quota wait.
ELIGIBILITY_RESET_HINT = "RESET_HINT"
ELIGIBILITY_BACKOFF_PROBE = "BACKOFF_PROBE"
ELIGIBILITY_SOURCES = (ELIGIBILITY_RESET_HINT, ELIGIBILITY_BACKOFF_PROBE)

READY = "READY"
WAIT = "WAIT"
REFUSE = "REFUSE"
UNKNOWN = "UNKNOWN"
VERDICTS = (READY, WAIT, REFUSE, UNKNOWN)

# Request-level refusal codes, in their fixed canonical order.
REQUEST_NOT_TYPED = "REQUEST_NOT_TYPED"
SCHEMA_VERSION_UNSUPPORTED = "SCHEMA_VERSION_UNSUPPORTED"
REQUEST_ID_INVALID = "REQUEST_ID_INVALID"
ID_SECRET_SHAPED = "ID_SECRET_SHAPED"
ID_DUPLICATE = "ID_DUPLICATE"
AS_OF_INVALID = "AS_OF_INVALID"
POLICY_NOT_TYPED = "POLICY_NOT_TYPED"
POLICY_SCHEMA_VERSION_UNSUPPORTED = "POLICY_SCHEMA_VERSION_UNSUPPORTED"
POLICY_ID_INVALID = "POLICY_ID_INVALID"
MAX_EVIDENCE_AGE_INVALID = "MAX_EVIDENCE_AGE_INVALID"
LIMITS_MALFORMED = "LIMITS_MALFORMED"
LIMITS_EMPTY = "LIMITS_EMPTY"
LIMIT_ID_INVALID = "LIMIT_ID_INVALID"
LIMIT_SCOPE_UNKNOWN = "LIMIT_SCOPE_UNKNOWN"
LIMIT_SCOPE_TARGET_INVALID = "LIMIT_SCOPE_TARGET_INVALID"
LIMIT_UNIT_UNKNOWN = "LIMIT_UNIT_UNKNOWN"
LIMIT_MAXIMUM_INVALID = "LIMIT_MAXIMUM_INVALID"
LIMIT_WINDOW_REQUIRED = "LIMIT_WINDOW_REQUIRED"
LIMIT_WINDOW_FORBIDDEN = "LIMIT_WINDOW_FORBIDDEN"
WINDOW_NOT_TYPED = "WINDOW_NOT_TYPED"
WINDOW_KIND_UNKNOWN = "WINDOW_KIND_UNKNOWN"
WINDOW_DURATION_INVALID = "WINDOW_DURATION_INVALID"
WINDOW_ANCHOR_INVALID = "WINDOW_ANCHOR_INVALID"
LIMIT_AMBIGUOUS = "LIMIT_AMBIGUOUS"
OBSERVATIONS_MALFORMED = "OBSERVATIONS_MALFORMED"
OBSERVATION_ID_INVALID = "OBSERVATION_ID_INVALID"
OBSERVATION_PROVIDER_INVALID = "OBSERVATION_PROVIDER_INVALID"
OBSERVATION_RESOURCE_INVALID = "OBSERVATION_RESOURCE_INVALID"
OBSERVATION_SOURCE_UNKNOWN = "OBSERVATION_SOURCE_UNKNOWN"
OBSERVATION_RELIABILITY_UNKNOWN = "OBSERVATION_RELIABILITY_UNKNOWN"
OBSERVATION_RELIABILITY_OVERCLAIMED = "OBSERVATION_RELIABILITY_OVERCLAIMED"
OBSERVATION_TIME_INVALID = "OBSERVATION_TIME_INVALID"
OBSERVATION_AVAILABILITY_UNKNOWN = "OBSERVATION_AVAILABILITY_UNKNOWN"
OBSERVATION_CONDITION_UNKNOWN = "OBSERVATION_CONDITION_UNKNOWN"
OBSERVATION_CONDITION_CONTRADICTS = "OBSERVATION_CONDITION_CONTRADICTS"
OBSERVATION_ELIGIBILITY_INVALID = "OBSERVATION_ELIGIBILITY_INVALID"
OBSERVATION_USAGE_INVALID = "OBSERVATION_USAGE_INVALID"
RESERVATION_NOT_TYPED = "RESERVATION_NOT_TYPED"
RESERVATION_ID_INVALID = "RESERVATION_ID_INVALID"
RESERVATION_TARGET_INVALID = "RESERVATION_TARGET_INVALID"
RESERVATION_AMOUNTS_MALFORMED = "RESERVATION_AMOUNTS_MALFORMED"
RESERVATION_UNIT_DUPLICATE = "RESERVATION_UNIT_DUPLICATE"
REQUEST_TOO_LARGE = "REQUEST_TOO_LARGE"
REQUEST_REASONS = (
    REQUEST_NOT_TYPED, SCHEMA_VERSION_UNSUPPORTED, REQUEST_ID_INVALID, ID_SECRET_SHAPED, ID_DUPLICATE,
    AS_OF_INVALID, POLICY_NOT_TYPED, POLICY_SCHEMA_VERSION_UNSUPPORTED, POLICY_ID_INVALID,
    MAX_EVIDENCE_AGE_INVALID, LIMITS_MALFORMED, LIMITS_EMPTY, LIMIT_ID_INVALID, LIMIT_SCOPE_UNKNOWN,
    LIMIT_SCOPE_TARGET_INVALID, LIMIT_UNIT_UNKNOWN, LIMIT_MAXIMUM_INVALID, LIMIT_WINDOW_REQUIRED,
    LIMIT_WINDOW_FORBIDDEN, WINDOW_NOT_TYPED, WINDOW_KIND_UNKNOWN, WINDOW_DURATION_INVALID, WINDOW_ANCHOR_INVALID,
    LIMIT_AMBIGUOUS, OBSERVATIONS_MALFORMED, OBSERVATION_ID_INVALID, OBSERVATION_PROVIDER_INVALID,
    OBSERVATION_RESOURCE_INVALID, OBSERVATION_SOURCE_UNKNOWN, OBSERVATION_RELIABILITY_UNKNOWN,
    OBSERVATION_RELIABILITY_OVERCLAIMED, OBSERVATION_TIME_INVALID, OBSERVATION_AVAILABILITY_UNKNOWN,
    OBSERVATION_CONDITION_UNKNOWN, OBSERVATION_CONDITION_CONTRADICTS, OBSERVATION_ELIGIBILITY_INVALID,
    OBSERVATION_USAGE_INVALID, RESERVATION_NOT_TYPED, RESERVATION_ID_INVALID, RESERVATION_TARGET_INVALID,
    RESERVATION_AMOUNTS_MALFORMED, RESERVATION_UNIT_DUPLICATE, REQUEST_TOO_LARGE,
)

# Evaluation reason codes for later stages, grouped by the verdict they
# force, in their fixed canonical order.
PROVIDER_AUTH_BLOCKED = "PROVIDER_AUTH_BLOCKED"
RESERVATION_EXCEEDS_LIMIT = "RESERVATION_EXCEEDS_LIMIT"
NO_EVIDENCE = "NO_EVIDENCE"
EVIDENCE_STALE = "EVIDENCE_STALE"
EVIDENCE_FROM_FUTURE = "EVIDENCE_FROM_FUTURE"
EVIDENCE_UNVERIFIED = "EVIDENCE_UNVERIFIED"
EVIDENCE_CONTRADICTORY = "EVIDENCE_CONTRADICTORY"
AVAILABILITY_UNKNOWN = "AVAILABILITY_UNKNOWN"
USAGE_UNKNOWN = "USAGE_UNKNOWN"
PROVIDER_QUOTA_WAIT = "PROVIDER_QUOTA_WAIT"
LIMIT_SATURATED = "LIMIT_SATURATED"
REFUSING_REASONS = (PROVIDER_AUTH_BLOCKED, RESERVATION_EXCEEDS_LIMIT)
UNKNOWN_REASONS = (
    NO_EVIDENCE, EVIDENCE_STALE, EVIDENCE_FROM_FUTURE, EVIDENCE_UNVERIFIED, EVIDENCE_CONTRADICTORY,
    AVAILABILITY_UNKNOWN, USAGE_UNKNOWN,
)
WAITING_REASONS = (PROVIDER_QUOTA_WAIT, LIMIT_SATURATED)
RESULT_REASONS = REFUSING_REASONS + UNKNOWN_REASONS + WAITING_REASONS


def _valid_id(value) -> bool:
    return type(value) is str and _ID_RE.fullmatch(value) is not None


def _secret_shaped(value) -> bool:
    return type(value) is str and availability.redact(value) != value


def _bounded_int(value, low: int, high: int) -> bool:
    return sc._is_int(value) and low <= value <= high


def _in(value, vocabulary) -> bool:
    return type(value) is str and value in vocabulary


def parse_utc(value):
    """Strict FCP-9A-02 parse, additionally requiring a zero UTC offset."""
    if type(value) is not str or not (value.endswith("Z") or value.endswith("+00:00")):
        return None
    return sw.parse_utc(value)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class QuotaWindow:
    """ROLLING: the trailing `duration_seconds`. FIXED: consecutive periods
    of `duration_seconds` starting at the UTC `anchor_utc`."""
    kind: str
    duration_seconds: int
    anchor_utc: Optional[str] = None


@dataclass(frozen=True)
class QuotaLimit:
    """A declared ceiling of `maximum` `unit` over `window` for one scope:
    GLOBAL (no target), PROVIDER (`provider_id`) or RESOURCE (`resource_id`,
    optionally of one provider)."""
    limit_id: str
    scope: str
    unit: str
    maximum: int
    window: Optional[QuotaWindow] = None
    provider_id: Optional[str] = None
    resource_id: Optional[str] = None


@dataclass(frozen=True)
class QuotaPolicy:
    """Caller-declared policy. It narrows; it never creates capacity."""
    policy_id: str
    limits: tuple
    max_evidence_age_seconds: int = DEFAULT_MAX_EVIDENCE_AGE_SECONDS
    schema_version: int = REQUEST_SCHEMA_VERSION


@dataclass(frozen=True)
class QuotaObservation:
    """One structured observation from an existing source (never prose).
    `next_eligible_utc` / `eligibility_source` mirror a Runner quota wait;
    `usage_unit` / `usage_amount` are observed consumption (both or none)."""
    evidence_id: str
    provider_id: str
    source: str
    reliability: str
    observed_at_utc: str
    availability: str
    condition: Optional[str] = None
    next_eligible_utc: Optional[str] = None
    eligibility_source: Optional[str] = None
    resource_id: Optional[str] = None
    usage_unit: Optional[str] = None
    usage_amount: Optional[int] = None


@dataclass(frozen=True)
class AdvisoryReservation:
    """The intended consumption of one prospective execution, as unique
    `(unit, amount)` pairs. Consultative only: nothing is ever held."""
    reservation_id: str
    provider_id: str
    amounts: tuple
    resource_id: Optional[str] = None


@dataclass(frozen=True)
class QuotaRequest:
    """Explicit, immutable quota question. Validated by `validate_request`
    (fail closed), not here."""
    request_id: str
    as_of_utc: str
    policy: object
    reservation: object
    observations: tuple = ()
    schema_version: int = REQUEST_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def verdict_for(reasons: tuple) -> str:
    """REFUSE > UNKNOWN > WAIT > READY."""
    if any(r in REFUSING_REASONS for r in reasons):
        return REFUSE
    if any(r in UNKNOWN_REASONS for r in reasons):
        return UNKNOWN
    return WAIT if reasons else READY


class _QuotaGuarantees(sc._NotAuthorized):
    """FCP-9A-01 zero-authority flags plus the quota-specific ones."""

    @property
    def reservation_held(self) -> bool:
        return False

    @property
    def quota_authority(self) -> bool:
        return False

    @property
    def purchase_allowed(self) -> bool:
        return False

    @property
    def remote_api_allowed(self) -> bool:
        return False

    @staticmethod
    def _guarantees() -> dict:
        guarantees = sc._NotAuthorized._guarantees()
        guarantees.update(marker=QUOTA_MARKER, reservation_held=False, quota_authority=False,
                          purchase_allowed=False, remote_api_allowed=False)
        return guarantees


@dataclass(frozen=True)
class QuotaResult(_QuotaGuarantees):
    """Advisory quota result. Echo fields hold only validated values (None
    and () when the request was refused). Construction re-derives the
    verdict, so a hand-made result cannot claim more than its reasons."""
    verdict: str
    request_id: Optional[str]
    request_fingerprint: Optional[str]
    request_reasons: tuple
    reasons: tuple
    evidence_ids: tuple
    wait_until_utc: Optional[str] = None

    def __post_init__(self):
        if not _in(self.verdict, VERDICTS):
            raise ValueError("unknown verdict")
        if not (type(self.request_reasons) is tuple and all(_in(r, REQUEST_REASONS) for r in self.request_reasons)
                and self.request_reasons == sc._ordered(self.request_reasons, REQUEST_REASONS)):
            raise ValueError("request_reasons must be ordered request reason codes")
        if self.request_reasons:
            if (self.verdict != REFUSE or self.reasons or self.evidence_ids
                    or (self.request_id, self.request_fingerprint, self.wait_until_utc) != (None, None, None)):
                raise ValueError("a refused request echoes nothing and decides nothing")
            return
        if not _valid_id(self.request_id):
            raise ValueError("request_id must be a valid id")
        if not (type(self.request_fingerprint) is str and sc._FINGERPRINT_RE.fullmatch(self.request_fingerprint)):
            raise ValueError("request_fingerprint must be a sha256 hex digest")
        if not (type(self.reasons) is tuple and all(_in(r, RESULT_REASONS) for r in self.reasons)
                and self.reasons == sc._ordered(self.reasons, RESULT_REASONS)):
            raise ValueError("reasons must be ordered result reason codes")
        if self.verdict != verdict_for(self.reasons):
            raise ValueError("verdict must be exactly the one derived from reasons")
        if not (type(self.evidence_ids) is tuple and len(self.evidence_ids) <= MAX_OBSERVATIONS
                and all(_valid_id(e) for e in self.evidence_ids)
                and list(self.evidence_ids) == sorted(set(self.evidence_ids))):
            raise ValueError("evidence_ids must be sorted unique ids")
        if self.verdict == READY and not self.evidence_ids:
            raise ValueError("READY must cite evidence; success is never inferred")
        if self.wait_until_utc is not None:
            parsed = parse_utc(self.wait_until_utc)
            if self.verdict != WAIT or parsed is None or sc._utc_text(parsed) != self.wait_until_utc:
                raise ValueError("only a WAIT carries a normalized UTC wait_until_utc")

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA, "schema_version": SCHEMA_VERSION, "verdict": self.verdict,
            "request_id": self.request_id, "request_fingerprint": self.request_fingerprint,
            "request_reasons": list(self.request_reasons), "reasons": list(self.reasons),
            "evidence_ids": list(self.evidence_ids), "wait_until_utc": self.wait_until_utc,
            **_QuotaGuarantees._guarantees(),
        }


def canonical_json(result: QuotaResult) -> str:
    """Stable, sorted, compact, size-bounded serialization of the exact
    contract type (a subclass cannot substitute `to_dict`)."""
    if type(result) is not QuotaResult:
        raise TypeError("canonical_json accepts only a QuotaResult")
    text = sc._canonical(QuotaResult.to_dict(result))
    if len(text) > MAX_CANONICAL_JSON_BYTES:
        raise ValueError("canonical result exceeds MAX_CANONICAL_JSON_BYTES")
    return text


def refused_result(reasons) -> QuotaResult:
    """The explained REFUSE of an invalid request (nothing echoed)."""
    return QuotaResult(verdict=REFUSE, request_id=None, request_fingerprint=None,
                       request_reasons=sc._ordered(reasons, REQUEST_REASONS), reasons=(), evidence_ids=())


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _window_reasons(window) -> set:
    if type(window) is not QuotaWindow:
        return {WINDOW_NOT_TYPED}
    reasons = set()
    if not _in(window.kind, WINDOW_KINDS):
        reasons.add(WINDOW_KIND_UNKNOWN)
    if not _bounded_int(window.duration_seconds, 1, MAX_WINDOW_SECONDS):
        reasons.add(WINDOW_DURATION_INVALID)
    if window.kind == WINDOW_FIXED:
        if parse_utc(window.anchor_utc) is None:
            reasons.add(WINDOW_ANCHOR_INVALID)
    elif window.anchor_utc is not None:
        reasons.add(WINDOW_ANCHOR_INVALID)
    return reasons


def _limit_reasons(limit: QuotaLimit) -> set:
    reasons = set()
    if not _valid_id(limit.limit_id):
        reasons.add(LIMIT_ID_INVALID)
    if not _in(limit.scope, LIMIT_SCOPES):
        reasons.add(LIMIT_SCOPE_UNKNOWN)
    else:
        provider_ok = limit.provider_id is None or sc._valid_provider_id(limit.provider_id)
        resource_ok = limit.resource_id is None or _valid_id(limit.resource_id)
        shape = {
            SCOPE_GLOBAL: limit.provider_id is None and limit.resource_id is None,
            SCOPE_PROVIDER: limit.provider_id is not None and limit.resource_id is None,
            SCOPE_RESOURCE: limit.resource_id is not None,
        }[limit.scope]
        if not (provider_ok and resource_ok and shape):
            reasons.add(LIMIT_SCOPE_TARGET_INVALID)
    if not _in(limit.unit, UNITS):
        reasons.add(LIMIT_UNIT_UNKNOWN)
        return reasons
    if not _bounded_int(limit.maximum, 1, UNIT_MAXIMUM[limit.unit]):
        reasons.add(LIMIT_MAXIMUM_INVALID)
    if limit.unit in INSTANT_UNITS:
        if limit.window is not None:
            reasons.add(LIMIT_WINDOW_FORBIDDEN)
    elif limit.window is None:
        reasons.add(LIMIT_WINDOW_REQUIRED)
    else:
        reasons |= _window_reasons(limit.window)
    return reasons


def _limit_key(limit: QuotaLimit) -> tuple:
    window = limit.window
    return (limit.scope, limit.provider_id, limit.resource_id, limit.unit,
            None if window is None else (window.kind, window.duration_seconds, sc._utc_text(parse_utc(window.anchor_utc))))


def _policy_reasons(policy) -> set:
    if type(policy) is not QuotaPolicy:
        return {POLICY_NOT_TYPED}
    reasons = set()
    if not (sc._is_int(policy.schema_version) and policy.schema_version == REQUEST_SCHEMA_VERSION):
        reasons.add(POLICY_SCHEMA_VERSION_UNSUPPORTED)
    if not _valid_id(policy.policy_id):
        reasons.add(POLICY_ID_INVALID)
    if not _bounded_int(policy.max_evidence_age_seconds, 1, MAX_EVIDENCE_AGE_SECONDS):
        reasons.add(MAX_EVIDENCE_AGE_INVALID)
    limits = policy.limits
    if not (type(limits) is tuple and len(limits) <= MAX_LIMITS and all(type(lim) is QuotaLimit for lim in limits)):
        reasons.add(LIMITS_MALFORMED)
        return reasons
    if not limits:
        reasons.add(LIMITS_EMPTY)
    clean = []
    for limit in limits:
        limit_reasons = _limit_reasons(limit)
        reasons |= limit_reasons
        if not limit_reasons:
            clean.append(limit)
    if len({_limit_key(lim) for lim in clean}) != len(clean):
        reasons.add(LIMIT_AMBIGUOUS)
    return reasons


def _usage_ok(unit, amount) -> bool:
    if unit is None and amount is None:
        return True
    return _in(unit, UNITS) and _bounded_int(amount, 0, UNIT_MAXIMUM[unit])


def _observation_reasons(obs: QuotaObservation) -> set:
    reasons = set()
    if not _valid_id(obs.evidence_id):
        reasons.add(OBSERVATION_ID_INVALID)
    if not sc._valid_provider_id(obs.provider_id):
        reasons.add(OBSERVATION_PROVIDER_INVALID)
    if obs.resource_id is not None and not _valid_id(obs.resource_id):
        reasons.add(OBSERVATION_RESOURCE_INVALID)
    source_ok = _in(obs.source, EVIDENCE_SOURCES)
    if not source_ok:
        reasons.add(OBSERVATION_SOURCE_UNKNOWN)
    if not _in(obs.reliability, RELIABILITIES):
        reasons.add(OBSERVATION_RELIABILITY_UNKNOWN)
    elif source_ok and RELIABILITIES.index(obs.reliability) > RELIABILITIES.index(SOURCE_MAX_RELIABILITY[obs.source]):
        reasons.add(OBSERVATION_RELIABILITY_OVERCLAIMED)
    if parse_utc(obs.observed_at_utc) is None:
        reasons.add(OBSERVATION_TIME_INVALID)
    availability_ok = _in(obs.availability, AVAILABILITY_STATES)
    if not availability_ok:
        reasons.add(OBSERVATION_AVAILABILITY_UNKNOWN)
    if obs.condition is not None:
        if not _in(obs.condition, CONDITIONS):
            reasons.add(OBSERVATION_CONDITION_UNKNOWN)
        elif availability_ok and obs.availability != "UNKNOWN":
            held_as = obs.availability if obs.availability in ("QUOTA_WAIT", "AUTH_BLOCKED") else None
            if CONDITION_AVAILABILITY[obs.condition] != held_as:
                reasons.add(OBSERVATION_CONDITION_CONTRADICTS)
    if obs.next_eligible_utc is None:
        if obs.eligibility_source is not None:
            reasons.add(OBSERVATION_ELIGIBILITY_INVALID)
    elif (parse_utc(obs.next_eligible_utc) is None or not _in(obs.eligibility_source, ELIGIBILITY_SOURCES)
          or obs.availability != "QUOTA_WAIT"):
        reasons.add(OBSERVATION_ELIGIBILITY_INVALID)
    if not _usage_ok(obs.usage_unit, obs.usage_amount):
        reasons.add(OBSERVATION_USAGE_INVALID)
    return reasons


def _reservation_reasons(reservation) -> set:
    if type(reservation) is not AdvisoryReservation:
        return {RESERVATION_NOT_TYPED}
    reasons = set()
    if not _valid_id(reservation.reservation_id):
        reasons.add(RESERVATION_ID_INVALID)
    if not sc._valid_provider_id(reservation.provider_id) or (
            reservation.resource_id is not None and not _valid_id(reservation.resource_id)):
        reasons.add(RESERVATION_TARGET_INVALID)
    amounts = reservation.amounts
    if not (type(amounts) is tuple and 1 <= len(amounts) <= len(UNITS) and all(
            type(p) is tuple and len(p) == 2 and _in(p[0], UNITS) and _bounded_int(p[1], 1, UNIT_MAXIMUM[p[0]])
            for p in amounts)):
        reasons.add(RESERVATION_AMOUNTS_MALFORMED)
    elif len({p[0] for p in amounts}) != len(amounts):
        reasons.add(RESERVATION_UNIT_DUPLICATE)
    return reasons


def _declared_ids(request: QuotaRequest) -> list:
    ids = [request.request_id]
    policy, reservation = request.policy, request.reservation
    if type(policy) is QuotaPolicy:
        ids.append(policy.policy_id)
        if type(policy.limits) is tuple:
            ids += [lim.limit_id for lim in policy.limits if type(lim) is QuotaLimit]
    if type(reservation) is AdvisoryReservation:
        ids.append(reservation.reservation_id)
    if type(request.observations) is tuple:
        ids += [o.evidence_id for o in request.observations if type(o) is QuotaObservation]
    return ids


def _structural_reasons(request) -> tuple:
    if type(request) is not QuotaRequest:
        return (REQUEST_NOT_TYPED,)
    reasons = set()
    if not (sc._is_int(request.schema_version) and request.schema_version == REQUEST_SCHEMA_VERSION):
        reasons.add(SCHEMA_VERSION_UNSUPPORTED)
    if not _valid_id(request.request_id):
        reasons.add(REQUEST_ID_INVALID)
    if parse_utc(request.as_of_utc) is None:
        reasons.add(AS_OF_INVALID)
    reasons |= _policy_reasons(request.policy)
    reasons |= _reservation_reasons(request.reservation)
    observations = request.observations
    if not (type(observations) is tuple and len(observations) <= MAX_OBSERVATIONS
            and all(type(o) is QuotaObservation for o in observations)):
        reasons.add(OBSERVATIONS_MALFORMED)
    else:
        for obs in observations:
            reasons |= _observation_reasons(obs)
    ids = _declared_ids(request)
    if any(_secret_shaped(i) for i in ids):
        reasons.add(ID_SECRET_SHAPED)
    strings = [i for i in ids if type(i) is str]
    if len(strings) != len(set(strings)):
        reasons.add(ID_DUPLICATE)
    return sc._ordered(reasons, REQUEST_REASONS)


def _utc(value) -> Optional[str]:
    return None if value is None else sc._utc_text(parse_utc(value))


def _request_dict(request: QuotaRequest) -> dict:
    policy, reservation = request.policy, request.reservation
    return {
        "schema": REQUEST_SCHEMA, "schema_version": REQUEST_SCHEMA_VERSION, "request_id": request.request_id,
        "as_of_utc": _utc(request.as_of_utc),
        "policy": {
            "policy_id": policy.policy_id, "max_evidence_age_seconds": policy.max_evidence_age_seconds,
            "limits": sorted(
                ({"limit_id": lim.limit_id, "scope": lim.scope, "unit": lim.unit, "maximum": lim.maximum,
                  "provider_id": lim.provider_id, "resource_id": lim.resource_id,
                  "window": None if lim.window is None else {
                      "kind": lim.window.kind, "duration_seconds": lim.window.duration_seconds,
                      "anchor_utc": _utc(lim.window.anchor_utc)}}
                 for lim in policy.limits), key=lambda d: d["limit_id"]),
        },
        "reservation": {
            "reservation_id": reservation.reservation_id, "provider_id": reservation.provider_id,
            "resource_id": reservation.resource_id, "amounts": sorted([u, a] for u, a in reservation.amounts),
        },
        "observations": sorted(
            ({"evidence_id": o.evidence_id, "provider_id": o.provider_id, "resource_id": o.resource_id,
              "source": o.source, "reliability": o.reliability, "observed_at_utc": _utc(o.observed_at_utc),
              "availability": o.availability, "condition": o.condition,
              "next_eligible_utc": _utc(o.next_eligible_utc), "eligibility_source": o.eligibility_source,
              "usage_unit": o.usage_unit, "usage_amount": o.usage_amount}
             for o in request.observations), key=lambda d: d["evidence_id"]),
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


def canonical_request_json(request: QuotaRequest) -> str:
    """Stable serialization of a VALID request: timestamps normalized to
    UTC "Z", order-free collections sorted. Raises ValueError otherwise."""
    reasons = validate_request(request)
    if reasons:
        raise ValueError("canonical_request_json accepts only a valid QuotaRequest: " + ",".join(reasons))
    return sc._canonical(_request_dict(request))


def request_fingerprint(request: QuotaRequest) -> str:
    """sha256 of the canonical request (raises ValueError if invalid)."""
    return hashlib.sha256(canonical_request_json(request).encode("ascii")).hexdigest()
