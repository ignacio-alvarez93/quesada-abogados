"""FCP-7B-01: Provider Routing Gateway - read-only pre-dispatch adapter that
turns observed adapter facts plus an explicit Direction preference into an
FCP-7A `RoutingAdvisory` for a new, not-yet-executed Work Order.

It never dispatches. Selection logic lives ONLY in
`fabric_provider_routing_policy.propose_route`; this module builds the exact
`RoutingRequest` and `ProviderFacts` snapshot that policy consumes and
returns its advisory unchanged, wrapped with the evidence of how every fact
was obtained.

Authority boundary
------------------
* The Runner (`runner_providers` preflight, `runner_pipeline` provider lock,
  quota/auth holds, `provider_limits`, worktree lease, execution,
  checkpoints, evidence) stays the ONLY authority at execution time and
  re-validates everything. Nothing here starts a work provider, builds or
  executes an invocation, creates a worktree, runs Git, writes files,
  schedules, retries or switches providers. `fabric_director` and
  `runner_pipeline` are not imported.
* Adapter facts come from the existing Provider Registry: `probe()` (a
  read-only version probe of the installed CLI - an OBSERVATION, never a
  credential or an authorization), `policy_refusal(policy)` and
  `capabilities(policy)` under the EXACT `ExecutionPolicy(mode,
  allow_shell)` requested. Nothing is relaxed: Codex without
  `allow_shell=True` is refused by its own adapter and stays refused.
* Availability (quota/auth) and concurrent capacity are NOT knowable from an
  adapter. They enter only as explicit `ProviderObservation`s carrying a
  closed-vocabulary provenance (`OBSERVATION_SOURCES`), none of which is a
  Runner certification. A missing, duplicate or malformed observation is
  recorded and degrades to `UNKNOWN`, which the policy excludes - it is
  never guessed as `NONE`/`AVAILABLE`.
* An adapter that cannot be resolved, whose identity does not match, or
  whose probe/policy/capability answer raises or is malformed contributes NO
  facts (the policy then reports `NO_FACTS`). Exception text, executable
  paths, versions and probe reasons are never echoed.

Pin / lock resolution
---------------------
`WorkOrderRoutingIntent.owner_provider` names the provider that owns a prior
execution (only meaningful with `prior_attempt_executed` or
`provider_locked`); `DirectionRoutingConfig.pinned_provider` is Direction's
hard pin. Both given and different -> `PIN_OWNER_CONFLICT` (never a silent
substitute). Owner without a lock flag -> `OWNER_WITHOUT_LOCK`. Otherwise
the effective pin is whichever was given; a lock without any pin is refused
by the policy itself (`LOCKED_WITHOUT_PIN`).

Output (`GatewayResult`, schema `fcp7b01-provider-router-gateway-v1`).
Every result fixes `certified`, `authorizes_action`, `execution_allowed`,
`auto_retry_allowed`, `resume_allowed`, `merging_allowed` and
`provider_switch_authorized` to False as read-only properties.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Optional

try:
    from scripts.ai import fabric_provider_routing_policy as policy
    from scripts.ai import runner_providers as providers
except ImportError:  # pragma: no cover - direct script execution
    import fabric_provider_routing_policy as policy  # type: ignore[no-redef]
    import runner_providers as providers  # type: ignore[no-redef]

SCHEMA = "fcp7b01-provider-router-gateway-v1"
SCHEMA_VERSION = 1
GATEWAY_MARKER = "FCP7B01_GATEWAY_PROPOSAL_ONLY_NOT_CERTIFIED_NOT_AUTHORIZED"

# Closed provenance vocabulary for availability/capacity observations. None
# of these is a Runner certification; each is an input the caller vouches for.
SOURCE_DIRECTION_DECLARED = "DIRECTION_DECLARED"
SOURCE_RUNNER_STATE_OBSERVED = "RUNNER_STATE_OBSERVED"
OBSERVATION_SOURCES = (SOURCE_DIRECTION_DECLARED, SOURCE_RUNNER_STATE_OBSERVED)
UNKNOWN_AVAILABILITY = "UNKNOWN"
UNKNOWN_CAPACITY = "UNKNOWN"

# Gateway-level refusal codes (no advisory is produced).
INTENT_NOT_TYPED = "INTENT_NOT_TYPED"
CONFIG_NOT_TYPED = "CONFIG_NOT_TYPED"
OWNER_WITHOUT_LOCK = "OWNER_WITHOUT_LOCK"
PIN_OWNER_CONFLICT = "PIN_OWNER_CONFLICT"
OBSERVATIONS_NOT_TUPLE = "OBSERVATIONS_NOT_TUPLE"
OBSERVATIONS_TOO_LARGE = "OBSERVATIONS_TOO_LARGE"
OBSERVATION_NOT_TYPED = "OBSERVATION_NOT_TYPED"
OBSERVATION_PROVIDER_ID_INVALID = "OBSERVATION_PROVIDER_ID_INVALID"
GATEWAY_REASONS = (
    INTENT_NOT_TYPED, CONFIG_NOT_TYPED, OWNER_WITHOUT_LOCK, PIN_OWNER_CONFLICT, OBSERVATIONS_NOT_TUPLE,
    OBSERVATIONS_TOO_LARGE, OBSERVATION_NOT_TYPED, OBSERVATION_PROVIDER_ID_INVALID,
)

# Per-provider evidence issue codes (recorded; the policy decides exclusion).
ADAPTER_UNREGISTERED = "ADAPTER_UNREGISTERED"
ADAPTER_RESOLUTION_FAILED = "ADAPTER_RESOLUTION_FAILED"
ADAPTER_IDENTITY_MISMATCH = "ADAPTER_IDENTITY_MISMATCH"
PROBE_FAILED = "PROBE_FAILED"
PROBE_MALFORMED = "PROBE_MALFORMED"
ADAPTER_POLICY_FAILED = "ADAPTER_POLICY_FAILED"
ADAPTER_CAPABILITIES_MALFORMED = "ADAPTER_CAPABILITIES_MALFORMED"
OBSERVATION_MISSING = "OBSERVATION_MISSING"
OBSERVATION_DUPLICATE = "OBSERVATION_DUPLICATE"
OBSERVATION_MALFORMED = "OBSERVATION_MALFORMED"
OBSERVATION_UNUSED = "OBSERVATION_UNUSED"
ISSUE_CODES = (
    ADAPTER_UNREGISTERED, ADAPTER_RESOLUTION_FAILED, ADAPTER_IDENTITY_MISMATCH, PROBE_FAILED, PROBE_MALFORMED,
    ADAPTER_POLICY_FAILED, ADAPTER_CAPABILITIES_MALFORMED, OBSERVATION_MISSING, OBSERVATION_DUPLICATE,
    OBSERVATION_MALFORMED, OBSERVATION_UNUSED,
)

GATEWAY_REFUSED = "GATEWAY_REFUSED"


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WorkOrderRoutingIntent:
    """What the not-yet-dispatched Work Order needs, stated explicitly.
    Validated by the FCP-7A policy (fail closed), not here."""
    mode: str
    allow_shell: bool = False
    required_capabilities: tuple = ()
    prior_attempt_executed: bool = False
    provider_locked: bool = False
    owner_provider: Optional[str] = None


@dataclass(frozen=True)
class DirectionRoutingConfig:
    """Direction's explicit preference: the ONLY ranking (no cost, latency,
    quality or score input exists)."""
    preference_order: tuple = ()
    pinned_provider: Optional[str] = None


@dataclass(frozen=True)
class ProviderObservation:
    """Caller-supplied availability/capacity observation of one provider,
    with provenance. Never a Runner certification; only ever excludes."""
    provider_id: str
    availability: str
    capacity: str
    source: str


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GatewayResult:
    """Wrapped FCP-7A advisory plus the evidence it was computed from.
    `advisory` is None exactly when the gateway itself refused."""
    gateway_reasons: tuple
    routing_request: Optional[policy.RoutingRequest]
    facts: tuple
    provenance: tuple
    issues: tuple
    advisory: Optional[policy.RoutingAdvisory]

    def __post_init__(self):
        if not (isinstance(self.gateway_reasons, tuple) and all(r in GATEWAY_REASONS for r in self.gateway_reasons)
                and self.gateway_reasons == policy._ordered(self.gateway_reasons, GATEWAY_REASONS)):
            raise ValueError("gateway_reasons must be ordered gateway reason codes")
        if bool(self.gateway_reasons) != (self.advisory is None):
            raise ValueError("a gateway result carries an advisory exactly when the gateway did not refuse")
        if self.advisory is not None and type(self.advisory) is not policy.RoutingAdvisory:
            raise ValueError("advisory must be an FCP-7A RoutingAdvisory")
        if not (isinstance(self.facts, tuple) and all(type(f) is policy.ProviderFacts for f in self.facts)):
            raise ValueError("facts must be a tuple of ProviderFacts")
        if not (isinstance(self.issues, tuple) and all(code in ISSUE_CODES for _, code in self.issues)):
            raise ValueError("issues must be (provider_id, issue code) pairs")
        if not (isinstance(self.provenance, tuple)
                and all(src is None or src in OBSERVATION_SOURCES for _, src in self.provenance)):
            raise ValueError("provenance must be (provider_id, source|None) pairs")

    @property
    def rationale(self) -> str:
        return GATEWAY_REFUSED if self.advisory is None else self.advisory.rationale

    @property
    def selected_provider(self) -> Optional[str]:
        """Informational only; never an instruction to dispatch."""
        return None if self.advisory is None else self.advisory.selected_provider

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

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA, "schema_version": SCHEMA_VERSION, "rationale": self.rationale,
            "selected_provider": self.selected_provider, "gateway_reasons": list(self.gateway_reasons),
            "facts": [_facts_dict(f) for f in self.facts],
            "provenance": [{"provider_id": pid, "source": src} for pid, src in self.provenance],
            "issues": [{"provider_id": pid, "code": code} for pid, code in self.issues],
            "advisory": None if self.advisory is None else self.advisory.to_dict(),
            "marker": GATEWAY_MARKER, "certified": False, "authorizes_action": False, "execution_allowed": False,
            "auto_retry_allowed": False, "resume_allowed": False, "merging_allowed": False,
            "provider_switch_authorized": False,
        }


def _facts_dict(facts: policy.ProviderFacts) -> dict:
    return {
        "provider_id": facts.provider_id, "probe_available": facts.probe_available,
        "policy_mode": facts.policy_mode, "policy_allow_shell": facts.policy_allow_shell,
        "policy_supported": facts.policy_supported, "capabilities": list(facts.capabilities),
        "availability": facts.availability, "capacity": facts.capacity,
    }


def canonical_json(result: GatewayResult) -> str:
    """Stable, sorted, compact serialization of a gateway result."""
    return json.dumps(result.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


# ---------------------------------------------------------------------------
# Gateway
# ---------------------------------------------------------------------------

def _refused(reasons: set) -> GatewayResult:
    return GatewayResult(
        gateway_reasons=policy._ordered(reasons, GATEWAY_REASONS), routing_request=None, facts=(), provenance=(),
        issues=(), advisory=None,
    )


def _resolve_pin(intent: WorkOrderRoutingIntent, config: DirectionRoutingConfig) -> tuple:
    """(reasons, effective_pin). Never substitutes an execution owner."""
    owner, pin = intent.owner_provider, config.pinned_provider
    locked = intent.prior_attempt_executed is True or intent.provider_locked is True
    reasons = set()
    if owner is not None and not locked:
        reasons.add(OWNER_WITHOUT_LOCK)
    if owner is not None and pin is not None and owner != pin:
        reasons.add(PIN_OWNER_CONFLICT)
    return reasons, (pin if pin is not None else owner)


def _index_observations(observations) -> tuple:
    """(gateway_reasons, {provider_id: [ProviderObservation, ...]})."""
    if type(observations) is not tuple:
        return {OBSERVATIONS_NOT_TUPLE}, {}
    reasons = set()
    if len(observations) > policy.MAX_PROVIDERS:
        reasons.add(OBSERVATIONS_TOO_LARGE)
    by_id: dict = {}
    for entry in observations:
        if type(entry) is not ProviderObservation:
            reasons.add(OBSERVATION_NOT_TYPED)
        elif not policy._valid_provider_id(entry.provider_id):
            reasons.add(OBSERVATION_PROVIDER_ID_INVALID)
        else:
            by_id.setdefault(entry.provider_id, []).append(entry)
    return reasons, by_id


def _observation_for(pid: str, by_id: dict, issues: list) -> tuple:
    """(availability, capacity, source). Anything unreliable -> UNKNOWN."""
    entries = by_id.get(pid, [])
    if not entries:
        issues.append((pid, OBSERVATION_MISSING))
        return UNKNOWN_AVAILABILITY, UNKNOWN_CAPACITY, None
    if len(entries) > 1:
        issues.append((pid, OBSERVATION_DUPLICATE))
        return UNKNOWN_AVAILABILITY, UNKNOWN_CAPACITY, None
    obs = entries[0]
    if not (type(obs.availability) is str and obs.availability in policy.AVAILABILITY_STATES
            and type(obs.capacity) is str and obs.capacity in policy.CAPACITY_STATES
            and type(obs.source) is str and obs.source in OBSERVATION_SOURCES):
        issues.append((pid, OBSERVATION_MALFORMED))
        return UNKNOWN_AVAILABILITY, UNKNOWN_CAPACITY, None
    return obs.availability, obs.capacity, obs.source


def _adapter_facts(pid: str, resolve: Callable, exec_policy, issues: list) -> Optional[tuple]:
    """(probe_available, policy_supported, capability names) observed through
    the registered adapter, or None when the adapter's answers cannot be
    trusted. Never builds or executes an invocation."""
    try:
        adapter = resolve(pid)
    except providers.UnknownProviderError:
        issues.append((pid, ADAPTER_UNREGISTERED))
        return None
    except Exception:  # adapter factories are third-party code
        issues.append((pid, ADAPTER_RESOLUTION_FAILED))
        return None
    if not isinstance(adapter, providers.Provider) or adapter.provider_id != pid:
        issues.append((pid, ADAPTER_IDENTITY_MISMATCH))
        return None
    try:
        probe = adapter.probe()
    except Exception:
        issues.append((pid, PROBE_FAILED))
        return None
    if type(probe) is not providers.ProviderProbe or probe.provider_id != pid or type(probe.available) is not bool:
        issues.append((pid, PROBE_MALFORMED))
        return None
    try:
        refusal = adapter.policy_refusal(exec_policy)
        caps = adapter.capabilities(exec_policy)
    except Exception:
        issues.append((pid, ADAPTER_POLICY_FAILED))
        return None
    if refusal is not None and type(refusal) is not str:
        issues.append((pid, ADAPTER_POLICY_FAILED))
        return None
    if not isinstance(caps, (frozenset, set)) or not all(isinstance(c, providers.Capability) for c in caps):
        issues.append((pid, ADAPTER_CAPABILITIES_MALFORMED))
        return None
    # Reported as-is: an adapter that refuses yet claims capabilities is left
    # for the policy to flag FACTS_INCONSISTENT, never "fixed" here.
    return probe.available, refusal is None, tuple(sorted(c.value for c in caps))


def route_work_order(
    intent: WorkOrderRoutingIntent,
    config: DirectionRoutingConfig,
    observations: tuple = (),
    *,
    registry: Optional[providers.ProviderRegistry] = None,
) -> GatewayResult:
    """Read-only routing proposal for one not-yet-executed Work Order.

    Never raises on bad input and never dispatches: the result is the FCP-7A
    advisory for exactly the request and snapshot reported alongside it."""
    reasons = set()
    if type(intent) is not WorkOrderRoutingIntent:
        reasons.add(INTENT_NOT_TYPED)
    if type(config) is not DirectionRoutingConfig:
        reasons.add(CONFIG_NOT_TYPED)
    if reasons:
        return _refused(reasons)
    pin_reasons, pin = _resolve_pin(intent, config)
    obs_reasons, by_id = _index_observations(observations)
    reasons = pin_reasons | obs_reasons
    if reasons:
        return _refused(reasons)

    request = policy.RoutingRequest(
        mode=intent.mode, allow_shell=intent.allow_shell, required_capabilities=intent.required_capabilities,
        preference_order=config.preference_order, pinned_provider=pin,
        prior_attempt_executed=intent.prior_attempt_executed, provider_locked=intent.provider_locked,
    )
    # Request validation is the policy's own: an invalid request is refused
    # before any adapter is touched.
    precheck = policy.propose_route(request, ())
    if precheck.rationale == policy.REFUSED_INVALID_REQUEST:
        return GatewayResult(
            gateway_reasons=(), routing_request=request, facts=(), provenance=(), issues=(), advisory=precheck,
        )

    # Only providers the request could select are observed: the pin alone
    # when pinned, else Direction's order.
    candidates = (pin,) if pin is not None else tuple(config.preference_order)
    resolve = registry.create if registry is not None else providers.resolve_provider
    exec_policy = providers.ExecutionPolicy(mode=intent.mode, allow_shell=intent.allow_shell)
    issues: list = []
    facts, provenance = [], []
    for pid in candidates:
        observed = _adapter_facts(pid, resolve, exec_policy, issues)
        if observed is None:
            continue
        probe_available, supported, caps = observed
        availability, capacity, source = _observation_for(pid, by_id, issues)
        provenance.append((pid, source))
        facts.append(policy.ProviderFacts(
            provider_id=pid, probe_available=probe_available, policy_mode=intent.mode,
            policy_allow_shell=intent.allow_shell, policy_supported=supported, capabilities=caps,
            availability=availability, capacity=capacity,
        ))
    for pid in sorted(set(by_id) - set(candidates)):
        issues.append((pid, OBSERVATION_UNUSED))

    snapshot = tuple(facts)
    return GatewayResult(
        gateway_reasons=(), routing_request=request, facts=snapshot, provenance=tuple(provenance),
        issues=tuple(sorted(set(issues), key=lambda i: (i[0], ISSUE_CODES.index(i[1])))),
        advisory=policy.propose_route(request, snapshot),
    )
