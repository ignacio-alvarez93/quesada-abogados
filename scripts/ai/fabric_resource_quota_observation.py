"""FCP-10A-02: Verifiable quota / availability observation adapter - pure,
deterministic, fail-closed, provider-neutral, NON-AUTHORITATIVE.

Answers ONE question: given structured facts the caller ALREADY holds from
existing Runner / Router / Scheduler sources, what FCP-10A-01 contract
observations (`QuotaObservation`) do they support, how fresh and how certain
is each, and what does that say about each provider's availability and
capacity right now? It never answers "may I dispatch / retry / switch now?".

Sources (exact native types only; nothing is read, probed or scraped)
----------------------------------------------------------------------
* RUNNER_PROVIDER_WAIT: a `runner_pipeline.WorkerRuntime` in a Runner
  provider hold (`WAITING_PROVIDER_QUOTA` / `BLOCKED_PROVIDER_AUTH`), read
  only through its state, `active_provider` and the structured fields of the
  `provider_wait` the Runner's own `_hold_for_provider` wrote (condition,
  `since_utc`, `last_hit_utc`, `next_eligible_utc`, `eligibility_source`,
  `consecutive_quota_waits`). Its instant is the Runner's `last_hit_utc`.
* RUNNER_PROVIDER_CONDITION: a `runner_provider_availability.
  ProviderClassification`, read only through its `condition` enum member.
* ROUTER_PROVIDER_FACTS: an FCP-7 `ProviderFacts` (availability, capacity).
* SCHEDULER_CAPACITY_FACTS: an FCP-9C-01 `ProviderCapacityFacts`
  (availability, capacity, proven slots, last condition, own instant).
OPERATOR_DECLARATION is a contract source but not a Runner/Router fact, so it
is never adapted. Provider prose is never evidence: `reason`, `reset_hint`,
`message_excerpt`, `budget_note` and `http_status` are ignored entirely, so
no quota reset, session/message limit or recovery is ever inferred from text.
`next_eligible_utc` is echoed only as the Runner computed it, never derived.

Fail closed
-----------
* A record that is untyped, of the wrong payload type, malformed (bool-as-int,
  str subclasses, out-of-vocabulary values), carries unexpected wait fields,
  is internally inconsistent or lacks a required fact is REJECTED: it yields
  no observation and makes its provider UNCERTAIN (EVIDENCE_REJECTED or
  FACT_MISSING); an unattributable rejection makes every provider UNCERTAIN.
* An internally contradictory record (condition vs availability, auth hold
  with an eligibility instant, AVAILABLE with zero proven slots) is adapted
  as UNKNOWN with EVIDENCE_CONTRADICTORY: no hold is invented from one half.
* Holds are never downgraded: AUTH_BLOCKED > QUOTA_WAIT > UNKNOWN > NONE and
  FULL > UNKNOWN > AVAILABLE across a provider's records. A positive claim
  (NONE / AVAILABLE) survives only without any rejected, missing, stale,
  future-dated or contradictory evidence; disagreeing records are
  EVIDENCE_CONTRADICTORY. A Runner quota wait whose `next_eligible_utc` has
  passed stays QUOTA_WAIT (QUOTA_RECOVERY_UNCONFIRMED): only the Runner's own
  next probe can end it. A transient / execution classification (e.g. a rate
  limit) is not quota and decides nothing (CONDITION_UNRESOLVED).
* Not-yet-known (AVAILABILITY_UNKNOWN, CAPACITY_UNKNOWN, CONDITION_UNRESOLVED,
  QUOTA_RECOVERY_UNCONFIRMED) and fact-missing (NO_EVIDENCE, FACT_MISSING)
  are UNCERTAIN, never success.

Output (`QuotaObservationSnapshot`, schema
`fcp10a02-resource-quota-observation-snapshot-v1`): outcome REFUSED (invalid
request, nothing echoed) > UNKNOWN (any rejected record, uncertain provider
or nothing observed) > OBSERVED (every provider CERTAIN; holds may remain).
OBSERVED is a statement about evidence quality, never a permit. It holds
only validated ids, enumerated codes, normalized UTC instants, integers,
contract observations and a self-verifying fingerprint, and fixes every
FCP-10A-01 zero-authority flag to False as read-only properties. No I/O,
clock, process, network, Git, pool, lease, ledger or store of its own.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Optional

try:
    from scripts.ai import fabric_provider_routing_policy as rt
    from scripts.ai import fabric_resource_quota_contract as qc
    from scripts.ai import fabric_scheduler_capacity as cap
    from scripts.ai import fabric_scheduler_contract as sc
    from scripts.ai import runner_pipeline as pipeline
    from scripts.ai import runner_provider_availability as availability
except ImportError:  # pragma: no cover - direct script execution
    import fabric_provider_routing_policy as rt  # type: ignore[no-redef]
    import fabric_resource_quota_contract as qc  # type: ignore[no-redef]
    import fabric_scheduler_capacity as cap  # type: ignore[no-redef]
    import fabric_scheduler_contract as sc  # type: ignore[no-redef]
    import runner_pipeline as pipeline  # type: ignore[no-redef]
    import runner_provider_availability as availability  # type: ignore[no-redef]

REQUEST_SCHEMA_VERSION = 1
SCHEMA = "fcp10a02-resource-quota-observation-snapshot-v1"
SCHEMA_VERSION = 1
OBSERVATION_MARKER = "FCP10A02_QUOTA_OBSERVATION_ONLY_NOT_CERTIFIED_NOT_AUTHORIZED"

MAX_RECORDS = qc.MAX_OBSERVATIONS
MAX_PROVIDERS = qc.MAX_PROVIDERS
MAX_CANONICAL_JSON_BYTES = qc.MAX_CANONICAL_JSON_BYTES
# Widest gap the strict UTC parser admits (years 2000..2199).
MAX_AGE_SECONDS = 200 * 366 * 86400

_W = pipeline.WorkerState
_QUOTA = availability.ProviderCondition.QUOTA_EXHAUSTED.value
_AUTH = availability.ProviderCondition.AUTH_BLOCKED.value
# The Runner hold state each held condition belongs to.
_HOLD_STATE_CONDITION = {_W.WAITING_PROVIDER_QUOTA.value: _QUOTA, _W.BLOCKED_PROVIDER_AUTH.value: _AUTH}
# Every key `PipelineRunner._hold_for_provider` writes; anything else is
# manipulated input. Only the structured ones are ever read.
RUNNER_WAIT_FIELDS = frozenset({
    "condition", "reason", "http_status", "reset_hint", "message_excerpt", "since_utc", "last_hit_utc",
    "next_eligible_utc", "eligibility_source", "consecutive_quota_waits", "budget_note",
})
RUNNER_WAIT_READ_FIELDS = frozenset({
    "condition", "since_utc", "last_hit_utc", "next_eligible_utc", "eligibility_source", "consecutive_quota_waits",
})
_WAIT_REQUIRED_FIELDS = ("condition", "since_utc", "last_hit_utc")

# Adaptable sources -> exact native payload type, and whether the payload
# carries its own observation instant (then the record must not supply one).
_SOURCE_PAYLOAD = {
    qc.SOURCE_RUNNER_PROVIDER_WAIT: pipeline.WorkerRuntime,
    qc.SOURCE_RUNNER_PROVIDER_CONDITION: availability.ProviderClassification,
    qc.SOURCE_ROUTER_PROVIDER_FACTS: rt.ProviderFacts,
    qc.SOURCE_SCHEDULER_CAPACITY_FACTS: cap.ProviderCapacityFacts,
}
ADAPTABLE_SOURCES = tuple(s for s in qc.EVIDENCE_SOURCES if s in _SOURCE_PAYLOAD)
_SELF_TIMED_SOURCES = frozenset({qc.SOURCE_RUNNER_PROVIDER_WAIT, qc.SOURCE_SCHEDULER_CAPACITY_FACTS})

OBSERVED = "OBSERVED"
UNKNOWN = qc.UNKNOWN
REFUSED = "REFUSED"
OUTCOMES = (OBSERVED, UNKNOWN, REFUSED)
ADAPTED = "ADAPTED"
REJECTED = "REJECTED"
RECORD_STATUSES = (ADAPTED, REJECTED)
CERTAIN = "CERTAIN"
UNCERTAIN = "UNCERTAIN"
CERTAINTIES = (CERTAIN, UNCERTAIN)
FRESH = "FRESH"
STALE = "STALE"
FROM_FUTURE = "FROM_FUTURE"
FRESHNESS = (FRESH, STALE, FROM_FUTURE)
AVAILABILITY_STATES = qc.AVAILABILITY_STATES
CAPACITY_STATES = rt.CAPACITY_STATES

# Request-level refusal codes, in their fixed canonical order.
REQUEST_NOT_TYPED = qc.REQUEST_NOT_TYPED
SCHEMA_VERSION_UNSUPPORTED = qc.SCHEMA_VERSION_UNSUPPORTED
REQUEST_ID_INVALID = qc.REQUEST_ID_INVALID
ID_SECRET_SHAPED = qc.ID_SECRET_SHAPED
AS_OF_INVALID = qc.AS_OF_INVALID
MAX_EVIDENCE_AGE_INVALID = qc.MAX_EVIDENCE_AGE_INVALID
RECORDS_MALFORMED = "RECORDS_MALFORMED"
PROVIDER_IDS_MALFORMED = "PROVIDER_IDS_MALFORMED"
PROVIDERS_TOO_MANY = "PROVIDERS_TOO_MANY"
REQUEST_TOO_LARGE = qc.REQUEST_TOO_LARGE
REQUEST_REASONS = (
    REQUEST_NOT_TYPED, SCHEMA_VERSION_UNSUPPORTED, REQUEST_ID_INVALID, ID_SECRET_SHAPED, AS_OF_INVALID,
    MAX_EVIDENCE_AGE_INVALID, RECORDS_MALFORMED, PROVIDER_IDS_MALFORMED, PROVIDERS_TOO_MANY, REQUEST_TOO_LARGE,
)

# Record rejection codes, in their fixed canonical order.
RECORD_NOT_TYPED = "RECORD_NOT_TYPED"
EVIDENCE_ID_INVALID = "EVIDENCE_ID_INVALID"
EVIDENCE_ID_SECRET_SHAPED = "EVIDENCE_ID_SECRET_SHAPED"
EVIDENCE_ID_DUPLICATE = "EVIDENCE_ID_DUPLICATE"
PROVIDER_ID_INVALID = "PROVIDER_ID_INVALID"
SOURCE_UNKNOWN = "SOURCE_UNKNOWN"
SOURCE_NOT_ADAPTABLE = "SOURCE_NOT_ADAPTABLE"
PAYLOAD_NOT_TYPED = "PAYLOAD_NOT_TYPED"
PAYLOAD_MALFORMED = "PAYLOAD_MALFORMED"
PAYLOAD_UNEXPECTED_FIELD = "PAYLOAD_UNEXPECTED_FIELD"
PAYLOAD_FACT_MISSING = "PAYLOAD_FACT_MISSING"
PAYLOAD_INCONSISTENT = "PAYLOAD_INCONSISTENT"
PROVIDER_MISMATCH = "PROVIDER_MISMATCH"
WAIT_NOT_HELD = "WAIT_NOT_HELD"
OBSERVED_AT_INVALID = "OBSERVED_AT_INVALID"
OBSERVED_AT_FORBIDDEN = "OBSERVED_AT_FORBIDDEN"
RECORD_REASONS = (
    RECORD_NOT_TYPED, EVIDENCE_ID_INVALID, EVIDENCE_ID_SECRET_SHAPED, EVIDENCE_ID_DUPLICATE, PROVIDER_ID_INVALID,
    SOURCE_UNKNOWN, SOURCE_NOT_ADAPTABLE, PAYLOAD_NOT_TYPED, PAYLOAD_MALFORMED, PAYLOAD_UNEXPECTED_FIELD,
    PAYLOAD_FACT_MISSING, PAYLOAD_INCONSISTENT, PROVIDER_MISMATCH, WAIT_NOT_HELD, OBSERVED_AT_INVALID,
    OBSERVED_AT_FORBIDDEN,
)

# Evidence reason codes (the contract's and Router's own where they exist),
# grouped by what they force, in their fixed canonical order.
NO_EVIDENCE = qc.NO_EVIDENCE
EVIDENCE_REJECTED = "EVIDENCE_REJECTED"
FACT_MISSING = "FACT_MISSING"
EVIDENCE_STALE = qc.EVIDENCE_STALE
EVIDENCE_FROM_FUTURE = qc.EVIDENCE_FROM_FUTURE
EVIDENCE_CONTRADICTORY = qc.EVIDENCE_CONTRADICTORY
AVAILABILITY_UNKNOWN = qc.AVAILABILITY_UNKNOWN
CAPACITY_UNKNOWN = rt.CAPACITY_UNKNOWN
CONDITION_UNRESOLVED = "CONDITION_UNRESOLVED"
QUOTA_RECOVERY_UNCONFIRMED = "QUOTA_RECOVERY_UNCONFIRMED"
AVAILABILITY_AUTH_BLOCKED = rt.AVAILABILITY_AUTH_BLOCKED
AVAILABILITY_QUOTA_WAIT = rt.AVAILABILITY_QUOTA_WAIT
CAPACITY_FULL = rt.CAPACITY_FULL
# Evidence that forbids any positive (NONE / AVAILABLE) claim.
DOUBT_REASONS = (NO_EVIDENCE, EVIDENCE_REJECTED, FACT_MISSING, EVIDENCE_STALE, EVIDENCE_FROM_FUTURE,
                 EVIDENCE_CONTRADICTORY)
NOT_YET_KNOWN_REASONS = (AVAILABILITY_UNKNOWN, CAPACITY_UNKNOWN, CONDITION_UNRESOLVED, QUOTA_RECOVERY_UNCONFIRMED)
UNCERTAIN_REASONS = DOUBT_REASONS + NOT_YET_KNOWN_REASONS
HOLD_REASONS = (AVAILABILITY_AUTH_BLOCKED, AVAILABILITY_QUOTA_WAIT, CAPACITY_FULL)
EVIDENCE_REASONS = UNCERTAIN_REASONS + HOLD_REASONS
# Snapshot-level codes.
EVIDENCE_UNATTRIBUTED = "EVIDENCE_UNATTRIBUTED"
SNAPSHOT_REASONS = (NO_EVIDENCE, EVIDENCE_UNATTRIBUTED)

_AVAILABILITY_RANK = ("AUTH_BLOCKED", "QUOTA_WAIT", "UNKNOWN", "NONE")
_CAPACITY_RANK = ("FULL", "UNKNOWN", "AVAILABLE")
_HOLD_OF = {"AUTH_BLOCKED": AVAILABILITY_AUTH_BLOCKED, "QUOTA_WAIT": AVAILABILITY_QUOTA_WAIT}


def _ordered(codes, vocabulary) -> tuple:
    return sc._ordered(codes, vocabulary)


def _codes_ok(codes, vocabulary) -> bool:
    return (type(codes) is tuple and all(qc._in(c, vocabulary) for c in codes)
            and codes == _ordered(codes, vocabulary))


def _utc(value) -> Optional[str]:
    return None if value is None else sc._utc_text(qc.parse_utc(value))


def _normalized_utc(value) -> bool:
    return type(value) is str and qc.parse_utc(value) is not None and _utc(value) == value


def certainty_for(reasons: tuple) -> str:
    return UNCERTAIN if any(r in UNCERTAIN_REASONS for r in reasons) else CERTAIN


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SourceRecord:
    """One already-held structured fact. `payload` is the source's exact
    native type; `observed_at_utc` (UTC, zero offset) is required for sources
    that carry no instant of their own and forbidden otherwise."""
    evidence_id: str
    source: str
    provider_id: str
    payload: object
    observed_at_utc: Optional[str] = None


@dataclass(frozen=True)
class ObservationRequest:
    """Explicit, immutable adaptation request. `provider_ids` names providers
    that must be accounted for even without a record. Validated by
    `adapt_observations` (fail closed), not here."""
    request_id: str
    as_of_utc: str
    records: tuple = ()
    provider_ids: tuple = ()
    max_evidence_age_seconds: int = qc.DEFAULT_MAX_EVIDENCE_AGE_SECONDS
    schema_version: int = REQUEST_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _observation_dict(obs) -> Optional[dict]:
    if obs is None:
        return None
    return {
        "evidence_id": obs.evidence_id, "provider_id": obs.provider_id, "resource_id": obs.resource_id,
        "source": obs.source, "reliability": obs.reliability, "observed_at_utc": obs.observed_at_utc,
        "availability": obs.availability, "condition": obs.condition, "next_eligible_utc": obs.next_eligible_utc,
        "eligibility_source": obs.eligibility_source, "usage_unit": obs.usage_unit, "usage_amount": obs.usage_amount,
    }


@dataclass(frozen=True)
class AdaptedRecord:
    """Outcome of one input record. ADAPTED carries exactly one valid
    contract observation and its evidence-quality reasons; REJECTED carries
    only its rejection codes (and its ids when they are valid)."""
    index: int
    status: str
    evidence_id: Optional[str]
    source: Optional[str]
    provider_id: Optional[str]
    reasons: tuple
    certainty: str
    freshness: Optional[str] = None
    age_seconds: Optional[int] = None
    capacity: Optional[str] = None
    proven_slots: Optional[int] = None
    observation: Optional[qc.QuotaObservation] = None

    def __post_init__(self):
        if not qc._bounded_int(self.index, 0, MAX_RECORDS - 1):
            raise ValueError("index must be 0..MAX_RECORDS-1")
        if not qc._in(self.status, RECORD_STATUSES):
            raise ValueError("unknown record status")
        if self.status == REJECTED:
            if not (_codes_ok(self.reasons, RECORD_REASONS) and self.reasons):
                raise ValueError("a rejected record carries ordered rejection codes")
            if (self.freshness, self.age_seconds, self.capacity, self.proven_slots, self.observation) != (None,) * 5:
                raise ValueError("a rejected record adapts nothing")
            if self.evidence_id is not None and not qc._valid_id(self.evidence_id):
                raise ValueError("evidence_id must be None or a valid id")
            if self.provider_id is not None and not sc._valid_provider_id(self.provider_id):
                raise ValueError("provider_id must be None or a valid provider id")
            if self.source is not None and not qc._in(self.source, qc.EVIDENCE_SOURCES):
                raise ValueError("source must be None or a contract source")
            if self.certainty != UNCERTAIN:
                raise ValueError("a rejected record is never certain")
            return
        obs = self.observation
        if type(obs) is not qc.QuotaObservation or qc._observation_reasons(obs):
            raise ValueError("an adapted record carries one valid contract observation")
        if (obs.evidence_id, obs.provider_id, obs.source) != (self.evidence_id, self.provider_id, self.source):
            raise ValueError("record ids must be the observation's own")
        if self.source not in ADAPTABLE_SOURCES or obs.reliability != qc.SOURCE_MAX_RELIABILITY[obs.source]:
            raise ValueError("an adapted observation claims exactly its source's reliability")
        if obs.resource_id is not None or obs.usage_unit is not None or obs.usage_amount is not None:
            raise ValueError("no source here observes resources or usage")
        if not _normalized_utc(obs.observed_at_utc) or (
                obs.next_eligible_utc is not None and not _normalized_utc(obs.next_eligible_utc)):
            raise ValueError("instants must be normalized UTC")
        if not (_codes_ok(self.reasons, UNCERTAIN_REASONS) and NO_EVIDENCE not in self.reasons
                and EVIDENCE_REJECTED not in self.reasons):
            raise ValueError("an adapted record carries ordered evidence-quality reasons")
        if not qc._in(self.freshness, FRESHNESS):
            raise ValueError("unknown freshness")
        if (self.freshness == FRESH) == (EVIDENCE_STALE in self.reasons or EVIDENCE_FROM_FUTURE in self.reasons) \
                or (self.freshness == STALE) != (EVIDENCE_STALE in self.reasons) \
                or (self.freshness == FROM_FUTURE) != (EVIDENCE_FROM_FUTURE in self.reasons):
            raise ValueError("freshness must match the freshness reasons")
        if self.freshness == FROM_FUTURE:
            if self.age_seconds is not None:
                raise ValueError("future evidence has no age")
        elif not qc._bounded_int(self.age_seconds, 0, MAX_AGE_SECONDS):
            raise ValueError("age_seconds must be a non-negative int")
        if (obs.availability == "UNKNOWN") != (AVAILABILITY_UNKNOWN in self.reasons):
            raise ValueError("AVAILABILITY_UNKNOWN exactly when the observation is UNKNOWN")
        if self.capacity is not None and not qc._in(self.capacity, CAPACITY_STATES):
            raise ValueError("unknown capacity")
        if self.proven_slots is not None and not qc._bounded_int(self.proven_slots, 0, cap.MAX_PROVEN_SLOTS):
            raise ValueError("proven_slots must be None or 0..MAX_PROVEN_SLOTS")
        if self.certainty != certainty_for(self.reasons):
            raise ValueError("certainty must be exactly the one derived from reasons")

    def to_dict(self) -> dict:
        return {
            "index": self.index, "status": self.status, "evidence_id": self.evidence_id, "source": self.source,
            "provider_id": self.provider_id, "reasons": list(self.reasons), "certainty": self.certainty,
            "freshness": self.freshness, "age_seconds": self.age_seconds, "capacity": self.capacity,
            "proven_slots": self.proven_slots, "observation": _observation_dict(self.observation),
        }


@dataclass(frozen=True)
class ProviderQuotaView:
    """What a provider's evidence supports, most restrictive first. A hold is
    never dropped; NONE / AVAILABLE only without any doubt."""
    provider_id: str
    availability: str
    capacity: str
    certainty: str
    reasons: tuple
    evidence_ids: tuple
    conditions: tuple = ()
    proven_slots: Optional[int] = None
    next_eligible_utc: Optional[str] = None
    eligibility_source: Optional[str] = None
    freshness: Optional[str] = None

    def __post_init__(self):
        if not sc._valid_provider_id(self.provider_id):
            raise ValueError("provider_id must be a valid provider id")
        if not (qc._in(self.availability, AVAILABILITY_STATES) and qc._in(self.capacity, CAPACITY_STATES)):
            raise ValueError("availability / capacity must use the Router vocabulary")
        if not _codes_ok(self.reasons, EVIDENCE_REASONS):
            raise ValueError("reasons must be ordered evidence reason codes")
        if self.certainty != certainty_for(self.reasons):
            raise ValueError("certainty must be exactly the one derived from reasons")
        doubt = any(r in DOUBT_REASONS for r in self.reasons)
        if doubt and (self.availability == "NONE" or self.capacity == "AVAILABLE"):
            raise ValueError("a positive claim needs undoubted evidence")
        holds = {r for r in self.reasons if r in HOLD_REASONS}
        expected = {_HOLD_OF[self.availability]} if self.availability in _HOLD_OF else set()
        if self.capacity == "FULL":
            expected.add(CAPACITY_FULL)
        if holds != expected:
            raise ValueError("hold reasons must be exactly the reported holds")
        if (self.availability == "UNKNOWN") != (AVAILABILITY_UNKNOWN in self.reasons) \
                or (self.capacity == "UNKNOWN") != (CAPACITY_UNKNOWN in self.reasons):
            raise ValueError("UNKNOWN states carry their own reason")
        if not (type(self.evidence_ids) is tuple and all(qc._valid_id(e) for e in self.evidence_ids)
                and list(self.evidence_ids) == sorted(set(self.evidence_ids))):
            raise ValueError("evidence_ids must be sorted unique ids")
        if NO_EVIDENCE in self.reasons and self.evidence_ids:
            raise ValueError("NO_EVIDENCE cites nothing")
        if not (type(self.conditions) is tuple and all(qc._in(c, qc.CONDITIONS) for c in self.conditions)
                and list(self.conditions) == sorted(set(self.conditions))):
            raise ValueError("conditions must be sorted unique Runner conditions")
        if self.proven_slots is not None and not qc._bounded_int(self.proven_slots, 0, cap.MAX_PROVEN_SLOTS):
            raise ValueError("proven_slots must be None or 0..MAX_PROVEN_SLOTS")
        if self.next_eligible_utc is None:
            if self.eligibility_source is not None:
                raise ValueError("eligibility_source only with next_eligible_utc")
        elif (self.availability != "QUOTA_WAIT" or not _normalized_utc(self.next_eligible_utc)
              or not qc._in(self.eligibility_source, qc.ELIGIBILITY_SOURCES)):
            raise ValueError("only a Runner quota wait carries a normalized eligibility instant")
        if self.freshness is not None and not qc._in(self.freshness, FRESHNESS):
            raise ValueError("unknown freshness")

    def to_dict(self) -> dict:
        return {
            "provider_id": self.provider_id, "availability": self.availability, "capacity": self.capacity,
            "certainty": self.certainty, "reasons": list(self.reasons), "evidence_ids": list(self.evidence_ids),
            "conditions": list(self.conditions), "proven_slots": self.proven_slots,
            "next_eligible_utc": self.next_eligible_utc, "eligibility_source": self.eligibility_source,
            "freshness": self.freshness,
        }


def outcome_for(request_reasons: tuple, snapshot_reasons: tuple, records: tuple, providers: tuple) -> str:
    """REFUSED > UNKNOWN > OBSERVED."""
    if request_reasons:
        return REFUSED
    if (snapshot_reasons or any(r.status == REJECTED for r in records)
            or any(p.certainty == UNCERTAIN for p in providers)):
        return UNKNOWN
    return OBSERVED


class _ObservationGuarantees(qc._QuotaGuarantees):
    @staticmethod
    def _guarantees() -> dict:
        guarantees = qc._QuotaGuarantees._guarantees()
        guarantees["marker"] = OBSERVATION_MARKER
        return guarantees


def _body(outcome, request_id, as_of_utc, max_evidence_age_seconds, request_reasons, snapshot_reasons, records,
          providers) -> dict:
    """The canonical snapshot without its fingerprint and fixed flags."""
    return {
        "schema": SCHEMA, "schema_version": SCHEMA_VERSION, "outcome": outcome, "request_id": request_id,
        "as_of_utc": as_of_utc, "max_evidence_age_seconds": max_evidence_age_seconds,
        "request_reasons": list(request_reasons), "snapshot_reasons": list(snapshot_reasons),
        "records": [r.to_dict() for r in records], "providers": [p.to_dict() for p in providers],
    }


def _fingerprint(body: dict) -> str:
    return hashlib.sha256(sc._canonical(body).encode("ascii")).hexdigest()


@dataclass(frozen=True)
class QuotaObservationSnapshot(_ObservationGuarantees):
    """Adapted evidence. Construction re-derives the outcome, every
    provider view from the records, and the fingerprint, so a hand-made
    snapshot cannot claim more than its evidence."""
    outcome: str
    request_id: Optional[str]
    as_of_utc: Optional[str]
    max_evidence_age_seconds: Optional[int]
    snapshot_fingerprint: Optional[str]
    request_reasons: tuple
    snapshot_reasons: tuple
    records: tuple
    providers: tuple

    def __post_init__(self):
        if not qc._in(self.outcome, OUTCOMES):
            raise ValueError("unknown outcome")
        if not _codes_ok(self.request_reasons, REQUEST_REASONS):
            raise ValueError("request_reasons must be ordered request reason codes")
        if self.request_reasons:
            if (self.outcome != REFUSED or self.snapshot_reasons or self.records or self.providers
                    or (self.request_id, self.as_of_utc, self.max_evidence_age_seconds,
                        self.snapshot_fingerprint) != (None,) * 4):
                raise ValueError("a refused request echoes nothing and adapts nothing")
            return
        if not qc._valid_id(self.request_id) or not _normalized_utc(self.as_of_utc):
            raise ValueError("request_id and as_of_utc must be validated")
        if not qc._bounded_int(self.max_evidence_age_seconds, 1, qc.MAX_EVIDENCE_AGE_SECONDS):
            raise ValueError("max_evidence_age_seconds out of bounds")
        if not _codes_ok(self.snapshot_reasons, SNAPSHOT_REASONS):
            raise ValueError("snapshot_reasons must be ordered snapshot codes")
        if not (type(self.records) is tuple and len(self.records) <= MAX_RECORDS
                and all(type(r) is AdaptedRecord for r in self.records)
                and [r.index for r in self.records] == list(range(len(self.records)))):
            raise ValueError("records must be AdaptedRecords indexed 0..n-1")
        if not (type(self.providers) is tuple and len(self.providers) <= MAX_PROVIDERS
                and all(type(p) is ProviderQuotaView for p in self.providers)):
            raise ValueError("providers must be ProviderQuotaViews")
        ids = [p.provider_id for p in self.providers]
        if ids != sorted(set(ids)):
            raise ValueError("providers must be sorted and unique")
        adapted_ids = [r.evidence_id for r in self.records if r.status == ADAPTED]
        if len(adapted_ids) != len(set(adapted_ids)):
            raise ValueError("adapted evidence ids must be unique")
        if any(r.provider_id is not None and r.provider_id not in ids for r in self.records):
            raise ValueError("every attributed record needs its provider view")
        expected = _aggregate(self.records, ids)
        if (self.snapshot_reasons, self.providers) != expected:
            raise ValueError("providers and snapshot reasons must be the ones derived from records")
        if self.outcome != outcome_for(self.request_reasons, self.snapshot_reasons, self.records, self.providers):
            raise ValueError("outcome must be exactly the one derived from the evidence")
        body = self._body()
        if self.snapshot_fingerprint != _fingerprint(body):
            raise ValueError("snapshot_fingerprint must be the sha256 of the canonical snapshot")
        if len(sc._canonical(body)) > MAX_CANONICAL_JSON_BYTES:
            raise ValueError("snapshot exceeds MAX_CANONICAL_JSON_BYTES")

    @property
    def observations(self) -> tuple:
        """The adapted FCP-10A-01 observations, sorted by evidence id, ready
        to be cited by a `QuotaRequest`. Informational evidence only."""
        return tuple(sorted((r.observation for r in self.records if r.status == ADAPTED),
                            key=lambda o: o.evidence_id))

    def provider_view(self, provider_id: str) -> Optional[ProviderQuotaView]:
        for view in self.providers:
            if view.provider_id == provider_id:
                return view
        return None

    def _body(self) -> dict:
        return _body(self.outcome, self.request_id, self.as_of_utc, self.max_evidence_age_seconds,
                     self.request_reasons, self.snapshot_reasons, self.records, self.providers)

    def to_dict(self) -> dict:
        return {**self._body(), "snapshot_fingerprint": self.snapshot_fingerprint,
                **_ObservationGuarantees._guarantees()}


def canonical_json(snapshot: QuotaObservationSnapshot) -> str:
    """Stable, sorted, compact, size-bounded serialization of the exact
    snapshot type (a subclass cannot substitute `to_dict`)."""
    if type(snapshot) is not QuotaObservationSnapshot:
        raise TypeError("canonical_json accepts only a QuotaObservationSnapshot")
    text = sc._canonical(QuotaObservationSnapshot.to_dict(snapshot))
    if len(text) > MAX_CANONICAL_JSON_BYTES:
        raise ValueError("canonical snapshot exceeds MAX_CANONICAL_JSON_BYTES")
    return text


def _refused(reasons) -> QuotaObservationSnapshot:
    return QuotaObservationSnapshot(
        outcome=REFUSED, request_id=None, as_of_utc=None, max_evidence_age_seconds=None, snapshot_fingerprint=None,
        request_reasons=_ordered(reasons, REQUEST_REASONS), snapshot_reasons=(), records=(), providers=(),
    )


# ---------------------------------------------------------------------------
# Per-source adaptation (each returns (rejections, fields))
# ---------------------------------------------------------------------------

def _fields(availability_state, observed, condition=None, next_eligible=None, eligibility=None, capacity=None,
            proven_slots=None, reasons=()) -> dict:
    return {"availability": availability_state, "observed": observed, "condition": condition,
            "next_eligible": next_eligible, "eligibility": eligibility, "capacity": capacity,
            "proven_slots": proven_slots, "reasons": set(reasons)}


def _adapt_runner_wait(worker, record, as_of) -> tuple:
    if not (type(worker.state) is str and type(worker.active_provider) is str):
        return {PAYLOAD_MALFORMED}, None
    if not sc._valid_provider_id(worker.active_provider):
        return {PAYLOAD_MALFORMED}, None
    rejections = set()
    if worker.active_provider != record.provider_id:
        rejections.add(PROVIDER_MISMATCH)
    held = _HOLD_STATE_CONDITION.get(worker.state)
    if held is None:
        return rejections | {WAIT_NOT_HELD}, None
    wait = worker.provider_wait
    if type(wait) is not dict:
        return rejections | {PAYLOAD_FACT_MISSING}, None
    if not all(type(k) is str for k in wait) or set(wait) - RUNNER_WAIT_FIELDS:
        return rejections | {PAYLOAD_UNEXPECTED_FIELD}, None
    if any(wait.get(k) is None for k in _WAIT_REQUIRED_FIELDS):
        return rejections | {PAYLOAD_FACT_MISSING}, None
    condition, eligibility = wait["condition"], wait.get("eligibility_source")
    since, last_hit = qc.parse_utc(wait["since_utc"]), qc.parse_utc(wait["last_hit_utc"])
    next_raw = wait.get("next_eligible_utc")
    next_eligible = None if next_raw is None else qc.parse_utc(next_raw)
    streak = wait.get("consecutive_quota_waits", 0)
    if (not qc._in(condition, qc.CONDITIONS) or since is None or last_hit is None
            or (next_raw is not None and next_eligible is None)
            or not (eligibility is None or qc._in(eligibility, qc.ELIGIBILITY_SOURCES))
            or not qc._bounded_int(streak, 0, 1_000_000)):
        return rejections | {PAYLOAD_MALFORMED}, None
    if since > last_hit or (next_eligible is not None and next_eligible < last_hit):
        rejections.add(PAYLOAD_INCONSISTENT)
    if rejections:
        return rejections, None
    observed = sc._utc_text(last_hit)
    if condition != held or (held == _AUTH and (next_raw is not None or eligibility is not None)):
        return set(), _fields("UNKNOWN", observed, condition=condition, reasons={EVIDENCE_CONTRADICTORY})
    if held == _AUTH:
        return set(), _fields("AUTH_BLOCKED", observed, condition=condition)
    if next_eligible is None or eligibility is None:
        return set(), _fields("QUOTA_WAIT", observed, condition=condition, reasons={FACT_MISSING})
    reasons = {QUOTA_RECOVERY_UNCONFIRMED} if next_eligible <= as_of else set()
    return set(), _fields("QUOTA_WAIT", observed, condition=condition, next_eligible=sc._utc_text(next_eligible),
                          eligibility=eligibility, reasons=reasons)


def _adapt_classification(classification, record, as_of) -> tuple:
    member = classification.condition
    if type(member) is not availability.ProviderCondition:
        return {PAYLOAD_MALFORMED}, None
    observed = _utc(record.observed_at_utc)
    held = qc.CONDITION_AVAILABILITY[member.value]
    if held is None:
        return set(), _fields("UNKNOWN", observed, condition=member.value, reasons={CONDITION_UNRESOLVED})
    return set(), _fields(held, observed, condition=member.value)


def _adapt_router_facts(facts, record, as_of) -> tuple:
    if not (sc._valid_provider_id(facts.provider_id) and rt._facts_well_formed(facts)):
        return {PAYLOAD_MALFORMED}, None
    if facts.provider_id != record.provider_id:
        return {PROVIDER_MISMATCH}, None
    return set(), _fields(facts.availability, _utc(record.observed_at_utc), capacity=facts.capacity)


def _adapt_capacity_facts(facts, record, as_of) -> tuple:
    if cap._facts_reasons((facts,)):
        return {PAYLOAD_MALFORMED}, None
    rejections = set()
    if facts.provider_id != record.provider_id:
        rejections.add(PROVIDER_MISMATCH)
    if qc.parse_utc(facts.observed_at_utc) is None:
        rejections.add(OBSERVED_AT_INVALID)
    if rejections:
        return rejections, None
    state, capacity, reasons = facts.availability, facts.capacity, set()
    if facts.last_condition is not None and state != "UNKNOWN":
        held_as = state if state in _HOLD_OF else None
        if qc.CONDITION_AVAILABILITY[facts.last_condition] != held_as:
            state = "UNKNOWN"
            reasons.add(EVIDENCE_CONTRADICTORY)
    if capacity == "AVAILABLE" and facts.proven_slots == 0:
        capacity = "UNKNOWN"
        reasons.add(EVIDENCE_CONTRADICTORY)
    return set(), _fields(state, _utc(facts.observed_at_utc), condition=facts.last_condition, capacity=capacity,
                          proven_slots=facts.proven_slots, reasons=reasons)


_ADAPTERS = {
    qc.SOURCE_RUNNER_PROVIDER_WAIT: _adapt_runner_wait,
    qc.SOURCE_RUNNER_PROVIDER_CONDITION: _adapt_classification,
    qc.SOURCE_ROUTER_PROVIDER_FACTS: _adapt_router_facts,
    qc.SOURCE_SCHEDULER_CAPACITY_FACTS: _adapt_capacity_facts,
}


def _rejected(index, reasons, evidence_id, source, provider_id) -> AdaptedRecord:
    return AdaptedRecord(
        index=index, status=REJECTED, reasons=_ordered(reasons, RECORD_REASONS), certainty=UNCERTAIN,
        evidence_id=evidence_id if qc._valid_id(evidence_id) and not qc._secret_shaped(evidence_id) else None,
        source=source if qc._in(source, qc.EVIDENCE_SOURCES) else None,
        provider_id=provider_id if sc._valid_provider_id(provider_id) and not qc._secret_shaped(provider_id) else None,
    )


def _adapt_record(index: int, record, as_of, max_age: int, duplicates: set) -> AdaptedRecord:
    if type(record) is not SourceRecord:
        return _rejected(index, {RECORD_NOT_TYPED}, None, None, None)
    reasons = set()
    if not qc._valid_id(record.evidence_id):
        reasons.add(EVIDENCE_ID_INVALID)
    elif qc._secret_shaped(record.evidence_id):
        reasons.add(EVIDENCE_ID_SECRET_SHAPED)
    elif record.evidence_id in duplicates:
        reasons.add(EVIDENCE_ID_DUPLICATE)
    if not sc._valid_provider_id(record.provider_id) or qc._secret_shaped(record.provider_id):
        reasons.add(PROVIDER_ID_INVALID)
    source = record.source
    if not qc._in(source, qc.EVIDENCE_SOURCES):
        reasons.add(SOURCE_UNKNOWN)
    elif source not in _SOURCE_PAYLOAD:
        reasons.add(SOURCE_NOT_ADAPTABLE)
    else:
        if type(record.payload) is not _SOURCE_PAYLOAD[source]:
            reasons.add(PAYLOAD_NOT_TYPED)
        if source in _SELF_TIMED_SOURCES:
            if record.observed_at_utc is not None:
                reasons.add(OBSERVED_AT_FORBIDDEN)
        elif qc.parse_utc(record.observed_at_utc) is None:
            reasons.add(OBSERVED_AT_INVALID)
    if reasons:
        return _rejected(index, reasons, record.evidence_id, source, record.provider_id)
    rejections, fields = _ADAPTERS[source](record.payload, record, as_of)
    if rejections:
        return _rejected(index, rejections, record.evidence_id, source, record.provider_id)
    obs = qc.QuotaObservation(
        evidence_id=record.evidence_id, provider_id=record.provider_id, source=source,
        reliability=qc.SOURCE_MAX_RELIABILITY[source], observed_at_utc=fields["observed"],
        availability=fields["availability"], condition=fields["condition"],
        next_eligible_utc=fields["next_eligible"], eligibility_source=fields["eligibility"],
    )
    if qc._observation_reasons(obs):
        return _rejected(index, {PAYLOAD_INCONSISTENT}, record.evidence_id, source, record.provider_id)
    evidence = fields["reasons"]
    if obs.availability == "UNKNOWN":
        evidence.add(AVAILABILITY_UNKNOWN)
    if fields["capacity"] == "UNKNOWN":
        evidence.add(CAPACITY_UNKNOWN)
    observed = qc.parse_utc(obs.observed_at_utc)
    age = None
    if observed > as_of:
        freshness = FROM_FUTURE
        evidence.add(EVIDENCE_FROM_FUTURE)
    else:
        age = int((as_of - observed).total_seconds())
        freshness = STALE if (as_of - observed).total_seconds() > max_age else FRESH
        if freshness == STALE:
            evidence.add(EVIDENCE_STALE)
    ordered = _ordered(evidence, UNCERTAIN_REASONS)
    return AdaptedRecord(
        index=index, status=ADAPTED, evidence_id=obs.evidence_id, source=source, provider_id=obs.provider_id,
        reasons=ordered, certainty=certainty_for(ordered), freshness=freshness, age_seconds=age,
        capacity=fields["capacity"], proven_slots=fields["proven_slots"], observation=obs,
    )


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def _most_restrictive(values, rank) -> str:
    return min(values, key=rank.index)


def _provider_view(provider: str, records: tuple, unattributed: bool) -> ProviderQuotaView:
    adapted = [r for r in records if r.status == ADAPTED and r.provider_id == provider]
    rejected = [r for r in records if r.status == REJECTED and r.provider_id == provider]
    reasons = set()
    if not adapted and not rejected:
        reasons.add(NO_EVIDENCE)
    if unattributed:
        reasons.add(EVIDENCE_REJECTED)
    for record in rejected:
        reasons.add(FACT_MISSING if PAYLOAD_FACT_MISSING in record.reasons else EVIDENCE_REJECTED)
    for record in adapted:
        reasons |= set(record.reasons) - {AVAILABILITY_UNKNOWN, CAPACITY_UNKNOWN}
    states = {r.observation.availability for r in adapted}
    capacities = {r.capacity for r in adapted if r.capacity is not None}
    if len(states - {"UNKNOWN"}) > 1 or {"AVAILABLE", "FULL"} <= capacities:
        reasons.add(EVIDENCE_CONTRADICTORY)
    state = _most_restrictive(states, _AVAILABILITY_RANK) if states else "UNKNOWN"
    capacity = _most_restrictive(capacities, _CAPACITY_RANK) if capacities else "UNKNOWN"
    doubt = any(r in DOUBT_REASONS for r in reasons)
    if doubt and state == "NONE":
        state = "UNKNOWN"
    if doubt and capacity == "AVAILABLE":
        capacity = "UNKNOWN"
    if state == "UNKNOWN":
        reasons.add(AVAILABILITY_UNKNOWN)
    elif state in _HOLD_OF:
        reasons.add(_HOLD_OF[state])
    if capacity == "UNKNOWN":
        reasons.add(CAPACITY_UNKNOWN)
    elif capacity == "FULL":
        reasons.add(CAPACITY_FULL)
    if state != "QUOTA_WAIT":
        reasons.discard(QUOTA_RECOVERY_UNCONFIRMED)
    next_eligible = eligibility = None
    waits = [r.observation for r in adapted if r.observation.next_eligible_utc is not None]
    if state == "QUOTA_WAIT" and waits:
        latest = max(waits, key=lambda o: (qc.parse_utc(o.next_eligible_utc), o.evidence_id))
        next_eligible, eligibility = latest.next_eligible_utc, latest.eligibility_source
    slots = [r.proven_slots for r in adapted if r.source == qc.SOURCE_SCHEDULER_CAPACITY_FACTS]
    freshness = _most_restrictive({r.freshness for r in adapted}, (FROM_FUTURE, STALE, FRESH)) if adapted else None
    ordered = _ordered(reasons, EVIDENCE_REASONS)
    return ProviderQuotaView(
        provider_id=provider, availability=state, capacity=capacity, certainty=certainty_for(ordered),
        reasons=ordered, evidence_ids=tuple(sorted({r.evidence_id for r in adapted + rejected if r.evidence_id})),
        conditions=tuple(sorted({r.observation.condition for r in adapted if r.observation.condition})),
        proven_slots=min(slots) if slots and None not in slots else None,
        next_eligible_utc=next_eligible, eligibility_source=eligibility, freshness=freshness,
    )


def _aggregate(records: tuple, provider_ids) -> tuple:
    """(snapshot_reasons, provider views) derived from the records only."""
    unattributed = any(r.status == REJECTED and r.provider_id is None for r in records)
    reasons = set()
    if not records and not provider_ids:
        reasons.add(NO_EVIDENCE)
    if unattributed:
        reasons.add(EVIDENCE_UNATTRIBUTED)
    views = tuple(_provider_view(p, records, unattributed) for p in sorted(set(provider_ids)))
    return _ordered(reasons, SNAPSHOT_REASONS), views


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _request_reasons(request) -> tuple:
    if type(request) is not ObservationRequest:
        return (REQUEST_NOT_TYPED,)
    reasons = set()
    if not (sc._is_int(request.schema_version) and request.schema_version == REQUEST_SCHEMA_VERSION):
        reasons.add(SCHEMA_VERSION_UNSUPPORTED)
    if not qc._valid_id(request.request_id):
        reasons.add(REQUEST_ID_INVALID)
    elif qc._secret_shaped(request.request_id):
        reasons.add(ID_SECRET_SHAPED)
    if qc.parse_utc(request.as_of_utc) is None:
        reasons.add(AS_OF_INVALID)
    if not qc._bounded_int(request.max_evidence_age_seconds, 1, qc.MAX_EVIDENCE_AGE_SECONDS):
        reasons.add(MAX_EVIDENCE_AGE_INVALID)
    records = request.records
    if not (type(records) is tuple and len(records) <= MAX_RECORDS):
        reasons.add(RECORDS_MALFORMED)
    ids = request.provider_ids
    if not (type(ids) is tuple and len(ids) <= MAX_PROVIDERS and len(set(ids)) == len(ids)
            and all(sc._valid_provider_id(p) and not qc._secret_shaped(p) for p in ids)):
        reasons.add(PROVIDER_IDS_MALFORMED)
    elif RECORDS_MALFORMED not in reasons:
        named = set(ids) | {r.provider_id for r in records
                            if type(r) is SourceRecord and sc._valid_provider_id(r.provider_id)}
        if len(named) > MAX_PROVIDERS:
            reasons.add(PROVIDERS_TOO_MANY)
    return _ordered(reasons, REQUEST_REASONS)


def adapt_observations(request: ObservationRequest) -> QuotaObservationSnapshot:
    """Pure, deterministic adaptation of already-held structured facts into
    FCP-10A-01 observations. Never raises on bad input and never mutates it:
    an invalid request is an explained REFUSED and every bad record an
    explained rejection. The result never authorizes dispatch, retry,
    resume, a provider switch, a purchase or a remote call."""
    reasons = _request_reasons(request)
    if reasons:
        return _refused(reasons)
    as_of = qc.parse_utc(request.as_of_utc)
    seen, duplicates = set(), set()
    for record in request.records:
        if type(record) is SourceRecord and type(record.evidence_id) is str:
            (duplicates if record.evidence_id in seen else seen).add(record.evidence_id)
    records = tuple(_adapt_record(i, r, as_of, request.max_evidence_age_seconds, duplicates)
                    for i, r in enumerate(request.records))
    provider_ids = set(request.provider_ids) | {r.provider_id for r in records if r.provider_id is not None}
    snapshot_reasons, providers = _aggregate(records, provider_ids)
    fields = dict(
        outcome=outcome_for((), snapshot_reasons, records, providers), request_id=request.request_id,
        as_of_utc=sc._utc_text(as_of), max_evidence_age_seconds=request.max_evidence_age_seconds,
        request_reasons=(), snapshot_reasons=snapshot_reasons, records=records, providers=providers,
    )
    body = _body(**fields)
    if len(sc._canonical(body)) > MAX_CANONICAL_JSON_BYTES:
        return _refused((REQUEST_TOO_LARGE,))
    return QuotaObservationSnapshot(snapshot_fingerprint=_fingerprint(body), **fields)
