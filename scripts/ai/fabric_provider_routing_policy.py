"""FCP-7A-01: Provider Routing Policy V1 - pure, deterministic, fail-closed,
NON-EXECUTABLE provider selection PROPOSAL for a new, not-yet-executed Work
Order.

Answers ONE question: given an explicit, immutable `RoutingRequest` and a
caller-supplied snapshot of `ProviderFacts`, which single provider (if any)
would the caller's own preference order point at, and why was every other
provider excluded? It never answers "may I dispatch now?".

Why this is a proposal, not a dispatcher
----------------------------------------
* The Provider Registry and the Runner (`runner_providers` preflight,
  `runner_pipeline` provider lock, quota/auth holds, `provider_limits`,
  fallback and worktree ownership) stay the ONLY authorities on actual
  availability, capability, shell permission, quota, authorization, locking,
  ownership, execution and fallback - at execution time. Nothing here
  probes a CLI, imports the registry, schedules, retries, falls back, runs a
  process or shell, touches Git, the filesystem or the network: stdlib only,
  no I/O, no mutable global state.
* `ProviderFacts` are caller-supplied OBSERVATIONS, not authenticated
  evidence. They are only ever used to EXCLUDE a provider; they can never
  widen what the request asked for, and nothing here invents a capability a
  fact did not attest.
* No cost, latency, quality or model score exists anywhere in the inputs or
  the output. The caller's explicit `preference_order` is the ONLY ranking.

Request (`RoutingRequest`, frozen; validated by `propose_route`, never by the
constructor, so every malformed request yields an explained refusal)
------------------------------------------------------------------------------
``RoutingRequest(mode, allow_shell=False, required_capabilities=(),
preference_order=(), pinned_provider=None, prior_attempt_executed=False,
provider_locked=False)``

* `mode`: exactly `"read-only"` or `"write"` (Runner `MODE_*`).
* `allow_shell`: a real bool, never inferred. True in read-only mode is
  refused (`ALLOW_SHELL_REQUIRES_WRITE_MODE`, the Runner manifest guard).
  Requesting `SHELL` without `allow_shell=True` is refused.
* `required_capabilities`: tuple of exact Runner `Capability` names that the
  Work Order explicitly requests. `READ_FILES`/`SEARCH_FILES` are always
  required and `EDIT_FILES`/`WRITE_FILES` in write mode, exactly as
  `runner_providers.required_capabilities`; unknown or duplicate names are
  refused (never silently dropped).
* `preference_order`: tuple of unique, bounded provider ids, highest
  preference first. Required unless `pinned_provider` is given.
* `pinned_provider`: hard pin - only that provider may be proposed, never a
  silent substitute. When `preference_order` is also given it must contain
  the pin.
* `prior_attempt_executed` / `provider_locked`: when either is True the
  provider owning the Work Order is fixed; it MUST be given as
  `pinned_provider` (else refused) and no other provider is ever proposed.

Facts (`ProviderFacts`, frozen; one per provider, a tuple snapshot)
--------------------------------------------------------------------
``ProviderFacts(provider_id, probe_available, policy_mode,
policy_allow_shell, policy_supported, capabilities, availability,
capacity)``

* `policy_mode`/`policy_allow_shell`: the EXACT `ExecutionPolicy` the
  capability observation was made under; it must equal the request's.
* `policy_supported`: the adapter's `policy_refusal(policy) is None`.
* `capabilities`: native Capability names under that exact policy.
* `availability`: `NONE`, `QUOTA_WAIT`, `AUTH_BLOCKED` or `UNKNOWN`.
* `capacity`: `AVAILABLE`, `FULL` or `UNKNOWN`.

Selection rule
--------------
Every provider named by the request or the snapshot is assessed and every
applicable exclusion code is recorded. A provider is eligible only with no
exclusion code at all. The proposal is the eligible provider with the
lowest index in the caller's order (the pin when pinned); since the order
holds unique ids no tie can occur, and the documented tie-break would be
the lexicographic provider id. No eligible provider -> no candidate.

Output (`RoutingAdvisory`, schema `fcp7a01-provider-routing-advisory-v1`,
version 1). `to_dict()` / `canonical_json()` are deterministic. Every
advisory fixes `certified`, `authorizes_action`, `execution_allowed`,
`auto_retry_allowed`, `resume_allowed`, `merging_allowed` and
`provider_switch_authorized` to False as read-only properties (not dataclass
fields: no constructor, `dataclasses.replace` or serialized input can set
them). A `selected_provider` is informational only.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Optional

SCHEMA = "fcp7a01-provider-routing-advisory-v1"
SCHEMA_VERSION = 1
ROUTING_MARKER = "FCP7A01_ROUTING_PROPOSAL_ONLY_NOT_CERTIFIED_NOT_AUTHORIZED"

# Mirrors runner_providers.MODE_* and Capability (pinned by tests; not
# imported, so the policy never loads the registry or a provider adapter).
MODE_READ_ONLY = "read-only"
MODE_WRITE = "write"
MODES = (MODE_READ_ONLY, MODE_WRITE)
CAPABILITIES = (
    "READ_FILES", "SEARCH_FILES", "EDIT_FILES", "WRITE_FILES", "SHELL", "TEST_EXECUTION", "STRUCTURED_RESULT",
)
BASE_CAPABILITIES = frozenset({"READ_FILES", "SEARCH_FILES"})
WRITE_MODE_CAPABILITIES = frozenset({"EDIT_FILES", "WRITE_FILES"})
_CAPABILITY_SET = frozenset(CAPABILITIES)

AVAILABILITY_STATES = ("NONE", "QUOTA_WAIT", "AUTH_BLOCKED", "UNKNOWN")
CAPACITY_STATES = ("AVAILABLE", "FULL", "UNKNOWN")

# Adapters whose native CLI always grants shell, so the native adapter
# refuses any policy without allow_shell (CodexProvider.policy_refusal).
# Only ever used to EXCLUDE, whatever the caller's facts claim.
SHELL_MANDATORY_PROVIDERS = frozenset({"codex"})

MAX_PROVIDERS = 16
_PROVIDER_ID_RE = re.compile(r"[a-z][a-z0-9-]{0,31}")

# Request-level refusal codes.
REQUEST_NOT_TYPED = "REQUEST_NOT_TYPED"
MODE_UNKNOWN = "MODE_UNKNOWN"
ALLOW_SHELL_NOT_BOOL = "ALLOW_SHELL_NOT_BOOL"
ALLOW_SHELL_REQUIRES_WRITE_MODE = "ALLOW_SHELL_REQUIRES_WRITE_MODE"
CAPABILITIES_MALFORMED = "CAPABILITIES_MALFORMED"
CAPABILITY_UNKNOWN = "CAPABILITY_UNKNOWN"
CAPABILITY_DUPLICATE = "CAPABILITY_DUPLICATE"
SHELL_REQUESTED_WITHOUT_ALLOW_SHELL = "SHELL_REQUESTED_WITHOUT_ALLOW_SHELL"
PREFERENCE_MALFORMED = "PREFERENCE_MALFORMED"
PREFERENCE_EMPTY = "PREFERENCE_EMPTY"
PREFERENCE_TOO_LONG = "PREFERENCE_TOO_LONG"
PREFERENCE_DUPLICATE = "PREFERENCE_DUPLICATE"
PREFERENCE_PROVIDER_ID_INVALID = "PREFERENCE_PROVIDER_ID_INVALID"
PIN_INVALID = "PIN_INVALID"
PIN_NOT_IN_PREFERENCE = "PIN_NOT_IN_PREFERENCE"
LOCK_FLAGS_MALFORMED = "LOCK_FLAGS_MALFORMED"
LOCKED_WITHOUT_PIN = "LOCKED_WITHOUT_PIN"
REQUEST_REASONS = (
    REQUEST_NOT_TYPED, MODE_UNKNOWN, ALLOW_SHELL_NOT_BOOL, ALLOW_SHELL_REQUIRES_WRITE_MODE, CAPABILITIES_MALFORMED,
    CAPABILITY_UNKNOWN, CAPABILITY_DUPLICATE, SHELL_REQUESTED_WITHOUT_ALLOW_SHELL, PREFERENCE_MALFORMED,
    PREFERENCE_EMPTY, PREFERENCE_TOO_LONG, PREFERENCE_DUPLICATE, PREFERENCE_PROVIDER_ID_INVALID, PIN_INVALID,
    PIN_NOT_IN_PREFERENCE, LOCK_FLAGS_MALFORMED, LOCKED_WITHOUT_PIN,
)

# Snapshot-level refusal codes.
SNAPSHOT_NOT_TUPLE = "SNAPSHOT_NOT_TUPLE"
SNAPSHOT_TOO_LARGE = "SNAPSHOT_TOO_LARGE"
SNAPSHOT_ENTRY_NOT_TYPED = "SNAPSHOT_ENTRY_NOT_TYPED"
SNAPSHOT_PROVIDER_ID_INVALID = "SNAPSHOT_PROVIDER_ID_INVALID"
SNAPSHOT_REASONS = (SNAPSHOT_NOT_TUPLE, SNAPSHOT_TOO_LARGE, SNAPSHOT_ENTRY_NOT_TYPED, SNAPSHOT_PROVIDER_ID_INVALID)

# Per-provider exclusion codes.
NOT_PINNED = "NOT_PINNED"
PROVIDER_LOCKED_TO_OTHER = "PROVIDER_LOCKED_TO_OTHER"
NOT_IN_PREFERENCE_ORDER = "NOT_IN_PREFERENCE_ORDER"
NO_FACTS = "NO_FACTS"
DUPLICATE_FACTS = "DUPLICATE_FACTS"
FACTS_MALFORMED = "FACTS_MALFORMED"
FACTS_UNKNOWN_CAPABILITY = "FACTS_UNKNOWN_CAPABILITY"
FACTS_POLICY_MISMATCH = "FACTS_POLICY_MISMATCH"
FACTS_INCONSISTENT = "FACTS_INCONSISTENT"
PROBE_UNAVAILABLE = "PROBE_UNAVAILABLE"
POLICY_REFUSED = "POLICY_REFUSED"
ADAPTER_REQUIRES_SHELL = "ADAPTER_REQUIRES_SHELL"
CAPABILITY_MISSING = "CAPABILITY_MISSING"
AVAILABILITY_QUOTA_WAIT = "AVAILABILITY_QUOTA_WAIT"
AVAILABILITY_AUTH_BLOCKED = "AVAILABILITY_AUTH_BLOCKED"
AVAILABILITY_UNKNOWN = "AVAILABILITY_UNKNOWN"
CAPACITY_FULL = "CAPACITY_FULL"
CAPACITY_UNKNOWN = "CAPACITY_UNKNOWN"
PROVIDER_REASONS = (
    NOT_PINNED, PROVIDER_LOCKED_TO_OTHER, NOT_IN_PREFERENCE_ORDER, NO_FACTS, DUPLICATE_FACTS, FACTS_MALFORMED,
    FACTS_UNKNOWN_CAPABILITY, FACTS_POLICY_MISMATCH, FACTS_INCONSISTENT, PROBE_UNAVAILABLE, POLICY_REFUSED,
    ADAPTER_REQUIRES_SHELL, CAPABILITY_MISSING, AVAILABILITY_QUOTA_WAIT, AVAILABILITY_AUTH_BLOCKED,
    AVAILABILITY_UNKNOWN, CAPACITY_FULL, CAPACITY_UNKNOWN,
)
_AVAILABILITY_REASON = {
    "QUOTA_WAIT": AVAILABILITY_QUOTA_WAIT, "AUTH_BLOCKED": AVAILABILITY_AUTH_BLOCKED,
    "UNKNOWN": AVAILABILITY_UNKNOWN,
}
_CAPACITY_REASON = {"FULL": CAPACITY_FULL, "UNKNOWN": CAPACITY_UNKNOWN}

# Rationale enum.
SELECTED_FIRST_ELIGIBLE_PREFERENCE = "SELECTED_FIRST_ELIGIBLE_PREFERENCE"
SELECTED_PINNED_PROVIDER = "SELECTED_PINNED_PROVIDER"
SELECTED_LOCKED_PROVIDER = "SELECTED_LOCKED_PROVIDER"
REFUSED_INVALID_REQUEST = "REFUSED_INVALID_REQUEST"
REFUSED_INVALID_SNAPSHOT = "REFUSED_INVALID_SNAPSHOT"
REFUSED_PINNED_PROVIDER_INELIGIBLE = "REFUSED_PINNED_PROVIDER_INELIGIBLE"
REFUSED_LOCKED_PROVIDER_INELIGIBLE = "REFUSED_LOCKED_PROVIDER_INELIGIBLE"
REFUSED_NO_ELIGIBLE_PROVIDER = "REFUSED_NO_ELIGIBLE_PROVIDER"
SELECTED_RATIONALES = (SELECTED_FIRST_ELIGIBLE_PREFERENCE, SELECTED_PINNED_PROVIDER, SELECTED_LOCKED_PROVIDER)
REFUSED_RATIONALES = (
    REFUSED_INVALID_REQUEST, REFUSED_INVALID_SNAPSHOT, REFUSED_PINNED_PROVIDER_INELIGIBLE,
    REFUSED_LOCKED_PROVIDER_INELIGIBLE, REFUSED_NO_ELIGIBLE_PROVIDER,
)
RATIONALES = SELECTED_RATIONALES + REFUSED_RATIONALES


def _is_bool(value) -> bool:
    return type(value) is bool


def _valid_provider_id(value) -> bool:
    return type(value) is str and _PROVIDER_ID_RE.fullmatch(value) is not None


def _str_tuple(value) -> bool:
    return type(value) is tuple and all(type(v) is str for v in value)


def _ordered(codes, vocabulary) -> tuple:
    return tuple(sorted(set(codes), key=vocabulary.index))


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RoutingRequest:
    """Explicit, immutable routing request for one not-yet-executed Work
    Order. Validated by `propose_route` (fail closed), not here."""
    mode: str
    allow_shell: bool = False
    required_capabilities: tuple = ()
    preference_order: tuple = ()
    pinned_provider: Optional[str] = None
    prior_attempt_executed: bool = False
    provider_locked: bool = False


@dataclass(frozen=True)
class ProviderFacts:
    """Caller-supplied observation of one provider under one exact
    ExecutionPolicy. Not authenticated evidence; only ever excludes."""
    provider_id: str
    probe_available: bool
    policy_mode: str
    policy_allow_shell: bool
    policy_supported: bool
    capabilities: tuple
    availability: str
    capacity: str


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProviderAssessment:
    """Compact, bounded per-provider verdict: eligible iff no reason."""
    provider_id: str
    preference_rank: Optional[int]
    eligible: bool
    reasons: tuple
    missing_capabilities: tuple

    def __post_init__(self):
        if not _valid_provider_id(self.provider_id):
            raise ValueError("assessment provider_id must be a bounded provider id")
        if not (isinstance(self.reasons, tuple) and all(r in PROVIDER_REASONS for r in self.reasons)
                and self.reasons == _ordered(self.reasons, PROVIDER_REASONS)):
            raise ValueError("assessment reasons must be ordered provider reason codes")
        if not (isinstance(self.missing_capabilities, tuple)
                and all(c in _CAPABILITY_SET for c in self.missing_capabilities)
                and self.missing_capabilities == tuple(sorted(set(self.missing_capabilities)))):
            raise ValueError("assessment missing_capabilities must be sorted capability names")
        if self.eligible is not (not self.reasons):
            raise ValueError("a provider is eligible exactly when it has no exclusion reason")
        if self.preference_rank is not None and not (type(self.preference_rank) is int and self.preference_rank >= 0):
            raise ValueError("preference_rank must be a non-negative int or None")

    def to_dict(self) -> dict:
        return {
            "provider_id": self.provider_id, "preference_rank": self.preference_rank, "eligible": self.eligible,
            "reasons": list(self.reasons), "missing_capabilities": list(self.missing_capabilities),
        }


class _NotAuthorized:
    """Fixed, read-only zero-authority guarantees (not dataclass fields, so no
    constructor, `dataclasses.replace` or serialization input can set them)."""

    @property
    def certified(self) -> bool:
        return False

    @property
    def authorizes_action(self) -> bool:
        return False

    @property
    def execution_allowed(self) -> bool:
        return False

    @property
    def auto_retry_allowed(self) -> bool:
        return False

    @property
    def resume_allowed(self) -> bool:
        return False

    @property
    def merging_allowed(self) -> bool:
        return False

    @property
    def provider_switch_authorized(self) -> bool:
        return False

    @staticmethod
    def _guarantees() -> dict:
        return {
            "marker": ROUTING_MARKER, "certified": False, "authorizes_action": False, "execution_allowed": False,
            "auto_retry_allowed": False, "resume_allowed": False, "merging_allowed": False,
            "provider_switch_authorized": False,
        }


@dataclass(frozen=True)
class RoutingAdvisory(_NotAuthorized):
    """Informational routing proposal. Request echo fields hold only
    validated values (None/() when the request was refused)."""
    rationale: str
    selected_provider: Optional[str]
    mode: Optional[str]
    allow_shell: Optional[bool]
    pinned_provider: Optional[str]
    prior_attempt_executed: Optional[bool]
    provider_locked: Optional[bool]
    preference_order: tuple
    required_capabilities: tuple
    request_reasons: tuple
    snapshot_reasons: tuple
    assessments: tuple

    def __post_init__(self):
        # Construction-time guard: an advisory can only name a candidate that
        # its own assessments show eligible, under a SELECTED_* rationale.
        if self.rationale not in RATIONALES:
            raise ValueError("unknown routing rationale")
        if not (isinstance(self.request_reasons, tuple)
                and self.request_reasons == _ordered(self.request_reasons, REQUEST_REASONS)
                and all(r in REQUEST_REASONS for r in self.request_reasons)):
            raise ValueError("request_reasons must be ordered request reason codes")
        if not (isinstance(self.snapshot_reasons, tuple)
                and self.snapshot_reasons == _ordered(self.snapshot_reasons, SNAPSHOT_REASONS)
                and all(r in SNAPSHOT_REASONS for r in self.snapshot_reasons)):
            raise ValueError("snapshot_reasons must be ordered snapshot reason codes")
        if not (isinstance(self.assessments, tuple) and all(isinstance(a, ProviderAssessment) for a in self.assessments)):
            raise ValueError("assessments must be a tuple of ProviderAssessment")
        ids = [a.provider_id for a in self.assessments]
        if len(ids) != len(set(ids)):
            raise ValueError("assessments must name each provider once")
        if (self.rationale == REFUSED_INVALID_REQUEST) != bool(self.request_reasons):
            raise ValueError("REFUSED_INVALID_REQUEST exactly when request reasons exist")
        if (self.rationale == REFUSED_INVALID_SNAPSHOT) != bool(self.snapshot_reasons):
            raise ValueError("REFUSED_INVALID_SNAPSHOT exactly when snapshot reasons exist")
        if self.rationale in SELECTED_RATIONALES:
            chosen = [a for a in self.assessments if a.provider_id == self.selected_provider]
            if not (chosen and chosen[0].eligible):
                raise ValueError("a selected provider must be an eligible assessed provider")
            if self.pinned_provider is not None and self.selected_provider != self.pinned_provider:
                raise ValueError("a pinned or locked request can only select its pinned provider")
        elif self.selected_provider is not None:
            raise ValueError("a refused advisory carries no selected provider")

    def rejections(self) -> tuple:
        """(provider_id, reasons) of every excluded provider, sorted by id."""
        return tuple(sorted((a.provider_id, a.reasons) for a in self.assessments if not a.eligible))

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA, "schema_version": SCHEMA_VERSION, "rationale": self.rationale,
            "selected_provider": self.selected_provider,
            "request": {
                "mode": self.mode, "allow_shell": self.allow_shell, "pinned_provider": self.pinned_provider,
                "prior_attempt_executed": self.prior_attempt_executed, "provider_locked": self.provider_locked,
                "preference_order": list(self.preference_order),
                "required_capabilities": list(self.required_capabilities),
            },
            "request_reasons": list(self.request_reasons), "snapshot_reasons": list(self.snapshot_reasons),
            "assessments": [a.to_dict() for a in self.assessments],
            "rejections": [{"provider_id": pid, "reasons": list(reasons)} for pid, reasons in self.rejections()],
            **self._guarantees(),
        }


def canonical_json(advisory: RoutingAdvisory) -> str:
    """Stable, sorted, compact serialization of an advisory's own fields."""
    return json.dumps(advisory.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

def _validate_request(request) -> tuple:
    """Returns (reasons, required_capabilities). Never echoes raw input."""
    if type(request) is not RoutingRequest:
        return (REQUEST_NOT_TYPED,), ()
    reasons = set()
    mode_ok = type(request.mode) is str and request.mode in MODES
    if not mode_ok:
        reasons.add(MODE_UNKNOWN)
    if not _is_bool(request.allow_shell):
        reasons.add(ALLOW_SHELL_NOT_BOOL)
    elif request.allow_shell and mode_ok and request.mode != MODE_WRITE:
        reasons.add(ALLOW_SHELL_REQUIRES_WRITE_MODE)

    explicit = request.required_capabilities
    if not _str_tuple(explicit):
        reasons.add(CAPABILITIES_MALFORMED)
        explicit = ()
    if any(c not in _CAPABILITY_SET for c in explicit):
        reasons.add(CAPABILITY_UNKNOWN)
    if len(explicit) != len(set(explicit)):
        reasons.add(CAPABILITY_DUPLICATE)
    if "SHELL" in explicit and request.allow_shell is not True:
        reasons.add(SHELL_REQUESTED_WITHOUT_ALLOW_SHELL)

    order = request.preference_order
    if not _str_tuple(order):
        reasons.add(PREFERENCE_MALFORMED)
        order = ()
    if len(order) > MAX_PROVIDERS:
        reasons.add(PREFERENCE_TOO_LONG)
    if any(not _valid_provider_id(p) for p in order):
        reasons.add(PREFERENCE_PROVIDER_ID_INVALID)
    if len(order) != len(set(order)):
        reasons.add(PREFERENCE_DUPLICATE)

    pin = request.pinned_provider
    if pin is not None and not _valid_provider_id(pin):
        reasons.add(PIN_INVALID)
    elif pin is not None and order and pin not in order:
        reasons.add(PIN_NOT_IN_PREFERENCE)
    if pin is None and not order and PREFERENCE_MALFORMED not in reasons:
        reasons.add(PREFERENCE_EMPTY)

    if not (_is_bool(request.prior_attempt_executed) and _is_bool(request.provider_locked)):
        reasons.add(LOCK_FLAGS_MALFORMED)
    elif (request.prior_attempt_executed or request.provider_locked) and pin is None:
        reasons.add(LOCKED_WITHOUT_PIN)

    if reasons:
        return _ordered(reasons, REQUEST_REASONS), ()
    required = set(BASE_CAPABILITIES) | set(explicit)
    if request.mode == MODE_WRITE:
        required |= WRITE_MODE_CAPABILITIES
    return (), tuple(sorted(required))


def _facts_well_formed(facts: ProviderFacts) -> bool:
    return (
        _is_bool(facts.probe_available) and _is_bool(facts.policy_allow_shell) and _is_bool(facts.policy_supported)
        and type(facts.policy_mode) is str and facts.policy_mode in MODES
        and _str_tuple(facts.capabilities) and len(facts.capabilities) == len(set(facts.capabilities))
        and type(facts.availability) is str and facts.availability in AVAILABILITY_STATES
        and type(facts.capacity) is str and facts.capacity in CAPACITY_STATES
    )


def _assess_facts(request: RoutingRequest, required: tuple, facts: ProviderFacts) -> tuple:
    """(reasons, missing_capabilities) of one provider's well-typed facts."""
    if not _facts_well_formed(facts):
        return {FACTS_MALFORMED}, ()
    if any(c not in _CAPABILITY_SET for c in facts.capabilities):
        return {FACTS_UNKNOWN_CAPABILITY}, ()
    reasons = set()
    caps = frozenset(facts.capabilities)
    if (facts.policy_mode, facts.policy_allow_shell) != (request.mode, request.allow_shell):
        reasons.add(FACTS_POLICY_MISMATCH)
    # Native contract: a refused policy reports no capabilities; shell is
    # never deliverable without allow_shell; read-only never edits/writes.
    if (not facts.policy_supported and caps) or (not facts.policy_allow_shell and "SHELL" in caps) \
            or (facts.policy_mode == MODE_READ_ONLY and caps & WRITE_MODE_CAPABILITIES):
        reasons.add(FACTS_INCONSISTENT)
    if not facts.probe_available:
        reasons.add(PROBE_UNAVAILABLE)
    if not facts.policy_supported:
        reasons.add(POLICY_REFUSED)
    if facts.provider_id in SHELL_MANDATORY_PROVIDERS and request.allow_shell is not True:
        reasons.add(ADAPTER_REQUIRES_SHELL)
    # As run_preflight: nothing is provided unless available and not refused.
    provided = caps if facts.probe_available and facts.policy_supported else frozenset()
    missing = tuple(sorted(set(required) - provided))
    if missing:
        reasons.add(CAPABILITY_MISSING)
    if facts.availability in _AVAILABILITY_REASON:
        reasons.add(_AVAILABILITY_REASON[facts.availability])
    if facts.capacity in _CAPACITY_REASON:
        reasons.add(_CAPACITY_REASON[facts.capacity])
    return reasons, missing


def _refused(rationale: str, request_reasons: tuple = (), snapshot_reasons: tuple = (), **echo) -> RoutingAdvisory:
    fields = {
        "mode": None, "allow_shell": None, "pinned_provider": None, "prior_attempt_executed": None,
        "provider_locked": None, "preference_order": (), "required_capabilities": (),
    }
    fields.update(echo)
    return RoutingAdvisory(
        rationale=rationale, selected_provider=None, request_reasons=request_reasons,
        snapshot_reasons=snapshot_reasons, assessments=(), **fields,
    )


def propose_route(request: RoutingRequest, provider_facts: tuple) -> RoutingAdvisory:
    """Pure, deterministic routing proposal. Never raises on bad input: every
    malformed request or snapshot is an explained refusal. The result never
    authorizes dispatch, retry, resume, merge or a provider switch."""
    request_reasons, required = _validate_request(request)
    if request_reasons:
        return _refused(REFUSED_INVALID_REQUEST, request_reasons=request_reasons)

    echo = {
        "mode": request.mode, "allow_shell": request.allow_shell, "pinned_provider": request.pinned_provider,
        "prior_attempt_executed": request.prior_attempt_executed, "provider_locked": request.provider_locked,
        "preference_order": request.preference_order, "required_capabilities": required,
    }
    snapshot_reasons = set()
    if type(provider_facts) is not tuple:
        snapshot_reasons.add(SNAPSHOT_NOT_TUPLE)
    else:
        if len(provider_facts) > MAX_PROVIDERS:
            snapshot_reasons.add(SNAPSHOT_TOO_LARGE)
        for entry in provider_facts:
            if type(entry) is not ProviderFacts:
                snapshot_reasons.add(SNAPSHOT_ENTRY_NOT_TYPED)
            elif not _valid_provider_id(entry.provider_id):
                snapshot_reasons.add(SNAPSHOT_PROVIDER_ID_INVALID)
    if snapshot_reasons:
        return _refused(REFUSED_INVALID_SNAPSHOT, snapshot_reasons=_ordered(snapshot_reasons, SNAPSHOT_REASONS), **echo)

    by_id: dict = {}
    for entry in provider_facts:
        by_id.setdefault(entry.provider_id, []).append(entry)

    pin = request.pinned_provider
    locked = request.prior_attempt_executed or request.provider_locked
    order = request.preference_order or (pin,)
    rank = {pid: i for i, pid in enumerate(request.preference_order)}
    candidates = tuple(order) + tuple(sorted(set(by_id) - set(order)))

    assessments = []
    for pid in candidates:
        entries = by_id.get(pid, [])
        missing: tuple = ()
        if not entries:
            reasons = {NO_FACTS}
        elif len(entries) > 1:
            reasons = {DUPLICATE_FACTS}
        else:
            reasons, missing = _assess_facts(request, required, entries[0])
        if pid not in order:
            reasons.add(NOT_IN_PREFERENCE_ORDER)
        if pin is not None and pid != pin:
            reasons.add(PROVIDER_LOCKED_TO_OTHER if locked else NOT_PINNED)
        assessments.append(ProviderAssessment(
            provider_id=pid, preference_rank=rank.get(pid), eligible=not reasons,
            reasons=_ordered(reasons, PROVIDER_REASONS), missing_capabilities=missing,
        ))

    # Caller order is the sole key; ids are unique so the documented
    # lexicographic tie-break can never be reached.
    eligible = sorted((a for a in assessments if a.eligible),
                      key=lambda a: (order.index(a.provider_id), a.provider_id))
    if eligible:
        selected = eligible[0].provider_id
        if locked:
            rationale = SELECTED_LOCKED_PROVIDER
        elif pin is not None:
            rationale = SELECTED_PINNED_PROVIDER
        else:
            rationale = SELECTED_FIRST_ELIGIBLE_PREFERENCE
    else:
        selected = None
        if locked:
            rationale = REFUSED_LOCKED_PROVIDER_INELIGIBLE
        elif pin is not None:
            rationale = REFUSED_PINNED_PROVIDER_INELIGIBLE
        else:
            rationale = REFUSED_NO_ELIGIBLE_PROVIDER
    return RoutingAdvisory(
        rationale=rationale, selected_provider=selected, request_reasons=(), snapshot_reasons=(),
        assessments=tuple(assessments), **echo,
    )
